from __future__ import annotations

import json
import re
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.common_entry import CommonEntry
from app.models.department import Department
from app.models.enums import CommonApprovalStatus, CommonCategory, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.services.common_leave import parse_common_view_annual_leave
from app.services.daily_report_logic import ko_rule_applies_for_task, parse_ko_user_id


REPORT_VERSION = "1.2"
DEFAULT_TIMEZONE = "Europe/Tirane"
VALID_STATUSES = {"TODO", "IN_PROGRESS", "WAITING_CLIENT", "WAITING_CONFIRMATION", "DONE"}
VALID_PRIORITIES = {"NORMAL", "HIGH"}
TECHNICAL_MARKUP = re.compile(r"\[\[\s*/?\s*(?:added|done)\s*\]\]", re.IGNORECASE)
NUMBERED_INSTRUCTION = re.compile(r"(?:^|\s)(?:\d+[.)]|[-•])\s+", re.MULTILINE)
OFFICIAL_PROJECT_IDENTIFIERS = {
    "WKF", "VS", "MST", "ASC", "TT", "FRG", "ARC", "CRM", "SMM",
}
ROUTINE_PATTERNS = (
    re.compile(r"\bPLNF\s+JAV\b", re.I),
    re.compile(r"\b1H\b", re.I),
    re.compile(r"^\s*(?:BLL|R1|P:|WFC|BKP)\b", re.I),
    re.compile(r"\b(?:daily|weekly|monthly|ditor|javor|mujor)\s+(?:report|raport)", re.I),
    re.compile(r"\b(?:report|raport)\s+(?:daily|weekly|monthly|ditor|javor|mujor)", re.I),
    re.compile(r"^\s*(?:TAK(?:\s+(?:INT|EXT))?|takim|meeting)\b", re.I),
    re.compile(r"^\s*(?:KO\d?|kontroll|check)\b", re.I),
    re.compile(r"^\s*(?:EM|email)\b", re.I),
    re.compile(r"^\s*RAP\b", re.I),
    re.compile(r"\b(?:routine|rutin[ëe]|reminder|kujtes[ëe])\b", re.I),
    re.compile(r"\b(?:payment|pages[ëe]|invoice|fatur[ëe])\s+(?:reminder|kujtes[ëe])\b", re.I),
    re.compile(r"\b(?:applicant|aplikant)\w*\s+(?:check|kontroll)", re.I),
    re.compile(r"\bCOMMON\s+VIEW\b.*\b(?:admin|check|kontroll)", re.I),
    re.compile(r"\bGDPR\b.*\b(?:reminder|kujtes[ëe]|check|kontroll)", re.I),
)

AUDIT_CHECK_REGISTRY: dict[str, tuple[str, ...]] = {
    "date": ("TASK_DATE_MISSING", "TASK_DATE_OUTSIDE_WEEK", "DATE_RANGE_INCONSISTENT"),
    "status": ("STATUS_MISSING", "STATUS_INVALID"),
    "priority": ("PRIORITY_MISSING", "PRIORITY_INVALID"),
    "KO1": ("KO_OWNER_MISSING",),
    "KO2": ("KO_OWNER_MISSING",),
    "Total/Mesatare": ("TOTAL_AVERAGE_INVALID",),
    "1H": ("ONE_H_SLOT_MISSING",),
    "R1": ("R1_FORMAT_INVALID",),
    "P:": ("PERSONAL_FORMAT_INVALID",),
    "WFC": ("WFC_FORMAT_INVALID",),
    "BLL": ("BLL_FORMAT_INVALID",),
    "BKP": ("BKP_FORMAT_INVALID",),
}
APPROVED_CHECK_DIMENSIONS = tuple(AUDIT_CHECK_REGISTRY)
TASK_INTRINSIC_RULES = frozenset({
    "STATUS_MISSING", "STATUS_INVALID", "PRIORITY_MISSING", "PRIORITY_INVALID",
    "DATE_RANGE_INCONSISTENT", "KO_OWNER_MISSING", "TOTAL_AVERAGE_INVALID",
    "ONE_H_SLOT_MISSING", "R1_FORMAT_INVALID", "PERSONAL_FORMAT_INVALID",
    "WFC_FORMAT_INVALID", "BLL_FORMAT_INVALID", "BKP_FORMAT_INVALID",
    "TITLE_TOO_LONG", "MULTIPLE_INSTRUCTIONS_IN_TITLE",
    "UNOFFICIAL_ABBREVIATION", "AI_TITLE_SEMANTIC", "SYSTEM_FOCUS_SELECTED",
})
OCCURRENCE_SPECIFIC_RULES = frozenset({
    "TASK_ON_ANNUAL_LEAVE", "TASK_DATE_MISSING", "TASK_DATE_OUTSIDE_WEEK",
})
TITLE_RELATED_RULES = frozenset({
    "TITLE_TOO_LONG", "MULTIPLE_INSTRUCTIONS_IN_TITLE",
    "UNOFFICIAL_ABBREVIATION", "AI_TITLE_SEMANTIC",
})


@dataclass(slots=True)
class AuditTaskOccurrence:
    user_id: uuid.UUID
    employee: str
    department: str
    task_id: uuid.UUID | None
    task_date: date | None
    title: str
    description: str | None = None
    internal_notes: str | None = None
    status: str | None = None
    priority: str | None = None
    finish_period: str | None = None
    start_date: datetime | date | None = None
    due_date: datetime | date | None = None
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    project_priority: bool = False
    is_system: bool = False
    system_template_origin_id: uuid.UUID | None = None
    is_1h_report: bool = False
    one_h_report_slot: str | None = None
    is_bllok: bool = False
    is_r1: bool = False
    is_personal: bool = False
    is_deadline_important: bool = False
    ko_required: bool = False
    ko_user_id_present: bool = False
    source: str = "Weekly Planner"


@dataclass(slots=True)
class AuditError:
    employee: str
    department: str
    task_id: str | None
    task_date: date | None
    current_title: str
    problem: str
    proposed_title: str
    correction: str
    rule_code: str
    severity: str
    project_id: str | None = None
    move_to_notes: str = ""
    weekly_focus: str = ""
    source: str = "Weekly Planner"


@dataclass(slots=True)
class FocusDecision:
    label: str
    source: str
    source_task_id: str | None
    source_project_id: str | None
    score: int


@dataclass(slots=True)
class PersonAudit:
    user_id: str
    employee: str
    department: str
    leave_status: str
    focus: str
    focus_source: str
    focus_source_task_id: str | None
    focus_source_project_id: str | None
    task_count: int
    error_count: int
    critical_count: int
    high_count: int
    assessment: str
    required_action: str


@dataclass(slots=True)
class WeeklyPlanningAuditReport:
    week_start: date
    week_end: date
    generated_at: datetime
    timezone: str
    slot: str
    people: list[PersonAudit] = field(default_factory=list)
    errors: list[AuditError] = field(default_factory=list)
    title_cleanup: list[dict[str, Any]] = field(default_factory=list)
    excluded_full_leave: list[str] = field(default_factory=list)
    partial_leave_users: list[str] = field(default_factory=list)
    abbreviations: dict[str, str] = field(default_factory=dict)
    abbreviation_version: str = "2026.1"
    abbreviation_source: str = "Official PX abbreviation dictionary"
    abbreviation_updated_at: str = "2026-07-31"
    ai_status: str = "not_needed"
    ai_model: str | None = None
    executed_checks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "week_start": self.week_start.isoformat(),
            "week_end": self.week_end.isoformat(),
            "generated_at": self.generated_at.isoformat(),
            "timezone": self.timezone,
            "slot": self.slot,
            "people": [asdict(person) for person in self.people],
            "errors": [
                {
                    **asdict(error),
                    "task_date": error.task_date.isoformat() if error.task_date else None,
                }
                for error in self.errors
            ],
            "title_cleanup": self.title_cleanup,
            "excluded_full_leave": self.excluded_full_leave,
            "partial_leave_users": self.partial_leave_users,
            "abbreviations": self.abbreviations,
            "abbreviation_version": self.abbreviation_version,
            "abbreviation_source": self.abbreviation_source,
            "abbreviation_updated_at": self.abbreviation_updated_at,
            "ai_status": self.ai_status,
            "ai_model": self.ai_model,
            "executed_checks": self.executed_checks,
        }


def validate_report_integrity(report: WeeklyPlanningAuditReport) -> None:
    """Fail generation if summary/detail counts or unique cleanup keys diverge."""
    detail_by_person: dict[str, list[AuditError]] = defaultdict(list)
    for error in report.errors:
        detail_by_person[error.employee].append(error)
    for person in report.people:
        rows = detail_by_person.get(person.employee, [])
        if person.error_count != len(rows):
            raise ValueError(f"Error count mismatch for {person.employee}")
        if person.critical_count != sum(item.severity == "CRITICAL" for item in rows):
            raise ValueError(f"Critical count mismatch for {person.employee}")
        if person.high_count != sum(item.severity == "HIGH" for item in rows):
            raise ValueError(f"High count mismatch for {person.employee}")
    cleanup_keys = [
        (item.get("user_id") or item.get("employee"), item.get("task_id"))
        for item in report.title_cleanup
    ]
    if len(cleanup_keys) != len(set(cleanup_keys)):
        raise ValueError("Duplicate person/task rows in title cleanup")
    missing_checks = set(APPROVED_CHECK_DIMENSIONS) - set(report.executed_checks)
    if missing_checks:
        raise ValueError(f"Approved checks were not executed: {sorted(missing_checks)}")


def clean_technical_markup(value: str | None) -> str:
    """Remove PrimeFlow diff tags while preserving every character inside them."""
    without_tags = TECHNICAL_MARKUP.sub("", value or "")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in without_tags.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def monday_of_next_working_week(now: datetime | None = None, timezone_name: str = DEFAULT_TIMEZONE) -> date:
    tz = ZoneInfo(timezone_name)
    local_now = now.astimezone(tz) if now and now.tzinfo else (now.replace(tzinfo=tz) if now else datetime.now(tz))
    days_until_next_monday = (7 - local_now.date().weekday()) % 7
    if days_until_next_monday == 0:
        days_until_next_monday = 7
    return local_now.date() + timedelta(days=days_until_next_monday)


def normalize_week_start(value: date | None, timezone_name: str = DEFAULT_TIMEZONE) -> date:
    week_start = value or monday_of_next_working_week(timezone_name=timezone_name)
    if week_start.weekday() != 0:
        raise ValueError("week_start must be a Monday")
    return week_start


def _as_date(value: datetime | date | None, timezone_name: str = DEFAULT_TIMEZONE) -> date | None:
    if isinstance(value, datetime):
        if value.tzinfo:
            return value.astimezone(ZoneInfo(timezone_name)).date()
        return value.date()
    return value


def load_px_abbreviations(override: dict[str, str] | None = None) -> tuple[dict[str, str], dict[str, str]]:
    path = Path(__file__).resolve().parents[1] / "data" / "px_abbreviations.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = {str(key).strip(): str(value).strip() for key, value in payload["entries"].items()}
    if override:
        entries = {str(key).strip(): str(value).strip() for key, value in override.items()}
    metadata = {
        "version": str(payload["version"]),
        "source": str(payload["source"]),
        "updated_at": str(payload["updated_at"]),
    }
    return entries, metadata


def suggested_concise_title(value: str | None, *, max_length: int = 100) -> str:
    cleaned = clean_technical_markup(value)
    cleaned = re.sub(r"(?<![\w/])RREG(?![\w/])", "Rregullim", cleaned, flags=re.I)
    if not cleaned:
        return ""
    first_line = cleaned.splitlines()[0]
    first_line = re.split(r"\s+(?:\d+[.)]|[-•])\s+", first_line, maxsplit=1)[0].strip()
    first_line = re.split(r"\s+(?:Hapat|Steps|Shënim|Note|Pyetje)\s*:", first_line, maxsplit=1, flags=re.I)[0].strip()
    if len(first_line) <= max_length:
        return first_line
    shortened = first_line[:max_length].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return shortened or first_line[:max_length]


def split_title_and_notes(value: str | None, *, max_length: int = 100) -> tuple[str, str]:
    """Return a report-safe title and the source text that belongs in notes."""
    cleaned = clean_technical_markup(value)
    if not cleaned:
        return "", ""
    lines = cleaned.splitlines()
    proposed = suggested_concise_title(cleaned, max_length=max_length)
    first_line = lines[0]
    remainder: list[str] = []
    if len(proposed) < len(first_line):
        suffix = first_line[len(proposed):].strip(" -:;,")
        if suffix:
            remainder.append(suffix)
    remainder.extend(lines[1:])
    return proposed, "\n".join(item for item in remainder if item).strip()


def extract_px_abbreviations(title: str | None, abbreviations: dict[str, str]) -> list[str]:
    """Match only official PX phrases in a title, longest first, without substrings."""
    normalized = clean_technical_markup(title)
    candidates: list[tuple[int, int, str]] = []
    for abbreviation in sorted(abbreviations, key=lambda value: (-len(value), value.casefold())):
        pattern = re.compile(rf"(?<!\w){re.escape(abbreviation)}(?!\w)", re.I)
        candidates.extend((match.start(), match.end(), abbreviation) for match in pattern.finditer(normalized))
    selected: list[tuple[int, int, str]] = []
    for start, end, abbreviation in sorted(candidates, key=lambda item: (item[0], -(item[1] - item[0]), item[2].casefold())):
        if any(not (end <= left or start >= right) for left, right, _ in selected):
            continue
        selected.append((start, end, abbreviation))
    return [item[2] for item in sorted(selected)]


def _uses_unofficial_abbreviation(occurrence: AuditTaskOccurrence) -> bool:
    title = clean_technical_markup(occurrence.title).upper()
    # RREG has repeatedly been used as an invented abbreviation; it is explicitly
    # not in the official dictionary. Unknown project codes remain untouched.
    return bool(re.search(r"(?<![\w/])RREG(?![\w/])", title))


def _ai_title_introduces_unknown_abbreviation(
    proposed_title: str,
    current_title: str,
    official_abbreviations: dict[str, str],
) -> bool:
    proposed_tokens = set(re.findall(r"\b[A-ZÇË][A-ZÇË0-9]{1,7}\b", proposed_title))
    current_tokens = set(re.findall(r"\b[A-ZÇË][A-ZÇË0-9]{1,7}\b", current_title))
    allowed = {key.upper() for key in official_abbreviations}
    return bool(proposed_tokens - current_tokens - allowed)


def validated_ai_errors_by_user(
    ai_result: dict[str, Any] | None,
    occurrences: Iterable[AuditTaskOccurrence],
    official_abbreviations: dict[str, str],
) -> dict[uuid.UUID, list[AuditError]]:
    """Convert only grounded, complete AI title findings into auditable errors."""
    occurrences_by_task_id: dict[str, list[AuditTaskOccurrence]] = defaultdict(list)
    for occurrence in occurrences:
        if occurrence.task_id is not None:
            occurrences_by_task_id[str(occurrence.task_id)].append(occurrence)
    accepted: dict[uuid.UUID, list[AuditError]] = defaultdict(list)
    for item in ((ai_result or {}).get("errors") or []):
        if not isinstance(item, dict):
            continue
        matching_occurrences = occurrences_by_task_id.get(str(item.get("task_id") or ""), [])
        problem = clean_technical_markup(str(item.get("problem") or ""))
        correction = clean_technical_markup(str(item.get("correction") or ""))
        proposed_raw = clean_technical_markup(str(item.get("proposed_title") or ""))
        severity = str(item.get("severity") or "").upper()
        if not matching_occurrences or not problem or not correction or not proposed_raw:
            continue
        if severity not in {"HIGH", "MEDIUM", "LOW"}:
            continue
        for occurrence in matching_occurrences:
            proposed_title = suggested_concise_title(proposed_raw)
            if _ai_title_introduces_unknown_abbreviation(
                proposed_title,
                clean_technical_markup(occurrence.title),
                official_abbreviations,
            ):
                continue
            _, move_to_notes = split_title_and_notes(occurrence.title)
            accepted[occurrence.user_id].append(AuditError(
                employee=occurrence.employee,
                department=occurrence.department,
                task_id=str(occurrence.task_id),
                project_id=str(occurrence.project_id) if occurrence.project_id else None,
                task_date=occurrence.task_date,
                current_title=clean_technical_markup(occurrence.title),
                problem=problem,
                proposed_title=proposed_title,
                correction=correction,
                rule_code="AI_TITLE_SEMANTIC",
                severity=severity,
                move_to_notes=move_to_notes,
                source="AI semantic audit",
            ))
    return dict(accepted)


def is_routine_or_system_work(occurrence: AuditTaskOccurrence) -> bool:
    if occurrence.is_system or occurrence.system_template_origin_id is not None:
        return True
    if occurrence.is_1h_report or occurrence.is_bllok or occurrence.is_r1 or occurrence.is_personal:
        return True
    title = clean_technical_markup(occurrence.title)
    focus_texts = tuple(filter(None, (title, clean_technical_markup(occurrence.project_name))))
    if re.search(r"^\s*(?:BLL\b|R1\b|P\s*:|WFC\b|BKP\b)", title, re.I):
        return True
    if re.search(r"\bPLNF\s+JAV\b|\b1H\s+(?:report|raport|reporting|raportim)", title, re.I):
        return True
    return any(pattern.search(value) for value in focus_texts for pattern in ROUTINE_PATTERNS)


def is_planner_work(occurrence: AuditTaskOccurrence) -> bool:
    """Planning presence is broader than focus eligibility."""
    return bool(occurrence.task_id) and not (
        occurrence.is_system or occurrence.system_template_origin_id is not None
    )


def select_weekly_focus(occurrences: Iterable[AuditTaskOccurrence]) -> FocusDecision:
    groups: dict[str, dict[str, Any]] = {}
    for occurrence in occurrences:
        if is_routine_or_system_work(occurrence):
            continue
        cleaned = clean_technical_markup(occurrence.title)
        label = clean_technical_markup(occurrence.project_name) if occurrence.project_id else cleaned.splitlines()[0]
        if not label:
            continue
        group_key = (
            f"project:{occurrence.project_id}"
            if occurrence.project_id
            else f"task:{occurrence.task_id or label.casefold()}"
        )
        group = groups.setdefault(
            group_key,
            {
                "label": label,
                "days": set(),
                "count": 0,
                "high": 0,
                "deadline": 0,
                "project_priority": 0,
                "task_ids": [],
                "project_id": occurrence.project_id,
                "earliest": occurrence.task_date or date.max,
                "valid_priority": False,
            },
        )
        if occurrence.task_date:
            group["days"].add(occurrence.task_date)
        group["count"] += 1
        group["high"] += int((occurrence.priority or "").upper() == "HIGH")
        group["deadline"] += int(occurrence.is_deadline_important)
        group["project_priority"] += int(occurrence.project_priority)
        group["earliest"] = min(group["earliest"], occurrence.task_date or date.max)
        group["valid_priority"] = group["valid_priority"] or (
            (occurrence.priority or "").upper() in VALID_PRIORITIES
        )
        if occurrence.task_id:
            group["task_ids"].append(str(occurrence.task_id))

    if not groups:
        return FocusDecision(
            label="Nuk është përcaktuar fokus jo-sistem",
            source="Nuk ka detyrë/projekt jo-sistem të vlefshëm",
            source_task_id=None,
            source_project_id=None,
            score=0,
        )

    ranked: list[tuple[int, int, int, int, int, int, date, str, str, dict[str, Any]]] = []
    for key, group in groups.items():
        stable_task_id = min(group["task_ids"]) if group["task_ids"] else key
        ranked.append((
            -int(group["project_id"] is not None),
            -int(group["project_priority"] > 0),
            -len(group["days"]),
            -group["count"],
            -group["high"],
            -group["deadline"],
            group["earliest"],
            stable_task_id,
            key,
            group,
        ))
    ranked.sort()
    _, _, negative_days, negative_count, negative_high, negative_deadline, _, _, _, winner = ranked[0]
    source_task_id = sorted(winner["task_ids"])[0] if winner["task_ids"] else None
    source_project_id = str(winner["project_id"]) if winner["project_id"] else None
    source_label = f"Project {source_project_id}" if source_project_id else f"Task {source_task_id or winner['label']}"
    source = (
        f"{source_label}; {len(winner['days'])} ditë, {winner['count']} paraqitje, "
        f"HIGH={winner['high']}, deadline={winner['deadline']}"
    )
    score = (
        int(winner["project_id"] is not None) * 1_000_000
        + int(winner["project_priority"] > 0) * 100_000
        + (-negative_days) * 10_000
        + (-negative_count) * 100
        + (-negative_high) * 10
        + (-negative_deadline)
    )
    return FocusDecision(
        label=winner["label"],
        source=source,
        source_task_id=source_task_id,
        source_project_id=source_project_id,
        score=score,
    )


def _error(
    occurrence: AuditTaskOccurrence,
    *,
    problem: str,
    correction: str,
    rule: str,
    severity: str,
) -> AuditError:
    cleaned_title = clean_technical_markup(occurrence.title)
    _, move_to_notes = split_title_and_notes(occurrence.title)
    return AuditError(
        employee=occurrence.employee,
        department=occurrence.department,
        task_id=str(occurrence.task_id) if occurrence.task_id else None,
        project_id=str(occurrence.project_id) if occurrence.project_id else None,
        task_date=occurrence.task_date,
        current_title=cleaned_title,
        problem=problem,
        proposed_title=suggested_concise_title(occurrence.title),
        correction=correction,
        rule_code=rule,
        severity=severity,
        move_to_notes=move_to_notes,
        source=occurrence.source,
    )


def should_require_priority(occurrence: AuditTaskOccurrence) -> bool:
    """Task.priority is mandatory for real Task rows, but not synthetic/system rows."""
    return bool(
        occurrence.task_id
        and not occurrence.is_system
        and occurrence.system_template_origin_id is None
    )


def should_require_due_date(occurrence: AuditTaskOccurrence) -> bool:
    """Planner visibility is authoritative; due_date is nullable in the Task model.

    Some legitimate PCM KO occurrences are derived from production/project dates, so
    this audit must not turn a nullable implementation detail into a planning error.
    """
    del occurrence
    return False


def validate_task_occurrence(
    occurrence: AuditTaskOccurrence,
    *,
    week_start: date,
    leave_dates: set[date],
    official_abbreviations: dict[str, str],
    executed_checks: set[str] | None = None,
) -> list[AuditError]:
    del official_abbreviations  # Dictionary is intentionally passed to keep this validator version-aware.
    if executed_checks is not None:
        executed_checks.update(APPROVED_CHECK_DIMENSIONS)
    errors: list[AuditError] = []
    week_end = week_start + timedelta(days=4)
    cleaned_title = clean_technical_markup(occurrence.title)
    task_day = occurrence.task_date

    if task_day is None:
        errors.append(_error(
            occurrence,
            problem="Detyra nuk ka datë të vlefshme planifikimi.",
            correction="Vendos një datë planifikimi nga e hëna deri të premten.",
            rule="TASK_DATE_MISSING",
            severity="CRITICAL",
        ))
    elif task_day.weekday() >= 5 or task_day < week_start or task_day > week_end:
        errors.append(_error(
            occurrence,
            problem="Detyra është jashtë javës së raportuar e hënë–e premte.",
            correction="Vendos datën brenda javës së raportuar ose largoje nga ky plan.",
            rule="TASK_DATE_OUTSIDE_WEEK",
            severity="HIGH",
        ))

    status = (occurrence.status or "").upper()
    if not status:
        errors.append(_error(
            occurrence, problem="Mungon statusi i detyrës.",
            correction="Vendos një status të vlefshëm.", rule="STATUS_MISSING", severity="HIGH",
        ))
    elif status not in VALID_STATUSES:
        errors.append(_error(
            occurrence, problem=f"Statusi '{occurrence.status}' nuk është i vlefshëm.",
            correction="Përdor TODO, IN_PROGRESS, WAITING_CLIENT, WAITING_CONFIRMATION ose DONE.",
            rule="STATUS_INVALID", severity="HIGH",
        ))

    if should_require_priority(occurrence):
        priority = (occurrence.priority or "").upper()
        if not priority:
            errors.append(_error(
                occurrence, problem="Mungon prioriteti i detyrës.",
                correction="Vendos prioritetin NORMAL ose HIGH.", rule="PRIORITY_MISSING", severity="MEDIUM",
            ))
        elif priority not in VALID_PRIORITIES:
            errors.append(_error(
                occurrence, problem=f"Prioriteti '{occurrence.priority}' nuk është i vlefshëm.",
                correction="Përdor prioritetin NORMAL ose HIGH.", rule="PRIORITY_INVALID", severity="MEDIUM",
            ))

    start_day = _as_date(occurrence.start_date)
    due_day = _as_date(occurrence.due_date)
    if should_require_due_date(occurrence) and due_day is None:
        errors.append(_error(
            occurrence, problem="Detyra nuk ka datë përfundimi.",
            correction="Vendos due date sipas planit javor.", rule="DUE_DATE_MISSING", severity="HIGH",
        ))
    if start_day and due_day and start_day > due_day:
        errors.append(_error(
            occurrence, problem="Data e fillimit është pas datës së përfundimit.",
            correction="Korrigjo start date dhe due date që të jenë në rend kronologjik.",
            rule="DATE_RANGE_INCONSISTENT", severity="HIGH",
        ))

    if task_day and task_day in leave_dates:
        errors.append(_error(
            occurrence,
            problem="Detyra është planifikuar në ditën e Pushimit Vjetor.",
            correction="Zhvendose detyrën në një ditë aktive ose largoje nga planifikimi i kësaj jave.",
            rule="TASK_ON_ANNUAL_LEAVE",
            severity="HIGH",
        ))

    if occurrence.ko_required and not occurrence.ko_user_id_present:
        errors.append(_error(
            occurrence, problem="Mungon personi përgjegjës i kontrollit KO për këtë detyrë.",
            correction="Vendos KO sipas rregullit ekzistues të Weekly Planner/Common View.",
            rule="KO_OWNER_MISSING", severity="HIGH",
        ))

    task_text = "\n".join(
        value for value in (
            cleaned_title,
            clean_technical_markup(occurrence.description),
            clean_technical_markup(occurrence.internal_notes),
        ) if value
    )
    if occurrence.ko_required:
        has_total = bool(re.search(r"\bTotal\s*[:=]\s*\d+", task_text, re.I))
        has_average = bool(re.search(r"\bMesatare\s*[:=]\s*\d+(?:[.,]\d+)?", task_text, re.I))
        if not (has_total and has_average):
            errors.append(_error(
                occurrence, problem="Formati kërkon vlera numerike për Total dhe Mesatare.",
                correction="Shto 'Total: <numër>' dhe 'Mesatare: <numër>' në fushën përkatëse.",
                rule="TOTAL_AVERAGE_INVALID", severity="MEDIUM",
            ))

    if occurrence.is_1h_report and not occurrence.one_h_report_slot:
        errors.append(_error(
            occurrence, problem="Detyra 1H nuk ka slot raportimi.",
            correction="Zgjidh një nga slotet zyrtare të raportimit 1H.",
            rule="ONE_H_SLOT_MISSING", severity="HIGH",
        ))

    format_rules = [
        (occurrence.is_r1, r"^R1\s*:", "R1_FORMAT_INVALID", "Titulli R1 duhet të fillojë me 'R1:'."),
        (occurrence.is_personal, r"^P\s*:", "PERSONAL_FORMAT_INVALID", "Titulli personal duhet të fillojë me 'P:'."),
        (bool(re.match(r"^\s*WFC\b", cleaned_title, re.I)), r"^WFC\s*:", "WFC_FORMAT_INVALID", "Titulli WFC duhet të fillojë me 'WFC:'."),
        (occurrence.is_bllok, r"^BLL\s*:", "BLL_FORMAT_INVALID", "Titulli BLL duhet të fillojë me 'BLL:'."),
        (bool(re.match(r"^\s*BKP\b", cleaned_title, re.I)), r"^BKP\s*:", "BKP_FORMAT_INVALID", "Titulli BKP duhet të fillojë me 'BKP:'."),
    ]
    for applies, pattern, code, correction in format_rules:
        if applies and not re.match(pattern, cleaned_title, re.I):
            errors.append(_error(
                occurrence, problem="Formati i titullit nuk përputhet me prefiksin zyrtar.",
                correction=correction, rule=code, severity="MEDIUM",
            ))

    if len(cleaned_title) > 120:
        errors.append(_error(
            occurrence, problem="Titulli është tepër i gjatë.",
            correction="Mbaj në titull vetëm personin, projektin/klientin dhe veprimin; kalo pjesën tjetër në Description/Notes.",
            rule="TITLE_TOO_LONG", severity="LOW",
        ))
    if len(NUMBERED_INSTRUCTION.findall(cleaned_title)) >= 2 or len(cleaned_title.splitlines()) > 1:
        errors.append(_error(
            occurrence, problem="Titulli përmban disa udhëzime ose hapa.",
            correction="Mbaj një titull të shkurtër dhe zhvendos hapat e plotë në Description/Notes.",
            rule="MULTIPLE_INSTRUCTIONS_IN_TITLE", severity="LOW",
        ))
    if _uses_unofficial_abbreviation(occurrence):
        errors.append(_error(
            occurrence, problem="Titulli përdor shkurtesën jozyrtare 'RREG'.",
            correction="Përdor fjalën e plotë 'Rregullim'; mos shpik shkurtesa që mungojnë në fjalorin PX.",
            rule="UNOFFICIAL_ABBREVIATION", severity="LOW",
        ))
    return errors


def leave_status_label(leave_dates: set[date]) -> str:
    if not leave_dates:
        return "Jo"
    ordered = sorted(leave_dates)
    ranges: list[tuple[date, date]] = []
    start = end = ordered[0]
    for item in ordered[1:]:
        if item == end + timedelta(days=1):
            end = item
        else:
            ranges.append((start, end))
            start = end = item
    ranges.append((start, end))
    labels = [
        left.strftime("%d.%m.%Y") if left == right else f"{left:%d.%m.%Y}–{right:%d.%m.%Y}"
        for left, right in ranges
    ]
    return "Po, parcial: " + ", ".join(labels)


def partition_users_by_full_week_leave(
    users: Iterable[Any],
    *,
    leave_dates_by_user: dict[uuid.UUID, set[date]],
    week_start: date,
) -> tuple[list[Any], list[Any]]:
    week_dates = {week_start + timedelta(days=offset) for offset in range(5)}
    included: list[Any] = []
    excluded: list[Any] = []
    for user in users:
        if leave_dates_by_user.get(user.id, set()) == week_dates:
            excluded.append(user)
        else:
            included.append(user)
    return included, excluded


def is_reportable_person(user: User, excluded_accounts: Iterable[str] | None = None) -> bool:
    """Include active employees, never the real Admin/technical accounts."""
    if not bool(getattr(user, "is_active", True)):
        return False
    role = getattr(user, "role", None)
    role_value = getattr(role, "value", role)
    if str(role_value or "").upper() == UserRole.ADMIN.value:
        return False
    username = str(getattr(user, "username", "") or "").strip().casefold()
    email_local = str(getattr(user, "email", "") or "").partition("@")[0].strip().casefold()
    full_name = str(getattr(user, "full_name", "") or "").strip().casefold()
    if username in {"admin", "administrator", "technical.admin", "technical_admin"}:
        return False
    if email_local in {"admin", "administrator", "technical.admin", "technical_admin"}:
        return False
    if full_name in {"admin", "administrator", "technical admin"}:
        return False
    excluded = {str(value).strip().casefold() for value in (excluded_accounts or []) if str(value).strip()}
    identifiers = {
        str(value).strip().casefold()
        for value in (getattr(user, "id", None), getattr(user, "username", None), getattr(user, "email", None))
        if value is not None and str(value).strip()
    }
    return not bool(identifiers & excluded)


def _is_technical_account(user: User) -> bool:
    """Backward-compatible alias; exclusions are now explicit configuration only."""
    configured = settings.WEEKLY_PLANNING_AUDIT_EXCLUDED_ACCOUNTS.split(",")
    return not is_reportable_person(user, configured)


def audit_error_dedup_key(user_id: uuid.UUID, error: AuditError) -> tuple[str, ...]:
    if error.rule_code in OCCURRENCE_SPECIFIC_RULES:
        return (
            str(user_id), error.task_id or "", error.task_date.isoformat() if error.task_date else "",
            error.rule_code,
        )
    return (str(user_id), error.task_id or "", error.rule_code)


def _occurrence_key(item: AuditTaskOccurrence) -> tuple[str, str, str]:
    return (
        str(item.user_id),
        str(item.task_id or clean_technical_markup(item.title).casefold()),
        item.task_date.isoformat() if item.task_date else "",
    )


async def _planner_occurrences(
    db: AsyncSession,
    *,
    week_start: date,
    timezone_name: str,
) -> list[AuditTaskOccurrence]:
    # Imported lazily to avoid router-package initialization cycles while still
    # using the exact read-only Weekly Planner query as the source of occurrences.
    from app.api.routers.planners import weekly_table_planner

    planner_user = SimpleNamespace(
        id=uuid.UUID(int=0),
        role=UserRole.MANAGER,
        department_id=None,
        full_name="Weekly Planning Audit",
    )
    planner = await weekly_table_planner(
        week_start=week_start,
        department_id=None,
        is_this_week=False,
        db=db,
        user=planner_user,
    )
    raw: list[dict[str, Any]] = []
    for department in planner.departments:
        for day in department.days:
            for person in day.users:
                for period, projects in (("AM", person.am_projects), ("PM", person.pm_projects)):
                    for project in projects:
                        for task in project.tasks:
                            raw.append({
                                "user_id": person.user_id,
                                "employee": person.user_name,
                                "department": department.department_name,
                                "task_date": day.date,
                                "task_id": task.task_id,
                                "project_id": project.project_id,
                                "project_name": project.project_title,
                                "finish_period": task.finish_period or period,
                                "is_system": False,
                                "source": "Weekly Planner / project",
                            })
                for period, tasks in (("AM", person.am_fast_tasks), ("PM", person.pm_fast_tasks)):
                    for task in tasks:
                        raw.append({
                            "user_id": person.user_id,
                            "employee": person.user_name,
                            "department": department.department_name,
                            "task_date": day.date,
                            "task_id": task.task_id,
                            "title": task.title,
                            "finish_period": task.finish_period or period,
                            "is_system": False,
                            "source": "Weekly Planner / fast task",
                        })
                for period, tasks in (("AM", person.am_system_tasks), ("PM", person.pm_system_tasks)):
                    for task in tasks:
                        raw.append({
                            "user_id": person.user_id,
                            "employee": person.user_name,
                            "department": department.department_name,
                            "task_date": day.date,
                            "task_id": task.task_id,
                            "title": task.title,
                            "finish_period": task.finish_period or period,
                            "is_system": True,
                            "source": "Weekly Planner / system task",
                        })

    task_ids = sorted({item["task_id"] for item in raw if item.get("task_id")}, key=str)
    task_map: dict[uuid.UUID, Task] = {}
    if task_ids:
        tasks = (await db.execute(select(Task).where(Task.work_staff_filter()).where(Task.id.in_(task_ids)))).scalars().all()
        task_map = {task.id: task for task in tasks}
    project_ids = sorted({item["project_id"] for item in raw if item.get("project_id")}, key=str)
    project_map: dict[uuid.UUID, Project] = {}
    if project_ids:
        projects = (await db.execute(select(Project).where(Project.id.in_(project_ids)))).scalars().all()
        project_map = {project.id: project for project in projects}
    department_rows = (await db.execute(select(Department.id, Department.code))).all()
    department_code_by_id = {department_id: code for department_id, code in department_rows}

    occurrences: dict[tuple[str, str, str], AuditTaskOccurrence] = {}
    for item in raw:
        task = task_map.get(item.get("task_id"))
        project = project_map.get(item.get("project_id"))
        task_department_id = task.department_id if task else None
        project_department_id = project.department_id if project else None
        department_code = department_code_by_id.get(task_department_id or project_department_id)
        ko_required = bool(
            task and ko_rule_applies_for_task(task, project=project, dept_code=department_code)
        )
        occurrence = AuditTaskOccurrence(
            user_id=item["user_id"],
            employee=item["employee"],
            department=item["department"],
            task_id=item.get("task_id"),
            task_date=item["task_date"],
            title=(task.title if task else item.get("title") or ""),
            description=task.description if task else None,
            internal_notes=task.internal_notes if task else None,
            status=task.status if task else None,
            priority=task.priority if task else None,
            finish_period=task.finish_period if task else item.get("finish_period"),
            start_date=task.start_date if task else None,
            due_date=task.due_date if task else None,
            project_id=item.get("project_id") or (task.project_id if task else None),
            project_name=(project.title if project else item.get("project_name")),
            is_system=bool(item["is_system"]),
            system_template_origin_id=task.system_template_origin_id if task else None,
            is_1h_report=bool(task.is_1h_report) if task else False,
            one_h_report_slot=task.one_h_report_slot if task else None,
            is_bllok=bool(task.is_bllok) if task else False,
            is_r1=bool(task.is_r1) if task else False,
            is_personal=bool(task.is_personal) if task else False,
            is_deadline_important=bool(task.is_deadline_important) if task else False,
            ko_required=ko_required,
            ko_user_id_present=bool(task and parse_ko_user_id(task.internal_notes)),
            source=item["source"],
        )
        occurrences[_occurrence_key(occurrence)] = occurrence
    return sorted(
        occurrences.values(),
        key=lambda item: (item.department.casefold(), item.employee.casefold(), item.task_date or date.min, item.title.casefold()),
    )


def audit_person_occurrences(
    user: Any,
    *,
    department: str,
    occurrences: list[AuditTaskOccurrence],
    leave_dates: set[date],
    week_start: date,
    abbreviations: dict[str, str],
    ai_errors: Iterable[AuditError] = (),
    executed_checks: set[str] | None = None,
) -> tuple[PersonAudit, list[AuditError], list[dict[str, Any]]]:
    employee = user.full_name or user.username or user.email
    focus = select_weekly_focus(occurrences)
    user_errors = list(ai_errors)
    for occurrence in occurrences:
        occurrence.employee = employee
        occurrence.department = department
        detected = validate_task_occurrence(
            occurrence,
            week_start=week_start,
            leave_dates=leave_dates,
            official_abbreviations=abbreviations,
            executed_checks=executed_checks,
        )
        for item in detected:
            item.weekly_focus = focus.label
        user_errors.extend(detected)

    planned_work = [item for item in occurrences if is_planner_work(item)]

    deduplicated: dict[tuple[str, ...], AuditError] = {}
    for item in user_errors:
        deduplicated[audit_error_dedup_key(user.id, item)] = item
    user_errors = sorted(
        deduplicated.values(),
        key=lambda item: (item.task_date or date.min, item.task_id or "", item.rule_code),
    )

    cleanup_rows: list[dict[str, Any]] = []
    title_occurrences: dict[str, AuditTaskOccurrence] = {}
    for occurrence in occurrences:
        title_key = str(occurrence.task_id) if occurrence.task_id else clean_technical_markup(occurrence.title).casefold()
        title_occurrences.setdefault(title_key, occurrence)
    for occurrence in title_occurrences.values():
        task_id = str(occurrence.task_id) if occurrence.task_id else None
        task_title_errors = [
            item for item in user_errors
            if item.task_id == task_id and item.rule_code in TITLE_RELATED_RULES
        ]
        if not task_title_errors:
            continue
        proposed_title, move_to_notes = split_title_and_notes(occurrence.title)
        cleanup_rows.append({
            "user_id": str(user.id),
            "employee": employee,
            "task_id": task_id,
            "current_title": clean_technical_markup(occurrence.title),
            "title_problem": "; ".join(dict.fromkeys(item.problem for item in task_title_errors)),
            "proposed_title": proposed_title,
            "move_to_notes": move_to_notes,
            "used_abbreviations": ", ".join(extract_px_abbreviations(proposed_title, abbreviations)),
            "rule_source": ", ".join(dict.fromkeys(item.rule_code for item in task_title_errors)),
        })

    critical = sum(item.severity == "CRITICAL" for item in user_errors)
    high = sum(item.severity == "HIGH" for item in user_errors)
    person = PersonAudit(
        user_id=str(user.id),
        employee=employee,
        department=department,
        leave_status=leave_status_label(leave_dates),
        focus=focus.label,
        focus_source=focus.source,
        focus_source_task_id=focus.source_task_id,
        focus_source_project_id=focus.source_project_id,
        task_count=len({str(item.task_id) for item in planned_work if item.task_id}),
        error_count=len(user_errors),
        critical_count=critical,
        high_count=high,
        assessment="Në rregull" if not user_errors else ("Kritike" if critical else "Kërkon korrigjim"),
        required_action="Asnjë veprim" if not user_errors else "Korrigjo gabimet para fillimit të javës.",
    )
    return person, user_errors, cleanup_rows


async def build_weekly_planning_audit(
    db: AsyncSession,
    *,
    week_start: date | None = None,
    slot: str = "10:30",
    timezone_name: str = DEFAULT_TIMEZONE,
    generated_at: datetime | None = None,
    abbreviation_override: dict[str, str] | None = None,
    abbreviation_version: str | None = None,
) -> WeeklyPlanningAuditReport:
    normalized_start = normalize_week_start(week_start, timezone_name)
    week_dates = {normalized_start + timedelta(days=offset) for offset in range(5)}
    tz = ZoneInfo(timezone_name)
    generated = generated_at or datetime.now(tz)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=tz)

    users = (await db.execute(
        select(User).where(User.work_staff_filter()).where(User.is_active.is_(True)).order_by(User.full_name, User.id)
    )).scalars().all()
    excluded_accounts = settings.WEEKLY_PLANNING_AUDIT_EXCLUDED_ACCOUNTS.split(",")
    users = [user for user in users if is_reportable_person(user, excluded_accounts)]
    departments = (await db.execute(select(Department))).scalars().all()
    department_map = {department.id: department.name for department in departments}

    leave_entries = (await db.execute(
        select(CommonEntry).where(
            CommonEntry.category == CommonCategory.annual_leave,
            CommonEntry.approval_status == CommonApprovalStatus.approved,
        )
    )).scalars().all()
    leave_dates_by_user: dict[uuid.UUID, set[date]] = defaultdict(set)
    for entry in leave_entries:
        start, end, full_day, _, _, _, is_all_users = parse_common_view_annual_leave(entry)
        if not full_day or end < normalized_start or start > normalized_start + timedelta(days=4):
            continue
        affected_dates = {day for day in week_dates if start <= day <= end}
        target_ids = [user.id for user in users] if is_all_users else [entry.assigned_to_user_id or entry.created_by_user_id]
        for user_id in target_ids:
            if user_id:
                leave_dates_by_user[user_id].update(affected_dates)

    included_users, excluded_users = partition_users_by_full_week_leave(
        users,
        leave_dates_by_user=leave_dates_by_user,
        week_start=normalized_start,
    )
    occurrences = await _planner_occurrences(db, week_start=normalized_start, timezone_name=timezone_name)
    included_ids = {user.id for user in included_users}
    occurrences = [item for item in occurrences if item.user_id in included_ids]
    by_user: dict[uuid.UUID, list[AuditTaskOccurrence]] = defaultdict(list)
    for occurrence in occurrences:
        by_user[occurrence.user_id].append(occurrence)
    for user in included_users:
        employee = user.full_name or user.username or user.email
        department = department_map.get(user.department_id, "Pa departament")
        for occurrence in by_user.get(user.id, []):
            occurrence.employee = employee
            occurrence.department = department

    abbreviations, abbreviation_meta = load_px_abbreviations(abbreviation_override)
    ai_payload = {
        "week_start": normalized_start.isoformat(),
        "week_end": (normalized_start + timedelta(days=4)).isoformat(),
        "official_px_abbreviations": abbreviations,
        "people": [
            {
                "user_id": str(user.id),
                "tasks": [
                    {
                        "task_id": str(item.task_id) if item.task_id else None,
                        "date": item.task_date.isoformat() if item.task_date else None,
                        "title": clean_technical_markup(item.title),
                        "description": clean_technical_markup(item.description)[:1500],
                        "notes": clean_technical_markup(item.internal_notes)[:800],
                        "project_id": str(item.project_id) if item.project_id else None,
                        "project_name": clean_technical_markup(item.project_name),
                        "is_system": item.is_system or item.system_template_origin_id is not None,
                        "is_routine": is_routine_or_system_work(item),
                    }
                    for item in by_user.get(user.id, [])
                    if not item.is_system and item.system_template_origin_id is None
                ],
            }
            for user in included_users
        ],
    }
    from app.services.weekly_planning_audit_ai import analyze_weekly_planning_audit

    ai_result, ai_status = await analyze_weekly_planning_audit(ai_payload)
    ai_errors_by_user = validated_ai_errors_by_user(ai_result, occurrences, abbreviations)
    errors: list[AuditError] = []
    people: list[PersonAudit] = []
    title_cleanup: list[dict[str, Any]] = []
    executed_checks: set[str] = set(APPROVED_CHECK_DIMENSIONS)
    for user in included_users:
        department = department_map.get(user.department_id, "Pa departament")
        person, user_errors, user_cleanup = audit_person_occurrences(
            user,
            department=department,
            occurrences=by_user.get(user.id, []),
            leave_dates=leave_dates_by_user[user.id],
            week_start=normalized_start,
            abbreviations=abbreviations,
            ai_errors=ai_errors_by_user.get(user.id, []),
            executed_checks=executed_checks,
        )
        people.append(person)
        errors.extend(user_errors)
        title_cleanup.extend(user_cleanup)

    report = WeeklyPlanningAuditReport(
        week_start=normalized_start,
        week_end=normalized_start + timedelta(days=4),
        generated_at=generated,
        timezone=timezone_name,
        slot=slot,
        people=sorted(people, key=lambda item: (item.department.casefold(), item.employee.casefold())),
        errors=sorted(errors, key=lambda item: (item.department.casefold(), item.employee.casefold(), item.task_date or date.min, item.rule_code)),
        title_cleanup=sorted(title_cleanup, key=lambda item: (item["employee"].casefold(), item["task_id"] or "")),
        excluded_full_leave=sorted((user.full_name or user.username or user.email) for user in excluded_users),
        partial_leave_users=sorted(
            (user.full_name or user.username or user.email)
            for user in included_users if leave_dates_by_user[user.id]
        ),
        abbreviations=abbreviations,
        abbreviation_version=abbreviation_version or abbreviation_meta["version"],
        abbreviation_source=(
            "Admin XLSX import (audited in PrimeFlow)" if abbreviation_override else abbreviation_meta["source"]
        ),
        abbreviation_updated_at=(
            generated.date().isoformat() if abbreviation_override else abbreviation_meta["updated_at"]
        ),
        ai_status=ai_status,
        ai_model=settings.WEEKLY_PLANNING_AUDIT_AI_MODEL if ai_status == "used" else None,
        executed_checks=[item for item in APPROVED_CHECK_DIMENSIONS if item in executed_checks],
    )
    validate_report_integrity(report)
    return report
