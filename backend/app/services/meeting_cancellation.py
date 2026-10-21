from __future__ import annotations

from zoneinfo import ZoneInfo

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.meeting import Meeting
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.models.task import Task
from app.services.meeting_occurrence import meeting_display_dates


async def external_meeting_is_canceled(db: AsyncSession, meeting: Meeting) -> bool:
    days = meeting_display_dates(meeting, local_timezone=ZoneInfo(settings.APP_TIMEZONE))
    if not days:
        return False
    return bool((await db.execute(select(MeetingOccurrenceStatus.id).where(
        MeetingOccurrenceStatus.meeting_id == meeting.id,
        MeetingOccurrenceStatus.occurrence_date.in_(days),
        MeetingOccurrenceStatus.status == "canceled",
    ).limit(1))).scalar_one_or_none())


async def delete_external_meeting_dependents(db: AsyncSession, meeting: Meeting) -> None:
    """Remove generated work while retaining the external meeting and its status."""
    linked_ids = list((await db.execute(select(Meeting.id).where(
        Meeting.meeting_type == "internal",
        or_(Meeting.pre_external_meeting_id == meeting.id,
            Meeting.paired_external_meeting_id == meeting.id),
    ))).scalars().all())
    # Preparation/follow-up tasks use the external ID even when scheduled on
    # another day. Delete only generated tasks, leaving manually entered work.
    await db.execute(delete(Task).where(
        Task.meeting_origin_id.in_([meeting.id, *linked_ids]),
        Task.meeting_system_task_kind.is_not(None),
    ))
    if linked_ids:
        await db.execute(delete(Meeting).where(Meeting.id.in_(linked_ids)))
