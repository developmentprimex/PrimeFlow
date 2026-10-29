"""Signed-in desktop companion API. No Discord identity or bot token accepted."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.schemas.mira_desktop import DesktopStart, DesktopFinish
from app.services import mira_desktop as service

router = APIRouter()


@router.get('/capabilities')
async def capabilities(user=Depends(get_current_user)):
    return dict(enabled=bool((settings.MIRA_NOTES_OPENAI_API_KEY or '').strip()), user_id=str(user.id),
        max_segment_seconds=10, max_duration_seconds=14400, frontend_url=settings.FRONTEND_URL)


@router.post('/sessions')
async def create(payload: DesktopStart, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return await service.create_session(db, user, payload)


@router.get('/sessions/{session_id}')
async def get(session_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return await service.get_session(db, user, session_id)


@router.post('/sessions/{session_id}/segments/{sequence}')
async def upload(session_id: uuid.UUID, sequence: int, request: Request,
        start_ms: int = Query(ge=0, le=14_400_000),
        end_ms: int = Query(ge=0, le=14_400_000),
        db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'audio/wav':
        raise HTTPException(415, 'audio_wav_required')
    # Bound streaming bodies too; do not trust Content-Length.
    data = bytearray()
    async for part in request.stream():
        if len(data)+len(part) > service.MAX_AUDIO_BYTES:
            raise HTTPException(413, 'invalid_audio_size')
        data.extend(part)
    return await service.upload_segment(db, user, session_id, sequence, start_ms, end_ms, bytes(data))


@router.post('/sessions/{session_id}/finish')
async def finish(session_id: uuid.UUID, payload: DesktopFinish, db: AsyncSession = Depends(get_db),
        user=Depends(get_current_user)):
    return await service.finish_session(db, user, session_id, payload)
