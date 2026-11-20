"""GA Discord mentions: storage, identity and read model for the GA assistant.

The read-only bot (``discord_ga_mentions.py``) sends every server-channel message that
mentions the GA, mentions a role she has, or replies to one of her messages. DMs are
never read. The bot authenticates with a secret derived from ``JWT_SECRET`` so no
extra secret has to be configured: both processes read the same ``backend/.env``.
"""
from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.discord_assistant import DiscordLink
from app.models.ga_discord_mention import GaDiscordMention
from app.models.user import User

STATUSES = ("new", "seen", "done")
OPEN_STATUSES = ("new", "seen")
REASONS = ("mention", "role", "reply")
BRIDGE_LABEL = b"primeflow-ga-discord-mentions-bridge-v1"


def bridge_secret() -> str:
    """Shared secret of the mentions bot and the API (derived, never stored)."""
    return hmac.new(settings.JWT_SECRET.encode("utf-8"), BRIDGE_LABEL, hashlib.sha256).hexdigest()


def initials(name: str | None) -> str:
    from app.services.meetings_report import _initials  # PrimeFlow report initials (e.g. LH, FG, DV)

    return _initials(name)


async def ga_discord_id(db: AsyncSession, guild_id: str | None = None) -> str | None:
    """The GA's Discord user id: explicit override, else her PrimeFlow Discord link."""
    if settings.GA_DISCORD_USER_ID:
        return settings.GA_DISCORD_USER_ID.strip() or None
    guild = guild_id or settings.DISCORD_GUILD_ID
    if not guild:
        return None
    return (
        await db.execute(
            select(DiscordLink.discord_user_id)
            .join(User, User.id == DiscordLink.user_id)
            .where(
                User.username == settings.GA_USERNAME,
                User.is_active.is_(True),
                DiscordLink.enabled.is_(True),
                DiscordLink.guild_id == guild,
            )
        )
    ).scalars().first()


async def last_message_at(db: AsyncSession) -> datetime | None:
    return (
        await db.execute(select(GaDiscordMention.created_at).order_by(GaDiscordMention.created_at.desc()).limit(1))
    ).scalar_one_or_none()


async def _linked_users(db: AsyncSession, guild_id: str, discord_ids: set[str]) -> dict[str, uuid.UUID]:
    if not discord_ids:
        return {}
    rows = await db.execute(
        select(DiscordLink.discord_user_id, DiscordLink.user_id).where(
            DiscordLink.guild_id == guild_id, DiscordLink.discord_user_id.in_(discord_ids)
        )
    )
    return {discord_id: user_id for discord_id, user_id in rows.all()}


async def store(db: AsyncSession, messages: list[dict[str, Any]]) -> int:
    """Insert new mentions; on a repeat (edit/backfill) refresh the text but keep the status."""
    if not messages:
        return 0
    users = await _linked_users(db, messages[0]["guild_id"], {m["author_discord_id"] for m in messages})
    for message in messages:
        values = {**message, "author_user_id": users.get(message["author_discord_id"])}
        statement = insert(GaDiscordMention).values(**values)
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=[GaDiscordMention.id],
                set_={
                    "content": statement.excluded.content,
                    "edited_at": statement.excluded.edited_at,
                    "attachments": statement.excluded.attachments,
                    "reasons": statement.excluded.reasons,
                    "channel_name": statement.excluded.channel_name,
                    "author_name": statement.excluded.author_name,
                    "author_user_id": statement.excluded.author_user_id,
                },
            )
        )
    await db.commit()
    return len(messages)


async def author_names(db: AsyncSession, rows: list[GaDiscordMention]) -> dict[uuid.UUID, str]:
    ids = {row.author_user_id for row in rows if row.author_user_id}
    if not ids:
        return {}
    result = await db.execute(select(User.id, User.full_name, User.username).where(User.id.in_(ids)))
    return {user_id: (full_name or username or "") for user_id, full_name, username in result.all()}


def mention_out(row: GaDiscordMention, names: dict[uuid.UUID, str], tz: ZoneInfo) -> dict[str, Any]:
    name = names.get(row.author_user_id) if row.author_user_id else None
    return {
        "id": f"dc:{row.id}",
        "author": name or row.author_name,
        "author_initials": initials(name or row.author_name),
        "author_in_primeflow": bool(name),
        "channel": f"#{row.channel_name}" if row.channel_name else row.channel_id,
        "time": row.created_at.astimezone(tz).isoformat(),
        "edited_at": row.edited_at.astimezone(tz).isoformat() if row.edited_at else None,
        "text": row.content,
        "url": row.jump_url,
        "attachments": row.attachments or [],
        "reasons": row.reasons or [],
        "status": row.status,
    }


async def list_mentions(
    db: AsyncSession, *, since: datetime | None, until: datetime | None, statuses: tuple[str, ...] | None
) -> list[GaDiscordMention]:
    statement = select(GaDiscordMention).order_by(GaDiscordMention.created_at)
    if since is not None:
        statement = statement.where(GaDiscordMention.created_at >= since.astimezone(timezone.utc))
    if until is not None:
        statement = statement.where(GaDiscordMention.created_at < until.astimezone(timezone.utc))
    if statuses:
        statement = statement.where(GaDiscordMention.status.in_(statuses))
    return list((await db.execute(statement.limit(1000))).scalars().all())
