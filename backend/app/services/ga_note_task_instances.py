from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ga_note import GaNote
from app.models.plan_note import PlanNote
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_one_h_report_slot import TaskOneHReportSlot
from app.models.user import User
from app.models.enums import TaskFinishPeriod, TaskPriority, TaskStatus
from app.services.one_h_slots import current_effective_slot_date
from app.services.task_marker import current_effective_marker_date


@dataclass(slots=True)
class GaNoteTaskReconcileResult:
    active_tasks: list[Task]
    created_tasks: list[Task] = field(default_factory=list)
    deactivated_tasks: list[Task] = field(default_factory=list)
    created_count: int = 0
    deactivated_count: int = 0
    deduplicated_count: int = 0


@dataclass(frozen=True, slots=True)
class GaNoteAssigneeExecutionState:
    assignee_id: uuid.UUID
    status: TaskStatus
    confirmation_assignee_id: uuid.UUID | None = None
    start_date: datetime | None = None
    due_date: datetime | None = None
    finish_period: TaskFinishPeriod | None = None
    one_h_report_slot: str | None = None
    one_h_report_slot_is_set: bool = False
    one_h_marker: str | None = None
    one_h_marker_is_set: bool = False
    is_deadline_important: bool = False
    priority: TaskPriority = TaskPriority.NORMAL
    is_bllok: bool = False
    is_1h_report: bool = False
    is_r1: bool = False
    is_personal: bool = False


def _dedupe_ids(values: list[uuid.UUID]) -> list[uuid.UUID]:
    seen: set[uuid.UUID] = set()
    return [value for value in values if not (value in seen or seen.add(value))]


async def _set_primary_assignee(
    db: AsyncSession,
    *,
    task: Task,
    user_id: uuid.UUID,
) -> None:
    """Keep a GA task copy owned by exactly one requested person.

    GA task membership is represented by independent Task rows.  The
    TaskAssignee row mirrors ``assigned_to`` so list filters and My View agree.
    Additional workflow/alignment users belong in their dedicated tables, not
    in the GA membership list.
    """

    task.assigned_to = user_id
    await db.execute(delete(TaskAssignee).where(TaskAssignee.task_id == task.id))
    await db.execute(
        insert(TaskAssignee),
        [{"task_id": task.id, "user_id": user_id}],
    )


def _copy_for_new_assignee(
    *,
    template: Task,
    note: GaNote,
    assignee: User,
    actor_user_id: uuid.UUID,
) -> Task:
    from app.services.task_marker_comment_title import update_comment_in_title

    return Task(
        title=update_comment_in_title(template.title, template.one_h_marker_comment, getattr(note, "one_h_marker_comment", None)),
        description=template.description,
        internal_notes=None,
        project_id=template.project_id,
        dependency_task_id=template.dependency_task_id,
        department_id=assignee.department_id or template.department_id or note.department_id,
        assigned_to=assignee.id,
        confirmation_assignee_id=template.confirmation_assignee_id,
        created_by=actor_user_id,
        ga_note_origin_id=note.id,
        plan_note_origin_id=None,
        system_template_origin_id=None,
        fast_task_group_id=None,
        status=TaskStatus.TODO,
        priority=template.priority,
        finish_period=template.finish_period,
        phase=template.phase,
        progress_percentage=0,
        daily_products=template.daily_products,
        start_date=template.start_date,
        due_date=template.due_date,
        original_due_date=None,
        completed_at=None,
        is_repetitive=bool(template.is_repetitive),
        is_deadline_important=template.is_deadline_important,
        is_bllok=template.is_bllok,
        is_1h_report=template.is_1h_report,
        one_h_report_slot=None,
        one_h_marker=getattr(note, "one_h_marker", None),
        one_h_marker_date=getattr(note, "one_h_marker_date", None),
        one_h_marker_by_ga=bool(getattr(note, "one_h_marker_by_ga", False)),
        one_h_marker_comment=getattr(note, "one_h_marker_comment", None),
        is_r1=template.is_r1,
        is_personal=template.is_personal,
        fast_task_order=None,
        is_active=True,
    )


def _copy_for_new_plan_assignee(
    *,
    template: Task,
    note: PlanNote,
    assignee: User,
    actor_user_id: uuid.UUID,
) -> Task:
    from app.services.task_marker_comment_title import update_comment_in_title

    return Task(
        title=update_comment_in_title(template.title, template.one_h_marker_comment, getattr(note, "one_h_marker_comment", None)),
        description=template.description,
        internal_notes=None,
        project_id=template.project_id,
        dependency_task_id=template.dependency_task_id,
        department_id=assignee.department_id or template.department_id or note.department_id,
        assigned_to=assignee.id,
        confirmation_assignee_id=template.confirmation_assignee_id,
        created_by=actor_user_id,
        ga_note_origin_id=None,
        plan_note_origin_id=note.id,
        system_template_origin_id=None,
        fast_task_group_id=None,
        status=TaskStatus.TODO,
        priority=template.priority,
        finish_period=template.finish_period,
        phase=template.phase,
        progress_percentage=0,
        daily_products=template.daily_products,
        start_date=template.start_date,
        due_date=template.due_date,
        original_due_date=None,
        completed_at=None,
        is_repetitive=bool(template.is_repetitive),
        is_deadline_important=template.is_deadline_important,
        is_bllok=template.is_bllok,
        is_1h_report=template.is_1h_report,
        one_h_report_slot=None,
        one_h_marker=getattr(note, "one_h_marker", None),
        one_h_marker_date=getattr(note, "one_h_marker_date", None),
        one_h_marker_by_ga=bool(getattr(note, "one_h_marker_by_ga", False)),
        one_h_marker_comment=getattr(note, "one_h_marker_comment", None),
        is_r1=template.is_r1,
        is_personal=template.is_personal,
        fast_task_order=None,
        is_active=True,
    )


async def reconcile_ga_note_task_assignees(
    db: AsyncSession,
    *,
    note: GaNote,
    desired_assignee_ids: list[uuid.UUID],
    actor_user_id: uuid.UUID,
) -> GaNoteTaskReconcileResult:
    """Reconcile one active, independent task copy per GA-note assignee.

    Existing copies retain their status, progress, completion data and user
    comments.  Removed copies are deactivated (never deleted); newly assigned
    users receive a fresh TODO copy.  The operation is safe to repeat with the
    same desired membership.
    """

    desired_ids = _dedupe_ids(desired_assignee_ids)
    desired_set = set(desired_ids)

    all_tasks = (
        await db.execute(
            select(Task)
            .where(Task.ga_note_origin_id == note.id)
            .order_by(Task.created_at.asc(), Task.id.asc())
            .with_for_update()
        )
    ).scalars().all()
    active_tasks = [task for task in all_tasks if task.is_active]
    template = active_tasks[0] if active_tasks else (all_tasks[-1] if all_tasks else None)

    if desired_ids and template is None:
        raise ValueError("No GA task template exists for this note")

    users: list[User] = []
    if desired_ids:
        users = (
            await db.execute(select(User).where(User.id.in_(desired_ids), User.is_active.is_(True)))
        ).scalars().all()
        if len(users) != len(desired_ids):
            raise ValueError("One or more assigned users do not exist or are inactive")
    user_by_id = {user.id: user for user in users}

    active_by_owner: dict[uuid.UUID, list[Task]] = {}
    ownerless: list[Task] = []
    for task in active_tasks:
        # GA-origin copies never participate in generic fast-task grouping.
        task.fast_task_group_id = None
        if task.assigned_to is None:
            ownerless.append(task)
            continue
        active_by_owner.setdefault(task.assigned_to, []).append(task)

    kept_by_owner: dict[uuid.UUID, Task] = {}
    deduplicated_count = 0
    deactivated_count = 0
    deactivated_tasks: list[Task] = []
    for owner_id, copies in active_by_owner.items():
        canonical = copies[0]
        kept_by_owner[owner_id] = canonical
        for duplicate in copies[1:]:
            duplicate.is_active = False
            duplicate.fast_task_group_id = None
            deduplicated_count += 1
            deactivated_count += 1
            deactivated_tasks.append(duplicate)

    # Ownerless legacy rows are templates/history, not active assignee copies.
    for task in ownerless:
        task.is_active = False
        deactivated_count += 1
        deactivated_tasks.append(task)

    for owner_id, task in kept_by_owner.items():
        if owner_id not in desired_set:
            task.is_active = False
            deactivated_count += 1
            deactivated_tasks.append(task)

    created_count = 0
    created_tasks: list[Task] = []
    next_active: list[Task] = []
    for assignee_id in desired_ids:
        existing = kept_by_owner.get(assignee_id)
        if existing is not None and existing.is_active:
            await _set_primary_assignee(db, task=existing, user_id=assignee_id)
            next_active.append(existing)
            continue

        assert template is not None
        new_task = _copy_for_new_assignee(
            template=template,
            note=note,
            assignee=user_by_id[assignee_id],
            actor_user_id=actor_user_id,
        )
        db.add(new_task)
        await db.flush()
        await _set_primary_assignee(db, task=new_task, user_id=assignee_id)
        next_active.append(new_task)
        created_tasks.append(new_task)
        created_count += 1

    note.is_converted_to_task = bool(next_active)
    return GaNoteTaskReconcileResult(
        active_tasks=next_active,
        created_tasks=created_tasks,
        deactivated_tasks=deactivated_tasks,
        created_count=created_count,
        deactivated_count=deactivated_count,
        deduplicated_count=deduplicated_count,
    )


async def reconcile_plan_note_task_assignees(
    db: AsyncSession,
    *,
    note: PlanNote,
    desired_assignee_ids: list[uuid.UUID],
    actor_user_id: uuid.UUID,
) -> GaNoteTaskReconcileResult:
    """Reconcile one active, independent task copy per PX JAV assignee."""

    desired_ids = _dedupe_ids(desired_assignee_ids)
    desired_set = set(desired_ids)
    all_tasks = (
        await db.execute(
            select(Task)
            .where(Task.plan_note_origin_id == note.id)
            .order_by(Task.created_at.asc(), Task.id.asc())
            .with_for_update()
        )
    ).scalars().all()
    active_tasks = [task for task in all_tasks if task.is_active]
    template = active_tasks[0] if active_tasks else (all_tasks[-1] if all_tasks else None)

    if desired_ids and template is None:
        raise ValueError("No PX JAV task template exists for this note")

    users: list[User] = []
    if desired_ids:
        users = (
            await db.execute(select(User).where(User.id.in_(desired_ids), User.is_active.is_(True)))
        ).scalars().all()
        if len(users) != len(desired_ids):
            raise ValueError("One or more assigned users do not exist or are inactive")
    user_by_id = {user.id: user for user in users}

    active_by_owner: dict[uuid.UUID, list[Task]] = {}
    ownerless: list[Task] = []
    for task in active_tasks:
        task.fast_task_group_id = None
        if task.assigned_to is None:
            ownerless.append(task)
        else:
            active_by_owner.setdefault(task.assigned_to, []).append(task)

    kept_by_owner: dict[uuid.UUID, Task] = {}
    deactivated_tasks: list[Task] = []
    deduplicated_count = 0
    deactivated_count = 0
    for owner_id, copies in active_by_owner.items():
        kept_by_owner[owner_id] = copies[0]
        for duplicate in copies[1:]:
            duplicate.is_active = False
            duplicate.fast_task_group_id = None
            deduplicated_count += 1
            deactivated_count += 1
            deactivated_tasks.append(duplicate)

    for task in ownerless:
        task.is_active = False
        deactivated_count += 1
        deactivated_tasks.append(task)

    for owner_id, task in kept_by_owner.items():
        if owner_id not in desired_set:
            task.is_active = False
            deactivated_count += 1
            deactivated_tasks.append(task)

    created_tasks: list[Task] = []
    next_active: list[Task] = []
    for assignee_id in desired_ids:
        existing = kept_by_owner.get(assignee_id)
        if existing is not None and existing.is_active:
            await _set_primary_assignee(db, task=existing, user_id=assignee_id)
            next_active.append(existing)
            continue

        assert template is not None
        new_task = _copy_for_new_plan_assignee(
            template=template,
            note=note,
            assignee=user_by_id[assignee_id],
            actor_user_id=actor_user_id,
        )
        db.add(new_task)
        await db.flush()
        await _set_primary_assignee(db, task=new_task, user_id=assignee_id)
        next_active.append(new_task)
        created_tasks.append(new_task)

    note.is_converted_to_task = bool(next_active)
    return GaNoteTaskReconcileResult(
        active_tasks=next_active,
        created_tasks=created_tasks,
        deactivated_tasks=deactivated_tasks,
        created_count=len(created_tasks),
        deactivated_count=deactivated_count,
        deduplicated_count=deduplicated_count,
    )


def apply_ga_note_shared_task_fields(
    tasks: list[Task],
    *,
    title: str | None = None,
    description_is_set: bool = False,
    description: str | None = None,
) -> int:
    """Apply GA-controlled fields without touching per-person execution state."""

    updated_count = 0
    for task in tasks:
        changed = False
        if title is not None and task.title != title:
            task.title = title
            changed = True
        if description_is_set and task.description != description:
            task.description = description
            changed = True
        if changed:
            updated_count += 1
    return updated_count


async def sync_ga_note_assignee_report_slots(
    db: AsyncSession,
    tasks: list[Task],
    assignee_ids: list[uuid.UUID],
) -> None:
    """Save explicitly edited slots for the same workday used by report views."""
    selected_assignees = set(assignee_ids)
    selected_tasks = {
        task.id: task
        for task in tasks
        if task.is_active and task.assigned_to in selected_assignees
    }
    if not selected_tasks:
        return

    slot_date = current_effective_slot_date()
    existing_rows = (
        await db.execute(
            select(TaskOneHReportSlot).where(
                TaskOneHReportSlot.task_id.in_(selected_tasks),
                TaskOneHReportSlot.report_date == slot_date,
            )
        )
    ).scalars().all()
    existing_by_task = {row.task_id: row for row in existing_rows}
    for task_id, task in selected_tasks.items():
        existing = existing_by_task.get(task_id)
        if task.one_h_report_slot is None:
            if existing is not None:
                await db.delete(existing)
        elif existing is None:
            db.add(TaskOneHReportSlot(
                task_id=task_id,
                report_date=slot_date,
                one_h_report_slot=task.one_h_report_slot,
            ))
        else:
            existing.one_h_report_slot = task.one_h_report_slot


def apply_ga_note_assignee_execution_states(
    tasks: list[Task],
    states: list[GaNoteAssigneeExecutionState],
) -> int:
    """Apply personal execution fields to exactly the matching active copy."""

    active_by_assignee = {
        task.assigned_to: task
        for task in tasks
        if task.is_active and task.assigned_to is not None
    }
    seen_assignees: set[uuid.UUID] = set()
    updated_count = 0
    for state in states:
        if state.assignee_id in seen_assignees:
            raise ValueError("Duplicate assignee state")
        seen_assignees.add(state.assignee_id)
        task = active_by_assignee.get(state.assignee_id)
        if task is None:
            raise ValueError("Assignee state does not match an active GA task copy")
        if state.status not in {
            TaskStatus.TODO,
            TaskStatus.IN_PROGRESS,
            TaskStatus.WAITING_CLIENT,
            TaskStatus.WAITING_CONFIRMATION,
            TaskStatus.DONE,
        }:
            raise ValueError(
                "GA task status must be TODO, IN_PROGRESS, WAITING_CLIENT, "
                "WAITING_CONFIRMATION, or DONE"
            )
        if state.start_date is not None and state.due_date is not None and state.start_date > state.due_date:
            raise ValueError("Start date cannot be after due date")

        changed = False
        next_status = state.status.value
        current_status = task.status.value if isinstance(task.status, TaskStatus) else str(task.status)
        if current_status != next_status:
            task.status = next_status
            task.completed_at = datetime.now(timezone.utc) if next_status == TaskStatus.DONE.value else None
            changed = True
        if task.confirmation_assignee_id != state.confirmation_assignee_id:
            task.confirmation_assignee_id = state.confirmation_assignee_id
            changed = True
        if task.start_date != state.start_date:
            task.start_date = state.start_date
            changed = True
        if task.due_date != state.due_date:
            if task.due_date is not None and task.original_due_date is None:
                task.original_due_date = task.due_date
            task.due_date = state.due_date
            changed = True
        next_finish_period = state.finish_period.value if state.finish_period is not None else None
        current_finish_period = task.finish_period.value if hasattr(task.finish_period, "value") else task.finish_period
        if current_finish_period != next_finish_period:
            task.finish_period = next_finish_period
            changed = True
        if state.one_h_report_slot_is_set and task.one_h_report_slot != state.one_h_report_slot:
            task.one_h_report_slot = state.one_h_report_slot
            changed = True
        if state.one_h_marker_is_set:
            marker_date = current_effective_marker_date()
            if task.one_h_marker != state.one_h_marker or task.one_h_marker_date != marker_date:
                task.one_h_marker = state.one_h_marker
                task.one_h_marker_date = marker_date
                changed = True
        if task.is_deadline_important != state.is_deadline_important:
            task.is_deadline_important = state.is_deadline_important
            changed = True
        next_priority = state.priority.value
        current_priority = task.priority.value if isinstance(task.priority, TaskPriority) else str(task.priority)
        if current_priority != next_priority:
            task.priority = next_priority
            changed = True
        for field_name, next_value in (
            ("is_bllok", state.is_bllok),
            ("is_1h_report", state.is_1h_report),
            ("is_r1", state.is_r1),
            ("is_personal", state.is_personal),
        ):
            if bool(getattr(task, field_name)) != next_value:
                setattr(task, field_name, next_value)
                changed = True
        if changed:
            updated_count += 1

    return updated_count
