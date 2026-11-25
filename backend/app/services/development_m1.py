import re
import unicodedata
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, update

from app.api.access import ensure_reports_access
from app.api.routers.common_view import _build_common_view, _ka_genti_confirmation_owner
from app.config import settings
from app.models.checklist import Checklist
from app.models.checklist_item import ChecklistItem
from app.models.department import Department
from app.models.enums import ChecklistItemType
from app.models.meeting import Meeting
from app.models.project import Project
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.user import User
from app.services.after_break_report import _belongs_to_day, _is_done, _task_covers_day, load_blue_notes
from app.services.meeting_palette import meeting_report_color
from app.services.meetings_report import (
    _clean_task_title, _effective_task_assignee_ids, _ka_genti_owner, _local_date,
    _m3_am_pm_label, _normalize_report_status,
)
from app.services.morning_report import _marked_task_identity
from app.services.px_note_email import is_email_note_content
from app.services.task_date_window import common_view_task_date_window_filter
from app.services.task_marker import active_one_h_marker
from app.services.task_title_rules import title_has_eight_am_indicator


DEVELOPMENT_CHECKLIST_KEY = "development_internal_meetings"
KA_GENT_TITLE = "Çfarë kemi me KA / Gentin sot?"
M1_TOPICS = (
    ("ka_gent", r"cfare kemi me ka\s*/\s*gentin"),
    ("attendance", r"vones|munges|pushim"),
    ("external", r"takim\w*\s+ext"),
    ("internal_all", r"^\s*takim\w*\s+interne[?\s]*$"),
    ("internal", r"takim\w*\s+int"),
    ("questions", r"(?:pyet|pytj|sqarim).*(?:gent|(?:per|me)\s+ka\b)"),
    ("notes", r"px\s*notes"),
    ("teams", r"\bteams\b|shenim\w*.*(?:trello|grup)"),
    ("visitors", r"vizitor|\bfrg\b"),
    ("physical", r"fizik|simbol\w*\s+f\b"),
    ("plan", r"detyr\w*\s+e\s+(?:secilit|te\s+gjitheve)|am\s*/\s*pm"),
)
TASK_STYLES = {
    "TODO": ("To do", "#FBCFE8", "#DC2626"),
    "IN_PROGRESS": ("In progress", "#FEF3C7", "#CBD5E1"),
    "PAUSED": ("Stopped", "#CBD5E1", "#94A3B8"),
    "DONE": ("Done", "#D4FFE1", "#CBD5E1"),
    "WAITING_CONFIRMATION": ("Waiting confirmation", "#FFEDD5", "#CBD5E1"),
    "WAITING_CLIENT": ("Waiting client", "#E2C15B", "#CBD5E1"),
}


def _task_answer(group, assignees, people_by_id, day):
    task = next((copy for copy in group if not _is_done(copy)), group[0])
    owners = sorted({
        person.full_name or person.username or person.email
        for copy in group for user_id in assignees.get(copy.id, set())
        if (person := people_by_id.get(user_id)) is not None
    }, key=str.casefold)
    labels, status_labels, descriptions, comments, markers = {}, {}, {}, {}, {}
    for copy in group:
        period = _m3_am_pm_label(copy)
        is_system = bool(copy.system_template_origin_id or copy.system_task_slot_id)
        status = "DONE" if _is_done(copy) else _normalize_report_status(copy.status)
        status_label = TASK_STYLES[status][0]
        status_labels[status_label] = None
        start, due = _local_date(copy.start_date), _local_date(copy.due_date)
        personal_owner = _ka_genti_owner(copy) if copy.is_personal else None
        for label in (
            "08:00" if title_has_eight_am_indicator(copy.title, is_system_task=is_system) else None,
            period if period != "-" else None,
            status_label,
            f"Personal me {personal_owner}" if personal_owner else "Personal" if copy.is_personal else None,
            f"Fillimi {start:%d.%m.%Y}" if start else None,
            f"Afati {due:%d.%m.%Y}" if due else None,
            "BLL" if copy.is_bllok else None,
            "R1" if copy.is_r1 else None,
        ):
            if label:
                labels[label] = None
        if copy.description:
            descriptions[copy.description] = None
        if copy.one_h_marker_comment:
            comments[copy.one_h_marker_comment] = None
        for marker in filter(None, (active_one_h_marker(copy) or "").split(",")):
            markers[marker] = markers.get(marker, True) and bool(copy.one_h_marker_by_ga)

    status = "DONE" if _is_done(task) else _normalize_report_status(task.status)
    _, color, border = TASK_STYLES[status]
    start = _local_date(task.start_date)
    if task.is_deadline_important and start and start <= day and status != "DONE":
        color, border = "#FEF2F2", "#DC2626"
    is_system = bool(task.system_template_origin_id or task.system_task_slot_id)
    return {
        "id": str(task.id), "title": _clean_task_title(task.title, is_system_task=is_system),
        "detail": "\n".join(descriptions), "task_assignees": owners,
        "href": f"/tasks/{task.id}", "labels": list(labels), "color": color, "border": border,
        "task_status_labels": list(status_labels),
        "marker": ",".join(markers) or None, "marker_by_ga": bool(markers) and all(markers.values()),
        "marker_comment": "\n".join(comments) or None,
    }


def development_m1_item_sections(items):
    mapped = {}
    for item in items:
        if item.item_type != ChecklistItemType.CHECKBOX or item.day not in {None, "", "M1"}:
            continue
        prefix, _, saved_key = (item.keyword or "").partition(":")
        if prefix == "development-m1" and any(key == saved_key for key, _ in M1_TOPICS):
            mapped[str(item.id)] = saved_key
            continue
        title = unicodedata.normalize("NFKD", (item.title or "").casefold())
        title = "".join(character for character in title if not unicodedata.combining(character))
        if key := next((key for key, pattern in M1_TOPICS if re.search(pattern, title)), None):
            mapped[str(item.id)] = key
    return mapped


async def ensure_development_m1_internal_item(db, checklist_id) -> bool:
    development_id = await db.scalar(select(Checklist.id).where(
        Checklist.id == checklist_id,
        Checklist.group_key == DEVELOPMENT_CHECKLIST_KEY,
    ).with_for_update())
    if development_id is None:
        return False
    items = (await db.scalars(select(ChecklistItem).where(
        ChecklistItem.checklist_id == checklist_id,
    ).order_by(ChecklistItem.position, ChecklistItem.id))).all()
    item_sections = development_m1_item_sections(items)
    if "internal_all" in item_sections.values():
        return False
    external = next((item for item in items if item_sections.get(str(item.id)) == "external"), None)
    if external is None:
        return False
    position = external.position + 1
    await db.execute(update(ChecklistItem).where(
        ChecklistItem.checklist_id == checklist_id,
        ChecklistItem.position >= position,
    ).values(position=ChecklistItem.position + 1))
    db.add(ChecklistItem(
        checklist_id=checklist_id, item_type=ChecklistItemType.CHECKBOX,
        path=external.path, day="M1", title="Takimet interne?",
        keyword="development-m1:internal_all", is_checked=False, position=position,
    ))
    return True


async def build_development_m1(db, user, *, checklist_items=None):
    ensure_reports_access(user)
    department = await db.scalar(select(Department).where(Department.code == "DEV"))
    if department is None:
        return None
    if checklist_items is None:
        checklist_items = (await db.scalars(
            select(ChecklistItem).join(Checklist).where(Checklist.group_key == DEVELOPMENT_CHECKLIST_KEY)
        )).all()

    now = datetime.now(timezone.utc)
    local_now = now.astimezone(ZoneInfo(settings.APP_TIMEZONE))
    day = local_now.date()
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    date_key = day.isoformat()
    people = (await db.scalars(select(User).where(User.work_staff_filter()))).all()
    people_by_id = {person.id: person for person in people}
    team_ids = {person.id for person in people if person.department_id == department.id}
    team = {str(user_id) for user_id in team_ids}
    ka_ids = {str(person.id) for person in people if _ka_genti_confirmation_owner(person) == "KA"}

    common = await _build_common_view(db, week_start=day, include="entries,meetings",
                                      include_all_departments=True, max_items_per_bucket=5000)
    if any(common.guardrails.truncated.values()):
        raise HTTPException(status_code=503, detail="Common View data is incomplete")
    buckets = common.items

    attendance = []
    for bucket, rows, start, end, color, border in (
        ("Mungesë", buckets.absent, "from", "to", "#FFE9E9", "#EF4444"),
        ("Vonesë", buckets.late, "start", "until", "#FFF4E6", "#F59E0B"),
        ("Pushim", buckets.leave, "from", "to", "#E9F9EF", "#22C55E"),
    ):
        for row in rows:
            applies = (
                row["startDate"] <= date_key <= row["endDate"]
                if bucket == "Pushim" else row["date"] == date_key
            )
            if applies and (row.get("userId") in team or row.get("isAllUsers")):
                hours = "08:00–16:30 · Gjithë ditën" if row.get("fullDay") else "–".join(
                    value for key in (start, end) if (value := row.get(key))
                )
                attendance.append({
                    "id": row["id"],
                    "title": "Të gjithë" if row.get("isAllUsers") else row["person"],
                    "detail": row.get("note") or "",
                    "labels": list(filter(None, (bucket, hours))),
                    "color": color,
                    "border": border,
                })

    external, internal, internal_with_ka = [], [], []
    today_meetings = [
        row for row in [*buckets.external, *buckets.internal]
        if row["id"].startswith("meeting:") and row["date"] == date_key
    ]
    meeting_ids = {row["id"]: UUID(row["id"].split(":")[1]) for row in today_meetings}
    meeting_meta = {
        meeting_id: (owner, url)
        for meeting_id, owner, url in (await db.execute(
            select(Meeting.id, Meeting.created_by, Meeting.meeting_url).where(Meeting.id.in_(meeting_ids.values()))
        )).all()
    } if meeting_ids else {}
    external_ids = {row["id"] for row in buckets.external}
    for row in sorted(today_meetings, key=lambda row: row.get("time") or ""):
        owner_id, url = meeting_meta.get(meeting_ids[row["id"]], (None, None))
        owner = str(owner_id)
        participants = set(row.get("assigneeUserIds") or [])
        is_external = row["id"] in external_ids
        if not is_external:
            is_development = row.get("department") == department.name or owner in team or team.intersection(participants)
            involves_ka = owner in ka_ids or ka_ids.intersection(participants)
        status = {"held": "Mbajtur", "canceled": "Anuluar"}.get(row.get("occurrenceStatus"))
        relation = "PARA" if row.get("preExternalMeetingId") else "PAS" if row.get("pairedExternalMeetingId") else None
        calendar = row.get("calendarImported") if is_external else row.get("linkedExternalCalendarImported")
        source = "CAL" if calendar else "MANUAL" if not is_external and not relation else None
        recurrence = row.get("recurrence_type")
        labels = [row.get("time"), row.get("platform"), source, relation, status]
        if recurrence and recurrence != "none":
            labels.append(recurrence)
        labels.extend(row.get("calendarCategories") or row.get("linkedExternalCalendarCategories") or [])
        names = ", ".join(row.get("assignees") or [])
        item = {
            "id": row["id"],
            "title": row["title"],
            "detail": " · ".join(filter(None, (
                row.get("department"),
                f"Organizues: {row['owner']}" if row.get("owner") else None,
                f"Pjesëmarrës: {names}" if names else None,
            ))),
            "labels": list(filter(None, labels)),
            "meeting": {
                "id": str(meeting_ids[row["id"]]),
                "date": row["date"],
                "type": "external" if is_external else "internal",
                **{key: row[key] for key in (
                    "time", "recurrence_type", "calendarImported", "calendarCategories",
                    "pairedExternalMeetingId", "preExternalMeetingId", "linkedExternalCalendarImported",
                    "linkedExternalCalendarCategories", "linkedExternalRecurrenceType", "occurrenceStatus",
                ) if key in row},
            },
            "color": meeting_report_color(row, meeting_type="external" if is_external else "internal"),
            "canceled": status == "Anuluar",
        }
        if url and url.lower().startswith(("https://", "http://")):
            item["meeting_url"] = url
        (external if is_external else internal).append(item)
        if not is_external and is_development and involves_ka:
            internal_with_ka.append(item)

    tasks = (await db.scalars(select(Task).where(
        Task.work_staff_filter(),
        Task.is_active.is_(True),
        or_(
            common_view_task_date_window_filter(day - timedelta(days=1), day + timedelta(days=1)),
            and_(Task.completed_at >= day_start, Task.completed_at < day_start + timedelta(days=1)),
        ),
        or_(
            Task.department_id == department.id,
            Task.project_id.in_(select(Project.id).where(Project.department_id == department.id)),
            Task.assigned_to.in_(team_ids),
            Task.id.in_(select(TaskAssignee.task_id).where(TaskAssignee.user_id.in_(team_ids))),
        ),
    ).order_by(Task.title, Task.id))).all()
    planned_ids = {task.id for task in tasks if _belongs_to_day(task, day)}
    tasks = [task for task in tasks if task.id in planned_ids or _task_covers_day(task, day)]
    assignees = await _effective_task_assignee_ids(db, tasks)
    questions, physical = {}, {}
    for task in tasks:
        markers = set((active_one_h_marker(task) or "").split(","))
        personal_owner = _ka_genti_owner(task) if task.is_personal else None
        planned = task.id in planned_ids
        has_question = bool(markers & {"KA", "GENT"}) and _task_covers_day(task, day)
        personal = planned and personal_owner
        is_physical = planned and "F" in markers
        identity = _marked_task_identity(task)
        if has_question or personal:
            questions.setdefault(identity, []).append(task)
        if is_physical:
            physical.setdefault(identity, []).append(task)

    notes = []
    for note_id, (_, _, content, author, created) in await load_blue_notes(db, created_before=now):
        note = {"id": note_id, "title": content, "detail": " · ".join(filter(None, (author, created))), "color": "#E0F2FE"}
        if is_email_note_content(content):
            # The report preview appends the original subject and sender after the saved title.
            note["email_heading"] = content.partition(" · ")[0].partition(" Dërguesi:")[0]
        notes.append(note)
    sections = [
        ("attendance", "Vonesa, mungesa dhe pushime", attendance, "Ndryshimet e planit diskutohen në takim."),
        ("external", "Takime externe", external, None),
        ("internal_all", "Takime interne", internal, None),
        ("internal", "Takime interne me KA", internal_with_ka, None),
        ("questions", "Pyetje për KA / Gentin", [_task_answer(group, assignees, people_by_id, day) for group in questions.values()], None),
        ("teams", "Shënime në Teams Zhvillim", [], "Pikë manuale. Microsoft Graph nuk lexon bisedat e Teams Personal."),
        ("notes", "PX Notes të padiskutuara", notes, None),
        ("visitors", "EF/RA · FRG · Vizitorë të rinj", [], "Pikë për diskutim në takim."),
        ("plan", "Diskutohen detyrat e secilit për AM / PM", [], "Pikë për diskutim në takim."),
        ("physical", "Detyrat fizike me simbolin F", [_task_answer(group, assignees, people_by_id, day) for group in physical.values()], None),
    ]
    item_sections = development_m1_item_sections(checklist_items)
    ka_gent_items = sorted(
        (item for item in checklist_items if item_sections.get(str(item.id)) in {"internal", "questions", "ka_gent"}),
        key=lambda item: (item.position or 0, str(item.id)),
    )
    hidden_item_ids = []
    first_by_topic = {}
    for item in ka_gent_items:
        first_by_topic.setdefault(item_sections[str(item.id)], item)
    if "ka_gent" in first_by_topic or {"internal", "questions"} <= first_by_topic.keys():
        primary = first_by_topic.get("ka_gent", ka_gent_items[0])
        primary_id = str(primary.id)
        title = primary.title if item_sections[primary_id] == "ka_gent" and primary.title else KA_GENT_TITLE
        item_sections[primary_id] = "ka_gent"
        hidden_item_ids = [str(item.id) for item in first_by_topic.values() if item.id != primary.id]
        combined_rows = []
        for key, heading in (("internal", "Takimet interne me KA"), ("questions", "Pyetjet dhe detyrat për KA / Gentin")):
            rows = next(rows for section_key, _, rows, _ in sections if section_key == key)
            combined_rows.append({"id": key, "title": heading, "detail": "", "heading": True})
            combined_rows.extend(rows or [{"id": f"{key}-empty", "title": "Nuk ka për sot.", "detail": ""}])
        sections.append(("ka_gent", title, combined_rows, None))
    return {
        "date": date_key,
        "item_sections": item_sections,
        "hidden_item_ids": hidden_item_ids,
        "sections": [
            {"key": key, "title": title, "rows": rows, "message": message}
            for key, title, rows, message in sections
        ],
    }
