import re
import unicodedata
from datetime import datetime, time
from urllib.parse import urlsplit

from sqlalchemy import select

from app.api.access import ensure_reports_access
from app.models.checklist import Checklist
from app.models.checklist_item import ChecklistItem
from app.models.department import Department
from app.models.enums import ChecklistItemType
from app.models.task import Task
from app.models.user import User
from app.services.after_break_report import load_blue_notes, load_new_email_mailboxes
from app.services.development_m1 import (
    DEVELOPMENT_CHECKLIST_KEY, _task_answer, development_note_answer, select_development_report_tasks,
)
from app.services.m2_reporting_points import DELIVERY_MARKERS, is_m2_delivery_task
from app.services.meetings_report import _effective_task_assignee_ids
from app.services.morning_report import _marked_task_identity
from app.services.primeflow_report import report_timezone
from app.services.report_inboxes import report_mailbox


M2_TOPICS = {
    "emails": r"\b(?:e[- ]?mails?|imell\w*|imejl\w*|emaill\w*)\b.*\b(?:it|std)\b",
    "notes": r"px\s*notes|ai\s*agents?\s*teams|shenim\w*.*\b(?:ga/ka|trello|teams)\b",
    "delivery": r"dorez\w*.*\bga\b",
}


def development_m2_item_sections(items):
    mapped = {}
    for item in items:
        if item.item_type != ChecklistItemType.CHECKBOX or item.day != "M2":
            continue
        prefix, _, key = (item.keyword or "").partition(":")
        if prefix == "development-m2" and key in M2_TOPICS:
            mapped[str(item.id)] = key
            continue
        title = unicodedata.normalize("NFKD", (item.title or "").casefold())
        title = "".join(character for character in title if not unicodedata.combining(character))
        if key := next((key for key, pattern in M2_TOPICS.items() if re.search(pattern, title)), None):
            mapped[str(item.id)] = key
    return mapped


async def _email_section(day, cutoff):
    mailbox = report_mailbox("it")
    end_label = cutoff.strftime("%H:%M")
    section = {"key": "emails", "title": "Email-et IT/STD", "rows": []}
    if cutoff.time() < time(8):
        return {**section, "message": "Kontrolli i email-eve fillon në 08:00."}
    inboxes = await load_new_email_mailboxes(day, cutoff, sources=("it",))
    inbox = inboxes.get("it", {})
    if inbox.get("configured") is False:
        return {**section, "message": f"Kutia {mailbox.email} nuk është konfiguruar në këtë server."}
    if not inbox.get("connected") or inbox.get("error"):
        return {**section, "message": inbox.get("error") or f"Kutia {mailbox.email} nuk është e lidhur."}
    messages = sorted(inbox["messages"], key=lambda message: message["received_datetime"], reverse=True)
    for message in messages:
        row = {"id": message["id"], "title": message["subject"], "detail": message["sender"],
               "labels": [message["received_at"]]}
        if url := message.get("original_email_url"):
            try:
                parsed = urlsplit(url)
                if parsed.scheme in {"http", "https"} and parsed.hostname:
                    row["href"] = url
            except ValueError:
                pass
        section["rows"].append(row)
    count = len(messages)
    return {**section, "message": f"{count} email-e në {mailbox.email} · 08:00–{end_label}."}


async def _delivery_rows(db, department, day):
    people = (await db.scalars(select(User).where(User.work_staff_filter()))).all()
    people_by_id = {person.id: person for person in people}
    team_ids = {person.id for person in people if person.department_id == department.id}
    tasks = (await db.scalars(select_development_report_tasks(department.id, team_ids).where(
        Task.one_h_marker.in_(DELIVERY_MARKERS),
    ).order_by(Task.title, Task.id))).all()
    tasks = [task for task in tasks if is_m2_delivery_task(task, day)]
    assignees = await _effective_task_assignee_ids(db, tasks)
    groups = {}
    for task in tasks:
        groups.setdefault(_marked_task_identity(task), []).append(task)
    return [_task_answer(group, assignees, people_by_id, day) for group in groups.values()]


async def build_development_m2(db, user, *, checklist_items=None):
    ensure_reports_access(user)
    department = await db.scalar(select(Department).where(Department.code == "DEV"))
    if department is None:
        return None
    if checklist_items is None:
        checklist_items = (await db.scalars(select(ChecklistItem).join(Checklist).where(
            Checklist.group_key == DEVELOPMENT_CHECKLIST_KEY,
            ChecklistItem.day == "M2",
        ))).all()
    item_sections = development_m2_item_sections(checklist_items)
    active_sections = set(item_sections.values())
    now = datetime.now(report_timezone())
    day = now.date()
    start = now.replace(hour=8, minute=0, second=0, microsecond=0)
    cutoff = min(now, start.replace(hour=12))
    sections = []
    if "emails" in active_sections:
        sections.append(await _email_section(day, cutoff))
    if "notes" in active_sections:
        notes = await load_blue_notes(db, created_from=start, created_before=cutoff) if cutoff >= start else []
        sections.append({
            "key": "notes",
            "title": "PX Notes të reja",
            "rows": [{
                **development_note_answer(note_id, values),
                "href": f"/ga-ka-notes#ga-note-content-{note_id}",
            } for note_id, values in notes],
            "message": ("Teams kontrollohet në takim." if notes else
                        "S’ka PX Notes të reja të padiskutuara në këtë interval. Teams kontrollohet në takim."),
        })
    if "delivery" in active_sections:
        sections.append({
            "key": "delivery",
            "title": "Detyrat për dorëzim te GA",
            "rows": await _delivery_rows(db, department, day),
            "message": None,
        })
    return {"date": day.isoformat(), "cutoff": cutoff.strftime("%H:%M"),
            "item_sections": item_sections, "sections": sections}
