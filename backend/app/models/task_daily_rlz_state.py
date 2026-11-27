from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TaskDailyRlzState(Base):
    """Mutable operational input; immutable copies live in Realization close events."""

    __tablename__ = "task_daily_rlz_states"
    __table_args__ = (
        UniqueConstraint("task_id", "user_id", "day_date", name="uq_task_daily_rlz_state_task_user_day"),
        CheckConstraint(
            "reason_code IS NULL OR reason_code IN ('TOOK_LONGER','OTHER_URGENCY','WAITING_CLIENT',"
            "'PRIORITY_CHANGE','TECHNICAL_PROBLEM','MISSING_INFORMATION','REQUEST_CHANGE',"
            "'NEW_REQUESTS','ABSENCE','OTHER','PV','WEEKLY_PLANNING')",
            name="ck_task_daily_rlz_state_reason_code",
        ),
        Index("ix_task_daily_rlz_state_user_day", "user_id", "day_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    day_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    reason_code: Mapped[str | None] = mapped_column(String(40))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
