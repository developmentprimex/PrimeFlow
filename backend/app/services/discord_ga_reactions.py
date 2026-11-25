"""Record live additions and report them using the GA comments window."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import HTTPException
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.models.discord_assistant import DiscordLink
from app.models.discord_ga_reaction import DiscordGaReaction
from app.models.user import User
from app.services.discord_ga_replies import (
    _report_window, _snapshot_for_day, _without_links, fetch_discord_message_attachments, ga_identity,
)
from app.services.primeflow_report import report_timezone

GA_REACTIONS_SECTION_KEY = "A KA REACTION TE GRUPI?"
GA_REACTIONS_SECTION_TITLE = "(GA) A KA REACTION NGA GA TEK DETYRAT NGA STAFI PER GA?"
REACTIONS_UNAVAILABLE = "Evidenca e reagimeve nga Discord nuk është e disponueshme për këtë raport."
NO_REACTIONS_RECORDED = "Asnjë reagim i regjistruar. Evidenca përfshin vetëm reagimet e marra nga boti pas aktivizimit."
Snowflake = Annotated[str, Field(pattern=r"^\d{1,32}$")]


class ReactionEvidence(BaseModel):
    event_id: UUID
    guild_id: Snowflake
    channel_id: Snowflake
    ga_user_id: Snowflake
    message_id: Snowflake
    message_channel_id: Snowflake | None = None
    message_author_id: Snowflake
    message_content: str = Field(max_length=4000)
    has_attachments: bool
    attachment_count: int | None = Field(default=None, ge=0, le=100)
    emoji: str = Field(min_length=1, max_length=100)
    observed_at: AwareDatetime


async def record_reaction(db, evidence: ReactionEvidence):
    if evidence.guild_id != settings.DISCORD_GUILD_ID or evidence.channel_id != settings.DISCORD_GA_REPLIES_CHANNEL_ID:
        raise HTTPException(403, "Kanali nuk është burimi i reagimeve të GA.")
    if evidence.ga_user_id != await ga_identity(db):
        raise HTTPException(409, "Lidhja Discord e GA ka ndryshuar.")
    if evidence.message_author_id == evidence.ga_user_id:
        return
    now = datetime.now(timezone.utc)
    if not now - timedelta(minutes=10) <= evidence.observed_at <= now + timedelta(seconds=30):
        raise HTTPException(422, "Koha e regjistrimit të reagimit është jashtë intervalit.")

    staff_name = (await db.execute(select(User.full_name).join(DiscordLink, DiscordLink.user_id == User.id).where(
        DiscordLink.guild_id == evidence.guild_id, DiscordLink.discord_user_id == evidence.message_author_id,
        DiscordLink.enabled.is_(True), User.is_active.is_(True), User.work_staff_filter(),
    ))).scalar_one_or_none()
    if staff_name is None:
        return

    excerpt = " ".join(_without_links(evidence.message_content).split())
    if len(excerpt) > 280:
        excerpt = excerpt[:279].rstrip() + "…"
    if not excerpt and evidence.has_attachments:
        excerpt = "(Mesazh me bashkëngjitje)"
    statement = insert(DiscordGaReaction).values(
        event_id=evidence.event_id, guild_id=evidence.guild_id, channel_id=evidence.channel_id,
        message_id=evidence.message_id, message_channel_id=evidence.message_channel_id,
        message_author_id=evidence.message_author_id, attachment_count=evidence.attachment_count,
        staff_name=staff_name, message_excerpt=excerpt,
        emoji=evidence.emoji, observed_at=evidence.observed_at,
    ).on_conflict_do_nothing(index_elements=["event_id"])
    await db.execute(statement)
    await db.commit()


_COLUMNS = [("NR", 3), ("AUTORI", 10), ("MESAZHI", 55), ("REAGIMI", 16),
            ("SKEDARËT", 96), ("DATA", 10), ("ORA", 5)]
_CAPTION = "Reagimet e GA në Discord"


def _source_details(reaction, legacy_messages):
    channel_id = getattr(reaction, "message_channel_id", None)
    author_id = getattr(reaction, "message_author_id", None)
    count = getattr(reaction, "attachment_count", None)
    if count == 0:
        return None
    if channel_id and author_id and count:
        return channel_id, author_id, count
    legacy = legacy_messages.get((reaction.guild_id, reaction.channel_id, reaction.message_id)) if legacy_messages else None
    if legacy and legacy.get("attachments"):
        return legacy.get("thread_root_id") or reaction.channel_id, legacy["author_id"], legacy["attachments"]
    return None


def _files_cell(reaction, legacy_messages) -> str:
    source = _source_details(reaction, legacy_messages)
    if not source:
        return "-"
    channel_id, _, count = source
    return f"{count} https://discord.com/channels/{reaction.guild_id}/{channel_id}/{reaction.message_id}"


async def _legacy_message_details(db, day, reactions):
    if not any(getattr(row, "attachment_count", None) is None for row in reactions):
        return {}
    snapshot = await _snapshot_for_day(db, day)
    evidence = (snapshot.evidence or {}) if snapshot else {}
    return {(evidence["guild_id"], evidence["channel_id"], message["id"]): message
            for message in evidence.get("messages", []) if message.get("attachments")}


def render_reactions(reactions, legacy_messages=None) -> str:
    from app.services.after_break_report import _ascii_table
    from app.services.meetings_report import _initials

    if not reactions:
        return NO_REACTIONS_RECORDED
    tz = report_timezone()
    rows = []
    for number, reaction in enumerate(reactions, 1):
        observed = reaction.observed_at.astimezone(tz)
        rows.append([
            str(number), _initials(reaction.staff_name),
            reaction.message_excerpt.replace("|", "¦") or "-", reaction.emoji.replace("|", "¦"),
            _files_cell(reaction, legacy_messages or {}), observed.strftime("%d.%m.%Y"), observed.strftime("%H:%M"),
        ])
    return "\n".join(_ascii_table(_CAPTION, _COLUMNS, rows))


def _window_query(day, report, generated_at):
    channel_id = settings.DISCORD_GA_REPLIES_CHANNEL_ID
    if not channel_id:
        return None
    start, end = _report_window(day, report, generated_at)
    if end < start:
        return None
    statement = select(DiscordGaReaction).where(
        DiscordGaReaction.channel_id == channel_id,
        DiscordGaReaction.observed_at >= start, DiscordGaReaction.observed_at <= end,
    )
    # Discord channel IDs are globally unique; report-only instances may lack bot settings.
    if settings.DISCORD_GUILD_ID:
        statement = statement.where(DiscordGaReaction.guild_id == settings.DISCORD_GUILD_ID)
    return statement


async def reaction_summary_for_day(db, day, *, report, generated_at):
    statement = _window_query(day, report, generated_at)
    if statement is None:
        return REACTIONS_UNAVAILABLE
    result = await db.scalars(statement.order_by(DiscordGaReaction.observed_at, DiscordGaReaction.event_id))
    rows = result.all()
    return render_reactions(rows, await _legacy_message_details(db, day, rows))


async def reaction_attachment_links(db, day, report, cutoff, message_id):
    statement = _window_query(day, report, cutoff)
    if statement is not None:
        result = await db.scalars(statement.where(DiscordGaReaction.message_id == message_id))
        rows = result.all()
        legacy = await _legacy_message_details(db, day, rows)
        for row in rows:
            if source := _source_details(row, legacy):
                channel_id, author_id, _ = source
                return await fetch_discord_message_attachments(channel_id, row.message_id, author_id)
    raise HTTPException(404, "Mesazhi me bashkëngjitje nuk gjendet te reagimet e këtij raporti.")


async def _upgrade_saved_table(db, body: str, day, report, cutoff) -> str:
    from app.services.after_break_report import _ascii_table
    from app.services.meetings_report import _initials, _section_report_table_rows

    if not body.casefold().startswith(_CAPTION.casefold() + ":"):
        return body
    headers, rows = _section_report_table_rows(body.splitlines()[1:])
    old_columns = [column for column in _COLUMNS if column[0] != "SKEDARËT"]
    if headers != [column for column, _ in old_columns]:
        return body
    by_row = {}
    statement = _window_query(day, report, cutoff)
    if statement is not None:
        reactions = (await db.scalars(statement)).all()
        legacy = await _legacy_message_details(db, day, reactions)
        tz = report_timezone()
        for reaction in reactions:
            observed = reaction.observed_at.astimezone(tz)
            key = (
                reaction.staff_name.replace("|", "¦"), reaction.message_excerpt.replace("|", "¦") or "-",
                reaction.emoji.replace("|", "¦"), observed.strftime("%d.%m.%Y"), observed.strftime("%H:%M"),
            )
            by_row.setdefault(tuple(" ".join(value.split()) for value in key), set()).add(_files_cell(reaction, legacy))
    upgraded = []
    for number, name, message, emoji, date, time in rows:
        key = tuple(" ".join(value.split()) for value in (name, message, emoji, date, time))
        files = by_row.get(key, set())
        upgraded.append([number, _initials(name), message, emoji, next(iter(files)) if len(files) == 1 else "-", date, time])
    return "\n".join(_ascii_table(_CAPTION, _COLUMNS, upgraded))


async def refresh_ga_reaction_section(db, sections, day, *, report, generated_snapshot, sent):
    generated_at = (generated_snapshot or {}).get("ga_replies_generated_at")
    if not generated_at:
        return sections
    cutoff = datetime.fromisoformat(generated_at)
    return [
        {**section, "body": await reaction_summary_for_day(
            db, day, report=report, generated_at=cutoff,
        ) if not sent or section.get("body") == REACTIONS_UNAVAILABLE
        else await _upgrade_saved_table(db, section.get("body", ""), day, report, cutoff)}
        if (section.get("section_key") or section.get("title")) == GA_REACTIONS_SECTION_KEY else section
        for section in sections
    ]
