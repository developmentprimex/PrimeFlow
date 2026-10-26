from __future__ import annotations

import uuid
from datetime import datetime, time

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Time, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.enums import CommonApprovalStatus, FrequencyType, SystemTaskScope, TaskFinishPeriod, TaskPriority


class SystemTaskTemplate(Base):
    __tablename__ = "system_task_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String)
    internal_notes: Mapped[str | None] = mapped_column(String)
    department_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"))
    default_assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    assignee_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=True)
    zv1_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    zv2_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    scope: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="ALL",
    )

    frequency: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    day_of_week: Mapped[int | None] = mapped_column(Integer)
    days_of_week: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    day_of_month: Mapped[int | None] = mapped_column(Integer)
    month_of_year: Mapped[int | None] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Europe/Budapest")
    due_time: Mapped[time] = mapped_column(Time, nullable=False, server_default="09:00:00")
    lookahead: Mapped[int] = mapped_column(Integer, nullable=False, server_default="14")
    interval: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    apply_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    trigger_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    priority: Mapped[str | None] = mapped_column(
        String(50), nullable=True, server_default="NORMAL"
    )
    finish_period: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )

    # Optional coordination/alignment settings (informational; does not affect scheduling directly).
    requires_alignment: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    alignment_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    show_in_weekly_planner: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Informational only; independent of recurrence and instance generation.
    is_repetitive: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    approval_status: Mapped[CommonApprovalStatus] = mapped_column(
        Enum(CommonApprovalStatus, name="common_approval_status"),
        nullable=False,
        index=True,
        server_default=CommonApprovalStatus.approved.value,
    )
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

