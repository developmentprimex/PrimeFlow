import re
import unicodedata
from datetime import datetime

from sqlalchemy import select

from app.api.access import ensure_reports_access
from app.models.checklist import Checklist
from app.models.checklist_item import ChecklistItem
from app.models.department import Department
from app.models.enums import ChecklistItemType
from app.models.task import Task
from app.models.user import User
from app.services.after_break_report import load_blue_notes
from app.services.daily_realization_events import semantic_local_day
from app.services.development_m1 import (
    DEVELOPMENT_CHECKLIST_KEY, _task_answer, development_meeting_rows, development_note_answer,
    load_development_common_view, select_development_report_tasks,
)
from app.services.meetings_report import _effective_task_assignee_ids, next_working_day
from app.services.morning_report import _marked_task_identity
from app.services.primeflow_report import report_timezone
from app.services.task_marker import active_one_h_marker


M3_TOPICS = {
    "notes": r"px\s*notes|shenim\w*.*(?:teams|trello|grup)",
    "leave": r"\bpv\b|pushim\w*",
    "delivery": r"\bdoc\b|dorez\w*|simbol\w*.*common\s*view",
    "internal": r"takim\w*\s+int",
    "external": r"takim\w*\s+ext",
}
DELIVERY_MARKERS = {"M3", "M2_M3"}
INTERNAL_MEETINGS_TITLE = "A ka takime interne për nesër?"
LEGACY_INTERNAL_TITLE = re.compile(r"a ka takime interne me ga\s*/\s*ka\s*/\s*gent(?:in?)?\s*\??")


def development_m3_item_sections(items):
    mapped = {}
    for item in items:
        if item.item_type != ChecklistItemType.CHECKBOX or item.day != "M3":
            continue
        prefix, _, saved_key = (item.keyword or "").partition(":")
        if prefix == "development-m3" and saved_key in M3_TOPICS:
            mapped[str(item.id)] = saved_key
            continue
        title = unicodedata.normalize("NFKD", (item.title or "").casefold())
        title = "".join(character for character in title if not unicodedata.combining(character))
        if key := next((key for key, pattern in M3_TOPICS.items() if re.search(pattern, title)), None):
            mapped[str(item.id)] = key
    return mapped


def _leave_rows(buckets, day, team):
    date_key = day.isoformat()
    for row in buckets.leave:
        if not (row["startDate"] <= date_key <= row["endDate"]):
            continue
        if row.get("userId") not in team and not row.get("isAllUsers"):
            continue
        hours = "08:00–16:30 · Gjithë ditën" if row.get("fullDay") else "–".join(
            value for key in ("from", "to") if (value := row.get(key))
        )
        yield {
            "id": f"{row['id']}:{date_key}",
            "title": "Të gjithë" if row.get("isAllUsers") else row["person"],
            "detail": row.get("note") or "",
            "labels": list(filter(None, (day.strftime("%d.%m.%Y"), hours))),
            "color": "#E9F9EF", "border": "#22C55E",
        }


async def _delivery_rows(db, department, day, people_by_id, team_ids):
    tasks = (await db.scalars(select_development_report_tasks(department.id, team_ids).where(
        Task.one_h_marker.in_(DELIVERY_MARKERS),
    ).order_by(Task.title, Task.id))).all()
    groups = {}
    eligible = []
    for task in tasks:
        start, due, created = map(semantic_local_day, (task.start_date, task.due_date, task.created_at))
        if (active_one_h_marker(task, day) in DELIVERY_MARKERS and start and due
                and start <= day <= due and (created is None or created <= day)):
            eligible.append(task)
            groups.setdefault(_marked_task_identity(task), []).append(task)
    assignees = await _effective_task_assignee_ids(db, eligible)
    return [_task_answer(group, assignees, people_by_id, day) for group in groups.values()]


async def build_development_m3(db, user, *, checklist_items=None):
    ensure_reports_access(user)
    department = await db.scalar(select(Department).where(Department.code == "DEV"))
    if department is None:
        return None
    if checklist_items is None:
        checklist_items = (await db.scalars(select(ChecklistItem).join(Checklist).where(
            Checklist.group_key == DEVELOPMENT_CHECKLIST_KEY,
            ChecklistItem.day == "M3",
        ))).all()
    item_sections = development_m3_item_sections(checklist_items)
    item_titles = {
        str(item.id): INTERNAL_MEETINGS_TITLE
        for item in checklist_items
        if item_sections.get(str(item.id)) == "internal"
        and LEGACY_INTERNAL_TITLE.fullmatch((item.title or "").strip().casefold())
    }
    active_sections = set(item_sections.values())
    now = datetime.now(report_timezone())
    day = now.date()
    tomorrow = next_working_day(day)
    following_day = next_working_day(tomorrow)
    sections = []

    def add_section(key, title, rows, empty_message):
        if key in active_sections:
            sections.append({"key": key, "title": title, "rows": rows, "message": None if rows else empty_message})

    if "notes" in active_sections:
        notes = await load_blue_notes(db, created_before=now)
        add_section("notes", "PX Notes të padiskutuara", [
            development_note_answer(note_id, values) for note_id, values in notes
        ], "Jo")

    if active_sections & {"leave", "delivery"}:
        people = (await db.scalars(select(User).where(User.work_staff_filter()))).all()
        people_by_id = {person.id: person for person in people}
        team_ids = {person.id for person in people if person.department_id == department.id}
        team = {str(user_id) for user_id in team_ids}

    buckets = await load_development_common_view(db, tomorrow) if active_sections & {"leave", "internal", "external"} else None
    if "leave" in active_sections:
        following_buckets = (buckets if following_day.weekday() > tomorrow.weekday()
                             else await load_development_common_view(db, following_day))
        add_section("leave", "Pushimet në dy ditët e ardhshme të punës", [
            *_leave_rows(buckets, tomorrow, team), *_leave_rows(following_buckets, following_day, team),
        ], "Nuk ka pushime.")

    if "delivery" in active_sections:
        delivery = await _delivery_rows(db, department, day, people_by_id, team_ids)
        add_section("delivery", "Detyrat për dorëzim te KA / GA", delivery, "Jo")

    if active_sections & {"internal", "external"}:
        external, internal, _ = await development_meeting_rows(db, buckets, tomorrow.isoformat())
        add_section("internal", INTERNAL_MEETINGS_TITLE, internal, "Jo")
        add_section("external", "Takimet externe për nesër", external, "Nuk ka takime.")

    return {"date": day.isoformat(), "item_sections": item_sections, "item_titles": item_titles, "sections": sections}
