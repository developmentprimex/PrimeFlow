"""Per-task interval counts for the live and archived 1H SHTYPI Today view."""
from __future__ import annotations

import re
import uuid
from collections import defaultdict
from datetime import date, datetime, time

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ga_note import GaNote
from app.models.plan_note import PlanNote
from app.models.task import Task
from app.models.task_strike_event import TaskStrikeEvent
from app.services.primeflow_report import report_timezone
from app.services.task_strike_events import count_struck_points_for_interval


def payload_task_ids(payload: dict) -> set[uuid.UUID]:
    ids = set()
    for bucket in (payload.get("items") or {}).values():
        if not isinstance(bucket, list):
            continue
        for item in bucket:
            if not isinstance(item, dict):
                continue
            try:
                ids.add(uuid.UUID(str(item.get("task_id") or item.get("taskId") or item.get("id"))))
            except (ValueError, TypeError):
                continue
    return ids


async def task_strike_summary(
    db: AsyncSession, day: date, task_ids: set[uuid.UUID], *, now: datetime | None = None,
    completed_through: datetime | None = None,
) -> dict:
    # Import at call time: delivery also imports the SHTYPI renderer.
    from app.services.primeflow_report_delivery import strike_interval_start, strike_interval_end

    now = now or datetime.now(report_timezone())
    slots = ("10:00", "11:00", "11:50", "14:20", "16:00")
    windows = {slot: (strike_interval_start(day, slot), strike_interval_end(day, slot)) for slot in slots}
    completed = {slot: window for slot, window in windows.items() if window[1] <= (completed_through or now)}
    active_slot = next(reversed(completed), None)
    active_interval = ({"start": completed[active_slot][0].strftime("%H:%M"),
                        "end": completed[active_slot][1].strftime("%H:%M")} if active_slot else None)
    summary = {
        "report_date": day.isoformat(), "captured_at": now.isoformat(), "active_slot": active_slot,
        "active_interval": active_interval,
        "intervals": {slot: {"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")}
                      for slot, (start, end) in windows.items()},
        "tasks": {},
    }
    if not task_ids or not completed:
        return summary
    cutoff = min(completed[active_slot][1], now)
    rows = (await db.execute(select(
        Task.id, Task.title, Task.description, GaNote.content, PlanNote.content, TaskStrikeEvent,
    ).outerjoin(GaNote, Task.ga_note_origin_id == GaNote.id)
      .outerjoin(PlanNote, Task.plan_note_origin_id == PlanNote.id)
      .outerjoin(TaskStrikeEvent, and_(
          TaskStrikeEvent.task_id == Task.id,
          TaskStrikeEvent.occurred_at >= datetime.combine(day, time.min, report_timezone()),
          TaskStrikeEvent.occurred_at <= cutoff,
      )).where(Task.id.in_(task_ids))
      .order_by(Task.id, TaskStrikeEvent.occurred_at, TaskStrikeEvent.id))).all()
    events = defaultdict(list)
    texts = {}
    for task_id, title, description, ga_content, plan_content, event in rows:
        # Read the authoritative note/task text and events in the same query,
        # matching 1H Reports even across a concurrent task save.
        texts[task_id] = (ga_content or plan_content or title, description)
        if event is not None:
            events[task_id].append(event)
    for task_id, (title, description) in texts.items():
        summary["tasks"][str(task_id)] = {
            slot: sum(count_struck_points_for_interval(
                text, events[task_id], interval_start=start, interval_end=min(end, now), field_name=field,
            ) for text, field in ((title, "TITLE"), (description, "DESCRIPTION")))
            for slot, (start, end) in completed.items()
        }
    return summary


def report_task_ids(report: dict) -> set[uuid.UUID]:
    return {uuid.UUID(value) for value in re.findall(
        r'data-task-id="([0-9a-fA-F-]{36})"', report.get("html") or "",
    )}


async def with_report_strikes(db: AsyncSession, report: dict, day: date) -> dict:
    ids = report_task_ids(report)
    return {**report, "one_h_strikes": await task_strike_summary(db, day, ids)}
