from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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


def _reconciliation_range(now_utc: datetime) -> tuple[date, date]:
    start = now_utc.astimezone(ZoneInfo(settings.APP_TIMEZONE)).date()
    return start, start + timedelta(days=max(int(settings.SYSTEM_TASK_GENERATE_AHEAD_DAYS), 0))


async def generate_system_tasks() -> int:
    async with SessionLocal() as db:
        await cleanup_inactive_user_system_tasks(db)
        now_utc = datetime.now(timezone.utc)
        created = await generate_system_task_instances(db=db, now_utc=now_utc)
        created += await reconcile_external_meeting_system_tasks(db=db, now_utc=now_utc)
        created += await reconcile_tak_int_one_h_tasks(db=db, now_utc=now_utc)
        start, end = _reconciliation_range(now_utc)
        await reconcile_system_task_assignments_in_range(
            db=db,
            start=start,
            end=end,
            now_utc=now_utc,
        )
        await db.commit()
    return created


async def pregenerate_system_tasks_today() -> int:
    return await generate_system_tasks()


async def reconcile_system_task_slots_daily() -> dict[str, int]:
    async with SessionLocal() as db:
        await cleanup_inactive_user_system_tasks(db)
        now_utc = datetime.now(timezone.utc)
        start, end = _reconciliation_range(now_utc)
        result = await reconcile_system_task_assignments_in_range(
            db=db,
            start=start,
            end=end,
            now_utc=now_utc,
        )
        await db.commit()
    return result
