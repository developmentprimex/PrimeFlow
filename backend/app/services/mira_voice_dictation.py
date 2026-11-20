"""Handle explicit note and task dictation in the meeting transcript."""

import logging
import re

from fastapi import HTTPException
from sqlalchemy import select

from app.config import settings
from app.models.discord_assistant import DiscordLink
from app.models.discord_voice_meeting import DiscordVoiceMeeting, DiscordVoiceSegment
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.ga_note import GaNoteCreate
from app.schemas.task import TaskCreate
from app.services.ga_note_creation import build_ga_note


log = logging.getLogger(__name__)
COMMAND = re.compile(
    r"(?<!\w)(?:mira[\s,:.]+(?:(?P<note>sh[ëe]no)|(?P<task>detyr[ëe]))"
    r"|fund[\s,:.]+(?:(?P<end_note>sh[ëe]nimi)|(?P<end_task>detyr[ëe]s?)))(?!\w)",
    re.IGNORECASE,
)
START_PREFIX = re.compile(r"(?<!\w)mira[\s,:.]*$", re.IGNORECASE)
ASSIGNEE_PREFIX = re.compile(r"^p[ëe]r[\s,:]+", re.IGNORECASE)
TASK_BODY = re.compile(
    r"^(?P<initials>[a-zçë](?:[.\s]+[a-zçë]){1,3}|[a-zçë]{2,5})"
    r"(?:[\s.,:;–—-]+)(?P<title>.+)$",
    re.IGNORECASE | re.DOTALL,
)
MAX_DICTATION_MS = 120_000
MAX_DICTATION_CHARS = 8_000
TASK_LIMIT_PER_TICK = 10


def consume(text, start_ms, end_ms, pending):
    """Read one speaker's chunks and return their next state and complete commands."""
    text = text.strip()
    started = None
    kind = None
    if pending and start_ms - pending["end_ms"] <= 15_000:
        started = pending.get("started")
        if started is None or end_ms - started <= MAX_DICTATION_MS:
            text = f"{pending['text']} {text}"
            kind = pending.get("kind", "note") if started is not None else None
        else:
            started = None

    commands = []
    body_start = 0
    for marker in COMMAND.finditer(text):
        marker_kind = marker.lastgroup
        if marker_kind in ("note", "task") and (kind is None or kind == marker_kind):
            started = start_ms
            kind = marker_kind
            body_start = marker.end()
        elif started is not None and marker_kind == f"end_{kind}":
            body = text[body_start:marker.start()].lstrip(" ,:.-–—\n\t").rstrip()
            if body and len(body) <= MAX_DICTATION_CHARS:
                commands.append((kind, body))
            started = None
            kind = None

    remaining = text[body_start:].lstrip(" ,:.-–—\n\t")
    if started is not None and len(remaining) <= MAX_DICTATION_CHARS:
        return {"started": started, "end_ms": end_ms, "text": remaining, "kind": kind}, commands
    prefix = START_PREFIX.search(text)
    return ({"end_ms": end_ms, "text": prefix.group()} if prefix else None), commands


def task_fields(body):
    match = TASK_BODY.fullmatch(ASSIGNEE_PREFIX.sub("", body, count=1))
    if not match:
        return None
    initials = re.sub(r"[.\s]", "", match["initials"]).upper()
    title = " ".join(match["title"].split()).strip(" .,:;–—-")
    if len(title) >= 2 and any(character.isalnum() for character in title):
        return initials, title
    return None


async def _linked_speaker(db, guild_id, speaker_id):
    return (await db.execute(
        select(User).join(DiscordLink, DiscordLink.user_id == User.id).where(
            DiscordLink.guild_id == guild_id,
            DiscordLink.discord_user_id == speaker_id,
            DiscordLink.enabled.is_(True),
            User.is_active.is_(True),
        )
    )).scalar_one_or_none()


async def _save_note(db, user, source, content):
    if user.department_id is None and user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        return
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
    tasks = list(progress.get("tasks", []))
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
        state, commands = consume(segment.transcript, segment.start_ms, segment.end_ms, state)
        if state:
            pending[segment.speaker_id] = state
        if commands:
            user = await _linked_speaker(db, meeting.guild_id, segment.speaker_id)
            if user is None:
                continue
            for index, (kind, body) in enumerate(commands):
                if kind == "note":
                    await _save_note(db, user, source, body)
                elif fields := task_fields(body):
                    code, title = fields
                    tasks.append({"command": f"{segment.sequence}:{index}", "speaker_id": segment.speaker_id,
                                  "creator_id": str(user.id), "initials": code, "title": title})

    meeting.dictation_progress = {"cursor": cursor, "pending": pending if finished_segments is None else {}}
    if tasks:
        meeting.dictation_progress = {**meeting.dictation_progress, "tasks": tasks}


def _consume_task(meeting):
    progress = dict(meeting.dictation_progress)
    remaining = progress.pop("tasks")[1:]
    if remaining:
        progress["tasks"] = remaining
    meeting.dictation_progress = progress


async def _create_task(db, meeting):
    from app.api.routers.tasks import create_task_in_session
    from app.services.tomorrow_print_report import _initials

    command = meeting.dictation_progress["tasks"][0]
    creator = await _linked_speaker(db, meeting.guild_id, command["speaker_id"])
    assignees = []
    if creator is not None and str(creator.id) == command["creator_id"]:
        users = await db.scalars(select(User).where(User.is_active.is_(True), User.work_staff_filter()))
        assignees = [user for user in users if _initials(user.full_name or "") == command["initials"]]
    if len(assignees) != 1:
        log.info("MIRA task skipped meeting=%s command=%s", meeting.id, command["command"])
        _consume_task(meeting)
        await db.commit()
        return

    assignee = assignees[0]
    payload = TaskCreate(
        title=command["title"], department_id=assignee.department_id, assigned_to=assignee.id, is_1h_report=True,
    )
    # Consume the command in the same commit as the task. A retry after a
    # worker interruption can never create the same task again.
    await create_task_in_session(payload, db, creator, before_commit=lambda _: _consume_task(meeting))


async def process_queued_tasks(sessions):
    """Run task creation outside the recording and note-saving transactions."""
    queue = DiscordVoiceMeeting.dictation_progress.has_key("tasks")
    async with sessions() as db:
        meeting_ids = (await db.scalars(select(DiscordVoiceMeeting.id).where(queue)
            .order_by(DiscordVoiceMeeting.created_at, DiscordVoiceMeeting.id).limit(TASK_LIMIT_PER_TICK))).all()
    for meeting_id in meeting_ids:
        async with sessions() as db:
            query = select(DiscordVoiceMeeting).where(DiscordVoiceMeeting.id == meeting_id, queue).with_for_update(skip_locked=True)
            meeting = await db.scalar(query)
            if meeting is None:
                continue
            command_id = meeting.dictation_progress["tasks"][0]["command"]
            try:
                await _create_task(db, meeting)
            except HTTPException as exc:
                await db.rollback()
                if 400 <= exc.status_code < 500:
                    current = await db.scalar(query)
                    if current is not None and current.dictation_progress["tasks"][0]["command"] == command_id:
                        _consume_task(current)
                        await db.commit()
                log.warning("MIRA task rejected meeting=%s command=%s status=%s", meeting_id, command_id, exc.status_code)
            except Exception as exc:
                log.warning("MIRA task processing failed meeting=%s command=%s error=%s",
                            meeting_id, command_id, type(exc).__name__)
