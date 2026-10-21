"""Mira Host: Mira leads the 1H meetings herself (test feature, started by /mira mbaj-takimet)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class MiraHostSettings(Base):
    __tablename__ = 'mira_host_settings'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    # Hosting runs only until this moment; /mira mbaj-takimet sets it, /mira ndalo clears it.
    enabled_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    # [{"name": "Elza Preniqi", "fallback": "Olsa Hajdari"}, ...] matched against users.full_name.
    ga_participants: Mapped[list] = mapped_column(JSONB, default=list)
    protocol_text: Mapped[str] = mapped_column(Text, default='')
    target_minutes_per_person: Mapped[int] = mapped_column(Integer, default=4)
    knowledge_char_budget: Mapped[int] = mapped_column(Integer, default=24000)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Mira1HMeeting(Base):
    __tablename__ = 'mira_1h_meetings'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_date: Mapped[date] = mapped_column(Date)
    slot: Mapped[str] = mapped_column(String(5))
    # PREP -> GA_PHASE -> STAFF_PHASE -> DONE, or ABORTED.
    status: Mapped[str] = mapped_column(String(20), default='PREP')
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    staff_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voice_meeting_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('discord_voice_meetings.id', ondelete='SET NULL'))
    # [{"at": iso, "role": "mira"|"staff", "speaker": name, "text": ...}]
    host_transcript: Mapped[list] = mapped_column(JSONB, default=list)
    summary: Mapped[str | None] = mapped_column(Text)
    summary_status: Mapped[str | None] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint('meeting_date', 'slot', name='uq_mira_1h_meeting_slot'),)


class Mira1HTurn(Base):
    __tablename__ = 'mira_1h_turns'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('mira_1h_meetings.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    order_idx: Mapped[int] = mapped_column(Integer)
    # WAITING -> ACTIVE -> DONE, or SKIPPED.
    status: Mapped[str] = mapped_column(String(20), default='WAITING')
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, default='')
    __table_args__ = (UniqueConstraint('meeting_id', 'user_id', name='uq_mira_1h_turn_user'),)


class Mira1HMention(Base):
    """What Mira already reported today, so the next 1H does not repeat it."""
    __tablename__ = 'mira_1h_mentions'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_date: Mapped[date] = mapped_column(Date)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'))
    kind: Mapped[str] = mapped_column(String(20))  # DONE / STRIKE
    point_key: Mapped[str] = mapped_column(String(64), default='')
    text: Mapped[str] = mapped_column(Text, default='')
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('mira_1h_meetings.id', ondelete='SET NULL'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint('meeting_date', 'task_id', 'kind', 'point_key', name='uq_mira_1h_mention'),)


class Mira1HEvent(Base):
    """Delivery log and audit trail; (key) makes every invitation idempotent."""
    __tablename__ = 'mira_1h_events'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str | None] = mapped_column(String(200), unique=True)
    meeting_date: Mapped[date] = mapped_column(Date)
    slot: Mapped[str] = mapped_column(String(5))
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('mira_1h_meetings.id', ondelete='CASCADE'))
    kind: Mapped[str] = mapped_column(String(30))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (Index('ix_mira_1h_events_day_slot', 'meeting_date', 'slot'),)


class MiraKnowledgeItem(Base):
    __tablename__ = 'mira_knowledge_items'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(30), default='TJETER')
    content_text: Mapped[str] = mapped_column(Text, default='')
    source: Mapped[str] = mapped_column(String(20), default='MANUAL')  # MANUAL / FILE
    file_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
