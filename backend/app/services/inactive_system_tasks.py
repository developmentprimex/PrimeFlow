"""Remove system-task instances owned only by inactive accounts."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import delete, inspect, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_task_occurrence import SystemTaskOccurrence
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.user import User
from app.services.audit import add_audit_log


@dataclass
class InactiveSystemTaskCleanup:
    inactive_user_ids: list[uuid.UUID] = field(default_factory=list)
    deleted_tasks: list[dict] = field(default_factory=list)
    shared_task_ids: list[uuid.UUID] = field(default_factory=list)
    reassigned_tasks: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    occurrence_ids: list[uuid.UUID] = field(default_factory=list)

    @property
    def task_ids(self) -> list[uuid.UUID]:
        return [row["id"] for row in self.deleted_tasks]


async def plan_inactive_system_task_cleanup(
    db: AsyncSession, *, user_ids: list[uuid.UUID] | None = None,
) -> InactiveSystemTaskCleanup:
    users_stmt = select(User.id).where(User.is_active.is_(False))
    if user_ids is not None:
        users_stmt = users_stmt.where(User.id.in_(user_ids))
    # Hold account state until the caller commits/rolls back this transaction.
    inactive_ids = list((await db.execute(users_stmt.with_for_update())).scalars().all())
    plan = InactiveSystemTaskCleanup(inactive_user_ids=inactive_ids)
    if not inactive_ids:
        return plan

    inactive_links = select(TaskAssignee.task_id).where(TaskAssignee.user_id.in_(inactive_ids))
    rows = (await db.execute(select(
        Task.id, Task.title, Task.status, Task.assigned_to, User.is_active,
    ).outerjoin(User, User.id == Task.assigned_to).where(
        or_(Task.system_template_origin_id.is_not(None), Task.system_task_slot_id.is_not(None)),
        or_(Task.assigned_to.in_(inactive_ids), Task.id.in_(inactive_links)),
    ).with_for_update(of=Task))).all()
    task_ids = [row.id for row in rows]
    active_links: dict[uuid.UUID, list[uuid.UUID]] = {}
    if task_ids:
        links = (await db.execute(select(TaskAssignee.task_id, TaskAssignee.user_id)
            .join(User, User.id == TaskAssignee.user_id)
            .where(TaskAssignee.task_id.in_(task_ids), User.is_active.is_(True))
            .order_by(TaskAssignee.user_id))).all()
        for task_id, user_id in links:
            active_links.setdefault(task_id, []).append(user_id)
    for task_id, title, status, assigned_to, primary_active in rows:
        if primary_active or active_links.get(task_id):
            plan.shared_task_ids.append(task_id)
            if not primary_active:
                plan.reassigned_tasks[task_id] = active_links[task_id][0]
        else:
            plan.deleted_tasks.append({"id": task_id, "title": title, "status": status,
                                       "assigned_to": assigned_to})
    # Current installations may have retired the old, non-task-backed table.
    has_legacy = await db.run_sync(lambda session: inspect(session.connection()).has_table("system_task_occurrences"))
    if has_legacy:
        plan.occurrence_ids = list((await db.execute(select(SystemTaskOccurrence.id).where(
            SystemTaskOccurrence.user_id.in_(inactive_ids),
        ))).scalars().all())
    return plan


async def apply_inactive_system_task_cleanup(
    db: AsyncSession, plan: InactiveSystemTaskCleanup, *, actor_user_id: uuid.UUID | None = None,
) -> dict[str, int]:
    # A shared task belongs to its active owners after removing inactive links.
    if plan.shared_task_ids:
        await db.execute(delete(TaskAssignee).where(
            TaskAssignee.task_id.in_(plan.shared_task_ids),
            TaskAssignee.user_id.in_(plan.inactive_user_ids),
        ))
    for task_id, user_id in plan.reassigned_tasks.items():
        await db.execute(update(Task).where(Task.id == task_id).values(assigned_to=user_id))
    for task in plan.deleted_tasks:
        add_audit_log(db=db, actor_user_id=actor_user_id, entity_type="task", entity_id=task["id"],
                      action="deleted_inactive_user", before={
                          "title": task["title"], "status": task["status"],
                          "assigned_to": str(task["assigned_to"]) if task["assigned_to"] else None,
                      })
    if plan.task_ids:
        # Child rows use the same CASCADE / SET NULL rules as normal task deletion.
        await db.execute(delete(Task).where(Task.id.in_(plan.task_ids)))
    if plan.occurrence_ids:
        await db.execute(delete(SystemTaskOccurrence).where(SystemTaskOccurrence.id.in_(plan.occurrence_ids)))
    return {"deleted_tasks": len(plan.task_ids), "deleted_occurrences": len(plan.occurrence_ids),
            "preserved_shared_tasks": len(plan.shared_task_ids), "reassigned_tasks": len(plan.reassigned_tasks)}


async def cleanup_inactive_user_system_tasks(
    db: AsyncSession, *, user_ids: list[uuid.UUID] | None = None, actor_user_id: uuid.UUID | None = None,
) -> dict[str, int]:
    plan = await plan_inactive_system_task_cleanup(db, user_ids=user_ids)
    return await apply_inactive_system_task_cleanup(db, plan, actor_user_id=actor_user_id)
