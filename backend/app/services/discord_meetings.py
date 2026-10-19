"""Which meeting alerts are due for people who linked Discord.

Uses the same occurrence, due-window and cancellation rules as the browser
meeting reminders, so Discord never alerts for a meeting PrimeFlow would not.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.jobs.reminders import _next_occurrence, _reminder_is_due
from app.models.meeting import Meeting, MeetingParticipant
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus


async def due_alerts(db: AsyncSession, current: datetime, user_ids: list[uuid.UUID]) -> list[tuple[Meeting, uuid.UUID, datetime, str]]:
    """Return (meeting, user_id, occurrence, kind); kind is "before" or "start"."""
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
    if not due:
        return []
    canceled = set((await db.execute(select(MeetingOccurrenceStatus.meeting_id, MeetingOccurrenceStatus.occurrence_date).where(
        MeetingOccurrenceStatus.meeting_id.in_({item[0].id for item in due}),
        MeetingOccurrenceStatus.occurrence_date.in_({item[2].astimezone(local_timezone).date() for item in due}),
        MeetingOccurrenceStatus.status == "canceled"))).all())
    return [item for item in due if (item[0].id, item[2].astimezone(local_timezone).date()) not in canceled]
