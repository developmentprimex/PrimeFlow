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
from app.services.discord_ga_replies import _report_window, _without_links, ga_identity
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
    message_author_id: Snowflake
    message_content: str = Field(max_length=4000)
    has_attachments: bool
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
        message_id=evidence.message_id, staff_name=staff_name, message_excerpt=excerpt,
        emoji=evidence.emoji, observed_at=evidence.observed_at,
    ).on_conflict_do_nothing(index_elements=["event_id"])
    await db.execute(statement)
    await db.commit()


def render_reactions(reactions) -> str:
    from app.services.after_break_report import _ascii_table

    if not reactions:
        return NO_REACTIONS_RECORDED
    tz = report_timezone()
    columns = [("NR", 3), ("AUTORI", 24), ("MESAZHI", 55), ("REAGIMI", 16), ("DATA", 10), ("ORA", 5)]
    rows = []
    for number, reaction in enumerate(reactions, 1):
        observed = reaction.observed_at.astimezone(tz)
        rows.append([
            str(number), reaction.staff_name.replace("|", "¦"),
            reaction.message_excerpt.replace("|", "¦") or "-", reaction.emoji.replace("|", "¦"),
            observed.strftime("%d.%m.%Y"), observed.strftime("%H:%M"),
        ])
    return "\n".join(_ascii_table("Reagimet e GA në Discord", columns, rows))


async def reaction_summary_for_day(db, day, *, report, generated_at):
    if not settings.DISCORD_GUILD_ID or not settings.DISCORD_GA_REPLIES_CHANNEL_ID:
        return REACTIONS_UNAVAILABLE
    start, end = _report_window(day, report, generated_at)
    if end < start:
        return REACTIONS_UNAVAILABLE
    result = await db.scalars(select(DiscordGaReaction).where(
        DiscordGaReaction.guild_id == settings.DISCORD_GUILD_ID,
        DiscordGaReaction.channel_id == settings.DISCORD_GA_REPLIES_CHANNEL_ID,
        DiscordGaReaction.observed_at >= start, DiscordGaReaction.observed_at <= end,
    ).order_by(DiscordGaReaction.observed_at, DiscordGaReaction.event_id))
    return render_reactions(result.all())
