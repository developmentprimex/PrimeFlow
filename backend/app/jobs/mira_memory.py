"""Apply each finished meeting to Mira's memory register, one meeting at a time in start order."""
import hashlib
import logging
from datetime import timedelta
from sqlalchemy import select, text, func, or_, and_
from app.config import settings
from app.db import SessionLocal
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting, DiscordVoiceSegment as Segment
from app.services import mira_memory
from app.services.discord_voice_meetings import now
from app.services import discord_voice_openai as provider

log = logging.getLogger(__name__)
LOCK_KEY = int.from_bytes(hashlib.sha256(b'mira-memory').digest()[:8], 'big', signed=True)
LEASE = timedelta(minutes=5)


def started(model=Meeting):
    return func.coalesce(model.started_at, model.created_at)


def error_code(exc):
    status = getattr(exc, 'status', None)
    code = str(exc) if isinstance(exc, ValueError) and str(exc) else type(exc).__name__
    return (code[:80] + (f':{status}' if status else ''))[:100]


async def claim(db):
    """The next meeting to apply and its attempt number, or a reason to wait."""
    await db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': LOCK_KEY})
    busy = await db.scalar(select(Meeting.id).where(Meeting.memory_status == 'RUNNING',
        Meeting.memory_lease_until > now()).limit(1))
    if busy:
        return None, False
    row = (await db.execute(select(Meeting).where(or_(Meeting.memory_status == 'PENDING',
        and_(Meeting.memory_status == 'RUNNING', Meeting.memory_lease_until <= now())))
        .order_by(started()).limit(1).with_for_update())).scalar_one_or_none()
    if row is None:
        return None, False
    if row.memory_status == 'RUNNING' and row.memory_attempts >= settings.MIRA_MEMORY_MAX_ATTEMPTS:
        # The worker died mid-run on every attempt; stop so later meetings are not held forever.
        row.memory_status, row.memory_error, row.memory_lease_until = 'FAILED', 'lease_expired', None
        log.warning('MIRA_DIAGNOSTIC memory meeting=%s stage=claim error=lease_expired attempt=%s', row.id, row.memory_attempts)
        return None, False
    # An earlier meeting still preparing its notes goes first, but holds the queue only so long.
    earlier = await db.scalar(select(Meeting.id).where(Meeting.status.in_(['FINALIZING', 'INTERRUPTED']),
        started() < (row.started_at or row.created_at),
        func.coalesce(Meeting.stopped_at, Meeting.created_at) > now()-timedelta(minutes=settings.MIRA_MEMORY_WAIT_MINUTES)).limit(1))
    if earlier:
        return None, True
    row.memory_status, row.memory_attempts, row.memory_lease_until = 'RUNNING', row.memory_attempts + 1, now() + LEASE
    return row, False


async def process_mira_memory():
    stats = {'applied': 0, 'failed': 0, 'waiting': False}
    if not settings.MIRA_MEMORY_ENABLED:
        return stats
    async with SessionLocal() as db:
        row, stats['waiting'] = await claim(db)
        if row is None:
            await db.commit()
            return stats
        sid, fence, title, partial = row.id, row.memory_attempts, row.title, row.partial
        meeting_date = row.started_at or row.created_at
        segments = [{'sequence': s.sequence, 'speaker_name': s.speaker_name, 'start_ms': s.start_ms, 'end_ms': s.end_ms,
            'transcript': s.transcript} for s in (await db.execute(select(Segment).where(Segment.session_id == sid,
                Segment.status == 'DONE', Segment.transcript.is_not(None)).order_by(Segment.start_ms, Segment.sequence))).scalars()]
        await db.commit()
    try:
        async with SessionLocal() as db:
            memory = await mira_memory.snapshot(db)
        operations = await provider.extract_memory_operations(title, segments, meeting_date=meeting_date, memory=memory)
        async with SessionLocal() as db:
            current = (await db.execute(select(Meeting).where(Meeting.id == sid).with_for_update()
                .execution_options(populate_existing=True))).scalar_one()
            if current.memory_status != 'RUNNING' or current.memory_attempts != fence:
                return stats
            result = await mira_memory.apply_operations(db, current, operations,
                {item['id']: item['version'] for item in memory['items']})
            current.memory_status, current.memory_error, current.memory_lease_until = 'APPLIED', None, None
            await db.commit()
        log.warning('MIRA_DIAGNOSTIC memory meeting=%s applied=%s rejected=%s dropped=%s omitted=%s partial=%s',
            sid, result['applied'], result['rejected'], result['dropped'], memory['omitted'], partial)
        stats['applied'] += 1
    except Exception as exc:
        code = error_code(exc)
        async with SessionLocal() as db:
            current = (await db.execute(select(Meeting).where(Meeting.id == sid).with_for_update()
                .execution_options(populate_existing=True))).scalar_one()
            if current.memory_status == 'RUNNING' and current.memory_attempts == fence:
                failed = current.memory_attempts >= settings.MIRA_MEMORY_MAX_ATTEMPTS
                current.memory_status = 'FAILED' if failed else 'PENDING'
                current.memory_error, current.memory_lease_until = code, None
                stats['failed'] += int(failed)
                await db.commit()
        log.warning('MIRA_DIAGNOSTIC memory meeting=%s stage=extract error=%s attempt=%s', sid, code, fence)
    return stats
