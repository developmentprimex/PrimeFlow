from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_manager_or_admin
from app.db import get_db
from app.models.user import User
from app.models.weekly_planner_short import WeeklyPlannerShortComment, WeeklyPlannerShortPoint

router = APIRouter()
PointNumber = Annotated[int, Path(ge=1, le=18)]


class PointInput(BaseModel):
    decision: Literal["check", "o", "x"] | None = None
    owner: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    due_date: date | None = None


class PointOut(PointInput):
    model_config = ConfigDict(from_attributes=True)
    point: int


class CommentInput(BaseModel):
    id: uuid.UUID
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    point: int
    author_name: str
    body: str
    created_at: datetime


class WeekOut(BaseModel):
    points: list[PointOut]
    comments: list[CommentOut]


def monday(week_start: date) -> date:
    if week_start.weekday() != 0:
        raise HTTPException(422, "Zgjidh një datë që bie të hënën.")
    return week_start


@router.get("/{week_start}", response_model=WeekOut)
async def get_week(
    week_start: Annotated[date, Depends(monday)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> WeekOut:
    points = await db.scalars(select(WeeklyPlannerShortPoint).where(WeeklyPlannerShortPoint.week_start == week_start))
    comments = await db.scalars(
        select(WeeklyPlannerShortComment)
        .where(WeeklyPlannerShortComment.week_start == week_start)
        .order_by(WeeklyPlannerShortComment.created_at, WeeklyPlannerShortComment.id)
    )
    return WeekOut(
        points=[PointOut.model_validate(row) for row in points],
        comments=[CommentOut.model_validate(row) for row in comments],
    )


@router.put("/{week_start}/points/{point}", response_model=PointOut)
async def save_point(
    week_start: Annotated[date, Depends(monday)],
    point: PointNumber,
    payload: PointInput,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_manager_or_admin)],
) -> PointOut:
    values = {**payload.model_dump(), "owner": payload.owner or None}
    query = insert(WeeklyPlannerShortPoint).values(week_start=week_start, point=point, **values)
    await db.execute(query.on_conflict_do_update(index_elements=["week_start", "point"], set_=values))
    await db.commit()
    return PointOut(point=point, **values)


@router.post("/{week_start}/points/{point}/comments", response_model=CommentOut, status_code=201)
async def add_comment(
    week_start: Annotated[date, Depends(monday)],
    point: PointNumber,
    payload: CommentInput,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> CommentOut:
    query = insert(WeeklyPlannerShortComment).values(
        id=payload.id, week_start=week_start, point=point,
        author_id=user.id, author_name=user.full_name, body=payload.body,
    )
    await db.execute(query.on_conflict_do_nothing(index_elements=["id"]))
    comment = await db.get(WeeklyPlannerShortComment, payload.id)
    if comment is None or (
        comment.week_start, comment.point, comment.author_id, comment.body
    ) != (week_start, point, user.id, payload.body):
        raise HTTPException(409, "Ky identifikues komenti është përdorur tashmë.")
    result = CommentOut.model_validate(comment)
    await db.commit()
    return result
