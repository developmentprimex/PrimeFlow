"""Discord writes requested by the GA through the assistant."""
import re
from datetime import datetime
from urllib.parse import quote
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.ga_discord_channel_message import GaDiscordChannelMessage
from app.models.ga_discord_mention import GaDiscordMention
from app.schemas.ga_discord_mentions import (
    DISCORD_MESSAGE_ID_PATTERN,
    DiscordReactIn,
    DiscordReactResult,
    DiscordReplyIn,
    DiscordReplyResult,
)
from app.services import ga_discord_channel_archive as archive, ga_discord_mentions as mentions

DISCORD_API = "https://discord.com/api/v10"


def discord_client() -> httpx.AsyncClient:
    token = settings.GA_DISCORD_MENTIONS_BOT_TOKEN
    if not token:
        raise HTTPException(424, "Boti i përmendjeve nuk është i konfiguruar.")
    return httpx.AsyncClient(timeout=8, headers={"Authorization": f"Bot {token}"})


async def request_discord(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> httpx.Response:
    try:
        response = await client.request(method, DISCORD_API + path, **kwargs)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(404, "Mesazhi nuk është më i disponueshëm në Discord.") from None
        if exc.response.status_code == 403:
            raise HTTPException(424, "Boti nuk ka lejen e nevojshme në këtë kanal ose thread.") from None
        if exc.response.status_code == 429:
            raise HTTPException(429, "Discord ka kufizuar përkohësisht kërkesat.") from None
        raise HTTPException(502, "Discord nuk e konfirmoi veprimin.") from None
    except httpx.RequestError:
        raise HTTPException(502, "Discord nuk e konfirmoi veprimin.") from None
    return response


async def target_message(
    db: AsyncSession, message_id: str,
) -> GaDiscordMention | GaDiscordChannelMessage:
    mention = await db.scalar(select(GaDiscordMention).where(
        archive.staff_mention_scope(), GaDiscordMention.id == message_id,
    ))
    target = mention if mention is not None else await archive.get_context_message(db, message_id)
    if target is None:
        raise HTTPException(404, "Mesazhi nuk gjendet në listën e GA-së ose në kontekstin e saj.")
    return target


def message_path(target: GaDiscordMention | GaDiscordChannelMessage) -> str:
    return f"/channels/{target.channel_id}/messages/{target.id}"


async def verify_target(db: AsyncSession, client: httpx.AsyncClient,
                        target: GaDiscordMention | GaDiscordChannelMessage) -> None:
    source = (await request_discord(client, "GET", message_path(target))).json()
    if (source.get("id") != target.id or source.get("channel_id") != target.channel_id
            or source.get("author", {}).get("id") != target.author_discord_id):
        raise HTTPException(404, "Mesazhi nuk përputhet me burimin në Discord.")
    if isinstance(target, GaDiscordMention):
        ga_id = await mentions.ga_discord_id(db)
        if not ga_id or not any(user.get("id") == ga_id for user in source.get("mentions", [])):
            raise HTTPException(404, "Mesazhi nuk përmban më përmendjen e GA-së.")


async def create_reply(
    db: AsyncSession, target: GaDiscordMention | GaDiscordChannelMessage, payload: DiscordReplyIn,
) -> tuple[DiscordReplyResult, dict]:
    anchor_ids = await archive.context_mention_ids(db, target.id)
    async with discord_client() as client:
        await verify_target(db, client, target)
        response = await request_discord(client, "POST", f"/channels/{target.channel_id}/messages", json={
            "content": f"GA: {payload.text}",
            "message_reference": {"message_id": target.id, "fail_if_not_exists": True},
            "allowed_mentions": {"parse": [], "replied_user": False},
            "nonce": payload.nonce or uuid4().hex[:24],
            "enforce_nonce": True,
        })

    reply = response.json()
    reply_id = reply.get("id", "")
    if (not re.fullmatch(DISCORD_MESSAGE_ID_PATTERN, reply_id) or reply.get("channel_id") != target.channel_id
            or (reply.get("message_reference") or {}).get("message_id") != target.id):
        raise HTTPException(502, "Discord nuk ktheu një përgjigje që përputhet me mesazhin.")
    url = f"https://discord.com/channels/{target.guild_id}/{target.channel_id}/{reply_id}"
    author = reply["author"]
    values = {
        "id": reply_id,
        "guild_id": target.guild_id,
        "channel_id": target.channel_id,
        "parent_channel_id": getattr(target, "parent_channel_id", None),
        "channel_name": target.channel_name,
        "author_discord_id": author["id"],
        "author_name": (author.get("global_name") or author["username"])[:200],
        "created_at": datetime.fromisoformat(reply["timestamp"]),
        "edited_at": None,
        "content": reply["content"],
        "jump_url": url,
        "attachments": [],
        "reactions": None,
        "reactions_synced_at": None,
        "reply_to_message_id": target.id,
        "reply_context_ids": anchor_ids,
    }
    return DiscordReplyResult(id=f"dc:{reply_id}", url=url), values


async def react(
    db: AsyncSession, target: GaDiscordMention | GaDiscordChannelMessage, payload: DiscordReactIn,
) -> DiscordReactResult:
    async with discord_client() as client:
        await verify_target(db, client, target)
        path = f"{message_path(target)}/reactions/{quote(payload.emoji, safe='')}/@me"
        await request_discord(client, "DELETE" if payload.remove else "PUT", path)
    return DiscordReactResult(id=f"dc:{target.id}", emoji=payload.emoji, removed=payload.remove)
