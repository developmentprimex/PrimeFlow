"""Read only the configured channel; do not send, react, or alter its permissions."""
from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import uuid4

import discord
import httpx

from app.config import settings


def message_evidence(message, ga_id, thread_root_id=None):
    if message.author.bot or message.type not in {discord.MessageType.default, discord.MessageType.reply}:
        return None
    reference = getattr(message, "reference", None)
    return {
        "id": str(message.id), "author_id": str(message.author.id),
        "author": message.author.display_name[:100], "content": message.content[:4000],
        "created_at": message.created_at.isoformat(),
        "mentions_ga": any(str(user.id) == ga_id for user in message.mentions),
        "reference_id": str(reference.message_id) if reference and reference.message_id else None,
        "thread_root_id": str(thread_root_id) if thread_root_id else None,
        "attachments": len(message.attachments),
    }


async def collect(bot, context):
    if context["guild_id"] != settings.DISCORD_GUILD_ID or context["channel_id"] != settings.DISCORD_GA_REPLIES_CHANNEL_ID:
        raise ValueError("Unexpected GA evidence channel")
    guild = bot.get_guild(int(context["guild_id"]))
    if guild is None:
        raise ValueError("GA evidence guild unavailable")
    channel = guild.get_channel(int(context["channel_id"])) or await guild.fetch_channel(int(context["channel_id"]))
    if not isinstance(channel, discord.TextChannel) or str(channel.guild.id) != context["guild_id"]:
        raise ValueError("GA evidence channel is not a text channel in this guild")
    permissions = channel.permissions_for(guild.me)
    if not permissions.view_channel or not permissions.read_message_history or not settings.DISCORD_MESSAGE_CONTENT_ENABLED:
        raise ValueError("GA evidence requires channel history and Message Content")
    after, before = (datetime.fromisoformat(context[key]) for key in ("window_start", "captured_at"))
    messages, partial = [], False

    async def read(source, limit, root=None):
        count = 0
        async for message in source.history(limit=limit + 1, after=after, before=before, oldest_first=False):
            count += 1
            if count > limit:
                return True
            value = message_evidence(message, context["ga_user_id"], root)
            if value:
                messages.append(value)
        return False

    partial = await read(channel, 2000)
    # Read public active and archived threads belonging to this channel only.
    # Private threads are deliberately excluded; they are not shared channel evidence.
    threads = {t.id: t for t in await guild.active_threads()
               if t.parent_id == channel.id and not t.is_private()}
    archived_count = 0
    async for thread in channel.archived_threads(limit=26):
        archived_count += 1
        if archived_count > 25:
            partial = True
            break
        threads[thread.id] = thread
    for thread in list(threads.values())[:25]:
        if len(messages) >= 4500:
            partial = True
            break
        partial = await read(thread, min(500, 4500 - len(messages)), thread.id) or partial
    partial = partial or len(threads) > 25
    return {**context, "status": "PARTIAL" if partial else "OK", "messages": messages}


async def sync(bot):
    context = await bot.bridge("/bot/ga-replies/context", {})
    try:
        evidence = await asyncio.wait_for(collect(bot, context), timeout=90)
    except (discord.DiscordException, ValueError, asyncio.TimeoutError):
        # Never turn missing permissions, empty content, or a failed read into "0 pending".
        evidence = {**context, "status": "UNAVAILABLE", "messages": []}
    await bot.bridge("/bot/ga-replies/snapshot", evidence)


async def capture_reaction(bot, event, observed_at):
    """Read a public staff-channel message only after verifying the reactor is GA."""
    guild_id = settings.DISCORD_GUILD_ID
    channel_id = settings.DISCORD_GA_REPLIES_CHANNEL_ID
    if not channel_id or event.guild_id is None or str(event.guild_id) != guild_id:
        return
    guild = bot.get_guild(event.guild_id)
    if guild is None:
        return
    channel = guild.get_channel_or_thread(event.channel_id)
    if channel is not None and not _in_staff_channel(channel, channel_id):
        return
    context = await bot.bridge("/bot/ga-replies/context", {})
    if str(event.user_id) != context["ga_user_id"]:
        return
    # Uncached public threads may arrive as raw Gateway events.
    channel = channel or await guild.fetch_channel(event.channel_id)
    if not _in_staff_channel(channel, channel_id):
        return
    message = await channel.fetch_message(event.message_id)
    if message.author.id == event.user_id:
        return
    evidence = message_evidence(message, context["ga_user_id"])
    if evidence is None:
        return

    payload = {
        "event_id": str(uuid4()),
        "guild_id": guild_id,
        "channel_id": channel_id,
        "ga_user_id": context["ga_user_id"],
        "message_id": evidence["id"],
        "message_author_id": evidence["author_id"],
        "message_content": evidence["content"],
        "has_attachments": bool(evidence["attachments"]),
        "emoji": event.emoji.name if event.emoji.id is None else f":{event.emoji.name}:",
        "observed_at": observed_at.isoformat(),
    }
    try:
        await bot.bridge("/bot/ga-reactions", payload)
    except httpx.TransportError:
        await asyncio.sleep(1)
        await bot.bridge("/bot/ga-reactions", payload)


def _in_staff_channel(channel, channel_id):
    if isinstance(channel, discord.TextChannel):
        return str(channel.id) == channel_id
    return isinstance(channel, discord.Thread) and str(channel.parent_id) == channel_id and not channel.is_private()
