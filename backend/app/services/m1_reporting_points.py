from __future__ import annotations

import asyncio
import html
import re
import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.common_entry import CommonEntry
from app.models.department import Department
from app.models.enums import CommonCategory, GaNoteStatus
from app.models.ga_note import GaNote
from app.models.plan_note import PlanNote
from app.models.m1_reporting_points import M1ReportingPointsReport
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.user import User
from app.services.meetings_report import (
    _initials, _m3_am_pm_label, _m3_department_label, _m3_task_type_label, _task_owners,
    apply_weekly_planner_task_order, common_view_task_sort_key,
)
from app.services.meetings_report_scheduler import normalize_recipients
from app.services.primeflow_report import GmailService, report_timezone
from app.services.report_rich_text import marked_note_runs, runs_html
from app.services import m2_reporting_points as m2, m3_reporting_points as m3
from app.services.daily_realization_events import semantic_local_day
from app.services.task_marker import active_one_h_marker, active_one_h_marker_by_ga, one_h_marker_label

TITLE = "PIKAT PER RAPORTIM M1"
POINTS = (
    ("absences", "1. MUNGESA"),
    ("delays", "2. VONESA"),
    ("plan_changes", "3. A KA NDRYSHIM TË PLANIT / PRIORITETEVE?"),
    ("notes", "4. NOTES TË REJA?"),
    ("tasks", "5. DETYRA TË REJA TË KRIJUARA SOT?"),
    ("reorganization", "6. A DUHET RIORGANIZIM?"),
    ("ga_progress", "7. DET ME GA: PERSONALISHT DHE ME SIMBOLE F, GA"),
    ("delivery", "8. SA PER DOREZIM M2?"),
)
MANUAL_POINTS = {key: title for key, title in POINTS if key in {"plan_changes", "reorganization"}}


def subject_for(day: date) -> str:
    return f"{TITLE} - {day:%d.%m.%Y}"


def reporting_windows(day: date, now: datetime | None = None) -> tuple[datetime, datetime, datetime]:
    zone = report_timezone()
    return (datetime.combine(day - timedelta(days=1), time(16, 30), zone),
            datetime.combine(day, time.min, zone),
            _local(now or datetime.now(zone)))


def _local(value: datetime) -> datetime:
    return (value if value.tzinfo else value.replace(tzinfo=report_timezone())).astimezone(report_timezone())


def _entry_details(description: str | None, category: str) -> dict:
    note = description or ""
    if category == "absences":
        match = re.search(r"From:\s*(\d{1,2}:\d{2})\s*-\s*To:\s*(\d{1,2}:\d{2})", note, re.I)
        values = {"from": match.group(1) if match else "08:00", "to": match.group(2) if match else "23:00"}
    else:
        start = re.search(r"Start:\s*(\d{1,2}:\d{2})", note, re.I)
        until = re.search(r"Until:\s*(\d{1,2}:\d{2})", note, re.I)
        values = {"start": start.group(1) if start else "08:00", "until": until.group(1) if until else "09:00"}
    note = re.sub(r"From:\s*\d{1,2}:\d{2}\s*-\s*To:\s*\d{1,2}:\d{2}|Start:\s*\d{1,2}:\d{2}|Until:\s*\d{1,2}:\d{2}|Date:\s*\d{4}-\d{2}-\d{2}", "", note, flags=re.I).strip()
    return {**values, "note": note or None}


def _px_notes_only(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row.get("source") == "PX Notes"]


def _newest_notes_first(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: (
        _local(datetime.fromisoformat(row["created_at"])).timestamp() if row.get("created_at") else float("-inf"),
        str(row.get("id") or "")), reverse=True)


def _done_last(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda row: str(row.get("status") or "").upper() == "DONE")


def _task_planning_columns(task, day: date) -> dict:
    start = semantic_local_day(getattr(task, "start_date", None))
    due = semantic_local_day(getattr(task, "due_date", None))
    tomorrow = day + timedelta(days=1)
    return {
        "start_date": start.isoformat() if start else None,
        "planned_for": ("Sot" if due == day else "Nesër" if due == tomorrow else
                        due.strftime("%d.%m.%Y") if due else "Pa afat"),
        "marker": one_h_marker_label(active_one_h_marker(task, day), active_one_h_marker_by_ga(task, day)),
    }


def select_sections(entries, ga_notes, _plan_notes, tasks, day: date, *, now: datetime | None = None,
                    users=None, departments=None, assignees=None) -> dict:
    users = users or {}
    departments = departments or {}
    assignees = assignees or {}
    names = {user_id: getattr(user, "full_name", None) or getattr(user, "username", None) or getattr(user, "email", None)
             for user_id, user in users.items()}
    note_start, task_start, cutoff = reporting_windows(day, now)
    data = {"absences": [], "delays": [], "notes": [], "tasks": []}
    for entry in entries:
        category = str(getattr(entry.category, "value", entry.category)).casefold()
        if category not in {"absences", "delays"}:
            continue
        entry_day = entry.entry_date or _local(entry.created_at).date()
        described_date = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", entry.description or "", re.I)
        if described_date:
            try:
                entry_day = date.fromisoformat(described_date.group(1))
            except ValueError:
                pass
        if entry_day != day or _local(entry.created_at) > cutoff:
            continue
        user = users.get(entry.assigned_to_user_id) or users.get(entry.created_by_user_id)
        person = (getattr(user, "full_name", None) or getattr(user, "username", None) or entry.title)
        data["absences" if category == "absences" else "delays"].append({
            "id": str(entry.id), "person": person, **_entry_details(entry.description, category),
        })
    for note in ga_notes:
        if (note_start <= _local(note.created_at) <= cutoff
                and not getattr(note, "is_converted_to_task", False)
                and getattr(note, "status", GaNoteStatus.OPEN) != GaNoteStatus.CLOSED):
            author = users.get(getattr(note, "created_by", None))
            data["notes"].append({"id": str(note.id), "source": "PX Notes", "content": note.content,
                                  "author": (getattr(author, "full_name", None) or getattr(author, "username", None)
                                             or getattr(author, "email", None) or "-"),
                                  "created_at": _local(note.created_at).isoformat()})
    for task in tasks:
        if task_start <= _local(task.created_at) <= cutoff:
            data["tasks"].append({"id": str(task.id), "title": task.title,
                                  "status": str(getattr(task.status, "value", task.status)),
                                  "created_at": _local(task.created_at).isoformat(),
                                  "assignees": _task_owners(task, names, assignees) if hasattr(task, "assigned_to") else "-",
                                  "department": _m3_department_label(task, departments),
                                  "am_pm": _m3_am_pm_label(task), "task_type": _m3_task_type_label(task),
                                  **_task_planning_columns(task, day)})
    for key in ("absences", "delays"):
        data[key].sort(key=lambda row: (row["person"].casefold(), row["id"]))
    data["notes"] = _newest_notes_first(data["notes"])
    return data


def sort_tasks_for_report(tasks, names: dict, assignees: dict) -> list:
    return sorted(tasks, key=lambda task: (
        str(getattr(getattr(task, "status", None), "value", getattr(task, "status", None))).upper() == "DONE",
        common_view_task_sort_key(task, names, assignees), str(task.id)))


async def excluded_note_ids(db: AsyncSession, row: M1ReportingPointsReport) -> set[str]:
    ids = set()
    for note in _px_notes_only((row.data or {}).get("notes") or []):
        try:
            ids.add(uuid.UUID(str(note["id"])))
        except (KeyError, TypeError, ValueError):
            pass
    if not ids:
        return set()
    result = await db.execute(select(GaNote.id).where(
        GaNote.id.in_(ids), or_(GaNote.is_converted_to_task.is_(True), GaNote.status == GaNoteStatus.CLOSED)))
    return {str(note_id) for note_id in result.scalars().all()}


def reorder_saved_task_rows(data: dict, ordered_ids: list[str]) -> dict:
    positions = {task_id: index for index, task_id in enumerate(ordered_ids)}
    rows = data.get("tasks") or []
    return {**data, "tasks": sorted(rows, key=lambda row: positions.get(str(row.get("id")), len(positions))),
            "task_order_version": 1}


def add_saved_note_authors(data: dict, authors: dict[tuple[str, str], str]) -> dict:
    return {**data, "notes": [
        {**note, "author": authors.get((note.get("source"), str(note.get("id")))) or note.get("author") or "-"}
        for note in data.get("notes") or []
    ], "note_author_version": 1}


async def backfill_saved_note_authors(db: AsyncSession, row: M1ReportingPointsReport) -> bool:
    data = row.data or {}
    if data.get("note_author_version") == 1:
        return False
    ids = set()
    for note in data.get("notes") or []:
        if note.get("source") != "PX Notes":
            continue
        try:
            ids.add(uuid.UUID(str(note["id"])))
        except (KeyError, TypeError, ValueError):
            pass
    creators = {}
    if ids:
        for note_id, user_id in (await db.execute(select(GaNote.id, GaNote.created_by).where(
            GaNote.id.in_(ids)
        ))).all():
            creators[("PX Notes", str(note_id))] = user_id
    user_ids = {user_id for user_id in creators.values() if user_id is not None}
    users = {}
    if user_ids:
        for user in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all():
            users[user.id] = user.full_name or user.username or user.email
    row.data = add_saved_note_authors(data, {key: users.get(user_id) for key, user_id in creators.items()})
    return True


async def prepare_task_context(db: AsyncSession, tasks: list) -> tuple[list, list, dict, dict]:
    users = (await db.execute(select(User))).scalars().all()
    departments = dict((await db.execute(select(Department.id, Department.code))).all())
    assignees = {}
    if tasks:
        for task_id, user_id in (await db.execute(select(TaskAssignee.task_id, TaskAssignee.user_id).where(
            TaskAssignee.task_id.in_({task.id for task in tasks})
        ))).all():
            assignees.setdefault(task_id, set()).add(user_id)
        await apply_weekly_planner_task_order(db, tasks, assignees, departments)
        names = {user.id: user.full_name or user.username or user.email for user in users}
        tasks = sort_tasks_for_report(tasks, names, assignees)
    return tasks, users, departments, assignees


async def reorder_saved_report_tasks(db: AsyncSession, row: M1ReportingPointsReport) -> bool:
    data = row.data or {}
    if row.sent_at or data.get("task_order_version") == 1:
        return False
    task_ids = set()
    for saved in data.get("tasks") or []:
        try:
            task_ids.add(uuid.UUID(str(saved["id"])))
        except (KeyError, TypeError, ValueError):
            pass
    tasks = (await db.execute(select(Task).where(Task.id.in_(task_ids)))).scalars().all() if task_ids else []
    tasks, _, _, _ = await prepare_task_context(db, tasks)
    row.data = reorder_saved_task_rows(data, [str(task.id) for task in tasks])
    return True


def needs_saved_task_planning(row: M1ReportingPointsReport) -> bool:
    return row.report_date == datetime.now(report_timezone()).date() and any(
        not task.get("planned_for") or "start_date" not in task for task in (row.data or {}).get("tasks") or [])


async def backfill_saved_task_planning(db: AsyncSession, row: M1ReportingPointsReport) -> bool:
    if not needs_saved_task_planning(row):
        return False
    saved_rows = (row.data or {}).get("tasks") or []
    ids = set()
    for saved in saved_rows:
        if not saved.get("planned_for") or "start_date" not in saved:
            try:
                ids.add(uuid.UUID(str(saved["id"])))
            except (KeyError, TypeError, ValueError):
                pass
    tasks = (await db.execute(select(Task).where(Task.id.in_(ids)))).scalars().all() if ids else []
    by_id = {str(task.id): task for task in tasks}
    updated = []
    for saved in saved_rows:
        task = by_id.get(str(saved.get("id")))
        if not saved.get("planned_for"):
            planning = _task_planning_columns(task, row.report_date) if task else {"planned_for": "Pa të dhëna"}
            saved = {**saved, "planned_for": planning["planned_for"]}
        if "start_date" not in saved:
            saved = {**saved, "start_date": _task_planning_columns(task, row.report_date)["start_date"] if task else None}
        updated.append(saved)
    row.data = {**row.data, "tasks": updated}
    return True


def select_ga_tasks(tasks, events, day: date, *, personal_titles: dict | None = None) -> dict:
    sections = m2.select_task_sections(tasks, events, day, personal_titles=personal_titles)
    return {key: sections[key] for key in ("ga_progress", "delivery")}


async def build_ga_task_data(db: AsyncSession, day: date, cutoff: datetime) -> dict:
    personal_titles = {}
    for model, origin in ((GaNote, Task.ga_note_origin_id), (PlanNote, Task.plan_note_origin_id)):
        personal_titles.update((await db.execute(select(model.id, model.content).join(
            Task, origin == model.id,
        ).where(Task.is_active.is_(True), Task.is_personal.is_(True)))).all())
    return await m3.build_task_data(db, day, section_selector=lambda tasks, events, report_day:
        select_ga_tasks([task for task in tasks if _local(task.created_at) <= cutoff], events, report_day,
                        personal_titles=personal_titles))


async def build_data(db: AsyncSession, day: date, now: datetime | None = None) -> dict:
    note_start, task_start, cutoff = reporting_windows(day, now)
    week_start = day - timedelta(days=day.weekday())
    week_end = week_start + timedelta(days=6)
    entries = (await db.execute(select(CommonEntry).where(
        CommonEntry.category.in_([CommonCategory.absences, CommonCategory.delays]),
        CommonEntry.created_at <= cutoff,
        func.coalesce(CommonEntry.entry_date, func.date(CommonEntry.created_at)) >= week_start,
        func.coalesce(CommonEntry.entry_date, func.date(CommonEntry.created_at)) <= week_end,
    ))).scalars().all()
    ga_notes = (await db.execute(select(GaNote).where(
        GaNote.created_at >= note_start, GaNote.created_at <= cutoff,
        GaNote.is_converted_to_task.is_(False), GaNote.status == GaNoteStatus.OPEN,
    ))).scalars().all()
    tasks = (await db.execute(select(Task).where(Task.created_at >= task_start, Task.created_at <= cutoff))).scalars().all()
    tasks, users, departments, assignees = await prepare_task_context(db, tasks)
    data = select_sections(entries, ga_notes, [], tasks, day, now=cutoff,
                                   users={user.id: user for user in users}, departments=departments, assignees=assignees)
    data["captured_until"] = cutoff.isoformat()
    data["task_order_version"] = 1
    data["note_author_version"] = 1
    data.update(await build_ga_task_data(db, day, cutoff))
    return data


async def get_settings(db: AsyncSession):
    from types import SimpleNamespace
    from app.services.reporting_points_settings import get_delivery_settings, manual_recipients
    settings = await get_delivery_settings(db, "M1")
    return SimpleNamespace(recipients=await manual_recipients(db, "M1", settings))


async def locked_report(db: AsyncSession, day: date, *, wait: bool = True) -> M1ReportingPointsReport | None:
    function = "pg_advisory_xact_lock" if wait else "pg_try_advisory_xact_lock"
    acquired = (await db.execute(text(f"SELECT {function}(hashtext(:key))"),
                                {"key": f"m1_reporting_points|{day.isoformat()}"})).scalar()
    if not wait and not acquired:
        return None
    row = (await db.execute(select(M1ReportingPointsReport).where(M1ReportingPointsReport.report_date == day))).scalar_one_or_none()
    if row is None:
        row = M1ReportingPointsReport(report_date=day, manual_answers={}, data={}, status="DRAFT")
        db.add(row)
        await db.flush()
    return row


async def refresh_report(db: AsyncSession, row: M1ReportingPointsReport, now: datetime | None = None) -> None:
    now = _local(now or datetime.now(report_timezone()))
    if row.report_date != now.date():
        raise ValueError("Raportet historike perdorin te dhenat e ruajtura te asaj dite.")
    row.data = await build_data(db, row.report_date, now)
    row.generated_at = now


def report_payload(row: M1ReportingPointsReport, *, excluded_note_ids: set[str] | None = None) -> dict:
    data = row.data or {}
    notes = [note for note in _px_notes_only(data.get("notes") or [])
             if str(note.get("id")) not in (excluded_note_ids or set())]
    return {"id": str(row.id), "report_date": row.report_date.isoformat(), "subject": subject_for(row.report_date),
            "manual_answers": row.manual_answers or {},
            "data": {**data, "notes": _newest_notes_first(notes), "tasks": _done_last(data.get("tasks") or [])},
            "status": row.status,
            "generated_at": row.generated_at.isoformat() if row.generated_at else None,
            "sent_at": row.sent_at.isoformat() if row.sent_at else None, "last_error": row.last_error}


TABLE_COLUMNS = {
    "absences": [("nr", "NR", 32), ("person", "PERSONI", 120), ("hours", "ORA", 120)],
    "delays": [("nr", "NR", 32), ("person", "PERSONI", 120), ("hours", "ORA", 120)],
    "notes": [("nr", "NR", 32), ("author", "KUSH", 48), ("content", "NOTE", 515),
              ("created", "KRIJUAR", 135)],
    "tasks": [("nr", "NR", 32), ("assignees", "KUSH", 58), ("department", "DEP", 55),
              ("am_pm", "AM/PM", 65), ("task_type", "LLOJI", 65),
              ("title", "DETYRA", 490), ("marker", "SIMBOLI", 60),
              ("planned_for", "PËR KUR", 100), ("created", "KRIJUAR", 135)],
}
TASK_FILLS = {"TODO": "#ffc4ed", "IN_PROGRESS": "#ffff00", "DONE": "#c4fdc4",
              "WAITING_CLIENT": "#e2c15b", "WAITING_CONFIRMATION": "#ffedd5"}


def _created_label(value: str | None) -> str:
    return datetime.fromisoformat(value).astimezone(report_timezone()).strftime("%d.%m.%Y %H:%M") if value else "-"


def _plain_note(value: str | None) -> str:
    return re.sub(r"\[{1,2}/?(?:added|done)\]\]", "", value or "", flags=re.I).strip() or "-"


def _task_title(value: str | None) -> str:
    return next((line.strip() for line in _plain_note(value).splitlines() if line.strip()), "-")


def _note_author_label(value: str | None) -> str:
    name = (value or "").strip()
    return name if re.fullmatch(r"[A-Z]{1,4}", name) else _initials(name)


def _table_rows(report: dict, key: str) -> list[list[dict]]:
    rendered = []
    rows = report.get("data", {}).get(key, [])
    if key == "notes":
        rows = _newest_notes_first(_px_notes_only(rows))
    elif key == "tasks":
        rows = _done_last(rows)
    for index, row in enumerate(rows, 1):
        if key in {"absences", "delays"}:
            hours = (f"{row.get('from') or '08:00'}–{row.get('to') or '23:00'}" if key == "absences" else
                     f"{row.get('start') or '08:00'}–{row.get('until') or '09:00'}")
            values = [str(index), row.get("person") or "-", hours]
            fill = "#fee2e2" if key == "absences" else "#fef3c7"
        elif key == "notes":
            values = [str(index), _note_author_label(row.get("author")), _plain_note(row.get("content")),
                      _created_label(row.get("created_at"))]
            fill = "#dbeafe"
        else:
            values = [str(index), row.get("assignees") or "-", row.get("department") or "-",
                      row.get("am_pm") or "-", row.get("task_type") or "-", _task_title(row.get("title")),
                      row.get("marker") or "-",
                      row.get("planned_for") or "-",
                      _created_label(row.get("created_at"))]
            fill = TASK_FILLS.get(str(row.get("status") or "").upper(), "#ffffff")
        rendered.append([{"text": str(value), "fill": fill, "color": "#000000",
                          "bold": column == (1 if key in {"absences", "delays", "notes"} else 5 if key == "tasks" else -1), "divider": False}
                         for column, value in enumerate(values)])
        if key == "notes":
            runs = marked_note_runs(row.get("content"))
            rendered[-1][2]["text"] = "".join(run["text"] for run in runs) or "-"
            rendered[-1][2]["runs"] = runs
    return rendered


def export_blocks(report: dict) -> list[dict]:
    blocks = [{"kind": "text", "text": TITLE, "level": 1},
              {"kind": "text", "text": f"Data: {report['report_date']}", "level": 0}]
    captured_until = (report.get("data") or {}).get("captured_until")
    if captured_until:
        blocks.append({"kind": "text", "text": f"Gjendja deri më: {_created_label(captured_until)}", "level": 0})
    for key, title in POINTS:
        blocks.append({"kind": "text", "text": title, "level": 2})
        if key in MANUAL_POINTS:
            blocks.append({"kind": "text", "text": report.get("manual_answers", {}).get(key) or "Pa përgjigje", "level": 0})
        elif key == "tasks":
            tasks = report.get("data", {}).get("tasks") or []
            day = date.fromisoformat(report["report_date"])
            for today, caption in ((True, "1. TË KRIJUARA SOT ME START DATE SOT"),
                                   (False, "2. TË KRIJUARA SOT ME START DATE NË DITË TJETËR")):
                group = [task for task in tasks if (semantic_local_day(task.get("start_date")) == day) == today]
                blocks.append({"kind": "text", "text": caption, "level": 3})
                if not today and any(not task.get("start_date") for task in group):
                    blocks.append({"kind": "text", "text": "Përfshihen edhe detyrat pa Start Date.", "level": 0})
                rows = _table_rows({**report, "data": {"tasks": group}}, "tasks")
                blocks.append({"kind": "table", "columns": TABLE_COLUMNS["tasks"], "rows": rows} if rows else
                              {"kind": "text", "text": "Asnjë detyrë.", "level": 0})
        elif key in {"ga_progress", "delivery"}:
            columns = m2.table_columns("ga_progress")
            rows = []
            for index, row in enumerate(report.get("data", {}).get(key) or [], 1):
                fill, color, _ = m3.task_row_appearance(row)
                rows.append([{"text": str(m2.table_value(report, row, column, index, "")),
                              "fill": fill, "color": color, "bold": column in {"title", "marker"},
                              "divider": False} for column, _, _ in columns])
            blocks.append({"kind": "table", "columns": columns, "rows": rows} if rows else
                          {"kind": "text", "text": "Asnjë detyrë.", "level": 0})
        else:
            rows = _table_rows(report, key)
            blocks.append({"kind": "table", "compact": key in {"absences", "delays"}, "columns": TABLE_COLUMNS[key], "rows": rows} if rows else
                          {"kind": "text", "text": "Asnjë të dhënë.", "level": 0})
    return blocks


def render_html(report: dict) -> str:
    parts = ["<!doctype html><html><head><meta charset='utf-8'></head><body style='font-family:Arial,sans-serif;color:#0f172a'>"]
    for block in export_blocks(report):
        if block["kind"] == "text":
            tag = "h1" if block["level"] == 1 else "h3" if block["level"] else "p"
            style = ("background:#f8fafc;border:1px solid #cbd5e1;padding:12px 14px;margin:22px 0 0" if block["level"] == 2 else
                     "white-space:pre-wrap;padding:10px 14px;margin:0;border:1px solid #e2e8f0" if block["level"] == 0 else
                     "margin:0 0 8px")
            parts.append(f"<{tag} style='{style}'>{html.escape(block['text']).replace(chr(10), '<br>')}</{tag}>")
        else:
            total_width = sum(width for _, _, width in block["columns"])
            header = "".join(f"<th width='{round(width * 100 / total_width)}%' style='width:{round(width * 100 / total_width)}%;background:#e2e8f0;border:1px solid #000;padding:7px;text-align:left;direction:ltr;vertical-align:{'bottom' if index < 2 else 'top'};font-size:11px'>{html.escape(label)}</th>"
                             for index, (_, label, width) in enumerate(block["columns"]))
            rows = "".join("<tr>" + "".join(
                f"<td style='background:{cell['fill']};color:{cell['color']};border:1px solid #000;padding:7px;vertical-align:{'bottom' if index < 2 else 'top'};text-align:left;direction:ltr;white-space:pre-wrap;overflow-wrap:anywhere{';font-weight:bold' if cell['bold'] else ''}'>{runs_html(cell['runs']) if cell.get('runs') else html.escape(cell['text']).replace(chr(10), '<br>')}</td>"
                for index, cell in enumerate(row)) + "</tr>" for row in block["rows"])
            table_width = f"{total_width}px" if len(block["columns"]) == 3 else "100%"
            parts.append(f"<table style='border-collapse:collapse;width:{table_width};max-width:100%;table-layout:fixed;font-size:12px'><thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table>")
    return "".join(parts) + "</body></html>"


def render_plain_text(report: dict) -> str:
    return "\n\n".join(block["text"] if block["kind"] == "text" else
                      "\n".join(" | ".join(cell["text"] for cell in row) for row in block["rows"])
                      for block in export_blocks(report))


def report_attachments(report: dict):
    from app.services.m3_reporting_points_attachments import render_docx, render_png, DOCX_MIME
    from app.services.reporting_points_excel import render_xlsx, XLSX_MIME
    blocks = export_blocks(report)
    stem = f"pikat_m1_{report['report_date']}"
    png = render_png(report, blocks=blocks)
    return [(stem + ".docx", render_docx(report, blocks=blocks), DOCX_MIME),
            (stem + ".png", png, "image/png"),
            (stem + ".xlsx", render_xlsx(blocks, sheet_name="PIKAT M1", preview_png=png), XLSX_MIME)]


async def send_report(db, row, recipients, *, automatic: bool = False):
    recipients = normalize_recipients(recipients)
    if not recipients["to"]:
        raise ValueError("Shto te pakten nje marres To ne konfigurimin e M1.")
    report = report_payload(row, excluded_note_ids=await excluded_note_ids(db, row))
    try:
        gmail = GmailService()
        html_body = render_html(report)
        attachments = await asyncio.to_thread(report_attachments, report)
        message = await gmail.send_verified(report["subject"], recipients, render_plain_text(report), html_body,
            attachments=[(f"pikat_m1_{row.report_date.isoformat()}.html", html_body.encode("utf-8"), "text/html"), *attachments])
    except Exception as exc:
        row.status, row.last_error = "FAILED", str(exc)[:2000]
        await db.commit()
        raise
    row.status, row.sent_at = "SENT", datetime.now(report_timezone())
    row.gmail_message_id, row.last_error = message.get("id"), None
    if automatic:
        row.auto_sent_at = row.sent_at
    await db.commit()
