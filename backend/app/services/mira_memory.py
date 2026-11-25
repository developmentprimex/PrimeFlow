"""Mira's living register: the snapshot she reads and the operations she writes."""
from __future__ import annotations

import json
import re
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from sqlalchemy import select, or_, and_, func, update
from app.config import settings
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting, DiscordVoiceSegment as Segment
from app.models.enums import UserRole
from app.models.mira_memory import MiraMemoryItem as Item, MiraMemoryEvent as Event
from app.models.project import Project
from app.models.user import User

KINDS = ('TASK', 'TOPIC', 'DECISION', 'INFO', 'ACTION', 'INSTRUCTION', 'OPEN_QUESTION',
    'BLOCKER', 'FOLLOW_UP', 'IMPORTANT_INFO')
FOLLOW_UP_KINDS = ('TASK', 'TOPIC', 'ACTION', 'INSTRUCTION', 'OPEN_QUESTION', 'BLOCKER', 'FOLLOW_UP')
RECORD_STATUSES = ('READY', 'SAVED', 'FAILED')
ACTIONS = ('add', 'mention', 'change', 'close')
HISTORY = ('MENTION', 'CHANGE', 'CLOSE')


def now():
    return datetime.now(timezone.utc)


def local_label(moment):
    return moment.astimezone(ZoneInfo(settings.APP_TIMEZONE)).strftime('%d.%m %H:%M')


def ordered(query):
    return query.order_by(Item.last_mentioned_at.desc().nulls_last(), Item.mention_count.desc(), Item.created_at)


async def snapshot(db, *, include_evidence=False) -> dict:
    """Open items and recently closed ones, newest first, bounded for the model's context."""
    moment = now()
    recent = moment - timedelta(days=settings.MIRA_MEMORY_RECENT_CLOSED_DAYS)
    quiet_before = moment - timedelta(days=settings.MIRA_MEMORY_QUIET_DAYS)
    items_query = select(Item).where(or_(Item.status == 'OPEN', and_(Item.status == 'CLOSED', Item.updated_at >= recent)))
    wrong_query = select(Item.title).where(Item.status == 'WRONG')
    has_evidence = func.jsonb_typeof(Event.details) == 'object'
    if not include_evidence:
        # The existing Host and full-notes consumers keep their historical context.
        mentions_for_item = select(Event.id).where(Event.item_id == Item.id, Event.kind == 'MENTION')
        legacy = or_(~mentions_for_item.where(has_evidence).exists(),
            mentions_for_item.where(has_evidence.is_not(True)).exists())
        items_query = items_query.where(legacy)
        wrong_query = wrong_query.where(legacy)
    rows = list((await db.execute(ordered(items_query))).scalars())
    mentions = {row.id: [] for row in rows}
    clarifications = {}
    if rows:
        events_query = select(Event, Meeting.title).outerjoin(Meeting, Meeting.id == Event.meeting_id).where(
            Event.item_id.in_(list(mentions)), Event.kind.in_(HISTORY))
        if not include_evidence:
            events_query = events_query.where(has_evidence.is_not(True))
        events = await db.execute(events_query.order_by(Event.created_at.desc()))
        for event, title in events:
            if len(mentions[event.item_id]) < 3:
                mentions[event.item_id].append({'date': local_label(event.created_at), 'meeting': title or '',
                    'text': event.text, 'project': (event.details or {}).get('project')})
        if include_evidence:
            answers = (await db.scalars(select(Event).join(Meeting, Meeting.id == Event.meeting_id)
                .where(Event.item_id.in_(list(mentions)), Event.kind == 'ANSWER',
                    Meeting.status.in_(RECORD_STATUSES)).order_by(Event.created_at.desc(), Event.id))).all()
            for event in answers:
                item_answers = clarifications.setdefault(event.item_id, {})
                if len(item_answers) < 3:
                    item_answers.setdefault(event.details['question'], event.text)
    items = [{'id': str(row.id), 'title': row.title, 'description': row.description, 'kind': row.kind,
        'status': row.status, 'people': list(row.people or []), 'human_edited': row.human_edited,
        'quiet': row.status == 'OPEN' and row.last_mentioned_at is not None and row.last_mentioned_at < quiet_before,
        'version': row.version, 'mentions': mentions[row.id]} for row in rows]
    for row, item in zip(rows, items):
        if row.id in clarifications:
            item['clarifications'] = clarifications[row.id]
    wrong = list((await db.execute(wrong_query.order_by(Item.created_at))).scalars())
    result = {'items': items, 'wrong_titles': wrong, 'omitted': 0}
    while items and len(json.dumps(result, ensure_ascii=False)) > settings.MIRA_MEMORY_CONTEXT_CHARS:
        items.pop()
        result['omitted'] += 1
    return result


def text_field(value, limit):
    return value.strip() if isinstance(value, str) and value.strip() and len(value.strip()) <= limit else None


def normalized(value):
    plain = unicodedata.normalize('NFKD', value.casefold())
    return ' '.join(re.findall(r'[^\W_]+', ''.join(c for c in plain if not unicodedata.combining(c))))


def match_group(kind):
    if kind in ('INFO', 'IMPORTANT_INFO'):
        return 'INFO'
    return 'DECISION' if kind == 'DECISION' else 'ISSUE'


def resolve_deadline(phrase, when):
    if not phrase:
        return None
    relative_days = {'sot': 0, 'neser': 1, 'pasneser': 2}
    relative = {relative_days[word] for word in normalized(phrase).split() if word in relative_days}
    dates = set()
    for match in re.finditer(r'\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}[./]\d{4})\b', phrase):
        parts = re.split(r'[-./]', match.group())
        year, month, day = map(int, parts if len(parts[0]) == 4 else reversed(parts))
        try:
            dates.add(date(year, month, day).isoformat())
        except ValueError:
            continue
    local_date = when.astimezone(ZoneInfo(settings.APP_TIMEZONE)).date()
    dates.update((local_date + timedelta(days=offset)).isoformat() for offset in relative)
    return dates.pop() if len(dates) == 1 else None


def cited_segments(operation, source_segments):
    raw = operation.get('segments')
    refs = list(dict.fromkeys(s for s in raw if type(s) is int))[:50] if isinstance(raw, list) else []
    return refs if source_segments is None else [ref for ref in refs if ref in source_segments]


def meeting_evidence(operation, refs, source_segments, project_ids, action, kind, when):
    if source_segments is None:
        return None
    sources = [source_segments[ref] for ref in refs]
    speakers = list(dict.fromkeys(s['speaker_name'] for s in sources if s.get('speaker_name')))
    source_texts = [f" {normalized(s['transcript'])} " for s in sources]

    def cited_field(name, limit):
        value = text_field(operation.get(name), limit)
        phrase = normalized(value) if value else ''
        return value if phrase and any(f' {phrase} ' in source for source in source_texts) else None

    project = cited_field('project', 200)
    assignee = cited_field('assignee', 200)
    deadline_text = cited_field('deadline_text', 120)
    deadline_date = resolve_deadline(deadline_text, when)
    request_by = text_field(operation.get('requested_by'), 200)
    requested_by = next((name for name in speakers if request_by and normalized(name) == normalized(request_by)), None)
    questions = operation.get('questions')
    questions = (list(dict.fromkeys(question for value in questions if (question := text_field(value, 240))))[:3]
        if isinstance(questions, list) and action != 'close' else [])
    confirmation = cited_field('confirmation', 600)
    if confirmation:
        words = normalized(confirmation).split()
        if (set(words) & {'nuk', 'mbase', 'ndoshta', 'pacartesi', 'ende', 'duhet', 'presim', 'mund'}
                or any(phrase in f' {" ".join(words)} ' for phrase in (' do te ', ' s eshte ', ' s u '))):
            confirmation = None
    return {'kind': kind, 'speakers': speakers, 'project': project,
        'project_id': project_ids.get(project.lower()) if project else None,
        'requested_by': requested_by if kind in ('ACTION', 'INSTRUCTION', 'TASK') else None,
        'assignee': assignee, 'deadline_text': deadline_text, 'deadline_date': deadline_date,
        'questions': questions, 'confirmation': confirmation}


async def apply_operations(db, meeting, operations: list[dict], versions: dict[str, int], *, source_segments=None) -> dict:
    """Apply Mira's operations for one meeting. The caller owns the transaction."""
    stats = {'applied': 0, 'rejected': 0, 'dropped': 0}
    # Mira's own changes in this meeting raise the version she expects; a meeting counts once per item.
    expected = dict(versions)
    recorded = {(item_id, kind, speech, tuple(refs or [])) for item_id, kind, speech, refs in
        await db.execute(select(Event.item_id, Event.kind, Event.text, Event.refs).where(Event.meeting_id == meeting.id))}
    seen = {item_id for item_id, *_ in recorded}
    when = meeting.started_at or meeting.created_at or now()
    # The memory worker applies one meeting at a time. Include rows outside the
    # compact model snapshot in exact-title duplicate detection.
    by_title = {}
    wrong = set()
    for item_id, title, status, kind in await db.execute(select(Item.id, Item.title, Item.status, Item.kind)):
        key = normalized(title)
        if status == 'WRONG':
            wrong.add(key)
        else:
            by_title.setdefault((key, match_group(kind)), []).append(item_id)
    project_ids = {}
    if source_segments is not None:
        names = {name.lower() for operation in operations if isinstance(operation, dict)
            and (name := text_field(operation.get('project'), 200))}
        if names:
            projects = await db.execute(select(func.lower(Project.title), Project.id)
                .where(func.lower(Project.title).in_(names), Project.is_template.is_(False),
                    Project.department_id == meeting.department_id))
            ambiguous = set()
            for name, project_id in projects:
                if name in project_ids:
                    ambiguous.add(name)
                project_ids[name] = str(project_id)
            for name in ambiguous:
                project_ids.pop(name)

    async def latest_project(item_id):
        return await db.scalar(select(Event.details['project'].astext)
            .where(Event.item_id == item_id, Event.details['project'].astext.is_not(None))
            .order_by(Event.created_at.desc(), Event.id).limit(1))

    def attributed_people(details, people):
        if details is None:
            return people
        return list(dict.fromkeys(filter(None, [*details['speakers'], details['assignee']])))

    def event(item, kind, text, segments, details):
        event_key = (item.id, kind, text, tuple(segments))
        if event_key in recorded:
            return
        recorded.add(event_key)
        db.add(Event(id=uuid.uuid4(), item_id=item.id, kind=kind, text=text, meeting_id=meeting.id,
            partial=bool(meeting.partial), refs=segments, details=details, created_at=when))

    for operation in operations:
        if not isinstance(operation, dict):
            stats['rejected'] += 1
            continue
        action = operation.get('action')
        said = text_field(operation.get('said'), 4000)
        raw_people = operation.get('people')
        people = [name for p in raw_people if (name := text_field(p, 200))][:20] if isinstance(raw_people, list) else []
        segments = cited_segments(operation, source_segments)
        if action not in ACTIONS or not said or (source_segments is not None and not segments):
            stats['rejected'] += 1
            continue
        item = None
        description = text_field(operation.get('description'), 4000)
        kind = operation.get('kind')
        if action == 'add':
            title = text_field(operation.get('title'), 200)
            key = normalized(title) if title else ''
            if not key or not description or kind not in KINDS or key in wrong:
                stats['rejected'] += 1
                continue
            details = meeting_evidence(operation, segments, source_segments, project_ids, action, kind, when)
            match_key = (key, match_group(kind))
            matches = by_title.get(match_key, [])
            if matches and details and details['project']:
                known_projects = (await db.execute(select(Event.item_id, Event.details['project'].astext)
                    .where(Event.item_id.in_(matches), Event.details['project'].astext.is_not(None))
                    .order_by(Event.created_at))).all()
                project_by_item = {item_id: normalized(project) for item_id, project in known_projects}
                project = normalized(details['project'])
                matches = [item_id for item_id in matches if project_by_item.get(item_id, project) == project]
            if len(matches) == 1:
                item = await db.get(Item, matches[0], with_for_update=True)
                action = 'mention'
            elif matches:
                stats['rejected'] += 1
                continue
            else:
                item = Item(id=uuid.uuid4(), title=title, description=description, kind=kind, status='OPEN',
                    people=attributed_people(details, people), version=1, mention_count=1,
                    last_mentioned_at=when, human_edited=False)
                db.add(item)
                await db.flush()
                by_title.setdefault(match_key, []).append(item.id)
                seen.add(item.id)
                event(item, 'MENTION', said, segments, details)
                stats['applied'] += 1
                continue
        else:
            item_id = operation.get('item_id')
            if isinstance(item_id, str) and item_id in versions:
                item = await db.get(Item, uuid.UUID(item_id), with_for_update=True)
        if item is None or item.status == 'WRONG' or (action == 'change' and not description):
            stats['rejected'] += 1
            continue
        details = meeting_evidence(operation, segments, source_segments, project_ids, action, item.kind, when)
        if details and details['project']:
            prior_project = await latest_project(item.id)
            if prior_project and normalized(prior_project) != normalized(details['project']):
                stats['rejected'] += 1
                continue
        item_id = str(item.id)
        stale = source_segments is not None and item.last_mentioned_at is not None and item.last_mentioned_at > when
        if item.id not in seen:
            seen.add(item.id)
            item.mention_count += 1
        item.last_mentioned_at = max(filter(None, (item.last_mentioned_at, when)))
        item.people = list(dict.fromkeys([*(item.people or []), *attributed_people(details, people)]))
        if action != 'mention' and (item.version != expected.get(item_id) or stale
                or (item.human_edited and (action == 'change' or item.updated_at > when))
                or (action == 'close' and details is not None and not details['confirmation'])):
            event(item, 'MENTION', said, segments, details)
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
        event(item, {'mention': 'MENTION', 'change': 'CHANGE', 'close': 'CLOSE'}[action], said, segments, details)
        stats['applied'] += 1
    await db.flush()
    return stats


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
    events = await db.execute(select(Event, Meeting.title, Meeting.status, User.full_name, User.username)
        .outerjoin(Meeting, Meeting.id == Event.meeting_id).outerjoin(User, User.id == Event.user_id)
        .where(Event.item_id == row.id).order_by(Event.created_at.desc()))
    return {**summary(row, now() - timedelta(days=settings.MIRA_MEMORY_QUIET_DAYS)),
        'description': row.description, 'people': list(row.people or []), 'version': row.version,
        'human_edited': row.human_edited,
        'events': [{'kind': event.kind, 'text': event.text, 'created_at': event.created_at.isoformat(),
            'meeting_title': title, 'user_name': full_name or username, 'partial': event.partial,
            'meeting_id': str(event.meeting_id) if status in RECORD_STATUSES else None}
            for event, title, status, full_name, username in events]}


async def meeting_points(db, meeting, segments):
    """Return evidence from this meeting and relevant earlier meetings."""
    events = (await db.execute(select(Event, Item)
        .join(Item, Item.id == Event.item_id).where(Event.meeting_id == meeting.id, Item.status != 'WRONG',
            Event.kind.in_(HISTORY))
        .order_by(Event.kind == 'CLOSE', Event.created_at, Event.id))).all()
    points = {}
    sources = {segment.sequence: segment for segment in segments}
    for event, item in events:
        details = event.details or {}
        point = points.setdefault(item.id, {
            'id': str(item.id), 'title': item.title, 'kind': item.kind, 'status': item.status,
            'version': item.version,
            'needs_follow_up': item.status == 'OPEN' and item.kind in FOLLOW_UP_KINDS,
            'text': event.text, 'correction': item.description if item.human_edited else None,
            'sources': {}, 'questions': [], 'answers': {}, 'project': None, 'project_id': None, 'requested_by': None,
            'assignee': None, 'deadline_text': None, 'deadline_date': None,
            'discussion_state': 'NEW',
        })
        if event.kind in ('CHANGE', 'CLOSE'):
            point['text'] = event.text
        if event.kind == 'CLOSE':
            point['discussion_state'] = 'RESOLVED'
        for field in ('project', 'project_id', 'requested_by', 'assignee', 'deadline_text', 'deadline_date'):
            if details.get(field):
                point[field] = details[field]
        if item.status == 'OPEN':
            point['questions'] = list(dict.fromkeys([*point['questions'], *details.get('questions', [])]))[:3]
        for ref in event.refs or []:
            if segment := sources.get(ref):
                point['sources'][segment.id] = {'id': str(segment.id), 'speaker': segment.speaker_name,
                    'start_ms': segment.start_ms, 'end_ms': segment.end_ms}
    if points:
        answers = (await db.scalars(select(Event).where(Event.meeting_id == meeting.id, Event.kind == 'ANSWER')
            .order_by(Event.created_at, Event.id))).all()
        for answer in answers:
            if answer.item_id in points:
                points[answer.item_id]['answers'][answer.details['question']] = answer.text
    for point in points.values():
        point['sources'] = sorted(point['sources'].values(), key=lambda source: source['start_ms'])
        point['questions'] = [question for question in point['questions'] if question not in point['answers']]

    prior_date = func.coalesce(Meeting.started_at, Meeting.created_at)
    when = meeting.started_at or meeting.created_at
    if not points:
        return {'points': [], 'previous': [], 'status': meeting.memory_status}
    history_rows = await db.execute(select(Event, Item, Meeting.id, Meeting.title, prior_date)
        .join(Item, Item.id == Event.item_id).join(Meeting, Meeting.id == Event.meeting_id)
        .where(Meeting.status.in_(RECORD_STATUSES), Event.kind.in_(HISTORY),
            prior_date < when, Event.item_id.in_(points))
        .distinct(Event.item_id).order_by(Event.item_id, prior_date.desc(), Event.kind.desc(), Event.id))
    history = sorted(history_rows, key=lambda row: row[4], reverse=True)
    for _, item, *_ in history:
        if points[item.id]['discussion_state'] == 'NEW':
            points[item.id]['discussion_state'] = 'REPEATED'
    previous = [{'id': str(item.id), 'title': item.title, 'status': item.status, 'text': event.text,
        'meeting_id': str(meeting_id), 'meeting_title': title, 'date': moment.isoformat()}
        for event, item, meeting_id, title, moment in history[:20]]
    return {'points': list(points.values()), 'previous': previous, 'status': meeting.memory_status}


async def upcoming_points(db, query=None):
    """Return open points to consult before the next meeting."""
    meeting_date = func.coalesce(Meeting.started_at, Meeting.created_at)
    latest = (select(Item.id.label('item_id'), Item.title, Event.text, Meeting.id.label('meeting_id'),
        Meeting.title.label('meeting_title'), meeting_date.label('date'),
        func.row_number().over(partition_by=Item.id, order_by=(meeting_date.desc(), Event.id)).label('position'))
        .join(Event, Event.item_id == Item.id).join(Meeting, Meeting.id == Event.meeting_id)
        .where(Item.status == 'OPEN', Item.kind.in_(FOLLOW_UP_KINDS),
            Meeting.status.in_(RECORD_STATUSES), Event.kind.in_(HISTORY)))
    if query:
        from sqlalchemy.orm import aliased
        source, source_meeting = aliased(Event), aliased(Meeting)
        matching_project = (select(source.id).join(source_meeting, source_meeting.id == source.meeting_id)
            .where(source.item_id == Item.id,
                source_meeting.status.in_(RECORD_STATUSES), source.details['project'].astext.icontains(query, autoescape=True)))
        latest = latest.where(or_(Item.title.icontains(query, autoescape=True), matching_project.exists()))
    latest = latest.subquery()
    rows = await db.execute(select(latest).where(latest.c.position == 1)
        .order_by(latest.c.date.desc(), latest.c.item_id).limit(12))
    return [{'id': str(row.item_id), 'title': row.title, 'text': row.text,
        'meeting_id': str(row.meeting_id), 'meeting_title': row.meeting_title, 'date': row.date.isoformat()}
        for row in rows]


async def locked_item(db, item_id, version):
    row = await db.get(Item, item_id, with_for_update=True, populate_existing=True)
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


async def answer_clarification(db, user, item_id, payload) -> dict:
    meeting = await db.scalar(select(Meeting.id).where(Meeting.id == payload.meeting_id,
        Meeting.status.in_(RECORD_STATUSES)))
    if meeting is None:
        raise HTTPException(404, 'Takimi nuk u gjet.')
    item = await db.get(Item, item_id, with_for_update=True, populate_existing=True)
    if item is None or item.status != 'OPEN':
        raise HTTPException(404, 'Pika e hapur nuk u gjet.')
    question, answer = payload.question.strip(), payload.answer.strip()
    if not answer:
        raise HTTPException(422, 'Shkruaj një përgjigje.')
    evidence = (await db.scalars(select(Event.details).where(Event.meeting_id == meeting,
        Event.item_id == item.id, Event.kind.in_(HISTORY)))).all()
    if not any(question in (details or {}).get('questions', []) for details in evidence):
        raise HTTPException(404, 'Pyetja nuk u gjet në këtë takim.')
    previous = await db.scalar(select(Event.text).where(Event.meeting_id == meeting, Event.item_id == item.id,
        Event.kind == 'ANSWER', Event.details['question'].astext == question)
        .order_by(Event.created_at.desc(), Event.id).limit(1))
    if previous != answer:
        item.version += 1
        db.add(Event(id=uuid.uuid4(), item_id=item.id, kind='ANSWER', text=answer, meeting_id=meeting,
            user_id=user.id, details={'question': question}, created_at=now()))
    await db.commit()
    return {'question': question, 'answer': answer, 'version': item.version}


async def retry_failed(db, user) -> dict:
    if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(403, 'Vetëm adminët dhe menaxherët mund ta provojnë sërish.')
    result = await db.execute(update(Meeting).where(Meeting.memory_status == 'FAILED')
        .values(memory_status='PENDING', memory_attempts=0, memory_error=None))
    await db.commit()
    return {'retried': result.rowcount}
