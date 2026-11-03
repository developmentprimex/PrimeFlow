from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.api.access import ensure_department_access, ensure_manager_or_admin
from app.api.deps import get_current_user
from app.auth.security import get_password_hash
from app.db import get_db
from app.models.department import Department
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.user import UserCreate, UserLookup, UserOut, UserUpdate


router = APIRouter()

USER_OUT_COLUMNS = (
    User.id,
    User.email,
    User.username,
    User.full_name,
    User.role,
    User.department_id,
    User.is_active,
    User.weekly_planner_sort_order,
    User.weekly_planner_hidden,
)


@router.get("", response_model=list[UserOut])
async def list_users(
    include_inactive: bool = False,
    include_all_departments: bool = False,
    include_household: bool = False,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[UserOut]:
    stmt = select(User).options(load_only(*USER_OUT_COLUMNS))
    if include_household:
        if user.role != UserRole.ADMIN:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    else:
        stmt = stmt.where(User.work_staff_filter())
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))
    users = (await db.execute(stmt.order_by(User.created_at))).scalars().all()
    return [
        UserOut(
            id=u.id,
            email=u.email,
            username=u.username,
            full_name=u.full_name,
            role=u.role,
            department_id=u.department_id,
            is_active=u.is_active,
            weekly_planner_sort_order=u.weekly_planner_sort_order,
            weekly_planner_hidden=u.weekly_planner_hidden,
        )
        for u in users
    ]


@router.get("/lookup", response_model=list[UserLookup])
async def list_users_lookup(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[UserLookup]:
    stmt = select(User).where(User.work_staff_filter()).options(
        load_only(
            User.id,
            User.email,
            User.username,
            User.full_name,
            User.role,
            User.department_id,
            User.is_active,
            User.weekly_planner_sort_order,
            User.weekly_planner_hidden,
        )
    )
    if not include_inactive:
        stmt = stmt.where(User.is_active.is_(True))
    users = (await db.execute(stmt.order_by(User.created_at))).scalars().all()
    return [
        UserLookup(
            id=u.id,
            email=u.email,
            username=u.username,
            full_name=u.full_name,
            role=u.role,
            department_id=u.department_id,
            is_active=u.is_active,
            weekly_planner_sort_order=u.weekly_planner_sort_order,
            weekly_planner_hidden=u.weekly_planner_hidden,
        )
        for u in users
    ]


@router.post("", response_model=UserOut)
async def create_user(payload: UserCreate, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)) -> UserOut:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    ensure_department_access(user, payload.department_id)
    dept = (await db.execute(select(Department).where(Department.id == payload.department_id))).scalar_one_or_none()
    if dept is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")

    existing_email = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if existing_email is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    if payload.username is not None:
        existing_username = (
            await db.execute(select(User).where(User.username == payload.username))
        ).scalar_one_or_none()
        if existing_username is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    new_user = User(
        email=payload.email,
        username=payload.username,
        full_name=payload.full_name,
        role=payload.role,
        department_id=payload.department_id,
        password_hash=get_password_hash(payload.password),
        is_active=True,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return UserOut(
        id=new_user.id,
        email=new_user.email,
        username=new_user.username,
        full_name=new_user.full_name,
        role=new_user.role,
        department_id=new_user.department_id,
        is_active=new_user.is_active,
        weekly_planner_sort_order=new_user.weekly_planner_sort_order,
        weekly_planner_hidden=new_user.weekly_planner_hidden,
    )


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current=Depends(get_current_user),
) -> UserOut:
    if current.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.email is not None:
        existing_email = (
            await db.execute(select(User).where(User.email == payload.email, User.id != target.id))
        ).scalar_one_or_none()
        if existing_email is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
        target.email = payload.email
    if payload.username is not None:
        existing_username = (
            await db.execute(select(User).where(User.username == payload.username, User.id != target.id))
        ).scalar_one_or_none()
        if existing_username is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
        target.username = payload.username
    if payload.department_id is not None:
        dept = (await db.execute(select(Department).where(Department.id == payload.department_id))).scalar_one_or_none()
        if dept is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
        target.department_id = payload.department_id
    if payload.full_name is not None:
        target.full_name = payload.full_name
    if payload.role is not None:
        target.role = payload.role
    if payload.is_active is not None:
        target.is_active = payload.is_active
    if payload.password is not None:
        target.password_hash = get_password_hash(payload.password)

    await db.commit()
    await db.refresh(target)
    return UserOut(
        id=target.id,
        email=target.email,
        username=target.username,
        full_name=target.full_name,
        role=target.role,
        department_id=target.department_id,
        is_active=target.is_active,
        weekly_planner_sort_order=target.weekly_planner_sort_order,
        weekly_planner_hidden=target.weekly_planner_hidden,
    )


@router.delete("/{user_id}", response_model=UserOut)
async def deactivate_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current=Depends(get_current_user),
) -> UserOut:
    if current.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.id == current.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate yourself")

    target.is_active = False
    await db.commit()
    await db.refresh(target)
    return UserOut(
        id=target.id,
        email=target.email,
        username=target.username,
        full_name=target.full_name,
        role=target.role,
        department_id=target.department_id,
        is_active=target.is_active,
        weekly_planner_sort_order=target.weekly_planner_sort_order,
        weekly_planner_hidden=target.weekly_planner_hidden,
    )

