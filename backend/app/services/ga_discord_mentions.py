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
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from sqlalchemy import Select, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.audit_log import AuditLog
from app.models.discord_assistant import DiscordLink
from app.models.ga_discord_channel_message import (
    GaDiscordChannelMessage,
    GaDiscordReactionEvent,
)
from app.models.ga_discord_mention import GaDiscordMention
from app.models.user import User
from app.schemas.ga_discord_mentions import DiscordAttachmentLink
from app.services import ga_discord_channel_archive as archive

STATUSES = ("new", "seen", "done")
TRACKED_DAYS = 30  # reactions are followed on mentions of the last 30 days
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
        if values.get("reactions") is None:
            values.pop("reactions", None)  # a live message/edit carries no reaction users: keep the stored ones
        else:
            values["reactions_synced_at"] = datetime.now(timezone.utc)
        statement = insert(GaDiscordMention).values(**values)
        update = {
            "content": statement.excluded.content,
            "edited_at": statement.excluded.edited_at,
            "attachments": statement.excluded.attachments,
            "reasons": statement.excluded.reasons,
            "channel_name": statement.excluded.channel_name,
            "author_name": statement.excluded.author_name,
            "author_user_id": statement.excluded.author_user_id,
        }
        if "reactions" in values:
            update["reactions"] = statement.excluded.reactions
            update["reactions_synced_at"] = statement.excluded.reactions_synced_at
        await db.execute(statement.on_conflict_do_update(index_elements=[GaDiscordMention.id], set_=update))
    await db.commit()
    return len(messages)


async def set_reactions(
    db: AsyncSession, message_id: str, reactions: list[dict[str, Any]], *, observed_at: datetime | None = None,
) -> bool:
    """Update the reactions wherever this Discord message was captured."""
    observed_at = observed_at or datetime.now(timezone.utc)
    updated = False
    for model in (GaDiscordMention, GaDiscordChannelMessage):
        values = {"reactions": reactions, "reactions_synced_at": observed_at}
        newer_snapshot = model.reactions_synced_at <= observed_at
        if model is GaDiscordChannelMessage:
            # A staff snapshot is already stored by the archive endpoint. An
            # independent, newer REST-only update has no matching event cursor.
            newer_snapshot = model.reactions_synced_at < observed_at
            values.update(reaction_session_id=None, reaction_sequence=None)
        row_id = await db.scalar(
            update(model).where(
                model.id == message_id,
                or_(model.reactions_synced_at.is_(None), newer_snapshot),
            ).values(**values).returning(model.id)
        )
        updated |= row_id is not None
    await db.commit()
    return updated


async def tracked(db: AsyncSession) -> tuple[list[str], list[dict[str, str]]]:
    """Recent stored mention ids (reactions followed) and those whose reactions were never read."""
    since = datetime.now(timezone.utc) - timedelta(days=TRACKED_DAYS)
    rows = (
        await db.execute(
            select(GaDiscordMention.id, GaDiscordMention.channel_id, GaDiscordMention.reactions_synced_at)
            .where(GaDiscordMention.created_at >= since)
            .order_by(GaDiscordMention.created_at.desc())
            .limit(5000)
        )
    ).all()
    ids = [row.id for row in rows]
    unsynced = [{"id": row.id, "channel_id": row.channel_id} for row in rows if row.reactions_synced_at is None][:500]
    return ids, unsynced


def approval_emojis() -> set[str]:
    return {normalize_emoji(item) for item in settings.GA_DISCORD_APPROVAL_EMOJIS.split(",") if item.strip()}


def normalize_emoji(value: str) -> str:
    """✔️ == ✔ and 👍🏽 == 👍 (variation selector and skin tones do not matter)."""
    return "".join(ch for ch in value.strip() if ch != "\ufe0f" and not 0x1F3FB <= ord(ch) <= 0x1F3FF)


async def reactor_names(db: AsyncSession, rows: list[GaDiscordMention | GaDiscordChannelMessage]) -> dict[str, str]:
    """Discord user id -> PrimeFlow name for everyone who reacted (linked users only)."""
    ids = {str(user.get("discord_id")) for row in rows for reaction in (row.reactions or []) for user in reaction.get("users") or []}
    return await _discord_display_names(db, ids)


async def _discord_display_names(db: AsyncSession, discord_ids: set[str], *, guild_id: str | None = None) -> dict[str, str]:
    if not discord_ids:
        return {}
    statement = (
        select(DiscordLink.discord_user_id, User.full_name, User.username)
        .join(User, User.id == DiscordLink.user_id)
        .where(DiscordLink.discord_user_id.in_(discord_ids))
    )
    if guild_id:
        statement = statement.where(DiscordLink.guild_id == guild_id)
    result = await db.execute(statement)
    return {discord_id: (full_name or username or "") for discord_id, full_name, username in result.all()}


def reactions_out(
    row: GaDiscordMention | GaDiscordChannelMessage, people: dict[str, str], ga_id: str | None, approvals: set[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Reactions with names/initials, and initials of the reviewers (approval emoji, not author, not GA)."""
    out: list[dict[str, Any]] = []
    reviewed: list[str] = []
    for reaction in getattr(row, "reactions", None) or []:
        users = []
        for user in reaction.get("users") or []:
            discord_id = str(user.get("discord_id") or "")
            name = people.get(discord_id) or user.get("name") or ""
            users.append({"name": name, "initials": initials(name)})
            counts = not user.get("ga_bot") and normalize_emoji(str(reaction.get("emoji") or "")) in approvals
            if counts and discord_id not in {row.author_discord_id, ga_id or ""}:
                code = initials(name)
                if code and code not in reviewed:
                    reviewed.append(code)
        out.append({"emoji": reaction.get("emoji"), "count": int(reaction.get("count") or len(users)), "users": users})
    return out, reviewed


async def render(db: AsyncSession, rows: list[GaDiscordMention], tz: ZoneInfo) -> list[dict[str, Any]]:
    names = await author_names(db, rows)
    people = await reactor_names(db, rows)
    ga_id = await ga_discord_id(db)
    approvals = approval_emojis()
    return [mention_out(row, names, tz, people=people, ga_id=ga_id, approvals=approvals) for row in rows]


async def render_with_context(db: AsyncSession, rows: list[GaDiscordMention], tz: ZoneInfo) -> list[dict[str, Any]]:
    if not rows:
        return []
    items = await render(db, rows, tz)
    candidate_ids = [row.id for row in rows if archive.archive_scope(row.guild_id, row.channel_id, None)
                     and "mention" in row.reasons]
    await _add_context(db, rows, items, tz, candidate_ids)
    return items


async def _add_context(
    db: AsyncSession, rows: list[GaDiscordMention], items: list[dict[str, Any]], tz: ZoneInfo,
    candidate_ids: list[str],
) -> set[tuple[str, str, str]]:
    contexts = {
        row.id: {"para": [], "pas": [], "reply": None, "përgjigjet": []}
        for row in rows
    }
    for row, item in zip(rows, items, strict=True):
        item["context"] = contexts[row.id]
    if not candidate_ids:
        return set()

    matches = await archive.context_rows(db, candidate_ids)
    if not matches:
        return set()
    messages = {row.id: row for _, row, *_ in matches}
    people = await reactor_names(db, list(messages.values()))
    authors = await _discord_display_names(db, {row.author_discord_id for row in messages.values()},
                                          guild_id=settings.DISCORD_GUILD_ID)
    rendered = {}
    for row in messages.values():
        name = authors.get(row.author_discord_id) or row.author_name
        value = message_out(row, name, tz)
        value["attachments"] = [{"name": file["name"]} for file in row.attachments or []]
        value["reactions"] = reactions_out(row, people, None, set())[0]
        rendered[row.id] = value
    for anchor_id, row, before, after, original, response in matches:
        value = rendered[row.id]
        context = contexts[anchor_id]
        if before:
            context["para"].append(value)
        if after:
            context["pas"].append(value)
        if original:
            context["reply"] = value
        if response:
            context["përgjigjet"].append(value)
    return {(anchor_id, row.id, row.author_discord_id) for anchor_id, row, *_, response in matches if response}


def feed_reaction_activity(
    row: GaDiscordMention | GaDiscordChannelMessage, events: list[GaDiscordReactionEvent],
    ga_id: str | None, names: dict[str, str],
) -> tuple[bool, list[str], bool]:
    """Current GA reaction, proven earlier colleagues, and whether the ordering is complete."""
    possible_ga = set()
    colleagues = {}
    snapshots = row.reactions or []
    complete = row.reactions_synced_at is not None
    for reaction in snapshots:
        users = reaction.get("users") or []
        complete &= len(users) == reaction["count"]
        emoji_key = reaction.get("emoji_key") or reaction["emoji"]
        for user in users:
            discord_id = user["discord_id"]
            key = (emoji_key, discord_id, bool(user.get("burst")))
            if discord_id == ga_id or user.get("ga_bot"):
                possible_ga.add(key)
            elif not user.get("bot"):
                colleagues[key] = names.get(discord_id) or user.get("name") or discord_id
    reacted = bool(possible_ga)
    if not colleagues:
        return reacted, [], complete

    last_sequence = getattr(row, "reaction_sequence", None)
    if not reacted or not last_sequence or ga_id is None or not complete:
        return reacted, [], False
    timeline = sorted((event for event in events if event.sequence <= last_sequence), key=lambda event: event.sequence)
    if len(timeline) != last_sequence:
        return reacted, [], False

    active = {}
    for event in timeline:
        key = (event.emoji_key, event.user_id, event.burst)
        if event.kind == "add":
            active.setdefault(key, event.sequence)
        elif event.kind == "remove":
            active.pop(key, None)
        elif event.kind == "clear_emoji":
            active = {key: seq for key, seq in active.items() if key[0] != event.emoji_key}
        else:
            active.clear()
    if not possible_ga.issubset(active):
        return reacted, [], False
    cutoff = min(active[key] for key in possible_ga)
    earlier = sorted(
        ((active[key], name) for key, name in colleagues.items() if key in active and active[key] < cutoff),
    )
    return reacted, list(dict.fromkeys(name for _, name in earlier)), colleagues.keys() <= active.keys()


async def render_feed(db: AsyncSession, rows: list[GaDiscordMention], tz: ZoneInfo) -> list[dict[str, Any]]:
    if not rows:
        return []
    ids = [row.id for row in rows]
    archived = {row.id: row for row in await db.scalars(
        select(GaDiscordChannelMessage).where(GaDiscordChannelMessage.id.in_(ids))
    )}
    snapshots = []
    for row in rows:
        candidate = archived.get(row.id)
        if (candidate is not None and candidate.reactions_synced_at is not None
                and (row.reactions_synced_at is None or candidate.reactions_synced_at >= row.reactions_synced_at)):
            snapshots.append(candidate)
        else:
            snapshots.append(row)
    people = await reactor_names(db, snapshots)
    ga_id = await ga_discord_id(db)
    authors = await author_names(db, rows)
    approvals = approval_emojis()
    items = [mention_out(row, authors, tz, people=people, ga_id=ga_id, approvals=approvals) for row in rows]
    responses = await _add_context(db, rows, items, tz, ids)
    reply_ids = {reply_id for _, reply_id, author_id in responses if author_id != ga_id}
    audited = set()
    if reply_ids:
        discord_id = AuditLog.after["discord_id"].as_string()
        entity_ids = [uuid.uuid5(uuid.NAMESPACE_URL, f"primeflow-ga-assistant:dc:{reply_id}") for reply_id in reply_ids]
        audited = set(await db.scalars(select(discord_id).where(
            AuditLog.entity_type == "ga_assistant", AuditLog.entity_id.in_(entity_ids),
            AuditLog.action == "GA_ASSISTANT_DISCORD_REPLY",
        )))
    replied = {anchor_id for anchor_id, reply_id, author_id in responses
               if author_id == ga_id or f"dc:{reply_id}" in audited}

    cursors = [(row.id, row.reaction_session_id) for row in snapshots
               if isinstance(row, GaDiscordChannelMessage) and row.reaction_session_id]
    events = defaultdict(list)
    if cursors:
        event = GaDiscordReactionEvent
        for evidence in await db.scalars(select(event).where(tuple_(event.message_id, event.session_id).in_(cursors))):
            events[evidence.message_id].append(evidence)

    for row, item in zip(snapshots, items, strict=True):
        item["reactions"], item["reviewed_by"] = reactions_out(row, people, ga_id, approvals)
        item["ready_for_ga"] = bool(item["reviewed_by"])
        item["reactions_synced_at"] = row.reactions_synced_at.isoformat() if row.reactions_synced_at else None
        reacted, names, known = feed_reaction_activity(row, events[row.id], ga_id, people)
        item.update(ga_replied=row.id in replied, ga_reacted=reacted, others_reacted_before_ga=bool(names),
                    others_reacted_before_ga_names=names, others_reacted_before_ga_known=known)
    return items


async def author_names(db: AsyncSession, rows: list[GaDiscordMention]) -> dict[uuid.UUID, str]:
    ids = {row.author_user_id for row in rows if row.author_user_id}
    if not ids:
        return {}
    result = await db.execute(select(User.id, User.full_name, User.username).where(User.id.in_(ids)))
    return {user_id: (full_name or username or "") for user_id, full_name, username in result.all()}


def mention_out(
    row: GaDiscordMention,
    names: dict[uuid.UUID, str],
    tz: ZoneInfo,
    *,
    people: dict[str, str] | None = None,
    ga_id: str | None = None,
    approvals: set[str] | None = None,
) -> dict[str, Any]:
    name = names.get(row.author_user_id) if row.author_user_id else None
    reactions, reviewed_by = reactions_out(row, people or {}, ga_id, approval_emojis() if approvals is None else approvals)
    return {
        **message_out(row, name or row.author_name, tz),
        "author_in_primeflow": bool(name),
        "reasons": row.reasons or [],
        "status": row.status,
        "reactions": reactions,
        "reviewed_by": reviewed_by,
        "ready_for_ga": bool(reviewed_by),
    }


def message_out(row: GaDiscordMention | GaDiscordChannelMessage, name: str, tz: ZoneInfo) -> dict[str, Any]:
    synced_at = getattr(row, "reactions_synced_at", None)
    return {
        "id": f"dc:{row.id}",
        "author": name,
        "author_initials": initials(name),
        "channel": f"#{row.channel_name}" if row.channel_name else row.channel_id,
        "time": row.created_at.astimezone(tz).isoformat(),
        "edited_at": row.edited_at.astimezone(tz).isoformat() if row.edited_at else None,
        "text": row.content,
        "url": row.jump_url,
        "attachments": row.attachments or [],
        "reactions_synced_at": synced_at.isoformat() if synced_at else None,
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


def _staff_channel_mentions() -> Select[tuple[GaDiscordMention]]:
    return select(GaDiscordMention).where(archive.staff_mention_scope())


async def list_staff_channel_mentions(
    db: AsyncSession, *, before: str | None, limit: int
) -> list[GaDiscordMention]:
    if not settings.DISCORD_GUILD_ID or not settings.DISCORD_GA_REPLIES_CHANNEL_ID:
        return []

    mention = GaDiscordMention
    statement = _staff_channel_mentions()
    if before is not None:
        cursor_time = await db.scalar(statement.with_only_columns(mention.created_at).where(mention.id == before))
        if cursor_time is None:
            raise ValueError("before must be a message ID from the GA staff channel feed")
        statement = statement.where(tuple_(mention.created_at, mention.id) < tuple_(cursor_time, before))

    statement = statement.order_by(mention.created_at.desc(), mention.id.desc()).limit(limit)
    return list((await db.scalars(statement)).all())


async def staff_mention_attachment_links(db: AsyncSession, message_id: str) -> list[DiscordAttachmentLink]:
    """Fetch signed URLs for an eligible mention or one of its context messages."""
    mention = await db.scalar(_staff_channel_mentions().where(GaDiscordMention.id == message_id))
    row = mention if mention is not None else await archive.get_context_message(db, message_id)
    ga_id = await ga_discord_id(db) if row else None
    if row is None or not ga_id:
        raise HTTPException(404, "Përmendja nuk gjendet në listën e GA-së.")
    if not settings.GA_DISCORD_MENTIONS_BOT_TOKEN:
        raise HTTPException(424, "Boti i përmendjeve nuk është i konfiguruar. Hape mesazhin në Discord.")

    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            response = await client.get(
                f"https://discord.com/api/v10/channels/{row.channel_id}/messages/{row.id}",
                headers={"Authorization": f"Bot {settings.GA_DISCORD_MENTIONS_BOT_TOKEN}"},
            )
            if response.status_code in {403, 404}:
                raise HTTPException(404, "Mesazhi nuk është më i disponueshëm në Discord.")
            response.raise_for_status()
            message = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "Skedarët nuk u lexuan nga Discord. Hape mesazhin në Discord.") from None

    if (message.get("id") != row.id or message.get("channel_id") != row.channel_id
            or message.get("author", {}).get("id") != row.author_discord_id
            or (mention is not None and not any(user.get("id") == ga_id for user in message.get("mentions", [])))):
        raise HTTPException(404, "Mesazhi nuk përputhet më me përmendjen e GA-së.")

    links = []
    for attachment in message.get("attachments", []):
        url = attachment.get("url", "")
        asset = urlsplit(url)
        if (asset.scheme == "https" and asset.netloc in {"cdn.discordapp.com", "media.discordapp.net"}
                and asset.path.startswith(f"/attachments/{row.channel_id}/{attachment['id']}/")):
            links.append(DiscordAttachmentLink(
                name=attachment["filename"], url=url, content_type=attachment.get("content_type"),
            ))
    return links
