"""Durable meeting state. Human actions and capture-worker credentials stay separate."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select, text
from app.api.routers import discord_assistant as bridge
from app.api.access import ensure_department_access
from app.config import settings
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting, DiscordVoiceSegment as Segment
from app.models.enums import UserRole
from app.schemas.ga_note import GaNoteCreate
from app.services.ga_note_creation import build_ga_note


def now():
    return datetime.now(timezone.utc)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def view(row):
    return dict(id=str(row.id), status=row.status, title=row.title, partial=bool(row.partial),
        organizer_user_id=str(row.user_id), voice_channel_id=row.voice_channel_id,
        private_channel_id=row.private_channel_id, error=row.error, draft_text=row.draft_text,
        saved_note_id=str(row.saved_note_id) if row.saved_note_id else None,
        note_url=settings.FRONTEND_URL.rstrip('/') + '/ga-ka-notes' if row.saved_note_id else None)


async def locked(db, session_id):
    row = (await db.execute(select(Meeting).where(Meeting.id == session_id).with_for_update()
        .execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, 'Takimi nuk u gjet.')
    return row


async def authorize_session(db, actor, session_id, *, operation):
    link, user = await bridge.identity(db, actor)
    row = await locked(db, session_id)
    owner = row.user_id == user.id and row.link_id == link.id and row.private_channel_id == actor.channel_id
    manager_stop = operation == 'stop' and user.role in (UserRole.ADMIN, UserRole.MANAGER) and actor.voice_channel_id == row.voice_channel_id
    if row.guild_id != actor.guild_id or not (owner or manager_stop):
        raise HTTPException(403, 'Nuk ke qasje te ky takim.')
    return row, user


def check_worker(row, token, instance):
    if not secrets.compare_digest(row.capture_token_hash, token_hash(token)) or row.instance_id != instance:
        raise HTTPException(403, 'Sesioni i audios nuk përputhet.')
    if row.heartbeat_at < now() - timedelta(seconds=60):
        raise HTTPException(409, 'Lidhja e takimit ka skaduar.')


async def worker_row(db, session_id, payload):
    row = await locked(db, session_id)
    check_worker(row, payload.capture_token, payload.instance_id)
    return row


async def start_session(db, actor):
    if not settings.DISCORD_MEETING_NOTES_ENABLED or not settings.OPENAI_API_KEY:
        raise HTTPException(503, 'Shënimet e takimeve nuk janë aktivizuar.')
    link, user = await bridge.identity(db, actor)
    if not actor.voice_channel_id:
        raise HTTPException(400, 'Hyr fillimisht në voice channel.')
    # Reserve per guild before checking for replay/another capture.
    lock_key = int.from_bytes(hashlib.sha256(('voice:' + actor.guild_id).encode()).digest()[:8], 'big', signed=True)
    await db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock_key})
    prior = (await db.execute(select(Meeting).where(Meeting.request_id == actor.request_id))).scalar_one_or_none()
    if prior:
        if prior.user_id != user.id or prior.instance_id != actor.instance_id or prior.capture_token_hash != token_hash(actor.capture_token):
            raise HTTPException(409, 'Kërkesa e nisjes nuk përputhet.')
        return view(prior)
    active = (await db.execute(select(Meeting).where(Meeting.guild_id == actor.guild_id,
        Meeting.status.in_(['STARTING', 'LISTENING'])))).scalar_one_or_none()
    if active:
        raise HTTPException(409, 'Një takim po dëgjohet tashmë në këtë server.')
    department = actor.department_id or user.department_id
    if department:
        ensure_department_access(user, department)
    elif user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(400, 'Zgjidh departamentin për shënimet.')
    row = Meeting(id=uuid.uuid4(), link_id=link.id, user_id=user.id, department_id=department,
        guild_id=actor.guild_id, voice_channel_id=actor.voice_channel_id, private_channel_id=actor.channel_id,
        request_id=actor.request_id, instance_id=actor.instance_id, capture_token_hash=token_hash(actor.capture_token),
        title=actor.title.strip(), status='STARTING', partial=False, stop_authorized=False, heartbeat_at=now())
    db.add(row)
    await db.commit()
    return view(row)


async def transition_session(db, session_id, payload, target):
    row = await worker_row(db, session_id, payload)
    if target == 'LISTENING' and row.status == 'STARTING':
        row.status, row.started_at = target, now()
    elif target == 'INTERRUPTED' and row.status in ('STARTING', 'LISTENING', 'FINALIZING'):
        row.status, row.partial, row.error, row.stopped_at = target, True, 'Dëgjimi u ndërpre.', now()
    elif target not in ('HEARTBEAT', row.status):
        raise HTTPException(409, 'Gjendja e takimit ka ndryshuar.')
    row.heartbeat_at = now()
    await db.commit()
    return view(row)


async def authorize_stop(db, actor, session_id):
    row, _ = await authorize_session(db, actor, session_id, operation='stop')
    row.stop_authorized = True
    await db.commit()
    return view(row)


async def finish_session(db, session_id, payload):
    row = await worker_row(db, session_id, payload)
    if row.status in ('READY', 'SAVED', 'FINALIZING', 'FAILED'):
        return view(row)
    if not row.stop_authorized and row.status != 'INTERRUPTED':
        raise HTTPException(403, 'Përfundimi nuk është autorizuar.')
    row.expected_segments = payload.segment_count
    row.partial = bool(row.partial or payload.partial)
    row.status, row.stopped_at = 'FINALIZING', now()
    await db.commit()
    return view(row)


async def save_notes(db, actor, session_id):
    row, user = await authorize_session(db, actor, session_id, operation='save')
    if row.saved_note_id:
        return view(row)
    if row.saved_at:
        raise HTTPException(409, 'Note-i i ruajtur është hequr; nuk krijohet përsëri.')
    if row.status != 'READY' or not (row.draft_text or '').strip():
        raise HTTPException(409, 'Shënimet nuk janë gati.')
    note = await build_ga_note(db, user, GaNoteCreate(content=row.draft_text, department_id=row.department_id,
        created_by=user.id))
    await db.flush()
    row.saved_note_id, row.saved_at, row.status = note.id, now(), 'SAVED'
    await db.commit()
    return view(row)
