"""Durable M3 and next-workday questions, scoped to one Discord identity."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class DiscordM3Question(Base):
    __tablename__ = 'discord_m3_questions'
    __table_args__ = (UniqueConstraint('link_id', 'day', 'kind', 'context_key', name='uq_discord_m3_question'),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    link_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('discord_links.id', ondelete='CASCADE'), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('tasks.id', ondelete='CASCADE'), index=True)
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('meetings.id', ondelete='CASCADE'), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    target_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(24))
    context_key: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSONB)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_id: Mapped[str | None] = mapped_column(String(32))
    answer: Mapped[dict | None] = mapped_column(JSONB)
    comment: Mapped[str | None] = mapped_column(Text)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
