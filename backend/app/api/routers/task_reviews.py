from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models.enums import TaskStatus, UserRole
from app.models.project import Project
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_review import TaskReview
from app.models.user import User
from app.schemas.task_review import (
    TaskReviewCreate,
    TaskReviewDeleteSamplesOut,
    TaskReviewOut,
    TaskReviewOverviewOut,
    TaskReviewOverviewRow,
    TaskReviewStatusFilter,
    TaskReviewUpdate,
    TaskReviewUserSummary,
)
from app.services.audit import add_audit_log
from app.services.realization_proposal_diamonds import load_proposal_diamonds


router = APIRouter()


def can_manage_task_reviews(role: UserRole) -> bool:
    return role in (UserRole.ADMIN, UserRole.MANAGER)


def can_create_task_reviews(role: UserRole) -> bool:
    return role in (UserRole.ADMIN, UserRole.MANAGER, UserRole.STAFF)


def can_view_review_for_user(role: UserRole, current_user_id: uuid.UUID, reviewee_user_id: uuid.UUID) -> bool:
    return role in (UserRole.ADMIN, UserRole.MANAGER, UserRole.STAFF)


def can_view_global_review_overview(role: UserRole, review_status: TaskReviewStatusFilter) -> bool:
    return role in (UserRole.ADMIN, UserRole.MANAGER, UserRole.STAFF)


def _clean_comment(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _app_timezone():
    try:
        return ZoneInfo(settings.APP_TIMEZONE)
    except Exception:
        return timezone.utc


def _is_completed_late(completed_at: datetime, due_date: datetime | None) -> bool:
    if due_date is None:
        return False
    app_timezone = _app_timezone()
    completed_value = completed_at if completed_at.tzinfo is not None else completed_at.replace(tzinfo=timezone.utc)
    due_value = due_date if due_date.tzinfo is not None else due_date.replace(tzinfo=timezone.utc)
    return completed_value.astimezone(app_timezone).date() > due_value.astimezone(app_timezone).date()


def _review_out(review: TaskReview) -> TaskReviewOut:
    return TaskReviewOut(
        id=review.id,
        task_id=review.task_id,
        reviewee_user_id=review.reviewee_user_id,
        reviewee_name=review.reviewee_name_snapshot,
        reviewer_user_id=review.reviewer_user_id,
        reviewer_name=review.reviewer_name_snapshot,
        diamond_score=review.diamond_score,
        comment=review.comment,
        is_sample=review.is_sample,
        task_title=review.task_title_snapshot,
        project_title=review.project_title_snapshot,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


async def _task_assignee_ids(db: AsyncSession, task: Task) -> set[uuid.UUID]:
    ids = set(
        (
            await db.execute(select(TaskAssignee.user_id).where(TaskAssignee.task_id == task.id))
        ).scalars().all()
    )
    if task.assigned_to is not None:
        ids.add(task.assigned_to)
    return ids


async def _review_or_404(db: AsyncSession, review_id: uuid.UUID) -> TaskReview:
    review = await db.get(TaskReview, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    return review


@router.get("/overview", response_model=TaskReviewOverviewOut)
async def review_overview(
    date_from: date,
    date_to: date,
    department_id: uuid.UUID | None = None,
    reviewee_user_id: uuid.UUID | None = None,
    review_status: TaskReviewStatusFilter = "all",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskReviewOverviewOut:
    if date_to < date_from:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="date_to must be on or after date_from")
    if date_to - date_from > timedelta(days=366):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Date range cannot exceed 366 days")
    if not can_view_global_review_overview(current_user.role, review_status):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    app_timezone = _app_timezone()
    start_at = datetime.combine(date_from, time.min, tzinfo=app_timezone).astimezone(timezone.utc)
    end_at = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=app_timezone).astimezone(timezone.utc)
    task_stmt = (
        select(Task)
        .where(
            Task.status == TaskStatus.DONE.value,
            Task.completed_at.is_not(None),
            Task.completed_at >= start_at,
            Task.completed_at < end_at,
            Task.is_active.is_(True),
        )
        .order_by(Task.completed_at.desc(), Task.title)
    )
    if department_id is not None:
        task_stmt = task_stmt.where(Task.department_id == department_id)
    tasks = (await db.execute(task_stmt)).scalars().all()
    task_ids = [task.id for task in tasks]
    assignment_rows = (
        await db.execute(
            select(TaskAssignee.task_id, User)
            .join(User, User.id == TaskAssignee.user_id)
            .where(TaskAssignee.task_id.in_(task_ids))
        )
    ).all()
    assignments: dict[uuid.UUID, dict[uuid.UUID, User]] = {}
    for task_id, assigned_user in assignment_rows:
        assignments.setdefault(task_id, {})[assigned_user.id] = assigned_user

    fallback_user_ids = {task.assigned_to for task in tasks if task.assigned_to is not None}
    if fallback_user_ids:
        fallback_users = (
            await db.execute(select(User).where(User.id.in_(fallback_user_ids)))
        ).scalars().all()
        fallback_map = {user.id: user for user in fallback_users}
        for task in tasks:
            if task.assigned_to is not None and task.assigned_to in fallback_map:
                assignments.setdefault(task.id, {})[task.assigned_to] = fallback_map[task.assigned_to]

    project_ids = {task.project_id for task in tasks if task.project_id is not None}
    projects = (
        (await db.execute(select(Project).where(Project.id.in_(project_ids)))).scalars().all()
        if project_ids
        else []
    )
    project_map = {project.id: project for project in projects}

    reviews = (
        await db.execute(select(TaskReview).where(TaskReview.task_id.in_(task_ids)))
    ).scalars().all()
    review_map = {(review.task_id, review.reviewee_user_id): review for review in reviews}

    rows: list[TaskReviewOverviewRow] = []
    for task in tasks:
        for assigned_user in assignments.get(task.id, {}).values():
            if reviewee_user_id is not None and assigned_user.id != reviewee_user_id:
                continue
            review = review_map.get((task.id, assigned_user.id))
            if review_status == "reviewed" and review is None:
                continue
            if review_status == "unreviewed" and review is not None:
                continue
            completed_at = task.completed_at
            if completed_at is None:
                continue
            project = project_map.get(task.project_id)
            rows.append(
                TaskReviewOverviewRow(
                    task_id=task.id,
                    task_title=task.title,
                    project_id=task.project_id,
                    project_title=project.title if project else None,
                    department_id=task.department_id,
                    reviewee_user_id=assigned_user.id,
                    reviewee_name=assigned_user.full_name or assigned_user.username or assigned_user.email,
                    completed_at=completed_at,
                    due_date=task.due_date,
                    is_late=_is_completed_late(completed_at, task.due_date),
                    review=_review_out(review) if review else None,
                )
            )

    if review_status != "unreviewed":
        rows.extend(await load_proposal_diamonds(
            db, date_from=date_from, date_to=date_to, department_id=department_id,
            reviewee_user_id=reviewee_user_id, app_timezone=app_timezone,
        ))
    rows.sort(key=lambda row: row.completed_at.replace(tzinfo=timezone.utc) if row.completed_at.tzinfo is None else row.completed_at, reverse=True)
    summary_state: dict[uuid.UUID, dict] = {}
    for row in rows:
        state = summary_state.setdefault(
            row.reviewee_user_id,
            {
                "user_id": row.reviewee_user_id,
                "user_name": row.reviewee_name,
                "completed_count": 0,
                "reviewed_count": 0,
                "late_count": 0,
                "diamonds_total": 0,
                "proposal_count": 0,
            },
        )
        proposal = row.source == "REALIZATION_PROPOSAL"
        state["proposal_count"] += int(proposal)
        state["completed_count"] += int(not proposal)
        if row.is_late:
            state["late_count"] += 1
        if row.review is not None:
            state["reviewed_count"] += int(not proposal)
            state["diamonds_total"] += row.review.diamond_score

    user_summaries = [
        TaskReviewUserSummary(
            **state,
            unreviewed_count=state["completed_count"] - state["reviewed_count"],
        )
        for state in summary_state.values()
    ]
    user_summaries.sort(key=lambda item: item.user_name.casefold())
    reviewed_count = sum(item.reviewed_count for item in user_summaries)
    diamonds_total = sum(item.diamonds_total for item in user_summaries)
    completed_count = sum(item.completed_count for item in user_summaries)
    return TaskReviewOverviewOut(
        completed_count=completed_count,
        reviewed_count=reviewed_count,
        unreviewed_count=completed_count - reviewed_count,
        diamonds_total=diamonds_total,
        proposal_count=sum(item.proposal_count for item in user_summaries),
        users=user_summaries,
        rows=rows,
    )


@router.get("/task/{task_id}", response_model=list[TaskReviewOut])
async def reviews_for_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[TaskReviewOut]:
    reviews = (
        await db.execute(
            select(TaskReview).where(TaskReview.task_id == task_id).order_by(TaskReview.created_at)
        )
    ).scalars().all()
    return [
        _review_out(review)
        for review in reviews
        if can_view_review_for_user(current_user.role, current_user.id, review.reviewee_user_id)
    ]


@router.post("", response_model=TaskReviewOut, status_code=status.HTTP_201_CREATED)
async def create_review(
    payload: TaskReviewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskReviewOut:
    if not can_create_task_reviews(current_user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if payload.reviewee_user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot review yourself")

    task = await db.get(Task, payload.task_id)
    if task is None or not task.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.status != TaskStatus.DONE.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only completed tasks can be reviewed")
    assignee_ids = await _task_assignee_ids(db, task)
    if payload.reviewee_user_id not in assignee_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reviewee must be assigned to the task")
    reviewee = await db.get(User, payload.reviewee_user_id)
    if reviewee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reviewee not found")
    project = await db.get(Project, task.project_id) if task.project_id else None

    review = TaskReview(
        task_id=task.id,
        reviewee_user_id=reviewee.id,
        reviewer_user_id=current_user.id,
        diamond_score=payload.diamond_score,
        comment=_clean_comment(payload.comment),
        task_title_snapshot=task.title,
        project_title_snapshot=project.title if project else None,
        reviewee_name_snapshot=reviewee.full_name or reviewee.username or reviewee.email,
        reviewer_name_snapshot=current_user.full_name or current_user.username or current_user.email,
    )
    db.add(review)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This user already has a review for this task",
        )
    add_audit_log(
        db=db,
        actor_user_id=current_user.id,
        entity_type="task_review",
        entity_id=review.id,
        action="create",
        after={"task_id": str(task.id), "reviewee_user_id": str(reviewee.id), "diamond_score": review.diamond_score},
    )
    await db.commit()
    await db.refresh(review)
    return _review_out(review)


@router.patch("/{review_id}", response_model=TaskReviewOut)
async def update_review(
    review_id: uuid.UUID,
    payload: TaskReviewUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskReviewOut:
    if not can_manage_task_reviews(current_user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only managers and admins can edit reviews")
    review = await _review_or_404(db, review_id)
    before = {"diamond_score": review.diamond_score, "comment": review.comment}
    if payload.diamond_score is not None:
        review.diamond_score = payload.diamond_score
    if "comment" in payload.model_fields_set:
        review.comment = _clean_comment(payload.comment)
    after = {"diamond_score": review.diamond_score, "comment": review.comment}
    add_audit_log(
        db=db,
        actor_user_id=current_user.id,
        entity_type="task_review",
        entity_id=review.id,
        action="update",
        before=before,
        after=after,
    )
    await db.commit()
    await db.refresh(review)
    return _review_out(review)


@router.delete("/samples", response_model=TaskReviewDeleteSamplesOut)
async def delete_sample_reviews(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TaskReviewDeleteSamplesOut:
    if not can_manage_task_reviews(current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only managers and admins can delete sample reviews",
        )
    reviews = (
        await db.execute(select(TaskReview).where(TaskReview.is_sample.is_(True)))
    ).scalars().all()
    for review in reviews:
        add_audit_log(
            db=db,
            actor_user_id=current_user.id,
            entity_type="task_review",
            entity_id=review.id,
            action="delete_sample",
            before={
                "task_id": str(review.task_id) if review.task_id else None,
                "reviewee_user_id": str(review.reviewee_user_id),
                "diamond_score": review.diamond_score,
            },
        )
        await db.delete(review)
    await db.commit()
    return TaskReviewDeleteSamplesOut(deleted_count=len(reviews))


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_review(
    review_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    if not can_manage_task_reviews(current_user.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only managers and admins can delete reviews")
    review = await _review_or_404(db, review_id)
    add_audit_log(
        db=db,
        actor_user_id=current_user.id,
        entity_type="task_review",
        entity_id=review.id,
        action="delete",
        before={
            "task_id": str(review.task_id) if review.task_id else None,
            "reviewee_user_id": str(review.reviewee_user_id),
            "diamond_score": review.diamond_score,
            "comment": review.comment,
        },
    )
    await db.delete(review)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
