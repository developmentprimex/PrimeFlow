from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class DiscordVoiceMeeting(Base):
    __tablename__ = 'discord_voice_meetings'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    link_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('discord_links.id', ondelete='CASCADE'))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('departments.id'))
    guild_id: Mapped[str] = mapped_column(String(32))
    voice_channel_id: Mapped[str] = mapped_column(String(32))
    private_channel_id: Mapped[str] = mapped_column(String(32))
    request_id: Mapped[str] = mapped_column(String(32), unique=True)
    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    capture_token_hash: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default='STARTING')
    partial: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(String(500))
    expected_segments: Mapped[int | None] = mapped_column(Integer)
    stop_authorized: Mapped[bool] = mapped_column(Boolean, default=False)
    draft_text: Mapped[str | None] = mapped_column(Text)
    summary_progress: Mapped[dict | None] = mapped_column(JSONB)
    saved_note_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('ga_notes.id', ondelete='SET NULL'))
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    delivery_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_ids: Mapped[list | None] = mapped_column(JSONB)
    __table_args__ = (Index('uq_discord_voice_active_guild', 'guild_id', unique=True,
        postgresql_where=text("status IN ('STARTING','LISTENING')")),)


class DiscordVoiceSegment(Base):
    __tablename__ = 'discord_voice_segments'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('discord_voice_meetings.id', ondelete='CASCADE'), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    speaker_id: Mapped[str] = mapped_column(String(32))
    speaker_name: Mapped[str] = mapped_column(String(100))
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default='PROCESSING')
    transcript: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(String(100))
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint('session_id', 'sequence', name='uq_voice_segment_sequence'),)
