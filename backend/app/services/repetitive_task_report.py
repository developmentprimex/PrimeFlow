"""One report row per logical repetitive task, including system definitions."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department import Department
from app.models.enums import CommonApprovalStatus, SystemTaskScope
from app.models.system_task_template import SystemTaskTemplate
from app.models.system_task_template_assignee_slot import SystemTaskTemplateAssigneeSlot
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.user import User
from app.services.note_markup import parse_marked_note_content


def _task_group_key(task: Task) -> tuple[str, object]:
    for field in ("ga_note_origin_id", "plan_note_origin_id", "fast_task_group_id"):
        value = getattr(task, field)
        if value is not None:
            return field, value
    return "task", task.id


async def repetitive_task_report_rows(db: AsyncSession) -> list[list[str]]:
    templates = (await db.execute(
        select(SystemTaskTemplate).where(
            SystemTaskTemplate.is_repetitive.is_(True),
            SystemTaskTemplate.approval_status == CommonApprovalStatus.approved,
        ).order_by(SystemTaskTemplate.title, SystemTaskTemplate.id)
    )).scalars().all()
    # Generated system instances are represented by their template above.
    # Completed ordinary tasks remain included; removed assignee copies do not.
    tasks = (await db.execute(
        select(Task).where(
            Task.is_repetitive.is_(True),
            Task.is_active.is_(True),
            Task.system_template_origin_id.is_(None),
        ).order_by(Task.created_at, Task.id)
    )).scalars().all()

    template_people = {}
    if templates:
        slots = (await db.execute(
            select(SystemTaskTemplateAssigneeSlot).where(
                SystemTaskTemplateAssigneeSlot.template_id.in_([item.id for item in templates]),
                SystemTaskTemplateAssigneeSlot.is_active.is_(True),
            )
        )).scalars().all()
        for slot in slots:
            template_people.setdefault(slot.template_id, set()).add(slot.primary_user_id)
    for template in templates:
        if template.id not in template_people:
            people = set(template.assignee_ids or [])
            if template.default_assignee_id:
                people.add(template.default_assignee_id)
            template_people[template.id] = people

    task_people = {}
    if tasks:
        assignments = (await db.execute(
            select(TaskAssignee.task_id, TaskAssignee.user_id).where(
                TaskAssignee.task_id.in_([item.id for item in tasks])
            )
        )).all()
        for task_id, user_id in assignments:
            task_people.setdefault(task_id, set()).add(user_id)
    for task in tasks:
        if task.id not in task_people:
            task_people[task.id] = {task.assigned_to} if task.assigned_to else set()

    people_ids = set().union(*template_people.values(), *task_people.values())
    users = (await db.execute(select(User).where(User.id.in_(people_ids)))).scalars().all() if people_ids else []
    user_map = {item.id: item for item in users}
    department_ids = {item.department_id for item in [*templates, *tasks, *users] if item.department_id}
    departments = (await db.execute(
        select(Department).where(Department.id.in_(department_ids))
    )).scalars().all() if department_ids else []
    department_map = {item.id: item.code or item.name for item in departments}

    def labels(people, dep_ids):
        names = []
        for person_id in sorted(people, key=str):
            person = user_map.get(person_id)
            if person:
                names.append(person.full_name or person.username or person.email)
                if person.department_id:
                    dep_ids.add(person.department_id)
        return ", ".join(sorted(names, key=str.casefold)) or "-", " / ".join(sorted({
            department_map[value] for value in dep_ids if value in department_map
        })) or "-"

    rows = []
    for template in templates:
        dep_ids = {template.department_id} if template.department_id else set()
        people, department = labels(template_people[template.id], dep_ids)
        if people == "-" and template.scope == SystemTaskScope.ALL.value:
            people = "All"
        if department == "-" and template.scope in {SystemTaskScope.ALL.value, SystemTaskScope.GA.value}:
            department = template.scope
        frequency = getattr(template.frequency, "value", template.frequency) or ""
        frequency_label = {
            "DAILY": "Daily", "WEEKLY": "Weekly", "MONTHLY": "Monthly", "YEARLY": "Yearly",
            "3_MONTHS": "Every 3 months", "6_MONTHS": "Every 6 months",
        }.get(frequency, frequency)
        rows.append([parse_marked_note_content(template.title).text, people, department, "SYS", frequency_label])

    grouped = {}
    for task in tasks:
        key = _task_group_key(task)
        group = grouped.setdefault(key, {"title": task.title, "people": set(), "departments": set()})
        group["people"].update(task_people[task.id])
        if task.department_id:
            group["departments"].add(task.department_id)
    for group in grouped.values():
        people, department = labels(group["people"], group["departments"])
        rows.append([parse_marked_note_content(group["title"]).text, people, department, "", ""])
    return sorted(rows, key=lambda row: (row[3] != "SYS", row[0].casefold(), row[1].casefold()))
