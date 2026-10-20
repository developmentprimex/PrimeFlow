"""Restart-safe, fenced analysis. Celery beat or `python -m app.jobs.recording_analysis`."""
import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, or_
from app.config import settings
from app.db import SessionLocal
from app.models.meeting_recording import MeetingRecording
from app.models.recording_analysis import RecordingAnalysis as Analysis, RecordingTranscript as Transcript, RecordingAction as Action
from app.services.meeting_recording_storage import LocalMeetingStorage


def now():
    return datetime.now(timezone.utc)


async def process_recording_analyses():
    if not settings.RECORDING_ANALYSIS_ENABLED or not settings.OPENAI_API_KEY:
        return 0
    from app.services import recording_analysis_provider as provider
    from app.services.discord_voice_openai import summarize_meeting
    async with SessionLocal() as db:
        job = (await db.execute(select(Analysis).where(Analysis.status.in_(['QUEUED', 'TRANSCRIBING', 'SUMMARIZING']),
            or_(Analysis.lease_until.is_(None), Analysis.lease_until < now())).order_by(Analysis.updated_at)
            .with_for_update(skip_locked=True).limit(1))).scalar_one_or_none()
        if not job:
            return 0
        sid, token = job.recording_id, uuid.uuid4()
        job.lease_token, job.lease_until = token, now() + timedelta(minutes=10)
        row = await db.get(MeetingRecording, sid)
        source = LocalMeetingStorage(settings.MEETING_RECORDINGS_ROOT).path(
            f"{row.storage_key}/recording.{'webm' if row.mime_type == 'video/webm' else 'mp4'}")
        title, partial, duration, language = row.title, row.is_partial, row.duration_seconds, job.language
        await db.commit()

    async def fenced(db):
        current = (await db.execute(select(Analysis).where(Analysis.recording_id == sid).with_for_update())).scalar_one()
        if current.lease_token != token:
            raise ValueError('analysis_lease_changed')
        current.lease_until = now() + timedelta(minutes=10)
        return current

    async def checkpoint(cache):
        async with SessionLocal() as db:
            current = await fenced(db)
            current.summary_progress = dict(cache)
            await db.commit()

    try:
        async with SessionLocal() as db:
            current = await fenced(db)
            segments = list((await db.execute(select(Transcript).where(Transcript.recording_id == sid).order_by(Transcript.index))).scalars())
            pending = next(((i, start, length) for i, (start, length) in enumerate(provider.segment_plan(duration))
                if not any(s.index == i and s.notes is not None for s in segments)), None)
            current.status = 'TRANSCRIBING' if pending else 'SUMMARIZING'
            await db.commit()
        if pending:
            index, start, length = pending
            segment = next((s for s in segments if s.index == index), None)
            if segment is None:
                wav = await asyncio.to_thread(provider.extract_audio, source, start, length)
                text = await provider.transcribe(wav, language)
                del wav
                async with SessionLocal() as db:
                    await fenced(db)
                    segment = Transcript(recording_id=sid, index=index, start_seconds=start, duration_seconds=length, text=text)
                    db.add(segment)
                    await db.commit()
            notes = await provider.extract_notes(segment.text)
            async with SessionLocal() as db:
                current = await fenced(db)
                stored = await db.get(Transcript, (sid, index))
                stored.notes = notes
                current.segments_done += 1
                current.lease_until = None
                await db.commit()
            return 1
        parts = [{'sequence': s.index, 'start_ms': s.start_seconds * 1000,
                  'end_ms': (s.start_seconds + s.duration_seconds) * 1000, 'transcript': s.text}
                 for s in segments if s.text.strip()]
        if not parts:
            raise ValueError('empty_transcript')
        async with SessionLocal() as db:
            current = await fenced(db)
            cache = current.summary_progress
            await db.commit()
        summary = await summarize_meeting(title, parts, partial=partial, cache=cache, checkpoint=checkpoint,
            model=settings.RECORDING_ANALYSIS_MODEL)
        async with SessionLocal() as db:
            current = await fenced(db)
            fingerprints = set()
            for segment in segments:
                for action in (segment.notes or {}).get('actions', []):
                    fingerprint = hashlib.sha256((' '.join(action['title'].casefold().split()) + '\n' + ' '.join(action['evidence'].casefold().split())).encode()).hexdigest()
                    if fingerprint in fingerprints:
                        continue
                    fingerprints.add(fingerprint)
                    db.add(Action(recording_id=sid, segment_index=segment.index, fingerprint=fingerprint, **action))
            current.status, current.summary, current.error_message = 'READY', summary, None
            current.lease_until = None
            await db.commit()
    except Exception as exc:
        # Never log provider bodies, transcript text, credentials or user media paths.
        async with SessionLocal() as db:
            current = (await db.execute(select(Analysis).where(Analysis.recording_id == sid).with_for_update())).scalar_one()
            if current.lease_token == token:
                current.status, current.lease_until = 'FAILED', None
                current.error_message = ('Nuk u dëgjua të folur i kuptueshëm.' if str(exc) == 'empty_transcript' else
                    'Përpunimi dështoi. Kontrolloni konfigurimin dhe lidhjen me shërbimin AI, pastaj riprovoni. Transkripti i përpunuar ruhet.')
                await db.commit()
    return 1


async def run_worker():
    while True:
        try:
            worked = await process_recording_analyses()
        except Exception:
            worked = 0
        await asyncio.sleep(0.1 if worked else 3)


if __name__ == '__main__':
    asyncio.run(run_worker())
