"""Person-specific M3 collection and direct, audited next-day planning actions."""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.routers.discord_assistant import Actor, identity, require_bot
from app.api.routers.discord_m2 import task_owned
from app.config import settings
from app.db import get_db
from app.models.discord_assistant import DiscordLink
from app.models.discord_m3_question import DiscordM3Question as Question
from app.models.meeting import Meeting, MeetingParticipant
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_daily_rlz_state import TaskDailyRlzState
from app.models.task_one_h_report_slot import TaskOneHReportSlot
from app.models.task_user_comment import TaskUserComment
from app.models.user import User
from app.services import discord_m3 as rules, m3_reporting_points as reports
from app.services.audit import add_audit_log
from app.services.discord_meetings import held_question_at, m2_recipients
from app.services.primeflow_report import report_timezone

router = APIRouter(dependencies=[Depends(require_bot)])


async def task_owners(db, tasks):
    owners = {str(task.id): {task.assigned_to} if task.assigned_to else set() for task in tasks}
    if owners:
        for tid, uid in (await db.execute(select(TaskAssignee.task_id, TaskAssignee.user_id).where(
            TaskAssignee.task_id.in_([task.id for task in tasks])))).all():
            owners[str(tid)].add(uid)
    return owners


async def tomorrow_data(db, day, *, user_id=None, task_id=None):
    query = select(Task).where(Task.is_active.is_(True), Task.status != 'DONE')
    if task_id is not None:
        original = await db.get(Task, task_id)
        if original is None:
            return [], {}, {}
        related = [Task.id == task_id]
        if original.fast_task_group_id:
            related.append(Task.fast_task_group_id == original.fast_task_group_id)
        if original.system_template_origin_id:
            related.append(Task.system_template_origin_id == original.system_template_origin_id)
        query = query.where(or_(*related))
    elif user_id is not None:
        query = query.where(or_(Task.assigned_to == user_id, Task.id.in_(
            select(TaskAssignee.task_id).where(TaskAssignee.user_id == user_id))))
    tasks = (await db.execute(query.order_by(Task.id).execution_options(populate_existing=True))).scalars().all()
    overrides = dict((await db.execute(select(TaskOneHReportSlot.task_id, TaskOneHReportSlot.one_h_report_slot)
        .where(TaskOneHReportSlot.report_date == day, TaskOneHReportSlot.task_id.in_([task.id for task in tasks])))).all())
    owners = await task_owners(db, tasks)
    names = {uid: full_name or username for uid, full_name, username in
        (await db.execute(select(User.id, User.full_name, User.username))).all()}
    return rules.tomorrow_rows(tasks, day, overrides), owners, names


async def meeting_candidates(db, now, linked_ids):
    day = now.astimezone(report_timezone()).date()
    meetings = (await db.execute(select(Meeting).where(Meeting.starts_at.is_not(None),
        Meeting.meeting_type.in_(('internal', 'external'))))).scalars().all()
    assigned = defaultdict(set)
    for mid, uid in (await db.execute(select(MeetingParticipant.meeting_id, MeetingParticipant.user_id).where(
        MeetingParticipant.assignment_source == 'manual'))).all():
        assigned[mid].add(uid)
    fallback = (await db.execute(select(User.id).where(User.username == 'diellza.veliu', User.is_active.is_(True)))).scalar_one_or_none()
    statuses = dict((await db.execute(select(MeetingOccurrenceStatus.meeting_id, MeetingOccurrenceStatus.status)
        .where(MeetingOccurrenceStatus.occurrence_date == day))).all())
    from app.services.microsoft_calendar_sync import is_common_view_visible_meeting
    result = []
    for meeting in meetings:
        occurrence = held_question_at(meeting, now, report_timezone())
        if (not occurrence or occurrence[1] > now or statuses.get(meeting.id)
                or not is_common_view_visible_meeting(meeting)):
            continue
        row = {'meeting_id': str(meeting.id), 'title': meeting.title, 'time': occurrence[0].isoformat()}
        for uid in m2_recipients(assigned[meeting.id], linked_ids, fallback):
            result.append((uid, row))
    return result


def question_payload(q, link):
    return {'id': str(q.id), 'kind': q.kind, 'task_id': str(q.task_id) if q.task_id else None,
        'meeting_id': str(q.meeting_id) if q.meeting_id else None, 'day': q.day.isoformat(),
        'target_date': q.target_date.isoformat(), 'snapshot': q.snapshot,
        'answer': q.answer or {}, 'comment': q.comment or '', 'answered': bool(q.answered_at),
        'answered_at': q.answered_at.isoformat() if q.answered_at else None,
        'message_id': q.message_id, 'discord_user_id': link.discord_user_id,
        'guild_id': link.guild_id, 'channel_id': link.channel_id}


@router.post('/claim')
async def claim(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    phase = rules.collection_phase(now)
    if phase is None:
        return {'jobs': []}
    return await collect_questions(db, now=now, phase=phase)


async def collect_questions(db, *, now, phase, only_user_id=None):
    day = now.astimezone(report_timezone()).date()
    report = await reports.locked_report(db, day, wait=False)
    if report is None:
        return {'jobs': []}
    links = (await db.execute(select(DiscordLink).join(User, User.id == DiscordLink.user_id).where(
        DiscordLink.enabled.is_(True), DiscordLink.guild_id == settings.DISCORD_GUILD_ID,
        DiscordLink.channel_id.is_not(None), User.is_active.is_(True)))).scalars().all()
    candidates = []
    if phase == 'm3':
        data = await reports.build_task_data(db, day)
        report.data = {**(report.data or {}), **data}
        report.generated_at = now
        ids = {uuid.UUID(row['task_id']) for section in ('untouched', 'delivery') for row in data.get(section, [])}
        tasks = (await db.execute(select(Task).where(Task.id.in_(ids), Task.is_active.is_(True)))).scalars().all() if ids else []
        owners = await task_owners(db, tasks)
        for kind in ('untouched', 'delivery'):
            for row in data.get(kind, []):
                for uid in owners.get(row['task_id'], set()):
                    candidates.append((uid, kind, row, day))
        for uid, row in await meeting_candidates(db, now, {link.user_id for link in links}):
            candidates.append((uid, 'meeting', row, day))
    else:
        target = rules.target_day(day)
        rows, owners, names = await tomorrow_data(db, target)
        for link in links:
            personal = [row for row in rows if link.user_id in owners.get(row['task_id'], set())]
            for row in personal:
                candidates.append((link.user_id, 'tomorrow_task', row, target))
            candidates.append((link.user_id, 'tomorrow', {'title': 'Konfirmimi përfundimtar', 'tasks': personal}, target))
        for row in rules.slot_questions(rows, owners, names):
            for uid in owners.get(row['task_id'], set()):
                candidates.append((uid, 'slot', row, target))
    existing = {(q.link_id, q.kind, q.context_key): q for q in (await db.execute(select(Question).where(Question.day == day))).scalars().all()}
    asked = {(q.kind, str(q.task_id)) for q in existing.values()}
    by_user = {link.user_id: link for link in links}
    jobs = []
    for uid, kind, row, target in candidates:
        if only_user_id is not None and uid != only_user_id:
            continue
        link = by_user.get(uid)
        if not link:
            continue
        key = rules.context_key(kind, {} if kind == 'tomorrow' else row)
        if kind == 'tomorrow':
            children = [existing.get((link.id, 'tomorrow_task', rules.context_key('tomorrow_task', task))) for task in row['tasks']]
            if any(child is None or (not child.answered_at and not rules.sent_in_regular_window(child, phase)) for child in children):
                continue
        if kind in {'untouched', 'delivery'} and (kind, row['task_id']) not in asked:
            manual = report.manual_answers or {}
            answer_key = f"{'delivery_choice' if kind == 'delivery' else 'untouched_comment'}:{row['task_id']}"
            if manual.get(answer_key):
                continue
        q = existing.get((link.id, kind, key))
        if q and not rules.delivery_is_pending(q, now, phase):
            continue
        if q is None:
            q = Question(link_id=link.id, task_id=uuid.UUID(row['task_id']) if row.get('task_id') else None,
                meeting_id=uuid.UUID(row['meeting_id']) if row.get('meeting_id') else None,
                day=day, target_date=target, kind=kind, context_key=key, snapshot=row, lease_until=now)
            db.add(q)
            await db.flush()
            existing[(link.id, kind, key)] = q
        if len(jobs) < 50:
            if q.sent_at and not rules.sent_in_regular_window(q, phase):
                q.snapshot = {**q.snapshot, '_previous_test_message_id': q.message_id,
                    '_test_sent_at': q.sent_at.isoformat()}
                # The real attempt now has its own lease. Keep the earlier
                # message ID for cleanup, but do not let parallel workers
                # reclaim it until this attempt is acknowledged or expires.
                q.sent_at = None
            q.lease_until = now + timedelta(minutes=2)
            job = question_payload(q, link)
            if q.snapshot.get('_previous_test_message_id'):
                job['previous_test_message_id'] = q.snapshot['_previous_test_message_id']
            jobs.append(job)
    await db.commit()
    return {'jobs': jobs}


async def own_question(db, question_id, actor, *, write=False):
    link, user = await identity(db, actor, lock=write)
    report = await reports.locked_report(db, datetime.now(report_timezone()).date()) if write else None
    query = select(Question).where(Question.id == question_id)
    q = (await db.execute(query.with_for_update() if write else query)).scalar_one_or_none()
    if not q or q.link_id != link.id:
        raise HTTPException(403, 'Kjo pyetje nuk është për ty.')
    if q.day != datetime.now(report_timezone()).date():
        raise HTTPException(409, 'Kjo pyetje i përket një dite të kaluar.')
    if q.task_id:
        await task_owned(db, user.id, q.task_id)
    if q.meeting_id:
        participants = set((await db.execute(select(MeetingParticipant.user_id).where(
            MeetingParticipant.meeting_id == q.meeting_id, MeetingParticipant.assignment_source == 'manual'))).scalars())
        if user.id not in participants and (participants or user.username != 'diellza.veliu'):
            raise HTTPException(403, 'Pjesëmarrësit e takimit kanë ndryshuar.')
    return q, link, user, report


async def live_payload(db, q, link, user):
    result = question_payload(q, link)
    if q.task_id:
        task = await task_owned(db, user.id, q.task_id)
        result['live_dates'] = {field: getattr(task, field).isoformat() if getattr(task, field) else None for field in ('start_date', 'due_date')}
        result['progress'] = task.progress_percentage or 0
        if task.status == 'DONE' and q.kind != 'delivery':
            result['resolved'] = 'Detyra është përfunduar.'
        if q.kind in {'untouched', 'delivery'} and not reports.select_task_sections([task], [], q.day)[q.kind]:
            result['resolved'] = 'Detyra nuk është më në këtë pikë të M3.'
    if (q.answer or {}).get('platform'):
        result['resolved'] = 'Përgjigjja u plotësua në PrimeFlow.'
    if q.kind in {'tomorrow', 'tomorrow_task', 'slot'}:
        rows, owners, names = await tomorrow_data(db, q.target_date,
            user_id=user.id if q.kind == 'tomorrow' else None, task_id=q.task_id)
        personal = [row for row in rows if user.id in owners.get(row['task_id'], set())]
        if q.kind == 'tomorrow':
            result['snapshot'] = {**q.snapshot, 'tasks': personal}
            result['plan_key'] = rules.context_key('tomorrow', result['snapshot'])
            result['plan_changed'] = bool(q.answered_at and (q.answer or {}).get('plan_key') != result['plan_key'])
        else:
            live = next((row for row in personal if row['task_id'] == str(q.task_id)), None)
            if live is None:
                result['resolved'] = 'Detyra nuk është më në planin për nesër.'
            elif q.kind == 'slot':
                conflict = next((row for row in rules.slot_questions(rows, owners, names) if row['task_id'] == str(q.task_id)), None)
                if not conflict:
                    result['resolved'] = 'Slotet janë në rregull.'
                else:
                    result['snapshot'] = conflict
            else:
                result['snapshot'] = live
    if q.meeting_id:
        status = (await db.execute(select(MeetingOccurrenceStatus.status).where(
            MeetingOccurrenceStatus.meeting_id == q.meeting_id, MeetingOccurrenceStatus.occurrence_date == q.day))).scalar_one_or_none()
        if status:
            result['resolved'] = 'Takimi u shënua: ' + status
    return result


@router.post('/{question_id}/open')
async def open_question(question_id: uuid.UUID, actor: Actor, db: AsyncSession = Depends(get_db)):
    q, link, user, _ = await own_question(db, question_id, actor)
    return await live_payload(db, q, link, user)


class Receipt(Actor):
    message_id: str = Field(pattern=r'^\d{1,32}$')


@router.post('/{question_id}/ack')
async def acknowledge(question_id: uuid.UUID, payload: Receipt, db: AsyncSession = Depends(get_db)):
    q, _, _, _ = await own_question(db, question_id, payload, write=True)
    q.message_id, q.sent_at = payload.message_id, datetime.now(timezone.utc)
    await db.commit()
    return {'ok': True}


@router.post('/{question_id}/tasks/{task_id}')
async def select_task(question_id: uuid.UUID, task_id: uuid.UUID, actor: Actor, db: AsyncSession = Depends(get_db)):
    parent, link, user, _ = await own_question(db, question_id, actor, write=True)
    if parent.kind != 'tomorrow':
        raise HTTPException(422, 'Zgjidh detyrën nga plani për nesër.')
    rows, owners, _ = await tomorrow_data(db, parent.target_date, user_id=user.id)
    row = next((r for r in rows if r['task_id'] == str(task_id) and user.id in owners.get(r['task_id'], set())), None)
    if row is None:
        raise HTTPException(409, 'Detyra nuk është në planin tënd për nesër.')
    key = rules.context_key('tomorrow_task', row)
    q = (await db.execute(select(Question).where(Question.link_id == link.id, Question.day == parent.day,
        Question.kind == 'tomorrow_task', Question.context_key == key))).scalar_one_or_none()
    if q is None:
        q = Question(link_id=link.id, task_id=task_id, day=parent.day, target_date=parent.target_date,
            kind='tomorrow_task', context_key=key, snapshot=row, lease_until=datetime.now(timezone.utc))
        db.add(q)
        await db.flush()
    result = await live_payload(db, q, link, user)
    await db.commit()
    return result


class Answer(Actor):
    action: Literal['comment', 'progress', 'done', 'postpone', 'PO', 'JO', 'held', 'canceled', 'slot']
    comment: str = Field(default='', max_length=4000)
    progress: int | None = Field(default=None, ge=1, le=99)
    start_date: datetime | None = None
    due_date: datetime | None = None
    slot: Literal['10:00', '11:00', '11:50', '14:20', '16:00'] | None = None
    expected_answered_at: datetime | None = None
    expected_dates: dict[str, str | None] | None = None
    expected_slot_key: str | None = None
    plan_key: str | None = None


def validate_answer(q, value):
    allowed = {'untouched': {'comment', 'progress', 'done', 'postpone'}, 'delivery': {'PO', 'JO'},
        'meeting': {'held', 'canceled'}, 'tomorrow': {'PO', 'JO'},
        'tomorrow_task': {'PO', 'JO', 'comment', 'postpone'}, 'slot': {'slot'}}
    if value.action not in allowed[q.kind]:
        raise HTTPException(422, 'Ky veprim nuk lejohet për këtë pyetje.')
    if value.action in {'comment', 'progress', 'done', 'postpone', 'JO', 'canceled'} and not value.comment.strip():
        raise HTTPException(422, 'Plotëso komentin.')
    if value.action == 'progress' and value.progress is None:
        raise HTTPException(422, 'Shëno progresin nga 1 deri në 99%.')
    if value.action == 'slot' and value.slot is None:
        raise HTTPException(422, 'Zgjidh slotin.')
    if value.action == 'postpone' and (value.start_date is None or value.due_date is None
            or value.start_date.tzinfo is None or value.due_date.tzinfo is None
            or value.start_date > value.due_date or value.expected_dates is None):
        raise HTTPException(422, 'Plotëso Start dhe Due me data të vlefshme; Start duhet të jetë para Due.')


async def update_report_answers(db, report, q):
    if q.kind not in {'untouched', 'delivery'}:
        return
    pairs = (await db.execute(select(Question, User).join(DiscordLink, DiscordLink.id == Question.link_id)
        .join(User, User.id == DiscordLink.user_id).where(Question.day == q.day, Question.task_id == q.task_id,
            Question.kind == q.kind, DiscordLink.enabled.is_(True), User.is_active.is_(True)).order_by(User.full_name))).all()
    task = await db.get(Task, q.task_id)
    owners = (await task_owners(db, [task])).get(str(q.task_id), set()) if task else set()
    pairs = [(item, user) for item, user in pairs if user.id in owners]
    answers = dict(report.manual_answers or {})
    prefix = 'delivery' if q.kind == 'delivery' else 'untouched_comment'
    answers[f'{prefix}:{q.task_id}'] = '\n'.join(f'{user.full_name or user.username}: {item.comment or (item.answer or {}).get("action", "")}'
        for item, user in pairs if item.answered_at)
    if q.kind == 'delivery':
        answers[f'delivery_choice:{q.task_id}'] = ('JO' if any((item.answer or {}).get('action') == 'JO' for item, _ in pairs)
            else 'PO' if pairs and all(item.answered_at and (item.answer or {}).get('action') == 'PO' for item, _ in pairs) else '')
    report.manual_answers = answers
    report.status, report.last_error = 'DRAFT', None


@router.post('/{question_id}/answer')
async def answer(question_id: uuid.UUID, value: Answer, db: AsyncSession = Depends(get_db)):
    q, link, user, report = await own_question(db, question_id, value, write=True)
    validate_answer(q, value)
    recorded = {key: item for key, item in value.model_dump(mode='json').items()
        if key in {'action', 'progress', 'slot', 'start_date', 'due_date'}}
    if q.kind == 'tomorrow':
        recorded['plan_key'] = value.plan_key
    if q.kind != 'tomorrow' and q.answered_at and q.answer == recorded and q.comment == value.comment.strip():
        return {'ok': True}
    if value.expected_answered_at != q.answered_at:
        raise HTTPException(409, 'Përgjigjja ndryshoi ndërkohë. Hape përsëri pyetjen.')
    live = await live_payload(db, q, link, user)
    if live.get('resolved'):
        raise HTTPException(409, live['resolved'])
    if q.kind == 'tomorrow' and value.plan_key != live['plan_key']:
        raise HTTPException(409, 'Plani për nesër ka ndryshuar. Rifresko listën para konfirmimit.')
    if q.kind == 'slot' and value.expected_slot_key != rules.context_key('slot', live['snapshot']):
        raise HTTPException(409, 'Slotet ndryshuan ndërkohë. Kontrollo oraret e reja.')
    if q.kind in {'untouched', 'delivery'}:
        task = await task_owned(db, user.id, q.task_id)
        current = reports.select_task_sections([task], [], q.day)[q.kind]
        if not current:
            raise HTTPException(409, 'Detyra nuk është më në këtë pikë të M3.')

    message_updates = []

    async def persist(_task=None):
        previous_answer, previous_stamp = q.answer, q.answered_at
        q.answer, q.comment, q.answered_at = recorded, value.comment.strip(), datetime.now(timezone.utc)
        if q.kind == 'tomorrow_task' and value.action == 'comment':
            q.answer = previous_answer if previous_stamp else recorded
            q.answered_at = previous_stamp
        if q.task_id:
            body = f'M3 {q.day:%d.%m.%Y} · {rules.KINDS[q.kind]} · {value.action}\n{q.comment}'
            existing = (await db.execute(select(TaskUserComment).where(TaskUserComment.task_id == q.task_id,
                TaskUserComment.user_id == user.id).with_for_update())).scalar_one_or_none()
            if existing:
                existing.comment = '\n\n'.join(filter(None, (existing.comment, body)))
            else:
                db.add(TaskUserComment(task_id=q.task_id, user_id=user.id, comment=body))
            if q.kind == 'untouched':
                state = insert(TaskDailyRlzState).values(task_id=q.task_id, user_id=user.id,
                    day_date=q.day, reason_code='OTHER', comment=q.comment)
                await db.execute(state.on_conflict_do_update(constraint='uq_task_daily_rlz_state_task_user_day',
                    set_={'reason_code': 'OTHER', 'comment': q.comment, 'updated_at': q.answered_at}))
        add_audit_log(db=db, actor_user_id=user.id, entity_type='task' if q.task_id else 'meeting' if q.meeting_id else 'discord_m3_question',
            entity_id=q.task_id or q.meeting_id or q.id, action='discord.m3_answer',
            after={'question_id': str(q.id), 'target_date': q.target_date.isoformat(), **recorded, 'comment': q.comment})
        await db.flush()
        await update_report_answers(db, report, q)
        if q.kind == 'untouched' and value.action in {'done', 'progress', 'postpone'}:
            report.data = {**(report.data or {}), **await reports.build_task_data(db, q.day)}
            report.generated_at = q.answered_at
        if q.kind == 'meeting':
            from app.services.m3_unheld_meetings import build_unheld_meetings
            report.data = {**(report.data or {}), 'unheld_meetings': await build_unheld_meetings(db, q.day)}
            if value.action == 'canceled':
                report.manual_answers = {**(report.manual_answers or {}), f'meeting_plan:{q.meeting_id}': q.comment}
            report.status, report.last_error, report.updated_by = 'DRAFT', None, user.id
        if q.kind == 'tomorrow' and value.action == 'PO':
            # "Po, të gjitha" explicitly includes work and completion at Due.
            due_ids = [uuid.UUID(row['task_id']) for row in live['snapshot']['tasks']]
            children = (await db.execute(select(Question).where(Question.link_id == q.link_id,
                Question.day == q.day, Question.kind == 'tomorrow_task', Question.task_id.in_(due_ids),
                Question.answered_at.is_(None)).with_for_update())).scalars().all()
            for child in children:
                child.answer = {'action': 'PO', 'summary_id': str(q.id)}
                child.answered_at = q.answered_at
                add_audit_log(db=db, actor_user_id=user.id, entity_type='task', entity_id=child.task_id,
                    action='discord.m3_answer', after={'question_id': str(child.id), 'action': 'PO', 'summary_id': str(q.id)})
                if child.message_id:
                    message_updates.append(question_payload(child, link))

    if value.action in {'postpone', 'done', 'progress'}:
        from app.api.routers.tasks import update_task_in_session
        from app.schemas.task import TaskUpdate
        updates = {'status': 'DONE', 'progress_percentage': 100} if value.action == 'done' else {
            'status': 'IN_PROGRESS', 'progress_percentage': value.progress}
        if value.action == 'postpone':
            updates = {'start_date': value.start_date, 'due_date': value.due_date,
                'postponement_reason_code': 'OTHER', 'postponement_comment': value.comment}

        async def recheck(task):
            await task_owned(db, user.id, q.task_id)
            if value.action == 'postpone':
                from app.services.discord_m2_postponements import iso
                if any(iso(getattr(task, field)) != iso(value.expected_dates.get(field)) for field in ('start_date', 'due_date')):
                    raise HTTPException(409, 'Datat ndryshuan ndërkohë. Hape përsëri formularin.')
                changed = [field for field in ('start_date', 'due_date') if iso(getattr(task, field)) != iso(getattr(value, field))]
                if not changed or any(getattr(task, field) and getattr(value, field) < getattr(task, field) for field in changed):
                    raise HTTPException(422, 'Shty Start ose Due përpara; lëre të pandryshuar datën tjetër sipas nevojës.')
            elif task.status == 'DONE':
                raise HTTPException(409, 'Detyra është përfunduar ndërkohë.')

        await update_task_in_session(q.task_id, TaskUpdate(**updates), db, user,
            before_update=recheck, before_commit=persist, return_dto=False)
    elif value.action == 'slot':
        # Same endpoint as My View, with an explicit tomorrow date (no rollover).
        from app.api.routers.tasks import update_task_one_h_report_slot_in_session, TaskOneHReportSlotUpdate

        async def recheck_slot(task):
            await task_owned(db, user.id, task.id)
            current = await live_payload(db, q, link, user)
            if current.get('resolved') or rules.context_key('slot', current['snapshot']) != value.expected_slot_key:
                raise HTTPException(409, 'Slotet ndryshuan ndërkohë. Kontrollo përsëri.')

        await update_task_one_h_report_slot_in_session(q.task_id, TaskOneHReportSlotUpdate(
            report_date=q.target_date, one_h_report_slot=value.slot), db, user,
            before_update=recheck_slot, before_commit=persist, return_dto=False)
    elif q.kind == 'meeting':
        from app.api.routers.meetings import update_meeting_occurrence_status_in_session
        from app.schemas.meeting import MeetingOccurrenceStatusUpdate

        async def recheck_meeting(meeting, status):
            participants = set((await db.execute(select(MeetingParticipant.user_id).where(
                MeetingParticipant.meeting_id == meeting.id, MeetingParticipant.assignment_source == 'manual'))).scalars())
            if user.id not in participants and (participants or user.username != 'diellza.veliu'):
                raise HTTPException(403, 'Pjesëmarrësit e takimit kanë ndryshuar.')
            if status and status.status:
                raise HTTPException(409, 'Takimi është shënuar ndërkohë. Rifresko pyetjen.')

        await update_meeting_occurrence_status_in_session(q.meeting_id, MeetingOccurrenceStatusUpdate(
            occurrence_date=q.day, status=value.action, note=value.comment), db, user,
            before_update=recheck_meeting, before_commit=persist)
    else:
        if q.kind == 'tomorrow':
            # Keep the exact plan the employee confirmed for later audit.
            q.snapshot = live['snapshot']
        await persist()
        await db.commit()
    return {'ok': True, 'message': 'U ruajt në PrimeFlow.', 'updates': message_updates}


async def capture_report_changes(db, report, before, submitted):
    """A manager's explicit platform answer supersedes outstanding Discord forms."""
    changed = {key for key, value in submitted.items() if value != before.get(key, '')
        and key.startswith(('untouched_comment:', 'delivery:', 'delivery_choice:'))}
    if not changed:
        return
    questions = (await db.execute(select(Question).where(Question.day == report.report_date))).scalars().all()
    for q in questions:
        keys = {f'delivery:{q.task_id}', f'delivery_choice:{q.task_id}'} if q.kind == 'delivery' else {f'untouched_comment:{q.task_id}'} if q.kind == 'untouched' else set()
        if changed.intersection(keys):
            q.answer = {'platform': True}
            q.comment = (report.manual_answers or {}).get(f'delivery:{q.task_id}' if q.kind == 'delivery' else f'untouched_comment:{q.task_id}', '')
            q.answered_at = datetime.now(timezone.utc)
