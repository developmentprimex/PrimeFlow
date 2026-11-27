"""Read the Development text channel for the three daily meeting checklists."""

import asyncio
import logging
import re
from datetime import datetime, time

import httpx
from sqlalchemy import select

from app.config import settings
from app.models.discord_assistant import DiscordLink
from app.services.primeflow_report import previous_working_day

DISCORD_API = "https://discord.com/api/v10"
CHANNEL_NAME = "zhvillim-text"
READ_PERMISSIONS = (1 << 10) | (1 << 16)  # VIEW_CHANNEL and READ_MESSAGE_HISTORY
ADMINISTRATOR = 1 << 3
DISCORD_EPOCH_MS = 1420070400000
END_TIMES = {"M1": time(8, 15), "M2": time(12), "M3": time(16, 30)}
logger = logging.getLogger(__name__)


def _window(slot, now):
    day = now.date()
    start_day = previous_working_day(day) if slot == "M1" else day
    start_at = {"M1": END_TIMES["M3"], "M2": END_TIMES["M1"], "M3": END_TIMES["M2"]}[slot]
    return (datetime.combine(start_day, start_at, now.tzinfo),
            min(now, datetime.combine(day, END_TIMES[slot], now.tzinfo)))


def _can_read_channel(guild, channel, member_id, member):
    if guild["owner_id"] == member_id:
        return True
    roles = set(member["roles"])
    everyone = guild["id"]
    permissions = 0
    for role in guild["roles"]:
        if role["id"] in roles or role["id"] == everyone:
            permissions |= int(role["permissions"])
    if permissions & ADMINISTRATOR:
        return True
    overwrites = channel["permission_overwrites"]
    for kind, ids in ((0, {everyone}), (0, roles), (1, {member_id})):
        allow = deny = 0
        for overwrite in overwrites:
            if overwrite["type"] == kind and overwrite["id"] in ids:
                allow |= int(overwrite["allow"])
                deny |= int(overwrite["deny"])
        permissions = (permissions & ~deny) | allow
    return permissions & READ_PERMISSIONS == READ_PERMISSIONS


async def _get(client, path, **kwargs):
    response = await client.get(path, **kwargs)
    response.raise_for_status()
    return response.json()


def _safe_text(value):
    # Discord text can be exported into an Excel cell.
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]", "", value or "").strip()


async def _read_messages(client, guild_id, channel_id, start, end):
    before = (int(end.timestamp() * 1000) - DISCORD_EPOCH_MS) << 22
    rows = []
    unreadable = False
    while True:
        page = await _get(client, f"/channels/{channel_id}/messages", params={"before": str(before), "limit": 100})
        if not page:
            break
        for message in page:
            posted = datetime.fromisoformat(message["timestamp"]).astimezone(start.tzinfo)
            if message["channel_id"] != channel_id or not start <= posted < end:
                continue
            content = _safe_text(message.get("content"))
            if not content:
                content = "\n".join(filter(None, (_safe_text(embed.get("description") or embed.get("title"))
                                                   for embed in message.get("embeds", []))))
            attachments = [_safe_text(item.get("filename")) for item in message.get("attachments", [])]
            if attachments := list(filter(None, attachments)):
                content = "\n".join(filter(None, (content, f"Skedarë: {', '.join(attachments)}")))
            if not content and message.get("type", 0) in (0, 19) and not (
                message.get("sticker_items") or message.get("poll") or message.get("message_snapshots")
            ):
                unreadable = True
            if content:
                author = message["author"]
                # IDs are Discord snowflakes and form an original-message URL.
                message_id = str(int(message["id"]))
                rows.append({
                    "id": message_id,
                    "title": _safe_text(author.get("global_name") or author.get("username")) or "Discord",
                    "detail": content,
                    "labels": [posted.strftime("%d.%m.%Y %H:%M")],
                    "href": f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}",
                })
        if len(page) < 100 or datetime.fromisoformat(page[-1]["timestamp"]) < start:
            break
        cursor = int(page[-1]["id"])
        if cursor >= before:
            raise ValueError("Discord history cursor did not advance")
        before = cursor
    return rows, unreadable


async def load_development_discord_notes(db, user, slot, now):
    guild_id = settings.DISCORD_GUILD_ID
    token = settings.DISCORD_BOT_TOKEN or settings.GA_DISCORD_MENTIONS_BOT_TOKEN
    if not (guild_id and guild_id.isdecimal() and token):
        return {"rows": [], "message": "Lidhja me Discord nuk është konfiguruar në këtë server."}
    discord_id = await db.scalar(select(DiscordLink.discord_user_id).where(
        DiscordLink.user_id == user.id,
        DiscordLink.guild_id == guild_id,
        DiscordLink.enabled.is_(True),
    ))
    if not discord_id or not discord_id.isdecimal():
        return {"rows": [], "message": "Lidh llogarinë Discord për të parë shënimet e kanalit."}
    start, end = _window(slot, now)
    if end <= start:
        return {"rows": [], "message": f"Leximi për {slot} fillon në {start:%H:%M}."}
    try:
        async with asyncio.timeout(12), httpx.AsyncClient(
            base_url=DISCORD_API, timeout=6, headers={"Authorization": f"Bot {token}"},
        ) as client:
            guild, channels, member, bot_user = await asyncio.gather(
                _get(client, f"/guilds/{guild_id}"),
                _get(client, f"/guilds/{guild_id}/channels"),
                _get(client, f"/guilds/{guild_id}/members/{discord_id}"),
                _get(client, "/users/@me"),
            )
            matches = [channel for channel in channels if channel.get("name") == CHANNEL_NAME and channel.get("type") == 0]
            if len(matches) != 1 or guild["id"] != guild_id:
                return {"rows": [], "message": "Kanali #zhvillim-text nuk u identifikua në Discord."}
            channel = matches[0]
            channel_id = str(int(channel["id"]))
            if not _can_read_channel(guild, channel, discord_id, member):
                return {"rows": [], "message": "Llogaria jote në Discord nuk ka leje leximi në këtë kanal."}
            bot_id = str(int(bot_user["id"]))
            bot_member = await _get(client, f"/guilds/{guild_id}/members/{bot_id}")
            if not _can_read_channel(guild, channel, bot_id, bot_member):
                return {"rows": [], "message": "Boti i PrimeFlow nuk ka leje leximi në #zhvillim-text."}
            rows, unreadable = await _read_messages(client, guild_id, channel_id, start, end)
    except (httpx.HTTPError, TimeoutError, KeyError, TypeError, ValueError) as error:
        logger.warning("Development Discord notes unavailable: %s", type(error).__name__)
        return {"rows": [], "message": "Shënimet nga #zhvillim-text nuk mund të lexoheshin."}
    message = "Disa postime erdhën pa tekst nga Discord. Kontrollo lejen Message Content të botit." if unreadable else (
        None if rows else "Asnjë shënim nga #zhvillim-text në këtë interval."
    )
    return {"rows": rows, "message": message,
            "interval": f"{start:%d.%m.%Y %H:%M} – {end:%d.%m.%Y %H:%M}"}


async def attach_development_discord_notes(db, user, slot, now, report, checklist_items):
    target = "teams" if slot == "M1" else "notes"
    if target not in report["item_sections"].values():
        return report
    discord_notes = await load_development_discord_notes(db, user, slot, now)
    item_titles = report.setdefault("item_titles", {})
    for item in checklist_items:
        item_id = str(item.id)
        if report["item_sections"].get(item_id) == target:
            original = item.title or ""
            renamed = re.sub(r"\b(?:(?:AI\s+AGENTS?|ZHVILLIM)\s+)?TEAMS(?:\s+ZHVILLIM)?\b",
                             "Discord #zhvillim-text", original, flags=re.I)
            if renamed != original:
                item_titles.setdefault(item_id, renamed)
    for section in report["sections"]:
        if section["key"] == target:
            section["discord_notes"] = discord_notes
            if slot == "M1":
                section["message"] = None
    return report
