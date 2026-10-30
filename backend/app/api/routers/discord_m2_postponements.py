from __future__ import annotations
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select, text, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.config import settings
from app.api.routers.discord_assistant import Actor, identity, require_bot
from app.api.routers.discord_m2 import own_question, task_owned, question_payload
from app.models.discord_m2_postponement import DiscordM2Postponement as Request
from app.models.discord_m2_question import DiscordM2Question
from app.models.discord_assistant import DiscordLink
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.user import User
from app.models.daily_plan_adjustment import DailyPlanAdjustment
from app.models.audit_log import AuditLog
from app.services import discord_m2_postponements as rules
from app.services.daily_rlz_compliance import REASON_LABELS
from app.services.audit import add_audit_log
from app.services.primeflow_report import report_timezone

router = APIRouter(dependencies=[Depends(require_bot)])


async def reviewer(db, guild_id):
    row = (await db.execute(select(User, DiscordLink).join(DiscordLink, DiscordLink.user_id == User.id).where(
        User.username == rules.APPROVER_USERNAME, User.is_active.is_(True), DiscordLink.enabled.is_(True),
        DiscordLink.guild_id == guild_id, DiscordLink.channel_id.is_not(None)))).one_or_none()
    if row is None:
        raise HTTPException(409, 'Diellza Veliu duhet të ketë lidhje aktive me Discord-in për konfirmimin.')
    return row


async def task_snapshots(db, task):
    from app.api.routers.tasks import _uses_fast_task_group
    tasks = [task]
    if task.fast_task_group_id and _uses_fast_task_group(task):
        tasks = list((await db.execute(select(Task).where(Task.fast_task_group_id == task.fast_task_group_id,
            Task.is_active.is_(True)).order_by(Task.id).execution_options(populate_existing=True))).scalars())
    ids = [item.id for item in tasks]
    owners = {item.id: {item.assigned_to} if item.assigned_to else set() for item in tasks}
    for task_id, owner in (await db.execute(select(TaskAssignee.task_id, TaskAssignee.user_id).where(TaskAssignee.task_id.in_(ids)))).all():
        owners[task_id].add(owner)
    names = dict((await db.execute(select(User.id, User.full_name).where(User.id.in_({uid for group in owners.values() for uid in group})))).all())
    return [{'id': str(item.id), 'start_date': rules.iso(item.start_date), 'due_date': rules.iso(item.due_date),
             'owners': sorted(map(str, owners[item.id])), 'people': ', '.join(names.get(uid) or str(uid) for uid in sorted(owners[item.id], key=str)),
             'active': item.is_active, 'status': str(getattr(item.status, 'value', item.status)), 'title': item.title} for item in tasks]


def payload(request, requester, approver=None):
    return {'id': str(request.id), 'question_id': str(request.question_id) if request.question_id else None, 'task_id': str(request.task_id),
            'status': request.status, 'status_label': rules.STATUS_LABELS[request.status], 'change_kind': request.change_kind,
            'original_tasks': request.original_tasks, 'proposed_dates': request.proposed_dates,
            'reason': REASON_LABELS[request.reason_code], 'comment': request.comment,
            'requester': requester.full_name or requester.username, 'decision_detail': request.decision_detail,
            'approver': approver.full_name if approver else 'Diellza Veliu'}


class Proposal(Actor):
    request_id: str = Field(pattern=r'^\d{1,32}$')
    change_kind: Literal['start', 'due', 'start_due']
    start_date: datetime | None = None
    due_date: datetime | None = None
    reason_code: str = Field(max_length=40)
    comment: str = Field(min_length=1, max_length=4000)


@router.post('/questions/{question_id}')
async def propose(question_id: uuid.UUID, value: Proposal, db: AsyncSession = Depends(get_db)):
    question, link, user = await own_question(db, question_id, value)
    if question.kind != 'continuation':
        raise HTTPException(422, 'Kërkesa duhet të bëhet nga pyetja e detyrës PM.')
    return await create_proposal(db, value, link, user, question.task_id, question)


@router.post('/tasks/{task_id}/open')
async def open_task(task_id: uuid.UUID, value: Actor, db: AsyncSession = Depends(get_db)):
    link, user = await identity(db, value)
    task = await task_owned(db, user.id, task_id)
    snapshots = await task_snapshots(db, task)
    rules.assert_snapshot_unchanged(snapshots, snapshots)
    pending = (await db.execute(select(Request.id).where(Request.task_id == task_id, Request.status == 'PENDING'))).first()
    if pending:
        raise HTTPException(409, 'Kjo detyrë ka tashmë një kërkesë në pritje të Diellzës.')
    return {'id': str(task_id), 'source': 'task', 'title': task.title,
        'live_dates': {'start_date': rules.iso(task.start_date), 'due_date': rules.iso(task.due_date)},
        'reasons': [{'value': key, 'label': label} for key, label in REASON_LABELS.items()]}


@router.post('/tasks/{task_id}')
async def propose_task(task_id: uuid.UUID, value: Proposal, db: AsyncSession = Depends(get_db)):
    link, user = await identity(db, value)
    return await create_proposal(db, value, link, user, task_id)


async def create_proposal(db, value, link, user, task_id, question=None, *, commit=True, expected_dates=None):
    duplicate = (await db.execute(select(Request).where(Request.request_id == value.request_id))).scalar_one_or_none()
    if duplicate:
        if duplicate.requester_link_id != link.id or duplicate.task_id != task_id:
            raise HTTPException(403, 'Kërkesë e një përdoruesi tjetër.')
        return payload(duplicate, user)
    # Serializes submissions from different owners of one shared task.
    await db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': int.from_bytes(hashlib.sha256(b'm2-proposal:' + task_id.bytes).digest()[:8], 'big', signed=True)})
    pending = (await db.execute(select(Request.id).where(Request.task_id == task_id, Request.status == 'PENDING'))).first()
    if pending:
        raise HTTPException(409, 'Kjo detyrë ka tashmë një kërkesë në pritje të Diellzës.')
    task = await task_owned(db, user.id, task_id)
    task = (await db.execute(select(Task).where(Task.id == task_id).with_for_update()
        .execution_options(populate_existing=True))).scalar_one()
    await task_owned(db, user.id, task_id)
    if expected_dates is not None and any(rules.iso(getattr(task, field)) != rules.iso(expected_dates.get(field))
                                          for field in ('start_date', 'due_date')):
        raise HTTPException(409, 'Datat ndryshuan ndërkohë. Hape përsëri formularin.')
    from app.services.m2_reporting_points import select_task_sections
    if question and not select_task_sections([task], [], question.day)['pm_continuation']:
        raise HTTPException(409, 'Detyra nuk është më në planin PM të sotëm.')
    approver, _ = await reviewer(db, link.guild_id)
    dates = {field: getattr(value, field) for field in ('start_date', 'due_date') if field in value.model_fields_set}
    proposed = rules.proposed_dates(task, value.change_kind, dates, value.reason_code, value.comment)
    snapshots = await task_snapshots(db, task)
    rules.assert_snapshot_unchanged(snapshots, snapshots)
    now = datetime.now(timezone.utc)
    request = Request(question_id=question.id if question else None, requester_link_id=link.id, task_id=task.id,
        day=question.day if question else datetime.now(report_timezone()).date(),
        approver_user_id=approver.id, request_id=value.request_id, change_kind=value.change_kind,
        proposed_dates=proposed, original_tasks=snapshots, reason_code=value.reason_code,
        comment=value.comment.strip(), status='PENDING', lease_until=now)
    db.add(request)
    await db.flush()
    add_audit_log(db=db, actor_user_id=user.id, entity_type='task', entity_id=task.id,
        action='task.m2_postponement_requested', after={'request_id': str(request.id), 'proposed_dates': proposed,
            'reason_code': value.reason_code, 'comment': request.comment, 'status': 'PENDING'})
    if commit:
        await db.commit()
    return payload(request, user, approver)


class Decision(Actor):
    decision: Literal['APPROVED', 'REJECTED']


@router.post('/{request_id}/decision')
async def decide(request_id: uuid.UUID, value: Decision, db: AsyncSession = Depends(get_db)):
    link, approver = await identity(db, value, lock=True)
    request = (await db.execute(select(Request).where(Request.id == request_id).with_for_update())).scalar_one_or_none()
    if not request or request.approver_user_id != approver.id or approver.username != rules.APPROVER_USERNAME:
        raise HTTPException(403, 'Vetëm Diellza Veliu mund ta vendosë këtë kërkesë.')
    requester_link = await db.get(DiscordLink, request.requester_link_id)
    if requester_link.guild_id != link.guild_id:
        raise HTTPException(403, 'Serveri nuk përputhet.')
    requester = await db.get(User, requester_link.user_id)
    requester_id, approver_id = requester.id, approver.id
    if request.status != 'PENDING':
        return payload(request, requester, approver)
    now = datetime.now(timezone.utc)

    def finish(status, detail=None):
        request.status, request.decided_at, request.decided_by = status, now, approver_id
        request.decision_detail, request.lease_until = detail, now
        add_audit_log(db=db, actor_user_id=approver_id, entity_type='task', entity_id=request.task_id,
            action='task.m2_postponement_decided', after={'request_id': str(request.id), 'status': status, 'detail': detail})

    if value.decision == 'REJECTED':
        finish('REJECTED')
        await db.commit()
        return payload(request, requester, approver)
    if (request.question_id and request.day != datetime.now(report_timezone()).date()) or not requester_link.enabled or not requester.is_active:
        finish('STALE', 'Dita ose lidhja e kërkuesit ka ndryshuar.')
        await db.commit()
        return payload(request, requester, approver)
    from app.api.routers.tasks import update_task_in_session
    from app.schemas.task import TaskUpdate

    async def check(locked_task):
        await task_owned(db, requester.id, request.task_id)
        rules.assert_snapshot_unchanged(request.original_tasks, await task_snapshots(db, locked_task))

    async def commit_decision(task):
        finish('APPROVED')
        # Normal date edits create realization adjustments. This decision already
        # authorizes those new events; do not leave them waiting for approval again.
        affected = {uuid.UUID(row['id']) for row in request.original_tasks}
        await db.flush()
        events = select(AuditLog.id).where(AuditLog.entity_id.in_(affected), AuditLog.actor_user_id == approver_id,
            AuditLog.created_at >= now, AuditLog.action.in_(['task.start_date_changed', 'task.due_date_changed']))
        adjustments = (await db.execute(select(DailyPlanAdjustment).where(DailyPlanAdjustment.audit_event_id.in_(events)))).scalars().all()
        for item in adjustments:
            item.status, item.decided_by, item.decided_at = 'APPROVED', approver_id, now
            item.decision_comment = f'Discord M2: {request.id}'
    try:
        await update_task_in_session(request.task_id, TaskUpdate(**request.proposed_dates,
            postponement_reason_code=request.reason_code, postponement_comment=request.comment), db, approver,
            before_update=check, before_commit=commit_decision, return_dto=False)
    except HTTPException as exc:
        is_stale = exc.status_code in {403, 404} or (isinstance(exc.detail, dict) and exc.detail.get('code') == 'M2_POSTPONEMENT_STALE')
        await db.rollback()
        if not is_stale:
            raise
        # The failed normal edit rolls back completely before recording a stale proposal.
        request = (await db.execute(select(Request).where(Request.id == request_id).with_for_update())).scalar_one()
        if request.status == 'PENDING':
            finish('STALE', 'Detyra ose përgjegjësit ndryshuan ndërkohë. Datat nuk u ndryshuan nga kjo kërkesë.')
            await db.commit()
        requester = await db.get(User, requester_id)
        approver = await db.get(User, approver_id)
    if request.status == 'APPROVED':
        try:
            from app.services import m2_reporting_points as reports
            report = await reports.locked_report(db, datetime.now(report_timezone()).date())
            await reports.refresh_report(db, report)
            await db.commit()
        except Exception:
            import logging
            logging.getLogger(__name__).warning('M2 postponement approved; report refresh deferred: %s', request_id)
            await db.rollback()
            request = await db.get(Request, request_id)
            requester = await db.get(User, requester_id)
            approver = await db.get(User, approver_id)
    return payload(request, requester, approver)


@router.post('/claim')
async def claim_notifications(db: AsyncSession = Depends(get_db)):
    acquired = (await db.execute(text("SELECT pg_try_advisory_xact_lock(hashtext('discord-m2-approval-notifications'))"))).scalar()
    if not acquired:
        return {'jobs': []}
    now = datetime.now(timezone.utc)
    outstanding = or_(and_(Request.status == 'PENDING', Request.review_sent_at.is_(None)),
        and_(Request.status != 'PENDING', or_(Request.requester_notified_at.is_(None),
            and_(Request.review_message_id.is_not(None), Request.review_updated_at.is_(None)))))
    requests = (await db.execute(select(Request).where(Request.lease_until <= now, outstanding)
                                .order_by(Request.created_at).limit(200))).scalars().all()
    jobs = []
    for request in requests:
        requester_link = await db.get(DiscordLink, request.requester_link_id)
        if not requester_link or not requester_link.enabled or requester_link.guild_id != settings.DISCORD_GUILD_ID:
            continue
        requester = await db.get(User, requester_link.user_id)
        if not requester or not requester.is_active:
            continue
        if request.status == 'PENDING' and request.review_sent_at is None:
            role = 'review'
        elif request.status != 'PENDING' and request.requester_notified_at is None:
            role = 'requester'
        elif request.status != 'PENDING' and request.review_message_id and request.review_updated_at is None:
            role = 'review_update'
        else:
            continue
        if role.startswith('review'):
            try:
                approver, target = await reviewer(db, requester_link.guild_id)
            except HTTPException:
                continue
            if approver.id != request.approver_user_id:
                continue
            message_id = request.review_message_id
        else:
            target, approver = requester_link, await db.get(User, request.approver_user_id)
            try:
                await task_owned(db, requester.id, request.task_id)
            except HTTPException:
                request.requester_notified_at = now
                continue
            question = await db.get(DiscordM2Question, request.question_id) if request.question_id else None
            message_id = question.message_id if question else None
        job = payload(request, requester, approver)
        from app.models.discord_m3_question import DiscordM3Question
        m3_question = (await db.execute(select(DiscordM3Question).where(
            DiscordM3Question.link_id == request.requester_link_id, DiscordM3Question.task_id == request.task_id,
            DiscordM3Question.answer['postponement_id'].astext == str(request.id))
            .order_by(DiscordM3Question.answered_at.desc()).limit(1))).scalar_one_or_none()
        if m3_question:
            job['source'] = 'm3'
            if role == 'requester':
                from app.api.routers.discord_m3 import live_payload
                job['m3_question'] = await live_payload(db, m3_question, requester_link, requester)
                message_id = m3_question.message_id
        job.update(role=role, discord_user_id=target.discord_user_id, guild_id=target.guild_id,
                   channel_id=target.channel_id, message_id=message_id)
        if role == 'requester' and question:
            job['question'] = question_payload(question, requester_link)
            job['question']['postponement'] = {'id': str(request.id), 'status': request.status}
        request.lease_until = now + timedelta(minutes=2)
        jobs.append(job)
        if len(jobs) >= 20:
            break
    await db.commit()
    return {'jobs': jobs}


class NotificationReceipt(Actor):
    role: Literal['review', 'review_update', 'requester']
    message_id: str = Field(pattern=r'^\d{1,32}$')


@router.post('/{request_id}/ack')
async def acknowledge(request_id: uuid.UUID, value: NotificationReceipt, db: AsyncSession = Depends(get_db)):
    link, user = await identity(db, value, lock=True)
    request = (await db.execute(select(Request).where(Request.id == request_id).with_for_update())).scalar_one_or_none()
    if not request or (value.role.startswith('review') and request.approver_user_id != user.id) or (value.role == 'requester' and request.requester_link_id != link.id):
        raise HTTPException(403, 'Njoftimi nuk i përket këtij përdoruesi.')
    now = datetime.now(timezone.utc)
    if value.role == 'review':
        request.review_message_id, request.review_sent_at = value.message_id, now
    elif value.role == 'review_update':
        request.review_updated_at = now
    else:
        request.requester_notified_at = now
    request.lease_until = now
    await db.commit()
    return {'ok': True}
