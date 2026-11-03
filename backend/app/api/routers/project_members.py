from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.api.access import ensure_department_access
from app.api.deps import get_current_user
from app.db import get_db
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.schemas.user import UserOut


router = APIRouter()


class ProjectMembersCreatePayload(BaseModel):
    project_id: uuid.UUID
    user_ids: list[uuid.UUID]


class ProjectMembersBatchItem(BaseModel):
    project_id: uuid.UUID
    members: list[UserOut]


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        department_id=user.department_id,
        is_active=user.is_active,
    )


@router.get("/batch", response_model=list[ProjectMembersBatchItem])
async def list_project_members_batch(
    project_ids: list[uuid.UUID] = Query(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[ProjectMembersBatchItem]:
    """Resolve many project member lists in a single database round trip."""

    unique_ids = list(dict.fromkeys(project_ids))
    if not unique_ids:
        return []
    rows = (
        await db.execute(
            select(ProjectMember.project_id, User).where(User.work_staff_filter())
            .options(
                load_only(
                    User.id,
                    User.email,
                    User.username,
                    User.full_name,
                    User.role,
                    User.department_id,
                    User.is_active,
                )
            )
            .join(User, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id.in_(unique_ids))
            .order_by(ProjectMember.project_id, User.full_name)
        )
    ).all()
    members_by_project: dict[uuid.UUID, list[UserOut]] = {project_id: [] for project_id in unique_ids}
    for project_id, member in rows:
        members_by_project[project_id].append(_user_out(member))
    return [
        ProjectMembersBatchItem(project_id=project_id, members=members_by_project[project_id])
        for project_id in unique_ids
    ]


@router.get("", response_model=list[UserOut])
async def list_project_members(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[UserOut]:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    members = (
        await db.execute(
            select(User).where(User.work_staff_filter())
            .options(
                load_only(
                    User.id,
                    User.email,
                    User.username,
                    User.full_name,
                    User.role,
                    User.department_id,
                    User.is_active,
                )
            )
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == project_id)
            .order_by(User.full_name)
        )
    ).scalars().all()

    return [_user_out(u) for u in members]


@router.post("", response_model=list[UserOut], status_code=status.HTTP_201_CREATED)
async def add_project_members(
    payload: ProjectMembersCreatePayload,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[UserOut]:
    project = (await db.execute(select(Project).where(Project.id == payload.project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.department_id is not None:
        ensure_department_access(user, project.department_id)

    if not payload.user_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_ids required")

    rows = (await db.execute(select(User).where(User.work_staff_filter()).where(User.id.in_(payload.user_ids)))).scalars().all()
    if len(rows) != len(set(payload.user_ids)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid users")

    for u in rows:
        if project.department_id is not None and u.department_id != project.department_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User must be in department")

    existing = (
        await db.execute(
            select(ProjectMember.user_id).where(ProjectMember.project_id == payload.project_id)
        )
    ).scalars().all()
    existing_set = set(existing)

    for u in rows:
        if u.id in existing_set:
            continue
        db.add(ProjectMember(project_id=payload.project_id, user_id=u.id))

    await db.commit()

    return [_user_out(u) for u in rows]
