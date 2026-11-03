from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, func, Integer, or_, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import UserRole


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), nullable=False, server_default="STAFF")

    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"))

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    weekly_planner_sort_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weekly_planner_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Most user lookups only need department_id. The authentication dependency
    # opts into the joined Department for the one request path that reads it.
    department = relationship("Department", lazy="noload")

    @classmethod
    def work_staff_filter(cls):
        """Household department accounts are active logins, not company staff.

        Apply explicitly to work rosters/assignments. Authentication, account
        administration and GA PERSONAL membership must still find these users.
        Keep unassigned company accounts and all work roles eligible.
        """
        from app.models.department import Department

        household_departments = select(Department.id).where(or_(
            func.upper(func.trim(Department.code)) == "GAP",
            func.upper(func.trim(Department.name)) == "GA PERSONAL",
        ))
        return or_(cls.department_id.is_(None), cls.department_id.not_in(household_departments))

