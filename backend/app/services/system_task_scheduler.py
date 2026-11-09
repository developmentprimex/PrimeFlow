from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings
from app.db import SessionLocal
from app.services.inactive_system_tasks import cleanup_inactive_user_system_tasks
from app.services.meeting_system_tasks import (
    reconcile_external_meeting_system_tasks,
    reconcile_tak_int_one_h_tasks,
)
from app.services.system_task_instances import (
    generate_system_task_instances,
    reconcile_system_task_assignments_in_range,
)


logger = logging.getLogger(__name__)

_WEEKDAY_MAP = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


def scheduler_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.APP_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def scheduler_run_time() -> time:
    return time(
        hour=max(0, min(int(settings.SYSTEM_TASK_SCHEDULER_HOUR), 23)),
        minute=max(0, min(int(settings.SYSTEM_TASK_SCHEDULER_MINUTE), 59)),
    )


def scheduler_weekday() -> int:
    value = (settings.SYSTEM_TASK_SCHEDULER_DAY_OF_WEEK or "fri").strip().lower()[:3]
    return _WEEKDAY_MAP.get(value, _WEEKDAY_MAP["fri"])


def daily_reconciliation_run_time() -> time:
    return time(
        hour=max(0, min(int(settings.SYSTEM_TASK_DAILY_RECONCILE_HOUR), 23)),
        minute=max(0, min(int(settings.SYSTEM_TASK_DAILY_RECONCILE_MINUTE), 59)),
    )


def next_scheduler_run_after(now_utc: datetime) -> datetime:
    tz = scheduler_timezone()
    local_now = now_utc.astimezone(tz)
    scheduled_weekday = scheduler_weekday()
    days_until_run = (scheduled_weekday - local_now.weekday()) % 7
    scheduled_date = local_now.date() + timedelta(days=days_until_run)
    scheduled_dt = datetime.combine(scheduled_date, scheduler_run_time(), tzinfo=tz)
    if local_now < scheduled_dt:
        return scheduled_dt.astimezone(timezone.utc)
    return (scheduled_dt + timedelta(days=7)).astimezone(timezone.utc)


def next_daily_reconciliation_after(now_utc: datetime) -> datetime:
    tz = scheduler_timezone()
    local_now = now_utc.astimezone(tz)
    scheduled_dt = datetime.combine(local_now.date(), daily_reconciliation_run_time(), tzinfo=tz)
    if local_now < scheduled_dt:
        return scheduled_dt.astimezone(timezone.utc)
    return (scheduled_dt + timedelta(days=1)).astimezone(timezone.utc)


async def run_system_task_scheduler_once(now_utc: datetime | None = None) -> int:
    now_utc = now_utc or datetime.now(timezone.utc)
    async with SessionLocal() as db:
        await cleanup_inactive_user_system_tasks(db)
        created = await generate_system_task_instances(db=db, now_utc=now_utc)
        created += await reconcile_external_meeting_system_tasks(db=db, now_utc=now_utc)
        created += await reconcile_tak_int_one_h_tasks(db=db, now_utc=now_utc)
        start = now_utc.astimezone(scheduler_timezone()).date()
        reconciliation = await reconcile_system_task_assignments_in_range(
            db=db,
            start=start,
            end=start + timedelta(days=max(int(settings.SYSTEM_TASK_GENERATE_AHEAD_DAYS), 0)),
            now_utc=now_utc,
        )
        await db.commit()
    logger.info(
        "System task scheduler created %s task(s); PV/ZV reconciliation: %s",
        created,
        reconciliation,
    )
    return created


async def run_system_task_daily_reconciliation_once(
    now_utc: datetime | None = None,
) -> dict[str, int]:
    now_utc = now_utc or datetime.now(timezone.utc)
    async with SessionLocal() as db:
        await cleanup_inactive_user_system_tasks(db)
        start = now_utc.astimezone(scheduler_timezone()).date()
        result = await reconcile_system_task_assignments_in_range(
            db=db,
            start=start,
            end=start + timedelta(days=max(int(settings.SYSTEM_TASK_GENERATE_AHEAD_DAYS), 0)),
            now_utc=now_utc,
        )
        await db.commit()
    logger.info("System task rolling PV/ZV reconciliation: %s", result)
    return result


async def run_system_task_scheduler_forever() -> None:
    if not settings.SYSTEM_TASK_SCHEDULER_ENABLED:
        logger.info("System task scheduler is disabled")
        return

    tz = scheduler_timezone()
    now_utc = datetime.now(timezone.utc)
    local_now = now_utc.astimezone(tz)
    if (
        local_now.weekday() == scheduler_weekday()
        and local_now.time() >= scheduler_run_time()
    ):
        await run_system_task_scheduler_once(now_utc=now_utc)

    while True:
        now_utc = datetime.now(timezone.utc)
        next_run_utc = next_scheduler_run_after(now_utc)
        sleep_seconds = max((next_run_utc - now_utc).total_seconds(), 1)
        await asyncio.sleep(sleep_seconds)
        await run_system_task_scheduler_once()


async def run_system_task_daily_reconciliation_forever() -> None:
    if not settings.SYSTEM_TASK_SCHEDULER_ENABLED:
        logger.info("System task daily PV/ZV reconciliation is disabled")
        return

    tz = scheduler_timezone()
    now_utc = datetime.now(timezone.utc)
    local_now = now_utc.astimezone(tz)
    if local_now.time() >= daily_reconciliation_run_time():
        await run_system_task_daily_reconciliation_once(now_utc=now_utc)

    while True:
        now_utc = datetime.now(timezone.utc)
        next_run_utc = next_daily_reconciliation_after(now_utc)
        sleep_seconds = max((next_run_utc - now_utc).total_seconds(), 1)
        await asyncio.sleep(sleep_seconds)
        await run_system_task_daily_reconciliation_once()
