from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(100))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meeting_url: Mapped[str | None] = mapped_column(String(500))
    microsoft_event_id: Mapped[str | None] = mapped_column(String(500), unique=True, index=True)
    calendar_imported: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    calendar_sync_status: Mapped[str | None] = mapped_column(String(20))
    calendar_change_key: Mapped[str | None] = mapped_column(String(500))
    calendar_categories: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    calendar_last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_minutes_before: Mapped[int | None] = mapped_column(Integer, nullable=True, server_default="15")
    meeting_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="external")
    recurrence_type: Mapped[str | None] = mapped_column(String(20))  # "none", "weekly", "monthly"
    recurrence_days_of_week: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    recurrence_days_of_month: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    external_agent_test_task_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    external_pim_image_test_task_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Training sessions keep meeting_type internal/external; Takimet groups them as "Trajnime".
    is_training: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("departments.id"), index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), index=True
    )
    paired_external_meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    pre_external_meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meetings.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    participants: Mapped[list[MeetingParticipant]] = relationship(
        "MeetingParticipant",
        primaryjoin="and_(Meeting.id == MeetingParticipant.meeting_id, MeetingParticipant.assignment_source == 'manual')",
        back_populates="meeting",
        cascade="all, delete-orphan",
    )


class MeetingParticipant(Base):
    __tablename__ = "meeting_participants"
    __table_args__ = (
        CheckConstraint(
            "assignment_source IN ('manual', 'calendar_legacy')",
            name="meeting_participant_assignment_source",
        ),
        UniqueConstraint(
            "meeting_id",
            "user_id",
            "assignment_source",
            name="meeting_participant_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assignment_source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="manual", index=True)
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    meeting: Mapped[Meeting] = relationship("Meeting", back_populates="participants")


class MeetingReminderDelivery(Base):
    __tablename__ = "meeting_reminder_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "user_id",
            "occurrence_starts_at",
            "minutes_before",
            name="uq_meeting_reminder_delivery",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occurrence_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    minutes_before: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
