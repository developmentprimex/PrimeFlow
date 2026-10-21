"""Lease-fenced finalization of persisted text; no audio and no Discord login."""
import logging
import uuid
from datetime import timedelta
from sqlalchemy import select, update, or_
from app.db import SessionLocal
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting, DiscordVoiceSegment as Segment
from app.models.user import User
from app.services import discord_voice_meetings as service
from app.services.discord_voice_meetings import now
from app.services import discord_voice_openai as provider
from app.services import mira_memory
from app.config import settings

log=logging.getLogger(__name__)


async def process_voice_meetings():
    stats={'ready':0,'failed':0,'interrupted':0}
    async with SessionLocal() as db:
        result=await db.execute(update(Meeting).where(Meeting.status.in_(['STARTING','LISTENING']),
            Meeting.heartbeat_at<now()-timedelta(seconds=60)).values(status='INTERRUPTED',partial=True,
            stopped_at=now(),error='Dëgjimi u ndërpre.'))
        stats['interrupted']=result.rowcount
        await db.commit()
    # Bound one tick's work; the next tick resumes persisted sessions/progress.
    async with SessionLocal() as db:
        ids=list((await db.execute(select(Meeting.id).where(Meeting.status.in_(['FINALIZING','INTERRUPTED']))
            .order_by(Meeting.created_at).limit(10))).scalars())
    for sid in ids:
        async with SessionLocal() as db:
            row=(await db.execute(select(Meeting).where(Meeting.id==sid).with_for_update(skip_locked=True))).scalar_one_or_none()
            if not row or row.status not in ('FINALIZING','INTERRUPTED') or (row.lease_until and row.lease_until>now()):continue
            if row.expected_segments is None and row.stopped_at and row.stopped_at>now()-timedelta(seconds=60):continue
            segments=list((await db.execute(select(Segment).where(Segment.session_id==sid).order_by(Segment.start_ms,Segment.sequence))).scalars())
            if any(s.status=='PROCESSING' and s.lease_until and s.lease_until>now() for s in segments):continue
            expected=row.expected_segments
            if expected is not None and len(segments)<expected and row.stopped_at>now()-timedelta(seconds=60):continue
            partial=bool(row.partial or expected is None or len(segments)!=(expected or 0) or any(s.status!='DONE' for s in segments))
            parts=[{'sequence':s.sequence,'speaker_id':s.speaker_id,'speaker_name':s.speaker_name,
                'start_ms':s.start_ms,'end_ms':s.end_ms,'transcript':s.transcript}
                for s in segments if s.status=='DONE' and s.transcript]
            if not parts:
                row.status='FAILED';row.error='Nuk u dëgjua të folur i kuptueshëm.';row.partial=partial
                row.memory_status='SKIPPED'
                # A scheduled 1H slot nobody spoke in is not worth a Discord message.
                if service.is_scheduled(row):row.delivered_at=now()
                await db.commit();stats['failed']+=1;continue
            lease=uuid.uuid4();row.lease_token=lease;row.lease_until=now()+timedelta(seconds=180)
            title,cache,meeting_date=row.title,row.summary_progress or {},row.started_at or row.created_at
            memory=None
            if settings.MIRA_MEMORY_ENABLED:
                # Notes never wait on memory: without a snapshot they are written as before.
                try:
                    async with db.begin_nested():memory=await mira_memory.snapshot(db)
                except Exception as exc:
                    log.warning('MIRA_DIAGNOSTIC memory meeting=%s stage=snapshot error=%s',sid,type(exc).__name__)
            await db.commit()
        async def checkpoint(progress):
            async with SessionLocal() as db:
                current=(await db.execute(select(Meeting).where(Meeting.id==sid).with_for_update())).scalar_one()
                if current.lease_token!=lease:raise ValueError('finalization_lease_changed')
                current.summary_progress=dict(progress);current.lease_until=now()+timedelta(seconds=180)
                await db.commit()
        try:
            try:
                draft=await provider.summarize_meeting(title,parts,meeting_date=meeting_date,
                    cache=cache,checkpoint=checkpoint,memory=memory)
            except ValueError:
                if memory is None:raise
                # Memory must never cost the notes: write them as before.
                log.warning('MIRA_DIAGNOSTIC memory meeting=%s stage=notes fallback=no_memory',sid)
                draft=await provider.summarize_meeting(title,parts,meeting_date=meeting_date,
                    cache=cache,checkpoint=checkpoint)
            error=None
        except ValueError:
            draft=None;error='Përmbledhja dështoi. Transkripti i marrë mbetet i ruajtur.'
        async with SessionLocal() as db:
            current=(await db.execute(select(Meeting).where(Meeting.id==sid).with_for_update())).scalar_one()
            if current.lease_token!=lease or current.status not in ('FINALIZING','INTERRUPTED'):continue
            current.status='FAILED' if error else 'READY';current.error=error
            current.draft_text=draft;current.partial=partial;current.lease_until=None
            current.memory_status='PENDING' if settings.MIRA_MEMORY_ENABLED else 'SKIPPED'
            if service.is_scheduled(current):
                # Scheduled 1H meetings go straight to PX Notes, in the same commit so
                # Discord delivery never sees them READY. If saving fails, the savepoint
                # rolls back and the notes are delivered in Discord as usual.
                try:
                    async with db.begin_nested():
                        if not error:await service.store_note(db,current,await db.get(User,current.user_id))
                        current.delivered_at=now()
                except Exception:
                    pass
            await db.commit();stats['failed' if error else 'ready']+=1
    return stats
