from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TaskStatus
from app.models.task_daily_progress import TaskDailyProgress


def _derive_daily_status(
    *,
    old_completed: int,
    new_completed: int,
    total: int,
) -> TaskStatus:
    if total <= 0:
        return TaskStatus.TODO
    if new_completed <= 0:
        return TaskStatus.TODO
    if new_completed >= total:
        return TaskStatus.DONE
    return TaskStatus.IN_PROGRESS


async def upsert_task_daily_progress(
    db: AsyncSession,
    *,
    task_id: uuid.UUID,
    day_date: date,
    old_completed: int,
    new_completed: int,
    total: int,
    finish_period: str | None = None,
    explicit_status: TaskStatus | None = None,
) -> None:
    # Use explicit_status if provided, otherwise derive from products
    if explicit_status is not None:
        status = explicit_status
    else:
        status = _derive_daily_status(old_completed=old_completed, new_completed=new_completed, total=total)
    
    delta = new_completed - old_completed
    delta_positive = delta if delta > 0 else 0
    finish_period_value = finish_period if finish_period in {"AM", "PM", "ALL"} else "ALL"

    existing = (
        await db.execute(
            select(TaskDailyProgress).where(
                TaskDailyProgress.task_id == task_id,
                TaskDailyProgress.day_date == day_date,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        db.add(
            TaskDailyProgress(
                task_id=task_id,
                day_date=day_date,
                completed_value=max(0, new_completed),
                total_value=max(0, total),
                completed_delta=max(0, delta_positive),
                daily_status=status.value,
                finish_period=finish_period_value,
            )
        )
        return

    existing.completed_value = max(0, new_completed)
    existing.total_value = max(0, total)
    if delta_positive:
        existing.completed_delta = max(0, (existing.completed_delta or 0) + delta_positive)
    # Only update daily_status if explicit_status is provided, or when product counts
    # drive a new derived status. Preserve explicit waiting states until they are
    # explicitly resolved by the user.
    if explicit_status is not None:
        existing.daily_status = status.value
    elif (existing.daily_status or "").upper() not in {
        TaskStatus.PAUSED.value,
        TaskStatus.WAITING_CLIENT.value,
        TaskStatus.WAITING_CONFIRMATION.value,
    }:
        existing.daily_status = status.value
    existing.finish_period = finish_period_value


async def upsert_explicit_task_daily_status(
    db: AsyncSession,
    *,
    task_id: uuid.UUID,
    day_date: date,
    status: TaskStatus,
    finish_period: str | None = None,
    finish_period_is_set: bool = False,
) -> None:
    """Keep the planner's per-day status aligned with an explicit task status change.

    Status changes made outside the main task PATCH endpoint (for example through
    the GA/PX note bundle editor) must update the same daily row used by Weekly
    Planner. Existing product counters are intentionally preserved.
    """

    finish_period_value = finish_period if finish_period in {"AM", "PM", "ALL"} else "ALL"
    existing = (
        await db.execute(
            select(TaskDailyProgress).where(
                TaskDailyProgress.task_id == task_id,
                TaskDailyProgress.day_date == day_date,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        db.add(
            TaskDailyProgress(
                task_id=task_id,
                day_date=day_date,
                completed_value=0,
                total_value=0,
                completed_delta=0,
                daily_status=status.value,
                finish_period=finish_period_value,
            )
        )
        return

    existing.daily_status = status.value
    if existing.finish_period is None or finish_period_is_set:
        existing.finish_period = finish_period_value


async def sync_task_daily_finish_period(
    db: AsyncSession,
    *,
    task_id: uuid.UUID,
    day_date: date,
    finish_period: str | None,
) -> None:
    """Move an existing daily row to the edited period without changing progress."""
    existing = (
        await db.execute(
            select(TaskDailyProgress).where(
                TaskDailyProgress.task_id == task_id,
                TaskDailyProgress.day_date == day_date,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.finish_period = finish_period if finish_period in {"AM", "PM", "ALL"} else "ALL"
