from __future__ import annotations

from app.services.task_pause import task_title_with_pause

from app.services.report_attendance import LEAVE_TABLE_COLUMNS, filter_task_context, filter_report_sections

import logging
import re
from collections.abc import Sequence, Set
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.common_entry import CommonEntry
from app.models.department import Department
from app.services.task_plan_feedback import load_task_plan_feedback
from app.models.enums import CommonCategory
from app.models.meeting import Meeting
from app.models.task import Task
from app.models.task_symbol_comment_event import TaskSymbolCommentEvent
from app.models.user import User
from app.services.report_ga_task_bz import ga_task_bz_labels
from app.services.after_break_report import (
    BLUE_NOTE_COLUMNS,
    NOTE_REFERENCES,
    _ascii_table,
    _belongs_to_day,
    _display_title,
    _personal_section,
    _task_covers_day,
    load_blue_notes,
    order_blue_notes_table,
)
from app.services.common_leave import parse_common_view_annual_leave
from app.services.microsoft_calendar_sync import is_common_view_visible_meeting
from app.services.daily_report_logic import daily_report_tyo_label, planned_range_for_daily_report
from app.services.discord_ga_replies import GA_REPLIES_SECTION_TITLE, GA_REPLIES_WINDOW_VERSION
from app.services.discord_ga_replies import GA_REPLIES_CAPTURE_VERSION, GA_REPLIES_CAPTURE_VERSION_KEY
from app.services.discord_ga_replies import _report_window, m1_report_cutoff
from app.services.discord_ga_reactions import (
    GA_REACTIONS_SECTION_KEY,
    GA_REACTIONS_SECTION_TITLE,
    REACTIONS_UNAVAILABLE,
    reaction_summary_for_day,
)
from app.services.task_marker import active_one_h_marker, one_h_marker_label
from app.services.meetings_report import (
    PERSONAL_GA,
    TECHNICAL_TAG,
    _all_participant_user_ids,
    _ascii_table_block,
    _assignee_names,
    apply_weekly_planner_task_order,
    _bz_alignment_lines,
    _clean_task_title,
    _effective_task_assignee_ids,
    _initials,
    _is_open,
    _is_report_wfc_task,
    _ka_genti_confirmer,
    _ka_genti_owner,
    _leave_lines,
    _local_date,
    _m3_am_pm_label,
    _m3_department_code_label,
    _m3_department_label,
    _m3_status_table,
    _m3_task_type_label,
    _meeting_lines,
    _meeting_occurs_on_date,
    _normalize_section,
    _normalize_report_status,
    _section_report_table_rows,
    _strip_status_markers,
    refresh_saved_leave_table,
    _task_lines,
    _task_metadata_by_title,
    _task_owners,
    _tomorrow_meeting_table,
    _tomorrow_task_table,
    weekly_planner_user_sort_keys,
    common_view_task_sort_key,
    send_section_report,
)
from app.services.report_section_merge import preserve_keyed_line
from app.services.m1_gmail_pilot import read_m1_gmail_messages
from app.services.primeflow_report import report_timezone

REPORT_TYPE = "morning_report"
REPORT_LABEL = "Hapja e dites M1"
GMAIL_PILOT_CAPTION = "EMAIL-E NGA GMAIL"
logger = logging.getLogger(__name__)
GA_TASKS_TITLE = "GA TASKS"
HV_TASKS_TITLE = "HV TASKS"
DV_TASKS_TITLE = "DV TASKS"
GA_HV_DV_TASKS_TITLE = "GA/HV/DV TASKS"
PHYSICAL_GA_TITLE = "FIZIKISHT ME GA?"
KA_GENT_QUESTIONS_TITLE = "A KA PYTJE/SQARIME ME KA/GENTIN"
GA_PF_COMMENTS_TITLE = "(GA) A KA KOMENTE NE PF?"
NEW_EMAILS_SECTION_TITLE = "EMAILS TE REJA?"
MARKER_TASK_SECTIONS = {
    PHYSICAL_GA_TITLE: ({"F"}, "DETYRAT ME F"),
    KA_GENT_QUESTIONS_TITLE: ({"KA", "GENT"}, "DETYRAT ME KA OSE GENT"),
}
SECTION_TITLES = [
    GA_REPLIES_SECTION_TITLE,
    # Auto-filled from PrimeFlow
    "(GA) DET NGA EMAILS TE REJA",
    "(GA) VONESA/MUNGESA. A NDRYSHON PLANI PER SOT?",
    "(GA) NOTES TE REJA ( NOT DISSCUSED)?",
    "PV/FESTA EXT/TAK EXT/ TAK INT/ BZ ME GA/BLLOK:",
    "(GA/KA) KUSH KA DET PERSONALISHT?",
    GA_HV_DV_TASKS_TITLE,
    "DET PERSONALISHT ME KA/GENTIN?",
    "WFC ME KA/GENTIN?",
    *MARKER_TASK_SECTIONS,
    GA_REACTIONS_SECTION_KEY,
    GA_PF_COMMENTS_TITLE,
]
DISPLAY_SECTION_TITLES = [
    SECTION_TITLES[2],
    GA_HV_DV_TASKS_TITLE,
    PHYSICAL_GA_TITLE,
    SECTION_TITLES[1],
    SECTION_TITLES[0],
    GA_REACTIONS_SECTION_KEY,
    GA_PF_COMMENTS_TITLE,
    *SECTION_TITLES[3:6],
    KA_GENT_QUESTIONS_TITLE,
    *SECTION_TITLES[7:9],
]
SECTION_DISPLAY_TITLES = {
    GA_REACTIONS_SECTION_KEY: GA_REACTIONS_SECTION_TITLE,
    SECTION_TITLES[1]: NEW_EMAILS_SECTION_TITLE,
    SECTION_TITLES[2]: "(GA) VONESA/MUNGESA/PV. A NDRYSHON PLANI PER SOT?",
    SECTION_TITLES[4]: "FESTA EXT/TAK EXT/TAK INT/BZ ME GA/BLLOK:",
}
MANUAL_SECTION_TITLES: set[str] = set()
SYMBOL_COMMENT_COLUMNS = [
    ("NR", 2), ("KUSH", 12), ("DEP", 5), ("AM/PM", 5), ("LLOJI", 7),
    ("STATUS", 18), ("SIMBOLI", 12), ("TITULLI", 52), ("KOMENT", 45), ("DATA / ORA", 16),
]
GA_HV_DV_TASK_COLUMNS = [
    ("NR", 2), ("KUSH", 12), ("DEP", 5), ("AM/PM", 5), ("LLOJI", 7),
    ("STATUS", 18), ("T/Y/O", 5), ("TITULLI", 52), ("VAZHDON?", 8), ("KOMENT", 45),
]
GA_TASK_COLUMNS = [*GA_HV_DV_TASK_COLUMNS[:8], ("BZ ME", 14), *GA_HV_DV_TASK_COLUMNS[8:]]
TASK_FEEDBACK_OVERRIDES = "task_feedback_overrides"
TASK_FEEDBACK_ROWS = "task_feedback_rows"
CONTINUATION_ICONS = {"PO": "✓", "JO": "X"}
RETIRED_EMAIL_TASK_CAPTION = re.compile(r"EM\s*:\s*(?:INFO PX|IT|HF|PX EU)\s*:\s*\d+\s*:?", re.I)
RETIRED_EMAIL_TASK_PLACEHOLDER = "Email-source tasks load automatically when M1 is generated."
LEGACY_NOTES_TITLE = (
    "(GA) NOTES TE REJA?- SELEKTO NOTES TE KALTRA DHE DISKUTO (ADM & DSG) SECILEN A KRIJOHET "
    "DETYRE? EM: INFO PX (KO SPAM), EM:INFO HF, (KO SPAM) EM: PRIMEX EU (GMAIL-KO SPAM), "
    "VENDOS DET: STATUS (1H: EM(08:00),08:00,DL,AM,AM&PM,PM/P/R1)"
)
SECTION_TITLE_ALIASES = {
    GA_REACTIONS_SECTION_TITLE: GA_REACTIONS_SECTION_KEY,
    NEW_EMAILS_SECTION_TITLE: SECTION_TITLES[1],
    "(GA/KA/GENTI) KUSH KA DET PERSONALISHT?": SECTION_TITLES[7],
    "TASKS PERSONALISHT ME KA/GENTIN?": SECTION_TITLES[7],
    "WFC TASKS (KA/GENTI)": SECTION_TITLES[8],
    "(GA) NOTES TE REJA?": SECTION_TITLES[3],
    "(GA) NOTES TE REJA?- SELEKTO NOTES TE KALTRA DHE DISKUTO (ADM & DSG) SECILEN A KRIJOHET DETYRE?": SECTION_TITLES[3],
    LEGACY_NOTES_TITLE: SECTION_TITLES[3],
}


def subject_for(day: date) -> str:
    return f"M1 - PrimeFlow Hapja e dites - {day:%d.%m.%Y}"


def is_generated_subject(subject: str | None, day: date) -> bool:
    """Recognize the old and current automatically generated M1 subjects."""
    return (subject or "").strip() in {
        subject_for(day),
        f"PrimeFlow Hapja e dites M1 - {day:%d.%m.%Y}",
    }


def _default_body(title: str) -> str:
    if title == GA_PF_COMMENTS_TITLE:
        return _symbol_comment_table([])
    if title == SECTION_TITLES[0]:
        return "Përgjigjet GA nga Discord përditësohen kur gjenerohet raporti."
    if title == GA_REACTIONS_SECTION_KEY:
        return REACTIONS_UNAVAILABLE
    if title == SECTION_TITLES[1]:
        return ""
    if title == SECTION_TITLES[2]:
        return "\n".join(["VONESA: 0", "", "MUNGESA: 0", "", "NDRYSHON PLANI: (Ploteso manualisht)"])
    if title == SECTION_TITLES[3]:
        return "NOTES: 0"
    if title == SECTION_TITLES[4]:
        return "\n\n".join(
            [
                "FESTA EXTERNE: 0",
                "TAKIMET EXTERNE: 0",
                "TAKIMET INTERNE: 0",
                "BZ ME GA: 0",
                "BLLOK: 0",
            ]
        )
    if title == GA_HV_DV_TASKS_TITLE:
        return "\n\n".join(f"{task_title}: 0" for task_title in (GA_TASKS_TITLE, HV_TASKS_TITLE, DV_TASKS_TITLE))
    if title == SECTION_TITLES[7]:
        return "PERSONAL KA: 0\n\nPERSONAL GENTI: 0"
    if title == SECTION_TITLES[8]:
        return "WFC KA: 0\n\nWFC GENTI: 0"
    if title in MARKER_TASK_SECTIONS:
        return _marker_task_table(MARKER_TASK_SECTIONS[title][1], [], {}, {}, {})
    return "\n\n".join(["TODO: 0", "IN PROGRESS: 0", "WFE: 0", "WAITING CONFIRMATION: 0", "DONE: 0"])


def _is_manual_email_line(line: str) -> bool:
    upper = line.strip().upper()
    return upper.startswith("EMAIL ") or upper.startswith("STATUSI I DETYRAVE")


def _without_retired_task_status_prompt(body: str) -> str:
    """Remove the retired task-status prompt from saved M1 email sections."""
    return "\n".join(
        line for line in (body or "").splitlines()
        if not line.strip().upper().startswith("STATUSI I DETYRAVE")
    ).strip()


def _without_retired_email_task_tables(body: str) -> str:
    """Remove generated task tables from old M1 drafts, preserving mailbox content."""
    lines = _without_retired_task_status_prompt(body).splitlines()
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if line == RETIRED_EMAIL_TASK_PLACEHOLDER:
            continue
        if RETIRED_EMAIL_TASK_CAPTION.fullmatch(line):
            start = next((i for i in range(index, len(lines)) if lines[i].strip()), len(lines))
            block = _ascii_table_block(lines, start)
            if block:
                index = block[1]
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _split_notes_and_emails(body: str) -> tuple[str, str]:
    note_lines: list[str] = []
    email_lines: list[str] = []
    for line in (body or "").splitlines():
        if _is_manual_email_line(line):
            email_lines.append(line.strip())
        else:
            note_lines.append(line)
    notes_body = "\n".join(note_lines).strip() or "NOTES: 0"
    emails_body = _without_retired_task_status_prompt("\n\n".join(line for line in email_lines if line))
    return notes_body, emails_body


def _separate_keyed_prompt_lines(body: str) -> str:
    """Keep one blank line between uppercase KEY: value prompts for readability."""
    parts = [line.strip() for line in (body or "").splitlines() if line.strip()]
    return "\n\n".join(parts) if parts else body


def _compact_section_title(title: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", (title or "").upper())


def _canonical_section_title(raw_title: str) -> str | None:
    title = SECTION_TITLE_ALIASES.get(raw_title, raw_title).strip()
    if title in SECTION_TITLES:
        return title

    compact = _compact_section_title(title)
    marker_title = _marker_section_title(title)
    if marker_title:
        return marker_title
    for known in SECTION_TITLES:
        if _compact_section_title(known) == compact:
            return known

    # Older drafts used near-identical wording for the emails / notes prompts.
    if "VENDOSDETSTATUS" in compact or compact.startswith("GAEMINFO"):
        return SECTION_TITLES[1]
    if "NOTESTEREJA" in compact and "VENDOSDETSTATUS" not in compact:
        return SECTION_TITLES[3]
    if "AKAREPLYNGAGA" in compact:
        return SECTION_TITLES[0]
    if "VONESA" in compact and "MUNGESA" in compact:
        return SECTION_TITLES[2]
    if "BZMEGA" in compact and "BLLOK" in compact:
        return SECTION_TITLES[4]
    if compact in {
        _compact_section_title(GA_HV_DV_TASKS_TITLE),
        _compact_section_title(GA_TASKS_TITLE),
        _compact_section_title(HV_TASKS_TITLE),
        _compact_section_title(DV_TASKS_TITLE),
    }:
        return GA_HV_DV_TASKS_TITLE
    if "KUSHKADETPERSONALISHT" in compact:
        return SECTION_TITLES[5]
    if "WFCTASKS" in compact:
        return SECTION_TITLES[8]
    return None


def _marker_section_title(title: str | None) -> str | None:
    compact = re.sub(r"^(?:MANUAL)?\d*", "", _compact_section_title(title or ""))
    if compact == "AKAPYETJESQARIMEMEKAGENTIN":
        return KA_GENT_QUESTIONS_TITLE
    return next((title for title in MARKER_TASK_SECTIONS if _compact_section_title(title) == compact), None)


def is_removed_morning_manual_question(title: str | None, section_key: str | None = None) -> bool:
    """Skip retired M1 questions and the old manual copies of automated tables."""
    key = (section_key or "").strip()
    if key and not key.startswith("manual:"):
        return False
    if key and _canonical_section_title(title or "") == GA_PF_COMMENTS_TITLE:
        return True
    for value in (title, key):
        compact = _compact_section_title((value or "").upper().replace("Ë", "E"))
        compact = re.sub(r"^(?:MANUAL)?\d*", "", compact)
        if compact in {"PIKATEDITESSOT", "EPAESHTELESHUARMIRAPARATAK12MIN"} or _marker_section_title(value):
            return True
    return False


def normalize_morning_report_sections(sections: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    by_title: dict[str, dict[str, str]] = {}
    extras: list[dict[str, str]] = []
    for section in sections or []:
        raw_title = str(section.get("title") or "").strip()
        section_key = str(section.get("section_key") or "").strip()
        if is_removed_morning_manual_question(raw_title, section_key):
            continue
        title = _canonical_section_title(section_key or raw_title)
        body = str(section.get("body") or "")
        if raw_title == LEGACY_NOTES_TITLE or (
            title == SECTION_TITLES[3] and any(_is_manual_email_line(line) for line in body.splitlines())
        ):
            notes_body, emails_body = _split_notes_and_emails(body)
            if SECTION_TITLES[3] not in by_title:
                by_title[SECTION_TITLES[3]] = {
                    "section_key": SECTION_TITLES[3], "title": SECTION_TITLES[3], "body": order_blue_notes_table(notes_body),
                }
            if SECTION_TITLES[1] not in by_title:
                by_title[SECTION_TITLES[1]] = {
                    "section_key": SECTION_TITLES[1], "title": NEW_EMAILS_SECTION_TITLE, "body": emails_body,
                }
            continue
        if title is None:
            if raw_title:
                extras.append({
                    "section_key": section_key or f"manual:{_compact_section_title(raw_title)}",
                    "title": raw_title,
                    "body": body,
                })
            continue
        if title == SECTION_TITLES[1]:
            body = _separate_keyed_prompt_lines(_without_retired_email_task_tables(body))
        if title == SECTION_TITLES[3]:
            body = order_blue_notes_table(body)
        if title == GA_PF_COMMENTS_TITLE and body.strip() in {"", "(Ploteso manualisht)"}:
            body = _default_body(title)
        if title not in by_title:
            visible_title = SECTION_DISPLAY_TITLES.get(title, title)
            if (section_key and raw_title != title
                    and title not in {GA_HV_DV_TASKS_TITLE, GA_REACTIONS_SECTION_KEY, GA_PF_COMMENTS_TITLE}
                    and title not in MARKER_TASK_SECTIONS):
                visible_title = raw_title
            by_title[title] = {
                "section_key": title,
                "title": visible_title,
                "body": body,
            }

    for title in DISPLAY_SECTION_TITLES:
        by_title.setdefault(title, {
            "section_key": title, "title": SECTION_DISPLAY_TITLES.get(title, title), "body": _default_body(title),
        })
    attendance = by_title[SECTION_TITLES[2]]
    context = by_title[SECTION_TITLES[4]]
    pv, context["body"] = _split_pv_table(context["body"])
    attendance_pv, attendance_body = _split_pv_table(attendance["body"])
    if not attendance_pv or (pv and attendance_pv == "PV: 0"):
        lines = attendance_body.splitlines()
        plan = next((index for index, line in enumerate(lines)
                     if line.strip().upper().startswith("NDRYSHON PLANI")), len(lines))
        attendance["body"] = "\n\n".join(part for part in (
            "\n".join(lines[:plan]).strip(), pv or "PV: 0", "\n".join(lines[plan:]).strip(),
        ) if part)
    known = [by_title[title] for title in DISPLAY_SECTION_TITLES]
    from app.services.meeting_point_manual_sync import order_custom_manual_sections

    return order_custom_manual_sections("morning", extras + known)


def _split_pv_table(body: str) -> tuple[str, str]:
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if not re.fullmatch(r"PV(?:\s*:\s*\d*)?", line.strip(), re.I):
            continue
        start = next((i for i in range(index + 1, len(lines)) if lines[i].strip()), len(lines))
        block = _ascii_table_block(lines, start)
        end = index + 1
        if block:
            header, _ = _section_report_table_rows(block[0])
            if tuple(header) == LEAVE_TABLE_COLUMNS:
                end = block[1]
        return "\n".join(lines[index:end]).strip(), "\n".join([*lines[:index], *lines[end:]]).strip()
    return "", body


def preserve_morning_plan_note(
    sections: list[dict[str, str]], existing: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    title = SECTION_TITLES[2]
    saved = next((section.get("body") for section in existing or []
                  if _canonical_section_title(section.get("section_key") or section.get("title") or "") == title), None)
    return [
        {**section, "body": preserve_keyed_line(section["body"], saved, "NDRYSHON PLANI")}
        if _canonical_section_title(section.get("section_key") or section["title"]) == title else section
        for section in sections
    ]


def _entry_day(entry: CommonEntry) -> date | None:
    if entry.entry_date:
        return entry.entry_date
    description = entry.description or ""
    match = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", description, re.I)
    if match:
        try:
            return date.fromisoformat(match.group(1))
        except ValueError:
            pass
    return _local_date(entry.created_at)


def _entry_person(entry: CommonEntry, names: dict[Any, str]) -> str:
    user_id = entry.assigned_to_user_id or entry.created_by_user_id
    return _initials(names.get(user_id) or entry.title)


def _clean_entry_note(value: str | None) -> str:
    note = TECHNICAL_TAG.sub("", value or "")
    note = re.sub(r"Date:\s*\d{4}-\d{2}-\d{2}", "", note, flags=re.I)
    note = re.sub(r"Start:\s*\d{1,2}:\d{2}", "", note, flags=re.I)
    note = re.sub(r"Until:\s*\d{1,2}:\d{2}", "", note, flags=re.I)
    note = re.sub(r"From:\s*\d{1,2}:\d{2}\s*-\s*To:\s*\d{1,2}:\d{2}", "", note, flags=re.I)
    return re.sub(r"\s+", " ", note).strip() or "-"


def _attendance_section(entries: list[CommonEntry], names: dict[Any, str], report_day: date) -> str:
    delay_rows: list[list[str]] = []
    absence_rows: list[list[str]] = []
    for entry in entries:
        if _entry_day(entry) != report_day:
            continue
        description = entry.description or ""
        if entry.category == CommonCategory.delays:
            start_match = re.search(r"Start:\s*(\d{1,2}:\d{2})", description, re.I)
            until_match = re.search(r"Until:\s*(\d{1,2}:\d{2})", description, re.I)
            start = start_match.group(1) if start_match else "08:00"
            until = until_match.group(1) if until_match else "09:00"
            delay_rows.append(
                [str(len(delay_rows) + 1), _entry_person(entry, names), f"{start}-{until}", _clean_entry_note(description)]
            )
        elif entry.category == CommonCategory.absences:
            times = re.search(
                r"From:\s*(\d{1,2}:\d{2})\s*-\s*To:\s*(\d{1,2}:\d{2})", description, re.I
            )
            when = f"{times.group(1)}-{times.group(2)}" if times else "08:00-23:00"
            absence_rows.append(
                [str(len(absence_rows) + 1), _entry_person(entry, names), when, _clean_entry_note(description)]
            )

    return _normalize_section(
        [
            *_ascii_table("VONESA", [("NR", 2), ("KUSH", 10), ("KOHA", 11), ("NOTE", 48)], delay_rows),
            "",
            *_ascii_table("MUNGESA", [("NR", 2), ("KUSH", 10), ("KOHA", 11), ("NOTE", 48)], absence_rows),
            "",
            "NDRYSHON PLANI: (Ploteso manualisht)",
        ]
    )


def _notes_section(note_rows: list[list[str]]) -> str:
    return _normalize_section(
        _ascii_table(
            "NOTES",
            BLUE_NOTE_COLUMNS,
            note_rows,
        )
    )


def _gmail_report_cell(value: str) -> str:
    # Pipes and line breaks are structural characters in report tables.
    return " ".join(value.replace("|", "｜").split()) or "-"


def _replace_gmail_table(body: str, gmail_body: str) -> str:
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith(f"{GMAIL_PILOT_CAPTION}:"):
            table_start = index + 1
            while table_start < len(lines) and not lines[table_start].strip():
                table_start += 1
            table = _ascii_table_block(lines, table_start)
            del lines[index:table[1] if table else index + 1]
            break
    return "\n\n".join(part for part in ("\n".join(lines).strip(), gmail_body) if part)


async def refresh_m1_gmail_section(
    sections: list[dict[str, str]], report_day: date, *, sent: bool = False,
    generated_snapshot: dict | None = None, sent_at: datetime | None = None,
) -> list[dict[str, str]]:
    tz = report_timezone()
    if sent and report_day != datetime.now(tz).date():
        return sections
    window = _report_window(report_day, "M1", m1_report_cutoff(generated_snapshot, sent_at if sent else None))
    try:
        messages = await read_m1_gmail_messages(report_day, tz, window=window)
    except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("m1_gmail_pilot_unavailable error_type=%s", type(exc).__name__)
        gmail_body = f"{GMAIL_PILOT_CAPTION}: Leximi nuk u krye"
    else:
        if messages is None:
            return sections
        rows = [
            [
                str(n),
                _gmail_report_cell(message.subject),
                _gmail_report_cell(message.sender),
                _gmail_report_cell(message.body),
                message.received_at.astimezone(tz).strftime("%H:%M"),
            ]
            for n, message in enumerate(messages, 1)
        ]
        gmail_body = _normalize_section(_ascii_table(
            GMAIL_PILOT_CAPTION,
            [("NR", 3), ("TITULLI", 24), ("DERGUESI", 24), ("PËRMBAJTJA", 72), ("ORA", 5)],
            rows,
        ))
        if rows:
            gmail_body = gmail_body.replace(f"{GMAIL_PILOT_CAPTION}:",
                                           f"{GMAIL_PILOT_CAPTION}: {len(rows)}", 1)
    return [
        {**section, "body": _replace_gmail_table(section["body"], gmail_body)}
        if section.get("section_key") == SECTION_TITLES[1] else section
        for section in sections
    ]


def _ga_hv_dv_task_rows(
    tasks: list[Task],
    names: dict[Any, str],
    assignee_ids_by_task: dict[Any, set[Any]],
    report_day: date,
    department_codes: dict[Any, str] | None = None,
    target_initials: str | None = None,
    *,
    selected_tasks: list[Task] | None = None,
    feedback_task_ids: Set[Any] = frozenset(),
) -> list[list[str]]:
    """Today's open tasks plus open overdue tasks for the GA/HV/DV tables.

    GA and DV are selected by assignee initials.  HV follows the M2 meaning:
    every task owned by the Finance department, regardless of assignee.
    """
    targets = {target_initials} if target_initials else {"GA", "HV", "DV"}

    def belongs_to_target(task: Task) -> bool:
        if target_initials == "HV":
            return _m3_department_code_label(task.department_id, department_codes) == "FIN"
        assignee_ids = set(assignee_ids_by_task.get(task.id, set()))
        if task.assigned_to:
            assignee_ids.add(task.assigned_to)
        return any(_initials(names.get(user_id)) in targets for user_id in assignee_ids)

    def belongs_to_report_day(task: Task) -> bool:
        due_day = _local_date(task.due_date)
        is_open_overdue = _is_open(task) and due_day is not None and due_day < report_day
        return _belongs_to_day(task, report_day) or is_open_overdue or task.id in feedback_task_ids

    selected = [
        task
        for task in tasks
        if _is_open(task) and belongs_to_report_day(task) and belongs_to_target(task)
    ]

    def m1_sort_key(task: Task) -> tuple:
        period_rank = {"AM": 0, "PM": 1, "AM/PM": 2}.get(_m3_am_pm_label(task), 3)
        task_type = _m3_task_type_label(task)
        # SYS first, every fast-task subtype second, and project tasks last.
        type_rank = 0 if task_type == "SYS" else (2 if task_type == "PRJK" else 1)
        due_day = _local_date(task.due_date)
        is_late = _is_open(task) and due_day is not None and due_day < report_day
        is_late_system = task_type == "SYS" and is_late
        status = "LATE" if is_late else _normalize_report_status(task.status)
        status_rank = {
            "LATE": 0,
            "TODO": 1,
            "IN_PROGRESS": 2,
            "PAUSED": 3,
            "WAITING_CLIENT": 4,
            "WAITING_CONFIRMATION": 5,
        }.get(status, 6)
        return (
            1 if is_late_system else 0,
            period_rank,
            type_rank,
            status_rank,
            common_view_task_sort_key(task, names, assignee_ids_by_task),
        )

    selected.sort(key=m1_sort_key)
    if selected_tasks is not None:
        selected_tasks.extend(selected)
    rows: list[list[str]] = []
    for index, task in enumerate(selected, start=1):
        planned_start, planned_end = planned_range_for_daily_report(task, None)
        tyo_mode = (
            "range"
            if planned_start is not None and planned_end is not None and planned_start < planned_end
            else "dueOnly"
        )
        rows.append([
            str(index),
            _task_owners(task, names, assignee_ids_by_task),
            _m3_department_label(task, department_codes),
            _m3_am_pm_label(task),
            _m3_task_type_label(task),
            (
                "STOPPED"
                if _normalize_report_status(task.status) == "PAUSED"
                else "LATE"
                if _is_open(task)
                and (due_day := _local_date(task.due_date)) is not None
                and due_day < report_day
                else _normalize_report_status(task.status)
            ),
            daily_report_tyo_label(
                report_day=report_day,
                start_day=planned_start if tyo_mode == "range" else None,
                due_day=planned_end,
                mode=tyo_mode,
            ),
            task_title_with_pause(_display_title(task.title), getattr(task, "pause_periods", None), report_day),
        ])
    return rows


def _ga_hv_dv_tables_body(
    rows_by_title: dict[str, list[list[str]]], plan_rows: Sequence[dict[str, str]] = (),
) -> str:
    lines: list[str] = []
    plans = {row["owners"]: row for row in plan_rows}
    for title in (HV_TASKS_TITLE, DV_TASKS_TITLE, GA_TASKS_TITLE):
        if lines:
            lines.append("")
        if plan := plans.get(title[:2]):
            answer = {"PO": "Po", "JO": "Jo"}.get(plan["continuation"], "–")
            comment = " ".join(plan["comment"].split())
            lines.append(f'{plan["title"]} ({plan["owners"]}): {answer}' + (f" · {comment}" if comment else ""))
        columns = GA_TASK_COLUMNS if title == GA_TASKS_TITLE else GA_HV_DV_TASK_COLUMNS
        rows = rows_by_title.get(title, [])
        if not rows:
            rows = [["-", "-", "-", "-", "-", "-", "-", "(Asnje detyre)"]]
        values = [row + [""] * (len(columns) - len(row)) for row in rows]
        lines.extend(_ascii_table(title, columns, values))
    return _normalize_section(lines)


async def _ga_hv_dv_task_section(
    db: AsyncSession,
    tasks: list[Task],
    names: dict[Any, str],
    assignee_ids_by_task: dict[Any, set[Any]],
    report_day: date,
    department_codes: dict[Any, str],
    overrides: dict,
) -> tuple[str, dict]:
    feedback_by_task = await load_task_plan_feedback(db, report_day, [task.id for task in tasks])

    rows_by_title = {}
    feedback_rows = {}
    for title, initials in ((HV_TASKS_TITLE, "HV"), (DV_TASKS_TITLE, "DV"), (GA_TASKS_TITLE, "GA")):
        responses_by_task = {}
        for task in tasks:
            answers_by_user = feedback_by_task.get(task.id)
            if not answers_by_user:
                continue
            owners = set(assignee_ids_by_task.get(task.id, ()))
            if task.assigned_to:
                owners.add(task.assigned_to)
            allowed = owners if title == HV_TASKS_TITLE else {
                owner for owner in owners if _initials(names.get(owner)) == initials
            }
            responses_by_task[task.id] = [
                (owner, action, comment)
                for owner, (action, comment) in answers_by_user.items()
                if owner in allowed
            ]
        selected: list[Task] = []
        rows = _ga_hv_dv_task_rows(
            tasks, names, assignee_ids_by_task, report_day, department_codes, initials,
            selected_tasks=selected,
            feedback_task_ids={
                task_id for task_id, responses in responses_by_task.items()
                if any(action or comment for _, action, comment in responses)
            },
        )
        rows_by_title[title] = rows
        feedback_rows[title] = []
        bz_labels = await ga_task_bz_labels(db, selected, assignee_ids_by_task) if title == GA_TASKS_TITLE else {}
        for row, task in zip(rows, selected):
            responses = responses_by_task.get(task.id, [])
            actions = {action for _, action, _ in responses}
            continuation = "JO" if "JO" in actions else "PO" if "PO" in actions else ""
            comments = [(owner, comment) for owner, _, comment in responses if comment]
            comment = " / ".join(
                f"{_initials(names.get(owner))}: {value}" if len(comments) > 1 else value
                for owner, value in sorted(comments, key=lambda item: (names.get(item[0], ""), str(item[0])))
            )
            key = f"{title}:{task.id}"
            manual = overrides.get(key, {})
            continuation = manual.get("continuation", continuation)
            comment = manual.get("comment", comment)
            if title == GA_TASKS_TITLE:
                row.append(bz_labels.get(task.id, "-"))
            row.extend((CONTINUATION_ICONS.get(continuation, ""), comment.replace("|", "│")))
            feedback_rows[title].append({
                "key": key, "title": row[7], "owners": row[1],
                "continuation": continuation, "comment": comment,
            })
    plan_rows = []
    for owners in ("HV", "DV", "GA"):
        key = f"plan:{owners}"
        saved = overrides.get(key, {})
        plan_rows.append({
            "key": key, "title": "A prishet plani për sot?", "owners": owners,
            "continuation": saved.get("continuation", ""), "comment": saved.get("comment", ""),
        })
    feedback_rows["plan"] = plan_rows
    return _ga_hv_dv_tables_body(rows_by_title, plan_rows), feedback_rows


def _marked_tasks_for_day(tasks: list[Task], report_day: date, markers: set[str]) -> list[Task]:
    return [
        task for task in tasks
        if markers.intersection((active_one_h_marker(task) or "").split(","))
        and _task_covers_day(task, report_day)
    ]


def _marked_task_identity(task: Task) -> tuple:
    for field in ("ga_note_origin_id", "plan_note_origin_id", "fast_task_group_id"):
        if value := getattr(task, field, None):
            return field, value
    if getattr(task, "system_template_origin_id", None) and getattr(task, "origin_run_at", None):
        return "system", task.system_template_origin_id, task.origin_run_at
    if all(getattr(task, field, None) for field in ("meeting_origin_id", "meeting_occurrence_date", "meeting_system_task_kind")):
        return "meeting", task.meeting_origin_id, task.meeting_occurrence_date, task.meeting_system_task_kind
    if task.project_id and task.created_at:
        # Project copies created together share PostgreSQL's transaction timestamp.
        return "project", task.project_id, task.created_at, getattr(task, "created_by", None), task.title
    return "task", task.id


def _group_marked_tasks(
    tasks: list[Task],
    names: dict[Any, str],
    assignee_ids_by_task: dict[Any, set[Any]],
) -> tuple[list[Task], dict[Any, set[Any]]]:
    grouped: dict[tuple, Task] = {}
    owners: dict[Any, set[Any]] = {}
    ordered = sorted(tasks, key=lambda task: (
        bool(getattr(task, "completed_at", None)) or _normalize_report_status(task.status) == "DONE",
        common_view_task_sort_key(task, names, assignee_ids_by_task),
        str(task.id),
    ))
    for task in ordered:
        markers = frozenset((active_one_h_marker(task) or "").split(","))
        representative = grouped.setdefault((_marked_task_identity(task), markers), task)
        assignees = assignee_ids_by_task.get(task.id, {task.assigned_to} if task.assigned_to else set())
        owners.setdefault(representative.id, set()).update(assignees)
    return list(grouped.values()), owners


def _marker_task_table(
    caption: str,
    tasks: list[Task],
    names: dict[Any, str],
    assignee_ids_by_task: dict[Any, set[Any]],
    department_codes: dict[Any, str],
) -> str:
    return _normalize_section(_m3_status_table(
        caption, tasks, names,
        with_status=True,
        include_department=True,
        include_am_pm=True,
        include_type=True,
        department_codes=department_codes,
        assignee_ids_by_task=assignee_ids_by_task,
        show_all_assignees=True,
    ))


def _symbol_comment_table(rows: list[list[str]]) -> str:
    if not rows:
        rows = [["-", "-", "-", "-", "-", "-", "-", "(Asnje koment te simbolet)", "-", "-"]]
    return _normalize_section(_ascii_table("KOMENTET TE SIMBOLET", SYMBOL_COMMENT_COLUMNS, rows))


async def _load_symbol_comments(
    db: AsyncSession,
    report_day: date,
    generated_at: datetime,
    tasks: list[Task],
    names: dict[Any, str],
    assignee_ids_by_task: dict[Any, set[Any]],
    department_codes: dict[Any, str],
) -> list[list[str]]:
    if not tasks:
        return []
    tz = report_timezone()
    start = datetime.combine(report_day - timedelta(days=1), time(16, 30), tz)
    next_day = datetime.combine(report_day + timedelta(days=1), time.min, tz)
    events = (await db.execute(
        select(TaskSymbolCommentEvent).where(
            TaskSymbolCommentEvent.created_at >= start,
            TaskSymbolCommentEvent.created_at <= generated_at,
            TaskSymbolCommentEvent.created_at < next_day,
        ).order_by(TaskSymbolCommentEvent.created_at.desc(), TaskSymbolCommentEvent.id.desc())
    )).scalars().all()

    by_task: dict[Any, list[TaskSymbolCommentEvent]] = {}
    for event in events:
        by_task.setdefault(event.task_id, []).append(event)
    grouped: dict[tuple, tuple[Task, TaskSymbolCommentEvent, set[Any]]] = {}
    ordered = sorted((task for task in tasks if task.id in by_task), key=lambda task: (
        bool(task.completed_at) or _normalize_report_status(task.status) == "DONE",
        common_view_task_sort_key(task, names, assignee_ids_by_task),
        str(task.id),
    ))
    for task in ordered:
        owners = assignee_ids_by_task.get(task.id, {task.assigned_to} if task.assigned_to else set())
        for event in by_task[task.id]:
            comment = " ".join(event.comment.split())
            if not comment or not event.marker.strip():
                continue
            key = (_marked_task_identity(task), event.marker, comment)
            representative, latest, combined = grouped.get(key, (task, event, set()))
            combined.update(owners)
            if event.created_at > latest.created_at:
                latest = event
            grouped[key] = representative, latest, combined

    rows = []
    for index, (task, event, owners) in enumerate(grouped.values(), 1):
        title = _clean_task_title(
            task.title,
            is_system_task=bool(task.system_template_origin_id or getattr(task, "system_task_slot_id", None)),
        )
        rows.append([
            str(index), _task_owners(task, names, {task.id: owners}, show_all_assignees=True),
            _m3_department_label(task, department_codes), _m3_am_pm_label(task), _m3_task_type_label(task),
            _normalize_report_status(task.status), one_h_marker_label(event.marker),
            _strip_status_markers(title).replace("|", "｜"),
            TECHNICAL_TAG.sub("", _strip_status_markers(event.comment)).replace("|", "｜"),
            event.created_at.astimezone(tz).strftime("%d.%m.%Y %H:%M"),
        ])
    return rows


async def refresh_morning_task_tables(
    db: AsyncSession,
    sections: list[dict[str, str]],
    report_day: date,
    *,
    task_feedback_overrides: dict | None = None,
) -> list[dict[str, Any]]:
    """Refresh the auto-filled task tables in an existing M1 draft."""
    tasks = (await db.execute(select(Task).where(Task.work_staff_filter()).where(Task.is_active.is_(True)))).scalars().all()
    names = await _assignee_names(db, tasks)
    assignee_ids_by_task = await _effective_task_assignee_ids(db, tasks)
    tasks, names, assignee_ids_by_task = await filter_task_context(db, report_day, tasks, names, assignee_ids_by_task)
    department_codes = {
        department_id: code
        for department_id, code in (await db.execute(select(Department.id, Department.code))).all()
    }
    await apply_weekly_planner_task_order(db, tasks, assignee_ids_by_task, department_codes)
    body, feedback_rows = await _ga_hv_dv_task_section(
        db, tasks, names, assignee_ids_by_task, report_day, department_codes, task_feedback_overrides or {},
    )
    bodies = {GA_HV_DV_TASKS_TITLE: body}
    for title, (markers, caption) in MARKER_TASK_SECTIONS.items():
        marked_tasks, owners = _group_marked_tasks(
            _marked_tasks_for_day(tasks, report_day, markers), names, assignee_ids_by_task,
        )
        bodies[title] = _marker_task_table(caption, marked_tasks, names, owners, department_codes)
    return [
        {
            **section,
            "body": bodies[section["section_key"]],
            **({TASK_FEEDBACK_ROWS: feedback_rows} if section["section_key"] == GA_HV_DV_TASKS_TITLE else {}),
        }
        if section.get("section_key") in bodies
        else section
        for section in sections
    ]


async def refresh_morning_leave_table(db, sections, report_day, snapshot):
    return await refresh_saved_leave_table(
        db, sections, section_title=SECTION_TITLES[2], report_day=report_day,
        leave_day=report_day, snapshot=snapshot,
    )


async def _day_context_section(
    db: AsyncSession,
    entries: list[CommonEntry],
    names: dict[Any, str],
    tasks: list[Task],
    assignee_ids_by_task: dict[Any, set[Any]],
    report_day: date,
    user_department_codes: dict[Any, str] | None = None,
    user_sort_keys: dict[Any, tuple[int, str, int, int, str]] | None = None,
) -> tuple[str, int]:
    leave_rows = []
    holiday_rows: list[list[str]] = []
    common_block_lines: list[str] = []
    for entry in entries:
        if entry.category == CommonCategory.annual_leave:
            start, end, full_day, start_time, end_time, note, is_all_users = parse_common_view_annual_leave(entry)
            if start <= report_day <= end:
                # _leave_lines is shared with M3 and expects the complete
                # annual-leave tuple, including the start and end dates.
                leave_rows.append((entry, start, end, full_day, start_time, end_time, note, is_all_users))
        elif entry.category == CommonCategory.external_holiday and _entry_day(entry) == report_day:
            holiday_rows.append(
                [str(len(holiday_rows) + 1), _display_title(entry.title), _clean_entry_note(entry.description)]
            )
        elif entry.category == CommonCategory.blocks and _entry_day(entry) == report_day:
            common_block_lines.append(f"- {_entry_person(entry, names)}: {_display_title(entry.title)}")

    meetings = (await db.execute(select(Meeting).where(Meeting.starts_at.is_not(None)))).scalars().all()
    meetings = [meeting for meeting in meetings if is_common_view_visible_meeting(meeting)]
    today_meetings = [meeting for meeting in meetings if _meeting_occurs_on_date(meeting, report_day)]
    external_meetings = [meeting for meeting in today_meetings if meeting.meeting_type == "external"]
    internal_meetings = [meeting for meeting in today_meetings if meeting.meeting_type != "external"]
    external_meetings_by_id = {
        str(meeting.id): meeting
        for meeting in meetings
        if meeting.meeting_type == "external"
    }

    # BZ can include a completed alignment task. Keep the open-task list for
    # normal report filtering, but retain all tasks for BZ row metadata so a
    # completed row still displays its responsible user's department and AM/PM.
    today_report_tasks = [task for task in tasks if _belongs_to_day(task, report_day)]
    today_tasks = [task for task in today_report_tasks if _is_open(task)]
    bz_tasks = [task for task in today_tasks if re.search(r"\bBZ\b", task.title or "", re.I)]
    blocked_tasks = [task for task in today_tasks if task.is_bllok]
    all_participant_ids = await _all_participant_user_ids(db)
    bz_lines = await _bz_alignment_lines(
        db, report_day, tasks, names, assignee_ids_by_task, include_status=True
    )
    bz_lines = bz_lines or _task_lines(
        bz_tasks,
        names,
        assignee_ids_by_task,
        include_status=True,
        all_participant_ids=all_participant_ids,
    )
    block_lines = [
        *common_block_lines,
        *_task_lines(
            blocked_tasks,
            names,
            assignee_ids_by_task,
            include_status=True,
            all_participant_ids=all_participant_ids,
        ),
    ]
    bz_lines = list(dict.fromkeys(line for line in bz_lines if line and not line.startswith("(")))
    block_lines = list(dict.fromkeys(line for line in block_lines if line and not line.startswith("(")))
    department_codes = {
        department_id: code
        for department_id, code in (await db.execute(select(Department.id, Department.code))).all()
    }

    lines = [
        "PV",
        *_leave_lines(leave_rows, names, user_department_codes, user_sort_keys),
        "",
        *_ascii_table("FESTA EXTERNE", [("NR", 2), ("FESTA", 48), ("NOTE", 32)], holiday_rows),
        "",
        *_tomorrow_meeting_table(
            "TAKIMET EXTERNE",
            _meeting_lines(external_meetings, external_meetings_by_id),
        ),
        "",
        *_tomorrow_meeting_table(
            "TAKIMET INTERNE",
            _meeting_lines(internal_meetings, external_meetings_by_id),
        ),
        "",
        *_tomorrow_task_table(
            "BZ ME GA",
            bz_lines,
            with_status=True,
            task_metadata=_task_metadata_by_title(
                today_report_tasks,
                department_codes,
                names,
                assignee_ids_by_task,
                all_participant_ids,
            ),
            include_am_pm_times=True,
        ),
        "",
        *_tomorrow_task_table(
            "BLLOK",
            block_lines,
            with_status=True,
            task_metadata=_task_metadata_by_title(
                blocked_tasks,
                department_codes,
                names,
                assignee_ids_by_task,
                all_participant_ids,
            ),
        ),
    ]
    count = len(leave_rows) + len(holiday_rows) + len(today_meetings) + len(bz_lines) + len(block_lines)
    return _normalize_section(lines), count


async def build_morning_report_sections(
    db: AsyncSession, report_day: date, *, task_feedback_overrides: dict | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    generated_at = datetime.now(timezone.utc)
    tasks = (await db.execute(select(Task).where(Task.work_staff_filter()).where(Task.is_active.is_(True)))).scalars().all()
    report_categories = [
        CommonCategory.delays,
        CommonCategory.absences,
        CommonCategory.annual_leave,
        CommonCategory.external_holiday,
        CommonCategory.blocks,
    ]
    entries = (
        await db.execute(select(CommonEntry).where(CommonEntry.category.in_(report_categories)))
    ).scalars().all()
    names = await _assignee_names(db, tasks)
    assignee_ids_by_task = await _effective_task_assignee_ids(db, tasks)
    tasks, names, assignee_ids_by_task = await filter_task_context(db, report_day, tasks, names, assignee_ids_by_task)
    entry_user_ids = {
        user_id
        for entry in entries
        for user_id in (entry.assigned_to_user_id, entry.created_by_user_id)
        if user_id and user_id not in names
    }
    if entry_user_ids:
        users = (await db.execute(select(User).where(User.work_staff_filter()).where(User.id.in_(entry_user_ids)))).scalars().all()
        names.update({user.id: user.full_name or user.username or user.email for user in users})

    department_codes = {
        department_id: code
        for department_id, code in (await db.execute(select(Department.id, Department.code))).all()
    }
    await apply_weekly_planner_task_order(db, tasks, assignee_ids_by_task, department_codes)
    user_department_codes = {
        user_id: department_codes.get(department_id, "-") or "-"
        for user_id, department_id in (await db.execute(select(User.id, User.department_id).where(User.work_staff_filter()))).all()
    }
    leave_user_ids = {
        entry.assigned_to_user_id or entry.created_by_user_id
        for entry in entries
        if entry.category == CommonCategory.annual_leave
        and (entry.assigned_to_user_id or entry.created_by_user_id)
    }
    leave_user_sort_keys = await weekly_planner_user_sort_keys(db, leave_user_ids, department_codes)

    blue_notes = await load_blue_notes(db)
    note_rows = [values for _, values in blue_notes]
    all_participant_ids = await _all_participant_user_ids(db)
    task_tables, feedback_rows = await _ga_hv_dv_task_section(
        db, tasks, names, assignee_ids_by_task, report_day, department_codes, task_feedback_overrides or {},
    )
    day_context, day_context_count = await _day_context_section(
        db,
        entries,
        names,
        tasks,
        assignee_ids_by_task,
        report_day,
        user_department_codes,
        leave_user_sort_keys,
    )
    personal = await _personal_section(
        db,
        tasks,
        names,
        assignee_ids_by_task,
        report_day,
        title_pattern=PERSONAL_GA,
        department_codes=department_codes,
    )
    personal_ka_genti = [
        task for task in tasks
        if task.is_personal
        and _belongs_to_day(task, report_day)
        and _ka_genti_owner(task) is not None
    ]
    personal_ka_genti_tables = [
        *_m3_status_table(
            "PERSONAL KA",
            [task for task in personal_ka_genti if _ka_genti_owner(task) == "KA"],
            names,
            with_status=True,
            include_department=True,
            include_am_pm=True,
            department_codes=department_codes,
            assignee_ids_by_task=assignee_ids_by_task,
            all_participant_ids=all_participant_ids,
        ),
        "",
        *_m3_status_table(
            "PERSONAL GENTI",
            [task for task in personal_ka_genti if _ka_genti_owner(task) == "GENTI"],
            names,
            with_status=True,
            include_department=True,
            include_am_pm=True,
            department_codes=department_codes,
            assignee_ids_by_task=assignee_ids_by_task,
            all_participant_ids=all_participant_ids,
        ),
    ]
    wfc_report_tasks = [
        task for task in tasks
        if _belongs_to_day(task, report_day)
        and _is_report_wfc_task(task)
        and _ka_genti_confirmer(task, names) is not None
    ]
    wfc = [
        *_m3_status_table(
            "WFC KA",
            [task for task in wfc_report_tasks if _ka_genti_confirmer(task, names) == "KA"],
            names,
            with_status=True,
            include_department=True,
            include_am_pm=True,
            department_codes=department_codes,
            assignee_ids_by_task=assignee_ids_by_task,
            all_participant_ids=all_participant_ids,
        ),
        "",
        *_m3_status_table(
            "WFC GENTI",
            [task for task in wfc_report_tasks if _ka_genti_confirmer(task, names) == "GENTI"],
            names,
            with_status=True,
            include_department=True,
            include_am_pm=True,
            department_codes=department_codes,
            assignee_ids_by_task=assignee_ids_by_task,
            all_participant_ids=all_participant_ids,
        ),
    ]

    attendance = _attendance_section(entries, names, report_day)
    symbol_comments = await _load_symbol_comments(
        db, report_day, generated_at, tasks, names, assignee_ids_by_task, department_codes,
    )
    from app.services.discord_ga_replies import summary_for_day
    sections = [
        {"title": SECTION_TITLES[0], "body": await summary_for_day(db, report_day, report="M1", generated_at=generated_at)},
        {"section_key": GA_REACTIONS_SECTION_KEY, "title": GA_REACTIONS_SECTION_TITLE,
         "body": await reaction_summary_for_day(db, report_day, report="M1", generated_at=generated_at)},
        {"title": GA_PF_COMMENTS_TITLE, "body": _symbol_comment_table(symbol_comments)},
        {"title": GA_HV_DV_TASKS_TITLE, "body": task_tables},
        {"title": SECTION_TITLES[2], "body": attendance},
        {"title": SECTION_TITLES[3], "body": _notes_section(note_rows)},
        {"title": SECTION_TITLES[4], "body": day_context},
        {"title": SECTION_TITLES[5], "body": _normalize_section(personal)},
        {"title": SECTION_TITLES[7], "body": _normalize_section(personal_ka_genti_tables)},
        {"title": SECTION_TITLES[8], "body": _normalize_section(wfc)},
    ]
    pv, _ = _split_pv_table(day_context)
    _, pv_rows = _section_report_table_rows(pv.splitlines())
    pv_count = sum(row[0].isdigit() for row in pv_rows)
    snapshot = {
        "report_day": report_day.isoformat(),
        NOTE_REFERENCES: blue_notes,
        "ga_replies_generated_at": generated_at.isoformat(),
        "ga_replies_window_version": GA_REPLIES_WINDOW_VERSION,
        GA_REPLIES_CAPTURE_VERSION_KEY: GA_REPLIES_CAPTURE_VERSION,
        "leave_table_preserved": True,
        TASK_FEEDBACK_ROWS: feedback_rows,
        TASK_FEEDBACK_OVERRIDES: task_feedback_overrides or {},
        "counts": {
            SECTION_TITLES[0]: 0,
            GA_PF_COMMENTS_TITLE: len(symbol_comments),
            GA_HV_DV_TASKS_TITLE: sum(len(rows) for title, rows in feedback_rows.items() if title != "plan"),
            SECTION_TITLES[2]: pv_count + sum(
                1
                for entry in entries
                if entry.category in {CommonCategory.delays, CommonCategory.absences}
                and _entry_day(entry) == report_day
            ),
            SECTION_TITLES[3]: len(note_rows),
            SECTION_TITLES[4]: day_context_count - pv_count,
            SECTION_TITLES[5]: sum(1 for line in personal if re.match(r"^\|\s+\d+\s+\|", line)),
            SECTION_TITLES[7]: len(personal_ka_genti),
            SECTION_TITLES[8]: len(wfc_report_tasks),
        },
    }
    for title, (markers, caption) in MARKER_TASK_SECTIONS.items():
        marked_tasks, owners = _group_marked_tasks(
            _marked_tasks_for_day(tasks, report_day, markers), names, assignee_ids_by_task,
        )
        sections.append({
            "section_key": title,
            "title": title,
            "body": _marker_task_table(caption, marked_tasks, names, owners, department_codes),
        })
        snapshot["counts"][title] = len(marked_tasks)
    ordered = await refresh_m1_gmail_section(
        normalize_morning_report_sections(sections), report_day, generated_snapshot=snapshot,
    )
    return await filter_report_sections(db, ordered, report_day), snapshot


def render_plain_text(subject: str, report_day: date, sections: list[dict[str, str]]) -> str:
    from app.services.meeting_point_manual_sync import section_group_label

    blocks = [subject, f"Sot: {report_day:%d.%m.%Y}", ""]
    current_group = ""
    for index, section in enumerate(sections, 1):
        group = section_group_label("morning", section["title"], section.get("section_key"))
        if group != current_group:
            blocks.append(group)
            current_group = group
        blocks.append(
            f"{index}. {section['title']}\n{_strip_status_markers(section.get('body') or '')}".strip()
        )
    return "\n\n".join(blocks)


def render_html(subject: str, report_day: date, sections: list[dict[str, str]]) -> str:
    from app.services.meeting_point_manual_sync import section_group_label
    from app.services.meetings_report import (
        _render_group_label_html,
        _render_section_block_html,
        _wrap_report_email_html,
    )

    section_chunks: list[str] = []
    current_group = ""
    for index, section in enumerate(sections, 1):
        group = section_group_label("morning", section["title"], section.get("section_key"))
        if group != current_group:
            section_chunks.append(_render_group_label_html(group))
            current_group = group
        section_chunks.append(_render_section_block_html(index, section["title"], section.get("body") or ""))
    return _wrap_report_email_html(
        subject,
        f"Sot: {report_day:%d.%m.%Y}",
        "".join(section_chunks),
    )


async def send_morning_report(
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
        report_code="M1", report_day=report_day, sections=sections,
    )
