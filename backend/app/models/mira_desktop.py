"""Owner-scoped desktop capture metadata. Raw audio is never stored here."""
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class MiraDesktopSession(Base):
    __tablename__ = 'mira_desktop_sessions'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('departments.id'))
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default='CAPTURING')
    partial: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(String(100))
    expected_segments: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    note_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('ga_notes.id', ondelete='SET NULL'))
    summary_progress: Mapped[dict | None] = mapped_column(JSONB)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MiraDesktopSegment(Base):
    __tablename__ = 'mira_desktop_segments'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('mira_desktop_sessions.id', ondelete='CASCADE'), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default='PROCESSING')
    transcript: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(String(100))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint('session_id', 'sequence', name='uq_mira_desktop_segment_sequence'),)


# Keep the desktop source separate from Discord's existing source marker. The
# shared PX Notes serializer combines both into its established Mira display.
from sqlalchemy import exists  # noqa: E402
from sqlalchemy.orm import column_property  # noqa: E402
from app.models.ga_note import GaNote  # noqa: E402

GaNote.from_mira_desktop = column_property(
    exists().where(MiraDesktopSession.note_id == GaNote.id))
