from __future__ import annotations

import re
import re
import uuid
from typing import Annotated
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

from fastapi import APIRouter, Depends, HTTPException, Response, status, Query
from sqlalchemy import delete, exists, func, insert, literal, null, or_, select, union_all, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, load_only

from app.api.access import ensure_department_access, ensure_manager_or_admin, ensure_task_editor
from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models.enums import NotificationType, ProjectPhaseStatus, TaskPriority, TaskSkillCategory, TaskStatus, UserRole
from app.models.department import Department
from app.models.ga_note import GaNote
from app.models.plan_note import PlanNote
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_planner_exclusion import ProjectPlannerExclusion
from app.models.question_library import QuestionDefinition, QuestionStatusEvent, QuestionUserStatus
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_user_comment import TaskUserComment
from app.models.task_alignment_user import TaskAlignmentUser
from app.models.task_planner_exclusion import TaskPlannerExclusion
from app.models.task_daily_progress import TaskDailyProgress
from app.models.task_one_h_report_slot import TaskOneHReportSlot
from app.services.one_h_slots import effective_slot_date
from app.models.system_task_template_alignment_user import SystemTaskTemplateAlignmentUser
from app.models.system_task_template_assignee_slot import SystemTaskTemplateAssigneeSlot
from app.models.user import User
from app.schemas.task import (
    GaNoteTaskSummaryOut,
    TaskAssigneeOut,
    TaskCreate,
    TaskOut,
    TaskRemoveFromDayRequest,
    TaskUpdate,
)
from app.schemas.plan_note import PxJavPlanningBrief
from pydantic import BaseModel, Field
from app.services.audit import add_audit_log
from app.services.notifications import add_notification, notification_task_preview, publish_notification
from app.services.ko_task_assignee_sync import ensure_ko_user_is_task_assignee
from app.services.task_daily_progress import (
    sync_task_daily_finish_period,
    upsert_explicit_task_daily_status,
    upsert_task_daily_progress,
)
from app.services.task_date_window import task_date_window_filter
from app.services.task_marker import active_one_h_marker, current_effective_marker_date, marker_is_by_ga, normalize_marker_comment, sync_task_marker
from app.services.marker_comments import record_initial_marker_comments
from app.services.task_classification import is_fast_task as is_fast_task_model, is_fast_task_fields
from app.services.daily_report_logic import business_days_between, parse_ko_user_id
from app.services.daily_realization_baseline import ensure_daily_baselines_for_departments
from app.services.daily_realization_events import record_task_semantic_events, task_semantic_state
from app.services.task_postponement import check_task_postponement_explanation, save_postponement_daily_explanation
from app.services.project_classification import (
    is_mst_or_tt_project as _is_mst_or_tt_project,
    is_mst_project,
)
from app.services.task_strike_events import (
    record_description_strike_events,
    record_title_strike_events,
)
from app.services.task_title_rules import (
    normalize_email_task_title as _normalize_email_task_title,
    title_has_eight_am_indicator,
)


router = APIRouter()

def _validate_eight_am_one_h_slot(
    title: str, slot: str | None, *, is_system_task: bool = False
) -> None:
    if title_has_eight_am_indicator(
        title, is_system_task=is_system_task
    ) and slot not in (None, "10:00"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="08:00 tasks are 1H tasks and must use the 10:00 slot.",
        )

MENTION_RE = re.compile(r"@([A-Za-z0-9_\\-\\.]{3,64})")
TOTAL_PRODUCTS_RE = re.compile(r"total_products[:=]\s*(\d+)", re.IGNORECASE)
COMPLETED_PRODUCTS_RE = re.compile(r"completed_products[:=]\s*(\d+)", re.IGNORECASE)


def _realization_today() -> date:
    return datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date()

async def _ensure_system_task_instance_integrity(db: AsyncSession, task: Task) -> None:
    """
    DB has a CHECK constraint requiring:
      system_template_origin_id IS NULL OR (origin_run_at IS NOT NULL AND system_task_slot_id IS NOT NULL)

    Some legacy/system tasks can end up with a NULL `system_task_slot_id` (e.g. older data or slot drift),
    which makes *any* update (like setting status DONE) fail.
    """
    if task.system_template_origin_id is None:
        return

    # Ensure origin_run_at exists for system tasks.
    if task.origin_run_at is None and task.start_date is not None:
        task.origin_run_at = task.start_date

    if task.system_task_slot_id is not None:
        return

    # Best-effort repair: find an existing slot for this template + assigned_to.
    if task.assigned_to is not None:
        slot_id = (
            await db.execute(
                select(SystemTaskTemplateAssigneeSlot.id)
                .where(SystemTaskTemplateAssigneeSlot.template_id == task.system_template_origin_id)
                .where(SystemTaskTemplateAssigneeSlot.primary_user_id == task.assigned_to)
                .order_by(SystemTaskTemplateAssigneeSlot.is_active.desc(), SystemTaskTemplateAssigneeSlot.created_at.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if slot_id is not None:
            task.system_task_slot_id = slot_id
            return

    # Last resort: create an inactive slot to keep existing task rows valid.
    # This avoids breaking historical tasks while preventing scheduler from using it.
    if task.assigned_to is not None and task.origin_run_at is not None:
        new_slot = SystemTaskTemplateAssigneeSlot(
            id=uuid.uuid4(),
            template_id=task.system_template_origin_id,
            primary_user_id=task.assigned_to,
            next_run_at=task.origin_run_at,
            is_active=False,
        )
        db.add(new_slot)
        task.system_task_slot_id = new_slot.id


def _as_local_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo:
            tz = None
            if ZoneInfo is not None:
                try:
                    tz = ZoneInfo("Europe/Pristina")
                except Exception:
                    try:
                        tz = ZoneInfo("Europe/Belgrade")
                    except Exception:
                        tz = None
            if tz is None:
                try:
                    import pytz  # type: ignore[import-not-found]

                    try:
                        tz = pytz.timezone("Europe/Pristina")
                    except Exception:
                        tz = pytz.timezone("Europe/Belgrade")
                except ImportError:
                    tz = timezone(timedelta(hours=1))
            return value.astimezone(tz).date()
        return value.date()
    return value


def _as_utc_datetime(value: datetime | None) -> datetime | None:
    """Make user-supplied task datetimes safe to compare with stored values.

    Browser date inputs submit a bare ``YYYY-MM-DD`` value, which Pydantic
    parses as a timezone-naive datetime.  PostgreSQL task timestamps are
    timezone-aware.  Comparing the two while editing only start or due date
    raises ``TypeError`` and previously caused Finance date updates to fail.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_development_department(department: Department | None) -> bool:
    if department is None:
        return False
    name = (department.name or "").strip().upper()
    code = (department.code or "").strip().upper()
    return name == "DEVELOPMENT" or code == "DEV"


def _normalize_project_task_phase(
    phase: str | ProjectPhaseStatus,
    *,
    is_development_project: bool,
) -> str | ProjectPhaseStatus:
    phase_value = phase.value if isinstance(phase, ProjectPhaseStatus) else phase
    if is_development_project and phase_value == ProjectPhaseStatus.MEETINGS.value:
        return ProjectPhaseStatus.PLANNING
    return phase


def _signed_business_days_between(start_day: date, end_day: date) -> int:
    if end_day >= start_day:
        return business_days_between(start_day, end_day)
    return -business_days_between(end_day, start_day)


def _task_late_days(task: Task, *, today: date) -> int | None:
    due_day = _as_local_date(task.due_date)
    if due_day is None:
        return None

    if task.status == TaskStatus.DONE.value:
        completed_day = _as_local_date(task.completed_at)
        if completed_day and completed_day > due_day:
            return business_days_between(due_day, completed_day)
        return None

    if today > due_day:
        late_days = business_days_between(due_day, today)
        return late_days or None
    return None


def _task_moved_days(task: Task) -> int | None:
    original_due_day = _as_local_date(task.original_due_date)
    due_day = _as_local_date(task.due_date)
    if original_due_day is None or due_day is None or original_due_day == due_day:
        return None
    return _signed_business_days_between(original_due_day, due_day)


def _task_planned_date(task: Task) -> datetime | None:
    if task.completed_at is not None and _enum_value(task.status) == TaskStatus.DONE.value:
        return task.due_date
    return task.original_due_date or task.due_date


def _sync_due_date_to_done_day(task: Task) -> None:
    if task.completed_at is None or _enum_value(task.status) != TaskStatus.DONE.value:
        return
    next_due_date = _due_date_on_done_day(task.due_date, task.completed_at)
    if (
        task.due_date is not None
        and next_due_date != task.due_date
        and task.original_due_date is None
    ):
        task.original_due_date = task.due_date
    task.due_date = next_due_date
    start_date = getattr(task, "start_date", None)
    if start_date is not None and _as_local_date(start_date) > _as_local_date(task.completed_at):
        task.start_date = task.completed_at


def _due_date_on_done_day(due_date: datetime | None, completed_at: datetime) -> datetime:
    completed_day = _as_local_date(completed_at)
    due_day = _as_local_date(due_date)
    if completed_day is not None and due_day != completed_day:
        return completed_at
    return due_date or completed_at


def _extract_total_and_completed(daily_products: int | None, internal_notes: str | None) -> tuple[int | None, int]:
    total: int | None = daily_products
    completed = 0

    if internal_notes:
        if total is None:
            m_total = TOTAL_PRODUCTS_RE.search(internal_notes)
            if m_total:
                try:
                    total = int(m_total.group(1))
                except Exception:
                    total = None

        m_completed = COMPLETED_PRODUCTS_RE.search(internal_notes)
        if m_completed:
            try:
                completed = int(m_completed.group(1))
            except Exception:
                completed = 0

    if completed < 0:
        completed = 0
    if total is not None and total < 0:
        total = 0
    return total, completed


def _compute_status_from_completed(total: int | None, completed: int) -> TaskStatus | None:
    if total is None:
        return None
    if total <= 0:
        return TaskStatus.TODO
    if completed <= 0:
        return TaskStatus.TODO
    if completed < total:
        return TaskStatus.IN_PROGRESS
    return TaskStatus.DONE


def _product_count_status_for_output(
    stored_status: str | TaskStatus,
    total: int | None,
    completed: int,
) -> TaskStatus | None:
    """Keep an explicitly completed product task completed in API responses."""
    if _enum_value(stored_status) == TaskStatus.DONE.value:
        return TaskStatus.DONE
    return _compute_status_from_completed(total, completed)


def _should_auto_status_from_product_counts(
    project: Project | None,
    phase: str | ProjectPhaseStatus | None,
) -> bool:
    if project is None:
        return False
    phase_value = phase.value if isinstance(phase, ProjectPhaseStatus) else phase
    return phase_value in (
        ProjectPhaseStatus.PRODUCT.value,
        ProjectPhaseStatus.CONTROL.value,
    )


_GA_NOTE_VALID_STATUSES = {
    TaskStatus.TODO.value,
    TaskStatus.IN_PROGRESS.value,
    TaskStatus.WAITING_CLIENT.value,
    TaskStatus.WAITING_CONFIRMATION.value,
    TaskStatus.DONE.value,
}

_GA_NOTE_SHARED_TASK_FIELDS = {
    "title",
    "project_id",
    "dependency_task_id",
    "department_id",
    "phase",
    "fast_task_order",
    "alignment_user_ids",
}


def _is_ga_confirmation_user(user: User) -> bool:
    """GA is an account identity, not one of the three system roles."""
    full_name = (user.full_name or "").strip().lower()
    username = (user.username or "").strip().lower()
    return full_name == "gane arifaj" or username in {"gane.arifaj", "gane_arifaj", "gane"}


def _normalize_ga_note_task_status(value: str | TaskStatus | None) -> TaskStatus:
    if not value:
        return TaskStatus.TODO
    raw = value.value if isinstance(value, TaskStatus) else str(value).strip()
    if raw in _GA_NOTE_VALID_STATUSES:
        return TaskStatus(raw)
    return TaskStatus.TODO


def _supports_waiting_confirmation(
    task: Task,
    *,
    is_bllok: bool | None = None,
    is_1h_report: bool | None = None,
    is_r1: bool | None = None,
    is_personal: bool | None = None,
) -> bool:
    """Waiting Confirmation is for special and note-origin tasks, never system tasks."""
    if bool(getattr(task, "system_template_origin_id", None) or getattr(task, "system_task_slot_id", None)):
        return False
    if getattr(task, "ga_note_origin_id", None) is not None or getattr(task, "plan_note_origin_id", None) is not None:
        return True
    return any(
        (
            getattr(task, "is_bllok", False) if is_bllok is None else is_bllok,
            getattr(task, "is_1h_report", False) if is_1h_report is None else is_1h_report,
            getattr(task, "is_r1", False) if is_r1 is None else is_r1,
            getattr(task, "is_personal", False) if is_personal is None else is_personal,
        )
    )


def _payload_supports_waiting_confirmation(payload: TaskCreate) -> bool:
    return bool(
        payload.ga_note_origin_id
        or payload.plan_note_origin_id
        or payload.is_bllok
        or payload.is_1h_report
        or payload.is_r1
        or payload.is_personal
    )


async def _validate_waiting_confirmation_assignee(
    db: AsyncSession,
    confirmation_assignee_id: uuid.UUID | None,
) -> None:
    if confirmation_assignee_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation assignee is required when status is WAITING_CONFIRMATION",
        )
    confirmation_user = (
        await db.execute(select(User).where(User.id == confirmation_assignee_id))
    ).scalar_one_or_none()
    if confirmation_user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Confirmation assignee not found")
    if confirmation_user.role not in (UserRole.ADMIN, UserRole.MANAGER) and not _is_ga_confirmation_user(confirmation_user):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation assignee must be a manager, admin, or GA",
        )


def _user_to_assignee(user: User) -> TaskAssigneeOut:
    return TaskAssigneeOut(
        id=user.id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
    )


def _payload_has_field(payload: BaseModel, field_name: str) -> bool:
    if hasattr(payload, "model_fields_set"):
        return field_name in payload.model_fields_set  # type: ignore[attr-defined]
    if hasattr(payload, "__fields_set__"):
        return field_name in payload.__fields_set__  # type: ignore[attr-defined]
    return False


def _confirmation_assignee_was_provided(payload: TaskUpdate) -> bool:
    """Recognize a submitted confirmer without relying only on model metadata."""
    return (
        payload.confirmation_assignee_id is not None
        or _payload_has_field(payload, "confirmation_assignee_id")
    )


def _iter_workdays(start_day: date, end_day: date) -> list[date]:
    if end_day < start_day:
        return []
    days: list[date] = []
    current = start_day
    while current <= end_day:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _planner_replan_exclusion_days(
    *,
    old_start: date | None,
    old_end: date | None,
    new_start: date | None,
    progress_days: set[date],
    today: date,
) -> list[date]:
    if old_start is None or old_end is None or new_start is None:
        return []
    if old_end < old_start or new_start <= old_start:
        return []

    latest_worked_day = max(
        (day for day in progress_days if old_start <= day <= old_end and day < new_start),
        default=None,
    )
    gap_start = (latest_worked_day + timedelta(days=1)) if latest_worked_day is not None else today
    gap_start = max(gap_start, old_start)
    gap_end = min(old_end, new_start - timedelta(days=1))
    return _iter_workdays(gap_start, gap_end)


async def _assignees_for_tasks(
    db: AsyncSession, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[TaskAssigneeOut]]:
    if not task_ids:
        return {}

    # Legacy tasks can have assigned_to without a TaskAssignee row. Resolve
    # explicit and fallback assignees in one query, while preserving the rule
    # that explicit TaskAssignee rows take precedence.
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


async def _task_list_metadata(
    db: AsyncSession,
    task_ids: list[uuid.UUID],
    user_id: uuid.UUID,
) -> tuple[
    dict[uuid.UUID, list[TaskAssigneeOut]],
    dict[uuid.UUID, str | None],
    dict[uuid.UUID, list[uuid.UUID]],
]:
    """Load assignees, the viewer's comments and alignments in one round trip."""

    if not task_ids:
        return {}, {}, {}

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

    assignee_rows = (
        select(
            effective_assignees.c.task_id,
            literal("assignee").label("kind"),
            User.id.label("user_id"),
            User.email.label("email"),
            User.username.label("username"),
            User.full_name.label("full_name"),
            null().label("comment"),
        )
        .join(User, effective_assignees.c.user_id == User.id)
    )
    comment_rows = select(
        TaskUserComment.task_id,
        literal("comment").label("kind"),
        null().label("user_id"),
        null().label("email"),
        null().label("username"),
        null().label("full_name"),
        TaskUserComment.comment.label("comment"),
    ).where(
        TaskUserComment.task_id.in_(task_ids),
        TaskUserComment.user_id == user_id,
    )
    alignment_rows = select(
        TaskAlignmentUser.task_id,
        literal("alignment").label("kind"),
        TaskAlignmentUser.user_id.label("user_id"),
        null().label("email"),
        null().label("username"),
        null().label("full_name"),
        null().label("comment"),
    ).where(TaskAlignmentUser.task_id.in_(task_ids))

    metadata = union_all(assignee_rows, comment_rows, alignment_rows).subquery()
    rows = (
        await db.execute(
            select(metadata).order_by(metadata.c.kind, metadata.c.full_name.nulls_last())
        )
    ).all()

    assignees: dict[uuid.UUID, list[TaskAssigneeOut]] = {task_id: [] for task_id in task_ids}
    comments: dict[uuid.UUID, str | None] = {}
    alignments: dict[uuid.UUID, list[uuid.UUID]] = {}
    for task_id, kind, metadata_user_id, email, username, full_name, comment in rows:
        if kind == "assignee" and metadata_user_id is not None and email is not None:
            assignees.setdefault(task_id, []).append(
                TaskAssigneeOut(
                    id=metadata_user_id,
                    email=email,
                    username=username,
                    full_name=full_name,
                )
            )
        elif kind == "comment":
            comments[task_id] = comment
        elif kind == "alignment" and metadata_user_id is not None:
            alignments.setdefault(task_id, []).append(metadata_user_id)
    return assignees, comments, alignments


async def _assignees_for_fast_task_groups(
    db: AsyncSession, group_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[TaskAssigneeOut]]:
    """
    For fast tasks split into per-user copies, we still want TaskOut.assignees to
    show the full group membership (active copies only).
    """
    if not group_ids:
        return {}
    rows = (
        await db.execute(
            select(
                Task.fast_task_group_id,
                User.id,
                User.email,
                User.username,
                User.full_name,
            )
            .join(TaskAssignee, TaskAssignee.task_id == Task.id)
            .join(User, TaskAssignee.user_id == User.id)
            .where(Task.fast_task_group_id.in_(group_ids))
            .where(Task.is_active.is_(True))
            .order_by(Task.fast_task_group_id, User.full_name)
        )
    ).all()
    out: dict[uuid.UUID, list[TaskAssigneeOut]] = {}
    seen: dict[uuid.UUID, set[uuid.UUID]] = {}
    for group_id, user_id, email, username, full_name in rows:
        if group_id is None:
            continue
        if group_id not in seen:
            seen[group_id] = set()
        if user_id in seen[group_id]:
            continue
        seen[group_id].add(user_id)
        out.setdefault(group_id, []).append(
            TaskAssigneeOut(
                id=user_id,
                email=email,
                username=username,
                full_name=full_name,
            )
        )
    return out


async def _replace_task_assignees(
    db: AsyncSession, task: Task, assignee_ids: list[uuid.UUID]
) -> None:
    await db.execute(delete(TaskAssignee).where(TaskAssignee.task_id == task.id))
    if assignee_ids:
        values = [{"task_id": task.id, "user_id": user_id} for user_id in assignee_ids]
        await db.execute(insert(TaskAssignee), values)


async def _task_assignee_ids_for_planner(db: AsyncSession, task: Task) -> list[uuid.UUID]:
    rows = (
        await db.execute(select(TaskAssignee.user_id).where(TaskAssignee.task_id == task.id))
    ).scalars().all()
    ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for user_id in rows:
        if user_id not in seen:
            seen.add(user_id)
            ids.append(user_id)
    if task.assigned_to is not None and task.assigned_to not in seen:
        ids.append(task.assigned_to)
    return ids


async def _add_task_planner_exclusions(
    db: AsyncSession,
    *,
    task_id: uuid.UUID,
    user_ids: list[uuid.UUID],
    day_dates: list[date],
    created_by: uuid.UUID | None,
) -> None:
    if not user_ids or not day_dates:
        return

    existing_rows = (
        await db.execute(
            select(
                TaskPlannerExclusion.user_id,
                TaskPlannerExclusion.day_date,
                TaskPlannerExclusion.time_slot,
            )
            .where(TaskPlannerExclusion.task_id == task_id)
            .where(TaskPlannerExclusion.user_id.in_(user_ids))
            .where(TaskPlannerExclusion.day_date.in_(day_dates))
            .where(TaskPlannerExclusion.time_slot == "ALL")
        )
    ).all()
    existing = {(user_id, day_date, time_slot) for user_id, day_date, time_slot in existing_rows}
    for user_id in user_ids:
        for day_date in day_dates:
            key = (user_id, day_date, "ALL")
            if key in existing:
                continue
            db.add(
                TaskPlannerExclusion(
                    task_id=task_id,
                    user_id=user_id,
                    day_date=day_date,
                    time_slot="ALL",
                    created_by=created_by,
                )
            )


def _task_planner_days(task: Task) -> list[date]:
    due_day = _as_local_date(task.due_date)
    if due_day is None:
        return []
    start_day = _as_local_date(task.start_date)
    if start_day is None or start_day > due_day:
        start_day = due_day
    return _iter_workdays(start_day, due_day)


def _planner_slots_for_finish_period(finish_period: object | None) -> set[str]:
    normalized = (str(finish_period).strip().upper() if finish_period else "")
    if normalized in ("AM", "PM"):
        return {normalized, "ALL"}
    return {"AM", "PM", "ALL"}


async def _clear_task_planner_exclusions_for_current_plan(
    db: AsyncSession,
    *,
    task: Task,
    user_ids: list[uuid.UUID],
) -> None:
    day_dates = _task_planner_days(task)
    if not user_ids or not day_dates:
        return

    slots_to_clear = sorted(_planner_slots_for_finish_period(task.finish_period))
    await db.execute(
        delete(TaskPlannerExclusion).where(
            TaskPlannerExclusion.task_id == task.id,
            TaskPlannerExclusion.user_id.in_(user_ids),
            TaskPlannerExclusion.day_date.in_(day_dates),
            TaskPlannerExclusion.time_slot.in_(slots_to_clear),
        )
    )

    if task.project_id is not None:
        await db.execute(
            delete(ProjectPlannerExclusion).where(
                ProjectPlannerExclusion.project_id == task.project_id,
                ProjectPlannerExclusion.user_id.in_(user_ids),
                ProjectPlannerExclusion.day_date.in_(day_dates),
                ProjectPlannerExclusion.time_slot.in_(slots_to_clear),
            )
        )


async def _user_comments_for_tasks(
    db: AsyncSession, task_ids: list[uuid.UUID], user_id: uuid.UUID
) -> dict[uuid.UUID, str | None]:
    if not task_ids:
        return {}
    rows = (
        await db.execute(
            select(TaskUserComment.task_id, TaskUserComment.comment)
            .where(TaskUserComment.task_id.in_(task_ids))
            .where(TaskUserComment.user_id == user_id)
        )
    ).all()
    return {task_id: comment for task_id, comment in rows}


async def _question_ids_by_task(
    db: AsyncSession,
    tasks: list[Task],
) -> dict[uuid.UUID, set[uuid.UUID]]:
    task_ids = [task.id for task in tasks if task.question_origin_id is not None]
    if not task_ids:
        return {}
    rows = (
        await db.execute(
            select(QuestionDefinition.task_id, QuestionDefinition.id).where(
                QuestionDefinition.task_id.in_(task_ids)
            )
        )
    ).all()
    result: dict[uuid.UUID, set[uuid.UUID]] = {task_id: set() for task_id in task_ids}
    for task_id, question_id in rows:
        if task_id is not None:
            result.setdefault(task_id, set()).add(question_id)
    for task in tasks:
        if task.question_origin_id is not None and not result.get(task.id):
            result.setdefault(task.id, set()).add(task.question_origin_id)
    return result


async def _question_task_status_overrides(
    db: AsyncSession,
    tasks: list[Task],
    user_id: uuid.UUID,
) -> dict[uuid.UUID, TaskStatus]:
    question_ids_by_task = await _question_ids_by_task(db, tasks)
    all_question_ids = {
        question_id
        for question_ids in question_ids_by_task.values()
        for question_id in question_ids
    }
    if not all_question_ids:
        return {}
    done_question_ids = set(
        (
            await db.execute(
                select(QuestionUserStatus.question_id).where(
                    QuestionUserStatus.question_id.in_(all_question_ids),
                    QuestionUserStatus.user_id == user_id,
                    QuestionUserStatus.status == TaskStatus.DONE.value,
                )
            )
        ).scalars().all()
    )
    return {
        task_id: TaskStatus.DONE
        for task_id, question_ids in question_ids_by_task.items()
        if question_ids and question_ids.issubset(done_question_ids)
    }


def _all_question_assignees_done(
    question_ids: set[uuid.UUID],
    assigned_user_ids: set[uuid.UUID],
    done_pairs: set[tuple[uuid.UUID, uuid.UUID]],
) -> bool:
    return bool(question_ids and assigned_user_ids) and all(
        (question_id, assignee_id) in done_pairs
        for question_id in question_ids
        for assignee_id in assigned_user_ids
    )


async def _set_question_task_user_completion(
    db: AsyncSession,
    *,
    task: Task,
    user: User,
    is_done: bool,
) -> TaskStatus | None:
    question_ids = (await _question_ids_by_task(db, [task])).get(task.id, set())
    if not question_ids:
        return None

    existing_rows = (
        await db.execute(
            select(QuestionUserStatus).where(
                QuestionUserStatus.question_id.in_(question_ids),
                QuestionUserStatus.user_id == user.id,
            )
        )
    ).scalars().all()
    existing_by_question = {row.question_id: row for row in existing_rows}
    status_value = TaskStatus.DONE.value if is_done else None

    for question_id in question_ids:
        current = existing_by_question.get(question_id)
        if is_done:
            if current is None:
                db.add(
                    QuestionUserStatus(
                        question_id=question_id,
                        user_id=user.id,
                        status=TaskStatus.DONE.value,
                    )
                )
            else:
                current.status = TaskStatus.DONE.value
                current.updated_at = func.now()
        elif current is not None:
            await db.delete(current)
        db.add(
            QuestionStatusEvent(
                question_id=question_id,
                user_id=user.id,
                user_full_name=user.full_name or user.username or user.email,
                status=status_value,
            )
        )

    await db.flush()
    assigned_user_ids = set(
        (
            await db.execute(
                select(TaskAssignee.user_id).where(TaskAssignee.task_id == task.id)
            )
        ).scalars().all()
    )
    done_pairs = set(
        (
            await db.execute(
                select(QuestionUserStatus.question_id, QuestionUserStatus.user_id).where(
                    QuestionUserStatus.question_id.in_(question_ids),
                    QuestionUserStatus.user_id.in_(assigned_user_ids),
                    QuestionUserStatus.status == TaskStatus.DONE.value,
                )
            )
        ).all()
    ) if assigned_user_ids else set()
    all_assignees_done = _all_question_assignees_done(
        question_ids,
        assigned_user_ids,
        done_pairs,
    )
    task.status = TaskStatus.DONE if all_assignees_done else TaskStatus.TODO
    task.completed_at = datetime.now(timezone.utc) if all_assignees_done else None
    return TaskStatus.DONE if is_done else None


def _task_to_out(
    task: Task,
    assignees: list[TaskAssigneeOut],
    user_comment: str | None = None,
    status_override: TaskStatus | None = None,
    late_days: int | None = None,
    moved_days: int | None = None,
) -> TaskOut:
    return TaskOut(
        id=task.id,
        title=_normalize_email_task_title(
            task.title,
            is_system_task=(task.system_template_origin_id is not None or task.system_task_slot_id is not None),
        ),
        description=task.description,
        internal_notes=task.internal_notes,
        skill_category=task.skill_category,
        project_id=task.project_id,
        dependency_task_id=task.dependency_task_id,
        department_id=task.department_id,
        assigned_to=task.assigned_to,
        confirmation_assignee_id=task.confirmation_assignee_id,
        assignees=assignees,
        created_by=task.created_by,
        ga_note_origin_id=task.ga_note_origin_id,
        plan_note_origin_id=task.plan_note_origin_id,
        question_origin_id=task.question_origin_id,
        system_template_origin_id=task.system_template_origin_id,
        origin_run_at=task.origin_run_at,
        system_task_slot_id=task.system_task_slot_id,
        meeting_origin_id=task.meeting_origin_id,
        meeting_occurrence_date=task.meeting_occurrence_date,
        meeting_system_task_kind=task.meeting_system_task_kind,
        status=status_override or task.status,
        priority=task.priority,
        finish_period=task.finish_period,
        phase=task.phase,
        progress_percentage=task.progress_percentage,
        daily_products=task.daily_products,
        start_date=task.start_date,
        due_date=task.due_date,
        original_due_date=task.original_due_date,
        planned_date=_task_planned_date(task),
        late_days=late_days,
        moved_days=moved_days,
        completed_at=task.completed_at,
        is_deadline_important=task.is_deadline_important,
        is_bllok=task.is_bllok,
        is_1h_report=task.is_1h_report,
        one_h_report_slot=task.one_h_report_slot,
        one_h_marker=active_one_h_marker(task),
        one_h_marker_by_ga=bool(active_one_h_marker(task) and task.one_h_marker_by_ga),
        one_h_marker_comment=task.one_h_marker_comment,
        is_r1=task.is_r1,
        is_personal=task.is_personal,
        fast_task_order=task.fast_task_order,
        is_active=task.is_active,
        user_comment=user_comment,
        alignment_user_ids=None,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _enum_value(value) -> str | None:
    if value is None:
        return None
    return value.value if hasattr(value, "value") else value


def _daily_progress_finish_period_value(value) -> str:
    normalized = _enum_value(value)
    return normalized if normalized in ("AM", "PM", "ALL") else "ALL"


def _parse_origin_task_id(internal_notes: str | None) -> uuid.UUID | None:
    if not internal_notes:
        return None
    match = re.search(r"origin_task_id[:=]\s*([a-f0-9-]+)", internal_notes, re.IGNORECASE)
    if not match:
        return None
    try:
        return uuid.UUID(match.group(1))
    except (ValueError, AttributeError):
        return None


def _pcm_control_title(title: str) -> str:
    """Label newly created PCM control tasks without duplicating KO."""
    return title if re.match(r"^\s*KO(?:\s|$)", title, re.IGNORECASE) else f"KO {title}"


async def _project_for_id(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


async def _validate_pcm_control_origin(
    db: AsyncSession,
    *,
    project: Project | None,
    phase: str | ProjectPhaseStatus | None,
    internal_notes: str | None,
    require_origin: bool,
) -> Task | None:
    """Validate the PRODUCT source for PCM MST/TT CONTROL tasks."""
    phase_value = phase.value if isinstance(phase, ProjectPhaseStatus) else str(phase or "")
    if project is None or phase_value.upper() != ProjectPhaseStatus.CONTROL.value:
        return None
    if not _is_mst_or_tt_project(project) or project.department_id is None:
        return None

    department_code = (
        await db.execute(select(Department.code).where(Department.id == project.department_id))
    ).scalar_one_or_none()
    if str(department_code or "").strip().upper() != "PCM":
        return None

    ko_user_id = parse_ko_user_id(internal_notes)
    if ko_user_id is not None:
        ko_user = (
            await db.execute(select(User).where(User.id == ko_user_id, User.is_active.is_(True)))
        ).scalar_one_or_none()
        if ko_user is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CONTROL task KO must be an active user",
            )

    origin_id = _parse_origin_task_id(internal_notes)
    if origin_id is None:
        if require_origin:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="CONTROL task requires a linked PRODUCT task",
            )
        return None

    origin = (
        await db.execute(select(Task).where(Task.id == origin_id))
    ).scalar_one_or_none()
    if (
        origin is None
        or not origin.is_active
        or origin.project_id != project.id
        or str(origin.phase or "").upper() != ProjectPhaseStatus.PRODUCT.value
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CONTROL task must link to an active PRODUCT task in the same project",
        )
    return origin


async def _sync_control_task_owner_from_ko(
    db: AsyncSession,
    *,
    task: Task,
    project: Project | None = None,
) -> uuid.UUID | None:
    """
    Keep KO as the sole owner of CONTROL MST/TT (PCM) tasks.

    The PRODUCT executor is resolved through origin_task_id and must not be
    duplicated in CONTROL assignment fields.
    """
    return await ensure_ko_user_is_task_assignee(db, task=task, project=project)


async def _create_pcm_control_for_product(
    db: AsyncSession,
    *,
    product_task: Task,
    project: Project | None,
) -> Task | None:
    """Create exactly one linked CONTROL for a new PCM MST/TT PRODUCT task."""
    phase_value = (
        product_task.phase.value
        if isinstance(product_task.phase, ProjectPhaseStatus)
        else str(product_task.phase or "")
    )
    if (
        project is None
        or product_task.project_id is None
        or phase_value.upper() != ProjectPhaseStatus.PRODUCT.value
        or not _is_mst_or_tt_project(project)
        or project.department_id is None
    ):
        return None

    department_code = (
        await db.execute(select(Department.code).where(Department.id == project.department_id))
    ).scalar_one_or_none()
    if str(department_code or "").strip().upper() != "PCM":
        return None

    possible_controls = (
        await db.execute(
            select(Task)
            .where(Task.project_id == project.id)
            .where(Task.phase == ProjectPhaseStatus.CONTROL.value)
            .where(Task.is_active.is_(True))
            .where(Task.internal_notes.ilike(f"%{product_task.id}%"))
        )
    ).scalars().all()
    for control in possible_controls:
        if _parse_origin_task_id(control.internal_notes) == product_task.id:
            return control

    total, _ = _extract_total_and_completed(product_task.daily_products, product_task.internal_notes)
    notes = f"origin_task_id={product_task.id}; total_products={total or 0}; completed_products=0"
    control = Task(
        title=_pcm_control_title(product_task.title),
        description=product_task.description,
        internal_notes=notes,
        project_id=project.id,
        department_id=project.department_id,
        assigned_to=None,
        created_by=product_task.created_by,
        status=TaskStatus.TODO,
        priority=product_task.priority,
        finish_period=product_task.finish_period,
        phase=ProjectPhaseStatus.CONTROL.value,
        progress_percentage=0,
        start_date=product_task.start_date,
        due_date=None,
        is_deadline_important=product_task.is_deadline_important,
    )
    db.add(control)
    await db.flush()
    add_audit_log(
        db=db,
        actor_user_id=product_task.created_by,
        entity_type="task",
        entity_id=control.id,
        action="created",
        before=None,
        after={
            "title": control.title,
            "status": TaskStatus.TODO.value,
            "assigned_to": None,
            "phase": ProjectPhaseStatus.CONTROL.value,
            "origin_task_id": str(product_task.id),
        },
    )
    return control


async def _users_by_usernames(db: AsyncSession, usernames: set[str]) -> list[User]:
    if not usernames:
        return []
    rows = (await db.execute(select(User).where(User.username.in_(sorted(usernames))))).scalars().all()
    return rows


def _extract_mentions(text: str | None) -> set[str]:
    if not text:
        return set()
    return set(MENTION_RE.findall(text))


async def _is_user_assigned_to_task(db: AsyncSession, task: Task, user_id: uuid.UUID) -> bool:
    if task.assigned_to == user_id:
        return True
    assignee_record = (
        await db.execute(
            select(TaskAssignee)
            .where(TaskAssignee.task_id == task.id, TaskAssignee.user_id == user_id)
        )
    ).scalar_one_or_none()
    return assignee_record is not None


class FastTaskOrderUpdate(BaseModel):
    user_id: uuid.UUID
    ordered_task_ids: list[uuid.UUID]


class GaNoteTaskBatchRequest(BaseModel):
    ga_note_origin_ids: list[uuid.UUID]
    plan_note_origin_ids: list[uuid.UUID] = Field(default_factory=list)
    include_done: bool = True
    include_all_done: bool = False
    include_inactive: bool = False


class DashboardTaskSummary(BaseModel):
    open_tasks: int
    overdue: int
    reminders: int
    system_tasks: int


def _ga_note_task_batch_stmt(payload: GaNoteTaskBatchRequest):
    ga_note_ids = list(dict.fromkeys(payload.ga_note_origin_ids))
    plan_note_ids = list(dict.fromkeys(payload.plan_note_origin_ids))
    origin_filters = []
    if ga_note_ids:
        origin_filters.append(Task.ga_note_origin_id.in_(ga_note_ids))
    if plan_note_ids:
        origin_filters.append(Task.plan_note_origin_id.in_(plan_note_ids))
    if not origin_filters:
        return None

    stmt = select(Task).where(or_(*origin_filters))
    if not payload.include_inactive:
        stmt = stmt.where(Task.is_active.is_(True))
    if not payload.include_done:
        stmt = stmt.where(Task.status != TaskStatus.DONE.value)
    elif not payload.include_all_done:
        done_cutoff = datetime.now(timezone.utc) - timedelta(days=45)
        stmt = stmt.where(
            or_(
                Task.status != TaskStatus.DONE.value,
                Task.completed_at >= done_cutoff,
            )
        )
    return stmt.order_by(Task.created_at)


def _is_common_view_orderable_task(task: Task) -> bool:
    return bool(
        is_fast_task_model(task)
        or task.is_bllok
        or task.is_1h_report
        or task.is_personal
        or task.is_r1
    )


def _uses_fast_task_group(task: Task) -> bool:
    """GA/plan-note copies are grouped by their origin, never as fast groups."""

    return bool(
        task.fast_task_group_id is not None
        and task.ga_note_origin_id is None
        and task.plan_note_origin_id is None
        and is_fast_task_model(task)
    )


def _can_complete_waiting_confirmation(
    *,
    user_role: UserRole,
    actor_user_id: uuid.UUID,
    confirmation_assignee_id: uuid.UUID | None,
    actor_is_assignee: bool,
) -> bool:
    if user_role in (UserRole.ADMIN, UserRole.MANAGER):
        return True
    if confirmation_assignee_id is not None and confirmation_assignee_id == actor_user_id:
        return True
    return actor_is_assignee


async def _require_rlz_completion_comment(
    db: AsyncSession,
    *,
    task: Task,
    user: User,
    actor_is_assignee: bool,
    override_reason: str | None,
) -> bool:
    """Return True when a manager/admin used an audited exceptional override."""
    if not task.is_active or task.department_id is None:
        return False
    comment = (
        await db.execute(
            select(TaskUserComment.comment).where(
                TaskUserComment.task_id == task.id,
                TaskUserComment.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    try:
        return _validate_rlz_completion_comment(
            user_role=user.role,
            actor_is_assignee=actor_is_assignee,
            personal_comment=comment,
            override_reason=override_reason,
        )
    except ValueError as exc:
        code = str(exc)
    if code == "RLZ_COMPLETION_OVERRIDE_REASON_REQUIRED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "RLZ_COMPLETION_OVERRIDE_REASON_REQUIRED",
                "message": "Mbyllja pa komentin personal kërkon arsye për përjashtim.",
            },
        )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "RLZ_TASK_COMMENT_REQUIRED",
            "message": "Para mbylljes, shto komentin për rezultatin e kësaj detyre.",
            "task_id": str(task.id),
        },
    )


def _requires_rlz_completion_comment(task: Task) -> bool:
    """Special and note-origin tasks do not use the RLZ result-comment flow."""
    return not _supports_waiting_confirmation(task)


def _validate_rlz_completion_comment(
    *,
    user_role: UserRole,
    actor_is_assignee: bool,
    personal_comment: str | None,
    override_reason: str | None,
) -> bool:
    """Pure completion rule used by every explicit task-status path and tests."""
    if actor_is_assignee and personal_comment and personal_comment.strip():
        return False
    if user_role in (UserRole.ADMIN, UserRole.MANAGER):
        if override_reason and override_reason.strip():
            return True
        raise ValueError("RLZ_COMPLETION_OVERRIDE_REASON_REQUIRED")
    raise ValueError("RLZ_TASK_COMMENT_REQUIRED")


async def _clear_ga_note_conversion_if_no_active_tasks(
    db: AsyncSession,
    *,
    note_id: uuid.UUID | None,
    deleting_task_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    if note_id is None:
        return

    remaining_active_count = (
        await db.execute(
            select(func.count())
            .select_from(Task)
            .where(Task.ga_note_origin_id == note_id)
            .where(Task.id != deleting_task_id)
            .where(Task.is_active.is_(True))
        )
    ).scalar_one()
    if remaining_active_count > 0:
        return

    note = (await db.execute(select(GaNote).where(GaNote.id == note_id))).scalar_one_or_none()
    if note is None or not note.is_converted_to_task:
        return

    note.is_converted_to_task = False
    add_audit_log(
        db=db,
        actor_user_id=actor_user_id,
        entity_type="ga_note",
        entity_id=note.id,
        action="task_conversion_cleared",
        before={"is_converted_to_task": True},
        after={"is_converted_to_task": False},
    )


async def _clear_plan_note_conversion_if_no_active_tasks(
    db: AsyncSession,
    *,
    note_id: uuid.UUID | None,
    deleting_task_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    if note_id is None:
        return

    remaining_active_count = (
        await db.execute(
            select(func.count())
            .select_from(Task)
            .where(Task.plan_note_origin_id == note_id)
            .where(Task.id != deleting_task_id)
            .where(Task.is_active.is_(True))
        )
    ).scalar_one()
    if remaining_active_count > 0:
        return

    note = (await db.execute(select(PlanNote).where(PlanNote.id == note_id))).scalar_one_or_none()
    if note is None or not note.is_converted_to_task:
        return

    note.is_converted_to_task = False
    add_audit_log(
        db=db,
        actor_user_id=actor_user_id,
        entity_type="plan_note",
        entity_id=note.id,
        action="task_conversion_cleared",
        before={"is_converted_to_task": True},
        after={"is_converted_to_task": False},
    )


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    department_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    status: TaskStatus | None = None,
    skill_category: TaskSkillCategory | None = None,
    assigned_to: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    ga_note_origin_ids: list[uuid.UUID] | None = Query(None),
    plan_note_origin_ids: list[uuid.UUID] | None = Query(None),
    due_from: datetime | None = None,
    due_to: datetime | None = None,
    window_from: datetime | None = None,
    window_to: datetime | None = None,
    include_done: bool = True,
    include_all_done: bool = False,
    include_inactive: bool = False,
    system_only: bool = False,
    include_all_departments: bool = False,
    related_user_id: uuid.UUID | None = None,
    related_department_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[TaskOut]:
    stmt = select(Task)
    project: Project | None = None
    is_mst_tt_project = False
    if project_id is not None:
        project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
        if project is not None:
            is_mst_tt_project = _is_mst_or_tt_project(project)

    if project_id is None:
        # No role-based filtering for task visibility.
        pass

    if not include_inactive:
        stmt = stmt.where(Task.is_active.is_(True))
    if system_only:
        stmt = stmt.where(Task.system_template_origin_id.is_not(None))

    if department_id:
        project_ids_in_department = select(Project.id).where(Project.department_id == department_id)
        task_ids_assigned_in_department = (
            select(TaskAssignee.task_id)
            .join(User, User.id == TaskAssignee.user_id)
            .where(User.department_id == department_id)
        )
        # A shared task can belong to a department through its assignees.
        # Keep these as semi-joins so PostgreSQL can resolve the small project
        # and user sets once instead of probing joined tables for every task.
        stmt = stmt.where(
            or_(
                Task.department_id == department_id,
                Task.project_id.in_(project_ids_in_department),
                Task.id.in_(task_ids_assigned_in_department),
            )
        )
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    if status:
        stmt = stmt.where(Task.status == status.value)
    if skill_category:
        stmt = stmt.where(Task.skill_category == skill_category)
    if assigned_to:
        # Check both Task.assigned_to and TaskAssignee table for multiple assignees
        stmt = stmt.where(
            or_(
                Task.assigned_to == assigned_to,
                exists(
                    select(1).where(
                        TaskAssignee.task_id == Task.id,
                        TaskAssignee.user_id == assigned_to,
                    )
                ),
            )
        )
    if created_by:
        stmt = stmt.where(Task.created_by == created_by)
    if related_user_id:
        # Everything a single-user view (e.g. Admin Tasks for GA) builds rows
        # from: the user's own tasks, the department's tasks, and every
        # instance of system templates the user works on or is aligned with,
        # so merged system-task assignees stay complete.
        def _related_task(entity):
            conditions = [
                entity.assigned_to == related_user_id,
                entity.confirmation_assignee_id == related_user_id,
                entity.id.in_(select(TaskAssignee.task_id).where(TaskAssignee.user_id == related_user_id)),
                entity.id.in_(select(TaskAlignmentUser.task_id).where(TaskAlignmentUser.user_id == related_user_id)),
            ]
            if related_department_id:
                conditions.append(entity.department_id == related_department_id)
            return or_(*conditions)

        related_instance = aliased(Task)
        related_template_ids = union_all(
            select(SystemTaskTemplateAlignmentUser.template_id).where(
                SystemTaskTemplateAlignmentUser.user_id == related_user_id
            ),
            select(related_instance.system_template_origin_id).where(
                related_instance.system_template_origin_id.is_not(None),
                related_instance.is_active.is_(True),
                _related_task(related_instance),
            ),
        )
        stmt = stmt.where(
            or_(_related_task(Task), Task.system_template_origin_id.in_(related_template_ids))
        )
    if ga_note_origin_ids:
        stmt = stmt.where(Task.ga_note_origin_id.in_(ga_note_origin_ids))
    if plan_note_origin_ids:
        stmt = stmt.where(Task.plan_note_origin_id.in_(plan_note_origin_ids))
    if due_from:
        stmt = stmt.where(Task.due_date >= due_from)
    if due_to:
        stmt = stmt.where(Task.due_date <= due_to)
    if window_from or window_to:
        stmt = stmt.where(task_date_window_filter(
            _as_local_date(window_from) if window_from else None,
            _as_local_date(window_to) if window_to else None,
        ))
    if not include_done:
        stmt = stmt.where(Task.status != TaskStatus.DONE.value)
    elif not include_all_done:
        # Only include DONE tasks completed within the last 45 days.
        # Historical completed tasks are never shown in kanban views anyway.
        done_cutoff = datetime.now(timezone.utc) - timedelta(days=45)
        stmt = stmt.where(
            or_(
                Task.status != TaskStatus.DONE.value,
                Task.completed_at >= done_cutoff,
            )
        )

    if q and q.strip():
        search = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(or_(Task.title.ilike(search, escape="\\"), Task.description.ilike(search, escape="\\")))
    stmt = stmt.order_by(Task.created_at).offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    tasks = (await db.execute(stmt)).scalars().all()
    task_ids = [t.id for t in tasks]
    assignee_map, comment_map, alignment_map = await _task_list_metadata(db, task_ids, user.id)
    question_status_overrides = await _question_task_status_overrides(db, tasks, user.id)

    out = []
    today = _as_local_date(datetime.now(timezone.utc)) or datetime.now(timezone.utc).date()
    for t in tasks:
        status_override: TaskStatus | None = None
        if is_mst_tt_project and t.phase in (ProjectPhaseStatus.PRODUCT.value, ProjectPhaseStatus.CONTROL.value):
            total, completed = _extract_total_and_completed(t.daily_products, t.internal_notes)
            status_override = _product_count_status_for_output(t.status, total, completed)
        if t.id in question_status_overrides:
            status_override = question_status_overrides[t.id]
        if not include_done and status_override == TaskStatus.DONE:
            continue
        # Important: for list views we keep task-local assignees (TaskAssignee rows).
        # Fast-task "group" membership is shown in the task details endpoint instead.
        # Otherwise each per-user copy would appear assigned to everyone in the group,
        # which breaks "My view" filtering and per-user status display.
        dto_assignees = assignee_map.get(t.id, [])
        dto = _task_to_out(
            t,
            dto_assignees or [],
            user_comment=comment_map.get(t.id),
            status_override=status_override,
            late_days=_task_late_days(t, today=today),
            moved_days=_task_moved_days(t),
        )
        dto.alignment_user_ids = alignment_map.get(t.id)
        out.append(dto)
    return out


@router.get("/dashboard-summary", response_model=DashboardTaskSummary)
async def dashboard_task_summary(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
) -> DashboardTaskSummary:
    """Return the counts rendered by the dashboard without materializing tasks.

    The current task response does not expose the legacy ``planned_for``,
    ``reminder_enabled`` or ``task_type`` fields, so those three client-side
    filters always produce zero. Keeping those values explicit preserves the
    existing dashboard result while reducing the request to one index-only
    count query.
    """

    open_tasks = (
        await db.execute(
            select(func.count())
            .select_from(Task)
            .where(Task.is_active.is_(True), Task.status != TaskStatus.DONE.value)
        )
    ).scalar_one()
    return DashboardTaskSummary(
        open_tasks=int(open_tasks or 0),
        overdue=0,
        reminders=0,
        system_tasks=0,
    )


@router.get("/waiting-confirmation-ga/count")
async def waiting_confirmation_ga_count(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict[str, int]:
    """Return the current recipient's pending-confirmation badge count."""

    count = (
        await db.execute(
            select(func.count())
            .select_from(Task)
            .where(
                Task.is_active.is_(True),
                Task.status == TaskStatus.WAITING_CONFIRMATION.value,
                Task.confirmation_assignee_id == user.id,
            )
        )
    ).scalar_one()
    return {"count": int(count or 0)}


@router.post("/by-ga-notes", response_model=list[TaskOut])
async def list_tasks_by_ga_notes(
    payload: GaNoteTaskBatchRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[TaskOut]:
    stmt = _ga_note_task_batch_stmt(payload)
    if stmt is None:
        return []
    tasks = (await db.execute(stmt)).scalars().all()
    task_ids = [task.id for task in tasks]
    assignee_map, comment_map, alignment_map = await _task_list_metadata(db, task_ids, user.id)

    today = _as_local_date(datetime.now(timezone.utc)) or datetime.now(timezone.utc).date()
    out = []
    for task in tasks:
        dto = _task_to_out(
            task,
            assignee_map.get(task.id, []) or [],
            user_comment=comment_map.get(task.id),
            late_days=_task_late_days(task, today=today),
            moved_days=_task_moved_days(task),
        )
        dto.alignment_user_ids = alignment_map.get(task.id)
        out.append(dto)
    return out


@router.post("/by-ga-notes/summary", response_model=list[GaNoteTaskSummaryOut])
async def list_task_summaries_by_ga_notes(
    payload: GaNoteTaskBatchRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
) -> list[GaNoteTaskSummaryOut]:
    """Return only the fields rendered by GA/KA Notes.

    The regular task endpoint remains unchanged for other consumers. This path
    avoids loading/serializing large task details and skips per-user comments
    and alignment metadata that the notes table never renders.
    """

    stmt = _ga_note_task_batch_stmt(payload)
    if stmt is None:
        return []
    stmt = stmt.options(
        load_only(
            Task.id,
            Task.description,
            Task.project_id,
            Task.department_id,
            Task.assigned_to,
            Task.confirmation_assignee_id,
            Task.ga_note_origin_id,
            Task.plan_note_origin_id,
            Task.status,
            Task.priority,
            Task.finish_period,
            Task.start_date,
            Task.due_date,
            Task.is_deadline_important,
            Task.is_bllok,
            Task.is_1h_report,
            Task.one_h_report_slot,
            Task.one_h_marker,
            Task.one_h_marker_date,
            Task.one_h_marker_comment,
            Task.is_r1,
            Task.is_personal,
            Task.created_at,
            Task.updated_at,
        )
    )
    tasks = (await db.execute(stmt)).scalars().all()
    assignee_map = await _assignees_for_tasks(db, [task.id for task in tasks])
    return [
        GaNoteTaskSummaryOut(
            id=task.id,
            description=task.description,
            project_id=task.project_id,
            department_id=task.department_id,
            assigned_to=task.assigned_to,
            confirmation_assignee_id=task.confirmation_assignee_id,
            assignees=assignee_map.get(task.id, []),
            ga_note_origin_id=task.ga_note_origin_id,
            plan_note_origin_id=task.plan_note_origin_id,
            status=task.status,
            priority=task.priority,
            finish_period=task.finish_period,
            start_date=task.start_date,
            due_date=task.due_date,
            is_deadline_important=task.is_deadline_important,
            is_bllok=task.is_bllok,
            is_1h_report=task.is_1h_report,
            one_h_report_slot=task.one_h_report_slot,
            one_h_marker=active_one_h_marker(task),
            one_h_marker_comment=task.one_h_marker_comment,
            is_r1=task.is_r1,
            is_personal=task.is_personal,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        for task in tasks
    ]


@router.patch("/fast-order", response_model=None)
async def update_fast_task_order(
    payload: FastTaskOrderUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> Response:
    ordered_task_ids: list[uuid.UUID] = []
    seen_task_ids: set[uuid.UUID] = set()
    for task_id in payload.ordered_task_ids or []:
        if task_id in seen_task_ids:
            continue
        seen_task_ids.add(task_id)
        ordered_task_ids.append(task_id)

    if not ordered_task_ids:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    tasks = (
        await db.execute(select(Task).where(Task.id.in_(ordered_task_ids)))
    ).scalars().all()
    if len(tasks) != len(ordered_task_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Some tasks were not found")

    task_ids = [task.id for task in tasks]
    assignee_rows = (
        await db.execute(
            select(TaskAssignee.task_id, TaskAssignee.user_id).where(TaskAssignee.task_id.in_(task_ids))
        )
    ).all()
    assignee_map: dict[uuid.UUID, set[uuid.UUID]] = {task_id: set() for task_id in task_ids}
    for task_id, assignee_id in assignee_rows:
        assignee_map.setdefault(task_id, set()).add(assignee_id)

    tasks_by_id = {task.id: task for task in tasks}
    for task_id in ordered_task_ids:
        task = tasks_by_id[task_id]
        ensure_task_editor(user, task)
        if not _is_common_view_orderable_task(task):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only Common View tasks can be reordered")
        assignee_ids = assignee_map.get(task.id, set())
        if task.assigned_to is not None:
            assignee_ids.add(task.assigned_to)
        if payload.user_id not in assignee_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ordered tasks must belong to the selected user",
            )

    for index, task_id in enumerate(ordered_task_ids, start=1):
        tasks_by_id[task_id].fast_task_order = index

    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> TaskOut:
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    assignee_map = await _assignees_for_tasks(db, [task.id])
    dto_assignees = assignee_map.get(task.id, [])
    if _uses_fast_task_group(task):
        group_map = await _assignees_for_fast_task_groups(db, [task.fast_task_group_id])
        dto_assignees = group_map.get(task.fast_task_group_id, dto_assignees)
    status_override: TaskStatus | None = None
    if task.project_id is not None and task.phase in (
        ProjectPhaseStatus.PRODUCT.value,
        ProjectPhaseStatus.CONTROL.value,
    ):
        project = (await db.execute(select(Project).where(Project.id == task.project_id))).scalar_one_or_none()
        if project is not None and _is_mst_or_tt_project(project):
            total, completed = _extract_total_and_completed(task.daily_products, task.internal_notes)
            status_override = _product_count_status_for_output(task.status, total, completed)
    question_status_overrides = await _question_task_status_overrides(db, [task], user.id)
    if task.id in question_status_overrides:
        status_override = question_status_overrides[task.id]

    dto = _task_to_out(task, dto_assignees or [], status_override=status_override)
    if task.plan_note_origin_id is not None:
        planning_brief_payload = (
            await db.execute(
                select(PlanNote.planning_brief).where(PlanNote.id == task.plan_note_origin_id)
            )
        ).scalar_one_or_none()
        dto.planning_brief = (
            PxJavPlanningBrief.model_validate(planning_brief_payload)
            if planning_brief_payload
            else None
        )
    rows = (
        await db.execute(
            select(TaskAlignmentUser.user_id).where(TaskAlignmentUser.task_id == task.id)
        )
    ).scalars().all()
    dto.alignment_user_ids = list(rows) if rows else None
    return dto


@router.post("", response_model=TaskOut)
async def create_task(
    payload: TaskCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> TaskOut:
    return await create_task_in_session(payload, db, user)


async def create_task_in_session(payload: TaskCreate, db: AsyncSession, user, *, before_commit=None) -> TaskOut:
    """Existing creation flow; an internal hook can attach provenance atomically.

    The hook is not an API parameter. It supports an ordinary task or one
    note's per-assignee tasks. For a group, the hook receives its
    representative first task once, after all copies have been constructed.
    """
    if before_commit is not None and (payload.plan_note_origin_id or payload.dependency_task_id):
        raise ValueError("Provenance hook does not support plan notes or dependencies")
    # ensures_manager_or_admin(user) - Removed to allow all department members to create tasks
    payload.title = _normalize_email_task_title(payload.title)
    _validate_eight_am_one_h_slot(payload.title, payload.one_h_report_slot)
    if payload.ga_note_origin_id is not None and payload.plan_note_origin_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot set both ga_note_origin_id and plan_note_origin_id",
        )

    if payload.ga_note_origin_id is None and payload.plan_note_origin_id is None:
        from app.services.task_marker_comment_title import update_comment_in_title

        payload.title = update_comment_in_title(
            payload.title, None, normalize_marker_comment(payload.one_h_marker, payload.one_h_marker_comment),
        )

    department_id = payload.department_id
    dependency_task_id = payload.dependency_task_id
    is_fast = is_fast_task_fields(
        title=payload.title,
        project_id=payload.project_id,
        dependency_task_id=dependency_task_id,
        system_template_origin_id=None,
        ga_note_origin_id=payload.ga_note_origin_id,
        plan_note_origin_id=payload.plan_note_origin_id,
    )
    project = None
    task_project_department = None
    if payload.project_id is not None:
        project = await _project_for_id(db, payload.project_id)
        if project.department_id is not None and project.department_id != department_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project department mismatch")
        if project.department_id is not None:
            task_project_department = (
                await db.execute(select(Department).where(Department.id == project.department_id))
            ).scalar_one_or_none()

    is_development_project = _is_development_department(task_project_department)

    # Task creation is intentionally global: every authenticated user may
    # create a task in any department and assign it to any active user.

    if dependency_task_id is not None:
        if payload.project_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dependency requires a project")
        dependency_task = (
            await db.execute(select(Task).where(Task.id == dependency_task_id))
        ).scalar_one_or_none()
        if dependency_task is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dependency task not found")
        if dependency_task.project_id != payload.project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dependency must be in the same project")
        task.dependency_task_id = payload.dependency_task_id

    if payload.ga_note_origin_id is not None:
        ga_note = (
            await db.execute(select(GaNote).where(GaNote.id == payload.ga_note_origin_id).with_for_update())
        ).scalar_one_or_none()
        if ga_note is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="GA note not found")
        ga_note_department = None
        if ga_note.department_id is not None:
            ga_note_department = (
                await db.execute(select(Department).where(Department.id == ga_note.department_id))
            ).scalar_one_or_none()
        is_dev_ga_note = False
        if ga_note_department is not None:
            dept_name = (ga_note_department.name or "").strip().upper()
            dept_code = (ga_note_department.code or "").strip().upper()
            if dept_name == "DEVELOPMENT" or dept_code == "DEV":
                is_dev_ga_note = True
        if ga_note.project_id is not None:
            ga_project = (
                await db.execute(select(Project).where(Project.id == ga_note.project_id))
            ).scalar_one_or_none()
            if ga_project is not None and ga_project.department_id is not None:
                ga_project_department = (
                    await db.execute(select(Department).where(Department.id == ga_project.department_id))
                ).scalar_one_or_none()
                if ga_project_department is not None:
                    code = (ga_project_department.code or "").upper()
                    if code in ("PCM", "GDS") and not is_dev_ga_note:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Tasks for PCM/GDS projects must be created manually",
                        )
        # Allow cross-department task creation from GA notes - removed department mismatch check
        # if ga_note.department_id is not None and ga_note.department_id != department_id:
        #     raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="GA note department mismatch")
        if ga_note.project_id is not None and ga_note.project_id != payload.project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="GA note project mismatch")
        existing_ga_note_task = (
            await db.execute(
                select(Task)
                .where(Task.ga_note_origin_id == payload.ga_note_origin_id)
                .where(Task.is_active.is_(True))
                .order_by(Task.created_at.asc(), Task.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing_ga_note_task is not None:
            if not ga_note.is_converted_to_task:
                ga_note.is_converted_to_task = True
                await db.commit()
                await db.refresh(existing_ga_note_task)

            assignee_map = await _assignees_for_tasks(db, [existing_ga_note_task.id])
            dto = _task_to_out(existing_ga_note_task, assignee_map.get(existing_ga_note_task.id, []))
            rows = (
                await db.execute(
                    select(TaskAlignmentUser.user_id).where(TaskAlignmentUser.task_id == existing_ga_note_task.id)
                )
            ).scalars().all()
            dto.alignment_user_ids = list(rows) if rows else None
            return dto
        ga_note.is_converted_to_task = True
        if _payload_has_field(payload, "one_h_marker"):
            ga_note.one_h_marker = payload.one_h_marker
        else:
            payload = payload.model_copy(update={"one_h_marker": ga_note.one_h_marker})

    if payload.plan_note_origin_id is not None:
        plan_note = (
            await db.execute(
                select(PlanNote)
                .where(PlanNote.id == payload.plan_note_origin_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if plan_note is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plan note not found")
        plan_note_department = None
        if plan_note.department_id is not None:
            plan_note_department = (
                await db.execute(select(Department).where(Department.id == plan_note.department_id))
            ).scalar_one_or_none()
        is_dev_plan_note = False
        if plan_note_department is not None:
            dept_name = (plan_note_department.name or "").strip().upper()
            dept_code = (plan_note_department.code or "").strip().upper()
            if dept_name == "DEVELOPMENT" or dept_code == "DEV":
                is_dev_plan_note = True
        if plan_note.project_id is not None:
            plan_project = (
                await db.execute(select(Project).where(Project.id == plan_note.project_id))
            ).scalar_one_or_none()
            if plan_project is not None and plan_project.department_id is not None:
                plan_project_department = (
                    await db.execute(select(Department).where(Department.id == plan_project.department_id))
                ).scalar_one_or_none()
                if plan_project_department is not None:
                    code = (plan_project_department.code or "").upper()
                    if code in ("PCM", "GDS") and not is_dev_plan_note:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Tasks for PCM/GDS projects must be created manually",
                        )
        if plan_note.project_id is not None and plan_note.project_id != payload.project_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plan note project mismatch")
        existing_plan_note_task = (
            await db.execute(
                select(Task)
                .where(Task.plan_note_origin_id == payload.plan_note_origin_id)
                .where(Task.is_active.is_(True))
                .order_by(Task.created_at.asc(), Task.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing_plan_note_task is not None:
            if not plan_note.is_converted_to_task:
                plan_note.is_converted_to_task = True
                await db.commit()
                await db.refresh(existing_plan_note_task)

            assignee_map = await _assignees_for_tasks(db, [existing_plan_note_task.id])
            dto = _task_to_out(existing_plan_note_task, assignee_map.get(existing_plan_note_task.id, []))
            rows = (
                await db.execute(
                    select(TaskAlignmentUser.user_id).where(TaskAlignmentUser.task_id == existing_plan_note_task.id)
                )
            ).scalars().all()
            dto.alignment_user_ids = list(rows) if rows else None
            return dto
        plan_note.is_converted_to_task = True
        if _payload_has_field(payload, "one_h_marker"):
            plan_note.one_h_marker = payload.one_h_marker
        else:
            payload = payload.model_copy(update={"one_h_marker": plan_note.one_h_marker})

    assignee_ids: list[uuid.UUID] | None = None
    assignee_users: list[User] = []
    # Allow cross-department for projects, GA notes, plan notes, or fast tasks (tasks without project_id)
    allow_cross_department = (
        project is not None
        or payload.ga_note_origin_id is not None
        or payload.plan_note_origin_id is not None
        or payload.project_id is None
    )
    if payload.assignees is not None:
        seen: set[uuid.UUID] = set()
        assignee_ids = [uid for uid in payload.assignees if not (uid in seen or seen.add(uid))]
    elif payload.assigned_to is not None:
        assignee_ids = [payload.assigned_to]

    if (payload.ga_note_origin_id is not None or payload.plan_note_origin_id is not None) and not assignee_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one assignee for a note task",
        )

    if assignee_ids is not None:
        assignee_users = (
            await db.execute(select(User).where(User.id.in_(assignee_ids)))
        ).scalars().all()
        if len(assignee_users) != len(assignee_ids):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user not found")
        for assignee in assignee_users:
            if not allow_cross_department and assignee.department_id != department_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user must be in department")

    assignee_dept_map: dict[uuid.UUID, uuid.UUID | None] = {
        user.id: user.department_id for user in assignee_users
    }
    await ensure_daily_baselines_for_departments(
        db=db,
        department_ids={department_id, *assignee_dept_map.values()},
        day=datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date(),
        actor=user,
    )

    status_value = payload.status or TaskStatus.TODO
    if payload.ga_note_origin_id is not None or payload.plan_note_origin_id is not None:
        status_value = _normalize_ga_note_task_status(status_value)
    if status_value == TaskStatus.DONE and department_id is not None:
        if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "RLZ_TASK_COMMENT_REQUIRED",
                    "message": "Krijo detyrën, shto komentin e rezultatit dhe pastaj mbylle.",
                },
            )
        if not (payload.completion_override_reason and payload.completion_override_reason.strip()):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "RLZ_COMPLETION_OVERRIDE_REASON_REQUIRED",
                    "message": "Krijimi direkt si DONE kërkon arsye për përjashtim.",
                },
            )
    confirmation_assignee_id = payload.confirmation_assignee_id
    if status_value == TaskStatus.WAITING_CONFIRMATION:
        if not _payload_supports_waiting_confirmation(payload):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="WAITING_CONFIRMATION is only available for 1H, R1, Personal, Bllok, GA/KA note, or plan-note tasks",
            )
        await _validate_waiting_confirmation_assignee(db, confirmation_assignee_id)
    elif confirmation_assignee_id is not None:
        confirmation_user = (
            await db.execute(select(User).where(User.id == confirmation_assignee_id))
        ).scalar_one_or_none()
        if confirmation_user is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Confirmation assignee not found")
    priority_value = payload.priority or TaskPriority.NORMAL
    phase_value = payload.phase or (project.current_phase if project else ProjectPhaseStatus.MEETINGS)
    phase_value = _normalize_project_task_phase(
        phase_value,
        is_development_project=is_development_project,
    )

    pcm_control_origin = await _validate_pcm_control_origin(
        db,
        project=project,
        phase=phase_value,
        internal_notes=payload.internal_notes,
        require_origin=True,
    )
    if pcm_control_origin is not None:
        # CONTROL ownership is authoritative: KO is the only assignee. This
        # also prevents a multi-assignee request from creating duplicate
        # CONTROL rows through the per-assignee creation branches below.
        ko_user_id = parse_ko_user_id(payload.internal_notes)
        if ko_user_id is None:
            assignee_ids = []
            assignee_users = []
            assignee_dept_map = {}
        else:
            ko_user = (
                await db.execute(select(User).where(User.id == ko_user_id, User.is_active.is_(True)))
            ).scalar_one()
            assignee_ids = [ko_user_id]
            assignee_users = [ko_user]
            assignee_dept_map = {ko_user_id: ko_user.department_id}
            await ensure_daily_baselines_for_departments(
                db=db,
                department_ids={project.department_id, ko_user.department_id} if project else {ko_user.department_id},
                day=datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date(),
                actor=user,
            )

    if _should_auto_status_from_product_counts(project, phase_value):
        total, completed = _extract_total_and_completed(payload.daily_products, payload.internal_notes)
        auto_status = _compute_status_from_completed(total, completed)
        if auto_status is not None:
            status_value = auto_status

    completed_at = payload.completed_at
    if status_value == TaskStatus.DONE:
        completed_at = completed_at or datetime.now(timezone.utc)
    else:
        completed_at = None

    start_date_value = payload.start_date or datetime.now(timezone.utc)
    due_date_value = payload.due_date
    original_due_date_value = None
    if completed_at is not None and _enum_value(status_value) == TaskStatus.DONE.value:
        original_due_date_value = due_date_value
        due_date_value = _due_date_on_done_day(due_date_value, completed_at)
        if original_due_date_value == due_date_value:
            original_due_date_value = None
        if _as_local_date(start_date_value) > _as_local_date(completed_at):
            start_date_value = completed_at
    if payload.fast_task_order is not None and not is_fast:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fast task order can only be set for fast tasks",
        )
    fast_task_order_value = payload.fast_task_order if is_fast else None

    # GA-origin tasks always use one independent row per assignee. Development
    # project tasks already use the same storage model.
    if project is not None and assignee_ids is not None and len(assignee_ids) > 1:
        if (
            is_development_project
            or payload.ga_note_origin_id is not None
            or payload.plan_note_origin_id is not None
        ):
            created_tasks: list[Task] = []
            created_notifications: list[Notification] = []

            ordered_assignee_ids = list(assignee_ids)
            if payload.assigned_to in ordered_assignee_ids:
                ordered_assignee_ids.remove(payload.assigned_to)  # type: ignore[arg-type]
                ordered_assignee_ids.insert(0, payload.assigned_to)  # type: ignore[arg-type]

            for assignee_id in ordered_assignee_ids:
                task_department_id = assignee_dept_map.get(assignee_id) or project.department_id
                t = Task(
                    title=payload.title,
                    description=payload.description,
                    internal_notes=payload.internal_notes,
                    skill_category=payload.skill_category,
                    project_id=payload.project_id,
                    dependency_task_id=dependency_task_id,
                    department_id=task_department_id,
                    assigned_to=assignee_id,
                    confirmation_assignee_id=confirmation_assignee_id,
                    created_by=user.id,
                    ga_note_origin_id=payload.ga_note_origin_id,
                    plan_note_origin_id=payload.plan_note_origin_id,
                    fast_task_group_id=None,
                    status=status_value,
                    priority=priority_value,
                    finish_period=payload.finish_period,
                    phase=phase_value,
                    progress_percentage=payload.progress_percentage or 0,
                    daily_products=payload.daily_products,
                    start_date=start_date_value,
                    due_date=due_date_value,
                    original_due_date=original_due_date_value,
                    completed_at=completed_at,
                    is_deadline_important=payload.is_deadline_important or False,
                    is_bllok=payload.is_bllok or False,
                    is_1h_report=payload.is_1h_report or False,
                    one_h_report_slot=payload.one_h_report_slot if (payload.is_1h_report or payload.is_r1) else None,
                    one_h_marker=payload.one_h_marker,
                    one_h_marker_date=current_effective_marker_date() if payload.one_h_marker else None,
                    one_h_marker_by_ga=bool(payload.one_h_marker and marker_is_by_ga(user.email)),
                    one_h_marker_comment=normalize_marker_comment(payload.one_h_marker, payload.one_h_marker_comment),
                    is_r1=payload.is_r1 or False,
                    is_personal=payload.is_personal or False,
                    fast_task_order=fast_task_order_value,
                )
                db.add(t)
                await db.flush()
                await _replace_task_assignees(db, t, [assignee_id])
                await _sync_control_task_owner_from_ko(db, task=t, project=project)

                if payload.alignment_user_ids:
                    seen_align: set[uuid.UUID] = set()
                    ids = [
                        uid
                        for uid in payload.alignment_user_ids
                        if not (uid in seen_align or seen_align.add(uid))
                    ]
                    await db.execute(
                        insert(TaskAlignmentUser),
                        [{"task_id": t.id, "user_id": uid} for uid in ids],
                    )

                await _clear_task_planner_exclusions_for_current_plan(
                    db,
                    task=t,
                    user_ids=[assignee_id],
                )

                created_tasks.append(t)
                created_notifications.append(
                    add_notification(
                        db=db,
                        user_id=assignee_id,
                        type=NotificationType.assignment,
                        title="Task assigned",
                        body=notification_task_preview(t.title),
                        data={"task_id": str(t.id)},
                    )
                )

                add_audit_log(
                    db=db,
                    actor_user_id=user.id,
                    entity_type="task",
                    entity_id=t.id,
                    action="created",
                    before=None,
                    after={
                        "title": t.title,
                        "status": _enum_value(t.status),
                        "assigned_to": str(t.assigned_to) if t.assigned_to else None,
                    },
                )

            await record_initial_marker_comments(db, created_tasks, actor_email=user.email)
            if before_commit is not None:
                before_commit(created_tasks[0])
            await db.commit()

            for n in created_notifications:
                try:
                    await publish_notification(user_id=n.user_id, notification=n)
                except Exception:
                    pass

            first = created_tasks[0]
            await db.refresh(first)
            assignee_map = await _assignees_for_tasks(db, [first.id])
            dto_assignees = assignee_map.get(first.id, [])
            dto = _task_to_out(first, dto_assignees or [])
            dto.alignment_user_ids = payload.alignment_user_ids
            return dto

    # MST Graphic Design cross-department project tasks: create per-assignee copies.
    if project is not None and assignee_ids is not None and len(assignee_ids) > 1:
        if is_mst_project(project):
            project_department = None
            if project.department_id is not None:
                project_department = (
                    await db.execute(select(Department).where(Department.id == project.department_id))
                ).scalar_one_or_none()
            is_graphic_design = False
            if project_department is not None:
                dept_name = (project_department.name or "").strip().upper()
                dept_code = (project_department.code or "").strip().upper()
                if dept_name == "GRAPHIC DESIGN" or dept_code in ("GD", "GDS"):
                    is_graphic_design = True

            if is_graphic_design:
                normalized_dept_ids: set[uuid.UUID | None] = set()
                for assignee_id in assignee_ids:
                    normalized_dept_ids.add(assignee_dept_map.get(assignee_id) or project.department_id)
                unique_dept_ids = {dept_id for dept_id in normalized_dept_ids if dept_id is not None}

                if len(unique_dept_ids) > 1:
                    created_tasks: list[Task] = []
                    created_notifications: list[Notification] = []

                    ordered_assignee_ids = list(assignee_ids)
                    if payload.assigned_to in ordered_assignee_ids:
                        ordered_assignee_ids.remove(payload.assigned_to)  # type: ignore[arg-type]
                        ordered_assignee_ids.insert(0, payload.assigned_to)  # type: ignore[arg-type]

                    for assignee_id in ordered_assignee_ids:
                        task_department_id = assignee_dept_map.get(assignee_id) or project.department_id
                        t = Task(
                            title=payload.title,
                            description=payload.description,
                            internal_notes=payload.internal_notes,
                            skill_category=payload.skill_category,
                            project_id=payload.project_id,
                            dependency_task_id=dependency_task_id,
                            department_id=task_department_id,
                            assigned_to=assignee_id,
                            confirmation_assignee_id=confirmation_assignee_id,
                            created_by=user.id,
                            ga_note_origin_id=payload.ga_note_origin_id,
                            plan_note_origin_id=payload.plan_note_origin_id,
                            fast_task_group_id=None,
                            status=status_value,
                            priority=priority_value,
                            finish_period=payload.finish_period,
                            phase=phase_value,
                            progress_percentage=payload.progress_percentage or 0,
                            daily_products=payload.daily_products,
                            start_date=start_date_value,
                            due_date=due_date_value,
                            original_due_date=original_due_date_value,
                            completed_at=completed_at,
                            is_deadline_important=payload.is_deadline_important or False,
                            is_bllok=payload.is_bllok or False,
                            is_1h_report=payload.is_1h_report or False,
                            one_h_report_slot=payload.one_h_report_slot if (payload.is_1h_report or payload.is_r1) else None,
                            one_h_marker=payload.one_h_marker,
                            one_h_marker_date=current_effective_marker_date() if payload.one_h_marker else None,
                            one_h_marker_by_ga=bool(payload.one_h_marker and marker_is_by_ga(user.email)),
                            one_h_marker_comment=normalize_marker_comment(payload.one_h_marker, payload.one_h_marker_comment),
                            is_r1=payload.is_r1 or False,
                            is_personal=payload.is_personal or False,
                            fast_task_order=fast_task_order_value,
                        )
                        db.add(t)
                        await db.flush()
                        await _replace_task_assignees(db, t, [assignee_id])
                        await _sync_control_task_owner_from_ko(db, task=t, project=project)

                        if payload.alignment_user_ids:
                            seen_align: set[uuid.UUID] = set()
                            ids = [uid for uid in payload.alignment_user_ids if not (uid in seen_align or seen_align.add(uid))]
                            await db.execute(
                                insert(TaskAlignmentUser),
                                [{"task_id": t.id, "user_id": uid} for uid in ids],
                            )

                        # Clear weekly planner exclusions so the task is visible for this assignee.
                        await _clear_task_planner_exclusions_for_current_plan(
                            db,
                            task=t,
                            user_ids=[assignee_id],
                        )

                        created_tasks.append(t)
                        created_notifications.append(
                            add_notification(
                                db=db,
                                user_id=assignee_id,
                                type=NotificationType.assignment,
                                title="Task assigned",
                                body=notification_task_preview(t.title),
                                data={"task_id": str(t.id)},
                            )
                        )

                        add_audit_log(
                            db=db,
                            actor_user_id=user.id,
                            entity_type="task",
                            entity_id=t.id,
                            action="created",
                            before=None,
                            after={
                                "title": t.title,
                                "status": _enum_value(t.status),
                                "assigned_to": str(t.assigned_to) if t.assigned_to else None,
                            },
                        )

                    await record_initial_marker_comments(db, created_tasks, actor_email=user.email)
                    if before_commit is not None:
                        before_commit(created_tasks[0])
                    await db.commit()

                    for n in created_notifications:
                        try:
                            await publish_notification(user_id=n.user_id, notification=n)
                        except Exception:
                            pass

                    first = created_tasks[0]
                    await db.refresh(first)
                    assignee_map = await _assignees_for_tasks(db, [first.id])
                    dto_assignees = assignee_map.get(first.id, [])
                    dto = _task_to_out(first, dto_assignees or [])
                    dto.alignment_user_ids = payload.alignment_user_ids
                    return dto

    # GA / plan note standalone multi-assignee: create per-user copies (no fast_task_group_id).
    if (
        (payload.ga_note_origin_id is not None or payload.plan_note_origin_id is not None)
        and payload.project_id is None
        and is_fast
        and assignee_ids is not None
        and len(assignee_ids) > 1
    ):
        created_tasks: list[Task] = []
        created_notifications: list[Notification] = []

        ordered_assignee_ids = list(assignee_ids)
        if payload.assigned_to in ordered_assignee_ids:
            ordered_assignee_ids.remove(payload.assigned_to)  # type: ignore[arg-type]
            ordered_assignee_ids.insert(0, payload.assigned_to)  # type: ignore[arg-type]

        for assignee_id in ordered_assignee_ids:
            task_department_id = assignee_dept_map.get(assignee_id) or department_id
            t = Task(
                title=payload.title,
                description=payload.description,
                internal_notes=payload.internal_notes,
                skill_category=payload.skill_category,
                project_id=payload.project_id,
                dependency_task_id=dependency_task_id,
                department_id=task_department_id,
                assigned_to=assignee_id,
                confirmation_assignee_id=confirmation_assignee_id,
                created_by=user.id,
                ga_note_origin_id=payload.ga_note_origin_id,
                plan_note_origin_id=payload.plan_note_origin_id,
                fast_task_group_id=None,
                status=status_value,
                priority=priority_value,
                finish_period=payload.finish_period,
                phase=phase_value,
                progress_percentage=payload.progress_percentage or 0,
                daily_products=payload.daily_products,
                start_date=start_date_value,
                due_date=due_date_value,
                original_due_date=original_due_date_value,
                completed_at=completed_at,
                is_deadline_important=payload.is_deadline_important or False,
                is_bllok=payload.is_bllok or False,
                is_1h_report=payload.is_1h_report or False,
                one_h_report_slot=payload.one_h_report_slot if (payload.is_1h_report or payload.is_r1) else None,
                one_h_marker=payload.one_h_marker,
                one_h_marker_date=current_effective_marker_date() if payload.one_h_marker else None,
                one_h_marker_by_ga=bool(payload.one_h_marker and marker_is_by_ga(user.email)),
                one_h_marker_comment=normalize_marker_comment(payload.one_h_marker, payload.one_h_marker_comment),
                is_r1=payload.is_r1 or False,
                is_personal=payload.is_personal or False,
                fast_task_order=fast_task_order_value,
            )
            db.add(t)
            await db.flush()
            await _replace_task_assignees(db, t, [assignee_id])
            await _sync_control_task_owner_from_ko(db, task=t, project=project)

            if payload.alignment_user_ids:
                seen_align: set[uuid.UUID] = set()
                ids = [uid for uid in payload.alignment_user_ids if not (uid in seen_align or seen_align.add(uid))]
                await db.execute(
                    insert(TaskAlignmentUser),
                    [{"task_id": t.id, "user_id": uid} for uid in ids],
                )

            created_tasks.append(t)
            created_notifications.append(
                add_notification(
                    db=db,
                    user_id=assignee_id,
                    type=NotificationType.assignment,
                    title="Task assigned",
                    body=notification_task_preview(t.title),
                    data={"task_id": str(t.id)},
                )
            )

            add_audit_log(
                db=db,
                actor_user_id=user.id,
                entity_type="task",
                entity_id=t.id,
                action="created",
                before=None,
                after={
                    "title": t.title,
                    "status": _enum_value(t.status),
                    "assigned_to": str(t.assigned_to) if t.assigned_to else None,
                },
            )

        await record_initial_marker_comments(db, created_tasks, actor_email=user.email)
        if before_commit is not None:
            before_commit(created_tasks[0])
        await db.commit()

        for n in created_notifications:
            try:
                await publish_notification(user_id=n.user_id, notification=n)
            except Exception:
                pass

        first = created_tasks[0]
        await db.refresh(first)
        assignee_map = await _assignees_for_tasks(db, [first.id])
        dto_assignees = assignee_map.get(first.id, [])
        dto = _task_to_out(first, dto_assignees or [])
        dto.alignment_user_ids = payload.alignment_user_ids
        return dto

    # Standalone task multi-assignee: create per-user copies tied by fast_task_group_id.
    if is_fast and assignee_ids is not None and len(assignee_ids) > 1:
        fast_task_group_id = uuid.uuid4()
        created_tasks: list[Task] = []
        created_notifications: list[Notification] = []

        # Keep deterministic ordering: prefer payload.assigned_to first if provided.
        ordered_assignee_ids = list(assignee_ids)
        if payload.assigned_to in ordered_assignee_ids:
            ordered_assignee_ids.remove(payload.assigned_to)  # type: ignore[arg-type]
            ordered_assignee_ids.insert(0, payload.assigned_to)  # type: ignore[arg-type]

        for assignee_id in ordered_assignee_ids:
            task_department_id = assignee_dept_map.get(assignee_id) or department_id
            t = Task(
                title=payload.title,
                description=payload.description,
                internal_notes=payload.internal_notes,
                skill_category=payload.skill_category,
                project_id=payload.project_id,
                dependency_task_id=dependency_task_id,
                department_id=task_department_id,
                assigned_to=assignee_id,
                confirmation_assignee_id=confirmation_assignee_id,
                created_by=user.id,
                ga_note_origin_id=payload.ga_note_origin_id,
                plan_note_origin_id=payload.plan_note_origin_id,
                fast_task_group_id=fast_task_group_id,
                status=status_value,
                priority=priority_value,
                finish_period=payload.finish_period,
                phase=phase_value,
                progress_percentage=payload.progress_percentage or 0,
                daily_products=payload.daily_products,
                start_date=start_date_value,
                due_date=due_date_value,
                original_due_date=original_due_date_value,
                completed_at=completed_at,
                is_deadline_important=payload.is_deadline_important or False,
                is_bllok=payload.is_bllok or False,
                is_1h_report=payload.is_1h_report or False,
                one_h_report_slot=payload.one_h_report_slot if (payload.is_1h_report or payload.is_r1) else None,
                one_h_marker=payload.one_h_marker,
                one_h_marker_date=current_effective_marker_date() if payload.one_h_marker else None,
                one_h_marker_by_ga=bool(payload.one_h_marker and marker_is_by_ga(user.email)),
                one_h_marker_comment=normalize_marker_comment(payload.one_h_marker, payload.one_h_marker_comment),
                is_r1=payload.is_r1 or False,
                is_personal=payload.is_personal or False,
                fast_task_order=fast_task_order_value,
            )
            db.add(t)
            await db.flush()
            await _replace_task_assignees(db, t, [assignee_id])

            # Optional: store alignment users for this task (fast-task alignment).
            if payload.alignment_user_ids:
                seen_align: set[uuid.UUID] = set()
                ids = [uid for uid in payload.alignment_user_ids if not (uid in seen_align or seen_align.add(uid))]
                await db.execute(
                    insert(TaskAlignmentUser),
                    [{"task_id": t.id, "user_id": uid} for uid in ids],
                )

            created_tasks.append(t)
            created_notifications.append(
                add_notification(
                    db=db,
                    user_id=assignee_id,
                    type=NotificationType.assignment,
                    title="Task assigned",
                    body=notification_task_preview(t.title),
                    data={"task_id": str(t.id)},
                )
            )

            add_audit_log(
                db=db,
                actor_user_id=user.id,
                entity_type="task",
                entity_id=t.id,
                action="created",
                before=None,
                after={
                    "title": t.title,
                    "status": _enum_value(t.status),
                    "assigned_to": str(t.assigned_to) if t.assigned_to else None,
                },
            )

        await record_initial_marker_comments(db, created_tasks, actor_email=user.email)
        if before_commit is not None:
            before_commit(created_tasks[0])
        await db.commit()

        for n in created_notifications:
            try:
                await publish_notification(user_id=n.user_id, notification=n)
            except Exception:
                pass

        # Return the first created task; clients typically refetch lists.
        first = created_tasks[0]
        await db.refresh(first)
        group_assignees = await _assignees_for_fast_task_groups(db, [fast_task_group_id])
        dto = _task_to_out(first, group_assignees.get(fast_task_group_id, []))
        dto.alignment_user_ids = payload.alignment_user_ids
        return dto

    fast_task_group_id = (
        uuid.uuid4()
        if is_fast and payload.ga_note_origin_id is None and payload.plan_note_origin_id is None
        else None
    )

    assigned_to_value = assignee_ids[0] if assignee_ids else None
    task_department_id = department_id
    if is_fast and assigned_to_value is not None:
        task_department_id = assignee_dept_map.get(assigned_to_value) or department_id

    task = Task(
        title=_pcm_control_title(payload.title) if pcm_control_origin is not None else payload.title,
        description=payload.description,
        internal_notes=payload.internal_notes,
        skill_category=payload.skill_category,
        project_id=payload.project_id,
        dependency_task_id=dependency_task_id,
        department_id=task_department_id,
        assigned_to=assigned_to_value,
        confirmation_assignee_id=confirmation_assignee_id,
        created_by=user.id,
        ga_note_origin_id=payload.ga_note_origin_id,
        plan_note_origin_id=payload.plan_note_origin_id,
        fast_task_group_id=fast_task_group_id,
        status=status_value,
        priority=priority_value,
        finish_period=payload.finish_period,
        phase=phase_value,
        progress_percentage=payload.progress_percentage or 0,
        daily_products=payload.daily_products,
        start_date=start_date_value,
        due_date=due_date_value,
        original_due_date=original_due_date_value,
        completed_at=completed_at,
        is_deadline_important=payload.is_deadline_important or False,
        is_bllok=payload.is_bllok or False,
        is_1h_report=payload.is_1h_report or False,
        one_h_report_slot=payload.one_h_report_slot if (payload.is_1h_report or payload.is_r1) else None,
        one_h_marker=payload.one_h_marker,
        one_h_marker_date=current_effective_marker_date() if payload.one_h_marker else None,
        one_h_marker_by_ga=bool(payload.one_h_marker and marker_is_by_ga(user.email)),
        one_h_marker_comment=normalize_marker_comment(payload.one_h_marker, payload.one_h_marker_comment),
        is_r1=payload.is_r1 or False,
        is_personal=payload.is_personal or False,
        fast_task_order=fast_task_order_value,
    )
    db.add(task)
    await db.flush()

    # Record per-day progress event for product-count driven project tasks.
    # This is per-day history; it does not retroactively change other days.
    if _should_auto_status_from_product_counts(project, phase_value):
        total, completed = _extract_total_and_completed(task.daily_products, task.internal_notes)
        if total is not None and total > 0 and completed > 0:
            today = _realization_today()
            await upsert_task_daily_progress(
                db,
                task_id=task.id,
                day_date=today,
                old_completed=0,
                new_completed=completed,
                total=total,
                finish_period=_daily_progress_finish_period_value(task.finish_period),
            )

    # Optional: store alignment users for this task (fast-task alignment).
    if payload.alignment_user_ids:
        seen: set[uuid.UUID] = set()
        ids = [uid for uid in payload.alignment_user_ids if not (uid in seen or seen.add(uid))]
        await db.execute(
            insert(TaskAlignmentUser),
            [{"task_id": task.id, "user_id": uid} for uid in ids],
        )
    if assignee_ids is not None:
        await _replace_task_assignees(db, task, assignee_ids)
        if assignee_ids == [] and task.system_template_origin_id and task.department_id is not None:
            task.is_active = False
    await _sync_control_task_owner_from_ko(db, task=task, project=project)
    await _create_pcm_control_for_product(db, product_task=task, project=project)

    # If this is a project task, and the project was previously removed from the weekly planner
    # for this user/day/slot, auto-clear that exclusion so the newly created task is visible.
    if task.project_id is not None and assignee_ids:
        await _clear_task_planner_exclusions_for_current_plan(
            db,
            task=task,
            user_ids=assignee_ids,
        )

    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="task",
        entity_id=task.id,
        action="created",
        before=None,
        after={
            "title": task.title,
            "status": _enum_value(task.status),
            "assigned_to": str(task.assigned_to) if task.assigned_to else None,
        },
    )
    if status_value == TaskStatus.DONE and payload.completion_override_reason:
        add_audit_log(
            db=db,
            actor_user_id=user.id,
            entity_type="task",
            entity_id=task.id,
            action="rlz_completion_comment_overridden",
            before=None,
            after={
                "status": TaskStatus.DONE.value,
                "reason": payload.completion_override_reason.strip(),
            },
        )

    created_notifications: list[Notification] = []
    existing_assignee_ids: set[uuid.UUID] = set()
    if payload.assignees is not None or payload.assigned_to is not None:
        rows = (
            await db.execute(
                select(TaskAssignee.user_id).where(TaskAssignee.task_id == task.id)
            )
        ).scalars().all()
        existing_assignee_ids = set(rows)
    for assignee in assignee_users:
        created_notifications.append(
            add_notification(
                db=db,
                user_id=assignee.id,
                type=NotificationType.assignment,
                title="Task assigned",
                body=notification_task_preview(task.title),
                data={"task_id": str(task.id)},
            )
        )

    mentions = _extract_mentions(task.title) | _extract_mentions(task.description)
    if mentions:
        mentioned_users = await _users_by_usernames(db, mentions)
        for mu in mentioned_users:
            if mu.id == user.id:
                continue
            created_notifications.append(
                add_notification(
                    db=db,
                    user_id=mu.id,
                    type=NotificationType.mention,
                    title="Mentioned in task",
                    body=notification_task_preview(task.title),
                    data={"task_id": str(task.id)},
                )
            )

    await record_initial_marker_comments(db, [task], actor_email=user.email)
    if before_commit is not None:
        before_commit(task)
    await db.commit()

    for n in created_notifications:
        try:
            await publish_notification(user_id=n.user_id, notification=n)
        except Exception:
            pass

    await db.refresh(task)
    assignee_map = await _assignees_for_tasks(db, [task.id])
    dto_assignees = assignee_map.get(task.id, [])
    if _uses_fast_task_group(task):
        group_map = await _assignees_for_fast_task_groups(db, [task.fast_task_group_id])
        dto_assignees = group_map.get(task.fast_task_group_id, dto_assignees)
    dto = _task_to_out(task, dto_assignees or [])
    dto.alignment_user_ids = payload.alignment_user_ids
    return dto


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> TaskOut:
    return await update_task_in_session(task_id, payload, db, user)


async def update_task_in_session(task_id: uuid.UUID, payload: TaskUpdate, db: AsyncSession, user,
                                 *, before_update=None, before_commit=None, return_dto=True) -> TaskOut | Task:
    """Internal hooks allow a reviewed proposal and the normal task edit to commit together."""
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if payload.title is not None:
        payload.title = _normalize_email_task_title(
            payload.title,
            is_system_task=(task.system_template_origin_id is not None or task.system_task_slot_id is not None),
        )
    is_assigned_to_task = await _is_user_assigned_to_task(db, task, user.id)

    ensure_task_editor(user, task)

    postponement = await check_task_postponement_explanation(
        db,
        task=task,
        updates={field: getattr(payload, field) for field in ("start_date", "due_date") if _payload_has_field(payload, field)},
        reason_code=payload.postponement_reason_code, comment=payload.postponement_comment,
    )

    prepared_date_departments = None
    if any(_payload_has_field(payload, field) for field in ("start_date", "due_date")):
        # Baselines must precede task row locks, as in the other mutation routes.
        # Then reload locked dates so a concurrent edit cannot bypass the rule.
        owner_ids = set((await db.execute(select(TaskAssignee.user_id).where(TaskAssignee.task_id == task.id))).scalars().all())
        owner_ids.update(payload.assignees or [])
        owner_ids.update(value for value in (task.assigned_to, payload.assigned_to) if value)
        department_ids = {task.department_id, payload.department_id}
        if owner_ids:
            department_ids.update((await db.execute(select(User.department_id).where(User.id.in_(owner_ids)))).scalars().all())
        await ensure_daily_baselines_for_departments(
            db=db, department_ids=department_ids, day=_realization_today(), actor=user,
        )
        prepared_date_departments = department_ids
        group_id = select(Task.fast_task_group_id).where(Task.id == task_id).correlate(None).scalar_subquery()
        locked = (await db.execute(select(Task).where(or_(Task.id == task_id, Task.fast_task_group_id == group_id))
            .order_by(Task.id).with_for_update().execution_options(populate_existing=True))).scalars().all()
        task = next((item for item in locked if item.id == task_id), None)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
        ensure_task_editor(user, task)
        postponement = await check_task_postponement_explanation(
            db,
            task=task,
            updates={field: getattr(payload, field) for field in ("start_date", "due_date") if _payload_has_field(payload, field)},
            reason_code=payload.postponement_reason_code, comment=payload.postponement_comment,
        )

    if before_update is not None:
        await before_update(task)

    question_status_requested = payload.status if task.question_origin_id is not None else None
    question_status_override: TaskStatus | None = None
    if question_status_requested is not None and not is_assigned_to_task:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Each assignee must update their own question task status",
        )

    if task.ga_note_origin_id is not None or task.plan_note_origin_id is not None:
        normalized_status = _normalize_ga_note_task_status(task.status)
        current_status = task.status.value if isinstance(task.status, TaskStatus) else str(task.status).strip()
        if current_status != normalized_status.value:
            task.status = normalized_status

    if (
        (task.ga_note_origin_id is not None or task.plan_note_origin_id is not None)
        and payload.status is not None
        and payload.status.value not in _GA_NOTE_VALID_STATUSES
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Note task status must be TODO, IN_PROGRESS, or DONE",
        )

    # Prevent DB constraint failures when updating legacy/system tasks.
    await _ensure_system_task_instance_integrity(db, task)
    
    # For system task status updates, allow admins and managers to bypass department check
    is_system_task_status_update = (
        (task.system_template_origin_id is not None or task.system_task_slot_id is not None)
        and payload.status is not None
        and user.role in (UserRole.ADMIN, UserRole.MANAGER)
    )
    # Department access check removed since can_edit above already verified
    # that user is admin, manager, creator, assignee, or same-department member

    if payload.status is not None and (task.system_template_origin_id is not None or task.system_task_slot_id is not None):
        if is_assigned_to_task:
            pass
        elif user.role in (UserRole.ADMIN, UserRole.MANAGER):
            # Allow admins and managers to update system task status
            pass
        else:
            status_assignment = (
                await db.execute(
                    select(TaskAssignee)
                    .where(TaskAssignee.task_id == task.id, TaskAssignee.user_id == user.id)
                )
            ).scalar_one_or_none()
            if status_assignment is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    # Forbidden fields check removed to allow staff full update access

    before = {
        "title": task.title,
        "description": task.description,
        "internal_notes": task.internal_notes,
        "dependency_task_id": str(task.dependency_task_id) if task.dependency_task_id else None,
        "status": _enum_value(task.status),
        "priority": _enum_value(task.priority),
        "finish_period": _enum_value(task.finish_period),
        "phase": _enum_value(task.phase),
        "assigned_to": str(task.assigned_to) if task.assigned_to else None,
        "confirmation_assignee_id": str(task.confirmation_assignee_id) if task.confirmation_assignee_id else None,
        "progress_percentage": task.progress_percentage,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "start_date": task.start_date.isoformat() if task.start_date else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "is_active": task.is_active,
        "is_deadline_important": task.is_deadline_important,
    }
    old_assignee_ids = set((await db.execute(
        select(TaskAssignee.user_id).where(TaskAssignee.task_id == task.id)
    )).scalars().all())
    if task.assigned_to:
        old_assignee_ids.add(task.assigned_to)
    requested_assignee_ids = set(payload.assignees or [])
    if _payload_has_field(payload, "assigned_to") and payload.assigned_to:
        requested_assignee_ids.add(payload.assigned_to)
    affected_user_ids = old_assignee_ids | requested_assignee_ids
    affected_departments = {task.department_id}
    if affected_user_ids:
        affected_departments.update((await db.execute(
            select(User.department_id).where(User.id.in_(affected_user_ids))
        )).scalars().all())
    if prepared_date_departments is None:
        await ensure_daily_baselines_for_departments(
            db=db,
            department_ids=affected_departments,
            day=datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date(),
            actor=user,
        )
    elif not affected_departments.issubset(prepared_date_departments):
        raise HTTPException(status_code=409, detail="Përgjegjësi i detyrës ndryshoi. Rifresko dhe provo përsëri.")

    # Snapshot completion values before update for MST/TT daily progress logging.
    old_total, old_completed = _extract_total_and_completed(task.daily_products, task.internal_notes)
    old_start_day = _as_local_date(task.start_date)
    old_due_day = _as_local_date(task.due_date)

    if question_status_requested is not None:
        if question_status_requested == TaskStatus.DONE:
            await _require_rlz_completion_comment(
                db,
                task=task,
                user=user,
                actor_is_assignee=True,
                override_reason=payload.completion_override_reason,
            )
        question_status_override = await _set_question_task_user_completion(
            db,
            task=task,
            user=user,
            is_done=question_status_requested == TaskStatus.DONE,
        )
        payload = payload.model_copy(update={"status": None, "completed_at": None})

    # Track if status was explicitly set in payload to prevent auto-status from overriding it
    status_was_explicitly_set = payload.status is not None
    start_date_set = _payload_has_field(payload, "start_date")
    due_date_set = _payload_has_field(payload, "due_date")
    finish_period_set = _payload_has_field(payload, "finish_period")
    one_h_marker_set = _payload_has_field(payload, "one_h_marker")
    effective_start_date = _as_utc_datetime(payload.start_date) if start_date_set else _as_utc_datetime(task.start_date)
    effective_due_date = _as_utc_datetime(payload.due_date) if due_date_set else _as_utc_datetime(task.due_date)
    if (
        effective_start_date is not None
        and effective_due_date is not None
        and effective_start_date > effective_due_date
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start date cannot be after due date",
        )
    progress_finish_period = _daily_progress_finish_period_value(
        payload.finish_period if finish_period_set else task.finish_period
    )

    created_notifications: list[Notification] = []
    assignee_users: list[User] = []
    # Allow cross-department for projects, GA notes, or fast tasks (tasks without project_id)
    # This matches the logic in create_task endpoint
    allow_cross_department = (
        task.project_id is not None or task.ga_note_origin_id is not None or task.plan_note_origin_id is not None or task.project_id is None
    )

    # Fast tasks are stored as per-user copies tied by fast_task_group_id.
    # For older rows, initialize the group id lazily on first update.
    if (
        is_fast_task_model(task)
        and task.ga_note_origin_id is None
        and task.plan_note_origin_id is None
        and task.fast_task_group_id is None
    ):
        task.fast_task_group_id = task.id
    is_fast_group_task = _uses_fast_task_group(task)
    fast_group_desired_assignee_ids: list[uuid.UUID] | None = None
    fast_group_semantic_tasks: list[Task] = []
    fast_group_semantic_before: dict[uuid.UUID, dict] = {}
    fast_group_postponements: dict[uuid.UUID, dict] = {}
    if is_fast_group_task and task.fast_task_group_id is not None:
        fast_group_semantic_tasks = (
            await db.execute(
                select(Task)
                .where(Task.fast_task_group_id == task.fast_task_group_id)
                .where(Task.is_active.is_(True))
                .with_for_update()
            )
        ).scalars().all()
        fast_group_semantic_before = {
            group_task.id: task_semantic_state(group_task)
            for group_task in fast_group_semantic_tasks
        }
        for group_task in fast_group_semantic_tasks:
            fast_group_postponements[group_task.id] = await check_task_postponement_explanation(
                db,
                task=group_task,
                updates={field: getattr(payload, field) for field in ("start_date", "due_date") if _payload_has_field(payload, field)},
                reason_code=payload.postponement_reason_code, comment=payload.postponement_comment,
            )

    if payload.title is not None:
        task.title = payload.title
    description_set = _payload_has_field(payload, "description")
    internal_notes_set = _payload_has_field(payload, "internal_notes")
    if description_set:
        task.description = payload.description
    if internal_notes_set:
        task.internal_notes = payload.internal_notes
    if _payload_has_field(payload, "skill_category"):
        task.skill_category = payload.skill_category
    dependency_set = _payload_has_field(payload, "dependency_task_id")

    if dependency_set:
        if payload.dependency_task_id is None:
            task.dependency_task_id = None
        else:
            dependency_task = (
                await db.execute(select(Task).where(Task.id == payload.dependency_task_id))
            ).scalar_one_or_none()
            if dependency_task is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dependency task not found")
            if task.project_id is None or dependency_task.project_id != task.project_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dependency must be in the same project")
            task.dependency_task_id = payload.dependency_task_id

    if payload.project_id is not None:
        project = await _project_for_id(db, payload.project_id)
        if task.department_id != project.department_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project department mismatch")
        task.project_id = payload.project_id

    if payload.department_id is not None and payload.department_id != task.department_id:
        task.department_id = payload.department_id

    # A non-null confirmer in the parsed payload is authoritative even if the
    # runtime's Pydantic field-set metadata is unavailable or incomplete.  The
    # latter was causing WAITING_CONFIRMATION updates to validate against the
    # task's old null value even though the browser submitted a selected user.
    # Keep the metadata check so an explicit null can still clear the field.
    confirmation_set = _confirmation_assignee_was_provided(payload)
    previous_confirmation_assignee_id = task.confirmation_assignee_id
    if confirmation_set:
        if payload.confirmation_assignee_id is not None:
            confirmation_user = (
                await db.execute(select(User).where(User.id == payload.confirmation_assignee_id))
            ).scalar_one_or_none()
            if confirmation_user is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Confirmation assignee not found")
        task.confirmation_assignee_id = payload.confirmation_assignee_id

    if (task.ga_note_origin_id is not None or task.plan_note_origin_id is not None) and (
        payload.assignees is not None or _payload_has_field(payload, "assigned_to")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Change note task membership from its source note",
        )

    if task.ga_note_origin_id is not None or task.plan_note_origin_id is not None:
        payload_fields = getattr(payload, "model_fields_set", getattr(payload, "__fields_set__", set()))
        shared_fields = sorted(_GA_NOTE_SHARED_TASK_FIELDS.intersection(payload_fields))
        if shared_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Change shared note task fields from its source note: " + ", ".join(shared_fields),
            )

    if payload.assignees is not None:
        # Fast task group: assignees represent group membership; don't mutate task.assigned_to.
        if is_fast_group_task:
            seen: set[uuid.UUID] = set()
            fast_group_desired_assignee_ids = [
                uid for uid in payload.assignees if not (uid in seen or seen.add(uid))
            ]
            assignee_users = (
                await db.execute(select(User).where(User.id.in_(fast_group_desired_assignee_ids)))
            ).scalars().all()
            if len(assignee_users) != len(fast_group_desired_assignee_ids):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user not found")
            for assignee in assignee_users:
                if not allow_cross_department and assignee.department_id != task.department_id:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user must be in department")
        else:
            # Non-fast tasks: keep existing multi-assignee behavior (single task row).
            rows = (
                await db.execute(
                    select(TaskAssignee.user_id).where(TaskAssignee.task_id == task.id)
                )
            ).scalars().all()
            existing_assignee_ids = set(rows)
            seen: set[uuid.UUID] = set()
            assignee_ids = [uid for uid in payload.assignees if not (uid in seen or seen.add(uid))]
            assignee_users = (
                await db.execute(select(User).where(User.id.in_(assignee_ids)))
            ).scalars().all()
            if len(assignee_users) != len(assignee_ids):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user not found")
            for assignee in assignee_users:
                if not allow_cross_department and assignee.department_id != task.department_id:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user must be in department")
            await _replace_task_assignees(db, task, assignee_ids)
            task.assigned_to = assignee_ids[0] if assignee_ids else None
            if assignee_ids == [] and task.system_template_origin_id and task.department_id is not None:
                task.is_active = False
            new_ids = set(assignee_ids) - existing_assignee_ids
            for assignee in assignee_users:
                if assignee.id not in new_ids:
                    continue
                created_notifications.append(
                    add_notification(
                        db=db,
                        user_id=assignee.id,
                        type=NotificationType.assignment,
                        title="Task assigned",
                        body=notification_task_preview(task.title),
                        data={"task_id": str(task.id)},
                    )
                )
    elif _payload_has_field(payload, "assigned_to") and not is_fast_group_task:
        # Allow task editors to change or clear the primary assignee.
        if payload.assigned_to is None:
            task.assigned_to = None
            await _replace_task_assignees(db, task, [])
            assignee_users = []
        elif payload.assigned_to != task.assigned_to:
            assigned_user = (await db.execute(select(User).where(User.id == payload.assigned_to))).scalar_one_or_none()
            if assigned_user is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user not found")
            if not allow_cross_department and assigned_user.department_id != task.department_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user must be in department")
            task.assigned_to = payload.assigned_to
            await _replace_task_assignees(db, task, [payload.assigned_to])
            assignee_users = [assigned_user]
            created_notifications.append(
                add_notification(
                    db=db,
                    user_id=assigned_user.id,
                    type=NotificationType.assignment,
                    title="Task assigned",
                    body=notification_task_preview(task.title),
                    data={"task_id": str(task.id)},
                )
            )

    current_status_raw = _enum_value(task.status)
    target_status_raw = payload.status.value if payload.status is not None else current_status_raw
    actor_is_assignee_for_completion = await _is_user_assigned_to_task(db, task, user.id)
    completion_override_used = False
    if (
        payload.status == TaskStatus.DONE
        and current_status_raw != TaskStatus.DONE.value
        and _requires_rlz_completion_comment(task)
    ):
        completion_override_used = await _require_rlz_completion_comment(
            db,
            task=task,
            user=user,
            actor_is_assignee=actor_is_assignee_for_completion,
            override_reason=payload.completion_override_reason,
        )
        if completion_override_used:
            add_audit_log(
                db=db,
                actor_user_id=user.id,
                entity_type="task",
                entity_id=task.id,
                action="rlz_completion_comment_overridden",
                before={"status": current_status_raw},
                after={
                    "status": TaskStatus.DONE.value,
                    "reason": payload.completion_override_reason.strip(),
                },
            )
    if payload.status == TaskStatus.WAITING_CONFIRMATION:
        if not _supports_waiting_confirmation(
            task,
            is_bllok=payload.is_bllok,
            is_1h_report=payload.is_1h_report,
            is_r1=payload.is_r1,
            is_personal=payload.is_personal,
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="WAITING_CONFIRMATION is only available for 1H, R1, Personal, Bllok, GA/KA note, or plan-note tasks",
            )
        await _validate_waiting_confirmation_assignee(db, task.confirmation_assignee_id)
    if (
        payload.status == TaskStatus.DONE
        and current_status_raw == TaskStatus.WAITING_CONFIRMATION.value
        and not _can_complete_waiting_confirmation(
            user_role=user.role,
            actor_user_id=user.id,
            confirmation_assignee_id=task.confirmation_assignee_id,
            actor_is_assignee=actor_is_assignee_for_completion,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only confirmation assignee, task assignees, or managers/admins can complete this task",
        )

    if payload.status is not None and payload.status != task.status:
        task.status = payload.status
        if task.status == TaskStatus.DONE:
            task.completed_at = task.completed_at or datetime.now(timezone.utc)
        else:
            task.completed_at = None

        # Record explicit per-day status change for all tasks (not just MST/TT).
        # This powers weekly planner day-by-day colors.
        today = _realization_today()
        await upsert_explicit_task_daily_status(
            db,
            task_id=task.id,
            day_date=today,
            status=task.status,
            finish_period=progress_finish_period,
            finish_period_is_set=finish_period_set,
        )
    elif finish_period_set:
        await sync_task_daily_finish_period(
            db,
            task_id=task.id,
            day_date=_realization_today(),
            finish_period=progress_finish_period,
        )

    if (
        task.status == TaskStatus.WAITING_CONFIRMATION
        and task.confirmation_assignee_id is not None
        and task.confirmation_assignee_id != user.id
        and (
            current_status_raw != TaskStatus.WAITING_CONFIRMATION.value
            or previous_confirmation_assignee_id != task.confirmation_assignee_id
        )
    ):
        created_notifications.append(
            add_notification(
                db=db,
                user_id=task.confirmation_assignee_id,
                type=NotificationType.status_change,
                title="Confirmation requested",
                body=notification_task_preview(task.title),
                data={"task_id": str(task.id), "status": TaskStatus.WAITING_CONFIRMATION.value},
            )
        )
    
    if payload.is_personal is not None:
        task.is_personal = payload.is_personal
    fast_task_order_set = _payload_has_field(payload, "fast_task_order")
    if fast_task_order_set:
        if not is_fast_task_model(task):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Fast task order can only be set for fast tasks",
            )
        task.fast_task_order = payload.fast_task_order
    # Optional: update alignment users if provided
    alignment_set = _payload_has_field(payload, "alignment_user_ids")
    if alignment_set:
        await db.execute(delete(TaskAlignmentUser).where(TaskAlignmentUser.task_id == task.id))
        if payload.alignment_user_ids:
            seen: set[uuid.UUID] = set()
            ids = [uid for uid in payload.alignment_user_ids if not (uid in seen or seen.add(uid))]
            await db.execute(
                insert(TaskAlignmentUser),
                [{"task_id": task.id, "user_id": uid} for uid in ids],
            )

    if payload.priority is not None:
        task.priority = payload.priority
    if finish_period_set:
        task.finish_period = payload.finish_period
    if payload.phase is not None:
        # Allow task editors to change phase (removed manager/admin restriction)
        task.phase = payload.phase
    if payload.progress_percentage is not None:
        task.progress_percentage = payload.progress_percentage
    if payload.daily_products is not None:
        task.daily_products = payload.daily_products
    if start_date_set:
        task.start_date = effective_start_date
    if due_date_set:
        # If due_date is being changed (postponed), preserve the original planned date once.
        if (
            task.due_date is not None
            and payload.due_date is not None
            and payload.due_date != task.due_date
            and task.original_due_date is None
        ):
            task.original_due_date = task.due_date
        task.due_date = effective_due_date
    if start_date_set or due_date_set:
        new_start_day = _as_local_date(task.start_date)
        progress_days: set[date] = set()
        if old_start_day is not None and new_start_day is not None:
            progress_days = set(
                (
                    await db.execute(
                        select(TaskDailyProgress.day_date)
                        .where(TaskDailyProgress.task_id == task.id)
                        .where(TaskDailyProgress.day_date >= old_start_day)
                        .where(TaskDailyProgress.day_date < new_start_day)
                    )
                ).scalars().all()
            )
        days_to_hide = _planner_replan_exclusion_days(
            old_start=old_start_day,
            old_end=old_due_day,
            new_start=new_start_day,
            progress_days=progress_days,
            today=_realization_today(),
        )
        if days_to_hide:
            planner_user_ids = await _task_assignee_ids_for_planner(db, task)
            await _add_task_planner_exclusions(
                db,
                task_id=task.id,
                user_ids=planner_user_ids,
                day_dates=days_to_hide,
                created_by=user.id,
            )
    if (
        payload.assignees is not None
        or _payload_has_field(payload, "assigned_to")
        or payload.project_id is not None
        or start_date_set
        or due_date_set
        or finish_period_set
    ):
        planner_user_ids = (
            fast_group_desired_assignee_ids
            if fast_group_desired_assignee_ids is not None
            else await _task_assignee_ids_for_planner(db, task)
        )
        await _clear_task_planner_exclusions_for_current_plan(
            db,
            task=task,
            user_ids=planner_user_ids,
        )
    if payload.completed_at is not None:
        task.completed_at = payload.completed_at
    _sync_due_date_to_done_day(task)
    if payload.is_deadline_important is not None:
        task.is_deadline_important = payload.is_deadline_important
    if payload.is_bllok is not None:
        task.is_bllok = payload.is_bllok
    if payload.is_1h_report is not None:
        task.is_1h_report = payload.is_1h_report
        if not payload.is_1h_report and not _payload_has_field(payload, "one_h_report_slot"):
            task.one_h_report_slot = None
    if _payload_has_field(payload, "one_h_report_slot"):
        if payload.one_h_report_slot is not None:
            # R1 uses the same report slots without changing the task type to 1H.
            if not task.is_r1 and payload.is_r1 is not True:
                task.is_1h_report = True
            task.one_h_report_slot = payload.one_h_report_slot
        else:
            task.one_h_report_slot = None
    if one_h_marker_set:
        await sync_task_marker(
            db, task, payload.one_h_marker, actor_email=user.email,
            marker_comment=payload.one_h_marker_comment,
        )
    if payload.is_r1 is not None:
        task.is_r1 = payload.is_r1

    if task.is_1h_report or task.is_r1:
        _validate_eight_am_one_h_slot(
            task.title,
            task.one_h_report_slot,
            is_system_task=(task.system_template_origin_id is not None or task.system_task_slot_id is not None),
        )

    project_for_control: Project | None = None
    if task.project_id is not None:
        project_for_control = (
            await db.execute(select(Project).where(Project.id == task.project_id))
        ).scalar_one_or_none()
    await _validate_pcm_control_origin(
        db,
        project=project_for_control,
        phase=task.phase,
        internal_notes=task.internal_notes,
        require_origin=(
            _parse_origin_task_id(before.get("internal_notes")) is not None
            or (
                payload.phase is not None
                and _enum_value(payload.phase) == ProjectPhaseStatus.CONTROL.value
            )
        ),
    )
    await _sync_control_task_owner_from_ko(db, task=task, project=project_for_control)

    # Validate fast task type flags are mutually exclusive (only for fast tasks)
    # Fast tasks: no project_id, no system_template_origin_id
    if task.project_id is None and task.system_template_origin_id is None:
        # Get the final flag values after applying payload updates
        final_is_bllok = payload.is_bllok if payload.is_bllok is not None else task.is_bllok
        final_is_r1 = payload.is_r1 if payload.is_r1 is not None else task.is_r1
        final_is_1h_report = payload.is_1h_report if payload.is_1h_report is not None else task.is_1h_report
        final_is_personal = payload.is_personal if payload.is_personal is not None else task.is_personal
        
        # Count how many type flags are set (GA type uses ga_note_origin_id, plan uses plan_note_origin_id)
        active_flags_count = sum([
            final_is_bllok,
            final_is_r1,
            final_is_1h_report,
            final_is_personal,
        ])
        
        if active_flags_count > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Fast task can only have one type: BLL, R1, 1H, or Personal"
            )

    project_for_product_status: Project | None = None
    if task.project_id is not None:
        project_for_product_status = (
            await db.execute(select(Project).where(Project.id == task.project_id))
        ).scalar_one_or_none()

    # Auto-status for project tasks that are driven by completed/total product counts.
    # Only auto-compute status if status wasn't explicitly set by user.
    if _should_auto_status_from_product_counts(project_for_product_status, task.phase):
        total, completed = _extract_total_and_completed(task.daily_products, task.internal_notes)

        # Only auto-compute status if status wasn't explicitly set in payload.
        # This preserves user's explicit status changes.
        if not status_was_explicitly_set:
            auto_status = _compute_status_from_completed(total, completed)
            if auto_status is not None:
                task.status = auto_status
                if task.status == TaskStatus.DONE:
                    task.completed_at = task.completed_at or datetime.now(timezone.utc)
                    _sync_due_date_to_done_day(task)
                else:
                    task.completed_at = None

        # Per-day progress logging: overdue tasks touch the record for their due_date.
        # Tasks due today, later or without a due date are logged on today, so work
        # done ahead of a deadline is credited to the day it actually happened.
        if total is not None and total > 0:
            made_progress = completed > old_completed
            became_done_today = completed >= total and old_completed < total
            is_already_done = completed >= total
            values_changed = completed != old_completed or total != old_total
            # Update if there's progress, just became done, is already done, or values changed (to keep status accurate).
            if made_progress or became_done_today or is_already_done or values_changed:
                today = _realization_today()
                progress_day: date | None = today
                if task.due_date is not None:
                    due_dt = task.due_date
                    due_day = due_dt.astimezone(timezone.utc).date() if due_dt.tzinfo else due_dt.date()
                    if due_day < today:
                        progress_day = due_day

                if progress_day is not None:
                    # Check if there's an existing TaskDailyProgress for today with explicit status.
                    # If status was explicitly set today, preserve it.
                    explicit_status_for_today: TaskStatus | None = None
                    if status_was_explicitly_set and progress_day == today:
                        # Check if we just set a status for today in the status change block above.
                        existing_today_progress = (
                            await db.execute(
                                select(TaskDailyProgress).where(
                                    TaskDailyProgress.task_id == task.id,
                                    TaskDailyProgress.day_date == today,
                                )
                            )
                        ).scalar_one_or_none()
                        if existing_today_progress and existing_today_progress.daily_status:
                            try:
                                explicit_status_for_today = TaskStatus(existing_today_progress.daily_status)
                            except Exception:
                                explicit_status_for_today = None

                    await upsert_task_daily_progress(
                        db,
                        task_id=task.id,
                        day_date=progress_day,
                        old_completed=old_completed,
                        new_completed=completed,
                        total=total,
                        finish_period=progress_finish_period,
                        explicit_status=explicit_status_for_today,
                    )

    if payload.status is not None and task.assigned_to is not None and task.status == payload.status:
        created_notifications.append(
            add_notification(
                db=db,
                user_id=task.assigned_to,
                type=NotificationType.status_change,
                title="Task status changed",
                body=notification_task_preview(task.title),
                data={"task_id": str(task.id), "status": _enum_value(task.status)},
            )
        )

    mentions = _extract_mentions(payload.title) | _extract_mentions(payload.description)
    if mentions:
        mentioned_users = await _users_by_usernames(db, mentions)
        for mu in mentioned_users:
            if mu.id == user.id:
                continue
            created_notifications.append(
                add_notification(
                    db=db,
                    user_id=mu.id,
                    type=NotificationType.mention,
                    title="Mentioned in task",
                    body=notification_task_preview(task.title),
                    data={"task_id": str(task.id)},
                )
            )

    # Fast task group behavior:
    # - shared edits propagate to all active copies (status remains per-user)
    # - assignees updates manage group membership (add copies / deactivate removed)
    if is_fast_group_task and task.fast_task_group_id is not None:
        shared_values: dict[str, object] = {}
        if payload.title is not None:
            shared_values["title"] = task.title
        if description_set:
            shared_values["description"] = task.description
        if internal_notes_set:
            shared_values["internal_notes"] = task.internal_notes
        if payload.department_id is not None:
            shared_values["department_id"] = task.department_id
        if confirmation_set:
            shared_values["confirmation_assignee_id"] = task.confirmation_assignee_id
        if due_date_set:
            shared_values["due_date"] = task.due_date
        if start_date_set:
            shared_values["start_date"] = task.start_date
        if payload.is_deadline_important is not None:
            shared_values["is_deadline_important"] = task.is_deadline_important
        if payload.priority is not None:
            shared_values["priority"] = task.priority
        if finish_period_set:
            shared_values["finish_period"] = task.finish_period
        if payload.phase is not None:
            shared_values["phase"] = task.phase
        if payload.progress_percentage is not None:
            shared_values["progress_percentage"] = task.progress_percentage
        if payload.daily_products is not None:
            shared_values["daily_products"] = task.daily_products
        if payload.is_bllok is not None:
            shared_values["is_bllok"] = task.is_bllok
        if payload.is_r1 is not None:
            shared_values["is_r1"] = task.is_r1
        if payload.is_1h_report is not None:
            shared_values["is_1h_report"] = task.is_1h_report
        if _payload_has_field(payload, "one_h_report_slot") or payload.is_1h_report is not None:
            shared_values["one_h_report_slot"] = task.one_h_report_slot
        if payload.is_personal is not None:
            shared_values["is_personal"] = task.is_personal
        if fast_task_order_set:
            shared_values["fast_task_order"] = task.fast_task_order

        if shared_values:
            await db.execute(
                update(Task)
                .where(Task.fast_task_group_id == task.fast_task_group_id)
                .where(Task.id != task.id)
                .where(Task.is_active.is_(True))
                .values(**shared_values)
            )

        if fast_group_desired_assignee_ids is not None:
            group_rows = (
                await db.execute(
                    select(Task.id, Task.assigned_to)
                    .where(Task.fast_task_group_id == task.fast_task_group_id)
                    .where(Task.is_active.is_(True))
                )
            ).all()
            current_user_ids = {uid for _, uid in group_rows if uid is not None}
            desired_user_ids = set(fast_group_desired_assignee_ids)

            to_add = sorted(desired_user_ids - current_user_ids)
            to_remove = current_user_ids - desired_user_ids

            if to_remove:
                remove_task_ids = [tid for tid, uid in group_rows if uid in to_remove]
                if remove_task_ids:
                    await db.execute(update(Task).where(Task.id.in_(remove_task_ids)).values(is_active=False))
                    await db.execute(delete(TaskAssignee).where(TaskAssignee.task_id.in_(remove_task_ids)))
                    if task.id in remove_task_ids:
                        task.is_active = False

            if to_add:
                # Use the current task's alignment users as the group default for new copies.
                alignment_user_ids = (
                    await db.execute(
                        select(TaskAlignmentUser.user_id).where(TaskAlignmentUser.task_id == task.id)
                    )
                ).scalars().all()

                # Validate added users exist and department rules.
                add_users = (
                    await db.execute(select(User).where(User.id.in_(to_add)))
                ).scalars().all()
                if len(add_users) != len(to_add):
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user not found")
                for au in add_users:
                    if not allow_cross_department and au.department_id != task.department_id:
                        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user must be in department")

                for au in add_users:
                    new_task = Task(
                        title=task.title,
                        description=task.description,
                        internal_notes=task.internal_notes,
                        skill_category=task.skill_category,
                        project_id=task.project_id,
                        dependency_task_id=task.dependency_task_id,
                        department_id=task.department_id,
                        assigned_to=au.id,
                        confirmation_assignee_id=task.confirmation_assignee_id,
                        created_by=task.created_by,
                        ga_note_origin_id=task.ga_note_origin_id,
                        plan_note_origin_id=task.plan_note_origin_id,
                        system_template_origin_id=task.system_template_origin_id,
                        fast_task_group_id=task.fast_task_group_id,
                        status=TaskStatus.TODO,
                        priority=task.priority,
                        finish_period=task.finish_period,
                        phase=task.phase,
                        progress_percentage=task.progress_percentage,
                        daily_products=task.daily_products,
                        start_date=task.start_date,
                        due_date=task.due_date,
                        original_due_date=task.original_due_date,
                        completed_at=None,
                        is_deadline_important=task.is_deadline_important,
                        is_bllok=task.is_bllok,
                        is_1h_report=task.is_1h_report,
                        one_h_report_slot=task.one_h_report_slot,
                        is_r1=task.is_r1,
                        is_personal=task.is_personal,
                        fast_task_order=task.fast_task_order,
                        is_active=True,
                    )
                    db.add(new_task)
                    await db.flush()
                    fast_group_semantic_tasks.append(new_task)
                    await _replace_task_assignees(db, new_task, [au.id])
                    await ensure_ko_user_is_task_assignee(db, task=new_task)

                    if alignment_user_ids:
                        await db.execute(
                            insert(TaskAlignmentUser),
                            [{"task_id": new_task.id, "user_id": uid} for uid in alignment_user_ids],
                        )

                    created_notifications.append(
                        add_notification(
                            db=db,
                            user_id=au.id,
                            type=NotificationType.assignment,
                            title="Task assigned",
                            body=notification_task_preview(new_task.title),
                            data={"task_id": str(new_task.id)},
                        )
                  )

    # Keep the source-note conversion flag consistent whenever an active note
    # task is edited. This also repairs older rows whose flag was cleared while
    # the linked task remained active.
    if task.is_active and task.ga_note_origin_id is not None:
        source_note = (
            await db.execute(select(GaNote).where(GaNote.id == task.ga_note_origin_id))
        ).scalar_one_or_none()
        if source_note is not None:
            source_note.is_converted_to_task = True
            from app.services.recording_task_notes import sync_recording_note_from_task
            await sync_recording_note_from_task(db, source_note, task, payload.model_fields_set, user.id)
    if task.is_active and task.plan_note_origin_id is not None:
        source_plan_note = (
            await db.execute(select(PlanNote).where(PlanNote.id == task.plan_note_origin_id))
        ).scalar_one_or_none()
        if source_plan_note is not None:
            source_plan_note.is_converted_to_task = True

    after = {
        "title": task.title,
        "description": task.description,
        "internal_notes": task.internal_notes,
        "dependency_task_id": str(task.dependency_task_id) if task.dependency_task_id else None,
        "status": _enum_value(task.status),
        "priority": _enum_value(task.priority),
        "finish_period": _enum_value(task.finish_period),
        "phase": _enum_value(task.phase),
        "assigned_to": str(task.assigned_to) if task.assigned_to else None,
        "confirmation_assignee_id": str(task.confirmation_assignee_id) if task.confirmation_assignee_id else None,
        "progress_percentage": task.progress_percentage,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "start_date": task.start_date.isoformat() if task.start_date else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "is_active": task.is_active,
        "is_deadline_important": task.is_deadline_important,
        "one_h_report_slot": task.one_h_report_slot,
    }

    new_assignee_ids = set((await db.execute(
        select(TaskAssignee.user_id).where(TaskAssignee.task_id == task.id)
    )).scalars().all())
    if task.assigned_to:
        new_assignee_ids.add(task.assigned_to)
    record_task_semantic_events(
        db=db, task_id=task.id, actor_user_id=user.id,
        before=before, after=after,
        old_assignee_ids=old_assignee_ids, new_assignee_ids=new_assignee_ids,
        **postponement,
    )
    await save_postponement_daily_explanation(
        db, task_id=task.id, user_ids=old_assignee_ids | new_assignee_ids or {user.id}, explanation=postponement,
    )
    for group_task in fast_group_semantic_tasks:
        if group_task.id == task.id:
            continue
        after_group = task_semantic_state(group_task)
        before_group = fast_group_semantic_before.get(
            group_task.id,
            {**after_group, "is_active": False, "assigned_to": None},
        )
        old_group_owner = before_group.get("assigned_to") if before_group.get("is_active") else None
        new_group_owner = after_group.get("assigned_to") if after_group.get("is_active") else None
        record_task_semantic_events(
            db=db, task_id=group_task.id, actor_user_id=user.id,
            before=before_group, after=after_group,
            old_assignee_ids=[old_group_owner] if old_group_owner else [],
            new_assignee_ids=[new_group_owner] if new_group_owner else [],
            **fast_group_postponements.get(group_task.id, {}),
        )
        await save_postponement_daily_explanation(
            db, task_id=group_task.id,
            user_ids={owner for owner in (old_group_owner, new_group_owner) if owner},
            explanation=fast_group_postponements.get(group_task.id, {}),
        )

    add_audit_log(
          db=db,
          actor_user_id=user.id,
          entity_type="task",
          entity_id=task.id,
          action="updated",
          before=before,
          after=after,
      )

    # Keep an append-only history of checklist-point strikes. 1H reports use
    # this rather than a task's current text alone, so a newly struck point is
    # shown only in the interval in which it changed and reopened points return.
    if before["title"] != task.title or (description_set and before["description"] != task.description):
        strike_event_task_ids = {task.id}
        if is_fast_group_task and task.fast_task_group_id is not None:
            strike_event_task_ids.update((await db.execute(
                select(Task.id)
                .where(Task.fast_task_group_id == task.fast_task_group_id)
                .where(Task.is_active.is_(True))
            )).scalars().all())
        for affected_task_id in strike_event_task_ids:
            if before["title"] != task.title:
                record_title_strike_events(
                    db,
                    task_id=affected_task_id,
                    actor_user_id=user.id,
                    before_title=before["title"],
                    after_title=task.title,
                )
            if description_set and before["description"] != task.description:
                record_description_strike_events(
                    db,
                    task_id=affected_task_id,
                    actor_user_id=user.id,
                    before_description=before["description"],
                    after_description=task.description,
                )

    if before_commit is not None:
        from inspect import isawaitable
        result = before_commit(task)
        if isawaitable(result):
            await result
    await db.commit()

    for n in created_notifications:
        try:
            await publish_notification(user_id=n.user_id, notification=n)
        except Exception:
            pass

    if not return_dto:
        return task
    await db.refresh(task)
    assignee_map = await _assignees_for_tasks(db, [task.id])
    dto_assignees = assignee_map.get(task.id, [])
    if _uses_fast_task_group(task):
        group_map = await _assignees_for_fast_task_groups(db, [task.fast_task_group_id])
        dto_assignees = group_map.get(task.fast_task_group_id, dto_assignees)
    dto = _task_to_out(task, dto_assignees or [], status_override=question_status_override)
    if alignment_set:
        dto.alignment_user_ids = payload.alignment_user_ids
    else:
        rows = (
            await db.execute(select(TaskAlignmentUser.user_id).where(TaskAlignmentUser.task_id == task.id))
        ).scalars().all()
        dto.alignment_user_ids = list(rows) if rows else None
    return dto


@router.post("/{task_id}/deactivate", response_model=TaskOut)
async def deactivate_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> TaskOut:
    ensure_manager_or_admin(user)
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    ensure_department_access(user, task.department_id)
    await ensure_daily_baselines_for_departments(
        db=db, department_ids={task.department_id},
        day=datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date(), actor=user,
    )
    before_active = task.is_active
    task.is_active = False
    record_task_semantic_events(
        db=db, task_id=task.id, actor_user_id=user.id,
        before={"is_active": before_active}, after={"is_active": False},
    )
    await db.commit()
    await db.refresh(task)
    assignee_map = await _assignees_for_tasks(db, [task.id])
    return _task_to_out(task, assignee_map.get(task.id, []))


class TaskCommentUpdate(BaseModel):
    comment: str | None = None


class TaskOneHReportSlotUpdate(BaseModel):
    report_date: date
    one_h_report_slot: str | None = None


class TaskOneHMarkerUpdate(BaseModel):
    one_h_marker: str | None = Field(default=None, pattern=r"^(EXCLAMATION|QUESTION|KA|GENT|FLAG|F|BZ1N1|M2|M3|M2_M3|MONITOR|CLOSE|CLIENT_URGENT|SHARE)$")
    one_h_marker_comment: str | None = Field(default=None, max_length=1000)


def _normalize_one_h_report_slot(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized if normalized in {"10:00", "11:00", "11:50", "14:20", "16:00"} else None


@router.patch("/{task_id}/one-h-report-slot", response_model=TaskOut)
async def update_task_one_h_report_slot(
    task_id: uuid.UUID,
    payload: TaskOneHReportSlotUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> TaskOut:
    return await update_task_one_h_report_slot_in_session(task_id, payload, db, user)


async def update_task_one_h_report_slot_in_session(task_id, payload, db, user, *, before_commit=None, before_update=None, return_dto=True):
    task = (await db.execute(select(Task).where(Task.id == task_id).with_for_update()
        .execution_options(populate_existing=True))).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    is_assigned = (
        task.assigned_to == user.id
        or (await db.execute(
            select(TaskAssignee).where(
                TaskAssignee.task_id == task_id,
                TaskAssignee.user_id == user.id,
            )
        )).scalar_one_or_none() is not None
    )
    if not is_assigned:
        ensure_task_editor(user, task)

    if before_update is not None:
        await before_update(task)

    next_slot = _normalize_one_h_report_slot(payload.one_h_report_slot)
    if payload.one_h_report_slot is not None and next_slot is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid 1H report slot")
    _validate_eight_am_one_h_slot(
        task.title,
        next_slot,
        is_system_task=(task.system_template_origin_id is not None or task.system_task_slot_id is not None),
    )

    # Current-day slots roll over to the next working day at 16:00.
    slot_date = effective_slot_date(payload.report_date)

    task.one_h_report_slot = next_slot
    if next_slot is not None and not task.is_r1:
        task.is_1h_report = True

    existing = (
        await db.execute(
            select(TaskOneHReportSlot).where(
                TaskOneHReportSlot.task_id == task_id,
                TaskOneHReportSlot.report_date == slot_date,
            )
        )
    ).scalar_one_or_none()

    if next_slot is None:
        if existing is not None:
            await db.delete(existing)
    elif existing is None:
        db.add(
            TaskOneHReportSlot(
                task_id=task_id,
                report_date=slot_date,
                one_h_report_slot=next_slot,
            )
        )
    else:
        existing.one_h_report_slot = next_slot

    if before_commit is not None:
        await before_commit(task)
    await db.commit()
    if not return_dto:
        return task
    await db.refresh(task)
    assignee_map = await _assignees_for_tasks(db, [task.id])
    comment_map = await _user_comments_for_tasks(db, [task.id], user.id)
    task_out = _task_to_out(task, assignee_map.get(task.id, []), comment_map.get(task.id))
    task_out.one_h_report_slot = next_slot
    return task_out


@router.patch("/{task_id}/one-h-marker", response_model=TaskOut)
async def update_task_one_h_marker(
    task_id: uuid.UUID,
    payload: TaskOneHMarkerUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> TaskOut:
    """Allow any authenticated user to classify a task shown in 1H SHTYPI."""
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    await sync_task_marker(
        db, task, payload.one_h_marker, actor_email=getattr(user, "email", None),
        marker_comment=payload.one_h_marker_comment,
    )

    await db.commit()
    await db.refresh(task)
    assignee_map = await _assignees_for_tasks(db, [task.id])
    return _task_to_out(task, assignee_map.get(task.id, []))


@router.patch("/{task_id}/comment", response_model=TaskOut)
async def update_task_user_comment(
    task_id: uuid.UUID,
    payload: TaskCommentUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> TaskOut:
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    
    # Check if user is assigned to the task
    is_assigned = (
        task.assigned_to == user.id
        or (await db.execute(
            select(TaskAssignee).where(
                TaskAssignee.task_id == task_id,
                TaskAssignee.user_id == user.id
            )
        )).scalar_one_or_none() is not None
    )
    if not is_assigned:
        if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only comment on tasks assigned to you",
            )
        ensure_department_access(user, task.department_id)
    
    # Get or create user comment
    user_comment = (
        await db.execute(
            select(TaskUserComment).where(
                TaskUserComment.task_id == task_id,
                TaskUserComment.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    
    if user_comment is None:
        user_comment = TaskUserComment(
            task_id=task_id,
            user_id=user.id,
            comment=payload.comment,
        )
        db.add(user_comment)
    else:
        user_comment.comment = payload.comment
    
    await db.commit()
    await db.refresh(task)
    assignee_map = await _assignees_for_tasks(db, [task.id])
    comment_map = await _user_comments_for_tasks(db, [task.id], user.id)
    return _task_to_out(task, assignee_map.get(task.id, []), comment_map.get(task.id))


class SharedCommentsRequest(BaseModel):
    task_ids: list[uuid.UUID] = Field(default_factory=list, max_length=2000)


class SharedCommentOut(BaseModel):
    task_id: uuid.UUID
    comment: str | None
    user_id: uuid.UUID
    updated_at: datetime | None


@router.post("/shared-comments", response_model=list[SharedCommentOut])
async def shared_task_comments(
    payload: SharedCommentsRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[SharedCommentOut]:
    """Latest comment per task, whoever wrote it (Admin Tasks shows one shared cell).

    A cleared comment counts as the latest one, so clearing the cell hides older comments.
    """
    if not payload.task_ids:
        return []
    rows = (
        await db.execute(
            select(TaskUserComment.task_id, TaskUserComment.comment, TaskUserComment.user_id, TaskUserComment.updated_at)
            .where(TaskUserComment.task_id.in_(payload.task_ids))
            .order_by(TaskUserComment.task_id, TaskUserComment.updated_at.desc().nulls_last())
            .distinct(TaskUserComment.task_id)
        )
    ).all()
    return [SharedCommentOut(task_id=task_id, comment=comment, user_id=user_id, updated_at=updated_at)
            for task_id, comment, user_id, updated_at in rows]


@router.post("/{task_id}/remove-from-day", response_model=None)
async def remove_task_from_day(
    task_id: uuid.UUID,
    payload: TaskRemoveFromDayRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Remove a task instance for a specific user/day/slot without touching the master task."""
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    
    if task.department_id is not None:
        ensure_department_access(current_user, task.department_id)
    
    # Only managers and admins can remove tasks from days
    if current_user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only managers and admins can remove tasks from days")
    
    slot = (payload.time_slot or "ALL").strip().upper()
    if slot not in ("AM", "PM", "ALL"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid time slot")

    existing = (
        await db.execute(
            select(TaskPlannerExclusion).where(
                TaskPlannerExclusion.task_id == task.id,
                TaskPlannerExclusion.user_id == payload.user_id,
                TaskPlannerExclusion.day_date == payload.day_date,
                TaskPlannerExclusion.time_slot == slot,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    await ensure_daily_baselines_for_departments(
        db=db, department_ids={task.department_id}, day=payload.day_date, actor=current_user,
    )

    exclusion = TaskPlannerExclusion(
        task_id=task.id,
        user_id=payload.user_id,
        day_date=payload.day_date,
        time_slot=slot,
        created_by=current_user.id,
    )
    db.add(exclusion)
    add_audit_log(
        db=db, actor_user_id=current_user.id, entity_type="task", entity_id=task.id,
        action="task.removed_from_day",
        before={"excluded": False, "day": payload.day_date.isoformat(), "user_id": str(payload.user_id), "time_slot": slot},
        after={"excluded": True, "day": payload.day_date.isoformat(), "user_id": str(payload.user_id), "time_slot": slot},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> Response:
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.department_id is not None:
        ensure_department_access(user, task.department_id)
    # Only managers and admins can delete tasks
    if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only managers and admins can delete tasks")

    await ensure_daily_baselines_for_departments(
        db=db, department_ids={task.department_id},
        day=datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date(), actor=user,
    )

    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="task",
        entity_id=task.id,
        action="deleted",
        before={
            "title": task.title,
            "status": _enum_value(task.status),
            "assigned_to": str(task.assigned_to) if task.assigned_to else None,
        },
    )

    if task.project_id is not None and task.phase == ProjectPhaseStatus.PRODUCT.value:
        project = (
            await db.execute(select(Project).where(Project.id == task.project_id))
        ).scalar_one_or_none()
        if project is not None and _is_mst_or_tt_project(project):
            control_tasks = (
                await db.execute(
                    select(Task)
                    .where(Task.project_id == task.project_id)
                    .where(Task.phase == ProjectPhaseStatus.CONTROL.value)
                    .where(Task.internal_notes.ilike("%origin_task_id%"))
                )
            ).scalars().all()
            linked_controls = [
                control_task
                for control_task in control_tasks
                if control_task.is_active and _parse_origin_task_id(control_task.internal_notes) == task.id
            ]
            if linked_controls:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "This PRODUCT task has a linked CONTROL task. "
                        "Delete the CONTROL task first."
                    ),
                )

    # Fast task groups: delete only this assignee copy, but remove the row entirely.
    if _uses_fast_task_group(task):
        await _clear_ga_note_conversion_if_no_active_tasks(
            db,
            note_id=task.ga_note_origin_id,
            deleting_task_id=task.id,
            actor_user_id=user.id,
        )
        await _clear_plan_note_conversion_if_no_active_tasks(
            db,
            note_id=task.plan_note_origin_id,
            deleting_task_id=task.id,
            actor_user_id=user.id,
        )
        await db.execute(delete(TaskAssignee).where(TaskAssignee.task_id == task.id))
        await db.execute(delete(TaskAlignmentUser).where(TaskAlignmentUser.task_id == task.id))
        await db.execute(delete(TaskUserComment).where(TaskUserComment.task_id == task.id))
        await db.flush()
        db.expire(task, ["assignees"])
        await db.delete(task)
        await db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # Explicitly delete related records to avoid SQLAlchemy relationship synchronization issues
    # Since TaskAssignee has a composite primary key, SQLAlchemy can't "blank out" the foreign key
    await _clear_ga_note_conversion_if_no_active_tasks(
        db,
        note_id=task.ga_note_origin_id,
        deleting_task_id=task.id,
        actor_user_id=user.id,
    )
    await _clear_plan_note_conversion_if_no_active_tasks(
        db,
        note_id=task.plan_note_origin_id,
        deleting_task_id=task.id,
        actor_user_id=user.id,
    )
    await db.execute(delete(TaskAssignee).where(TaskAssignee.task_id == task.id))
    await db.execute(delete(TaskAlignmentUser).where(TaskAlignmentUser.task_id == task.id))
    await db.execute(delete(TaskUserComment).where(TaskUserComment.task_id == task.id))
    
    # Flush to ensure deletes are processed
    await db.flush()
    
    # Expire the assignees relationship to prevent SQLAlchemy from trying to synchronize it
    db.expire(task, ["assignees"])
    
    # Now delete the task - database CASCADE will handle other related records
    await db.delete(task)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
