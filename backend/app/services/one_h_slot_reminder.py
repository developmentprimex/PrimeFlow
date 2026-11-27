import logging
from datetime import date, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Header, HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TaskFinishPeriod, TaskStatus
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.services.one_h_slots import current_effective_slot_date
from app.services.task_date_window import common_view_task_date_window_filter
from app.services.task_pause import pause_until_on_day


HEADER = "X-PrimeFlow-One-H-Slot-Reminder"
SlotReminderHeader = Annotated[str | None, Header(alias=HEADER)]
CODE = "ONE_H_PM_BLOCK_REMINDER"
ALTERNATIVE_SLOTS = ("10:00", "11:00", "11:50", "14:20")
MESSAGE = (
    "Përgjegjësi ka detyrë Bllok PM për të njëjtën ditë. "
    "Për shkak të Bllokut PM, mos cakto slotin 16:00 për detyrën 1H. "
    "Nëse zgjedh të vazhdosh, sloti 16:00 do të ruhet."
)
logger = logging.getLogger(__name__)


async def has_pm_block(db: AsyncSession, day: date, owners: set[UUID]) -> bool:
    return bool(await pm_block_owners(db, day, owners))


async def pm_block_owners(db: AsyncSession, day: date, owners: set[UUID]) -> set[UUID]:
    if not owners:
        return set()

    from app.api.routers.common_view import _get_task_dates

    query = select(
        Task.start_date, Task.due_date, Task.created_at, Task.phase, Task.pause_periods,
        Task.assigned_to, TaskAssignee.user_id,
    ).select_from(Task).outerjoin(TaskAssignee, and_(TaskAssignee.task_id == Task.id, TaskAssignee.user_id.in_(owners))).where(
        Task.work_staff_filter(),
        Task.is_active.is_(True),
        Task.is_bllok.is_(True),
        Task.finish_period == TaskFinishPeriod.PM.value,
        Task.status.notin_([TaskStatus.DONE.value, TaskStatus.PAUSED.value]),
        Task.completed_at.is_(None),
        or_(Task.assigned_to.in_(owners), TaskAssignee.user_id.is_not(None)),
        # SQL compares stored dates. Confirm the workday below in app time.
        common_view_task_date_window_filter(day - timedelta(days=1), day + timedelta(days=1)),
    )
    try:
        async with db.begin_nested():
            blocks = (await db.execute(query)).all()
    except SQLAlchemyError:
        logger.warning("Could not check the 16:00 slot reminder", exc_info=True)
        return set()
    return {
        owner for task in blocks
        if day in _get_task_dates(task, (task.phase or "").upper() in {"CHECK", "CONTROL"})
        and not pause_until_on_day(task.pause_periods, day)
        for owner in (task.assigned_to, task.user_id)
        if owner in owners
    }


async def confirm_pm_block_slot(
    reminder: str | None, db: AsyncSession, day: date, owners: set[UUID], *,
    period: str | None = None, per_assignee: bool = False,
) -> None:
    if reminder != "ask":
        return
    affected = await pm_block_owners(db, day, owners)
    if not affected:
        return
    slots = ALTERNATIVE_SLOTS[-1:] if period == "PM" else (
        ALTERNATIVE_SLOTS[:-1] if period == "AM" else ALTERNATIVE_SLOTS
    )
    detail = {"code": CODE, "message": MESSAGE, "slots": slots}
    if per_assignee:
        detail["assignee_ids"] = [str(owner) for owner in sorted(affected)]
    raise HTTPException(409, detail=detail)


def scheduled_slot_day(task) -> date:
    from app.api.routers.common_view import _get_task_dates

    effective_day = current_effective_slot_date()
    dates = _get_task_dates(task, task.phase in {"CHECK", "CONTROL"})
    return next((scheduled for scheduled in dates if scheduled >= effective_day), dates[-1])


def note_slot_owners(
    tasks: list[Task], requested: set[UUID], already_at_16: set[UUID],
) -> set[UUID]:
    return {
        task.assigned_to for task in tasks
        if task.is_active and task.assigned_to in requested
        and task.id not in already_at_16
        and task.is_1h_report and not task.is_r1 and not task.is_bllok and task.one_h_report_slot == "16:00"
    }
