"""Real PostgreSQL/migration, FFmpeg and Tasks flow; provider responses are mocked."""
import asyncio
import hashlib
import tempfile
import subprocess
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch
from recording_test_support import TEST_URL


@unittest.skipUnless(TEST_URL, 'Requires isolated primeflow_recorder_test database')
class AnalysisApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from recording_test_support import prepare_database
        cls.fixture = prepare_database(full_schema=True)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.routers.meeting_recordings import router
        from app.api.routers.recording_analysis import router as ai_router
        from app.config import settings
        from app.db import get_db
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy.pool import NullPool
        cls.settings = settings
        cls.tmp = tempfile.TemporaryDirectory()
        cls.patches = [patch.object(settings, 'MEETING_RECORDINGS_ROOT', cls.tmp.name),
            patch.object(settings, 'OPENAI_API_KEY', 'test-provider-never-sent'), patch.object(settings, 'REDIS_ENABLED', False),
            patch.object(settings, 'REALIZATION_DAILY_ENABLED', False)]
        for p in cls.patches: p.start()
        engine = create_async_engine(TEST_URL.replace('postgresql://', 'postgresql+asyncpg://', 1), poolclass=NullPool)
        cls.session = async_sessionmaker(engine, expire_on_commit=False)
        async def get_test_db():
            async with cls.session() as db: yield db
        app = FastAPI()
        app.dependency_overrides[get_db] = get_test_db
        app.include_router(router, prefix='/api/meeting-recordings')
        app.include_router(ai_router, prefix='/api/meeting-recordings')
        cls.client = TestClient(app)
        cls.app = app
        cls.worker_patch = patch('app.jobs.recording_analysis.SessionLocal', cls.session)
        cls.worker_patch.start()
        media = Path(cls.tmp.name) / 'source.webm'
        subprocess.run([settings.MEETING_RECORDINGS_FFMPEG, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc=size=160x90:rate=10',
            '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1.2', '-c:v', 'libvpx', '-c:a', 'libopus', str(media)], check=True)
        cls.media = media.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.client.close(); cls.worker_patch.stop()
        for p in cls.patches: p.stop()
        cls.tmp.cleanup()

    def auth(self, who='owner'):
        return {'Authorization': 'Bearer ' + self.fixture[who]['token']}

    def saved(self):
        response = self.client.post('/api/meeting-recordings', headers=self.auth(), json={
            'title': 'AI ' + str(uuid.uuid4()), 'mime_type': 'video/webm', 'capture_source_type': 'browser',
            'consent_acknowledged': True, 'has_system_audio': True, 'meeting_id': self.fixture['meeting_id']})
        self.assertEqual(response.status_code, 201, response.text)
        sid = response.json()['id']
        response = self.client.put(f'/api/meeting-recordings/{sid}/chunks/0', headers={**self.auth(),
            'Content-Type': 'application/octet-stream', 'X-Chunk-SHA256': hashlib.sha256(self.media).hexdigest()}, content=self.media)
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(f'/api/meeting-recordings/{sid}/complete', headers=self.auth(), json={'chunks': 1})
        self.assertEqual(response.status_code, 200, response.text)
        return sid

    def get(self, sid, who='owner'):
        return self.client.get(f'/api/meeting-recordings/{sid}/analysis', headers=self.auth(who))

    def start(self, sid):
        return self.client.post(f'/api/meeting-recordings/{sid}/analysis', headers=self.auth(), json={'consent_acknowledged': True, 'language': 'sq'})

    def tick(self):
        from app.jobs.recording_analysis import process_recording_analyses
        return asyncio.run(process_recording_analyses())

    def test_audio_format_reaches_meeting_client_history_and_action_note(self):
        from app.api.routers.meeting_notes import router as notes_router
        from app.models.meeting import Meeting
        from app.models.project import Project
        from app.models.recording_analysis import RecordingAction, RecordingAnalysis

        meeting_id = uuid.UUID(self.fixture["meeting_id"])
        owner_id = uuid.UUID(self.fixture["owner"]["id"])

        async def link_project():
            async with self.session() as db:
                project = Project(title="Voice recording client")
                db.add(project)
                await db.flush()
                meeting = await db.get(Meeting, meeting_id)
                meeting.project_id = project.id
                await db.commit()
                return str(project.id)

        project_id = asyncio.run(link_project())
        self.app.include_router(notes_router, prefix="/api/meeting-notes")
        response = self.client.post("/api/meeting-recordings", headers=self.auth(), json={
            "title": "Physical meeting", "meeting_id": str(meeting_id), "project_id": project_id,
            "mime_type": "audio/webm", "capture_source_type": "microphone",
            "consent_acknowledged": True, "has_microphone_audio": True,
        })
        self.assertEqual(response.status_code, 201, response.text)
        recording_id = response.json()["id"]
        self.assertEqual(response.json()["project_id"], project_id)
        media = subprocess.check_output([
            self.settings.MEETING_RECORDINGS_FFMPEG, "-v", "error", "-i", str(Path(self.tmp.name) / "source.webm"),
            "-map", "0:a", "-c:a", "copy", "-f", "webm", "pipe:1",
        ], timeout=30)
        response = self.client.put(f"/api/meeting-recordings/{recording_id}/chunks/0", headers={
            **self.auth(), "Content-Type": "application/octet-stream", "X-Chunk-SHA256": hashlib.sha256(media).hexdigest(),
        }, content=media)
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(f"/api/meeting-recordings/{recording_id}/complete", headers=self.auth(), json={"chunks": 1})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "READY")
        self.assertIsNone(response.json()["video_width"])

        async def add_proposal():
            async with self.session() as db:
                sid = uuid.UUID(recording_id)
                db.add(RecordingAnalysis(recording_id=sid, requested_by=owner_id, status="READY", language="sq",
                                         total_segments=1, segments_done=1))
                await db.flush()
                action = RecordingAction(recording_id=sid, fingerprint="a" * 64, segment_index=0,
                                         title="Physical meeting follow-up", description="", evidence="Follow up")
                db.add(action)
                await db.commit()
                return str(action.id)

        action_id = asyncio.run(add_proposal())
        response = self.client.post(f"/api/meeting-notes/recordings/{recording_id}/actions/{action_id}/note", headers=self.auth())
        self.assertEqual(response.status_code, 200, response.text)
        note = response.json()
        self.assertEqual(note["recording_mime_type"], "audio/webm")
        meeting_path = f"/api/meeting-notes/meetings/{meeting_id}"
        response = self.client.get(meeting_path, headers=self.auth())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(recording_id, [rec["id"] for session in response.json()["sessions"]
                                    for rec in session["recordings"] if rec["mime_type"] == "audio/webm"])
        response = self.client.get(meeting_path + "/notes", headers=self.auth())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(next(row for row in response.json() if row["id"] == note["id"])["recording_mime_type"], "audio/webm")
        response = self.client.get("/api/meeting-notes/client-history", headers=self.auth(), params={
            "project_id": project_id, "date_from": note["occurrence_date"], "date_to": note["occurrence_date"],
        })
        self.assertEqual(response.status_code, 200, response.text)
        history = response.json()["sessions"][0]
        self.assertIn(recording_id, [rec["id"] for rec in history["recordings"] if rec["mime_type"] == "audio/webm"])
        self.assertEqual(history["notes"][0]["recording_mime_type"], "audio/webm")
        response = self.client.post(f"/api/meeting-notes/recordings/{recording_id}/screenshot", headers=self.auth(),
                                    files={"file": ("frame.png", b"frame", "image/png")})
        self.assertEqual(response.status_code, 422, response.text)

    def test_citation_times_are_explicit_cached_authorized_and_restart_safe(self):
        from app.jobs import recording_timing as worker
        from app.models.recording_analysis import RecordingAnalysis, RecordingAction, RecordingTranscript
        from sqlalchemy import text
        from types import SimpleNamespace
        repeated = [SimpleNamespace(text='Dergo raportin.'), SimpleNamespace(text='Dergo raportin.')]
        self.assertFalse(worker.unique_evidence('Dergo raportin', repeated))
        self.assertFalse(worker.unique_evidence('Mungon citimi', repeated))
        self.assertTrue(worker.unique_evidence('Dergo raportin', repeated[:1]))
        async def competing_worker():
            async with self.session.kw['bind'].connect() as lock:
                await lock.execute(text('SELECT pg_advisory_lock(:key)'), {'key': worker.LOCK_ID})
                try:
                    with patch.object(worker, 'engine', self.session.kw['bind']), patch.object(worker, 'process_locked', new=AsyncMock()) as process:
                        self.assertEqual(await worker.process_recording_timings(), 0)
                        process.assert_not_awaited()
                finally:
                    await lock.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': worker.LOCK_ID})
        sid = self.saved()
        async def seed():
            async with self.session() as db:
                db.add(RecordingAnalysis(recording_id=uuid.UUID(sid), requested_by=uuid.UUID(self.fixture['owner']['id']),
                    status='READY', language='sq', total_segments=2, segments_done=2))
                await db.flush()
                for index in range(2):
                    db.add(RecordingTranscript(recording_id=uuid.UUID(sid), index=index, start_seconds=index * 300,
                        duration_seconds=20, text=f'Dergo raportin {index}.'))
                    db.add(RecordingAction(recording_id=uuid.UUID(sid), segment_index=index, fingerprint=str(index),
                        title='Dergo raportin', description='', evidence=f'Dergo raportin {index}.'))
                await db.commit()
        asyncio.run(seed())
        url = f'/api/meeting-recordings/{sid}/citation-times'
        with patch.object(self.settings, 'RECORDING_TIMING_ENABLED', True), patch.object(self.settings, 'RECORDING_TIMING_PYTHON', 'isolated-python'), patch.object(worker, 'SessionLocal', self.session):
            asyncio.run(competing_worker())
            self.assertIsNone(self.get(sid).json()['timing'])
            self.assertEqual(asyncio.run(worker.process_locked()), 0, 'Reading/creating a recording must not enqueue timing')
            for who in ['participant', 'other', 'manager']:
                self.assertEqual(self.client.post(url, headers=self.auth(who)).status_code, 404)
            self.assertEqual(self.client.post(url, headers=self.auth()).status_code, 202)
            requested = self.get(sid).json()['timing']['requested_at']
            self.client.post(url, headers=self.auth())
            self.assertEqual(self.get(sid).json()['timing']['requested_at'], requested)
            def result(source, segment, actions):
                return {str(a.id): {'start': segment.start_seconds + 1.2, 'end': segment.start_seconds + 2, 'approximate': True} for a in actions}
            with patch.object(worker, 'measure_segment', side_effect=result) as measure:
                asyncio.run(worker.process_locked())
                self.assertEqual(self.get(sid).json()['timing']['completed'], 1)
                self.client.post(url, headers=self.auth())
                with patch.object(worker, 'measure_segment', side_effect=RuntimeError('private detail')):
                    asyncio.run(worker.process_locked())
                failed = self.get(sid).json()['timing']
                self.assertEqual(failed['status'], 'FAILED')
                self.assertNotIn('private detail', failed['error'])
                self.assertEqual(failed['done'], [0])
                self.client.post(url, headers=self.auth())
                asyncio.run(worker.process_locked())
                self.assertEqual(measure.call_count, 2, 'Retry must skip completed segments')
                ready = self.get(sid, 'participant').json()['timing']
                self.assertEqual(ready['status'], 'READY')
                self.assertEqual(len(ready['results']), 2)
                self.client.post(url, headers=self.auth())
                self.assertEqual(asyncio.run(worker.process_locked()), 0)
                self.assertEqual(measure.call_count, 2)

    def test_authorization_consent_and_provider_configuration(self):
        from app.models.recording_analysis import RecordingAnalysis

        async def remove_job(recording_id):
            async with self.session() as db:
                job = await db.get(RecordingAnalysis, uuid.UUID(recording_id))
                if job is not None:
                    await db.delete(job)
                    await db.commit()

        sid = self.saved()
        self.assertEqual(self.get(sid, 'other').status_code, 200)
        self.assertEqual(self.get(sid, 'participant').status_code, 200)
        for who in ['other', 'participant', 'manager']:
            sid = self.saved()
            self.addCleanup(lambda recording_id=sid: asyncio.run(remove_job(recording_id)))
            self.assertTrue(self.get(sid, who).json()['can_start_analysis'])
            response = self.client.post(f'/api/meeting-recordings/{sid}/analysis', headers=self.auth(who), json={'consent_acknowledged': True})
            self.assertEqual(response.status_code, 202, response.text)
            self.assertFalse(self.get(sid, who).json()['can_manage'])
            # Repeated starts by another viewer reuse the existing job.
            self.assertEqual(self.start(sid).status_code, 202)
            async def requester():
                async with self.session() as db:
                    return str((await db.get(RecordingAnalysis, uuid.UUID(sid))).requested_by)
            self.assertEqual(asyncio.run(requester()), self.fixture[who]['id'])
        self.assertEqual(self.client.post(f'/api/meeting-recordings/{sid}/analysis', headers=self.auth(), json={'consent_acknowledged': False}).status_code, 422)
        with patch.object(self.settings, 'OPENAI_API_KEY', None):
            self.assertFalse(self.get(sid).json()['configured'])
            self.assertEqual(self.start(sid).status_code, 503)

    def test_durable_failure_retry_summary_and_atomic_task_confirmation(self):
        sid = self.saved()
        self.assertEqual(self.start(sid).status_code, 202)
        from datetime import date
        notes = {'summary': 'Përmbledhja e takimit', 'decisions': ['Raporti dërgohet nesër'], 'actions': [{'title': 'Dërgo raportin',
            'description': 'Dërgo raportin e takimit.', 'evidence': 'Do ta dërgoj raportin @other nesër.', 'assignee_text': 'Owner',
            'deadline_text': 'nesër', 'due_date': date(2026, 10, 21)}]}
        async def expire_backoff():
            from app.models.recording_analysis import RecordingAnalysis
            async with self.session() as db:
                job = await db.get(RecordingAnalysis, uuid.UUID(sid))
                job.lease_until = None
                await db.commit()
        with patch('app.services.recording_analysis_provider.transcribe', new=AsyncMock(return_value='Do ta dërgoj raportin @other nesër.')) as transcribe:
            self.tick()
            with patch('app.services.recording_analysis_provider.analyze_meeting', new=AsyncMock(side_effect=ValueError('meeting_provider_failed'))):
                self.tick()
            data = self.get(sid).json()
            self.assertEqual(data['analysis']['status'], 'SUMMARIZING', 'Transient failures retry automatically')
            self.assertIn('automatikisht', data['analysis']['error_message'])
            self.assertEqual(data['segments'][0]['text'], 'Do ta dërgoj raportin @other nesër.')
            self.assertEqual(self.tick(), 0, 'Backoff delays the automatic retry')
            asyncio.run(expire_backoff())
            with patch('app.services.recording_analysis_provider.analyze_meeting', new=AsyncMock(return_value=notes)):
                self.tick()
            self.assertEqual(transcribe.await_count, 1, 'Persisted transcript must survive worker restart/retry')
        data = self.get(sid).json()
        self.assertEqual(data['analysis']['status'], 'READY', data)
        self.assertEqual(len(data['actions']), 1)
        self.assertEqual(data['analysis']['decisions'], ['Raporti dërgohet nesër'])
        action = data['actions'][0]
        self.assertEqual(action['suggested_due_date'], '2026-10-21')
        self.assertIsNone(action['created_task_id'])
        self.assertEqual(self.start(sid).status_code, 202)
        self.assertEqual(data['transcript_review']['status'], 'QUEUED')
        with patch('app.services.recording_analysis_provider.transcribe', new=AsyncMock(return_value='Do ta dërgoj raportin nesër.')) as listen, \
                patch('app.services.recording_analysis_provider.refine_transcript',
                      new=AsyncMock(return_value='Do ta dërgoj raportin nesër.')):
            self.assertEqual(self.tick(), 1)
            self.assertTrue(listen.await_args.kwargs['review'])
        corrected = self.get(sid).json()
        self.assertEqual(corrected['transcript_review'], {'status': 'READY', 'completed': 1})
        self.assertEqual(corrected['segments'][0]['corrected_text'], 'Do ta dërgoj raportin nesër.')
        self.assertEqual(corrected['segments'][0]['text'], data['segments'][0]['text'])
        self.assertEqual(corrected['actions'], data['actions'])
        self.assertEqual(self.tick(), 0)
        async def department():
            from app.models.user import User
            async with self.session() as db:
                person = await db.get(User, uuid.UUID(self.fixture['owner']['id']))
                return str(person.department_id)
        body = {'title': 'Dërgo raportin e rishikuar', 'department_id': asyncio.run(department()), 'assigned_to': self.fixture['owner']['id']}
        path = f"/api/meeting-recordings/{sid}/actions/{action['id']}/task"
        for who in ['other', 'participant', 'manager']:
            self.assertEqual(self.client.post(path, headers=self.auth(who), json=body).status_code, 404)
        self.assertEqual(self.client.post(path, headers=self.auth(), json={**body, 'ga_note_origin_id': str(uuid.uuid4())}).status_code, 422)
        first = self.client.post(path, headers=self.auth(), json=body)
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post(path, headers=self.auth(), json=body)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(second.json()['duplicate'])
        self.assertEqual(first.json()['task_id'], second.json()['task_id'])
        async def verify_px_note():
            from app.models.task import Task
            from app.models.ga_note import GaNote
            async with self.session() as db:
                task = await db.get(Task, uuid.UUID(first.json()['task_id']))
                self.assertEqual(str(task.ga_note_origin_id), first.json()['ga_note_id'])
                note = await db.get(GaNote, task.ga_note_origin_id)
                self.assertTrue(note.is_converted_to_task)
                self.assertEqual(note.knowledge_type, 'RECORDING')
                self.assertEqual(note.content, task.title)
        asyncio.run(verify_px_note())
        async def unintended_notifications():
            from sqlalchemy import select, func
            from app.models.notification import Notification
            async with self.session() as db:
                return await db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == uuid.UUID(self.fixture['other']['id'])))
        self.assertEqual(asyncio.run(unintended_notifications()), 0, 'Quoted evidence must not notify an unselected @mentioned user')
        from fastapi.testclient import TestClient
        with TestClient(self.app) as restarted:
            reloaded = restarted.get(f'/api/meeting-recordings/{sid}/analysis', headers=self.auth()).json()
        self.assertEqual(reloaded['actions'][0]['created_task_id'], first.json()['task_id'])
        self.assertTrue(reloaded['analysis']['summary'].endswith('Përmbledhja e takimit'))

    def test_worker_claim_fencing_and_expired_lease_recovery(self):
        from datetime import datetime, timedelta, timezone
        from app.models.recording_analysis import RecordingAnalysis
        sid = self.saved()
        self.assertEqual(self.start(sid).status_code, 202)
        async def lease(expired):
            async with self.session() as db:
                job = await db.get(RecordingAnalysis, uuid.UUID(sid))
                job.status = 'TRANSCRIBING'
                job.lease_token = uuid.uuid4()
                job.lease_until = datetime.now(timezone.utc) + timedelta(minutes=-1 if expired else 10)
                await db.commit()
        asyncio.run(lease(False))
        with patch('app.services.recording_analysis_provider.transcribe', new=AsyncMock(return_value='')) as provider:
            self.assertEqual(self.tick(), 0)
            provider.assert_not_awaited()
            asyncio.run(lease(True))
            self.assertEqual(self.tick(), 1)
            provider.assert_awaited_once()
        self.tick()  # Empty speech must fail without fabricating a summary.
        data = self.get(sid).json()
        self.assertEqual(data['analysis']['status'], 'FAILED')
        self.assertEqual(data['actions'], [])
        self.assertIsNone(data['analysis']['summary'])
        original = self.client.get(f'/api/meeting-recordings/{sid}', headers=self.auth()).json()
        self.assertEqual(original['status'], 'READY')


if __name__ == '__main__': unittest.main()
