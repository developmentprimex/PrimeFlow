from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.meeting import Meeting
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.models.task import Task
from app.services.meeting_occurrence import meeting_display_dates


async def delete_internal_meeting_tasks(
    db: AsyncSession, meeting: Meeting, occurrence_date: date,
) -> None:
    """Delete this internal meeting's generated tasks, preserving other meetings."""
    origins = [Task.meeting_origin_id == meeting.id]
    if meeting.pre_external_meeting_id:
        origins.append((Task.meeting_origin_id == meeting.pre_external_meeting_id)
                       & (Task.meeting_system_task_kind == "tak_int_pre_one_h"))
    if meeting.paired_external_meeting_id:
        origins.append((Task.meeting_origin_id == meeting.paired_external_meeting_id)
                       & (Task.meeting_system_task_kind == "tak_int_post_one_h"))
    statement = delete(Task).where(or_(*origins), Task.meeting_system_task_kind.is_not(None))
    if (meeting.recurrence_type or "").strip().lower() not in ("", "none"):
        statement = statement.where(Task.meeting_occurrence_date == occurrence_date)
    await db.execute(statement)


async def internal_meeting_task_is_canceled(
    db: AsyncSession, external_id: uuid.UUID, task_kind: str, task_date: date,
) -> bool:
    link = (Meeting.pre_external_meeting_id if task_kind == "tak_int_pre_one_h"
            else Meeting.paired_external_meeting_id)
    rows = (await db.execute(select(
        Meeting.starts_at, Meeting.created_at, Meeting.recurrence_type,
        MeetingOccurrenceStatus.occurrence_date,
    ).join(MeetingOccurrenceStatus, MeetingOccurrenceStatus.meeting_id == Meeting.id).where(
        Meeting.meeting_type == "internal", link == external_id,
        MeetingOccurrenceStatus.status == "canceled",
    ))).all()
    for starts_at, created_at, recurrence, canceled_date in rows:
        if (recurrence or "").strip().lower() not in ("", "none"):
            if canceled_date == task_date:
                return True
        elif canceled_date in meeting_display_dates(
            SimpleNamespace(meeting_type="internal", starts_at=starts_at, created_at=created_at),
            local_timezone=ZoneInfo(settings.APP_TIMEZONE),
        ):
            # Preparation / follow-up slots can be on a different day from
            # the actual one-time internal meeting.
            return True
    return False


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
