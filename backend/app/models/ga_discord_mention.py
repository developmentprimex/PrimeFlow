"""Discord server messages that mention the GA (user or one of her roles) or reply to her.

Written only by the read-only GA mentions bot (``discord_ga_mentions.py``) through
``/api/ga-discord-bot/mentions``; read and marked by the GA assistant.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GaDiscordMention(Base):
    __tablename__ = "ga_discord_mentions"
    __table_args__ = (Index("ix_ga_discord_mentions_status_created", "status", "created_at"),)

    # Discord message id (snowflake) is the idempotency key.
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_name: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    author_discord_id: Mapped[str] = mapped_column(String(32), nullable=False)
    author_name: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    jump_url: Mapped[str] = mapped_column(String(300), nullable=False)
    attachments: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    # "mention" (@GA), "role" (@a role GA has) or "reply" (reply to a GA message).
    reasons: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    reply_to_message_id: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="new")
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
