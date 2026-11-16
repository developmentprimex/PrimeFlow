from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TaskOneHMarkerHistory(Base):
    __tablename__ = "task_one_h_marker_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marker_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # NULL is a deliberate tombstone: the user manually removed the symbol on
    # marker_date, so older symbols must not carry past that date.
    one_h_marker: Mapped[str | None] = mapped_column(String(32), nullable=True)
    one_h_marker_by_ga: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    one_h_marker_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("task_id", "marker_date", name="uq_task_one_h_marker_history_task_date"),
    )
