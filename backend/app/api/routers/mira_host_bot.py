"""Bridge for Mira Host (the speaking 1H bot). Only the Discord worker calls these."""
import uuid
from typing import Literal
from datetime import date
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.routers.discord_assistant import require_bot
from app.config import settings
from app.db import get_db
from app.models.enums import UserRole
from app.services import mira_host as host

router = APIRouter(dependencies=[Depends(require_bot)])


class CommandContext(BaseModel):
    guild_id: str | None = Field(default=None, pattern=r"^\d{1,32}$")
    channel_id: str | None = Field(default=None, pattern=r"^\d{1,32}$")


class Caller(CommandContext):
    discord_user_id: str = Field(pattern=r"^\d{1,32}$")


class Enable(Caller):
    until: str | None = Field(default=None, max_length=5)


class Stop(Caller):
    test_only: bool = False


class Start(CommandContext):
    slot: str = Field(pattern=r"^\d{2}:\d{2}$")
    # Present only for an explicit slash command, never for a scheduled start.
    discord_user_id: str | None = Field(default=None, pattern=r"^\d{1,32}$")
    test_mode: bool = False
    test_meeting_id: uuid.UUID | None = None


class NextTurn(BaseModel):
    summary: str | None = Field(default=None, max_length=1500)
    expected_turn_id: uuid.UUID | None = None
    outcome: str = Field(default="DONE", pattern="^(DONE|DEFERRED|TIMEOUT)$")
    available_user_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)


class Invited(BaseModel):
    turn_id: uuid.UUID


class Metric(BaseModel):
    id: uuid.UUID
    kind: Literal['generated_audio', 'tool']
    duration_ms: float = Field(ge=0, le=180000, allow_inf_nan=False)
    tool: str | None = Field(default=None, max_length=80)


class Lines(BaseModel):
    lines: list[dict] = Field(max_length=200)
    metrics: list[Metric] = Field(default_factory=list, max_length=200)


class Finish(BaseModel):
    reason: str = Field(default="completed", max_length=100)


class ProgressAck(BaseModel):
    token: uuid.UUID


class ProposalAck(ProgressAck):
    played_at: str = Field(max_length=50)


class ToolCall(BaseModel):
    arguments: dict = Field(default_factory=dict)
    speaker_id: str | None = Field(default=None, pattern=r"^\d{1,32}$")
    speech_id: str | None = Field(default=None, max_length=200)
    speech_text: str | None = Field(default=None, max_length=4000)
    speech_started_at: str | None = Field(default=None, max_length=50)


async def manager(db: AsyncSession, caller: Caller):
    user = await host.user_for_discord(db, caller.discord_user_id)
    if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(403, "Vetëm admin ose menaxher mund ta nisë/ndalë Mira-n si mbajtëse takimesh.")
    return user


async def command_user(db: AsyncSession, caller: Caller):
    if caller.guild_id is not None or caller.channel_id is not None:
        if (caller.guild_id == settings.DISCORD_GUILD_ID and settings.DISCORD_MEETING_CONTROL_CHANNEL_ID
                and caller.channel_id == settings.DISCORD_MEETING_CONTROL_CHANNEL_ID):
            from app.services.discord_meeting_control import control_identity
            from app.schemas.discord_voice_meeting import VoiceActor
            _, user = await control_identity(db, VoiceActor(discord_user_id=caller.discord_user_id,
                guild_id=caller.guild_id, channel_id=caller.channel_id))
            return user
        if caller.guild_id != settings.DISCORD_GUILD_ID:
            raise HTTPException(403, 'Përdor serverin Discord të PrimeFlow.')
    return await manager(db, caller)


@router.post('/enable')
async def enable(payload: Enable, db: AsyncSession = Depends(get_db)):
    user = await command_user(db, payload)
    if not (settings.MIRA_HOST_ENABLED and settings.MIRA_HOST_BOT_TOKEN
            and (settings.MIRA_HOST_OPENAI_API_KEY or '').strip()):
        raise HTTPException(503, "Mira Host nuk është konfiguruar (MIRA_HOST_ENABLED / MIRA_HOST_BOT_TOKEN / MIRA_HOST_OPENAI_API_KEY).")
    row = await host.get_settings(db, lock=True)
    row.enabled_until, row.enabled_by_user_id = host.enable_until(host.now(), payload.until), user.id
    await db.commit()
    return host.settings_view(row)


@router.post('/authorize')
async def authorize(payload: Caller, db: AsyncSession = Depends(get_db)):
    """Authorize a manual takeover before interrupting a rehearsal."""
    await command_user(db, payload)
    return {"ok": True}


@router.post('/disable')
async def disable(payload: Stop, db: AsyncSession = Depends(get_db)):
    await command_user(db, payload)
    row = await host.get_settings(db, lock=True)
    if not getattr(payload, 'test_only', False):
        row.enabled_until = None
    await db.commit()
    return host.settings_view(row)


@router.post('/status')
async def status(db: AsyncSession = Depends(get_db)):
    result = await host.live_status(db)
    await db.commit()
    return result


@router.post('/tick')
async def tick(db: AsyncSession = Depends(get_db)):
    return await host.tick(db)


@router.post('/session/start')
async def start(payload: Start, db: AsyncSession = Depends(get_db)):
    if payload.test_mode and not payload.discord_user_id:
        raise HTTPException(422, "Test mode niset vetëm me komandën manuale /mira hyr.")
    if payload.test_meeting_id and not payload.test_mode:
        raise HTTPException(422, "Vetëm testet mund të ripërdorin ID të testimit.")
    if payload.discord_user_id:
        await command_user(db, Caller(discord_user_id=payload.discord_user_id,
            guild_id=payload.guild_id, channel_id=payload.channel_id))
        if not (settings.MIRA_HOST_ENABLED and settings.MIRA_HOST_BOT_TOKEN):
            raise HTTPException(503, "Mira Host nuk është konfiguruar në server.")
    row = await host.get_settings(db)
    if not payload.discord_user_id and not host.is_enabled(row):
        raise HTTPException(409, "Mira nuk është nisur si mbajtëse takimesh.")
    if not (settings.MIRA_HOST_OPENAI_API_KEY or '').strip():
        raise HTTPException(503, "MIRA_HOST_OPENAI_API_KEY mungon.")
    extra = {'test_meeting_id': payload.test_meeting_id} if payload.test_meeting_id else {}
    meeting = await host.start_meeting(db, payload.slot, test_mode=payload.test_mode, **extra)
    await db.commit()
    try:
        session = await host.realtime_session(db, meeting)
    except HTTPException as exc:
        # The meeting never started; it must not stay "live" in the Mira view.
        await host.finish_meeting(db, meeting, f"realtime:{exc.detail}")
        await db.commit()
        raise
    await db.commit()
    return {"meeting": host.meeting_row(meeting), **session,
            "starts_at": (host.now() if payload.discord_user_id else
                          host.slot_at(meeting.meeting_date, meeting.slot)).isoformat(),
            "target_minutes": row.target_minutes_per_person}


@router.post('/meetings/{meeting_id}/staff')
async def staff(meeting_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    meeting = await host.meeting_for(db, meeting_id, lock=True)
    turns = await host.begin_staff(db, meeting)
    await db.commit()
    return {"turns": turns}


@router.post('/meetings/{meeting_id}/turns/next')
async def next_turn(meeting_id: uuid.UUID, payload: NextTurn, db: AsyncSession = Depends(get_db)):
    meeting = await host.meeting_for(db, meeting_id, lock=True)
    result = await host.next_turn(db, meeting, payload.summary, expected_turn_id=payload.expected_turn_id,
                                 outcome=payload.outcome, available_user_ids=payload.available_user_ids)
    await db.commit()
    return result


@router.post('/meetings/{meeting_id}/turns/invited')
async def invited(meeting_id: uuid.UUID, payload: Invited, db: AsyncSession = Depends(get_db)):
    meeting = await host.meeting_for(db, meeting_id)
    await host.mark_invited(db, meeting, payload.turn_id)
    await db.commit()
    return {"ok": True}


@router.post('/meetings/{meeting_id}/turns/current')
async def current_turn(meeting_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    meeting = await host.meeting_for(db, meeting_id, lock=True)
    result = await host.current_turn_state(db, meeting)
    await db.commit()
    return result


@router.post('/meetings/{meeting_id}/transcript')
async def transcript(meeting_id: uuid.UUID, payload: Lines, db: AsyncSession = Depends(get_db)):
    meeting = await host.meeting_for(db, meeting_id, lock=True)
    await host.append_transcript(db, meeting, payload.lines)
    await host.append_metrics(db, meeting, [item.model_dump(mode='json') for item in payload.metrics])
    await db.commit()
    return {"ok": True}


@router.post('/meetings/{meeting_id}/tools/{name}')
async def tool(meeting_id: uuid.UUID, name: str, payload: ToolCall, db: AsyncSession = Depends(get_db)):
    meeting = await host.meeting_for(db, meeting_id, lock=True)
    try:
        result = await host.run_tool(db, meeting, name, payload.arguments, speaker_id=payload.speaker_id, speech_id=payload.speech_id,
                                     speech_text=payload.speech_text, speech_started_at=payload.speech_started_at)
    except ValidationError:
        result = {"error": "Argumentet nuk janë të vlefshme."}
    await db.commit()
    return result


@router.post('/meetings/{meeting_id}/finish')
async def finish(meeting_id: uuid.UUID, payload: Finish, background: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    meeting = await host.meeting_for(db, meeting_id, lock=True)
    if meeting.status not in ("DONE", "ABORTED"):
        await host.finish_meeting(db, meeting, payload.reason)
    await db.commit()
    if meeting.summary_status == "PENDING":
        background.add_task(host.summarize, meeting.id)
    return host.meeting_row(meeting)


@router.post('/meetings/{meeting_id}/progress/ack')
async def progress_ack(meeting_id: uuid.UUID, payload: ProgressAck, db: AsyncSession = Depends(get_db)):
    meeting = await host.meeting_for(db, meeting_id, lock=True)
    result = await host.acknowledge_progress(db, meeting, payload.token)
    await db.commit()
    return result


@router.post('/meetings/{meeting_id}/proposal/ack')
async def proposal_ack(meeting_id: uuid.UUID, payload: ProposalAck, db: AsyncSession = Depends(get_db)):
    meeting = await host.meeting_for(db, meeting_id, lock=True)
    result = await host.acknowledge_proposal(db, meeting, payload.token, payload.played_at)
    await db.commit()
    return result
