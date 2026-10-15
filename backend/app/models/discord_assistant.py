from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DiscordLink(Base):
    __tablename__ = "discord_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    discord_user_id: Mapped[str] = mapped_column(String(32))
    guild_id: Mapped[str] = mapped_column(String(32))
    channel_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    selected_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"))
    pending_instruction: Mapped[str | None] = mapped_column(Text)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    selected_fingerprint: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("guild_id", "discord_user_id", name="uq_discord_link_identity"),)


class DiscordLinkCode(Base):
    __tablename__ = "discord_link_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DiscordReminder(Base):
    __tablename__ = "discord_reminders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    link_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("discord_links.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    bucket: Mapped[str] = mapped_column(String(16))
    lease_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message_ids: Mapped[list | None] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("link_id", "day", "bucket", name="uq_discord_reminder_bucket"),)


class DiscordAction(Base):
    __tablename__ = "discord_actions"

    # Discord interaction/message ID is the idempotency key.
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    link_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("discord_links.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    instruction: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="PROCESSING")
    result: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
