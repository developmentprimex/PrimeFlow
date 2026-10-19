from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import String, and_, case, cast, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_current_user
from app.db import get_db
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_marker_comment_inbox import TaskMarkerCommentInbox as Inbox
from app.models.user import User
from app.services.task_marker import one_h_marker_label
from app.services.task_marker_visibility import marker_alert_task

router = APIRouter()


def source_key(task):
    return case(*[
        (getattr(task, field).is_not(None), prefix + cast(getattr(task, field), String))
        for prefix, field in (("plan:", "plan_note_origin_id"), ("ga:", "ga_note_origin_id"), ("group:", "fast_task_group_id"))
    ], else_="task:" + cast(task.id, String))


def task_membership(user_id):
    # Responsibility belongs to the logical task, including its active copies.
    # Being its creator or having an old observer receipt does not qualify.
    related = aliased(Task)
    return exists().where(
        marker_alert_task(related), source_key(related) == Inbox.source_key,
        or_(related.assigned_to == user_id, exists().where(
            TaskAssignee.task_id == related.id, TaskAssignee.user_id == user_id,
        )),
    )


def visible_comments(user_id):
    return select(Inbox).join(Task, Task.id == Inbox.task_id).where(
        Inbox.user_id == user_id, marker_alert_task(Task),
        task_membership(user_id), Inbox.marker == Task.one_h_marker,
        Inbox.comment == func.btrim(func.coalesce(Task.one_h_marker_comment, "")),
    )


async def recipient_progress(db, items):
    if not items:
        return {}
    current = {item.source_key: item for item in items}
    key = source_key(Task)
    rows = (await db.execute(
        select(key, User.id, User.full_name, User.username, Inbox.marker, Inbox.comment, Inbox.read_at)
        .select_from(Task).outerjoin(TaskAssignee, TaskAssignee.task_id == Task.id)
        .join(User, or_(User.id == Task.assigned_to, User.id == TaskAssignee.user_id))
        .outerjoin(Inbox, and_(Inbox.source_key == key, Inbox.user_id == User.id))
        .where(marker_alert_task(Task), User.is_active.is_(True), key.in_(current))
    )).all()
    recipients = {key: {} for key in current}
    for key, user_id, full_name, username, marker, comment, read_at in rows:
        item = current[key]
        name = full_name or username or "Përdorues"
        recipients[key][user_id] = {
            "user_id": str(user_id), "name": name,
            "initials": "".join(part[0] for part in name.split())[:3].upper(),
            "read_at": read_at if (marker, comment) == (item.marker, item.comment) else None,
        }
    progress = {}
    for key, by_user in recipients.items():
        people = sorted(by_user.values(), key=lambda person: (person["name"], person["user_id"]))
        read_count = sum(person["read_at"] is not None for person in people)
        progress[key] = {
            "recipients": people, "recipient_count": len(people), "read_count": read_count,
            "all_read": bool(people) and read_count == len(people),
        }
    return progress


@router.get("")
async def list_marker_comments(
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
    scope: Literal["mine", "all"] = "mine",
):
    # Task details and PX Notes are already readable by authenticated users.
    # Team browsing shows acknowledgement by current responsible recipients.
    mine = and_(Inbox.user_id == user.id, task_membership(user.id))
    stmt = visible_comments(user.id) if scope == "mine" else select(Inbox).join(Task, Task.id == Inbox.task_id).where(
        marker_alert_task(Task), Inbox.marker == Task.one_h_marker,
        Inbox.comment == func.btrim(func.coalesce(Task.one_h_marker_comment, "")),
    )
    stmt = stmt.add_columns(Task.title, User.full_name, Task.one_h_marker_by_ga, mine.label("is_mine"))
    stmt = stmt.outerjoin(User, User.id == Inbox.author_id)
    if scope == "all":
        # Prefer the current viewer's receipt, otherwise pick one representation.
        stmt = stmt.distinct(Inbox.source_key).order_by(Inbox.source_key, case((mine, 0), else_=1), Inbox.updated_at.desc(), Inbox.id)
    else:
        stmt = stmt.order_by(Inbox.updated_at.desc(), Inbox.id)
    rows = (await db.execute(stmt)).all()
    rows = sorted(rows, key=lambda row: row[0].updated_at, reverse=True)
    progress = await recipient_progress(db, [row[0] for row in rows])
    return {"items": [{
        "id": str(item.id), "source_key": item.source_key, "task_id": str(item.task_id), "task_ids": item.task_ids,
        "revision": str(item.revision), "title": title,
        "marker": item.marker, "marker_by_ga": bool(marker_by_ga), "symbol": one_h_marker_label(item.marker, bool(marker_by_ga)),
        "comment": item.comment, "author_name": author_name,
        "updated_at": item.updated_at, "read_at": item.read_at if is_mine else None,
        "is_mine": bool(is_mine), "can_mark_read": bool(is_mine),
        **progress[item.source_key],
    } for item, title, author_name, marker_by_ga, is_mine in rows]}


class ReadComment(BaseModel):
    revision: uuid.UUID
    scope: Literal["mine", "all"] = "mine"


@router.post("/{comment_id}/read")
async def read_marker_comment(
    comment_id: uuid.UUID, payload: ReadComment,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    # Scope never grants permission to acknowledge somebody else's comment.
    stmt = visible_comments(user.id)
    item = (await db.execute(stmt.where(Inbox.id == comment_id).with_for_update(of=Inbox))).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    if item.revision != payload.revision:
        raise HTTPException(status_code=409, detail="Comment changed; open the latest version")
    read_at = datetime.now(timezone.utc)
    source_key = item.source_key
    # Conditional update protects an edit arriving while the user reads the old revision.
    result = await db.execute(update(Inbox).where(
        Inbox.id == comment_id, Inbox.user_id == user.id, Inbox.revision == payload.revision,
    ).values(read_at=read_at).returning(Inbox.id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=409, detail="Comment changed; open the latest version")
    await db.commit()
    return {"status": "ok", "source_key": source_key, "revision": str(payload.revision), "read_at": read_at}
