"""Evidence-based M1 reply summary; never infer replies from adjacent messages."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import settings
from app.models.discord_assistant import DiscordLink
from app.models.discord_ga_reply_snapshot import DiscordGaReplySnapshot
from app.models.user import User
from app.services.primeflow_report import report_timezone


class ChannelMessage(BaseModel):
    id: str = Field(pattern=r"^\d{1,32}$")
    author_id: str = Field(pattern=r"^\d{1,32}$")
    author: str = Field(max_length=100)
    content: str = Field(max_length=4000)
    created_at: datetime
    mentions_ga: bool = False
    reference_id: str | None = Field(default=None, pattern=r"^\d{1,32}$")
    thread_root_id: str | None = Field(default=None, pattern=r"^\d{1,32}$")
    # Store filenames/count only; no attachment downloads or signed URLs.
    attachments: int = Field(default=0, ge=0, le=100)


class ChannelEvidence(BaseModel):
    guild_id: str = Field(pattern=r"^\d{1,32}$")
    channel_id: str = Field(pattern=r"^\d{1,32}$")
    ga_user_id: str = Field(pattern=r"^\d{1,32}$")
    captured_at: datetime
    window_start: datetime
    status: str = Field(pattern=r"^(OK|PARTIAL|UNAVAILABLE)$")
    messages: list[ChannelMessage] = Field(default_factory=list, max_length=5000)


async def ga_identity(db):
    identity = (await db.execute(select(DiscordLink.discord_user_id).join(
        User, User.id == DiscordLink.user_id).where(
        User.username == "gane.arifaj", User.is_active.is_(True),
        DiscordLink.enabled.is_(True), DiscordLink.guild_id == settings.DISCORD_GUILD_ID,
    ))).scalar_one_or_none()
    if not identity:
        raise HTTPException(424, "GA nuk ka lidhje aktive Discord në këtë server.")
    return identity


def validate_evidence(value, ga_id, now):
    if value.guild_id != settings.DISCORD_GUILD_ID or value.channel_id != settings.DISCORD_GA_REPLIES_CHANNEL_ID:
        raise HTTPException(403, "Kanali nuk është burimi i M1 për përgjigjet GA.")
    if value.ga_user_id != ga_id:
        raise HTTPException(409, "Lidhja Discord e GA ka ndryshuar; rilexo burimin.")
    if value.captured_at.tzinfo is None or value.window_start.tzinfo is None:
        raise HTTPException(422, "Koha e burimit duhet të ketë zonë kohore.")
    if not now - timedelta(minutes=5) <= value.captured_at <= now + timedelta(seconds=30):
        raise HTTPException(409, "Burimi Discord është i vjetruar.")
    if abs((value.captured_at - value.window_start) - timedelta(days=30)) > timedelta(seconds=1):
        raise HTTPException(422, "Dritarja e burimit duhet të jetë 30 ditë.")
    if any(m.created_at.tzinfo is None or not value.window_start <= m.created_at <= value.captured_at for m in value.messages):
        raise HTTPException(422, "Mesazh jashtë intervalit të burimit.")


def requests_with_replies(messages, ga_id):
    """One explicitly addressed message = one request, even with several questions."""
    by_id = {m["id"]: m for m in messages}
    requests = {}
    for m in by_id.values():
        text = re.sub(r"<@!?\d+>", "", m["content"]).strip()
        if (m["author_id"] != ga_id and m["mentions_ga"] and not m.get("reference_id")
                and not m.get("thread_root_id") and (text or m.get("attachments"))):
            requests[m["id"]] = {**m, "reply_id": None, "reply_channel_id": None}
    for m in sorted(by_id.values(), key=lambda item: int(item["id"])):
        if m["author_id"] != ga_id or not (m["content"].strip() or m.get("attachments")):
            continue
        parent = m.get("thread_root_id") or m.get("reference_id")
        seen = {m["id"]}
        while parent and parent not in seen:
            if parent in requests:
                requests[parent]["reply_id"] = m["id"]
                requests[parent]["reply_channel_id"] = m.get("thread_root_id")
                break
            seen.add(parent)
            ancestor = by_id.get(parent, {})
            parent = ancestor.get("thread_root_id") or ancestor.get("reference_id")
    return sorted(requests.values(), key=lambda item: int(item["id"]))


def render_summary(evidence, captured_at, now):
    if (not evidence or evidence.get("status") == "UNAVAILABLE"
            or now - captured_at > timedelta(minutes=5)):
        return "Përgjigjet GA: burimi Discord nuk është i disponueshëm ose i përditësuar. Nuk mund të konfirmohet numërimi."
    rows = requests_with_replies(evidence["messages"], evidence["ga_user_id"])
    replied = sum(bool(row["reply_id"]) for row in rows)
    channel = f"https://discord.com/channels/{evidence['guild_id']}/{evidence['channel_id']}"
    lines = [
        f"GA është përgjigjur në {replied} nga {len(rows)} kërkesa; {len(rows) - replied} pa reply të lidhur.",
        "Burimi: #det-nga-stafi-per-ga — " + channel,
        "Kërkesat me @GA gjatë 30 ditëve të fundit; një mesazh llogaritet si një kërkesë.",
        "Përgjigjet verifikohen vetëm me Reply ose thread. Mesazhet e lira dhe reagimet nuk konfirmojnë përgjigje.",
        f"Kontrolluar: {captured_at.astimezone(report_timezone()):%d.%m.%Y %H:%M}.",
    ]
    if evidence["status"] == "PARTIAL":
        lines.insert(0, "KONTROLL I PJESSHËM: numërimi më poshtë mbulon vetëm mesazhet e lexuara.")
    for index, row in enumerate(rows, 1):
        title = re.sub(r"<@!?\d+>", "", row["content"])
        title = re.sub(r"[\r\n|]+", " ", title).strip()[:180] or "Kërkesë me bashkëngjitje"
        author = re.sub(r"[\r\n|]+", " ", row["author"])
        lines += [f"{index}. {author}: {title}", f"Kërkesa: {channel}/{row['id']}"]
        if row["reply_id"]:
            reply_channel = row["reply_channel_id"] or evidence["channel_id"]
            lines.append(f"Përgjigjja GA: https://discord.com/channels/{evidence['guild_id']}/{reply_channel}/{row['reply_id']}")
        else:
            lines.append("Pa reply të lidhur nga GA.")
    return "\n".join(lines)


async def summary_for_day(db, day):
    now = datetime.now(timezone.utc)
    row = await db.get(DiscordGaReplySnapshot, (settings.DISCORD_GUILD_ID or "", settings.DISCORD_GA_REPLIES_CHANNEL_ID, day))
    if day != now.astimezone(report_timezone()).date():
        # Regenerating a historical draft uses that day's evidence only.
        return render_summary(row.evidence, row.captured_at, row.captured_at) if row else "Përgjigjet GA: nuk ka burim të ruajtur për këtë datë."
    if not settings.DISCORD_ASSISTANT_ENABLED:
        row = None
    elif row:
        try:
            if row.evidence.get("ga_user_id") != await ga_identity(db):
                row = None
        except HTTPException:
            row = None
    return render_summary(row.evidence if row else None, row.captured_at if row else now, now)


async def refresh_m1_section(db, sections, day):
    from app.services.morning_report import SECTION_TITLES
    # This is only called for drafts. Historical drafts and sent snapshots stay frozen.
    if day != datetime.now(report_timezone()).date():
        return sections
    title = SECTION_TITLES[0]
    body = await summary_for_day(db, day)
    return [{**section, "body": body}
            if (section.get("section_key") or section.get("title")) == title else section
            for section in sections]
