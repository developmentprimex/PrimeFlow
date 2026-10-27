from __future__ import annotations

import hashlib
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from time import perf_counter
from typing import Any
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_department_access
from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models.common_entry import CommonEntry
from app.models.department import Department
from app.models.enums import CommonApprovalStatus, CommonCategory, UserRole
from app.models.ga_note import GaNote
from app.models.plan_note import PlanNote
from app.models.meeting import Meeting, MeetingParticipant
from app.models.project import Project
from app.services.project_classification import has_mst_identity, is_vs_or_vl_project
from app.services.common_leave import parse_common_view_annual_leave
from app.models.system_task_template import SystemTaskTemplate
from app.models.system_task_template_alignment_user import SystemTaskTemplateAlignmentUser
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_one_h_report_slot import TaskOneHReportSlot
from app.models.user import User
from app.services.one_h_slots import effective_slot_date
from app.services.one_h_project_coverage import is_project_coverage_department, project_task_periods
from app.services.meeting_occurrence import meeting_display_dates, meeting_occurs_on_date
from app.services.microsoft_calendar_sync import is_common_view_visible_meeting
from app.services.system_task_schedule import matches_template_date
from app.services.task_title_rules import normalize_email_task_title, title_has_eight_am_indicator
from app.services.task_marker import active_one_h_marker, active_one_h_marker_by_ga
from app.services.task_date_window import common_view_task_date_window_filter


router = APIRouter()
FEEDBACK_DAILY_MARKER = "[EVERYDAY]"


KNOWN_INCLUDES = {"users", "departments", "entries", "meetings", "system_tasks", "tasks"}
DEFAULT_INCLUDES = ["users", "departments", "entries", "meetings", "system_tasks", "tasks"]
BUCKETS = [
    "late",
    "absent",
    "leave",
    "externalHoliday",
    "blocked",
    "oneH",
    "personal",
    "external",
    "internal",
    "r1",
    "problems",
    "feedback",
    "priority",
    "important",
    "bz",
]

DEFAULT_MAX_ITEMS_PER_BUCKET = int(os.getenv("COMMON_VIEW_MAX_ITEMS_PER_BUCKET", "1000"))
SERVER_CACHE_TTL_SECONDS = int(os.getenv("COMMON_VIEW_CACHE_TTL_SECONDS", "15"))
COMMON_VIEW_CACHE_VERSION = "21"

_cache: dict[str, tuple[float, str, dict[str, Any]]] = {}


class CommonViewGuardrails(BaseModel):
    max_items_per_bucket: int
    truncated: dict[str, bool]


class CommonViewCounts(BaseModel):
    late: int = 0
    absent: int = 0
    leave: int = 0
    externalHoliday: int = 0
    blocked: int = 0
    oneH: int = 0
    personal: int = 0
    external: int = 0
    internal: int = 0
    r1: int = 0
    problems: int = 0
    feedback: int = 0
    priority: int = 0
    important: int = 0
    bz: int = 0


class CommonViewItemPayload(BaseModel):
    late: list[dict[str, Any]] = Field(default_factory=list)
    absent: list[dict[str, Any]] = Field(default_factory=list)
    leave: list[dict[str, Any]] = Field(default_factory=list)
    externalHoliday: list[dict[str, Any]] = Field(default_factory=list)
    blocked: list[dict[str, Any]] = Field(default_factory=list)
    oneH: list[dict[str, Any]] = Field(default_factory=list)
    personal: list[dict[str, Any]] = Field(default_factory=list)
    external: list[dict[str, Any]] = Field(default_factory=list)
    internal: list[dict[str, Any]] = Field(default_factory=list)
    r1: list[dict[str, Any]] = Field(default_factory=list)
    problems: list[dict[str, Any]] = Field(default_factory=list)
    feedback: list[dict[str, Any]] = Field(default_factory=list)
    priority: list[dict[str, Any]] = Field(default_factory=list)
    important: list[dict[str, Any]] = Field(default_factory=list)
    bz: list[dict[str, Any]] = Field(default_factory=list)


class CommonViewResponse(BaseModel):
    schema_version: int
    generated_at: datetime
    week_start: date
    week_end: date
    requested: list[str]
    included: list[str]
    missing: list[str]
    counts: CommonViewCounts
    items: CommonViewItemPayload
    guardrails: CommonViewGuardrails
    trace_id: str
    timings_ms: dict[str, float] | None = None
    users: list[dict[str, Any]] | None = None
    departments: list[dict[str, Any]] | None = None
    meetings: list[dict[str, Any]] | None = None
    system_tasks: list[dict[str, Any]] | None = None
    tasks: list[dict[str, Any]] | None = None


def _week_start_for(value: date | None) -> date:
    base = value or date.today()
    return base - timedelta(days=base.weekday())


def _week_dates(week_start: date) -> list[date]:
    return [week_start + timedelta(days=i) for i in range(5)]


def _daily_feedback_filter():
    return and_(
        CommonEntry.category.in_(
            [
                CommonCategory.complaints,
                CommonCategory.requests,
                CommonCategory.proposals,
                CommonCategory.problems,
            ]
        ),
        CommonEntry.description.isnot(None),
        CommonEntry.description.ilike(f"%{FEEDBACK_DAILY_MARKER}%"),
    )

def _tirane_tz():
    tz_name = settings.APP_TIMEZONE
    tz = None
    if ZoneInfo is not None:
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = None
    if tz is None:
        try:
            import pytz

            try:
                tz = pytz.timezone(tz_name)
            except Exception:
                tz = None
        except ImportError:
            tz = None
    if tz is None:
        tz = timezone.utc
    return tz

def _as_tirane_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo:
        return value.astimezone(_tirane_tz())
    return value

def _as_tirane_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        local = _as_tirane_dt(value) or value
        return local.date()
    return value


def _format_time(value: datetime | None) -> str:
    if value is None:
        return "TBD"
    local = _as_tirane_dt(value) or value
    return local.strftime("%H:%M")


def _parse_annual_leave(entry: CommonEntry) -> tuple[date, date, bool, str | None, str | None, str | None, bool]:
    return parse_common_view_annual_leave(entry)


def _initials(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        return "?"
    parts = re.split(r"\s+", cleaned)
    first = parts[0][0] if parts else ""
    last = parts[-1][0] if len(parts) > 1 else ""
    return f"{first}{last}".upper()


def _ka_genti_confirmation_owner(user: User | None) -> str | None:
    """Mirror the M1/M3 WFC ownership rules for Common View consumers."""
    if user is None:
        return None
    full_name = (user.full_name or "").strip()
    name_parts = re.findall(r"[^\W\d_]+", full_name, flags=re.UNICODE)
    if name_parts and name_parts[0].casefold() in {"gent", "genti"}:
        return "GENT"
    if _initials(full_name) == "KA":
        return "KA"

    username = (user.username or "").strip().casefold()
    email = (user.email or "").strip().casefold()
    if username == "gent.arifaj" or email == "g.arifaj@primexeu.com":
        return "GENT"
    if username == "kosove.arifaj" or email == "kosove.arifaj@ht-furniture.de":
        return "KA"
    return None


def _normalize_multiline_title(value: str | None) -> str:
    lines = [
        re.sub(r"[ \t\f\v]+", " ", line).strip()
        for line in (value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    return "\n".join(line for line in lines if line)


def _should_include_task(task: Task) -> bool:
    status_value = (task.status or "").lower()
    is_done = bool(task.completed_at) or status_value in {"done", "completed"}
    if is_done:
        return bool(
            getattr(task, "is_1h_report", False)
            or getattr(task, "is_r1", False)
            or getattr(task, "is_personal", False)
            or getattr(task, "is_bllok", False)
        )
    return True


def _get_task_date_source(task: Task) -> datetime | None:
    planned_for = getattr(task, "planned_for", None)
    return planned_for or task.due_date or task.start_date or task.created_at


def _get_task_dates(task: Task, single_day_only: bool, range_end: date | None = None) -> list[date]:
    start_dt = task.start_date
    due_dt = task.due_date
    if single_day_only:
        source = _get_task_date_source(task)
        start = end = _as_tirane_date(source) or date.today()
    elif start_dt and due_dt:
        start = _as_tirane_date(start_dt) or start_dt.date()
        end = _as_tirane_date(due_dt) or due_dt.date()
        if start > end:
            start, end = end, start
    else:
        source = _get_task_date_source(task)
        start = end = _as_tirane_date(source) or date.today()

    # Deadline importance changes highlighting, not the scheduled date range.
    # range_end is retained for callers, but must never extend a task's due date.

    dates: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            dates.append(current)
        current = current + timedelta(days=1)
    return dates if dates else [start]


def _meeting_occurs_on_date(meeting: Meeting, day: date) -> bool:
    return meeting_occurs_on_date(meeting, day, local_timezone=_tirane_tz())


def _meeting_display_dates(meeting: Meeting) -> list[date]:
    return meeting_display_dates(meeting, local_timezone=_tirane_tz())


def _max_timestamp_scalar(column, filters: list[Any] | None = None):
    stmt = select(func.max(column))
    if filters:
        stmt = stmt.where(and_(*filters))
    return stmt.scalar_subquery()


def _count_rows_scalar(model, filters: list[Any] | None = None):
    stmt = select(func.count()).select_from(model)
    if filters:
        stmt = stmt.where(and_(*filters))
    return stmt.scalar_subquery()


def _one_h_slot_report_dates(
    week_start: date,
    week_end: date,
    freeze_one_h_slots: bool,
    now: datetime,
) -> list[date]:
    dates: list[date] = []
    current = week_start
    while current <= week_end:
        dates.append(current if freeze_one_h_slots else effective_slot_date(current, now))
        current += timedelta(days=1)
    return dates


async def _compute_etag(
    db: AsyncSession,
    week_start: date,
    week_end: date,
    requested: list[str],
    user: User,
    department_id: uuid.UUID | None,
    include_all_departments: bool,
    freeze_one_h_slots: bool,
    one_h_slot_report_dates: list[date],
    one_h_slot_report_start: date,
    one_h_slot_report_end: date,
) -> str:
    parts: list[str] = [
        COMMON_VIEW_CACHE_VERSION,
        week_start.isoformat(),
        week_end.isoformat(),
        ",".join(sorted(requested)),
        str(department_id) if department_id else "",
        "1" if include_all_departments else "0",
        str(user.role),
        "1" if freeze_one_h_slots else "0",
        ",".join(day.isoformat() for day in one_h_slot_report_dates),
        one_h_slot_report_start.isoformat(),
        one_h_slot_report_end.isoformat(),
    ]
    fingerprint_fields: list[tuple[str, Any, bool]] = []
    if "users" in requested:
        fingerprint_fields.append(("users_updated", _max_timestamp_scalar(User.updated_at), False))
    if "departments" in requested or "meetings" in requested or "tasks" in requested:
        fingerprint_fields.append(
            ("departments_created", _max_timestamp_scalar(Department.created_at), False)
        )
    if "entries" in requested:
        entry_effective = func.coalesce(CommonEntry.entry_date, func.date(CommonEntry.created_at))
        date_filter = and_(entry_effective >= week_start, entry_effective <= week_end)
        entry_filters = [or_(date_filter, _daily_feedback_filter())]
        fingerprint_fields.append(
            ("entries_updated", _max_timestamp_scalar(CommonEntry.updated_at, entry_filters), False)
        )
    if "meetings" in requested:
        meeting_filters: list[Any] = []
        if department_id is not None:
            meeting_filters.append(Meeting.department_id == department_id)
        fingerprint_fields.extend(
            [
                ("meetings_updated", _max_timestamp_scalar(Meeting.updated_at, meeting_filters), False),
                ("meetings_count", _count_rows_scalar(Meeting, meeting_filters), True),
            ]
        )
    if "system_tasks" in requested:
        fingerprint_fields.append(
            ("system_tasks_created", _max_timestamp_scalar(SystemTaskTemplate.created_at), False)
        )
    if "tasks" in requested:
        task_filters = [
            Task.is_active.is_(True),
            common_view_task_date_window_filter(week_start, week_end),
        ]
        active_task_ids = select(Task.id).where(*task_filters)
        task_project_ids = select(Task.project_id).where(*task_filters)
        project_filters = [Project.id.in_(task_project_ids)]
        active_task_assignee_count = (
            select(func.count())
            .select_from(TaskAssignee)
            .where(TaskAssignee.task_id.in_(active_task_ids))
            .scalar_subquery()
        )
        active_task_assignee_updated = (
            select(func.max(TaskAssignee.created_at))
            .where(TaskAssignee.task_id.in_(active_task_ids))
            .scalar_subquery()
        )
        fingerprint_fields.extend(
            [
                ("tasks_updated", _max_timestamp_scalar(Task.updated_at, task_filters), False),
                ("tasks_count", _count_rows_scalar(Task, task_filters), True),
                ("projects_updated", _max_timestamp_scalar(Project.updated_at, project_filters), False),
                ("active_projects_count", _count_rows_scalar(Project, [*project_filters, Project.is_active.is_(True)]), True),
                ("task_assignees_count", active_task_assignee_count, True),
                ("task_assignees_updated", active_task_assignee_updated, False),
                (
                    "one_h_slots_updated",
                    _max_timestamp_scalar(
                        TaskOneHReportSlot.updated_at,
                        [
                            TaskOneHReportSlot.report_date >= one_h_slot_report_start,
                            TaskOneHReportSlot.report_date <= one_h_slot_report_end,
                        ],
                    ),
                    False,
                ),
                ("ga_notes_updated", _max_timestamp_scalar(GaNote.updated_at), False),
            ]
        )

    if fingerprint_fields:
        fingerprint_stmt = select(
            *(expression.label(label) for label, expression, _ in fingerprint_fields)
        )
        fingerprint = (await db.execute(fingerprint_stmt)).mappings().one()
        for label, _, is_count in fingerprint_fields:
            value = fingerprint[label]
            if is_count:
                parts.append(str(int(value or 0)))
            else:
                parts.append(value.isoformat() if value else "")

    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


@router.get("", response_model=CommonViewResponse)
async def get_common_view(
    request: Request,
    response: Response,
    week_start: date | None = None,
    include: str | None = None,
    department_id: uuid.UUID | None = None,
    include_all_departments: bool = False,
    freeze_one_h_slots: bool = False,
    max_items_per_bucket: int | None = None,
    debug: int = 0,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> CommonViewResponse | Response:
    if department_id is not None and not include_all_departments:
        ensure_department_access(user, department_id)
    if include_all_departments:
        department_id = None
    if user.role == UserRole.STAFF and department_id is None and not include_all_departments:
        department_id = user.department_id

    requested: list[str] = []
    if include:
        for token in include.split(","):
            cleaned = token.strip()
            if cleaned in KNOWN_INCLUDES and cleaned not in requested:
                requested.append(cleaned)
    if not requested:
        requested = list(DEFAULT_INCLUDES)

    week_start_date = _week_start_for(week_start)
    week_end = week_start_date + timedelta(days=6)
    slot_effective_now = (
        datetime.now(ZoneInfo(settings.APP_TIMEZONE))
        if ZoneInfo is not None
        else datetime.now(timezone.utc)
    )
    one_h_slot_report_dates = _one_h_slot_report_dates(
        week_start_date,
        week_end,
        freeze_one_h_slots,
        slot_effective_now,
    )
    one_h_slot_report_start = min(one_h_slot_report_dates)
    one_h_slot_report_end = max(one_h_slot_report_dates)

    etag = await _compute_etag(
        db=db,
        week_start=week_start_date,
        week_end=week_end,
        requested=requested,
        user=user,
        department_id=department_id,
        include_all_departments=include_all_departments,
        freeze_one_h_slots=freeze_one_h_slots,
        one_h_slot_report_dates=one_h_slot_report_dates,
        one_h_slot_report_start=one_h_slot_report_start,
        one_h_slot_report_end=one_h_slot_report_end,
    )
    request_cache_control = request.headers.get("cache-control", "").lower()
    bypass_cache = "no-cache" in request_cache_control or "no-store" in request_cache_control
    if_match = request.headers.get("if-none-match")
    if not bypass_cache and if_match and if_match.strip('"') == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

    cache_key = (
        f"{COMMON_VIEW_CACHE_VERSION}|{week_start_date}|{week_end}|{','.join(sorted(requested))}|"
        f"{department_id}|{include_all_departments}|{user.role}|{freeze_one_h_slots}|"
        f"{','.join(day.isoformat() for day in one_h_slot_report_dates)}|"
        f"{one_h_slot_report_start}|{one_h_slot_report_end}"
    )
    if SERVER_CACHE_TTL_SECONDS > 0 and not bypass_cache:
        cached = _cache.get(cache_key)
        if cached:
            expires_at, cached_etag, payload = cached
            if expires_at >= datetime.utcnow().timestamp() and cached_etag == etag:
                if if_match and if_match.strip('"') == cached_etag:
                    return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": cached_etag})
                payload_copy = dict(payload)
                payload_copy["trace_id"] = str(uuid.uuid4())
                response.headers["ETag"] = cached_etag
                return CommonViewResponse(**payload_copy).copy(
                    update={"trace_id": payload_copy["trace_id"]}
                )

    trace_id = str(uuid.uuid4())
    timings: dict[str, float] | None = {} if debug else None

    t0 = perf_counter()
    max_items = max_items_per_bucket or DEFAULT_MAX_ITEMS_PER_BUCKET

    items = {bucket: [] for bucket in BUCKETS}
    included: list[str] = []
    missing: list[str] = []

    def _time_start() -> float:
        return perf_counter()

    def _time_end(label: str, start: float) -> None:
        if timings is not None:
            timings[label] = (perf_counter() - start) * 1000

    users_map: dict[uuid.UUID, User] = {}
    departments_map: dict[uuid.UUID, Department] = {}

    needs_users = any(name in requested for name in ["users", "entries", "tasks", "meetings", "system_tasks"])
    if needs_users:
        ts = _time_start()
        users_stmt = select(User).where(User.is_active.is_(True))
        users = (await db.execute(users_stmt.order_by(User.full_name))).scalars().all()
        users_map = {u.id: u for u in users}
        _time_end("users", ts)
        if "users" in requested:
            included.append("users")
    needs_departments = any(name in requested for name in ["departments", "meetings", "tasks"])
    if needs_departments:
        ts = _time_start()
        departments = (await db.execute(select(Department).order_by(Department.name))).scalars().all()
        departments_map = {d.id: d for d in departments}
        _time_end("departments", ts)
        if "departments" in requested:
            included.append("departments")

    if "entries" in requested:
        ts = _time_start()
        effective_date = func.coalesce(CommonEntry.entry_date, func.date(CommonEntry.created_at))
        date_filter = and_(effective_date >= week_start_date, effective_date <= week_end)
        non_annual_stmt = select(CommonEntry).where(
            CommonEntry.category != CommonCategory.annual_leave,
            or_(date_filter, _daily_feedback_filter()),
        )
        non_annual_entries = (await db.execute(non_annual_stmt)).scalars().all()

        two_years_ago = datetime.now().date() - timedelta(days=730)
        annual_stmt = select(CommonEntry).where(
            CommonEntry.category == CommonCategory.annual_leave,
            or_(
                CommonEntry.entry_date.is_(None),
                CommonEntry.entry_date >= two_years_ago,
            ),
        )
        annual_entries = (await db.execute(annual_stmt)).scalars().all()
        annual_overlapping: list[CommonEntry] = []
        for entry in annual_entries:
            start_date, end_date, _, _, _, _, _ = _parse_annual_leave(entry)
            if end_date < week_start_date or start_date > week_end:
                continue
            annual_overlapping.append(entry)
        entries = non_annual_entries + annual_overlapping

        for e in entries:
            user_for_entry = None
            if e.assigned_to_user_id:
                user_for_entry = users_map.get(e.assigned_to_user_id)
            if user_for_entry is None:
                user_for_entry = users_map.get(e.created_by_user_id)
            if department_id and user_for_entry and user_for_entry.department_id != department_id:
                continue
            person_name = (
                user_for_entry.full_name
                if user_for_entry and user_for_entry.full_name
                else user_for_entry.username
                if user_for_entry and user_for_entry.username
                else e.title
            )

            entry_date = e.entry_date or e.created_at.date()
            if e.description:
                match = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", e.description, re.I)
                if match:
                    try:
                        entry_date = date.fromisoformat(match.group(1))
                    except ValueError:
                        pass

            if e.category == CommonCategory.delays:
                note = e.description or ""
                start = "08:00"
                until = "09:00"
                start_match = re.search(r"Start:\s*(\d{1,2}:\d{2})", note, re.I)
                if start_match:
                    start = start_match.group(1)
                    note = re.sub(r"Start:\s*\d{1,2}:\d{2}", "", note, flags=re.I).strip()
                until_match = re.search(r"Until:\s*(\d{1,2}:\d{2})", note, re.I)
                if until_match:
                    until = until_match.group(1)
                    note = re.sub(r"Until:\s*\d{1,2}:\d{2}", "", note, flags=re.I).strip()
                note = re.sub(r"Date:\s*\d{4}-\d{2}-\d{2}", "", note, flags=re.I).strip()
                items["late"].append(
                    {
                        "id": f"entry:{e.id}",
                        "entryId": str(e.id),
                        "person": person_name or "Unknown",
                        "date": entry_date.isoformat(),
                        "until": until,
                        "start": start,
                        "note": note or None,
                        "userId": str(e.assigned_to_user_id or e.created_by_user_id)
                        if (e.assigned_to_user_id or e.created_by_user_id)
                        else None,
                    }
                )
            elif e.category == CommonCategory.absences:
                note = e.description or ""
                from_time = "08:00"
                to_time = "23:00"
                from_to_match = re.search(r"From:\s*(\d{1,2}:\d{2})\s*-\s*To:\s*(\d{1,2}:\d{2})", note, re.I)
                if from_to_match:
                    from_time = from_to_match.group(1)
                    to_time = from_to_match.group(2)
                    note = re.sub(
                        r"From:\s*\d{1,2}:\d{2}\s*-\s*To:\s*\d{1,2}:\d{2}", "", note, flags=re.I
                    ).strip()
                note = re.sub(r"Date:\s*\d{4}-\d{2}-\d{2}", "", note, flags=re.I).strip()
                items["absent"].append(
                    {
                        "id": f"entry:{e.id}",
                        "entryId": str(e.id),
                        "person": person_name or "Unknown",
                        "date": entry_date.isoformat(),
                        "from": from_time,
                        "to": to_time,
                        "note": note or None,
                        "userId": str(e.assigned_to_user_id or e.created_by_user_id)
                        if (e.assigned_to_user_id or e.created_by_user_id)
                        else None,
                    }
                )
            elif e.category == CommonCategory.annual_leave:
                start_date, end_date, full_day, start_time, end_time, note, is_all_users = _parse_annual_leave(e)
                items["leave"].append(
                    {
                        "id": f"entry:{e.id}",
                        "entryId": str(e.id),
                        "person": person_name or "Unknown",
                        "startDate": start_date.isoformat(),
                        "endDate": end_date.isoformat(),
                        "fullDay": full_day,
                        "from": start_time,
                        "to": end_time,
                        "note": note,
                        "isAllUsers": is_all_users,
                        "userId": str(e.assigned_to_user_id or e.created_by_user_id),
                    }
                )
            elif e.category == CommonCategory.blocks:
                items["blocked"].append(
                    {
                        "id": f"entry:{e.id}",
                        "title": e.title,
                        "person": person_name or "Unknown",
                        "date": entry_date.isoformat(),
                        "note": e.description or None,
                    }
                )
            elif e.category == CommonCategory.external_tasks:
                items["external"].append(
                    {
                        "id": f"entry:{e.id}",
                        "title": e.title,
                        "date": entry_date.isoformat(),
                        "time": "14:00",
                        "platform": "Zoom",
                        "owner": person_name or "Unknown",
                        "department": None,
                    }
                )
            elif e.category == CommonCategory.external_holiday:
                items["externalHoliday"].append(
                    {
                        "id": f"entry:{e.id}",
                        "entryId": str(e.id),
                        "title": e.title,
                        "date": entry_date.isoformat(),
                        "note": e.description or None,
                    }
                )
            elif e.category == CommonCategory.problems:
                items["problems"].append(
                    {
                        "id": f"entry:{e.id}",
                        "entryId": str(e.id),
                        "title": e.title,
                        "person": person_name or "Unknown",
                        "date": entry_date.isoformat(),
                        "createdDate": e.created_at.date().isoformat(),
                        "note": e.description or None,
                    }
                )
            elif e.category in (CommonCategory.complaints, CommonCategory.requests, CommonCategory.proposals):
                items["feedback"].append(
                    {
                        "id": f"entry:{e.id}",
                        "entryId": str(e.id),
                        "title": e.title,
                        "person": person_name or "Unknown",
                        "date": entry_date.isoformat(),
                        "createdDate": e.created_at.date().isoformat(),
                        "note": e.description or None,
                    }
                )

        included.append("entries")
        _time_end("entries", ts)
    if "tasks" in requested:
        ts = _time_start()
        stmt = select(Task).where(Task.is_active.is_(True))
        if department_id:
            stmt = stmt.outerjoin(Project, Task.project_id == Project.id).where(
                or_(Task.department_id == department_id, Project.department_id == department_id)
            )
        stmt = stmt.where(common_view_task_date_window_filter(week_start_date, week_end))
        tasks = (await db.execute(stmt.order_by(Task.created_at))).scalars().all()
        tasks = [t for t in tasks if _should_include_task(t)]

        task_ids = [t.id for t in tasks]
        one_h_slots_by_task_date: dict[tuple[uuid.UUID, date], str] = {}
        if task_ids:
            rows = (
                await db.execute(
                    select(
                        TaskOneHReportSlot.task_id,
                        TaskOneHReportSlot.report_date,
                        TaskOneHReportSlot.one_h_report_slot,
                    )
                    .where(TaskOneHReportSlot.task_id.in_(task_ids))
                    .where(TaskOneHReportSlot.report_date >= one_h_slot_report_start)
                    .where(TaskOneHReportSlot.report_date <= one_h_slot_report_end)
                )
            ).all()
            one_h_slots_by_task_date = {
                (task_id, report_date): slot for task_id, report_date, slot in rows
            }
        assignee_rows = (
            await db.execute(
                select(TaskAssignee.task_id, User)
                .join(User, TaskAssignee.user_id == User.id)
                .where(TaskAssignee.task_id.in_(task_ids))
            )
        ).all()
        assignees_by_task: dict[uuid.UUID, list[User]] = {}
        for task_id, user_row in assignee_rows:
            assignees_by_task.setdefault(task_id, []).append(user_row)

        project_ids = list({t.project_id for t in tasks if t.project_id})
        projects: dict[uuid.UUID, Project] = {}
        if project_ids:
            rows = (await db.execute(select(Project).where(Project.id.in_(project_ids)))).scalars().all()
            projects = {p.id: p for p in rows}

        ga_note_origin_ids = list({t.ga_note_origin_id for t in tasks if t.ga_note_origin_id})
        ga_note_titles: dict[uuid.UUID, str] = {}
        if ga_note_origin_ids:
            rows = (
                await db.execute(select(GaNote.id, GaNote.content).where(GaNote.id.in_(ga_note_origin_ids)))
            ).all()
            ga_note_titles = {
                note_id: normalized
                for note_id, content in rows
                if (normalized := _normalize_multiline_title(content))
            }

        plan_note_origin_ids = list({t.plan_note_origin_id for t in tasks if t.plan_note_origin_id})
        plan_note_titles: dict[uuid.UUID, str] = {}
        if plan_note_origin_ids:
            rows = (
                await db.execute(select(PlanNote.id, PlanNote.content).where(PlanNote.id.in_(plan_note_origin_ids)))
            ).all()
            plan_note_titles = {
                note_id: normalized
                for note_id, content in rows
                if (normalized := _normalize_multiline_title(content))
            }

        product_content_dept_id: uuid.UUID | None = None
        for d in departments_map.values():
            name_lower = (d.name or "").lower()
            if "project content" in name_lower or "content manager" in name_lower or d.code == "PCM":
                product_content_dept_id = d.id
                break

        all_participant_ids = {
            user.id
            for user in users_map.values()
            if user.is_active and _initials(user.full_name or user.username or "") not in {"GA", "KA", "HV"}
        }

        priority_map: dict[uuid.UUID, dict[str, Any]] = {}
        for t in tasks:
            display_title = ga_note_titles.get(t.ga_note_origin_id) if t.ga_note_origin_id else None
            display_title = display_title or (
                plan_note_titles.get(t.plan_note_origin_id) if t.plan_note_origin_id else None
            )
            is_system_task = (t.system_template_origin_id is not None or t.system_task_slot_id is not None)
            display_title = normalize_email_task_title(
                display_title or t.title,
                is_system_task=is_system_task,
            )
            assignees = assignees_by_task.get(t.id) or []
            if not assignees and t.assigned_to:
                user_for_task = users_map.get(t.assigned_to)
                if user_for_task:
                    assignees = [user_for_task]
            assignee_id = t.assigned_to or (assignees[0].id if assignees else None)
            assignee_names = [u.full_name or u.username or u.email for u in assignees if u]
            assignee_ids = {u.id for u in assignees if u}
            if all_participant_ids and assignee_ids and all_participant_ids.issubset(assignee_ids):
                owner_label = "ALL"
            else:
                owner_label = ", ".join([n for n in assignee_names if n]) or "Unknown"
            status_value = (t.status or "").lower()
            is_done = bool(t.completed_at) or status_value in {"done", "completed"}
            task_status = (t.status or ("DONE" if is_done else "TODO")).strip() or ("DONE" if is_done else "TODO")
            confirmation_owner = _ka_genti_confirmation_owner(
                users_map.get(t.confirmation_assignee_id) if t.confirmation_assignee_id else None
            )
            confirmation_fields = {
                "confirmation_assignee_id": str(t.confirmation_assignee_id) if t.confirmation_assignee_id else None,
                "confirmation_owner": confirmation_owner,
                "is_system_task": is_system_task,
            }
            dept_id = None
            if assignees:
                dept_id = assignees[0].department_id
            if dept_id is None:
                dept_id = t.department_id

            phase_value = (t.phase or "").upper()
            is_check_phase = phase_value in {"CHECK", "CONTROL"}
            task_dates = _get_task_dates(t, is_check_phase, week_end)
            task_dates = [d for d in task_dates if week_start_date <= d <= week_end]
            if not task_dates:
                continue

            for task_date in task_dates:
                one_h_slot_date = (
                    task_date if freeze_one_h_slots else effective_slot_date(task_date, slot_effective_now)
                )
                if t.is_bllok:
                    items["blocked"].append(
                        {
                            "id": f"task:{t.id}:{task_date.isoformat()}",
                            "task_id": str(t.id),
                            "title": display_title,
                            "task_title": t.title,
                            "person": owner_label,
                            "assignees": assignee_names or None,
                            "user_id": str(assignee_id) if assignee_id else None,
                            "department_id": str(dept_id) if dept_id else None,
                            "date": task_date.isoformat(),
                            "note": t.description or None,
                            "description": t.description,
                            "status": task_status,
                            "isDone": is_done,
                            "fast_task_order": t.fast_task_order,
                            "finish_period": t.finish_period,
                            "one_h_marker": active_one_h_marker(t, task_date, slot_effective_now),
                            "one_h_marker_by_ga": active_one_h_marker_by_ga(t, task_date, slot_effective_now),
                            "one_h_marker_comment": t.one_h_marker_comment,
                            "is_deadline_important": bool(t.is_deadline_important),
                            "due_date": t.due_date.isoformat() if t.due_date else None,
                            "start_date": t.start_date.isoformat() if t.start_date else None,
                            "created_at": t.created_at.isoformat() if t.created_at else None,
                            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                            **confirmation_fields,
                        }
                    )
                if t.is_1h_report:
                    items["oneH"].append(
                        {
                            "id": f"task:{t.id}:{task_date.isoformat()}",
                            "task_id": str(t.id),
                            "title": display_title,
                            "task_title": t.title,
                            "person": owner_label,
                            "assignees": assignee_names or None,
                            "user_id": str(assignee_id) if assignee_id else None,
                            "date": task_date.isoformat(),
                            "note": t.description or None,
                            "description": t.description,
                            "department_id": str(dept_id) if dept_id else None,
                            "status": task_status,
                            "isDone": is_done,
                            "fast_task_order": t.fast_task_order,
                            "finish_period": t.finish_period,
                            "one_h_report_slot": one_h_slots_by_task_date.get((t.id, one_h_slot_date))
                            or t.one_h_report_slot,
                            "one_h_marker": active_one_h_marker(t, task_date, slot_effective_now),
                            "one_h_marker_by_ga": active_one_h_marker_by_ga(t, task_date, slot_effective_now),
                            "one_h_marker_comment": t.one_h_marker_comment,
                            "is_deadline_important": bool(t.is_deadline_important),
                            "due_date": t.due_date.isoformat() if t.due_date else None,
                            "start_date": t.start_date.isoformat() if t.start_date else None,
                            "created_at": t.created_at.isoformat() if t.created_at else None,
                            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                            **confirmation_fields,
                        }
                    )
                if t.is_personal:
                    items["personal"].append(
                        {
                            "id": f"task:{t.id}:{task_date.isoformat()}",
                            "task_id": str(t.id),
                            "title": display_title,
                            "task_title": t.title,
                            "person": owner_label,
                            "assignees": assignee_names or None,
                            "user_id": str(assignee_id) if assignee_id else None,
                            "date": task_date.isoformat(),
                            "note": t.description or None,
                            "description": t.description,
                            "department_id": str(dept_id) if dept_id else None,
                            "status": task_status,
                            "isDone": is_done,
                            "fast_task_order": t.fast_task_order,
                            "finish_period": t.finish_period,
                            "one_h_marker": active_one_h_marker(t, task_date, slot_effective_now),
                            "one_h_marker_by_ga": active_one_h_marker_by_ga(t, task_date, slot_effective_now),
                            "one_h_marker_comment": t.one_h_marker_comment,
                            "is_deadline_important": bool(t.is_deadline_important),
                            "due_date": t.due_date.isoformat() if t.due_date else None,
                            "start_date": t.start_date.isoformat() if t.start_date else None,
                            "created_at": t.created_at.isoformat() if t.created_at else None,
                            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                            "is_personal_task": True,
                            **confirmation_fields,
                        }
                    )
                if t.is_r1:
                    items["r1"].append(
                        {
                            "id": f"task:{t.id}:{task_date.isoformat()}",
                            "task_id": str(t.id),
                            "title": display_title,
                            "task_title": t.title,
                            "date": task_date.isoformat(),
                            "owner": owner_label,
                            "assignees": assignee_names or None,
                            "user_id": str(assignee_id) if assignee_id else None,
                            "note": t.description or None,
                            "description": t.description,
                            "department_id": str(dept_id) if dept_id else None,
                            "status": task_status,
                            "isDone": is_done,
                            "fast_task_order": t.fast_task_order,
                            "finish_period": t.finish_period,
                            "one_h_report_slot": one_h_slots_by_task_date.get((t.id, one_h_slot_date))
                            or t.one_h_report_slot,
                            "one_h_marker": active_one_h_marker(t, task_date, slot_effective_now),
                            "one_h_marker_by_ga": active_one_h_marker_by_ga(t, task_date, slot_effective_now),
                            "one_h_marker_comment": t.one_h_marker_comment,
                            "is_deadline_important": bool(t.is_deadline_important),
                            "due_date": t.due_date.isoformat() if t.due_date else None,
                            "start_date": t.start_date.isoformat() if t.start_date else None,
                            "created_at": t.created_at.isoformat() if t.created_at else None,
                            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                            **confirmation_fields,
                        }
                    )
                if (
                    t.is_deadline_important
                    or title_has_eight_am_indicator(
                        display_title or t.title,
                        is_system_task=is_system_task,
                    )
                ) and not (t.is_1h_report or t.is_bllok or t.is_r1 or t.is_personal):
                    items["important"].append(
                        {
                            "id": f"task:{t.id}:{task_date.isoformat()}",
                            "task_id": str(t.id),
                            "title": display_title,
                            "task_title": t.title,
                            "person": owner_label,
                            "assignees": assignee_names or None,
                            "user_id": str(assignee_id) if assignee_id else None,
                            "date": task_date.isoformat(),
                            "note": t.description or None,
                            "description": t.description,
                            "department_id": str(dept_id) if dept_id else None,
                            "status": task_status,
                            "isDone": is_done,
                            "fast_task_order": t.fast_task_order,
                            "finish_period": t.finish_period,
                            "one_h_marker": active_one_h_marker(t, task_date, slot_effective_now),
                            "one_h_marker_by_ga": active_one_h_marker_by_ga(t, task_date, slot_effective_now),
                            "one_h_marker_comment": t.one_h_marker_comment,
                            "is_deadline_important": bool(t.is_deadline_important),
                            "due_date": t.due_date.isoformat() if t.due_date else None,
                            "start_date": t.start_date.isoformat() if t.start_date else None,
                            "created_at": t.created_at.isoformat() if t.created_at else None,
                            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                            **confirmation_fields,
                        }
                    )

                if (
                    not t.is_personal
                    and not is_done
                    and task_status.strip().upper() in {"WAITING", "PENDING_CONFIRMATION", "WAITING_CONFIRMATION"}
                    and confirmation_owner in {"KA", "GENT"}
                ):
                    items["personal"].append(
                        {
                            "id": f"task:{t.id}:{task_date.isoformat()}:wfc",
                            "task_id": str(t.id),
                            "title": display_title,
                            "task_title": t.title,
                            "person": owner_label,
                            "assignees": assignee_names or None,
                            "user_id": str(assignee_id) if assignee_id else None,
                            "date": task_date.isoformat(),
                            "note": t.description or None,
                            "description": t.description,
                            "department_id": str(dept_id) if dept_id else None,
                            "status": task_status,
                            "isDone": False,
                            "fast_task_order": t.fast_task_order,
                            "finish_period": t.finish_period,
                            "one_h_report_slot": one_h_slots_by_task_date.get((t.id, one_h_slot_date))
                            or t.one_h_report_slot,
                            "one_h_marker": active_one_h_marker(t, task_date, slot_effective_now),
                            "is_deadline_important": bool(t.is_deadline_important),
                            "due_date": t.due_date.isoformat() if t.due_date else None,
                            "start_date": t.start_date.isoformat() if t.start_date else None,
                            "created_at": t.created_at.isoformat() if t.created_at else None,
                            "completed_at": None,
                            "is_personal_task": False,
                            **confirmation_fields,
                        }
                    )

            if t.project_id:
                project = projects.get(t.project_id)
                # Project activity only controls PRJK visibility; retain task history in 1H/BLL/etc.
                if not project or not project.is_active:
                    continue
                base_title = (project.title or "").strip()
                if not base_title:
                    continue
                project_name = (
                    f"{base_title} - {project.total_products}"
                    if project.project_type == "MST" and project.total_products and project.total_products > 0
                    else base_title
                )
                entry = priority_map.get(t.project_id)
                if entry is None:
                    entry = {
                        "project": project_name,
                        "assignees_by_date": {},
                        "task_assignees_by_date_period": {},
                        "dates": set(),
                    }
                    priority_map[t.project_id] = entry
                for task_date in task_dates:
                    entry["dates"].add(task_date)
                    date_key = task_date.isoformat()
                    entry["assignees_by_date"].setdefault(date_key, set()).update(assignee_names)
                    project_department = departments_map.get(project.department_id)
                    if project_department and is_project_coverage_department(project_department.code, project_department.name):
                        for period in project_task_periods(t.finish_period):
                            period_users = entry["task_assignees_by_date_period"].setdefault(date_key, {}).setdefault(period, set())
                            period_users.update(str(user_id) for user_id in assignee_ids)
                            if t.assigned_to:
                                period_users.add(str(t.assigned_to))

        expanded_priority: list[dict[str, Any]] = []
        for project_id, entry in priority_map.items():
            project = projects.get(project_id)
            if not project:
                continue
            is_mst = has_mst_identity(project)
            is_vs_vl = is_vs_or_vl_project(project)
            is_product_content = project.department_id == product_content_dept_id

            dates_to_use: list[date] = []
            if (is_mst or is_vs_vl) and is_product_content:
                if project.due_date:
                    start_date = week_start_date
                    end_date = min(week_end, project.due_date.date())
                    current = start_date
                    while current <= end_date:
                        if current.weekday() < 5:
                            dates_to_use.append(current)
                        current = current + timedelta(days=1)
                elif entry["dates"]:
                    dates_to_use = sorted(entry["dates"])
                else:
                    dates_to_use = [week_start_date]
            else:
                if entry["dates"]:
                    dates_to_use = sorted(entry["dates"])
                else:
                    continue

            if entry["dates"]:
                merged = set(dates_to_use)
                merged.update(entry["dates"])
                dates_to_use = sorted(merged)
            dates_to_use = [d for d in dates_to_use if week_start_date <= d <= week_end]
            if not dates_to_use:
                continue

            for d in dates_to_use:
                date_key = d.isoformat()
                assignees = sorted(entry["assignees_by_date"].get(date_key, set()))
                dept_id = project.department_id
                dept_name = departments_map.get(dept_id).name if dept_id and dept_id in departments_map else "Other"
                expanded_priority.append(
                    {
                        "id": f"priority:{project_id}:{date_key}",
                        "project": entry["project"],
                        "date": date_key,
                        "assignees": assignees,
                        "projectTaskAssigneesByPeriod": {
                            period: sorted(user_ids)
                            for period, user_ids in entry["task_assignees_by_date_period"].get(date_key, {}).items()
                        },
                        "department_id": str(dept_id) if dept_id else None,
                        "department_name": dept_name,
                    }
                )

        items["priority"] = expanded_priority

        # Keep Common View task buckets in the same department/person sequence
        # used by the Weekly Planner. M3 consumes these rows as a fallback, so
        # the ordering metadata travels with the task instead of being inferred
        # again from display initials.
        department_by_id = {str(department.id): department for department in departments_map.values()}
        users_by_id = {str(user.id): user for user in users_map.values()}
        department_rank_by_code = {"DEV": 0, "GD": 1, "PCM": 2}

        def weekly_planner_sort(item: dict[str, Any]) -> tuple[int, str, int, int, str]:
            user = users_by_id.get(str(item.get("user_id") or item.get("userId") or ""))
            department_id = (
                str(user.department_id) if user and user.department_id else str(item.get("department_id") or item.get("departmentId") or "")
            )
            department = department_by_id.get(department_id)
            code = ((department.code or "") if department else "").strip().upper()
            aliases = {
                "DEVELOPMENT": "DEV",
                "GRAPHIC DESIGN": "GD",
                "GDS": "GD",
                "PRODUCT CONTENT": "PCM",
                "PROJECT CONTENT MANAGER": "PCM",
            }
            code = aliases.get(code, code or "-")
            order = user.weekly_planner_sort_order if user else None
            name = (user.full_name or user.username or user.email) if user else (item.get("person") or item.get("owner") or "")
            return (
                department_rank_by_code.get(code, len(department_rank_by_code)),
                code.casefold(),
                1 if order is None else 0,
                order or 0,
                str(name).casefold(),
            )

        for bucket in ("blocked", "oneH", "personal", "r1", "bz"):
            for item in items[bucket]:
                item["weekly_planner_sort"] = weekly_planner_sort(item)

        included.append("tasks")
        _time_end("tasks", ts)

    if "meetings" in requested:
        ts = _time_start()
        meeting_stmt = select(Meeting)
        if department_id:
            meeting_stmt = meeting_stmt.where(Meeting.department_id == department_id)
        meetings = (await db.execute(meeting_stmt.order_by(Meeting.starts_at, Meeting.created_at.desc()))).scalars().all()
        meetings_by_id = {meeting.id: meeting for meeting in meetings}
        participant_users_by_meeting: dict[uuid.UUID, list[tuple[str, str]]] = {}
        if meetings_by_id:
            participant_rows = (
                await db.execute(
                    select(MeetingParticipant.meeting_id, MeetingParticipant.user_id)
                    .where(
                        MeetingParticipant.meeting_id.in_(meetings_by_id),
                        MeetingParticipant.assignment_source == "manual",
                    )
                )
            ).all()
            for meeting_id, user_id in participant_rows:
                participant = users_map.get(user_id)
                if participant is None:
                    continue
                participant_name = (
                    participant.full_name or participant.username or participant.email or ""
                ).strip()
                if participant_name:
                    participant_users_by_meeting.setdefault(meeting_id, []).append(
                        (participant_name, str(user_id))
                    )
            for participant_users in participant_users_by_meeting.values():
                participant_users.sort(key=lambda value: value[0].casefold())
        week_days = [week_start_date + timedelta(days=i) for i in range(7)]

        for meeting in meetings:
            if not is_common_view_visible_meeting(meeting):
                continue
            is_calendar_meeting = bool(meeting.calendar_imported or meeting.microsoft_event_id)
            owner_user = users_map.get(meeting.created_by) if meeting.created_by else None
            owner_name = owner_user.full_name if owner_user and owner_user.full_name else owner_user.username if owner_user else "Unknown"
            department_name = (
                departments_map.get(meeting.department_id).name
                if meeting.department_id in departments_map
                else "Department TBD"
            )
            linked_external_id = meeting.paired_external_meeting_id or meeting.pre_external_meeting_id
            linked_external = (
                meetings_by_id.get(linked_external_id)
                if meeting.meeting_type == "internal" and linked_external_id
                else None
            )
            link_payload = (
                {
                    "pairedExternalMeetingId": (
                        str(meeting.paired_external_meeting_id)
                        if meeting.paired_external_meeting_id
                        else None
                    ),
                    "preExternalMeetingId": (
                        str(meeting.pre_external_meeting_id)
                        if meeting.pre_external_meeting_id
                        else None
                    ),
                    "linkedExternalCalendarCategories": linked_external.calendar_categories or [],
                    "linkedExternalCalendarImported": bool(
                        linked_external.calendar_imported or linked_external.microsoft_event_id
                    ),
                    "linkedExternalRecurrenceType": linked_external.recurrence_type or "none",
                }
                if linked_external is not None
                else {}
            )
            if meeting.recurrence_type and meeting.recurrence_type != "none":
                time_label = _format_time(meeting.starts_at)
                for day in week_days:
                    if _meeting_occurs_on_date(meeting, day):
                        target = "external" if meeting.meeting_type == "external" else "internal"
                        items[target].append(
                            {
                                "id": f"meeting:{meeting.id}:{day.isoformat()}",
                                "title": meeting.title or ("External meeting" if target == "external" else "Internal meeting"),
                                "date": day.isoformat(),
                                "time": time_label,
                                "platform": meeting.platform or "TBD",
                                "owner": owner_name,
                                "assignees": [
                                    name for name, _ in participant_users_by_meeting.get(meeting.id, [])
                                ],
                                "assigneeUserIds": [
                                    user_id for _, user_id in participant_users_by_meeting.get(meeting.id, [])
                                ],
                                "department": department_name,
                                "recurrence_type": meeting.recurrence_type or "none",
                                "calendarImported": is_calendar_meeting,
                                "calendarCategories": meeting.calendar_categories or [],
                                **link_payload,
                            }
                        )
            else:
                target = "external" if meeting.meeting_type == "external" else "internal"
                for day in _meeting_display_dates(meeting):
                    if not (week_start_date <= day <= week_end):
                        continue
                    items[target].append(
                        {
                            "id": f"meeting:{meeting.id}:{day.isoformat()}",
                            "title": meeting.title or ("External meeting" if target == "external" else "Internal meeting"),
                            "date": day.isoformat(),
                            "time": _format_time(meeting.starts_at),
                            "platform": meeting.platform or "TBD",
                            "owner": owner_name,
                            "assignees": [
                                name for name, _ in participant_users_by_meeting.get(meeting.id, [])
                            ],
                            "assigneeUserIds": [
                                user_id for _, user_id in participant_users_by_meeting.get(meeting.id, [])
                            ],
                            "department": department_name,
                            "recurrence_type": meeting.recurrence_type or "none",
                            "calendarImported": is_calendar_meeting,
                            "calendarCategories": meeting.calendar_categories or [],
                            **link_payload,
                        }
                    )

        included.append("meetings")
        _time_end("meetings", ts)

    if "system_tasks" in requested:
        ts = _time_start()
        templates = (
            await db.execute(
                select(SystemTaskTemplate)
                .where(SystemTaskTemplate.is_active == True)
                .where(SystemTaskTemplate.approval_status == CommonApprovalStatus.approved)
            )
        ).scalars().all()
        template_ids = [t.id for t in templates]
        alignment_user_rows = (
            await db.execute(
                select(SystemTaskTemplateAlignmentUser.template_id, SystemTaskTemplateAlignmentUser.user_id)
                .where(SystemTaskTemplateAlignmentUser.template_id.in_(template_ids))
            )
        ).all()
        alignment_users_map: dict[uuid.UUID, list[uuid.UUID]] = {}
        for tid, uid in alignment_user_rows:
            alignment_users_map.setdefault(tid, []).append(uid)

        gane_user = next((u for u in users_map.values() if (u.username or "").lower() == "gane.arifaj"), None)
        gane_user_id = gane_user.id if gane_user else None
        week_dates = _week_dates(week_start_date)

        for tmpl in templates:
            alignment_ids = alignment_users_map.get(tmpl.id, [])
            if not alignment_ids:
                continue
            if not gane_user_id or gane_user_id not in alignment_ids:
                continue
            for day in week_dates:
                if not matches_template_date(tmpl, day):
                    continue
                assignee_ids = tmpl.assignee_ids or ([tmpl.default_assignee_id] if tmpl.default_assignee_id else [])
                # For a multi-user BZ template, the first assignee is the
                # report reference user (department and Weekly Planner order).
                primary_assignee_id = assignee_ids[0] if assignee_ids else tmpl.default_assignee_id
                primary_assignee = users_map.get(primary_assignee_id)
                assignees = []
                for uid in assignee_ids:
                    user_obj = users_map.get(uid)
                    if user_obj:
                        assignees.append(user_obj.full_name or user_obj.username or user_obj.email)
                bz_with = [
                    _initials(users_map[uid].full_name or users_map[uid].username or "")
                    for uid in alignment_ids
                    if uid in users_map
                ]
                bz_label = ", ".join([v for v in bz_with if v])
                items["bz"].append(
                    {
                        "id": f"system:{tmpl.id}:{day.isoformat()}",
                        "title": tmpl.title or "-",
                        "date": day.isoformat(),
                        "time": tmpl.alignment_time.strftime("%H:%M") if tmpl.alignment_time else "TBD",
                        "assignees": assignees or None,
                        "user_id": str(primary_assignee_id) if primary_assignee_id else None,
                        "department_id": str(primary_assignee.department_id)
                        if primary_assignee and primary_assignee.department_id else None,
                        "bzWithLabel": bz_label,
                    }
                )

        included.append("system_tasks")
        _time_end("system_tasks", ts)
    counts = CommonViewCounts(**{k: len(items[k]) for k in BUCKETS})
    truncated: dict[str, bool] = {}
    for bucket in BUCKETS:
        if len(items[bucket]) > max_items:
            items[bucket] = items[bucket][:max_items]
            truncated[bucket] = True
        else:
            truncated[bucket] = False

    guardrails = CommonViewGuardrails(max_items_per_bucket=max_items, truncated=truncated)

    if timings is not None:
        timings["total"] = (perf_counter() - t0) * 1000

    missing = [name for name in requested if name not in included]

    payload = CommonViewResponse(
        schema_version=2,
        generated_at=datetime.utcnow(),
        week_start=week_start_date,
        week_end=week_end,
        requested=requested,
        included=included,
        missing=missing,
        counts=counts,
        items=CommonViewItemPayload(**items),
        guardrails=guardrails,
        trace_id=trace_id,
        timings_ms=timings,
        users=[{
            "id": str(u.id),
            "username": u.username,
            "full_name": u.full_name,
            "role": u.role,
            "department_id": str(u.department_id) if u.department_id else None,
            "is_active": u.is_active,
            "weekly_planner_sort_order": u.weekly_planner_sort_order,
        } for u in users_map.values()] if "users" in requested else None,
        departments=[{"id": str(d.id), "code": d.code, "name": d.name} for d in departments_map.values()] if "departments" in requested else None,
        meetings=None,
        system_tasks=None,
        tasks=None,
    )

    payload_dict = payload.dict()
    if SERVER_CACHE_TTL_SECONDS > 0:
        _cache[cache_key] = (datetime.utcnow().timestamp() + SERVER_CACHE_TTL_SECONDS, etag, payload_dict)

    response.headers["ETag"] = etag
    if bypass_cache:
        response.headers["Cache-Control"] = "no-store"
    response_payload = CommonViewResponse(**payload_dict)
    return response_payload.copy(update={"trace_id": trace_id})
