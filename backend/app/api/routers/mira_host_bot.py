"""Bridge for Mira Host (the speaking 1H bot). Only the Discord worker calls these."""
import uuid
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


class Caller(BaseModel):
    discord_user_id: str = Field(pattern=r"^\d{1,32}$")


class Enable(Caller):
    until: str | None = Field(default=None, max_length=5)


class Start(BaseModel):
    slot: str = Field(pattern=r"^\d{2}:\d{2}$")


class NextTurn(BaseModel):
    summary: str | None = Field(default=None, max_length=1500)


class Invited(BaseModel):
    turn_id: uuid.UUID


class Lines(BaseModel):
    lines: list[dict] = Field(max_length=200)


class Finish(BaseModel):
    reason: str = Field(default="completed", max_length=100)


class ToolCall(BaseModel):
    arguments: dict = Field(default_factory=dict)


async def manager(db: AsyncSession, caller: Caller):
    user = await host.user_for_discord(db, caller.discord_user_id)
    if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(403, "Vetëm admin ose menaxher mund ta nisë/ndalë Mira-n si mbajtëse takimesh.")
    return user


@router.post('/enable')
async def enable(payload: Enable, db: AsyncSession = Depends(get_db)):
    user = await manager(db, payload)
    if not (settings.MIRA_HOST_ENABLED and settings.MIRA_HOST_BOT_TOKEN):
        raise HTTPException(503, "Mira Host nuk është konfiguruar (MIRA_HOST_ENABLED / MIRA_HOST_BOT_TOKEN).")
    row = await host.get_settings(db, lock=True)
    row.enabled_until, row.enabled_by_user_id = host.enable_until(host.now(), payload.until), user.id
    await db.commit()
    return host.settings_view(row)


@router.post('/disable')
async def disable(payload: Caller, db: AsyncSession = Depends(get_db)):
    await manager(db, payload)
    row = await host.get_settings(db, lock=True)
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
    row = await host.get_settings(db)
    if not host.is_enabled(row):
        raise HTTPException(409, "Mira nuk është nisur si mbajtëse takimesh.")
    meeting = await host.start_meeting(db, payload.slot)
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
            "starts_at": host.slot_at(meeting.meeting_date, meeting.slot).isoformat(),
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
    result = await host.next_turn(db, meeting, payload.summary)
    await db.commit()
    return result


@router.post('/meetings/{meeting_id}/turns/invited')
async def invited(meeting_id: uuid.UUID, payload: Invited, db: AsyncSession = Depends(get_db)):
    meeting = await host.meeting_for(db, meeting_id)
    await host.mark_invited(db, meeting, payload.turn_id)
    await db.commit()
    return {"ok": True}


@router.post('/meetings/{meeting_id}/transcript')
async def transcript(meeting_id: uuid.UUID, payload: Lines, db: AsyncSession = Depends(get_db)):
    meeting = await host.meeting_for(db, meeting_id, lock=True)
    await host.append_transcript(db, meeting, payload.lines)
    await db.commit()
    return {"ok": True}


@router.post('/meetings/{meeting_id}/tools/{name}')
async def tool(meeting_id: uuid.UUID, name: str, payload: ToolCall, db: AsyncSession = Depends(get_db)):
    meeting = await host.meeting_for(db, meeting_id)
    try:
        result = await host.run_tool(db, meeting, name, payload.arguments)
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
