"""Additions observed in the staff-to-GA Discord channel."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DiscordGaReaction(Base):
    __tablename__ = "discord_ga_reactions"
    __table_args__ = (Index("ix_discord_ga_reactions_window", "guild_id", "channel_id", "observed_at"),)

    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32))
    channel_id: Mapped[str] = mapped_column(String(32))
    message_id: Mapped[str] = mapped_column(String(32))
    message_channel_id: Mapped[str | None] = mapped_column(String(32))
    message_author_id: Mapped[str | None] = mapped_column(String(32))
    attachment_count: Mapped[int | None] = mapped_column()
    staff_name: Mapped[str] = mapped_column(String(100))
    message_excerpt: Mapped[str] = mapped_column(String(280))
    emoji: Mapped[str] = mapped_column(String(100))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
