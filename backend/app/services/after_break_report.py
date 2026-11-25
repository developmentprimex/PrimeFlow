from __future__ import annotations

from app.services.report_attendance import filter_task_context, filter_report_sections
from app.services.discord_ga_replies import (
    GA_REPLIES_CAPTURE_VERSION,
    GA_REPLIES_CAPTURE_VERSION_KEY,
    GA_REPLIES_SECTION_TITLE,
    UNAVAILABLE,
    _report_window,
    refresh_ga_reply_section,
    summary_for_day,
)
from app.services.discord_ga_reactions import (
    GA_REACTIONS_SECTION_KEY,
    GA_REACTIONS_SECTION_TITLE,
    REACTIONS_UNAVAILABLE,
    reaction_summary_for_day,
    refresh_ga_reaction_section,
)

import asyncio
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import String, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models.after_break_report_settings import AfterBreakReportSettings
from app.models.audit_log import AuditLog
from app.models.department import Department
from app.models.discord_m2_question import DiscordM2Question
from app.models.enums import CommonApprovalStatus, GaNoteStatus, TaskStatus
from app.models.ga_note import GaNote
from app.services.gmail_px_notes import sync_gmail_px_notes
from app.models.meeting import Meeting
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.models.question_library import QuestionCategory, QuestionDefinition, QuestionUserStatus
from app.models.system_task_template import SystemTaskTemplate
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.user import User
from app.services.report_note_visibility import is_mira_note, mira_note_expression
from app.services.microsoft_calendar_sync import is_common_view_visible_meeting
from app.services.personal_task_owner import personal_task_owner
from app.services.meetings_report import (
    PERSONAL_GA,
    TECHNICAL_TAG,
    _all_participant_user_ids,
    _ascii_table_block,
    _assignee_names,
    apply_weekly_planner_task_order,
    _clean_task_title as _display_title,
    _daily_rlz_values_by_task,
    _effective_task_assignee_ids,
    _initials,
    _is_open,
    _local_date,
    _local_time,
    _meeting_group_title,
    _meeting_occurs_on_date,
    _meeting_status_checkbox_table,
    _m3_am_pm_label,
    _m3_department_code_label,
    _m3_department_label,
    _m3_finance_ga_sections,
    _m3_task_type_label,
    _normalize_section,
    _normalize_report_status,
    _render_group_label_html,
    _render_section_block_html,
    _section_report_table_rows,
    _task_owners,
    _wrap_fixed_width,
    _wrap_report_email_html,
    common_view_task_sort_key,
    send_section_report,
)
from app.services.task_title_rules import title_has_eight_am_indicator
from app.services.primeflow_report import report_timezone
from app.services.px_note_email import EMAIL_NOTE_ORIGINS, email_preview, email_preview_text, is_email_note_content
from app.services.report_inboxes import MailSource, REPORT_INBOX_SOURCES, read_report_inbox, report_mailbox

REPORT_TYPE = "after_break_report"
REPORT_LABEL = "Permbledhja pas pauzes"
UNFINISHED_PRIORITY_TABLE_LABEL = "DET TE PAKRYERA, 08:00/DEADLINE"
UNFINISHED_EXPLANATION_OVERRIDES = "unfinished_explanation_overrides"
WAITING_CLIENT_TABLE_LABEL = "DT WFE"
DONE_AM_TABLE_LABEL = "DET E KRYERA NE AM"
UNHELD_MEETINGS_TABLE_LABEL = "TAK INT/EXT TE PAMBAJTURA"
PCM_PROJECTS_TITLE = "PROJEKTET: ATO QE KEMI PUNU DHE SKEMI PUNU"
PCM_PROJECT_CODES = ("VS", "VL", "MST", "TT")
PCM_CODES_REQUIRING_PROJECT = {"MST", "TT"}
PCM_PROJECT_CODE_PATTERN = re.compile(r"(?<![A-Z0-9])(?:VS|VL|MST|TT)(?![A-Z0-9])", re.IGNORECASE)
PCM_PROJECT_SUMMARY_PATTERN = re.compile("\n".join(f"{code} - (?:PO|JO)" for code in PCM_PROJECT_CODES))
NEW_EMAILS_TITLE = "(GA) EMAILS TE REJA?"
NEW_EMAILS_SNAPSHOT_KEY = "new_email_mailboxes"
NEW_EMAILS_NOT_GENERATED = "Gjenero raportin për të lexuar email-et e ardhura nga ora 08:00."
AUTOMATED_SECTION_TITLES = {NEW_EMAILS_TITLE, GA_REPLIES_SECTION_TITLE, GA_REACTIONS_SECTION_KEY, PCM_PROJECTS_TITLE}
SECTION_TITLES = [
    NEW_EMAILS_TITLE,
    PCM_PROJECTS_TITLE,
    "A JEMI BRENDA PLANIT ME PROJEKTE/DIZAJN?",  # Retired, kept as a legacy key.
    "PIKAT E BORDIT/DISKUTO APLIKANTAT",  # Retired, kept as a legacy key.
    UNFINISHED_PRIORITY_TABLE_LABEL,
    DONE_AM_TABLE_LABEL,
    UNHELD_MEETINGS_TABLE_LABEL,
    "A KEMI NEW SYSTEM TASKS/ PYETJE PER KONFIRMIM?",
    "(GA/KA) KUSH KA DET PERSONALISHT?",
    "NOTES TE REJA ( NOT DISSCUSED)",
    "GA MBYLLJA E DET",
    "HV MBYLLJA E DET",
    WAITING_CLIENT_TABLE_LABEL,
    GA_REPLIES_SECTION_TITLE,
    GA_REACTIONS_SECTION_KEY,
]
MANUAL_SECTION_TITLES: set[str] = set()
DISPLAY_SECTION_TITLES = [
    SECTION_TITLES[0],
    GA_REPLIES_SECTION_TITLE,
    GA_REACTIONS_SECTION_KEY,
    PCM_PROJECTS_TITLE,
    SECTION_TITLES[9],  # Undiscussed notes first among auto-filled sections.
    SECTION_TITLES[6],  # Unheld internal/external meetings immediately after notes.
    SECTION_TITLES[4],
    SECTION_TITLES[12],  # Active tasks waiting for the client, after unfinished priority work.
    SECTION_TITLES[5],
    SECTION_TITLES[7],
    SECTION_TITLES[8],
    *SECTION_TITLES[10:12],
]
SECTION_TITLE_ALIASES = {
    GA_REACTIONS_SECTION_TITLE: GA_REACTIONS_SECTION_KEY,
    "NOTES TE REJA ME TE KALTER DHE DISSCUSED": SECTION_TITLES[9],
    "NOTES TE REJA ME TE KALTER DHE DISSCUSED?": SECTION_TITLES[9],
    # Preserve the user's edited display title while recovering this existing
    # draft's stable auto-filled identity.
    "DET TE PAKRYERA AM, 08:00/DEADLINE": SECTION_TITLES[4],
}
RETIRED_MANUAL_KEYS = {
    re.sub(r"[^A-Z0-9]+", "", title)
    for title in ("DET NGA EMAIL/ PX INFO & ZHVILLIM", *SECTION_TITLES[2:4])
}
# Personal tasks count only when the title marks them as GA's: initials then a slash or a
# colon, e.g. "DM/GA: BZ GA - P/P PARA PF" or "ER:GA DEVICES". "AT/KA:" and "ER/KA:" stay out.
PERSONAL_COLUMNS = [("NR", 2), ("WHO", 20), ("DEP", 5), ("AM/PM", 5), ("TITLE", 56)]
SYSTEM_TASK_COLUMNS = [("NR", 2), ("WHO", 20), ("DEP", 5), ("AM/PM", 5), ("TITLE", 56), ("DATA", 10)]
UNFINISHED_PRIORITY_COLUMNS = [
    ("NR", 2), ("KUSH", 12), ("DEP", 5), ("AM/PM", 5), ("STATUS", 12),
    ("LLOJI", 18), ("TIPI", 5), ("TITULLI", 45), ("DUE DATE", 12),
    ("ARSYEJA", 24), ("KOMENT", 36),
]
DONE_AM_COLUMNS = [
    ("NR", 2), ("KUSH", 12), ("DEP", 5), ("AM/PM", 5), ("LLOJI", 7), ("TITULLI", 58),
]
WAITING_CLIENT_COLUMNS = [
    ("NR", 2), ("KUSH", 12), ("DEP", 5), ("WFE NGA", 8), ("AM/PM", 5), ("LLOJI", 7), ("TITULLI", 58),
]
PERSONAL_GROUPS = [
    ("TODO", "TODO"),
    ("IN PROGRESS", "IN_PROGRESS"),
    ("STOPPED", "PAUSED"),
    ("WFE", "WAITING_CLIENT"),
    ("WFC INT", "WAITING_CONFIRMATION"),
    ("DONE", "DONE"),
]
def subject_for(day: date) -> str:
    return f"M2 - PrimeFlow Permbledhja pas pauzes - {day:%d.%m.%Y}"


def is_generated_subject(subject: str | None, day: date) -> bool:
    """Recognize the old and current automatically generated M2 subjects."""
    return (subject or "").strip() in {
        subject_for(day),
        f"PrimeFlow Permbledhja pas pauzes - {day:%d.%m.%Y}",
    }


def _ascii_table(
    label: str,
    columns: list[tuple[str, int]],
    rows_values: list[list[str]],
    *,
    show_empty_table: bool = False,
) -> list[str]:
    if not rows_values and not show_empty_table:
        return [f"{label}: 0"]
    border = "+" + "+".join("-" * (width + 2) for _, width in columns) + "+"
    rows = [
        f"{label}:",
        border,
        "| " + " | ".join(f"{name:<{width}}" for name, width in columns) + " |",
        border,
    ]
    # Keep short identity columns on one line so one logical row is not split visually.
    no_wrap = {"NR", "WHO", "KUSH", "FROM", "PER", "DISK", "TIME", "ORA", "KOHA", "DATA", "DATE", "DUE DATE", "AFATI", "LATE"}
    if not rows_values:
        empty_values = ["-" for _ in columns]
        title_index = next(index for index, (name, _) in enumerate(columns) if name == "TITULLI")
        empty_values[title_index] = "(Asnje detyre)"
        rows_values = [empty_values]
    for values in rows_values:
        wrapped = []
        for value, (name, width) in zip(values, columns):
            cleaned = re.sub(r"\s+", " ", value).strip() if value.strip() else ""
            if name.upper() in no_wrap:
                wrapped.append([cleaned])
            else:
                wrapped.append(_wrap_fixed_width(cleaned, width) if cleaned else [""])
        for position in range(max(len(cell) for cell in wrapped)):
            line_cells = [
                cell[position] if position < len(cell) else ""
                for cell in wrapped
            ]
            rows.append("| " + " | ".join(f"{value:<{width}}" for value, (_, width) in zip(line_cells, columns)) + " |")
        rows.append(border)
    return rows


def _note_text(value: str | None) -> str:
    """Strip [[added]]/[[done]] markers only; keep the wrapped text."""
    cleaned = TECHNICAL_TAG.sub("", value or "")
    return re.sub(r"\s+", " ", cleaned).strip() or "-"


def _task_covers_day(task: Task, day: date) -> bool:
    """Mirror the Common View date logic so the report shows the same rows as the P: lane."""
    single_day_only = str(getattr(task, "phase", None) or "").upper() in {"CHECK", "CONTROL"}
    start = _local_date(getattr(task, "start_date", None))
    due = _local_date(getattr(task, "due_date", None))
    if not single_day_only and start and due:
        if start > due:
            start, due = due, start
        if any(current.weekday() < 5 for current in _days_between(start, due)):
            return start <= day <= due and day.weekday() < 5
        return day == start
    source = (
        getattr(task, "planned_for", None)
        or getattr(task, "due_date", None)
        or getattr(task, "start_date", None)
        or getattr(task, "created_at", None)
    )
    return _local_date(source) == day


def _days_between(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _is_done(task: Task) -> bool:
    return bool(task.completed_at) or str(task.status or "").upper() in {"DONE", "COMPLETED"}


def _as_timezone(value: datetime | None, timezone: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(timezone) if value.tzinfo else value.replace(tzinfo=timezone)


def _unfinished_priority_task_rows(
    tasks: list[Task],
    names: dict[Any, str],
    assignee_ids_by_task: dict[Any, set[Any]],
    report_day: date,
    cutoff: datetime,
    timezone: ZoneInfo,
    department_codes: dict[Any, str] | None = None,
    *, include_task_id: bool = False,
) -> list[list[str]]:
    """AM/AM-PM TODO or in-progress work whose due date is the report day."""
    selected: list[tuple[Task, datetime | None, str, str]] = []
    for task in tasks:
        due_at = _as_timezone(task.due_date, timezone)
        if due_at is None or due_at.date() != report_day:
            continue

        # M2 section 7 covers work that belonged to the morning. PM-only tasks
        # remain outside this section even when marked as 08:00 or deadline.
        finish_period = str(getattr(task, "finish_period", None) or "").strip().upper()
        if finish_period not in {"AM", "AM/PM"}:
            continue

        # Match Common View: its 08:00 badge/filter is driven by the title marker,
        # while due_date only determines which calendar day the task belongs to.
        is_eight_am = title_has_eight_am_indicator(
            task.title,
            is_system_task=bool(getattr(task, "system_template_origin_id", None) or getattr(task, "system_task_slot_id", None)),
        )
        is_deadline = bool(task.is_deadline_important)

        created_at = _as_timezone(task.created_at, timezone)
        if created_at is not None and created_at > cutoff:
            continue

        completed_at = _as_timezone(task.completed_at, timezone)
        if completed_at is not None and completed_at <= cutoff:
            continue

        status = _normalize_report_status(task.status)
        # A report regenerated after the cutoff may see a task that was still
        # open at send time as DONE. Preserve it as in-progress for that cutoff.
        if status == "DONE" and completed_at is not None and completed_at > cutoff:
            status = "IN_PROGRESS"
        if status not in {"TODO", "IN_PROGRESS"}:
            continue

        task_type = (
            "DEADLINE / 08:00"
            if is_deadline and is_eight_am
            else ("DEADLINE" if is_deadline else ("08:00" if is_eight_am else "DUE SOT"))
        )
        selected.append((task, due_at, task_type, status))

    selected.sort(
        key=lambda item: (
            0 if item[2] == "08:00" else (1 if "08:00" in item[2] else 2),
            common_view_task_sort_key(item[0], names, assignee_ids_by_task),
        )
    )
    return [
        [
            str(index),
            _task_owners(task, names, assignee_ids_by_task),
            _m3_department_label(task, department_codes),
            str(getattr(task, "finish_period", None) or "").strip().upper(),
            status,
            task_type,
            _m3_task_type_label(task),
            _display_title(task.title),
            "SOT",
        ] + ([str(task.id)] if include_task_id else [])
        for index, (task, due_at, task_type, status) in enumerate(selected, start=1)
    ]


async def _after_break_cutoff(db: AsyncSession, report_day: date) -> tuple[datetime, ZoneInfo]:
    settings = (
        await db.execute(select(AfterBreakReportSettings).order_by(AfterBreakReportSettings.created_at.asc()))
    ).scalars().first()
    timezone_name = settings.timezone if settings and settings.timezone else "Europe/Tirane"
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("Europe/Tirane")
    send_time = settings.send_time if settings and settings.send_time else time(13, 20)
    return datetime.combine(report_day, send_time, tzinfo=timezone), timezone


def _done_am_task_rows(
    tasks: list[Task],
    names: dict[Any, str],
    assignee_ids_by_task: dict[Any, set[Any]],
    report_day: date,
    timezone: ZoneInfo,
    department_codes: dict[Any, str] | None = None,
) -> list[list[str]]:
    done_am: list[tuple[Task, datetime]] = []
    for task in tasks:
        if (
            bool(getattr(task, "system_template_origin_id", None) or getattr(task, "system_task_slot_id", None))
            or getattr(task, "system_task_slot_id", None) is not None
        ):
            continue
        completed_at = _as_timezone(task.completed_at, timezone)
        if completed_at is None or completed_at.date() != report_day or completed_at.hour >= 12:
            continue
        if str(task.status or "").upper() not in {"DONE", "COMPLETED"}:
            continue
        done_am.append((task, completed_at))

    done_am.sort(
        key=lambda item: (
            *common_view_task_sort_key(item[0], names, assignee_ids_by_task),
            item[1],
        )
    )
    return [
        [
            str(index),
            _task_owners(task, names, assignee_ids_by_task),
            _m3_department_label(task, department_codes),
            _m3_am_pm_label(task),
            _m3_task_type_label(task),
            _display_title(task.title),
        ]
        for index, (task, _completed_at) in enumerate(done_am, start=1)
    ]


async def _waiting_client_entry_dates(db: AsyncSession, tasks: list[Task]) -> dict[Any, datetime]:
    """Read the latest actual WFE entry, ignoring edits made while already in WFE."""
    task_ids = [task.id for task in tasks if _normalize_report_status(task.status) == TaskStatus.WAITING_CLIENT.value]
    if not task_ids:
        return {}
    events = (await db.execute(
        select(AuditLog)
        .where(AuditLog.entity_type == "task", AuditLog.entity_id.in_(task_ids))
        .where(
            AuditLog.after["status"].astext.is_not(None)
            | (AuditLog.after["field"].astext == "status")
        )
        .order_by(AuditLog.created_at.desc())
    )).scalars().all()
    entries: dict[Any, datetime] = {}
    for event in events:
        before, after = event.before or {}, event.after or {}
        old_status = before.get("value") if before.get("field") == "status" else before.get("status")
        new_status = after.get("value") if after.get("field") == "status" else after.get("status")
        if (
            event.entity_id not in entries
            and _normalize_report_status(new_status) == TaskStatus.WAITING_CLIENT.value
            and _normalize_report_status(old_status) != TaskStatus.WAITING_CLIENT.value
            and (old_status is not None or event.action == "created")
        ):
            entries[event.entity_id] = event.created_at
    return entries


def _waiting_client_task_rows(
    tasks: list[Task],
    names: dict[Any, str],
    assignee_ids_by_task: dict[Any, set[Any]],
    report_day: date,
    department_codes: dict[Any, str] | None = None,
    entry_dates: dict[Any, datetime] | None = None,
    timezone: ZoneInfo | None = None,
) -> list[list[str]]:
    """All active tasks currently waiting for action or information from the client."""
    def entry_day_label(task: Task) -> str:
        entered_at = _as_timezone((entry_dates or {}).get(task.id), timezone or ZoneInfo("Europe/Tirane"))
        if entered_at is None or entered_at.date() > report_day:
            return "Pa date"
        age = (report_day - entered_at.date()).days
        return "Sot" if age == 0 else "Dje" if age == 1 else entered_at.strftime("%d.%m")

    waiting = [
        task for task in tasks
        if _normalize_report_status(task.status) == TaskStatus.WAITING_CLIENT.value
    ]
    def entry_sort_key(task: Task) -> tuple:
        entered_at = _as_timezone((entry_dates or {}).get(task.id), timezone or ZoneInfo("Europe/Tirane"))
        known_date = entered_at is not None and entered_at.date() <= report_day
        return (
            -entered_at.timestamp() if known_date else float("inf"),
            common_view_task_sort_key(task, names, assignee_ids_by_task),
        )

    waiting.sort(key=entry_sort_key)
    return [
        [
            str(index),
            _task_owners(task, names, assignee_ids_by_task),
            _m3_department_label(task, department_codes),
            entry_day_label(task),
            _m3_am_pm_label(task),
            _m3_task_type_label(task),
            _display_title(task.title),
        ]
        for index, task in enumerate(waiting, start=1)
    ]


async def build_unfinished_priority_task_rows(
    db: AsyncSession, report_day: date, *, include_task_id: bool = False,
    explanation_overrides: dict | None = None, explanation_rows: list | None = None,
) -> list[list[str]]:
    """Load unfinished morning work at the configured M2 send cutoff."""
    tasks = (await db.execute(select(Task).where(Task.work_staff_filter()).where(Task.is_active.is_(True)))).scalars().all()
    names = await _assignee_names(db, tasks)
    assignee_ids_by_task = await _effective_task_assignee_ids(db, tasks)
    tasks, names, assignee_ids_by_task = await filter_task_context(db, report_day, tasks, names, assignee_ids_by_task)
    await apply_weekly_planner_task_order(db, tasks, assignee_ids_by_task)
    department_codes = {
        department_id: code
        for department_id, code in (await db.execute(select(Department.id, Department.code))).all()
    }
    cutoff, cutoff_timezone = await _after_break_cutoff(db, report_day)
    rows = _unfinished_priority_task_rows(
        tasks,
        names,
        assignee_ids_by_task,
        report_day,
        cutoff,
        cutoff_timezone,
        department_codes,
        include_task_id=True,
    )
    if include_task_id:
        return rows
    return await _append_unfinished_priority_explanations(
        db, rows, tasks, report_day, names, assignee_ids_by_task,
        overrides=explanation_overrides, explanation_rows=explanation_rows,
    )


async def _append_unfinished_priority_explanations(
    db: AsyncSession,
    rows: list[list[str]],
    tasks: list[Task],
    report_day: date,
    names: dict[Any, str],
    assignee_ids_by_task: dict[Any, set[Any]],
    *, overrides: dict | None = None, explanation_rows: list | None = None,
) -> list[list[str]]:
    row_ids = {row[-1] for row in rows}
    selected = [task for task in tasks if str(task.id) in row_ids]
    values = await _daily_rlz_values_by_task(db, selected, report_day, names, assignee_ids_by_task)
    by_id = {str(task_id): fields for task_id, fields in values.items()}
    discord_comments: dict[str, list[str]] = {}
    if selected:
        selected_ids = [task.id for task in selected]
        continued_from_am = select(cast(DiscordM2Question.id, String)).where(
            DiscordM2Question.day == report_day,
            DiscordM2Question.task_id.in_(selected_ids),
            DiscordM2Question.kind == "continuation",
            DiscordM2Question.snapshot["continued_from_am"].astext == "true",
        )
        notes = (await db.execute(
            select(AuditLog.entity_id, AuditLog.actor_user_id, AuditLog.after)
            .where(
                AuditLog.entity_type == "task",
                AuditLog.entity_id.in_(selected_ids),
                AuditLog.after["day"].astext == report_day.isoformat(),
                or_(
                    (AuditLog.action == "task.discord_m2_comment") & (AuditLog.after["kind"].astext == "unfinished"),
                    AuditLog.action.in_(["task.discord_m2_comment", "task.discord_m2_answer"])
                    & (AuditLog.after["kind"].astext == "continuation")
                    & AuditLog.after["question_id"].astext.in_(continued_from_am),
                ),
            )
            .order_by(AuditLog.created_at, AuditLog.id)
        )).all()
        for task_id, user_id, evidence in notes:
            comment = (evidence.get("comment") or "").strip()
            if comment:
                initials = _initials(names.get(user_id))
                discord_comments.setdefault(str(task_id), []).append(f"{initials}: {comment}" if initials != "-" else comment)
    result = []
    for row in rows:
        task_id = row[-1]
        reason, comment = by_id.get(task_id, ("-", "-"))
        sources = ([comment] if comment != "-" else []) + discord_comments.get(task_id, [])
        manual = (overrides or {}).get(task_id, {})
        reason = manual.get("reason", reason) or "-"
        comment = manual.get("comment", "; ".join(dict.fromkeys(sources))) or "-"
        if explanation_rows is not None:
            explanation_rows.append({
                "row_number": row[0], "task_id": task_id, "title": row[7],
                "assignees": row[1], "reason": reason, "comment": comment,
            })
        result.append([*row[:-1], reason.replace("|", "¦"), comment.replace("|", "¦")])
    return result


async def apply_unfinished_priority_task_table(
    db: AsyncSession,
    sections: list[dict[str, str]],
    report_day: date,
    *, explanation_overrides: dict | None = None, explanation_rows: list | None = None,
) -> list[dict[str, str]]:
    """Refresh M2 section 7 from the task state at the configured send cutoff."""
    rows = await build_unfinished_priority_task_rows(
        db, report_day, explanation_overrides=explanation_overrides, explanation_rows=explanation_rows,
    )
    body = _normalize_section(
        _ascii_table(
            UNFINISHED_PRIORITY_TABLE_LABEL,
            UNFINISHED_PRIORITY_COLUMNS,
            rows,
            show_empty_table=True,
        )
    )
    return [
        {**section, "body": body}
        if section.get("section_key") == UNFINISHED_PRIORITY_TABLE_LABEL
        or section.get("title") == UNFINISHED_PRIORITY_TABLE_LABEL
        else section
        for section in sections
    ]


async def apply_waiting_client_task_table(
    db: AsyncSession, sections: list[dict[str, str]], report_day: date
) -> list[dict[str, str]]:
    """Refresh DT WFE in existing M2 drafts without replacing manual sections."""
    tasks = (await db.execute(select(Task).where(Task.work_staff_filter()).where(Task.is_active.is_(True)))).scalars().all()
    names = await _assignee_names(db, tasks)
    assignee_ids_by_task = await _effective_task_assignee_ids(db, tasks)
    tasks, names, assignee_ids_by_task = await filter_task_context(db, report_day, tasks, names, assignee_ids_by_task)
    department_codes = {
        department_id: code
        for department_id, code in (await db.execute(select(Department.id, Department.code))).all()
    }
    # Use the exact same department mapping for both the visible DEP column and
    # the Weekly Planner department/user ordering metadata.
    await apply_weekly_planner_task_order(
        db, tasks, assignee_ids_by_task, department_codes
    )
    entry_dates = await _waiting_client_entry_dates(db, tasks)
    _, report_timezone = await _after_break_cutoff(db, report_day)
    rows = _waiting_client_task_rows(
        tasks, names, assignee_ids_by_task, report_day, department_codes, entry_dates, report_timezone,
    )
    body = _normalize_section(
        _ascii_table(WAITING_CLIENT_TABLE_LABEL, WAITING_CLIENT_COLUMNS, rows)
    )
    refreshed = []
    found = False
    for section in sections:
        if not is_waiting_client_section(section.get("title"), section.get("section_key")):
            refreshed.append(section)
        elif not found:
            refreshed.append({**section, "section_key": WAITING_CLIENT_TABLE_LABEL, "body": body})
            found = True
    return refreshed


def _unheld_meeting_section(
    meetings: list[Meeting],
    status_by_meeting: dict[Any, str],
    all_meetings: list[Meeting] | None = None,
) -> tuple[list[str], int]:
    unheld = []
    for meeting in meetings:
        meeting_time = _local_time(meeting.starts_at)
        if meeting_time == "-" or meeting_time >= "12:00":
            continue
        if str(status_by_meeting.get(meeting.id, "") or "").strip().lower() == "held":
            continue
        unheld.append(meeting)
    external = [meeting for meeting in unheld if str(getattr(meeting, "meeting_type", "")).lower() == "external"]
    internal = [meeting for meeting in unheld if str(getattr(meeting, "meeting_type", "")).lower() != "external"]
    external_by_id = {
        str(meeting.id): meeting
        for meeting in (all_meetings or meetings)
        if str(getattr(meeting, "meeting_type", "")).lower() == "external"
    }
    return ([
        *_meeting_group_title("TAK EXTERNE"),
        *_meeting_status_checkbox_table(external, status_by_meeting, external_by_id),
        "",
        *_meeting_group_title("TAK INTERNE"),
        *_meeting_status_checkbox_table(internal, status_by_meeting, external_by_id),
    ], len(unheld))


def _belongs_to_day(task: Task, day: date) -> bool:
    """Only today's work: a finished task counts on the day it was finished, not for its whole range."""
    if _is_done(task):
        completed = _local_date(task.completed_at)
        if completed is not None:
            return completed == day
    return _task_covers_day(task, day)


async def _new_system_task_rows(
    db: AsyncSession, department_codes: dict[Any, str] | None = None
) -> list[list[str]]:
    templates = (
        await db.execute(
            select(SystemTaskTemplate).where(SystemTaskTemplate.approval_status == CommonApprovalStatus.pending)
        )
    ).scalars().all()
    if not templates:
        return []

    user_ids: set[Any] = set()
    for template in templates:
        user_ids.update(template.assignee_ids or [])
        if template.default_assignee_id:
            user_ids.add(template.default_assignee_id)
    users_map: dict[Any, User] = {}
    if user_ids:
        users = (await db.execute(select(User).where(User.work_staff_filter()).where(User.id.in_(user_ids)))).scalars().all()
        users_map = {user.id: user for user in users}

    rows: list[list[str]] = []
    def _created_sort_key(template: SystemTaskTemplate) -> tuple[bool, float, str]:
        created_at = template.created_at
        return (created_at is None, created_at.timestamp() if created_at else 0.0, template.title or "")

    for template in sorted(templates, key=_created_sort_key):
        assignee_ids = list(template.assignee_ids or [])
        if not assignee_ids and template.default_assignee_id:
            assignee_ids = [template.default_assignee_id]
        owners = [
            _initials(users_map[user_id].full_name or users_map[user_id].username or users_map[user_id].email)
            for user_id in assignee_ids
            if user_id in users_map
        ]
        owner_label = " ".join(dict.fromkeys([owner for owner in owners if owner != "-"])) or "-"
        primary_user_id = template.default_assignee_id or (assignee_ids[0] if assignee_ids else None)
        primary_user = users_map.get(primary_user_id)
        user_department = _m3_department_code_label(
            getattr(primary_user, "department_id", None), department_codes
        ) if primary_user else "-"
        created = _local_date(template.created_at)
        rows.append([
            str(len(rows) + 1),
            owner_label,
            user_department,
            _m3_am_pm_label(template),
            _display_title(template.title),
            created.strftime("%d.%m.%Y") if created else "-",
        ])
    return rows


def _format_confirmation_questions(questions: list[tuple[str, str, str]]) -> list[str]:
    """Render pending confirmation questions with their Questions category (Kategoria)."""
    rows: list[list[str]] = []
    for index, (category, text, guidance) in enumerate(questions, 1):
        question = (text or "").strip() or "-"
        tip = (guidance or "").strip()
        if tip:
            question = f"{question} — {tip}"
        rows.append([str(index), (category or "").strip() or "-", question])
    return _ascii_table(
        "PYETJE PER KONFIRMIM",
        [("NR", 2), ("Kategoria", 12), ("PYETJA", 64)],
        rows,
    )


async def _load_1h_confirmation_questions(db: AsyncSession) -> list[tuple[str, str, str]]:
    """Load unconfirmed View Question tasks for M2 PYETJE PER KONFIRMIM.

    Only questions that created an assignee task (from any Questions category)
    appear here. Template/library questions without a task are excluded.
    Once every assigned user marks the question done (or the task is DONE),
    it is omitted.

    Returns (category_name, question_text, guidance) tuples.
    """
    result = (
        await db.execute(
            select(QuestionDefinition, QuestionCategory.name)
            .join(QuestionCategory, QuestionCategory.id == QuestionDefinition.category_id)
            .where(QuestionDefinition.task_id.is_not(None))
            .order_by(
                QuestionDefinition.created_at.asc(),
                QuestionCategory.sort_order,
                QuestionDefinition.sort_order,
            )
        )
    ).all()
    if not result:
        return []

    rows = [row for row, _category_name in result]
    question_ids = [row.id for row in rows]
    task_ids = {row.task_id for row in rows if row.task_id is not None}
    if not task_ids:
        return []

    assignees_by_task: dict = {task_id: set() for task_id in task_ids}
    for task_id, user_id in (
        await db.execute(
            select(TaskAssignee.task_id, TaskAssignee.user_id).where(
                TaskAssignee.task_id.in_(task_ids)
            )
        )
    ).all():
        assignees_by_task.setdefault(task_id, set()).add(user_id)

    done_task_ids = set(
        (
            await db.execute(
                select(Task.id).where(Task.work_staff_filter()).where(
                    Task.id.in_(task_ids),
                    Task.status == TaskStatus.DONE,
                )
            )
        ).scalars().all()
    )

    done_pairs = {
        (question_id, user_id)
        for question_id, user_id in (
            await db.execute(
                select(QuestionUserStatus.question_id, QuestionUserStatus.user_id).where(
                    QuestionUserStatus.question_id.in_(question_ids),
                    QuestionUserStatus.status == TaskStatus.DONE.value,
                )
            )
        ).all()
    }

    pending: list[tuple[str, str, str]] = []
    seen_text: set[str] = set()
    for row, category_name in result:
        text = (row.text or "").strip()
        if not text:
            continue
        text_key = text.casefold()
        if text_key in seen_text:
            continue

        linked_task_id = row.task_id
        if linked_task_id is None:
            continue
        if linked_task_id in done_task_ids:
            continue

        assignees = assignees_by_task.get(linked_task_id, set())
        if assignees and all((row.id, user_id) in done_pairs for user_id in assignees):
            continue

        seen_text.add(text_key)
        pending.append(((category_name or "").strip() or "-", text, (row.guidance or "").strip()))
    return pending


def _replace_confirmation_questions_block(body: str, question_lines: list[str]) -> str:
    lines = (body or "").splitlines()
    marker_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip().upper().startswith("PYETJE PER KONFIRMIM")
        ),
        -1,
    )
    head = list(lines[:marker_index] if marker_index >= 0 else lines)
    while head and not head[-1].strip():
        head.pop()
    return "\n".join([*head, "", *question_lines]).strip()


def is_retired_after_break_question(title: str | None, section_key: str | None = None) -> bool:
    for value in (title, section_key):
        compact = re.sub(r"[^A-Z0-9]+", "", (value or "").upper().replace("Ë", "E"))
        if re.sub(r"^(?:MANUAL)?\d*", "", compact) in RETIRED_MANUAL_KEYS:
            return True
    return False


def is_waiting_client_section(title: str | None, section_key: str | None = None) -> bool:
    return any(re.fullmatch(r"(?:MANUAL)?\d*DTWFE", re.sub(r"[^A-Z0-9]+", "", (value or "").upper()))
               for value in (title, section_key))


def after_break_automated_section_title(title: str | None, section_key: str | None = None) -> str | None:
    for value in (section_key, title):
        compact = re.sub(r"[^A-Z0-9]+", "", (value or "").upper())
        compact = re.sub(r"^(?:MANUAL)?\d*", "", compact)
        for expected in AUTOMATED_SECTION_TITLES:
            if compact == re.sub(r"[^A-Z0-9]+", "", expected):
                return expected
    return None


def _pcm_projects_summary(tasks: list[Task], report_day: date) -> str:
    worked: set[str] = set()
    for task in tasks:
        start, due = _local_date(task.start_date), _local_date(task.due_date)
        if start and due and start <= report_day <= due:
            codes = {code.upper() for code in PCM_PROJECT_CODE_PATTERN.findall(task.title or "")}
            if task.project_id is None:
                codes -= PCM_CODES_REQUIRING_PROJECT
            worked.update(codes)
    return "\n".join(f"{code} - {'PO' if code in worked else 'JO'}" for code in PCM_PROJECT_CODES)


async def _load_pcm_projects_summary(db: AsyncSession, report_day: date) -> str:
    pcm_users = select(User.id).join(Department, User.department_id == Department.id).where(
        Department.code.in_(("PCM", "PRODUCT CONTENT", "PROJECT CONTENT MANAGER")),
        User.work_staff_filter(),
    )
    tasks = (await db.execute(select(Task).where(Task.is_active.is_(True), or_(
        Task.assigned_to.in_(pcm_users),
        Task.id.in_(select(TaskAssignee.task_id).where(TaskAssignee.user_id.in_(pcm_users))),
    )))).scalars().all()
    return _pcm_projects_summary(tasks, report_day)


async def populate_pcm_projects_section(db: AsyncSession, sections: list[dict[str, str]], report_day: date):
    return [
        {**section, "body": await _load_pcm_projects_summary(db, report_day)}
        if section.get("section_key") == PCM_PROJECTS_TITLE and not section.get("body") else section
        for section in sections
    ]


def normalize_after_break_report_sections(sections: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    by_title: dict[str, dict[str, str]] = {}
    extras: list[dict[str, str]] = []
    for section in sections or []:
        raw_title = str(section.get("title") or "").strip()
        section_key = str(section.get("section_key") or "").strip()
        if is_retired_after_break_question(raw_title, section_key):
            continue
        automated_title = after_break_automated_section_title(raw_title, section_key)
        if automated_title and section_key != automated_title:
            continue
        identity = section_key or raw_title
        title = SECTION_TITLE_ALIASES.get(identity, identity)
        if is_waiting_client_section(raw_title, section_key):
            title = WAITING_CLIENT_TABLE_LABEL
            if title in by_title:
                continue
        body = str(section.get("body") or "")
        if title == SECTION_TITLES[8]:
            body = re.sub(r"(?m)^WAITING CONFIRMATION(?=:)", "WFC INT", body)
        if title == SECTION_TITLES[9]:
            body = order_blue_notes_table(body)
        if title == PCM_PROJECTS_TITLE and not PCM_PROJECT_SUMMARY_PATTERN.fullmatch(body):
            body = ""
        if title in SECTION_TITLES and title not in by_title:
            visible_title = raw_title if section_key or raw_title in SECTION_TITLE_ALIASES else title
            if title == GA_REACTIONS_SECTION_KEY:
                visible_title = GA_REACTIONS_SECTION_TITLE
            by_title[title] = {
                "section_key": title,
                "title": visible_title,
                "body": body,
            }
        elif title:
            extras.append({
                "section_key": section_key or f"manual:{re.sub(r'[^A-Z0-9]+', '', title.upper())}",
                "title": raw_title or title,
                "body": body,
            })

    normalized: list[dict[str, str]] = []
    for title in DISPLAY_SECTION_TITLES:
        if title in by_title:
            section = by_title[title]
            if (
                title == SECTION_TITLES[4]
                and section.get("body", "").strip() == f"{UNFINISHED_PRIORITY_TABLE_LABEL}: 0"
            ):
                section = {
                    **section,
                    "body": _normalize_section(
                        _ascii_table(
                            UNFINISHED_PRIORITY_TABLE_LABEL,
                            UNFINISHED_PRIORITY_COLUMNS,
                            [],
                            show_empty_table=True,
                        )
                    ),
                }
            normalized.append(section)
            continue
        elif title == NEW_EMAILS_TITLE:
            body = NEW_EMAILS_NOT_GENERATED
        elif title == GA_REPLIES_SECTION_TITLE:
            body = UNAVAILABLE
        elif title == GA_REACTIONS_SECTION_KEY:
            body = REACTIONS_UNAVAILABLE
        elif title == PCM_PROJECTS_TITLE:
            body = ""
        elif title == SECTION_TITLES[4]:
            body = _normalize_section(
                _ascii_table(
                    UNFINISHED_PRIORITY_TABLE_LABEL,
                    UNFINISHED_PRIORITY_COLUMNS,
                    [],
                    show_empty_table=True,
                )
            )
        elif title == SECTION_TITLES[5]:
            body = f"{DONE_AM_TABLE_LABEL}: 0"
        elif title == SECTION_TITLES[12]:
            body = f"{WAITING_CLIENT_TABLE_LABEL}: 0"
        elif title == SECTION_TITLES[6]:
            body = f"{UNHELD_MEETINGS_TABLE_LABEL}: 0"
        elif title == SECTION_TITLES[7]:
            body = "\n".join(["NEW SYSTEM TASKS: 0", "", "PYETJE PER KONFIRMIM: 0"])
        elif title == SECTION_TITLES[8]:
            body = "\n".join(["TODO: 0", "", "IN PROGRESS: 0", "", "WFE: 0", "", "WFC INT: 0", "", "DONE: 0"])
        elif title in {SECTION_TITLES[10], SECTION_TITLES[11]}:
            body = "TODO: 0\n\nIN PROGRESS: 0\n\nDONE: 0\n\nLATE: 0"
        else:
            body = "NOTES: 0"
        normalized.append({"section_key": title,
                           "title": GA_REACTIONS_SECTION_TITLE if title == GA_REACTIONS_SECTION_KEY else title,
                           "body": body})
    # Keep Common View–synced manuals with the other manuals (before auto sections).
    manual_count = len(MANUAL_SECTION_TITLES)
    from app.services.meeting_point_manual_sync import order_custom_manual_sections

    if not extras:
        return order_custom_manual_sections("after_break", normalized)
    return order_custom_manual_sections("after_break", normalized[:manual_count] + extras + normalized[manual_count:])


async def apply_1h_confirmation_questions(
    db: AsyncSession, sections: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Keep NEW SYSTEM TASKS; refresh PYETJE PER KONFIRMIM from PYETJET PER 1H."""
    question_lines = _format_confirmation_questions(await _load_1h_confirmation_questions(db))
    updated: list[dict[str, str]] = []
    for section in sections:
        if section.get("section_key") == SECTION_TITLES[7] or section.get("title") == SECTION_TITLES[7]:
            updated.append({
                **section,
                "body": _replace_confirmation_questions_block(section.get("body") or "", question_lines),
            })
        else:
            updated.append(section)
    return updated


async def _personal_section(
    db: AsyncSession,
    tasks: list[Task],
    names: dict[Any, str],
    assignee_ids_by_task: dict[Any, set[Any]],
    report_day: date,
    title_pattern: re.Pattern[str] = PERSONAL_GA,
    department_codes: dict[Any, str] | None = None,
) -> list[str]:
    personal = [task for task in tasks if task.is_personal and _belongs_to_day(task, report_day)]
    all_participant_ids = await _all_participant_user_ids(db)

    # Common View shows the originating GA/KA note text for note-based tasks, not the task title.
    note_ids = {task.ga_note_origin_id for task in personal if task.ga_note_origin_id}
    note_titles: dict[Any, str] = {}
    if note_ids:
        rows = (await db.execute(select(GaNote.id, GaNote.content).where(GaNote.id.in_(note_ids)))).all()
        note_titles = {note_id: _display_title(content) for note_id, content in rows}

    def _title(task: Task) -> str:
        return note_titles.get(task.ga_note_origin_id) or _display_title(task.title)

    def _matches_title(task: Task) -> bool:
        if title_pattern is PERSONAL_GA:
            return personal_task_owner(_title(task)) == "GA"
        return bool(title_pattern.search(_title(task)) or title_pattern.search(task.title or ""))

    ga_personal = [task for task in personal if _matches_title(task)]

    def _group_key(task: Task) -> str:
        return "DONE" if _is_done(task) else str(task.status or "").upper()

    grouped: dict[str, list[Task]] = {}
    for task in ga_personal:
        grouped.setdefault(_group_key(task), []).append(task)

    known = {key for _, key in PERSONAL_GROUPS}
    other = [task for key, rows in grouped.items() if key not in known for task in rows]
    groups = [(label, key) for label, key in PERSONAL_GROUPS if key != "PAUSED" or grouped.get(key)]
    if other:
        groups.append(("TJERA", "TJERA"))
    grouped["TJERA"] = other

    lines: list[str] = []
    for label, key in groups:
        ordered = sorted(
            grouped.get(key, []),
            key=lambda task: common_view_task_sort_key(
                task, names, assignee_ids_by_task, all_participant_ids=all_participant_ids
            ),
        )
        rows_values = [
            [
                str(index),
                _task_owners(
                    task, names, assignee_ids_by_task, all_participant_ids=all_participant_ids
                ),
                _m3_department_label(task, department_codes),
                _m3_am_pm_label(task),
                _title(task),
            ]
            for index, task in enumerate(ordered, start=1)
        ]
        if lines:
            lines.append("")
        lines.extend(_ascii_table(label, PERSONAL_COLUMNS, rows_values))
    return lines


BLUE_NOTE_COLUMNS = [("NR", 2), ("DISK", 4), ("NOTE", 60), ("FROM", 8), ("TIME", 5)]
NOTE_REFERENCES = "px_note_references"


def order_blue_note_references(references: list[tuple[str, list[str]]]) -> list[tuple[str, list[str]]]:
    ordered = sorted(references, key=lambda entry: is_email_note_content(entry[1][2]))
    if ordered == references:
        return references
    return [(note_id, [str(index), *values[1:]]) for index, (note_id, values) in enumerate(ordered, 1)]


def order_blue_notes_table(body: str) -> str:
    lines = body.splitlines()
    caption_index = next((index for index, line in enumerate(lines) if line.strip() == "NOTES:"), None)
    if caption_index is None:
        return body
    start = next((index for index in range(caption_index + 1, len(lines)) if lines[index].strip()), len(lines))
    block = _ascii_table_block(lines, start)
    if block is None:
        return body
    table, end = block
    header, rows = _section_report_table_rows(table)
    if header != [column for column, _ in BLUE_NOTE_COLUMNS] or not all(row[0].isdecimal() for row in rows):
        return body
    ordered = sorted(rows, key=lambda row: is_email_note_content(row[2]))
    if ordered == rows:
        return body
    numbered = [[str(index), *row[1:]] for index, row in enumerate(ordered, 1)]
    return "\n".join([*lines[:caption_index], *_ascii_table("NOTES", BLUE_NOTE_COLUMNS, numbered), *lines[end:]])


async def load_blue_notes(
    db: AsyncSession, *, created_before: datetime | None = None, compact_email: bool = True,
) -> list[tuple[str, list[str]]]:
    """All eligible PX Notes that have not yet been discussed."""
    statement = (
        select(GaNote)
        .where(GaNote.is_converted_to_task.is_(False))
        .where(GaNote.status != GaNoteStatus.CLOSED)
        .where(GaNote.is_discussed.is_(False))
        .where(~mira_note_expression())
    )
    if created_before is not None:
        statement = statement.where(GaNote.created_at <= created_before)
    else:
        await sync_gmail_px_notes()
    notes = (await db.execute(statement)).scalars().all()
    if not notes:
        return []

    note_ids = [note.id for note in notes]
    linked_note_ids = set(
        (
            await db.execute(
                select(Task.ga_note_origin_id).where(Task.work_staff_filter())
                .where(Task.ga_note_origin_id.in_(note_ids))
                .where(Task.is_active.is_(True))
            )
        ).scalars().all()
    )
    open_notes = [
        note for note in notes
        if note.id not in linked_note_ids
        and not note.is_discussed
        and not is_mira_note(note)
    ]
    if not open_notes:
        return []

    author_ids = {note.created_by for note in open_notes if note.created_by}
    names: dict[Any, str] = {}
    if author_ids:
        users = (await db.execute(select(User).where(User.work_staff_filter()).where(User.id.in_(author_ids)))).scalars().all()
        names = {user.id: user.full_name or user.username or user.email for user in users}

    ordered = sorted(open_notes, key=lambda note: (
        getattr(note, "knowledge_type", None) in EMAIL_NOTE_ORIGINS or is_email_note_content(note.content),
        note.created_at or note.updated_at,
    ))
    return [
        (str(note.id), [
            str(index),
            "YES" if note.is_discussed else "NO",
            email_preview_text(preview) if compact_email and (preview := email_preview(note)) else _note_text(note.content),
            _initials(names.get(note.created_by)),
            _local_time(note.created_at),
        ])
        for index, note in enumerate(ordered, start=1)
    ]


async def refresh_after_break_discord_sections(
    db: AsyncSession, sections: list[dict[str, str]], report_day: date, *,
    generated_snapshot: dict | None, sent: bool, sent_at: datetime | None,
) -> list[dict[str, str]]:
    snapshot = generated_snapshot or {}
    if not snapshot.get("ga_replies_generated_at") and not sent:
        # Older drafts have no saved generation time. Read both points as of
        # the same instant, just as a newly generated M2 does.
        cutoff = datetime.now(timezone.utc)
        sections = [
            {**section, "body": await summary_for_day(db, report_day, report="M2", generated_at=cutoff)}
            if (section.get("section_key") or section.get("title")) == GA_REPLIES_SECTION_TITLE else section
            for section in sections
        ]
        snapshot = {**snapshot, "ga_replies_generated_at": cutoff.isoformat()}
    else:
        sections = await refresh_ga_reply_section(
            db, sections, report_day, report="M2", refresh_current=not sent,
            sent_at=sent_at, populate_missing=True, generated_snapshot=snapshot,
        )
        if sent and sent_at and not snapshot.get("ga_replies_generated_at"):
            snapshot = {**snapshot, "ga_replies_generated_at": sent_at.isoformat()}
    return await refresh_ga_reaction_section(
        db, sections, report_day, report="M2", generated_snapshot=snapshot, sent=sent,
    )


async def load_new_email_mailboxes(
    report_day: date, generated_at: datetime,
) -> dict[MailSource, dict]:
    window = _report_window(report_day, "M2", generated_at)
    start, end = window
    if end < start:
        return {}

    async def load(source: MailSource) -> tuple[MailSource, dict]:
        # Token refresh can commit. Keep each connection outside the report
        # transaction, which owns the automatic send's advisory lock.
        async with SessionLocal() as mail_db:
            try:
                async with asyncio.timeout(30):
                    inbox = await read_report_inbox(mail_db, source, report_day, window=window)
            except TimeoutError:
                inbox = {
                    "configured": True, "connected": False, "messages": [],
                    "error": f"Leximi i email-eve nga {report_mailbox(source).label} mori shumë kohë.",
                }
        selected = [
            message for message in inbox["messages"]
            if start <= datetime.fromisoformat(message["received_datetime"]) <= end
        ]
        return source, {**inbox, "messages": selected}

    return dict(await asyncio.gather(*(load(source) for source in REPORT_INBOX_SOURCES)))


def _new_emails_report_body(mailboxes: dict[MailSource, dict], report_day: date, generated_at: datetime) -> str:
    start, end = _report_window(report_day, "M2", generated_at)
    if end < start:
        return f"Intervali i email-eve për këtë datë fillon në {start:%H:%M}."
    end_label = end.astimezone(start.tzinfo).strftime("%H:%M")
    blocks = [f"Email-et e pranuara nga {start:%H:%M} deri në {end_label}."]
    for source, inbox in mailboxes.items():
        label = report_mailbox(source).label
        if not inbox["configured"]:
            continue
        if inbox.get("error"):
            blocks.append(inbox["error"])
        elif not inbox["connected"]:
            blocks.append(f"{label}: Kutia e email-it ende nuk është lidhur.")
        else:
            rows = [
                [mail[key].replace("|", "¦") for key in ("sender", "subject", "received_at")]
                for mail in inbox["messages"]
            ]
            blocks.append(_normalize_section(_ascii_table(
                label, [("DËRGUESI", 38), ("SUBJEKTI", 66), ("ORA", 5)], rows,
            )) if rows else f"{label}: Asnjë email në këtë interval.")
    if len(blocks) == 1:
        blocks.append("Asnjë kuti email-i e konfiguruar.")
    return "\n\n".join(blocks)


async def build_after_break_report_sections(db: AsyncSession, report_day: date) -> tuple[list[dict[str, str]], dict[str, Any]]:
    generated_at = datetime.now(timezone.utc)
    mailboxes = await load_new_email_mailboxes(report_day, generated_at)
    tasks = (await db.execute(select(Task).where(Task.work_staff_filter()).where(Task.is_active.is_(True)))).scalars().all()
    names = await _assignee_names(db, tasks)
    assignee_ids_by_task = await _effective_task_assignee_ids(db, tasks)
    tasks, names, assignee_ids_by_task = await filter_task_context(db, report_day, tasks, names, assignee_ids_by_task)
    department_codes = {
        department_id: code
        for department_id, code in (await db.execute(select(Department.id, Department.code))).all()
    }
    await apply_weekly_planner_task_order(
        db, tasks, assignee_ids_by_task, department_codes
    )
    cutoff, cutoff_timezone = await _after_break_cutoff(db, report_day)
    unfinished_priority_rows = _unfinished_priority_task_rows(
        tasks,
        names,
        assignee_ids_by_task,
        report_day,
        cutoff,
        cutoff_timezone,
        department_codes,
        include_task_id=True,
    )
    unfinished_priority_rows = await _append_unfinished_priority_explanations(
        db, unfinished_priority_rows, tasks, report_day, names, assignee_ids_by_task,
    )
    done_am_rows = _done_am_task_rows(
        tasks,
        names,
        assignee_ids_by_task,
        report_day,
        cutoff_timezone,
        department_codes,
    )
    entry_dates = await _waiting_client_entry_dates(db, tasks)
    waiting_client_rows = _waiting_client_task_rows(
        tasks,
        names,
        assignee_ids_by_task,
        report_day,
        department_codes,
        entry_dates,
        cutoff_timezone,
    )
    meetings = (await db.execute(select(Meeting).where(Meeting.starts_at.is_not(None)))).scalars().all()
    meetings = [meeting for meeting in meetings if is_common_view_visible_meeting(meeting)]
    today_meetings = [meeting for meeting in meetings if _meeting_occurs_on_date(meeting, report_day)]
    meeting_statuses = (
        await db.execute(
            select(MeetingOccurrenceStatus).where(MeetingOccurrenceStatus.occurrence_date == report_day)
        )
    ).scalars().all()
    unheld_meeting_section, unheld_meeting_count = _unheld_meeting_section(
        today_meetings,
        {row.meeting_id: row.status for row in meeting_statuses},
        meetings,
    )

    confirmation_ids = {
        task.confirmation_assignee_id for task in tasks
        if task.confirmation_assignee_id and task.confirmation_assignee_id not in names
    }
    if confirmation_ids:
        confirmation_users = (await db.execute(select(User).where(User.work_staff_filter()).where(User.id.in_(confirmation_ids)))).scalars().all()
        names.update({user.id: user.full_name or user.username or user.email for user in confirmation_users})

    section_1 = [
        *_ascii_table(
            "NEW SYSTEM TASKS",
            SYSTEM_TASK_COLUMNS,
            await _new_system_task_rows(db, department_codes),
        ),
        "",
        *_format_confirmation_questions(await _load_1h_confirmation_questions(db)),
    ]
    section_2 = await _personal_section(
        db, tasks, names, assignee_ids_by_task, report_day, department_codes=department_codes
    )
    blue_notes = await load_blue_notes(db)
    section_3 = _ascii_table("NOTES", BLUE_NOTE_COLUMNS, [values for _, values in blue_notes])
    ga_section, hv_section = await _m3_finance_ga_sections(db, tasks, names, report_day, include_ga_bz=True)

    sections = [
        {"section_key": NEW_EMAILS_TITLE, "title": NEW_EMAILS_TITLE,
         "body": _new_emails_report_body(mailboxes, report_day, generated_at)},
        {"section_key": PCM_PROJECTS_TITLE, "title": PCM_PROJECTS_TITLE, "body": await _load_pcm_projects_summary(db, report_day)},
        {"section_key": GA_REPLIES_SECTION_TITLE, "title": GA_REPLIES_SECTION_TITLE,
         "body": await summary_for_day(db, report_day, report="M2", generated_at=generated_at)},
        {"section_key": GA_REACTIONS_SECTION_KEY, "title": GA_REACTIONS_SECTION_TITLE,
         "body": await reaction_summary_for_day(db, report_day, report="M2", generated_at=generated_at)},
        {
            "title": SECTION_TITLES[4],
            "body": _normalize_section(
                _ascii_table(
                    UNFINISHED_PRIORITY_TABLE_LABEL,
                    UNFINISHED_PRIORITY_COLUMNS,
                    unfinished_priority_rows,
                    show_empty_table=True,
                )
            ),
        },
        {
            "title": SECTION_TITLES[5],
            "body": _normalize_section(
                _ascii_table(DONE_AM_TABLE_LABEL, DONE_AM_COLUMNS, done_am_rows)
            ),
        },
        {
            "title": SECTION_TITLES[12],
            "body": _normalize_section(
                _ascii_table(
                    WAITING_CLIENT_TABLE_LABEL,
                    WAITING_CLIENT_COLUMNS,
                    waiting_client_rows,
                )
            ),
        },
        {
            "title": SECTION_TITLES[6],
            "body": _normalize_section(unheld_meeting_section),
        },
        {"title": SECTION_TITLES[7], "body": _normalize_section(section_1)},
        {"title": SECTION_TITLES[8], "body": _normalize_section(section_2)},
        {"title": SECTION_TITLES[9], "body": _normalize_section(section_3)},
        {"title": SECTION_TITLES[10], "body": ga_section},
        {"title": SECTION_TITLES[11], "body": hv_section},
    ]
    sections_by_title = {section.get("section_key", section["title"]): section for section in sections}
    sections = [sections_by_title[title] for title in DISPLAY_SECTION_TITLES]
    snapshot = {
        "report_day": report_day.isoformat(),
        NEW_EMAILS_SNAPSHOT_KEY: mailboxes,
        NOTE_REFERENCES: blue_notes,
        "ga_replies_generated_at": generated_at.isoformat(),
        GA_REPLIES_CAPTURE_VERSION_KEY: GA_REPLIES_CAPTURE_VERSION,
        "counts": {
            NEW_EMAILS_TITLE: sum(len(inbox["messages"]) for inbox in mailboxes.values()),
            SECTION_TITLES[4]: len(unfinished_priority_rows),
            SECTION_TITLES[5]: len(done_am_rows),
            SECTION_TITLES[12]: len(waiting_client_rows),
            SECTION_TITLES[6]: unheld_meeting_count,
            SECTION_TITLES[7]: len(section_1),
            SECTION_TITLES[8]: len(section_2),
            SECTION_TITLES[9]: len(section_3),
            SECTION_TITLES[10]: ga_section.count("\n- ") + (1 if ga_section.startswith("- ") else 0),
            SECTION_TITLES[11]: hv_section.count("\n- ") + (1 if hv_section.startswith("- ") else 0),
        },
    }
    return await filter_report_sections(db, sections, report_day), snapshot


def render_plain_text(subject: str, report_day: date, sections: list[dict[str, str]]) -> str:
    blocks = [subject, f"Sot: {report_day:%d.%m.%Y}", ""]
    current_group = ""
    for index, section in enumerate(sections, 1):
        group = _section_group_label(section["title"], section.get("section_key"))
        if group != current_group:
            blocks.append(group)
            current_group = group
        blocks.append(f"{index}. {section['title']}\n{section.get('body') or ''}".strip())
    return "\n\n".join(blocks)


def _section_group_label(title: str, section_key: str | None = None) -> str:
    from app.services.meeting_point_manual_sync import section_group_label

    return section_group_label("after_break", title, section_key)


def render_html(subject: str, report_day: date, sections: list[dict[str, str]]) -> str:
    section_chunks: list[str] = []
    current_group = ""
    for index, section in enumerate(sections, 1):
        group = _section_group_label(section["title"], section.get("section_key"))
        if group != current_group:
            section_chunks.append(_render_group_label_html(group))
            current_group = group
        section_chunks.append(
            _render_section_block_html(index, section["title"], section.get("body") or "")
        )
    return _wrap_report_email_html(
        subject,
        f"Sot: {report_day:%d.%m.%Y}",
        "".join(section_chunks),
    )


async def send_after_break_report(
    subject: str,
    recipients: dict[str, list[str]],
    plain_text: str,
    html_body: str,
    *,
    report_day: date,
    sections: list[dict[str, str]],
) -> dict[str, Any]:
    return await send_section_report(
        subject, recipients, plain_text, html_body,
        report_code="M2", report_day=report_day, sections=sections,
    )
