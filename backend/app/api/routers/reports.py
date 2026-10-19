from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, cast, func, or_, select, Date as SQLDate
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_department_access
from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models.department import Department
from app.models.enums import GaNoteStatus, UserRole, TaskStatus
from app.models.ga_note import GaNote
from app.models.project import Project
from app.models.daily_report_ga_entry import DailyReportGaEntry
from app.models.system_task_template import SystemTaskTemplate
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_one_h_report_slot import TaskOneHReportSlot
from app.services.meeting_system_tasks import TAK_INT_ONE_H_TASK_KINDS
from app.services.one_h_slots import effective_slot_date
from app.services.task_marker import active_one_h_marker
from app.models.task_user_comment import TaskUserComment
from app.models.task_daily_rlz_state import TaskDailyRlzState
from app.models.realization import RealizationDailyCloseEvent, RealizationPeriod
from app.models.user import User
from app.schemas.daily_report import (
    DailyReportResponse,
    DailyReportSystemOccurrence,
    DailyReportTaskItem,
    DailyReportGaEntryOut,
    DailyReportGaEntryUpsert,
    DailyReportGaNoteOut,
    DailyReportGaTableResponse,
    DailyRlzStateUpsert,
    DailyRlzTaskStateOut,
    DailyRlzCloseStateOut,
    DailyRlzStateCorrection,
)
from app.schemas.task import TaskAssigneeOut, TaskOut
from app.services.project_display_title import build_project_display_title_map
from app.services.daily_report_logic import (
    completed_on_day,
    planned_range_for_daily_report,
    task_matches_department_scope,
    task_is_visible_to_user,
    business_days_between,
)
from app.services.daily_rlz_compliance import (
    REASON_LABELS, build_daily_rlz_compliance, build_daily_rlz_control,
    editable_until, is_editable_day,
)
from app.services.audit import add_audit_log
from app.services.daily_realization_explanation import requires_daily_explanation
from app.services.daily_realization_events import semantic_local_day


router = APIRouter()
_ONE_H_SLOT_UNSET = object()
try:
    APP_TZ = ZoneInfo(settings.APP_TIMEZONE)
except Exception:
    APP_TZ = timezone.utc


def _tirana_day_utc_bounds(day: date) -> tuple[datetime, datetime]:
    day_start_local = datetime.combine(day, time.min, tzinfo=APP_TZ)
    day_end_local = day_start_local + timedelta(days=1)
    return day_start_local.astimezone(timezone.utc), day_end_local.astimezone(timezone.utc)


def _has_global_report_scope(user: User) -> bool:
    return user.role in {UserRole.ADMIN, UserRole.MANAGER}


def _resolve_effective_department_id(
    *,
    current_user: User,
    requested_department_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if requested_department_id is not None:
        return requested_department_id
    if not _has_global_report_scope(current_user):
        return current_user.department_id
    return None


def _resolve_target_user_id(
    *,
    requested_user_id: uuid.UUID | None,
    current_user_id: uuid.UUID,
) -> uuid.UUID:
    return requested_user_id or current_user_id


def _enforce_daily_report_target_scope(
    *,
    current_user: User,
    effective_department_id: uuid.UUID | None,
    target_user: User,
) -> None:
    if _has_global_report_scope(current_user) and effective_department_id is None:
        return
    if effective_department_id is None or target_user.department_id != effective_department_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


async def _resolve_daily_report_scope(
    *,
    db: AsyncSession,
    current_user: User,
    requested_department_id: uuid.UUID | None,
    requested_user_id: uuid.UUID | None,
) -> tuple[uuid.UUID | None, uuid.UUID]:
    effective_department_id = _resolve_effective_department_id(
        current_user=current_user,
        requested_department_id=requested_department_id,
    )
    target_user_id = _resolve_target_user_id(
        requested_user_id=requested_user_id,
        current_user_id=current_user.id,
    )
    target_user = (
        await db.execute(select(User).where(User.id == target_user_id))
    ).scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _enforce_daily_report_target_scope(
        current_user=current_user,
        effective_department_id=effective_department_id,
        target_user=target_user,
    )
    return effective_department_id, target_user.id


def _user_to_assignee(user: User) -> TaskAssigneeOut:
    return TaskAssigneeOut(
        id=user.id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
    )


async def _assignees_for_tasks(db: AsyncSession, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[TaskAssigneeOut]]:
    if not task_ids:
        return {}
    rows = (
        await db.execute(
            select(TaskAssignee.task_id, User)
            .join(User, TaskAssignee.user_id == User.id)
            .where(TaskAssignee.task_id.in_(task_ids))
            .order_by(User.full_name)
        )
    ).all()
    out: dict[uuid.UUID, list[TaskAssigneeOut]] = {tid: [] for tid in task_ids}
    for tid, user in rows:
        out.setdefault(tid, []).append(_user_to_assignee(user))
    return out


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


def _task_to_out(
    t: Task,
    assignees: list[TaskAssigneeOut],
    user_comment: str | None = None,
    one_h_report_slot: str | None | object = _ONE_H_SLOT_UNSET,
    marker_report_date: date | None = None,
) -> TaskOut:
    # Reuse TaskOut model shape; keep it minimal for reporting.
    return TaskOut(
        id=t.id,
        title=t.title,
        description=t.description,
        internal_notes=t.internal_notes,
        project_id=t.project_id,
        dependency_task_id=t.dependency_task_id,
        department_id=t.department_id,
        assigned_to=t.assigned_to,
        assignees=assignees,
        created_by=t.created_by,
        ga_note_origin_id=t.ga_note_origin_id,
        system_template_origin_id=t.system_template_origin_id,
        status="DONE" if t.completed_at else t.status,
        priority=t.priority,
        finish_period=t.finish_period,
        phase=t.phase,
        progress_percentage=t.progress_percentage,
        daily_products=t.daily_products,
        start_date=t.start_date,
        due_date=t.due_date,
        completed_at=t.completed_at,
        is_deadline_important=t.is_deadline_important,
        is_bllok=t.is_bllok,
        is_1h_report=t.is_1h_report,
        one_h_report_slot=t.one_h_report_slot if one_h_report_slot is _ONE_H_SLOT_UNSET else one_h_report_slot,
        one_h_marker=active_one_h_marker(t, marker_report_date),
        is_r1=t.is_r1,
        is_personal=t.is_personal,
        is_active=t.is_active,
        user_comment=user_comment,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def _planned_range_for_task(t: Task) -> tuple[date | None, date | None]:
    if t.due_date is None:
        return None, None
    due = t.due_date.date()
    if t.start_date is not None:
        start = t.start_date.date()
        # Only treat start_date as a planning start if it forms a valid interval.
        if start <= due:
            return start, due
    # Default: single-day planned task on due date.
    return due, due


def _has_0800_marker(title: str | None, *, is_system_task: bool = False) -> bool:
    from app.services.task_title_rules import title_has_eight_am_indicator

    return title_has_eight_am_indicator(title, is_system_task=is_system_task)


def _finish_period_rank(value: str | None) -> int:
    normalized = (value or "").strip().upper()
    if normalized == "AM":
        return 0
    if normalized in {"", "AM/PM"}:
        return 1
    if normalized == "PM":
        return 2
    return 3


def _daily_task_sort_key(item: DailyReportTaskItem) -> tuple[int, int, int, int, datetime, datetime, str]:
    task = item.task
    due_date = task.due_date or datetime.max.replace(tzinfo=timezone.utc)
    created_at = task.created_at or datetime.max.replace(tzinfo=timezone.utc)
    status_value = str(getattr(task.status, "value", task.status) or "").strip().upper()
    is_done = bool(task.completed_at) or status_value == "DONE"
    return (
        1 if is_done else 0,
        _finish_period_rank(task.finish_period),
        0
        if _has_0800_marker(
            task.title,
            is_system_task=bool(getattr(task, "system_template_origin_id", None) or getattr(task, "system_task_slot_id", None)),
        )
        else 1,
        0 if task.is_deadline_important else 1,
        due_date,
        created_at,
        task.title.lower(),
    )


def _infer_department_code(name: str | None) -> str | None:
    if not name:
        return None
    upper = name.strip().upper()
    if "DEVELOPMENT" in upper:
        return "DEV"
    if "GRAPHIC" in upper and "DESIGN" in upper:
        return "GDS"
    if ("PRODUCT" in upper and "CONTENT" in upper) or "PROJECT CONTENT" in upper:
        return "PCM"
    cleaned = re.sub(r"[^A-Z]", "", upper)
    return cleaned[:3] or None


async def _department_code_for_id(db: AsyncSession, department_id: uuid.UUID | None) -> str | None:
    if department_id is None:
        return None
    dept = (
        await db.execute(select(Department).where(Department.id == department_id))
    ).scalar_one_or_none()
    if dept is None:
        return None
    if dept.code:
        return dept.code.strip().upper()
    return _infer_department_code(dept.name)


@router.get("/daily", response_model=DailyReportResponse)
async def daily_report(
    day: date,
    department_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> DailyReportResponse:
    """
    Daily Report = execution/accountability:
    - tasks scheduled for day
    - tasks from previous days not completed (late X days, show original planned date)
    - system tasks: per-occurrence status (OPEN / DONE / NOT_DONE / SKIPPED), with late logic
    """
    department_id, user_id = await _resolve_daily_report_scope(
        db=db,
        current_user=user,
        requested_department_id=department_id,
        requested_user_id=user_id,
    )

    # --- Regular tasks (non-system) ---
    dept_code = await _department_code_for_id(db, department_id)
    day_start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    task_stmt = (
        select(Task)
        .outerjoin(Project, Task.project_id == Project.id)
        .where(Task.is_active.is_(True))
        .where(Task.system_template_origin_id.is_(None))
        .where(Task.due_date.is_not(None))
    )
    include_cross_department_assigned = user_id is not None
    if department_id is not None and not include_cross_department_assigned:
        task_stmt = task_stmt.where(or_(Task.department_id == department_id, Project.department_id == department_id))

    # Prefilter by user to avoid scanning all tasks (still apply KO filtering in Python for correctness).
    if user_id is not None:
        task_stmt = (
            task_stmt.outerjoin(TaskAssignee, TaskAssignee.task_id == Task.id)
            .where(
                or_(
                    Task.assigned_to == user_id,
                    TaskAssignee.user_id == user_id,
                    Task.internal_notes.ilike(f"%ko_user_id={user_id}%"),
                    Task.internal_notes.ilike(f"%ko_user_id:%{user_id}%"),
                    Task.internal_notes.ilike(f"%ko_user_id%{user_id}%"),
                )
            )
            .distinct()
        )

    tasks = (await db.execute(task_stmt.order_by(Task.due_date, Task.created_at))).scalars().all()
    task_ids = [t.id for t in tasks]
    assignee_out_map = await _assignees_for_tasks(db, task_ids)
    comment_map = await _user_comments_for_tasks(db, task_ids, user_id)
    daily_rlz_map = {}
    if task_ids:
        daily_rlz_map = {row.task_id: row for row in (await db.execute(
            select(TaskDailyRlzState).where(
                TaskDailyRlzState.task_id.in_(task_ids),
                TaskDailyRlzState.user_id == user_id,
                TaskDailyRlzState.day_date == day,
            )
        )).scalars().all()}
    one_h_slot_map: dict[uuid.UUID, str] = {}
    if task_ids:
        rows = (
            await db.execute(
                select(TaskOneHReportSlot.task_id, TaskOneHReportSlot.one_h_report_slot)
                .where(TaskOneHReportSlot.task_id.in_(task_ids))
                .where(TaskOneHReportSlot.report_date == effective_slot_date(day))
            )
        ).all()
        one_h_slot_map = {task_id: slot for task_id, slot in rows}
        # TAK INT 1H tasks take their slot from the meeting, so the 16:00 rollover must not blank it
        # on the slot day itself. On any other day the slot stays empty.
        for t in tasks:
            if (
                t.meeting_system_task_kind in TAK_INT_ONE_H_TASK_KINDS
                and t.one_h_report_slot
                and t.meeting_occurrence_date == day
            ):
                one_h_slot_map.setdefault(t.id, t.one_h_report_slot)

    assignee_ids_by_task: dict[uuid.UUID, set[uuid.UUID]] = {tid: set() for tid in task_ids}
    if task_ids:
        rows = (
            await db.execute(
                select(TaskAssignee.task_id, TaskAssignee.user_id).where(TaskAssignee.task_id.in_(task_ids))
            )
        ).all()
        for tid, uid in rows:
            assignee_ids_by_task.setdefault(tid, set()).add(uid)

    project_ids = {t.project_id for t in tasks if t.project_id is not None}
    projects: list[Project] = []
    if project_ids:
        projects = (
            await db.execute(select(Project).where(Project.id.in_(project_ids)))
        ).scalars().all()
    project_by_id = {p.id: p for p in projects}
    display_title_by_id = await build_project_display_title_map(db, projects)
    project_title_by_id: dict[uuid.UUID, str] = {
        p.id: (display_title_by_id.get(p.id) or p.title or p.name or "") for p in projects if (p.title or p.name)
    }

    tasks_today: list[DailyReportTaskItem] = []
    tasks_overdue: list[DailyReportTaskItem] = []
    for t in tasks:
        project = project_by_id.get(t.project_id) if t.project_id else None
        if not task_matches_department_scope(
            t,
            project=project,
            department_id=department_id,
            include_cross_department_assigned=include_cross_department_assigned,
        ):
            continue
        if user_id is not None and not task_is_visible_to_user(
            t,
            user_id=user_id,
            assignee_ids=assignee_ids_by_task.get(t.id),
            project=project,
            dept_code=dept_code,
        ):
            continue

        planned_start, planned_end = planned_range_for_daily_report(t, dept_code)
        if planned_start is None or planned_end is None:
            continue

        completed_today = completed_on_day(t.completed_at, day)
        is_done = t.completed_at is not None or t.status == TaskStatus.DONE
        if completed_today:
            tasks_today.append(
                DailyReportTaskItem(
                    task=_task_to_out(
                        t,
                        assignee_out_map.get(t.id, []),
                        user_comment=comment_map.get(t.id),
                        one_h_report_slot=one_h_slot_map.get(t.id),
                        marker_report_date=day,
                    ),
                    project_title=project_title_by_id.get(t.project_id) if t.project_id else None,
                    planned_start=planned_start,
                    planned_end=planned_end,
                    original_planned_end=t.original_due_date.date() if t.original_due_date else planned_end,
                    is_overdue=False,
                    late_days=None,
                    rlz_daily_state=_daily_rlz_state_out(daily_rlz_map.get(t.id), day, comment_map.get(t.id), task=t),
                )
            )
            continue

        if planned_start <= day <= planned_end:
            tasks_today.append(
                DailyReportTaskItem(
                    task=_task_to_out(
                        t,
                        assignee_out_map.get(t.id, []),
                        user_comment=comment_map.get(t.id),
                        one_h_report_slot=one_h_slot_map.get(t.id),
                        marker_report_date=day,
                    ),
                    project_title=project_title_by_id.get(t.project_id) if t.project_id else None,
                    planned_start=planned_start,
                    planned_end=planned_end,
                    original_planned_end=t.original_due_date.date() if t.original_due_date else planned_end,
                    is_overdue=False,
                    late_days=None,
                    rlz_daily_state=_daily_rlz_state_out(daily_rlz_map.get(t.id), day, comment_map.get(t.id), task=t),
                )
            )
        elif planned_end < day:
            if is_done:
                continue
            late_days = business_days_between(planned_end, day)
            tasks_overdue.append(
                DailyReportTaskItem(
                    task=_task_to_out(
                        t,
                        assignee_out_map.get(t.id, []),
                        user_comment=comment_map.get(t.id),
                        one_h_report_slot=one_h_slot_map.get(t.id),
                        marker_report_date=day,
                    ),
                    project_title=project_title_by_id.get(t.project_id) if t.project_id else None,
                    planned_start=planned_start,
                    planned_end=planned_end,
                    original_planned_end=t.original_due_date.date() if t.original_due_date else planned_end,
                    is_overdue=True,
                    late_days=late_days,
                    rlz_daily_state=_daily_rlz_state_out(daily_rlz_map.get(t.id), day, comment_map.get(t.id), task=t),
                )
            )

    # --- System recurring tasks from `tasks` (origin_run_at) ---
    done_like_statuses = ("DONE", "NOT_DONE", "SKIPPED")
    local_occurrence_date = cast(
        func.timezone(func.coalesce(SystemTaskTemplate.timezone, settings.APP_TIMEZONE), Task.origin_run_at),
        SQLDate,
    )

    system_today_rows = (
        await db.execute(
            select(Task, SystemTaskTemplate, local_occurrence_date.label("occurrence_date"))
            .join(SystemTaskTemplate, Task.system_template_origin_id == SystemTaskTemplate.id)
            .where(Task.assigned_to == user_id)
            .where(Task.system_template_origin_id.is_not(None))
            .where(Task.origin_run_at.is_not(None))
            .where(Task.is_active.is_(True))
            .where(local_occurrence_date == day)
            .order_by(SystemTaskTemplate.title)
        )
    ).all()

    day_start_utc, day_end_utc = _tirana_day_utc_bounds(day)
    system_acted_today_rows = (
        await db.execute(
            select(Task, SystemTaskTemplate, local_occurrence_date.label("occurrence_date"))
            .join(SystemTaskTemplate, Task.system_template_origin_id == SystemTaskTemplate.id)
            .where(Task.assigned_to == user_id)
            .where(Task.system_template_origin_id.is_not(None))
            .where(Task.origin_run_at.is_not(None))
            .where(Task.is_active.is_(True))
            .where(local_occurrence_date < day)
            .where(Task.status.in_(done_like_statuses))
            .where(Task.completed_at.is_not(None))
            .where(Task.completed_at >= day_start_utc)
            .where(Task.completed_at < day_end_utc)
            .order_by(Task.completed_at.desc(), SystemTaskTemplate.title)
        )
    ).all()

    latest_occurrence = (
        select(
            Task.system_template_origin_id.label("template_id"),
            Task.system_task_slot_id.label("slot_id"),
            func.max(local_occurrence_date).label("latest_date"),
        )
        .join(SystemTaskTemplate, Task.system_template_origin_id == SystemTaskTemplate.id)
        .where(Task.assigned_to == user_id)
        .where(Task.system_template_origin_id.is_not(None))
        .where(Task.origin_run_at.is_not(None))
        .where(Task.is_active.is_(True))
        .where(local_occurrence_date <= day)
        .group_by(Task.system_template_origin_id, Task.system_task_slot_id)
    ).subquery()

    system_overdue_rows = (
        await db.execute(
            select(Task, SystemTaskTemplate, local_occurrence_date.label("occurrence_date"))
            .join(SystemTaskTemplate, Task.system_template_origin_id == SystemTaskTemplate.id)
            .join(
                latest_occurrence,
                and_(
                    Task.system_template_origin_id == latest_occurrence.c.template_id,
                    Task.system_task_slot_id.is_not_distinct_from(latest_occurrence.c.slot_id),
                    local_occurrence_date == latest_occurrence.c.latest_date,
                ),
            )
            .where(Task.assigned_to == user_id)
            .where(Task.is_active.is_(True))
            .where(local_occurrence_date < day)
            .where(Task.status.not_in(done_like_statuses))
            .order_by(local_occurrence_date.desc(), SystemTaskTemplate.title)
        )
    ).all()

    all_system_task_ids = [task.id for task, _, _ in (system_today_rows + system_acted_today_rows + system_overdue_rows)]
    system_assignee_out_map = await _assignees_for_tasks(db, all_system_task_ids)
    system_comment_map = await _user_comments_for_tasks(db, all_system_task_ids, user_id)
    system_daily_rlz_map = {
        row.task_id: row
        for row in (await db.execute(select(TaskDailyRlzState).where(
            TaskDailyRlzState.task_id.in_(all_system_task_ids),
            TaskDailyRlzState.user_id == user_id,
            TaskDailyRlzState.day_date == day,
        ))).scalars().all()
    } if all_system_task_ids else {}

    def _to_occurrence_status(task_status: str | None) -> str:
        if task_status in done_like_statuses:
            return task_status or "OPEN"
        return "OPEN"

    merged_today_rows = sorted(
        system_today_rows + system_acted_today_rows,
        key=lambda row: ((row[1].title or "").lower(), row[2]),
    )
    system_today: list[DailyReportSystemOccurrence] = []
    for task, tmpl, occurrence_day in merged_today_rows:
        is_from_overdue = occurrence_day < day
        late_days = business_days_between(occurrence_day, day) if is_from_overdue else None
        system_today.append(
            DailyReportSystemOccurrence(
                task=_task_to_out(
                    task,
                    system_assignee_out_map.get(task.id, []),
                    user_comment=system_comment_map.get(task.id),
                    marker_report_date=day,
                ),
                template_id=tmpl.id,
                title=tmpl.title,
                frequency=tmpl.frequency,
                department_id=tmpl.department_id,
                scope=tmpl.scope,
                occurrence_date=occurrence_day,
                status=_to_occurrence_status(task.status),
                comment=system_comment_map.get(task.id),
                acted_at=task.completed_at,
                is_overdue=is_from_overdue,
                late_days=late_days,
                rlz_daily_state=_daily_rlz_state_out(
                    system_daily_rlz_map.get(task.id), day, system_comment_map.get(task.id),
                    system_task=task,
                ),
            )
        )

    system_overdue: list[DailyReportSystemOccurrence] = []
    for task, tmpl, occurrence_day in system_overdue_rows:
        late_days = business_days_between(occurrence_day, day)
        system_overdue.append(
            DailyReportSystemOccurrence(
                task=_task_to_out(
                    task,
                    system_assignee_out_map.get(task.id, []),
                    user_comment=system_comment_map.get(task.id),
                    marker_report_date=day,
                ),
                template_id=tmpl.id,
                title=tmpl.title,
                frequency=tmpl.frequency,
                department_id=tmpl.department_id,
                scope=tmpl.scope,
                occurrence_date=occurrence_day,
                status=_to_occurrence_status(task.status),
                comment=system_comment_map.get(task.id),
                acted_at=task.completed_at,
                is_overdue=True,
                late_days=late_days,
                rlz_daily_state=_daily_rlz_state_out(
                    system_daily_rlz_map.get(task.id), day, system_comment_map.get(task.id),
                    system_task=task,
                ),
            )
        )

    tasks_today.sort(key=_daily_task_sort_key)
    tasks_overdue.sort(key=_daily_task_sort_key)

    compliance = await build_daily_rlz_compliance(db, user_id=user_id, day=day)
    requirement_by_task = {item["task_id"]: item for item in compliance.get("tasks", [])}
    # System-task inputs follow their occurrence's TODO status directly, including
    # occurrences excluded from Realization or carried over from a previous day.
    for collection in (tasks_today, tasks_overdue):
        for item in collection:
            state = item.rlz_daily_state
            requirement = requirement_by_task.get(str(item.task.id))
            if state is not None and requirement is not None:
                for field in (
                    "requires_explanation", "reason_required", "comment_required",
                    "reason_missing", "comment_missing", "deadline_was_today",
                    "deadline_is_overdue", "postponed_today",
                ):
                    setattr(state, field, bool(requirement.get(field)))
    return DailyReportResponse(
        day=day,
        tasks_today=tasks_today,
        tasks_overdue=tasks_overdue,
        system_today=system_today,
        system_overdue=system_overdue,
        rlz_close_state=DailyRlzCloseStateOut(**compliance["rlz_close_state"]),
    )


def _daily_rlz_state_out(
    row: TaskDailyRlzState | None, day: date, fallback_comment: str | None = None,
    *, system_task: Task | None = None, task: Task | None = None,
) -> DailyRlzTaskStateOut:
    task = task if task is not None else system_task
    explanation_required = bool(task is not None and requires_daily_explanation(
        status="DONE" if task.completed_at else str(getattr(task.status, "value", task.status)),
        selected_day=day, deadline=semantic_local_day(task.due_date),
    ).requires_explanation)
    return DailyRlzTaskStateOut(
        reason_code=row.reason_code if row else None,
        reason_label=REASON_LABELS.get(row.reason_code) if row else None,
        comment=row.comment if row else None,
        updated_at=row.updated_at if row else None,
        is_editable=is_editable_day(day),
        editable_until=editable_until(day),
        requires_explanation=explanation_required,
        reason_required=explanation_required,
        comment_required=explanation_required,
        reason_missing=explanation_required and not (row and row.reason_code),
        comment_missing=explanation_required and not (row and (row.comment or "").strip()),
    )


@router.put("/daily-rlz-state/{task_id}", response_model=DailyRlzTaskStateOut)
async def upsert_daily_rlz_state(
    task_id: uuid.UUID,
    payload: DailyRlzStateUpsert,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DailyRlzTaskStateOut:
    if not is_editable_day(payload.day):
        raise HTTPException(status_code=409, detail={
            "code": "DAILY_RLZ_EDIT_WINDOW_CLOSED",
            "message": "Arsyeja dhe komenti për këtë ditë mund të ndryshohen vetëm deri në orën 17:00.",
        })
    task = await db.get(Task, task_id)
    if task is None or not task.is_active:
        raise HTTPException(status_code=404, detail="Task not found")
    target_user_id = payload.user_id or user.id
    if target_user_id != user.id and user.role not in {UserRole.MANAGER, UserRole.ADMIN}:
        raise HTTPException(status_code=403, detail="Only manager/admin can edit another employee's Daily Report")
    if target_user_id != user.id and await db.get(User, target_user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    assigned = task.assigned_to == target_user_id or bool(await db.scalar(select(TaskAssignee.task_id).where(
        TaskAssignee.task_id == task_id, TaskAssignee.user_id == target_user_id,
    )))
    if not assigned:
        raise HTTPException(status_code=403, detail="The selected employee is not assigned to this task")
    row = (await db.execute(select(TaskDailyRlzState).where(
        TaskDailyRlzState.task_id == task_id, TaskDailyRlzState.user_id == target_user_id,
        TaskDailyRlzState.day_date == payload.day,
    ).with_for_update())).scalar_one_or_none()
    before = {"reason_code": row.reason_code, "comment": row.comment} if row else None
    if row is None:
        row = TaskDailyRlzState(task_id=task_id, user_id=target_user_id, day_date=payload.day)
        db.add(row)
    row.reason_code = payload.reason_code
    row.comment = payload.comment.strip() if payload.comment and payload.comment.strip() else None
    if target_user_id != user.id:
        await db.flush()
        add_audit_log(
            db=db,
            actor_user_id=user.id,
            entity_type="task_daily_rlz_state",
            entity_id=row.id,
            action="MANAGER_DAILY_RLZ_UPDATE",
            before=before,
            after={"reason_code": row.reason_code, "comment": row.comment, "user_id": str(target_user_id)},
        )
    await db.commit()
    await db.refresh(row)
    return _daily_rlz_state_out(
        row, payload.day,
        task=task,
    )


@router.put("/daily-rlz-state/{task_id}/correction", response_model=DailyRlzTaskStateOut)
async def correct_daily_rlz_state(
    task_id: uuid.UUID, payload: DailyRlzStateCorrection,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
) -> DailyRlzTaskStateOut:
    if user.role not in {UserRole.MANAGER, UserRole.ADMIN}:
        raise HTTPException(status_code=403, detail="Only manager/admin can correct closed Daily RLZ evidence")
    subject = await db.get(User, payload.user_id)
    task = await db.get(Task, task_id)
    if not subject or not task:
        raise HTTPException(status_code=404, detail="User or task not found")
    subject_assigned = task.assigned_to == subject.id or bool(await db.scalar(select(TaskAssignee.task_id).where(
        TaskAssignee.task_id == task_id, TaskAssignee.user_id == subject.id,
    )))
    if not subject_assigned:
        raise HTTPException(status_code=409, detail="The task is not assigned to the selected employee")
    latest = (await db.execute(select(RealizationDailyCloseEvent).join(
        RealizationPeriod, RealizationPeriod.id == RealizationDailyCloseEvent.period_id
    ).where(
        RealizationDailyCloseEvent.user_id == payload.user_id,
        RealizationPeriod.period_type == "DAILY", RealizationPeriod.start_date == payload.day,
    ).order_by(RealizationDailyCloseEvent.created_at.desc(), RealizationDailyCloseEvent.id.desc()).limit(1))).scalar_one_or_none()
    if latest is None or latest.action != "REOPEN":
        raise HTTPException(status_code=409, detail="Reopen the Realization day before correcting historical evidence")
    row = (await db.execute(select(TaskDailyRlzState).where(
        TaskDailyRlzState.task_id == task_id, TaskDailyRlzState.user_id == payload.user_id,
        TaskDailyRlzState.day_date == payload.day,
    ).with_for_update())).scalar_one_or_none()
    before = {"reason_code": row.reason_code, "comment": row.comment} if row else None
    if row is None:
        row = TaskDailyRlzState(task_id=task_id, user_id=payload.user_id, day_date=payload.day)
        db.add(row)
    row.reason_code = payload.reason_code
    row.comment = payload.comment.strip() if payload.comment and payload.comment.strip() else None
    await db.flush()
    add_audit_log(db=db, actor_user_id=user.id, entity_type="task_daily_rlz_state", entity_id=row.id,
                  action="AUTHORIZED_CORRECTION", before=before,
                  after={"reason_code": row.reason_code, "comment": row.comment,
                         "correction_reason": payload.correction_reason, "reopen_event_id": str(latest.id)})
    await db.commit()
    await db.refresh(row)
    return _daily_rlz_state_out(
        row, payload.day,
        task=task,
    )


@router.get("/daily-rlz-compliance")
async def daily_rlz_compliance(
    day: date, user_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
) -> dict:
    target_id = user.id if user.role == UserRole.STAFF else (user_id or user.id)
    return await build_daily_rlz_compliance(db, user_id=target_id, day=day)


@router.get("/daily-rlz-control")
async def daily_rlz_control(
    day: date, department_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
) -> dict:
    if user.role == UserRole.STAFF:
        raise HTTPException(status_code=403, detail="Forbidden")
    return await build_daily_rlz_control(db, day=day, department_id=department_id, user_id=user_id)


@router.get("/daily-ga-table", response_model=DailyReportGaTableResponse)
async def daily_ga_table(
    day: date,
    department_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> DailyReportGaTableResponse:
    if user.role == UserRole.STAFF:
        department_id = user.department_id
        user_id = user.id

    if department_id is not None:
        ensure_department_access(user, department_id)
    elif not _has_global_report_scope(user):
        department_id = user.department_id

    if user_id is None:
        user_id = user.id

    entry = None
    if department_id is not None:
        entry = (
            await db.execute(
                select(DailyReportGaEntry).where(
                    DailyReportGaEntry.user_id == user_id,
                    DailyReportGaEntry.department_id == department_id,
                    DailyReportGaEntry.entry_date == day,
                )
            )
        ).scalar_one_or_none()

    task_stmt = (
        select(Task)
        .where(Task.completed_at.is_(None))
        .where(Task.is_active.is_(True))
        .where(Task.system_template_origin_id.is_(None))
        .where(Task.due_date.is_not(None))
    )
    if department_id is not None:
        task_stmt = task_stmt.where(Task.department_id == department_id)
    if user_id is not None:
        task_stmt = task_stmt.where(Task.assigned_to == user_id)

    tasks = (await db.execute(task_stmt.order_by(Task.due_date, Task.created_at))).scalars().all()
    project_ids: set[uuid.UUID] = set()
    for task in tasks:
        planned_start, planned_end = _planned_range_for_task(task)
        if planned_start is None or planned_end is None:
            continue
        if planned_start <= day <= planned_end and task.project_id is not None:
            project_ids.add(task.project_id)

    closed_cutoff = datetime.utcnow() - timedelta(days=30)
    base_filters = [
        or_(
            GaNote.status != GaNoteStatus.CLOSED,
            GaNote.completed_at.is_(None),
            GaNote.completed_at >= closed_cutoff,
        ),
    ]

    user_notes = (
        await db.execute(
            select(GaNote)
            .where(GaNote.created_by == user_id)
            .where(*base_filters)
            .order_by(GaNote.created_at.desc())
        )
    ).scalars().all()

    project_notes: list[GaNote] = []
    if project_ids:
        project_notes = (
            await db.execute(
                select(GaNote)
                .where(GaNote.project_id.in_(project_ids))
                .where(*base_filters)
                .order_by(GaNote.created_at.desc())
            )
        ).scalars().all()

    notes_by_id: dict[uuid.UUID, GaNote] = {}
    for note in user_notes + project_notes:
        notes_by_id[note.id] = note

    note_project_ids = {note.project_id for note in notes_by_id.values() if note.project_id}
    project_map: dict[uuid.UUID, Project] = {}
    if note_project_ids:
        projects = (
            await db.execute(select(Project).where(Project.id.in_(note_project_ids)))
        ).scalars().all()
        project_map = {proj.id: proj for proj in projects}

    def _project_name(pid: uuid.UUID | None) -> str | None:
        if not pid:
            return None
        proj = project_map.get(pid)
        if not proj:
            return None
        return proj.title or proj.name

    notes_sorted = sorted(notes_by_id.values(), key=lambda n: n.created_at, reverse=True)
    notes_out = [
        DailyReportGaNoteOut(
            id=n.id,
            content=n.content,
            note_type=n.note_type,
            status=n.status,
            priority=n.priority,
            created_at=n.created_at,
            project_id=n.project_id,
            project_name=_project_name(n.project_id),
        )
        for n in notes_sorted
    ]

    return DailyReportGaTableResponse(
        entry=DailyReportGaEntryOut(
            id=entry.id,
            user_id=entry.user_id,
            department_id=entry.department_id,
            entry_date=entry.entry_date,
            content=entry.content,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )
        if entry
        else None,
        notes=notes_out,
    )


@router.put("/daily-ga-entry", response_model=DailyReportGaEntryOut)
async def upsert_daily_ga_entry(
    payload: DailyReportGaEntryUpsert,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> DailyReportGaEntryOut:
    department_id = payload.department_id
    user_id = payload.user_id or user.id

    if user.role == UserRole.STAFF:
        user_id = user.id
        department_id = user.department_id

    if department_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="department_id required")

    ensure_department_access(user, department_id)

    entry = (
        await db.execute(
            select(DailyReportGaEntry).where(
                DailyReportGaEntry.user_id == user_id,
                DailyReportGaEntry.department_id == department_id,
                DailyReportGaEntry.entry_date == payload.day,
            )
        )
    ).scalar_one_or_none()

    if entry is None:
        entry = DailyReportGaEntry(
            user_id=user_id,
            department_id=department_id,
            entry_date=payload.day,
            content=payload.content,
        )
        db.add(entry)
    else:
        entry.content = payload.content

    await db.commit()
    await db.refresh(entry)

    return DailyReportGaEntryOut(
        id=entry.id,
        user_id=entry.user_id,
        department_id=entry.department_id,
        entry_date=entry.entry_date,
        content=entry.content,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )
