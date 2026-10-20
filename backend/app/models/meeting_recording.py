from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MeetingRecording(Base):
    __tablename__ = "meeting_recordings"
    __table_args__ = (
        CheckConstraint("status IN ('CREATED','RECORDING','UPLOADING','FINALIZING','READY','FAILED')", name="recording_status"),
        CheckConstraint("chunks_received >= 0 AND size_bytes >= 0", name="recording_counters"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="SET NULL"), index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    capture_source_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(16), default="CREATED", index=True)
    recording_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    recording_stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    mime_type: Mapped[str] = mapped_column(String(100))
    video_width: Mapped[int | None] = mapped_column(Integer)
    video_height: Mapped[int | None] = mapped_column(Integer)
    has_microphone_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    has_system_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    is_partial: Mapped[bool] = mapped_column(Boolean, default=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    storage_backend: Mapped[str] = mapped_column(String(20), default="local")
    storage_key: Mapped[str] = mapped_column(String(200), unique=True)
    chunks_received: Mapped[int] = mapped_column(Integer, default=0)
    upload_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    error_message: Mapped[str | None] = mapped_column(String(500))


class MeetingRecordingChunk(Base):
    __tablename__ = "meeting_recording_chunks"
    recording_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("meeting_recordings.id", ondelete="CASCADE"), primary_key=True)
    index: Mapped[int] = mapped_column(Integer, primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
