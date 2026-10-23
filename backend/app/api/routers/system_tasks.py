from __future__ import annotations

import uuid
from types import SimpleNamespace
from datetime import date, datetime, timedelta, timezone, time as dt_time
from collections import defaultdict

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, insert, or_, select, text, cast, Date as SQLDate, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.api.access import ensure_department_access
from app.config import settings
from app.api.deps import get_current_user, require_admin
from app.db import get_db
from app.models.department import Department
from app.models.enums import (
    CommonApprovalStatus,
    FrequencyType,
    SystemTaskScope,
    TaskFinishPeriod,
    TaskPriority,
    TaskStatus,
    UserRole,
)
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_user_comment import TaskUserComment
from app.models.system_task_template import SystemTaskTemplate
from app.models.system_task_template_assignee_slot import SystemTaskTemplateAssigneeSlot
from app.models.system_task_template_alignment_role import SystemTaskTemplateAlignmentRole
from app.models.system_task_template_alignment_user import SystemTaskTemplateAlignmentUser
from app.models.user import User
from app.schemas.system_task import SystemTaskOut
from app.schemas.task import TaskAssigneeOut
from app.schemas.system_task_template import (
    SystemTaskTemplateAssigneeSlotIn,
    SystemTaskTemplateAssigneeSlotOut,
    SystemTaskTemplateCreate, SystemTaskTemplateOut,
    SystemTaskTemplateReject,
    SystemTaskTemplateUpdate,
)
from app.services.system_task_schedule import (
    first_run_at,
    matches_template_date,
    next_occurrence_date,
    previous_occurrence_date,
    should_reopen_system_task,
    template_tz,
)
from app.services.system_task_instances import (
    ensure_slots_initialized,
    generate_system_task_instances,
    reconcile_system_task_assignments_in_range,
)
from app.services.meeting_system_tasks import (
    EXTERNAL_MEETING_TASK_KIND,
    EXTERNAL_MEETING_TRIGGER_TYPE,
)
from app.services.daily_realization_baseline import ensure_daily_baselines_for_departments
from app.services.daily_realization_events import record_task_semantic_events
from app.services.task_postponement import check_task_postponement_explanation, save_postponement_daily_explanation


router = APIRouter()
GA_EMAIL = "ga@primexeu.com"
MAX_ASSIGNEES_REQUIRING_REPLACEMENTS = 9


def _enum_value(value) -> str | None:
    if value is None:
        return None
    return value.value if hasattr(value, "value") else value


def _task_is_active(template: SystemTaskTemplate) -> bool:
    if not template.is_active:
        return False
    if _template_approval_status(template) != CommonApprovalStatus.approved:
        return False
    return True


def _template_approval_status(template: SystemTaskTemplate) -> CommonApprovalStatus:
    value = getattr(template, "approval_status", None)
    if value is None:
        return CommonApprovalStatus.approved
    return value if isinstance(value, CommonApprovalStatus) else CommonApprovalStatus(value)


def _user_to_assignee(user: User) -> TaskAssigneeOut:
    return TaskAssigneeOut(
        id=user.id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
    )


def _is_gane_user(user: User | object) -> bool:
    return (getattr(user, "email", None) or "").strip().lower() == GA_EMAIL


def _replacements_required(assignee_ids: list[uuid.UUID] | None) -> bool:
    return 0 < len(assignee_ids or []) <= MAX_ASSIGNEES_REQUIRING_REPLACEMENTS


async def _validate_replacement_users(
    db: AsyncSession,
    *,
    zv1_user_id: uuid.UUID | None,
    zv2_user_id: uuid.UUID | None,
    assignee_ids: list[uuid.UUID] | None,
    required: bool,
) -> None:
    if required and zv1_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ZV1 is required for specifically assigned tasks",
        )

    replacement_user_ids = {user_id for user_id in (zv1_user_id, zv2_user_id) if user_id is not None}
    if not replacement_user_ids:
        return
    if zv1_user_id is not None and zv1_user_id == zv2_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ZV1 and ZV2 must be different users",
        )
    if replacement_user_ids & set(assignee_ids or []):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ZV1 and ZV2 cannot also be assignees",
        )

    replacement_users = (
        await db.execute(select(User).where(User.id.in_(replacement_user_ids)))
    ).scalars().all()
    if len(replacement_users) != len(replacement_user_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Replacement user not found")
    if any(not user.is_active for user in replacement_users):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ZV1 and ZV2 must be active users",
        )


async def _validate_alignment_user_ids(db: AsyncSession, user_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    if not user_ids:
        return []
    users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
    if len(users) != len(set(user_ids)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alignment user not found")
    for u in users:
        if u.role != UserRole.MANAGER:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Alignment users must be MANAGERs")
    # stable unique
    seen: set[uuid.UUID] = set()
    return [uid for uid in user_ids if not (uid in seen or seen.add(uid))]


async def _validate_slot_user_ids(
    db: AsyncSession,
    slots: list[SystemTaskTemplateAssigneeSlotIn] | None,
) -> None:
    if not slots:
        return
    expected = {slot.primary_user_id for slot in slots}
    users = (await db.execute(select(User.id).where(User.id.in_(expected)))).scalars().all()
    if len(set(users)) != len(expected):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignee slot user not found")


async def _assignees_for_tasks(
    db: AsyncSession, task_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[TaskAssigneeOut]]:
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
    assignees: dict[uuid.UUID, list[TaskAssigneeOut]] = {task_id: [] for task_id in task_ids}
    for task_id, user in rows:
        assignees.setdefault(task_id, []).append(_user_to_assignee(user))
    return assignees


async def _alignment_maps_for_templates(
    db: AsyncSession, template_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, list[str]], dict[uuid.UUID, list[uuid.UUID]]]:
    if not template_ids:
        return {}, {}
    role_rows = (
        await db.execute(
            select(SystemTaskTemplateAlignmentRole.template_id, SystemTaskTemplateAlignmentRole.role)
            .where(SystemTaskTemplateAlignmentRole.template_id.in_(template_ids))
        )
    ).all()
    roles_map: dict[uuid.UUID, list[str]] = {}
    for tid, role in role_rows:
        roles_map.setdefault(tid, []).append(role)

    alignment_user_rows = (
        await db.execute(
            select(SystemTaskTemplateAlignmentUser.template_id, SystemTaskTemplateAlignmentUser.user_id)
            .where(SystemTaskTemplateAlignmentUser.template_id.in_(template_ids))
        )
    ).all()
    alignment_users_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    for tid, uid in alignment_user_rows:
        alignment_users_map.setdefault(tid, []).append(uid)

    return roles_map, alignment_users_map


async def _replace_task_assignees(
    db: AsyncSession, task: Task, assignee_ids: list[uuid.UUID]
) -> None:
    await db.execute(delete(TaskAssignee).where(TaskAssignee.task_id == task.id))
    if assignee_ids:
        values = [{"task_id": task.id, "user_id": user_id} for user_id in assignee_ids]
        await db.execute(insert(TaskAssignee), values)


def _dedupe_assignee_ids(values: list[uuid.UUID] | None) -> list[uuid.UUID]:
    seen: set[uuid.UUID] = set()
    return [uid for uid in (values or []) if not (uid in seen or seen.add(uid))]


async def _slots_for_template(
    db: AsyncSession, template_id: uuid.UUID
) -> list[SystemTaskTemplateAssigneeSlot]:
    return (
        await db.execute(
            select(SystemTaskTemplateAssigneeSlot)
            .where(SystemTaskTemplateAssigneeSlot.template_id == template_id)
            .order_by(SystemTaskTemplateAssigneeSlot.created_at.asc())
        )
    ).scalars().all()


def _slot_to_out(slot: SystemTaskTemplateAssigneeSlot) -> SystemTaskTemplateAssigneeSlotOut:
    return SystemTaskTemplateAssigneeSlotOut(
        id=slot.id,
        primary_user_id=slot.primary_user_id,
        is_active=slot.is_active,
    )


async def _sync_template_slots_from_payload(
    db: AsyncSession,
    *,
    template: SystemTaskTemplate,
    assignee_slots: list[SystemTaskTemplateAssigneeSlotIn] | None,
    assignee_ids: list[uuid.UUID] | None,
) -> list[SystemTaskTemplateAssigneeSlot]:
    await ensure_slots_initialized(db)
    if assignee_slots is None:
        if assignee_ids is None:
            return await _slots_for_template(db, template.id)
        assignee_slots = [SystemTaskTemplateAssigneeSlotIn(primary_user_id=uid) for uid in assignee_ids]

    normalized_slots: list[SystemTaskTemplateAssigneeSlotIn] = []
    seen_primary_ids: set[uuid.UUID] = set()
    for item in assignee_slots:
        if item.primary_user_id in seen_primary_ids:
            continue
        seen_primary_ids.add(item.primary_user_id)
        normalized_slots.append(item)

    existing_slots = await _slots_for_template(db, template.id)
    # IMPORTANT:
    # We must not delete slots that have already been referenced by generated tasks.
    # `tasks.system_task_slot_id` is `ON DELETE SET NULL`, but tasks that originate
    # from a system template must keep a non-null slot_id due to the DB check constraint
    # `ck_tasks_system_task_instance_integrity`.
    #
    # So we "soft-remove" by setting `is_active = False`, and we re-use existing slot
    # records whenever possible to keep historical tasks valid.
    existing_by_id: dict[uuid.UUID, SystemTaskTemplateAssigneeSlot] = {s.id: s for s in existing_slots}
    existing_by_primary: dict[uuid.UUID, SystemTaskTemplateAssigneeSlot] = {
        s.primary_user_id: s for s in existing_slots
    }
    used_slot_ids: set[uuid.UUID] = set()

    now = datetime.now(timezone.utc)
    for item in normalized_slots:
        slot: SystemTaskTemplateAssigneeSlot | None = None
        if item.id is not None:
            slot = existing_by_id.get(item.id)
        if slot is None:
            slot = existing_by_primary.get(item.primary_user_id)

        if slot is None:
            slot = SystemTaskTemplateAssigneeSlot(
                id=item.id or uuid.uuid4(),
                template_id=template.id,
                primary_user_id=item.primary_user_id,
                next_run_at=first_run_at(template, now),
                is_active=True if item.is_active is None else item.is_active,
            )
            db.add(slot)
        else:
            slot.primary_user_id = item.primary_user_id
            slot.is_active = True if item.is_active is None else item.is_active
            # Keep slot.next_run_at as-is; only schedule resets should change it.
        used_slot_ids.add(slot.id)

    # Deactivate removed slots instead of deleting them (keeps existing tasks valid).
    for slot in existing_slots:
        if slot.id not in used_slot_ids:
            slot.is_active = False
    await db.flush()
    return await _slots_for_template(db, template.id)


async def _reset_template_slots_next_run_at(
    db: AsyncSession,
    *,
    template: SystemTaskTemplate,
    now: datetime | None = None,
) -> list[SystemTaskTemplateAssigneeSlot]:
    slots = await _slots_for_template(db, template.id)
    if not slots:
        return []
    next_run_at = first_run_at(template, now or datetime.now(timezone.utc))
    for slot in slots:
        slot.next_run_at = next_run_at
    await db.flush()
    return slots


async def _regenerate_template_after_assignment_change(
    db: AsyncSession,
    *,
    template: SystemTaskTemplate,
    now: datetime | None = None,
) -> None:
    """Generate and PV/ZV-reconcile a template immediately after assignees change."""
    now_utc = now or datetime.now(timezone.utc)
    tz = template_tz(template)
    local_today = now_utc.astimezone(tz).date()
    local_day_start = datetime.combine(local_today, dt_time.min, tzinfo=tz).astimezone(timezone.utc)
    range_end = local_today + timedelta(days=max(int(settings.SYSTEM_TASK_GENERATE_AHEAD_DAYS), 0))

    # Rewind to the start of today so an assignee added after the configured
    # due time still receives today's matching occurrence.
    await _reset_template_slots_next_run_at(db, template=template, now=local_day_start)
    await generate_system_task_instances(
        db=db,
        now_utc=now_utc,
        start=local_today,
        end=range_end,
        template_ids=[template.id],
    )
    await reconcile_system_task_assignments_in_range(
        db=db,
        start=local_today,
        end=range_end,
        now_utc=now_utc,
        template_ids=[template.id],
    )


def _task_row_to_out(
    task: Task,
    template: SystemTaskTemplate,
    assignees: list[TaskAssigneeOut],
    user_comment: str | None = None,
    alignment_roles: list[str] | None = None,
    alignment_user_ids: list[uuid.UUID] | None = None,
    occurrence_date: date | None = None,
    next_occurrence_date_value: date | None = None,
    effective_occurrence_date: date | None = None,
    occurrence_status: str | None = None,  # NEW: occurrence status for current user
) -> SystemTaskOut:
    priority_value = task.priority or TaskPriority.NORMAL
    
    # Use occurrence status if provided, otherwise use task status
    # Map occurrence status to TaskStatus
    if occurrence_status:
        if occurrence_status == "DONE":
            final_status = TaskStatus.DONE
        elif occurrence_status == "NOT_DONE":
            final_status = TaskStatus.NOT_DONE
        elif occurrence_status == "SKIPPED":
            final_status = TaskStatus.NOT_DONE
        elif occurrence_status == "OPEN":
            final_status = TaskStatus.TODO
        else:
            final_status = task.status
    else:
        final_status = task.status
    
    return SystemTaskOut(
        id=task.id,
        template_id=template.id,
        title=task.title,
        description=task.description,
        internal_notes=template.internal_notes,
        department_id=task.department_id,
        default_assignee_id=task.assigned_to,
        assignees=assignees,
        scope=template.scope,
        frequency=template.frequency,
        day_of_week=template.day_of_week,
        days_of_week=template.days_of_week,
        day_of_month=template.day_of_month,
        month_of_year=template.month_of_year,
        occurrence_date=occurrence_date,
        next_occurrence_date=next_occurrence_date_value,
        effective_occurrence_date=effective_occurrence_date,
        priority=priority_value,
        finish_period=task.finish_period,
        start_date=task.start_date,
        due_date=task.due_date,
        status=final_status,
        is_active=task.is_active,
        user_comment=user_comment,
        requires_alignment=bool(getattr(template, "requires_alignment", False)),
        alignment_time=getattr(template, "alignment_time", None),
        show_in_weekly_planner=bool(getattr(template, "show_in_weekly_planner", False)),
        alignment_roles=alignment_roles,
        alignment_user_ids=alignment_user_ids,
        created_by=task.created_by,
        approval_status=_template_approval_status(template),
        created_at=task.created_at,
    )


async def _template_to_out(
    db: AsyncSession,
    *,
    template: SystemTaskTemplate,
    user_id: uuid.UUID | None,
    occurrence_date: date | None = None,
    next_occurrence_date_value: date | None = None,
    effective_occurrence_date: date | None = None,
    alignment_roles: list[str] | None = None,
    alignment_user_ids: list[uuid.UUID] | None = None,
) -> SystemTaskOut:
    assignees_list: list[TaskAssigneeOut] = []
    department_ids_set: set[uuid.UUID] = set()
    if template.assignee_ids:
        assignee_users = (
            await db.execute(select(User).where(User.id.in_(template.assignee_ids)))
        ).scalars().all()
        assignees_list = [_user_to_assignee(user) for user in assignee_users]
        department_ids_set = {user.department_id for user in assignee_users if user.department_id is not None}
    elif template.default_assignee_id:
        assignee_user = (
            await db.execute(select(User).where(User.id == template.default_assignee_id))
        ).scalar_one_or_none()
        if assignee_user:
            assignees_list = [_user_to_assignee(assignee_user)]
            if assignee_user.department_id:
                department_ids_set.add(assignee_user.department_id)

    if template.department_id and template.department_id not in department_ids_set:
        department_ids_set.add(template.department_id)
    department_ids = sorted(list(department_ids_set)) if department_ids_set else None

    task_out = SystemTaskOut(
        id=template.id,
        template_id=template.id,
        title=template.title,
        description=template.description,
        internal_notes=template.internal_notes,
        department_id=template.department_id,
        default_assignee_id=template.default_assignee_id,
        assignees=assignees_list,
        scope=SystemTaskScope(template.scope),
        frequency=FrequencyType(template.frequency),
        day_of_week=template.day_of_week,
        days_of_week=template.days_of_week,
        day_of_month=template.day_of_month,
        month_of_year=template.month_of_year,
        occurrence_date=occurrence_date,
        next_occurrence_date=next_occurrence_date_value,
        effective_occurrence_date=effective_occurrence_date,
        priority=TaskPriority(template.priority) if template.priority else TaskPriority.NORMAL,
        finish_period=TaskFinishPeriod(template.finish_period) if template.finish_period else None,
        start_date=None,
        due_date=None,
        status=TaskStatus.TODO,
        is_active=template.is_active,
        user_comment=None,
        requires_alignment=getattr(template, "requires_alignment", False),
        alignment_time=getattr(template, "alignment_time", None),
        show_in_weekly_planner=bool(getattr(template, "show_in_weekly_planner", False)),
        alignment_roles=alignment_roles,
        alignment_user_ids=alignment_user_ids,
        created_by=template.created_by_user_id or user_id,
        approval_status=_template_approval_status(template),
        created_at=template.created_at,
    )
    task_out.department_ids = department_ids
    return task_out


async def _template_definition_to_out(
    db: AsyncSession,
    *,
    template: SystemTaskTemplate,
) -> SystemTaskTemplateOut:
    role_map, alignment_user_map = await _alignment_maps_for_templates(db, [template.id])
    slots = await _slots_for_template(db, template.id)
    assignee_ids = template.assignee_ids or ([template.default_assignee_id] if template.default_assignee_id else [])
    assignee_users = (
        (await db.execute(select(User).where(User.id.in_(assignee_ids)))).scalars().all()
        if assignee_ids
        else []
    )
    assignee_user_map = {user.id: user for user in assignee_users}

    department_ids = sorted(
        {
            user.department_id
            for user_id in assignee_ids
            for user in [assignee_user_map.get(user_id)]
            if user is not None and user.department_id is not None
        }
    ) or None

    return SystemTaskTemplateOut(
        id=template.id,
        title=template.title,
        description=template.description,
        internal_notes=template.internal_notes,
        department_id=template.department_id,
        department_ids=department_ids,
        default_assignee_id=template.default_assignee_id,
        assignee_ids=template.assignee_ids,
        zv1_user_id=getattr(template, "zv1_user_id", None),
        zv2_user_id=getattr(template, "zv2_user_id", None),
        assignees=[
            _user_to_assignee(assignee_user_map[user_id])
            for user_id in assignee_ids
            if user_id in assignee_user_map
        ],
        assignee_slots=[_slot_to_out(slot) for slot in slots],
        scope=SystemTaskScope(template.scope),
        frequency=FrequencyType(template.frequency),
        day_of_week=template.day_of_week,
        days_of_week=template.days_of_week,
        day_of_month=template.day_of_month,
        month_of_year=template.month_of_year,
        timezone=template.timezone or settings.APP_TIMEZONE,
        due_time=template.due_time,
        lookahead=template.lookahead,
        interval=template.interval,
        apply_from=template.apply_from,
        duration_days=template.duration_days,
        priority=TaskPriority(template.priority) if template.priority else None,
        finish_period=TaskFinishPeriod(template.finish_period) if template.finish_period else None,
        requires_alignment=bool(getattr(template, "requires_alignment", False)),
        alignment_time=getattr(template, "alignment_time", None),
        show_in_weekly_planner=bool(getattr(template, "show_in_weekly_planner", False)),
        alignment_roles=role_map.get(template.id),
        alignment_user_ids=alignment_user_map.get(template.id),
        is_active=template.is_active,
        created_by_user_id=template.created_by_user_id,
        approval_status=_template_approval_status(template),
        approved_by_user_id=template.approved_by_user_id,
        approved_at=template.approved_at,
        rejected_by_user_id=template.rejected_by_user_id,
        rejected_at=template.rejected_at,
        rejection_reason=template.rejection_reason,
        created_at=template.created_at,
    )


def _previous_occurrence_date(template: SystemTaskTemplate, target: date) -> date:
    return previous_occurrence_date(template, target)


def _template_zoneinfo(template: SystemTaskTemplate):
    fallback_tz = settings.APP_TIMEZONE
    tz_name = (getattr(template, "timezone", None) or "").strip() or fallback_tz
    if ZoneInfo is None:
        return timezone.utc, fallback_tz
    try:
        return ZoneInfo(tz_name), tz_name
    except Exception:
        try:
            return ZoneInfo(fallback_tz), fallback_tz
        except Exception:
            return timezone.utc, fallback_tz


def _local_day_utc_bounds(local_day: date, tzinfo) -> tuple[datetime, datetime]:
    local_start = datetime.combine(local_day, dt_time.min, tzinfo=tzinfo)
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def _app_local_today() -> date:
    try:
        return datetime.now(ZoneInfo(settings.APP_TIMEZONE)).date()
    except Exception:
        return datetime.now(timezone.utc).date()


def _local_date(value: datetime | None, tzinfo) -> date | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(tzinfo).date()


def _sync_system_task_due_date_to_done_day(task: Task, completed_at: datetime, tzinfo) -> None:
    if _local_date(task.due_date, tzinfo) != _local_date(completed_at, tzinfo):
        if task.due_date is not None and task.original_due_date is None:
            task.original_due_date = task.due_date
        task.due_date = completed_at
    if task.start_date is not None and _local_date(task.start_date, tzinfo) > _local_date(completed_at, tzinfo):
        task.start_date = completed_at


async def _meeting_system_task_rows(
    db: AsyncSession,
    *,
    base_date: date,
    assigned_to: uuid.UUID | None,
    department_id: uuid.UUID | None,
    only_active: bool,
    include_overdue: bool,
) -> list[tuple[SystemTaskTemplate, Task, date]]:
    template = (
        await db.execute(
            select(SystemTaskTemplate).where(SystemTaskTemplate.trigger_type == EXTERNAL_MEETING_TRIGGER_TYPE)
        )
    ).scalar_one_or_none()
    if template is None:
        return []

    stmt = (
        select(Task)
        .options(noload(Task.assignees))
        .where(Task.system_template_origin_id == template.id)
        .where(Task.meeting_system_task_kind == EXTERNAL_MEETING_TASK_KIND)
        .where(Task.meeting_occurrence_date.is_not(None))
    )
    if include_overdue:
        stmt = stmt.where(or_(Task.meeting_occurrence_date == base_date, and_(Task.meeting_occurrence_date < base_date, Task.status != TaskStatus.DONE)))
    else:
        stmt = stmt.where(Task.meeting_occurrence_date == base_date)
    if assigned_to is not None:
        stmt = stmt.where(Task.assigned_to == assigned_to)
    if department_id is not None:
        stmt = stmt.where(Task.department_id == department_id)
    if only_active:
        stmt = stmt.where(Task.is_active.is_(True))
    tasks = (await db.execute(stmt.order_by(Task.created_at.desc().nullslast()))).scalars().all()
    return [
        (template, task, task.meeting_occurrence_date or base_date)
        for task in tasks
    ]


@router.get("", response_model=list[SystemTaskOut])
async def list_system_tasks(
    department_id: uuid.UUID | None = None,
    only_active: bool = False,
    assigned_to: uuid.UUID | None = None,  # Filter by user for "My View"
    occurrence_date: date | None = None,
    include_overdue: bool = False,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[SystemTaskOut]:
    local_today = _app_local_today()
    template_stmt = (
        select(SystemTaskTemplate)
        .where(SystemTaskTemplate.trigger_type.is_(None))
        .where(SystemTaskTemplate.approval_status == CommonApprovalStatus.approved)
        .order_by(SystemTaskTemplate.created_at.desc())
    )

    if department_id is not None:
        # Allow all users to view system tasks from any department (for department kanban views)
        template_stmt = template_stmt.where(
            or_(
                and_(
                    SystemTaskTemplate.scope == SystemTaskScope.DEPARTMENT.value,
                    SystemTaskTemplate.department_id == department_id,
                ),
                SystemTaskTemplate.scope == SystemTaskScope.ALL.value,
            )
        )
    # When no department_id is provided (main system tasks view), show all system tasks to all users
    # No filtering needed - everyone can see all system tasks

    all_templates = (await db.execute(template_stmt)).scalars().all()

    base_date = occurrence_date or date.today()
    templates = all_templates
    if occurrence_date is not None:
        templates = [tmpl for tmpl in templates if matches_template_date(tmpl, base_date)]

    template_ids = [t.id for t in templates]
    all_template_ids = [t.id for t in all_templates]
    occurrence_date_map: dict[uuid.UUID, date] = {
        tmpl.id: (
            base_date
            if occurrence_date is not None
            else (base_date if matches_template_date(tmpl, base_date) else _previous_occurrence_date(tmpl, base_date))
        )
        for tmpl in all_templates
    }
    next_occurrence_date_map: dict[uuid.UUID, date] = {
        tmpl.id: next_occurrence_date(tmpl, base_date)
        for tmpl in all_templates
    }
    effective_occurrence_date_map: dict[uuid.UUID, date] = dict(occurrence_date_map)

    # Build per-timezone UTC bounds and fetch only the matching day-window tasks.
    bucket_template_ids: dict[tuple[str, date], list[uuid.UUID]] = defaultdict(list)
    bucket_utc_bounds: dict[tuple[str, date], tuple[datetime, datetime]] = {}
    for tmpl in templates:
        tzinfo, tz_name = _template_zoneinfo(tmpl)
        occ = occurrence_date_map[tmpl.id]
        bucket_key = (tz_name, occ)
        bucket_template_ids[bucket_key].append(tmpl.id)
        if bucket_key not in bucket_utc_bounds:
            bucket_utc_bounds[bucket_key] = _local_day_utc_bounds(occ, tzinfo)

    range_clauses = []
    for bucket_key, tmpl_ids in bucket_template_ids.items():
        start_utc, end_utc = bucket_utc_bounds[bucket_key]
        range_clauses.append(
            and_(
                Task.system_template_origin_id.in_(tmpl_ids),
                Task.origin_run_at >= start_utc,
                Task.origin_run_at < end_utc,
            )
        )

    tasks: list[Task] = []
    if range_clauses:
        task_stmt = (
            select(Task)
            # Assignees are loaded explicitly below; disabling implicit relationship loading
            # avoids async lazy-loads that can raise MissingGreenlet in production.
            .options(noload(Task.assignees))
            .where(Task.origin_run_at.is_not(None))
            .where(or_(*range_clauses))
            .order_by(Task.is_active.desc().nullslast(), Task.created_at.desc().nullslast())
        )
        if assigned_to is not None:
            task_stmt = task_stmt.where(Task.assigned_to == assigned_to)
        if only_active:
            task_stmt = task_stmt.where(Task.is_active.is_(True))
        tasks = (await db.execute(task_stmt)).scalars().all()

    template_assignees_map: dict[uuid.UUID, set[uuid.UUID]] = {}
    for tmpl in all_templates:
        assignee_ids = getattr(tmpl, "assignee_ids", None) or []
        if not assignee_ids and tmpl.default_assignee_id:
            assignee_ids = [tmpl.default_assignee_id]
        template_assignees_map[tmpl.id] = set(assignee_ids)

    # Keep only task instances that belong to configured template assignees.
    filtered_tasks: list[Task] = []
    for task in tasks:
        if task.system_template_origin_id is None:
            continue
        allowed_ids = template_assignees_map.get(task.system_template_origin_id, set())
        if not allowed_ids:
            continue
        if task.assigned_to and task.assigned_to in allowed_ids:
            filtered_tasks.append(task)

    template_by_id = {t.id: t for t in templates}
    rows: list[tuple[SystemTaskTemplate, Task | None, date | None]] = []
    template_tasks_map_for_rows: dict[uuid.UUID, list[Task]] = defaultdict(list)
    for task in filtered_tasks:
        if task.system_template_origin_id in template_by_id:
            template_tasks_map_for_rows[task.system_template_origin_id].append(task)
    for tmpl in templates:
        tmpl_tasks = template_tasks_map_for_rows.get(tmpl.id, [])
        if tmpl_tasks:
            for task in tmpl_tasks:
                rows.append((tmpl, task, occurrence_date_map.get(tmpl.id)))

    if include_overdue and occurrence_date is not None and all_template_ids:
        overdue_local_date = cast(
            func.timezone(func.coalesce(SystemTaskTemplate.timezone, settings.APP_TIMEZONE), Task.origin_run_at),
            SQLDate,
        )
        overdue_stmt = (
            select(Task, SystemTaskTemplate, overdue_local_date.label("task_date"))
            .join(SystemTaskTemplate, Task.system_template_origin_id == SystemTaskTemplate.id)
            .options(noload(Task.assignees))
            .where(Task.system_template_origin_id.in_(all_template_ids))
            .where(Task.origin_run_at.is_not(None))
            .where(overdue_local_date < base_date)
            .where(Task.status != TaskStatus.DONE)
            .order_by(overdue_local_date.desc(), Task.created_at.desc().nullslast())
        )
        if assigned_to is not None:
            overdue_stmt = overdue_stmt.where(Task.assigned_to == assigned_to)
        if only_active:
            overdue_stmt = overdue_stmt.where(Task.is_active.is_(True))
        overdue_rows = (await db.execute(overdue_stmt)).all()
        existing_task_ids = {task.id for _, task, _ in rows if task is not None}
        for task, template, task_date in overdue_rows:
            if task.id in existing_task_ids or task.system_template_origin_id is None:
                continue
            allowed_ids = template_assignees_map.get(task.system_template_origin_id, set())
            if not allowed_ids:
                continue
            if not task.assigned_to or task.assigned_to not in allowed_ids:
                continue
            filtered_tasks.append(task)
            rows.append((template, task, task_date))
            existing_task_ids.add(task.id)

    meeting_rows = await _meeting_system_task_rows(
        db,
        base_date=base_date,
        assigned_to=assigned_to,
        department_id=department_id,
        only_active=only_active,
        include_overdue=include_overdue and occurrence_date is not None,
    )
    if meeting_rows:
        existing_task_ids = {task.id for _, task, _ in rows if task is not None}
        for template, task, task_date in meeting_rows:
            if task.id in existing_task_ids:
                continue
            rows.append((template, task, task_date))
            filtered_tasks.append(task)
            existing_task_ids.add(task.id)

    if not rows and assigned_to is not None:
        return []

    # Return all tasks for each template (no de-duplication)
    task_ids = [task.id for template, task, _ in rows if task is not None]
    assignee_map = await _assignees_for_tasks(db, task_ids)

    fallback_ids = [
        task.assigned_to
        for task in filtered_tasks
        if task is not None and task.assigned_to is not None and not assignee_map.get(task.id)
    ]
    if fallback_ids:
        fallback_users = (
            await db.execute(select(User).where(User.id.in_(fallback_ids)))
        ).scalars().all()
        fallback_map = {user.id: user for user in fallback_users}
        for task in filtered_tasks:
            if assignee_map.get(task.id):
                continue
            if task.assigned_to in fallback_map:
                assignee_map[task.id] = [_user_to_assignee(fallback_map[task.assigned_to])]

    # Fetch user comments for all tasks
    user_comment_map: dict[uuid.UUID, str | None] = {}
    if user.id and task_ids:
        comment_rows = (
            await db.execute(
                select(TaskUserComment.task_id, TaskUserComment.comment)
                .where(TaskUserComment.task_id.in_(task_ids))
                .where(TaskUserComment.user_id == user.id)
            )
        ).all()
        user_comment_map = {task_id: comment for task_id, comment in comment_rows}

    roles_map, alignment_users_map = await _alignment_maps_for_templates(db, all_template_ids)

    # Department-scoped lists and My View should return real task rows only.
    if assigned_to is not None or department_id is not None:
        result = []
        for template, task, row_date in rows:
            if task is None:
                continue
            
            task_assignees = assignee_map.get(task.id, [])
            task_out = _task_row_to_out(
                task,
                template,
                task_assignees,
                user_comment_map.get(task.id),
                roles_map.get(template.id),
                alignment_users_map.get(template.id),
                occurrence_date=row_date or occurrence_date_map.get(template.id),
                next_occurrence_date_value=next_occurrence_date_map.get(template.id),
                effective_occurrence_date=row_date or effective_occurrence_date_map.get(template.id),
            )
            task_out.department_ids = [task.department_id] if task.department_id else None
            result.append(task_out)
        result.sort(key=lambda item: item.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return result

    # Group tasks by template_id to collect all departments (for Department View)
    template_tasks_map: dict[uuid.UUID, list[tuple[Task, SystemTaskTemplate]]] = {}

    meeting_result_rows: list[tuple[SystemTaskTemplate, Task, date | None]] = []
    for template, task, row_date in rows:
        if getattr(template, "trigger_type", None) == EXTERNAL_MEETING_TRIGGER_TYPE:
            if task is not None:
                meeting_result_rows.append((template, task, row_date))
            continue
        if template.id not in template_tasks_map:
            template_tasks_map[template.id] = []
        template_tasks_map[template.id].append((task, template))

    result = []

    # Process templates with tasks - group by template and collect all departments
    for template_id, task_list in template_tasks_map.items():
        template = task_list[0][1]  # Get template from first task
        # Collect all unique department IDs from tasks
        department_ids_set = {task.department_id for task, _ in task_list if task.department_id is not None}
        department_ids = sorted(list(department_ids_set)) if department_ids_set else None
        
        # Collect all unique assignees from all tasks
        all_assignees_map = {}
        for task, _ in task_list:
            task_assignees = assignee_map.get(task.id, [])
            for assignee in task_assignees:
                if assignee.id not in all_assignees_map:
                    all_assignees_map[assignee.id] = assignee
        all_assignees = list(all_assignees_map.values())
        
        # Use the first task for the main response, but include all department_ids and all assignees
        first_task, _ = task_list[0]
        task_out = _task_row_to_out(
            first_task,
            template,
            all_assignees,
            user_comment_map.get(first_task.id),
            roles_map.get(template.id),
            alignment_users_map.get(template.id),
            occurrence_date=occurrence_date_map.get(template.id),
            next_occurrence_date_value=next_occurrence_date_map.get(template.id),
            effective_occurrence_date=effective_occurrence_date_map.get(template.id),
        )
        # Add department_ids to the response
        task_out.department_ids = department_ids if department_ids else None
        result.append(task_out)

    for template, task, row_date in meeting_result_rows:
        task_assignees = assignee_map.get(task.id, [])
        task_out = _task_row_to_out(
            task,
            template,
            task_assignees,
            user_comment_map.get(task.id),
            roles_map.get(template.id),
            alignment_users_map.get(template.id),
            occurrence_date=row_date or task.meeting_occurrence_date or occurrence_date_map.get(template.id),
            next_occurrence_date_value=None,
            effective_occurrence_date=row_date or task.meeting_occurrence_date,
        )
        task_out.department_ids = [task.department_id] if task.department_id else None
        result.append(task_out)

    rendered_template_ids = {item.template_id for item in result if item.template_id is not None}
    missing_templates = [tmpl for tmpl in templates if tmpl.id not in rendered_template_ids]
    for template in missing_templates:
        task_out = await _template_to_out(
            db,
            template=template,
            user_id=user.id,
            occurrence_date=occurrence_date_map.get(template.id),
            next_occurrence_date_value=next_occurrence_date_map.get(template.id),
            effective_occurrence_date=effective_occurrence_date_map.get(template.id),
            alignment_roles=roles_map.get(template.id),
            alignment_user_ids=alignment_users_map.get(template.id),
        )
        result.append(task_out)

    result.sort(key=lambda item: item.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    return result


@router.get("/templates", response_model=list[SystemTaskTemplateOut])
async def list_system_task_templates(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[SystemTaskTemplateOut]:
    templates = (
        await db.execute(
            select(SystemTaskTemplate)
            .where(SystemTaskTemplate.trigger_type.is_(None))
            .order_by(SystemTaskTemplate.created_at.desc())
        )
    ).scalars().all()
    if not templates:
        return []

    template_ids = [t.id for t in templates]
    role_rows = []
    if template_ids:
        role_rows = (
            await db.execute(
                select(SystemTaskTemplateAlignmentRole.template_id, SystemTaskTemplateAlignmentRole.role)
                .where(SystemTaskTemplateAlignmentRole.template_id.in_(template_ids))
            )
        ).all()
    roles_map: dict[uuid.UUID, list[str]] = {}
    for tid, role in role_rows:
        roles_map.setdefault(tid, []).append(role)

    alignment_user_rows = []
    if template_ids:
        alignment_user_rows = (
            await db.execute(
                select(SystemTaskTemplateAlignmentUser.template_id, SystemTaskTemplateAlignmentUser.user_id).where(
                    SystemTaskTemplateAlignmentUser.template_id.in_(template_ids)
                )
            )
        ).all()
    alignment_users_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    for tid, uid in alignment_user_rows:
        alignment_users_map.setdefault(tid, []).append(uid)

    slot_rows = (
        await db.execute(select(SystemTaskTemplateAssigneeSlot).where(SystemTaskTemplateAssigneeSlot.template_id.in_(template_ids)))
    ).scalars().all() if template_ids else []
    slots_map: dict[uuid.UUID, list[SystemTaskTemplateAssigneeSlotOut]] = {}
    for slot in slot_rows:
        slots_map.setdefault(slot.template_id, []).append(_slot_to_out(slot))

    assignee_user_ids: set[uuid.UUID] = set()
    for template in templates:
        if template.assignee_ids:
            assignee_user_ids.update(template.assignee_ids)
        elif template.default_assignee_id:
            assignee_user_ids.add(template.default_assignee_id)

    assignee_users = (
        (await db.execute(select(User).where(User.id.in_(assignee_user_ids)))).scalars().all()
        if assignee_user_ids
        else []
    )
    assignee_user_map = {row.id: row for row in assignee_users}

    return [
        SystemTaskTemplateOut(
            id=t.id,
            title=t.title,
            description=t.description,
            internal_notes=t.internal_notes,
            department_id=t.department_id,
            department_ids=sorted(
                {
                    user.department_id
                    for user_id in (t.assignee_ids or ([t.default_assignee_id] if t.default_assignee_id else []))
                    for user in [assignee_user_map.get(user_id)]
                    if user is not None and user.department_id is not None
                }
            )
            or None,
            default_assignee_id=t.default_assignee_id,
            assignee_ids=t.assignee_ids,
            zv1_user_id=getattr(t, "zv1_user_id", None),
            zv2_user_id=getattr(t, "zv2_user_id", None),
            assignees=[
                _user_to_assignee(assignee_user_map[user_id])
                for user_id in (t.assignee_ids or ([t.default_assignee_id] if t.default_assignee_id else []))
                if user_id in assignee_user_map
            ],
            scope=SystemTaskScope(t.scope),
            frequency=FrequencyType(t.frequency),
            day_of_week=t.day_of_week,
            days_of_week=t.days_of_week,
            day_of_month=t.day_of_month,
            month_of_year=t.month_of_year,
            timezone=t.timezone or settings.APP_TIMEZONE,
            due_time=t.due_time,
            lookahead=t.lookahead,
            interval=t.interval,
            apply_from=t.apply_from,
            duration_days=t.duration_days,
            priority=TaskPriority(t.priority) if t.priority else None,
            finish_period=TaskFinishPeriod(t.finish_period) if t.finish_period else None,
            requires_alignment=bool(getattr(t, "requires_alignment", False)),
            alignment_time=getattr(t, "alignment_time", None),
            show_in_weekly_planner=bool(getattr(t, "show_in_weekly_planner", False)),
            alignment_roles=roles_map.get(t.id),
            alignment_user_ids=alignment_users_map.get(t.id),
            assignee_slots=slots_map.get(t.id, []),
            is_active=t.is_active,
            created_by_user_id=t.created_by_user_id,
            approval_status=_template_approval_status(t),
            approved_by_user_id=t.approved_by_user_id,
            approved_at=t.approved_at,
            rejected_by_user_id=t.rejected_by_user_id,
            rejected_at=t.rejected_at,
            rejection_reason=t.rejection_reason,
            created_at=t.created_at,
        )
        for t in templates
    ]


class SystemTaskOccurrenceUpdate(BaseModel):
    template_id: uuid.UUID
    occurrence_date: date
    status: str
    comment: str | None = None


@router.post("/occurrences", status_code=status.HTTP_200_OK)
async def set_system_task_occurrence_status(
    payload: SystemTaskOccurrenceUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    allowed = {"OPEN", "DONE", "NOT_DONE", "SKIPPED"}
    if payload.status not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")

    tmpl = (
        await db.execute(select(SystemTaskTemplate).where(SystemTaskTemplate.id == payload.template_id))
    ).scalar_one_or_none()
    if tmpl is None:
        # Some clients might send a task ID instead of a template ID.
        task = (
            await db.execute(select(Task).where(Task.id == payload.template_id))
        ).scalar_one_or_none()
        if task and task.system_template_origin_id:
            tmpl = (
                await db.execute(
                    select(SystemTaskTemplate).where(SystemTaskTemplate.id == task.system_template_origin_id)
                )
            ).scalar_one_or_none()
        if tmpl is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    # Minimal permissions: user can update their own occurrence; admins/managers can also do it.
    if user.role not in (UserRole.ADMIN, UserRole.MANAGER, UserRole.STAFF):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    # Check if user is in the assignee list
    assignee_ids = getattr(tmpl, 'assignee_ids', None) or []
    if not assignee_ids and tmpl.default_assignee_id:
        assignee_ids = [tmpl.default_assignee_id]
    
    if user.id not in assignee_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="You are not assigned to this system task"
        )

    task_local_date = cast(func.timezone(tmpl.timezone or settings.APP_TIMEZONE, Task.origin_run_at), SQLDate)
    task = (
        await db.execute(
            select(Task)
            .where(Task.system_template_origin_id == tmpl.id)
            .where(Task.assigned_to == user.id)
            .where(task_local_date == payload.occurrence_date)
            .order_by(Task.created_at.desc())
        )
    ).scalars().first()
    if task is None:
        fallback_date = previous_occurrence_date(tmpl, payload.occurrence_date)
        task = (
            await db.execute(
                select(Task)
                .where(Task.system_template_origin_id == tmpl.id)
                .where(Task.assigned_to == user.id)
                .where(task_local_date == fallback_date)
                .order_by(Task.created_at.desc())
            )
        ).scalars().first()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task instance not available for this user/date. Please refresh and try again.",
        )

    await ensure_daily_baselines_for_departments(
        db=db, department_ids={task.department_id, user.department_id},
        day=payload.occurrence_date, actor=user,
    )
    status_before = _enum_value(task.status)

    now = datetime.now(timezone.utc)
    if payload.status == "DONE":
        if not (payload.comment and payload.comment.strip()):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "RLZ_TASK_COMMENT_REQUIRED",
                    "message": "Para mbylljes, shto komentin për rezultatin e kësaj detyre.",
                },
            )
        task.status = TaskStatus.DONE
        task.completed_at = now
        task_tz, _ = _template_zoneinfo(tmpl)
        _sync_system_task_due_date_to_done_day(task, now, task_tz)
    elif payload.status in ("NOT_DONE", "SKIPPED"):
        task.status = TaskStatus.NOT_DONE
        task.completed_at = now
    else:
        task.status = TaskStatus.TODO
        task.completed_at = None

    if payload.comment is not None:
        user_comment = (
            await db.execute(
                select(TaskUserComment)
                .where(TaskUserComment.task_id == task.id)
                .where(TaskUserComment.user_id == user.id)
            )
        ).scalar_one_or_none()
        if user_comment is None:
            db.add(TaskUserComment(task_id=task.id, user_id=user.id, comment=payload.comment))
        else:
            user_comment.comment = payload.comment

    record_task_semantic_events(
        db=db, task_id=task.id, actor_user_id=user.id,
        before={"status": status_before}, after={"status": _enum_value(task.status)},
        old_assignee_ids={task.assigned_to} if task.assigned_to else set(),
        new_assignee_ids={task.assigned_to} if task.assigned_to else set(),
    )

    await db.commit()
    return {"ok": True}


class SystemTaskOccurrenceDateOverrideIn(BaseModel):
    template_id: uuid.UUID
    source_occurrence_date: date
    target_occurrence_date: date
    postponement_reason_code: str | None = Field(default=None, max_length=40)
    postponement_comment: str | None = Field(default=None, max_length=10000)


def _can_override_system_occurrence_date(user: User, template: SystemTaskTemplate) -> bool:
    assignee_ids = getattr(template, "assignee_ids", None) or []
    if not assignee_ids and template.default_assignee_id:
        assignee_ids = [template.default_assignee_id]
    if user.id in assignee_ids:
        return True
    if user.role in (UserRole.ADMIN, UserRole.MANAGER):
        return True
    return False


@router.patch("/occurrence-date", response_model=SystemTaskOut)
async def override_system_task_occurrence_date(
    payload: SystemTaskOccurrenceDateOverrideIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> SystemTaskOut:
    tmpl = (
        await db.execute(select(SystemTaskTemplate).where(SystemTaskTemplate.id == payload.template_id))
    ).scalar_one_or_none()
    if tmpl is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    if not _can_override_system_occurrence_date(user, tmpl):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    if payload.source_occurrence_date == payload.target_occurrence_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Target date must be different from source date")

    task_local_date = cast(func.timezone(tmpl.timezone or settings.APP_TIMEZONE, Task.origin_run_at), SQLDate)
    task = (
        await db.execute(
            select(Task)
            .where(Task.system_template_origin_id == tmpl.id)
            .where(Task.assigned_to == user.id)
            .where(task_local_date == payload.source_occurrence_date)
            .order_by(Task.created_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if task is None and user.role in (UserRole.ADMIN, UserRole.MANAGER):
        task = (
            await db.execute(
                select(Task)
                .where(Task.system_template_origin_id == tmpl.id)
                .where(task_local_date == payload.source_occurrence_date)
                .order_by(Task.created_at.desc())
                .limit(1)
            )
        ).scalars().first()

    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found for template")
    if task.status == TaskStatus.DONE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Done system tasks cannot be edited")

    old_due_date = task.due_date or task.origin_run_at or task.start_date
    if old_due_date is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task does not have a date to move")
    day_shift = (payload.target_occurrence_date - payload.source_occurrence_date).days
    new_due_date = old_due_date + timedelta(days=day_shift)
    postponement = await check_task_postponement_explanation(
        db,
        task=SimpleNamespace(id=task.id, title=task.title, project_id=task.project_id, start_date=task.start_date, due_date=old_due_date),
        updates={"due_date": new_due_date}, reason_code=payload.postponement_reason_code, comment=payload.postponement_comment,
    )
    await ensure_daily_baselines_for_departments(
        db=db, department_ids={task.department_id},
        day=payload.source_occurrence_date, actor=user,
    )
    # Match the baseline-before-task-lock order of the other mutation routes.
    await db.refresh(task, with_for_update=True)
    if task.status == TaskStatus.DONE:
        raise HTTPException(status_code=400, detail="Done system tasks cannot be edited")
    old_due_date = task.due_date or task.origin_run_at or task.start_date
    if old_due_date is None:
        raise HTTPException(status_code=400, detail="Task does not have a date to move")
    new_due_date = old_due_date + timedelta(days=day_shift)
    postponement = await check_task_postponement_explanation(
        db,
        task=SimpleNamespace(id=task.id, title=task.title, project_id=task.project_id, start_date=task.start_date, due_date=old_due_date),
        updates={"due_date": new_due_date}, reason_code=payload.postponement_reason_code, comment=payload.postponement_comment,
    )
    status_before = _enum_value(task.status)
    if task.due_date is not None and new_due_date != task.due_date and task.original_due_date is None:
        task.original_due_date = task.due_date
    task.due_date = new_due_date
    task.status = TaskStatus.TODO
    task.completed_at = None

    record_task_semantic_events(
        db=db, task_id=task.id, actor_user_id=user.id,
        before={"due_date": old_due_date.isoformat(), "status": status_before},
        after={"due_date": new_due_date.isoformat(), "status": _enum_value(task.status)},
        old_assignee_ids={task.assigned_to} if task.assigned_to else set(),
        new_assignee_ids={task.assigned_to} if task.assigned_to else set(),
        **postponement,
    )
    await save_postponement_daily_explanation(
        db, task_id=task.id, user_ids={task.assigned_to or user.id}, explanation=postponement,
    )

    await db.commit()
    await db.refresh(task)

    assignee_map = await _assignees_for_tasks(db, [task.id])
    if not assignee_map.get(task.id) and task.assigned_to is not None:
        assigned_user = (await db.execute(select(User).where(User.id == task.assigned_to))).scalar_one_or_none()
        if assigned_user is not None:
            assignee_map[task.id] = [_user_to_assignee(assigned_user)]
    roles_map, alignment_users_map = await _alignment_maps_for_templates(db, [tmpl.id])

    return _task_row_to_out(
        task,
        tmpl,
        assignee_map.get(task.id, []),
        None,
        roles_map.get(tmpl.id),
        alignment_users_map.get(tmpl.id),
        occurrence_date=payload.source_occurrence_date,
        next_occurrence_date_value=payload.source_occurrence_date,
        effective_occurrence_date=payload.target_occurrence_date,
    )


@router.post("", response_model=SystemTaskTemplateOut, status_code=status.HTTP_201_CREATED)
async def create_system_task_template(
    payload: SystemTaskTemplateCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> SystemTaskTemplateOut:
    if payload.frequency == FrequencyType.WEEKLY and payload.day_of_week is None and not payload.days_of_week:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Weekday is required for weekly tasks",
        )
    if payload.frequency == FrequencyType.MONTHLY and payload.day_of_month is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Day of month is required for monthly tasks",
        )
    if payload.frequency == FrequencyType.YEARLY:
        if payload.day_of_month is None or payload.month_of_year is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Day of month and month are required for yearly tasks",
            )
        if payload.month_of_year < 1 or payload.month_of_year > 12:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid start month")
    if payload.frequency in (FrequencyType.THREE_MONTHS, FrequencyType.SIX_MONTHS):
        if payload.day_of_month is None or payload.month_of_year is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Day of month and start month are required for 3/6-month tasks",
            )
        if payload.month_of_year < 1 or payload.month_of_year > 12:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid start month")
    days_of_week = payload.days_of_week
    if days_of_week is None and payload.day_of_week is not None:
        days_of_week = [payload.day_of_week]
    if days_of_week:
        cleaned_days = sorted({int(day) for day in days_of_week})
        if any(day < 0 or day > 6 for day in cleaned_days):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid weekday")
        days_of_week = cleaned_days

    assignee_slots = payload.assignee_slots
    await _validate_slot_user_ids(db, assignee_slots)
    assignee_ids = None
    if assignee_slots is not None:
        assignee_ids = _dedupe_assignee_ids([slot.primary_user_id for slot in assignee_slots])
    elif payload.assignee_ids is not None:
        assignee_ids = _dedupe_assignee_ids(payload.assignee_ids)
    elif payload.default_assignee_id is not None:
        assignee_ids = [payload.default_assignee_id]

    await _validate_replacement_users(
        db,
        zv1_user_id=payload.zv1_user_id,
        zv2_user_id=payload.zv2_user_id,
        assignee_ids=assignee_ids,
        required=_replacements_required(assignee_ids),
    )

    # Get assignee users first to determine department automatically
    assignee_users: list[User] | None = None
    if assignee_ids is not None:
        assignee_users = (
            await db.execute(select(User).where(User.id.in_(assignee_ids)))
        ).scalars().all()
        if len(assignee_users) != len(assignee_ids):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignee not found")

    # Determine department and scope from assignees if not explicitly set
    department_id = payload.department_id
    scope_value = payload.scope
    
    if assignee_users and len(assignee_users) > 0:
        # Get unique departments from assignees
        assignee_departments = {u.department_id for u in assignee_users if u.department_id is not None}
        is_gane_assignee = any(_is_gane_user(u) for u in assignee_users)
        ga_department = None
        if is_gane_assignee:
            ga_department = (
                await db.execute(select(Department).where(Department.code == "GA"))
            ).scalar_one_or_none()

        # Only force GA when ALL assignees are from GA (prevents mixed-department tasks from being hidden)
        if ga_department and assignee_departments == {ga_department.id}:
            department_id = ga_department.id
            scope_value = SystemTaskScope.DEPARTMENT
        elif len(assignee_departments) == 1:
            # All assignees are from the same department - use that department
            department_id = list(assignee_departments)[0]
            scope_value = SystemTaskScope.DEPARTMENT
        elif len(assignee_departments) > 1:
            # Assignees are from different departments - use ALL scope
            department_id = None
            scope_value = SystemTaskScope.ALL
        elif len(assignee_departments) == 0:
            # Assignees have no department - if no department was set, use ALL scope
            if department_id is None:
                scope_value = SystemTaskScope.ALL
    else:
        # No assignees - use scope/department from payload or defaults
        if scope_value is None:
            scope_value = SystemTaskScope.DEPARTMENT if payload.department_id is not None else SystemTaskScope.ALL
        if scope_value == SystemTaskScope.DEPARTMENT and department_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Department is required when scope is DEPARTMENT and no assignees are provided")

    # Validate scope and department consistency
    if scope_value == SystemTaskScope.DEPARTMENT:
        if department_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Department is required")
    else:
        if department_id is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Department must be empty for ALL scope")

    if department_id is not None:
        department = (
            await db.execute(select(Department).where(Department.id == department_id))
        ).scalar_one_or_none()
        if department is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    priority_value = payload.priority or TaskPriority.NORMAL

    template = SystemTaskTemplate(
        title=payload.title,
        description=payload.description,
        internal_notes=payload.internal_notes,
        department_id=department_id,
        default_assignee_id=assignee_ids[0] if assignee_ids else None,
        assignee_ids=assignee_ids,
        zv1_user_id=payload.zv1_user_id,
        zv2_user_id=payload.zv2_user_id,
        scope=_enum_value(scope_value),
        frequency=_enum_value(payload.frequency),
        day_of_week=days_of_week[0] if days_of_week else payload.day_of_week,
        days_of_week=days_of_week,
        day_of_month=payload.day_of_month,
        month_of_year=payload.month_of_year,
        timezone=payload.timezone or settings.APP_TIMEZONE,
        due_time=payload.due_time or datetime.strptime("09:00", "%H:%M").time(),
        lookahead=payload.lookahead or 14,
        interval=payload.interval or 1,
        apply_from=payload.apply_from,
        duration_days=payload.duration_days or 1,
        priority=_enum_value(priority_value),
        finish_period=_enum_value(payload.finish_period),
        requires_alignment=payload.requires_alignment if payload.requires_alignment is not None else False,
        alignment_time=payload.alignment_time,
        show_in_weekly_planner=(
            payload.show_in_weekly_planner if payload.show_in_weekly_planner is not None else False
        ),
        is_active=payload.is_active if payload.is_active is not None else True,
        created_by_user_id=user.id,
        approval_status=CommonApprovalStatus.pending,
    )

    db.add(template)
    await db.flush()
    await _sync_template_slots_from_payload(
        db,
        template=template,
        assignee_slots=assignee_slots,
        assignee_ids=assignee_ids,
    )

    # Alignment roles/users. Stored on the template (applies to future occurrences).
    if payload.requires_alignment:
        if payload.alignment_time is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="alignment_time is required")
        roles = payload.alignment_roles or []
        cleaned = sorted({str(r).upper() for r in roles if str(r).strip()})
        if not cleaned:
            cleaned = ["MANAGER"]
        values = [{"template_id": template.id, "role": role} for role in cleaned]
        await db.execute(insert(SystemTaskTemplateAlignmentRole), values)
        alignment_user_ids = await _validate_alignment_user_ids(db, payload.alignment_user_ids or [])
        if alignment_user_ids:
            await db.execute(
                insert(SystemTaskTemplateAlignmentUser),
                [{"template_id": template.id, "user_id": uid} for uid in alignment_user_ids],
            )
    await db.commit()
    await db.refresh(template)
    return await _template_definition_to_out(db, template=template)


@router.post("/{template_id}/approve", response_model=SystemTaskTemplateOut)
async def approve_system_task_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> SystemTaskTemplateOut:
    if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    template = (
        await db.execute(select(SystemTaskTemplate).where(SystemTaskTemplate.id == template_id))
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System task not found")
    if _template_approval_status(template) != CommonApprovalStatus.pending:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="System task already processed")

    approved_at = datetime.now(timezone.utc)
    template.approval_status = CommonApprovalStatus.approved
    template.approved_by_user_id = user.id
    template.approved_at = approved_at
    template.rejected_by_user_id = None
    template.rejected_at = None
    template.rejection_reason = None

    # Approval is the creation boundary. Reset any cursor saved while the
    # template was pending, then generate only this template from today
    # forward. This prevents late approval from backfilling earlier days.
    await db.flush()
    await _reset_template_slots_next_run_at(db, template=template, now=approved_at)
    approval_day = approved_at.astimezone(template_tz(template)).date()
    await generate_system_task_instances(
        db=db,
        now_utc=approved_at,
        start=approval_day,
        end=approval_day + timedelta(days=max(int(settings.SYSTEM_TASK_GENERATE_AHEAD_DAYS), 0)),
        template_ids=[template.id],
    )
    await reconcile_system_task_assignments_in_range(
        db=db,
        start=approval_day,
        end=approval_day + timedelta(days=max(int(settings.SYSTEM_TASK_GENERATE_AHEAD_DAYS), 0)),
        now_utc=approved_at,
        template_ids=[template.id],
    )

    await db.commit()
    await db.refresh(template)
    return await _template_definition_to_out(db, template=template)


@router.post("/{template_id}/reject", response_model=SystemTaskTemplateOut)
async def reject_system_task_template(
    template_id: uuid.UUID,
    payload: SystemTaskTemplateReject,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> SystemTaskTemplateOut:
    if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    template = (
        await db.execute(select(SystemTaskTemplate).where(SystemTaskTemplate.id == template_id))
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System task not found")
    if _template_approval_status(template) != CommonApprovalStatus.pending:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="System task already processed")

    template.approval_status = CommonApprovalStatus.rejected
    template.rejected_by_user_id = user.id
    template.rejected_at = datetime.now(timezone.utc)
    template.rejection_reason = payload.reason
    template.approved_by_user_id = None
    template.approved_at = None

    await db.commit()
    await db.refresh(template)
    return await _template_definition_to_out(db, template=template)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_system_task_template(
    template_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_admin),
) -> Response:
    template = (
        await db.execute(select(SystemTaskTemplate).where(SystemTaskTemplate.id == template_id))
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System task not found")

    has_system_origin = await db.execute(
        text(
            "select 1 from information_schema.columns "
            "where table_name = 'tasks' and column_name = 'system_template_origin_id'"
        )
    )
    if has_system_origin.scalar() is not None:
        await db.execute(delete(Task).where(Task.system_template_origin_id == template_id))

    await db.delete(template)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{template_id}", response_model=SystemTaskTemplateOut)
async def update_system_task_template(
    template_id: uuid.UUID,
    payload: SystemTaskTemplateUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> SystemTaskTemplateOut:
    template = (
        await db.execute(select(SystemTaskTemplate).where(SystemTaskTemplate.id == template_id))
    ).scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System task not found")

    # Allow all users to edit all system tasks - no permission restrictions
    original_approval_status = _template_approval_status(template)
    was_active = bool(template.is_active)

    fields_set = payload.model_fields_set
    is_reactivating = "is_active" in fields_set and payload.is_active is True and not was_active
    scope_set = "scope" in fields_set
    department_set = "department_id" in fields_set
    assignee_set = "default_assignee_id" in fields_set or "assignee_ids" in fields_set or "assignee_slots" in fields_set
    days_set = "days_of_week" in fields_set or "day_of_week" in fields_set
    schedule_fields_set = (
        "frequency" in fields_set
        or "day_of_week" in fields_set
        or "days_of_week" in fields_set
        or "day_of_month" in fields_set
        or "month_of_year" in fields_set
    )
    slot_schedule_fields_set = schedule_fields_set or any(
        field in fields_set for field in ("timezone", "due_time", "interval", "apply_from")
    )
    days_of_week = payload.days_of_week
    if days_of_week is None and "day_of_week" in fields_set:
        if payload.day_of_week is not None:
            days_of_week = [payload.day_of_week]
        else:
            days_of_week = []
    if days_of_week is not None:
        cleaned_days = sorted({int(day) for day in days_of_week})
        if any(day < 0 or day > 6 for day in cleaned_days):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid weekday")
        days_of_week = cleaned_days

    effective_frequency = payload.frequency if "frequency" in fields_set else template.frequency
    effective_day = payload.day_of_month if "day_of_month" in fields_set else template.day_of_month
    effective_month = payload.month_of_year if "month_of_year" in fields_set else template.month_of_year
    effective_days_of_week = days_of_week if days_of_week is not None else template.days_of_week
    effective_day_of_week = payload.day_of_week if "day_of_week" in fields_set else template.day_of_week
    if schedule_fields_set and effective_frequency == FrequencyType.WEEKLY:
        has_weekday = bool(effective_days_of_week) or effective_day_of_week is not None
        if not has_weekday:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Weekday is required for weekly tasks",
            )
    if schedule_fields_set and effective_frequency == FrequencyType.MONTHLY and effective_day is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Day of month is required for monthly tasks",
        )
    if schedule_fields_set and effective_frequency == FrequencyType.YEARLY:
        if effective_day is None or effective_month is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Day of month and month are required for yearly tasks",
            )
        if effective_month < 1 or effective_month > 12:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid start month")
    if schedule_fields_set and effective_frequency in (FrequencyType.THREE_MONTHS, FrequencyType.SIX_MONTHS):
        if effective_day is None or effective_month is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Day of month and start month are required for 3/6-month tasks",
            )
        if effective_month < 1 or effective_month > 12:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid start month")

    assignee_slots = payload.assignee_slots if "assignee_slots" in fields_set else None
    await _validate_slot_user_ids(db, assignee_slots)
    assignee_ids = None
    if assignee_slots is not None:
        assignee_ids = _dedupe_assignee_ids([slot.primary_user_id for slot in assignee_slots])
    elif "assignee_ids" in fields_set:
        assignee_ids = _dedupe_assignee_ids(payload.assignee_ids or [])
    elif "default_assignee_id" in fields_set and payload.default_assignee_id is not None:
        assignee_ids = [payload.default_assignee_id]
    elif assignee_set:
        # Use existing assignees from template
        assignee_ids = template.assignee_ids or ([template.default_assignee_id] if template.default_assignee_id else None)

    effective_assignee_ids = (
        assignee_ids
        if assignee_ids is not None
        else template.assignee_ids or ([template.default_assignee_id] if template.default_assignee_id else [])
    )
    effective_zv1_user_id = (
        payload.zv1_user_id if "zv1_user_id" in fields_set else getattr(template, "zv1_user_id", None)
    )
    effective_zv2_user_id = (
        payload.zv2_user_id if "zv2_user_id" in fields_set else getattr(template, "zv2_user_id", None)
    )
    await _validate_replacement_users(
        db,
        zv1_user_id=effective_zv1_user_id,
        zv2_user_id=effective_zv2_user_id,
        assignee_ids=effective_assignee_ids,
        required=(
            getattr(template, "trigger_type", None) is None
            and _replacements_required(effective_assignee_ids)
        ),
    )

    # Get assignee users first to determine department automatically
    assignee_users: list[User] | None = None
    if assignee_ids is not None:
        assignee_users = (
            await db.execute(select(User).where(User.id.in_(assignee_ids)))
        ).scalars().all()
        if len(assignee_users) != len(assignee_ids):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignee not found")

    # Determine department and scope from assignees if assignees are being set
    scope_value = template.scope
    if scope_set:
        if payload.scope is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Scope is required")
        scope_value = payload.scope

    target_department = payload.department_id if department_set else template.department_id
    
    # If assignees are being set/changed, automatically determine department from assignees
    if assignee_set and assignee_users and len(assignee_users) > 0:
        # Get unique departments from assignees
        assignee_departments = {u.department_id for u in assignee_users if u.department_id is not None}
        is_gane_assignee = any(_is_gane_user(u) for u in assignee_users)
        ga_department = None
        if is_gane_assignee:
            ga_department = (
                await db.execute(select(Department).where(Department.code == "GA"))
            ).scalar_one_or_none()

        # Only force GA when ALL assignees are from GA (prevents mixed-department tasks from being hidden)
        if ga_department and assignee_departments == {ga_department.id}:
            target_department = ga_department.id
            scope_value = SystemTaskScope.DEPARTMENT
        elif len(assignee_departments) == 1:
            # All assignees are from the same department - use that department
            target_department = list(assignee_departments)[0]
            scope_value = SystemTaskScope.DEPARTMENT
        elif len(assignee_departments) > 1:
            # Assignees are from different departments - use ALL scope
            target_department = None
            scope_value = SystemTaskScope.ALL
        elif len(assignee_departments) == 0:
            # Assignees have no department - if no department was set, use ALL scope
            if target_department is None:
                scope_value = SystemTaskScope.ALL

    # Validate scope and department consistency
    if scope_value == SystemTaskScope.DEPARTMENT:
        if target_department is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Department is required")
    else:
        if department_set and payload.department_id is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Department must be empty for ALL scope")
        target_department = None

    if scope_value == SystemTaskScope.DEPARTMENT and target_department is not None:
        # Allow all users to edit tasks from any department
        department = (
            await db.execute(select(Department).where(Department.id == target_department))
        ).scalar_one_or_none()
        if department is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    if payload.title is not None:
        template.title = payload.title
    if payload.description is not None:
        template.description = payload.description
    if "internal_notes" in fields_set:
        template.internal_notes = payload.internal_notes
    if scope_set:
        template.scope = _enum_value(scope_value)
    if scope_value == SystemTaskScope.DEPARTMENT:
        if department_set or assignee_set:
            template.department_id = target_department
    else:
        template.department_id = None
    if assignee_set and assignee_ids is not None:
        template.default_assignee_id = assignee_ids[0] if assignee_ids else None
        template.assignee_ids = assignee_ids
    if "zv1_user_id" in fields_set:
        template.zv1_user_id = payload.zv1_user_id
    if "zv2_user_id" in fields_set:
        template.zv2_user_id = payload.zv2_user_id
    if payload.frequency is not None:
        template.frequency = _enum_value(payload.frequency)
    if days_set:
        template.days_of_week = days_of_week or None
        template.day_of_week = days_of_week[0] if days_of_week else payload.day_of_week
    if payload.day_of_month is not None:
        template.day_of_month = payload.day_of_month
    if payload.month_of_year is not None:
        template.month_of_year = payload.month_of_year
    if "timezone" in fields_set and payload.timezone is not None:
        template.timezone = payload.timezone
    if "due_time" in fields_set and payload.due_time is not None:
        template.due_time = payload.due_time
    if "lookahead" in fields_set and payload.lookahead is not None:
        template.lookahead = payload.lookahead
    if "interval" in fields_set and payload.interval is not None:
        template.interval = payload.interval
    if "apply_from" in fields_set:
        template.apply_from = payload.apply_from
    if "duration_days" in fields_set and payload.duration_days is not None:
        template.duration_days = payload.duration_days
    if payload.priority is not None:
        template.priority = _enum_value(payload.priority)
    if "finish_period" in fields_set:
        template.finish_period = _enum_value(payload.finish_period)
    if payload.requires_alignment is not None:
        template.requires_alignment = payload.requires_alignment
    if "alignment_time" in fields_set:
        template.alignment_time = payload.alignment_time
    if payload.show_in_weekly_planner is not None:
        template.show_in_weekly_planner = payload.show_in_weekly_planner
    if payload.is_active is not None:
        template.is_active = payload.is_active

    if original_approval_status == CommonApprovalStatus.rejected:
        template.approval_status = CommonApprovalStatus.pending
        template.approved_by_user_id = None
        template.approved_at = None
        template.rejected_by_user_id = None
        template.rejected_at = None
        template.rejection_reason = None

    # Update alignment roles if provided.
    if (
        "alignment_roles" in fields_set
        or "alignment_user_ids" in fields_set
        or "requires_alignment" in fields_set
    ):
        await db.execute(delete(SystemTaskTemplateAlignmentRole).where(SystemTaskTemplateAlignmentRole.template_id == template.id))
        await db.execute(delete(SystemTaskTemplateAlignmentUser).where(SystemTaskTemplateAlignmentUser.template_id == template.id))
        if template.requires_alignment:
            if template.alignment_time is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="alignment_time is required")
            roles = payload.alignment_roles or []
            cleaned = sorted({str(r).upper() for r in roles if str(r).strip()})
            if not cleaned:
                cleaned = ["MANAGER"]
            values = [{"template_id": template.id, "role": role} for role in cleaned]
            await db.execute(insert(SystemTaskTemplateAlignmentRole), values)
            alignment_user_ids = await _validate_alignment_user_ids(db, payload.alignment_user_ids or [])
            if alignment_user_ids:
                await db.execute(
                    insert(SystemTaskTemplateAlignmentUser),
                    [{"template_id": template.id, "user_id": uid} for uid in alignment_user_ids],
                )

    await db.flush()
    if assignee_set:
        await _sync_template_slots_from_payload(
            db,
            template=template,
            assignee_slots=assignee_slots,
            assignee_ids=assignee_ids,
        )
    if assignee_set:
        await _regenerate_template_after_assignment_change(db, template=template)
    elif slot_schedule_fields_set or is_reactivating:
        await _reset_template_slots_next_run_at(db, template=template)
    await db.commit()
    await db.refresh(template)
    return await _template_definition_to_out(db, template=template)
