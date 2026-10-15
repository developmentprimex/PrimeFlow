from __future__ import annotations

import html
import os
import re
from io import BytesIO
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.compact_report_questions import question_parts, layout_question_parts
from app.config import settings
from app.services.meeting_palette import meeting_report_color
from app.services.meetings_report import common_view_item_sort_key, next_working_day
from app.services.primeflow_report import GmailService, PrimeFlowClient, REPORT_SENDER_EMAIL, report_timezone
from app.services.personal_task_owner import personal_task_owner
from app.services.one_h_ga_summary import build_ga_summary, summary_html, summary_text, TITLE as GA_SUMMARY_TITLE
from app.services.task_title_rules import normalize_email_task_title, title_has_eight_am_indicator
from app.services.tomorrow_closing_sections import (
    ClosingSection,
    ClosingTable,
    ClosingTableRow,
    build_tomorrow_closing_sections,
)


TASK_ROWS = (
    ("oneH", "1H 10:00", "10:00"),
    ("oneH", "1H 11:00", "11:00"),
    ("oneH", "1H 11:50", "11:50"),
    ("oneH", "1H 14:20", "14:20"),
    ("waitingClient", "WFE", None),
    ("blocked", "BLL\n14:30 - 16:00\nRAP 16:10", None),
    ("oneH", "1H 16:00", "16:00"),
    ("oneH", "1H NO SLOT", ""),
    ("important", "DEADLINE / 08:00", None),
    ("r1", "R1=1H", None),
    ("personal", "P: GA\n08:15 / 13:15", "GA"),
    ("personal", "P: KA\n08:30 / 13:15", "KA"),
    ("personal", "P: GENT", "GENT"),
    ("personal", "P: PX\n08:45 / 14:00", "PX"),
)
MEETING_ROWS = (("external", "TAK EXT"), ("internal", "TAK INT"))
VALID_1H_SLOTS = {"10:00", "11:00", "11:50", "14:20", "16:00"}
EXCLUDED_1H_MISSING_INITIALS = {"GA", "KA", "HV", "HS"}
ONE_H_BOARD_PRIMARY_CHECKLIST = (
    ("Slotin paraprak/aktual", ""),
    ("A ke filluar me slotin aktual?", ""),
    ("Nese jo, kur?", ""),
    ("A kryhet sot?", ""),
    ("A kryhet kete jave?", ""),
    ("A arrihet RLZ javor?", ""),
)
ONE_H_BOARD_FOLLOW_UP_CHECKLIST = (
    ("Notes te reja? Data? AM/PM? Kujt", ""),
    ("Done? / Strikes?", ""),
    ("BZ Det nga Stafi per GA", "Komunikimi GA teams Det nga Stafi/ KA email"),
    ("BZ Notes", "Secili i lexon vet para BZ me GA"),
)
ONE_H_BOARD_CHECKLIST = ONE_H_BOARD_PRIMARY_CHECKLIST + ONE_H_BOARD_FOLLOW_UP_CHECKLIST
ONE_H_STAFF_CHECKLIST = (
    ("Hap doc dhe det", ""),
    ("Share screen side by side DET/REZULTATIN", ""),
    ("Sqaro slotin paraprak pastaj aktual", ""),
    ("BZ Det nga Stafi per GA", "Komunikimi GA teams Det nga Stafi/ KA email"),
)
THURSDAY_ONE_H_BOARD_CHECKLIST = (("Planifikimi javor short", ""),)
THURSDAY_ONE_H_STAFF_CHECKLIST = (
    ("Emails per missing info, per me vazhdu javen tjeter", ""),
    ("Shikohen det qe mbesin vetem per neser (te premten)", ""),
)
FRIDAY_ONE_H_STAFF_CHECKLIST = (
    ("BZ PERSONALISHT ME GA: KOMENTET TEK OPEN TASKS EXCEL", ""),
    ("BZ PERSONALISHT ME GA: DET GA TEK PER/NGA STAFI PER GA TEAMS", ""),
    ("Barazimi i planifikimit javor - next week", ""),
    ("Barazimi i realizimit javor - this week", ""),
    ("Emails per missing info, per me vazhdu javen tjeter", ""),
)
THURSDAY_ONE_H_QUESTION_REPORT_CODES = {
    "Emails per missing info, per me vazhdu javen tjeter": "M1",
    "Shikohen det qe mbesin vetem per neser (te premten)": "M3",
    "Planifikimi javor short": "M1",
}
FRIDAY_ONE_H_QUESTION_REPORT_CODES = {
    "BZ PERSONALISHT ME GA: KOMENTET TEK OPEN TASKS EXCEL": "M1",
    "BZ PERSONALISHT ME GA: DET GA TEK PER/NGA STAFI PER GA TEAMS": "M1",

    "Barazimi i planifikimit javor - next week": "M1",
    "Barazimi i realizimit javor - this week": "M1",
    "Emails per missing info, per me vazhdu javen tjeter": "M1",
}


def _checklist_question_number(report_day: date | None, index: int, question: str) -> str:
    report_codes = (
        THURSDAY_ONE_H_QUESTION_REPORT_CODES if report_day is not None and report_day.weekday() == 3
        else FRIDAY_ONE_H_QUESTION_REPORT_CODES if report_day is not None and report_day.weekday() == 4
        else {}
    )
    report_code = report_codes.get(question)
    return f"{report_code} - {index}." if report_code else f"{index}."


def _one_h_checklists_for_day(
    report_day: date | None,
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    """Return Board and Staff checklists with Thursday/Friday closing checks."""
    if report_day is not None and report_day.weekday() == 3:
        return (
            ONE_H_BOARD_CHECKLIST + THURSDAY_ONE_H_BOARD_CHECKLIST,
            ONE_H_STAFF_CHECKLIST + THURSDAY_ONE_H_STAFF_CHECKLIST,
        )
    if report_day is not None and report_day.weekday() == 4:
        return ONE_H_BOARD_CHECKLIST, ONE_H_STAFF_CHECKLIST + FRIDAY_ONE_H_STAFF_CHECKLIST
    return ONE_H_BOARD_CHECKLIST, ONE_H_STAFF_CHECKLIST


def _day_specific_question_label(report_day: date | None) -> str:
    if report_day is not None and report_day.weekday() == 3:
        return "E ENJTE- PYETJET E TE ENJTES"
    if report_day is not None and report_day.weekday() == 4:
        return "E PREMTE"
    return "PYETJET SHTESE: 0"

# Gmail can remove style blocks from message bodies. Keep the styles that form
# the report grid inline so the received email matches the preview.
TABLE_STYLE = "width:100%;border-collapse:collapse;table-layout:fixed;margin:12px 0;font-family:Arial,sans-serif;font-size:12px;line-height:1.25;color:#000"
CELL_STYLE = "border:1px solid #000;padding:5px;vertical-align:top;text-align:left;overflow-wrap:anywhere;word-break:break-word"
HEADER_STYLE = f"{CELL_STYLE};text-align:center;font-weight:700"
SLOT_DIVIDER_STYLE = "border-top:2px solid #111827"
MEETING_TYPE_DIVIDER_STYLE = "border-top:4px solid #111827"
INTRA_SLOT_DIVIDER_STYLE = "border-top:1px solid #cbd5e1"
SLOT_END_DIVIDER_STYLE = "border-bottom:2px solid #111827"
TASK_TABLE_FRAME_STYLE = "border:3px solid #111827"
TASK_HEADER_FRAME_STYLE = "border-top:3px solid #111827;border-bottom:3px solid #111827"
MEETING_TABLE_FRAME_STYLE = "border:4px solid #111827"
MEETING_HEADER_FRAME_STYLE = "border:3px solid #111827"
SLOT_LABEL_STYLE = f"{CELL_STYLE};font-weight:700"
PERSONAL_GA_COLOR = "#D8B4FE"
PERSONAL_GA_CELL_STYLE = f"{CELL_STYLE};background-color:{PERSONAL_GA_COLOR}"
PERSONAL_ROW_LABEL_STYLE = (
    f"{CELL_STYLE};font-size:10px;line-height:1.15;white-space:pre-line;"
    "overflow-wrap:normal;word-break:normal"
)
PERSONAL_TIME_STYLE = "font-size:13px;line-height:1.2;font-weight:800;white-space:nowrap"
TASK_TITLE_TEXT_STYLE = "display:inline-block;font-size:17px;line-height:1.25;padding-top:4px"
MEETING_TITLE_TEXT_STYLE = "font-size:14px;line-height:1.3;padding-top:8px"
DEADLINE_COLOR = "#DC2626"
EIGHT_AM_BORDER_COLOR = "#DC2626"
NON_ROUTINE_MEETING_BORDER_COLOR = "#2563EB"
CALENDAR_INTERNAL_TEXT_COLOR = "#64748B"
PERSONAL_TASK_INITIALS = re.compile(r"^[A-Z]{1,5}(?:\s*[:/]\s*[A-Z]{1,5})*(?=\s|:|/|$)", re.I)
NOTE_MARKERS_RE = re.compile(r"\[\[\s*/?\s*(?:added|done)\s*\]\]", re.I)
WFC_TOKEN_RE = re.compile(r"\bWFC\b", re.I)
STATUS_COLORS = {
    "TODO": "#FFC4ED",
    "IN_PROGRESS": "#FFFF00",
    "WAITING_CLIENT": "#E2C15B",
    "WAITING_CONFIRMATION": "#FFEDD5",
    "DONE": "#C4FDC4",
}
CLOSING_TONE_COLORS = {
    "todo": STATUS_COLORS["TODO"],
    "notes": "#DBEAFE",
}
COMMENT_DEV_INITIALS = ("AT", "EF", "RA", "EH", "LH")
COMMENT_GD_INITIALS = ("FG",)
COMMENT_FIXED_INITIALS = COMMENT_DEV_INITIALS + COMMENT_GD_INITIALS
COMMENT_WRITE_IN_LINE = "_" * 20
REQUIRED_SHTYPI_RECIPIENTS = (
    "130primex.eu@gmail.com",
    "313primex.eu@gmail.com",
    "131primex.eu@gmail.com",
    "info@primexeu.com",
)
# Kept for callers that use the original archive mailbox constant.
REQUIRED_SHTYPI_RECIPIENT = REQUIRED_SHTYPI_RECIPIENTS[0]


def ensure_required_shtypi_recipient(
    recipients: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Always include every required SHTYPI mailbox as a To recipient."""
    result = {key: [] for key in ("to", "cc", "bcc")}
    seen: set[str] = set()
    for key in ("to", "cc", "bcc"):
        for raw in recipients.get(key, []):
            email = str(raw or "").strip()
            normalized = email.casefold()
            if not email or normalized in seen:
                continue
            seen.add(normalized)
            result[key].append(email)
    for required_email in REQUIRED_SHTYPI_RECIPIENTS:
        required_key = required_email.casefold()
        for key in ("cc", "bcc"):
            result[key] = [email for email in result[key] if email.casefold() != required_key]
        if all(email.casefold() != required_key for email in result["to"]):
            result["to"].append(required_email)
    return result


def subject_for(target_date: date, relative_day_label: str) -> str:
    """Return the shared email subject and visible report title."""
    return f"1H SHTYPI {relative_day_label} (Shiko simbolet) — {target_date:%d.%m.%Y}"


def _item_date(item: dict[str, Any]) -> date | None:
    raw = item.get("date") or item.get("entryDate") or item.get("entry_date")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _slot(item: dict[str, Any]) -> str:
    raw = str(item.get("oneHReportSlot") or item.get("one_h_report_slot") or "").strip()
    return raw if raw in VALID_1H_SLOTS else ""


def _first_line(value: Any) -> str:
    return next((line.strip() for line in str(value or "").splitlines() if line.strip()), "")


def _report_text(value: Any) -> str:
    """Remove note-editor markup; recipients must only see the task text."""
    return re.sub(r"\s{2,}", " ", NOTE_MARKERS_RE.sub("", str(value or ""))).strip()


def _task_status(item: dict[str, Any]) -> str:
    raw = str(item.get("status") or item.get("task_status") or item.get("state") or "TODO")
    normalized = raw.strip().upper().replace(" ", "_").replace("-", "_")
    if normalized in {"COMPLETED", "COMPLETE"}:
        return "DONE"
    if normalized in {"TO_DO", "TODO"}:
        return "TODO"
    if normalized in {"INPROGRESS", "IN_PROGRESS"}:
        return "IN_PROGRESS"
    if normalized in {"WFE", "WAITINGCLIENT", "WAITING_FOR_CLIENT", "WAITING_CLIENT"}:
        return "WAITING_CLIENT"
    if normalized in {"WAITING", "PENDING_CONFIRMATION", "WAITING_CONFIRMATION"}:
        return "WAITING_CONFIRMATION"
    return normalized if normalized in STATUS_COLORS else "TODO"


def _completed_on_day(item: dict[str, Any], report_day: date) -> bool:
    if _task_status(item) != "DONE":
        return False
    raw = item.get("completed_at") or item.get("completedAt")
    if not raw:
        return False
    try:
        completed_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if completed_at.tzinfo is not None:
        completed_at = completed_at.astimezone(report_timezone())
    return completed_at.date() == report_day


def _task_period_label(item: dict[str, Any]) -> str:
    """Match the AM/PM indicator used by Common View task cards."""
    raw = str(item.get("finishPeriod") or item.get("finish_period") or "").strip().upper()
    return raw if raw in {"AM", "PM"} else "AM/PM"


def _task_marker_label(item: dict[str, Any]) -> str:
    raw = str(item.get("oneHMarker") or item.get("one_h_marker") or "").strip().upper()
    label = {
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
    }.get(raw, "")
    marker_by_ga = _task_marker_was_set_by_ga(item)
    return f"({label})" if label and marker_by_ga else label


def _task_marker_was_set_by_ga(item: dict[str, Any]) -> bool:
    return bool(item.get("oneHMarkerByGa") or item.get("one_h_marker_by_ga"))


def _task_marker_text_token(item: dict[str, Any]) -> str:
    label = _task_marker_label(item)
    if not label:
        return ""
    return label if _task_marker_was_set_by_ga(item) else f"[{label}]"


def _task_marker_comment(item: dict[str, Any]) -> str:
    return str(item.get("oneHMarkerComment") or item.get("one_h_marker_comment") or "").strip()


def _task_marker_legend_text() -> str:
    return (
        "LEGJENDA: ? - PYETJE/PAQARTESI / "
        "! - DYSHIM/ NUK KUPTOHET DET / "
        "!!! - KLIENT/URGJENT / "
        "SHARE - DET QE DUHET SCREENSHARE ME GA / "
        "👁 - KËRKON MONITORIM NGA DIKUSH TJETËR / "
        "X - MBYLL DETYREN / "
        "M2 - DOREZIM DERI NE PAUZE / "
        "M3 - DOREZIM DERI NE FUND TE DITES / "
        "M2/3 - DOREZIM EDHE NE M2 EDHE M3 / "
        "GENT - PYETJE/SQARIM ME GENTIN / "
        "KA - PYETJE/SQARIM ME KA / GA - PYETJE/SQARIM ME GA / "
        "F - DET FIZIKISHT / BZ1N1"
    )


def _task_cell_style(
    item: dict[str, Any], *, personal: bool, report_date: date | None = None
) -> tuple[str, str]:
    """Done green wins; otherwise GA-personal purple wins over deadline red."""
    deadline = bool(item.get("is_deadline_important") or item.get("isDeadlineImportant"))
    status = _task_status(item)
    if status == "DONE":
        color = STATUS_COLORS["DONE"]
    elif personal and _is_personal_task_for_ga(item):
        color = PERSONAL_GA_COLOR
    elif deadline:
        color = DEADLINE_COLOR
    else:
        color = STATUS_COLORS[status]
    border = f";border:2px solid {EIGHT_AM_BORDER_COLOR}" if _is_eight_am_task(item) else ""
    text_color = ";color:#fff;font-weight:700" if color == DEADLINE_COLOR else ""
    return f"{CELL_STYLE};background-color:{color}{border}{text_color}", color


def _initials(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    if re.sub(r"\s+", " ", cleaned).casefold() == "haris shaqiri":
        return "HSH"
    if re.fullmatch(r"[A-Za-z]{1,4}", cleaned):
        return cleaned.upper()
    parts = re.findall(r"[^\W\d_]+", cleaned, flags=re.UNICODE)
    return "".join(part[0] for part in parts).upper()


def _one_h_slot_from_label(label: str) -> str | None:
    match = re.fullmatch(r"\s*1H\s+(\d{1,2}:\d{2})\s*", label, flags=re.I)
    if not match:
        return None
    slot = match.group(1)
    return slot if slot in VALID_1H_SLOTS else None


def _project_covered_initials(payload: dict[str, Any], target_date: date) -> dict[str, list[str]]:
    from app.services.one_h_project_coverage import is_project_coverage_department

    departments = {str(row.get("id")): row for row in payload.get("departments") or []}
    users = {str(row.get("id")): _initials(str(row.get("full_name") or row.get("username") or row.get("email") or ""))
             for row in payload.get("users") or []}
    covered: dict[str, list[str]] = {slot: [] for slot in (*sorted(VALID_1H_SLOTS), "BLL")}
    for project in (payload.get("items") or {}).get("priority") or []:
        if _item_date(project) != target_date:
            continue
        department = departments.get(str(project.get("department_id")), {})
        if not is_project_coverage_department(department.get("code"), project.get("department_name") or department.get("name")):
            continue
        periods = project.get("projectTaskAssigneesByPeriod") or {}
        for slot in covered:
            period = "AM" if slot in {"10:00", "11:00", "11:50"} else "PM"
            for user_id in periods.get(period) or []:
                initials = users.get(str(user_id))
                if initials and initials not in covered[slot]:
                    covered[slot].append(initials)
    return covered


def _personal_covered_initials(payload: dict[str, Any], target_date: date) -> dict[str, list[str]]:
    from app.services.one_h_project_coverage import project_task_periods

    users = {str(row.get("id")): row for row in payload.get("users") or []}
    users_by_name = {
        str(value).strip().casefold(): user_id
        for user_id, user in users.items()
        for value in (user.get("full_name"), user.get("username"), user.get("email")) if value
    }
    covered: dict[str, list[str]] = {slot: [] for slot in (*sorted(VALID_1H_SLOTS), "BLL")}
    for item in (payload.get("items") or {}).get("personal") or []:
        if _item_date(item) != target_date or item.get("is_personal_task", item.get("isPersonalTask", True)) is False:
            continue
        user_ids = {str(item.get("userId") or item.get("user_id") or "")}
        for name in item.get("assignees") or [item.get("person") or item.get("owner")]:
            user_id = users_by_name.get(str(name or "").strip().casefold())
            if user_id:
                user_ids.add(user_id)
        periods = project_task_periods(item.get("finishPeriod") or item.get("finish_period"))
        for slot in covered:
            period = "AM" if slot in {"10:00", "11:00", "11:50"} else "PM"
            if period not in periods:
                continue
            for user_id in user_ids:
                user = users.get(user_id)
                if not user:
                    continue
                initials = _initials(str(user.get("full_name") or user.get("username") or user.get("email") or ""))
                if initials and initials not in covered[slot]:
                    covered[slot].append(initials)
    return covered


def _missing_task_initials(
    payload: dict[str, Any], target_date: date, *, bucket: str, slots: tuple[str, ...]
) -> dict[str, list[str]]:
    """Return active, present non-admin users missing work in each requested slot."""
    users = [row for row in payload.get("users") or [] if isinstance(row, dict)]
    items = payload.get("items") or {}
    department_codes = {
        str(row.get("id")): str(row.get("code") or row.get("name") or "").strip().upper()
        for row in payload.get("departments") or []
        if isinstance(row, dict) and row.get("id") is not None
    }
    department_aliases = {
        "DEVELOPMENT": "DEV",
        "GRAPHIC DESIGN": "GD",
        "GDS": "GD",
        "PRODUCT CONTENT": "PCM",
        "PROJECT CONTENT MANAGER": "PCM",
    }
    department_ranks = {"DEV": 0, "GD": 1, "PCM": 2}

    def identity_values(row: dict[str, Any]) -> list[str]:
        email_name = str(row.get("email") or "").split("@", 1)[0]
        return [
            str(row.get("full_name") or "").strip(),
            re.sub(r"[._-]+", " ", str(row.get("username") or "")).strip(),
            re.sub(r"[._-]+", " ", email_name).strip(),
        ]

    eligible: list[tuple[int, str, int, int, str, str, str]] = []
    user_id_by_name: dict[str, str] = {}
    for row in users:
        user_id = str(row.get("id") or "").strip()
        if not user_id or row.get("is_active") is False:
            continue
        if str(row.get("role") or "").strip().upper() == "ADMIN":
            continue
        identities = [value for value in identity_values(row) if value]
        if any(_initials(value) in EXCLUDED_1H_MISSING_INITIALS for value in identities):
            continue
        label = str(row.get("full_name") or row.get("username") or row.get("email") or "").strip()
        user_initials = _initials(label)
        if not user_initials:
            continue
        department_code = department_codes.get(str(row.get("department_id") or ""), "-")
        department_code = department_aliases.get(department_code, department_code or "-")
        order = row.get("weekly_planner_sort_order")
        eligible.append((
            department_ranks.get(department_code, len(department_ranks)),
            department_code.casefold(),
            1 if order is None else 0,
            int(order or 0),
            label.casefold(),
            user_id,
            user_initials,
        ))
        for value in identity_values(row):
            if value:
                user_id_by_name[value.casefold()] = user_id

    all_unavailable, unavailable_ids, unavailable_names = _full_day_unavailable(items, target_date)
    if all_unavailable:
        return {slot: [] for slot in slots}
    unavailable_ids.update(
        user_id_by_name[name] for name in unavailable_names if name in user_id_by_name
    )

    users_by_slot = {slot: set() for slot in slots}
    for item in items.get(bucket) or []:
        if not isinstance(item, dict) or _item_date(item) != target_date:
            continue
        if _task_status(item) == "WAITING_CLIENT":
            continue
        slot = _slot(item) if bucket == "oneH" else "BLL"
        if slot not in users_by_slot:
            continue
        user_id = item.get("userId") or item.get("user_id")
        if user_id:
            users_by_slot[slot].add(str(user_id))
        names = item.get("assignees") or [item.get("person") or item.get("owner")]
        for name in names:
            resolved_id = user_id_by_name.get(str(name or "").strip().casefold())
            if resolved_id:
                users_by_slot[slot].add(resolved_id)

    result: dict[str, list[str]] = {}
    for slot in slots:
        seen: set[str] = set()
        result[slot] = []
        for *_, user_id, user_initials in sorted(eligible):
            if user_id in unavailable_ids or user_id in users_by_slot[slot] or user_initials in seen:
                continue
            seen.add(user_initials)
            result[slot].append(user_initials)
    return result


def _missing_one_h_initials(payload: dict[str, Any], target_date: date) -> dict[str, list[str]]:
    return _missing_task_initials(
        payload, target_date, bucket="oneH", slots=tuple(sorted(VALID_1H_SLOTS))
    )


def _missing_blocked_initials(payload: dict[str, Any], target_date: date) -> list[str]:
    return _missing_task_initials(payload, target_date, bucket="blocked", slots=("BLL",))["BLL"]


def _comment_user_initials(payload: dict[str, Any]) -> list[str]:
    """Fixed report users followed by PCM users in Weekly Planner order."""
    departments = {
        str(row.get("id")): str(row.get("code") or row.get("name") or "").strip().upper()
        for row in (payload.get("departments") or [])
        if isinstance(row, dict) and row.get("id") is not None
    }
    pcm_aliases = {"PCM", "PRODUCT CONTENT", "PROJECT CONTENT", "PROJECT CONTENT MANAGER"}
    pcm_users: list[tuple[int, int, str, str]] = []
    for row in payload.get("users") or []:
        if not isinstance(row, dict) or row.get("is_active") is False:
            continue
        if departments.get(str(row.get("department_id"))) not in pcm_aliases:
            continue
        label = str(row.get("full_name") or row.get("username") or "").strip()
        initials = _initials(label)
        if not initials:
            continue
        order = row.get("weekly_planner_sort_order")
        pcm_users.append((1 if order is None else 0, int(order or 0), label.casefold(), initials))

    result = list(COMMENT_FIXED_INITIALS)
    for *_, initials in sorted(pcm_users):
        if initials not in result:
            result.append(initials)
    return result


def _comment_department_rows(initials: list[str]) -> list[list[tuple[str, list[str]]]]:
    values = initials or list(COMMENT_FIXED_INITIALS)
    dev = [value for value in COMMENT_DEV_INITIALS if value in values]
    gd = [value for value in COMMENT_GD_INITIALS if value in values]
    pcm = [value for value in values if value not in COMMENT_FIXED_INITIALS]
    return [[("DEV", dev)], [("PX", [*gd, *pcm])]]


def _comment_write_in_lines(initials: list[str]) -> list[str]:
    return [
        "    ".join(
            f"{department}: "
            + ",    ".join(f"{value}: {COMMENT_WRITE_IN_LINE}" for value in members)
            for department, members in row
        )
        for row in _comment_department_rows(initials)
    ]


def _comments_table_html(initials: list[str]) -> str:
    """Render staff comment fields in two department-grouped rows."""
    rows: list[str] = []
    for department_row in _comment_department_rows(initials):
        member_count = sum(len(members) for _, members in department_row)
        width_unit = 100 / max(member_count + len(department_row) * 0.5, 1)
        entries = ""
        for department, members in department_row:
            entries += (
                '<td data-comment-department="{department}" width="{width:.2f}%" '
                'style="width:{width:.2f}%;padding:0 6px 8px 0;white-space:nowrap;vertical-align:bottom;">'
                '<strong>{department}:</strong></td>'
            ).format(department=html.escape(department), width=width_unit * 0.5)
            entries += "".join(
                '<td data-user-comment="{initials}" width="{width:.2f}%" valign="bottom" '
                'style="width:{width:.2f}%;padding:0 14px 8px 0;vertical-align:bottom;">'
                '<table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" '
                'style="width:100%;border-collapse:collapse;font-family:Arial,sans-serif;font-size:13px;">'
                '<tr><td width="1%" style="width:1%;padding:0 5px 1px 0;white-space:nowrap;">'
                '<strong>{initials}:</strong></td><td style="width:99%;border-bottom:1px solid #111827;">&nbsp;</td>'
                '</tr></table></td>'.format(initials=html.escape(value), width=width_unit)
                for value in members
            )
        rows.append(
            '<table data-user-comment-line="true" role="presentation" width="100%" border="0" '
            'cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;table-layout:fixed;">'
            f'<tr>{entries}</tr></table>'
        )
    return (
        '<div data-user-comments-lines="true" style="margin-top:18px;">'
        '<div style="font-family:Arial,sans-serif;font-size:16px;font-weight:800;margin:0 0 6px;">'
        "KOMENTE PER STAF</div>"
        f"{''.join(rows)}</div>"
    )


def _assignees(item: dict[str, Any]) -> list[str]:
    raw = item.get("assignees")
    if not isinstance(raw, list) or not raw:
        raw = str(item.get("person") or item.get("owner") or "").split(",")
    result: list[str] = []
    for value in raw:
        label = _initials(str(value or ""))
        if label and label not in result:
            result.append(label)
    return result


def _is_system_task_item(item: dict[str, Any]) -> bool:
    return bool(
        item.get("is_system_task")
        or item.get("isSystemTask")
        or item.get("system_template_origin_id")
        or item.get("systemTemplateOriginId")
        or item.get("system_task_slot_id")
        or item.get("systemTaskSlotId")
    )


def _task_title(item: dict[str, Any], *, personal: bool) -> str:
    title = _report_text(_first_line(item.get("title")))
    if personal:
        return normalize_email_task_title(title, is_system_task=_is_system_task_item(item))
    title = re.sub(r"^[A-Z]{1,4}(?:/[A-Z]{1,4})*:\s*", "", title)
    title = normalize_email_task_title(title, is_system_task=_is_system_task_item(item))
    owners = _assignees(item)
    return f"{'/'.join(owners)}: {title}" if owners else title


def _task_title_html(value: str, *, red_background: bool) -> str:
    """Escape a task title and make standalone WFC tokens visually distinct."""
    parts: list[str] = []
    cursor = 0
    for match in WFC_TOKEN_RE.finditer(value):
        parts.append(html.escape(value[cursor:match.start()]))
        style = "color:#DC2626;font-weight:800;"
        if red_background:
            style += "background-color:#FFFFFF;border-radius:2px;padding:0 2px;"
        parts.append(
            f'<span data-task-token="wfc" style="{style}">{html.escape(match.group(0))}</span>'
        )
        cursor = match.end()
    parts.append(html.escape(value[cursor:]))
    return "".join(parts)


def _excel_task_title(
    value: str, *, red_background: bool, marker_label: str = "", marker_by_ga: bool = False
) -> str | CellRichText:
    """Color WFC and the task symbol independently in Excel rich text."""
    marker_token = (marker_label if marker_by_ga else f"[{marker_label}]") if marker_label else ""
    marker_re = re.compile(re.escape(marker_token)) if marker_token else None
    token_re = re.compile(
        f"(?:{WFC_TOKEN_RE.pattern})|(?:{marker_re.pattern})"
        if marker_re else WFC_TOKEN_RE.pattern,
        re.I,
    )
    if token_re.search(value) is None:
        return value
    default_font = InlineFont(color="FFFFFFFF" if red_background else "FF000000")
    wfc_font = InlineFont(color="FFFFFF00" if red_background else "FFDC2626", b=True)
    marker_font = InlineFont(color="FFDC2626", b=True)
    parts: list[str | TextBlock] = []
    cursor = 0
    for match in token_re.finditer(value):
        if match.start() > cursor:
            parts.append(TextBlock(default_font, value[cursor:match.start()]))
        font = marker_font if marker_token and match.group(0).casefold() == marker_token.casefold() else wfc_font
        parts.append(TextBlock(font, match.group(0)))
        cursor = match.end()
    if cursor < len(value):
        parts.append(TextBlock(default_font, value[cursor:]))
    return CellRichText(parts)


def _excel_meeting_user_initials(
    item: dict[str, Any], *, default_color: str = "000000"
) -> str | CellRichText:
    users = _meeting_users(item)
    if not users:
        return "-"
    unavailable = {str(value) for value in item.get("_unavailableUserInitials") or []}
    if not unavailable:
        return "/".join(label for label, _ in users)

    parts: list[str | TextBlock] = []
    for index, (label, _) in enumerate(users):
        if index:
            parts.append(TextBlock(InlineFont(b=True, color=default_color), "/"))
        color = DEADLINE_COLOR.removeprefix("#") if label in unavailable else default_color
        parts.append(TextBlock(InlineFont(b=True, color=color), label))
    return CellRichText(parts)


def _is_eight_am_task(item: dict[str, Any]) -> bool:
    title = " ".join(str(item.get(key) or "") for key in ("title", "task_title"))
    if title_has_eight_am_indicator(title, is_system_task=_is_system_task_item(item)):
        return True
    raw_due_date = item.get("due_date") or item.get("dueDate")
    if isinstance(raw_due_date, datetime):
        return raw_due_date.hour == 8 and raw_due_date.minute == 0
    match = re.search(r"T08:00(?::00)?", str(raw_due_date or ""))
    return bool(match)


def _task_due_day(item: dict[str, Any]) -> date | None:
    raw = (
        item.get("due_date")
        or item.get("dueDate")
        or item.get("deadline_date")
        or item.get("deadlineDate")
    )
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw or "")[:10])
    except ValueError:
        return None


def _task_start_day(item: dict[str, Any]) -> date | None:
    raw = (
        item.get("start_date")
        or item.get("startDate")
        or item.get("date")
    )
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw or "")[:10])
    except ValueError:
        return None


def _task_created_day(item: dict[str, Any]) -> date | None:
    raw = item.get("created_at") or item.get("createdAt")
    if isinstance(raw, datetime):
        created_at = raw
    elif isinstance(raw, date):
        return raw
    else:
        try:
            created_at = datetime.fromisoformat(str(raw or "").replace("Z", "+00:00"))
        except ValueError:
            return None
    if created_at.tzinfo is not None:
        created_at = created_at.astimezone(ZoneInfo(settings.APP_TIMEZONE))
    return created_at.date()


def _task_badges_html(item: dict[str, Any], report_date: date | None) -> tuple[str, str]:
    top_badges: list[str] = []
    badge_base = (
        "display:inline-block;float:right;margin:0 0 3px 4px;padding:3px 7px;border-radius:999px;"
        "font-family:Arial,sans-serif;font-size:10px;font-weight:800;line-height:1;white-space:nowrap;"
    )
    period = _task_period_label(item)
    period_style = (
        f"{badge_base}background-color:#E0F2FE;border:1px solid #BAE6FD;color:#0369A1;"
    )
    top_badges.append(
        f'<span data-task-badge="finish-period" style="{period_style}">{period}</span>'
    )
    if _task_status(item) == "WAITING_CONFIRMATION":
        wfc_style = (
            f"{badge_base}background-color:#FFEDD5;border:1px solid #FB923C;color:#C2410C;"
        )
        top_badges.append(
            f'<span data-task-badge="wfc" style="{wfc_style}">WFC</span>'
        )
    marker = _task_marker_label(item)
    if marker:
        marker_style = (
            f"{badge_base}padding:3px 8px;background-color:#EFF6FF;border:1px solid #93C5FD;"
            "color:#DC2626;font-size:16px;font-weight:900;text-shadow:0 0 0 currentColor;"
        )
        top_badges.append(
            f'<span data-task-badge="one-h-marker" style="{marker_style}">{marker}</span>'
        )
    if _is_eight_am_task(item):
        eight_am_style = (
            f"{badge_base}background-color:#DC2626;border:1px solid #B91C1C;color:#FFFFFF;"
        )
        top_badges.append(
            f'<span data-task-badge="08:00" style="{eight_am_style}">08:00</span>'
        )
    date_badge_base = (
        "display:inline-block;box-sizing:border-box;height:19px;padding:2px 5px;"
        "border:1px solid #93C5FD;border-radius:3px;vertical-align:bottom;"
        "background-color:#EFF6FF;color:#1D4ED8;font-family:Arial,sans-serif;"
        "font-size:10px;font-weight:900;line-height:13px;white-space:nowrap;"
    )
    start_day = _task_start_day(item)
    due_day = _task_due_day(item)
    start_today = (
        bool(item.get("start_date") or item.get("startDate"))
        and report_date is not None
        and _task_created_day(item) == report_date
        and start_day == report_date
        and due_day == report_date
    )
    start_today_badge = (
        '<span data-task-badge="start-today" '
        'style="display:block;width:max-content;margin:0 0 2px 0;padding:2px 5px;'
        'border:1px solid #60A5FA;border-radius:999px;background-color:#DBEAFE;'
        'color:#1D4ED8;font-family:Arial,sans-serif;font-size:9px;font-weight:800;'
        'line-height:1;white-space:nowrap;">START SOT</span>'
        if start_today else ""
    )
    due_today = report_date is not None and due_day == report_date
    due_label = "SOT" if due_today else (due_day.strftime("%d.%m.%Y") if due_day else "")
    start_badge = (
            f'<span data-task-badge="start-date" style="{date_badge_base}">'
            f'{start_day:%d.%m.%Y}</span>'
        if start_day else ""
    )
    due_badge_style = (
        "height:26px;border:1px solid #991B1B;border-radius:4px;background-color:#DC2626;"
        "color:#FFFFFF;padding:3px 9px;font-size:14px;line-height:18px;font-weight:900;"
        "box-shadow:0 1px 3px rgba(127,29,29,0.45);"
        if due_today else
        "border:3px solid #B91C1C;padding:0 3px;"
    )
    due_badge = (
            f'<span data-task-badge="due-date" data-badge-position="bottom-right" '
            f'data-due-today="{str(due_today).lower()}" '
            f'style="{date_badge_base}{due_badge_style}">{due_label}</span>'
        if due_day else ""
    )
    date_badges = ""
    if start_badge or due_badge:
        date_badges = (
            '<table role="presentation" width="100%" border="0" cellpadding="0" cellspacing="0" '
            'style="width:100%;border-collapse:collapse;table-layout:fixed;"><tr>'
            f'<td valign="bottom" align="left" style="padding:0;text-align:left;vertical-align:bottom;white-space:nowrap;">{start_today_badge}{start_badge}</td>'
            f'<td height="19" valign="bottom" align="right" style="height:19px;padding:0;text-align:right;vertical-align:bottom;white-space:nowrap;">{due_badge}</td>'
            '</tr></table>'
        )
    return "".join(top_badges), date_badges


def _personal_task_group(item: dict[str, Any]) -> str:
    """Assign each personal task to exactly one ownership row."""
    title = _report_text(_first_line(item.get("title")))
    return personal_task_owner(title)


def _confirmation_owner(item: dict[str, Any]) -> str | None:
    value = str(item.get("confirmationOwner") or item.get("confirmation_owner") or "").strip().upper()
    if value in {"GENT", "GENTI", "GT"}:
        return "GENT"
    return value if value == "KA" else None


def _is_appended_wfc(item: dict[str, Any]) -> bool:
    return (
        item.get("isPersonalTask", item.get("is_personal_task")) is False
        and _task_status(item) == "WAITING_CONFIRMATION"
        and _confirmation_owner(item) in {"KA", "GENT"}
    )


def _is_routed_wfc(item: dict[str, Any]) -> bool:
    return _task_status(item) == "WAITING_CONFIRMATION" and _confirmation_owner(item) in {"KA", "GENT"}


def _is_personal_task_for_ga(item: dict[str, Any]) -> bool:
    """Keep the existing GA-specific card color after splitting the P rows."""
    return _personal_task_group(item) == "GA"


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for item in items:
        # Development and converted-note multi-assignee work is stored as one
        # independent task row per assignee.  Those rows intentionally share
        # their title, date and report metadata, so include their stable task
        # identity (or assignees for legacy payloads) in the duplicate key.
        # The same task repeated across Common View buckets still collapses.
        identity = str(
            item.get("task_id") or item.get("taskId") or item.get("id") or ""
        ).strip()
        if not identity:
            identity = "/".join(_assignees(item))
        key = (
            identity,
            _first_line(item.get("title")).casefold(),
            str(item.get("date") or ""),
            _slot(item),
            str(item.get("finishPeriod") or item.get("finish_period") or "").upper(),
            str(item.get("oneHMarker") or item.get("one_h_marker") or "").upper(),
        )
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _full_day_unavailable(
    items: dict[str, Any], target_date: date,
) -> tuple[bool, set[str], set[str]]:
    """Use the Common View workday (08:00-16:00) for full-day absences."""
    target_iso = target_date.isoformat()
    user_ids: set[str] = set()
    names: set[str] = set()
    all_users = False
    for bucket in ("absent", "leave"):
        for row in items.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            if bucket == "leave":
                start = str(row.get("startDate") or row.get("start_date") or "")[:10]
                end = str(row.get("endDate") or row.get("end_date") or start)[:10]
                if not start or not start <= target_iso <= end:
                    continue
            elif str(row.get("date") or "")[:10] != target_iso:
                continue
            full_day = row.get("fullDay", row.get("full_day"))
            start_minutes = _clock_minutes(row.get("from"))
            end_minutes = _clock_minutes(row.get("to"))
            if full_day is not True and not (
                (start_minutes is None and end_minutes is None and full_day is not False)
                or (start_minutes is not None and end_minutes is not None
                    and start_minutes <= 8 * 60 and end_minutes >= 16 * 60)
            ):
                continue
            all_users = all_users or bool(row.get("isAllUsers") or row.get("is_all_users"))
            user_id = row.get("userId") or row.get("user_id")
            if user_id:
                user_ids.add(str(user_id))
            name = str(row.get("person") or row.get("owner") or "").strip().casefold()
            if name:
                names.add(name)
    return all_users, user_ids, names


def _task_rows(
    items: dict[str, Any], target_date: date, *, include_completed_today: bool = False,
    users: list[dict[str, Any]] | None = None,
) -> list[tuple[str, list[dict[str, Any]], bool]]:
    all_unavailable, unavailable_ids, unavailable_names = _full_day_unavailable(items, target_date)
    for user in users or []:
        if str(user.get("id")) in unavailable_ids:
            unavailable_names.update(
                str(user[key]).strip().casefold()
                for key in ("full_name", "username", "email") if user.get(key)
            )

    def available(item: dict[str, Any]) -> bool:
        if all_unavailable:
            return False
        user_id = item.get("userId") or item.get("user_id")
        assignees = item.get("assignees") or []
        if assignees:
            if len(assignees) == 1 and str(user_id) in unavailable_ids:
                return False
            # Shared work stays visible while at least one assignee is present.
            return any(str(name).strip().casefold() not in unavailable_names for name in assignees)
        name = str(item.get("person") or item.get("owner") or "").strip().casefold()
        return str(user_id) not in unavailable_ids and name not in unavailable_names

    by_bucket = {
        name: [item for item in values if isinstance(item, dict) and _item_date(item) == target_date and available(item)]
        for name, values in items.items()
        if isinstance(values, list)
    }
    rows: list[tuple[str, list[dict[str, Any]], bool]] = []
    for bucket, label, requested_value in TASK_ROWS:
        if bucket == "waitingClient":
            values = [
                item
                for source_bucket, bucket_items in by_bucket.items()
                if source_bucket in {"oneH", "blocked", "important", "r1", "personal"}
                for item in bucket_items
                if _task_status(item) == "WAITING_CLIENT"
            ]
        else:
            values = [
                item
                for item in by_bucket.get(bucket, [])
                if _task_status(item) != "WAITING_CLIENT"
                and (bucket == "personal" or not _is_routed_wfc(item))
            ]
        if bucket == "oneH":
            values = [item for item in values if _slot(item) == requested_value]
        elif bucket == "personal":
            regular_personal = [
                item for item in values
                if not _is_appended_wfc(item) and _personal_task_group(item) == requested_value
            ]
            waiting_confirmation = [
                item for item in values
                if _is_appended_wfc(item) and _confirmation_owner(item) == requested_value
            ]
            values = [*regular_personal, *waiting_confirmation]
        # Today's report also shows tasks completed on its report date.
        # Tomorrow's report continues to show only unfinished work.
        values = [
            item for item in values
            if _task_status(item) != "DONE"
            or (include_completed_today and _completed_on_day(item, target_date))
        ]
        values = _dedupe(values)
        values.sort(
            key=lambda item: (
                _task_status(item) == "DONE",
                _is_appended_wfc(item) if bucket == "personal" else False,
                common_view_item_sort_key(item),
            )
        )
        rows.append((label, values, bucket == "personal"))
    return rows


def _meeting_time_sort_key(item: dict[str, Any]) -> tuple[int, int, int, str]:
    raw_time = str(item.get("time") or "").strip()
    match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", raw_time)
    if match:
        return (
            0,
            int(match.group(1)),
            int(match.group(2)),
            _first_line(item.get("title")).casefold(),
        )
    return (1, 24, 60, f"{raw_time.casefold()}|{_first_line(item.get('title')).casefold()}")


def _is_calendar_meeting(item: dict[str, Any], *, meeting_type: str) -> bool:
    if meeting_type == "internal" and (
        item.get("pairedExternalMeetingId")
        or item.get("paired_external_meeting_id")
        or item.get("preExternalMeetingId")
        or item.get("pre_external_meeting_id")
    ):
        return bool(
            item.get("linkedExternalCalendarImported")
            or item.get("linked_external_calendar_imported")
        )
    return bool(
        item.get("calendarImported")
        or item.get("calendar_imported")
        or item.get("microsoftEventId")
        or item.get("microsoft_event_id")
    )


def _is_faded_calendar_internal(item: dict[str, Any], *, meeting_type: str) -> bool:
    return meeting_type == "internal" and _is_calendar_meeting(
        item, meeting_type=meeting_type
    )


def _meeting_user_initials(item: dict[str, Any]) -> str:
    return "/".join(label for label, _ in _meeting_users(item)) or "-"


def _meeting_users(item: dict[str, Any]) -> list[tuple[str, str | None]]:
    raw = item.get("assignees") or item.get("participantNames") or item.get("participant_names") or []
    raw_ids = (
        item.get("assigneeUserIds")
        or item.get("assignee_user_ids")
        or item.get("participantUserIds")
        or item.get("participant_user_ids")
        or []
    )
    if isinstance(raw, str):
        raw = raw.split(",")
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    if not isinstance(raw, (list, tuple, set)):
        return []
    ids = list(raw_ids) if isinstance(raw_ids, (list, tuple, set)) else []

    result: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for index, value in enumerate(raw):
        if isinstance(value, dict):
            user_id = value.get("id") or value.get("userId") or value.get("user_id")
            value = value.get("full_name") or value.get("username") or value.get("email") or ""
        else:
            user_id = ids[index] if index < len(ids) else None
        label = _initials(str(value or ""))
        if label and label not in seen:
            seen.add(label)
            result.append((label, str(user_id) if user_id else None))
    return result


def _clock_minutes(value: Any) -> int | None:
    match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", str(value or ""))
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    return hour * 60 + minute if hour < 24 and minute < 60 else None


def _meeting_unavailable_initials(
    item: dict[str, Any], items: dict[str, Any], target_date: date
) -> set[str]:
    users = _meeting_users(item)
    if not users:
        return set()
    meeting_minutes = _clock_minutes(item.get("time"))
    target_iso = target_date.isoformat()

    def row_matches_user(row: dict[str, Any], label: str, user_id: str | None) -> bool:
        row_user_id = row.get("userId") or row.get("user_id")
        if user_id and row_user_id and str(user_id) == str(row_user_id):
            return True
        return _initials(str(row.get("person") or "")) == label

    def range_covers(
        start: Any, end: Any, *, default_start: str, default_end: str
    ) -> bool:
        if meeting_minutes is None:
            return True
        start_minutes = _clock_minutes(start)
        end_minutes = _clock_minutes(end)
        if start_minutes is None:
            start_minutes = _clock_minutes(default_start)
        if end_minutes is None:
            end_minutes = _clock_minutes(default_end)
        return bool(
            start_minutes is not None
            and end_minutes is not None
            and start_minutes <= meeting_minutes <= end_minutes
        )

    if any(
        isinstance(row, dict) and str(row.get("date") or "")[:10] == target_iso
        for row in items.get("externalHoliday") or []
    ):
        return {label for label, _ in users}

    unavailable: set[str] = set()
    for label, user_id in users:
        for row in items.get("leave") or []:
            if not isinstance(row, dict):
                continue
            start_date = str(row.get("startDate") or row.get("start_date") or "")[:10]
            end_date = str(row.get("endDate") or row.get("end_date") or start_date)[:10]
            if not start_date or not (start_date <= target_iso <= end_date):
                continue
            if not (row.get("isAllUsers") or row.get("is_all_users")) and not row_matches_user(
                row, label, user_id
            ):
                continue
            full_day = row.get("fullDay") if "fullDay" in row else row.get("full_day")
            if full_day is not False or range_covers(
                row.get("from"), row.get("to"), default_start="00:00", default_end="23:59"
            ):
                unavailable.add(label)
                break
        if label in unavailable:
            continue
        for row in items.get("absent") or []:
            if not isinstance(row, dict) or str(row.get("date") or "")[:10] != target_iso:
                continue
            if row_matches_user(row, label, user_id) and range_covers(
                row.get("from"), row.get("to"), default_start="08:00", default_end="23:00"
            ):
                unavailable.add(label)
                break
        if label in unavailable:
            continue
        for row in items.get("late") or []:
            if not isinstance(row, dict) or str(row.get("date") or "")[:10] != target_iso:
                continue
            if not row_matches_user(row, label, user_id):
                continue
            start_minutes = _clock_minutes(row.get("start"))
            until_minutes = _clock_minutes(row.get("until"))
            if start_minutes is None:
                start_minutes = _clock_minutes("08:00")
            if until_minutes is None:
                until_minutes = _clock_minutes("09:00")
            if meeting_minutes is None or (
                start_minutes is not None
                and until_minutes is not None
                and start_minutes <= meeting_minutes < until_minutes
            ):
                unavailable.add(label)
                break
    return unavailable


def _is_manual_internal_meeting(item: dict[str, Any], *, meeting_type: str) -> bool:
    return meeting_type == "internal" and not any(
        item.get(field)
        for field in (
            "pairedExternalMeetingId",
            "paired_external_meeting_id",
            "preExternalMeetingId",
            "pre_external_meeting_id",
        )
    )


def _meeting_title(item: dict[str, Any]) -> str:
    return _report_text(_first_line(item.get("title")))


def _meeting_relation(item: dict[str, Any]) -> str:
    if item.get("preExternalMeetingId") or item.get("pre_external_meeting_id"):
        return "PARA"
    if item.get("pairedExternalMeetingId") or item.get("paired_external_meeting_id"):
        return "PAS"
    return ""


def _meeting_time_display(item: dict[str, Any], *, meeting_type: str) -> str:
    value = str(item.get("time") or "-").strip() or "-"
    if _is_calendar_meeting(item, meeting_type=meeting_type):
        return f"{value} CAL"
    if _is_manual_internal_meeting(item, meeting_type=meeting_type):
        return f"{value} MANUAL"
    return value


def _meeting_rows(items: dict[str, Any], target_date: date) -> list[tuple[str, list[dict[str, Any]]]]:
    rows: list[tuple[str, list[dict[str, Any]]]] = []
    for bucket, label in MEETING_ROWS:
        values = []
        for item in items.get(bucket, []):
            if not isinstance(item, dict) or _item_date(item) != target_date:
                continue
            report_item = dict(item)
            report_item["_unavailableUserInitials"] = sorted(
                _meeting_unavailable_initials(item, items, target_date)
            )
            values.append(report_item)
        values.sort(key=_meeting_time_sort_key)
        rows.append((label, values))
    return rows


def _flatten_meeting_rows(
    rows: list[tuple[str, list[dict[str, Any]], bool]],
) -> list[tuple[str, dict[str, Any]]]:
    return [
        (label, item)
        for label, items, *_ in rows
        for item in sorted(items, key=_meeting_time_sort_key)
    ]


def _is_non_routine_meeting(item: dict[str, Any]) -> bool:
    recurrence = str(item.get("recurrence_type") or item.get("recurrenceType") or "").strip().lower()
    return recurrence not in {"daily", "weekly"}


def _extra_question_parts(checklist_date):
    board, staff = _one_h_checklists_for_day(checklist_date)
    return question_parts(_day_specific_question_label(checklist_date), [
        [f"{_checklist_question_number(checklist_date, index, question)} {question}"
         + (f" ({description})" if description else "")
         for index, (question, description) in enumerate(questions, 1)]
        for questions in (staff[len(ONE_H_STAFF_CHECKLIST):], board[len(ONE_H_BOARD_CHECKLIST):])
    ])


def _one_h_checklists_html(report_day: date | None = None) -> str:
    """The two preparation checklists shown above every 1H Shtypi task grid."""
    board_questions, staff_questions = _one_h_checklists_for_day(report_day)

    def question_text(questions: tuple[tuple[str, str], ...], *, extra: bool) -> str:
        if extra:
            return ' <strong style="font-size:20px;font-weight:900;line-height:1;vertical-align:-2px;padding:0 5px;"> / </strong> '.join(
                '<span data-extra-checklist-question="true" style="display:inline;">'
                f'<strong>{html.escape(_checklist_question_number(report_day, index, question))} {html.escape(question)}</strong>'
                + (f' <span style="color:#dc2626;font-weight:400;">({html.escape(description)})</span>' if description else "")
                + '</span>'
                for index, (question, description) in enumerate(questions, 1)
            )
        separators = (
            '<span style="font-size:20px;font-weight:900;color:#111827;line-height:12px;"> / </span>'
        )
        return separators.join(
            f'<strong>{index}. {html.escape(question)}</strong>'
            + (f' <span style="color:#475569;">({html.escape(description)})</span>' if description else "")
            for index, (question, description) in enumerate(questions, 1)
        )

    def checklist(
        title: str, questions: tuple[tuple[str, str], ...], *, board: bool = False
    ) -> str:
        board_marker = ' data-board-checklist-columns="true"' if board else ""
        content_rows = [questions]
        if board:
            content_rows = [ONE_H_BOARD_FOLLOW_UP_CHECKLIST, ONE_H_BOARD_PRIMARY_CHECKLIST]
        rendered_rows = "".join(
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"'
            + (f' data-board-checklist-section="{"follow-up" if index == 0 else "primary"}"' if board else "")
            + f' style="width:100%;border-collapse:collapse;{("margin:0 0 6px;" if board and index == 0 else "")}">'
            '<tr><td style="border:1px solid #64748b;padding:8px 10px;font-family:Arial,sans-serif;'
            f'font-size:12px;line-height:1.45;">{question_text(row_questions, extra=False)}</td></tr></table>'
            for index, row_questions in enumerate(content_rows)
        )
        return (
            f'<div data-compact-checklist-row="true"{board_marker}>'
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
            'style="width:100%;border-collapse:collapse;">'
            '<tr><th style="background-color:#eef2ff;border-left:5px solid #2563eb;padding:10px 12px;'
            f'font-family:Arial,sans-serif;font-size:14px;text-align:left;">{html.escape(title)}</th></tr></table>'
            f'{rendered_rows}</div>'
        )

    day_label = _day_specific_question_label(report_day)
    staff_extra = staff_questions[len(ONE_H_STAFF_CHECKLIST):]
    board_extra = board_questions[len(ONE_H_BOARD_CHECKLIST):]
    extra_groups = [questions for questions in (staff_extra, board_extra) if questions]
    extra_content = ' <strong style="font-size:20px;font-weight:900;line-height:1;vertical-align:-2px;padding:0 5px;"> / </strong> '.join(
        question_text(questions, extra=True) for questions in extra_groups
    )
    weekday_block = (
        '<div data-day-specific-question-label="true" style="font-family:Arial,sans-serif;'
        'font-size:13px;line-height:1.45;color:#b91c1c;margin:0 0 10px;padding:6px 10px;'
        'background:#fff7f7;border-left:6px solid #dc2626;">'
        f'<strong style="margin-right:12px;font-size:15px;font-weight:900;">{html.escape(day_label)}</strong>'
        + (f'<span data-day-specific-checklist-columns="true">{extra_content}</span>' if extra_content else "")
        + '</div>'
    )
    return (
        weekday_block
        +
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" '
        'data-one-h-checklist-columns="true" style="width:100%;border-collapse:collapse;margin:0 0 14px;">'
        '<tr>'
        '<td width="50%" valign="top" style="width:50%;padding:0 6px 0 0;vertical-align:top;">'
        f"{checklist('STAFF - HAPAT PER 1H', staff_questions[:len(ONE_H_STAFF_CHECKLIST)])}"
        '</td>'
        '<td width="50%" valign="top" style="width:50%;padding:0 0 0 6px;vertical-align:top;">'
        f"{checklist('PYETJET PER 1H - BORD', board_questions[:len(ONE_H_BOARD_CHECKLIST)], board=True)}"
        '</td>'
        '</tr></table>'
    )


def _task_marker_legend_html() -> str:
    """Explain the task markers wherever the generated 1H report is rendered."""
    items = (
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
    separator = (
        '<span aria-hidden="true" style="display:inline-block;margin:0 14px;'
        'color:#0F2A5F;font-size:21px;font-weight:900;line-height:1;vertical-align:middle;">/</span>'
    )
    content = separator.join(
        '<span style="display:inline-block;margin:2px 16px 2px 0;white-space:nowrap;">'
        f'<strong style="color:#DC2626;font-size:{"12px" if symbol in {"KA", "GA", "GENT", "BZ1N1", "M2", "M3", "M2/3"} else "17px"};font-weight:900;">{symbol}</strong>'
        f'{f" - {html.escape(description)}" if description else ""}</span>'
        for symbol, description in items
    )
    return (
        '<div data-task-marker-legend="true" style="margin:0 0 10px;padding:6px 9px;'
        'border:1px solid #93C5FD;border-radius:5px;background:#EFF6FF;color:#0F2A5F;'
        'font-family:Arial,sans-serif;font-size:11px;font-weight:700;line-height:1.3;">'
        '<strong style="margin-right:12px;">LEGJENDA:</strong>'
        f'{content}</div>'
    )


def _html_table(
    rows: list[tuple[str, list[dict[str, Any]], bool]], *, meeting: bool = False,
    report_date: date | None = None, missing_one_h_by_slot: dict[str, list[str]] | None = None,
    missing_blocked_initials: list[str] | None = None,
    missing_blocked_with_one_h_at_16_initials: list[str] | None = None,
    missing_one_h_at_16_with_blocked_initials: list[str] | None = None,
    project_covered_by_slot: dict[str, list[str]] | None = None,
    personal_covered_by_slot: dict[str, list[str]] | None = None,
) -> str:
    header = "MEETING" if meeting else "TASK"
    label_header = "LLOJI" if meeting else "LLOJI DHE SLOTI"
    body: list[str] = []

    def row_label_html(label: str, personal: bool) -> str:
        escaped_lines = [html.escape(line) for line in label.splitlines()]
        if personal and len(escaped_lines) > 1:
            return (
                f'{escaped_lines[0]}<br><span style="{PERSONAL_TIME_STYLE}">'
                f'{" ".join(escaped_lines[1:])}</span>'
            )
        label_html = "<br>".join(escaped_lines)
        if label.splitlines()[0].strip().upper() == "BLL":
            with_one_h_at_16 = set(missing_blocked_with_one_h_at_16_initials or [])
            with_project = set((project_covered_by_slot or {}).get("BLL", []))
            with_personal = set((personal_covered_by_slot or {}).get("BLL", []))
            with_one_h_at_16.update(with_project)
            with_one_h_at_16.update(with_personal)
            red_initials = [value for value in missing_blocked_initials or [] if value not in with_one_h_at_16]
            green_initials = [value for value in missing_blocked_initials or [] if value in with_one_h_at_16]
            for initials, attribute, color in (
                (red_initials, "data-missing-blocked-users", "#DC2626"),
                ([v for v in green_initials if v not in with_project and v not in with_personal], "data-missing-blocked-with-one-h-at-16-users", "#15803D"),
                ([v for v in green_initials if v in with_project], "data-missing-blocked-with-project-users", "#15803D"),
                ([v for v in green_initials if v in with_personal and v not in with_project], "data-missing-blocked-with-personal-users", "#15803D"),
            ):
                if not initials:
                    continue
                missing_html = " &bull; ".join(html.escape(value) for value in initials)
                label_html += (
                    f'<span {attribute}="true" '
                    f'style="display:block;margin-top:7px;color:{color};font-size:11px;'
                    f'font-weight:800;line-height:1.35;">{missing_html}</span>'
                )
        slot = _one_h_slot_from_label(label)
        missing = (missing_one_h_by_slot or {}).get(slot or "", [])
        if missing:
            with_blocked = set(missing_one_h_at_16_with_blocked_initials or []) if slot == "16:00" else set()
            with_project = set((project_covered_by_slot or {}).get(slot or "", []))
            with_personal = set((personal_covered_by_slot or {}).get(slot or "", []))
            with_blocked.update(with_project)
            with_blocked.update(with_personal)
            red_initials = [value for value in missing if value not in with_blocked]
            green_initials = [value for value in missing if value in with_blocked]
            for initials, attribute, color in (
                (red_initials, "data-missing-one-h-users", "#DC2626"),
                ([v for v in green_initials if v not in with_project and v not in with_personal], "data-missing-one-h-with-blocked-users", "#15803D"),
                ([v for v in green_initials if v in with_project], "data-missing-one-h-with-project-users", "#15803D"),
                ([v for v in green_initials if v in with_personal and v not in with_project], "data-missing-one-h-with-personal-users", "#15803D"),
            ):
                if not initials:
                    continue
                missing_html = " &bull; ".join(html.escape(value) for value in initials)
                label_html += (
                    f'<span {attribute}="true" '
                    f'style="display:block;margin-top:7px;color:{color};font-size:11px;'
                    f'font-weight:800;line-height:1.35;">{missing_html}</span>'
                )
        return label_html

    for number, (label, values, *rest) in enumerate(rows, 1):
        personal = bool(rest and rest[0])
        chunks = [values[index:index + 6] for index in range(0, len(values), 6)] or [[]]
        for chunk_index, chunk in enumerate(chunks):
            first_row_divider = (
                MEETING_TYPE_DIVIDER_STYLE
                if meeting and "INT" in label.upper()
                else SLOT_DIVIDER_STYLE
            )
            row_divider_style = INTRA_SLOT_DIVIDER_STYLE if chunk_index else first_row_divider
            if not meeting:
                title_cells: list[str] = []
                date_cells: list[str] = []
                for item_index in range(6):
                    item = chunk[item_index] if item_index < len(chunk) else None
                    if item is None:
                        background = ""
                        title_style = f"{CELL_STYLE};{row_divider_style};border-bottom:0;padding-bottom:2px"
                        date_style = f"{CELL_STYLE};border-top:0;padding-top:0;vertical-align:bottom;height:25px"
                        date_badges = ""
                    else:
                        cell_style, color = _task_cell_style(
                            item, personal=personal, report_date=report_date
                        )
                        background = f' bgcolor="{color}"' if color else ""
                        title_style = f"{cell_style};{row_divider_style};border-bottom:0;padding-bottom:2px"
                        date_style = f"{cell_style};border-top:0;padding-top:0;vertical-align:bottom;height:25px"
                        badges, date_badges = _task_badges_html(item, report_date)
                        title = _task_title(item, personal=personal)
                        title_html = _task_title_html(title, red_background=color == DEADLINE_COLOR)
                        task_number = item_index + (chunk_index * 6) + 1
                        task_id = html.escape(str(item.get("task_id") or item.get("taskId") or ""), quote=True)
                        marker_value = html.escape(
                            str(item.get("one_h_marker") or item.get("oneHMarker") or ""), quote=True
                        )
                        marker_by_ga = "true" if (
                            item.get("one_h_marker_by_ga") or item.get("oneHMarkerByGa")
                        ) else "false"
                        marker_comment = _task_marker_comment(item)
                        deadline_important = "true" if (
                            item.get("is_deadline_important") or item.get("isDeadlineImportant")
                        ) else "false"
                        starts_today = "true" if (
                            report_date is not None and _task_start_day(item) == report_date
                        ) else "false"
                        task_attr = (
                            f' data-task-id="{task_id}" data-task-marker="{marker_value}"'
                            f' data-task-deadline-important="{deadline_important}"'
                            f' data-task-starts-today="{starts_today}"'
                            f' data-task-marker-by-ga="{marker_by_ga}"'
                            f' data-task-marker-comment="{html.escape(marker_comment, quote=True)}"'
                            if task_id else ""
                        )
                        comment_display = "block" if marker_comment else "none"
                        comment_html = (
                            '<div data-task-marker-comment="true" '
                            f'title="{html.escape(marker_comment, quote=True)}" '
                            'style="clear:both;width:fit-content;max-width:min(100%,150px);box-sizing:border-box;'
                            'margin:4px 0;padding:2px 6px;border:1px solid #BFDBFE;'
                            'border-radius:4px;background:#EFF6FF;color:#1E3A8A;'
                            'font-size:11px;font-weight:500;line-height:1.25;'
                            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:{comment_display};">'
                            f'<strong>COM:</strong> {html.escape(marker_comment)}</div>'
                        )
                        task_text_html = (
                            f'<span data-task-title-text="true" style="{TASK_TITLE_TEXT_STYLE}">'
                            f'{task_number}. {title_html}</span>'
                        )
                        title_cells.append(
                            f'<td{task_attr}{background} style="{title_style}">{badges}{comment_html}{task_text_html}</td>'
                        )
                    if chunk_index == len(chunks) - 1:
                        date_style = f"{date_style};{SLOT_END_DIVIDER_STYLE}"
                    if item is None:
                        title_cells.append(f'<td style="{title_style}"></td>')
                    date_cells.append(
                        f'<td{background} height="25" valign="bottom" '
                        f'style="{date_style}">{date_badges}</td>'
                    )

                label_divider_style = f"{SLOT_DIVIDER_STYLE};{SLOT_END_DIVIDER_STYLE}"
                row_header = (
                    f'<th rowspan="{len(chunks) * 2}" style="{SLOT_LABEL_STYLE};{label_divider_style}">{number}</th>'
                    f'<th rowspan="{len(chunks) * 2}" style="{PERSONAL_ROW_LABEL_STYLE if personal else SLOT_LABEL_STYLE};{label_divider_style}">{row_label_html(label, personal)}</th>'
                    if chunk_index == 0 else ""
                )
                body.append(f'<tr data-task-card-row="content">{row_header}{"".join(title_cells)}</tr>')
                body.append(f'<tr data-task-card-row="dates">{"".join(date_cells)}</tr>')
                continue

            cells: list[str] = []
            for item_index, item in enumerate(chunk):
                value = (
                    f"{_meeting_title(item)} {str(item.get('time') or '').strip()}".strip()
                    if meeting
                    else _task_title(item, personal=personal)
                )
                if meeting:
                    meeting_type = "internal" if "INT" in label.upper() else "external"
                    color = meeting_report_color(item, meeting_type=meeting_type)
                    cell_style = (
                        f"{CELL_STYLE};border:2px solid {NON_ROUTINE_MEETING_BORDER_COLOR}"
                        if _is_non_routine_meeting(item) else CELL_STYLE
                    )
                    cell_style = f"{cell_style};background-color:{color};{MEETING_TITLE_TEXT_STYLE}"
                else:
                    cell_style, color = _task_cell_style(
                        item, personal=personal, report_date=report_date
                    )
                cell_style = f"{cell_style};{row_divider_style}"
                background = f' bgcolor="{color}"' if color else ""
                badges, _ = ("", "") if meeting else _task_badges_html(item, report_date)
                title_html = (
                    html.escape(value)
                    if meeting
                    else _task_title_html(value, red_background=color == DEADLINE_COLOR)
                )
                task_content = f'{badges}{item_index + (chunk_index * 6) + 1}. {title_html}'
                cells.append(
                    f'<td{background} style="{cell_style}">{task_content}</td>'
                )
            cells.extend(f'<td style="{CELL_STYLE};{row_divider_style}"></td>' for _ in range(6 - len(cells)))
            label_divider_style = (
                f"{SLOT_DIVIDER_STYLE};{SLOT_END_DIVIDER_STYLE}"
                if not meeting else first_row_divider
            )
            row_header = (
                f'<th rowspan="{len(chunks)}" style="{SLOT_LABEL_STYLE};{label_divider_style}">{number}</th>'
                f'<th rowspan="{len(chunks)}" style="{PERSONAL_ROW_LABEL_STYLE if personal else SLOT_LABEL_STYLE};{label_divider_style}">{row_label_html(label, personal)}</th>'
                if chunk_index == 0 else ""
            )
            body.append(f"<tr>{row_header}{''.join(cells)}</tr>")
    table_style = f"{TABLE_STYLE};{TASK_TABLE_FRAME_STYLE}" if not meeting else TABLE_STYLE
    header_style = f"{HEADER_STYLE};{TASK_HEADER_FRAME_STYLE}" if not meeting else HEADER_STYLE
    return (
        f'<table role="presentation" width="100%" border="1" cellpadding="0" cellspacing="0" style="{table_style}">'
        '<colgroup><col width="2.5%"><col width="10.5%"><col width="14.5%" span="6"></colgroup>'
        f'<thead><tr><th style="{header_style}">NR</th><th style="{header_style}">{label_header}</th>'
        + (
            "".join(f'<th style="{HEADER_STYLE}">{header} {index}</th>' for index in range(1, 7))
            if meeting else f'<th colspan="6" style="{header_style}">TASKS</th>'
        )
        + '</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def _dated_meetings_html(
    sections: list[tuple[date, str, list[tuple[str, list[dict[str, Any]], bool]]]],
) -> str:
    if not sections:
        return ""

    visible_sections = sections[:2]
    while len(visible_sections) < 2:
        visible_sections.append((visible_sections[0][0], "", []))
    left, right = visible_sections
    divider_style = "border-left:4px solid #2563EB"

    def meeting_value_cells(
        item: dict[str, Any] | None, index: int, divider: str, label: str
    ) -> str:
        if item is None:
            return (
                f'<td data-meeting-time="true" style="{CELL_STYLE};{divider}">&nbsp;</td>'
                f'<td data-meeting-users="true" style="{CELL_STYLE};{divider}">&nbsp;</td>'
                f'<td data-meeting-relation="true" style="{CELL_STYLE};{divider}">&nbsp;</td>'
                f'<td data-meeting-cell="true" style="{CELL_STYLE};{divider}">&nbsp;</td>'
            )
        meeting_time = str(item.get("time") or "-").strip() or "-"
        meeting_users = _meeting_users(item)
        unavailable_users = {
            str(value) for value in item.get("_unavailableUserInitials") or []
        }
        meeting_users_html = "/".join(
            (
                f'<span data-unavailable-meeting-user="true" style="color:{DEADLINE_COLOR};font-weight:800">'
                f'{html.escape(label)}</span>'
                if label in unavailable_users
                else html.escape(label)
            )
            for label, _ in meeting_users
        ) or "-"
        value = _meeting_title(item)
        meeting_type = "internal" if "INT" in label.upper() else "external"
        color = meeting_report_color(item, meeting_type=meeting_type)
        text_color = (
            f";color:{CALENDAR_INTERNAL_TEXT_COLOR}"
            if _is_faded_calendar_internal(item, meeting_type=meeting_type)
            else ""
        )
        calendar_badge = (
            ' <span data-calendar-meeting="true" style="display:inline-block;padding:1px 5px;'
            'border-radius:999px;background:#0D9488;color:#FFFFFF;font-size:9px;font-weight:700">CAL</span>'
            if _is_calendar_meeting(item, meeting_type=meeting_type)
            else ""
        )
        manual_badge = (
            ' <span data-manual-internal-meeting="true" style="display:inline-block;padding:1px 5px;'
            'border-radius:999px;background:#2563EB;color:#FFFFFF;font-size:9px;font-weight:700">MANUAL</span>'
            if _is_manual_internal_meeting(item, meeting_type=meeting_type)
            else ""
        )
        background = f' bgcolor="{color}"'
        highlight = (
            f";border:2px solid {NON_ROUTINE_MEETING_BORDER_COLOR}"
            if _is_non_routine_meeting(item)
            or _is_manual_internal_meeting(item, meeting_type=meeting_type)
            else ""
        )
        return (
            f'<td data-meeting-time="true"{background} style="{CELL_STYLE}{highlight};{divider};background-color:{color};white-space:nowrap{text_color}">'
            f'{html.escape(meeting_time)}{calendar_badge}{manual_badge}</td>'
            f'<td data-meeting-users="true"{background} style="{CELL_STYLE}{highlight};{divider};background-color:{color};'
            f'white-space:nowrap;font-weight:700{text_color}">{meeting_users_html}</td>'
            f'<td data-meeting-relation="true"{background} style="{CELL_STYLE}{highlight};{divider};background-color:{color};'
            f'white-space:nowrap;text-align:center;font-weight:800;">{_meeting_relation(item) if meeting_type == "internal" else ""}</td>'
            f'<td data-meeting-cell="true"{background} style="{CELL_STYLE}{highlight};{divider};background-color:{color};{MEETING_TITLE_TEXT_STYLE};'
            f'{"font-weight:800" if meeting_type == "external" or manual_badge else ""}{text_color}">'
            f"{index}. {html.escape(value)}</td>"
        )

    left_rows = {
        label: sorted(values, key=_meeting_time_sort_key)
        for label, values, *_ in left[2]
    }
    right_rows = {
        label: sorted(values, key=_meeting_time_sort_key)
        for label, values, *_ in right[2]
    }
    labels = list(left_rows)
    labels.extend(label for label in right_rows if label not in left_rows)
    body_rows: list[str] = []
    for label in labels:
        left_items = left_rows.get(label, [])
        right_items = right_rows.get(label, [])
        meeting_count = max(len(left_items), len(right_items), 1)
        for index in range(meeting_count):
            type_divider = MEETING_TYPE_DIVIDER_STYLE if "INT" in label.upper() else SLOT_DIVIDER_STYLE
            row_divider = type_divider if index == 0 else INTRA_SLOT_DIVIDER_STYLE
            left_label = (
                f'<th rowspan="{meeting_count}" data-meeting-type="true" '
                f'style="{SLOT_LABEL_STYLE};{type_divider}">{html.escape(label)}</th>'
                if index == 0 else ""
            )
            right_label = (
                f'<th rowspan="{meeting_count}" data-meeting-type="true" '
                f'style="{SLOT_LABEL_STYLE};{type_divider};{divider_style}">'
                f'{html.escape(label)}</th>'
                if index == 0 else ""
            )
            left_cells = meeting_value_cells(
                left_items[index] if index < len(left_items) else None,
                index + 1,
                row_divider,
                label,
            )
            right_cells = meeting_value_cells(
                right_items[index] if index < len(right_items) else None,
                index + 1,
                row_divider,
                label,
            )
            body_rows.append(
                '<tr data-meeting-row="true">'
                f'{left_label}{left_cells}{right_label}{right_cells}'
                '</tr>'
            )
    body = "".join(body_rows)

    def day_header(section: tuple[date, str, list[tuple[str, list[dict[str, Any]], bool]]]) -> str:
        meeting_date, relative, _ = section
        return f"TAKIMET {html.escape(relative)} - {meeting_date:%d.%m.%Y}" if relative else "&nbsp;"

    return (
        '<table data-side-by-side-meetings="true" role="presentation" width="100%" border="1" '
        f'cellpadding="0" cellspacing="0" style="{TABLE_STYLE};margin-top:18px;{MEETING_TABLE_FRAME_STYLE}">'
        '<colgroup><col width="8%"><col width="7%"><col width="7%"><col width="4%"><col width="24%">'
        '<col width="8%"><col width="7%"><col width="7%"><col width="4%"><col width="24%"></colgroup>'
        '<thead><tr>'
        f'<th colspan="5" style="{HEADER_STYLE};background-color:#EEF2FF;{MEETING_HEADER_FRAME_STYLE};border-left:5px solid #2563EB;'
        f'font-size:15px;">{day_header(left)}</th>'
        f'<th colspan="5" style="{HEADER_STYLE};background-color:#EEF2FF;{MEETING_HEADER_FRAME_STYLE};{divider_style};font-size:15px;">'
        f'{day_header(right)}</th></tr>'
        '<tr>'
        f'<th style="{HEADER_STYLE};{MEETING_HEADER_FRAME_STYLE}">LLOJI</th>'
        f'<th style="{HEADER_STYLE};{MEETING_HEADER_FRAME_STYLE}">KOHA</th>'
        f'<th style="{HEADER_STYLE};{MEETING_HEADER_FRAME_STYLE}">USER</th>'
        f'<th style="{HEADER_STYLE};{MEETING_HEADER_FRAME_STYLE}">PARA/PAS</th>'
        f'<th style="{HEADER_STYLE};{MEETING_HEADER_FRAME_STYLE}">TAKIMET</th>'
        f'<th style="{HEADER_STYLE};{MEETING_HEADER_FRAME_STYLE};{divider_style}">LLOJI</th>'
        f'<th style="{HEADER_STYLE};{MEETING_HEADER_FRAME_STYLE}">KOHA</th>'
        f'<th style="{HEADER_STYLE};{MEETING_HEADER_FRAME_STYLE}">USER</th>'
        f'<th style="{HEADER_STYLE};{MEETING_HEADER_FRAME_STYLE}">PARA/PAS</th>'
        f'<th style="{HEADER_STYLE};{MEETING_HEADER_FRAME_STYLE}">TAKIMET</th>'
        f"</tr></thead><tbody>{body}</tbody></table>"
    )


def _closing_row_color(row: ClosingTableRow, table: ClosingTable) -> str:
    if row.is_deadline:
        return DEADLINE_COLOR
    if row.status:
        return STATUS_COLORS.get(row.status, CLOSING_TONE_COLORS.get(table.tone, "#FFFFFF"))
    return CLOSING_TONE_COLORS.get(table.tone, "#FFFFFF")


def _empty_closing_table_row(table: ClosingTable) -> ClosingTableRow:
    values = ["-"] * len(table.columns)
    message_column = table.columns.index("TITULLI") if "TITULLI" in table.columns else len(values) - 1
    values[message_column] = "(Asnje detyre)"
    return ClosingTableRow(values=values)


def _closing_table_has_project_titles(table: ClosingTable) -> bool:
    if "PRJK" not in table.columns:
        return False
    project_index = table.columns.index("PRJK")
    return any(
        len(row.values) > project_index
        and str(row.values[project_index]).strip().upper()
        not in {"", "-", "(ASNJE DETYRE)", "(ASNJË DETYRË)"}
        for row in table.rows
    )


def _is_overdue_tyo_value(value: Any) -> bool:
    normalized = str(value or "").strip().upper()
    if normalized == "Y":
        return True
    try:
        return int(normalized) >= 2
    except ValueError:
        return False


def _closing_sections_html(sections: list[ClosingSection]) -> str:
    chunks: list[str] = []
    for section in sections:
        chunks.append(
            '<div data-closing-section="true" style="margin:16px 0 12px;">'
            f'<div style="background-color:#EEF2FF;border-left:5px solid #2563EB;padding:8px 10px;'
            f'font-family:Arial,sans-serif;font-size:14px;font-weight:700;">{html.escape(section.title)}</div>'
        )
        for table in section.tables:
            chunks.append(
                f'<div style="margin:8px 0 4px;font-family:Arial,sans-serif;font-size:12px;font-weight:700;">'
                f'{html.escape(table.label)}:</div>'
            )
            project_has_titles = _closing_table_has_project_titles(table)
            compact_columns = {
                "NR", "KUSH", "DEP", "AM/PM", "LLOJI", "NGA", "NE", "T/Y/O",
                "DISK", "FROM", "TIME",
            }
            if "PRJK" in table.columns and not project_has_titles:
                compact_columns.add("PRJK")
            widths = {
                "PRJK": "10%" if project_has_titles else "1%",
                "ARSYEJA": "16%",
                "KOMENT": "20%",
            }
            def header_cell(column: str) -> str:
                width = widths.get(column)
                width_attr = f' width="{width}"' if width else (' width="1%"' if column in compact_columns else "")
                nowrap = "white-space:nowrap;" if column in compact_columns else ""
                return (
                    f'<th{width_attr} style="{HEADER_STYLE};background-color:#E2E8F0;{nowrap}">'
                    f'{html.escape(column)}</th>'
                )

            header = "".join(header_cell(column) for column in table.columns)
            rows = table.rows or [_empty_closing_table_row(table)]
            body: list[str] = []
            for row in rows:
                color = _closing_row_color(row, table)
                foreground = "#FFFFFF" if color == DEADLINE_COLOR else "#111827"
                priority_border = f";border:2px solid {EIGHT_AM_BORDER_COLOR}" if row.is_eight_am else ""
                cells = []
                for column, value in zip(table.columns, row.values):
                    cell_color, cell_foreground = color, foreground
                    extra = ";white-space:nowrap;width:1%" if column in compact_columns else ""
                    stacked_dates = column in {"NGA", "NE"} and "\n" in str(value)
                    if stacked_dates:
                        extra += ";padding:0"
                    if column == "T/Y/O" and _is_overdue_tyo_value(value):
                        cell_color, cell_foreground = DEADLINE_COLOR, "#FFFFFF"
                        extra += ";font-weight:400;text-align:left"
                    if column == "DISK":
                        normalized = str(value).strip().upper()
                        if normalized == "YES":
                            extra += ";background-color:#DCFCE7;color:#166534;font-weight:700;text-align:center"
                        elif normalized == "NO":
                            extra += ";background-color:#FEE2E2;color:#991B1B;font-weight:700;text-align:center"
                    if stacked_dates:
                        first_line, second_line = str(value).split("\n", 1)
                        cell_content = (
                            '<div style="padding:5px;border-bottom:3px solid #334155;">'
                            f'{html.escape(first_line)}</div>'
                            f'<div style="padding:5px;">{html.escape(second_line)}</div>'
                        )
                    else:
                        cell_content = html.escape(str(value)).replace(chr(10), "<br>")
                    cells.append(
                        f'<td style="{CELL_STYLE};background-color:{cell_color};color:{cell_foreground}{priority_border}{extra}">'
                        f'{cell_content}</td>'
                    )
                body.append(f'<tr data-closing-row="true">{"".join(cells)}</tr>')
            chunks.append(
                f'<table data-closing-table="true" role="presentation" width="100%" border="1" cellpadding="0" '
                f'cellspacing="0" style="{TABLE_STYLE};table-layout:auto;border:3px solid #111827;">'
                f'<thead><tr>{header}</tr></thead><tbody>{"".join(body)}</tbody></table>'
            )
        chunks.append("</div>")
    return "".join(chunks)


def _closing_sections_plain_text(sections: list[ClosingSection]) -> list[str]:
    lines: list[str] = []
    for section in sections:
        lines.extend(["", section.title])
        for table in section.tables:
            lines.append(f"{table.label}: {' | '.join(table.columns)}")
            if not table.rows:
                lines.append("(Asnje detyre)")
            else:
                lines.extend(" | ".join(str(value) for value in row.values) for row in table.rows)
    return lines


def _excel_table_attachment(
    task_rows: list[tuple[str, list[dict[str, Any]], bool]],
    meeting_rows: list[tuple[str, list[dict[str, Any]], bool]],
    target_date: date,
    *,
    include_meetings: bool = True,
    comment_initials: list[str] | None = None,
    meeting_sections: list[tuple[date, str, list[tuple[str, list[dict[str, Any]], bool]]]] | None = None,
    closing_sections: list[ClosingSection] | None = None,
    checklist_date: date | None = None,
    missing_one_h_by_slot: dict[str, list[str]] | None = None,
    report_day_label: str = "SOT",
    project_covered_by_slot: dict[str, list[str]] | None = None,
) -> tuple[str, bytes, str]:
    """Create the same printable grid as an XLSX attachment for email recipients."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "1H SHTYPI"
    sheet.merge_cells("A1:H1")
    title_cell = sheet["A1"]
    title_cell.value = f"1H SHTYPI {report_day_label} (Shiko simbolet) - {target_date:%d.%m.%Y}"
    title_cell.font = Font(bold=True, size=14)
    title_cell.alignment = Alignment(horizontal="center")

    border = Border(
        left=Side(style="thin", color="000000"), right=Side(style="thin", color="000000"),
        top=Side(style="thin", color="000000"), bottom=Side(style="thin", color="000000"),
    )
    slot_divider_border = Border(
        left=Side(style="thin", color="000000"), right=Side(style="thin", color="000000"),
        top=Side(style="medium", color="111827"), bottom=Side(style="thin", color="000000"),
    )
    intra_slot_divider_border = Border(
        left=Side(style="thin", color="000000"), right=Side(style="thin", color="000000"),
        top=Side(style="thin", color="CBD5E1"), bottom=Side(style="thin", color="000000"),
    )
    medium_grid_side = Side(style="medium", color="111827")
    meeting_type_divider_side = Side(style="thick", color="111827")

    def task_grid_border(
        current: Border, *, category_start: bool = False, category_end: bool = False,
        outer_left: bool = False, outer_right: bool = False,
    ) -> Border:
        """Add the task-grid hierarchy without changing fills, fonts, or task content."""
        return Border(
            left=medium_grid_side if outer_left else current.left,
            right=medium_grid_side if outer_right else current.right,
            top=medium_grid_side if category_start else current.top,
            bottom=medium_grid_side if category_end else current.bottom,
        )

    def meeting_type_border(current: Border) -> Border:
        return Border(
            left=current.left,
            right=current.right,
            top=meeting_type_divider_side,
            bottom=current.bottom,
        )
    header_fill = PatternFill("solid", fgColor="EAF0FF")
    fills = {
        status: PatternFill("solid", fgColor=color.removeprefix("#"))
        for status, color in STATUS_COLORS.items()
    }
    ga_fill = PatternFill("solid", fgColor=PERSONAL_GA_COLOR.removeprefix("#"))
    deadline_fill = PatternFill("solid", fgColor=DEADLINE_COLOR.removeprefix("#"))
    eight_am_border = Border(
        left=Side(style="medium", color=EIGHT_AM_BORDER_COLOR.removeprefix("#")),
        right=Side(style="medium", color=EIGHT_AM_BORDER_COLOR.removeprefix("#")),
        top=Side(style="medium", color=EIGHT_AM_BORDER_COLOR.removeprefix("#")),
        bottom=Side(style="medium", color=EIGHT_AM_BORDER_COLOR.removeprefix("#")),
    )
    non_routine_meeting_border = Border(
        left=Side(style="medium", color=NON_ROUTINE_MEETING_BORDER_COLOR.removeprefix("#")),
        right=Side(style="medium", color=NON_ROUTINE_MEETING_BORDER_COLOR.removeprefix("#")),
        top=Side(style="medium", color=NON_ROUTINE_MEETING_BORDER_COLOR.removeprefix("#")),
        bottom=Side(style="medium", color=NON_ROUTINE_MEETING_BORDER_COLOR.removeprefix("#")),
    )

    def write_closing_sections(row_number: int) -> int:
        for section in closing_sections or []:
            sheet.merge_cells(start_row=row_number, start_column=1, end_row=row_number, end_column=8)
            section_cell = sheet.cell(row_number, 1, section.title)
            section_cell.fill = PatternFill("solid", fgColor="EEF2FF")
            section_cell.font = Font(bold=True, size=12)
            section_cell.alignment = Alignment(vertical="center")
            row_number += 1
            for table in section.tables:
                sheet.merge_cells(start_row=row_number, start_column=1, end_row=row_number, end_column=8)
                label_cell = sheet.cell(row_number, 1, f"{table.label}:")
                label_cell.font = Font(bold=True)
                row_number += 1
                for column, value in enumerate(table.columns, 1):
                    cell = sheet.cell(row_number, column, value)
                    cell.font = Font(bold=True)
                    cell.fill = header_fill
                    cell.border = border
                    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                row_number += 1
                rows = table.rows or [_empty_closing_table_row(table)]
                for row in rows:
                    color = _closing_row_color(row, table).removeprefix("#")
                    for column, (header, value) in enumerate(zip(table.columns, row.values), 1):
                        cell = sheet.cell(row_number, column, value)
                        cell.fill = PatternFill("solid", fgColor=color)
                        cell.border = eight_am_border if row.is_eight_am else border
                        cell.alignment = Alignment(vertical="top", wrap_text=True)
                        if color == DEADLINE_COLOR.removeprefix("#"):
                            cell.font = Font(color="FFFFFF", bold=True)
                        if header == "T/Y/O" and _is_overdue_tyo_value(value):
                            cell.fill = PatternFill("solid", fgColor=DEADLINE_COLOR.removeprefix("#"))
                            cell.font = Font(color="FFFFFF", bold=False)
                            cell.alignment = Alignment(horizontal="left", vertical="center")
                        if header == "DISK":
                            normalized = str(value).strip().upper()
                            if normalized == "YES":
                                cell.fill = PatternFill("solid", fgColor="DCFCE7")
                                cell.font = Font(color="166534", bold=True)
                            elif normalized == "NO":
                                cell.fill = PatternFill("solid", fgColor="FEE2E2")
                                cell.font = Font(color="991B1B", bold=True)
                            cell.alignment = Alignment(horizontal="center", vertical="center")
                    row_number += 1
            row_number += 1
        return row_number
    def write_checklists(row_number: int) -> int:
        """Write each preparation list as a title row plus one compact content row."""
        checklist_fill = PatternFill("solid", fgColor="EEF2FF")
        weekday_fill = PatternFill("solid", fgColor="FFF7F7")
        board_questions, staff_questions = _one_h_checklists_for_day(checklist_date)
        staff_extra = staff_questions[len(ONE_H_STAFF_CHECKLIST):]
        board_extra = board_questions[len(ONE_H_BOARD_CHECKLIST):]
        day_label = _day_specific_question_label(checklist_date)
        if staff_extra or board_extra:
            sheet.merge_cells(start_row=row_number, start_column=1, end_row=row_number, end_column=8)
            extra_cell = sheet.cell(row_number, 1)
            extra_cell.value = CellRichText([
                TextBlock(InlineFont(rFont="Arial", b=role != "question", sz=14 if role == "separator" else 12 if role == "label" else 10, color="B91C1C"), text)
                for text, role in _extra_question_parts(checklist_date)
            ])
            extra_cell.fill = weekday_fill
            extra_cell.font = Font(color="B91C1C", size=10)
            extra_cell.alignment = Alignment(vertical="center", wrap_text=True)
            extra_cell.border = border
            sheet.row_dimensions[row_number].height = 18 * max(1, (len(str(extra_cell.value)) + 179) // 180)
            row_number += 1
        else:
            sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=8)
            label_cell = sheet.cell(2, 1, day_label)
            label_cell.fill = weekday_fill
            label_cell.font = Font(color="B91C1C", bold=True, size=10)
            label_cell.alignment = Alignment(vertical="center")
            label_cell.border = border

        for start_column, end_column, title, questions in (
            (1, 4, "STAFF - HAPAT PER 1H", staff_questions[:len(ONE_H_STAFF_CHECKLIST)]),
            (5, 8, "PYETJET PER 1H - BORD", ONE_H_BOARD_FOLLOW_UP_CHECKLIST),
        ):
            sheet.merge_cells(start_row=row_number, start_column=start_column, end_row=row_number, end_column=end_column)
            title_cell = sheet.cell(row_number, start_column, title)
            title_cell.fill = checklist_fill
            title_cell.font = Font(bold=True, size=11)
            title_cell.alignment = Alignment(vertical="center")
            title_cell.border = border
            sheet.merge_cells(
                start_row=row_number + 1,
                start_column=start_column,
                end_row=row_number + 1,
                end_column=end_column,
            )
            question_cell = sheet.cell(
                row_number + 1,
                start_column,
                " / ".join(
                    f"{_checklist_question_number(checklist_date, index, question)} {question}" + (f" ({description})" if description else "")
                    for index, (question, description) in enumerate(questions, 1)
                ),
            )
            question_cell.font = Font(bold=True, size=10)
            question_cell.alignment = Alignment(vertical="center", wrap_text=True)
            question_cell.border = border
        sheet.row_dimensions[row_number + 1].height = 48
        sheet.merge_cells(start_row=row_number + 2, start_column=1, end_row=row_number + 2, end_column=4)
        staff_spacer = sheet.cell(row_number + 2, 1, "")
        staff_spacer.border = border
        sheet.merge_cells(start_row=row_number + 2, start_column=5, end_row=row_number + 2, end_column=8)
        board_primary_cell = sheet.cell(
            row_number + 2,
            5,
            " / ".join(
                f"{index}. {question}" + (f" ({description})" if description else "")
                for index, (question, description) in enumerate(ONE_H_BOARD_PRIMARY_CHECKLIST, 1)
            ),
        )
        board_primary_cell.font = Font(bold=True, size=10)
        board_primary_cell.alignment = Alignment(vertical="center", wrap_text=True)
        board_primary_cell.border = border
        sheet.row_dimensions[row_number + 2].height = 60
        return row_number + 3

    def write_marker_legend(row_number: int) -> int:
        sheet.merge_cells(start_row=row_number, start_column=1, end_row=row_number, end_column=8)
        legend_cell = sheet.cell(row_number, 1, _task_marker_legend_text())
        legend_cell.fill = PatternFill("solid", fgColor="EFF6FF")
        legend_cell.font = Font(color="0F2A5F", bold=True, size=9)
        legend_cell.alignment = Alignment(vertical="center", wrap_text=True)
        legend_cell.border = Border(
            left=Side(style="thin", color="93C5FD"),
            right=Side(style="thin", color="93C5FD"),
            top=Side(style="thin", color="93C5FD"),
            bottom=Side(style="thin", color="93C5FD"),
        )
        sheet.row_dimensions[row_number].height = 28
        return row_number + 1

    def write_section(
        rows: list[tuple[str, list[dict[str, Any]], bool]], *, meeting: bool, row_number: int
    ) -> int:
        section_headers = (
            ["NR", "LLOJI", "MEETING 1", "MEETING 2", "MEETING 3", "MEETING 4", "MEETING 5", "MEETING 6"]
            if meeting else ["NR", "LLOJI DHE SLOTI", "TASKS", None, None, None, None, None]
        )
        for column, value in enumerate(section_headers, 1):
            cell = sheet.cell(row_number, column, value)
            cell.font = Font(bold=True)
            cell.fill = header_fill
            cell.border = border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            if not meeting:
                cell.border = task_grid_border(
                    cell.border,
                    category_start=True,
                    category_end=True,
                    outer_left=column == 1,
                    # C is the anchor of merged C:H; its right border becomes
                    # the visible right edge of the merged TASKS heading.
                    outer_right=column in (3, 8),
                )
            else:
                cell.border = task_grid_border(
                    cell.border,
                    category_start=True,
                    category_end=True,
                    outer_left=column == 1,
                    outer_right=column == 8,
                )
        if not meeting:
            sheet.merge_cells(start_row=row_number, start_column=3, end_row=row_number, end_column=8)
            # Reapply the perimeter after merging C:H; openpyxl rebuilds merged-cell
            # borders and otherwise drops the right edge from H.
            for column in range(1, 9):
                cell = sheet.cell(row_number, column)
                cell.border = task_grid_border(
                    cell.border,
                    category_start=True,
                    category_end=True,
                    outer_left=column == 1,
                    outer_right=column in (3, 8),
                )
        row_number += 1
        for number, (label, values, personal) in enumerate(rows, 1):
            chunks = [values[index:index + 6] for index in range(0, len(values), 6)] or [[]]
            first_row = row_number
            for chunk_index, chunk in enumerate(chunks):
                row_border = intra_slot_divider_border if chunk_index else slot_divider_border
                category_start = chunk_index == 0
                category_end = chunk_index == len(chunks) - 1
                if chunk_index == 0:
                    sheet.cell(row_number, 1, number)
                    label_value: str | CellRichText = label
                    if personal and "\n" in label:
                        personal_title, personal_time = label.split("\n", 1)
                        label_value = CellRichText([
                            TextBlock(InlineFont(b=True, sz=10), personal_title),
                            "\n",
                            TextBlock(InlineFont(b=True, sz=14), personal_time),
                        ])
                    else:
                        slot = _one_h_slot_from_label(label) or ("BLL" if label.strip() == "BLL" else None)
                        missing = (missing_one_h_by_slot or {}).get(slot or "", [])
                        if missing:
                            covered = set((project_covered_by_slot or {}).get(slot or "", []))
                            label_value = CellRichText([TextBlock(InlineFont(b=True, sz=10), label)])
                            for group, color in (([x for x in missing if x not in covered], "DC2626"), ([x for x in missing if x in covered], "15803D")):
                                if group:
                                    label_value.extend(["\n", TextBlock(InlineFont(b=True, sz=10, color=color), " • ".join(group))])
                    label_cell = sheet.cell(row_number, 2, label_value)
                    label_cell.font = Font(bold=True, size=10)
                    if personal:
                        label_cell.alignment = Alignment(vertical="top", wrap_text=True)
                for item_index, item in enumerate(chunk, 3):
                    value = (
                        f"{_meeting_title(item)} {str(item.get('time') or '').strip()}".strip()
                        if meeting else _task_title(item, personal=personal)
                    )
                    if not meeting:
                        labels: list[str] = [f"[{_task_period_label(item)}]"]
                        if _task_status(item) == "WAITING_CONFIRMATION":
                            labels.append("[WFC]")
                        marker_label = _task_marker_label(item)
                        if marker_label:
                            labels.append(_task_marker_text_token(item))
                        if _is_eight_am_task(item):
                            labels.append("[08:00]")
                        marker_comment = _task_marker_comment(item)
                        if marker_comment:
                            value = f"COM: {marker_comment}\n{value}"
                        if labels:
                            value = f"{' '.join(labels)}\n{value}"
                        date_labels: list[str] = []
                        start_day = _task_start_day(item)
                        due_day = _task_due_day(item)
                        if start_day:
                            date_labels.append(f"[START: {start_day:%d.%m.%Y}]")
                        if due_day:
                            due_label = "SOT" if due_day == target_date else due_day.strftime("%d.%m.%Y")
                            date_labels.append(f"[DUE: {due_label}]")
                        if date_labels:
                            value = f"{value}\n{' '.join(date_labels)}"
                    cell_value = f"{item_index - 2 + chunk_index * 6}. {value}"
                    background = _task_cell_style(
                        item, personal=personal, report_date=target_date
                    )[1]
                    if not meeting:
                        cell_value = _excel_task_title(
                            cell_value,
                            red_background=background == DEADLINE_COLOR,
                            marker_label=marker_label,
                            marker_by_ga=_task_marker_was_set_by_ga(item),
                        )
                    cell = sheet.cell(row_number, item_index, cell_value)
                    if not meeting:
                        if background == PERSONAL_GA_COLOR:
                            cell.fill = ga_fill
                        elif background == DEADLINE_COLOR:
                            cell.fill = deadline_fill
                            cell.font = Font(color="FFFFFF", bold=True)
                        else:
                            cell.fill = fills[_task_status(item)]
                        if _is_eight_am_task(item):
                            cell.border = eight_am_border
                    elif _is_non_routine_meeting(item):
                        cell.border = non_routine_meeting_border
                    if meeting:
                        meeting_type = "internal" if "INT" in label.upper() else "external"
                        cell.fill = PatternFill(
                            "solid",
                            fgColor=meeting_report_color(item, meeting_type=meeting_type).removeprefix("#"),
                        )
                for column in range(1, 9):
                    cell = sheet.cell(row_number, column)
                    is_highlighted_meeting_cell = (
                        meeting
                        and column >= 3
                        and column - 3 < len(chunk)
                        and _is_non_routine_meeting(chunk[column - 3])
                    )
                    is_eight_am_task_cell = (
                        not meeting
                        and column >= 3
                        and column - 3 < len(chunk)
                        and _is_eight_am_task(chunk[column - 3])
                    )
                    if not is_highlighted_meeting_cell and not is_eight_am_task_cell:
                        cell.border = row_border
                    if not meeting:
                        cell.border = task_grid_border(
                            cell.border,
                            category_start=category_start,
                            category_end=category_end,
                            outer_left=column == 1,
                            outer_right=column == 8,
                        )
                    else:
                        cell.border = task_grid_border(
                            cell.border,
                            category_end=number == len(rows) and category_end,
                            outer_left=column == 1,
                            outer_right=column == 8,
                        )
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
                row_number += 1
            if len(chunks) > 1:
                sheet.merge_cells(start_row=first_row, start_column=1, end_row=row_number - 1, end_column=1)
                sheet.merge_cells(start_row=first_row, start_column=2, end_row=row_number - 1, end_column=2)
        return row_number

    def write_meeting_section(
        rows: list[tuple[str, list[dict[str, Any]], bool]], row_number: int
    ) -> int:
        sheet.merge_cells(start_row=row_number, start_column=1, end_row=row_number, end_column=2)
        sheet.merge_cells(start_row=row_number, start_column=6, end_row=row_number, end_column=8)
        for column, value in ((1, "LLOJI"), (3, "KOHA"), (4, "USER"), (5, "PARA/PAS"), (6, "TAKIMET")):
            cell = sheet.cell(row_number, column, value)
            cell.font = Font(bold=True)
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for column in range(1, 9):
            sheet.cell(row_number, column).border = task_grid_border(
                sheet.cell(row_number, column).border,
                category_start=True,
                category_end=True,
                outer_left=column == 1,
                outer_right=column in (5, 8),
            )
        row_number += 1

        meeting_values = _flatten_meeting_rows(rows) or [("-", None)]
        for index, (label, item) in enumerate(meeting_values, 1):
            sheet.merge_cells(start_row=row_number, start_column=1, end_row=row_number, end_column=2)
            sheet.merge_cells(start_row=row_number, start_column=6, end_row=row_number, end_column=8)
            sheet.cell(row_number, 1, label)
            meeting_type = "internal" if "INT" in label.upper() else "external"
            meeting_text_color = (
                CALENDAR_INTERNAL_TEXT_COLOR.removeprefix("#")
                if item is not None
                and _is_faded_calendar_internal(item, meeting_type=meeting_type)
                else "000000"
            )
            sheet.cell(
                row_number,
                3,
                _meeting_time_display(item, meeting_type=meeting_type) if item else "-",
            )
            sheet.cell(
                row_number,
                4,
                _excel_meeting_user_initials(item, default_color=meeting_text_color)
                if item else "-",
            )
            sheet.cell(
                row_number,
                5,
                _meeting_relation(item) if item and meeting_type == "internal" else "",
            )
            sheet.cell(
                row_number,
                6,
                f"{index}. {_meeting_title(item)}" if item else "-",
            )
            highlighted = item is not None and (
                _is_non_routine_meeting(item)
                or _is_manual_internal_meeting(item, meeting_type=meeting_type)
            )
            meeting_fill = (
                PatternFill("solid", fgColor=meeting_report_color(item, meeting_type=meeting_type).removeprefix("#"))
                if item else None
            )
            for column in range(1, 9):
                cell = sheet.cell(row_number, column)
                cell.border = non_routine_meeting_border if highlighted and column >= 3 else border
                if "INT" in label.upper():
                    previous_label = meeting_values[index - 2][0] if index > 1 else ""
                    if "INT" not in previous_label.upper():
                        cell.border = meeting_type_border(cell.border)
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                if meeting_fill is not None and column >= 3:
                    cell.fill = meeting_fill
            sheet.cell(row_number, 1).font = Font(bold=True)
            sheet.cell(row_number, 4).font = Font(bold=True)
            sheet.cell(row_number, 5).font = Font(bold=True)
            sheet.cell(row_number, 5).alignment = Alignment(horizontal="center", vertical="top")
            if item is not None and (
                meeting_type == "external"
                or _is_manual_internal_meeting(item, meeting_type=meeting_type)
            ):
                sheet.cell(row_number, 6).font = Font(bold=True)
            if item is not None and _is_faded_calendar_internal(item, meeting_type=meeting_type):
                for column in (3, 4, 6):
                    sheet.cell(row_number, column).font = Font(
                        bold=column == 4,
                        color=CALENDAR_INTERNAL_TEXT_COLOR.removeprefix("#"),
                    )
            row_number += 1
        return row_number

    task_header_row = write_checklists(write_closing_sections(3))
    next_row = write_section(task_rows, meeting=False, row_number=task_header_row)
    if include_meetings:
        if meeting_sections:
            for meeting_date, relative, dated_rows in meeting_sections:
                section_row = next_row + 1
                sheet.merge_cells(start_row=section_row, start_column=1, end_row=section_row, end_column=8)
                section_cell = sheet.cell(section_row, 1, f"TAKIMET {relative} - {meeting_date:%d.%m.%Y}")
                section_cell.font = Font(bold=True, size=12)
                section_cell.fill = PatternFill("solid", fgColor="EEF2FF")
                section_cell.alignment = Alignment(horizontal="left", vertical="center")
                for column in range(1, 9):
                    cell = sheet.cell(section_row, column)
                    cell.border = task_grid_border(
                        cell.border,
                        category_start=True,
                        category_end=True,
                        outer_left=column == 1,
                        outer_right=column in (1, 8),
                    )
                next_row = write_meeting_section(dated_rows, row_number=section_row + 1)
        else:
            next_row = write_section(meeting_rows, meeting=True, row_number=next_row + 1)

    comment_columns = comment_initials or list(COMMENT_FIXED_INITIALS)
    comment_start_row = next_row + 1
    sheet.merge_cells(
        start_row=comment_start_row,
        start_column=1,
        end_row=comment_start_row,
        end_column=8,
    )
    comment_title = sheet.cell(comment_start_row, 1, "KOMENTE PER STAF")
    comment_title.font = Font(bold=True, size=12)
    comment_title.alignment = Alignment(horizontal="left", vertical="center")
    for offset, line in enumerate(_comment_write_in_lines(comment_columns), 1):
        row = comment_start_row + offset
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
        line_cell = sheet.cell(row, 1, line)
        line_cell.font = Font(size=11)
        line_cell.alignment = Alignment(horizontal="left", vertical="center")
        sheet.row_dimensions[row].height = 22
    write_marker_legend(comment_start_row + len(_comment_write_in_lines(comment_columns)) + 2)
    widths = [4, 24, 29, 29, 29, 29, 29, 29]
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[chr(64 + index)].width = width
    sheet.freeze_panes = f"C{task_header_row + 1}"

    output = BytesIO()
    workbook.save(output)
    return (
        f"1H_SHTYPI_{target_date:%Y-%m-%d}.xlsx",
        output.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _docx_table_attachment(
    task_rows: list[tuple[str, list[dict[str, Any]], bool]],
    target_date: date,
    *,
    closing_sections: list[ClosingSection] | None = None,
    meeting_sections: list[tuple[date, str, list[tuple[str, list[dict[str, Any]], bool]]]] | None = None,
    comment_initials: list[str] | None = None,
    missing_one_h_by_slot: dict[str, list[str]] | None = None,
    report_day_label: str = "SOT",
    checklist_date: date | None = None,
    project_covered_by_slot: dict[str, list[str]] | None = None,
) -> tuple[str, bytes, str]:
    """Create a landscape Word report from the same rows and colours as HTML."""
    document = Document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = Inches(11), Inches(8.5)
    section.top_margin = section.bottom_margin = Inches(0.45)
    section.left_margin = section.right_margin = Inches(0.45)
    styles = document.styles
    normal = styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(8)
    normal.paragraph_format.space_after = Pt(0)

    def shade(cell: Any, color: str) -> None:
        properties = cell._tc.get_or_add_tcPr()
        fill = properties.find(qn("w:shd"))
        if fill is None:
            fill = OxmlElement("w:shd")
            properties.append(fill)
        fill.set(qn("w:fill"), color.removeprefix("#"))

    def set_cell(cell: Any, value: str, *, bold: bool = False, color: str = "000000", center: bool = False) -> None:
        cell.text = ""
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.space_after = Pt(0)
        run = paragraph.add_run(str(value))
        run.font.name = "Arial"
        run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:ascii"), "Arial")
        run.font.size = Pt(7.5)
        run.bold = bold
        run.font.color.rgb = RGBColor.from_string(color.removeprefix("#"))

    def set_meeting_user_cell(cell: Any, item: dict[str, Any], *, color: str) -> None:
        cell.text = ""
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        paragraph = cell.paragraphs[0]
        paragraph.paragraph_format.space_after = Pt(0)
        users = _meeting_users(item)
        unavailable = {str(value) for value in item.get("_unavailableUserInitials") or []}
        for index, (label, _) in enumerate(users or [("-", None)]):
            if index:
                separator = paragraph.add_run("/")
                separator.font.name = "Arial"
                separator.font.size = Pt(7.5)
                separator.bold = True
                separator.font.color.rgb = RGBColor.from_string(color.removeprefix("#"))
            run = paragraph.add_run(label)
            run.font.name = "Arial"
            run.font.size = Pt(7.5)
            run.bold = True
            run.font.color.rgb = RGBColor.from_string(
                DEADLINE_COLOR.removeprefix("#") if label in unavailable else color.removeprefix("#")
            )

    def set_task_cell(cell: Any, item: dict[str, Any], number: int, *, personal: bool, bold: bool, color: str) -> None:
        cell.text = ""
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        paragraph = cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.space_after = Pt(0)
        marker_comment = _task_marker_comment(item)
        if marker_comment:
            run = paragraph.add_run(f"COM: {marker_comment}\n")
            run.font.name = "Arial"
            run.font.size = Pt(7)
            run.bold = False
            run.font.color.rgb = RGBColor.from_string("0F2A5F")
        marker = _task_marker_label(item)
        parts = [
            (f"{number}. [{_task_period_label(item)}]", color),
            (" [WFC]" if _task_status(item) == "WAITING_CONFIRMATION" else "", color),
            (f" {_task_marker_text_token(item)}" if marker else "", "DC2626"),
            (f" {_task_title(item, personal=personal)}", color),
        ]
        for value, run_color in parts:
            if not value:
                continue
            run = paragraph.add_run(value)
            run.font.name = "Arial"
            run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:ascii"), "Arial")
            run.font.size = Pt(7.5)
            run.bold = bold or run_color == "DC2626"
            run.font.color.rgb = RGBColor.from_string(run_color.removeprefix("#"))

    def set_stacked_date_cell(cell: Any, value: str, *, color: str = "000000") -> None:
        first_line, second_line = str(value).split("\n", 1)
        cell.text = ""
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        first = cell.paragraphs[0]
        second = cell.add_paragraph()
        for paragraph, line in ((first, first_line), (second, second_line)):
            paragraph.paragraph_format.space_after = Pt(0)
            run = paragraph.add_run(line)
            run.font.name = "Arial"
            run.font.size = Pt(7.5)
            run.font.color.rgb = RGBColor.from_string(color.removeprefix("#"))
        properties = first._p.get_or_add_pPr()
        borders = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "12")
        bottom.set(qn("w:space"), "2")
        bottom.set(qn("w:color"), "334155")
        borders.append(bottom)
        properties.append(borders)

    def style_header(row: Any) -> None:
        for cell in row.cells:
            shade(cell, "E2E8F0")
            set_cell(cell, cell.text, bold=True, center=True)

    def set_meeting_type_divider(cell: Any) -> None:
        properties = cell._tc.get_or_add_tcPr()
        borders = properties.find(qn("w:tcBorders"))
        if borders is None:
            borders = OxmlElement("w:tcBorders")
            properties.append(borders)
        top = borders.find(qn("w:top"))
        if top is None:
            top = OxmlElement("w:top")
            borders.append(top)
        top.set(qn("w:val"), "single")
        top.set(qn("w:sz"), "24")
        top.set(qn("w:color"), "111827")

    def set_widths(table: Any, widths: list[float]) -> None:
        table.autofit = False
        for column, width in zip(table.columns, widths):
            column.width = Inches(width)
            for cell in column.cells:
                cell.width = Inches(width)

    def heading(value: str, *, size: float = 11) -> None:
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.space_before = Pt(6)
        paragraph.paragraph_format.space_after = Pt(3)
        run = paragraph.add_run(value)
        run.font.name = "Arial"
        run.font.size = Pt(size)
        run.bold = True

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(6)
    title_run = title.add_run(f"1H SHTYPI {report_day_label} (Shiko simbolet) - {target_date:%d.%m.%Y}")
    title_run.font.name = "Arial"
    title_run.font.size = Pt(16)
    title_run.bold = True

    board_questions, staff_questions = _one_h_checklists_for_day(checklist_date)
    staff_extra = staff_questions[len(ONE_H_STAFF_CHECKLIST):]
    board_extra = board_questions[len(ONE_H_BOARD_CHECKLIST):]
    extra_status_cell = document.add_table(rows=1, cols=1).cell(0, 0)
    shade(extra_status_cell, "FFF7F7")
    paragraph = extra_status_cell.paragraphs[0]
    for text, role in _extra_question_parts(checklist_date):
        run = paragraph.add_run(text)
        run.bold = role != "question"
        run.font.size = Pt(14 if role == "separator" else 12 if role == "label" else 10)
        run.font.color.rgb = RGBColor.from_string("B91C1C")

    for closing_section in closing_sections or []:
        heading(closing_section.title, size=11)
        for closing_table in closing_section.tables:
            heading(f"{closing_table.label}:", size=8.5)
            table = document.add_table(rows=1, cols=len(closing_table.columns))
            table.style = "Table Grid"
            project_has_titles = _closing_table_has_project_titles(closing_table)
            width_weights = {
                "NR": .28, "KUSH": .42, "DEP": .42, "AM/PM": .48, "LLOJI": .48,
                "PRJK": 1.0 if project_has_titles else .42,
                "NGA": 1.0, "NE": 1.0, "TITULLI": 5.6, "ARSYEJA": 1.25,
                "KOMENT": 1.55, "T/Y/O": .48, "DISK": .42, "NOTE": 8.0,
                "FROM": .58, "TIME": .58,
            }
            raw_widths = [width_weights.get(column, 1.0) for column in closing_table.columns]
            scale = 10.1 / sum(raw_widths)
            set_widths(table, [value * scale for value in raw_widths])
            for index, column in enumerate(closing_table.columns):
                set_cell(table.rows[0].cells[index], column, bold=True, center=True)
            style_header(table.rows[0])
            rows = closing_table.rows or [_empty_closing_table_row(closing_table)]
            for data in rows:
                row = table.add_row()
                background = _closing_row_color(data, closing_table)
                foreground = "FFFFFF" if background == DEADLINE_COLOR else "111827"
                for index, (column, value) in enumerate(zip(closing_table.columns, data.values)):
                    cell = row.cells[index]
                    cell_background, cell_foreground = background, foreground
                    if column == "T/Y/O" and _is_overdue_tyo_value(value):
                        cell_background, cell_foreground = DEADLINE_COLOR, "FFFFFF"
                    elif column == "DISK" and str(value).strip().upper() == "YES":
                        cell_background, cell_foreground = "DCFCE7", "166534"
                    elif column == "DISK" and str(value).strip().upper() == "NO":
                        cell_background, cell_foreground = "FEE2E2", "991B1B"
                    shade(cell, cell_background)
                    if column in {"NGA", "NE"} and "\n" in str(value):
                        set_stacked_date_cell(cell, value, color=cell_foreground)
                    else:
                        set_cell(
                            cell,
                            value,
                            bold=column == "DISK",
                            color=cell_foreground,
                            center=column in {"NR", "DISK"},
                        )

    marker_legend_cell = document.add_table(rows=1, cols=1).cell(0, 0)
    shade(marker_legend_cell, "EFF6FF")
    marker_legend_run = marker_legend_cell.paragraphs[0].add_run(_task_marker_legend_text())
    marker_legend_run.bold = True
    marker_legend_run.font.name = "Arial"
    marker_legend_run.font.size = Pt(7.5)
    marker_legend_run.font.color.rgb = RGBColor.from_string("0F2A5F")

    heading("TASKS", size=11)
    task_table = document.add_table(rows=1, cols=8)
    task_table.style = "Table Grid"
    set_widths(task_table, [.4, 1.35, 1.391, 1.391, 1.391, 1.391, 1.391, 1.391])
    for index, value in enumerate(["NR", "LLOJI DHE SLOTI", "TASK 1", "TASK 2", "TASK 3", "TASK 4", "TASK 5", "TASK 6"]):
        set_cell(task_table.rows[0].cells[index], value, bold=True, center=True)
    style_header(task_table.rows[0])
    for number, (label, values, personal) in enumerate(task_rows, 1):
        chunks = [values[index:index + 6] for index in range(0, len(values), 6)] or [[]]
        for chunk_index, chunk in enumerate(chunks):
            row = task_table.add_row()
            set_cell(row.cells[0], str(number) if chunk_index == 0 else "", center=True)
            set_cell(row.cells[1], label if chunk_index == 0 else "", bold=True)
            if chunk_index == 0:
                slot = _one_h_slot_from_label(label) or ("BLL" if label.strip() == "BLL" else None)
                missing = (missing_one_h_by_slot or {}).get(slot or "", [])
                if missing:
                    covered = set((project_covered_by_slot or {}).get(slot or "", []))
                    for group, color in (([x for x in missing if x not in covered], RGBColor(220, 38, 38)), ([x for x in missing if x in covered], RGBColor(21, 128, 61))):
                        if not group:
                            continue
                        missing_run = row.cells[1].paragraphs[0].add_run(f"\n{' • '.join(group)}")
                        missing_run.font.name = "Arial"
                        missing_run.font.size = Pt(7.5)
                        missing_run.bold = True
                        missing_run.font.color.rgb = color
            for item_index in range(6):
                if item_index >= len(chunk):
                    set_cell(row.cells[item_index + 2], "")
                    continue
                item = chunk[item_index]
                background = _task_cell_style(item, personal=personal, report_date=target_date)[1]
                foreground = "FFFFFF" if background == DEADLINE_COLOR else "111827"
                shade(row.cells[item_index + 2], background)
                set_task_cell(
                    row.cells[item_index + 2],
                    item,
                    item_index + 1 + chunk_index * 6,
                    personal=personal,
                    bold=background == DEADLINE_COLOR,
                    color=foreground,
                )

    for meeting_date, relative, dated_rows in meeting_sections or []:
        heading(f"TAKIMET {relative} - {meeting_date:%d.%m.%Y}", size=10)
        meeting_table = document.add_table(rows=1, cols=5)
        meeting_table.style = "Table Grid"
        set_widths(meeting_table, [1.4, 1.0, 1.1, 0.8, 5.8])
        for index, value in enumerate(["LLOJI", "KOHA", "USER", "PARA/PAS", "TAKIMET"]):
            set_cell(meeting_table.rows[0].cells[index], value, bold=True, center=True)
        style_header(meeting_table.rows[0])
        flattened_meetings = _flatten_meeting_rows(dated_rows)
        for index, (label, item) in enumerate(flattened_meetings, 1):
            row = meeting_table.add_row()
            set_cell(row.cells[0], label, bold=True)
            meeting_type = "internal" if "INT" in label.upper() else "external"
            meeting_fill = meeting_report_color(item, meeting_type=meeting_type)
            shade(row.cells[1], meeting_fill)
            shade(row.cells[2], meeting_fill)
            shade(row.cells[3], meeting_fill)
            shade(row.cells[4], meeting_fill)
            text_color = (
                CALENDAR_INTERNAL_TEXT_COLOR
                if _is_faded_calendar_internal(item, meeting_type=meeting_type)
                else "000000"
            )
            set_cell(
                row.cells[1],
                _meeting_time_display(item, meeting_type=meeting_type),
                color=text_color,
            )
            set_meeting_user_cell(row.cells[2], item, color=text_color)
            set_cell(row.cells[3], _meeting_relation(item) if meeting_type == "internal" else "", bold=True, center=True)
            set_cell(
                row.cells[4],
                f"{index}. {_meeting_title(item)}",
                bold=meeting_type == "external" or _is_manual_internal_meeting(item, meeting_type=meeting_type),
                color=text_color,
            )
            previous_label = flattened_meetings[index - 2][0] if index > 1 else ""
            if "INT" in label.upper() and "INT" not in previous_label.upper():
                for cell in row.cells:
                    set_meeting_type_divider(cell)

    heading("KOMENTE PER STAF", size=10)
    for line in _comment_write_in_lines(comment_initials or list(COMMENT_FIXED_INITIALS)):
        paragraph = document.add_paragraph(line)
        paragraph.paragraph_format.space_after = Pt(3)
        for run in paragraph.runs:
            run.font.name = "Arial"
            run.font.size = Pt(8)

    output = BytesIO()
    document.save(output)
    return (
        f"1H_SHTYPI_{target_date:%Y-%m-%d}.docx",
        output.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def _core_png_table_attachment(
    task_rows: list[tuple[str, list[dict[str, Any]], bool]], target_date: date,
    comment_initials: list[str] | None = None,
    meeting_sections: list[tuple[date, str, list[tuple[str, list[dict[str, Any]], bool]]]] | None = None,
    report_day_label: str = "SOT",
    missing_one_h_by_slot: dict[str, list[str]] | None = None,
    checklist_date: date | None = None,
    project_covered_by_slot: dict[str, list[str]] | None = None,
) -> tuple[str, bytes, str]:
    """Render the Today SHTYPI task grid with the same task-state colours."""
    margin = 28
    column_widths = [40, 228, *([267] * 6)]
    width = sum(column_widths) + (margin * 2)
    try:
        regular = ImageFont.truetype(os.getenv("PRIMEFLOW_REPORT_FONT_PATH", r"C:\Windows\Fonts\segoeui.ttf"), 16)
        bold = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 16)
        personal_time_font = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 20)
        small_bold = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 14)
        heading = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 27)
    except OSError:
        regular = bold = personal_time_font = small_bold = heading = ImageFont.load_default()
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1), "white"))

    def wrap(value: str, font: Any, max_width: int) -> list[str]:
        result: list[str] = []
        for source in str(value or "").splitlines() or [""]:
            words, current = source.split() or [""], ""
            for word in words:
                candidate = word if not current else f"{current} {word}"
                if current and measure.textlength(candidate, font=font) > max_width:
                    result.append(current)
                    current = word
                else:
                    current = candidate
            result.append(current)
        return result or [""]

    layout: list[tuple[str, list[dict[str, Any]], bool, int, int]] = []
    for label, values, personal in task_rows:
        chunks = [values[index:index + 6] for index in range(0, len(values), 6)] or [[]]
        for chunk_index, chunk in enumerate(chunks):
            label_line_count = len(wrap(label, bold, column_widths[1] - 12))
            slot = _one_h_slot_from_label(label) or ("BLL" if label.strip() == "BLL" else None)
            missing = (missing_one_h_by_slot or {}).get(slot or "", [])
            if missing:
                covered = set((project_covered_by_slot or {}).get(slot or "", []))
                for group in ([v for v in missing if v not in covered], [v for v in missing if v in covered]):
                    if group:
                        label_line_count += len(wrap(" • ".join(group), small_bold, column_widths[1] - 12))
            line_counts = [label_line_count]
            for item in chunk:
                # AM/PM and 08:00 share the top badge row. A deadline date
                # uses its own row at the bottom of the task card.
                badges = 1 + int(
                    bool(item.get("is_deadline_important") or item.get("isDeadlineImportant"))
                    and _task_due_day(item) is not None
                )
                line_counts.append(
                    len(wrap(_task_title(item, personal=personal), regular, column_widths[2] - 12)) + badges
                )
            layout.append((label, chunk, personal, chunk_index, max(44, 12 + max(line_counts) * 21)))

    board_questions, staff_questions = _one_h_checklists_for_day(checklist_date)
    staff_extra = staff_questions[len(ONE_H_STAFF_CHECKLIST):]
    board_extra = board_questions[len(ONE_H_BOARD_CHECKLIST):]
    placements, compact_height = layout_question_parts(
        _extra_question_parts(checklist_date),
        {"label": bold, "question": regular, "separator": heading}, width - 2 * margin - 20,
    )
    extra_status_height = compact_height + 16
    header_top, header_height = 92 + extra_status_height, 40
    comment_columns = comment_initials or list(COMMENT_FIXED_INITIALS)
    comment_lines = _comment_write_in_lines(comment_columns)
    comment_title_height, comment_line_height = 30, 28
    comment_block_height = 20 + comment_title_height + len(comment_lines) * comment_line_height
    meeting_pair = list((meeting_sections or [])[:2])
    if meeting_pair:
        while len(meeting_pair) < 2:
            meeting_pair.append((meeting_pair[0][0], "", []))
    meeting_half_width = (width - (margin * 2)) // 2
    meeting_label_width = 125
    meeting_time_width = 85
    meeting_user_width = 90
    meeting_relation_width = 95
    meeting_content_width = (
        meeting_half_width - meeting_label_width - meeting_time_width - meeting_user_width - meeting_relation_width
    )
    meeting_layout: list[
        tuple[tuple[str, dict[str, Any]] | None, tuple[str, dict[str, Any]] | None, int]
    ] = []
    if meeting_pair:
        left_rows = _flatten_meeting_rows(meeting_pair[0][2])
        right_rows = _flatten_meeting_rows(meeting_pair[1][2])
        meeting_count = max(len(left_rows), len(right_rows), 1)
        for index in range(meeting_count):
            left_entry = left_rows[index] if index < len(left_rows) else None
            right_entry = right_rows[index] if index < len(right_rows) else None

            def entry_height(entry: tuple[str, dict[str, Any]] | None) -> int:
                if entry is None:
                    return 44
                value = f"{index + 1}. {_report_text(_first_line(entry[1].get('title')))}"
                return max(44, len(wrap(value, regular, meeting_content_width - 18)) * 20 + 12)

            meeting_layout.append((left_entry, right_entry, max(entry_height(left_entry), entry_height(right_entry))))
    meeting_block_height = (
        20 + 42 + 38 + sum(row[2] for row in meeting_layout)
        if meeting_pair else 0
    )
    height = (
        header_top + header_height + sum(row[4] for row in layout)
        + meeting_block_height + comment_block_height + margin
    )
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    def draw_task_title_line(
        position: tuple[float, float], value: str, font: Any, default_color: str, *, red_background: bool
    ) -> None:
        cursor_x, cursor_y = position
        text_cursor = 0
        for match in WFC_TOKEN_RE.finditer(value):
            prefix = value[text_cursor:match.start()]
            if prefix:
                draw.text((cursor_x, cursor_y), prefix, fill=default_color, font=font)
                cursor_x += measure.textlength(prefix, font=font)
            token = match.group(0)
            token_width = measure.textlength(token, font=font)
            if red_background:
                draw.rounded_rectangle(
                    (cursor_x - 2, cursor_y - 1, cursor_x + token_width + 2, cursor_y + 19),
                    radius=2,
                    fill="#FFFFFF",
                )
            draw.text((cursor_x, cursor_y), token, fill=DEADLINE_COLOR, font=font)
            cursor_x += token_width
            text_cursor = match.end()
        suffix = value[text_cursor:]
        if suffix:
            draw.text((cursor_x, cursor_y), suffix, fill=default_color, font=font)

    draw.text((margin, 22), f"1H SHTYPI {report_day_label} (Shiko simbolet) - {target_date:%d.%m.%Y}", fill="#111827", font=heading)
    draw.text((margin, 59), "Current Common View state used by the 1H report", fill="#475569", font=regular)

    status_top = 88
    draw.rectangle(
        (margin, status_top, width - margin, status_top + extra_status_height - 4),
        fill="#FFF7F7",
        outline="#DC2626",
    )
    for part_x, part_y, text, part_font in placements:
        draw.text((margin + 10 + part_x, status_top + 6 + part_y), text, fill="#B91C1C", font=part_font)

    y, x = header_top, margin
    task_table_top = y
    for column, label in enumerate(["NR", "LLOJI DHE SLOTI"]):
        right = x + column_widths[column]
        draw.rectangle((x, y, right, y + header_height), fill="#F8FAFC", outline="#111827")
        draw.text((x + 6, y + 10), label, fill="#111827", font=bold)
        x = right
    tasks_right = width - margin
    draw.rectangle((x, y, tasks_right, y + header_height), fill="#F8FAFC", outline="#111827")
    tasks_bounds = draw.textbbox((0, 0), "TASKS", font=bold)
    tasks_width = tasks_bounds[2] - tasks_bounds[0]
    draw.text((x + (tasks_right - x - tasks_width) / 2, y + 10), "TASKS", fill="#111827", font=bold)
    y += header_height

    number = 0
    category_edges = [y]
    for layout_index, (label, chunk, personal, chunk_index, row_height) in enumerate(layout):
        if chunk_index == 0:
            number += 1
        x = margin
        for column, value in ((0, str(number) if chunk_index == 0 else ""), (1, label if chunk_index == 0 else "")):
            right = x + column_widths[column]
            draw.rectangle((x, y, right, y + row_height), fill="#FFFFFF", outline="#111827", width=2 if chunk_index == 0 else 1)
            if personal and column == 1 and value and "\n" in value:
                personal_title, personal_time = value.split("\n", 1)
                draw.text((x + 6, y + 6), personal_title, fill="#111827", font=bold)
                draw.text((x + 6, y + 27), personal_time, fill="#111827", font=personal_time_font)
            else:
                label_lines = wrap(value, bold, column_widths[column] - 12)
                for line_index, line in enumerate(label_lines):
                    draw.text((x + 6, y + 6 + line_index * 20), line, fill="#111827", font=bold)
                if column == 1 and chunk_index == 0:
                    slot = _one_h_slot_from_label(label) or ("BLL" if label.strip() == "BLL" else None)
                    missing = (missing_one_h_by_slot or {}).get(slot or "", [])
                    covered = set((project_covered_by_slot or {}).get(slot or "", []))
                    missing_index = 0
                    for group, color in (([v for v in missing if v not in covered], DEADLINE_COLOR), ([v for v in missing if v in covered], "#15803D")):
                        for missing_line in wrap(" • ".join(group), small_bold, column_widths[column] - 12) if group else []:
                            draw.text(
                                (x + 6, y + 8 + (len(label_lines) + missing_index) * 20),
                                missing_line, fill=color, font=small_bold,
                            )
                            missing_index += 1
            x = right
        for item_index in range(6):
            right = x + column_widths[2 + item_index]
            item = chunk[item_index] if item_index < len(chunk) else None
            fill, text_color, outline, outline_width = "#FFFFFF", "#111827", "#111827", 1
            if item is not None:
                fill = _task_cell_style(
                    item, personal=personal, report_date=target_date
                )[1]
                if fill == DEADLINE_COLOR:
                    text_color = "#FFFFFF"
                if _is_eight_am_task(item):
                    outline, outline_width = EIGHT_AM_BORDER_COLOR, 4
            draw.rectangle((x, y, right, y + row_height), fill=fill, outline=outline, width=outline_width)
            if item is not None:
                text_y = y + 6
                deadline = bool(item.get("is_deadline_important") or item.get("isDeadlineImportant"))
                due_day = _task_due_day(item) if deadline else None
                badge_right = right - 5
                if due_day:
                    date_label = "SOT" if due_day == target_date else due_day.strftime("%d.%m.%Y")
                    badge_width = int(measure.textlength(date_label, font=small_bold)) + (18 if due_day == target_date else 12)
                    badge_left = badge_right - badge_width
                    badge_bottom = y + row_height - 5
                    badge_top = badge_bottom - (26 if due_day == target_date else 23)
                    if due_day == target_date:
                        draw.rounded_rectangle(
                            (badge_left, badge_top, badge_right, badge_bottom),
                            radius=4,
                            fill="#DC2626",
                            outline="#991B1B",
                            width=1,
                        )
                        draw.text((badge_left + 6, badge_top + 3), date_label, fill="#FFFFFF", font=small_bold)
                    else:
                        draw.text((badge_left + 6, badge_top + 3), date_label, fill="#FFFFFF", font=small_bold)
                if _is_eight_am_task(item):
                    badge_width = int(measure.textlength("08:00", font=small_bold)) + 12
                    badge_left = badge_right - badge_width
                    draw.rounded_rectangle(
                        (badge_left, text_y, badge_right, text_y + 23),
                        radius=10,
                        fill="#DC2626",
                        outline="#B91C1C",
                        width=1,
                    )
                    draw.text((badge_left + 6, text_y + 3), "08:00", fill="#FFFFFF", font=small_bold)
                    badge_right = badge_left - 5
                period_label = _task_period_label(item)
                badge_width = int(measure.textlength(period_label, font=small_bold)) + 12
                badge_left = badge_right - badge_width
                draw.rounded_rectangle(
                    (badge_left, text_y, badge_right, text_y + 23),
                    radius=10,
                    fill="#E0F2FE",
                    outline="#BAE6FD",
                    width=1,
                )
                draw.text((badge_left + 6, text_y + 3), period_label, fill="#0369A1", font=small_bold)
                badge_right = badge_left - 5
                if _task_status(item) == "WAITING_CONFIRMATION":
                    badge_width = int(measure.textlength("WFC", font=small_bold)) + 12
                    badge_left = badge_right - badge_width
                    draw.rounded_rectangle(
                        (badge_left, text_y, badge_right, text_y + 23),
                        radius=10,
                        fill="#FFEDD5",
                        outline="#FB923C",
                        width=1,
                    )
                    draw.text((badge_left + 6, text_y + 3), "WFC", fill="#C2410C", font=small_bold)
                    badge_right = badge_left - 5
                marker_label = _task_marker_label(item)
                if marker_label:
                    badge_width = int(measure.textlength(marker_label, font=small_bold)) + 12
                    badge_left = badge_right - badge_width
                    draw.rounded_rectangle(
                        (badge_left, text_y, badge_right, text_y + 23),
                        radius=10,
                        fill="#EFF6FF",
                        outline="#93C5FD",
                        width=1,
                    )
                    draw.text((badge_left + 6, text_y + 3), marker_label, fill="#DC2626", font=small_bold)
                text_y += 28
                value = f"{item_index + 1 + chunk_index * 6}. {_task_title(item, personal=personal)}"
                marker_comment = _task_marker_comment(item)
                if marker_comment:
                    value = f"COM: {marker_comment}\n{value}"
                task_font = bold if fill == DEADLINE_COLOR else regular
                for line_index, line in enumerate(wrap(value, task_font, column_widths[2 + item_index] - 12)):
                    draw_task_title_line(
                        (x + 6, text_y + line_index * 20),
                        line,
                        task_font,
                        text_color,
                        red_background=fill == DEADLINE_COLOR,
                    )
            x = right
        y += row_height
        if layout_index == len(layout) - 1 or layout[layout_index + 1][3] == 0:
            category_edges.append(y)

    # Draw hierarchy lines last so task fills and special task outlines cannot hide them.
    draw.rectangle((margin, task_table_top, tasks_right, y), outline="#111827", width=4)
    draw.rectangle((margin, task_table_top, tasks_right, task_table_top + header_height), outline="#111827", width=4)
    for edge_y in category_edges:
        draw.line((margin, edge_y, tasks_right, edge_y), fill="#111827", width=3)

    if meeting_pair:
        y += 20
        meeting_table_top = y
        table_right = width - margin
        center = margin + meeting_half_width
        left_date, left_relative, _ = meeting_pair[0]
        right_date, right_relative, _ = meeting_pair[1]
        group_bottom = y + 42
        draw.rectangle((margin, y, center, group_bottom), fill="#EEF2FF", outline="#111827", width=4)
        draw.rectangle((center, y, table_right, group_bottom), fill="#EEF2FF", outline="#111827", width=4)
        left_header = f"TAKIMET {left_relative} - {left_date:%d.%m.%Y}"
        left_bounds = draw.textbbox((0, 0), left_header, font=bold)
        left_text_width = left_bounds[2] - left_bounds[0]
        draw.text(
            (margin + (meeting_half_width - left_text_width) / 2, y + 10),
            left_header,
            fill="#111827",
            font=bold,
        )
        right_header = f"TAKIMET {right_relative} - {right_date:%d.%m.%Y}" if right_relative else ""
        right_bounds = draw.textbbox((0, 0), right_header, font=bold)
        right_text_width = right_bounds[2] - right_bounds[0]
        draw.text(
            (center + (meeting_half_width - right_text_width) / 2, y + 10),
            right_header,
            fill="#111827",
            font=bold,
        )
        draw.line((center, y, center, group_bottom), fill=NON_ROUTINE_MEETING_BORDER_COLOR, width=5)
        y = group_bottom

        x = margin
        meeting_column_widths = [
            meeting_label_width,
            meeting_time_width,
            meeting_user_width,
            meeting_relation_width,
            meeting_content_width,
            meeting_label_width,
            meeting_time_width,
            meeting_user_width,
            meeting_relation_width,
            meeting_content_width,
        ]
        for column, label in enumerate(
            ["LLOJI", "KOHA", "USER", "PARA/PAS", "TAKIMET", "LLOJI", "KOHA", "USER", "PARA/PAS", "TAKIMET"]
        ):
            right = x + meeting_column_widths[column]
            draw.rectangle((x, y, right, y + 38), fill="#F8FAFC", outline="#111827", width=3)
            draw.text((x + 6, y + 9), label, fill="#111827", font=bold)
            x = right
        draw.line((center, y, center, y + 38), fill=NON_ROUTINE_MEETING_BORDER_COLOR, width=5)
        y += 38
        for meeting_index, (left_entry, right_entry, row_height) in enumerate(meeting_layout, 1):
            previous_left = meeting_layout[meeting_index - 2][0] if meeting_index > 1 else None
            previous_right = meeting_layout[meeting_index - 2][1] if meeting_index > 1 else None

            def starts_internal_group(
                entry: tuple[str, dict[str, Any]] | None,
                previous: tuple[str, dict[str, Any]] | None,
            ) -> bool:
                return bool(
                    entry
                    and "INT" in entry[0].upper()
                    and (previous is None or "INT" not in previous[0].upper())
                )

            x = margin
            row_bottom = y + row_height
            for entry in (left_entry, right_entry):
                label, item = entry if entry is not None else ("", None)
                label_right = x + meeting_label_width
                draw.rectangle((x, y, label_right, row_bottom), fill="#FFFFFF", outline="#111827")
                draw.text((x + 6, y + 8), label, fill="#111827", font=bold)
                time_right = label_right + meeting_time_width
                user_right = time_right + meeting_user_width
                relation_right = user_right + meeting_relation_width
                content_right = relation_right + meeting_content_width
                draw.rectangle((label_right, y, time_right, row_bottom), fill="#FFFFFF", outline="#111827")
                draw.rectangle((time_right, y, user_right, row_bottom), fill="#FFFFFF", outline="#111827")
                draw.rectangle((user_right, y, relation_right, row_bottom), fill="#FFFFFF", outline="#111827")
                draw.rectangle((relation_right, y, content_right, row_bottom), fill="#FFFFFF", outline="#111827")
                if item is not None:
                    meeting_type = "internal" if "INT" in label.upper() else "external"
                    meeting_fill = meeting_report_color(item, meeting_type=meeting_type)
                    text_color = (
                        CALENDAR_INTERNAL_TEXT_COLOR
                        if _is_faded_calendar_internal(item, meeting_type=meeting_type)
                        else "#111827"
                    )
                    outline = (
                        NON_ROUTINE_MEETING_BORDER_COLOR
                        if _is_non_routine_meeting(item)
                        or _is_manual_internal_meeting(item, meeting_type=meeting_type)
                        else "#111827"
                    )
                    outline_width = 3 if outline == NON_ROUTINE_MEETING_BORDER_COLOR else 1
                    draw.rectangle(
                        (label_right, y, time_right, row_bottom),
                        fill=meeting_fill,
                        outline=outline,
                        width=outline_width,
                    )
                    draw.rectangle(
                        (time_right, y, user_right, row_bottom),
                        fill=meeting_fill,
                        outline=outline,
                        width=outline_width,
                    )
                    draw.rectangle(
                        (user_right, y, relation_right, row_bottom),
                        fill=meeting_fill,
                        outline=outline,
                        width=outline_width,
                    )
                    draw.text((user_right + 8, y + 8), _meeting_relation(item) if meeting_type == "internal" else "", fill="#111827", font=bold)
                    draw.rectangle(
                        (relation_right, y, content_right, row_bottom),
                        fill=meeting_fill,
                        outline=outline,
                        width=outline_width,
                    )
                    draw.text(
                        (label_right + 6, y + 8),
                        _meeting_time_display(item, meeting_type=meeting_type),
                        fill=text_color,
                        font=regular,
                    )
                    user_x = time_right + 6
                    unavailable_users = {
                        str(value) for value in item.get("_unavailableUserInitials") or []
                    }
                    for user_index, (user_label, _) in enumerate(
                        _meeting_users(item) or [("-", None)]
                    ):
                        token = f"/{user_label}" if user_index else user_label
                        token_color = (
                            DEADLINE_COLOR if user_label in unavailable_users else text_color
                        )
                        draw.text(
                            (user_x, y + 8), token, fill=token_color, font=bold
                        )
                        user_x += measure.textlength(token, font=bold)
                    value = f"{meeting_index}. {_meeting_title(item)}"
                    lines = wrap(value, regular, meeting_content_width - 18)
                    for line_index, line in enumerate(lines):
                        draw.text(
                            (relation_right + 9, y + 8 + line_index * 20),
                            line,
                            fill=text_color,
                            font=(bold if meeting_type == "external" or _is_manual_internal_meeting(item, meeting_type=meeting_type) else regular),
                        )
                x = content_right
            draw.line((center, y, center, row_bottom), fill=NON_ROUTINE_MEETING_BORDER_COLOR, width=5)
            if starts_internal_group(left_entry, previous_left):
                draw.line((margin, y, center, y), fill="#111827", width=6)
            if starts_internal_group(right_entry, previous_right):
                draw.line((center, y, table_right, y), fill="#111827", width=6)
            y = row_bottom
        draw.rectangle((margin, meeting_table_top, table_right, y), outline="#111827", width=4)

    y += 20
    draw.text((margin, y + 3), "KOMENTE PER STAF", fill="#111827", font=bold)
    y += comment_title_height
    for line in comment_lines:
        draw.text((margin, y + 3), line, fill="#111827", font=regular)
        y += comment_line_height

    output = BytesIO()
    image.crop((0, 0, width, y + margin)).save(output, format="PNG", optimize=True)
    return f"1H-SHTYPI-Today-{target_date:%Y-%m-%d}.png", output.getvalue(), "image/png"


def _png_table_attachment(
    task_rows: list[tuple[str, list[dict[str, Any]], bool]], target_date: date,
    comment_initials: list[str] | None = None,
    meeting_sections: list[tuple[date, str, list[tuple[str, list[dict[str, Any]], bool]]]] | None = None,
    closing_sections: list[ClosingSection] | None = None,
    missing_one_h_by_slot: dict[str, list[str]] | None = None,
    report_day_label: str = "SOT",
    checklist_date: date | None = None,
    project_covered_by_slot: dict[str, list[str]] | None = None,
) -> tuple[str, bytes, str]:
    """Render one PNG containing the closing tables and the canonical task grid."""
    filename, core_bytes, mime_type = _core_png_table_attachment(
        task_rows,
        target_date,
        comment_initials,
        meeting_sections,
        report_day_label,
        missing_one_h_by_slot,
        checklist_date,
        project_covered_by_slot=project_covered_by_slot,
    )
    if not closing_sections:
        return filename, core_bytes, mime_type

    core = Image.open(BytesIO(core_bytes)).convert("RGB")
    width = core.width
    margin = 28
    try:
        regular = ImageFont.truetype(os.getenv("PRIMEFLOW_REPORT_FONT_PATH", r"C:\Windows\Fonts\segoeui.ttf"), 16)
        bold = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 16)
        section_font = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 20)
    except OSError:
        regular = bold = section_font = ImageFont.load_default()
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1), "white"))

    def wrap(value: str, font: Any, max_width: int) -> list[str]:
        lines: list[str] = []
        for source in str(value or "").splitlines() or [""]:
            current = ""
            for word in source.split() or [""]:
                candidate = word if not current else f"{current} {word}"
                if current and measure.textlength(candidate, font=font) > max_width:
                    lines.append(current)
                    current = word
                else:
                    current = candidate
            lines.append(current)
        return lines or [""]

    preferred = {
        "NR": 42, "KUSH": 62, "DEP": 58, "AM/PM": 68, "LLOJI": 68,
        "PRJK": 180, "NGA": 155, "NE": 155, "TITULLI": 760, "ARSYEJA": 230, "KOMENT": 285,
        "T/Y/O": 68, "DISK": 62, "NOTE": 1100, "FROM": 75, "TIME": 72,
    }
    layouts: list[tuple[ClosingSection, list[tuple[ClosingTable, list[int], list[tuple[ClosingTableRow, int]]]]]] = []
    closing_height = 16
    available = width - margin * 2
    for section in closing_sections:
        closing_height += 42
        table_layouts = []
        for table in section.tables:
            project_has_titles = _closing_table_has_project_titles(table)
            raw = [
                75 if column == "PRJK" and not project_has_titles else preferred.get(column, 160)
                for column in table.columns
            ]
            scale = available / sum(raw)
            widths = [max(48, int(value * scale)) for value in raw]
            widths[-1] += available - sum(widths)
            rendered_rows = table.rows or [_empty_closing_table_row(table)]
            row_layouts: list[tuple[ClosingTableRow, int]] = []
            for row in rendered_rows:
                line_count = max(
                    len(wrap(value, regular, widths[index] - 12))
                    for index, value in enumerate(row.values)
                )
                row_layouts.append((row, max(38, line_count * 20 + 12)))
            closing_height += 30 + 38 + sum(height for _, height in row_layouts) + 12
            table_layouts.append((table, widths, row_layouts))
        layouts.append((section, table_layouts))

    closing = Image.new("RGB", (width, closing_height), "white")
    draw = ImageDraw.Draw(closing)
    y = 10
    for section, table_layouts in layouts:
        draw.rectangle((margin, y, width - margin, y + 36), fill="#EEF2FF", outline="#2563EB", width=2)
        draw.text((margin + 10, y + 7), section.title, fill="#111827", font=section_font)
        y += 42
        for table, widths, row_layouts in table_layouts:
            draw.text((margin, y + 4), f"{table.label}:", fill="#111827", font=bold)
            y += 30
            x = margin
            for index, column in enumerate(table.columns):
                right = x + widths[index]
                draw.rectangle((x, y, right, y + 38), fill="#E2E8F0", outline="#111827")
                draw.text((x + 5, y + 9), column, fill="#111827", font=bold)
                x = right
            y += 38
            for row, row_height in row_layouts:
                x = margin
                background = _closing_row_color(row, table)
                foreground = "#FFFFFF" if background == DEADLINE_COLOR else "#111827"
                for index, (column, value) in enumerate(zip(table.columns, row.values)):
                    right = x + widths[index]
                    cell_bg, cell_fg = background, foreground
                    if column == "T/Y/O" and _is_overdue_tyo_value(value):
                        cell_bg, cell_fg = DEADLINE_COLOR, "#FFFFFF"
                    elif column == "DISK" and str(value).strip().upper() == "YES":
                        cell_bg, cell_fg = "#DCFCE7", "#166534"
                    elif column == "DISK" and str(value).strip().upper() == "NO":
                        cell_bg, cell_fg = "#FEE2E2", "#991B1B"
                    draw.rectangle(
                        (x, y, right, y + row_height),
                        fill=cell_bg,
                        outline=EIGHT_AM_BORDER_COLOR if row.is_eight_am else "#111827",
                        width=3 if row.is_eight_am else 1,
                    )
                    if column in {"NGA", "NE"} and "\n" in str(value):
                        first_line, second_line = str(value).split("\n", 1)
                        divider_y = y + row_height // 2
                        draw.line((x, divider_y, right, divider_y), fill="#334155", width=3)
                        draw.text((x + 6, y + 5), first_line, fill=cell_fg, font=regular)
                        draw.text((x + 6, divider_y + 5), second_line, fill=cell_fg, font=regular)
                    else:
                        for line_index, line in enumerate(wrap(value, bold if column == "DISK" else regular, widths[index] - 12)):
                            draw.text((x + 6, y + 6 + line_index * 20), line, fill=cell_fg, font=bold if column == "DISK" else regular)
                    x = right
                y += row_height
            y += 12

    combined = Image.new("RGB", (width, closing.height + core.height), "white")
    combined.paste(closing, (0, 0))
    combined.paste(core, (0, closing.height))
    output = BytesIO()
    combined.save(output, format="PNG", optimize=True)
    return f"1H-SHTYPI-{target_date:%Y-%m-%d}.png", output.getvalue(), mime_type


async def _build_print_report(
    target_date: date, *, include_attachment: bool = False, include_meetings: bool = True,
    include_png: bool = False, first_meeting_day_label: str = "NESER",
    report_day_label: str,
    payload: dict[str, Any] | None = None,
    db: AsyncSession | None = None,
    closing_report_day: date | None = None,
    include_docx: bool = False,
    checklist_date: date | None = None,
    next_day_payload: dict[str, Any] | None = None,
    include_completed_today: bool = False,
) -> dict[str, Any]:
    if payload is None:
        base_url = settings.PRIMEFLOW_API_BASE_URL
        if not base_url:
            raise RuntimeError("PRIMEFLOW_API_BASE_URL is required to generate 1H SHTYPI")
        client = PrimeFlowClient(
            base_url.rstrip("/"),
            settings.PRIMEFLOW_EMAIL or settings.ADMIN_EMAIL,
            settings.PRIMEFLOW_PASSWORD or settings.ADMIN_PASSWORD,
            settings.PRIMEFLOW_ACCESS_TOKEN,
        )
        payload = await client.common_view(target_date)
    items = payload.get("items") or {}
    comment_initials = _comment_user_initials(payload)
    missing_one_h_by_slot = _missing_one_h_initials(payload, target_date)
    project_covered_by_slot = _project_covered_initials(payload, target_date)
    personal_covered_by_slot = _personal_covered_initials(payload, target_date)
    missing_blocked_users = _missing_blocked_initials(payload, target_date)
    missing_at_16 = set(missing_one_h_by_slot.get("16:00", []))
    missing_blocked_with_one_h_at_16 = [value for value in missing_blocked_users if value not in missing_at_16]
    missing_blocked_set = set(missing_blocked_users)
    missing_one_h_at_16_with_blocked = [
        value for value in missing_one_h_by_slot.get("16:00", []) if value not in missing_blocked_set
    ]
    task_rows = _task_rows(items, target_date, include_completed_today=include_completed_today, users=payload.get("users"))
    ga_summary = build_ga_summary(payload, [(item, personal) for _, values, personal in task_rows for item in values])
    meeting_dates = [target_date, next_working_day(target_date)] if include_meetings else []
    next_meeting_payload = next_day_payload or payload
    if len(meeting_dates) > 1 and payload.get("week_end"):
        try:
            payload_week_end = date.fromisoformat(str(payload["week_end"])[:10])
        except ValueError:
            payload_week_end = meeting_dates[-1]
        if meeting_dates[-1] > payload_week_end and next_day_payload is None:
            base_url = settings.PRIMEFLOW_API_BASE_URL
            if not base_url:
                raise RuntimeError("PRIMEFLOW_API_BASE_URL is required to load next-day meetings")
            next_meeting_payload = await PrimeFlowClient(
                base_url.rstrip("/"),
                settings.PRIMEFLOW_EMAIL or settings.ADMIN_EMAIL,
                settings.PRIMEFLOW_PASSWORD or settings.ADMIN_PASSWORD,
                settings.PRIMEFLOW_ACCESS_TOKEN,
            ).common_view(meeting_dates[-1])
    meeting_sections = [
        (
            meeting_date,
            (
                first_meeting_day_label
                if index == 0
                else ("NESER" if first_meeting_day_label == "SOT" else "PAS NESER")
            ),
            [
                (label, values, False)
                for label, values in _meeting_rows(
                    (payload if meeting_date == target_date else next_meeting_payload).get("items") or {},
                    meeting_date,
                )
            ],
        )
        for index, meeting_date in enumerate(meeting_dates)
    ]
    meeting_rows = meeting_sections[0][2] if meeting_sections else []
    closing_sections = (
        await build_tomorrow_closing_sections(db, closing_report_day)
        if db is not None and closing_report_day is not None
        else []
    )
    report_date = target_date.strftime("%d.%m.%Y")
    summary_sections = [ClosingSection(title=GA_SUMMARY_TITLE, tables=[ClosingTable(
        label="F / GA / P / M2",
        columns=["PERSONAT"],
        rows=[ClosingTableRow(values=[summary_text(ga_summary)])],
    )])] if ga_summary else []
    attachment_sections = [*summary_sections, *closing_sections]
    report_title = subject_for(target_date, report_day_label)
    board_questions, staff_questions = _one_h_checklists_for_day(checklist_date)
    html_body = f"""<!doctype html><html><body style=\"margin:0;color:#000;font-family:Arial,sans-serif\">
<div data-report-intro="true">
<div style=\"text-align:center;font-size:20px;font-weight:700;margin:0 0 12px\">{report_title}</div>
{_one_h_checklists_html(checklist_date)}{_task_marker_legend_html()}</div>{summary_html(ga_summary)}{_closing_sections_html(closing_sections)}{_html_table(task_rows, report_date=target_date, missing_one_h_by_slot=missing_one_h_by_slot, missing_blocked_initials=missing_blocked_users, missing_blocked_with_one_h_at_16_initials=missing_blocked_with_one_h_at_16, missing_one_h_at_16_with_blocked_initials=missing_one_h_at_16_with_blocked, project_covered_by_slot=project_covered_by_slot, personal_covered_by_slot=personal_covered_by_slot)}{_dated_meetings_html(meeting_sections)}{_comments_table_html(comment_initials)}</body></html>"""
    content_html = (
        '<div data-today-print-report="true" style="margin:18px 0 14px">'
        + re.sub(r"^.*?<body[^>]*>|</body>.*$", "", html_body, flags=re.S)
        + "</div>"
    )

    def plain_checklist_lines(
        questions: tuple[tuple[str, str], ...], *, day_specific: bool = False
    ) -> list[str]:
        return [
            f"{_checklist_question_number(checklist_date if day_specific else None, index, question)} {question}"
            + (f" ({description})" if description else "")
            for index, (question, description) in enumerate(questions, 1)
        ]

    day_label = _day_specific_question_label(checklist_date)
    staff_extra = staff_questions[len(ONE_H_STAFF_CHECKLIST):]
    board_extra = board_questions[len(ONE_H_BOARD_CHECKLIST):]
    plain_rows = [
        report_title,
        "",
        *(
            [
                "".join(text for text, _ in _extra_question_parts(checklist_date)),
                "",
            ]
            if day_label else []
        ),
        "",
        "STAFF - HAPAT PER 1H",
        *plain_checklist_lines(staff_questions[:len(ONE_H_STAFF_CHECKLIST)]),
        "",
        "PYETJET PER 1H - BORD",
        *plain_checklist_lines(ONE_H_BOARD_FOLLOW_UP_CHECKLIST),
        "",
        *plain_checklist_lines(ONE_H_BOARD_PRIMARY_CHECKLIST),
        "",
    ]
    plain_rows.extend(_closing_sections_plain_text(attachment_sections))
    plain_rows.extend([
        "",
        "LEGJENDA: ? - PYETJE/PAQARTESI / "
        "! - DYSHIM/ NUK KUPTOHET DET / "
        "!!! - KLIENT/URGJENT / "
        "SHARE - DET QE DUHET SCREENSHARE ME GA / "
        "👁 - KËRKON MONITORIM NGA DIKUSH TJETËR / X - MBYLL DETYREN / "
        "M2 - DOREZIM DERI NE PAUZE / M3 - DOREZIM DERI NE FUND TE DITES / "
        "M2/3 - DOREZIM EDHE NE M2 EDHE M3 / "
        "GENT - PYETJE/SQARIM ME GENTIN / KA - PYETJE/SQARIM ME KA / "
        "GA - PYETJE/SQARIM ME GA / F - DET FIZIKISHT / BZ1N1",
        "",
        "TASKS",
    ])
    for label, values, personal in task_rows:
        slot = _one_h_slot_from_label(label) or ("BLL" if label.strip() == "BLL" else None)
        missing = missing_blocked_users if slot == "BLL" else missing_one_h_by_slot.get(slot or "", [])
        covered = set(project_covered_by_slot.get(slot or "", [])) | set(personal_covered_by_slot.get(slot or "", []))
        unjustified = [value for value in missing if value not in covered]
        justified = [value for value in missing if value in covered]
        missing_label = f" [PA {'BLL' if slot == 'BLL' else '1H'}: {', '.join(unjustified)}]" if unjustified else ""
        if justified:
            period = "AM" if slot in {"10:00", "11:00", "11:50"} else "PM"
            missing_label += f" [ME DETYRË PROJEKTI/PERSONALE {period}: {', '.join(justified)}]"
        plain_rows.append(
            f"{label}{missing_label}: "
            + "; ".join(
                f"[{_task_period_label(item)}]"
                f"{' [WFC]' if _task_status(item) == 'WAITING_CONFIRMATION' else ''}"
                f"{f' {_task_marker_text_token(item)}' if _task_marker_label(item) else ''} "
                f"{f'COM: {_task_marker_comment(item)} | ' if _task_marker_comment(item) else ''}"
                f"{_task_title(item, personal=personal)}"
                for item in values
            )
        )
    if include_meetings:
        for meeting_date, relative, dated_rows in meeting_sections:
            plain_rows.append("")
            plain_rows.append(f"MEETINGS - {relative} - {meeting_date:%d.%m.%Y}")
            for label, values, _ in dated_rows:
                plain_rows.append(
                    f"{label}: " + "; ".join(
                        f"[{_meeting_user_initials(item)}] "
                        + (f"[{_meeting_relation(item)}] " if "INT" in label.upper() and _meeting_relation(item) else "")
                        + f"{_meeting_title(item)} {item.get('time') or ''}".strip()
                        for item in values
                    )
                )
    plain_rows.extend([
        "",
        "KOMENTE PER STAF",
        *_comment_write_in_lines(comment_initials),
    ])
    report: dict[str, Any] = {
        "subject": report_title,
        "target_date": target_date.isoformat(),
        "html": html_body,
        "content_html": content_html,
        "plain_text": "\n".join(plain_rows),
        "ga_task_summary": [row.model_dump() for row in ga_summary],
    }
    if include_attachment:
        attachment_missing_by_slot = {**missing_one_h_by_slot, "BLL": missing_blocked_users}
        attachment_covered_by_slot = {key: list(dict.fromkeys([*values, *personal_covered_by_slot.get(key, [])])) for key, values in project_covered_by_slot.items()}
        attachment_covered_by_slot["BLL"].extend(missing_blocked_with_one_h_at_16)
        attachment_covered_by_slot["16:00"].extend(missing_one_h_at_16_with_blocked)
        attachments = [
            _excel_table_attachment(
                task_rows, meeting_rows, target_date, include_meetings=include_meetings,
                comment_initials=comment_initials, meeting_sections=meeting_sections,
                closing_sections=attachment_sections,
                checklist_date=checklist_date,
                missing_one_h_by_slot=attachment_missing_by_slot,
                project_covered_by_slot=attachment_covered_by_slot,
                report_day_label=report_day_label,
            )
        ]
        if include_png:
            attachments.append(
                _png_table_attachment(
                    task_rows,
                    target_date,
                    comment_initials,
                    meeting_sections,
                    attachment_sections,
                    attachment_missing_by_slot,
                    report_day_label,
                    checklist_date,
                    project_covered_by_slot=attachment_covered_by_slot,
                )
            )
        if include_docx:
            attachments.append(
                _docx_table_attachment(
                    task_rows,
                    target_date,
                    closing_sections=attachment_sections,
                    meeting_sections=meeting_sections,
                    comment_initials=comment_initials,
                    missing_one_h_by_slot=attachment_missing_by_slot,
                    project_covered_by_slot=attachment_covered_by_slot,
                    report_day_label=report_day_label,
                    checklist_date=checklist_date,
                )
            )
        report["attachments"] = attachments
    return report


async def build_tomorrow_print_report(
    delivery_date: date, *, include_attachment: bool = False, db: AsyncSession | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_date = next_working_day(delivery_date)
    return await _build_print_report(
        target_date, include_attachment=include_attachment, include_meetings=True,
        include_png=include_attachment,
        include_docx=include_attachment,
        report_day_label="NESER",
        db=db,
        closing_report_day=delivery_date,
        checklist_date=target_date,
        payload=payload,
    )


async def build_today_print_report(
    report_date: date, *, include_attachment: bool = False, payload: dict[str, Any] | None = None,
    next_day_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build today's task grid plus today/next-working-day meeting sections."""
    return await _build_print_report(
        report_date, include_attachment=include_attachment, include_meetings=True,
        include_png=True, first_meeting_day_label="SOT", report_day_label="SOT",
        checklist_date=report_date, payload=payload, next_day_payload=next_day_payload,
        include_completed_today=True,
    )


async def send_tomorrow_print_report(report: dict[str, Any], recipients: dict[str, list[str]]) -> dict[str, Any]:
    recipients = ensure_required_shtypi_recipient(recipients)
    password = os.getenv("EMAIL_PASSWORD") or settings.EMAIL_PASSWORD
    if not password:
        raise ValueError("Missing email configuration: EMAIL_PASSWORD")
    return await GmailService(sender=REPORT_SENDER_EMAIL, password=password).send_verified(
        report["subject"], recipients, report["plain_text"], report["html"], attachments=report.get("attachments")
    )
