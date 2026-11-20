"""Read-only Discord bot: stores server messages that mention the GA, for the GA assistant.

What it stores (PrimEx server channels and public threads only, never DMs):
* messages that @mention the GA,
* messages that @mention a role the GA has,
* replies to one of the GA's messages.

It never sends, edits, reacts to or deletes anything: it only connects with the
Guilds, Guild Messages and Message Content intents, and needs only the View Channels
and Read Message History permissions. The token is read from backend/.env
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
        "reply_to_message_id": str(reference.message_id) if reference and reference.message_id else None,
    }


class GaMentionsBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
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

    async def close(self) -> None:
        await self.api.aclose()
        await super().close()

    async def refresh_context(self, *, force: bool = False) -> bool:
        if not force and time.monotonic() - self.context_at < CONTEXT_TTL_SECONDS and self.ga_id:
            return True
        try:
            response = await self.api.get("/context")
            response.raise_for_status()
            self.context = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("PrimeFlow context unavailable: %s", type(exc).__name__)
            return bool(self.ga_id)
        ga_raw = self.context.get("ga_discord_id")
        guild = self.get_guild(int(self.context.get("guild_id") or 0))
        if not ga_raw or guild is None:
            log.error("GA Discord id or PrimEx server unavailable (is the bot invited, is GA's Discord linked?)")
            self.ga_id = None
            return False
        self.ga_id = int(ga_raw)
        try:
            member = await guild.fetch_member(self.ga_id)  # REST call; needs no privileged intent
            self.ga_roles = {role.id for role in member.roles if not role.is_default()}
        except discord.DiscordException as exc:
            log.warning("GA roles unavailable: %s", type(exc).__name__)
        self.context_at = time.monotonic()
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
        for start in range(0, len(payloads), POST_BATCH):
            batch = payloads[start:start + POST_BATCH]
            for attempt in range(3):
                try:
                    response = await self.api.post("/mentions", json={"messages": batch})
                    response.raise_for_status()
                    break
                except httpx.HTTPError as exc:
                    log.warning("Storing %s mention(s) failed (%s), attempt %s", len(batch), type(exc).__name__, attempt + 1)
                    await asyncio.sleep(2 * (attempt + 1))

    async def handle(self, message) -> None:
        if not await self.refresh_context():
            return
        reasons = self.concerns_ga(message)
        if reasons:
            await self.send([message_payload(message, reasons)])

    async def on_ready(self) -> None:
        log.info("GA mentions bot connected as %s", self.user)
        if await self.refresh_context(force=True):
            asyncio.create_task(self.backfill())

    async def on_message(self, message) -> None:
        await self.handle(message)

    async def on_message_edit(self, _before, after) -> None:
        await self.handle(after)

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
                            found.append(message_payload(message, reasons))
                except discord.DiscordException as exc:
                    log.info("Skipped #%s during backfill: %s", getattr(channel, "name", "?"), type(exc).__name__)
            await self.send(found)
            log.info("Backfill checked %s channel(s) since %s; %s mention(s) sent", len(channels), after.isoformat(), len(found))


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
