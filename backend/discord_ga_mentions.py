"""Read-only Discord bot for GA mentions and the staff channel archive.

What it stores (PrimEx server channels and public threads only, never DMs):
* messages that @mention the GA,
* messages that @mention a role the GA has,
* replies to one of the GA's messages.
* every message in the configured staff channel and its public threads.

It also follows the reactions on stored mentions (who already reviewed a message):
live through reaction add/remove events, and once over REST for older mentions.

The gateway worker only reads Discord and connects with the
Guilds, Guild Messages, Guild Message Reactions and Message Content intents, and needs
only the View Channels and Read Message History permissions. The token is read from backend/.env
(GA_DISCORD_MENTIONS_BOT_TOKEN); without it the process exits at once.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import discord
import httpx

from app.config import settings
from app.services.ga_discord_mentions import bridge_secret

log = logging.getLogger("primeflow.ga_discord_mentions")
CONTEXT_TTL_SECONDS = 600
HISTORY_LIMIT_PER_CHANNEL = 1000
POST_BATCH = 100
REACTION_DEBOUNCE_SECONDS = 2.0
REACTION_USERS_LIMIT = 100


def channel_label(channel) -> str:
    parent = getattr(channel, "parent", None)
    name = getattr(channel, "name", "") or ""
    return f"{parent.name} › {name}" if isinstance(channel, discord.Thread) and parent is not None else name


def readable(channel, me) -> bool:
    try:
        permissions = channel.permissions_for(me)
    except (AttributeError, discord.ClientException):
        return False
    return bool(permissions.view_channel and permissions.read_message_history)


def mention_reasons(message, ga_id: int, ga_roles: set[int]) -> list[str]:
    """Why a message concerns the GA (empty list = it does not)."""
    reasons = []
    if ga_id in message.raw_mentions:
        reasons.append("mention")
    if ga_roles.intersection(message.raw_role_mentions):
        reasons.append("role")
    reference = getattr(message, "reference", None)
    resolved = getattr(reference, "resolved", None) if reference else None
    if isinstance(resolved, discord.Message) and resolved.author.id == ga_id:
        reasons.append("reply")
    return reasons


def message_payload(message, reasons: list[str]) -> dict:
    reference = getattr(message, "reference", None)
    return {
        "id": str(message.id),
        "guild_id": str(message.guild.id),
        "channel_id": str(message.channel.id),
        "channel_name": channel_label(message.channel)[:200],
        "author_discord_id": str(message.author.id),
        "author_name": (getattr(message.author, "display_name", None) or message.author.name or "")[:200],
        "created_at": message.created_at.isoformat(),
        "edited_at": message.edited_at.isoformat() if message.edited_at else None,
        "content": (message.content or "")[:8000],
        "jump_url": message.jump_url,
        "attachments": [{"name": a.filename[:300], "url": a.url[:1000]} for a in message.attachments[:20]],
        "reasons": reasons,
        "reply_to_message_id": str(reference.message_id)
        if message.type == discord.MessageType.reply and reference and reference.message_id else None,
    }


def archive_payload(message) -> dict:
    payload = message_payload(message, [])
    del payload["reasons"]
    thread = message.channel if isinstance(message.channel, discord.Thread) else None
    payload["parent_channel_id"] = str(thread.parent_id) if thread else None
    return payload


def emoji_label(emoji) -> str:
    """Unicode emoji as-is, custom server emoji as :name:."""
    if isinstance(emoji, str):
        return emoji
    if getattr(emoji, "id", None):
        return f":{emoji.name}:"
    return str(emoji)


async def read_reactions(message, ga_bot_id: int | None = None) -> list[dict]:
    """[{emoji, count, users:[{discord_id, name}]}] of a message (REST, read-only)."""
    out = []
    for reaction in getattr(message, "reactions", None) or []:
        users = []
        try:
            async for user in reaction.users(limit=REACTION_USERS_LIMIT):
                name = getattr(user, "display_name", None) or getattr(user, "global_name", None) or user.name or ""
                value = {"discord_id": str(user.id), "name": name[:200]}
                if user.id == ga_bot_id:
                    value["ga_bot"] = True
                users.append(value)
        except discord.DiscordException as exc:
            log.info("Reaction users unavailable: %s", type(exc).__name__)
        out.append({"emoji": emoji_label(reaction.emoji)[:100], "count": int(reaction.count), "users": users})
    return out[:50]


async def archive_snapshot(message, ga_bot_id: int | None = None) -> dict:
    return {
        **archive_payload(message),
        "reactions_synced_at": datetime.now(timezone.utc).isoformat(),
        "reactions": await read_reactions(message, ga_bot_id),
    }


class GaMentionsBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.guild_reactions = True  # reaction add/remove in server channels only (no DM reactions)
        intents.message_content = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        base = os.getenv("PRIMEFLOW_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        self.api = httpx.AsyncClient(
            base_url=f"{base}/api/ga-discord-bot", timeout=30, headers={"X-GA-Mentions-Secret": bridge_secret()}
        )
        self.ga_id: int | None = None
        self.ga_roles: set[int] = set()
        self.context_at = 0.0
        self.context: dict = {}
        self.backfill_lock = asyncio.Lock()
        self.archive_lock = asyncio.Lock()
        self.archive_channels: set[int] = set()
        self.tracked: set[int] = set()
        self.pending_reactions: dict[int, asyncio.Task] = {}

    async def close(self) -> None:
        await self.api.aclose()
        await super().close()

    async def refresh_context(self, *, force: bool = False) -> bool:
        if not force and self.context.get("guild_id") and time.monotonic() - self.context_at < CONTEXT_TTL_SECONDS:
            return True
        try:
            response = await self.api.get("/context")
            response.raise_for_status()
            self.context = response.json()
            self.tracked.update(int(item) for item in self.context.get("tracked_message_ids") or [])
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("PrimeFlow context unavailable: %s", type(exc).__name__)
            return bool(self.context.get("guild_id"))
        ga_raw = self.context.get("ga_discord_id")
        guild = self.get_guild(int(self.context.get("guild_id") or 0))
        if guild is None:
            log.error("PrimEx server unavailable (is the bot invited?)")
            self.ga_id = None
            return False
        self.context_at = time.monotonic()
        if not ga_raw:
            log.warning("GA Discord id unavailable; the staff channel archive can still run")
            self.ga_id = None
            self.ga_roles = set()
            return True
        if self.ga_id != int(ga_raw):
            self.ga_roles = set()
        self.ga_id = int(ga_raw)
        try:
            member = await guild.fetch_member(self.ga_id)  # REST call; needs no privileged intent
            self.ga_roles = {role.id for role in member.roles if not role.is_default()}
        except discord.DiscordException as exc:
            log.warning("GA roles unavailable: %s", type(exc).__name__)
        return True

    def concerns_ga(self, message) -> list[str]:
        if message.guild is None or str(message.guild.id) != str(self.context.get("guild_id")):
            return []  # DMs and other servers are never read
        if message.author.bot or self.ga_id is None or message.author.id == self.ga_id:
            return []
        if message.type not in {discord.MessageType.default, discord.MessageType.reply}:
            return []
        return mention_reasons(message, self.ga_id, self.ga_roles)

    async def send(self, payloads: list[dict]) -> None:
        self.tracked.update(int(payload["id"]) for payload in payloads)
        for start in range(0, len(payloads), POST_BATCH):
            await self.post_batch("/mentions", {"messages": payloads[start:start + POST_BATCH]})

    async def post_batch(self, endpoint: str, data: dict) -> bool:
        for attempt in range(3):
            try:
                response = await self.api.post(endpoint, json=data)
                response.raise_for_status()
                return True
            except httpx.HTTPError as exc:
                log.warning("Storing Discord batch at %s failed (%s), attempt %s", endpoint, type(exc).__name__, attempt + 1)
                if attempt < 2:
                    await asyncio.sleep(2 * (attempt + 1))
        return False

    def is_staff_channel(self, channel) -> bool:
        staff_channel = self.context.get("staff_channel_id")
        if channel is None or not staff_channel:
            return False
        if isinstance(channel, discord.Thread):
            return not channel.is_private() and str(channel.parent_id) == staff_channel
        return str(channel.id) == staff_channel

    async def handle(self, message) -> None:
        if not await self.refresh_context():
            return
        if (message.guild and str(message.guild.id) == self.context.get("guild_id")
                and self.is_staff_channel(message.channel) and message.type != discord.MessageType.thread_starter_message):
            self.archive_channels.add(message.channel.id)
            await self.post_batch("/channel-messages", {"messages": [archive_payload(message)]})
        reasons = self.concerns_ga(message)
        if reasons:
            await self.send([message_payload(message, reasons)])

    async def on_ready(self) -> None:
        log.info("GA mentions bot connected as %s", self.user)
        if await self.refresh_context(force=True):
            asyncio.create_task(self.backfill())
            asyncio.create_task(self.backfill_archive())

    async def on_resumed(self) -> None:
        if await self.refresh_context(force=True):
            asyncio.create_task(self.backfill_archive())

    async def on_raw_reaction_add(self, payload) -> None:
        self.reaction_changed(payload)

    async def on_raw_reaction_remove(self, payload) -> None:
        self.reaction_changed(payload)

    async def on_raw_reaction_clear(self, payload) -> None:
        self.reaction_changed(payload)

    async def on_raw_reaction_clear_emoji(self, payload) -> None:
        self.reaction_changed(payload)

    def reaction_changed(self, payload) -> None:
        """Re-read the reactions of a stored mention (debounced: one REST read per burst)."""
        guild_id = getattr(payload, "guild_id", None)
        if guild_id is None or str(guild_id) != str(self.context.get("guild_id")):
            return  # DMs and other servers are never read
        if (payload.message_id not in self.tracked and payload.channel_id not in self.archive_channels
                and str(payload.channel_id) != self.context.get("staff_channel_id")
                and not self.is_staff_channel(self.get_channel(payload.channel_id))):
            return
        pending = self.pending_reactions.pop(payload.message_id, None)
        if pending is not None:
            pending.cancel()
        self.pending_reactions[payload.message_id] = asyncio.create_task(
            self.sync_reactions(payload.channel_id, payload.message_id, delay=REACTION_DEBOUNCE_SECONDS)
        )

    async def sync_reactions(self, channel_id: int, message_id: int, *, delay: float = 0.0) -> None:
        try:
            if delay:
                await asyncio.sleep(delay)
            channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
            if getattr(channel, "guild", None) is None:
                return
            message = await channel.fetch_message(message_id)  # GET /channels/{id}/messages/{id}
            archived = self.is_staff_channel(channel) and message.type != discord.MessageType.thread_starter_message
            if archived:
                snapshot = await archive_snapshot(message, self.user.id if self.user else None)
                await self.post_batch("/channel-messages", {"messages": [snapshot]})
                reactions = snapshot["reactions"]
                observed_at = snapshot["reactions_synced_at"]
            else:
                observed_at = datetime.now(timezone.utc).isoformat()
                reactions = await read_reactions(message, self.user.id if self.user else None)
            if archived or message_id in self.tracked:
                response = await self.api.post("/reactions", json={
                    "message_id": str(message_id), "reactions": reactions, "observed_at": observed_at,
                })
                response.raise_for_status()
        except asyncio.CancelledError:
            raise
        except discord.NotFound:
            log.info("Message %s is gone; reactions not updated", message_id)
        except (discord.DiscordException, httpx.HTTPError) as exc:
            log.warning("Reactions of %s not updated: %s", message_id, type(exc).__name__)
        finally:
            task = self.pending_reactions.get(message_id)
            if task is asyncio.current_task():
                self.pending_reactions.pop(message_id, None)

    async def sync_old_reactions(self) -> None:
        """Read reactions once for stored mentions that never had them read."""
        items = self.context.get("reactions_unsynced") or []
        for item in items:
            await self.sync_reactions(int(item["channel_id"]), int(item["id"]))
        if items:
            log.info("Reactions read for %s older mention(s)", len(items))

    async def on_message(self, message) -> None:
        await self.handle(message)

    async def on_message_edit(self, _before, after) -> None:
        await self.handle(after)

    async def on_raw_message_edit(self, payload) -> None:
        if payload.cached_message is not None or str(payload.guild_id) != self.context.get("guild_id"):
            return
        channel = self.get_channel(payload.channel_id)
        if (not self.is_staff_channel(channel) and payload.channel_id not in self.archive_channels
                and str(payload.channel_id) != self.context.get("staff_channel_id")):
            return
        try:
            channel = channel or await self.fetch_channel(payload.channel_id)
            await self.handle(await channel.fetch_message(payload.message_id))
        except discord.DiscordException as exc:
            log.info("Discord edit unavailable in the staff channel: %s", type(exc).__name__)

    async def backfill_archive(self) -> None:
        async with self.archive_lock:
            guild = self.get_guild(int(self.context.get("guild_id") or 0))
            if guild is None:
                return
            staff = guild.get_channel(int(self.context.get("staff_channel_id") or 0))
            if not isinstance(staff, discord.TextChannel) or not readable(staff, guild.me):
                return

            checkpoints = self.context.setdefault("archive_checkpoints", {})
            await self.archive_history(staff, checkpoints)
            scanned = set()
            try:
                for thread in await guild.active_threads():
                    if self.is_staff_channel(thread) and readable(thread, guild.me):
                        await self.archive_history(thread, checkpoints)
                        scanned.add(thread.id)
            except discord.DiscordException as exc:
                log.warning("Active staff threads unavailable: %s", type(exc).__name__)
            try:
                async for thread in staff.archived_threads(limit=None):
                    if thread.id not in scanned and readable(thread, guild.me):
                        await self.archive_history(thread, checkpoints)
            except discord.DiscordException as exc:
                log.warning("Archived staff threads unavailable: %s", type(exc).__name__)

    async def archive_history(self, channel, checkpoints: dict[str, str]) -> None:
        self.archive_channels.add(channel.id)
        channel_id = str(channel.id)
        cursor = checkpoints.get(channel_id)
        after = discord.Object(id=int(cursor)) if cursor else None
        batch = []
        try:
            async for message in channel.history(limit=None, after=after, oldest_first=True):
                if message.type == discord.MessageType.thread_starter_message:
                    continue
                batch.append(await archive_snapshot(message, self.user.id if self.user else None))
                if len(batch) == POST_BATCH:
                    if not await self.post_batch("/channel-messages", {"messages": batch, "checkpoint_channel_id": channel_id}):
                        return
                    checkpoints[channel_id] = batch[-1]["id"]
                    batch = []
        except discord.DiscordException as exc:
            log.warning("Staff archive history interrupted in channel %s: %s", channel_id, type(exc).__name__)
        if batch and await self.post_batch("/channel-messages", {"messages": batch, "checkpoint_channel_id": channel_id}):
            checkpoints[channel_id] = batch[-1]["id"]

    async def backfill(self) -> None:
        """After a (re)connect, read what was written while the bot was offline."""
        async with self.backfill_lock:
            guild = self.get_guild(int(self.context.get("guild_id") or 0))
            if guild is None:
                return
            now = datetime.now(timezone.utc)
            after = now - timedelta(hours=int(self.context.get("backfill_hours") or 72))
            if self.context.get("last_message_at"):
                after = max(after, datetime.fromisoformat(self.context["last_message_at"]) - timedelta(minutes=5))
            channels = [c for c in guild.text_channels if readable(c, guild.me)]
            try:
                channels += [t for t in await guild.active_threads() if not t.is_private() and readable(t, guild.me)]
            except discord.DiscordException:
                pass
            found = []
            for channel in channels:
                try:
                    async for message in channel.history(limit=HISTORY_LIMIT_PER_CHANNEL, after=after, oldest_first=True):
                        reasons = self.concerns_ga(message)
                        if reasons:
                            payload = message_payload(message, reasons)
                            payload["reactions"] = await read_reactions(message, self.user.id if self.user else None)
                            found.append(payload)
                except discord.DiscordException as exc:
                    log.info("Skipped #%s during backfill: %s", getattr(channel, "name", "?"), type(exc).__name__)
            await self.send(found)
            log.info("Backfill checked %s channel(s) since %s; %s mention(s) sent", len(channels), after.isoformat(), len(found))
            await self.sync_old_reactions()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    token = settings.GA_DISCORD_MENTIONS_BOT_TOKEN
    if not token:
        print("GA_DISCORD_MENTIONS_BOT_TOKEN is not set; the GA mentions bot stays off.")
        return
    if not settings.DISCORD_GUILD_ID:
        print("DISCORD_GUILD_ID is not set; the GA mentions bot stays off.")
        return
    GaMentionsBot().run(token, log_handler=None)


if __name__ == "__main__":
    main()
