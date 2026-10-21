"""Mira's living register: the snapshot she reads and the operations she writes."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select, or_, and_, func, update
from app.config import settings
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting
from app.models.enums import UserRole
from app.models.mira_memory import MiraMemoryItem as Item, MiraMemoryEvent as Event
from app.models.user import User

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
    # Mira's own changes in this meeting raise the version she expects; a meeting counts once per item.
    expected, seen = dict(versions), set()
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
        if item.id not in seen:
            seen.add(item.id)
            item.mention_count += 1
        item.last_mentioned_at = max(filter(None, (item.last_mentioned_at, when)))
        item.people = list(dict.fromkeys([*(item.people or []), *people]))
        if action != 'mention' and (item.version != expected[item_id] or item.status == 'WRONG'):
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
            expected[item_id] = item.version
        event(item, {'mention': 'MENTION', 'change': 'CHANGE', 'close': 'CLOSE'}[action], said, segments)
        stats['applied'] += 1
    await db.flush()
    return stats


# The page: everyone who is signed in reads and corrects the same register.

STALE = 'Pika është ndryshuar ndërkohë. U rifreskua.'
EVENT_KINDS = {'close': ('CLOSED', 'CLOSE'), 'reopen': ('OPEN', 'REOPEN'), 'wrong': ('WRONG', 'WRONG')}


def summary(row, quiet_before):
    return {'id': str(row.id), 'title': row.title, 'kind': row.kind, 'status': row.status,
        'quiet': row.status == 'OPEN' and row.last_mentioned_at is not None and row.last_mentioned_at < quiet_before,
        'mention_count': row.mention_count,
        'last_mentioned_at': row.last_mentioned_at.isoformat() if row.last_mentioned_at else None}


async def list_items(db, status: str) -> dict:
    quiet_before = now() - timedelta(days=settings.MIRA_MEMORY_QUIET_DAYS)
    groups = {'open': ['OPEN'], 'closed': ['CLOSED', 'WRONG'], 'all': ['OPEN', 'CLOSED', 'WRONG']}
    rows = (await db.execute(ordered(select(Item).where(Item.status.in_(groups[status]))))).scalars()
    counts = dict((await db.execute(select(Item.status, func.count()).group_by(Item.status))).all())
    failed = await db.scalar(select(func.count()).select_from(Meeting).where(Meeting.memory_status == 'FAILED'))
    return {'items': [summary(row, quiet_before) for row in rows],
        'counts': {'open': counts.get('OPEN', 0), 'closed': counts.get('CLOSED', 0) + counts.get('WRONG', 0)},
        'failed_meetings': failed}


async def get_item(db, item_id) -> dict:
    row = await db.get(Item, item_id, populate_existing=True)
    if row is None:
        raise HTTPException(404, 'Pika nuk u gjet.')
    events = await db.execute(select(Event, Meeting.title, User.full_name, User.username)
        .outerjoin(Meeting, Meeting.id == Event.meeting_id).outerjoin(User, User.id == Event.user_id)
        .where(Event.item_id == row.id).order_by(Event.created_at.desc()))
    return {**summary(row, now() - timedelta(days=settings.MIRA_MEMORY_QUIET_DAYS)),
        'description': row.description, 'people': list(row.people or []), 'version': row.version,
        'human_edited': row.human_edited,
        'events': [{'kind': event.kind, 'text': event.text, 'created_at': event.created_at.isoformat(),
            'meeting_title': title, 'user_name': full_name or username, 'partial': event.partial}
            for event, title, full_name, username in events]}


async def locked_item(db, item_id, version):
    row = (await db.execute(select(Item).where(Item.id == item_id).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, 'Pika nuk u gjet.')
    if row.version != version:
        raise HTTPException(409, STALE)
    return row


def touched(db, row, user, kind, text):
    row.version += 1
    row.human_edited, row.updated_by_user_id = True, user.id
    db.add(Event(id=uuid.uuid4(), item_id=row.id, kind=kind, text=text, user_id=user.id, created_at=now()))


async def edit_item(db, user, item_id, payload) -> dict:
    row = await locked_item(db, item_id, payload.version)
    row.title, row.description = payload.title.strip(), payload.description.strip()
    touched(db, row, user, 'EDIT', row.description)
    await db.commit()
    return await get_item(db, item_id)


async def set_status(db, user, item_id, payload) -> dict:
    row = await locked_item(db, item_id, payload.version)
    row.status, kind = EVENT_KINDS[payload.action]
    touched(db, row, user, kind, '')
    await db.commit()
    return await get_item(db, item_id)


async def retry_failed(db, user) -> dict:
    if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(403, 'Vetëm adminët dhe menaxherët mund ta provojnë sërish.')
    result = await db.execute(update(Meeting).where(Meeting.memory_status == 'FAILED')
        .values(memory_status='PENDING', memory_attempts=0, memory_error=None))
    await db.commit()
    return {'retried': result.rowcount}
