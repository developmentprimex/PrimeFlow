from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:
    # Fallback for Python < 3.9
    try:
        import pytz
        ZoneInfo = None  # Will use pytz instead
    except ImportError:
        ZoneInfo = None

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import Date, cast, exists, func, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_department_access, ensure_manager_or_admin
from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models.common_entry import CommonEntry
from app.models.enums import CommonApprovalStatus, CommonCategory, ProjectPhaseStatus, ProjectType, TaskFinishPeriod, TaskPriority, TaskStatus, UserRole
from app.models.project import Project
from app.models.project_planner_exclusion import ProjectPlannerExclusion
from app.models.project_member import ProjectMember
from app.models.system_task_template import SystemTaskTemplate
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_planner_exclusion import TaskPlannerExclusion
from app.models.task_daily_progress import TaskDailyProgress
from app.models.task_one_h_marker_history import TaskOneHMarkerHistory
from app.models.user import User
from app.models.weekly_plan import WeeklyPlan
from app.models.weekly_planner_snapshot import WeeklyPlannerSnapshot
from app.models.weekly_planner_legend_entry import WeeklyPlannerLegendEntry
from app.models.department import Department
from app.services.task_classification import is_fast_task as is_fast_task_model
from app.services.task_marker import historical_marker_for_day
from app.services.system_task_schedule import matches_template_date
from app.services.project_display_title import build_project_display_title_map
from app.services.project_classification import (
    is_mst_or_tt_project as _is_mst_or_tt_project,
    is_mst_project as _is_mst_project,
    is_tt_project as _is_tt_project,
)
from app.schemas.planner import (
    MonthlyPlannerResponse,
    MonthlyPlannerSummary,
    WeeklyPlannerDay,
    WeeklyPlannerLegendEntryOut,
    WeeklyPlannerLegendEntryUpdate,
    WeeklyPlannerSaveDayRequest,
    WeeklyPlannerSaveDayResponse,
    WeeklyPlannerUserOrderUpdate,
    WeeklyPlannerUserVisibilityUpdate,
    WeeklyPlannerProject,
    WeeklyPlannerResponse,
    WeeklyTableDay,
    WeeklyTableDepartment,
    WeeklyTableProjectEntry,
    WeeklyTableProjectTaskEntry,
    WeeklyTableResponse,
    WeeklyTableTaskEntry,
    WeeklyTableUserDay,
)
from app.schemas.project import ProjectOut
from app.schemas.task import TaskAssigneeOut, TaskOut
from app.schemas.weekly_plan import WeeklyPlanCreate, WeeklyPlanOut, WeeklyPlanUpdate
from app.schemas.weekly_planner_snapshot import (
    WeeklySnapshotCompareAssigneeGroupOut,
    WeeklySnapshotCompareSummaryOut,
    WeeklySnapshotCompareTaskOut,
    WeeklySnapshotCompareOut,
    WeeklySnapshotCreateRequest,
    WeeklySnapshotLatestOut,
    WeeklySnapshotOut,
    WeeklySnapshotOverviewOut,
    WeeklySnapshotOverviewWeekOut,
    WeeklySnapshotPlanVsActualOut,
    WeeklySnapshotSaveMode,
    WeeklySnapshotSaveRequest,
    WeeklySnapshotSaveResponse,
    WeeklySnapshotTaskAssigneeOut,
    WeeklySnapshotTaskOccurrenceOut,
    WeeklySnapshotType,
    WeeklySnapshotVersionOut,
)


router = APIRouter()


def _parse_ko_user_id(internal_notes: str | None) -> uuid.UUID | None:
    """Parse ko_user_id from task internal_notes.
    
    The KO field is stored as 'ko_user_id=<uuid>' or 'ko_user_id: <uuid>' 
    in the internal_notes field.
    """
    if not internal_notes:
        return None
    # Match pattern: ko_user_id=<uuid> or ko_user_id: <uuid>
    match = re.search(r'ko_user_id[:=]\s*([a-f0-9-]+)', internal_notes, re.IGNORECASE)
    if match:
        try:
            return uuid.UUID(match.group(1))
        except (ValueError, AttributeError):
            return None
    return None


def _parse_origin_task_id(internal_notes: str | None) -> uuid.UUID | None:
    """Parse origin_task_id from task internal_notes."""
    if not internal_notes:
        return None
    match = re.search(r"origin_task_id[:=]\s*([a-f0-9-]+)", internal_notes, re.IGNORECASE)
    if not match:
        return None
    try:
        return uuid.UUID(match.group(1))
    except (ValueError, AttributeError):
        return None


def _parse_total_products(internal_notes: str | None) -> int | None:
    """Parse total_products from task internal_notes."""
    if not internal_notes:
        return None
    match = re.search(r"total_products[:=]\s*(\d+)", internal_notes, re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


COMPLETED_PRODUCTS_RE = re.compile(r"completed_products[:=]\s*(\d+)", re.IGNORECASE)


def _parse_completed_products(internal_notes: str | None) -> int | None:
    """Parse completed_products from task internal_notes."""
    if not internal_notes:
        return None
    match = COMPLETED_PRODUCTS_RE.search(internal_notes)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except Exception:
        return None
    if value < 0:
        return 0
    return value


def _extract_total_and_completed(
    total_hint: int | None,
    internal_notes: str | None,
) -> tuple[int | None, int | None]:
    total = total_hint
    if total is None:
        total = _parse_total_products(internal_notes)
    if total is not None and total < 0:
        total = 0
    completed = _parse_completed_products(internal_notes)
    return total, completed


def _build_weekly_task_product_metrics(
    *,
    base_total: int | None,
    base_completed: int | None,
    progress_counts: tuple[int, int] | None,
    is_mst_tt_task: bool,
    status_for_day: str,
) -> tuple[int | None, int | None, int | None, int | None, int | None]:
    """
    Build legacy and extended product metrics for weekly planner task entries.

    Returns:
    - effective_total (legacy total_products)
    - effective_completed (legacy completed_products)
    - weekly_planned (base weekly planned target)
    - day_total (total target for the rendered day)
    - day_done (cumulative done value as of the rendered day)
    """
    effective_total = base_total
    effective_completed = base_completed

    if progress_counts is not None:
        progress_completed, progress_total = progress_counts
        effective_completed = progress_completed
        if progress_total > 0:
            effective_total = progress_total
    elif is_mst_tt_task and effective_total is not None and effective_completed is None:
        effective_completed = 0

    if effective_total is not None and status_for_day == "DONE":
        if effective_completed is None or effective_completed < effective_total:
            effective_completed = effective_total

    weekly_planned = base_total
    day_total = effective_total
    day_done = effective_completed
    return effective_total, effective_completed, weekly_planned, day_total, day_done


def _should_add_empty_project_entry_for_department(
    department_id: uuid.UUID | None,
    product_content_department_ids: set[uuid.UUID],
) -> bool:
    """
    Decide whether a project may appear in Weekly Planner without any active tasks
    for the rendered user/day slot.

    Weekly Planner should only show projects when that day has active project tasks.
    """
    return False


def _is_note_origin_task(task: Task) -> bool:
    """GA/PX-JAV note copies keep their own start→due schedule per assignee."""
    return getattr(task, "ga_note_origin_id", None) is not None or getattr(task, "plan_note_origin_id", None) is not None


def _parse_production_date(internal_notes: str | None) -> date | None:
    """Parse production_date (YYYY-MM-DD) from task internal_notes."""
    if not internal_notes:
        return None
    match = re.search(r"production_date[:=]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", internal_notes, re.IGNORECASE)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d").date()
    except Exception:
        return None


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _month_range(year: int, month: int) -> tuple[date, date]:
    month_start = date(year, month, 1)
    next_month = date(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1)
    return month_start, next_month - timedelta(days=1)


def _as_utc_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date() if value.tzinfo else value.date()
    return value


def _as_local_date(value: datetime | date | None) -> date | None:
    """
    Extract the date component from a datetime, preserving the local date meaning.
    For planning purposes, we want the date in APP_TIMEZONE, not UTC.
    
    When PostgreSQL stores a date like "2026-02-05 00:00:00+01" (midnight in local timezone),
    it stores the UTC equivalent "2026-02-04 23:00:00 UTC". SQLAlchemy retrieves it as UTC.
    We need to convert back to APP_TIMEZONE before extracting the date.
    
    Example:
    - Input: 2026-02-04 23:00:00+00:00 (UTC representation of 2026-02-05 00:00:00+01)
    - Output: 2026-02-05 (the intended local date in APP_TIMEZONE)
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo:
            local_dt = value.astimezone(_app_tz())
            # Extract date from local timezone datetime
            return local_dt.date()
        else:
            # Naive datetime, use as-is
            return value.date()
    # Already a date
    return value


def _app_tz():
    """
    Resolve APP_TIMEZONE with fallbacks.

    Note: This file supports both zoneinfo and pytz fallbacks for older environments.
    """
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


def _today_app_date() -> date:
    return datetime.now(timezone.utc).astimezone(_app_tz()).date()


async def _assignees_for_tasks(
    db: AsyncSession, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[TaskAssigneeOut]]:
    if not task_ids:
        return {}

    explicit_assignees = select(
        TaskAssignee.task_id.label("task_id"),
        TaskAssignee.user_id.label("user_id"),
    ).where(TaskAssignee.task_id.in_(task_ids))
    has_explicit_assignee = exists(
        select(1).where(TaskAssignee.task_id == Task.id)
    ).correlate(Task)
    fallback_assignees = select(
        Task.id.label("task_id"),
        Task.assigned_to.label("user_id"),
    ).where(
        Task.id.in_(task_ids),
        Task.assigned_to.is_not(None),
        ~has_explicit_assignee,
    )
    effective_assignees = union_all(explicit_assignees, fallback_assignees).subquery()
    rows = (
        await db.execute(
            select(
                effective_assignees.c.task_id,
                User.id,
                User.email,
                User.username,
                User.full_name,
            )
            .join(User, effective_assignees.c.user_id == User.id)
            .order_by(User.full_name)
        )
    ).all()
    assignees: dict[uuid.UUID, list[TaskAssigneeOut]] = {task_id: [] for task_id in task_ids}
    for task_id, user_id, email, username, full_name in rows:
        assignees.setdefault(task_id, []).append(
            TaskAssigneeOut(
                id=user_id,
                email=email,
                username=username,
                full_name=full_name,
            )
        )
    return assignees


def _task_to_out(t: Task, assignees: list[TaskAssigneeOut] | None = None) -> TaskOut:
    # Convert string values to enums
    status_enum = TaskStatus(t.status) if t.status else TaskStatus.TODO
    priority_enum = TaskPriority(t.priority) if t.priority else TaskPriority.NORMAL
    finish_period_enum = TaskFinishPeriod(t.finish_period) if t.finish_period else None
    phase_enum = ProjectPhaseStatus(t.phase) if t.phase else ProjectPhaseStatus.MEETINGS
    
    return TaskOut(
        id=t.id,
        title=t.title,
        description=t.description,
        internal_notes=t.internal_notes,
        project_id=t.project_id,
        dependency_task_id=t.dependency_task_id,
        department_id=t.department_id,
        assigned_to=t.assigned_to,
        assignees=assignees or [],
        created_by=t.created_by,
        ga_note_origin_id=t.ga_note_origin_id,
        plan_note_origin_id=t.plan_note_origin_id,
        system_template_origin_id=t.system_template_origin_id,
        status=status_enum,
        priority=priority_enum,
        finish_period=finish_period_enum,
        phase=phase_enum,
        progress_percentage=t.progress_percentage,
        daily_products=t.daily_products,
        start_date=t.start_date,
        due_date=t.due_date,
        completed_at=t.completed_at,
        is_deadline_important=t.is_deadline_important,
        is_bllok=t.is_bllok,
        is_1h_report=t.is_1h_report,
        is_r1=t.is_r1,
        is_personal=t.is_personal,
        is_active=t.is_active,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def _project_to_out(p: Project) -> ProjectOut:
    # Convert string values to enums
    from app.models.enums import ProjectType
    
    project_type_enum = None
    if p.project_type:
        try:
            project_type_enum = ProjectType(p.project_type)
        except ValueError:
            project_type_enum = None
    
    phase_enum = ProjectPhaseStatus(p.current_phase) if p.current_phase else ProjectPhaseStatus.MEETINGS
    status_enum = TaskStatus(p.status) if p.status else TaskStatus.TODO
    
    return ProjectOut(
        id=p.id,
        title=p.title,
        description=p.description,
        department_id=p.department_id,
        manager_id=p.manager_id,
        created_by=p.created_by,
        project_type=project_type_enum,
        current_phase=phase_enum,
        status=status_enum,
        progress_percentage=p.progress_percentage,
        total_products=p.total_products,
        is_template=p.is_template,
        start_date=p.start_date,
        due_date=p.due_date,
        completed_at=p.completed_at,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _get_next_5_working_days(start_date: date) -> list[date]:
    """Get next 5 working days (Monday-Friday) starting from start_date.
    If start_date is a weekend, starts from next Monday."""
    # If start_date is Saturday (5) or Sunday (6), move to next Monday
    if start_date.weekday() >= 5:
        days_until_monday = 7 - start_date.weekday()
        start_date = start_date + timedelta(days=days_until_monday)
    
    working_days = []
    current = start_date
    while len(working_days) < 5:
        # Monday = 0, Sunday = 6
        if current.weekday() < 5:  # Monday to Friday
            working_days.append(current)
        current += timedelta(days=1)
    return working_days


def _safe_iso_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback


def _parse_annual_leave_for_snapshot(
    entry: CommonEntry,
) -> tuple[date, date, bool, str | None, str | None, str | None]:
    note = entry.description or ""
    base_date = entry.entry_date or entry.created_at.date()
    start_date = base_date
    end_date = base_date
    full_day = True
    start_time: str | None = None
    end_time: str | None = None

    date_range_match = re.search(r"Date range:\s*(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})", note, re.I)
    if date_range_match:
        start_date = _safe_iso_date(date_range_match.group(1), start_date)
        end_date = _safe_iso_date(date_range_match.group(2), end_date)
        note = re.sub(
            r"Date range:\s*\d{4}-\d{2}-\d{2}\s+to\s+\d{4}-\d{2}-\d{2}",
            "",
            note,
            flags=re.I,
        ).strip()
    else:
        date_match = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", note, re.I)
        if date_match:
            parsed = _safe_iso_date(date_match.group(1), start_date)
            start_date = parsed
            end_date = parsed
            note = re.sub(r"Date:\s*\d{4}-\d{2}-\d{2}", "", note, flags=re.I).strip()
        else:
            date_matches = re.findall(r"\d{4}-\d{2}-\d{2}", note)
            if date_matches:
                start_date = _safe_iso_date(date_matches[0], start_date)
                end_date = _safe_iso_date(date_matches[1] if len(date_matches) > 1 else date_matches[0], end_date)

    if re.search(r"\(Full day\)", note, re.I):
        full_day = True
        note = re.sub(r"\(Full day\)", "", note, flags=re.I).strip()
    else:
        time_match = re.search(r"\((\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\)", note)
        if time_match:
            full_day = False
            start_time = time_match.group(1)
            end_time = time_match.group(2)
            note = re.sub(r"\(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\)", "", note).strip()

    cleaned_note = note.strip() if note.strip() else None
    return start_date, end_date, full_day, start_time, end_time, cleaned_note


async def _load_pv_fest_blocks_for_snapshot(
    *,
    db: AsyncSession,
    department_id: uuid.UUID,
    week_start: date,
    week_end: date,
) -> list[dict]:
    users_in_department = (
        await db.execute(select(User.id).where(User.department_id == department_id, User.is_active == True))
    ).scalars().all()
    if not users_in_department:
        return []

    entries_stmt = select(CommonEntry).where(CommonEntry.category == CommonCategory.annual_leave).where(
        (CommonEntry.assigned_to_user_id.in_(users_in_department))
        | (
            (CommonEntry.assigned_to_user_id.is_(None))
            & (CommonEntry.created_by_user_id.in_(users_in_department))
        )
    )
    entries = (await db.execute(entries_stmt.order_by(CommonEntry.created_at.desc()))).scalars().all()

    blocks: list[dict] = []
    for entry in entries:
        entry_user_id = entry.assigned_to_user_id or entry.created_by_user_id
        start_date, end_date, full_day, start_time, end_time, note = _parse_annual_leave_for_snapshot(entry)
        if end_date < week_start or start_date > week_end:
            continue
        blocks.append(
            {
                "entry_id": entry.id,
                "user_id": entry_user_id,
                "start_date": start_date,
                "end_date": end_date,
                "full_day": full_day,
                "start_time": start_time,
                "end_time": end_time,
                "note": note,
            }
        )
    return blocks


def _snapshot_type_for_mode(mode: WeeklySnapshotSaveMode) -> WeeklySnapshotType:
    if mode == WeeklySnapshotSaveMode.THIS_WEEK_FINAL:
        return WeeklySnapshotType.FINAL
    return WeeklySnapshotType.PLANNED


def _snapshot_week_start_for_mode(mode: WeeklySnapshotSaveMode, today: date) -> date:
    if mode == WeeklySnapshotSaveMode.THIS_WEEK_FINAL:
        return _week_start(today)
    return _week_start(today + timedelta(days=7))


def _snapshot_version_out(
    snapshot: WeeklyPlannerSnapshot,
    *,
    is_official: bool = False,
) -> WeeklySnapshotVersionOut:
    return WeeklySnapshotVersionOut(
        id=snapshot.id,
        department_id=snapshot.department_id,
        week_start_date=snapshot.week_start_date,
        week_end_date=snapshot.week_end_date,
        snapshot_type=WeeklySnapshotType(snapshot.snapshot_type),
        created_by=snapshot.created_by,
        created_at=snapshot.created_at,
        is_official=is_official,
    )


def _snapshot_out(
    snapshot: WeeklyPlannerSnapshot,
    *,
    is_official: bool = False,
) -> WeeklySnapshotOut:
    return WeeklySnapshotOut(
        id=snapshot.id,
        department_id=snapshot.department_id,
        week_start_date=snapshot.week_start_date,
        week_end_date=snapshot.week_end_date,
        snapshot_type=WeeklySnapshotType(snapshot.snapshot_type),
        created_by=snapshot.created_by,
        created_at=snapshot.created_at,
        is_official=is_official,
        payload=snapshot.payload,
    )


NO_PLAN_SNAPSHOT_MESSAGE = (
    "No plan snapshot found for this week. Please create the weekly plan on Friday (Next Week) first."
)


def _normalize_task_status(value: str | None) -> str:
    if not value:
        return "TODO"
    normalized = value.strip().upper().replace(" ", "_")
    if normalized == "TO_DO":
        return "TODO"
    if normalized == "INPROGRESS":
        return "IN_PROGRESS"
    if normalized in {"WAITINGCLIENT", "WAITING_FOR_CLIENT", "WFE"}:
        return "WAITING_CLIENT"
    if normalized == "WAITINGCONFIRMATION":
        return "WAITING_CONFIRMATION"
    if normalized == "WAITING_CONFIRMATION":
        return "WAITING_CONFIRMATION"
    return normalized


def _status_rank(value: str | None) -> int:
    normalized = _normalize_task_status(value)
    if normalized == "DONE":
        return 5
    if normalized == "WAITING_CONFIRMATION":
        return 4
    if normalized == "WAITING_CLIENT":
        return 3
    if normalized == "IN_PROGRESS":
        return 2
    if normalized == "TODO":
        return 1
    return 0


def _pick_stronger_status(current: str | None, candidate: str | None) -> str | None:
    if candidate is None:
        return current
    if current is None:
        return _normalize_task_status(candidate)
    return (
        _normalize_task_status(candidate)
        if _status_rank(candidate) >= _status_rank(current)
        else _normalize_task_status(current)
    )


def _parse_uuid_value(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _parse_iso_date_value(value: str | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value[:10])
    except Exception:
        return None


def _parse_iso_datetime_value(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        normalized = value.replace("Z", "+00:00") if isinstance(value, str) else str(value)
        return datetime.fromisoformat(normalized)
    except Exception:
        return None


def _entry_is_completed(
    *,
    status: str | None,
    daily_status: str | None,
    completed_at: datetime | None,
) -> bool:
    if completed_at is not None:
        return True
    if _normalize_task_status(status) == "DONE":
        return True
    if _normalize_task_status(daily_status) == "DONE":
        return True
    return False


def _status_for_day(
    *,
    status: str | None,
    daily_status: str | None,
    completed_at: datetime | None,
    day_date: date | None,
) -> str:
    normalized = _normalize_task_status(status)
    normalized_daily = _normalize_task_status(daily_status) if daily_status is not None else None
    completed_date = _as_local_date(completed_at) if completed_at is not None else None

    # An explicit task completion is authoritative for its completion day. This
    # also repairs display of legacy rows whose daily status remained stale.
    if normalized == "DONE" and completed_date is not None and day_date == completed_date:
        return "DONE"

    if normalized_daily == "DONE":
        return "DONE"
    if normalized_daily == "IN_PROGRESS":
        return "IN_PROGRESS"
    if normalized_daily == "WAITING_CLIENT":
        return "WAITING_CLIENT"
    if normalized_daily == "WAITING_CONFIRMATION":
        return "WAITING_CONFIRMATION"
    if normalized_daily is not None:
        return "TODO"

    if completed_date is not None and day_date is not None:
        if day_date == completed_date:
            return "DONE"
        if normalized == "DONE":
            return "IN_PROGRESS"

    if normalized == "DONE" and completed_date is None:
        return "DONE"

    if normalized in {"WAITING_CLIENT", "WAITING_CONFIRMATION"}:
        return normalized
    return "TODO" if normalized == "TODO" else "IN_PROGRESS"


def _override_daily_status_from_progress(
    daily_status: TaskStatus | None,
    progress_counts: tuple[int, int] | None,
) -> TaskStatus | None:
    """When per-day product counts are complete, treat the day as DONE even if daily_status is stale."""
    if progress_counts is None:
        return daily_status
    completed, total = progress_counts
    if total > 0 and completed >= total:
        return TaskStatus.DONE
    return daily_status


def _build_task_fallback_key(
    *,
    title: str,
    source_type: str,
    project_id: uuid.UUID | None,
) -> str:
    normalized_title = " ".join((title or "").strip().lower().split())
    normalized_source = (source_type or "").strip().lower()
    return f"{normalized_source}|{project_id or ''}|{normalized_title}"


def _task_ids_from_department_payload(department_payload: dict | None) -> set[uuid.UUID]:
    if not department_payload:
        return set()

    task_ids: set[uuid.UUID] = set()
    for day in department_payload.get("days") or []:
        for user_day in day.get("users") or []:
            for bucket_name in ("am_projects", "pm_projects"):
                for project in user_day.get(bucket_name) or []:
                    for task in project.get("tasks") or []:
                        task_id = _parse_uuid_value(task.get("task_id"))
                        if task_id is not None:
                            task_ids.add(task_id)
            for bucket_name in ("am_system_tasks", "pm_system_tasks", "am_fast_tasks", "pm_fast_tasks"):
                for task in user_day.get(bucket_name) or []:
                    task_id = _parse_uuid_value(task.get("task_id"))
                    if task_id is not None:
                        task_ids.add(task_id)
    return task_ids


def _normalize_task_items_payload(task_items: list[dict] | None) -> list[dict]:
    if not task_items:
        return []

    normalized_items: list[dict] = []
    for item in task_items:
        task_id = _parse_uuid_value(item.get("task_id"))
        project_id = _parse_uuid_value(item.get("project_id"))
        completed_at = _parse_iso_datetime_value(item.get("completed_at"))
        title = (item.get("title") or "").strip() or "(Untitled task)"
        source_type = item.get("source_type") or "project"
        finish_period = item.get("finish_period")
        fallback_key = item.get("fallback_key")
        if task_id is None:
            fallback_key = _build_task_fallback_key(
                title=title,
                source_type=source_type,
                project_id=project_id,
            )
        assignees_raw = item.get("assignees") or []
        assignees = [
            {
                "assignee_id": _parse_uuid_value(assignee.get("assignee_id")),
                "assignee_name": (assignee.get("assignee_name") or "").strip() or "Unassigned",
            }
            for assignee in assignees_raw
        ]
        occurrences_raw = item.get("occurrences") or []
        occurrences = [
            {
                "day": _parse_iso_date_value(occurrence.get("day")),
                "time_slot": occurrence.get("time_slot"),
                "assignee_id": _parse_uuid_value(occurrence.get("assignee_id")),
                "assignee_name": occurrence.get("assignee_name"),
            }
            for occurrence in occurrences_raw
        ]
        status = _normalize_task_status(item.get("status"))
        daily_status = _normalize_task_status(item.get("daily_status")) if item.get("daily_status") else None
        normalized_items.append(
            {
                "match_key": f"id:{task_id}" if task_id is not None else f"fallback:{fallback_key or ''}",
                "task_id": task_id,
                "fallback_key": fallback_key,
                "title": title,
                "project_id": project_id,
                "project_title": item.get("project_title"),
                "source_type": source_type,
                "status": status,
                "daily_status": daily_status,
                "completed_at": completed_at,
                "is_completed": bool(item.get("is_completed"))
                or _entry_is_completed(status=status, daily_status=daily_status, completed_at=completed_at),
                "finish_period": finish_period,
                "priority": item.get("priority"),
                "tags": sorted(set(item.get("tags") or [])),
                "assignees": assignees,
                "occurrences": occurrences,
            }
        )
    return normalized_items


def _flatten_weekly_department_tasks(
    department_payload: dict | None,
    *,
    task_priority_map: dict[uuid.UUID, str] | None = None,
) -> list[dict]:
    if not department_payload:
        return []

    priorities = task_priority_map or {}
    index: dict[str, dict] = {}

    def ensure_row(
        *,
        task_id: uuid.UUID | None,
        title: str,
        source_type: str,
        project_id: uuid.UUID | None,
        project_title: str | None,
        finish_period: str | None,
        fallback_key: str,
    ) -> dict:
        match_key = f"id:{task_id}" if task_id is not None else f"fallback:{fallback_key}"
        if match_key not in index:
            index[match_key] = {
                "match_key": match_key,
                "task_id": task_id,
                "fallback_key": None if task_id is not None else fallback_key,
                "title": title,
                "project_id": project_id,
                "project_title": project_title,
                "source_type": source_type,
                "status": None,
                "daily_status": None,
                "completed_at": None,
                "is_completed": False,
                "finish_period": finish_period,
                "priority": priorities.get(task_id) if task_id is not None else None,
                "_tags": set(),
                "_assignees": {},
                "_occurrence_keys": set(),
                "occurrences": [],
            }
        row = index[match_key]
        if not row.get("title") and title:
            row["title"] = title
        if not row.get("project_title") and project_title:
            row["project_title"] = project_title
        if not row.get("finish_period") and finish_period:
            row["finish_period"] = finish_period
        if task_id is not None and row.get("priority") is None:
            row["priority"] = priorities.get(task_id)
        return row

    def add_task_entry(
        *,
        task_entry: dict,
        source_type: str,
        project_id: str | None,
        project_title: str | None,
        day_iso: str | date | None,
        slot: str,
        user_id: str | uuid.UUID | None,
        user_name: str | None,
    ) -> None:
        task_id = _parse_uuid_value(task_entry.get("task_id"))
        project_uuid = _parse_uuid_value(project_id)
        title = (task_entry.get("task_title") or task_entry.get("title") or "").strip() or "(Untitled task)"
        finish_period = task_entry.get("finish_period")
        fallback_key = _build_task_fallback_key(
            title=title,
            source_type=source_type,
            project_id=project_uuid,
        )
        row = ensure_row(
            task_id=task_id,
            title=title,
            source_type=source_type,
            project_id=project_uuid,
            project_title=project_title,
            finish_period=finish_period,
            fallback_key=fallback_key,
        )

        status = _normalize_task_status(task_entry.get("status"))
        daily_status_value = task_entry.get("daily_status")
        daily_status = (
            _normalize_task_status(daily_status_value) if daily_status_value is not None else None
        )
        completed_at = _parse_iso_datetime_value(task_entry.get("completed_at"))

        row["status"] = _pick_stronger_status(row.get("status"), status)
        row["daily_status"] = _pick_stronger_status(row.get("daily_status"), daily_status)
        if row.get("completed_at") is None and completed_at is not None:
            row["completed_at"] = completed_at
        row["is_completed"] = bool(row.get("is_completed")) or _entry_is_completed(
            status=status,
            daily_status=daily_status,
            completed_at=completed_at,
        )

        if task_entry.get("is_bllok"):
            row["_tags"].add("BLL")
        if task_entry.get("is_r1"):
            row["_tags"].add("R1")
        if task_entry.get("is_1h_report"):
            row["_tags"].add("1H")
        if task_entry.get("is_personal"):
            row["_tags"].add("P:")
        if task_entry.get("ga_note_origin_id"):
            row["_tags"].add("GA")
        if task_entry.get("plan_note_origin_id"):
            row["_tags"].add("PX JAV")
        if task_entry.get("fast_task_type"):
            row["_tags"].add(str(task_entry.get("fast_task_type")).strip().upper())

        assignee_uuid = _parse_uuid_value(user_id)
        assignee_name = (user_name or "").strip() or "Unassigned"
        assignee_key = str(assignee_uuid) if assignee_uuid is not None else f"name:{assignee_name.lower()}"
        row["_assignees"][assignee_key] = {
            "assignee_id": assignee_uuid,
            "assignee_name": assignee_name,
        }

        day_value = _parse_iso_date_value(day_iso)
        occurrence_key = f"{day_value}|{slot}|{assignee_key}"
        if occurrence_key not in row["_occurrence_keys"]:
            row["_occurrence_keys"].add(occurrence_key)
            row["occurrences"].append(
                {
                    "day": day_value,
                    "time_slot": slot,
                    "assignee_id": assignee_uuid,
                    "assignee_name": assignee_name,
                }
            )

    for day in department_payload.get("days") or []:
        day_date = day.get("date")
        for user_day in day.get("users") or []:
            user_id = user_day.get("user_id")
            user_name = user_day.get("user_name")
            for slot_key, slot_label in (("am", "AM"), ("pm", "PM")):
                project_bucket = user_day.get(f"{slot_key}_projects") or []
                for project in project_bucket:
                    project_id = project.get("project_id")
                    project_title = project.get("project_title")
                    for task in project.get("tasks") or []:
                        add_task_entry(
                            task_entry=task,
                            source_type="project",
                            project_id=project_id,
                            project_title=project_title,
                            day_iso=day_date,
                            slot=slot_label,
                            user_id=user_id,
                            user_name=user_name,
                        )
                for source_type, task_bucket_name in (
                    ("system", f"{slot_key}_system_tasks"),
                    ("fast", f"{slot_key}_fast_tasks"),
                ):
                    for task in user_day.get(task_bucket_name) or []:
                        add_task_entry(
                            task_entry=task,
                            source_type=source_type,
                            project_id=None,
                            project_title=None,
                            day_iso=day_date,
                            slot=slot_label,
                            user_id=user_id,
                            user_name=user_name,
                        )

    rows: list[dict] = []
    for row in index.values():
        assignees = sorted(
            row["_assignees"].values(),
            key=lambda assignee: (
                1 if assignee["assignee_id"] is None else 0,
                (assignee["assignee_name"] or "").lower(),
            ),
        )
        occurrences = sorted(
            row["occurrences"],
            key=lambda occurrence: (
                occurrence.get("day") or date.min,
                occurrence.get("time_slot") or "",
                occurrence.get("assignee_name") or "",
            ),
        )
        rows.append(
            {
                "match_key": row["match_key"],
                "task_id": row["task_id"],
                "fallback_key": row["fallback_key"],
                "title": row["title"],
                "project_id": row["project_id"],
                "project_title": row["project_title"],
                "source_type": row["source_type"],
                "status": row["status"],
                "daily_status": row["daily_status"],
                "completed_at": row["completed_at"],
                "is_completed": bool(row["is_completed"]),
                "finish_period": row["finish_period"],
                "priority": row["priority"],
                "tags": sorted(row["_tags"]),
                "assignees": assignees,
                "occurrences": occurrences,
            }
        )

    rows.sort(key=lambda task: (task.get("title") or "").lower())
    return rows


async def _load_task_priority_map(
    db: AsyncSession,
    task_ids: set[uuid.UUID],
) -> dict[uuid.UUID, str]:
    if not task_ids:
        return {}
    rows = (
        await db.execute(
            select(Task.id, Task.priority).where(Task.id.in_(list(task_ids)))
        )
    ).all()
    return {task_id: priority for task_id, priority in rows if priority is not None}


def _to_compare_task_out(task: dict) -> WeeklySnapshotCompareTaskOut:
    assignees = [
        WeeklySnapshotTaskAssigneeOut(
            assignee_id=assignee.get("assignee_id"),
            assignee_name=assignee.get("assignee_name") or "Unassigned",
        )
        for assignee in (task.get("assignees") or [])
    ]
    occurrences = [
        WeeklySnapshotTaskOccurrenceOut(
            day=occurrence.get("day"),
            time_slot=occurrence.get("time_slot"),
            assignee_id=occurrence.get("assignee_id"),
            assignee_name=occurrence.get("assignee_name"),
        )
        for occurrence in (task.get("occurrences") or [])
    ]
    return WeeklySnapshotCompareTaskOut(
        match_key=task.get("match_key") or "",
        task_id=task.get("task_id"),
        fallback_key=task.get("fallback_key"),
        title=task.get("title") or "(Untitled task)",
        project_id=task.get("project_id"),
        project_title=task.get("project_title"),
        source_type=task.get("source_type") or "project",
        status=task.get("status"),
        daily_status=task.get("daily_status"),
        completed_at=task.get("completed_at"),
        is_completed=bool(task.get("is_completed")),
        finish_period=task.get("finish_period"),
        priority=task.get("priority"),
        tags=task.get("tags") or [],
        assignees=assignees,
        occurrences=occurrences,
    )


def _tasks_by_key_from_snapshot_payload(payload: dict) -> dict[str, dict]:
    task_items = _normalize_task_items_payload(payload.get("task_items"))
    if not task_items:
        task_items = _flatten_weekly_department_tasks(payload.get("department"))
    return {task["match_key"]: task for task in task_items if task.get("match_key")}


def _planned_last_day_for_task(planned_task: dict, *, week_end: date) -> date:
    occurrences = planned_task.get("occurrences") or []
    days = [occurrence.get("day") for occurrence in occurrences if occurrence.get("day") is not None]
    return max(days) if days else week_end


def _effective_status(task: dict) -> str:
    daily_status = task.get("daily_status")
    status_value = daily_status if daily_status is not None else task.get("status")
    return _normalize_task_status(status_value)


def _merge_planned_view(*, planned_task: dict, actual_task: dict) -> dict:
    merged = dict(actual_task)
    merged["assignees"] = planned_task.get("assignees") or []
    merged["occurrences"] = planned_task.get("occurrences") or []
    if merged.get("finish_period") is None and planned_task.get("finish_period") is not None:
        merged["finish_period"] = planned_task.get("finish_period")
    return merged


def _classify_weekly_plan_performance(
    *,
    planned_tasks: dict[str, dict],
    actual_tasks: dict[str, dict],
    week_end: date,
    as_of_date: date,
) -> dict[str, list[dict]]:
    completed: list[dict] = []
    in_progress: list[dict] = []
    pending: list[dict] = []
    late: list[dict] = []
    additional: list[dict] = []
    removed_or_canceled: list[dict] = []

    for match_key, planned_task in planned_tasks.items():
        actual_task = actual_tasks.get(match_key)
        if actual_task is None:
            removed_or_canceled.append(planned_task)
            continue

        merged = _merge_planned_view(planned_task=planned_task, actual_task=actual_task)
        if merged.get("is_completed"):
            completed.append(merged)
            continue

        planned_last_day = _planned_last_day_for_task(planned_task, week_end=week_end)
        if planned_last_day < as_of_date:
            late.append(merged)
            continue

        effective = _effective_status(merged)
        if effective == "IN_PROGRESS":
            in_progress.append(merged)
        else:
            pending.append(merged)

    for match_key, actual_task in actual_tasks.items():
        if match_key not in planned_tasks:
            additional.append(actual_task)

    return {
        "completed": completed,
        "in_progress": in_progress,
        "pending": pending,
        "late": late,
        "additional": additional,
        "removed_or_canceled": removed_or_canceled,
    }


def _group_compare_tasks_by_assignee(
    *,
    completed: list[WeeklySnapshotCompareTaskOut],
    in_progress: list[WeeklySnapshotCompareTaskOut],
    pending: list[WeeklySnapshotCompareTaskOut],
    late: list[WeeklySnapshotCompareTaskOut],
    additional: list[WeeklySnapshotCompareTaskOut],
    removed_or_canceled: list[WeeklySnapshotCompareTaskOut],
) -> list[WeeklySnapshotCompareAssigneeGroupOut]:
    groups: dict[str, dict] = {}

    def ensure_group(assignee: WeeklySnapshotTaskAssigneeOut | None) -> dict:
        assignee_id = assignee.assignee_id if assignee else None
        assignee_name = (assignee.assignee_name if assignee else None) or "Unassigned"
        key = str(assignee_id) if assignee_id is not None else f"name:{assignee_name.lower()}"
        if key not in groups:
            groups[key] = {
                "assignee_id": assignee_id,
                "assignee_name": assignee_name,
                "completed": [],
                "in_progress": [],
                "pending": [],
                "late": [],
                "additional": [],
                "not_completed": [],
                "added_during_week": [],
                "removed_or_canceled": [],
                "_completed_keys": set(),
                "_in_progress_keys": set(),
                "_pending_keys": set(),
                "_late_keys": set(),
                "_additional_keys": set(),
                "_removed_keys": set(),
            }
        return groups[key]

    def add_category(category: str, tasks: list[WeeklySnapshotCompareTaskOut], key_name: str) -> None:
        for task in tasks:
            assignees = task.assignees or [WeeklySnapshotTaskAssigneeOut(assignee_name="Unassigned")]
            for assignee in assignees:
                group = ensure_group(assignee)
                if task.match_key in group[key_name]:
                    continue
                group[key_name].add(task.match_key)
                group[category].append(task)

    add_category("completed", completed, "_completed_keys")
    add_category("in_progress", in_progress, "_in_progress_keys")
    add_category("pending", pending, "_pending_keys")
    add_category("late", late, "_late_keys")
    add_category("additional", additional, "_additional_keys")
    add_category("removed_or_canceled", removed_or_canceled, "_removed_keys")

    grouped_rows = []
    for group in groups.values():
        group["completed"].sort(key=lambda task: task.title.lower())
        group["in_progress"].sort(key=lambda task: task.title.lower())
        group["pending"].sort(key=lambda task: task.title.lower())
        group["late"].sort(key=lambda task: task.title.lower())
        group["additional"].sort(key=lambda task: task.title.lower())
        group["removed_or_canceled"].sort(key=lambda task: task.title.lower())

        # Back-compat aggregate buckets (older UI)
        group["not_completed"] = sorted(
            [*group["in_progress"], *group["pending"], *group["late"]],
            key=lambda task: task.title.lower(),
        )
        group["added_during_week"] = list(group["additional"])
        grouped_rows.append(
            WeeklySnapshotCompareAssigneeGroupOut(
                assignee_id=group["assignee_id"],
                assignee_name=group["assignee_name"],
                completed=group["completed"],
                in_progress=group["in_progress"],
                pending=group["pending"],
                late=group["late"],
                additional=group["additional"],
                not_completed=group["not_completed"],
                added_during_week=group["added_during_week"],
                removed_or_canceled=group["removed_or_canceled"],
            )
        )

    grouped_rows.sort(
        key=lambda group: (
            1 if group.assignee_id is None else 0,
            group.assignee_name.lower(),
        )
    )
    return grouped_rows


@router.get("/weekly", response_model=WeeklyPlannerResponse)
async def weekly_planner(
    week_start: date | None = None,
    department_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> WeeklyPlannerResponse:
    today = datetime.now(timezone.utc).date()
    week_start_date = week_start or _week_start(today)
    # Get next 5 working days (Monday-Friday)
    working_days = _get_next_5_working_days(week_start_date)
    week_end = working_days[-1]

    if user.role == UserRole.STAFF:
        user_id = user.id
        department_id = user.department_id

    # Handle "All Departments" case - if department_id is provided, check access
    # If not provided (None), admins and managers can see all, others see their department
    if department_id is not None:
        ensure_department_access(user, department_id)
    elif user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        # Non-admin/manager users without department_id should see their own department
        department_id = user.department_id

    # Get active projects (not completed, not templates)
    project_stmt = select(Project).where(
        Project.completed_at.is_(None),
        Project.is_template == False,
    )
    if department_id is not None:
        project_stmt = project_stmt.where(Project.department_id == department_id)
    projects = (await db.execute(project_stmt.order_by(Project.created_at))).scalars().all()
    project_map = {p.id: p for p in projects}

    # Get all active tasks (including completed ones so they can show through completion day)
    task_stmt = select(Task).where(Task.is_active == True)
    if department_id is not None:
        task_stmt = task_stmt.where(Task.department_id == department_id)

    # SQL-level date filter: only load tasks relevant to this week ±60 days.
    # Tasks far outside the window would never appear in the UI anyway.
    _lookahead = timedelta(days=60)
    _done_cutoff = week_start_date - timedelta(days=30)
    task_stmt = task_stmt.where(
        or_(
            Task.due_date.is_(None),
            Task.due_date.between(
                week_start_date - _lookahead,
                week_end + _lookahead,
            ),
        )
    ).where(
        or_(
            Task.status != TaskStatus.DONE.value,
            Task.completed_at >= _done_cutoff,
        )
    )

    # Note: We don't filter by user_id at SQL level to allow KO field checking in Python
    # Filtering by user will be done after fetching tasks

    all_tasks = (await db.execute(task_stmt.order_by(Task.due_date.nullsfirst(), Task.created_at))).scalars().all()
    
    # Filter by user_id if provided (check assigned_to, assignees, and KO field for MST/TT Control phase)
    if user_id is not None:
        # Get task IDs with this user as assignee
        task_ids_with_assignee = (
            await db.execute(
                select(TaskAssignee.task_id).where(TaskAssignee.user_id == user_id).distinct()
            )
        ).scalars().all()
        task_ids_with_assignee_set = set(task_ids_with_assignee)
        
        # Filter tasks: include if assigned_to matches, assignee matches, or KO field matches (for MST/TT Control)
        filtered_tasks = []
        for t in all_tasks:
            if t.project_id is not None and t.phase == ProjectPhaseStatus.CONTROL.value:
                project = project_map.get(t.project_id)
                if project is not None and _is_mst_or_tt_project(project):
                    ko_user_id = _parse_ko_user_id(t.internal_notes)
                    if ko_user_id is not None:
                        if ko_user_id == user_id:
                            filtered_tasks.append(t)
                        continue

            # Check assigned_to
            if t.assigned_to == user_id:
                filtered_tasks.append(t)
                continue
            # Check assignees
            if t.id in task_ids_with_assignee_set:
                filtered_tasks.append(t)
                continue

        all_tasks = filtered_tasks
    
    # Get task assignees
    task_ids = [t.id for t in all_tasks]
    assignee_map = await _assignees_for_tasks(db, task_ids)

    # Prefetch active system task templates and resolve assignees for weekly planner display.
    # Weekly Planner must show only the occurrences that belong to the selected week and day (no overdue/late).
    system_templates = (
        await db.execute(
            select(SystemTaskTemplate)
            .where(SystemTaskTemplate.is_active.is_(True))
            .where(SystemTaskTemplate.approval_status == CommonApprovalStatus.approved)
        )
    ).scalars().all()
    system_template_ids = [t.id for t in system_templates]
    # template_id -> set[user_id]
    system_template_assignees: dict[uuid.UUID, set[uuid.UUID]] = {tid: set() for tid in system_template_ids}
    if system_template_ids:
        sys_tasks = (
            await db.execute(
                select(Task.id, Task.system_template_origin_id, Task.assigned_to)
                .where(Task.system_template_origin_id.in_(system_template_ids))
            )
        ).all()
        sys_task_ids = [row[0] for row in sys_tasks]
        task_assignee_rows = []
        if sys_task_ids:
            task_assignee_rows = (
                await db.execute(
                    select(TaskAssignee.task_id, TaskAssignee.user_id).where(TaskAssignee.task_id.in_(sys_task_ids))
                )
            ).all()
        assignees_by_task: dict[uuid.UUID, set[uuid.UUID]] = {}
        for task_id, user_id in task_assignee_rows:
            assignees_by_task.setdefault(task_id, set()).add(user_id)
        for task_id, template_id, assigned_to in sys_tasks:
            if template_id is None:
                continue
            explicit = assignees_by_task.get(task_id) or set()
            if explicit:
                system_template_assignees.setdefault(template_id, set()).update(explicit)
            elif assigned_to is not None:
                system_template_assignees.setdefault(template_id, set()).add(assigned_to)
        # fallback to template.default_assignee_id when no Task/TaskAssignee mapping exists
        for tmpl in system_templates:
            if not system_template_assignees.get(tmpl.id) and tmpl.default_assignee_id is not None:
                system_template_assignees.setdefault(tmpl.id, set()).add(tmpl.default_assignee_id)

    # Weekly Planner = planning-only (no overdue/late, no carry-over).
    def _planned_range_weekly(task: Task) -> tuple[date | None, date | None]:
        if task.due_date is None:
            return None, None
        due = _as_local_date(task.due_date)
        if due is None:
            return None, None
        
        # MST/TT project tasks: show only on due_date (ignore start_date),
        # except GA/PX note copies which keep each assignee's start→due window.
        is_mst_tt_project = False
        if task.project_id and task.project_id in project_map:
            project = project_map[task.project_id]
            if project:
                is_mst_tt_project = _is_mst_or_tt_project(project)
        if is_mst_tt_project and task.project_id is not None and not _is_note_origin_task(task):
            return due, due

        if task.start_date is not None:
            start = _as_local_date(task.start_date)
            if start is None:
                return due, due
            if start <= due:
                return start, due
        return due, due

    def _overlaps_selected_week(task: Task) -> bool:
        start, end = _planned_range_weekly(task)
        if start is None or end is None:
            return False
        return start <= working_days[-1] and end >= working_days[0]

    week_tasks = [t for t in all_tasks if t.system_template_origin_id is None and _overlaps_selected_week(t)]
    overdue: list[TaskOut] = []

    # Organize tasks by project
    project_tasks_map: dict[uuid.UUID, list[Task]] = {}
    for task in week_tasks:
        if task.project_id is not None:
            if task.project_id not in project_tasks_map:
                project_tasks_map[task.project_id] = []
            project_tasks_map[task.project_id].append(task)

    # Create project list with their tasks
    projects_with_tasks: list[WeeklyPlannerProject] = []
    for project in projects:
        if project.id in project_tasks_map:
            project_tasks = project_tasks_map[project.id]
            projects_with_tasks.append(
                WeeklyPlannerProject(
                    project=_project_to_out(project),
                    tasks=[_task_to_out(t, assignee_map.get(t.id, [])) for t in project_tasks],
                )
            )

    # Fast tasks (standalone ad-hoc tasks only)
    fast_tasks = [
        _task_to_out(t, assignee_map.get(t.id, []))
        for t in week_tasks
        if is_fast_task_model(t)
    ]

    # Organize tasks by day for the days view
    days: list[WeeklyPlannerDay] = []
    for d in working_days:
        day_tasks = []
        for t in week_tasks:
            start, end = _planned_range_weekly(t)
            if start is None or end is None:
                continue
            if start <= d <= end:
                day_tasks.append(_task_to_out(t, assignee_map.get(t.id, [])))
        days.append(WeeklyPlannerDay(date=d, tasks=day_tasks))

    return WeeklyPlannerResponse(
        week_start=week_start_date,
        week_end=week_end,
        overdue=overdue,
        projects=projects_with_tasks,
        fast_tasks=fast_tasks,
        days=days,
    )


@router.get("/monthly", response_model=MonthlyPlannerResponse)
async def monthly_planner(
    year: int,
    month: int,
    department_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MonthlyPlannerResponse:
    if user.role == UserRole.STAFF:
        user_id = user.id
        department_id = user.department_id

    if department_id is not None:
        ensure_department_access(user, department_id)
    elif user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        department_id = user.department_id

    month_start, month_end = _month_range(year, month)
    planned_date = func.coalesce(cast(Task.due_date, Date), cast(Task.start_date, Date))
    assignee_task_ids = None

    if user_id is not None:
        assignee_task_ids = set(
            (
                await db.execute(
                    select(TaskAssignee.task_id).where(TaskAssignee.user_id == user_id)
                )
            ).scalars().all()
        )

    stmt = select(Task).where(
        planned_date.is_not(None),
        planned_date >= month_start,
        planned_date <= month_end,
    )
    if department_id is not None:
        stmt = stmt.where(Task.department_id == department_id)

    tasks = (await db.execute(stmt.order_by(Task.due_date.nullsfirst(), Task.start_date.nullsfirst(), Task.created_at))).scalars().all()
    if assignee_task_ids is not None:
        tasks = [
            task
            for task in tasks
            if task.assigned_to == user_id or task.id in assignee_task_ids
        ]
    task_out = [_task_to_out(t) for t in tasks]

    recurring = [t for t in task_out if t.system_template_origin_id is not None]

    prev_month = month - 1
    prev_year = year
    if prev_month == 0:
        prev_month = 12
        prev_year -= 1
    prev_start, prev_end = _month_range(prev_year, prev_month)

    base_filters = [planned_date.is_not(None)]
    if department_id is not None:
        base_filters.append(Task.department_id == department_id)

    month_completed_query = select(func.count(Task.id)).where(
        *base_filters,
        planned_date >= month_start,
        planned_date <= month_end,
        Task.completed_at.is_not(None),
    )
    prev_completed_query = select(func.count(Task.id)).where(
        *base_filters,
        planned_date >= prev_start,
        planned_date <= prev_end,
        Task.completed_at.is_not(None),
    )
    if user_id is not None:
        month_completed_query = month_completed_query.where(
            or_(Task.assigned_to == user_id, Task.id.in_(assignee_task_ids or {uuid.UUID(int=0)}))
        )
        prev_completed_query = prev_completed_query.where(
            or_(Task.assigned_to == user_id, Task.id.in_(assignee_task_ids or {uuid.UUID(int=0)}))
        )

    month_completed = (await db.execute(month_completed_query)).scalar_one()
    prev_completed = (await db.execute(prev_completed_query)).scalar_one()

    return MonthlyPlannerResponse(
        month_start=month_start,
        month_end=month_end,
        tasks=task_out,
        recurring=recurring,
        summary=MonthlyPlannerSummary(month_completed=month_completed, previous_month_completed=prev_completed),
    )


# Weekly Plan CRUD endpoints
@router.get("/weekly-plans", response_model=list[WeeklyPlanOut])
async def list_weekly_plans(
    department_id: uuid.UUID | None = None,
    week_start: date | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[WeeklyPlanOut]:
    """List weekly plans, optionally filtered by department and week"""
    stmt = select(WeeklyPlan)
    
    if department_id is not None:
        ensure_department_access(user, department_id)
        stmt = stmt.where(WeeklyPlan.department_id == department_id)
    elif user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        if user.department_id is not None:
            stmt = stmt.where(WeeklyPlan.department_id == user.department_id)
        else:
            return []
    
    if week_start is not None:
        week_end = week_start + timedelta(days=6)
        stmt = stmt.where(
            (WeeklyPlan.start_date <= week_end) & (WeeklyPlan.end_date >= week_start)
        )
    
    plans = (await db.execute(stmt.order_by(WeeklyPlan.start_date.desc()))).scalars().all()
    return [
        WeeklyPlanOut(
            id=p.id,
            department_id=p.department_id,
            start_date=p.start_date,
            end_date=p.end_date,
            content=p.content,
            is_finalized=p.is_finalized,
            created_by=p.created_by,
            created_at=p.created_at,
        )
        for p in plans
    ]


@router.get("/weekly-plans/{plan_id}", response_model=WeeklyPlanOut)
async def get_weekly_plan(
    plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> WeeklyPlanOut:
    """Get a specific weekly plan"""
    plan = (await db.execute(select(WeeklyPlan).where(WeeklyPlan.id == plan_id))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Weekly plan not found")
    
    if plan.department_id is not None:
        ensure_department_access(user, plan.department_id)
    elif user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    
    return WeeklyPlanOut(
        id=plan.id,
        department_id=plan.department_id,
        start_date=plan.start_date,
        end_date=plan.end_date,
        content=plan.content,
        is_finalized=plan.is_finalized,
        created_by=plan.created_by,
        created_at=plan.created_at,
    )


@router.post("/weekly-plans", response_model=WeeklyPlanOut)
async def create_weekly_plan(
    payload: WeeklyPlanCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> WeeklyPlanOut:
    """Create a new weekly plan"""
    ensure_manager_or_admin(user)
    
    if payload.department_id is not None:
        ensure_department_access(user, payload.department_id)
    
    plan = WeeklyPlan(
        department_id=payload.department_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        content=payload.content,
        is_finalized=payload.is_finalized or False,
        created_by=user.id,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    
    return WeeklyPlanOut(
        id=plan.id,
        department_id=plan.department_id,
        start_date=plan.start_date,
        end_date=plan.end_date,
        content=plan.content,
        is_finalized=plan.is_finalized,
        created_by=plan.created_by,
        created_at=plan.created_at,
    )


@router.patch("/weekly-plans/{plan_id}", response_model=WeeklyPlanOut)
async def update_weekly_plan(
    plan_id: uuid.UUID,
    payload: WeeklyPlanUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> WeeklyPlanOut:
    """Update a weekly plan"""
    ensure_manager_or_admin(user)
    
    plan = (await db.execute(select(WeeklyPlan).where(WeeklyPlan.id == plan_id))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Weekly plan not found")
    
    if plan.department_id is not None:
        ensure_department_access(user, plan.department_id)
    elif user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    
    if payload.content is not None:
        plan.content = payload.content
    if payload.is_finalized is not None:
        plan.is_finalized = payload.is_finalized
    
    await db.commit()
    await db.refresh(plan)
    
    return WeeklyPlanOut(
        id=plan.id,
        department_id=plan.department_id,
        start_date=plan.start_date,
        end_date=plan.end_date,
        content=plan.content,
        is_finalized=plan.is_finalized,
        created_by=plan.created_by,
        created_at=plan.created_at,
    )


@router.delete("/weekly-plans/{plan_id}")
async def delete_weekly_plan(
    plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> Response:
    """Delete a weekly plan"""
    ensure_manager_or_admin(user)
    
    plan = (await db.execute(select(WeeklyPlan).where(WeeklyPlan.id == plan_id))).scalar_one_or_none()
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Weekly plan not found")
    
    if plan.department_id is not None:
        ensure_department_access(user, plan.department_id)
    elif user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    
    await db.delete(plan)
    await db.commit()
    
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/weekly-table", response_model=WeeklyTableResponse)
async def weekly_table_planner(
    week_start: date | None = None,
    department_id: uuid.UUID | None = None,
    is_this_week: bool = False,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> WeeklyTableResponse:
    """Get weekly planner in table format organized by departments, users, days, and AM/PM"""
    today = datetime.now(timezone.utc).date()
    
    # Determine which week to show
    if is_this_week:
        # This week: show the plan that was made for next week but is now this week
        week_start_date = _week_start(today)
    else:
        # Next week: show the plan for the upcoming week
        week_start_date = week_start or _week_start(today + timedelta(days=7))
    
    working_days = _get_next_5_working_days(week_start_date)
    week_end = working_days[-1]
    
    # Identify departments with special weekly planner logic (use all departments, not filtered)
    all_dept_rows = (await db.execute(select(Department.id, Department.name))).all()
    dev_dept_names = {"Development"}
    dev_dept_ids = {dept_id for dept_id, name in all_dept_rows if name in dev_dept_names}
    # Product Content department: tasks should only show on due_date, not from start_date to due_date
    # Note: Database may store "Project Content Manager" but display name is "Product Content"
    pc_dept_names = {"Product Content", "Project Content Manager"}
    pc_dept_ids = {dept_id for dept_id, name in all_dept_rows if name in pc_dept_names}

    # Get departments to show
    # For STAFF users, always use their own department
    if user.role == UserRole.STAFF:
        department_id = user.department_id
    
    dept_stmt = select(Department)
    if department_id is not None:
        # MANAGERs should have the same access as ADMINS for weekly planner
        # For non-ADMIN/MANAGER users, ensure they can only access their own department
        # If they try to access a different department, silently use their own instead
        if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
            if user.department_id is not None and user.department_id != department_id:
                # User tried to access a different department - use their own instead
                department_id = user.department_id
            elif user.department_id is None:
                # User has no department - return empty response
                return WeeklyTableResponse(
                    week_start=week_start_date,
                    week_end=week_end,
                    departments=[],
                    saved_plan_id=None,
                )
        dept_stmt = dept_stmt.where(Department.id == department_id)
    elif user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        # Non-admin/manager users without department_id parameter should see their own department
        if user.department_id is not None:
            department_id = user.department_id
            dept_stmt = dept_stmt.where(Department.id == user.department_id)
        else:
            # User has no department - return empty response
            return WeeklyTableResponse(
                week_start=week_start_date,
                week_end=week_end,
                departments=[],
                saved_plan_id=None,
            )
    
    # Check if there's a saved plan for this week (after department_id is finalized)
    saved_plan_id: uuid.UUID | None = None
    if department_id is not None:
        plan_stmt = select(WeeklyPlan).where(
            WeeklyPlan.department_id == department_id,
            WeeklyPlan.start_date == week_start_date,
        )
        saved_plan = (await db.execute(plan_stmt)).scalar_one_or_none()
        if saved_plan:
            saved_plan_id = saved_plan.id
    
    departments = (await db.execute(dept_stmt.order_by(Department.name))).scalars().all()
    
    # Get all users - filter by department if a specific department is selected
    users_stmt = select(User).where(User.is_active == True)
    if department_id is not None:
        users_stmt = users_stmt.where(User.department_id == department_id)
    all_users = (await db.execute(users_stmt.order_by(User.full_name))).scalars().all()
    
    # Get projects (not templates). Completed projects are included for weekly overlap logic.
    # We don't filter by department here because we show tasks by assignee department.
    project_stmt = select(Project).where(Project.is_template == False)
    projects = (await db.execute(project_stmt.order_by(Project.created_at))).scalars().all()
    project_map = {p.id: p for p in projects}
    
    # Get active tasks (including completed ones so they can show through completion day).
    # We don't filter by department here because we show tasks by assignee department.
    task_stmt = select(Task).where(
        Task.is_active == True,
        Task.system_template_origin_id.is_(None),
    )
    if department_id is not None:
        selected_user_ids = [user.id for user in all_users]
        if selected_user_ids:
            task_stmt = task_stmt.where(
                or_(
                    Task.assigned_to.in_(selected_user_ids),
                    exists(
                        select(1).where(
                            TaskAssignee.task_id == Task.id,
                            TaskAssignee.user_id.in_(selected_user_ids),
                        )
                    ),
                    # Product Content CONTROL ownership can be encoded in
                    # internal_notes instead of the normal assignee columns.
                    Task.phase == ProjectPhaseStatus.CONTROL.value,
                )
            )
    all_tasks = (await db.execute(task_stmt.order_by(Task.due_date.nullsfirst(), Task.created_at))).scalars().all()
    
    # Filter tasks for the selected week (planning only):
    # - show tasks ONLY if they belong to the selected week
    # - show tasks ONLY on their planned days
    # - NEVER carry over tasks from previous weeks
    # - NEVER include unscheduled tasks (no due_date), except special-cases handled in _planned_range
    def _planned_range(task: Task) -> tuple[date | None, date | None]:
        if task.due_date is None:
            # Special-case: Product Content MST/TT CONTROL tasks without a due_date.
            # These tasks are driven by KO and totals; if no explicit production_date/due_date is set,
            # show them across the visible week (up to project due date) so they still appear in Weekly Planner.
            if task.project_id is None:
                return None, None
            project = project_map.get(task.project_id)
            if project is None:
                return None, None
            is_mst_tt_project = _is_mst_or_tt_project(project)
            is_control = task.phase == ProjectPhaseStatus.CONTROL.value
            is_pc_task = (task.department_id in pc_dept_ids) or (project.department_id in pc_dept_ids)
            if is_pc_task and is_mst_tt_project and is_control:
                production_date = _parse_production_date(task.internal_notes)
                if production_date is not None:
                    return production_date, production_date
                project_due = _as_local_date(project.due_date)
                if project_due is None:
                    return None, None
                start = working_days[0]
                end = min(project_due, week_end)
                if end < start:
                    return None, None
                return start, end
            return None, None
        due = _as_local_date(task.due_date)
        if due is None:
            return None, None
        
        # DEBUG: Log for LEA BLLOK TASK
        if task.title and "LEA BLLOK" in task.title.upper():
            logger = logging.getLogger(__name__)
            logger.warning(
                f"[PLANNED_RANGE DEBUG] task_id={task.id}, title={task.title}: "
                f"due_date_raw={task.due_date}, "
                f"due_date_type={type(task.due_date)}, "
                f"due_date_tzinfo={task.due_date.tzinfo if hasattr(task.due_date, 'tzinfo') else None}, "
                f"due_converted={due}, "
                f"start_date_raw={task.start_date}, "
                f"start_date_tzinfo={task.start_date.tzinfo if task.start_date and hasattr(task.start_date, 'tzinfo') else None}"
            )
        
        # MST project tasks: show only on due_date (ignore start_date).
        # GA/PX note copies keep each assignee's explicit start→due schedule.
        task_dept_id = task.department_id
        project_dept_id = None
        is_mst_project = False
        is_tt_project = False
        if task.project_id:
            # Try to get project from map
            if task.project_id in project_map:
                project = project_map[task.project_id]
                if project:
                    project_dept_id = project.department_id
                    is_mst_project = _is_mst_project(project)
                    is_tt_project = _is_tt_project(project)
            # If project not in map, try to find it (shouldn't happen, but defensive)
            else:
                # Project should already be in map, but if not, we'll check task's department
                pass
        note_origin = _is_note_origin_task(task)
        if is_mst_project and task.project_id is not None and not note_origin:
            return due, due

        # For Product Content department, regular project tasks should only show on due_date,
        # not from start_date to due_date. Note-origin copies are personal schedules and must
        # keep start→due (e.g. OH Finish AM across Mon–Fri on the PCM board).
        # Check both task's department_id and project's department_id (in case task doesn't have department_id set)
        is_pc_task = (task_dept_id in pc_dept_ids) or (project_dept_id in pc_dept_ids)
        if is_pc_task and task.project_id is not None and not note_origin:
            # Product Content project tasks: show only on due_date (ignore start_date),
            # except for TT tasks which should span start_date -> due_date.
            if not is_tt_project:
                return due, due
        
        # For all other tasks (including fast tasks), use start_date if available
        if task.start_date is not None:
            start = _as_local_date(task.start_date)
            if start is None:
                return due, due
            
            # DEBUG: Log start date conversion
            if task.title and "LEA BLLOK" in task.title.upper():
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"[PLANNED_RANGE DEBUG] task_id={task.id}: "
                    f"start_converted={start}, "
                    f"due_converted={due}, "
                    f"range=({start}, {due})"
                )
            
            # Only treat start_date as planning start if it forms a valid interval.
            if start <= due:
                return start, due
        # Default: single-day planned task on due date.
        return due, due

    def _task_active_range(task: Task) -> tuple[date | None, date | None]:
        # Check if task belongs to Development department (check both task and project)
        task_dept_id = task.department_id
        project_dept_id = None
        if task.project_id and task.project_id in project_map:
            project = project_map[task.project_id]
            if project:
                project_dept_id = project.department_id
        is_dev_task = (task_dept_id in dev_dept_ids) or (project_dept_id in dev_dept_ids)
        
        if is_dev_task and task.project_id is not None:
            # Development weekly plan: show project tasks from start_date to due_date (not created_at).
            start, end = _planned_range(task)
            if start is None or end is None:
                # Ensures dev project tasks without due_date do not appear in weekly plan.
                return None, None

            # Completed tasks should stop on their completion day, but never extend past due_date.
            if task.completed_at:
                completed_date = _as_utc_date(task.completed_at)
                if completed_date is not None and completed_date < end:
                    end = completed_date

            if end < start:
                return None, None
            return start, end
        start, end = _planned_range(task)
        if start is None or end is None:
            return None, None
        
        # DEBUG: Log for LEA BLLOK TASK
        if task.title and "LEA BLLOK" in task.title.upper():
            logger = logging.getLogger(__name__)
            is_fast = is_fast_task_model(task)
            logger.warning(
                f"[TASK_ACTIVE_RANGE DEBUG] task_id={task.id}, title={task.title}: "
                f"is_fast_task={is_fast}, "
                f"status={task.status}, "
                f"completed_at={task.completed_at}, "
                f"planned_range=({start}, {end})"
            )
        
        # For FAST TASKS, never adjust date range based on completed_at or status.
        # Always use the original start_date and due_date from _planned_range.
        if not is_fast_task_model(task) and task.completed_at:
            completed_date = _as_utc_date(task.completed_at)
            if completed_date is not None:
                # Check if this is an MST task (TT should follow normal clamping)
                is_mst_task = False
                if task.project_id and task.project_id in project_map:
                    project = project_map[task.project_id]
                    if project:
                        is_mst_task = _is_mst_project(project)
                
                if is_mst_task:
                    # For MST tasks, if completed, show on the completion day
                    # Use completed_date as both start and end to ensure it shows on that day
                    start = completed_date
                    end = completed_date
                elif completed_date < end:
                    end = completed_date
        
        # DEBUG: Log final range
        if task.title and "LEA BLLOK" in task.title.upper():
            logger = logging.getLogger(__name__)
            logger.warning(
                f"[TASK_ACTIVE_RANGE DEBUG] task_id={task.id}: "
                f"final_range=({start}, {end})"
            )
        
        if end < start:
            return None, None
        return start, end

    def _overlaps_week(task: Task) -> bool:
        start, end = _task_active_range(task)
        if start is None or end is None:
            return False
        return start <= working_days[-1] and end >= working_days[0]

    # Replanned tasks may move out of this week, but any per-day progress rows
    # are still historical work that should remain visible on the days it happened.
    progress_days_by_task: dict[uuid.UUID, set[date]] = {}
    progress_rows = []
    all_task_ids = [t.id for t in all_tasks]
    if all_task_ids:
        progress_rows = (
            await db.execute(
                select(
                    TaskDailyProgress.task_id,
                    TaskDailyProgress.day_date,
                    TaskDailyProgress.daily_status,
                    TaskDailyProgress.finish_period,
                    TaskDailyProgress.completed_value,
                    TaskDailyProgress.total_value,
                )
                .where(TaskDailyProgress.task_id.in_(all_task_ids))
                .where(TaskDailyProgress.day_date >= working_days[0])
                .where(TaskDailyProgress.day_date <= working_days[-1])
            )
        ).all()
        for progress_task_id, progress_day, _, _, _, _ in progress_rows:
            progress_days_by_task.setdefault(progress_task_id, set()).add(progress_day)

    week_tasks: list[Task] = []
    task_project_ids: set[uuid.UUID] = set()
    for t in all_tasks:
        if t.system_template_origin_id is not None:
            continue
        has_progress_this_week = bool(progress_days_by_task.get(t.id))
        if not _overlaps_week(t) and not has_progress_this_week:
            continue
        week_tasks.append(t)
        if t.project_id is not None:
            task_project_ids.add(t.project_id)

    week_task_ids = [t.id for t in week_tasks]

    marker_history_rows = []
    if all_task_ids:
        marker_history_rows = (
            await db.execute(
                select(TaskOneHMarkerHistory)
                .where(TaskOneHMarkerHistory.task_id.in_(all_task_ids))
                .where(TaskOneHMarkerHistory.marker_date <= working_days[-1])
            )
        ).scalars().all()
    all_tasks_by_id = {task.id: task for task in all_tasks}

    def _marker_identity_keys(task: Task) -> list[tuple[str, uuid.UUID]]:
        return [("task", task.id)]

    marker_history_by_identity: dict[tuple[str, uuid.UUID], list[TaskOneHMarkerHistory]] = {}
    current_tasks_by_identity: dict[tuple[str, uuid.UUID], list[Task]] = {}
    for candidate in all_tasks:
        for identity in _marker_identity_keys(candidate):
            current_tasks_by_identity.setdefault(identity, []).append(candidate)
    for row in marker_history_rows:
        source_task = all_tasks_by_id.get(row.task_id)
        if source_task is None:
            continue
        for identity in _marker_identity_keys(source_task):
            marker_history_by_identity.setdefault(identity, []).append(row)
    for rows in marker_history_by_identity.values():
        rows.sort(key=lambda item: item.marker_date)

    def _marker_for_task_day(task: Task, day_date: date) -> tuple[str | None, bool, str | None]:
        identities = _marker_identity_keys(task)
        # A history row remains effective until the next manual change. Prefer
        # this exact task without borrowing another assignee's symbol.
        saved = historical_marker_for_day(
            [row for identity in identities for row in marker_history_by_identity.get(identity, [])],
            day_date,
        )
        if saved is not None:
            return saved
        # Compatibility fallback for rows created before marker history was deployed.
        for identity in identities:
            for candidate in current_tasks_by_identity.get(identity, []):
                if (
                    candidate.one_h_marker
                    and candidate.one_h_marker_date is not None
                    and candidate.one_h_marker_date <= day_date
                ):
                    return (
                        candidate.one_h_marker,
                        candidate.one_h_marker_by_ga,
                        candidate.one_h_marker_comment,
                    )
        return None, False, None
    
    # Ensure project_map includes all projects referenced by tasks
    missing_project_ids = task_project_ids - set(project_map.keys())
    if missing_project_ids:
        missing_projects = (await db.execute(
            select(Project).where(Project.id.in_(missing_project_ids))
        )).scalars().all()
        for p in missing_projects:
            project_map[p.id] = p
    project_display_title_by_id = await build_project_display_title_map(
        db,
        list(project_map.values()),
        week_start=week_start_date,
        week_end=week_start_date + timedelta(days=6),
    )

    # Prefetch per-day status history for all tasks so we can paint each day cell independently.
    daily_status_by_task_day: dict[tuple[uuid.UUID, date], TaskStatus] = {}
    daily_finish_period_by_task_day: dict[tuple[uuid.UUID, date], str | None] = {}
    prior_status_by_task: dict[uuid.UUID, TaskStatus] = {}
    if week_task_ids:
        week_task_id_set = set(week_task_ids)
        for task_id_row, day_date_row, daily_status_row, finish_period_row, _, _ in progress_rows:
            if task_id_row not in week_task_id_set:
                continue
            try:
                daily_status_by_task_day[(task_id_row, day_date_row)] = TaskStatus(daily_status_row)
            except Exception:
                daily_status_by_task_day[(task_id_row, day_date_row)] = TaskStatus.TODO
            daily_finish_period_by_task_day[(task_id_row, day_date_row)] = finish_period_row

        pre_week_subq = (
            select(
                TaskDailyProgress.task_id,
                func.max(TaskDailyProgress.day_date).label("day_date"),
            )
            .where(TaskDailyProgress.task_id.in_(week_task_ids))
            .where(TaskDailyProgress.day_date < working_days[0])
            .where(TaskDailyProgress.daily_status != TaskStatus.DONE.value)
            .group_by(TaskDailyProgress.task_id)
            .subquery()
        )
        pre_week_rows = (
            await db.execute(
                select(
                    TaskDailyProgress.task_id,
                    TaskDailyProgress.day_date,
                    TaskDailyProgress.daily_status,
                ).join(
                    pre_week_subq,
                    (TaskDailyProgress.task_id == pre_week_subq.c.task_id)
                    & (TaskDailyProgress.day_date == pre_week_subq.c.day_date),
                )
            )
        ).all()
        for task_id_row, _, daily_status_row in pre_week_rows:
            try:
                prior_status_by_task[task_id_row] = TaskStatus(daily_status_row)
            except Exception:
                prior_status_by_task[task_id_row] = TaskStatus.TODO

    def _daily_status_for_task_day(task: Task, day_date: date) -> TaskStatus | None:
        completed_day = _as_local_date(task.completed_at)
        task_status = task.status.value if isinstance(task.status, TaskStatus) else str(task.status)
        if task_status == TaskStatus.DONE.value and completed_day == day_date:
            return TaskStatus.DONE
        for check_date in sorted([d for d in working_days if d <= day_date], reverse=True):
            key = (task.id, check_date)
            if key in daily_status_by_task_day:
                status_for_change = daily_status_by_task_day[key]
                if status_for_change == TaskStatus.DONE and check_date != day_date:
                    continue
                return status_for_change
        if task.id in prior_status_by_task:
            prior_status = prior_status_by_task[task.id]
            if prior_status != TaskStatus.DONE:
                return prior_status
        updated_day = _as_local_date(task.updated_at)
        if updated_day is not None and day_date >= updated_day:
            try:
                current_status = TaskStatus(task.status)
                if current_status == TaskStatus.DONE:
                    completed_day = _as_local_date(task.completed_at)
                    return TaskStatus.DONE if completed_day == day_date else TaskStatus.TODO
                return current_status
            except Exception:
                return TaskStatus.TODO
        return TaskStatus.TODO

    def _finish_period_for_task_day(task: Task, day_date: date) -> str | None:
        key = (task.id, day_date)
        if key in daily_finish_period_by_task_day:
            daily_finish_period = daily_finish_period_by_task_day[key]
            if daily_finish_period == "ALL":
                return None
            if daily_finish_period is not None:
                return daily_finish_period
            # Older progress rows can have NULL because status/product updates did not
            # always persist the slot. Do not let that missing history override a
            # task that is currently planned for a concrete AM/PM slot.
            if task.finish_period in ("AM", "PM"):
                return task.finish_period
        return task.finish_period

    # Prefetch per-day progress statuses for MST/TT tasks so we can paint each day cell independently.
    mst_tt_task_ids: set[uuid.UUID] = set()
    for t in week_tasks:
        if t.project_id is None:
            continue
        if t.phase not in (ProjectPhaseStatus.PRODUCT.value, ProjectPhaseStatus.CONTROL.value):
            continue
        project = project_map.get(t.project_id)
        if project is not None and _is_mst_or_tt_project(project):
            mst_tt_task_ids.add(t.id)

    daily_progress_counts_map: dict[tuple[uuid.UUID, date], tuple[int, int]] = {}
    if mst_tt_task_ids:
        for task_id_row, day_date_row, _, _, completed_value_row, total_value_row in progress_rows:
            if task_id_row not in mst_tt_task_ids:
                continue
            try:
                completed_value = int(completed_value_row or 0)
            except Exception:
                completed_value = 0
            try:
                total_value = int(total_value_row or 0)
            except Exception:
                total_value = 0
            daily_progress_counts_map[(task_id_row, day_date_row)] = (completed_value, total_value)

    def _task_product_counts(task: Task) -> tuple[int | None, int | None]:
        total_hint = task.daily_products
        if total_hint is None:
            total_hint = mst_tt_control_total_by_task_id.get(task.id)
        return _extract_total_and_completed(total_hint, task.internal_notes)

    def _progress_counts_for_day(
        task_id: uuid.UUID,
        day_date: date,
    ) -> tuple[int, int] | None:
        if task_id not in mst_tt_task_ids:
            return None
        for check_date in sorted([d for d in working_days if d <= day_date], reverse=True):
            key = (task_id, check_date)
            if key in daily_progress_counts_map:
                return daily_progress_counts_map[key]
        return None
    
    # Get task assignees for all week tasks
    task_ids = [t.id for t in week_tasks]
    assignee_map = await _assignees_for_tasks(db, task_ids)

    # Derive product totals for MST/TT CONTROL tasks.
    # These tasks often store totals in internal_notes (total_products=...) or reference an origin task
    # via origin_task_id whose daily_products holds the total.
    mst_tt_control_total_by_task_id: dict[uuid.UUID, int] = {}
    mst_tt_control_origin_by_task_id: dict[uuid.UUID, uuid.UUID] = {}
    origin_task_ids: set[uuid.UUID] = set()
    for t in week_tasks:
        if t.id not in mst_tt_task_ids:
            continue
        if t.phase != ProjectPhaseStatus.CONTROL.value:
            continue
        notes_total = _parse_total_products(t.internal_notes)
        if notes_total is not None:
            mst_tt_control_total_by_task_id[t.id] = notes_total
            continue
        origin_id = _parse_origin_task_id(t.internal_notes)
        if origin_id is not None:
            mst_tt_control_origin_by_task_id[t.id] = origin_id
            origin_task_ids.add(origin_id)

    if origin_task_ids:
        origin_rows = (
            await db.execute(
                select(Task.id, Task.daily_products, Task.internal_notes).where(Task.id.in_(list(origin_task_ids)))
            )
        ).all()
        origin_total_by_id: dict[uuid.UUID, int] = {}
        for origin_id, origin_daily_products, origin_internal_notes in origin_rows:
            if origin_daily_products is not None:
                origin_total_by_id[origin_id] = int(origin_daily_products)
                continue
            notes_total = _parse_total_products(origin_internal_notes)
            if notes_total is not None:
                origin_total_by_id[origin_id] = notes_total

        for task_id, origin_id in mst_tt_control_origin_by_task_id.items():
            if task_id in mst_tt_control_total_by_task_id:
                continue
            if origin_id in origin_total_by_id:
                mst_tt_control_total_by_task_id[task_id] = origin_total_by_id[origin_id]

    def _effective_weekly_assignee_ids(task: Task) -> set[uuid.UUID]:
        """
        Effective assignee rule for Weekly Planner (table):
        - For Product Content MST/TT tasks in CONTROL phase: assign ONLY to KO user (if set),
          otherwise hide from weekly planner (empty set).
        - For all other tasks: assign to explicit assignees (TaskAssignee) plus assigned_to fallback.
        """
        project: Project | None = None
        if task.project_id is not None:
            project = project_map.get(task.project_id)

        # Product Content detection mirrors _planned_range logic: check task.department_id and project.department_id.
        task_dept_id = task.department_id
        project_dept_id = project.department_id if project is not None else None
        is_pc_task = (task_dept_id in pc_dept_ids) or (project_dept_id in pc_dept_ids)

        if (
            is_pc_task
            and task.project_id is not None
            and task.phase == ProjectPhaseStatus.CONTROL.value
            and project is not None
            and _is_mst_or_tt_project(project)
        ):
            ko_user_id = _parse_ko_user_id(task.internal_notes)
            return {ko_user_id} if ko_user_id is not None else set()

        ids = {a.id for a in (assignee_map.get(task.id) or [])}
        if task.assigned_to is not None:
            ids.add(task.assigned_to)
        return ids

    # Weekly planned target for MST/TT should reflect the full weekly load per user+project,
    # not just the current task row.
    weekly_mst_tt_planned_by_user_project: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    for task in week_tasks:
        if task.project_id is None:
            continue
        if task.id not in mst_tt_task_ids:
            continue
        base_total_products, _ = _task_product_counts(task)
        if base_total_products is None or base_total_products <= 0:
            continue
        assignee_ids = _effective_weekly_assignee_ids(task)
        for assignee_id in assignee_ids:
            key = (assignee_id, task.project_id)
            weekly_mst_tt_planned_by_user_project[key] = (
                weekly_mst_tt_planned_by_user_project.get(key, 0) + int(base_total_products)
            )

    exclusion_map: dict[tuple[uuid.UUID, uuid.UUID, date], set[str]] = {}
    if task_ids and all_users:
        user_ids = [u.id for u in all_users]
        exclusion_rows = (
            await db.execute(
                select(
                    TaskPlannerExclusion.task_id,
                    TaskPlannerExclusion.user_id,
                    TaskPlannerExclusion.day_date,
                    TaskPlannerExclusion.time_slot,
                )
                .where(TaskPlannerExclusion.day_date >= working_days[0])
                .where(TaskPlannerExclusion.day_date <= working_days[-1])
                .where(TaskPlannerExclusion.user_id.in_(user_ids))
                .where(TaskPlannerExclusion.task_id.in_(task_ids))
            )
        ).all()
        for task_id, user_id, day_date, time_slot in exclusion_rows:
            slot_value = (time_slot or "ALL").strip().upper()
            exclusion_map.setdefault((task_id, user_id, day_date), set()).add(slot_value)

    def _is_excluded(task_id: uuid.UUID, user_id: uuid.UUID, day_date: date, slot: str) -> bool:
        slots = exclusion_map.get((task_id, user_id, day_date))
        if not slots:
            return False
        if "ALL" in slots:
            return True
        return slot in slots

    project_exclusion_map: dict[tuple[uuid.UUID, uuid.UUID, date], set[str]] = {}
    if project_map and all_users:
        project_ids = list(project_map.keys())
        user_ids = [u.id for u in all_users]
        project_exclusions = (
            await db.execute(
                select(
                    ProjectPlannerExclusion.project_id,
                    ProjectPlannerExclusion.user_id,
                    ProjectPlannerExclusion.day_date,
                    ProjectPlannerExclusion.time_slot,
                )
                .where(ProjectPlannerExclusion.day_date >= working_days[0])
                .where(ProjectPlannerExclusion.day_date <= working_days[-1])
                .where(ProjectPlannerExclusion.user_id.in_(user_ids))
                .where(ProjectPlannerExclusion.project_id.in_(project_ids))
            )
        ).all()
        for project_id, user_id, day_date, time_slot in project_exclusions:
            slot_value = (time_slot or "ALL").strip().upper()
            project_exclusion_map.setdefault((project_id, user_id, day_date), set()).add(slot_value)

    def _is_project_excluded(project_id: uuid.UUID, user_id: uuid.UUID, day_date: date, slot: str) -> bool:
        slots = project_exclusion_map.get((project_id, user_id, day_date))
        if not slots:
            return False
        if "ALL" in slots:
            return True
        return slot in slots

    # Prefetch active system task templates and resolve assignees for weekly planner display.
    system_templates = (
        await db.execute(
            select(SystemTaskTemplate)
            .where(SystemTaskTemplate.is_active.is_(True))
            .where(SystemTaskTemplate.approval_status == CommonApprovalStatus.approved)
        )
    ).scalars().all()
    system_template_ids = [t.id for t in system_templates]
    system_template_assignees: dict[uuid.UUID, set[uuid.UUID]] = {tid: set() for tid in system_template_ids}
    if system_template_ids:
        sys_tasks = (
            await db.execute(
                select(Task.id, Task.system_template_origin_id, Task.assigned_to)
                .where(Task.system_template_origin_id.in_(system_template_ids))
            )
        ).all()
        sys_task_ids = [row[0] for row in sys_tasks]
        task_assignee_rows = []
        if sys_task_ids:
            task_assignee_rows = (
                await db.execute(
                    select(TaskAssignee.task_id, TaskAssignee.user_id).where(TaskAssignee.task_id.in_(sys_task_ids))
                )
            ).all()
        assignees_by_task: dict[uuid.UUID, set[uuid.UUID]] = {}
        for task_id, user_id in task_assignee_rows:
            assignees_by_task.setdefault(task_id, set()).add(user_id)
        for task_id, template_id, assigned_to in sys_tasks:
            if template_id is None:
                continue
            explicit = assignees_by_task.get(task_id) or set()
            if explicit:
                system_template_assignees.setdefault(template_id, set()).update(explicit)
            elif assigned_to is not None:
                system_template_assignees.setdefault(template_id, set()).add(assigned_to)
        for tmpl in system_templates:
            if not system_template_assignees.get(tmpl.id) and tmpl.default_assignee_id is not None:
                system_template_assignees.setdefault(tmpl.id, set()).add(tmpl.default_assignee_id)

    # Get projects with due dates and their members
    # Projects should show for members from Monday until due date
    # If overdue and not completed, show on Monday as late project
    logger = logging.getLogger(__name__)
    projects_with_due_dates = [p for p in projects if p.due_date is not None]
    logger.debug(f"Total projects in department: {len(projects)}")
    logger.debug(f"Projects with due dates (not completed): {len(projects_with_due_dates)}")
    for p in projects_with_due_dates:
        logger.debug(f"  - {p.title} (id={p.id}, due={_as_utc_date(p.due_date)}, dept={p.department_id})")
    
    # Get project members for all projects with due dates
    project_members_map: dict[uuid.UUID, set[uuid.UUID]] = {}
    if projects_with_due_dates:
        project_ids_with_due = [p.id for p in projects_with_due_dates]
        project_members = (
            await db.execute(
                select(ProjectMember.project_id, ProjectMember.user_id)
                .where(ProjectMember.project_id.in_(project_ids_with_due))
            )
        ).all()
        for project_id, user_id in project_members:
            if project_id not in project_members_map:
                project_members_map[project_id] = set()
            project_members_map[project_id].add(user_id)
        
        # Debug logging
        logger.debug(f"Found {len(projects_with_due_dates)} projects with due dates")
        logger.debug(f"Found {len(project_members)} project member relationships")
        for p in projects_with_due_dates:
            members_count = len(project_members_map.get(p.id, set()))
            member_ids = list(project_members_map.get(p.id, set()))
            logger.debug(f"Project {p.title} (id={p.id}, due={_as_utc_date(p.due_date)}) has {members_count} members: {member_ids}")
    
    # Build table structure: Departments -> Days -> Users -> AM/PM
    def get_fast_task_type(task: Task) -> str | None:
        if task.is_bllok:
            return "BLL"
        if task.is_r1:
            return "R1"
        if task.is_1h_report:
            return "1H"
        if task.ga_note_origin_id is not None:
            return "GA"
        if task.plan_note_origin_id is not None:
            return "PX JAV"
        if task.is_personal:
            return "P:"
        return None

    departments_data: list[WeeklyTableDepartment] = []
    
    # Debug: Log task counts
    logger.debug(f"Weekly planner: Found {len(week_tasks)} tasks for week {week_start_date} to {week_end}")
    
    def _weekly_user_sort_key(u: User) -> tuple[int, int, str]:
        name = (u.full_name or u.username or "").strip().lower()
        order_value = u.weekly_planner_sort_order
        return (1 if order_value is None else 0, order_value or 0, name)

    for dept in departments:
        # Show only users from this specific department (exclude users with no department)
        dept_users = [
            u
            for u in all_users
            if u.department_id is not None
            and u.department_id == dept.id
            and not u.weekly_planner_hidden
        ]
        dept_users = sorted(dept_users, key=_weekly_user_sort_key)
        # Show tasks that belong to users in this department (regardless of task.department_id)
        dept_user_ids = {u.id for u in dept_users}
        dept_tasks = []
        for t in week_tasks:
            effective_ids = _effective_weekly_assignee_ids(t)
            if effective_ids.intersection(dept_user_ids):
                dept_tasks.append(t)
                continue

        # Load opted-in generated system-task occurrences once for this department/week.
        system_rows_by_user_day: dict[
            tuple[uuid.UUID, date], list[tuple[Task, SystemTaskTemplate]]
        ] = {}
        if dept_user_ids:
            system_task_local_day = cast(
                func.timezone(
                    func.coalesce(SystemTaskTemplate.timezone, settings.APP_TIMEZONE),
                    func.coalesce(Task.due_date, Task.origin_run_at),
                ),
                Date,
            )
            weekly_system_rows = (
                await db.execute(
                    select(Task, SystemTaskTemplate, system_task_local_day.label("local_day"))
                    .join(SystemTaskTemplate, Task.system_template_origin_id == SystemTaskTemplate.id)
                    .where(Task.assigned_to.in_(dept_user_ids))
                    .where(Task.system_template_origin_id.is_not(None))
                    .where(Task.is_active.is_(True))
                    .where(system_task_local_day >= working_days[0])
                    .where(system_task_local_day <= working_days[-1])
                    .where(SystemTaskTemplate.is_active.is_(True))
                    .where(SystemTaskTemplate.show_in_weekly_planner.is_(True))
                    .where(SystemTaskTemplate.approval_status == CommonApprovalStatus.approved)
                    .order_by(SystemTaskTemplate.title, Task.created_at.desc())
                )
            ).all()
            for system_task, template, local_day in weekly_system_rows:
                if system_task.assigned_to is None:
                    continue
                system_rows_by_user_day.setdefault(
                    (system_task.assigned_to, local_day), []
                ).append((system_task, template))
        
        # Organize tasks by day and user
        days_data: list[WeeklyTableDay] = []
        
        # Keep weekly planner read-only: do not generate system tasks during page loads.
        for day_date in working_days:
            users_day_data: list[WeeklyTableUserDay] = []
            
            for dept_user in dept_users:
                # Get tasks for this user on this day
                user_task_ids = set()
                for t in dept_tasks:
                    effective_ids = _effective_weekly_assignee_ids(t)
                    if dept_user.id in effective_ids:
                        user_task_ids.add(t.id)
                
                # Planning-only per-day filtering:
                # - single-day tasks show only on due_date
                # - multi-day tasks show on each active day within [start_date..due_date]
                user_tasks = []
                for t in dept_tasks:
                    if t.id not in user_task_ids:
                        continue
                    start, end = _task_active_range(t)
                    has_progress_for_day = day_date in progress_days_by_task.get(t.id, set())
                    if (start is None or end is None) and not has_progress_for_day:
                        continue
                    
                    # DEBUG: Log day filtering for LEA BLLOK TASK
                    if t.title and "LEA BLLOK" in t.title.upper():
                        logger = logging.getLogger(__name__)
                        appears_today = has_progress_for_day or (
                            start is not None and end is not None and start <= day_date <= end
                        )
                        logger.warning(
                            f"[DAY_FILTER DEBUG] task_id={t.id}, day={day_date}: "
                            f"range=({start}, {end}), "
                            f"appears_today={appears_today}, "
                            f"check: {start} <= {day_date} <= {end}"
                        )
                    
                    if has_progress_for_day or (start is not None and end is not None and start <= day_date <= end):
                        user_tasks.append(t)
                
                # Add projects with due dates for this user
                # Projects should show from Monday until due date
                # If overdue (due_date < Monday) and not completed, show on Monday as late project
                user_projects_with_due: set[uuid.UUID] = set()
                user_late_projects: set[uuid.UUID] = set()
                for project in projects_with_due_dates:
                    # Check if user is a member of this project
                    if project.id not in project_members_map:
                        logger.debug(f"Project {project.title} (id={project.id}) has no members in map - skipping")
                        continue
                    if dept_user.id not in project_members_map[project.id]:
                        logger.debug(f"Project {project.title} (id={project.id}) - user {dept_user.full_name} (id={dept_user.id}) is not a member. Members: {list(project_members_map[project.id])}")
                        continue
                    
                    # No department filter here: project visibility is based on membership
                    
                    project_due_date = _as_utc_date(project.due_date)
                    if project_due_date is None:
                        continue
                    project_start_date = _as_utc_date(project.created_at)
                    if project_start_date is None:
                        continue
                    project_end_date = project_due_date
                    if project.completed_at is not None:
                        completed_day = _as_utc_date(project.completed_at)
                        if completed_day is not None:
                            project_end_date = min(project_end_date, completed_day)
                    monday_of_week = working_days[0]
                    week_end = working_days[-1]
                    
                    # Debug logging for this specific project
                    logger.info(
                        f"[PROJECT CHECK] {project.title}: "
                        f"start={project_start_date}, due={project_due_date}, "
                        f"monday={monday_of_week}, week_end={week_end}, "
                        f"day={day_date}, user={dept_user.full_name}, "
                        f"dept={dept.name}"
                    )
                    
                    # Determine if project should show on this day (created -> due, stop on completion)
                    should_show = False
                    effective_start = max(project_start_date, monday_of_week)

                    if project_start_date <= week_end:
                        if day_date >= effective_start and day_date <= project_end_date and day_date <= week_end:
                            should_show = True
                            logger.debug(f"Project {project.title} showing from {effective_start} to {project_end_date} on {day_date}")
                    else:
                        logger.debug(f"Project {project.title} start_date {project_start_date} is after week_end {week_end} - not showing")
                    
                    if should_show:
                        user_projects_with_due.add(project.id)
                        logger.info(
                            f"[PROJECT ADDED] {project.title} added to user_projects_with_due for "
                            f"user={dept_user.full_name}, day={day_date}"
                        )
                        # Ensure project is in project_map
                        if project.id not in project_map:
                            project_map[project.id] = project
                    else:
                        logger.debug(
                            f"[PROJECT SKIPPED] {project.title} NOT added - "
                            f"start={project_start_date}, due={project_due_date}, "
                            f"monday={monday_of_week}, day={day_date}, week_end={week_end}"
                        )
                
                # Debug: Log user tasks found
                if user_tasks:
                    logger.debug(f"User {dept_user.full_name} on {day_date}: {len(user_tasks)} tasks")
                if user_projects_with_due:
                    logger.info(f"[USER PROJECTS] User {dept_user.full_name} on {day_date}: {len(user_projects_with_due)} projects with due dates: {list(user_projects_with_due)}")
                else:
                    logger.debug(f"User {dept_user.full_name} on {day_date}: NO projects with due dates")
                
                # Separate tasks by type: projects, system tasks, fast tasks
                # And split by AM/PM based on finish_period
                am_projects_map: dict[uuid.UUID, list[Task]] = {}
                pm_projects_map: dict[uuid.UUID, list[Task]] = {}
                am_system_tasks: list[WeeklyTableTaskEntry] = []
                pm_system_tasks: list[WeeklyTableTaskEntry] = []
                am_fast_tasks: list[WeeklyTableTaskEntry] = []
                pm_fast_tasks: list[WeeklyTableTaskEntry] = []
                
                # Fetch generated occurrences only for templates explicitly opted into the weekly planner.
                system_rows = system_rows_by_user_day.get((dept_user.id, day_date), [])

                if system_rows:
                    logger.debug(
                        f"[SYSTEM TASKS] Found {len(system_rows)} system tasks for "
                        f"{dept_user.username} on {day_date}"
                    )

                # Convert task rows to WeeklyTableTaskEntry.
                for system_task, tmpl in system_rows:
                    if system_task.status == TaskStatus.DONE:
                        task_status = TaskStatus.DONE
                        completed_at = system_task.completed_at
                    else:
                        task_status = TaskStatus.TODO
                        completed_at = None

                    finish_period_value = system_task.finish_period or tmpl.finish_period
                    finish_period_upper = None
                    if finish_period_value:
                        finish_period_str = str(finish_period_value).strip()
                        if finish_period_str:
                            finish_period_upper = finish_period_str.upper()

                    is_pm = finish_period_upper == "PM"
                    is_both = not finish_period_upper or finish_period_upper not in ("AM", "PM")
                    marker, marker_by_ga, marker_comment = _marker_for_task_day(system_task, day_date)

                    entry = WeeklyTableTaskEntry(
                        task_id=system_task.id,
                        title=tmpl.title,
                        status=task_status,
                        daily_status=None,
                        created_at=system_task.created_at,
                        completed_at=completed_at,
                        daily_products=None,
                        finish_period=finish_period_value,
                        fast_task_type=None,
                        is_bllok=False,
                        is_1h_report=False,
                        is_r1=False,
                        is_personal=False,
                        is_deadline_important=system_task.is_deadline_important,
                        one_h_marker=marker,
                        one_h_marker_by_ga=marker_by_ga,
                        one_h_marker_comment=marker_comment,
                        ga_note_origin_id=None,
                        plan_note_origin_id=None,
                    )

                    if is_both:
                        am_system_tasks.append(entry)
                        pm_system_tasks.append(entry)
                    elif is_pm:
                        pm_system_tasks.append(entry)
                    else:
                        am_system_tasks.append(entry)

                for task in user_tasks:
                    # Handle finish_period: None or empty means both AM and PM
                    # Check if finish_period is None, empty string, or not a valid AM/PM value
                    finish_period_value = _finish_period_for_task_day(task, day_date)
                    
                    # Normalize the finish_period value
                    finish_period_upper = None
                    if finish_period_value:
                        finish_period_str = str(finish_period_value).strip()
                        if finish_period_str:
                            finish_period_upper = finish_period_str.upper()
                    
                    # Determine which time slot(s) this task should appear in
                    is_pm = finish_period_upper == "PM"
                    is_am = finish_period_upper == "AM"
                    # If finish_period is None, empty, or not "AM"/"PM", it should appear in both slots
                    is_both = not finish_period_upper or finish_period_upper not in ("AM", "PM")
                    
                    # System tasks (have system_template_origin_id)
                    if task.system_template_origin_id is not None:
                        continue
                    # Fast tasks (standalone ad-hoc tasks only)
                    elif is_fast_task_model(task):
                        daily_status_value = _daily_status_for_task_day(task, day_date)
                        marker, marker_by_ga, marker_comment = _marker_for_task_day(task, day_date)
                        entry = WeeklyTableTaskEntry(
                            task_id=task.id,
                            title=task.title,
                            status=TaskStatus(task.status) if task.status else TaskStatus.TODO,
                            daily_status=daily_status_value,
                            created_at=task.created_at,
                            completed_at=task.completed_at,
                            daily_products=task.daily_products,
                            finish_period=finish_period_value,
                            fast_task_type=get_fast_task_type(task),
                            is_bllok=task.is_bllok,
                            is_1h_report=task.is_1h_report,
                            is_r1=task.is_r1,
                            is_personal=task.is_personal,
                            is_deadline_important=task.is_deadline_important,
                            one_h_marker=marker,
                            one_h_marker_by_ga=marker_by_ga,
                            one_h_marker_comment=marker_comment,
                            ga_note_origin_id=task.ga_note_origin_id,
                            plan_note_origin_id=task.plan_note_origin_id,
                        )
                        if is_both:
                            # Add to both AM and PM
                            if not _is_excluded(task.id, dept_user.id, day_date, "AM"):
                                am_fast_tasks.append(entry)
                            if not _is_excluded(task.id, dept_user.id, day_date, "PM"):
                                pm_fast_tasks.append(entry)
                        elif is_pm:
                            if not _is_excluded(task.id, dept_user.id, day_date, "PM"):
                                pm_fast_tasks.append(entry)
                        else:
                            # Default to AM if not PM and not both
                            if not _is_excluded(task.id, dept_user.id, day_date, "AM"):
                                am_fast_tasks.append(entry)
                    # Project tasks (have project_id)
                    elif task.project_id is not None:
                        # GA/PX-JAV assignee copies are personal work items. Do not hide them
                        # behind project-slot removals on another department's board.
                        note_origin = task.ga_note_origin_id is not None or task.plan_note_origin_id is not None
                        if is_both:
                            # Add to both AM and PM
                            if (note_origin or not _is_project_excluded(task.project_id, dept_user.id, day_date, "AM")) and not _is_excluded(task.id, dept_user.id, day_date, "AM"):
                                if task.project_id not in am_projects_map:
                                    am_projects_map[task.project_id] = []
                                am_projects_map[task.project_id].append(task)
                            if (note_origin or not _is_project_excluded(task.project_id, dept_user.id, day_date, "PM")) and not _is_excluded(task.id, dept_user.id, day_date, "PM"):
                                if task.project_id not in pm_projects_map:
                                    pm_projects_map[task.project_id] = []
                                pm_projects_map[task.project_id].append(task)
                        elif is_pm:
                            if (note_origin or not _is_project_excluded(task.project_id, dept_user.id, day_date, "PM")) and not _is_excluded(task.id, dept_user.id, day_date, "PM"):
                                if task.project_id not in pm_projects_map:
                                    pm_projects_map[task.project_id] = []
                                pm_projects_map[task.project_id].append(task)
                        else:
                            # Default to AM if not PM and not both
                            if (note_origin or not _is_project_excluded(task.project_id, dept_user.id, day_date, "AM")) and not _is_excluded(task.id, dept_user.id, day_date, "AM"):
                                if task.project_id not in am_projects_map:
                                    am_projects_map[task.project_id] = []
                                am_projects_map[task.project_id].append(task)
                
                # Add projects with due dates that don't have tasks yet
                # These projects should show for members even without tasks
                # If project already has tasks in map, keep those tasks
                allow_empty_project_entries = _should_add_empty_project_entry_for_department(
                    dept.id,
                    pc_dept_ids,
                )
                for project_id in user_projects_with_due:
                    # Only add if not already in maps (from tasks above)
                    # If project already has tasks, we keep those tasks
                    # The project will show with its tasks on days with tasks,
                    # and without tasks (but still visible) on other days until due date
                    if not allow_empty_project_entries:
                        continue
                    if project_id not in am_projects_map and project_id not in pm_projects_map:
                        # Default to AM if no tasks exist
                        if not _is_project_excluded(project_id, dept_user.id, day_date, "AM"):
                            am_projects_map[project_id] = []
                
                # Convert project maps to lists with task details
                # Include all projects, even if not in project_map (they'll show as "Unknown Project")
                am_projects: list[WeeklyTableProjectEntry] = []
                for project_id, tasks_list in am_projects_map.items():
                    task_entries: list[WeeklyTableProjectTaskEntry] = []
                    for t in tasks_list:
                        marker, marker_by_ga, marker_comment = _marker_for_task_day(t, day_date)
                        base_total_products, base_completed_products = _task_product_counts(t)
                        progress_counts = _progress_counts_for_day(t.id, day_date)
                        daily_status_value = _override_daily_status_from_progress(
                            _daily_status_for_task_day(t, day_date),
                            progress_counts,
                        )
                        status_for_day = _status_for_day(
                            status=TaskStatus(t.status) if t.status else TaskStatus.TODO,
                            daily_status=daily_status_value,
                            completed_at=t.completed_at,
                            day_date=day_date,
                        )
                        total_products, completed_products, weekly_planned_products, day_total_products, day_done_products = _build_weekly_task_product_metrics(
                            base_total=base_total_products,
                            base_completed=base_completed_products,
                            progress_counts=progress_counts,
                            is_mst_tt_task=t.id in mst_tt_task_ids,
                            status_for_day=status_for_day,
                        )
                        if t.id in mst_tt_task_ids and t.project_id is not None:
                            weekly_planned_products = weekly_mst_tt_planned_by_user_project.get(
                                (dept_user.id, t.project_id),
                                weekly_planned_products if weekly_planned_products is not None else 0,
                            )
                        task_entries.append(
                            WeeklyTableProjectTaskEntry(
                                task_id=t.id,
                                task_title=t.title,
                                phase=t.phase,
                                status=TaskStatus(t.status) if t.status else TaskStatus.TODO,
                                daily_status=daily_status_value,
                                created_at=t.created_at,
                                completed_at=t.completed_at,
                                daily_products=total_products,
                                total_products=total_products,
                                completed_products=completed_products,
                                weekly_planned_products=weekly_planned_products,
                                day_total_products=day_total_products,
                                day_done_products=day_done_products,
                                finish_period=_finish_period_for_task_day(t, day_date),
                                is_bllok=t.is_bllok,
                                is_1h_report=t.is_1h_report,
                                is_r1=t.is_r1,
                                is_personal=t.is_personal,
                                is_deadline_important=t.is_deadline_important,
                                one_h_marker=marker,
                                one_h_marker_by_ga=marker_by_ga,
                                one_h_marker_comment=marker_comment,
                                ga_note_origin_id=t.ga_note_origin_id,
                                plan_note_origin_id=t.plan_note_origin_id,
                            )
                        )
                    am_projects.append(
                        WeeklyTableProjectEntry(
                            project_id=project_id,
                            project_title=project_display_title_by_id.get(project_id)
                            or (project_map[project_id].title if project_id in project_map else "Unknown Project"),
                            project_total_products=project_map[project_id].total_products if project_id in project_map else None,
                            project_current_phase=project_map[project_id].current_phase if project_id in project_map else None,
                            project_type=project_map[project_id].project_type if project_id in project_map else None,
                            task_count=len(tasks_list),
                            tasks=task_entries,
                            is_late=False,
                        )
                    )
                pm_projects: list[WeeklyTableProjectEntry] = []
                for project_id, tasks_list in pm_projects_map.items():
                    task_entries: list[WeeklyTableProjectTaskEntry] = []
                    for t in tasks_list:
                        marker, marker_by_ga, marker_comment = _marker_for_task_day(t, day_date)
                        base_total_products, base_completed_products = _task_product_counts(t)
                        progress_counts = _progress_counts_for_day(t.id, day_date)
                        daily_status_value = _override_daily_status_from_progress(
                            _daily_status_for_task_day(t, day_date),
                            progress_counts,
                        )
                        status_for_day = _status_for_day(
                            status=TaskStatus(t.status) if t.status else TaskStatus.TODO,
                            daily_status=daily_status_value,
                            completed_at=t.completed_at,
                            day_date=day_date,
                        )
                        total_products, completed_products, weekly_planned_products, day_total_products, day_done_products = _build_weekly_task_product_metrics(
                            base_total=base_total_products,
                            base_completed=base_completed_products,
                            progress_counts=progress_counts,
                            is_mst_tt_task=t.id in mst_tt_task_ids,
                            status_for_day=status_for_day,
                        )
                        if t.id in mst_tt_task_ids and t.project_id is not None:
                            weekly_planned_products = weekly_mst_tt_planned_by_user_project.get(
                                (dept_user.id, t.project_id),
                                weekly_planned_products if weekly_planned_products is not None else 0,
                            )
                        task_entries.append(
                            WeeklyTableProjectTaskEntry(
                                task_id=t.id,
                                task_title=t.title,
                                phase=t.phase,
                                status=TaskStatus(t.status) if t.status else TaskStatus.TODO,
                                daily_status=daily_status_value,
                                created_at=t.created_at,
                                completed_at=t.completed_at,
                                daily_products=total_products,
                                total_products=total_products,
                                completed_products=completed_products,
                                weekly_planned_products=weekly_planned_products,
                                day_total_products=day_total_products,
                                day_done_products=day_done_products,
                                finish_period=_finish_period_for_task_day(t, day_date),
                                is_bllok=t.is_bllok,
                                is_1h_report=t.is_1h_report,
                                is_r1=t.is_r1,
                                is_personal=t.is_personal,
                                is_deadline_important=t.is_deadline_important,
                                one_h_marker=marker,
                                one_h_marker_by_ga=marker_by_ga,
                                one_h_marker_comment=marker_comment,
                                ga_note_origin_id=t.ga_note_origin_id,
                                plan_note_origin_id=t.plan_note_origin_id,
                            )
                        )
                    pm_projects.append(
                        WeeklyTableProjectEntry(
                            project_id=project_id,
                            project_title=project_display_title_by_id.get(project_id)
                            or (project_map[project_id].title if project_id in project_map else "Unknown Project"),
                            project_total_products=project_map[project_id].total_products if project_id in project_map else None,
                            project_current_phase=project_map[project_id].current_phase if project_id in project_map else None,
                            project_type=project_map[project_id].project_type if project_id in project_map else None,
                            task_count=len(tasks_list),
                            tasks=task_entries,
                            is_late=False,
                        )
                    )
                
                users_day_data.append(
                    WeeklyTableUserDay(
                        user_id=dept_user.id,
                        user_name=dept_user.full_name or dept_user.username or "",
                        am_projects=am_projects,
                        pm_projects=pm_projects,
                        am_system_tasks=am_system_tasks,
                        pm_system_tasks=pm_system_tasks,
                        am_fast_tasks=am_fast_tasks,
                        pm_fast_tasks=pm_fast_tasks,
                    )
                )
            
            days_data.append(
                WeeklyTableDay(
                    date=day_date,
                    users=users_day_data,
                )
            )
        
        departments_data.append(
            WeeklyTableDepartment(
                department_id=dept.id,
                department_name=dept.name,
                days=days_data,
            )
        )
    
    return WeeklyTableResponse(
        week_start=week_start_date,
        week_end=week_end,
        departments=departments_data,
        saved_plan_id=saved_plan_id,
    )


@router.post("/weekly-table/save-day", response_model=WeeklyPlannerSaveDayResponse)
async def save_weekly_table_day(
    payload: WeeklyPlannerSaveDayRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> WeeklyPlannerSaveDayResponse:
    ensure_department_access(user, payload.department_id)

    day_date = payload.day_date or _today_app_date()
    week_start_date = _week_start(payload.week_start or day_date)
    working_days = _get_next_5_working_days(week_start_date)
    if day_date not in working_days:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Day is not in the selected work week")

    weekly_table = await weekly_table_planner(
        week_start=week_start_date,
        department_id=payload.department_id,
        is_this_week=False,
        db=db,
        user=user,
    )
    department = next(
        (dept for dept in weekly_table.departments if dept.department_id == payload.department_id),
        None,
    )
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department planner data not found")

    target_days = [working_day for working_day in working_days if working_day <= day_date]
    day_payloads = [day for day in department.days if day.date in set(target_days)]
    if not day_payloads:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Day planner data not found")

    def normalize_entry_status(value: TaskStatus | str | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, TaskStatus):
            return value.value
        return _normalize_task_status(str(value))

    def add_task(
        rows_by_task: dict[uuid.UUID, dict],
        *,
        task_id: uuid.UUID | None,
        status_value: TaskStatus | str | None,
        daily_status_value: TaskStatus | str | None,
        slot: str,
        completed_value: int | None = None,
        total_value: int | None = None,
    ) -> None:
        if task_id is None:
            return
        row = rows_by_task.setdefault(
            task_id,
            {
                "status": None,
                "daily_status": None,
                "slots": set(),
                "completed_value": 0,
                "total_value": 0,
            },
        )
        row["status"] = _pick_stronger_status(row.get("status"), normalize_entry_status(status_value))
        row["daily_status"] = _pick_stronger_status(row.get("daily_status"), normalize_entry_status(daily_status_value))
        row["slots"].add(slot)
        row["completed_value"] = max(int(row.get("completed_value") or 0), int(completed_value or 0))
        row["total_value"] = max(int(row.get("total_value") or 0), int(total_value or 0))

    def collect_day_rows(day_payload: WeeklyTableDay) -> dict[uuid.UUID, dict]:
        rows_by_task: dict[uuid.UUID, dict] = {}
        for user_day in day_payload.users:
            if user_day.user_id != user.id:
                continue
            for slot, project_bucket in (("AM", user_day.am_projects), ("PM", user_day.pm_projects)):
                for project in project_bucket:
                    for task in project.tasks:
                        add_task(
                            rows_by_task,
                            task_id=task.task_id,
                            status_value=task.status,
                            daily_status_value=task.daily_status,
                            slot=slot,
                            completed_value=task.day_done_products if task.day_done_products is not None else task.completed_products,
                            total_value=task.day_total_products if task.day_total_products is not None else task.total_products,
                        )
            for slot, task_buckets in (
                ("AM", (user_day.am_system_tasks, user_day.am_fast_tasks)),
                ("PM", (user_day.pm_system_tasks, user_day.pm_fast_tasks)),
            ):
                for task_bucket in task_buckets:
                    for task in task_bucket:
                        add_task(
                            rows_by_task,
                            task_id=task.task_id,
                            status_value=task.status,
                            daily_status_value=task.daily_status,
                            slot=slot,
                            completed_value=task.daily_products,
                            total_value=task.daily_products,
                        )
        return rows_by_task

    saved_count = 0
    for day_payload in day_payloads:
        rows_by_task = collect_day_rows(day_payload)
        if not rows_by_task:
            continue

        existing_rows = (
            await db.execute(
                select(TaskDailyProgress)
                .where(TaskDailyProgress.task_id.in_(list(rows_by_task.keys())))
                .where(TaskDailyProgress.day_date == day_payload.date)
            )
        ).scalars().all()
        existing_by_task = {row.task_id: row for row in existing_rows}

        for task_id, row in rows_by_task.items():
            daily_status = row.get("daily_status") or row.get("status") or TaskStatus.TODO
            daily_status_value = normalize_entry_status(daily_status) or TaskStatus.TODO.value
            slots = {str(slot).strip().upper() for slot in row.get("slots", set())}
            if slots == {"AM"}:
                finish_period = "AM"
            elif slots == {"PM"}:
                finish_period = "PM"
            else:
                finish_period = "ALL"

            existing = existing_by_task.get(task_id)
            if existing is not None:
                continue

            db.add(
                TaskDailyProgress(
                    task_id=task_id,
                    day_date=day_payload.date,
                    completed_value=max(0, int(row.get("completed_value") or 0)),
                    total_value=max(0, int(row.get("total_value") or 0)),
                    completed_delta=0,
                    daily_status=daily_status_value,
                    finish_period=finish_period,
                )
            )
            saved_count += 1

    await db.commit()
    return WeeklyPlannerSaveDayResponse(
        department_id=payload.department_id,
        day_date=day_date,
        saved_count=saved_count,
    )


@router.patch("/weekly-table/user-order")
async def update_weekly_table_user_order(
    payload: WeeklyPlannerUserOrderUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> Response:
    ensure_manager_or_admin(user)
    ensure_department_access(user, payload.department_id)

    dept = (
        await db.execute(select(Department).where(Department.id == payload.department_id))
    ).scalar_one_or_none()
    if dept is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    users = (
        await db.execute(
            select(User)
            .where(User.department_id == payload.department_id)
            .where(User.is_active == True)
        )
    ).scalars().all()
    dept_user_map = {u.id: u for u in users}
    dept_user_ids = set(dept_user_map.keys())
    if not dept_user_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active users found for department")

    ordered_unique_ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for user_id in payload.ordered_user_ids or []:
        if user_id in seen:
            continue
        seen.add(user_id)
        ordered_unique_ids.append(user_id)

    invalid_ids = [user_id for user_id in ordered_unique_ids if user_id not in dept_user_ids]
    if invalid_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ordered users must belong to the selected department",
        )

    # Reset all user orders in this department
    for dept_user in users:
        dept_user.weekly_planner_sort_order = None

    # Apply new order
    for index, user_id in enumerate(ordered_unique_ids, start=1):
        dept_user_map[user_id].weekly_planner_sort_order = index

    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/weekly-table/user-visibility")
async def update_weekly_table_user_visibility(
    payload: WeeklyPlannerUserVisibilityUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> Response:
    ensure_manager_or_admin(user)
    ensure_department_access(user, payload.department_id)

    target = (
        await db.execute(
            select(User)
            .where(User.id == payload.user_id)
            .where(User.department_id == payload.department_id)
            .where(User.is_active.is_(True))
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active department user not found")

    target.weekly_planner_hidden = payload.hidden
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _build_weekly_snapshot_payload(
    *,
    db: AsyncSession,
    user: User,
    department_id: uuid.UUID,
    week_start_date: date,
    is_this_week: bool = False,
) -> tuple[date, date, dict]:
    weekly_table = await weekly_table_planner(
        week_start=week_start_date,
        department_id=department_id,
        is_this_week=is_this_week,
        db=db,
        user=user,
    )
    weekly_table_json = jsonable_encoder(weekly_table)
    department_rows = weekly_table_json.get("departments") or []
    department_payload = department_rows[0] if department_rows else None
    task_ids_for_snapshot = _task_ids_from_department_payload(department_payload)
    task_priority_map = await _load_task_priority_map(db, task_ids_for_snapshot)
    task_items = _flatten_weekly_department_tasks(
        department_payload,
        task_priority_map=task_priority_map,
    )

    legend_entries = await get_weekly_planner_legend(
        department_id=department_id,
        week_start=week_start_date,
        db=db,
        user=user,
    )
    legend_payload = [entry.model_dump(mode="json") for entry in legend_entries]

    week_start = weekly_table.week_start
    week_end = weekly_table.week_end
    pv_fest_blocks = await _load_pv_fest_blocks_for_snapshot(
        db=db,
        department_id=department_id,
        week_start=week_start,
        week_end=week_end,
    )

    payload = jsonable_encoder(
        {
            "week_start": week_start,
            "week_end": week_end,
            "department_filter": {
                "department_id": department_id,
                "label": (department_payload or {}).get("department_name") if department_payload else "All Departments",
            },
            "department": department_payload,
            "task_items": task_items,
            "legend_entries": legend_payload,
            "pv_fest_blocks": pv_fest_blocks,
            "snapshot_created_by": user.id,
            "snapshot_created_at": datetime.now(timezone.utc),
        }
    )
    return week_start, week_end, payload


async def _create_and_store_weekly_snapshot(
    *,
    db: AsyncSession,
    user: User,
    department_id: uuid.UUID,
    week_start_date: date,
    snapshot_type: WeeklySnapshotType,
    is_this_week: bool = False,
) -> WeeklySnapshotSaveResponse:
    week_start, week_end, snapshot_payload = await _build_weekly_snapshot_payload(
        db=db,
        user=user,
        department_id=department_id,
        week_start_date=week_start_date,
        is_this_week=is_this_week,
    )
    snapshot = WeeklyPlannerSnapshot(
        department_id=department_id,
        week_start_date=week_start,
        week_end_date=week_end,
        snapshot_type=snapshot_type.value,
        payload=snapshot_payload,
        created_by=user.id,
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)

    versions = (
        await db.execute(
            select(WeeklyPlannerSnapshot)
            .where(
                WeeklyPlannerSnapshot.department_id == department_id,
                WeeklyPlannerSnapshot.week_start_date == week_start,
                WeeklyPlannerSnapshot.snapshot_type == snapshot_type.value,
            )
            .order_by(WeeklyPlannerSnapshot.created_at.asc())
        )
    ).scalars().all()
    official_snapshot = versions[0]

    return WeeklySnapshotSaveResponse(
        snapshot=_snapshot_version_out(snapshot, is_official=snapshot.id == official_snapshot.id),
        version_count=len(versions),
        official_snapshot_id=official_snapshot.id,
    )


@router.post("/weekly-snapshots/create", response_model=WeeklySnapshotSaveResponse)
async def create_weekly_snapshot_for_week(
    payload: WeeklySnapshotCreateRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> WeeklySnapshotSaveResponse:
    ensure_manager_or_admin(user)
    ensure_department_access(user, payload.department_id)

    dept = (await db.execute(select(Department).where(Department.id == payload.department_id))).scalar_one_or_none()
    if dept is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    target_week_start = _week_start(payload.week_start)
    return await _create_and_store_weekly_snapshot(
        db=db,
        user=user,
        department_id=payload.department_id,
        week_start_date=target_week_start,
        snapshot_type=payload.snapshot_type,
        is_this_week=False,
    )


@router.post("/weekly-snapshots/save", response_model=WeeklySnapshotSaveResponse)
async def save_weekly_snapshot(
    payload: WeeklySnapshotSaveRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> WeeklySnapshotSaveResponse:
    ensure_manager_or_admin(user)
    ensure_department_access(user, payload.department_id)

    dept = (await db.execute(select(Department).where(Department.id == payload.department_id))).scalar_one_or_none()
    if dept is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    today = _today_app_date()
    target_week_start = _snapshot_week_start_for_mode(payload.mode, today)
    snapshot_type = _snapshot_type_for_mode(payload.mode)
    is_this_week = payload.mode == WeeklySnapshotSaveMode.THIS_WEEK_FINAL
    return await _create_and_store_weekly_snapshot(
        db=db,
        user=user,
        department_id=payload.department_id,
        week_start_date=target_week_start,
        snapshot_type=snapshot_type,
        is_this_week=is_this_week,
    )


@router.get("/weekly-snapshots/overview", response_model=WeeklySnapshotOverviewOut)
async def weekly_snapshot_overview(
    department_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> WeeklySnapshotOverviewOut:
    ensure_department_access(user, department_id)

    today = _today_app_date()
    this_week_start = _week_start(today)
    week_starts = [
        this_week_start - timedelta(days=14),
        this_week_start - timedelta(days=7),
        this_week_start,
        this_week_start + timedelta(days=7),
    ]
    labels = {
        week_starts[0]: "last_last_week",
        week_starts[1]: "last_week",
        week_starts[2]: "this_week",
        week_starts[3]: "next_week",
    }

    snapshots = (
        await db.execute(
            select(WeeklyPlannerSnapshot)
            .where(
                WeeklyPlannerSnapshot.department_id == department_id,
                WeeklyPlannerSnapshot.week_start_date.in_(week_starts),
            )
            .order_by(WeeklyPlannerSnapshot.created_at.asc())
        )
    ).scalars().all()

    grouped: dict[date, dict[str, list[WeeklyPlannerSnapshot]]] = {
        week_start: {
            WeeklySnapshotType.PLANNED.value: [],
            WeeklySnapshotType.FINAL.value: [],
        }
        for week_start in week_starts
    }
    for snapshot in snapshots:
        if snapshot.week_start_date not in grouped:
            continue
        grouped[snapshot.week_start_date].setdefault(snapshot.snapshot_type, []).append(snapshot)

    weeks: list[WeeklySnapshotOverviewWeekOut] = []
    for week_start in week_starts:
        planned_versions = grouped[week_start][WeeklySnapshotType.PLANNED.value]
        final_versions = grouped[week_start][WeeklySnapshotType.FINAL.value]
        week_end = _get_next_5_working_days(week_start)[-1]
        weeks.append(
            WeeklySnapshotOverviewWeekOut(
                week_start=week_start,
                week_end=week_end,
                label=labels[week_start],
                planned_official_id=planned_versions[0].id if planned_versions else None,
                planned_versions=len(planned_versions),
                final_official_id=final_versions[0].id if final_versions else None,
                final_versions=len(final_versions),
            )
        )

    return WeeklySnapshotOverviewOut(weeks=weeks)


@router.get("/weekly-snapshots/latest", response_model=WeeklySnapshotLatestOut)
async def get_latest_weekly_snapshot_for_week(
    department_id: uuid.UUID,
    week_start: date,
    snapshot_type: WeeklySnapshotType = WeeklySnapshotType.PLANNED,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> WeeklySnapshotLatestOut:
    ensure_department_access(user, department_id)
    normalized_week_start = _week_start(week_start)
    week_end = _get_next_5_working_days(normalized_week_start)[-1]

    latest_snapshot = (
        await db.execute(
            select(WeeklyPlannerSnapshot)
            .where(
                WeeklyPlannerSnapshot.department_id == department_id,
                WeeklyPlannerSnapshot.week_start_date == normalized_week_start,
                WeeklyPlannerSnapshot.snapshot_type == snapshot_type.value,
            )
            .order_by(WeeklyPlannerSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest_snapshot is None:
        return WeeklySnapshotLatestOut(
            week_start=normalized_week_start,
            week_end=week_end,
            department_id=department_id,
            snapshot_type=snapshot_type,
            snapshot=None,
            message=NO_PLAN_SNAPSHOT_MESSAGE if snapshot_type == WeeklySnapshotType.PLANNED else None,
        )

    return WeeklySnapshotLatestOut(
        week_start=normalized_week_start,
        week_end=latest_snapshot.week_end_date or week_end,
        department_id=department_id,
        snapshot_type=snapshot_type,
        snapshot=_snapshot_out(latest_snapshot, is_official=True),
    )


@router.get("/weekly-snapshots/plan-vs-actual", response_model=WeeklySnapshotPlanVsActualOut)
async def weekly_plan_vs_actual_compare(
    department_id: uuid.UUID,
    week_start: date,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> WeeklySnapshotPlanVsActualOut:
    ensure_department_access(user, department_id)

    normalized_week_start = _week_start(week_start)
    week_end = _get_next_5_working_days(normalized_week_start)[-1]

    department = (await db.execute(select(Department).where(Department.id == department_id))).scalar_one_or_none()
    department_name = department.name if department is not None else None

    planned_official_snapshot = (
        await db.execute(
            select(WeeklyPlannerSnapshot)
            .where(
                WeeklyPlannerSnapshot.department_id == department_id,
                WeeklyPlannerSnapshot.week_start_date == normalized_week_start,
                WeeklyPlannerSnapshot.snapshot_type == WeeklySnapshotType.PLANNED.value,
            )
            .order_by(WeeklyPlannerSnapshot.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if planned_official_snapshot is None:
        return WeeklySnapshotPlanVsActualOut(
            week_start=normalized_week_start,
            week_end=week_end,
            department_id=department_id,
            department_name=department_name,
            message=NO_PLAN_SNAPSHOT_MESSAGE,
            summary=WeeklySnapshotCompareSummaryOut(),
        )

    snapshot_tasks_by_key = _tasks_by_key_from_snapshot_payload(planned_official_snapshot.payload or {})

    current_weekly_table = await weekly_table_planner(
        week_start=normalized_week_start,
        department_id=department_id,
        is_this_week=False,
        db=db,
        user=user,
    )
    current_table_json = jsonable_encoder(current_weekly_table)
    current_departments = current_table_json.get("departments") or []
    current_department_payload = current_departments[0] if current_departments else None
    current_task_ids = _task_ids_from_department_payload(current_department_payload)
    current_task_priorities = await _load_task_priority_map(db, current_task_ids)
    current_task_items = _flatten_weekly_department_tasks(
        current_department_payload,
        task_priority_map=current_task_priorities,
    )
    current_tasks_by_key = {
        task["match_key"]: task
        for task in current_task_items
    }

    today_local = _today_app_date()
    as_of_date = min(today_local, week_end)

    buckets = _classify_weekly_plan_performance(
        planned_tasks=snapshot_tasks_by_key,
        actual_tasks=current_tasks_by_key,
        week_end=week_end,
        as_of_date=as_of_date,
    )

    completed = [_to_compare_task_out(task) for task in buckets["completed"]]
    in_progress = [_to_compare_task_out(task) for task in buckets["in_progress"]]
    pending = [_to_compare_task_out(task) for task in buckets["pending"]]
    late = [_to_compare_task_out(task) for task in buckets["late"]]
    additional = [_to_compare_task_out(task) for task in buckets["additional"]]
    removed_or_canceled = [_to_compare_task_out(task) for task in buckets["removed_or_canceled"]]

    not_completed = [*in_progress, *pending, *late]
    added_during_week = list(additional)

    completed.sort(key=lambda task: task.title.lower())
    in_progress.sort(key=lambda task: task.title.lower())
    pending.sort(key=lambda task: task.title.lower())
    late.sort(key=lambda task: task.title.lower())
    additional.sort(key=lambda task: task.title.lower())
    not_completed.sort(key=lambda task: task.title.lower())
    removed_or_canceled.sort(key=lambda task: task.title.lower())

    summary = WeeklySnapshotCompareSummaryOut(
        total_planned=len(snapshot_tasks_by_key),
        completed=len(completed),
        in_progress=len(in_progress),
        pending=len(pending),
        late=len(late),
        additional=len(additional),
        not_completed=len(not_completed),
        added_during_week=len(added_during_week),
        removed_or_canceled=len(removed_or_canceled),
    )

    by_assignee = _group_compare_tasks_by_assignee(
        completed=completed,
        in_progress=in_progress,
        pending=pending,
        late=late,
        additional=additional,
        removed_or_canceled=removed_or_canceled,
    )

    return WeeklySnapshotPlanVsActualOut(
        week_start=normalized_week_start,
        week_end=week_end,
        department_id=department_id,
        department_name=department_name,
        snapshot_id=planned_official_snapshot.id,
        snapshot_created_at=planned_official_snapshot.created_at,
        snapshot_created_by=planned_official_snapshot.created_by,
        summary=summary,
        completed=completed,
        in_progress=in_progress,
        pending=pending,
        late=late,
        additional=additional,
        not_completed=not_completed,
        added_during_week=added_during_week,
        removed_or_canceled=removed_or_canceled,
        by_assignee=by_assignee,
    )


@router.get("/weekly-snapshots/plan-vs-final", response_model=WeeklySnapshotPlanVsActualOut)
async def weekly_plan_vs_final_compare(
    department_id: uuid.UUID,
    week_start: date,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> WeeklySnapshotPlanVsActualOut:
    ensure_department_access(user, department_id)

    normalized_week_start = _week_start(week_start)
    week_end = _get_next_5_working_days(normalized_week_start)[-1]

    department = (await db.execute(select(Department).where(Department.id == department_id))).scalar_one_or_none()
    department_name = department.name if department is not None else None

    planned_official_snapshot = (
        await db.execute(
            select(WeeklyPlannerSnapshot)
            .where(
                WeeklyPlannerSnapshot.department_id == department_id,
                WeeklyPlannerSnapshot.week_start_date == normalized_week_start,
                WeeklyPlannerSnapshot.snapshot_type == WeeklySnapshotType.PLANNED.value,
            )
            .order_by(WeeklyPlannerSnapshot.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if planned_official_snapshot is None:
        return WeeklySnapshotPlanVsActualOut(
            week_start=normalized_week_start,
            week_end=week_end,
            department_id=department_id,
            department_name=department_name,
            message=NO_PLAN_SNAPSHOT_MESSAGE,
            summary=WeeklySnapshotCompareSummaryOut(),
        )

    latest_final_snapshot = (
        await db.execute(
            select(WeeklyPlannerSnapshot)
            .where(
                WeeklyPlannerSnapshot.department_id == department_id,
                WeeklyPlannerSnapshot.week_start_date == normalized_week_start,
                WeeklyPlannerSnapshot.snapshot_type == WeeklySnapshotType.FINAL.value,
            )
            .order_by(WeeklyPlannerSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest_final_snapshot is None:
        planned_tasks_by_key = _tasks_by_key_from_snapshot_payload(planned_official_snapshot.payload or {})
        return WeeklySnapshotPlanVsActualOut(
            week_start=normalized_week_start,
            week_end=week_end,
            department_id=department_id,
            department_name=department_name,
            snapshot_id=planned_official_snapshot.id,
            snapshot_created_at=planned_official_snapshot.created_at,
            snapshot_created_by=planned_official_snapshot.created_by,
            message="No final snapshot found for this week. Save This Week (Final) first.",
            summary=WeeklySnapshotCompareSummaryOut(total_planned=len(planned_tasks_by_key)),
        )

    planned_tasks_by_key = _tasks_by_key_from_snapshot_payload(planned_official_snapshot.payload or {})
    final_tasks_by_key = _tasks_by_key_from_snapshot_payload(latest_final_snapshot.payload or {})

    as_of_date = week_end + timedelta(days=1)
    buckets = _classify_weekly_plan_performance(
        planned_tasks=planned_tasks_by_key,
        actual_tasks=final_tasks_by_key,
        week_end=week_end,
        as_of_date=as_of_date,
    )

    completed = [_to_compare_task_out(task) for task in buckets["completed"]]
    in_progress = [_to_compare_task_out(task) for task in buckets["in_progress"]]
    pending = [_to_compare_task_out(task) for task in buckets["pending"]]
    late = [_to_compare_task_out(task) for task in buckets["late"]]
    additional = [_to_compare_task_out(task) for task in buckets["additional"]]
    removed_or_canceled = [_to_compare_task_out(task) for task in buckets["removed_or_canceled"]]

    not_completed = [*in_progress, *pending, *late]
    added_during_week = list(additional)

    completed.sort(key=lambda task: task.title.lower())
    in_progress.sort(key=lambda task: task.title.lower())
    pending.sort(key=lambda task: task.title.lower())
    late.sort(key=lambda task: task.title.lower())
    additional.sort(key=lambda task: task.title.lower())
    removed_or_canceled.sort(key=lambda task: task.title.lower())

    summary = WeeklySnapshotCompareSummaryOut(
        total_planned=len(planned_tasks_by_key),
        completed=len(completed),
        in_progress=len(in_progress),
        pending=len(pending),
        late=len(late),
        additional=len(additional),
        not_completed=len(not_completed),
        added_during_week=len(added_during_week),
        removed_or_canceled=len(removed_or_canceled),
    )

    by_assignee = _group_compare_tasks_by_assignee(
        completed=completed,
        in_progress=in_progress,
        pending=pending,
        late=late,
        additional=additional,
        removed_or_canceled=removed_or_canceled,
    )

    return WeeklySnapshotPlanVsActualOut(
        week_start=normalized_week_start,
        week_end=week_end,
        department_id=department_id,
        department_name=department_name,
        snapshot_id=planned_official_snapshot.id,
        snapshot_created_at=planned_official_snapshot.created_at,
        snapshot_created_by=planned_official_snapshot.created_by,
        final_snapshot_id=latest_final_snapshot.id,
        final_snapshot_created_at=latest_final_snapshot.created_at,
        final_snapshot_created_by=latest_final_snapshot.created_by,
        summary=summary,
        completed=completed,
        in_progress=in_progress,
        pending=pending,
        late=late,
        additional=additional,
        not_completed=not_completed,
        added_during_week=added_during_week,
        removed_or_canceled=removed_or_canceled,
        by_assignee=by_assignee,
    )


@router.get("/weekly-snapshots/compare-by-id", response_model=WeeklySnapshotPlanVsActualOut)
@router.get("/weekly-snapshots/compare/by-id", response_model=WeeklySnapshotPlanVsActualOut)
async def weekly_snapshot_compare_by_id(
    baseline_snapshot_id: uuid.UUID,
    compare_snapshot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> WeeklySnapshotPlanVsActualOut:
    if baseline_snapshot_id == compare_snapshot_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choose two different snapshots.")

    baseline_snapshot = (
        await db.execute(select(WeeklyPlannerSnapshot).where(WeeklyPlannerSnapshot.id == baseline_snapshot_id))
    ).scalar_one_or_none()
    if baseline_snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Baseline snapshot not found")

    compare_snapshot = (
        await db.execute(select(WeeklyPlannerSnapshot).where(WeeklyPlannerSnapshot.id == compare_snapshot_id))
    ).scalar_one_or_none()
    if compare_snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comparison snapshot not found")

    ensure_department_access(user, baseline_snapshot.department_id)
    ensure_department_access(user, compare_snapshot.department_id)

    if baseline_snapshot.department_id != compare_snapshot.department_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Snapshots must belong to the same department.")
    if baseline_snapshot.week_start_date != compare_snapshot.week_start_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Snapshots must be from the same week.")

    department = (
        await db.execute(select(Department).where(Department.id == baseline_snapshot.department_id))
    ).scalar_one_or_none()
    department_name = department.name if department is not None else None

    week_start = baseline_snapshot.week_start_date
    week_end = baseline_snapshot.week_end_date or _get_next_5_working_days(week_start)[-1]

    planned_tasks_by_key = _tasks_by_key_from_snapshot_payload(baseline_snapshot.payload or {})
    actual_tasks_by_key = _tasks_by_key_from_snapshot_payload(compare_snapshot.payload or {})

    as_of_date = week_end + timedelta(days=1)
    buckets = _classify_weekly_plan_performance(
        planned_tasks=planned_tasks_by_key,
        actual_tasks=actual_tasks_by_key,
        week_end=week_end,
        as_of_date=as_of_date,
    )

    completed = [_to_compare_task_out(task) for task in buckets["completed"]]
    in_progress = [_to_compare_task_out(task) for task in buckets["in_progress"]]
    pending = [_to_compare_task_out(task) for task in buckets["pending"]]
    late = [_to_compare_task_out(task) for task in buckets["late"]]
    additional = [_to_compare_task_out(task) for task in buckets["additional"]]
    removed_or_canceled = [_to_compare_task_out(task) for task in buckets["removed_or_canceled"]]

    not_completed = [*in_progress, *pending, *late]
    added_during_week = list(additional)

    completed.sort(key=lambda task: task.title.lower())
    in_progress.sort(key=lambda task: task.title.lower())
    pending.sort(key=lambda task: task.title.lower())
    late.sort(key=lambda task: task.title.lower())
    additional.sort(key=lambda task: task.title.lower())
    removed_or_canceled.sort(key=lambda task: task.title.lower())

    summary = WeeklySnapshotCompareSummaryOut(
        total_planned=len(planned_tasks_by_key),
        completed=len(completed),
        in_progress=len(in_progress),
        pending=len(pending),
        late=len(late),
        additional=len(additional),
        not_completed=len(not_completed),
        added_during_week=len(added_during_week),
        removed_or_canceled=len(removed_or_canceled),
    )

    by_assignee = _group_compare_tasks_by_assignee(
        completed=completed,
        in_progress=in_progress,
        pending=pending,
        late=late,
        additional=additional,
        removed_or_canceled=removed_or_canceled,
    )

    return WeeklySnapshotPlanVsActualOut(
        week_start=week_start,
        week_end=week_end,
        department_id=baseline_snapshot.department_id,
        department_name=department_name,
        snapshot_id=baseline_snapshot.id,
        snapshot_created_at=baseline_snapshot.created_at,
        snapshot_created_by=baseline_snapshot.created_by,
        final_snapshot_id=compare_snapshot.id,
        final_snapshot_created_at=compare_snapshot.created_at,
        final_snapshot_created_by=compare_snapshot.created_by,
        summary=summary,
        completed=completed,
        in_progress=in_progress,
        pending=pending,
        late=late,
        additional=additional,
        not_completed=not_completed,
        added_during_week=added_during_week,
        removed_or_canceled=removed_or_canceled,
        by_assignee=by_assignee,
    )


@router.get("/weekly-snapshots/compare", response_model=WeeklySnapshotCompareOut)
async def weekly_snapshot_compare(
    department_id: uuid.UUID,
    week_start: date,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> WeeklySnapshotCompareOut:
    ensure_department_access(user, department_id)

    normalized_week_start = _week_start(week_start)
    week_end = _get_next_5_working_days(normalized_week_start)[-1]
    rows = (
        await db.execute(
            select(WeeklyPlannerSnapshot)
            .where(
                WeeklyPlannerSnapshot.department_id == department_id,
                WeeklyPlannerSnapshot.week_start_date == normalized_week_start,
            )
            .order_by(WeeklyPlannerSnapshot.created_at.asc())
        )
    ).scalars().all()

    planned_rows = [row for row in rows if row.snapshot_type == WeeklySnapshotType.PLANNED.value]
    final_rows = [row for row in rows if row.snapshot_type == WeeklySnapshotType.FINAL.value]

    planned_versions = [
        _snapshot_version_out(row, is_official=index == 0) for index, row in enumerate(planned_rows)
    ]
    final_versions = [
        _snapshot_version_out(row, is_official=index == 0) for index, row in enumerate(final_rows)
    ]

    return WeeklySnapshotCompareOut(
        week_start=normalized_week_start,
        week_end=week_end,
        planned_official=_snapshot_out(planned_rows[0], is_official=True) if planned_rows else None,
        final_official=_snapshot_out(final_rows[0], is_official=True) if final_rows else None,
        planned_versions=planned_versions,
        final_versions=final_versions,
    )


@router.get("/weekly-snapshots/{snapshot_id}", response_model=WeeklySnapshotOut)
async def get_weekly_snapshot(
    snapshot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> WeeklySnapshotOut:
    snapshot = (
        await db.execute(select(WeeklyPlannerSnapshot).where(WeeklyPlannerSnapshot.id == snapshot_id))
    ).scalar_one_or_none()
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")

    ensure_department_access(user, snapshot.department_id)
    official = (
        await db.execute(
            select(WeeklyPlannerSnapshot.id)
            .where(
                WeeklyPlannerSnapshot.department_id == snapshot.department_id,
                WeeklyPlannerSnapshot.week_start_date == snapshot.week_start_date,
                WeeklyPlannerSnapshot.snapshot_type == snapshot.snapshot_type,
            )
            .order_by(WeeklyPlannerSnapshot.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _snapshot_out(snapshot, is_official=official == snapshot.id)


# Development department legend questions configuration
# Color mapping:
# - PINK = TO DO / New task
# - GREEN = KRYER / Done
# - RED = NUK ESHTE PUNUAR / Not worked
# - YELLOW = PROCES / In process
# - LIGHT GREY = PV
DEVELOPMENT_LEGEND_QUESTIONS = [
    {
        "key": "to_do",
        "label": "TO DO",
        "question_text": "A KEMI PROJEKTE TE TJERA TE P(A)PLANIFIKUARA?",
        "color": "#FF0000",  # Red
    },
    {
        "key": "kryer",
        "label": "KRYER",
        "question_text": "A PRITEN PROJEKTE TE TJERA GJATE JAVES QE DUHET ME I PLNF KETE JAVE, APO BARTEN JAVEN TJETER?",
        "color": "#C4FDC4",  # Green
    },
    {
        "key": "nuk_eshte_punuar",
        "label": "NUK ESHTE PUNUAR",
        "question_text": "BLOK?",
        "color": "#FFC4ED",  # Pink
    },
    {
        "key": "proces",
        "label": "PROCES",
        "question_text": "A PRITEN PROJEKTE TE TJERA GJATE JAVES QE DUHET ME I PLNF KETE JAVE, APO BARTEN JAVEN TJETER?",
        "color": "#FFD700",  # Yellow
    },
    {
        "key": "pv",
        "label": "PV",
        "question_text": "",
        "color": "#D3D3D3",  # Light Grey
    },
]

GRAPHIC_DESIGN_LEGEND_QUESTIONS = [
    {
        "key": "kryer",
        "label": "KRYER",
        "question_text": "A KEMI PROJEKTE TE TJERA TE PAPLANIFIKUARA?",
        "color": "#C4FDC4",  # Green
    },
    {
        "key": "nuk_eshte_punuar",
        "label": "NUK ESHTE PUNUAR",
        "question_text": "A KA KLIENT QE NUK KEMI PROJEKTE TE HAPURA?",
        "color": "#FFC4ED",  # Pink
    },
    {
        "key": "proces",
        "label": "PROCES",
        "question_text": "A PRITEN PROJEKTE TE TJERA GJATE JAVES QE DUHET ME I PLANIFIKU KETE JAVE, APO BARTEN JAVEN TJETER?",
        "color": "#FFD700",  # Yellow
    },
    {
        "key": "pv",
        "label": "PV",
        "question_text": "NENGARKESE (NUK ESHTE I PLANIFIKUAR PERSONI PER KOMPLET JAVEN)?",
        "color": "#D3D3D3",  # Light Grey
    },
    {
        "key": "mbingarkese",
        "label": "MBINGARKESE?",
        "question_text": "MBINGARKESE?",
        "color": "#D3D3D3",  # Light Grey
    },
    {
        "key": "komplet",
        "label": "KOMPLET (100% PROJEKTE)",
        "question_text": "KOMPLET (100% PROJEKTE)",
        "color": "#D3D3D3",  # Light Grey
    },
]

def normalize_department_key(name: str | None) -> str:
    return "".join((name or "").strip().lower().split())


LEGEND_QUESTION_SETS = {
    "development": DEVELOPMENT_LEGEND_QUESTIONS,
    "zhvillim": DEVELOPMENT_LEGEND_QUESTIONS,
    "graphicdesign": GRAPHIC_DESIGN_LEGEND_QUESTIONS,
    "grafikdizajn": GRAPHIC_DESIGN_LEGEND_QUESTIONS,
    "dizajngrafik": GRAPHIC_DESIGN_LEGEND_QUESTIONS,
    "productcontent": GRAPHIC_DESIGN_LEGEND_QUESTIONS,
    "produktcontent": GRAPHIC_DESIGN_LEGEND_QUESTIONS,
    "projectcontentmanager": GRAPHIC_DESIGN_LEGEND_QUESTIONS,
    "pcm": GRAPHIC_DESIGN_LEGEND_QUESTIONS,
}


@router.get("/weekly-planner/legend", response_model=list[WeeklyPlannerLegendEntryOut])
async def get_weekly_planner_legend(
    department_id: uuid.UUID,
    week_start: date,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[WeeklyPlannerLegendEntryOut]:
    """Get legend entries for a specific department and week. Auto-creates default entries for supported departments."""
    # Check department access
    ensure_department_access(user, department_id)
    
    # Get department to check if it's Development
    dept = (await db.execute(select(Department).where(Department.id == department_id))).scalar_one_or_none()
    if not dept:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
    
    legend_questions = LEGEND_QUESTION_SETS.get(normalize_department_key(dept.name))
    if not legend_questions and getattr(dept, "code", None):
        legend_questions = LEGEND_QUESTION_SETS.get(normalize_department_key(dept.code))
    if not legend_questions:
        return []
    
    # Get existing entries
    stmt = select(WeeklyPlannerLegendEntry).where(
        WeeklyPlannerLegendEntry.department_id == department_id,
        WeeklyPlannerLegendEntry.week_start_date == week_start,
    )
    existing_entries = (await db.execute(stmt.order_by(WeeklyPlannerLegendEntry.key))).scalars().all()
    
    existing_by_key = {entry.key: entry for entry in existing_entries}
    new_entries = []

    for question in legend_questions:
        if question["key"] in existing_by_key:
            continue
        entry = WeeklyPlannerLegendEntry(
            department_id=department_id,
            week_start_date=week_start,
            key=question["key"],
            label=question["label"],
            question_text=question["question_text"],
            answer_text=None,
            created_by=user.id,
        )
        db.add(entry)
        new_entries.append(entry)

    if new_entries:
        await db.commit()
        for entry in new_entries:
            await db.refresh(entry)
        existing_entries.extend(new_entries)

    if not existing_entries:
        return []

    return [WeeklyPlannerLegendEntryOut.model_validate(entry) for entry in existing_entries]


@router.patch("/weekly-planner/legend/{entry_id}", response_model=WeeklyPlannerLegendEntryOut)
async def update_weekly_planner_legend_entry(
    entry_id: uuid.UUID,
    payload: WeeklyPlannerLegendEntryUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> WeeklyPlannerLegendEntryOut:
    """Update the answer_text for a legend entry."""
    entry = (await db.execute(
        select(WeeklyPlannerLegendEntry).where(WeeklyPlannerLegendEntry.id == entry_id)
    )).scalar_one_or_none()
    
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Legend entry not found")
    
    # Check department access
    ensure_department_access(user, entry.department_id)
    
    # Update answer_text - handle both None and empty string as null
    # This allows clearing the field by sending empty string or null
    if payload.answer_text is not None:
        # Trim whitespace and set to None if empty
        answer_text = payload.answer_text.strip() if payload.answer_text else None
        entry.answer_text = answer_text if answer_text else None
    else:
        # Explicitly set to None if payload.answer_text is None
        entry.answer_text = None
    
    await db.commit()
    await db.refresh(entry)
    
    return WeeklyPlannerLegendEntryOut.model_validate(entry)

