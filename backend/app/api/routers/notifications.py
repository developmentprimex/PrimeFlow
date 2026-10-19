from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import String, cast, delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import get_db
from app.models.notification import Notification
from app.schemas.notification import NotificationOut
from app.models.task import Task
from app.services.task_marker_visibility import marker_alert_task


router = APIRouter()


def visible_marker_notifications():
    kind = Notification.data["kind"].astext
    return or_(
        func.coalesce(kind, "").not_in(("task_marker", "task_marker_comment")),
        exists().where(cast(Task.id, String) == Notification.data["task_id"].astext, marker_alert_task(Task)),
    )


def _to_out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        user_id=n.user_id,
        type=n.type,
        title=n.title,
        body=n.body,
        data=n.data,
        created_at=n.created_at,
        read_at=n.read_at,
    )


@router.get("/unread-count")
async def unread_notification_count(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict[str, int]:
    count = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None), visible_marker_notifications())
        )
    ).scalar_one()
    return {"count": int(count or 0)}


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    unread_only: bool = False,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[NotificationOut]:
    stmt = select(Notification).where(Notification.user_id == user.id, visible_marker_notifications())
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    notifications = (await db.execute(stmt.order_by(Notification.created_at.desc()))).scalars().all()
    return [_to_out(n) for n in notifications]


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    n = (
        await db.execute(
            select(Notification).where(Notification.id == notification_id, Notification.user_id == user.id)
        )
    ).scalar_one_or_none()
    if n is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if n.read_at is None:
        n.read_at = datetime.now(timezone.utc)
        await db.commit()
    return {"status": "ok"}


@router.post("/read-all")
async def mark_all_read(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)) -> dict:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=now)
    )
    await db.commit()
    return {"status": "ok"}


@router.post("/delete-all")
async def delete_all_notifications_post(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    await db.execute(delete(Notification).where(Notification.user_id == user.id))
    await db.commit()
    return {"status": "ok"}


@router.post("/{notification_id}/delete")
async def delete_notification_post(
    notification_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    result = await db.execute(
        delete(Notification)
        .where(Notification.id == notification_id, Notification.user_id == user.id)
        .returning(Notification.id)
    )
    deleted_id = result.scalar_one_or_none()
    if deleted_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    await db.commit()
    return {"status": "ok"}


