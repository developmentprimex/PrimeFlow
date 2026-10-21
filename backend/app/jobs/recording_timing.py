"""Opt-in timing worker: python -m app.jobs.recording_timing.

Separate from Celery/transcription. A PostgreSQL session advisory lock permits
one active timing process across workers, with segment checkpoints on restart.
"""
import asyncio
import json
import math
import os
import re
from pathlib import Path
import subprocess
import tempfile
from sqlalchemy import select, text
from app.config import settings
from app.db import SessionLocal, engine
from app.models.recording_analysis import RecordingAnalysis as Analysis, RecordingAction as Action, RecordingTranscript as Transcript
from app.models.meeting_recording import MeetingRecording
from app.services.meeting_recording_storage import LocalMeetingStorage

LOCK_ID = 74150621
RUNNER = Path(__file__).resolve().parents[2] / 'scripts' / 'recording_citation_times.py'


def unique_evidence(evidence, segments):
    target = re.findall(r'\w+', evidence.lower())
    source = re.findall(r'\w+', ' '.join(s.text for s in segments).lower())
    return bool(target) and sum(source[i:i + len(target)] == target for i in range(len(source) - len(target) + 1)) == 1


def measure_segment(source, segment, actions):
    # Extract only the segment that has relevant citations. No video upload.
    start, duration = segment.start_seconds, segment.duration_seconds
    lead = min(2, start)
    with tempfile.TemporaryDirectory(prefix='primeflow-timing-') as directory:
        folder = Path(directory)
        flags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 0
        subprocess.run([settings.MEETING_RECORDINGS_FFMPEG, '-nostdin', '-v', 'error', '-threads', '1',
            '-ss', str(start - lead), '-i', str(source), '-t', str(duration + lead), '-vn',
            '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(folder / 'audio.wav')],
            check=True, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        payload = {'text': segment.text, 'actions': [{'id': str(a.id), 'evidence': a.evidence} for a in actions]}
        (folder / 'input.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        subprocess.run([settings.RECORDING_TIMING_PYTHON, str(RUNNER), '--input', str(folder / 'input.json'),
            '--cache', str(Path(settings.RECORDING_TIMING_MODEL_CACHE).resolve()), '--parent-pid', str(os.getpid())], check=True, timeout=1800,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        result = json.loads((folder / 'output.json').read_text(encoding='utf-8'))
        expected = {str(a.id) for a in actions}
        timings = {}
        for item in result['actions']:
            if item['id'] not in expected:
                raise ValueError('invalid_timing_action')
            first, last = item['start'], item['end']
            if first is not None:
                if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (first, last)) or not 0 <= first < last <= duration + lead + 0.1:
                    raise ValueError('invalid_timing_range')
                first, last = round(first + start - lead, 3), round(last + start - lead, 3)
            timings[item['id']] = {'start': first, 'end': last, 'approximate': True}
        if set(timings) != expected:
            raise ValueError('missing_timing_actions')
        return timings


async def process_locked():
    async with SessionLocal() as db:
        job = (await db.execute(select(Analysis).where(
            Analysis.timing['status'].astext.in_(['QUEUED', 'RUNNING']))
            .order_by(Analysis.created_at).with_for_update(skip_locked=True).limit(1))).scalar_one_or_none()
        if not job:
            return 0
        sid = job.recording_id
        progress = dict(job.timing)
        segments = list((await db.execute(select(Transcript).where(Transcript.recording_id == sid).order_by(Transcript.index))).scalars())
        actions = list((await db.execute(select(Action).where(Action.recording_id == sid))).scalars())
        relevant = [s for s in segments if any(a.segment_index == s.index for a in actions)]
        done = progress.get('done', [])
        pending = next((s for s in relevant if s.index not in done), None)
        progress.update(status='RUNNING' if pending else 'READY', total=len(relevant), completed=len(done), error=None)
        job.timing = progress
        row = await db.get(MeetingRecording, sid)
        source = LocalMeetingStorage(settings.MEETING_RECORDINGS_ROOT).path(
            f"{row.storage_key}/recording.{'webm' if row.mime_type == 'video/webm' else 'mp4'}")
        await db.commit()
    if not pending:
        return 1
    try:
        selected = [a for a in actions if a.segment_index == pending.index]
        unambiguous = [a for a in selected if unique_evidence(a.evidence, segments)]
        results = {str(a.id): {'start': None, 'end': None, 'approximate': True} for a in selected}
        if unambiguous:
            results.update(await asyncio.to_thread(measure_segment, source, pending, unambiguous))
        progress.update(results={**progress.get('results', {}), **results}, done=[*done, pending.index],
                        completed=len(done) + 1, status='READY' if len(done) + 1 == len(relevant) else 'RUNNING')
    except Exception:
        progress.update(status='FAILED', error='Gjetja e kohëve u ndërpre. Rezultatet e përfunduara ruhen; mund të riprovoni.')
    async with SessionLocal() as db:
        current = await db.get(Analysis, sid)
        if current:
            current.timing = progress
            await db.commit()
    return 1


async def process_recording_timings():
    if not settings.RECORDING_TIMING_ENABLED or not settings.RECORDING_TIMING_PYTHON:
        return 0
    # Dedicated connection retains the lock across checkpoint commits.
    async with engine.connect() as connection:
        acquired = (await connection.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': LOCK_ID})).scalar()
        await connection.commit()
        if not acquired:
            return 0
        try:
            return await process_locked()
        finally:
            await connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': LOCK_ID})
            await connection.commit()


async def main():
    while True:
        try:
            worked = await process_recording_timings()
        except Exception:
            worked = 0
        await asyncio.sleep(1 if worked else 5)


if __name__ == '__main__':
    asyncio.run(main())
