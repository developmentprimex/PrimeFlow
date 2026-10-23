from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import smtplib
import ssl
import html
import io
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field

from app.services.compact_report_questions import question_parts, questions_html, layout_question_parts
from app.config import settings
from app.services.one_h_ga_summary import GaTaskCounts, build_ga_summary, summary_html, summary_text, TITLE as GA_SUMMARY_TITLE

logger = logging.getLogger(__name__)
REPORT_TYPE = "primeflow_1h"
REPORT_SENDER_EMAIL = "130primex.eu@gmail.com"
SLOTS = ("10:00", "11:00", "11:50", "14:10", "14:20", "16:00")
STATUS_ORDER = {"IN_PROGRESS": 0, "TODO": 1, "WAITING_CLIENT": 2, "DONE": 3}
STATUS_MARKERS = {
    "IN_PROGRESS": "🟡 IN PROGRESS",
    "TODO": "⚪ TODO",
    "WAITING_CLIENT": "🟣 WFE",
    "DONE": "✅ DONE",
}
REMINDER_CATEGORY_NORMALIZED = "pyetjet per 1h"
BOARD_REMINDER_SECTION_TITLE = "PYETJET PER 1H - BORD"
REMINDER_SECTION_TITLE = "STAFF - HAPAT PER 1H"
UNDISCUSSED_NOTES_SECTION_TITLE = "NOTA PA DISKUTUARA"
TECHNICAL_TAGS = re.compile(
    r"\[\[\s*/?\s*(?:added|done(?:\s*:\s*(?:grey|gray|blue|green))?)\s*\]\]",
    re.IGNORECASE,
)
ADDED_TAGS = re.compile(r"\[\[\s*/?\s*added\s*\]\]", re.IGNORECASE)
DONE_BLOCK = re.compile(
    r"\[\[\s*done(?:\s*:\s*(grey|gray|blue|green))?\s*\]\](.*?)\[\[\s*/\s*done\s*\]\]",
    re.IGNORECASE | re.DOTALL,
)
STRIKE_COLORS = {"grey": "#6b7280", "gray": "#6b7280", "blue": "#2563eb", "green": "#16a34a"}
STRIKE_TIMESTAMP_DISPLAY = re.compile(r"\s+\d{2}:\d{2}\s+\d{2}\.\d{2}\s*$", re.MULTILINE)
NUMBERED_ITEM = re.compile(r"(?<!\S)(\d+)\.\s*")
TRANSIENT_CODES = {429, 500, 502, 503, 504}
STATUS_COLORS = {
    "TODO": ("#fbcfe8", "#111827", "#ec4899"),
    "IN_PROGRESS": ("#fef3c7", "#111827", "#d97706"),
    "WAITING_CLIENT": ("#e2c15b", "#4f3a00", "#b8860b"),
    "DONE": ("#d4ffe1", "#14532d", "#22c55e"),
}
REPORT_STRIKE_LEGEND = (
    ("Blue strike", "Kryer ne intervalin e caktuar", STRIKE_COLORS["blue"]),
    ("Green strike", "Kryer me heret", STRIKE_COLORS["green"]),
    ("Grey strike", "Kryer dje", STRIKE_COLORS["grey"]),
)
ONE_H_MARKER_SYMBOLS = {
    "EXCLAMATION": "!",
    "CLIENT_URGENT": "!!!",
    "SHARE": "SHARE",
    "QUESTION": "?",
    "KA": "KA",
    "GENT": "GENT",
    "F": "F",
    "BZ1N1": "BZ1N1",
    "M2": "M2",
    "M3": "M3",
    "M2_M3": "M2/3",
    "MONITOR": "👁",
    "CLOSE": "X",
    "FLAG": "GA",
}
ONE_H_MARKER_LEGEND = (
    ("?", "PYETJE/PAQARTESI"),
    ("!", "DYSHIM/ NUK KUPTOHET DET"),
    ("!!!", "KLIENT/URGJENT"),
    ("SHARE", "DET QE DUHET SCREENSHARE ME GA"),
    ("👁", "KËRKON MONITORIM NGA DIKUSH TJETËR"),
    ("X", "MBYLL DETYREN"),
    ("M2", "DOREZIM DERI NE PAUZE"),
    ("M3", "DOREZIM DERI NE FUND TE DITES"),
    ("M2/3", "DOREZIM EDHE NE M2 EDHE M3"),
    ("GENT", "PYETJE/SQARIM ME GENTIN"),
    ("KA", "PYETJE/SQARIM ME KA"),
    ("GA", "PYETJE/SQARIM ME GA"),
    ("F", "DET FIZIKISHT"),
    ("BZ1N1", ""),
)
BLOCKED_SECTION_TITLE_PREFIX = "BLLOK 14:30-16:00"


class GmailVerificationError(RuntimeError):
    def __init__(self, message: str, response: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.response = response or {}


class ReportTask(BaseModel):
    task_id: str = ""
    title: str
    description: str
    marked_title: str = ""
    marked_description: str = ""
    department: str = "-"
    status: str
    marker: str
    one_h_marker: str = ""
    strike_count: int | None = None


def one_h_marker_symbol(value: Any) -> str:
    return ONE_H_MARKER_SYMBOLS.get(str(value or "").strip().upper(), "")


def one_h_marker_legend_text() -> str:
    return "LEGJENDA: " + " / ".join(
        f"{symbol} - {description}" if description else symbol
        for symbol, description in ONE_H_MARKER_LEGEND
    )


class ReportEmployee(BaseModel):
    name: str
    tasks: list[ReportTask] = Field(default_factory=list)


class ReportSection(BaseModel):
    title: str
    employees: list[ReportEmployee] = Field(default_factory=list)


class ReportReminderQuestion(BaseModel):
    text: str
    guidance: str = ""
    is_extra: bool = False


class ReportUndiscussedNote(BaseModel):
    content: str
    author: str = "-"
    created_at: datetime | None = None


def _board_reminder_questions(report_day: date | None = None) -> list[ReportReminderQuestion]:
    questions = [
        ReportReminderQuestion(text="Slotin paraprak/aktual"),
        ReportReminderQuestion(text="A ke filluar me slotin aktual?"),
        ReportReminderQuestion(text="Nese jo, kur?"),
        ReportReminderQuestion(text="A kryhet sot?"),
        ReportReminderQuestion(text="A kryhet kete jave?"),
        ReportReminderQuestion(text="A arrihet RLZ javor?"),
        ReportReminderQuestion(text="Notes te reja? Data? AM/PM? Kujt"),
        ReportReminderQuestion(text="Done? / Strikes?"),
        ReportReminderQuestion(
            text="BZ Det nga Stafi per GA",
            guidance="Komunikimi GA teams Det nga Stafi/ KA email",
        ),
        ReportReminderQuestion(text="BZ Notes", guidance="Secili i lexon vet para BZ me GA"),
    ]
    if report_day is not None and report_day.weekday() == 3:
        questions.append(ReportReminderQuestion(text="Planifikimi javor short", is_extra=True))
    return questions


def _partition_reminder_questions(
    questions: list[ReportReminderQuestion],
) -> tuple[list[tuple[int, ReportReminderQuestion]], list[tuple[int, ReportReminderQuestion]]]:
    """Return day-specific extras first, numbering each group from one."""
    extras = [question for question in questions if question.is_extra]
    regular = [question for question in questions if not question.is_extra]
    return (
        list(enumerate(extras, 1)),
        list(enumerate(regular, 1)),
    )


def _split_board_regular_questions(
    questions: list[ReportReminderQuestion],
) -> tuple[list[tuple[int, ReportReminderQuestion]], list[tuple[int, ReportReminderQuestion]]]:
    """Return Board follow-up questions first and primary questions second."""
    regular = [question for question in questions if not question.is_extra]
    follow_up_texts = {
        "Notes te reja? Data? AM/PM? Kujt",
        "Done? / Strikes?",
        "BZ Det nga Stafi per GA",
        "BZ Notes",
    }
    follow_up = [question for question in regular if question.text in follow_up_texts]
    primary = [question for question in regular if question.text not in follow_up_texts]
    return list(enumerate(follow_up, 1)), list(enumerate(primary, 1))


def _day_specific_question_label(report_day: date | None) -> str:
    if report_day is not None and report_day.weekday() == 3:
        return "E ENJTE- PYETJET E TE ENJTES"
    if report_day is not None and report_day.weekday() == 4:
        return "E PREMTE"
    return "PYETJET SHTESE: 0"


THURSDAY_QUESTION_REPORT_CODES = {
    "Emails per missing info, per me vazhdu javen tjeter": "M1",
    "Shikohen det qe mbesin vetem per neser (te premten)": "M3",
    "Planifikimi javor short": "M1",
}
FRIDAY_QUESTION_REPORT_CODES = {
    "BZ PERSONALISHT ME GA: KOMENTET TEK OPEN TASKS EXCEL": "M1",
    "BZ PERSONALISHT ME GA: DET GA TEK PER/NGA STAFI PER GA TEAMS": "M1",

    "Barazimi i planifikimit javor - next week": "M1",
    "Barazimi i realizimit javor - this week": "M1",
    "Emails per missing info, per me vazhdu javen tjeter": "M1",
}


def _reminder_question_number(
    index: int, question: ReportReminderQuestion, report_day: date | None
) -> str:
    report_codes = (
        THURSDAY_QUESTION_REPORT_CODES if report_day is not None and report_day.weekday() == 3
        else FRIDAY_QUESTION_REPORT_CODES if report_day is not None and report_day.weekday() == 4
        else {}
    )
    report_code = report_codes.get(question.text)
    return f"{report_code} - {index}." if report_code else f"{index}."


def _extra_question_parts(document):
    return question_parts(_day_specific_question_label(document.report_date), [
        [f"{_reminder_question_number(index, question, document.report_date)} {question.text}"
         + (f" ({question.guidance})" if question.guidance else "")
         for index, question in _partition_reminder_questions(questions)[0]]
        for questions in (document.reminders, document.board_reminders)
    ])


class ReportDocument(BaseModel):
    subject: str
    report_date: date
    report_slot: str
    generated_at: datetime
    source_generated_at: datetime
    recipients: dict[str, list[str]]
    sections: list[ReportSection]
    board_reminders: list[ReportReminderQuestion] = Field(default_factory=_board_reminder_questions)
    reminders: list[ReportReminderQuestion] = Field(default_factory=list)
    undiscussed_notes: list[ReportUndiscussedNote] = Field(default_factory=list)
    ga_task_summary: list[GaTaskCounts] = Field(default_factory=list)
    truncated: bool = False
    strike_interval: str | None = None

    @property
    def task_count(self) -> int:
        return sum(len(employee.tasks) for section in self.sections for employee in section.employees)

    @property
    def strike_total(self) -> int | None:
        counts: dict[str, int] = {}
        for section in self.sections:
            for employee in section.employees:
                for task in employee.tasks:
                    if task.strike_count is not None:
                        # Shared tasks can appear under several people or slots.
                        key = task.task_id or str(id(task))
                        counts[key] = max(counts.get(key, 0), task.strike_count)
        return sum(counts.values()) if counts or self.strike_interval else None


def strike_count_label(count: int, document: ReportDocument, *, total: bool = False) -> str:
    label = f"{'Total strikes' if total else 'Strikes'}: {count}"
    return f"{label} · {document.strike_interval}" if document.strike_interval else label


def report_timezone() -> ZoneInfo:
    return ZoneInfo(os.getenv("PRIMEFLOW_REPORT_TIMEZONE", "Europe/Tirane"))


def previous_working_day(day: date, holidays: set[date] | None = None) -> date:
    holidays = holidays or set()
    candidate = day - timedelta(days=1)
    while candidate.weekday() >= 5 or candidate in holidays:
        candidate -= timedelta(days=1)
    return candidate


def report_subject(day: date, slot: str) -> str:
    if slot not in SLOTS:
        raise ValueError(f"Unsupported report slot: {slot}")
    # Subjects are plain text in Gmail. Brackets give the leading time a
    # strong, consistent visual treatment without relying on unsupported HTML.
    return f"【{slot}】 PrimeFlow 1H - {day:%d.%m.%Y}"


def exact_subject(headers: list[dict[str, str]], expected: str) -> bool:
    return any(h.get("name", "").lower() == "subject" and h.get("value") == expected for h in headers)


def clean_description(value: str | None) -> str:
    cleaned = TECHNICAL_TAGS.sub("", value or "")
    return STRIKE_TIMESTAMP_DISPLAY.sub("", re.sub(r"[ \t]+", " ", cleaned)).strip()


def clean_title(value: str | None) -> str:
    return clean_description(value)


def preserve_done_marks(value: str | None) -> str:
    return ADDED_TAGS.sub("", value or "").strip()


def split_numbered_text(value: str) -> tuple[str, list[str]]:
    matches = list(NUMBERED_ITEM.finditer(value))
    if not matches:
        return value.strip(), []
    heading = value[:matches[0].start()].strip()
    items = [
        value[match.start():matches[index + 1].start() if index + 1 < len(matches) else len(value)].strip()
        for index, match in enumerate(matches)
    ]
    return heading, items


def split_task_display(title: str) -> tuple[str, list[str]]:
    """First line stays the black title; every following line renders grey."""
    heading, numbered_items = split_numbered_text(title)
    heading_lines = [line.strip() for line in heading.splitlines() if line.strip()]
    if not heading_lines:
        return "", numbered_items
    return heading_lines[0], [*heading_lines[1:], *numbered_items]


def done_ranges(value: str, marked_source: str) -> list[tuple[int, int, str]]:
    ranges = []
    cursor = 0
    for match in DONE_BLOCK.finditer(marked_source):
        selected = TECHNICAL_TAGS.sub("", match.group(2))
        start = value.find(selected, cursor)
        if start >= 0:
            colour = STRIKE_COLORS.get((match.group(1) or "grey").lower(), STRIKE_COLORS["grey"])
            ranges.append((start, start + len(selected), colour))
            cursor = start + len(selected)
    return ranges


def task_calendar_day(raw: Any) -> date | None:
    """Read timestamp deadlines in the report timezone, preserving date-only values."""
    if isinstance(raw, datetime):
        parsed = raw
    elif isinstance(raw, date):
        return raw
    else:
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(report_timezone())
    return parsed.date()


def _task_date(item: dict[str, Any]) -> date | None:
    raw = item.get("report_date") or item.get("date") or item.get("day")
    if not raw:
        raw = item.get("planned_for") or item.get("due_date") or item.get("start_date")
    return task_calendar_day(raw)


def _slot(item: dict[str, Any]) -> str | None:
    return item.get("one_h_report_slot") or item.get("slot") or item.get("time_slot")


def _completed_in_report_window(
    item: dict[str, Any],
    *,
    window_start: datetime | None,
    window_end: datetime | None,
) -> bool:
    """Keep DONE tasks only in the 1H window in which they were completed."""

    status = str(item.get("status") or "").upper()
    if status not in {"DONE", "COMPLETED"} or window_start is None or window_end is None:
        return True
    raw_completed_at = item.get("completed_at") or item.get("completedAt")
    if not raw_completed_at:
        # Legacy rows can be DONE without a completion timestamp. Retaining
        # them is safer than silently dropping work whose interval is unknown.
        return True
    try:
        completed_at = datetime.fromisoformat(str(raw_completed_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=window_end.tzinfo)
    return window_start < completed_at <= window_end


def _source_slot_for_report_slot(slot: str) -> str:
    """The internal 14:10 report remains distinct from the 14:20 Today digest."""
    return "14:20" if slot == "14:10" else slot


def _employee(item: dict[str, Any]) -> str:
    return str(
        item.get("employee") or item.get("person") or item.get("owner")
        or item.get("user_name") or item.get("assignee_name") or item.get("user") or ""
    ).strip()


def employee_initials(name: str) -> str:
    parts = re.findall(r"[^\W\d_]+", name, flags=re.UNICODE)
    return "".join(part[0] for part in parts).upper()


def _weekly_planner_user_sort_key(item: dict[str, Any]) -> tuple[int, str, int, int, str] | None:
    """Read the user order supplied by the Common View payload.

    Common View assigns this key to 1H rows using the same department and
    Weekly Planner user order used by M1, M2, and M3.  Keep it as payload
    metadata so the report can use one normalized order for every output.
    """
    raw = item.get("weekly_planner_sort") or item.get("weeklyPlannerSort")
    if not isinstance(raw, (list, tuple)) or len(raw) < 5:
        return None
    try:
        return (
            int(raw[0]),
            str(raw[1]).casefold(),
            int(raw[2]),
            int(raw[3]),
            str(raw[4]).casefold(),
        )
    except (TypeError, ValueError):
        return None


def _employee_sort_key(employee: str, tasks: list[dict[str, Any]]) -> tuple[int, str, int, int, str]:
    keys = [key for task in tasks if (key := _weekly_planner_user_sort_key(task)) is not None]
    return min(keys) if keys else (10**6, "~", 1, 10**6, employee.casefold())


def _group_tasks_by_employee(tasks: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        grouped.setdefault(_employee(task), []).append(task)
    return sorted(grouped.items(), key=lambda group: _employee_sort_key(*group))


def filter_tasks(
    items: list[dict[str, Any]], day: date, slot: str | None = None,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for item in items:
        employee = _employee(item)
        title = item.get("task_title") or item.get("title") or item.get("task")
        if not employee or not str(title or "").strip() or _task_date(item) != day:
            continue
        if slot is not None and _slot(item) != slot:
            continue
        key = str(item.get("id") or json.dumps(item, sort_keys=True, default=str))
        if key in seen:
            continue
        seen.add(key)
        status = str(item.get("status") or "").upper()
        if status not in STATUS_ORDER:
            logger.error("Unexpected task status task_id=%s status=%s", key, status)
            continue
        result.append(item)
    return result


def _merge_unique_tasks(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            key = str(item.get("task_id") or item.get("id") or id(item))
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
    return result


def _render_section(title: str, tasks: list[dict[str, Any]]) -> str:
    lines = [title]
    employee_groups = _group_tasks_by_employee(tasks)
    for employee_index, (employee, employee_tasks) in enumerate(employee_groups, 1):
        lines.append(f"{employee_index}. {employee}")
        ordered = sorted(employee_tasks, key=lambda x: (STATUS_ORDER[str(x.get("status")).upper()], str(x.get("task_title") or x.get("title") or x.get("task"))))
        for task_index, task in enumerate(ordered, 1):
            status = str(task.get("status")).upper()
            title_value = clean_title(str(task.get("task_title") or task.get("title") or task.get("task")))
            description = clean_description(task.get("description") if "description" in task else task.get("note"))
            lines.extend([f"{employee_index}.{task_index} {STATUS_MARKERS[status]} {title_value}", "Përshkrimi:", description])
    if not employee_groups:
        lines.append("(Asnjë detyrë)")
    return "\n".join(lines)


def _document_section(
    title: str,
    tasks: list[dict[str, Any]],
    title_overrides: dict[str, tuple[str, str]] | None = None,
    description_overrides: dict[str, tuple[str, str]] | None = None,
    department_codes: dict[str, str] | None = None,
) -> ReportSection:
    employees = []
    for employee, employee_tasks in _group_tasks_by_employee(tasks):
        ordered = sorted(employee_tasks, key=lambda x: (
            STATUS_ORDER[str(x.get("status")).upper()],
            str(x.get("task_title") or x.get("title") or x.get("task")),
        ))
        report_tasks = []
        for task in ordered:
            # Common View's `title` is the full source-note content when a
            # task comes from GA/KA or PX notes. `task_title` is only its
            # one-line task label, so it must not hide the numbered points.
            raw_title = str(task.get("title") or task.get("task_title") or task.get("task"))
            raw_description = task.get("description") if "description" in task else task.get("note")
            task_id = str(task.get("task_id") or task.get("id") or "")
            title_override = (title_overrides or {}).get(task_id)
            description_override = (description_overrides or {}).get(task_id)
            marked_title = title_override[1] if title_override else preserve_done_marks(raw_title)
            marked_description = description_override[1] if description_override else preserve_done_marks(raw_description)
            # Same blue point markers counted by count_struck_points_for_interval.
            # Count both source fields, even when duplicate display text is hidden.
            strike_count = sum(
                (match.group(1) or "").lower() == "blue"
                for marked in (marked_title, marked_description) for match in DONE_BLOCK.finditer(marked)
            )
            description_duplicates_title = bool(raw_description) and (
                clean_description(raw_description) == clean_title(raw_title)
            )
            department_id = str(task.get("department_id") or task.get("departmentId") or "")
            department = (
                task.get("department_code")
                or task.get("departmentCode")
                or (department_codes or {}).get(department_id)
                or "-"
            )
            report_tasks.append(ReportTask(
                task_id=task_id,
                title=clean_title(title_override[0]) if title_override else clean_title(raw_title),
                description="" if description_duplicates_title else (
                    clean_description(description_override[0]) if description_override else clean_description(raw_description)
                ),
                marked_title=marked_title,
                marked_description="" if description_duplicates_title else marked_description,
                department=str(department).strip() or "-",
                status=str(task.get("status")).upper(),
                marker=STATUS_MARKERS[str(task.get("status")).upper()],
                one_h_marker=one_h_marker_symbol(task.get("one_h_marker") or task.get("oneHMarker")),
                strike_count=strike_count,
            ))
        employees.append(ReportEmployee(
            name=employee_initials(employee),
            tasks=report_tasks,
        ))
    return ReportSection(title=title, employees=employees)


def build_report_document(
    data: dict[str, Any],
    report_day: date,
    slot: str,
    recipients: dict[str, list[str]] | None = None,
    reminders: list[ReportReminderQuestion] | None = None,
    title_overrides: dict[str, tuple[str, str]] | None = None,
    description_overrides: dict[str, tuple[str, str]] | None = None,
    undiscussed_notes: list[ReportUndiscussedNote] | None = None,
    completion_window_start: datetime | None = None,
    completion_window_end: datetime | None = None,
) -> ReportDocument:
    guardrails = data.get("guardrails") or {}
    truncated = any((guardrails.get("truncated") or {}).values())
    if truncated:
        raise ValueError("Common View contains truncated buckets")
    source_items = data.get("items") or {}
    items = {
        bucket: (
            [
                item for item in values
                if _completed_in_report_window(
                    item,
                    window_start=completion_window_start,
                    window_end=completion_window_end,
                )
            ]
            if isinstance(values, list) else values
        )
        for bucket, values in source_items.items()
    }
    department_codes = {
        str(department.get("id")): str(department.get("code") or "").strip()
        for department in (data.get("departments") or [])
        if isinstance(department, dict) and department.get("id")
    }
    fallback_tasks = [
        item for item in (data.get("tasks") or [])
        if _completed_in_report_window(
            item,
            window_start=completion_window_start,
            window_end=completion_window_end,
        )
    ]
    one_h = items.get("oneH") or fallback_tasks
    done_this_window = [
        task for task in filter_tasks(one_h, report_day)
        if str(task.get("status") or "").upper() in {"DONE", "COMPLETED"}
        and bool(task.get("completed_at") or task.get("completedAt"))
    ]
    definitions: list[tuple[str, list[dict[str, Any]]]] = []
    if slot in {"10:00", "14:20"}:
        # The morning report is the full-day baseline. The new 14:20 report
        # repeats today's work completed or planned through 14:20 only.
        candidate_slots = ("10:00", "11:00", "11:50", "14:20", "16:00") if slot == "10:00" else (
            "10:00", "11:00", "11:50", "14:20"
        )
        for candidate in candidate_slots:
            candidate_tasks = filter_tasks(one_h, report_day, candidate)
            if slot == "14:20" and candidate == "14:20":
                # A task completed during this interval belongs in this report
                # even if it had been planned for the later 16:00 slot.
                candidate_tasks = _merge_unique_tasks(candidate_tasks, [
                    task for task in done_this_window
                    if _slot(task) not in {*candidate_slots, None}
                ])
            definitions.append(
                (
                    f"{candidate} SLOTI {report_day:%d.%m.%Y}",
                    candidate_tasks,
                )
            )
        definitions.extend([
            ("DETYRA PA SLOT – E GJITHË DITA", [
                task for task in filter_tasks(one_h, report_day, None) if _slot(task) is None
            ]),
            ("P: PERSONALE", filter_tasks(items.get("personal") or [], report_day)),
            ("R1 = 1H", filter_tasks(items.get("r1") or [], report_day)),
        ])
    else:
        previous_slot = SLOTS[SLOTS.index(slot) - 1]
        source_slot = _source_slot_for_report_slot(slot)
        previous_source_slot = _source_slot_for_report_slot(previous_slot)
        current_tasks = _merge_unique_tasks(
            filter_tasks(one_h, report_day, source_slot),
            [
                task for task in done_this_window
                if _slot(task) not in {source_slot, previous_source_slot}
            ],
        )
        definitions.extend([
            (
                f"{slot} SLOTI {report_day:%d.%m.%Y}",
                current_tasks,
            ),
            (
                f"{previous_slot} SLOTI PARAPRAK {report_day:%d.%m.%Y}",
                filter_tasks(one_h, report_day, _source_slot_for_report_slot(previous_slot)),
            ),
        ])
        # The normal afternoon report uses the internal 14:10 identity so it
        # stays distinct from the Today digest when both deliver at 14:20.
        # It covers the 14:20 task bucket and keeps BLL work visible.
        if slot == "14:10":
            definitions.append((
                f"{BLOCKED_SECTION_TITLE_PREFIX} {report_day:%d.%m.%Y}",
                filter_tasks(items.get("blocked") or [], report_day),
            ))
    generated_value = data.get("generated_at") or datetime.now(report_timezone()).isoformat()
    source_generated = datetime.fromisoformat(str(generated_value).replace("Z", "+00:00"))
    return ReportDocument(
        subject=report_subject(report_day, slot),
        report_date=report_day,
        report_slot=slot,
        generated_at=datetime.now(report_timezone()),
        source_generated_at=source_generated,
        recipients=recipients or {"to": [], "cc": [], "bcc": []},
        strike_interval=(f"{completion_window_start:%H:%M}–{completion_window_end:%H:%M}"
                         if completion_window_start and completion_window_end else None),
        sections=[
            _document_section(
                title,
                tasks,
                title_overrides,
                description_overrides,
                department_codes,
            )
            for title, tasks in definitions
        ],
        board_reminders=_board_reminder_questions(report_day),
        reminders=list(reminders or []),
        undiscussed_notes=list(undiscussed_notes or []),
        ga_task_summary=build_ga_summary(data, [
            (task, bucket == "personal")
            for bucket in ("oneH", "blocked", "important", "r1", "personal")
            for task in filter_tasks(one_h if bucket == "oneH" else items.get(bucket) or [], report_day)
        ]),
    )


def render_plain_text(document: ReportDocument) -> str:
    symbol_legend = one_h_marker_legend_text()
    blocks = [document.subject, f"Generated: {document.generated_at.isoformat()}", symbol_legend, ""]
    if document.strike_total is not None:
        blocks.insert(2, strike_count_label(document.strike_total, document, total=True))
    reminder_groups = (
        (BOARD_REMINDER_SECTION_TITLE, document.board_reminders),
        (REMINDER_SECTION_TITLE, document.reminders),
    )
    blocks.append("".join(text for text, _ in _extra_question_parts(document)))
    for reminder_title, questions in reminder_groups:
        if not questions:
            continue
        reminder_lines = [reminder_title]
        groups = _split_board_regular_questions(questions) if reminder_title == BOARD_REMINDER_SECTION_TITLE else (_partition_reminder_questions(questions)[1],)
        for group_index, regular_questions in enumerate(groups):
            if group_index:
                reminder_lines.append("")
            for index, question in regular_questions:
                reminder_lines.append(f"{_reminder_question_number(index, question, document.report_date)} {question.text}")
                if question.guidance:
                    reminder_lines.append(f"   {question.guidance}")
        blocks.append("\n".join(reminder_lines))
    if document.ga_task_summary:
        blocks.append(GA_SUMMARY_TITLE + "\n" + summary_text(document.ga_task_summary))
    if document.undiscussed_notes:
        note_lines = [UNDISCUSSED_NOTES_SECTION_TITLE, "NR | NOTE | KUSH | DATA"]
        for index, note in enumerate(document.undiscussed_notes, 1):
            created = note.created_at.astimezone(report_timezone()).strftime("%d.%m %H:%M") if note.created_at else "-"
            note_lines.append(f"{index} | {note.content} | {note.author} | {created}")
        blocks.append("\n".join(note_lines))
    for section in document.sections:
        lines = [section.title]
        if not section.employees:
            lines.append("(Asnjë detyrë)")
        for employee in section.employees:
            lines.append(employee.name)
            for task in employee.tasks:
                heading, detail_lines = split_task_display(task.title)
                if heading:
                    lines.append(f"{task.one_h_marker} {heading}".strip())
                lines.extend(detail_lines)
                if task.description:
                    lines.append(task.description)
                if task.strike_count is not None:
                    lines.append(strike_count_label(task.strike_count, document))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def add_preview_strike_filter(report_html: str) -> str:
    """Add a local view filter to the preview, keeping delivery/exports static."""
    controls = '''<div style="margin:0 0 12px;font-family:Arial,sans-serif;">
<button type="button" id="one-h-strikes-filter" aria-pressed="false"
style="padding:8px 12px;border:1px solid #cbd5e1;border-radius:6px;background:#f8fafc;color:#0f172a;font:700 13px Arial,sans-serif;cursor:pointer;">
Vetëm me strikes &gt; 0</button>
<span id="one-h-strikes-filter-status" role="status" style="margin-left:10px;font-size:12px;color:#475569;"></span>
<p id="one-h-strikes-filter-empty" hidden style="padding:12px;background:#f8fafc;border:1px solid #cbd5e1;border-radius:6px;font-size:13px;">
Nuk ka detyra me strikes &gt; 0 në këtë interval.</p>
</div>
<script>
(function () {
  const button = document.getElementById('one-h-strikes-filter');
  button.addEventListener('click', function () {
    const selected = button.getAttribute('aria-pressed') !== 'true';
    button.setAttribute('aria-pressed', String(selected));
    button.style.background = selected ? '#dbeafe' : '#f8fafc';
    button.style.borderColor = selected ? '#2563eb' : '#cbd5e1';
    button.style.color = selected ? '#1e40af' : '#0f172a';
    let visible = 0;
    document.querySelectorAll('[data-report-task="true"]').forEach(function (task) {
      task.hidden = selected && !(Number(task.dataset.strikeCount) > 0);
      if (!task.hidden) visible += 1;
    });
    document.querySelectorAll('[data-report-task-employee], [data-report-task-section]').forEach(function (group) {
      group.hidden = selected && !group.querySelector('[data-report-task="true"]:not([hidden])');
    });
    document.querySelectorAll('[data-report-supplement]').forEach(function (group) { group.hidden = selected; });
    document.getElementById('one-h-strikes-filter-status').textContent = 'Shfaqen ' + visible + ' detyra';
    document.getElementById('one-h-strikes-filter-empty').hidden = !selected || visible > 0;
  });
})();
</script>'''
    return report_html.replace("<!-- report-strike-filter -->", controls, 1)


def render_html(
    document: ReportDocument,
    *,
    pre_sections_html: str = "",
    content_width: int = 600,
) -> str:
    """Outlook-safe 1H HTML: nested tables, inline styles, bgcolor (Word engine)."""

    def marked_html(value: str, marked_source: str) -> str:
        ranges = done_ranges(value, marked_source)
        boundaries = sorted({0, len(value), *(point for start, end, _colour in ranges for point in (start, end))})
        parts = []
        for start, end in zip(boundaries, boundaries[1:]):
            content = html.escape(value[start:end]).replace(chr(10), "<br>")
            mark = next((item for item in ranges if item[0] <= start and item[1] >= end), None)
            if mark is not None:
                content = (
                    f"<span style=\"color:{mark[2]};text-decoration:line-through;text-decoration-thickness:2px;\">"
                    f"{content}</span>"
                )
            parts.append(content)
        return "".join(parts)

    def detail_row(content: str) -> str:
        return (
            f"<div style=\"font-family:Arial,sans-serif;font-size:13px;line-height:1.4;"
            f"color:#64748b;font-weight:400;margin:5px 0 0;\">{content}</div>"
        )

    def marker_badge(symbol: str) -> str:
        if not symbol:
            return ""
        return (
            '<span data-task-symbol="true" style="display:inline-block;min-width:22px;'
            'margin-right:7px;padding:2px 6px;border:1px solid #93c5fd;border-radius:5px;'
            'background-color:#eff6ff;color:#dc2626;font-size:16px;font-weight:900;'
            f'line-height:1;text-align:center;">{html.escape(symbol)}</span>'
        )

    def strike_badge(task: ReportTask) -> str:
        if task.strike_count is None:
            return ""
        active = task.strike_count > 0
        return (
            '<div data-task-strike-count="true" style="display:table;margin-top:5px;padding:2px 5px;'
            f'border:1px solid {"#2563eb" if active else "#94a3b8"};border-radius:4px;'
            f'background-color:{"#dbeafe" if active else "#f8fafc"};color:{"#1e40af" if active else "#475569"};'
            'font:700 10px/1.4 Arial,sans-serif;">'
            f'{html.escape(strike_count_label(task.strike_count, document))}</div>'
        )

    def task_card(background: str, accent: str, title_html: str, body_html: str, strike_count: int | None) -> str:
        # Left accent as its own cell — Outlook ignores CSS border-left reliably.
        return (
            "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" "
            f'data-report-task="true" data-strike-count="{strike_count if strike_count is not None else "unknown"}" '
            "style=\"width:100%;border-collapse:collapse;margin:8px 0;\">"
            "<tr>"
            f"<td width=\"6\" bgcolor=\"{accent}\" style=\"width:6px;background-color:{accent};"
            f"font-size:0;line-height:0;\">&nbsp;</td>"
            f"<td bgcolor=\"{background}\" style=\"background-color:{background};border:1px solid {accent};"
            f"border-left:0;padding:10px 12px;font-family:Arial,sans-serif;\">"
            f"<div style=\"font-family:Arial,sans-serif;font-size:14px;line-height:1.35;"
            f"font-weight:700;color:#050505;\">{title_html}</div>"
            f"{body_html}"
            "</td></tr></table>"
        )

    def section_title_block(title: str) -> str:
        return (
            "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" "
            "style=\"width:100%;border-collapse:collapse;margin:18px 0 10px;\">"
            "<tr>"
            "<td width=\"6\" bgcolor=\"#2563eb\" style=\"width:6px;background-color:#2563eb;"
            "font-size:0;line-height:0;\">&nbsp;</td>"
            "<td bgcolor=\"#eef2ff\" style=\"background-color:#eef2ff;padding:11px 14px;"
            "font-family:Arial,sans-serif;font-size:16px;font-weight:800;color:#0f172a;\">"
            f"{html.escape(title)}"
            "</td></tr></table>"
        )

    def section_separator() -> str:
        """A reliable visual break between report slots in Gmail and Outlook."""
        return (
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'data-report-section-separator="true" '
            'style="width:100%;border-collapse:collapse;margin:30px 0 4px;">'
            '<tr><td height="4" bgcolor="#334155" '
            'style="height:4px;line-height:4px;font-size:0;background-color:#334155;">&nbsp;</td></tr>'
            '</table>'
        )

    def bll_task_table(section: ReportSection) -> str:
        """Compact BLL table used at the end of the normal afternoon report."""
        rows: list[str] = []
        number = 0
        for employee in section.employees:
            for task in employee.tasks:
                number += 1
                background, _, accent = STATUS_COLORS[task.status]
                heading, detail_lines = split_task_display(task.title)
                details = "".join(
                    detail_row(marked_html(item, task.marked_title)) for item in detail_lines
                )
                if task.description:
                    details += detail_row(marked_html(task.description, task.marked_description))
                details += strike_badge(task)
                rows.append(
                    f'<tr data-report-task="true" data-strike-count="{task.strike_count if task.strike_count is not None else "unknown"}">'
                    f'<td style="padding:9px;border:1px solid #cbd5e1;text-align:center;font-family:Arial,sans-serif;">{number}</td>'
                    f'<td style="padding:9px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;font-weight:700;">{html.escape(employee.name)}</td>'
                    f'<td style="padding:9px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;">{html.escape(task.department)}</td>'
                    f'<td bgcolor="{background}" style="padding:9px;border:1px solid {accent};font-family:Arial,sans-serif;">'
                    f'<div style="font-size:14px;font-weight:700;color:#050505;">{marker_badge(task.one_h_marker)}{marked_html(heading or task.title, task.marked_title)}</div>{details}'
                    "</td></tr>"
                )
        if not rows:
            rows.append(
                '<tr><td colspan="4" style="padding:10px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;color:#64748b;">(Asnjë detyrë)</td></tr>'
            )
        return (
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'data-bll-task-table="true" style="width:100%;border-collapse:collapse;margin:8px 0 4px;">'
            '<tr bgcolor="#e2e8f0">'
            '<th style="padding:8px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;text-align:center;font-size:12px;">NR</th>'
            '<th style="padding:8px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;text-align:left;font-size:12px;">KUSH</th>'
            '<th style="padding:8px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;text-align:left;font-size:12px;">DEP</th>'
            '<th style="padding:8px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;text-align:left;font-size:12px;">TITULLI</th>'
            "</tr>"
            f"{''.join(rows)}"
            "</table>"
        )

    def undiscussed_notes_table(notes: list[ReportUndiscussedNote]) -> str:
        rows = []
        for index, note in enumerate(notes, 1):
            created = note.created_at.astimezone(report_timezone()).strftime("%d.%m %H:%M") if note.created_at else "-"
            rows.append(
                '<tr bgcolor="#dbeafe" style="background-color:#dbeafe;">'
                f'<td bgcolor="#dbeafe" style="background-color:#dbeafe;padding:8px;border:1px solid #93c5fd;text-align:center;font-family:Arial,sans-serif;vertical-align:top;">{index}</td>'
                f'<td bgcolor="#dbeafe" style="background-color:#dbeafe;padding:8px;border:1px solid #93c5fd;font-family:Arial,sans-serif;vertical-align:top;white-space:pre-wrap;">{html.escape(note.content).replace(chr(10), "<br>")}</td>'
                f'<td bgcolor="#dbeafe" style="background-color:#dbeafe;padding:8px;border:1px solid #93c5fd;font-family:Arial,sans-serif;vertical-align:top;">{html.escape(note.author)}</td>'
                f'<td bgcolor="#dbeafe" style="background-color:#dbeafe;padding:8px;border:1px solid #93c5fd;font-family:Arial,sans-serif;vertical-align:top;white-space:nowrap;">{created}</td>'
                "</tr>"
            )
        return (
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'data-undiscussed-notes-table="true" style="width:100%;border-collapse:collapse;margin:8px 0 4px;">'
            '<tr bgcolor="#e2e8f0">'
            '<th style="padding:8px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;text-align:center;font-size:12px;">NR</th>'
            '<th style="padding:8px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;text-align:left;font-size:12px;">NOTE</th>'
            '<th style="padding:8px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;text-align:left;font-size:12px;">KUSH</th>'
            '<th style="padding:8px;border:1px solid #cbd5e1;font-family:Arial,sans-serif;text-align:left;font-size:12px;">DATA</th>'
            '</tr>'
            f"{''.join(rows)}"
            "</table>"
        )

    def reminder_column(
        title: str,
        questions: list[ReportReminderQuestion],
        *,
        show_title: bool = True,
        show_extra: bool = True,
        show_regular: bool = True,
        split_board: bool = False,
    ) -> str:
        def reminder_card(
            indexed_questions: list[tuple[int, ReportReminderQuestion]], *, extra: bool
        ) -> str:
            if not indexed_questions:
                return ""
            text_color = "#b91c1c" if extra else "#0f172a"
            guidance_color = "#dc2626" if extra else "#64748b"
            accent = "#dc2626" if extra else "#64748b"
            border = "#dc2626" if extra else "#94a3b8"
            background = "#fff7f7" if extra else "#f8fafc"
            question_parts = []
            for index, question in indexed_questions:
                guidance = (
                    f' <span style="color:{guidance_color};font-weight:400;">'
                    f'({html.escape(question.guidance).replace(chr(10), " / ")})</span>'
                    if question.guidance else ""
                )
                item_tag = "div" if extra else "span"
                item_style = "display:block;white-space:normal;" if extra else "white-space:normal;"
                question_parts.append(
                    f'<{item_tag} style="{item_style}"><strong>{html.escape(_reminder_question_number(index, question, document.report_date))}</strong> '
                    f'{html.escape(question.text)}{guidance}</{item_tag}>'
                )
            data_attribute = ' data-extra-reminder-card="true"' if extra else ""
            margin = "0 0 8px" if extra else "0"
            return (
                '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
                f'data-compact-reminder-row="true"{data_attribute} '
                f'style="width:100%;border-collapse:collapse;margin:{margin};">'
                f'<tr><td bgcolor="{background}" style="background-color:{background};border:1px solid {border};'
                f'border-left:6px solid {accent};padding:9px 10px;font-family:Arial,sans-serif;'
                f'font-size:13px;line-height:1.45;color:{text_color};">'
                + (
                    "".join(question_parts)
                    if extra
                    else f' <strong style="display:inline-block;color:{accent};font-size:20px;line-height:1;'
                    'font-weight:900;vertical-align:-2px;padding:0 5px;">/</strong> '.join(question_parts)
                )
                + '</td></tr></table>'
            )

        extra_questions, regular_questions = _partition_reminder_questions(questions)
        regular_cards = ""
        if show_regular:
            if split_board:
                follow_up_questions, primary_questions = _split_board_regular_questions(questions)
                regular_cards = reminder_card(follow_up_questions, extra=False) + reminder_card(primary_questions, extra=False)
            else:
                regular_cards = reminder_card(regular_questions, extra=False)
        return (
            (section_title_block(title) if show_title else "")
            + (reminder_card(extra_questions, extra=True) if show_extra else "")
            + regular_cards
        )

    def board_reminder_column(
        questions: list[ReportReminderQuestion], *, show_extra: bool = True
    ) -> str:
        return (
            '<div data-board-reminder-columns="true">'
            + reminder_column(
                BOARD_REMINDER_SECTION_TITLE, questions, show_extra=show_extra
                , split_board=True
            )
            + '</div>'
        )

    def report_legend_html() -> str:
        def strike_item(label: str, description: str, color: str) -> str:
            return (
                '<td width="33.33%" style="width:33.33%;padding:6px 8px;border:1px solid #cbd5e1;'
                'font-family:Arial,sans-serif;font-size:11px;line-height:1.3;vertical-align:middle;">'
                f'<strong style="color:{color};text-decoration:line-through;'
                f'text-decoration-thickness:2px;">{html.escape(label)}</strong><br>'
                f'<span style="color:#64748b;">{html.escape(description)}</span></td>'
            )

        return (
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'data-report-color-legend="true" style="width:100%;border-collapse:collapse;margin:0 0 12px;">'
            '<tr><th colspan="3" bgcolor="#f1f5f9" style="background-color:#f1f5f9;'
            'border:1px solid #cbd5e1;padding:7px 9px;font-family:Arial,sans-serif;'
            'font-size:12px;text-align:left;color:#0f172a;">COLOR LEGEND</th></tr><tr>'
            + "".join(strike_item(*item) for item in REPORT_STRIKE_LEGEND)
            + '</tr></table>'
        )

    def symbol_legend_html() -> str:
        items = '<b style="font-size:16px;margin:0 5px;color:#0f2a5f;">/</b>'.join(
            f'<span style="white-space:nowrap;"><b style="font-size:{"10px" if symbol in {"KA", "GA", "GENT", "BZ1N1"} else "15px"};font-weight:900;color:#dc2626;">'
            f'{html.escape(symbol)}</b>{f" - {html.escape(description)}" if description else ""}</span>'
            for symbol, description in ONE_H_MARKER_LEGEND
        )
        return (
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'data-report-symbol-legend="true" style="width:100%;border-collapse:collapse;margin:0 0 12px;">'
            '<tr><td bgcolor="#eff6ff" style="background-color:#eff6ff;border:1px solid #93c5fd;'
            'padding:8px 10px;font-family:Arial,sans-serif;font-size:10px;line-height:1.35;'
            'text-align:left;color:#0f2a5f;white-space:nowrap;">'
            f'<strong style="margin-right:9px;">LEGJENDA:</strong>{items}</td></tr></table>'
        )

    body_chunks: list[str] = [report_legend_html(), symbol_legend_html()]
    if pre_sections_html:
        body_chunks.append(f'<div data-report-supplement="true">{pre_sections_html}</div>')

    reminder_groups = (
        (REMINDER_SECTION_TITLE, document.reminders),
        (BOARD_REMINDER_SECTION_TITLE, document.board_reminders),
    )

    body_chunks.append(
        '<div data-day-specific-question-label="true" style="font-family:Arial,sans-serif;'
        'font-size:13px;line-height:1.45;color:#b91c1c;margin:0 0 10px;padding:6px 10px;'
        'background:#fff7f7;border:1px solid #dc2626;border-left:6px solid #dc2626;">'
        + questions_html(_extra_question_parts(document)) + '</div>'
    )

    if document.board_reminders and document.reminders:
        body_chunks.append(
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'data-reminder-columns="true" style="width:100%;border-collapse:collapse;">'
            '<tr>'
            '<td width="50%" valign="top" style="width:50%;padding:0 6px 0 0;vertical-align:top;">'
            f"{reminder_column(REMINDER_SECTION_TITLE, document.reminders, show_extra=False)}"
            '</td>'
            '<td width="50%" valign="top" style="width:50%;padding:0 0 0 6px;vertical-align:top;">'
            f"{board_reminder_column(document.board_reminders, show_extra=False)}"
            '</td>'
            '</tr></table>'
        )
    elif document.board_reminders:
        body_chunks.append(board_reminder_column(document.board_reminders, show_extra=False))
    elif document.reminders:
        body_chunks.append(reminder_column(REMINDER_SECTION_TITLE, document.reminders, show_extra=False))

    body_chunks.append(summary_html(document.ga_task_summary))
    if document.undiscussed_notes:
        body_chunks.append(section_title_block(UNDISCUSSED_NOTES_SECTION_TITLE))
        body_chunks.append(undiscussed_notes_table(document.undiscussed_notes))

    for section_index, section in enumerate(document.sections):
        body_chunks.append('<div data-report-task-section="true">')
        if section_index or document.undiscussed_notes:
            body_chunks.append(section_separator())
        body_chunks.append(section_title_block(section.title))
        if section.title.startswith(BLOCKED_SECTION_TITLE_PREFIX):
            body_chunks.append(bll_task_table(section))
            body_chunks.append('</div>')
            continue
        if not section.employees:
            body_chunks.append(
                "<div style=\"font-family:Arial,sans-serif;color:#64748b;padding:8px 0;\">(Asnjë detyrë)</div>"
            )
        for employee in section.employees:
            body_chunks.append('<div data-report-task-employee="true">')
            body_chunks.append(
                f"<div style=\"font-family:Arial,sans-serif;font-size:15px;font-weight:800;"
                f"color:#0f172a;margin:12px 0 6px;\">{html.escape(employee.name)}</div>"
            )
            for task in employee.tasks:
                background, _, accent = STATUS_COLORS[task.status]
                heading, detail_lines = split_task_display(task.title)
                detail_html = "".join(
                    detail_row(marked_html(item, task.marked_title)) for item in detail_lines
                )
                if task.description:
                    detail_html += detail_row(
                        marked_html(task.description, task.marked_description)
                    )
                detail_html += strike_badge(task)
                body_chunks.append(
                    task_card(
                        background,
                        accent,
                        marker_badge(task.one_h_marker) + marked_html(heading or task.title, task.marked_title),
                        detail_html,
                        task.strike_count,
                    )
                )
            body_chunks.append('</div>')
        body_chunks.append('</div>')

    meta = (
        f"Generated {html.escape(document.generated_at.isoformat())} · {document.task_count} tasks"
    )
    strike_total_html = (
        '<div data-report-strike-total="true" style="font-family:Arial,sans-serif;'
        'font-size:14px;font-weight:700;color:#ffffff;margin-top:8px;">'
        f'{html.escape(strike_count_label(document.strike_total, document, total=True))}</div>'
        if document.strike_total is not None else ""
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<!--[if mso]>
<style type="text/css">
table, td {{ font-family: Arial, sans-serif !important; }}
</style>
<![endif]-->
</head>
<body style="margin:0;padding:0;background:#f8fafc;font-family:Arial,sans-serif;color:#0f172a;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;background:#f8fafc;border-collapse:collapse;">
<tr><td align="center" style="padding:16px 8px;">
<!--[if mso]>
<table role="presentation" width="{content_width}" cellspacing="0" cellpadding="0" border="0"><tr><td>
<![endif]-->
<table role="presentation" width="{content_width}" cellspacing="0" cellpadding="0" border="0" style="width:{content_width}px;max-width:100%;background:#ffffff;border:1px solid #e5e7eb;border-collapse:collapse;">
<tr><td bgcolor="#8799b2" style="background-color:#8799b2;padding:18px 20px;font-family:Arial,sans-serif;">
<div style="font-family:Arial,sans-serif;font-size:22px;line-height:1.25;font-weight:700;color:#ffffff;margin:0 0 4px;">{html.escape(document.subject)}</div>
<div style="font-family:Arial,sans-serif;font-size:13px;line-height:1.35;color:#ffffff;">{meta}</div>
{strike_total_html}
</td></tr>
<tr><td style="padding:14px 16px;font-family:Arial,sans-serif;background:#ffffff;">
<!-- report-strike-filter -->
{''.join(body_chunks)}
</td></tr>
</table>
<!--[if mso]>
</td></tr></table>
<![endif]-->
</td></tr></table>
</body></html>"""


def render_docx(document: ReportDocument) -> bytes:
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor

    def shade(cell: Any, color: str) -> None:
        fill = OxmlElement("w:shd")
        fill.set(qn("w:fill"), color.lstrip("#"))
        cell._tc.get_or_add_tcPr().append(fill)

    def border(cell: Any, color: str, size: str = "12") -> None:
        borders = OxmlElement("w:tcBorders")
        for edge_name in ("top", "left", "bottom", "right"):
            edge = OxmlElement(f"w:{edge_name}")
            edge.set(qn("w:val"), "single")
            edge.set(qn("w:sz"), size)
            edge.set(qn("w:color"), color.lstrip("#"))
            borders.append(edge)
        cell._tc.get_or_add_tcPr().append(borders)

    def add_marked_runs(paragraph: Any, value: str, marked_source: str, *, bold: bool, color: str) -> None:
        ranges = done_ranges(value, marked_source)
        boundaries = sorted({0, len(value), *(point for start, end, _colour in ranges for point in (start, end))})
        for start, end in zip(boundaries, boundaries[1:]):
            run = paragraph.add_run(value[start:end])
            run.bold = bold
            mark = next((item for item in ranges if item[0] <= start and item[1] >= end), None)
            run.font.strike = mark is not None
            run.font.size = Pt(9.5 if bold else 9)
            run.font.color.rgb = RGBColor.from_string((mark[2] if mark else color).lstrip("#"))

    output = io.BytesIO()
    doc = Document()
    doc.sections[0].top_margin = doc.sections[0].bottom_margin = Inches(0.65)
    doc.sections[0].left_margin = doc.sections[0].right_margin = Inches(0.7)
    title_cell = doc.add_table(rows=1, cols=1).cell(0, 0)
    shade(title_cell, "#8799b2")
    title_run = title_cell.paragraphs[0].add_run(document.subject)
    title_run.bold = True
    title_run.font.size = Pt(20)
    title_run.font.color.rgb = RGBColor(255, 255, 255)
    meta = title_cell.add_paragraph(f"Generated {document.generated_at.isoformat()} · {document.task_count} tasks")
    meta.runs[0].font.size = Pt(9)
    meta.runs[0].font.color.rgb = RGBColor(255, 255, 255)
    if document.strike_total is not None:
        total_run = title_cell.add_paragraph(strike_count_label(document.strike_total, document, total=True)).runs[0]
        total_run.bold = True
        total_run.font.size = Pt(10)
        total_run.font.color.rgb = RGBColor(255, 255, 255)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    legend_header = doc.add_table(rows=1, cols=1).cell(0, 0)
    shade(legend_header, "#f1f5f9")
    legend_title = legend_header.paragraphs[0].add_run("COLOR LEGEND")
    legend_title.bold = True
    legend_title.font.size = Pt(10)
    legend_table = doc.add_table(rows=1, cols=3)
    legend_table.style = "Table Grid"
    for cell, (label, description, color) in zip(legend_table.rows[0].cells, REPORT_STRIKE_LEGEND):
        label_run = cell.paragraphs[0].add_run(label)
        label_run.bold = True
        label_run.font.strike = True
        label_run.font.size = Pt(8.5)
        label_run.font.color.rgb = RGBColor.from_string(color.lstrip("#"))
        description_run = cell.add_paragraph().add_run(description)
        description_run.font.size = Pt(7.5)
        description_run.font.color.rgb = RGBColor.from_string("475569")
    symbol_legend_cell = doc.add_table(rows=1, cols=1).cell(0, 0)
    shade(symbol_legend_cell, "#EFF6FF")
    border(symbol_legend_cell, "#93C5FD", size="6")
    symbol_legend_paragraph = symbol_legend_cell.paragraphs[0]
    legend_label_run = symbol_legend_paragraph.add_run("LEGJENDA: ")
    legend_label_run.bold = True
    legend_label_run.font.size = Pt(8)
    legend_label_run.font.color.rgb = RGBColor.from_string("0F2A5F")
    for index, (symbol, description) in enumerate(ONE_H_MARKER_LEGEND):
        if index:
            separator_run = symbol_legend_paragraph.add_run("  /  ")
            separator_run.bold = True
            separator_run.font.size = Pt(11)
            separator_run.font.color.rgb = RGBColor.from_string("0F2A5F")
        symbol_run = symbol_legend_paragraph.add_run(symbol)
        symbol_run.bold = True
        symbol_run.font.size = Pt(8 if symbol in {"KA", "GA", "GENT", "BZ1N1"} else 9)
        symbol_run.font.color.rgb = RGBColor.from_string("DC2626")
        if description:
            description_run = symbol_legend_paragraph.add_run(f" - {description}")
            description_run.font.size = Pt(6.5)
            description_run.font.color.rgb = RGBColor.from_string("0F2A5F")
    reminder_groups = (
        (REMINDER_SECTION_TITLE, document.reminders),
        (BOARD_REMINDER_SECTION_TITLE, document.board_reminders),
    )

    def add_reminder_card(
        indexed_questions: list[tuple[int, ReportReminderQuestion]], *, extra: bool
    ) -> None:
        if not indexed_questions:
            return
        card_cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        shade(card_cell, "#fff7f7" if extra else "#f8fafc")
        border(card_cell, "#dc2626" if extra else "#94a3b8")
        for question_position, (index, question) in enumerate(indexed_questions):
            paragraph = card_cell.paragraphs[0] if question_position == 0 else card_cell.add_paragraph()
            add_marked_runs(
                paragraph,
                f"{_reminder_question_number(index, question, document.report_date)} {question.text}",
                f"{_reminder_question_number(index, question, document.report_date)} {question.text}",
                bold=True,
                color="#b91c1c" if extra else "#050505",
            )
            if question.guidance:
                guidance = card_cell.add_paragraph()
                add_marked_runs(
                    guidance,
                    question.guidance,
                    question.guidance,
                    bold=False,
                    color="#dc2626" if extra else "#64748b",
                )
        doc.add_paragraph().paragraph_format.space_after = Pt(0)

    day_cell = doc.add_table(rows=1, cols=1).cell(0, 0)
    shade(day_cell, "#fff7f7")
    border(day_cell, "#dc2626")
    paragraph = day_cell.paragraphs[0]
    for text, role in _extra_question_parts(document):
        run = paragraph.add_run(text)
        run.bold = role != "question"
        run.font.size = Pt(14 if role == "separator" else 12 if role == "label" else 10)
        run.font.color.rgb = RGBColor.from_string("B91C1C")
    for reminder_title, questions in reminder_groups:
        if not questions:
            continue
        doc.add_paragraph()
        reminder_header = doc.add_table(rows=1, cols=1).cell(0, 0)
        shade(reminder_header, "#eef2ff")
        reminder_run = reminder_header.paragraphs[0].add_run(reminder_title)
        reminder_run.bold = True
        reminder_run.font.size = Pt(13)
        regular_groups = _split_board_regular_questions(questions) if reminder_title == BOARD_REMINDER_SECTION_TITLE else (_partition_reminder_questions(questions)[1],)
        for regular_questions in regular_groups:
            add_reminder_card(regular_questions, extra=False)
    if document.undiscussed_notes:
        doc.add_paragraph()
        notes_header = doc.add_table(rows=1, cols=1).cell(0, 0)
        shade(notes_header, "#eef2ff")
        notes_title = notes_header.paragraphs[0].add_run(UNDISCUSSED_NOTES_SECTION_TITLE)
        notes_title.bold = True
        notes_title.font.size = Pt(13)
        table = doc.add_table(rows=1, cols=4)
        table.style = "Table Grid"
        for cell, label in zip(table.rows[0].cells, ("NR", "NOTE", "KUSH", "DATA")):
            shade(cell, "#e2e8f0")
            run = cell.paragraphs[0].add_run(label)
            run.bold = True
        for index, note in enumerate(document.undiscussed_notes, 1):
            cells = table.add_row().cells
            created = note.created_at.astimezone(report_timezone()).strftime("%d.%m %H:%M") if note.created_at else "-"
            for cell, value in zip(cells, (str(index), note.content, note.author, created)):
                cell.text = value
                for run in cell.paragraphs[0].runs:
                    run.font.size = Pt(9)
    if document.ga_task_summary:
        doc.add_paragraph(GA_SUMMARY_TITLE)
        summary_cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        shade(summary_cell, "#eff6ff")
        run = summary_cell.paragraphs[0].add_run(summary_text(document.ga_task_summary))
        run.font.size = Pt(9)
        run.bold = True
    for section in document.sections:
        doc.add_paragraph()
        section_cell = doc.add_table(rows=1, cols=1).cell(0, 0)
        shade(section_cell, "#eef2ff")
        section_run = section_cell.paragraphs[0].add_run(section.title)
        section_run.bold = True
        section_run.font.size = Pt(13)
        if not section.employees:
            doc.add_paragraph("(Asnjë detyrë)")
        for employee in section.employees:
            employee_paragraph = doc.add_paragraph()
            employee_paragraph.paragraph_format.space_before = Pt(8)
            employee_paragraph.paragraph_format.space_after = Pt(3)
            employee_run = employee_paragraph.add_run(employee.name)
            employee_run.bold = True
            employee_run.font.size = Pt(11)
            for task in employee.tasks:
                background, _, _ = STATUS_COLORS[task.status]
                card_cell = doc.add_table(rows=1, cols=1).cell(0, 0)
                shade(card_cell, background)
                heading, detail_lines = split_task_display(task.title)
                if task.one_h_marker:
                    marker_run = card_cell.paragraphs[0].add_run(f"{task.one_h_marker} ")
                    marker_run.bold = True
                    marker_run.font.size = Pt(12)
                    marker_run.font.color.rgb = RGBColor.from_string("DC2626")
                add_marked_runs(card_cell.paragraphs[0], heading or task.title, task.marked_title, bold=True, color="#050505")
                for item in detail_lines:
                    detail = card_cell.add_paragraph()
                    detail.paragraph_format.space_after = Pt(2)
                    add_marked_runs(detail, item, task.marked_title, bold=False, color="#64748b")
                if task.description:
                    description = card_cell.add_paragraph()
                    add_marked_runs(
                        description, task.description, task.marked_description, bold=False, color="#64748b"
                    )
                if task.strike_count is not None:
                    count_run = card_cell.add_paragraph(strike_count_label(task.strike_count, document)).runs[0]
                    count_run.bold = True
                    count_run.font.size = Pt(8)
                    count_run.font.color.rgb = RGBColor.from_string("1E40AF" if task.strike_count else "475569")
                doc.add_paragraph().paragraph_format.space_after = Pt(0)
    doc.save(output)
    return output.getvalue()


def render_png(document: ReportDocument) -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    width, margin = 1400, 55
    font_path = os.getenv("PRIMEFLOW_REPORT_FONT_PATH", r"C:\Windows\Fonts\seguiemj.ttf")
    fallback = r"C:\Windows\Fonts\arial.ttf"
    try:
        font = ImageFont.truetype(font_path if os.path.exists(font_path) else fallback, 20)
        bold = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 21)
        heading = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 30)
        legend_font = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 12)
    except OSError:
        font = bold = heading = legend_font = ImageFont.load_default()
    import textwrap

    def wrap_description(value: str, width: int) -> list[str]:
        # Keep checklist points separate so the exported strike colour and
        # the visible point count agree, including adjacent open points.
        return [wrapped for line in value.splitlines() for wrapped in (textwrap.wrap(line, width) or [""])]

    def draw_line_with_marks(x: int, line_y: int, line: str, marked_source: str, line_font: Any, color: str) -> None:
        marked_values = [
            (TECHNICAL_TAGS.sub("", match.group(2)).strip(), STRIKE_COLORS.get((match.group(1) or "grey").lower(), STRIKE_COLORS["grey"]))
            for match in DONE_BLOCK.finditer(marked_source)
        ]
        mark_colour = next(
            (strike_colour for selected, strike_colour in marked_values if selected and (line.strip() in selected or selected in line)),
            None,
        )
        draw.text((x, line_y), line, fill=mark_colour or color, font=line_font)
        if mark_colour:
            bounds = draw.textbbox((x, line_y), line, font=line_font)
            strike_y = (bounds[1] + bounds[3]) // 2
            draw.line((bounds[0], strike_y, bounds[2], strike_y), fill=mark_colour, width=2)

    estimated_lines = (
        15
        + (4 + len(textwrap.wrap(summary_text(document.ga_task_summary), 105)) if document.ga_task_summary else 0)
        + len(document.sections) * 3
        + sum(
            2 + len(textwrap.wrap(question.text, 90)) + len(textwrap.wrap(question.guidance or "", 95))
            for questions in (document.board_reminders, document.reminders)
            for question in questions
        )
        + sum(
            3 + sum(
                5 + len(textwrap.wrap(task.title, 85)) + len(wrap_description(task.description, 90))
                for task in employee.tasks
            )
            for section in document.sections
            for employee in section.employees
        )
        + sum(2 + len(textwrap.wrap(note.content, 82)) for note in document.undiscussed_notes)
    )
    height = max(650, 140 + estimated_lines * 30)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    has_total = document.strike_total is not None
    draw.rounded_rectangle((margin, 35, width - margin, 165 if has_total else 135), radius=12, fill="#8799b2")
    draw.text((margin + 24, 55), document.subject, fill="white", font=heading)
    draw.text((margin + 24, 99), f"Generated {document.generated_at.isoformat()} · {document.task_count} tasks", fill="white", font=font)
    if has_total:
        draw.text((margin + 24, 129), strike_count_label(document.strike_total, document, total=True), fill="white", font=bold)
    y = 190 if has_total else 160
    legend_height = 76
    draw.rounded_rectangle(
        (margin, y, width - margin, y + legend_height),
        radius=8,
        fill="#ffffff",
        outline="#cbd5e1",
        width=1,
    )
    draw.rectangle((margin, y, width - margin, y + 30), fill="#f1f5f9", outline="#cbd5e1")
    draw.text((margin + 10, y + 5), "COLOR LEGEND", fill="#0f172a", font=bold)
    legend_column_width = (width - (2 * margin)) // 3
    for column, (label, description, color) in enumerate(REPORT_STRIKE_LEGEND):
        left = margin + (column * legend_column_width)
        top = y + 30
        if column:
            draw.line((left, top, left, top + 46), fill="#cbd5e1", width=1)
        text_left = left + 10
        draw.text((text_left, top + 5), label, fill=color, font=bold)
        bounds = draw.textbbox((text_left, top + 5), label, font=bold)
        strike_y = (bounds[1] + bounds[3]) // 2
        draw.line((bounds[0], strike_y, bounds[2], strike_y), fill=color, width=2)
        draw.text((text_left, top + 26), description, fill="#64748b", font=font)
    y += legend_height + 18
    symbol_legend_height = 46
    draw.rounded_rectangle(
        (margin, y, width - margin, y + symbol_legend_height),
        radius=8,
        fill="#eff6ff",
        outline="#93c5fd",
        width=1,
    )
    legend_x = margin + 12
    legend_y = y + 14
    legend_label = "LEGJENDA: "
    draw.text((legend_x, legend_y), legend_label, fill="#0f2a5f", font=legend_font)
    legend_x += draw.textlength(legend_label, font=legend_font)
    for index, (symbol, description) in enumerate(ONE_H_MARKER_LEGEND):
        if index:
            separator = " / "
            draw.text((legend_x, legend_y), separator, fill="#0f2a5f", font=legend_font)
            legend_x += draw.textlength(separator, font=legend_font)
        draw.text((legend_x, legend_y), symbol, fill="#dc2626", font=legend_font)
        legend_x += draw.textlength(symbol, font=legend_font)
        if description:
            detail = f" - {description}"
            draw.text((legend_x, legend_y), detail, fill="#0f2a5f", font=legend_font)
            legend_x += draw.textlength(detail, font=legend_font)
    y += symbol_legend_height + 18
    reminder_groups = (
        (REMINDER_SECTION_TITLE, document.reminders),
        (BOARD_REMINDER_SECTION_TITLE, document.board_reminders),
    )

    def draw_reminder_card(
        indexed_questions: list[tuple[int, ReportReminderQuestion]], *, extra: bool
    ) -> None:
        nonlocal y
        if not indexed_questions:
            return
        card_lines: list[tuple[str, bool]] = []
        for index, question in indexed_questions:
            card_lines.extend(
                (line, True)
                for line in (textwrap.wrap(f"{_reminder_question_number(index, question, document.report_date)} {question.text}", 95) or [""])
            )
            card_lines.extend(
                (line, False)
                for line in (textwrap.wrap(question.guidance, 105) if question.guidance else [])
            )
        card_height = 25 + 28 * len(card_lines)
        accent = "#dc2626" if extra else "#64748b"
        draw.rounded_rectangle(
            (margin + 5, y, width - margin, y + card_height),
            radius=8,
            fill="#fff7f7" if extra else "#f8fafc",
            outline=accent,
            width=2,
        )
        draw.rectangle((margin + 5, y + 4, margin + 11, y + card_height - 4), fill=accent)
        line_y = y + 12
        for line, is_title in card_lines:
            draw.text(
                (margin + 25, line_y),
                line,
                fill=("#b91c1c" if is_title else "#dc2626")
                if extra
                else ("#050505" if is_title else "#64748b"),
                font=bold if is_title else font,
            )
            line_y += 28
        y += card_height + 12

    from PIL import ImageFont
    try:
        separator_font = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 30)
    except OSError:
        separator_font = bold
    placements, compact_height = layout_question_parts(
        _extra_question_parts(document),
        {"label": bold, "question": font, "separator": separator_font}, width - 2 * margin - 40,
    )
    draw.rectangle((margin, y, width - margin, y + compact_height + 20), fill="#fff7f7", outline="#dc2626")
    for part_x, part_y, text, part_font in placements:
        draw.text((margin + 20 + part_x, y + 8 + part_y), text, fill="#b91c1c", font=part_font)
    y += compact_height + 34
    for reminder_title, questions in reminder_groups:
        if not questions:
            continue
        draw.rectangle((margin, y, width - margin, y + 48), fill="#eef2ff")
        draw.rectangle((margin, y, margin + 7, y + 48), fill="#2563eb")
        draw.text((margin + 18, y + 11), reminder_title, fill="#0f172a", font=bold)
        y += 62
        regular_groups = _split_board_regular_questions(questions) if reminder_title == BOARD_REMINDER_SECTION_TITLE else (_partition_reminder_questions(questions)[1],)
        for regular_questions in regular_groups:
            draw_reminder_card(regular_questions, extra=False)
        y += 14

    def draw_undiscussed_notes() -> None:
        nonlocal y
        if not document.undiscussed_notes:
            return
        draw.rectangle((margin, y, width - margin, y + 48), fill="#eef2ff")
        draw.rectangle((margin, y, margin + 7, y + 48), fill="#2563eb")
        draw.text((margin + 18, y + 11), UNDISCUSSED_NOTES_SECTION_TITLE, fill="#0f172a", font=bold)
        y += 62
        table_left, table_right = margin + 5, width - margin
        columns = (table_left, table_left + 60, table_left + 900, table_left + 1080, table_right)
        header_height = 34
        draw.rectangle((table_left, y, table_right, y + header_height), fill="#e2e8f0", outline="#94a3b8", width=1)
        for x in columns[1:-1]:
            draw.line((x, y, x, y + header_height), fill="#94a3b8", width=1)
        for label, x in zip(("NR", "NOTE", "KUSH", "DATA"), columns[:-1]):
            draw.text((x + 7, y + 7), label, fill="#0f172a", font=bold)
        y += header_height
        for index, note in enumerate(document.undiscussed_notes, 1):
            note_lines = textwrap.wrap(note.content, 68) or [""]
            row_height = max(32, 26 * len(note_lines))
            draw.rectangle((table_left, y, table_right, y + row_height), fill="#ffffff", outline="#cbd5e1", width=1)
            for x in columns[1:-1]:
                draw.line((x, y, x, y + row_height), fill="#cbd5e1", width=1)
            draw.text((columns[0] + 7, y + 6), str(index), fill="#0f172a", font=font)
            for line_index, line in enumerate(note_lines):
                draw.text((columns[1] + 7, y + 6 + 25 * line_index), line, fill="#0f172a", font=font)
            draw.text((columns[2] + 7, y + 6), note.author, fill="#0f172a", font=font)
            created = note.created_at.astimezone(report_timezone()).strftime("%d.%m %H:%M") if note.created_at else "-"
            draw.text((columns[3] + 7, y + 6), created, fill="#0f172a", font=font)
            y += row_height
        y += 14

    draw_undiscussed_notes()
    if document.ga_task_summary:
        draw.text((margin + 8, y), GA_SUMMARY_TITLE, fill="#0f172a", font=bold)
        y += 36
        lines = textwrap.wrap(summary_text(document.ga_task_summary), 105)
        row_height = 20 + len(lines) * 28
        draw.rectangle((margin, y, width - margin, y + row_height), fill="#eff6ff", outline="#cbd5e1")
        for index, line in enumerate(lines):
            draw.text((margin + 10, y + 10 + index * 28), line, fill="#0f172a", font=font)
        y += row_height + 18
    for section in document.sections:
        draw.rectangle((margin, y, width - margin, y + 48), fill="#eef2ff")
        draw.rectangle((margin, y, margin + 7, y + 48), fill="#2563eb")
        draw.text((margin + 18, y + 11), section.title, fill="#0f172a", font=bold)
        y += 62
        if not section.employees:
            draw.text((margin + 18, y), "(Asnjë detyrë)", fill="#64748b", font=font)
            y += 40
        for employee in section.employees:
            draw.text((margin + 5, y), employee.name, fill="#0f172a", font=bold)
            y += 38
            for task in employee.tasks:
                background, _, accent = STATUS_COLORS[task.status]
                task_heading, detail_items = split_task_display(task.title)
                title_lines = textwrap.wrap(task_heading or task.title, 95) or [""]
                detail_lines = [
                    line for item in detail_items
                    for line in (textwrap.wrap(item, 105, subsequent_indent="   ") or [""])
                ]
                description_lines = wrap_description(task.description, 105)
                count_lines = [strike_count_label(task.strike_count, document)] if task.strike_count is not None else []
                card_height = 25 + 28 * (len(title_lines) + len(detail_lines) + len(description_lines) + len(count_lines))
                draw.rounded_rectangle((margin + 5, y, width - margin, y + card_height), radius=8, fill=background, outline=accent, width=2)
                draw.rectangle((margin + 5, y + 4, margin + 11, y + card_height - 4), fill=accent)
                line_y = y + 12
                for title_index, line in enumerate(title_lines):
                    title_x = margin + 25
                    if title_index == 0 and task.one_h_marker:
                        draw.text((title_x, line_y), task.one_h_marker, fill="#dc2626", font=bold)
                        marker_bounds = draw.textbbox((title_x, line_y), task.one_h_marker, font=bold)
                        title_x = marker_bounds[2] + 10
                    draw_line_with_marks(title_x, line_y, line, task.marked_title, bold, "#050505")
                    line_y += 28
                for line in detail_lines:
                    draw_line_with_marks(margin + 25, line_y, line, task.marked_title, font, "#64748b")
                    line_y += 28
                for line in description_lines:
                    draw_line_with_marks(margin + 25, line_y, line, task.marked_description, font, "#64748b")
                    line_y += 28
                for line in count_lines:
                    draw.text((margin + 25, line_y), line, fill="#1e40af" if task.strike_count else "#475569", font=bold)
                    line_y += 28
                y += card_height + 12
        y += 14
    image = image.crop((0, 0, width, y + margin))
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def build_report(data: dict[str, Any], report_day: date, slot: str) -> str:
    return render_plain_text(build_report_document(data, report_day, slot))


async def retry(operation: Callable[[], Awaitable[Any]], *, delays: tuple[float, ...] = (0, 2, 5)) -> Any:
    last: Exception | None = None
    for attempt, delay in enumerate(delays, 1):
        if delay:
            await asyncio.sleep(delay)
        try:
            return await operation()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            last = exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in TRANSIENT_CODES:
                raise
            last = exc
        logger.warning("transient_operation_failure attempt=%s error=%s", attempt, type(last).__name__)
    assert last is not None
    raise last


# Access tokens from PrimeFlowClient logins, shared by every report build.
_LOGIN_TOKENS: dict[tuple[str, str | None], str] = {}


@dataclass
class PrimeFlowClient:
    base_url: str
    email: str | None
    password: str | None
    access_token: str | None = None

    def _login_cache_key(self) -> tuple[str, str | None]:
        return (self.base_url, self.email)

    async def _token(self, client: httpx.AsyncClient) -> str:
        if self.access_token:
            return self.access_token
        # Logging in hashes the password on the server, so every report used
        # to pay for it. Reuse the last token; a 401 below logs in again.
        cached = _LOGIN_TOKENS.get(self._login_cache_key())
        if cached:
            self.access_token = cached
            return cached
        response = await client.post("/api/auth/login", json={"email": self.email, "password": self.password})
        response.raise_for_status()
        self.access_token = response.json().get("access_token") or response.json().get("accessToken")
        if not self.access_token:
            raise ValueError("PrimeFlow login response contained no access token")
        _LOGIN_TOKENS[self._login_cache_key()] = self.access_token
        return self.access_token

    async def common_view(self, day: date) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=30) as client:
            async def retrieve(week_day: date) -> dict[str, Any]:
                params = {
                    "week_start": week_day.isoformat(),
                    "include_all_departments": "true",
                    "freeze_one_h_slots": "false",
                    "max_items_per_bucket": 5000,
                }
                token = await self._token(client)
                response = await client.get(
                    "/api/common-view",
                    params=params,
                    headers={"Authorization": f"Bearer {token}", "Cache-Control": "no-cache"},
                )
                if response.status_code == 401:
                    self.access_token = None
                    _LOGIN_TOKENS.pop(self._login_cache_key(), None)
                    token = await self._token(client)
                    response = await client.get(
                        "/api/common-view",
                        params=params,
                        headers={"Authorization": f"Bearer {token}", "Cache-Control": "no-cache"},
                    )
                response.raise_for_status()
                payload = response.json()
                if any((payload.get("guardrails", {}).get("truncated") or {}).values()):
                    raise ValueError("Common View contains truncated buckets")
                return payload
            if day.weekday() != 0:
                return await retry(lambda: retrieve(day))
            # Monday also needs Friday; log in once, then load both weeks at
            # the same time instead of one after the other.
            await self._token(client)
            current, previous = await asyncio.gather(
                retry(lambda: retrieve(day)),
                retry(lambda: retrieve(previous_working_day(day))),
            )
            for bucket, values in (previous.get("items") or {}).items():
                current.setdefault("items", {}).setdefault(bucket, []).extend(values)
            current["generated_at"] = max(current["generated_at"], previous["generated_at"])
            return current


class GmailService:
    def __init__(self, *, sender: str | None = None, password: str | None = None) -> None:
        configured_sender = (
            sender or os.getenv("EMAIL_USER") or settings.EMAIL_USER or REPORT_SENDER_EMAIL
        ).strip()
        if configured_sender.casefold() != REPORT_SENDER_EMAIL.casefold():
            raise ValueError(
                f"PrimeFlow reports must be sent from {REPORT_SENDER_EMAIL}; "
                f"configured sender is {configured_sender}"
            )
        password = password or os.getenv("EMAIL_PASSWORD") or settings.EMAIL_PASSWORD
        if not password:
            raise ValueError("Missing email configuration: EMAIL_PASSWORD")
        self.sender = REPORT_SENDER_EMAIL
        self.password = password.replace(" ", "")
        self.host = (os.getenv("EMAIL_HOST") or settings.EMAIL_HOST).strip()
        self.port = int(os.getenv("EMAIL_PORT") or settings.EMAIL_PORT)

    async def find_exact(self, subject: str, recipients: list[str] | None = None) -> dict[str, Any] | None:
        # SMTP has no mailbox-search operation. Database uniqueness and row locks
        # in the delivery service provide the idempotency guard for SMTP sends.
        return None

    async def send_verified(
        self, subject: str, recipients: list[str] | dict[str, list[str]], body: str,
        html_body: str | None = None,
        attachments: list[tuple[str, bytes, str]] | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        recipient_map = recipients if isinstance(recipients, dict) else {"to": recipients, "cc": [], "bcc": []}
        all_recipients = sum(recipient_map.values(), [])
        if not recipient_map["to"]:
            raise ValueError("At least one To recipient is required")
        message = EmailMessage()
        message_id = message_id or make_msgid(domain=self.sender.rsplit("@", 1)[-1])
        if not message_id.startswith("<"):
            message_id = f"<{message_id}>"
        message["From"] = self.sender
        message["To"] = ", ".join(recipient_map["to"])
        message["Subject"] = subject
        message["Message-ID"] = message_id
        message["X-Entity-Ref-ID"] = message_id.strip("<>")
        if recipient_map["cc"]:
            message["Cc"] = ", ".join(recipient_map["cc"])
        if recipient_map["bcc"]:
            message["Bcc"] = ", ".join(recipient_map["bcc"])
        message.set_content(body, charset="utf-8")
        if html_body:
            # multipart/alternative with HTML last — Outlook/Gmail prefer the last part.
            message.add_alternative(html_body, subtype="html", charset="utf-8")
        for filename, content, mime_type in attachments or []:
            maintype, subtype = mime_type.split("/", 1)
            message.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

        def send_smtp() -> None:
            context = ssl.create_default_context()
            with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                smtp.login(self.sender, self.password)
                smtp.send_message(message, from_addr=self.sender, to_addrs=all_recipients)

        await asyncio.to_thread(send_smtp)
        return {
            "id": message_id.strip("<>"),
            "threadId": None,
            "provider_message_id": None,
            "transport": "smtp",
        }


def predecessor(day: date, slot: str) -> tuple[date, str]:
    index = SLOTS.index(slot)
    return (previous_working_day(day), "16:00") if index == 0 else (day, SLOTS[index - 1])
