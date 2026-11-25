"""Bridge for the GA mentions and staff-channel archive bot."""
from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.services import ga_discord_channel_archive as archive, ga_discord_mentions as mentions

router = APIRouter()

SNOWFLAKE = r"^[0-9]{1,32}$"


def require_mentions_bot(x_ga_mentions_secret: Annotated[str | None, Header()] = None) -> None:
    if not settings.GA_DISCORD_MENTIONS_BOT_TOKEN:
        raise HTTPException(503, "GA Discord mentions bot is not configured")
    if not x_ga_mentions_secret or not hmac.compare_digest(x_ga_mentions_secret, mentions.bridge_secret()):
        raise HTTPException(401, "Invalid bot credentials")


class Attachment(BaseModel):
    name: str = Field(max_length=300)
    url: str = Field(max_length=1000)


class ReactionUser(BaseModel):
    discord_id: str = Field(pattern=SNOWFLAKE)
    name: str = Field(default="", max_length=200)
    ga_bot: bool = False


class ReactionIn(BaseModel):
    emoji: str = Field(min_length=1, max_length=100)
    count: int = Field(ge=0, le=100000)
    users: list[ReactionUser] = Field(default_factory=list, max_length=100)


class MessageIn(BaseModel):
    id: str = Field(pattern=SNOWFLAKE)
    guild_id: str = Field(pattern=SNOWFLAKE)
    channel_id: str = Field(pattern=SNOWFLAKE)
    channel_name: str = Field(default="", max_length=200)
    author_discord_id: str = Field(pattern=SNOWFLAKE)
    author_name: str = Field(default="", max_length=200)
    created_at: datetime
    edited_at: datetime | None = None
    content: str = Field(default="", max_length=8000)
    jump_url: str = Field(max_length=300)
    attachments: list[Attachment] = Field(default_factory=list, max_length=20)
    reply_to_message_id: str | None = Field(default=None, pattern=SNOWFLAKE)
    # Present only when the bot read the reactions (backfill); live messages keep the stored ones.
    reactions: list[ReactionIn] | None = Field(default=None, max_length=50)

    def storage_values(self) -> dict:
        return {
            **self.model_dump(),
            "created_at": self.created_at.astimezone(timezone.utc),
            "edited_at": self.edited_at.astimezone(timezone.utc) if self.edited_at else None,
        }


class MentionIn(MessageIn):
    reasons: list[str] = Field(min_length=1, max_length=3)


class ArchivedMessageIn(MessageIn):
    parent_channel_id: str | None = Field(default=None, pattern=SNOWFLAKE)
    reactions_synced_at: datetime | None = None


class MentionBatch(BaseModel):
    messages: list[MentionIn] = Field(max_length=500)


class ArchiveBatch(BaseModel):
    messages: list[ArchivedMessageIn] = Field(max_length=500)
    checkpoint_channel_id: str | None = Field(default=None, pattern=SNOWFLAKE)


class ReactionsUpdate(BaseModel):
    message_id: str = Field(pattern=SNOWFLAKE)
    reactions: list[ReactionIn] = Field(max_length=50)
    observed_at: datetime | None = None


@router.get("/context", dependencies=[Depends(require_mentions_bot)])
async def context(db: AsyncSession = Depends(get_db)) -> dict:
    last = await mentions.last_message_at(db)
    tracked_ids, unsynced = await mentions.tracked(db)
    return {
        "tracked_message_ids": tracked_ids,
        "reactions_unsynced": unsynced,
        "guild_id": settings.DISCORD_GUILD_ID,
        "staff_channel_id": settings.DISCORD_GA_REPLIES_CHANNEL_ID,
        "archive_checkpoints": await archive.checkpoints(db),
        "ga_discord_id": await mentions.ga_discord_id(db),
        "last_message_at": last.isoformat() if last else None,
        "backfill_hours": settings.GA_DISCORD_MENTIONS_BACKFILL_HOURS,
    }


@router.post("/mentions", dependencies=[Depends(require_mentions_bot)])
async def store_mentions(payload: MentionBatch, db: AsyncSession = Depends(get_db)) -> dict:
    ga_id = await mentions.ga_discord_id(db)
    accepted = []
    for message in payload.messages:
        if message.guild_id != settings.DISCORD_GUILD_ID or message.author_discord_id == ga_id:
            continue  # other servers and GA's own messages are never stored
        if not message.jump_url.startswith("https://discord.com/channels/"):
            continue
        reasons = [reason for reason in message.reasons if reason in mentions.REASONS]
        if not reasons:
            continue
        accepted.append({**message.storage_values(), "reasons": reasons})
    stored = await mentions.store(db, accepted)
    return {"stored": stored, "skipped": len(payload.messages) - stored}


@router.post("/channel-messages", dependencies=[Depends(require_mentions_bot)])
async def store_channel_messages(payload: ArchiveBatch, db: AsyncSession = Depends(get_db)) -> dict:
    accepted = []
    for message in payload.messages:
        if archive.archive_scope(message.guild_id, message.channel_id, message.parent_channel_id):
            values = message.storage_values()
            values["jump_url"] = f"https://discord.com/channels/{message.guild_id}/{message.channel_id}/{message.id}"
            accepted.append(values)
    checkpoint = payload.checkpoint_channel_id
    if checkpoint and (len(accepted) != len(payload.messages) or any(row["channel_id"] != checkpoint for row in accepted)):
        raise HTTPException(422, "Checkpoint must refer to the archived channel for this entire batch.")
    await archive.store_messages(db, accepted, checkpoint_channel_id=checkpoint)
    return {"stored": len(accepted), "skipped": len(payload.messages) - len(accepted)}


@router.post("/reactions", dependencies=[Depends(require_mentions_bot)])
async def store_reactions(payload: ReactionsUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    """Current reactions of an archived message or mention."""
    updated = await mentions.set_reactions(
        db, payload.message_id, [reaction.model_dump() for reaction in payload.reactions], observed_at=payload.observed_at,
    )
    return {"updated": updated}
