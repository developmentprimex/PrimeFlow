from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, http_bearer
from app.auth.security import ALGORITHM, decode_token, require_token_type
from app.config import settings
from app.db import get_db
from app.models.enums import UserRole
from app.models.meeting import Meeting, MeetingParticipant
from app.models.meeting_recording import MeetingRecording as Recording, MeetingRecordingChunk as Chunk
from app.models.user import User
from app.schemas.meeting_recording import RecordingComplete, RecordingCreate, RecordingOut, RecordingUpdate
from app.services.audit import add_audit_log
from app.services.meeting_recording_storage import LocalMeetingStorage, StorageBusy, StorageError, durable_replace

router = APIRouter()


def storage():
    return LocalMeetingStorage(settings.MEETING_RECORDINGS_ROOT)


def management(user):
    # The existing meeting RBAC permits both roles across departments.
    return user.role in (UserRole.ADMIN, UserRole.MANAGER)


def meeting_scope(user):
    participant = exists(select(MeetingParticipant.id).where(
        MeetingParticipant.meeting_id == Meeting.id,
        MeetingParticipant.user_id == user.id,
        MeetingParticipant.assignment_source == "manual",
    ))
    return or_(Meeting.created_by == user.id, participant)


def read_scope(user):
    # The recording library is shared with every authenticated active account.
    # Authentication still runs on metadata, playback, downloads and analysis.
    return True


async def load_recording(db, recording_id, user, *, write=False):
    stmt = select(Recording).where(Recording.id == recording_id, Recording.deleted_at.is_(None))
    stmt = stmt.where(Recording.created_by == user.id if write else read_scope(user))
    if write:
        stmt = stmt.with_for_update()
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Recording not found")
    return row


def audit(db, user, row, action, **details):
    add_audit_log(db=db, actor_user_id=user.id, entity_type="meeting_recording", entity_id=row.id, action=action, after=details or None)


async def recording_output(row):
    result = RecordingOut.model_validate(row)
    if row.status == "READY":
        media = await asyncio.to_thread(storage().available_media, row.storage_key, row.mime_type, row.size_bytes)
        result.media_available = media is not None
    return result


@router.post("", response_model=RecordingOut, status_code=201)
async def create_recording(payload: RecordingCreate, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    try:
        storage().check_tools(settings.MEETING_RECORDINGS_FFMPEG, settings.MEETING_RECORDINGS_FFPROBE)
    except StorageError:
        raise HTTPException(503, "Recording encoder is not configured")
    # Serialize open-session quota checks for this account across API processes.
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    count = await db.scalar(select(func.count()).select_from(Recording).where(
        Recording.created_by == user.id, Recording.status.in_(["CREATED", "RECORDING", "UPLOADING", "FINALIZING"])))
    if count >= settings.MEETING_RECORDINGS_MAX_OPEN_SESSIONS:
        raise HTTPException(409, "Recover or abandon an unfinished recording first")
    if payload.meeting_id:
        stmt = select(Meeting).where(Meeting.id == payload.meeting_id)
        if not management(user):
            stmt = stmt.where(meeting_scope(user))
        if (await db.execute(stmt)).scalar_one_or_none() is None:
            raise HTTPException(404, "Meeting not found or recording access denied")
    now, recording_id = datetime.now(timezone.utc), uuid.uuid4()
    row = Recording(id=recording_id, created_by=user.id, **payload.model_dump(exclude={"consent_acknowledged"}),
                    storage_key=f"{now:%Y/%m}/{recording_id}", status="CREATED")
    db.add(row)
    audit(db, user, row, "recording_created", consent_acknowledged=True)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("", response_model=list[RecordingOut])
async def list_recordings(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                          db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    rows = (await db.execute(select(Recording, User.full_name, Meeting.title)
                            .join(User, Recording.created_by == User.id)
                            .outerjoin(Meeting, Recording.meeting_id == Meeting.id)
                            .where(read_scope(user), Recording.deleted_at.is_(None)).order_by(Recording.created_at.desc()).offset(offset).limit(limit))).all()
    return [(await recording_output(row)).model_copy(update={"recorded_by_name": name, "meeting_title": title}) for row, name, title in rows]


@router.get("/{recording_id}", response_model=RecordingOut)
async def get_recording(recording_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    row = await load_recording(db, recording_id, user)
    result = await recording_output(row)
    result.recorded_by_name = await db.scalar(select(User.full_name).where(User.id == row.created_by))
    result.meeting_title = await db.scalar(select(Meeting.title).where(Meeting.id == row.meeting_id)) if row.meeting_id else None
    return result


@router.patch("/{recording_id}", response_model=RecordingOut)
async def update_recording(recording_id: uuid.UUID, payload: RecordingUpdate,
                           db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    row = (await db.execute(select(Recording).where(
        Recording.id == recording_id, Recording.deleted_at.is_(None)).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Recording not found")
    if row.created_by != user.id and not management(user):
        raise HTTPException(403, "Only the creator, admins and managers can edit recordings")
    previous_title = row.title
    row.title = payload.title
    audit(db, user, row, "recording_title_updated", previous_title=previous_title, title=row.title)
    await db.commit()
    await db.refresh(row)
    return await get_recording(recording_id, db, user)


@router.delete("/{recording_id}", status_code=204)
async def delete_recording(recording_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if not management(user):
        raise HTTPException(403, "Only admins and managers can delete recordings")
    row = (await db.execute(select(Recording).where(Recording.id == recording_id)
                            .with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Recording not found")
    if row.deleted_at is not None:
        return Response(status_code=204)
    if row.status not in {"READY", "FAILED"}:
        raise HTTPException(409, "Stop or abandon an active recording before deleting it")
    row.deleted_at = datetime.now(timezone.utc)
    audit(db, user, row, "recording_deleted", title=row.title)
    await db.commit()
    return Response(status_code=204)


@router.put("/{recording_id}/chunks/{index}")
async def upload_chunk(recording_id: uuid.UUID, request: Request, index: int = Path(ge=0, le=99999),
                       x_chunk_sha256: str = Header(), db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    row = await load_recording(db, recording_id, user, write=True)
    if row.status not in {"CREATED", "RECORDING", "UPLOADING"}:
        raise HTTPException(409, "Recording is closed for uploads")
    if index > row.chunks_received:
        raise HTTPException(409, "Chunks must be uploaded sequentially")
    if not re.fullmatch(r"[a-f0-9]{64}", x_chunk_sha256):
        raise HTTPException(422, "Invalid chunk digest")
    if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
        raise HTTPException(415, "Expected binary recording fragment")
    limit = settings.MEETING_RECORDINGS_MAX_CHUNK_BYTES
    try:
        content_length = int(request.headers.get("content-length", "0"))
    except ValueError:
        raise HTTPException(422, "Invalid content length")
    if content_length < 0 or content_length > limit:
        raise HTTPException(413, "Chunk exceeds upload limit")
    store = storage()
    try:
        temp, size, digest = await store.receive(row.storage_key, request.stream(), limit)
    except StorageError:
        raise HTTPException(413, "Empty or oversized recording fragment")
    try:
        if digest != x_chunk_sha256:
            raise HTTPException(422, "Chunk digest does not match content")
        previous = await db.get(Chunk, (row.id, index))
        if previous:
            if previous.sha256 != digest or previous.size_bytes != size:
                raise HTTPException(409, "Chunk index already contains different content")
            return {"index": index, "sha256": digest, "size_bytes": size, "duplicate": True}
        if index != row.chunks_received:
            raise HTTPException(409, "Chunk receipt is missing; recording requires recovery")
        if row.size_bytes + size > settings.MEETING_RECORDINGS_MAX_SESSION_BYTES:
            raise HTTPException(413, "Recording exceeds session storage limit")
        destination = store.path(f"{row.storage_key}/chunks/{index:08d}.chunk")
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(durable_replace, temp, destination)
        db.add(Chunk(recording_id=row.id, index=index, size_bytes=size, sha256=digest))
        row.chunks_received += 1
        row.size_bytes += size
        row.status = "UPLOADING"
        row.error_message = None
        # A crash before this commit leaves an unacknowledged file which the
        # same-index retry safely replaces; the DB receipt is authoritative.
        await db.commit()
        return {"index": index, "sha256": digest, "size_bytes": size, "duplicate": False}
    finally:
        temp.unlink(missing_ok=True)


@router.post("/{recording_id}/complete", response_model=RecordingOut)
async def complete_recording(recording_id: uuid.UUID, payload: RecordingComplete,
                             db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    row = await load_recording(db, recording_id, user, write=True)
    if payload.chunks != row.chunks_received:
        raise HTTPException(409, "Required recording chunks are missing")
    if row.status == "READY":
        return row
    chunks = (await db.execute(select(Chunk).where(Chunk.recording_id == row.id).order_by(Chunk.index))).scalars().all()
    if len(chunks) != payload.chunks or any(chunk.index != index for index, chunk in enumerate(chunks)):
        raise HTTPException(409, "Required recording chunks are missing")
    row.status = "FINALIZING"
    row.is_partial = payload.partial
    row.recording_stopped_at = datetime.now(timezone.utc)
    try:
        result = await asyncio.to_thread(storage().finalize, row.storage_key, chunks, row.mime_type,
                                        settings.MEETING_RECORDINGS_FFMPEG, settings.MEETING_RECORDINGS_FFPROBE,
                                        settings.MEETING_RECORDINGS_MAX_DURATION_SECONDS)
    except StorageBusy as exc:
        await db.rollback()
        raise HTTPException(409, str(exc))
    except StorageError:
        row.status = "FAILED"
        row.error_message = "Media validation failed. Retained server chunks can be finalized again."
        audit(db, user, row, "recording_validation_failed")
        await db.commit()
        raise HTTPException(422, row.error_message)
    for key in ("duration_seconds", "size_bytes", "video_width", "video_height", "mime_type"):
        setattr(row, key, result[key])
    if not result["has_audio"]:
        row.has_microphone_audio = row.has_system_audio = False
    # Audio-source attribution is a browser declaration, not a forensic claim.
    row.status, row.error_message = "READY", None
    row.upload_completed_at = datetime.now(timezone.utc)
    audit(db, user, row, "recording_ready", size_bytes=row.size_bytes, chunks=row.chunks_received)
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/{recording_id}/fail", response_model=RecordingOut)
async def fail_recording(recording_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    row = await load_recording(db, recording_id, user, write=True)
    if row.status == "READY":
        raise HTTPException(409, "A saved recording cannot be abandoned")
    row.status, row.error_message = "FAILED", "Capture interrupted or abandoned; never confirmed as saved."
    audit(db, user, row, "recording_abandoned")
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/{recording_id}/playback")
async def playback_grant(recording_id: uuid.UUID, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    row = await load_recording(db, recording_id, user)
    if row.status != "READY":
        raise HTTPException(409, "Recording is not ready")
    now = datetime.now(timezone.utc)
    token = jwt.encode({"type": "recording_playback", "sub": str(user.id), "recording_id": str(row.id),
                        "exp": now + timedelta(minutes=15), "iat": now}, settings.JWT_SECRET, algorithm=ALGORITHM)
    audit(db, user, row, "recording_playback_authorized")
    await db.commit()
    return {"token": token, "expires_in": 900}


async def media_user(recording_id: uuid.UUID, credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
                     db: AsyncSession = Depends(get_db)):
    if credentials is None:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") == "access":
            return await get_current_user(db=db, credentials=credentials)
        require_token_type(payload, "recording_playback")
        if payload.get("recording_id") != str(recording_id):
            raise ValueError("Wrong recording")
        user = await db.get(User, uuid.UUID(payload["sub"]))
        if user is None or not user.is_active:
            raise ValueError("Inactive user")
        return user
    except (ValueError, KeyError):
        raise HTTPException(401, "Invalid playback authorization")


async def serve_media(recording_id, db, user, request: Request, *, download=False):
    row = await load_recording(db, recording_id, user)
    byte_range = request.headers.get("range")
    if byte_range and not re.fullmatch(r"bytes=\d{0,20}-\d{0,20}", byte_range):
        raise HTTPException(416, "Only a single byte range is supported")
    if row.status != "READY":
        raise HTTPException(409, "Recording is not ready")
    extension = "webm" if row.mime_type == "video/webm" else "mp4"
    file = await asyncio.to_thread(storage().available_media, row.storage_key, row.mime_type, row.size_bytes)
    if file is None:
        raise HTTPException(503, "Recording storage is unavailable")
    audit(db, user, row, "recording_downloaded" if download else "recording_streamed")
    await db.commit()
    return FileResponse(file, media_type=row.mime_type, filename=f"recording-{row.id}.{extension}",
                        content_disposition_type="attachment" if download else "inline",
                        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.api_route("/{recording_id}/stream", methods=["GET", "HEAD"])
async def stream_recording(recording_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db), user=Depends(media_user)):
    return await serve_media(recording_id, db, user, request)


@router.get("/{recording_id}/download")
async def download_recording(recording_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db), user=Depends(media_user)):
    return await serve_media(recording_id, db, user, request, download=True)
