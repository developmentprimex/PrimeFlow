"""Bridge for the read-only GA Discord mentions bot (``discord_ga_mentions.py``).

The bot never writes to Discord. It reads server channels and sends here only the
messages that mention the GA, mention one of her roles, or reply to one of her messages.
"""
from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.services import ga_discord_mentions as mentions

router = APIRouter()

SNOWFLAKE = r"^\d{1,32}$"


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


class ReactionIn(BaseModel):
    emoji: str = Field(min_length=1, max_length=100)
    count: int = Field(ge=0, le=100000)
    users: list[ReactionUser] = Field(default_factory=list, max_length=100)


class MentionIn(BaseModel):
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
    reasons: list[str] = Field(min_length=1, max_length=3)
    reply_to_message_id: str | None = Field(default=None, pattern=SNOWFLAKE)
    # Present only when the bot read the reactions (backfill); live messages keep the stored ones.
    reactions: list[ReactionIn] | None = Field(default=None, max_length=50)


class MentionBatch(BaseModel):
    messages: list[MentionIn] = Field(max_length=500)


class ReactionsUpdate(BaseModel):
    message_id: str = Field(pattern=SNOWFLAKE)
    reactions: list[ReactionIn] = Field(max_length=50)


@router.get("/context", dependencies=[Depends(require_mentions_bot)])
async def context(db: AsyncSession = Depends(get_db)) -> dict:
    last = await mentions.last_message_at(db)
    tracked_ids, unsynced = await mentions.tracked(db)
    return {
        "tracked_message_ids": tracked_ids,
        "reactions_unsynced": unsynced,
        "guild_id": settings.DISCORD_GUILD_ID,
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
        accepted.append({
            **message.model_dump(exclude={"attachments", "reasons", "reactions"}),
            "reactions": None if message.reactions is None else [reaction.model_dump() for reaction in message.reactions],
            "created_at": message.created_at.astimezone(timezone.utc),
            "edited_at": message.edited_at.astimezone(timezone.utc) if message.edited_at else None,
            "attachments": [attachment.model_dump() for attachment in message.attachments],
            "reasons": reasons,
        })
    stored = await mentions.store(db, accepted)
    return {"stored": stored, "skipped": len(payload.messages) - stored}


@router.post("/reactions", dependencies=[Depends(require_mentions_bot)])
async def store_reactions(payload: ReactionsUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    """Current reactions of a stored mention (ignored for any other message)."""
    updated = await mentions.set_reactions(db, payload.message_id, [reaction.model_dump() for reaction in payload.reactions])
    return {"updated": updated}
