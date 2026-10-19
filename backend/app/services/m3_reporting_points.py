from __future__ import annotations

import html
import asyncio
import uuid
from types import SimpleNamespace
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.department import Department
from app.models.m3_reporting_points import M3ReportingPointsReport
from app.models.project import Project
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_daily_progress import TaskDailyProgress
from app.models.task_daily_rlz_state import TaskDailyRlzState
from app.models.user import User
from app.services.daily_realization_events import semantic_local_day
from app.services.daily_realization_live import build_live_daily_realization
from app.services.daily_realization_metrics import combine_daily_metrics
from app.services.daily_rlz_compliance import REASON_LABELS
from app.services.meetings_report import (
    _clean_task_title, _initials, _local_time, _m3_am_pm_label, _m3_department_label,
    _m3_task_type_label, _task_owners, apply_weekly_planner_task_order,
    common_view_task_sort_key, _render_table_cell_html,
)
from app.services.m3_unheld_meetings import (
    MEETING_COLUMNS, MEETING_TITLE, add_saved_meeting_appearance, build_unheld_meetings,
    meeting_cells, meeting_groups, meeting_values,
)
from app.services.meetings_report_scheduler import normalize_recipients
from app.services.primeflow_report import GmailService, report_timezone
from app.services.tomorrow_print_report import STATUS_COLORS
from app.services.task_title_rules import title_has_eight_am_indicator
from app.services.task_marker import active_one_h_marker, active_one_h_marker_by_ga, one_h_marker_label

M3_TITLE = "PIKAT PER RAPORTIM M3"
GA_TITLE = "PIKAT PER RAPORTIM PER GA"
MANUAL_POINTS = {
    "underload": "1. NENNGARKESE",
    "overload": "2. MBINGARKESE",
    "reorganization": "3. RIORGANIZIM NESER?",
    "ga_reorganization": "1. A KA NEVOJE PER RIORGANIZIM?",
}
AUTO_TITLES = {
    "postponed": "1. DET QE JANE SHTY NGA KJO JAVE NE JAVEN TJETER / BRENDA JAVES",
    "postponed_today": "DET QE JANE SHTYER SOT AM DHE PM",
    "untouched": "2. PSE PA PREK TERE DITEN?",
    "same_day": "3. SOT PËR SOT/DEADLINE - PROGRESI?",
    "realization": "5. REALIZIMI - A MBERRIHET?",
    "ga_postponed": "2. A KA DET QE SHTYHET (SOT/SOT) OSE DEADLINE?",
}
DATE_ACTIONS = {"task.due_date_changed": "due_date", "task.start_date_changed": "start_date"}


REALIZATION_CAPTURE_TIME = time(16, 15)


def subject_for(day: date) -> str:
    return f"{M3_TITLE} - {day:%d.%m.%Y}"


def postponement_risk(original: date, moved_to: date) -> tuple[str, str]:
    week_start = original - timedelta(days=original.weekday())
    if moved_to >= week_start + timedelta(days=7) or moved_to.weekday() == 4:
        return "RREZIK", "#fee2e2"
    return "OK", "#dcfce7"


def planned_for_report_day(row: dict, day: date) -> bool:
    start = semantic_local_day(row.get("original_day_start_date", row.get("old_start_date")))
    due = semantic_local_day(row.get("original_day_due_date", row.get("old_due_date")))
    if start and due and start <= due:
        return start <= day <= due
    return start == day or due == day


def planned_for_report_week(row: dict, day: date) -> bool:
    week_start = day - timedelta(days=day.weekday())
    week_end = week_start + timedelta(days=6)
    start = semantic_local_day(row.get("old_start_date"))
    due = semantic_local_day(row.get("old_due_date"))
    if start and due and start <= due:
        return start <= week_end and due >= week_start
    return any(value is not None and week_start <= value <= week_end for value in (start, due))


def select_task_sections(tasks: list[Any], events: list[Any], day: date, *, postponement_period: str | None = None) -> dict[str, list[dict]]:
    """Classify today's tasks using current status and pre-change planning dates."""
    events_by_task: dict[Any, list[Any]] = defaultdict(list)
    for event in events:
        if event.action in DATE_ACTIONS and semantic_local_day(event.created_at) == day:
            events_by_task[event.entity_id].append(event)
    if postponement_period:
        # AM ends when the operational lunch break starts at 12:00 local time.
        # Replay AM as it stood before lunch, even when PM edits followed it.
        def period(event):
            stamp = event.created_at
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return "AM" if stamp.astimezone(report_timezone()).time() < time(12) else "PM"

        window_tasks = []
        for task in tasks:
            snapshot = SimpleNamespace(**vars(task))
            if postponement_period == "AM":
                for event in sorted(events_by_task.get(task.id, []), key=lambda item: (item.created_at, str(item.id)), reverse=True):
                    if period(event) == "PM":
                        setattr(snapshot, DATE_ACTIONS[event.action], (event.before or {}).get("value"))
            window_tasks.append(snapshot)
        tasks = window_tasks
        events_by_task = {task_id: [event for event in changes if period(event) == postponement_period]
                          for task_id, changes in events_by_task.items()}
    sections: dict[str, list[dict]] = {key: [] for key in ("postponed", "untouched", "same_day", "ga_postponed")}
    for task in tasks:
        task_events = sorted(events_by_task.get(task.id, []), key=lambda event: (event.created_at, str(event.id)))
        current = {field: semantic_local_day(getattr(task, field, None)) for field in ("start_date", "due_date")}
        original = dict(current)
        # Reverse today's changes to recover the dates before postponement,
        # including cases where start and due were moved in separate requests.
        for event in reversed(task_events):
            before_date = semantic_local_day((event.before or {}).get("value"))
            if before_date is not None:
                original[DATE_ACTIONS[event.action]] = before_date
        created_today = semantic_local_day(task.created_at) == day
        dates_before_event = dict(original)
        originally_same_day = False
        for event in task_events:
            field = DATE_ACTIONS[event.action]
            before_date = semantic_local_day((event.before or {}).get("value"))
            after_date = semantic_local_day((event.after or {}).get("value"))
            dates_before_event[field] = before_date
            if (created_today and before_date and after_date and after_date > before_date
                    and dates_before_event["start_date"] == day and dates_before_event["due_date"] == day):
                originally_same_day = True
            dates_before_event[field] = after_date
        status = str(getattr(task.status, "value", task.status)).upper()
        is_system = bool(getattr(task, "system_template_origin_id", None) or getattr(task, "system_task_slot_id", None))
        base = {"task_id": str(task.id), "title": _clean_task_title(task.title, is_system_task=is_system), "status": status,
                "am_pm": _m3_am_pm_label(task), "task_type": _m3_task_type_label(task),
                "progress": task.progress_percentage or 0,
                "created_date": semantic_local_day(task.created_at).isoformat() if task.created_at else None,
                "start_date": current["start_date"].isoformat() if current["start_date"] else None,
                "due_date": current["due_date"].isoformat() if current["due_date"] else None,
                "deadline_important": bool(task.is_deadline_important), "is_system_task": is_system,
                "marker": one_h_marker_label(active_one_h_marker(task, day), active_one_h_marker_by_ga(task, day)),
                "eight_am": title_has_eight_am_indicator(task.title, is_system_task=is_system)
                    or (isinstance(task.due_date, datetime) and _local_time(task.due_date) == "08:00")}
        if (status == "TODO" and current["start_date"] and current["due_date"]
                and current["start_date"] <= day <= current["due_date"]):
            sections["untouched"].append(dict(base))
        if status != "DONE" and created_today and current["start_date"] == day and current["due_date"] == day:
            sections["same_day"].append(dict(base))
        moved_fields = []
        for field in ("start_date", "due_date"):
            before, after = original[field], current[field]
            if field == "due_date" and status == "DONE" and semantic_local_day(getattr(task, "completed_at", None)) == after:
                # Completing a late task normalizes due_date to completed_at;
                # that automatic normalization is not a postponement.
                continue
            if before and after and after > before and any(DATE_ACTIONS[event.action] == field for event in task_events):
                moved_fields.append((field, before, after))
        if not moved_fields:
            continue
        old_due = original["due_date"]
        # Due changes determine risk when present; otherwise use the moved start.
        _, before, after = next((item for item in moved_fields if item[0] == "due_date"), moved_fields[0])
        risk, color = postponement_risk(day, after)
        row = {**base, "old_start_date": original["start_date"].isoformat() if original["start_date"] else None,
               "old_due_date": old_due.isoformat() if old_due else None,
               "postponement_kind": "start_due" if len(moved_fields) == 2 else "start" if moved_fields[0][0] == "start_date" else "due",
               "from_date": before.isoformat(), "to_date": after.isoformat(), "risk": risk, "risk_color": color,
               "postponement_period": postponement_period,
               "change_reason": next((str((event.after or {}).get("reason") or "") for event in reversed(task_events)
                                      if (event.after or {}).get("reason")), "")}
        # The audit day determines membership, regardless of the original planning week.
        sections["postponed"].append(dict(row))
        if task.is_deadline_important or originally_same_day:
            if originally_same_day:
                row["old_start_date"] = row["old_due_date"] = day.isoformat()
            row["category"] = " / ".join(label for flag, label in (
                (bool(task.is_deadline_important), "Deadline Important"), (originally_same_day, "SOT/SOT"),
            ) if flag)
            sections["ga_postponed"].append(row)
    if postponement_period is None:
        original_plans = {row["task_id"]: row for row in sections["postponed"]}
        daily_rows = []
        for period in ("AM", "PM"):
            for row in select_task_sections(tasks, events, day, postponement_period=period)["postponed"]:
                original = original_plans.get(row["task_id"], row)
                row = {**row, "original_day_start_date": original.get("old_start_date"),
                       "original_day_due_date": original.get("old_due_date")}
                if planned_for_report_day(row, day):
                    daily_rows.append(row)
        sections["postponed_today"] = daily_rows
        sections["postponed"] = [row for row in sections["postponed"] if planned_for_report_week(row, day)]
    return sections


async def build_task_data(db: AsyncSession, day: date, *, section_selector=select_task_sections) -> dict:
    local_start = datetime.combine(day, time.min, tzinfo=report_timezone())
    start, end = local_start.astimezone(timezone.utc), (local_start + timedelta(days=1)).astimezone(timezone.utc)
    tasks = list((await db.execute(select(Task).where(Task.is_active.is_(True), Task.created_at < end)
                                  .order_by(Task.department_id, Task.title, Task.id))).scalars().all())
    events = list((await db.execute(select(AuditLog).where(
        AuditLog.entity_type == "task", AuditLog.action.in_(DATE_ACTIONS),
        AuditLog.created_at >= start, AuditLog.created_at < end,
    ).order_by(AuditLog.created_at, AuditLog.id))).scalars().all())
    sections = section_selector(tasks, events, day)
    selected = {uuid.UUID(row["task_id"]) for rows in sections.values() for row in rows}
    if not selected:
        return sections
    users = {user.id: user.full_name or user.username or user.email
             for user in (await db.execute(select(User))).scalars().all()}
    department_codes = {item.id: item.code for item in (await db.execute(select(Department))).scalars().all()}
    projects = {item.id: item.title for item in (await db.execute(select(Project).where(
        Project.id.in_({task.project_id for task in tasks if task.id in selected and task.project_id})
    ))).scalars().all()}
    owners: dict[Any, set[Any]] = defaultdict(set)
    for task_id, user_id in (await db.execute(select(TaskAssignee.task_id, TaskAssignee.user_id)
                                            .where(TaskAssignee.task_id.in_(selected)))).all():
        owners[task_id].add(user_id)
    selected_tasks = [task for task in tasks if task.id in selected]
    for task in selected_tasks:
        if task.assigned_to:
            owners[task.id].add(task.assigned_to)
    await apply_weekly_planner_task_order(db, selected_tasks, owners, department_codes)
    states: dict[Any, list[Any]] = defaultdict(list)
    for state in (await db.execute(select(TaskDailyRlzState).where(
        TaskDailyRlzState.day_date == day, TaskDailyRlzState.task_id.in_(selected),
    ).order_by(TaskDailyRlzState.user_id))).scalars().all():
        states[state.task_id].append(state)
    progress = {item.task_id: item for item in (await db.execute(select(TaskDailyProgress).where(
        TaskDailyProgress.day_date == day, TaskDailyProgress.task_id.in_(selected),
    ))).scalars().all()}
    by_id = {task.id: task for task in tasks}
    for key, rows in sections.items():
        for row in rows:
            task_id = uuid.UUID(row["task_id"])
            task = by_id[task_id]
            if task.assigned_to:
                owners[task_id].add(task.assigned_to)
            row["assignees"] = _task_owners(task, users, owners)
            row["department"] = _m3_department_label(task, department_codes)
            row["project"] = projects.get(task.project_id, "-")
            evidence = states[task_id]
            # My View writes day-scoped reasons/comments to TaskDailyRlzState.
            # Do not replace absent daily evidence with the date-change audit reason.
            row.update(daily_explanation_values(evidence, users))
            daily = progress.get(task_id)
            row["completed_today"] = daily.completed_delta if daily else 0
            row["completed_value"] = daily.completed_value if daily else None
            row["total_value"] = daily.total_value if daily else None
        rows.sort(key=lambda row: (
            *common_view_task_sort_key(by_id[uuid.UUID(row["task_id"])], users, owners), row["task_id"],
        ))
    return sections


async def build_realization_capture(db: AsyncSession, day: date) -> dict:
    users = list((await db.execute(select(User).where(User.is_active.is_(True),
        User.department_id.is_not(None)))).scalars().all())
    department_by_id = {item.id: item for item in (await db.execute(select(Department))).scalars().all()}
    people, missing, departments = [], [], []
    for department_id in sorted(department_by_id, key=lambda value: (
        {"DEV": 0, "GD": 1, "PCM": 2}.get(getattr(department_by_id.get(value), "code", ""), 3),
        getattr(department_by_id.get(value), "code", str(value)),
    )):
        live = await build_live_daily_realization(db, department_id=department_id, day=day)
        if not live.get("baseline_available"):
            missing.append(str(department_id))
        for person in live.get("people", []):
            # Use the same complete live population as the Realization page,
            # including managers and historical assignees retained by its engine.
            people.append({"user_id": str(person["user_id"]), "name": person.get("user_name"),
                           "percent": (person.get("metrics") or {}).get("raw_plan_realization")})
        department_metrics = live["metrics"]
        department_percent = department_metrics["raw_plan_realization"]
        department = department_by_id.get(department_id)
        departments.append({"department_id": str(department_id), "code": getattr(department, "code", str(department_id)),
                            "name": getattr(department, "name", ""), "percent": department_percent,
                            "employees": sum(user.department_id == department_id for user in users),
                            "baseline_available": bool(live.get("baseline_available")), "metrics": department_metrics,
                            "comment": realization_department_comment(department_percent)})
    metrics = combine_daily_metrics(item["metrics"] for item in departments)
    # Missing baselines are metadata, not a reason to hide PLAN RLZ: the daily
    # dashboard also shows the total from the available department metrics.
    percent = metrics["raw_plan_realization"]
    return {"percent": percent, "employees": len(users), "people": people, "metrics": metrics,
            "baseline_available": not missing and bool(users), "missing_departments": missing,
            "comment": realization_comment(percent), "departments": departments}


def realization_department_rows(realization: dict | None) -> list[dict]:
    return [{**item, "comment": realization_department_comment(item.get("percent"))}
            for item in (realization or {}).get("departments", [])
            if str(item.get("code") or "").strip().upper() not in {"GA", "HR"}]


def realization_department_comment(percent: float | None) -> str:
    if percent is None:
        return realization_comment(percent)
    if percent == 50:
        return "Jemi në 50%"
    return f"Jemi {'mbi' if percent > 50 else 'nën'} 50%"


def realization_comment(percent: float | None) -> str:
    if percent is None:
        return "Mungojne te dhenat e plota per realizimin e stafit."
    if percent == 50:
        return "Jemi ne 50%."
    return f"Jemi {'mbi' if percent > 50 else 'nen'} 50% me {abs(percent - 50):g} pike perqindjeje."


async def get_settings(db: AsyncSession):
    from types import SimpleNamespace
    from app.services.reporting_points_settings import get_delivery_settings, manual_recipients
    settings = await get_delivery_settings(db, "M3")
    return SimpleNamespace(recipients=await manual_recipients(db, "M3", settings))


async def locked_report(db: AsyncSession, day: date, *, wait: bool = True) -> M3ReportingPointsReport | None:
    function = "pg_advisory_xact_lock" if wait else "pg_try_advisory_xact_lock"
    acquired = (await db.execute(text(f"SELECT {function}(hashtext(:key))"),
                                {"key": f"m3_reporting_points|{day.isoformat()}"})).scalar()
    if not wait and not acquired:
        return None
    row = (await db.execute(select(M3ReportingPointsReport).where(M3ReportingPointsReport.report_date == day))).scalar_one_or_none()
    if row is None:
        row = M3ReportingPointsReport(report_date=day, manual_answers={}, data={}, status="DRAFT")
        db.add(row)
        await db.flush()
    return row


async def refresh_report(db: AsyncSession, row: M3ReportingPointsReport, now: datetime | None = None) -> None:
    """Rebuild today's report, including the latest staff realization.

    From 16:15 on the realization is stored as the day's final value, replacing
    any earlier capture. Before that it is only a live preview and the report
    cannot be sent yet.
    """
    now = (now or datetime.now(report_timezone())).astimezone(report_timezone())
    if row.report_date != now.date():
        raise ValueError("Raportet historike perdorin te dhenat e ruajtura te asaj dite.")
    data = await build_task_data(db, row.report_date)
    data["unheld_meetings"] = await build_unheld_meetings(db, row.report_date)
    row.data = data
    row.realization = await build_realization_capture(db, row.report_date)
    if now.time().replace(tzinfo=None) >= REALIZATION_CAPTURE_TIME:
        row.realization_captured_at = now
    row.generated_at = now


def report_payload(row: M3ReportingPointsReport) -> dict:
    realization = row.realization
    if realization and "departments" in realization:
        realization = {**realization, "departments": realization_department_rows(realization)}
    return {"id": str(row.id), "report_date": row.report_date.isoformat(), "subject": subject_for(row.report_date),
            "manual_answers": row.manual_answers or {},
            "data": {key: [item for item in rows if item.get("status") != "DONE"] if key == "same_day" else
                     [item for item in rows if planned_for_report_day(item, row.report_date)] if key == "postponed_today" else rows
                     for key, rows in (row.data or {}).items()}, "realization": realization,
            "realization_captured_at": row.realization_captured_at.isoformat() if row.realization_captured_at else None,
            "generated_at": row.generated_at.isoformat() if row.generated_at else None, "status": row.status,
            "sent_at": row.sent_at.isoformat() if row.sent_at else None, "last_error": row.last_error}


def daily_explanation_values(evidence, users: dict) -> dict:
    def prefix(item):
        return f"{_initials(users.get(item.user_id))}: " if len(evidence) > 1 else ""
    return {
        "comment": "\n".join(prefix(item) + item.comment.strip()
                              for item in evidence if item.comment and item.comment.strip()) or "-",
        "reason": "\n".join(prefix(item) + REASON_LABELS.get(item.reason_code, item.reason_code)
                             for item in evidence if item.reason_code) or "-",
    }


async def with_current_task_explanations(db: AsyncSession, payload: dict, section: str) -> dict:
    # Today's My View edits appear on the next report refresh. Historical reports
    # keep their saved evidence, and manual report comments remain independent.
    if payload["report_date"] != datetime.now(report_timezone()).date().isoformat():
        return payload
    rows = payload["data"].get(section, [])
    task_ids = {uuid.UUID(row["task_id"]) for row in rows if row.get("task_id")}
    if not task_ids:
        return payload
    states = defaultdict(list)
    for state in (await db.execute(select(TaskDailyRlzState).where(
        TaskDailyRlzState.day_date == date.fromisoformat(payload["report_date"]),
        TaskDailyRlzState.task_id.in_(task_ids),
    ).order_by(TaskDailyRlzState.user_id))).scalars().all():
        states[state.task_id].append(state)
    user_ids = {state.user_id for items in states.values() for state in items}
    users = {user.id: user.full_name or user.username or user.email
             for user in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()} if user_ids else {}
    updated = [{**row, **daily_explanation_values(states[uuid.UUID(row["task_id"])], users)}
               if row.get("task_id") else row for row in rows]
    return {**payload, "data": {**payload["data"], section: updated}}


async def current_report_payload(db: AsyncSession, row: M3ReportingPointsReport) -> dict:
    payload = report_payload(row)
    payload = await with_current_task_explanations(db, payload, "untouched")
    payload["data"] = await add_saved_meeting_appearance(db, payload["data"])
    return payload


def _cell(value: Any) -> str:
    return html.escape(str(value if value is not None else "-"), quote=True).replace("\n", "<br>")


def postponement_kind(row: dict) -> str:
    if row.get("postponement_kind") in {"start_due", "due", "start"}:
        return row["postponement_kind"]
    start_moved = bool(row.get("old_start_date") and row.get("start_date") and row["start_date"] > row["old_start_date"])
    due_moved = bool(row.get("old_due_date") and row.get("due_date") and row["due_date"] > row["old_due_date"])
    return "start_due" if start_moved and due_moved else "start" if start_moved else "due"


def task_table_groups(rows: list[dict], key: str) -> list[tuple[str, str, list[dict]]]:
    if key == "same_day":
        rows = [row for row in rows if row.get("status") != "DONE"]
    if key == "untouched":
        return [("DET FT DHE PRJK PA PROGRES", "", [row for row in rows if not is_system_row(row)]),
                ("DETYRAT E SISTEMIT PA PROGRES", "", [row for row in rows if is_system_row(row)])]
    if key not in {"postponed", "ga_postponed", "postponed_today"}:
        return [("", "", rows)]
    if key == "postponed_today":
        periods = ["AM", "PM"] + (["-"] if any(not row.get("postponement_period") for row in rows) else [])
        return [(f"{period} - {caption}", movement, group)
                for period in periods
                for caption, movement, group in task_table_groups(
                    [row for row in rows if (row.get("postponement_period") or "-") == period], "ga_postponed")]
    groups = [("SHTYER START DHE DUE DATE", "start_due"), ("SHTYER DUE DATE", "due")]
    if any(postponement_kind(row) == "start" for row in rows):
        groups.append(("SHTYER START DATE", "start"))
    return [(caption, kind, [row for row in rows if postponement_kind(row) == kind]) for caption, kind in groups]


def is_system_row(row: dict) -> bool:
    return bool(row.get("is_system_task") or row.get("task_type") == "SYS")


def task_row_appearance(row: dict) -> tuple[str, str, bool]:
    deadline = bool(row.get("deadline_important") or "Deadline Important" in str(row.get("category") or ""))
    eight_am = bool(row.get("eight_am") or title_has_eight_am_indicator(row.get("title"), is_system_task=is_system_row(row)))
    return ("#dc2626" if deadline else STATUS_COLORS.get(row.get("status"), "#ffffff"),
            "#ffffff" if deadline else "#000000", eight_am)


def report_table_columns(key: str, movement: str = "") -> list[tuple[str, str, int]]:
    if key == "postponed_today":
        key = "postponed"
    columns = [("nr", "NR", 28), ("assignees", "KUSH", 42), ("department", "DEP", 44),
               ("project", "PRJK", 96), ("am_pm", "AM/PM", 48), ("task_type", "LLOJI", 48)]
    if key in {"postponed", "ga_postponed"}:
        date_width = 124 if movement == "start_due" else 88
        columns += [("from", "NGA", date_width), ("to", "NE", date_width)]
    columns.append(("title", "TITULLI", 360))
    columns += [("reason", "ARSYEJA", 124), ("comment", "KOMENTI", 160)]
    if key == "untouched":
        columns.append(("manual_comment", "KOMENT MANUAL", 220))
    if key in {"postponed", "ga_postponed"}:
        columns.append(("risk", "VLERESIMI", 80))
        if key == "ga_postponed":
            columns.append(("category", "KUSHTI", 100))
    return columns


def report_table_value(row: dict, column: str, index: int, kind: str, report: dict | None = None) -> Any:
    if column == "manual_comment":
        return (report or {}).get("manual_answers", {}).get(f"untouched_comment:{row.get('task_id')}") or "-"
    def formatted(value):
        day = semantic_local_day(value)
        return day.strftime("%d.%m.%Y") if day else "-"
    if column == "nr":
        return index
    if column == "title":
        title = _clean_task_title(row.get("title"), is_system_task=True)
        return f"{row['marker']} {title}" if row.get("marker") else title
    if column in {"from", "to"}:
        prefix = "old_" if column == "from" else ""
        if kind == "start_due":
            return f"START: {formatted(row.get(prefix + 'start_date'))}\nDUE: {formatted(row.get(prefix + 'due_date'))}"
        field = "start_date" if kind == "start" else "due_date"
        return formatted(row.get(prefix + field))
    if column.endswith("_date"):
        return formatted(row.get(column))
    return row.get(column) or "-"


def render_html(report: dict) -> str:
    cell_style = "border:1px solid #000;padding:6px 4px;vertical-align:top;text-align:left;overflow-wrap:anywhere"
    def manual(keys):
        return "".join(f"<h3>{_cell(MANUAL_POINTS[key])}</h3><p style='white-space:pre-wrap'>{_cell(report['manual_answers'].get(key) or 'Pa pergjigje')}</p>" for key in keys)

    def table(key):
        parts = [f"<h3>{_cell(AUTO_TITLES[key])}</h3>"]
        if key == "postponed":
            parts.append(
                "<p style='font-size:14px;font-weight:700;line-height:1.5'>Shtyrjet e bëra gjatë ditës. "
                "<span style='background-color:#dcfce7;color:#14532d;padding:2px 4px'>Brenda javës: OK.</span> "
                "<span style='background-color:#fee2e2;color:#7f1d1d;padding:2px 4px'>Për të premten ose javën tjetër: RREZIK.</span></p>"
            )
        for caption, kind, rows in task_table_groups(report["data"].get(key, []), key):
            columns = report_table_columns(key, kind)
            if caption:
                parts.append(f"<h4>{caption}:</h4>")
            if not rows:
                parts.append("<p>Asnje detyre.</p>")
                continue
            header = "".join(
                f"<th bgcolor='#e2e8f0' style='{cell_style};background-color:#e2e8f0;font-size:11px;font-weight:700"
                + (f";width:{width}px" if column != "title" else "") + f"'>{label}</th>"
                for column, label, width in columns
            )
            body = []
            for index, row in enumerate(rows, 1):
                cells = []
                row_fill, row_color, eight_am = task_row_appearance(row)
                for column_index, (column, _, width) in enumerate(columns):
                    color = ("#fee2e2" if row.get("risk") == "RREZIK" else "#dcfce7") if column == "risk" else row_fill
                    style = f"{cell_style};background:{color};white-space:normal;word-break:break-word"
                    style += f";color:{row_color}"
                    if eight_am:
                        style += ";border-top:3px solid #dc2626;border-bottom:3px solid #dc2626"
                        if column_index == 0:
                            style += ";border-left:3px solid #dc2626"
                        if column_index == len(columns) - 1:
                            style += ";border-right:3px solid #dc2626"
                    if column != "title":
                        style += f";width:{width}px"
                    if column == "risk":
                        style += ";font-weight:700;color:" + ("#7f1d1d" if row.get("risk") == "RREZIK" else "#14532d")
                    value = _cell(report_table_value(row, column, index, kind, report))
                    if column == "title":
                        if row.get("marker"):
                            value = (f"<strong data-task-symbol='true' style='display:inline-block;margin-right:4px;color:{'#ffffff' if row_color == '#ffffff' else '#DC2626'};font-size:1.18em;font-weight:900'>"
                                     f"{_cell(row['marker'])}</strong>{_cell(_clean_task_title(row.get('title'), is_system_task=True))}")
                        else:
                            value = _render_table_cell_html("TITULLI", report_table_value(row, column, index, kind))
                        if row_color == "#ffffff":
                            value = value.replace("color:#DC2626;", "color:#ffffff;")
                        value = f"<div style='white-space:normal;overflow-wrap:anywhere'>{value}</div>"
                    elif column in {"from", "to"} and kind == "start_due":
                        first, second = value.split("<br>", 1)
                        # Presentation tables preserve the full-width divider in
                        # email clients that do not honor block styles on spans.
                        value = (
                            "<table role='presentation' width='100%' border='0' cellpadding='0' cellspacing='0' "
                            "style='width:100%;border-collapse:collapse;font:inherit;color:inherit'>"
                            f"<tr><td style='border:0;border-bottom:3px solid #000;padding:0 0 3px'>{first}</td></tr>"
                            f"<tr><td style='border:0;padding:3px 0 0'>{second}</td></tr></table>"
                        )
                    cells.append(f"<td bgcolor='{color}' valign='top' style='{style}'>{value}</td>")
                body.append("<tr>" + "".join(cells) + "</tr>")
            colgroup = "".join("<col>" if column == "title" else f"<col style='width:{width}px'>" for column, _, width in columns)
            parts.append(f"<div style='overflow-x:auto'><table width='100%' border='1' cellpadding='0' cellspacing='0' style='width:100%;min-width:{sum(width for _, _, width in columns)}px;table-layout:fixed;border-collapse:collapse;border:1px solid #000;font-size:12px;line-height:1.5'><colgroup>{colgroup}</colgroup><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table></div>")
        return "".join(parts)

    meeting_html = f"<h3>{MEETING_TITLE}</h3>"
    for label, meetings in meeting_groups(report):
        meeting_html += f"<h4 style='background:#f8fafc;padding:8px 12px;margin:0'>{label}</h4>"
        headers = "".join(f"<th style='{cell_style};background:#e2e8f0;width:{width}px'>{_cell(title)}</th>"
                          for _, title, width in MEETING_COLUMNS)
        body = []
        for index, row in enumerate(meetings, 1):
            cells = []
            for column, cell in enumerate(meeting_cells(row, index)):
                frame = ""
                if cell["meeting_highlight"]:
                    frame = ";border-top:3px solid #2563eb;border-bottom:3px solid #2563eb"
                    if cell["first"]:
                        frame += ";border-left:3px solid #2563eb"
                    if cell["last"]:
                        frame += ";border-right:3px solid #2563eb"
                value = _cell(cell["text"])
                if column == 3:
                    value = _cell(row.get("title"))
                    if row.get("origin"):
                        badge = "background:#0d9488;color:#fff" if row["origin"] == "CAL" else "background:#FFF4CC;color:#78350f;border:1px solid #D6B44C"
                        value = f"<strong style='{badge};border-radius:12px;padding:1px 5px;font-size:9px;margin-right:6px'>{row['origin']}</strong>" + value
                    if row.get("meeting_relation") in {"PARA", "PAS"}:
                        value = ("<strong style='border:1px solid #334155;background:#fff;color:#0f172a;border-radius:12px;padding:1px 5px;font-size:9px;margin-right:6px'>"
                                 + row["meeting_relation"] + "</strong>" + value)
                style = f"{cell_style};background:{cell['fill']};color:{cell['color']};white-space:pre-wrap{frame}"
                if cell["bold"]:
                    style += ";font-weight:bold"
                if column == 2:
                    style += ";text-align:center"
                cells.append(f"<td bgcolor='{cell['fill']}' style='{style}'>{value}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        table_width = sum(width for _, _, width in MEETING_COLUMNS)
        meeting_html += (f"<table width='{table_width}' border='1' cellpadding='0' cellspacing='0' "
                         f"style='width:{table_width}px;max-width:100%;table-layout:fixed;border-collapse:collapse;font-size:12px'>"
                         f"<thead><tr>{headers}</tr></thead><tbody>{''.join(body)}</tbody></table>")
        if not meetings:
            meeting_html += "<p>Asnjë takim i anuluar për këtë datë.</p>"

    realization = report.get("realization")
    if realization:
        percent = realization.get("percent")
        summary = f"{percent:g}%" if percent is not None else "Pa te dhena"
        realization_html = f"<p><strong>{summary}</strong> — {_cell(realization['comment'])}</p><p>Marrë në: {_cell(report.get('realization_captured_at'))}</p>"
        department_rows = realization_department_rows(realization)
        if department_rows:
            realization_html += "<table border='1' cellpadding='6' cellspacing='0' style='width:auto;border-collapse:collapse;border:1px solid #000'><tr>"
            compact_style = ";white-space:nowrap"
            realization_html += "".join(f"<th bgcolor='#e2e8f0' style='{cell_style};background-color:#e2e8f0{compact_style}'>{label}</th>" for label in ("DEP", "REALIZIMI", "VLERËSIMI")) + "</tr>"
            for item in department_rows:
                value = item.get("percent")
                fill = "#e2e8f0" if value is None else "#fee2e2" if value < 50 else "#dcfce7"
                realization_html += (f"<tr><td style='{cell_style}{compact_style}'>{_cell(item['code'])}</td>"
                                     f"<td bgcolor='{fill}' style='{cell_style}{compact_style};background-color:{fill};font-weight:700'>{f'{value:g}%' if value is not None else 'Pa të dhëna'}</td>"
                                     f"<td style='{cell_style}'>{_cell(item['comment'])}</td></tr>")
            realization_html += "</table>"
    else:
        realization_html = "<p>Vlera e realizimit merret ne 16:15. Nuk ka vlere te ruajtur per kete date.</p>"
    return ("<!doctype html><html><head><meta charset='utf-8'></head><body style='font-family:Arial,sans-serif;color:#0f172a'>"
            + f"<h1>{M3_TITLE}</h1><p>Data: {_cell(report['report_date'])}</p>"
            + manual(("underload", "overload", "reorganization"))
            + "".join(table(key) for key in ("postponed", "postponed_today", "untouched", "same_day"))
            + meeting_html
            + f"<h3>{AUTO_TITLES['realization']}</h3>{realization_html}" + "</body></html>")


def render_plain_text(report: dict) -> str:
    lines = [M3_TITLE, report["report_date"]]
    for key in ("underload", "overload", "reorganization"):
        lines += [MANUAL_POINTS[key], report["manual_answers"].get(key) or "Pa pergjigje"]
    for key in ("postponed", "postponed_today", "untouched", "same_day", "unheld_meetings", "realization"):
        if key == "unheld_meetings":
            lines.append(MEETING_TITLE)
            for label, meetings in meeting_groups(report):
                lines.append(label)
                lines.extend(" | ".join(f"{label}: {value}" for (_, label, _), value in zip(MEETING_COLUMNS, meeting_values(row, index)))
                             for index, row in enumerate(meetings, 1))
                if not meetings:
                    lines.append("Asnjë takim i anuluar për këtë datë.")
            continue
        lines.append(AUTO_TITLES[key])
        if key == "postponed":
            lines.append("Shtyrjet e bëra gjatë ditës. Brenda javës: OK. Për të premten ose javën tjetër: RREZIK.")
        if key == "realization":
            realization = report.get("realization")
            lines.append(f"{realization.get('percent')}% - {realization['comment']}" if realization and realization.get("percent") is not None
                         else "Pa te dhena te ruajtura ne 16:15.")
            for item in realization_department_rows(realization):
                value = item.get("percent")
                lines.append(f"{item['code']}: " + (f"{value:g}%" if value is not None else "Pa të dhëna") + f" - {item['comment']}")
            continue
        for caption, kind, rows in task_table_groups(report["data"].get(key, []), key):
            if caption:
                lines.append(caption)
            lines.extend(" | ".join(f"{label}: {report_table_value(row, column, index, kind, report)}"
                                    for column, label, _ in report_table_columns(key, kind))
                         for index, row in enumerate(rows, 1))
            if not rows:
                lines.append("Asnje detyre.")
    return "\n\n".join(lines)


async def send_report(db: AsyncSession, row: M3ReportingPointsReport, recipients: dict, *, automatic: bool = False) -> None:
    recipients = normalize_recipients(recipients)
    if not recipients["to"]:
        raise ValueError("Shto te pakten nje marres To perpara dergimit.")
    report = await current_report_payload(db, row)
    try:
        gmail = GmailService()
        html_body = render_html(report)
        from app.services.m3_reporting_points_attachments import report_attachments
        attachments = await asyncio.to_thread(report_attachments, report)
        # Every manual send is a new delivery, including an unchanged report.
        # Keep every row in a standalone copy as well as in the email body.
        message = await gmail.send_verified(report["subject"], recipients,
                                             render_plain_text(report), html_body,
                                             attachments=[(f"pikat_m3_{row.report_date.isoformat()}.html",
                                                           html_body.encode("utf-8"), "text/html"), *attachments])
    except Exception as exc:
        row.status, row.last_error = "FAILED", str(exc)[:2000]
        await db.commit()
        raise
    row.status, row.sent_at = "SENT", datetime.now(report_timezone())
    row.gmail_message_id, row.last_error = message.get("id"), None
    if automatic:
        row.auto_sent_at = row.sent_at
    await db.commit()
