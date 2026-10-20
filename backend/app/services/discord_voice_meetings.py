"""Durable meeting state. Human actions and capture-worker credentials stay separate."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from sqlalchemy import select, text, or_
from app.api.routers import discord_assistant as bridge
from app.api.access import ensure_department_access
from app.config import settings
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting, DiscordVoiceSegment as Segment
from app.models.enums import UserRole
from app.models.discord_assistant import DiscordLink
from app.models.user import User
from app.schemas.ga_note import GaNoteCreate
from app.services.ga_note_creation import build_ga_note


def now():
    return datetime.now(timezone.utc)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def view(row):
    return dict(id=str(row.id), status=row.status, title=row.title, partial=bool(row.partial),
        created_at=row.created_at.isoformat() if row.created_at else None,
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


async def receive_segment(db, session_id, payload, audio):
    from app.services import discord_voice_openai as provider
    provider.validate_wav(audio)
    if payload.end_ms < payload.start_ms or payload.end_ms-payload.start_ms>11000:
        raise HTTPException(422, 'Koha e segmentit nuk është e vlefshme.')
    digest=hashlib.sha256(audio).hexdigest()
    row=await worker_row(db, session_id, payload)
    if row.status not in ('STARTING','LISTENING','INTERRUPTED','FINALIZING'):
        raise HTTPException(409, 'Audioja është mbyllur.')
    if row.expected_segments is not None and payload.sequence>=row.expected_segments:
        raise HTTPException(409, 'Segmenti është jashtë takimit.')
    segment=(await db.execute(select(Segment).where(Segment.session_id==session_id,
        Segment.sequence==payload.sequence).with_for_update())).scalar_one_or_none()
    if segment:
        if (segment.content_hash,segment.speaker_id,segment.start_ms,segment.end_ms)!=(digest,payload.speaker_id,payload.start_ms,payload.end_ms):
            raise HTTPException(409, 'Segmenti i përsëritur nuk përputhet.')
        if segment.status in ('DONE','ERROR'):
            return {'sequence':segment.sequence,'status':segment.status}
        if segment.lease_until and segment.lease_until>now():
            raise HTTPException(409, 'Segmenti po përpunohet.')
    else:
        segment=Segment(id=uuid.uuid4(),session_id=session_id,sequence=payload.sequence,
            speaker_id=payload.speaker_id,speaker_name=payload.speaker_name,start_ms=payload.start_ms,
            end_ms=payload.end_ms,content_hash=digest,status='PROCESSING')
        db.add(segment)
    lease=uuid.uuid4();segment.lease_token=lease;segment.lease_until=now()+timedelta(seconds=120)
    await db.commit()
    try:
        transcript=await provider.transcribe_segment(audio);error=None
    except ValueError:
        transcript=None;error='transcription_failed'
    # Reacquire in a consistent order; never hold a DB lock over remote IO.
    row=await locked(db,session_id)
    segment=(await db.execute(select(Segment).where(Segment.id==segment.id).with_for_update()
        .execution_options(populate_existing=True))).scalar_one()
    if segment.lease_token!=lease:raise HTTPException(409,'Përpunimi i segmentit ka ndryshuar.')
    segment.transcript,segment.error,segment.status=transcript,error,'ERROR' if error else 'DONE'
    if error:row.partial=True
    await db.commit()
    return {'sequence':segment.sequence,'status':segment.status}


async def claim_deliveries(db):
    rows=(await db.execute(select(Meeting,DiscordLink).join(DiscordLink,DiscordLink.id==Meeting.link_id)
        .join(User,User.id==Meeting.user_id).where(Meeting.status.in_(['READY','FAILED']),
            Meeting.delivered_at.is_(None),or_(Meeting.delivery_until.is_(None),Meeting.delivery_until<now()),
            DiscordLink.enabled.is_(True),User.is_active.is_(True),DiscordLink.channel_id==Meeting.private_channel_id,
            Meeting.guild_id==settings.DISCORD_GUILD_ID)
        .order_by(Meeting.created_at).with_for_update(of=Meeting,skip_locked=True).limit(10))).all()
    jobs=[]
    for row,link in rows:
        row.delivery_token=uuid.uuid4();row.delivery_until=now()+timedelta(minutes=5)
        jobs.append(dict(id=str(row.id),guild_id=row.guild_id,channel_id=row.private_channel_id,
            discord_user_id=link.discord_user_id,delivery_token=str(row.delivery_token)))
    await db.commit()
    return {'jobs':jobs}


async def ack_delivery(db,session_id,payload):
    row=await locked(db,session_id)
    if row.delivery_token!=payload.delivery_token:raise HTTPException(409,'Njoftimi ka ndryshuar.')
    row.message_ids=payload.message_ids;row.delivered_at=now();row.delivery_until=None
    await db.commit()
    return {'success':True}
