from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MeetingSchedulingStandard(Base):
    __tablename__ = "meeting_scheduling_standards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    meeting_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title_prefix: Mapped[str | None] = mapped_column(String(80))
    default_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")
    buffer_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    workday_start: Mapped[str] = mapped_column(String(5), nullable=False, server_default="08:00")
    workday_end: Mapped[str] = mapped_column(String(5), nullable=False, server_default="17:00")
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MeetingScheduleRequest(Base):
    __tablename__ = "meeting_schedule_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    meeting_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    platform: Mapped[str | None] = mapped_column(String(100))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    client_name: Mapped[str | None] = mapped_column(String(200))
    client_email: Mapped[str | None] = mapped_column(String(320))
    notes: Mapped[str | None] = mapped_column(Text)
    department_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id"), nullable=False, index=True
    )
    is_training: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    standard_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_scheduling_standards.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="PENDING_APPROVAL", index=True)
    validation_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    microsoft_event_id: Mapped[str | None] = mapped_column(String(500))
    teams_url: Mapped[str | None] = mapped_column(String(1000))
    final_meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="SET NULL")
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    rejected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MeetingScheduleRequestParticipant(Base):
    __tablename__ = "meeting_schedule_request_participants"
    __table_args__ = (
        UniqueConstraint("request_id", "user_id", name="uq_meeting_schedule_request_participant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_schedule_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MeetingScheduleApproval(Base):
    __tablename__ = "meeting_schedule_approvals"
    __table_args__ = (
        UniqueConstraint("request_id", "approved_by_user_id", name="uq_meeting_schedule_approval_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_schedule_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    approved_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
