"""Current comments on company 1H tasks and their GA assistant read state."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, func, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routers.ga_assistant import _now, _parse_moment, ensure_assistant_user
from app.db import get_db
from app.models.ga_1h_comment_receipt import GaOneHCommentReceipt as Receipt
from app.models.task import Task
from app.models.task_marker_comment_inbox import TaskMarkerCommentInbox as Inbox
from app.models.task_user_comment import TaskUserComment
from app.models.user import User
from app.services.ga_assistant import frontend_url
from app.services.ga_discord_mentions import initials

router = APIRouter()

CommentSource = Literal["user", "marker"]
CommentStatus = Literal["new", "seen"]


@dataclass(frozen=True)
class Comment:
    source: CommentSource
    source_id: uuid.UUID
    task_id: uuid.UUID
    title: str
    author: str | None
    time: datetime
    text: str
    marker_revision: uuid.UUID | None = None

    @property
    def revision(self) -> str:
        if self.marker_revision is not None:
            return self.marker_revision.hex
        # Ordinary comments mutate in place; the id and time alone do not
        # distinguish edits made within one database transaction.
        return hashlib.sha256(f"{self.time.isoformat()}\n{self.text}".encode()).hexdigest()

    @property
    def id(self) -> str:
        return f"{self.source}:{self.source_id.hex}:{self.revision}"


class CommentMark(BaseModel):
    id: str = Field(pattern=r"^(user:[0-9a-f]{32}:[0-9a-f]{64}|marker:[0-9a-f]{32}:[0-9a-f]{32})$")
    status: CommentStatus


def _one_h_task():
    return and_(Task.is_active.is_(True), Task.is_1h_report.is_(True), Task.work_staff_filter())


def _user_comments():
    return select(
        TaskUserComment.id, Task.id, Task.title, func.coalesce(func.nullif(User.full_name, ""), User.username),
        TaskUserComment.updated_at, TaskUserComment.comment,
    ).select_from(TaskUserComment).join(Task, Task.id == TaskUserComment.task_id).join(
        User, User.id == TaskUserComment.user_id,
    ).where(_one_h_task(), func.btrim(TaskUserComment.comment, " \t\r\n") != "")


def _marker_comments(since: datetime | None = None):
    # An inbox row records one recipient's view of a comment. Select the latest
    # matching revision once per task and leave every recipient's read state alone.
    current = select(Inbox.author_id, Inbox.updated_at, Inbox.comment, Inbox.revision).where(
        Inbox.task_id == Task.id,
        Inbox.marker == func.coalesce(Task.one_h_marker, ""),
        Inbox.comment == func.btrim(Task.one_h_marker_comment),
        Inbox.comment != "",
    ).order_by(Inbox.updated_at.desc(), Inbox.author_id.asc().nulls_last(), Inbox.id).limit(1).lateral()
    query = select(
        Task.id, Task.id, Task.title, func.coalesce(func.nullif(User.full_name, ""), User.username),
        current.c.updated_at, current.c.comment, current.c.revision,
    ).select_from(Task).join(current, true()).outerjoin(User, User.id == current.c.author_id).where(_one_h_task())
    if since is not None:
        query = query.where(current.c.updated_at >= since)
    return query


@router.get("/1h/comments")
async def list_1h_comments(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    since: str | None = None,
    only_new: bool = False,
):
    ensure_assistant_user(user)
    start = _parse_moment(since, default=_now()) if since is not None else None
    ordinary = _user_comments()
    if start is not None:
        ordinary = ordinary.where(TaskUserComment.updated_at >= start)
    comments = [Comment("user", *row) for row in (await db.execute(ordinary)).all()]
    comments.extend(Comment("marker", *row) for row in (await db.execute(_marker_comments(start))).all())
    if not comments:
        return {"items": []}
    receipts = (await db.execute(select(Receipt.source, Receipt.source_id, Receipt.revision).where(
        Receipt.user_id == user.id,
    ))).all()
    seen = {(source, source_id): revision for source, source_id, revision in receipts}
    items = []
    for comment in sorted(comments, key=lambda item: (item.time, item.source_id), reverse=True):
        status = "seen" if seen.get((comment.source, comment.source_id)) == comment.revision else "new"
        if only_new and status == "seen":
            continue
        items.append({
            "id": comment.id,
            "task": {"id": str(comment.task_id), "title": comment.title, "link": frontend_url(f"/tasks/{comment.task_id}")},
            "author": {"name": comment.author, "initials": initials(comment.author) if comment.author else None},
            "time": comment.time,
            "text": comment.text,
            "status": status,
        })
    return {"items": items}


@router.post("/1h/comments/mark")
async def mark_1h_comment(
    payload: CommentMark,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ensure_assistant_user(user)
    source, raw_id, requested_revision = payload.id.split(":")
    source_id = uuid.UUID(raw_id)
    task_id = source_id
    if source == "user":
        task_id = (await db.execute(select(TaskUserComment.task_id).where(
            TaskUserComment.id == source_id,
        ))).scalar_one_or_none()
    # Comment editors take the task lock before writing. Use the same lock
    # order and load the current revision with a fresh snapshot afterward.
    task = (await db.execute(select(Task.id).where(
        Task.id == task_id, _one_h_task(),
    ).with_for_update(of=Task))).scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="1H comment not found")
    query = (
        _user_comments().where(TaskUserComment.id == source_id).with_for_update(of=TaskUserComment)
        if source == "user" else _marker_comments().where(Task.id == source_id)
    )
    row = (await db.execute(query)).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="1H comment not found")
    comment = Comment(source, *row)
    if comment.revision != requested_revision:
        raise HTTPException(status_code=409, detail="Comment changed. Open the latest version.")
    if payload.status == "seen":
        receipt = insert(Receipt).values(
            user_id=user.id, source=source, source_id=source_id, task_id=comment.task_id, revision=requested_revision,
        )
        await db.execute(receipt.on_conflict_do_update(
            index_elements=[Receipt.user_id, Receipt.source, Receipt.source_id],
            set_={"revision": receipt.excluded.revision},
        ))
    else:
        await db.execute(delete(Receipt).where(
            Receipt.user_id == user.id, Receipt.source == source, Receipt.source_id == source_id,
            Receipt.revision == requested_revision,
        ))
    await db.commit()
    return payload
