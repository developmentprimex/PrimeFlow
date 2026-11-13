"""Notes, questions and decisions captured per meeting session (Takimet).

A note lives with its meeting and session. It reaches PX Notes only when a user
sends it (alone or merged with other notes of the same meeting); tasks are then
created from that PX note with the existing PX Notes workflow.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, Text, exists, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from app.db import Base
from app.models.ga_note import GaNote


class MeetingNote(Base):
    __tablename__ = "meeting_notes"
    __table_args__ = (
        CheckConstraint("kind IN ('NOTE','QUESTION')", name="meeting_note_kind"),
        CheckConstraint("source IN ('MANUAL','RECORDING')", name="meeting_note_source"),
        CheckConstraint("manual_status IN ('TODO','IN_PROGRESS','WAITING_CLIENT','WAITING_CONFIRMATION','DONE')", name="meeting_note_manual_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occurrence_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default="NOTE")
    reference: Mapped[str | None] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="MANUAL")
    recording_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_recordings.id", ondelete="SET NULL"), index=True
    )
    recording_action_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recording_actions.id", ondelete="SET NULL"), index=True
    )
    recording_seconds: Mapped[float | None] = mapped_column(Float)
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    due_date: Mapped[date | None] = mapped_column(Date)
    manual_status: Mapped[str] = mapped_column(String(32), nullable=False, default="TODO", server_default="TODO")
    ga_note_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ga_notes.id", ondelete="SET NULL"), index=True
    )
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    attachments = relationship(
        "MeetingNoteAttachment",
        backref="note",
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MeetingNoteAttachment.created_at",
    )


# Load the existing meeting-to-PX link with the note, including older and merged notes.
GaNote.from_meeting = column_property(exists().where(MeetingNote.ga_note_id == GaNote.id))


class MeetingNoteAttachment(Base):
    __tablename__ = "meeting_note_attachments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    note_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meeting_notes.id", ondelete="CASCADE"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
