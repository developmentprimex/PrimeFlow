from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_task_template import SystemTaskTemplate
from app.models.system_task_template_alignment_user import SystemTaskTemplateAlignmentUser
from app.models.task import Task
from app.models.task_alignment_user import TaskAlignmentUser
from app.models.user import User


async def ga_task_bz_labels(
    db: AsyncSession, tasks: list[Task], assignee_ids_by_task: dict[Any, set[Any]],
) -> dict[Any, str]:
    """Mirror the Admin Tasks BZ ME column for the selected GA tasks."""
    if not tasks:
        return {}

    task_ids = [task.id for task in tasks]
    task_alignment: dict[Any, set[Any]] = {}
    for task_id, user_id in (await db.execute(
        select(TaskAlignmentUser.task_id, TaskAlignmentUser.user_id)
        .where(TaskAlignmentUser.task_id.in_(task_ids))
    )).all():
        task_alignment.setdefault(task_id, set()).add(user_id)

    template_ids = {task.system_template_origin_id for task in tasks if task.system_template_origin_id}
    template_assignees: dict[Any, list[Any]] = {}
    template_alignment: dict[Any, set[Any]] = {}
    if template_ids:
        for template_id, default_id, assignee_ids, alignment_id in (await db.execute(
            select(SystemTaskTemplate.id, SystemTaskTemplate.default_assignee_id,
                   SystemTaskTemplate.assignee_ids, SystemTaskTemplateAlignmentUser.user_id)
            .outerjoin(SystemTaskTemplateAlignmentUser,
                       SystemTaskTemplateAlignmentUser.template_id == SystemTaskTemplate.id)
            .where(SystemTaskTemplate.id.in_(template_ids))
        )).all():
            template_assignees[template_id] = [default_id, *(assignee_ids or [])]
            if alignment_id:
                template_alignment.setdefault(template_id, set()).add(alignment_id)

    executors_by_task = {}
    for task in tasks:
        template_id = task.system_template_origin_id
        coordinators = task_alignment.get(task.id, set()) | template_alignment.get(template_id, set())
        assigned = [task.assigned_to, *sorted(assignee_ids_by_task.get(task.id, ()), key=str),
                    *template_assignees.get(template_id, [])]
        executors_by_task[task.id] = [user_id for user_id in dict.fromkeys(assigned)
                                      if user_id and user_id not in coordinators]

    user_ids = {user_id for executors in executors_by_task.values() for user_id in executors}
    if not user_ids:
        return {}
    initials = {
        user_id: "".join(part[0].upper() for part in (full_name or username or "").split()[:2])
        for user_id, full_name, username in (await db.execute(
            select(User.id, User.full_name, User.username).where(User.id.in_(user_ids), User.work_staff_filter())
        )).all()
    }
    return {
        task_id: " / ".join(initials[user_id] for user_id in executors if initials.get(user_id)) or "-"
        for task_id, executors in executors_by_task.items()
    }
