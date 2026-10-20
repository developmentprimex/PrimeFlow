import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.api.routers.discord_assistant import require_bot
from app.schemas.discord_voice_meeting import VoiceActor, VoiceStart, Worker, Finish, Interrupt
from app.services import discord_voice_meetings as service

router = APIRouter(dependencies=[Depends(require_bot)])

@router.post('/start')
async def start(payload: VoiceStart, db: AsyncSession = Depends(get_db)):
    return await service.start_session(db, payload)

@router.post('/{session_id}/detail')
async def detail(session_id: uuid.UUID, payload: VoiceActor, db: AsyncSession = Depends(get_db)):
    row, _ = await service.authorize_session(db, payload, session_id, operation='read')
    return service.view(row)

@router.post('/{session_id}/authorize-stop')
async def authorize_stop(session_id: uuid.UUID, payload: VoiceActor, db: AsyncSession = Depends(get_db)):
    return await service.authorize_stop(db, payload, session_id)

@router.post('/{session_id}/listening')
async def listening(session_id: uuid.UUID, payload: Worker, db: AsyncSession = Depends(get_db)):
    return await service.transition_session(db, session_id, payload, 'LISTENING')

@router.post('/{session_id}/heartbeat')
async def heartbeat(session_id: uuid.UUID, payload: Worker, db: AsyncSession = Depends(get_db)):
    return await service.transition_session(db, session_id, payload, 'HEARTBEAT')

@router.post('/{session_id}/interrupt')
async def interrupt(session_id: uuid.UUID, payload: Interrupt, db: AsyncSession = Depends(get_db)):
    return await service.transition_session(db, session_id, payload, 'INTERRUPTED')

@router.post('/{session_id}/finish')
async def finish(session_id: uuid.UUID, payload: Finish, db: AsyncSession = Depends(get_db)):
    return await service.finish_session(db, session_id, payload)

@router.post('/{session_id}/save')
async def save(session_id: uuid.UUID, payload: VoiceActor, db: AsyncSession = Depends(get_db)):
    return await service.save_notes(db, payload, session_id)
