"""Single source of truth for identifying the GA (CEO) account.

Historically the GA user was found through ``GA_USERNAME``/``GA_EMAIL`` constants
copied into several modules. They now all read ``settings.GA_USERNAME`` and
``settings.GA_USER_EMAIL``; the defaults are the previous constant values, so
behaviour is unchanged unless the environment overrides them.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User


def ga_email() -> str:
    return (settings.GA_USER_EMAIL or "").strip().casefold()


def ga_username() -> str:
    return (settings.GA_USERNAME or "").strip().casefold()


def is_ga_email(value: str | None) -> bool:
    email = ga_email()
    return bool(email) and (value or "").strip().casefold() == email


def is_ga_username(value: str | None) -> bool:
    username = ga_username()
    return bool(username) and (value or "").strip().casefold() == username


def is_ga_user(user: object | None) -> bool:
    if user is None:
        return False
    return is_ga_username(getattr(user, "username", None)) or is_ga_email(getattr(user, "email", None))


async def resolve_ga_user(db: AsyncSession, *, work_staff_only: bool = False) -> User | None:
    """Find the GA user by username first, then by email (the historical order)."""
    stmt = select(User).where(func.lower(User.username) == ga_username())
    if work_staff_only:
        stmt = stmt.where(User.work_staff_filter())
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is not None:
        return user
    stmt = select(User).where(func.lower(User.email) == ga_email())
    if work_staff_only:
        stmt = stmt.where(User.work_staff_filter())
    return (await db.execute(stmt)).scalar_one_or_none()
