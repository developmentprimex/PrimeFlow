"""Mira's living register: the snapshot she reads and the operations she writes."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select, or_, and_
from app.config import settings
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting
from app.models.mira_memory import MiraMemoryItem as Item, MiraMemoryEvent as Event

KINDS = ('TASK', 'TOPIC', 'DECISION', 'INFO')
ACTIONS = ('add', 'mention', 'change', 'close')
HISTORY = ('MENTION', 'CHANGE', 'CLOSE')


def now():
    return datetime.now(timezone.utc)


def local_label(moment):
    return moment.astimezone(ZoneInfo(settings.APP_TIMEZONE)).strftime('%d.%m %H:%M')


def ordered(query):
    return query.order_by(Item.last_mentioned_at.desc().nulls_last(), Item.mention_count.desc(), Item.created_at)


async def snapshot(db) -> dict:
    """Open items and recently closed ones, newest first, bounded for the model's context."""
    moment = now()
    recent = moment - timedelta(days=settings.MIRA_MEMORY_RECENT_CLOSED_DAYS)
    quiet_before = moment - timedelta(days=settings.MIRA_MEMORY_QUIET_DAYS)
    rows = list((await db.execute(ordered(select(Item).where(or_(Item.status == 'OPEN',
        and_(Item.status == 'CLOSED', Item.updated_at >= recent)))))).scalars())
    mentions = {row.id: [] for row in rows}
    if rows:
        events = await db.execute(select(Event, Meeting.title).outerjoin(Meeting, Meeting.id == Event.meeting_id)
            .where(Event.item_id.in_(list(mentions)), Event.kind.in_(HISTORY))
            .order_by(Event.created_at.desc()))
        for event, title in events:
            if len(mentions[event.item_id]) < 3:
                mentions[event.item_id].append({'date': local_label(event.created_at), 'meeting': title or '',
                    'text': event.text})
    items = [{'id': str(row.id), 'title': row.title, 'description': row.description, 'kind': row.kind,
        'status': row.status, 'people': list(row.people or []), 'human_edited': row.human_edited,
        'quiet': row.status == 'OPEN' and row.last_mentioned_at is not None and row.last_mentioned_at < quiet_before,
        'version': row.version, 'mentions': mentions[row.id]} for row in rows]
    wrong = list((await db.execute(select(Item.title).where(Item.status == 'WRONG').order_by(Item.created_at))).scalars())
    result = {'items': items, 'wrong_titles': wrong, 'omitted': 0}
    while items and len(json.dumps(result, ensure_ascii=False)) > settings.MIRA_MEMORY_CONTEXT_CHARS:
        items.pop()
        result['omitted'] += 1
    return result


def text_field(value, limit):
    return value.strip() if isinstance(value, str) and value.strip() and len(value.strip()) <= limit else None


async def apply_operations(db, meeting, operations: list[dict], versions: dict[str, int]) -> dict:
    """Apply Mira's operations for one meeting. The caller owns the transaction."""
    stats = {'applied': 0, 'rejected': 0, 'dropped': 0}
    when = meeting.started_at or meeting.created_at or now()
    wrong = {title.strip().lower() for title in (await db.execute(select(Item.title).where(Item.status == 'WRONG'))).scalars()}

    def event(item, kind, text, segments):
        db.add(Event(id=uuid.uuid4(), item_id=item.id, kind=kind, text=text, meeting_id=meeting.id,
            partial=bool(meeting.partial), refs=segments, created_at=when))

    for operation in operations:
        action = operation.get('action')
        said = text_field(operation.get('said'), 4000)
        people = [p.strip() for p in operation.get('people') or [] if isinstance(p, str) and p.strip()][:20]
        segments = [s for s in operation.get('segments') or [] if isinstance(s, int)][:50]
        if action not in ACTIONS or not said:
            stats['rejected'] += 1
            continue
        if action == 'add':
            title = text_field(operation.get('title'), 200)
            description = text_field(operation.get('description'), 4000)
            if not title or not description or operation.get('kind') not in KINDS or title.lower() in wrong:
                stats['rejected'] += 1
                continue
            item = Item(id=uuid.uuid4(), title=title, description=description, kind=operation['kind'], status='OPEN',
                people=people, version=1, mention_count=1, last_mentioned_at=when, human_edited=False)
            db.add(item)
            await db.flush()
            event(item, 'MENTION', said, segments)
            stats['applied'] += 1
            continue
        item_id = operation.get('item_id')
        item = None
        if item_id in versions:
            item = (await db.execute(select(Item).where(Item.id == uuid.UUID(item_id)).with_for_update())).scalar_one_or_none()
        description = text_field(operation.get('description'), 4000)
        if item is None or (action == 'change' and not description):
            stats['rejected'] += 1
            continue
        item.mention_count += 1
        item.last_mentioned_at = max(filter(None, (item.last_mentioned_at, when)))
        item.people = list(dict.fromkeys([*(item.people or []), *people]))
        if action != 'mention' and (item.version != versions[item_id] or item.status == 'WRONG'):
            # A person changed it while Mira was reading: keep what was said, not her change.
            event(item, 'MENTION', said, segments)
            stats['dropped'] += 1
            continue
        if action == 'change':
            item.description, item.status = description, 'OPEN'
        elif action == 'close':
            item.status = 'CLOSED'
        if action != 'mention':
            item.version += 1
            item.updated_by_user_id = None
        event(item, {'mention': 'MENTION', 'change': 'CHANGE', 'close': 'CLOSE'}[action], said, segments)
        stats['applied'] += 1
    await db.flush()
    return stats
