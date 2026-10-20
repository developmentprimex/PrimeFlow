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

    def test_authorization_consent_and_provider_configuration(self):
        sid = self.saved()
        self.assertEqual(self.get(sid, 'other').status_code, 404)
        self.assertEqual(self.get(sid, 'participant').status_code, 200)
        for who in ['other', 'participant', 'manager']:
            response = self.client.post(f'/api/meeting-recordings/{sid}/analysis', headers=self.auth(who), json={'consent_acknowledged': True})
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.post(f'/api/meeting-recordings/{sid}/analysis', headers=self.auth(), json={'consent_acknowledged': False}).status_code, 422)
        with patch.object(self.settings, 'OPENAI_API_KEY', None):
            self.assertFalse(self.get(sid).json()['configured'])
            self.assertEqual(self.start(sid).status_code, 503)

    def test_durable_failure_retry_summary_and_atomic_task_confirmation(self):
        sid = self.saved()
        self.assertEqual(self.start(sid).status_code, 202)
        notes = {'summary': 'Raporti', 'decisions': [], 'actions': [{'title': 'Dërgo raportin', 'description': 'Dërgo raportin e takimit.',
            'evidence': 'Do ta dërgoj raportin @other nesër.', 'assignee_text': None, 'deadline_text': None}]}
        with patch('app.services.recording_analysis_provider.transcribe', new=AsyncMock(return_value='Do ta dërgoj raportin @other nesër.')) as transcribe:
            with patch('app.services.recording_analysis_provider.extract_notes', new=AsyncMock(side_effect=ValueError('provider_failed'))):
                self.tick()
            data = self.get(sid).json()
            self.assertEqual(data['analysis']['status'], 'FAILED')
            self.assertEqual(data['segments'][0]['text'], 'Do ta dërgoj raportin @other nesër.')
            self.assertEqual(self.start(sid).status_code, 202)
            with patch('app.services.recording_analysis_provider.extract_notes', new=AsyncMock(return_value=notes)):
                self.tick()
            self.assertEqual(transcribe.await_count, 1, 'Persisted transcript must survive worker restart/retry')
        with patch('app.services.discord_voice_openai.summarize_meeting', new=AsyncMock(return_value='Përmbledhja e takimit')):
            self.tick()
        data = self.get(sid).json()
        self.assertEqual(data['analysis']['status'], 'READY', data)
        self.assertEqual(len(data['actions']), 1)
        action = data['actions'][0]
        self.assertIsNone(action['created_task_id'])
        self.assertEqual(self.start(sid).status_code, 202)
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
        self.assertEqual(self.client.post(path, headers=self.auth(), json={**body, 'is_personal': True}).status_code, 422)
        first = self.client.post(path, headers=self.auth(), json=body)
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post(path, headers=self.auth(), json=body)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(second.json()['duplicate'])
        self.assertEqual(first.json()['task_id'], second.json()['task_id'])
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
        self.assertEqual(reloaded['analysis']['summary'], 'Përmbledhja e takimit')

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
