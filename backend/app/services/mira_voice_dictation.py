"""Turn explicit voice dictation into standalone PX Notes."""

import re

from sqlalchemy import select

from app.config import settings
from app.models.discord_assistant import DiscordLink
from app.models.discord_voice_meeting import DiscordVoiceSegment
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.ga_note import GaNoteCreate
from app.services.ga_note_creation import build_ga_note


COMMAND = re.compile(r"(?<!\w)(?:(?P<start>mira[\s,:.]+sh[ëe]no)|fund[\s,:.]+sh[ëe]nimi)(?!\w)", re.IGNORECASE)
START_PREFIX = re.compile(r"(?<!\w)mira[\s,:.]*$", re.IGNORECASE)
MAX_DICTATION_MS = 120_000
MAX_DICTATION_CHARS = 8_000


def consume(text, start_ms, end_ms, pending):
    """Read one speaker's chunks in order and return their next state and finished notes."""
    text = text.strip()
    started = None
    if pending and start_ms - pending["end_ms"] <= 15_000:
        started = pending.get("started")
        if started is None or end_ms - started <= MAX_DICTATION_MS:
            text = f"{pending['text']} {text}"
        else:
            started = None

    notes = []
    body_start = 0
    for marker in COMMAND.finditer(text):
        if marker.group("start"):
            started = start_ms
            body_start = marker.end()
        elif started is not None:
            body = text[body_start:marker.start()].lstrip(" ,:.-–—\n\t").rstrip()
            if body and len(body) <= MAX_DICTATION_CHARS:
                notes.append(body)
            started = None

    remaining = text[body_start:].lstrip(" ,:.-–—\n\t")
    if started is not None and len(remaining) <= MAX_DICTATION_CHARS:
        return {"started": started, "end_ms": end_ms, "text": remaining}, notes
    prefix = START_PREFIX.search(text)
    return ({"end_ms": end_ms, "text": prefix.group()} if prefix else None), notes


async def _save_notes(db, guild_id, speaker_id, source, notes):
    user = (await db.execute(
        select(User).join(DiscordLink, DiscordLink.user_id == User.id).where(
            DiscordLink.guild_id == guild_id,
            DiscordLink.discord_user_id == speaker_id,
            DiscordLink.enabled.is_(True),
            User.is_active.is_(True),
        )
    )).scalar_one_or_none()
    if user is None or (user.department_id is None and user.role not in (UserRole.ADMIN, UserRole.MANAGER)):
        return
    for content in notes:
        note = await build_ga_note(db, user, GaNoteCreate(content=content, department_id=user.department_id))
        note.mira_dictation_source = source


async def process(db, meeting, *, finished_segments=None):
    """Advance the cursor under the caller's meeting lock, in the note's transaction."""
    channel = {
        "primary": settings.DISCORD_1H_VOICE_CHANNEL_ID,
        "ai_agent": settings.DISCORD_AI_AGENT_VOICE_CHANNEL_ID,
    }.get(meeting.recorder)
    if not channel or meeting.voice_channel_id != channel or meeting.guild_id != settings.DISCORD_GUILD_ID:
        return
    source = "ai_agent" if meeting.recorder == "ai_agent" else "1h"
    progress = meeting.dictation_progress or {}
    cursor = progress.get("cursor", 0)
    pending = dict(progress.get("pending", {}))
    if finished_segments is None:
        segments = (await db.execute(select(DiscordVoiceSegment).where(
            DiscordVoiceSegment.session_id == meeting.id, DiscordVoiceSegment.sequence >= cursor,
        ).order_by(DiscordVoiceSegment.sequence))).scalars()
    else:
        segments = sorted(finished_segments, key=lambda segment: segment.sequence)

    for segment in segments:
        if segment.sequence < cursor:
            continue
        if finished_segments is None and (segment.sequence != cursor or segment.status == "PROCESSING"):
            break
        if segment.sequence != cursor:
            pending.clear()
        cursor = segment.sequence + 1
        state = pending.pop(segment.speaker_id, None)
        if segment.status != "DONE" or not segment.transcript:
            if segment.status == "DONE" and state:
                pending[segment.speaker_id] = state
            continue
        state, notes = consume(segment.transcript, segment.start_ms, segment.end_ms, state)
        if state:
            pending[segment.speaker_id] = state
        if notes:
            await _save_notes(db, meeting.guild_id, segment.speaker_id, source, notes)

    meeting.dictation_progress = {"cursor": cursor, "pending": pending if finished_segments is None else {}}
