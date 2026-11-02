"""Explicit generation and authenticated cached downloads; no document editor."""
import uuid
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import quote
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user
from app.api.routers.meeting_recordings import load_recording, audit
from app.config import settings
from app.db import get_db
from app.models.recording_analysis import RecordingAnalysis, RecordingTranscript, RecordingAction
from app.models.recording_protocol import RecordingProtocol
from app.models.meeting import Meeting

router = APIRouter()
Language = Literal['en', 'de']


def protocol_filename(title, downloaded_at, full_name):
    def clean(value):
        value = ''.join(char for char in value if not unicodedata.category(char).startswith('C'))
        return re.sub(r'\s+', ' ', re.sub(r'[<>:"/\\|?*]', '-', value)).strip(' ._-')
    meeting = clean(title or '')[:120].rstrip(' ._-') or 'Takimi'
    initials = ''.join(word[0] for word in re.findall(r'[^\W\d_]+', full_name or '', re.UNICODE)).upper()[:10] or 'USER'
    date = downloaded_at.astimezone(ZoneInfo(settings.APP_TIMEZONE)).strftime('%d.%m.%Y')
    return f'{meeting}_PROTOCOL_{date}_{initials}.docx'


class Start(BaseModel):
    model_config = ConfigDict(extra='forbid')
    language: Language
    regenerate: bool = False


def output(job):
    return {'language': job.language, 'status': job.status, 'error': job.error_message,
        'created_at': job.created_at, 'updated_at': job.updated_at}


@router.get('/{recording_id}/protocols')
async def list_protocols(recording_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    row = await load_recording(db, recording_id, user)
    jobs = (await db.execute(select(RecordingProtocol.language, RecordingProtocol.status,
        RecordingProtocol.error_message, RecordingProtocol.created_at, RecordingProtocol.updated_at)
        .where(RecordingProtocol.recording_id == row.id))).all()
    return {'protocols': [output(job) for job in jobs]}


@router.post('/{recording_id}/protocols', status_code=202)
async def start_protocol(recording_id: uuid.UUID, payload: Start,
        db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    # Recording lock serializes concurrent requests, including a first insert.
    row = await load_recording(db, recording_id, user, lock=True)
    job = await db.get(RecordingProtocol, (row.id, payload.language))
    if job and (job.status in ('QUEUED', 'GENERATING') or
            (job.status == 'READY' and not payload.regenerate)):
        return output(job)
    analysis = await db.get(RecordingAnalysis, row.id)
    if not analysis or analysis.status != 'READY':
        raise HTTPException(409, 'Përfundo transkriptimin dhe përmbledhjen para protokollit.')
    if not settings.RECORDING_ANALYSIS_ENABLED or not settings.OPENAI_API_KEY:
        raise HTTPException(503, 'Shërbimi AI nuk është konfiguruar.')
    if job and not payload.regenerate:
        job.status, job.error_message, job.lease_token, job.lease_until = 'QUEUED', None, None, None
    else:
        segments = (await db.execute(select(RecordingTranscript.text).where(
            RecordingTranscript.recording_id == row.id).order_by(RecordingTranscript.index))).scalars().all()
        transcript = '\n\n'.join(segments)
        if not transcript.strip():
            raise HTTPException(409, 'Transkripti mungon; protokolli nuk mund të verifikohet.')
        actions = (await db.execute(select(RecordingAction).where(RecordingAction.recording_id == row.id))).scalars().all()
        started = row.recording_started_at.astimezone(ZoneInfo(settings.APP_TIMEZONE))
        source = {'title': row.title, 'date': started.date().isoformat(),
            'display_date': started.strftime('%d.%m.%Y'), 'time': started.strftime('%H:%M'),
            'transcript': transcript, 'summary': analysis.summary, 'decisions': analysis.decisions or [],
            'proposed_actions': [{'title': a.title, 'description': a.description, 'evidence': a.evidence,
                'responsible': a.assignee_text, 'deadline': a.deadline_text} for a in actions]}
        if job:
            job.source, job.requested_by = source, user.id
            job.status, job.error_message = 'QUEUED', None
            job.checkpoint, job.content, job.document = None, None, None
            job.lease_token, job.lease_until = None, None
        else:
            job = RecordingProtocol(recording_id=row.id, language=payload.language, requested_by=user.id,
                status='QUEUED', source=source)
            db.add(job)
    audit(db, user, row, 'recording_protocol_requested', language=payload.language, regenerate=payload.regenerate)
    await db.commit()
    await db.refresh(job)
    return output(job)


@router.get('/{recording_id}/protocols/{language}/download')
async def download_protocol(recording_id: uuid.UUID, language: Language,
        db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    row = await load_recording(db, recording_id, user)
    job = await db.get(RecordingProtocol, (row.id, language))
    if not job or job.status != 'READY' or not job.document:
        raise HTTPException(409, 'Protokolli ende nuk është gati për shkarkim.')
    document = job.document
    meeting_title = await db.scalar(select(Meeting.title).where(Meeting.id == row.meeting_id)) if row.meeting_id else None
    filename = protocol_filename(meeting_title or row.title, datetime.now(timezone.utc), user.full_name)
    fallback = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')
    audit(db, user, row, 'recording_protocol_downloaded', language=language)
    await db.commit()
    return Response(document, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        headers={'Content-Disposition': f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename, safe="")}',
            'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})
