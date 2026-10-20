"""Durable AI progress; never changes the source recording's READY status."""
import uuid
from datetime import date, datetime
from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class RecordingAnalysis(Base):
    __tablename__ = 'recording_analyses'
    __table_args__ = (CheckConstraint("status IN ('QUEUED','TRANSCRIBING','SUMMARIZING','READY','FAILED')", name='analysis_status'),)
    recording_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('meeting_recordings.id', ondelete='CASCADE'), primary_key=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(16), default='QUEUED', index=True)
    language: Mapped[str] = mapped_column(String(8), default='sq')
    total_segments: Mapped[int] = mapped_column(Integer)
    segments_done: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[str | None] = mapped_column(Text)
    summary_progress: Mapped[dict | None] = mapped_column(JSONB)
    decisions: Mapped[list | None] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    error_message: Mapped[str | None] = mapped_column(String(500))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RecordingTranscript(Base):
    __tablename__ = 'recording_transcripts'
    recording_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('recording_analyses.recording_id', ondelete='CASCADE'), primary_key=True)
    index: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_seconds: Mapped[int] = mapped_column(Integer)
    duration_seconds: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    notes: Mapped[dict | None] = mapped_column(JSONB)


class RecordingAction(Base):
    __tablename__ = 'recording_actions'
    __table_args__ = (UniqueConstraint('recording_id', 'fingerprint'),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recording_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('recording_analyses.recording_id', ondelete='CASCADE'), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    segment_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    assignee_text: Mapped[str | None] = mapped_column(String(200))
    deadline_text: Mapped[str | None] = mapped_column(String(200))
    suggested_assignee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'))
    suggested_due_date: Mapped[date | None] = mapped_column(Date)
    created_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('tasks.id', ondelete='SET NULL'))
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
