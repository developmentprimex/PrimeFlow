"""Independent, replay-safe desktop notes; durable text and leases only."""
import hashlib
import io
import json
import uuid
import wave
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select, inspect
from app.config import settings
from app.models.mira_desktop import MiraDesktopSession, MiraDesktopSegment
from app.models.user import User
from app.schemas.ga_note import GaNoteCreate
from app.services.ga_note_creation import build_ga_note
from app.services import discord_voice_openai as provider

MAX_AUDIO_BYTES = 2_000_044
MAX_DURATION_MS = 14_400_000
MAX_SEGMENTS = 14_400
NO_SPEAKERS = '''
Rregull për këtë regjistrim desktop, me përparësi mbi çdo udhëzim më sipër:
Nuk ka identifikim folësish. Mos identifiko, emërto, etiketo apo hamendëso folësit.
Mos krijo emra folësish dhe mos ia atribuo fjalët një personi. Emrat e klientëve,
projekteve dhe përgjegjësve të përmendur shprehimisht si të dhëna mund të ruhen.
Zëvendëso çdo format reference me [segmenti 0, 00:02–00:07]: vetëm segmenti dhe koha.
Mos përdor fushë ose etiketë folësi, as emra, as "Folësi 1".
'''


def now():
    return datetime.now(timezone.utc)


def enabled():
    if not settings.OPENAI_API_KEY:
        raise HTTPException(503, 'mira_desktop_not_configured')


def validate_audio(data, start_ms, end_ms):
    if not 0 <= start_ms < end_ms <= MAX_DURATION_MS:
        raise HTTPException(422, 'invalid_audio_timing')
    if not data or len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, 'invalid_audio_size')
    try:
        with wave.open(io.BytesIO(data), 'rb') as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (2, 2, 48000, 'NONE'):
                raise ValueError()
            frames = audio.getnframes()
            if not 0 < frames <= 480000 or abs((end_ms-start_ms) - frames/48) > 2:
                raise ValueError()
            pcm = audio.readframes(frames)
            if len(pcm) != frames*4:
                raise ValueError()
        # Canonicalize metadata-heavy WAVs before reusing the existing transport.
        out = io.BytesIO()
        with wave.open(out, 'wb') as audio:
            audio.setnchannels(2); audio.setsampwidth(2); audio.setframerate(48000)
            audio.writeframes(pcm)
        return out.getvalue()
    except (wave.Error, EOFError, ValueError):
        raise HTTPException(422, 'invalid_audio_format_or_duration') from None


async def owner(db, user, session_id, lock=False):
    # Rollback expires ORM attributes. Read the stable identity without async lazy IO.
    state = inspect(user, raiseerr=False)
    user_id = state.identity[0] if state is not None and state.identity else user.id
    query = select(MiraDesktopSession).where(MiraDesktopSession.id == session_id,
        MiraDesktopSession.user_id == user_id)
    if lock:
        query = query.with_for_update()
    row = (await db.execute(query.execution_options(populate_existing=True))).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, 'session_not_found')
    return row


async def segments(db, session_id):
    return list((await db.scalars(select(MiraDesktopSegment).where(
        MiraDesktopSegment.session_id == session_id).order_by(MiraDesktopSegment.sequence)
        .execution_options(populate_existing=True))).all())


async def view(db, row):
    chunks = await segments(db, row.id)
    transcript = '\n'.join(f'[segmenti {s.sequence}, {provider.clock(s.start_ms)}–{provider.clock(s.end_ms)}] {s.transcript}'
        for s in chunks if s.status == 'DONE' and s.transcript)
    return dict(id=str(row.id), status=row.status, segment_count=len(chunks), transcript=transcript,
        notes=row.notes or '', note_id=str(row.note_id) if row.note_id else None,
        error=row.error, partial=row.partial)


async def get_session(db, user, session_id):
    return await view(db, await owner(db, user, session_id))


async def note_transcript_for_note(db, user, note_id):
    """Support the existing PX Notes transcript link without widening access."""
    session=(await db.execute(select(MiraDesktopSession).where(
        MiraDesktopSession.note_id==note_id))).scalar_one_or_none()
    if session is None:return None
    state=inspect(user,raiseerr=False)
    user_id=state.identity[0] if state is not None and state.identity else user.id
    if session.user_id!=user_id:raise HTTPException(404,'session_not_found')
    chunks=await segments(db,session.id)
    end=max((part.end_ms for part in chunks),default=0)
    return dict(note_id=str(note_id),title=session.title,status=session.status,partial=session.partial,
        started_at=session.created_at.isoformat(),
        stopped_at=(session.created_at+timedelta(milliseconds=end)).isoformat(),
        passages=[dict(speaker='',time=provider.clock(part.start_ms)+'–'+provider.clock(part.end_ms),
            text=part.transcript) for part in chunks if part.status=='DONE' and part.transcript])


async def create_session(db, user, payload):
    enabled()
    # Serialize per-owner creation so simultaneous starts cannot bypass quotas.
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    existing = (await db.execute(select(MiraDesktopSession).where(
        MiraDesktopSession.id == payload.id))).scalar_one_or_none()
    if existing:
        if existing.user_id != user.id:
            raise HTTPException(404, 'session_not_found')
        if existing.title != payload.title:
            raise HTTPException(409, 'session_conflict')
        return await view(db, existing)
    # Reuse the actual note builder to preflight all applicable authorization.
    probe = await build_ga_note(db, user, GaNoteCreate(content='Desktop preflight', department_id=user.department_id))
    db.expunge(probe)
    active = await db.scalar(select(func.count()).select_from(MiraDesktopSession).where(
        MiraDesktopSession.user_id == user.id, MiraDesktopSession.status != 'DONE'))
    daily = await db.scalar(select(func.count()).select_from(MiraDesktopSession).where(
        MiraDesktopSession.user_id == user.id, MiraDesktopSession.created_at >= now()-timedelta(days=1)))
    if active >= 3 or daily >= 24:
        raise HTTPException(429, 'capture_quota_exceeded')
    row = MiraDesktopSession(id=payload.id, user_id=user.id, department_id=user.department_id,
        title=payload.title, status='CAPTURING', partial=False)
    db.add(row)
    await db.commit()
    return await view(db, row)


def busy(until):
    return until is not None and until > now()


def receipt(row):
    return dict(sequence=row.sequence, status=row.status, transcript=row.transcript or '')


async def upload_segment(db, user, session_id, sequence, start_ms, end_ms, data):
    enabled()
    if not 0 <= sequence < MAX_SEGMENTS:
        raise HTTPException(422, 'invalid_sequence')
    wav = validate_audio(data, start_ms, end_ms)
    digest = hashlib.sha256(data).hexdigest()
    session = await owner(db, user, session_id, lock=True)
    row = (await db.execute(select(MiraDesktopSegment).where(
        MiraDesktopSegment.session_id == session_id, MiraDesktopSegment.sequence == sequence)
        .execution_options(populate_existing=True))).scalar_one_or_none()
    if row:
        if (row.content_hash, row.start_ms, row.end_ms) != (digest, start_ms, end_ms):
            raise HTTPException(409, 'segment_conflict')
        if row.status == 'DONE':
            return receipt(row)
        if busy(row.lease_until):
            raise HTTPException(409, 'segment_busy', headers={'Retry-After': '5'})
    if session.status != 'CAPTURING':
        raise HTTPException(409, 'session_closed')
    # Uploads are sequential; reject gaps, overlaps, and accidental new encoder lifetimes.
    prior = await segments(db, session_id)
    if row is None:
        if sequence != len(prior) or (prior and prior[-1].status != 'DONE'):
            raise HTTPException(409, 'segments_out_of_order')
        if (not prior and start_ms != 0) or (prior and abs(start_ms-prior[-1].end_ms) > 2):
            raise HTTPException(409, 'segment_timeline_gap')
        row = MiraDesktopSegment(session_id=session_id, sequence=sequence,
            start_ms=start_ms, end_ms=end_ms, content_hash=digest)
        db.add(row)
    token = uuid.uuid4()
    row.status, row.error = 'PROCESSING', None
    row.lease_token, row.lease_until = token, now()+timedelta(minutes=2)
    await db.commit()
    try:
        text = await provider.transcribe_segment(wav)
    except Exception:
        await owner(db, user, session_id, lock=True)
        await db.refresh(row)
        if row.lease_token == token:
            row.status, row.error, row.lease_until = 'FAILED', 'transcription_failed', None
            await db.commit()
        raise HTTPException(503, 'transcription_failed', headers={'Retry-After': '5'}) from None
    await owner(db, user, session_id, lock=True)
    await db.refresh(row)
    if row.lease_token != token:
        raise HTTPException(409, 'segment_lease_lost')
    row.status, row.transcript, row.lease_until = 'DONE', text, None
    await db.commit()
    return receipt(row)


async def summarize(title, chunks, cache, checkpoint):
    parts = [json.dumps(dict(segment=s['sequence'],
        time=provider.clock(s['start_ms'])+'–'+provider.clock(s['end_ms']), text=s['transcript']),
        ensure_ascii=False) for s in chunks if s['transcript']]
    if not parts:
        return ''
    async def run(group, final=False):
        payload = dict(model=settings.DISCORD_AI_MODEL, store=False, input=[
            dict(role='system', content=(provider.FINAL_SYSTEM if final else provider.PART_SYSTEM)+NO_SPEAKERS),
            dict(role='user', content=json.dumps(dict(title=title, segments=group), ensure_ascii=False))])
        return await provider.cached(payload, cache, checkpoint, provider.checked_summary)
    while sum(map(len, parts)) > provider.SUMMARY_DIRECT_CHARS:
        reduced = [await run(group) for group in provider.group_parts(parts, provider.SUMMARY_GROUP_CHARS)]
        if sum(map(len, reduced)) >= sum(map(len, parts)):
            raise ValueError('summary_did_not_reduce')
        parts = reduced
    return title+'\n\n'+await run(parts, True)


async def finish_session(db, user, session_id, payload):
    enabled()
    session = await owner(db, user, session_id, lock=True)
    if session.status == 'DONE':
        return await view(db, session)
    if session.expected_segments is not None and (session.expected_segments != payload.segment_count or session.partial != payload.partial):
        raise HTTPException(409, 'finish_conflict')
    if busy(session.lease_until):
        raise HTTPException(409, 'finalization_busy', headers={'Retry-After': '5'})
    chunks = await segments(db, session_id)
    if len(chunks) != payload.segment_count or any(s.sequence != i or s.status != 'DONE' for i, s in enumerate(chunks)):
        raise HTTPException(409, 'missing_segments')
    session.expected_segments, session.partial = payload.segment_count, payload.partial
    session.status, session.error = 'FINALIZING', None
    token = uuid.uuid4()
    session.lease_token, session.lease_until = token, now()+timedelta(minutes=15)
    cache = dict(session.summary_progress or {})
    title = session.title
    inputs = [dict(sequence=s.sequence, start_ms=s.start_ms, end_ms=s.end_ms, transcript=s.transcript or '') for s in chunks]
    await db.commit()

    async def checkpoint(progress):
        locked = await owner(db, user, session_id, lock=True)
        if locked.lease_token != token:
            raise HTTPException(409, 'finalization_lease_lost')
        locked.summary_progress = dict(progress)
        locked.lease_until = now()+timedelta(minutes=15)
        await db.commit()
    try:
        notes = await summarize(title, inputs, cache, checkpoint)
        locked = await owner(db, user, session_id, lock=True)
        if locked.lease_token != token:
            raise HTTPException(409, 'finalization_lease_lost')
        # Save and completion share one locked transaction, even when the HTTP response is lost.
        if notes:
            note = await build_ga_note(db, user, GaNoteCreate(content=notes,
                department_id=locked.department_id))
            await db.flush()
            locked.note_id = note.id
        locked.notes, locked.status, locked.error, locked.lease_until = notes, 'DONE', None, None
        await db.commit()
        return await view(db, locked)
    except Exception as exc:
        await db.rollback()
        locked = await owner(db, user, session_id, lock=True)
        if locked.lease_token == token and locked.status != 'DONE':
            locked.error, locked.lease_until = 'finalization_failed', None
            await db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(503, 'finalization_failed', headers={'Retry-After': '5'}) from None
