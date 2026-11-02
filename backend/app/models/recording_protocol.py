"""One durable, cached Word protocol per recording and output language."""
import uuid
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class RecordingProtocol(Base):
    __tablename__ = 'recording_protocols'
    __table_args__ = (
        CheckConstraint("language IN ('en','de')", name='protocol_language'),
        CheckConstraint("status IN ('QUEUED','GENERATING','READY','FAILED')", name='protocol_status'),
    )
    recording_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('meeting_recordings.id', ondelete='CASCADE'), primary_key=True)
    language: Mapped[str] = mapped_column(String(2), primary_key=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey('users.id'))
    status: Mapped[str] = mapped_column(String(16), default='QUEUED', index=True)
    source: Mapped[dict] = mapped_column(JSONB)
    checkpoint: Mapped[dict | None] = mapped_column(JSONB)
    content: Mapped[dict | None] = mapped_column(JSONB)
    document: Mapped[bytes | None] = mapped_column(LargeBinary)
    error_message: Mapped[str | None] = mapped_column(String(500))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
