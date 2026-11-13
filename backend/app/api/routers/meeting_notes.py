"""Takimet: notes, questions and decisions per meeting session.

Notes stay with their meeting until a user sends them to PX Notes (alone or
merged). Tasks are then created from that PX note with the existing workflow,
while meeting-note statuses are maintained manually and independently.
"""
from __future__ import annotations

import shutil
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.routers.meeting_recordings import load_recording
from app.config import settings
from app.db import get_db
from app.models.ga_note_attachment import GaNoteAttachment
from app.models.meeting import Meeting
from app.models.meeting_client import MeetingClient
from app.models.meeting_note import MeetingNote, MeetingNoteAttachment
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.models.meeting_recording import MeetingRecording
from app.models.project import Project
from app.models.recording_analysis import RecordingAction, RecordingAnalysis
from app.models.task import Task
from app.schemas.ga_note import GaNoteCreate
from app.schemas.meeting import MeetingClientIdentification, MeetingClientCreate, MeetingClientOut
from app.services.meeting_clients import resolve_meeting_client
from app.services.ga_note_creation import build_ga_note
from app.services.meeting_occurrence import meeting_occurs_on_date
from app.services.meeting_participants import manual_participant_ids, meeting_to_out
from app.services.microsoft_calendar_sync import is_common_view_visible_meeting

router = APIRouter()

NOTE_KINDS = ("NOTE", "QUESTION")


# ---------------------------------------------------------------- schemas

class MeetingNoteAttachmentOut(BaseModel):
    id: uuid.UUID
    original_filename: str
    content_type: str | None = None
    size_bytes: int
    created_at: datetime


class MeetingNoteOut(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    occurrence_date: date
    kind: str
    reference: str | None = None
    content: str
    answer: str | None = None
    source: str
    recording_id: uuid.UUID | None = None
    recording_action_id: uuid.UUID | None = None
    recording_seconds: float | None = None
    assignee_user_id: uuid.UUID | None = None
    due_date: date | None = None
    ga_note_id: uuid.UUID | None = None
    is_closed: bool = False
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    attachments: list[MeetingNoteAttachmentOut] = []
    # Read from the tasks created in PX Notes from the linked PX note.
    task_status: str | None = None
    manual_status: str = "TODO"
    task_ids: list[uuid.UUID] = []


class MeetingNoteCreate(BaseModel):
    occurrence_date: date
    content: str = Field(min_length=1, max_length=10000)
    kind: Literal["NOTE", "QUESTION"] = "NOTE"
    reference: str | None = Field(default=None, max_length=200)
    answer: str | None = Field(default=None, max_length=10000)
    assignee_user_id: uuid.UUID | None = None
    due_date: date | None = None


class MeetingNoteUpdate(BaseModel):
    manual_status: Literal["TODO", "IN_PROGRESS", "WAITING_CLIENT", "WAITING_CONFIRMATION", "DONE"] = "TODO"
    content: str | None = Field(default=None, min_length=1, max_length=10000)
    kind: Literal["NOTE", "QUESTION"] | None = None
    reference: str | None = Field(default=None, max_length=200)
    answer: str | None = Field(default=None, max_length=10000)
    assignee_user_id: uuid.UUID | None = None
    due_date: date | None = None
    is_closed: bool | None = None


class SendToPxIn(BaseModel):
    note_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    merge: bool = False


class TrainingIn(BaseModel):
    is_training: bool


class DismissIn(BaseModel):
    dismissed: bool = True


# ---------------------------------------------------------------- helpers

def _tz() -> ZoneInfo:
    return ZoneInfo(settings.APP_TIMEZONE)


def _today() -> date:
    return datetime.now(_tz()).date()


def _local_date(value: datetime | None) -> date | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(_tz()).date()


def _upload_dir() -> Path:
    base = Path(settings.MEETING_NOTES_UPLOAD_DIR)
    if not base.is_absolute():
        base = Path(__file__).resolve().parents[3] / base
    return base


def _ga_upload_dir() -> Path:
    base = Path(settings.GA_NOTES_UPLOAD_DIR)
    if not base.is_absolute():
        base = Path(__file__).resolve().parents[3] / base
    return base


def aggregate_task_status(statuses: list[str]) -> str | None:
    """Mirror PX Notes' aggregateTaskStatus so both views show the same colour."""
    values = [str(getattr(s, "value", s) or "TODO").upper() for s in statuses]
    values = [v if v in ("TODO", "IN_PROGRESS", "WAITING_CLIENT", "WAITING_CONFIRMATION", "DONE") else "TODO" for v in values]
    if not values:
        return None
    if all(v == "DONE" for v in values):
        return "DONE"
    if all(v == "WAITING_CONFIRMATION" for v in values):
        return "WAITING_CONFIRMATION"
    if all(v == "WAITING_CLIENT" for v in values):
        return "WAITING_CLIENT"
    if any(v == "IN_PROGRESS" for v in values):
        return "IN_PROGRESS"
    any_waiting = any(v in ("WAITING_CONFIRMATION", "WAITING_CLIENT") for v in values)
    any_todo = any(v == "TODO" for v in values)
    if any_waiting and any_todo:
        return "IN_PROGRESS"
    if any_waiting:
        return "WAITING_CONFIRMATION"
    if any(v == "DONE" for v in values):
        return "IN_PROGRESS"
    return "TODO"


async def _task_map(db: AsyncSession, ga_note_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str | None, list[uuid.UUID]]]:
    ids = [i for i in set(ga_note_ids) if i is not None]
    if not ids:
        return {}
    rows = (await db.execute(
        select(Task.id, Task.ga_note_origin_id, Task.status).where(
            Task.ga_note_origin_id.in_(ids), Task.is_active.is_(True)
        )
    )).all()
    grouped: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = defaultdict(list)
    for task_id, note_id, task_status in rows:
        grouped[note_id].append((task_id, task_status))
    return {
        note_id: (aggregate_task_status([s for _, s in items]), [t for t, _ in items])
        for note_id, items in grouped.items()
    }


def _note_out(note: MeetingNote, tasks: dict) -> MeetingNoteOut:
    task_status, task_ids = tasks.get(note.ga_note_id, (None, [])) if note.ga_note_id else (None, [])
    return MeetingNoteOut(
        id=note.id,
        meeting_id=note.meeting_id,
        occurrence_date=note.occurrence_date,
        kind=note.kind,
        reference=note.reference,
        content=note.content,
        answer=note.answer,
        source=note.source,
        recording_id=note.recording_id,
        recording_action_id=note.recording_action_id,
        recording_seconds=note.recording_seconds,
        assignee_user_id=note.assignee_user_id,
        due_date=note.due_date,
        ga_note_id=note.ga_note_id,
        is_closed=bool(note.is_closed),
        created_by=note.created_by,
        created_at=note.created_at,
        updated_at=note.updated_at,
        attachments=[
            MeetingNoteAttachmentOut(
                id=a.id, original_filename=a.original_filename, content_type=a.content_type,
                size_bytes=a.size_bytes, created_at=a.created_at,
            )
            for a in (note.attachments or [])
        ],
        task_status=task_status,
        manual_status=note.manual_status,
        task_ids=task_ids,
    )


async def _notes_out(db: AsyncSession, notes: list[MeetingNote]) -> list[MeetingNoteOut]:
    tasks = await _task_map(db, [n.ga_note_id for n in notes if n.ga_note_id])
    return [_note_out(n, tasks) for n in notes]


def _is_open(note: MeetingNote, tasks: dict) -> bool:
    return not note.is_closed and note.manual_status != "DONE"


async def _get_meeting(db: AsyncSession, meeting_id: uuid.UUID) -> Meeting:
    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Takimi nuk u gjet.")
    return meeting


async def _get_note(db: AsyncSession, note_id: uuid.UUID) -> MeetingNote:
    note = await db.get(MeetingNote, note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shënimi nuk u gjet.")
    return note


def _occurrences(meeting: Meeting, start: date, end: date) -> list[date]:
    tz = _tz()
    days = []
    current = start
    while current <= end:
        if meeting_occurs_on_date(meeting, current, local_timezone=tz):
            days.append(current)
        current += timedelta(days=1)
    return days


def _is_recurring(meeting: Meeting) -> bool:
    return str(meeting.recurrence_type or "").lower() in ("weekly", "monthly", "yearly")


def _meeting_kind(meeting: Meeting) -> str:
    if getattr(meeting, "is_training", False):
        return "TRAINING"
    return "INTERNAL" if meeting.meeting_type == "internal" else "EXTERNAL"


def _visible_meeting_filter():
    return or_(
        Meeting.calendar_sync_status.is_(None),
        Meeting.calendar_sync_status.notin_(("excluded", "out_of_window")),
    )


async def _save_attachments(db: AsyncSession, note: MeetingNote, files: list[UploadFile], user) -> list[MeetingNoteAttachment]:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nuk u ngarkua asnjë skedar.")
    if len(files) > settings.GA_NOTES_MAX_FILES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Maksimumi {settings.GA_NOTES_MAX_FILES} skedarë.")
    max_bytes = settings.GA_NOTES_MAX_FILE_MB * 1024 * 1024
    note_dir = _upload_dir() / str(note.id)
    note_dir.mkdir(parents=True, exist_ok=True)
    created: list[MeetingNoteAttachment] = []
    stored: list[Path] = []
    try:
        for upload in files:
            attachment_id = uuid.uuid4()
            original = (upload.filename or "screenshot.png").strip() or "screenshot.png"
            stored_name = f"{attachment_id}{Path(original).suffix}"
            path = note_dir / stored_name
            size = 0
            with path.open("wb") as buffer:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Skedari është më i madh se {settings.GA_NOTES_MAX_FILE_MB}MB.")
                    buffer.write(chunk)
            stored.append(path)
            attachment = MeetingNoteAttachment(
                id=attachment_id, note_id=note.id, original_filename=original, stored_filename=stored_name,
                content_type=upload.content_type, size_bytes=size, created_by=user.id,
            )
            db.add(attachment)
            created.append(attachment)
            await upload.close()
        await db.flush()
    except Exception:
        for path in stored:
            path.unlink(missing_ok=True)
        raise
    return created


async def _reload(db: AsyncSession, note_id: uuid.UUID) -> MeetingNote:
    db.expire_all()
    return (await db.execute(select(MeetingNote).where(MeetingNote.id == note_id))).scalar_one()


# ---------------------------------------------------------------- meetings

@router.get("/clients", response_model=list[MeetingClientOut])
async def list_clients(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    return (await db.execute(select(MeetingClient).order_by(MeetingClient.name_key))).scalars().all()


@router.post("/clients", response_model=MeetingClientOut)
async def create_client(payload: MeetingClientCreate, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    client = await resolve_meeting_client(db, client_name=payload.name, actor_id=user.id)
    await db.commit()
    return client

@router.get("/overview")
async def meetings_overview(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """Meetings for the Takimet list with next session and task counts."""
    today = _today()
    recent = datetime.now(timezone.utc) - timedelta(days=45)
    with_notes = select(MeetingNote.meeting_id).distinct()
    stmt = select(Meeting).where(_visible_meeting_filter()).where(
        or_(
            Meeting.recurrence_type.in_(("weekly", "monthly", "yearly")),
            Meeting.starts_at >= recent,
            Meeting.id.in_(with_notes),
        )
    )
    meetings = [m for m in (await db.execute(stmt)).scalars().all() if is_common_view_visible_meeting(m)]
    ids = [m.id for m in meetings]
    notes = (await db.execute(
        select(MeetingNote).where(MeetingNote.meeting_id.in_(ids))
    )).scalars().all() if ids else []
    tasks = await _task_map(db, [n.ga_note_id for n in notes if n.ga_note_id])
    counts: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: {"open_notes": 0, "TODO": 0, "IN_PROGRESS": 0, "WAITING": 0, "DONE": 0})
    for note in notes:
        c = counts[note.meeting_id]
        task_status = note.manual_status
        if _is_open(note, tasks):
            c["open_notes"] += 1
        if task_status in ("WAITING_CLIENT", "WAITING_CONFIRMATION"):
            c["WAITING"] += 1
        else:
            c[task_status] += 1
    participants = await manual_participant_ids(db, ids)
    out = []
    for meeting in meetings:
        if _is_recurring(meeting):
            past = _occurrences(meeting, today - timedelta(days=62), today)
            future = _occurrences(meeting, today, today + timedelta(days=62))
            last = past[-1] if past else None
            nxt = future[0] if future else None
        else:
            day = _local_date(meeting.starts_at) or _local_date(meeting.created_at)
            last = day if day and day <= today else None
            nxt = day if day and day >= today else None
        out.append({
            "meeting": meeting_to_out(meeting, participant_ids=participants.get(meeting.id, [])).model_dump(mode="json"),
            "kind": _meeting_kind(meeting),
            "last_session": last,
            "next_session": nxt,
            "counts": counts[meeting.id],
        })
    out.sort(key=lambda row: (row["next_session"] is None, row["next_session"] or date.max, row["meeting"]["title"].lower()))
    return out


@router.get("/meetings/{meeting_id}")
async def meeting_detail(meeting_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """Meeting with its sessions (recent + next), session statuses and recordings."""
    meeting = await _get_meeting(db, meeting_id)
    today = _today()
    if _is_recurring(meeting):
        window = 400 if str(meeting.recurrence_type).lower() != "weekly" else 120
        past = _occurrences(meeting, today - timedelta(days=window), today)[-10:]
        future = _occurrences(meeting, today + timedelta(days=1), today + timedelta(days=62))[:1]
        days = set(past + future)
    else:
        day = _local_date(meeting.starts_at) or _local_date(meeting.created_at)
        days = {day} if day else set()
    note_days = (await db.execute(
        select(MeetingNote.occurrence_date).where(MeetingNote.meeting_id == meeting.id).distinct()
    )).scalars().all()
    days.update(note_days)
    statuses = {
        row.occurrence_date: row.status
        for row in (await db.execute(
            select(MeetingOccurrenceStatus).where(MeetingOccurrenceStatus.meeting_id == meeting.id)
        )).scalars().all()
    }
    recordings = (await db.execute(
        select(MeetingRecording).where(
            MeetingRecording.meeting_id == meeting.id, MeetingRecording.deleted_at.is_(None)
        ).order_by(MeetingRecording.recording_started_at.desc())
    )).scalars().all()
    rec_by_day: dict[date, list[dict]] = defaultdict(list)
    for rec in recordings:
        day = _local_date(rec.recording_started_at)
        if day is None:
            continue
        days.add(day)
        rec_by_day[day].append({"id": rec.id, "title": rec.title, "status": rec.status, "duration_seconds": rec.duration_seconds})
    sessions = [
        {"date": day, "status": statuses.get(day) or ("planned" if day > today else None),
         "is_today": day == today, "recordings": rec_by_day.get(day, [])}
        for day in sorted(d for d in days if d)
    ]
    participants = await manual_participant_ids(db, [meeting.id])
    project = await db.get(Project, meeting.project_id) if meeting.project_id else None
    return {
        "meeting": meeting_to_out(meeting, participant_ids=participants.get(meeting.id, [])).model_dump(mode="json"),
        "kind": _meeting_kind(meeting),
        "project": {"id": project.id, "title": getattr(project, "title", None) or getattr(project, "name", None)} if project else None,
        "sessions": sessions,
        "today": today,
    }


@router.patch("/meetings/{meeting_id}/training")
async def set_training(meeting_id: uuid.UUID, payload: TrainingIn, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    meeting = await _get_meeting(db, meeting_id)
    meeting.is_training = payload.is_training
    await db.commit()
    return {"id": meeting.id, "is_training": meeting.is_training}


@router.patch("/meetings/{meeting_id}/client")
async def set_client_identification(
    meeting_id: uuid.UUID,
    payload: MeetingClientIdentification,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Any authenticated user can edit this local identification, like meeting notes."""
    meeting = await _get_meeting(db, meeting_id)
    client = await resolve_meeting_client(db, client_id=payload.client_id, client_name=payload.client_name, actor_id=user.id)
    meeting.client_id = client.id if client else None
    meeting.client_name = client.name if client else None
    await db.commit()
    return {"id": meeting.id, "client_id": meeting.client_id, "client_name": meeting.client_name}


# ---------------------------------------------------------------- notes

@router.get("/meetings/{meeting_id}/notes", response_model=list[MeetingNoteOut])
async def list_notes(
    meeting_id: uuid.UUID,
    session: date | None = None,
    scope: Literal["session", "all"] = "session",
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Session scope: that session's notes plus earlier ones still open
    (a cancelled session's open notes therefore continue in the next one)."""
    await _get_meeting(db, meeting_id)
    stmt = select(MeetingNote).where(MeetingNote.meeting_id == meeting_id)
    if scope == "session" and session is not None:
        stmt = stmt.where(MeetingNote.occurrence_date <= session)
    notes = (await db.execute(stmt.order_by(MeetingNote.occurrence_date.desc(), MeetingNote.position, MeetingNote.created_at))).scalars().all()
    tasks = await _task_map(db, [n.ga_note_id for n in notes if n.ga_note_id])
    if scope == "session" and session is not None:
        notes = [n for n in notes if n.occurrence_date == session or _is_open(n, tasks)]
    return [_note_out(n, tasks) for n in notes]


@router.post("/meetings/{meeting_id}/notes", response_model=MeetingNoteOut, status_code=status.HTTP_201_CREATED)
async def create_note(meeting_id: uuid.UUID, payload: MeetingNoteCreate, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    await _get_meeting(db, meeting_id)
    note = MeetingNote(
        meeting_id=meeting_id, occurrence_date=payload.occurrence_date, kind=payload.kind,
        reference=(payload.reference or "").strip() or None, content=payload.content.strip(),
        answer=(payload.answer or "").strip() or None, source="MANUAL",
        assignee_user_id=payload.assignee_user_id, due_date=payload.due_date, created_by=user.id,
    )
    db.add(note)
    await db.commit()
    note = await _reload(db, note.id)
    return (await _notes_out(db, [note]))[0]


@router.patch("/{note_id}", response_model=MeetingNoteOut)
async def update_note(note_id: uuid.UUID, payload: MeetingNoteUpdate, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    note = await _get_note(db, note_id)
    fields = payload.model_dump(exclude_unset=True)
    for key in ("content", "kind", "assignee_user_id", "due_date", "manual_status"):
        if key in fields:
            setattr(note, key, fields[key].strip() if isinstance(fields[key], str) else fields[key])
    for key in ("reference", "answer"):
        if key in fields:
            setattr(note, key, (fields[key] or "").strip() or None)
    if "is_closed" in fields and fields["is_closed"] is not None:
        note.is_closed = bool(fields["is_closed"])
        note.closed_at = datetime.now(timezone.utc) if note.is_closed else None
    await db.commit()
    note = await _reload(db, note.id)
    return (await _notes_out(db, [note]))[0]


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_note(note_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    note = await _get_note(db, note_id)
    note_dir = _upload_dir() / str(note.id)
    await db.delete(note)
    await db.commit()
    shutil.rmtree(note_dir, ignore_errors=True)


@router.post("/{note_id}/attachments", response_model=MeetingNoteOut, status_code=status.HTTP_201_CREATED)
async def upload_attachments(note_id: uuid.UUID, files: list[UploadFile] = File(...), db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    note = await _get_note(db, note_id)
    await _save_attachments(db, note, files, user)
    await db.commit()
    note = await _reload(db, note.id)
    return (await _notes_out(db, [note]))[0]


@router.get("/attachments/{attachment_id}")
async def download_attachment(attachment_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    attachment = await db.get(MeetingNoteAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skedari nuk u gjet.")
    path = _upload_dir() / str(attachment.note_id) / attachment.stored_filename
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skedari nuk gjendet në server.")
    return FileResponse(path, media_type=attachment.content_type or "application/octet-stream", filename=attachment.original_filename)


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_attachment(attachment_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    attachment = await db.get(MeetingNoteAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skedari nuk u gjet.")
    path = _upload_dir() / str(attachment.note_id) / attachment.stored_filename
    await db.delete(attachment)
    await db.commit()
    path.unlink(missing_ok=True)


# ---------------------------------------------------------------- PX Notes

def _px_line(note: MeetingNote) -> str:
    text = note.content.strip()
    if note.reference:
        text = f"{note.reference}: {text}"
    if note.kind == "QUESTION" and not text.startswith("?"):
        text = f"? {text}"
    if note.answer:
        text = f"{text}\nVendimi: {note.answer.strip()}"
    return text


async def _copy_attachments_to_px(db: AsyncSession, notes: list[MeetingNote], ga_note_id: uuid.UUID, user) -> list[Path]:
    copied: list[Path] = []
    target_dir = _ga_upload_dir() / str(ga_note_id)
    for note in notes:
        for attachment in note.attachments or []:
            source = _upload_dir() / str(note.id) / attachment.stored_filename
            if not source.exists():
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            new_id = uuid.uuid4()
            stored_name = f"{new_id}{Path(attachment.original_filename).suffix}"
            target = target_dir / stored_name
            shutil.copyfile(source, target)
            copied.append(target)
            db.add(GaNoteAttachment(
                id=new_id, note_id=ga_note_id, original_filename=attachment.original_filename,
                stored_filename=stored_name, content_type=attachment.content_type,
                size_bytes=attachment.size_bytes, created_by=user.id,
            ))
    return copied


@router.post("/send-to-px", response_model=list[MeetingNoteOut])
async def send_to_px(payload: SendToPxIn, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """Create PX notes from meeting notes: one per note, or one merged note."""
    ids = list(dict.fromkeys(payload.note_ids))
    notes = (await db.execute(select(MeetingNote).where(MeetingNote.id.in_(ids)))).scalars().all()
    if len(notes) != len(ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Një ose më shumë shënime nuk u gjetën.")
    if any(n.ga_note_id for n in notes):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Disa shënime janë dërguar tashmë në PX Notes.")
    meeting_ids = {n.meeting_id for n in notes}
    if payload.merge and len(meeting_ids) != 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bashkohen vetëm shënimet e të njëjtit takim.")
    order = {note_id: index for index, note_id in enumerate(ids)}
    notes = sorted(notes, key=lambda n: order[n.id])
    meetings = {m_id: await _get_meeting(db, m_id) for m_id in meeting_ids}
    groups = [notes] if payload.merge else [[n] for n in notes]
    copied: list[Path] = []
    try:
        for group in groups:
            meeting = meetings[group[0].meeting_id]
            if len(group) == 1:
                content = _px_line(group[0])
            else:
                header = f"{meeting.title} · {group[0].occurrence_date.strftime('%d.%m.%Y')}"
                content = header + "\n" + "\n".join(f"{index}. {_px_line(n)}" for index, n in enumerate(group, start=1))
            ga_note = await build_ga_note(db, user, GaNoteCreate(
                content=content,
                project_id=meeting.project_id,
                department_id=None if meeting.project_id else meeting.department_id,
                is_discussed=True,
            ))
            await db.flush()
            copied += await _copy_attachments_to_px(db, group, ga_note.id, user)
            for note in group:
                note.ga_note_id = ga_note.id
        await db.commit()
    except Exception:
        for path in copied:
            path.unlink(missing_ok=True)
        await db.rollback()
        raise
    db.expire_all()
    refreshed = (await db.execute(select(MeetingNote).where(MeetingNote.id.in_(ids)))).scalars().all()
    return await _notes_out(db, sorted(refreshed, key=lambda n: order[n.id]))


# ---------------------------------------------------------------- client history

@router.get("/client-history")
async def client_history(
    project_id: uuid.UUID,
    date_from: date,
    date_to: date,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """All sessions of a client's (project's) meetings in a period, with notes."""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Projekti nuk u gjet.")
    meetings = (await db.execute(select(Meeting).where(Meeting.project_id == project_id).where(_visible_meeting_filter()))).scalars().all()
    by_id = {m.id: m for m in meetings}
    ids = list(by_id)
    sessions: dict[tuple[uuid.UUID, date], dict] = {}

    def session(meeting_id: uuid.UUID, day: date) -> dict:
        key = (meeting_id, day)
        if key not in sessions:
            meeting = by_id[meeting_id]
            sessions[key] = {
                "meeting": {"id": meeting.id, "title": meeting.title, "meeting_type": meeting.meeting_type,
                            "kind": _meeting_kind(meeting)},
                "date": day, "status": None, "recordings": [], "notes": [],
            }
        return sessions[key]

    if ids:
        notes = (await db.execute(
            select(MeetingNote).where(
                MeetingNote.meeting_id.in_(ids),
                MeetingNote.occurrence_date >= date_from,
                MeetingNote.occurrence_date <= date_to,
            ).order_by(MeetingNote.position, MeetingNote.created_at)
        )).scalars().all()
        for note_out in await _notes_out(db, list(notes)):
            session(note_out.meeting_id, note_out.occurrence_date)["notes"].append(note_out.model_dump(mode="json"))
        for row in (await db.execute(
            select(MeetingOccurrenceStatus).where(
                MeetingOccurrenceStatus.meeting_id.in_(ids),
                MeetingOccurrenceStatus.occurrence_date >= date_from,
                MeetingOccurrenceStatus.occurrence_date <= date_to,
            )
        )).scalars().all():
            session(row.meeting_id, row.occurrence_date)["status"] = row.status
        start = datetime.combine(date_from, datetime.min.time(), tzinfo=_tz())
        end = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=_tz())
        for rec in (await db.execute(
            select(MeetingRecording).where(
                MeetingRecording.meeting_id.in_(ids), MeetingRecording.deleted_at.is_(None),
                MeetingRecording.recording_started_at >= start, MeetingRecording.recording_started_at < end,
            )
        )).scalars().all():
            day = _local_date(rec.recording_started_at)
            session(rec.meeting_id, day)["recordings"].append({"id": rec.id, "duration_seconds": rec.duration_seconds})
    rows = sorted(sessions.values(), key=lambda s: (s["date"], s["meeting"]["title"]), reverse=True)
    return {
        "project": {"id": project.id, "title": getattr(project, "title", None) or getattr(project, "name", None)},
        "meetings": [{"id": m.id, "title": m.title, "kind": _meeting_kind(m)} for m in meetings],
        "sessions": rows,
    }


# ---------------------------------------------------------------- recordings

def _action_seconds(job: RecordingAnalysis | None, action_id: uuid.UUID) -> float | None:
    results = ((job.timing or {}).get("results") or {}) if job else {}
    value = results.get(str(action_id)) or {}
    start = value.get("start") if isinstance(value, dict) else None
    return float(start) if isinstance(start, (int, float)) else None


async def _recording_meeting(db: AsyncSession, recording: MeetingRecording) -> Meeting:
    if recording.meeting_id is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lidhe regjistrimin me një takim para se të ruash shënime.")
    return await _get_meeting(db, recording.meeting_id)


@router.post("/recordings/{recording_id}/actions/{action_id}/note", response_model=MeetingNoteOut)
async def action_as_note(recording_id: uuid.UUID, action_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    """Keep an AI proposal as a meeting note (no task)."""
    recording = await load_recording(db, recording_id, user)
    meeting = await _recording_meeting(db, recording)
    action = (await db.execute(select(RecordingAction).where(RecordingAction.id == action_id, RecordingAction.recording_id == recording.id))).scalar_one_or_none()
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Propozimi nuk u gjet.")
    existing = (await db.execute(select(MeetingNote).where(MeetingNote.recording_action_id == action.id))).scalars().first()
    if existing:
        return (await _notes_out(db, [existing]))[0]
    job = await db.get(RecordingAnalysis, recording.id)
    content = "\n".join(part for part in (action.title.strip(), (action.description or "").strip()) if part)
    note = MeetingNote(
        meeting_id=meeting.id, occurrence_date=_local_date(recording.recording_started_at) or _today(),
        kind="QUESTION" if content.rstrip().endswith("?") else "NOTE", content=content, source="RECORDING",
        recording_id=recording.id, recording_action_id=action.id, recording_seconds=_action_seconds(job, action.id),
        assignee_user_id=action.suggested_assignee_id, due_date=action.suggested_due_date, created_by=user.id,
    )
    action.dismissed_at = None
    db.add(note)
    await db.commit()
    note = await _reload(db, note.id)
    return (await _notes_out(db, [note]))[0]


@router.post("/recordings/{recording_id}/actions/{action_id}/dismiss")
async def dismiss_action(recording_id: uuid.UUID, action_id: uuid.UUID, payload: DismissIn, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    recording = await load_recording(db, recording_id, user)
    action = (await db.execute(select(RecordingAction).where(RecordingAction.id == action_id, RecordingAction.recording_id == recording.id))).scalar_one_or_none()
    if action is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Propozimi nuk u gjet.")
    if payload.dismissed:
        action.dismissed_at = datetime.now(timezone.utc)
    else:
        action.dismissed_at = None
        # "Zhbëj" on a kept note removes that meeting note again.
        for note in (await db.execute(select(MeetingNote).where(MeetingNote.recording_action_id == action.id, MeetingNote.ga_note_id.is_(None)))).scalars().all():
            await db.delete(note)
    await db.commit()
    return {"id": action.id, "dismissed_at": action.dismissed_at}


@router.post("/recordings/{recording_id}/screenshot", response_model=MeetingNoteOut, status_code=status.HTTP_201_CREATED)
async def recording_screenshot(
    recording_id: uuid.UUID,
    seconds: float = Form(0),
    content: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Save the current video frame as a meeting note with the screenshot attached."""
    recording = await load_recording(db, recording_id, user)
    meeting = await _recording_meeting(db, recording)
    total = int(max(seconds, 0))
    stamp = f"{total // 3600:02d}:{total // 60 % 60:02d}:{total % 60:02d}"
    note = MeetingNote(
        meeting_id=meeting.id, occurrence_date=_local_date(recording.recording_started_at) or _today(),
        kind="NOTE", content=(content or "").strip() or f"Screenshot nga videoja · {stamp}", source="RECORDING",
        recording_id=recording.id, recording_seconds=max(seconds, 0), created_by=user.id,
    )
    db.add(note)
    await db.flush()
    await _save_attachments(db, note, [file], user)
    await db.commit()
    note = await _reload(db, note.id)
    return (await _notes_out(db, [note]))[0]
