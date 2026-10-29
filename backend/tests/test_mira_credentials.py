"""Credential isolation at the real HTTP boundary, using synthetic credentials only."""
import asyncio
import json
import os
import unittest
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET', 'credential-isolation-tests-only')

from app.config import settings
from app.models.mira_host import Mira1HMeeting, MiraHostSettings
from app.services import discord_voice_openai as notes
from app.services import mira_host as host
from app.services import recording_analysis_provider as recording
from tests.test_discord_voice_openai import wav
from tests.test_recording_analysis_provider import tone, wav_bytes


def answer(text):
    return {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}


class CredentialIsolationTests(unittest.IsolatedAsyncioTestCase):
    @contextmanager
    def provider(self, handler, **overrides):
        keys = dict(OPENAI_API_KEY='general-test', MIRA_NOTES_OPENAI_API_KEY='notes-test',
                    MIRA_HOST_OPENAI_API_KEY='host-test', KUJTESA_OPENAI_API_KEY='family-test')
        real = httpx.AsyncClient
        with patch.dict(settings.__dict__, {**keys, **overrides}), patch.object(
            httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
        ):
            yield

    async def test_silent_transcription_and_memory_use_notes_key(self):
        seen = []
        def transport(request):
            seen.append(request.headers['Authorization'])
            body = {'text': 'Po.'} if request.url.path.endswith('transcriptions') else answer('{"operations": []}')
            return httpx.Response(200, json=body)
        with self.provider(transport):
            self.assertEqual(await notes.transcribe_segment(wav()), 'Po.')
            self.assertEqual(await notes.extract_memory_operations('Staff', [{'text': 'Po.'}],
                meeting_date=date(2026, 10, 29), memory={'items': []}), [])
        self.assertEqual(seen, ['Bearer notes-test', 'Bearer notes-test'])

    async def test_host_summary_batches_and_retries_keep_host_scope(self):
        seen = []
        def transport(request):
            seen.append(request.headers['Authorization'])
            return httpx.Response(429 if len(seen) == 1 else 200, json=answer('Raporti.'))
        with self.provider(transport), patch.object(notes.asyncio, 'sleep', AsyncMock()):
            result = await notes.summarize_meeting('Staff', [{'text': str(i) * 50000} for i in range(3)], scope='host')
        self.assertIn('Raporti.', result)
        self.assertEqual(seen, ['Bearer host-test'] * 5)

    async def test_concurrent_notes_and_host_requests_do_not_share_scope_or_cache(self):
        seen = []
        def transport(request):
            seen.append(request.headers['Authorization'])
            return httpx.Response(200, json=answer('Raporti.'))
        checkpointed = {}
        async def checkpoint(value):
            checkpointed.update(value)
        with self.provider(transport):
            await asyncio.gather(
                notes.summarize_meeting('Staff', [{'text': 'Po.'}], checkpoint=checkpoint),
                notes.summarize_meeting('Staff', [{'text': 'Po.'}], scope='host'))
            await notes.summarize_meeting('Staff', [{'text': 'Po.'}], scope='host', cache=checkpointed)
        self.assertCountEqual(seen, ['Bearer notes-test', 'Bearer host-test', 'Bearer host-test'])

    async def test_missing_role_key_never_uses_any_other_configured_key(self):
        seen = []
        def transport(request):
            seen.append(request)
            return httpx.Response(200, json=answer('Raporti.'))
        for scope, key in [('notes', 'MIRA_NOTES_OPENAI_API_KEY'), ('host', 'MIRA_HOST_OPENAI_API_KEY')]:
            with self.subTest(scope=scope), self.provider(transport, **{key: '  '}):
                with self.assertRaisesRegex(ValueError, 'openai_not_configured'):
                    await notes.summarize_meeting('Staff', [{'text': 'Po.'}], scope=scope)
        self.assertEqual(seen, [])

    async def test_silent_notes_capabilities_and_start_require_notes_key(self):
        from fastapi import HTTPException
        from app.api.routers import mira_desktop as desktop_api
        from app.services import mira_desktop, discord_voice_meetings
        actor = SimpleNamespace(id=uuid.uuid4())
        with self.provider(lambda request: httpx.Response(200), MIRA_NOTES_OPENAI_API_KEY=None), \
                patch.object(settings, 'DISCORD_MEETING_NOTES_ENABLED', True):
            self.assertFalse((await desktop_api.capabilities(actor))['enabled'])
            with self.assertRaises(HTTPException) as desktop_error:
                mira_desktop.enabled()
            self.assertEqual(desktop_error.exception.status_code, 503)
            with self.assertRaises(HTTPException) as discord_error:
                await discord_voice_meetings.start_session(None, None)
            self.assertEqual(discord_error.exception.status_code, 503)
        with self.provider(lambda request: httpx.Response(200), OPENAI_API_KEY=None):
            self.assertTrue((await desktop_api.capabilities(actor))['enabled'])
            mira_desktop.enabled()

    async def test_host_capability_requires_its_own_key(self):
        with self.provider(lambda request: httpx.Response(200), MIRA_HOST_OPENAI_API_KEY=None), \
                patch.object(settings, 'MIRA_HOST_ENABLED', True), \
                patch.object(settings, 'MIRA_HOST_BOT_TOKEN', 'host-bot-test'):
            self.assertFalse(host.settings_view(MiraHostSettings())['configured'])

    async def test_host_enable_and_manual_or_scheduled_start_reject_missing_key(self):
        from fastapi import HTTPException
        from app.api.routers import mira_host_bot as api
        row = MiraHostSettings(enabled_until=datetime(2099, 1, 1, tzinfo=timezone.utc))
        db = SimpleNamespace(commit=AsyncMock())
        with self.provider(lambda request: httpx.Response(200), MIRA_HOST_OPENAI_API_KEY=None), \
                patch.object(settings, 'MIRA_HOST_ENABLED', True), \
                patch.object(settings, 'MIRA_HOST_BOT_TOKEN', 'host-bot-test'), \
                patch.object(api, 'manager', AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))), \
                patch.object(host, 'get_settings', AsyncMock(return_value=row)):
            calls = [(api.enable, api.Enable(discord_user_id='11')),
                     (api.start, api.Start(slot='11:00', discord_user_id='11')),
                     (api.start, api.Start(slot='11:00'))]
            for operation, payload in calls:
                with self.subTest(operation=operation.__name__, payload=payload):
                    with self.assertRaises(HTTPException) as error:
                        await operation(payload, db)
                    self.assertEqual(error.exception.status_code, 503)

    async def test_work_ui_cannot_enable_host_without_its_key(self):
        from fastapi import HTTPException
        from app.api.routers import mira as api
        db = SimpleNamespace(commit=AsyncMock())
        with self.provider(lambda request: httpx.Response(200), MIRA_HOST_OPENAI_API_KEY=None), \
                patch.object(host, 'get_settings', AsyncMock(return_value=MiraHostSettings())):
            with self.assertRaises(HTTPException) as error:
                await api.switch_host(api.HostSwitch(enabled=True), db, SimpleNamespace(id=uuid.uuid4()))
            self.assertEqual(error.exception.status_code, 503)

    async def test_host_tick_does_not_invite_people_when_key_was_removed(self):
        at = datetime(2026, 10, 29, 9, 58, tzinfo=timezone.utc)
        row = MiraHostSettings(enabled_until=datetime(2099, 1, 1, tzinfo=timezone.utc))
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalars=lambda: [])), commit=AsyncMock())
        with self.provider(lambda request: httpx.Response(200), MIRA_HOST_OPENAI_API_KEY=None), \
                patch.object(host, 'get_settings', AsyncMock(return_value=row)), \
                patch.object(host, 'common_payload', AsyncMock(side_effect=AssertionError('must not prepare invitations'))):
            self.assertEqual(await host.tick(db, at), {'enabled': False, 'jobs': []})

    async def test_host_realtime_uses_host_key_and_fails_closed(self):
        seen = []
        def transport(request):
            seen.append(request.headers['Authorization'])
            return httpx.Response(200, json={'value': 'ephemeral-test'})
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=date(2026, 10, 29), slot='11:00')
        with self.provider(transport), patch.object(host, 'get_settings', AsyncMock(return_value=MiraHostSettings())), \
                patch.object(host, 'instructions', AsyncMock(return_value='Test')):
            result = await host.realtime_session(None, meeting)
        self.assertEqual(result['client_secret'], 'ephemeral-test')
        self.assertEqual(seen, ['Bearer host-test'])
        with self.provider(transport, MIRA_HOST_OPENAI_API_KEY=None):
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as error:
                await host.realtime_session(None, meeting)
            self.assertEqual(error.exception.status_code, 503)
        self.assertEqual(len(seen), 1)

    async def test_host_background_summary_and_turn_notes_use_host_key(self):
        seen = []
        turn = SimpleNamespace(id=uuid.uuid4(), started_at=datetime(2026, 10, 29, 10, tzinfo=timezone.utc),
                               ended_at=None, notes=None)
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=date(2026, 10, 29), slot='11:00',
            summary_status='PENDING', host_transcript=[{'speaker': 'Ana', 'at': turn.started_at.isoformat(), 'text': 'Po.'}])
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock(all=lambda: [(turn, 'Ana')])),
                             commit=AsyncMock(), rollback=AsyncMock())
        class Session:
            async def __aenter__(self): return db
            async def __aexit__(self, *args): return False
        def transport(request):
            seen.append(request.headers['Authorization'])
            body = answer('Raporti.' if len(seen) == 1 else json.dumps({'notes': {str(turn.id): 'Raportoi.'}}))
            return httpx.Response(200, json=body)
        with self.provider(transport), patch('app.db.SessionLocal', return_value=Session()), \
                patch.object(host, 'meeting_for', AsyncMock(return_value=meeting)), \
                patch.object(host, 'turns_view', AsyncMock(return_value=[])), \
                patch.object(host, 'meeting_events', AsyncMock(return_value=[])):
            await host.summarize(meeting.id)
        self.assertEqual(meeting.summary_status, 'READY')
        self.assertEqual(turn.notes, 'Raportoi.')
        self.assertEqual(seen, ['Bearer host-test', 'Bearer host-test'])

    async def test_general_recording_transcription_and_analysis_keep_general_key(self):
        seen = []
        def transport(request):
            seen.append(request.headers['Authorization'])
            return httpx.Response(200, json={'text': 'Po.'} if len(seen) == 1 else answer(
                '{"summary": "Raporti.", "decisions": [], "actions": []}'))
        with self.provider(transport, MIRA_NOTES_OPENAI_API_KEY=None):
            self.assertEqual(await recording.transcribe(wav_bytes(tone(2, 8000)), 'sq'), 'Po.')
            result = await recording.analyze_meeting('Staff', [{'text': 'Po.', 'start_seconds': 0, 'duration_seconds': 2}],
                meeting_day=date(2026, 10, 29))
        self.assertIn('Raporti.', str(result))
        self.assertEqual(seen, ['Bearer general-test', 'Bearer general-test'])
