"""Evidence-based M1 reply summary; never infer replies from adjacent messages."""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import settings
from app.models.discord_assistant import DiscordLink
from app.models.discord_ga_reply_snapshot import DiscordGaReplySnapshot
from app.models.user import User
from app.services.primeflow_report import report_timezone

NO_REPLY = "Nuk ka përgjigje ose komente nga GA për këtë raport."
LEGACY_NO_REPLY = "Nuk ka përgjigje të lidhura nga GA."
EMPTY_REPLY_ROW = "Asnjë reply"
UNAVAILABLE = "Teksti i përgjigjeve të GA nuk është i disponueshëm."
LEGACY_REPLY_LINK = re.compile(r"^Përgjigjja GA: https://discord\.com/channels/\d+/\d+/(\d+)[ \t]*\r?$", re.M)
GA_MESSAGES_CAPTION = "Përgjigjet dhe komentet e GA"
GA_REPLIES_SECTION_TITLE = "(GA) A KA REPLY NGA GA TEK DETYRAT NGA STAFI PER GA?"


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


async def ga_identity(db, *, guild_id=None):
    identity = (await db.execute(select(DiscordLink.discord_user_id).join(
        User, User.id == DiscordLink.user_id).where(
        User.username == "gane.arifaj", User.is_active.is_(True),
        DiscordLink.enabled.is_(True), DiscordLink.guild_id == (guild_id or settings.DISCORD_GUILD_ID),
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
            requests[m["id"]] = {**m, "reply_id": None}
    for m in sorted(by_id.values(), key=lambda item: int(item["id"])):
        if m["author_id"] != ga_id or not (m["content"].strip() or m.get("attachments")):
            continue
        parent = m.get("thread_root_id") or m.get("reference_id")
        seen = {m["id"]}
        while parent and parent not in seen:
            if parent in requests:
                requests[parent]["reply_id"] = m["id"]
                break
            seen.add(parent)
            ancestor = by_id.get(parent, {})
            parent = ancestor.get("thread_root_id") or ancestor.get("reference_id")
    return sorted(requests.values(), key=lambda item: int(item["id"]))


def _without_links(text):
    text = re.sub(r"\[([^\]\n]+)\]\(https?://[^\s)]+\)", r"\1", text)
    return re.sub(r"<?https?://[^\s<>]+>?", "", text).strip()


def _message_time(message):
    return datetime.fromisoformat(message["created_at"])


def _linked_reply_ids(evidence):
    rows = requests_with_replies(evidence["messages"], evidence["ga_user_id"])
    return [row["reply_id"] for row in rows if row["reply_id"]]


def _ga_message_rows(evidence, reply_ids, *, include_context=True, initials_by_user=None):
    from app.services.meetings_report import _initials

    messages = {message["id"]: message for message in evidence["messages"]}
    rows = []
    for reply_id in dict.fromkeys(reply_ids):
        reply = messages.get(reply_id)
        if not reply or reply["author_id"] != evidence["ga_user_id"]:
            continue
        text = _without_links(reply["content"])
        if not text:
            continue
        author, first_sentence = "", ""
        if include_context:
            text = re.sub(r"<@!?\d+>\s*", "", text).strip()
            if not text:
                continue
            original = messages.get(reply.get("reference_id") or reply.get("thread_root_id"))
            if original:
                author = " ".join(_without_links(original["author"]).split())
                if initials_by_user is not None and author:
                    author = initials_by_user.get(original["author_id"]) or _initials(author)
                original_text = re.sub(r"<@!?\d+>\s*", "", _without_links(original["content"])).strip()
                first_line = original_text.split("\n", 1)[0].strip()
                first_sentence = re.split(r"(?<=[!?])\s+|(?<!\d\.)(?<=\.)\s+", first_line, maxsplit=1)[0]
                if len(first_sentence) > 240:
                    first_sentence = first_sentence[:239].rsplit(" ", 1)[0] + "…"
        rows.append((author, first_sentence, text))
    return rows


def _included_message_ids(evidence, report_day, reply_ids):
    linked_ids = _linked_reply_ids(evidence) if reply_ids is None else reply_ids
    daily_ids = {
        message["id"] for message in evidence["messages"]
        if message["author_id"] == evidence["ga_user_id"]
        and _message_time(message).astimezone(report_timezone()).date() == report_day
        and (reply_ids is None or not (message.get("reference_id") or message.get("thread_root_id")))
    }
    return sorted(daily_ids.union(linked_ids), key=int), linked_ids


def _previous_context_body(rows):
    texts = []
    for author, original, text in rows:
        if author:
            context = f"Përgjigje për {author}" + (f" — «{original}»" if original else "")
            text = f"{context}\n{text}"
        texts.append(text)
    return "\n\n".join(texts)


def _render_reply_table(values):
    from app.services.after_break_report import _ascii_table

    return "\n".join(_ascii_table(GA_MESSAGES_CAPTION,
        [("NR", 2), ("PËR KË", 7), ("MESAZHI ORIGJINAL", 40), ("PËRGJIGJJA E GA", 52)], values))


def _empty_reply_table():
    return _render_reply_table([["-", "", "", EMPTY_REPLY_ROW]])


def _has_reply(evidence, message_ids):
    selected = set(message_ids)
    return any(
        message["id"] in selected and (message.get("reference_id") or message.get("thread_root_id"))
        for message in evidence["messages"]
    )


def _report_window(day, report, cutoff):
    tz = report_timezone()
    start = datetime.combine(day - timedelta(days=1), time(16, 30), tz) if report == "M1" else datetime.combine(day, time(8), tz)
    end_of_day = datetime.combine(day, time.max, tz)
    return start, min(cutoff, end_of_day)


def render_summary(evidence, captured_at, now, *, day=None, reply_ids=None, initials_by_user=None, window=None):
    if (not evidence or evidence.get("status") == "UNAVAILABLE"
            or now - captured_at > timedelta(minutes=5)):
        return UNAVAILABLE
    if window:
        start, cutoff = window
        message_ids = sorted({message["id"] for message in evidence["messages"]
                              if message["author_id"] == evidence["ga_user_id"]
                              and start <= _message_time(message) <= cutoff}, key=int)
        linked_ids = []
    else:
        message_ids, linked_ids = _included_message_ids(evidence, day or captured_at.astimezone(report_timezone()).date(), reply_ids)
    rows = _ga_message_rows(evidence, message_ids, initials_by_user=initials_by_user or {})
    has_reply = bool(linked_ids) or _has_reply(evidence, message_ids)
    if not rows and (has_reply or evidence["status"] == "PARTIAL"):
        return UNAVAILABLE
    values = [[str(index), *(value.replace("|", "¦") for value in row)] for index, row in enumerate(rows, 1)]
    if not has_reply and evidence["status"] == "OK":
        values.append(["-", "", "", EMPTY_REPLY_ROW])
    return _render_reply_table(values)


async def _recipient_initials(db, evidence):
    from app.services.meetings_report import _initials

    authors_by_id = {message["id"]: message["author_id"] for message in evidence["messages"]}
    recipient_ids = {
        authors_by_id[parent]
        for message in evidence["messages"] if message["author_id"] == evidence["ga_user_id"]
        if (parent := message.get("reference_id") or message.get("thread_root_id")) in authors_by_id
    }
    if not recipient_ids:
        return {}
    links = await db.execute(select(DiscordLink.discord_user_id, User.full_name).join(
        User, User.id == DiscordLink.user_id,
    ).where(DiscordLink.guild_id == evidence["guild_id"], DiscordLink.enabled.is_(True),
            DiscordLink.discord_user_id.in_(recipient_ids)))
    return {discord_id: _initials(full_name) for discord_id, full_name in links.all() if full_name}


def _upgrade_old_reply_table(body, evidence, initials_by_user, day):
    from app.services.meetings_report import _initials, _section_report_blocks

    by_display_name = {}
    for message in evidence.get("messages", []):
        author = " ".join(_without_links(message["author"]).split())
        initials = initials_by_user.get(message["author_id"])
        if initials:
            by_display_name.setdefault(author, set()).add(initials)
    rows = next((block["rows"] for block in _section_report_blocks(body) if block["kind"] == "table"), [])
    if not rows:
        return body
    values = []
    for number, author, original, reply in rows:
        author = " ".join(author.split())
        options = by_display_name.get(author, set())
        initials = next(iter(options)) if len(options) == 1 else _initials(author) if author else ""
        values.append([number, initials, original, reply])
    if not any(row[1] for row in values) and evidence.get("status") == "OK":
        message_ids, _ = _included_message_ids(evidence, day, None)
        if not _has_reply(evidence, message_ids):
            values.append(["-", "", "", EMPTY_REPLY_ROW])
    return _render_reply_table(values)


async def _snapshot_for_day(db, day):
    channel_id = settings.DISCORD_GA_REPLIES_CHANNEL_ID
    if settings.DISCORD_GUILD_ID:
        return await db.get(DiscordGaReplySnapshot, (settings.DISCORD_GUILD_ID, channel_id, day))
    # Report-only instances may lack bot settings. Discord channel IDs are globally unique.
    return (await db.execute(select(DiscordGaReplySnapshot).where(
        DiscordGaReplySnapshot.channel_id == channel_id, DiscordGaReplySnapshot.day == day,
    ))).scalar_one_or_none()


async def summary_for_day(db, day, *, report=None, generated_at=None):
    now = datetime.now(timezone.utc)
    row = await _snapshot_for_day(db, day)
    current = day == now.astimezone(report_timezone()).date()
    if row and current:
        try:
            if row.evidence.get("ga_user_id") != await ga_identity(db, guild_id=row.evidence.get("guild_id")):
                row = None
        except HTTPException:
            row = None
    if not row:
        return UNAVAILABLE
    return render_summary(row.evidence, row.captured_at, now if current else row.captured_at,
                          day=day, initials_by_user=await _recipient_initials(db, row.evidence),
                          window=_report_window(day, report, generated_at or now) if report else None)


async def refresh_m1_section(db, sections, day, *, refresh_current=True, sent_at=None, generated_snapshot=None):
    return await refresh_ga_reply_section(db, sections, day, report="M1", refresh_current=refresh_current,
                                          sent_at=sent_at, generated_snapshot=generated_snapshot)


async def refresh_ga_reply_section(db, sections, day, *, report=None, refresh_current=True, sent_at=None,
                                   populate_missing=False, generated_snapshot=None):
    if (generated_snapshot or {}).get("ga_replies_generated_at"):
        return sections
    current = refresh_current and day == datetime.now(report_timezone()).date()
    result = []
    for section in sections:
        if (section.get("section_key") or section.get("title")) != GA_REPLIES_SECTION_TITLE:
            result.append(section)
            continue
        body = section.get("body") or ""
        if current:
            body = await summary_for_day(db, day, report=report)
        elif populate_missing and body in {"", "(Ploteso manualisht)", UNAVAILABLE}:
            snapshot = await _snapshot_for_day(db, day)
            evidence = _evidence_until(snapshot.evidence, sent_at) if snapshot else None
            body = render_summary(evidence, snapshot.captured_at, snapshot.captured_at, day=day,
                                  initials_by_user=await _recipient_initials(db, evidence),
                                  window=_report_window(day, report, sent_at or snapshot.captured_at) if report else None) if evidence else UNAVAILABLE
        elif body in {NO_REPLY, LEGACY_NO_REPLY}:
            body = _empty_reply_table()
        elif body.startswith(f"{GA_MESSAGES_CAPTION}:") and f"| {'PËR KË':<19} |" in body:
            snapshot = await _snapshot_for_day(db, day)
            evidence = snapshot.evidence if snapshot else {}
            initials = await _recipient_initials(db, evidence) if evidence else {}
            body = _upgrade_old_reply_table(body, evidence, initials, day)
        else:
            legacy = body.startswith(("GA është përgjigjur në ", "KONTROLL I PJESSHËM:")) and "Burimi: #det-nga-stafi-per-ga" in body
            can_upgrade = sent_at and not body.startswith(f"{GA_MESSAGES_CAPTION}:")
            if not (legacy or can_upgrade):
                result.append(section)
                continue
            snapshot = await _snapshot_for_day(db, day)
            if not snapshot and legacy:
                body = UNAVAILABLE if LEGACY_REPLY_LINK.search(body) or body.startswith("KONTROLL I PJESSHËM:") else _empty_reply_table()
            elif snapshot:
                evidence = _evidence_until(snapshot.evidence, sent_at)
                old_text = "\n\n".join(text for _, _, text in _ga_message_rows(
                    evidence, _linked_reply_ids(evidence), include_context=False,
                ))
                message_ids, _ = _included_message_ids(evidence, day, None)
                previous_context = _previous_context_body(_ga_message_rows(evidence, message_ids))
                if legacy or body in {UNAVAILABLE, LEGACY_NO_REPLY} or (body and body in {old_text, previous_context}):
                    reply_ids = LEGACY_REPLY_LINK.findall(body) if legacy else None
                    updated = render_summary(evidence, snapshot.captured_at, snapshot.captured_at, day=day,
                                             reply_ids=reply_ids, initials_by_user=await _recipient_initials(db, evidence))
                    if body != UNAVAILABLE or updated != _empty_reply_table():
                        body = updated
        result.append({**section, "body": body})
    return result


def _evidence_until(evidence, sent_at):
    if not sent_at:
        return evidence
    return {**evidence, "messages": [
        message for message in evidence["messages"] if _message_time(message) <= sent_at
    ]}
