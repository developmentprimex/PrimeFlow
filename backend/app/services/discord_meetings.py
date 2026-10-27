"""Which meeting alerts are due for people who linked Discord.

Uses the same occurrence, due-window and cancellation rules as the browser
meeting reminders, so Discord never alerts for a meeting PrimeFlow would not.
"""
from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.jobs.reminders import _next_occurrence, _reminder_is_due
from app.models.meeting import Meeting, MeetingParticipant
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.models.user import User
from app.services.discord_m2 import collection_open
from app.services.meeting_occurrence import meeting_occurs_on_date

# After the meeting, participants are asked whether it was held or canceled.
AFTER_DEFAULT_MINUTES = 30
AFTER_WINDOW = timedelta(hours=2)
HELD_KINDS = ('after', 'm2_after')


def m2_recipients(assigned_ids, linked_ids, fallback_id):
    # An assigned person without Discord is not an unassigned meeting.
    targets = set(assigned_ids) if assigned_ids else {fallback_id} if fallback_id else set()
    return sorted(targets & set(linked_ids), key=str)


def m2_occurrence(meeting, current, local_timezone):
    if not collection_open(current) or meeting.meeting_type not in {'internal', 'external'}:
        return None
    held = held_question_at(meeting, current, local_timezone)
    if not held:
        return None
    occurrence, ends = held
    original_start = meeting.starts_at if meeting.starts_at.tzinfo else meeting.starts_at.replace(tzinfo=local_timezone)
    if original_start.astimezone(local_timezone).date() > current.astimezone(local_timezone).date():
        return None
    if meeting.ends_at is not None:
        original_end = meeting.ends_at if meeting.ends_at.tzinfo else meeting.ends_at.replace(tzinfo=local_timezone)
        if original_end > original_start:
            ends = occurrence + (original_end - original_start)
    # Do not ask about a meeting that has not finished yet, including an AM
    # meeting still in progress at the first collection tick.
    if occurrence.astimezone(local_timezone).hour >= 12 or ends > current:
        return None
    return occurrence.astimezone(timezone.utc)


async def m2_due_alerts(db, current, user_ids):
    if not user_ids or not collection_open(current):
        return []
    local_timezone = ZoneInfo(settings.APP_TIMEZONE)
    meetings = (await db.execute(select(Meeting).where(Meeting.starts_at.is_not(None),
        Meeting.meeting_type.in_(('internal', 'external')),
        or_(Meeting.calendar_sync_status.is_(None),
            Meeting.calendar_sync_status.notin_(('cancelled', 'excluded', 'out_of_window')))))).scalars().all()
    candidates = [(meeting, occurrence) for meeting in meetings
        if (occurrence := m2_occurrence(meeting, current, local_timezone)) is not None]
    if not candidates:
        return []
    ids = [meeting.id for meeting, _ in candidates]
    assigned = {}
    for meeting_id, user_id in (await db.execute(select(MeetingParticipant.meeting_id, MeetingParticipant.user_id).where(
        MeetingParticipant.meeting_id.in_(ids), MeetingParticipant.assignment_source == 'manual'))).all():
        assigned.setdefault(meeting_id, set()).add(user_id)
    fallback = (await db.execute(select(User.id).where(User.username == 'diellza.veliu', User.is_active.is_(True)))).scalar_one_or_none()
    statuses = dict((await db.execute(select(MeetingOccurrenceStatus.meeting_id, MeetingOccurrenceStatus.status).where(
        MeetingOccurrenceStatus.meeting_id.in_(ids),
        MeetingOccurrenceStatus.occurrence_date == current.astimezone(local_timezone).date()))).all())
    return [(meeting, user_id, occurrence, 'm2_after') for meeting, occurrence in candidates
        if not statuses.get(meeting.id)
        for user_id in m2_recipients(assigned.get(meeting.id, set()), user_ids, fallback)]


def held_question_at(meeting: Meeting, current: datetime, local_timezone: ZoneInfo) -> tuple[datetime, datetime] | None:
    """(occurrence, ask_at) for today's occurrence that has already started; asked when it ends."""
    if meeting.starts_at is None:
        return None
    starts_at = meeting.starts_at if meeting.starts_at.tzinfo else meeting.starts_at.replace(tzinfo=local_timezone)
    today = current.astimezone(local_timezone).date()
    if (meeting.recurrence_type or "").strip().lower() in {"weekly", "monthly", "yearly"}:
        if not meeting_occurs_on_date(meeting, today, local_timezone=local_timezone):
            return None
        local_start = starts_at.astimezone(local_timezone)
        occurrence = datetime.combine(today, time(local_start.hour, local_start.minute), tzinfo=local_timezone)
    elif starts_at.astimezone(local_timezone).date() == today:
        occurrence = starts_at
    else:
        return None
    minutes = AFTER_DEFAULT_MINUTES
    if meeting.ends_at is not None:
        ends_at = meeting.ends_at if meeting.ends_at.tzinfo else meeting.ends_at.replace(tzinfo=local_timezone)
        length = int((ends_at - starts_at).total_seconds() // 60)
        if 5 <= length <= 240:
            minutes = length
    return occurrence, occurrence + timedelta(minutes=minutes)


async def due_alerts(db: AsyncSession, current: datetime, user_ids: list[uuid.UUID]) -> list[tuple[Meeting, uuid.UUID, datetime, str]]:
    """Return (meeting, user_id, occurrence, kind); kind is "before", "start" or "after"."""
    if not user_ids:
        return []
    local_timezone = ZoneInfo(settings.APP_TIMEZONE)
    rows = (await db.execute(select(Meeting, MeetingParticipant.user_id)
        .join(MeetingParticipant, MeetingParticipant.meeting_id == Meeting.id)
        .where(MeetingParticipant.assignment_source == "manual", MeetingParticipant.user_id.in_(user_ids),
               Meeting.reminder_minutes_before.is_not(None),
               or_(Meeting.calendar_sync_status.is_(None),
                   Meeting.calendar_sync_status.notin_(("cancelled", "excluded", "out_of_window")))))).all()
    due = []
    for meeting, user_id in rows:
        occurrence = _next_occurrence(meeting, current, local_timezone)
        if occurrence is None:
            continue
        minutes = int(meeting.reminder_minutes_before or 0)
        internal = meeting.meeting_type == "internal"
        # Internal meetings also call everyone when they start; then the
        # "starts in N minutes" alert is no longer useful.
        if minutes > 0 and _reminder_is_due(occurrence=occurrence, current=current, minutes_before=minutes) \
                and not (internal and current >= occurrence):
            due.append((meeting, user_id, occurrence, "before"))
        if (internal or minutes == 0) and _reminder_is_due(occurrence=occurrence, current=current, minutes_before=0):
            due.append((meeting, user_id, occurrence, "start"))
        held = held_question_at(meeting, current, local_timezone)
        if held and held[1] <= current < held[1] + AFTER_WINDOW:
            due.append((meeting, user_id, held[0].astimezone(timezone.utc), "after"))
    if not due:
        return []
    statuses = {(meeting_id, day): value for meeting_id, day, value in (await db.execute(
        select(MeetingOccurrenceStatus.meeting_id, MeetingOccurrenceStatus.occurrence_date, MeetingOccurrenceStatus.status).where(
            MeetingOccurrenceStatus.meeting_id.in_({item[0].id for item in due}),
            MeetingOccurrenceStatus.occurrence_date.in_({item[2].astimezone(local_timezone).date() for item in due})))).all()}

    def wanted(item) -> bool:
        status = statuses.get((item[0].id, item[2].astimezone(local_timezone).date())) or ""
        # Nobody is asked about a meeting already marked in Common View.
        return not status if item[3] == "after" else status != "canceled"
    return [item for item in due if wanted(item)]
