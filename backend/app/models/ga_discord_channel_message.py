from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GaDiscordChannelMessage(Base):
    __tablename__ = "ga_discord_channel_messages"
    __table_args__ = (
        Index("ix_ga_discord_channel_author_time", "channel_id", "author_discord_id", "created_at"),
        Index("ix_ga_discord_channel_reply", "reply_to_message_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(32))
    channel_id: Mapped[str] = mapped_column(String(32))
    parent_channel_id: Mapped[str | None] = mapped_column(String(32))
    channel_name: Mapped[str] = mapped_column(String(200))
    author_discord_id: Mapped[str] = mapped_column(String(32))
    author_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content: Mapped[str] = mapped_column(Text)
    jump_url: Mapped[str] = mapped_column(String(300))
    attachments: Mapped[list] = mapped_column(JSONB, server_default="[]")
    reply_to_message_id: Mapped[str | None] = mapped_column(String(32))
    reply_context_ids: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    reactions: Mapped[list] = mapped_column(JSONB, server_default="[]")
    reactions_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reaction_session_id: Mapped[str | None] = mapped_column(String(32))
    reaction_sequence: Mapped[int | None] = mapped_column(BigInteger)


class GaDiscordReactionEvent(Base):
    __tablename__ = "ga_discord_reaction_events"

    message_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    user_id: Mapped[str | None] = mapped_column(String(32))
    emoji_key: Mapped[str | None] = mapped_column(String(100))
    burst: Mapped[bool] = mapped_column(Boolean, server_default="false")


class GaDiscordArchiveCheckpoint(Base):
    __tablename__ = "ga_discord_archive_checkpoints"

    channel_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_message_id: Mapped[str] = mapped_column(String(32))
