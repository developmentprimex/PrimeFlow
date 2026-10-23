"""Explicit AI processing and reviewed, idempotent creation through existing Tasks."""
import uuid
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user
from app.api.routers.meeting_recordings import load_recording, audit
from app.config import settings
from app.db import get_db
from app.models.recording_analysis import RecordingAnalysis as Analysis, RecordingTranscript as Transcript, RecordingAction as Action
from app.models.user import User
from app.models.department import Department
from app.schemas.task import TaskCreate
from app.models.enums import TaskPriority, TaskFinishPeriod, TaskSkillCategory

router = APIRouter()


class AnalysisStart(BaseModel):
    consent_acknowledged: Literal[True]
    language: Literal['sq', 'en', 'de', 'auto'] = 'sq'


class TaskConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=2, max_length=6000)
    description: str = Field(default='', max_length=5000)
    department_id: uuid.UUID
    assigned_to: uuid.UUID | None = None
    due_date: datetime | None = None
    start_date: datetime | None = None
    assignees: list[uuid.UUID] | None = None
    project_id: uuid.UUID | None = None
    priority: TaskPriority | None = None
    finish_period: TaskFinishPeriod | None = None
    is_deadline_important: bool = False
    is_bllok: bool = False
    is_1h_report: bool = False
    is_r1: bool = False
    is_personal: bool = False
    one_h_report_slot: str | None = Field(default=None, pattern=r'^(10:00|11:00|11:50|14:20|16:00)$')
    one_h_marker: str | None = Field(default=None, pattern=r'^(EXCLAMATION|QUESTION|KA|GENT|FLAG|F|BZ1N1|M2|M3|M2_M3|MONITOR|CLOSE|CLIENT_URGENT|SHARE)$')
    one_h_marker_comment: str | None = Field(default=None, max_length=1000)
    skill_category: TaskSkillCategory | None = None


def available():
    return bool(settings.RECORDING_ANALYSIS_ENABLED and settings.OPENAI_API_KEY)


@router.get('/{recording_id}/analysis')
async def get_analysis(recording_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    row = await load_recording(db, recording_id, user)
    job = await db.get(Analysis, row.id)
    segments = (await db.execute(select(Transcript).where(Transcript.recording_id == row.id).order_by(Transcript.index))).scalars().all() if job else []
    actions = (await db.execute(select(Action).where(Action.recording_id == row.id).order_by(Action.segment_index, Action.id))).scalars().all() if job else []
    if job:
        audit(db, user, row, 'recording_analysis_viewed')
        await db.commit()
    return {'configured': available(), 'can_manage': row.created_by == user.id,
        'timing_configured': bool(settings.RECORDING_TIMING_ENABLED and settings.RECORDING_TIMING_PYTHON),
        'timing': job.timing if job else None,
        'analysis': {**{key: getattr(job, key) for key in ('status', 'language', 'total_segments', 'segments_done', 'summary', 'error_message', 'updated_at')},
            # Analyses from before meeting-level notes kept decisions per segment.
            'decisions': job.decisions if job.decisions is not None else [d for s in segments for d in (s.notes or {}).get('decisions', [])]} if job else None,
        'segments': [{'index': s.index, 'start_seconds': s.start_seconds, 'duration_seconds': s.duration_seconds,
                      'text': s.text} for s in segments],
        'actions': [{key: getattr(a, key) for key in ('id', 'segment_index', 'title', 'description', 'evidence', 'assignee_text', 'deadline_text',
            'suggested_assignee_id', 'suggested_due_date', 'created_task_id', 'confirmed_at')} for a in actions]}


@router.post('/{recording_id}/analysis', status_code=202)
async def start_analysis(recording_id: uuid.UUID, payload: AnalysisStart, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    row = await load_recording(db, recording_id, user, write=True)
    if row.status != 'READY':
        raise HTTPException(409, 'Regjistrimi ende nuk është ruajtur.')
    if not available():
        raise HTTPException(503, 'Transkriptimi kërkon konfigurimin e OPENAI_API_KEY në server.')
    job = await db.get(Analysis, row.id)
    if job and job.status != 'FAILED':
        return {'status': job.status}
    if job:
        if job.language != payload.language:
            raise HTTPException(409, 'Riprovo me gjuhën fillestare që të ruhen pjesët e përpunuara.')
        if job.lease_until and job.lease_until > datetime.now(timezone.utc):
            raise HTTPException(409, 'Përpunimi është ende aktiv.')
        job.status, job.error_message, job.lease_token, job.lease_until, job.attempts = 'QUEUED', None, None, None, 0
    else:
        from app.services.recording_analysis_provider import segment_plan
        job = Analysis(recording_id=row.id, requested_by=user.id, language=payload.language,
            total_segments=len(segment_plan(row.duration_seconds or 0)))
        db.add(job)
    audit(db, user, row, 'recording_analysis_requested', provider='openai', language=payload.language, consent_acknowledged=True)
    await db.commit()
    return {'status': job.status}


@router.post('/{recording_id}/citation-times', status_code=202)
async def request_citation_times(recording_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    row = await load_recording(db, recording_id, user, write=True)
    job = (await db.execute(select(Analysis).where(Analysis.recording_id == row.id).with_for_update())).scalar_one_or_none()
    if row.status != 'READY' or not job or job.status != 'READY':
        raise HTTPException(409, 'Përfundoni transkriptimin para se të kërkoni kohët.')
    # Cached or pending requests never enqueue duplicate work.
    if job.timing and job.timing.get('status') != 'FAILED':
        return {'status': job.timing['status']}
    if not settings.RECORDING_TIMING_ENABLED or not settings.RECORDING_TIMING_PYTHON:
        raise HTTPException(503, 'Gjetja e kohëve nuk është aktivizuar ende.')
    if job.language != 'sq':
        raise HTTPException(422, 'Gjetja e kohëve aktualisht mbështet regjistrimet në shqip.')
    if not (await db.execute(select(Action.id).where(Action.recording_id == row.id).limit(1))).first():
        raise HTTPException(409, 'Nuk ka citime detyrash për t’u kërkuar.')
    job.timing = {**(job.timing or {}), 'status': 'QUEUED', 'error': None,
        'requested_at': datetime.now(timezone.utc).isoformat(), 'requested_by': str(user.id)}
    audit(db, user, row, 'recording_timing_requested')
    await db.commit()
    return {'status': 'QUEUED'}


@router.post('/{recording_id}/actions/{action_id}/task')
async def confirm_task(recording_id: uuid.UUID, action_id: uuid.UUID, payload: TaskConfirmation,
        db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    row = await load_recording(db, recording_id, user, write=True)
    proposal = (await db.execute(select(Action).where(Action.id == action_id, Action.recording_id == row.id).with_for_update())).scalar_one_or_none()
    if not proposal:
        raise HTTPException(404, 'Propozimi nuk u gjet.')
    if proposal.confirmed_at:
        if not proposal.created_task_id:
            raise HTTPException(409, 'Detyra e konfirmuar është fshirë. Krijoje manualisht në Tasks.')
        return {'task_id': proposal.created_task_id, 'duplicate': True}
    if not await db.get(Department, payload.department_id):
        raise HTTPException(422, 'Departamenti nuk u gjet.')
    for assignee_id in set([*(payload.assignees or []), *([payload.assigned_to] if payload.assigned_to else [])]):
        assignee = await db.get(User, assignee_id)
        if assignee is None or not assignee.is_active:
            raise HTTPException(422, 'Zgjidhni një përdorues aktiv.')
    if payload.due_date and payload.due_date.tzinfo is None:
        raise HTTPException(422, 'Afati duhet të përmbajë zonën kohore.')
    if payload.start_date and payload.start_date.tzinfo is None:
        raise HTTPException(422, 'Data e fillimit duhet të përmbajë zonën kohore.')
    if len(payload.title.strip()) < 2:
        raise HTTPException(422, 'Titulli duhet të ketë të paktën dy shkronja.')
    # Only owner-reviewed task fields are accepted. Privileged origins remain
    # unavailable; existing Tasks validates permissions and business rules.
    from app.api.routers.tasks import create_task_in_session
    from app.services.recording_task_notes import create_recording_note
    title_lines = payload.title.strip().replace('\r\n', '\n').split('\n')
    title_lines[0] = title_lines[0].upper()
    title = '\n'.join(title_lines)
    note = await create_recording_note(db, proposal.id, payload, user, title)
    def attach(task):
        note.content = task.title
        proposal.created_task_id, proposal.confirmed_by = task.id, user.id
        proposal.confirmed_at = datetime.now(timezone.utc)
        audit(db, user, row, 'recording_task_confirmed', action_id=str(proposal.id), task_id=str(task.id))
    result = await create_task_in_session(TaskCreate(**payload.model_dump(exclude={'description', 'title'}),
        title=title, description=payload.description.strip() or None, ga_note_origin_id=note.id), db, user, before_commit=attach)
    return {'task_id': result.id, 'ga_note_id': note.id, 'duplicate': False}
