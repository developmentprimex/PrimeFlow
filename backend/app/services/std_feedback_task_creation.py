from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypedDict

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.enums import GaNotePriority, GaNoteStatus, GaNoteType, NotificationType, TaskStatus
from app.models.ga_note import GaNote
from app.models.notification import Notification
from app.models.project import Project
from app.models.std_feedback_ticket import StdFeedbackTicket
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.user import User
from app.services.audit import add_audit_log
from app.services.notifications import add_notification


@dataclass(slots=True)
class StdTicketTaskBundle:
    note: GaNote
    tasks: list[Task]
    tickets: list[StdFeedbackTicket]
    notifications: list[Notification]
    created: bool


class TaskTypeFields(TypedDict):
    priority: str
    is_1h_report: bool
    is_r1: bool
    is_personal: bool
    is_bllok: bool


def is_std_project_title(title: str | None) -> bool:
    normalized = (title or "").casefold()
    keywords = settings.std_feedback_project_keyword_list
    return bool(keywords) and any(keyword in normalized for keyword in keywords)


def default_bundle_title(tickets: list[StdFeedbackTicket]) -> str:
    return f"STD - {len(tickets)} TIK EXT PËR RREGULLIM"


def user_initials(user: User) -> str:
    label = (user.full_name or user.username or user.email.split("@", 1)[0]).strip()
    parts = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", label)
    return "".join(part[0] for part in parts).upper() or "U"


def assignee_task_title(base_title: str, user: User) -> str:
    return f"{user_initials(user)}: {base_title}"


def task_type_fields(task_type: str) -> TaskTypeFields:
    normalized = task_type.upper()
    if normalized not in {"NORMAL", "HIGH", "1H", "R1", "PERSONAL", "BLLOK"}:
        raise ValueError("Invalid task priority/type")
    return {
        "priority": "HIGH" if normalized == "HIGH" else "NORMAL",
        "is_1h_report": normalized == "1H",
        "is_r1": normalized == "R1",
        "is_personal": normalized == "PERSONAL",
        "is_bllok": normalized == "BLLOK",
    }


def _ticket_line(ticket: StdFeedbackTicket, index: int) -> str:
    ticket_number = (
        ticket.order_ticket_number
        or (str(ticket.issue_number) if ticket.issue_number is not None else None)
        or ticket.external_id[:8]
    )
    return f"{index}. {ticket_number}"


def default_bundle_description(tickets: list[StdFeedbackTicket]) -> str:
    lines = ["Rregullo ticket-at externe të ardhura nga STD:"]
    lines.extend(_ticket_line(ticket, index) for index, ticket in enumerate(tickets, 1))
    lines.append("")
    lines.append("Burimi: STD External")
    return "\n".join(lines)


async def mark_tickets_no_action(
    db: AsyncSession,
    *,
    ticket_ids: list[uuid.UUID],
    actor_user_id: uuid.UUID,
    note: str | None,
) -> list[StdFeedbackTicket]:
    unique_ids = list(dict.fromkeys(ticket_ids))
    tickets = (
        await db.execute(
            select(StdFeedbackTicket)
            .where(StdFeedbackTicket.id.in_(unique_ids), StdFeedbackTicket.is_external.is_(True))
            .with_for_update()
        )
    ).scalars().all()
    if len(tickets) != len(unique_ids):
        raise ValueError("One or more external tickets were not found")
    if any(ticket.ga_note_id or ticket.task_id or ticket.review_status == "TASK_CREATED" for ticket in tickets):
        raise ValueError("A ticket that already created a task cannot be marked as no action")

    now = datetime.now(timezone.utc)
    for ticket in tickets:
        ticket.review_status = "NO_ACTION"
        ticket.review_note = (note or "").strip() or None
        ticket.reviewed_by = actor_user_id
        ticket.reviewed_at = now
        add_audit_log(
            db=db,
            actor_user_id=actor_user_id,
            entity_type="std_feedback_ticket",
            entity_id=ticket.id,
            action="marked_no_action",
            after={"review_status": "NO_ACTION", "review_note": ticket.review_note},
        )
    return tickets


async def create_ticket_task_bundle(
    db: AsyncSession,
    *,
    ticket_ids: list[uuid.UUID],
    project_id: uuid.UUID,
    assignee_ids: list[uuid.UUID],
    actor_user_id: uuid.UUID,
    title: str | None,
    description: str | None,
    review_note: str | None,
    priority: str,
    start_date: datetime | None,
    due_date: datetime | None,
) -> StdTicketTaskBundle:
    unique_ticket_ids = list(dict.fromkeys(ticket_ids))
    unique_assignee_ids = list(dict.fromkeys(assignee_ids))
    tickets = (
        await db.execute(
            select(StdFeedbackTicket)
            .where(StdFeedbackTicket.id.in_(unique_ticket_ids), StdFeedbackTicket.is_external.is_(True))
            .order_by(StdFeedbackTicket.issue_number.asc().nullslast(), StdFeedbackTicket.created_at.asc())
            .with_for_update()
        )
    ).scalars().all()
    if len(tickets) != len(unique_ticket_ids):
        raise ValueError("One or more external tickets were not found")

    converted = [ticket for ticket in tickets if ticket.ga_note_id or ticket.task_id]
    if converted:
        note_ids = {ticket.ga_note_id for ticket in tickets}
        if len(converted) == len(tickets) and len(note_ids) == 1 and None not in note_ids:
            note_id = next(iter(note_ids))
            existing_note = (
                await db.execute(select(GaNote).where(GaNote.id == note_id))
            ).scalar_one()
            existing_tasks = (
                await db.execute(
                    select(Task)
                    .where(Task.ga_note_origin_id == note_id, Task.is_active.is_(True))
                    .order_by(Task.created_at.asc())
                )
            ).scalars().all()
            return StdTicketTaskBundle(
                note=existing_note,
                tasks=existing_tasks,
                tickets=tickets,
                notifications=[],
                created=False,
            )
        raise ValueError("One or more selected tickets already belong to another task")

    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise ValueError("Project not found")
    if not is_std_project_title(project.title):
        raise ValueError("Select a project configured for STD tickets")

    users = (
        await db.execute(select(User).where(User.work_staff_filter()).where(User.id.in_(unique_assignee_ids), User.is_active.is_(True)))
    ).scalars().all()
    if len(users) != len(unique_assignee_ids):
        raise ValueError("One or more assigned users do not exist or are inactive")
    user_by_id = {user.id: user for user in users}
    ordered_users = [user_by_id[user_id] for user_id in unique_assignee_ids]

    now = datetime.now(timezone.utc)
    effective_start = start_date or now
    if due_date is not None and effective_start > due_date:
        raise ValueError("Start date cannot be after due date")

    base_task_title = (title or "").strip() or default_bundle_title(tickets)
    ticket_list_description = default_bundle_description(tickets)
    extra_description = (description or "").strip()
    task_description = extra_description or None
    task_fields = task_type_fields(priority)
    personalized_titles = [assignee_task_title(base_task_title, assignee) for assignee in ordered_users]
    note_initials = "/".join(user_initials(assignee) for assignee in ordered_users)
    note_title = f"{note_initials}: {base_task_title}"
    note_content = f"{note_title}\n\n{ticket_list_description}"
    note = GaNote(
        content=note_content,
        created_by=actor_user_id,
        note_type=GaNoteType.GA,
        status=GaNoteStatus.OPEN,
        priority=GaNotePriority.HIGH if task_fields["priority"] == "HIGH" else GaNotePriority.NORMAL,
        start_date=effective_start,
        due_date=due_date,
        is_converted_to_task=True,
        is_discussed=False,
        project_id=project.id,
        department_id=project.department_id,
    )
    db.add(note)
    await db.flush()

    tasks: list[Task] = []
    notifications: list[Notification] = []
    for assignee, task_title in zip(ordered_users, personalized_titles, strict=True):
        task = Task(
            title=task_title,
            description=task_description,
            internal_notes=(review_note or "").strip() or None,
            project_id=project.id,
            department_id=assignee.department_id or project.department_id,
            assigned_to=assignee.id,
            created_by=actor_user_id,
            ga_note_origin_id=note.id,
            status=TaskStatus.TODO.value,
            priority=task_fields["priority"],
            phase=project.current_phase or "MEETINGS",
            progress_percentage=0,
            start_date=effective_start,
            due_date=due_date,
            is_deadline_important=due_date is not None,
            is_bllok=task_fields["is_bllok"],
            is_1h_report=task_fields["is_1h_report"],
            is_r1=task_fields["is_r1"],
            is_personal=task_fields["is_personal"],
            is_active=True,
        )
        db.add(task)
        await db.flush()
        await db.execute(insert(TaskAssignee), [{"task_id": task.id, "user_id": assignee.id}])
        tasks.append(task)
        notifications.append(
            add_notification(
                db=db,
                user_id=assignee.id,
                type=NotificationType.assignment,
                title="Task assigned from STD External",
                body=task_title,
                data={"task_id": str(task.id), "ga_note_id": str(note.id)},
            )
        )
        add_audit_log(
            db=db,
            actor_user_id=actor_user_id,
            entity_type="task",
            entity_id=task.id,
            action="created_from_std_external",
            after={"title": task_title, "assigned_to": str(assignee.id)},
        )

    primary_task_id = tasks[0].id
    for ticket in tickets:
        ticket.review_status = "TASK_CREATED"
        ticket.review_note = (review_note or "").strip() or None
        ticket.reviewed_by = actor_user_id
        ticket.reviewed_at = now
        ticket.ga_note_id = note.id
        ticket.task_id = primary_task_id
        add_audit_log(
            db=db,
            actor_user_id=actor_user_id,
            entity_type="std_feedback_ticket",
            entity_id=ticket.id,
            action="converted_to_task",
            after={"ga_note_id": str(note.id), "task_id": str(primary_task_id)},
        )

    return StdTicketTaskBundle(
        note=note,
        tasks=tasks,
        tickets=tickets,
        notifications=notifications,
        created=True,
    )
