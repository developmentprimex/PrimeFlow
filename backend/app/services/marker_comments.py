from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NotificationType
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_marker_comment_inbox import TaskMarkerCommentInbox
from app.models.user import User
from app.services.notifications import add_notification
from app.services.task_marker_visibility import marker_alert_enabled


def marker_comment_source_key(task: Task) -> str:
    for prefix, field in (("plan", "plan_note_origin_id"), ("ga", "ga_note_origin_id"), ("group", "fast_task_group_id")):
        value = getattr(task, field, None)
        if value is not None:
            return f"{prefix}:{value}"
    return f"task:{task.id}"


async def record_initial_marker_comments(db: AsyncSession, tasks: list[Task], *, actor_email: str | None) -> None:
    seen: set[str] = set()
    for task in tasks:
        if not task.one_h_marker and not task.one_h_marker_comment:
            continue
        key = marker_comment_source_key(task)
        if key in seen:
            continue
        seen.add(key)
        related = [Task.id == task.id]
        for field in ("plan_note_origin_id", "ga_note_origin_id", "fast_task_group_id"):
            value = getattr(task, field, None)
            if value:
                related.append(getattr(Task, field) == value)
        shared = list((await db.execute(select(Task).where(or_(*related), Task.is_active.is_(True)))).scalars())
        await record_marker_change(db, shared, marker=task.one_h_marker, comment=task.one_h_marker_comment, actor_email=actor_email)


async def record_marker_change(
    db: AsyncSession, tasks: list[Task], *, marker: str | None, comment: str | None,
    actor_email: str | None,
) -> None:
    """Called within the marker write transaction, once for the shared change."""
    if not tasks:
        return
    from app.services.task_marker import one_h_marker_label

    actor = (await db.execute(select(User).where(func.lower(User.email) == (actor_email or "").strip().lower()))).scalar_one_or_none()
    task_ids = [task.id for task in tasks]
    assignments = (await db.execute(select(TaskAssignee.task_id, TaskAssignee.user_id).where(TaskAssignee.task_id.in_(task_ids)))).all()
    recipients: dict[uuid.UUID, Task] = {}
    by_id = {task.id: task for task in tasks}
    def choose_recipient(user_id, task):
        previous_task = recipients.get(user_id)
        if previous_task is None or marker_alert_enabled(task) or not marker_alert_enabled(previous_task):
            recipients[user_id] = task
    # Prefer a person's own task copy for navigation and subsequent access checks.
    for task in tasks:
        if task.created_by:
            recipients.setdefault(task.created_by, task)
    for task_id, user_id in assignments:
        choose_recipient(user_id, by_id[task_id])
    for task in tasks:
        if task.assigned_to:
            choose_recipient(task.assigned_to, task)
    active_ids = set((await db.execute(select(User.id).where(User.id.in_(recipients), User.is_active.is_(True)))).scalars())
    source_key = marker_comment_source_key(tasks[0])
    existing = {item.user_id: item for item in (await db.execute(
        select(TaskMarkerCommentInbox).where(TaskMarkerCommentInbox.source_key == source_key)
    )).scalars()}
    now = datetime.now(timezone.utc)
    revision = uuid.uuid4()
    comment = (comment or "").strip()
    has_content = bool(marker or comment)
    # A symbol or a standalone comment requires acknowledgement.
    await db.execute(delete(TaskMarkerCommentInbox).where(
        TaskMarkerCommentInbox.source_key == source_key,
        *([TaskMarkerCommentInbox.user_id.not_in(active_ids)] if has_content else []),
    ))
    actor_name = (actor.full_name or actor.username or actor.email) if actor else "Përdorues"
    for user_id, task in recipients.items():
        if user_id not in active_ids:
            continue
        previous = existing.get(user_id)
        if has_content and previous and (previous.marker, previous.comment) == (marker or "", comment):
            previous.task_id = task.id
            previous.task_ids = [str(value) for value in task_ids]
            continue
        inbox_id = uuid.uuid4()
        if has_content:
            stmt = insert(TaskMarkerCommentInbox).values(
                id=inbox_id, source_key=source_key, user_id=user_id, task_id=task.id,
                task_ids=[str(value) for value in task_ids], author_id=actor.id if actor else None,
                revision=revision, marker=marker or "", comment=comment, updated_at=now,
                # Writing a comment never acknowledges it, even for its author.
                read_at=None,
            )
            inbox_id = (await db.execute(stmt.on_conflict_do_update(
                constraint="uq_marker_comment_source_user",
                set_={key: getattr(stmt.excluded, key) for key in (
                    "task_id", "task_ids", "author_id", "revision", "marker", "comment", "updated_at", "read_at",
                )},
            ).returning(TaskMarkerCommentInbox).execution_options(populate_existing=True))).scalar_one().id
        if not marker_alert_enabled(task) or (actor and user_id == actor.id):
            continue
        symbol = one_h_marker_label(marker)
        notification = add_notification(
            db=db, user_id=user_id, type=NotificationType.status_change,
            title=f"{actor_name}: {('koment te simboli ' + symbol if symbol else 'koment te detyra') if comment else 'simboli ' + (symbol or 'u hoq')}",
            body=f"{task.title.splitlines()[0]}\n{comment}" if comment else task.title.splitlines()[0],
            data={
                "kind": "task_marker_comment" if comment else "task_marker",
                "task_id": str(task.id), "comment_id": str(inbox_id) if has_content else None,
                "open_url": f"/comments?comment={inbox_id}" if has_content else f"/tasks/{task.id}",
            },
        )
        db.info.setdefault("pending_marker_notifications", []).append(notification)
