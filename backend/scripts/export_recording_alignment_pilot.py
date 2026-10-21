"""Export one short, already-transcribed recording for an offline timing pilot.

Run from backend/ with the application's venv. No database writes or AI calls.
Private output stays under backend/private-data/alignment-pilot/.
"""
import argparse
import asyncio
import json
import math
import sys
import wave
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from app.db import SessionLocal
from app.models.meeting_recording import MeetingRecording
from app.models.recording_analysis import RecordingTranscript, RecordingAction
from app.services.meeting_recording_storage import LocalMeetingStorage
from app.services.recording_analysis_provider import extract_audio
from app.config import settings


async def export(recording_id):
    async with SessionLocal() as db:
        row = await db.get(MeetingRecording, recording_id)
        if not row or row.status != 'READY' or not 0 < row.duration_seconds <= 60:
            raise ValueError('Pilot requires a READY recording of at most 60 seconds')
        segments = list((await db.execute(select(RecordingTranscript).where(
            RecordingTranscript.recording_id == recording_id).order_by(RecordingTranscript.index))).scalars())
        actions = list((await db.execute(select(RecordingAction).where(
            RecordingAction.recording_id == recording_id))).scalars())
        if not segments or not any(s.text.strip() for s in segments):
            raise ValueError('Recording has no saved transcript')
        source = LocalMeetingStorage(settings.MEETING_RECORDINGS_ROOT).path(
            f"{row.storage_key}/recording.{'webm' if row.mime_type == 'video/webm' else 'mp4'}")
        folder = Path(__file__).resolve().parents[1] / 'private-data' / 'alignment-pilot' / str(recording_id)
        folder.mkdir(parents=True, exist_ok=True)
        audio = extract_audio(source, 0, math.ceil(row.duration_seconds))
        (folder / 'audio.wav').write_bytes(audio)
        with wave.open(str(folder / 'audio.wav'), 'rb') as wav:
            duration = wav.getnframes() / wav.getframerate()
        payload = {'recording_id': str(recording_id), 'duration_seconds': duration,
            'segments': [{'index': s.index, 'start_seconds': s.start_seconds, 'text': s.text} for s in segments],
            'actions': [{'id': str(a.id), 'title': a.title, 'evidence': a.evidence, 'segment_index': a.segment_index} for a in actions]}
        (folder / 'input.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'Private pilot exported: {duration:.2f}s, {len(segments)} transcript segment(s), {len(actions)} action(s). No database changes.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--recording-id', required=True, type=UUID)
    asyncio.run(export(parser.parse_args().recording_id))
