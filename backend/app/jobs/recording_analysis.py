"""Restart-safe, fenced analysis. Celery beat or `python -m app.jobs.recording_analysis`."""
import asyncio
import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select, or_
from app.config import settings
from app.db import SessionLocal
from app.models.department import Department
from app.models.meeting import MeetingParticipant
from app.models.meeting_recording import MeetingRecording
from app.models.recording_analysis import RecordingAnalysis as Analysis, RecordingTranscript as Transcript, RecordingAction as Action
from app.models.user import User
from app.services.meeting_recording_storage import LocalMeetingStorage

MAX_ATTEMPTS = 3
# Failures that retrying cannot fix go straight to FAILED.
PERMANENT_ERRORS = {'empty_transcript', 'invalid_recording_duration', 'audio_extraction_failed', 'invalid_audio_format'}


def now():
    return datetime.now(timezone.utc)


async def load_people(db, row):
    """Active staff with the recording's meeting participants first, so they survive the prompt cap."""
    participants = set()
    if row.meeting_id:
        participants = set((await db.execute(select(MeetingParticipant.user_id)
            .where(MeetingParticipant.meeting_id == row.meeting_id))).scalars())
    participants.add(row.created_by)
    users = (await db.execute(select(User.id, User.full_name).where(User.is_active.is_(True)).order_by(User.full_name))).all()
    people = sorted(((u.id, u.full_name) for u in users if u.full_name), key=lambda p: p[0] not in participants)
    departments = (await db.execute(select(Department.name).order_by(Department.name))).scalars().all()
    return people, [p for p in people if p[0] in participants], list(departments)


async def process_recording_analyses():
    if not settings.RECORDING_ANALYSIS_ENABLED or not settings.OPENAI_API_KEY:
        return 0
    from app.services import recording_analysis_provider as provider
    async with SessionLocal() as db:
        job = (await db.execute(select(Analysis).where(Analysis.status.in_(['QUEUED', 'TRANSCRIBING', 'SUMMARIZING']),
            or_(Analysis.lease_until.is_(None), Analysis.lease_until < now())).order_by(Analysis.updated_at)
            .with_for_update(skip_locked=True).limit(1))).scalar_one_or_none()
        if not job:
            return 0
        sid, token = job.recording_id, uuid.uuid4()
        job.lease_token, job.lease_until = token, now() + timedelta(minutes=15)
        row = await db.get(MeetingRecording, sid)
        source = LocalMeetingStorage(settings.MEETING_RECORDINGS_ROOT).path(
            f"{row.storage_key}/recording.{'webm' if row.mime_type == 'video/webm' else 'mp4'}")
        title, duration, language = row.title, row.duration_seconds, job.language
        meeting_day = row.recording_started_at.astimezone(ZoneInfo(settings.APP_TIMEZONE)).date()
        people, participants, departments = await load_people(db, row)
        await db.commit()

    async def fenced(db):
        current = (await db.execute(select(Analysis).where(Analysis.recording_id == sid).with_for_update())).scalar_one()
        if current.lease_token != token:
            raise ValueError('analysis_lease_changed')
        current.lease_until = now() + timedelta(minutes=15)
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
            done = {s.index for s in segments}
            pending = next(((i, start, length) for i, (start, length) in enumerate(provider.segment_plan(duration))
                if i not in done), None)
            current.status = 'TRANSCRIBING' if pending else 'SUMMARIZING'
            await db.commit()
        if pending:
            index, start, length = pending
            previous = next((s.text for s in segments if s.index == index - 1), '')
            vocabulary = [name for _, name in people] + departments + [
                t.strip() for t in settings.RECORDING_TRANSCRIPTION_VOCABULARY.split(',') if t.strip()]
            wav = await asyncio.to_thread(provider.extract_audio, source, start, length)
            text = await provider.transcribe(wav, language, vocabulary=vocabulary, previous=previous)
            del wav
            async with SessionLocal() as db:
                current = await fenced(db)
                db.add(Transcript(recording_id=sid, index=index, start_seconds=start, duration_seconds=length, text=text))
                current.segments_done = len(done) + 1
                current.attempts, current.error_message, current.lease_until = 0, None, None
                await db.commit()
            return 1
        rows = [{'index': s.index, 'start_seconds': s.start_seconds, 'duration_seconds': s.duration_seconds, 'text': s.text}
                for s in segments]
        async with SessionLocal() as db:
            current = await fenced(db)
            cache = current.summary_progress
            await db.commit()
        notes = await provider.analyze_meeting(title, rows, meeting_day=meeting_day,
            participants=[name for _, name in participants], cache=cache, checkpoint=checkpoint)
        async with SessionLocal() as db:
            current = await fenced(db)
            fingerprints = set()
            for action in notes['actions']:
                fingerprint = hashlib.sha256((provider.normalize(action['title']) + '\n' + provider.normalize(action['evidence'])).encode()).hexdigest()
                if fingerprint in fingerprints:
                    continue
                fingerprints.add(fingerprint)
                db.add(Action(recording_id=sid, segment_index=provider.evidence_segment(action['evidence'], rows),
                    fingerprint=fingerprint, title=action['title'], description=action['description'], evidence=action['evidence'],
                    assignee_text=action['assignee_text'], deadline_text=action['deadline_text'],
                    suggested_assignee_id=provider.match_person(action['assignee_text'], people),
                    suggested_due_date=action['due_date']))
            # Default recorder titles already carry the date; add it only when missing.
            heading = title if re.search(r'\d{1,2}\.\d{1,2}\.\d{4}', title) else provider.albanian_date_for(meeting_day) + '\n' + title
            current.status, current.summary, current.decisions = 'READY', heading + '\n\n' + notes['summary'], notes['decisions']
            current.error_message, current.attempts, current.lease_until = None, 0, None
            await db.commit()
    except Exception as exc:
        # Never log provider bodies, transcript text, credentials or user media paths.
        async with SessionLocal() as db:
            current = (await db.execute(select(Analysis).where(Analysis.recording_id == sid).with_for_update())).scalar_one()
            if current.lease_token == token:
                current.attempts = (current.attempts or 0) + 1
                if str(exc) not in PERMANENT_ERRORS and current.attempts < MAX_ATTEMPTS:
                    # Transient provider or network failure: back off and let the next tick resume from the checkpoint.
                    current.lease_until = now() + timedelta(minutes=current.attempts)
                    current.error_message = 'Shërbimi AI nuk u përgjigj. Do të riprovohet automatikisht.'
                else:
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
