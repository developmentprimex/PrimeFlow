"""Durable, person-specific M2 questions and their answers."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from sqlalchemy import Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class DiscordM2Question(Base):
    __tablename__ = "discord_m2_questions"
    __table_args__ = (UniqueConstraint("link_id", "day", "task_id", "kind", "context_key", name="uq_discord_m2_question"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    link_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("discord_links.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(16))
    context_key: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(JSONB)
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_id: Mapped[str | None] = mapped_column(String(32))
    reason_code: Mapped[str | None] = mapped_column(String(40))
    comment: Mapped[str | None] = mapped_column(Text)
    choice: Mapped[str | None] = mapped_column(String(2))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    platform_answer: Mapped[dict | None] = mapped_column(JSONB)
    platform_answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_hash: Mapped[str | None] = mapped_column(String(64))
    sync_pending_hash: Mapped[str | None] = mapped_column(String(64))
    sync_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
