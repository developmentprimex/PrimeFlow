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
from app.services.meeting_occurrence import meeting_occurs_on_date

# After the meeting, participants are asked whether it was held or canceled.
AFTER_DEFAULT_MINUTES = 30
AFTER_WINDOW = timedelta(hours=2)


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
