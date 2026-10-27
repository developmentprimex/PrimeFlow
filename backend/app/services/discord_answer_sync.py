"""Reconcile existing Discord questions with answers saved in PrimeFlow."""
from datetime import datetime, timezone
import hashlib
import json
from sqlalchemy import select
from app.models.discord_assistant import DiscordMeetingAlert, DiscordLink
from app.models.discord_m2_question import DiscordM2Question
from app.models.discord_m2_postponement import DiscordM2Postponement
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_daily_rlz_state import TaskDailyRlzState
from app.models.meeting import Meeting
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.models.user import User
from app.services.primeflow_report import report_timezone
from app.services.daily_realization_events import semantic_local_day

MODELS = {'m2': DiscordM2Question, 'meeting': DiscordMeetingAlert}
PREFIXES = {'delivery': ('delivery_choice', 'delivery'), 'continuation': ('pm_choice', 'pm_comment'),
    'unfinished': (None, 'unfinished_comment'), 'progress': (None, 'progress_comment')}


async def capture_report_changes(db, report, before, submitted, *, changed_at=None):
    """Only explicit changes to actual answer columns close a question.

    Postponed_comment is the independent manual report note and never counts
    as the employee's explanation of a date change.
    """
    changed = {key for key, value in submitted.items() if value != before.get(key, '')}
    if not changed:
        return
    questions = (await db.execute(select(DiscordM2Question).where(DiscordM2Question.day == report.report_date))).scalars().all()
    now = changed_at or datetime.now(timezone.utc)
    answers = report.manual_answers or {}
    for question in questions:
        if question.platform_answered_at and question.platform_answered_at > now:
            continue
        if question.kind not in PREFIXES:
            continue
        choice_prefix, comment_prefix = PREFIXES[question.kind]
        choice_key = f'{choice_prefix}:{question.task_id}' if choice_prefix else None
        comment_key = f'{comment_prefix}:{question.task_id}'
        reason_key = f'{question.kind}_reason:{question.task_id}'
        if not changed.intersection({choice_key, comment_key, reason_key}):
            continue
        question.platform_answer = {'choice': answers.get(choice_key) if choice_key else None,
            'comment': answers.get(comment_key, ''), 'reason_code': answers.get(reason_key)}
        question.platform_answered_at = now


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


async def m2_payload(db, question, link):
    from app.api.routers.discord_m2 import question_payload
    result = question_payload(question, link)
    task = await db.get(Task, question.task_id)
    status = ''
    if not task or not task.is_active:
        status = 'Detyra nuk është më aktive në PrimeFlow.'
    else:
        owned = task.assigned_to == link.user_id or (await db.execute(select(TaskAssignee.task_id).where(
            TaskAssignee.task_id == task.id, TaskAssignee.user_id == link.user_id))).first()
        if not owned:
            status = 'Përgjegjësit e detyrës ndryshuan në PrimeFlow.'
        elif str(getattr(task.status, 'value', task.status)) == 'DONE':
            status = 'Detyra u përfundua në PrimeFlow.'
        elif question.kind in {'unfinished', 'progress', 'postponed'}:
            state = (await db.execute(select(TaskDailyRlzState).where(TaskDailyRlzState.task_id == task.id,
                TaskDailyRlzState.user_id == link.user_id, TaskDailyRlzState.day_date == question.day))).scalar_one_or_none()
            stamp = max(value for value in (question.sent_at, question.answered_at) if value) if question.sent_at else question.answered_at
            if state and state.reason_code and (state.comment or '').strip() and (not stamp or state.updated_at > stamp):
                status = 'Arsyeja dhe komenti u plotësuan në PrimeFlow.'
            if question.kind == 'postponed' and any(
                question.snapshot.get(field) and str(semantic_local_day(getattr(task, field))) != question.snapshot[field]
                for field in ('start_date', 'due_date')):
                status = 'Datat ndryshuan në PrimeFlow; kjo pyetje nuk është më aktive.'
    if status:
        result['platform_status'] = status
    if question.kind == 'continuation':
        request = (await db.execute(select(DiscordM2Postponement).where(DiscordM2Postponement.question_id == question.id)
            .order_by(DiscordM2Postponement.created_at.desc()).limit(1))).scalar_one_or_none()
        if request:
            result['postponement'] = {'id': str(request.id), 'status': request.status}
    return result


async def meeting_payload(db, alert, link):
    day = alert.occurrence_starts_at.astimezone(report_timezone()).date()
    status = (await db.execute(select(MeetingOccurrenceStatus).where(
        MeetingOccurrenceStatus.meeting_id == alert.meeting_id, MeetingOccurrenceStatus.occurrence_date == day))).scalar_one_or_none()
    meeting = await db.get(Meeting, alert.meeting_id)
    if not meeting:
        return None
    checked_by = await db.get(User, status.checked_by_user_id) if status and status.checked_by_user_id else None
    return {'id': str(alert.id), 'kind': alert.kind, 'discord_user_id': link.discord_user_id,
        'status': status.status if status else '', 'by': (checked_by.full_name or checked_by.username) if checked_by else 'PrimeFlow',
        'meeting': {'id': str(meeting.id), 'title': meeting.title, 'starts_at': alert.occurrence_starts_at.isoformat(),
            'type': meeting.meeting_type, 'platform': meeting.platform, 'url': meeting.meeting_url}}


async def make_job(db, kind, source, link):
    payload = await m2_payload(db, source, link) if kind == 'm2' else await meeting_payload(db, source, link)
    if payload is None:
        return None
    changed_on_platform = bool(payload.get('platform_status')) if kind == 'm2' else bool(payload.get('status'))
    # Leave unanswered task cards/wizards alone until a platform change matters.
    if not changed_on_platform and not source.sync_hash:
        return None
    digest = fingerprint(payload)
    return {'id': str(source.id), 'source': kind, 'fingerprint': digest,
        'discord_user_id': link.discord_user_id, 'guild_id': link.guild_id, 'channel_id': link.channel_id,
        'message_id': source.message_id, 'payload': payload}
