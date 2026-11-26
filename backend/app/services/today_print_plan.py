"""Save Tomorrow's task grid at 17:00 and compare it with the same day's Today grid."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models.one_h_print_report_snapshot import OneHPrintReportSnapshot
from app.models.task import Task
from app.services.one_h_print_report_snapshot import get_one_h_print_snapshot
from app.services.primeflow_report import report_timezone
from app.services.tomorrow_print_report import (
    _slot,
    _task_period_label,
    _task_rows,
    _task_status,
    _task_title,
    next_working_day,
)

logger = logging.getLogger(__name__)
PLAN_KIND = "TOMORROW_PLAN"
CAPTURE_TIME = time(16, 59, 59)
SAVE_TIME = time(17)


def capture_target(now: datetime) -> date | None:
    local = now.astimezone(report_timezone())
    if local.weekday() < 5 and CAPTURE_TIME <= local.time() < SAVE_TIME:
        return next_working_day(local.date())
    return None


def report_tasks(payload: dict, day: date, *, include_completed: bool = False) -> dict[str, dict]:
    rows = _task_rows(
        payload.get("items") or {}, day, include_completed_today=include_completed, users=payload.get("users"),
    )
    tasks = {}
    for section, items, _ in rows:
        for item in items:
            task_id = item.get("task_id") or item.get("taskId")
            if not task_id:
                continue
            task = tasks.setdefault(str(task_id), {
                "title": _task_title(item, personal=True),
                "slot": _slot(item),
                "period": _task_period_label(item),
                "assignees": sorted(set(item.get("assignees") or [item.get("person") or item.get("owner") or ""]) - {""}),
                "sections": [],
                "status": _task_status(item),
            })
            label = section.splitlines()[0]
            if label not in task["sections"]:
                task["sections"].append(label)
    return tasks


def compare_tasks(planned: dict, actual: dict, absent: dict) -> list[dict]:
    changes = []
    for task_id, before in planned.items():
        after = actual.get(task_id)
        evidence = absent.get(task_id, {"kind": "missing"})
        if after is None:
            changes.append({"task_id": task_id, "before": before, "after": None, **evidence})
        elif after["status"] == "DONE":
            changes.append({"task_id": task_id, "before": before, "after": after, "kind": "completed"})
        elif any(before[field] != after[field] for field in ("slot", "period", "assignees", "sections")):
            changes.append({"task_id": task_id, "before": before, "after": after, "kind": "changed"})
    changes.extend(
        {"task_id": task_id, "before": None, "after": after, "kind": "added"}
        for task_id, after in actual.items() if task_id not in planned
    )
    return changes


async def compare_plan(db: AsyncSession, day: date, plan: OneHPrintReportSnapshot, payload: dict) -> dict:
    from app.api.routers.common_view import _as_tirane_date, _get_task_dates

    planned = plan.report_payload["tasks"]
    actual = report_tasks(payload, day, include_completed=True)
    absent = {}
    missing_ids = [UUID(task_id) for task_id in planned.keys() - actual.keys()]
    if missing_ids:
        tasks = (await db.execute(select(Task).where(
            Task.id.in_(missing_ids), Task.is_active.is_(True), Task.work_staff_filter(),
        ))).scalars()
        for task in tasks:
            if task.status == "DONE":
                if _as_tirane_date(task.completed_at) == day:
                    absent[str(task.id)] = {"kind": "completed"}
                continue
            dates = _get_task_dates(task, (task.phase or "").upper() in {"CHECK", "CONTROL"})
            if day not in dates:
                absent[str(task.id)] = {
                    "kind": "rescheduled",
                    "date": min(dates, key=lambda scheduled: abs(scheduled - day)).isoformat(),
                }
    return {"saved_at": plan.report_payload["saved_at"], "changes": compare_tasks(planned, actual, absent)}


async def capture_tomorrow_plan(capture_at: datetime) -> bool:
    from app.api.routers.common_view import load_report_common_view_with_previous_week

    async with SessionLocal() as db:
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        await asyncio.sleep(max(0, (capture_at - datetime.now(report_timezone())).total_seconds()))
        started_at = datetime.now(report_timezone())
        target = capture_target(started_at)
        if target is None:
            return False
        locked = (await db.execute(text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
                                   {"key": f"tomorrow_plan|{target}"})).scalar()
        captured_at = datetime.now(report_timezone())
        if not locked or capture_target(captured_at) != target:
            return False
        if await get_one_h_print_snapshot(db, PLAN_KIND, target) is not None:
            return False
        payload = await load_report_common_view_with_previous_week(db, target)
        db.add(OneHPrintReportSnapshot(
            report_kind=PLAN_KIND, report_date=target, target_date=target,
            report_payload={
                "saved_at": datetime.combine(captured_at.date(), SAVE_TIME, report_timezone()).isoformat(),
                "source_captured_at": captured_at.isoformat(),
                "tasks": report_tasks(payload, target),
            },
        ))
        await db.commit()
        return True


async def run_tomorrow_plan_scheduler_forever() -> None:
    while True:
        now = datetime.now(report_timezone())
        day = now.date()
        if day.weekday() >= 5 or now.time() >= SAVE_TIME:
            day = next_working_day(day)
        capture_at = datetime.combine(day, CAPTURE_TIME, report_timezone())
        prepare_in = (capture_at - now).total_seconds() - 4
        if prepare_in > 0:
            await asyncio.sleep(min(60, prepare_in))
            continue
        try:
            if await capture_tomorrow_plan(capture_at):
                logger.info("tomorrow_plan_saved target_date=%s", next_working_day(day))
        except Exception:
            logger.exception("tomorrow_plan_capture_failed source_date=%s", day)
        boundary = datetime.combine(day, SAVE_TIME, report_timezone())
        await asyncio.sleep(max(0, (boundary - datetime.now(report_timezone())).total_seconds()))
