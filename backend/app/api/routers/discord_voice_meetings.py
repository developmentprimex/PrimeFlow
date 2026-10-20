import uuid
from fastapi import APIRouter, Depends, File, Form, UploadFile, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.api.routers.discord_assistant import require_bot
from app.schemas.discord_voice_meeting import VoiceActor, VoiceStart, Worker, Finish, Interrupt, SegmentMeta, DeliveryAck
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

@router.post('/{session_id}/segments')
async def segment(session_id: uuid.UUID, capture_token: str = Form(...), instance_id: uuid.UUID = Form(...),
    sequence: int = Form(...), speaker_id: str = Form(...), speaker_name: str = Form(...),
    start_ms: int = Form(...), end_ms: int = Form(...), file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    from pydantic import ValidationError
    try:
        payload=SegmentMeta(capture_token=capture_token,instance_id=instance_id,sequence=sequence,
            speaker_id=speaker_id,speaker_name=speaker_name,start_ms=start_ms,end_ms=end_ms)
    except ValidationError:
        raise HTTPException(422,'Të dhënat e segmentit nuk janë të vlefshme.') from None
    await service.worker_row(db,session_id,payload)
    await db.rollback()
    data=bytearray()
    try:
        while chunk:=await file.read(65536):
            data.extend(chunk)
            if len(data)>2_000_000:raise HTTPException(413,'Segmenti është shumë i madh.')
    finally:await file.close()
    try:return await service.receive_segment(db,session_id,payload,bytes(data))
    except ValueError:raise HTTPException(422,'Audioja nuk është WAV i vlefshëm.') from None

@router.post('/delivery/claim')
async def claim(db: AsyncSession = Depends(get_db)):
    return await service.claim_deliveries(db)

@router.post('/{session_id}/delivery/ack')
async def ack(session_id: uuid.UUID, payload: DeliveryAck, db: AsyncSession = Depends(get_db)):
    return await service.ack_delivery(db,session_id,payload)
