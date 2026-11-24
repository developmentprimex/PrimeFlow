"""Verify the deployed staff-channel context against Discord without logging message data."""
import asyncio
import json
from datetime import datetime, timedelta

import httpx
from fastapi import HTTPException
from sqlalchemy import select, text

from app.config import settings
from app.db import SessionLocal, engine
from app.models.ga_discord_channel_message import GaDiscordArchiveCheckpoint
from app.schemas.ga_discord_mentions import DiscordFeedMention
from app.services.ga_assistant import ga_tz
from app.services.ga_discord_mentions import (
    list_staff_channel_mentions,
    render_with_context,
    staff_mention_attachment_links,
)

CHECKED_FIELDS = ("para", "pas", "reply", "direct_reply", "thread", "context_attachment", "mention_attachment")
DISCORD_API = "https://discord.com/api/v10"


def channel_id(item):
    return item["url"].rsplit("/", 2)[-2]


def message_id(item):
    return item["id"].removeprefix("dc:")


async def fetch_discord(client, path):
    response = await client.get(
        DISCORD_API + path, headers={"Authorization": f"Bot {settings.GA_DISCORD_MENTIONS_BOT_TOKEN}"},
    )
    if response.status_code == 429:
        await asyncio.sleep(min(5, float(response.json().get("retry_after", 1))))
        response = await client.get(
            DISCORD_API + path, headers={"Authorization": f"Bot {settings.GA_DISCORD_MENTIONS_BOT_TOKEN}"},
        )
    return response.json() if response.is_success else None


async def verify_attachment(db, client, item):
    if not item["attachments"]:
        return False
    try:
        links = await staff_mention_attachment_links(db, message_id(item))
    except HTTPException:
        # The file may have been removed since collection. Continue to another message.
        return False
    for link in links:
        try:
            response = await client.head(link.url)
        except httpx.HTTPError:
            continue
        if response.is_success:
            return True
    return False


async def verify_context(db, client, items):
    verified = dict.fromkeys(CHECKED_FIELDS, False)
    candidates = dict.fromkeys(CHECKED_FIELDS, 0)
    attachment_attempts = {"context_attachment": set(), "mention_attachment": set()}
    cache = {}

    async def source(item):
        key = (channel_id(item), message_id(item))
        if key not in cache:
            cache[key] = await fetch_discord(client, f"/channels/{key[0]}/messages/{key[1]}")
        return cache[key]

    for item in items:
        context = item["context"]
        for field in ("para", "pas", "reply"):
            values = [context[field]] if field == "reply" and context[field] else (context[field] or [])
            candidates[field] += len(values)
            if verified[field] or not values:
                continue
            anchor = await source(item)
            if not anchor:
                continue
            for value in values[:4]:
                related = await source(value)
                if not related or related["channel_id"] != anchor["channel_id"]:
                    continue
                if field == "reply":
                    verified[field] = (anchor.get("message_reference") or {}).get("message_id") == related["id"]
                else:
                    seconds = (datetime.fromisoformat(related["timestamp"]) -
                               datetime.fromisoformat(anchor["timestamp"])).total_seconds()
                    if field == "para":
                        seconds = -seconds
                    verified[field] = 0 <= seconds <= 120 and related["author"]["id"] == anchor["author"]["id"]
                if verified[field]:
                    break

        attachment_context = [*context["para"], *context["pas"], *context["përgjigjet"]]
        if context["reply"]:
            attachment_context.append(context["reply"])
        for value in context["përgjigjet"]:
            in_thread = channel_id(value) == message_id(item)
            field = "thread" if in_thread else "direct_reply"
            candidates[field] += 1
            if verified[field]:
                continue
            related = await source(value)
            if not related:
                continue
            if in_thread:
                thread = await fetch_discord(client, f"/channels/{channel_id(value)}")
                verified[field] = bool(thread and thread.get("parent_id") == settings.DISCORD_GA_REPLIES_CHANNEL_ID)
            else:
                verified[field] = (related.get("message_reference") or {}).get("message_id") == message_id(item)

        for field, values in (("context_attachment", attachment_context), ("mention_attachment", [item])):
            for value in values:
                if value["attachments"]:
                    candidates[field] += 1
                    attempted = attachment_attempts[field]
                    if not verified[field] and len(attempted) < 8 and value["id"] not in attempted:
                        attempted.add(value["id"])
                        verified[field] = await verify_attachment(db, client, value)
    return {"candidates": candidates, "verified": verified}


async def main():
    root = settings.DISCORD_GA_REPLIES_CHANNEL_ID
    if not root or not settings.GA_DISCORD_MENTIONS_BOT_TOKEN:
        raise SystemExit("Staff channel and mentions bot must be configured")

    for _ in range(24):
        async with SessionLocal() as db:
            await db.execute(text("SET TRANSACTION READ ONLY"))
            await db.execute(text("SET LOCAL statement_timeout = '15s'"))
            marker = await db.scalar(select(GaDiscordArchiveCheckpoint.last_message_id).where(
                GaDiscordArchiveCheckpoint.channel_id == root,
            ))
            recent = await list_staff_channel_mentions(db, before=None, limit=50)
            imported = bool(marker and recent and int(marker) >= int(recent[-1].id))
            if imported:
                break
        await asyncio.sleep(5)

    async with SessionLocal() as db, httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        await db.execute(text("SET LOCAL statement_timeout = '15s'"))
        rows = await list_staff_channel_mentions(db, before=None, limit=100)
        items = await render_with_context(db, rows, ga_tz())
        for item in items:
            DiscordFeedMention.model_validate(item)
        result = await verify_context(db, client, items)
    await engine.dispose()
    print("GA_CONTEXT_CHECK " + json.dumps({"mentions_checked": len(items), "recent_history_imported": imported, **result}))


if __name__ == "__main__":
    asyncio.run(main())
