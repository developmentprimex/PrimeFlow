from __future__ import annotations

from app.services.report_attendance import filter_task_context, filter_report_sections

import re
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.department import Department
from app.models.ga_note import GaNote
from app.models.meeting import Meeting
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.models.plan_note import PlanNote
from app.models.task import Task
from app.models.user import User
from app.services.after_break_report import _ascii_table, _task_covers_day
from app.services.meeting_palette import meeting_report_tone
from app.services.microsoft_calendar_sync import is_common_view_visible_meeting
from app.services.meetings_report import (
    _assignee_names,
    _clean_task_title,
    _effective_task_assignee_ids,
    _initials,
    _is_open,
    _local_date,
    _local_time,
    _m3_am_pm_label,
    _m3_department_label,
    _m3_task_type_label,
    _normalize_report_status,
    _render_section_block_html,
    _task_owners,
    _wrap_report_email_html,
    apply_weekly_planner_task_order,
    common_view_task_sort_key,
    send_section_report,
    _meeting_occurs_on_date,
    TECHNICAL_TAG,
)
from app.services.task_title_rules import title_has_eight_am_indicator
from app.services.personal_task_owner import personal_task_owner

REPORT_TYPE = "end_week_bz_report"
REPORT_LABEL = "PIKAT E BZ FIN JAV"
SECTION_TITLES = [
    "PERSONAL TASKS",
    "WFC TASKS",
    "TASKS WITH DEADLINE",
    "R1 TASKS",
    "08:00 TASKS",
    "EXTERNAL/INTERNAL MEETINGS",
]

PERSONAL_COLUMNS = [("NR", 2), ("WHO", 12), ("DEP", 5), ("AM/PM", 5), ("TITLE", 48), ("STATUS", 20)]
WFC_COLUMNS = [("NR", 2), ("WHO", 12), ("TYPE", 7), ("DEP", 5), ("AM/PM", 5), ("TITLE", 42), ("STATUS", 20)]
DEADLINE_COLUMNS = [("NR", 2), ("WHO", 12), ("TYPE", 7), ("DEP", 5), ("AM/PM", 5), ("TITLE", 38), ("DEADLINE", 16), ("STATUS", 20)]
R1_COLUMNS = [("NR", 2), ("WHO", 12), ("DEP", 5), ("AM/PM", 5), ("TITLE", 45), ("DUE DATE", 16), ("STATUS", 20)]
EIGHT_AM_COLUMNS = [("NR", 2), ("WHO", 12), ("TYPE", 7), ("DEP", 5), ("AM/PM", 5), ("TITLE", 38), ("DUE DATE", 16), ("STATUS", 20)]
MEETING_COLUMNS = [("NR", 2), ("WHO", 14), ("TIME", 11), ("TITLE", 42), ("RECURRENCE", 10), ("STATUS", 10)]
def subject_for(day: date) -> str:
    return f"{REPORT_LABEL} - {day:%d.%m.%Y}"


def _due_text(task: Task) -> str:
    if not task.due_date:
        return "-"
    local_day = _local_date(task.due_date)
    if not local_day:
        return "-"
    # Date-only task deadlines are persisted as midnight UTC. Do not expose
    # their timezone conversion as a misleading 02:00 deadline.
    if task.due_date.hour == 0 and task.due_date.minute == 0:
        return f"{local_day:%d.%m.%Y}"
    return f"{local_day:%d.%m.%Y} {_local_time(task.due_date)}"


def _first_visible_line(value: str | None) -> str:
    cleaned = TECHNICAL_TAG.sub("", str(value or ""))
    return next((line.strip() for line in cleaned.splitlines() if line.strip()), "")


def _personal_group(task: Task, display_title: str | None = None) -> str:
    # This is intentionally identical to Common View's getPersonalTaskGroup:
    # classify the first visible line of the resolved note/task display title.
    return personal_task_owner(_first_visible_line(display_title or task.title))


def _is_wfc_task(task: Task) -> bool:
    return _is_open(task) and _normalize_report_status(task.status) in {
        "WAITING_CLIENT", "WAITING_CONFIRMATION",
    }


def _task_rows(
    tasks: list[Task], names: dict[Any, str], assignees: dict[Any, set[Any]],
    departments: dict[Any, str], columns: list[tuple[str, int]],
    display_titles: dict[Any, str] | None = None,
) -> list[list[str]]:
    rows: list[list[str]] = []
    for index, task in enumerate(sorted(tasks, key=lambda item: common_view_task_sort_key(item, names, assignees)), 1):
        values = {
            "NR": str(index),
            "WHO": _task_owners(task, names, assignees),
            "TYPE": _m3_task_type_label(task),
            "DEP": _m3_department_label(task, departments),
            "AM/PM": _m3_am_pm_label(task),
            "TITLE": _first_visible_line((display_titles or {}).get(task.id) or task.title) or "-",
            "DEADLINE": _due_text(task),
            "DUE DATE": _due_text(task),
            "STATUS": _normalize_report_status(task.status),
        }
        rows.append([values[name] for name, _ in columns])
    return rows


def _meeting_recurrence(meeting: Meeting) -> str:
    value = str(meeting.recurrence_type or "none").strip().upper()
    return value if value and value != "NONE" else "ONE-TIME"


def _meeting_rows(
    meetings: list[Meeting], status_by_meeting: dict[Any, str], participant_names: dict[Any, str]
) -> list[list[str]]:
    rows: list[list[str]] = []
    ordered = sorted(meetings, key=lambda item: (_local_time(item.starts_at), (item.title or "").casefold()))
    for index, meeting in enumerate(ordered, 1):
        owners = sorted({
            _initials(participant_names.get(participant.user_id))
            for participant in (meeting.participants or [])
            if _initials(participant_names.get(participant.user_id)) != "-"
        })
        title = f"{_clean_task_title(meeting.title)} [[mc:{meeting_report_tone(meeting)}]]"
        recurrence = _meeting_recurrence(meeting)
        if recurrence not in {"DAILY", "WEEKLY", "MONTHLY"}:
            title = f"{title} [[mt:non_daily_weekly]]"
        rows.append([
            str(index), " ".join(owners) or "-", _local_time(meeting.starts_at),
            title, recurrence,
            str(status_by_meeting.get(meeting.id) or "PLANNED").upper(),
        ])
    return rows


def normalize_sections(sections: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    by_key = {str(item.get("section_key") or item.get("title") or ""): item for item in sections or []}
    return [{
        "section_key": title,
        "title": str(by_key.get(title, {}).get("title") or title),
        "body": str(by_key.get(title, {}).get("body") or f"{title}: 0"),
    } for title in SECTION_TITLES]


async def build_end_week_bz_report_sections(db: AsyncSession, report_day: date) -> tuple[list[dict[str, str]], dict[str, Any]]:
    tasks = (await db.execute(select(Task).where(Task.work_staff_filter()).where(Task.is_active.is_(True)))).scalars().all()
    names = await _assignee_names(db, tasks)
    assignees = await _effective_task_assignee_ids(db, tasks)
    tasks, names, assignees = await filter_task_context(db, report_day, tasks, names, assignees)
    await apply_weekly_planner_task_order(db, tasks, assignees)
    departments = dict((await db.execute(select(Department.id, Department.code))).all())
    open_for_day = [task for task in tasks if _is_open(task) and _task_covers_day(task, report_day)]

    ga_note_ids = {task.ga_note_origin_id for task in tasks if task.ga_note_origin_id}
    plan_note_ids = {task.plan_note_origin_id for task in tasks if task.plan_note_origin_id}
    ga_note_titles = dict((await db.execute(select(GaNote.id, GaNote.content).where(GaNote.id.in_(ga_note_ids)))).all()) if ga_note_ids else {}
    plan_note_titles = dict((await db.execute(select(PlanNote.id, PlanNote.content).where(PlanNote.id.in_(plan_note_ids)))).all()) if plan_note_ids else {}
    display_titles = {
        task.id: str(ga_note_titles.get(task.ga_note_origin_id) or plan_note_titles.get(task.plan_note_origin_id) or task.title or "")
        for task in tasks
    }

    # Common View moves WAITING_CLIENT rows out of P: GA/KA/PX into its WFC
    # lane. Keep the weekly report's personal buckets identical.
    personal = [
        task for task in open_for_day
        if task.is_personal and _normalize_report_status(task.status) != "WAITING_CLIENT"
    ]
    waiting = [task for task in tasks if _is_wfc_task(task)]
    deadline = [task for task in open_for_day if task.is_deadline_important]
    r1 = [task for task in open_for_day if task.is_r1]
    at_eight = [
        task
        for task in open_for_day
        if title_has_eight_am_indicator(
            task.title,
            is_system_task=bool(getattr(task, "system_template_origin_id", None) or getattr(task, "system_task_slot_id", None)),
        )
        or _local_time(task.due_date) == "08:00"
    ]

    meetings = (await db.execute(select(Meeting).options(selectinload(Meeting.participants)).where(Meeting.starts_at.is_not(None)))).scalars().unique().all()
    meetings = [meeting for meeting in meetings if is_common_view_visible_meeting(meeting)]
    meetings = [meeting for meeting in meetings if _meeting_occurs_on_date(meeting, report_day)]
    statuses = (await db.execute(select(MeetingOccurrenceStatus).where(MeetingOccurrenceStatus.occurrence_date == report_day))).scalars().all()
    status_map = {row.meeting_id: row.status for row in statuses}
    participant_ids = {participant.user_id for meeting in meetings for participant in (meeting.participants or [])}
    participant_names: dict[Any, str] = {}
    if participant_ids:
        users = (await db.execute(select(User).where(User.work_staff_filter()).where(User.id.in_(participant_ids)))).scalars().all()
        participant_names = {user.id: user.full_name or user.username or user.email for user in users}

    personal_lines: list[str] = []
    counts: dict[str, int] = {}
    for group in ("KA", "GENT", "GA", "PX"):
        grouped = [task for task in personal if _personal_group(task, display_titles.get(task.id)) == group]
        if personal_lines:
            personal_lines.append("")
        personal_lines.extend(_ascii_table(f"P: {group}", PERSONAL_COLUMNS, _task_rows(grouped, names, assignees, departments, PERSONAL_COLUMNS, display_titles)))
        counts[f"P: {group}"] = len(grouped)

    wfc_lines: list[str] = []
    for label, status in (("WFE", "WAITING_CLIENT"), ("WAITING CONFIRMATION", "WAITING_CONFIRMATION")):
        grouped = [task for task in waiting if _normalize_report_status(task.status) == status]
        if wfc_lines:
            wfc_lines.append("")
        wfc_lines.extend(_ascii_table(label, WFC_COLUMNS, _task_rows(grouped, names, assignees, departments, WFC_COLUMNS)))
        counts[label] = len(grouped)

    external = [meeting for meeting in meetings if str(meeting.meeting_type or "").lower() == "external"]
    internal = [meeting for meeting in meetings if str(meeting.meeting_type or "").lower() != "external"]
    meeting_lines = [
        *_ascii_table("TAK EXT", MEETING_COLUMNS, _meeting_rows(external, status_map, participant_names)), "",
        *_ascii_table("TAK INT", MEETING_COLUMNS, _meeting_rows(internal, status_map, participant_names)),
    ]
    bodies = {
        SECTION_TITLES[0]: "\n".join(personal_lines),
        SECTION_TITLES[1]: "\n".join(wfc_lines),
        SECTION_TITLES[2]: "\n".join(_ascii_table(SECTION_TITLES[2], DEADLINE_COLUMNS, _task_rows(deadline, names, assignees, departments, DEADLINE_COLUMNS, display_titles))),
        SECTION_TITLES[3]: "\n".join(_ascii_table(SECTION_TITLES[3], R1_COLUMNS, _task_rows(r1, names, assignees, departments, R1_COLUMNS))),
        SECTION_TITLES[4]: "\n".join(_ascii_table(SECTION_TITLES[4], EIGHT_AM_COLUMNS, _task_rows(at_eight, names, assignees, departments, EIGHT_AM_COLUMNS, display_titles))),
        SECTION_TITLES[5]: "\n".join(meeting_lines),
    }
    counts.update({SECTION_TITLES[2]: len(deadline), SECTION_TITLES[3]: len(r1), SECTION_TITLES[4]: len(at_eight), "TAK EXT": len(external), "TAK INT": len(internal)})
    sections = [{"section_key": title, "title": title, "body": bodies[title]} for title in SECTION_TITLES]
    return await filter_report_sections(db, sections, report_day), {"report_day": report_day.isoformat(), "counts": counts}


def render_plain_text(subject: str, report_day: date, sections: list[dict[str, str]]) -> str:
    return "\n\n".join([subject, f"Data: {report_day:%d.%m.%Y}", *[f"{index}. {section['title']}\n{section['body']}" for index, section in enumerate(sections, 1)]])


def render_html(subject: str, report_day: date, sections: list[dict[str, str]]) -> str:
    blocks = "".join(_render_section_block_html(index, section["title"], section.get("body") or "") for index, section in enumerate(sections, 1))
    return _wrap_report_email_html(subject, f"Data: {report_day:%d.%m.%Y}", blocks)


async def send_end_week_bz_report(subject: str, recipients: dict[str, list[str]], plain_text: str, html_body: str, *, report_day: date, sections: list[dict[str, str]]) -> dict[str, Any]:
    return await send_section_report(subject, recipients, plain_text, html_body, report_code="BZ_FIN_JAV", report_day=report_day, sections=sections)
