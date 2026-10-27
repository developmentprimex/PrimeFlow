from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.routers.discord_assistant import Actor, identity, require_bot
from app.config import settings
from app.db import get_db
from app.models.audit_log import AuditLog
from app.models.discord_assistant import DiscordLink
from app.models.discord_m2_question import DiscordM2Question as Question
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_daily_rlz_state import TaskDailyRlzState
from app.models.task_user_comment import TaskUserComment
from app.models.user import User
from app.models.discord_m2_postponement import DiscordM2Postponement
from app.services import discord_m2 as service, m2_reporting_points as reports
from app.services.audit import add_audit_log
from app.services.daily_rlz_compliance import REASON_LABELS
from app.services.primeflow_report import report_timezone

router = APIRouter(dependencies=[Depends(require_bot)])


async def task_owned(db, user_id, task_id):
    task = await db.get(Task, task_id, populate_existing=True)
    assigned = task and (task.assigned_to == user_id or (await db.execute(select(TaskAssignee.task_id).where(
        TaskAssignee.task_id == task_id, TaskAssignee.user_id == user_id))).scalar_one_or_none())
    if not assigned or not task.is_active:
        raise HTTPException(403, "Detyra nuk është më e caktuar për ty ose nuk është aktive.")
    return task


async def data_with_moves(db, day):
    data = await reports.build_task_data(db, day)
    # Identify the latest date change so an old reply cannot explain a new move.
    ids = {uuid.UUID(row['task_id']) for key in ('postponed', 'postponed_am') for row in data.get(key, [])}
    if ids:
        moves = dict((await db.execute(select(AuditLog.entity_id, func.max(AuditLog.created_at)).where(
            AuditLog.entity_type == 'task', AuditLog.entity_id.in_(ids),
            AuditLog.action.in_(['task.start_date_changed', 'task.due_date_changed']),
        ).group_by(AuditLog.entity_id))).all())
        for section in ('postponed', 'postponed_am'):
            for row in data.get(section, []):
                stamp = moves.get(uuid.UUID(row['task_id']))
                row['last_move_at'] = stamp.isoformat() if stamp else None
    return data


def question_payload(question, link):
    result = {'id': str(question.id), 'task_id': str(question.task_id), 'kind': question.kind,
            'day': question.day.isoformat(), 'snapshot': question.snapshot,
            'discord_user_id': link.discord_user_id, 'guild_id': link.guild_id, 'channel_id': link.channel_id,
            'answered': bool(question.answered_at), 'reason_code': question.reason_code,
            'answered_at': question.answered_at.isoformat() if question.answered_at else None,
            'message_id': question.message_id,
            'comment': question.comment, 'choice': question.choice,
            'reasons': [{'value': code, 'label': label} for code, label in REASON_LABELS.items()]}
    if question.platform_answered_at and (not question.answered_at or question.platform_answered_at > question.answered_at):
        values = question.platform_answer or {}
        result.update(choice=values.get('choice'), reason_code=values.get('reason_code'), comment=values.get('comment', ''),
            answered=bool(values.get('choice') or values.get('comment')), answered_at=question.platform_answered_at.isoformat())
        if result['answered']:
            result['platform_status'] = 'Përgjigjja u plotësua në PrimeFlow.'
            result['platform_answered'] = True
    return result


@router.post('/claim')
async def claim(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    if not service.collection_open(now):
        return {'jobs': []}
    return await collect_questions(db, now=now)


async def collect_questions(db: AsyncSession, *, now: datetime, only_user_id: uuid.UUID | None = None):
    """Shared collector; an operator can run a targeted test without changing the clock.

    Only /claim is an HTTP endpoint and retains its normal scheduling guard.
    """
    day = now.astimezone(report_timezone()).date()
    report = await reports.locked_report(db, day, wait=False)
    if report is None:
        return {'jobs': []}
    data = await data_with_moves(db, day)
    report.data, report.generated_at = data, now
    links_query = select(DiscordLink).join(User, User.id == DiscordLink.user_id).where(
        DiscordLink.enabled.is_(True), DiscordLink.channel_id.is_not(None),
        DiscordLink.guild_id == settings.DISCORD_GUILD_ID, User.is_active.is_(True))
    if only_user_id is not None:
        links_query = links_query.where(DiscordLink.user_id == only_user_id)
    links = (await db.execute(links_query)).scalars().all()
    candidates = service.question_rows(data)
    ids = {uuid.UUID(row['task_id']) for _, row in candidates}
    task_rows = (await db.execute(select(Task.id, Task.assigned_to, Task.status).where(
        Task.id.in_(ids), Task.is_active.is_(True)))).all() if ids else []
    owners = {task_id: {owner} if owner else set() for task_id, owner, _ in task_rows}
    done = {task_id for task_id, _, status in task_rows if str(getattr(status, 'value', status)) == 'DONE'}
    if ids:
        for task_id, owner in (await db.execute(select(TaskAssignee.task_id, TaskAssignee.user_id).where(TaskAssignee.task_id.in_(ids)))).all():
            if task_id in owners:
                owners[task_id].add(owner)
    states = {(state.task_id, state.user_id): state for state in (await db.execute(select(TaskDailyRlzState).where(
        TaskDailyRlzState.day_date == day, TaskDailyRlzState.task_id.in_(ids)))).scalars().all()} if ids else {}
    existing = {(q.link_id, q.kind, q.context_key): q for q in (await db.execute(select(Question).where(Question.day == day))).scalars().all()}
    jobs = []
    for link in links:
        for kind, snapshot in candidates:
            task_id = uuid.UUID(snapshot['task_id'])
            if kind != 'delivery' and task_id in done:
                continue
            if link.user_id not in owners.get(task_id, set()):
                continue
            state = states.get((task_id, link.user_id))
            if kind == 'postponed' and state and state.reason_code and (state.comment or '').strip():
                move = snapshot.get('last_move_at')
                if move and state.updated_at >= datetime.fromisoformat(move):
                    continue
            key = service.context_key(kind, snapshot)
            question = existing.get((link.id, kind, key))
            if question and (question.answered_at or question.sent_at or question.lease_until > now):
                continue
            if question is None:
                question = Question(link_id=link.id, task_id=task_id, day=day, kind=kind,
                                    context_key=key, snapshot=snapshot, lease_until=now)
                db.add(question)
                await db.flush()
            if len(jobs) < 50:
                question.lease_until = now + timedelta(minutes=2)
                jobs.append(question_payload(question, link))
    await db.commit()
    return {'jobs': jobs}


async def own_question(db, question_id, actor):
    link, user = await identity(db, actor, lock=True)
    question = (await db.execute(select(Question).where(Question.id == question_id))).scalar_one_or_none()
    if question is None or question.link_id != link.id:
        raise HTTPException(403, 'Kjo pyetje nuk është për ty.')
    if question.day != datetime.now(report_timezone()).date():
        raise HTTPException(409, 'Kjo pyetje i përket një dite të kaluar.')
    await task_owned(db, user.id, question.task_id)
    return question, link, user


@router.post('/{question_id}/open')
async def open_question(question_id: uuid.UUID, actor: Actor, db: AsyncSession = Depends(get_db)):
    question, link, _ = await own_question(db, question_id, actor)
    result = question_payload(question, link)
    task = await db.get(Task, question.task_id)
    result['live_dates'] = {field: getattr(task, field).isoformat() if getattr(task, field) else None for field in ('start_date', 'due_date')}
    if question.kind == 'continuation':
        request = (await db.execute(select(DiscordM2Postponement).where(
            DiscordM2Postponement.question_id == question.id).order_by(DiscordM2Postponement.created_at.desc()).limit(1))).scalar_one_or_none()
        if request:
            result['postponement'] = {'id': str(request.id), 'status': request.status}
    return result


class Receipt(Actor):
    message_id: str = Field(pattern=r'^\d{1,32}$')


@router.post('/{question_id}/ack')
async def ack(question_id: uuid.UUID, payload: Receipt, db: AsyncSession = Depends(get_db)):
    question, _, _ = await own_question(db, question_id, payload)
    question.sent_at, question.message_id = datetime.now(timezone.utc), payload.message_id
    await db.commit()
    return {'ok': True}


class Answer(Actor):
    reason_code: str | None = Field(default=None, max_length=40)
    comment: str = Field(default='', max_length=4000)
    choice: Literal['PO', 'JO'] | None = None
    expected_answered_at: datetime | None = None


async def update_report_answers(db, report, question):
    pairs = (await db.execute(select(Question, User).join(DiscordLink, DiscordLink.id == Question.link_id)
        .join(User, User.id == DiscordLink.user_id).where(Question.day == question.day,
        Question.task_id == question.task_id, Question.kind == question.kind,
        Question.context_key == question.context_key, Question.answered_at.is_not(None))
        .order_by(Question.answered_at, Question.id))).all()
    answers = dict(report.manual_answers or {})
    comment = '\n'.join(f'{user.full_name or user.username}: {q.comment or "Dorëzuar"}' for q, user in pairs)
    if question.kind != 'postponed':
        prefix = {'unfinished': 'unfinished_comment', 'progress': 'progress_comment', 'delivery': 'delivery', 'continuation': 'pm_comment'}[question.kind]
        answers[f'{prefix}:{question.task_id}'] = comment
    if question.kind == 'continuation':
        answers[f'pm_choice:{question.task_id}'] = 'JO' if any(q.choice == 'JO' for q, _ in pairs) else 'PO'
    if question.kind == 'delivery':
        # For shared tasks, keep each person's answer visible; any JO wins.
        pending = (await db.execute(select(Question.id).join(DiscordLink, DiscordLink.id == Question.link_id).where(
            Question.day == question.day, Question.task_id == question.task_id, Question.kind == 'delivery',
            Question.context_key == question.context_key, Question.answered_at.is_(None), DiscordLink.enabled.is_(True)))).first()
        answers[f'delivery_choice:{question.task_id}'] = 'JO' if any(q.choice == 'JO' for q, _ in pairs) else '' if pending else 'PO'
    if question.kind == 'progress':
        reasons = {q.reason_code for q, _ in pairs}
        answers[f'progress_reason:{question.task_id}'] = next(iter(reasons)) if len(reasons) == 1 else 'OTHER'
    elif question.kind in {'unfinished', 'postponed'}:
        reasons = {q.reason_code for q, _ in pairs}
        answers[f'{question.kind}_reason:{question.task_id}'] = next(iter(reasons)) if len(reasons) == 1 else 'OTHER'
    report.manual_answers = answers


@router.post('/{question_id}/answer')
async def answer(question_id: uuid.UUID, payload: Answer, db: AsyncSession = Depends(get_db)):
    question, _, user = await own_question(db, question_id, payload)
    task = await task_owned(db, user.id, question.task_id)
    if question.kind != 'delivery' and str(getattr(task.status, 'value', task.status)) == 'DONE':
        raise HTTPException(409, 'Detyra është përfunduar ndërkohë.')
    try:
        reason, comment, choice = service.validate_answer(question.kind, payload.reason_code, payload.comment, payload.choice)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    platform_newer = question.platform_answered_at and (not question.answered_at or question.platform_answered_at > question.answered_at)
    if platform_newer and any((question.platform_answer or {}).get(key) for key in ('choice', 'comment')):
        raise HTTPException(409, 'Pyetja është plotësuar në PrimeFlow. Rifresko mesazhin.')
    if not platform_newer and question.answered_at and (question.reason_code, question.comment, question.choice) == (reason, comment, choice):
        return {'ok': True, 'message': 'Përgjigjja është ruajtur tashmë.'}
    effective_stamp = question.platform_answered_at if platform_newer else question.answered_at
    if 'expected_answered_at' in payload.model_fields_set and payload.expected_answered_at != effective_stamp:
        raise HTTPException(409, 'Përgjigjja ka ndryshuar ndërkohë. Hape përsëri formularin.')
    if question.kind in {'unfinished', 'progress', 'postponed'}:
        state = (await db.execute(select(TaskDailyRlzState).where(TaskDailyRlzState.task_id == question.task_id,
            TaskDailyRlzState.user_id == user.id, TaskDailyRlzState.day_date == question.day))).scalar_one_or_none()
        latest_question_stamp = max(value for value in (question.sent_at, question.answered_at) if value) if (question.sent_at or question.answered_at) else None
        if state and state.reason_code and (state.comment or '').strip() and (not latest_question_stamp or state.updated_at > latest_question_stamp):
            raise HTTPException(409, 'Arsyeja dhe komenti janë plotësuar në PrimeFlow. Rifresko mesazhin.')
    report = await reports.locked_report(db, question.day)
    if question.kind in {'delivery', 'continuation'}:
        # These choices change only the person's answer, not the task's dates or
        # progress. Validate the actual task with the report's selector without
        # rebuilding every section for the entire company twice per click.
        section = 'delivery' if question.kind == 'delivery' else 'pm_continuation'
        current = next(iter(reports.select_task_sections([task], [], question.day)[section]), None)
        data = dict(report.data or {})
    else:
        data = await data_with_moves(db, question.day)
        current = next((row for kind, row in service.question_rows(data)
                        if kind == question.kind and service.context_key(kind, row) == question.context_key), None)
    if current is None:
        raise HTTPException(409, 'Detyra ka ndryshuar ose është përfunduar. Rifresko raportin M2.')
    previous = {'reason_code': question.reason_code, 'comment': question.comment, 'choice': question.choice,
                'answered_at': question.answered_at.isoformat() if question.answered_at else None}
    question.reason_code, question.comment, question.choice = reason, comment, choice
    question.answered_at = datetime.now(timezone.utc)
    if question.kind not in {'delivery', 'continuation'}:
        state = insert(TaskDailyRlzState).values(task_id=question.task_id, user_id=user.id,
            day_date=question.day, reason_code=reason, comment=comment)
        await db.execute(state.on_conflict_do_update(constraint='uq_task_daily_rlz_state_task_user_day',
            set_={'reason_code': reason, 'comment': comment, 'updated_at': func.now()}))
    # Keep the existing personal task comment and append the M2 response.
    label = service.KINDS[question.kind]
    body = f'M2 {question.day:%d.%m.%Y} — {label}\n' + (f'{REASON_LABELS[reason]}\n' if reason else '')
    choice_label = 'Vazhdon në PM' if question.kind == 'continuation' else 'Dorëzuar'
    body += (f'{choice_label}: {choice}\n' if choice else '') + comment
    existing = (await db.execute(select(TaskUserComment).where(TaskUserComment.task_id == question.task_id,
        TaskUserComment.user_id == user.id).with_for_update())).scalar_one_or_none()
    if existing:
        existing.comment = '\n\n'.join(part for part in (existing.comment, body) if part)
    else:
        db.add(TaskUserComment(task_id=question.task_id, user_id=user.id, comment=body))
    await db.flush()
    if question.kind not in {'delivery', 'continuation'}:
        data = await data_with_moves(db, question.day)
        report.data, report.generated_at = data, datetime.now(timezone.utc)
    report.updated_by = user.id
    report.status, report.last_error = 'DRAFT', None
    await update_report_answers(db, report, question)
    add_audit_log(db=db, actor_user_id=user.id, entity_type='task', entity_id=question.task_id,
        action='task.discord_m2_answer', before=previous, after={'question_id': str(question.id), 'kind': question.kind,
        'day': question.day.isoformat(), 'reason_code': reason, 'comment': comment, 'choice': choice,
        'context': question.snapshot})
    await db.commit()
    return {'ok': True, 'message': 'U ruajt te detyra dhe raporti M2 në PrimeFlow.'}
