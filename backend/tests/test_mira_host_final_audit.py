"""Final audit: in-flight writes, poisoned recovery backlogs and network stalls."""
import asyncio
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

from tests.test_mira_host_bot import session
from tests.test_mira_host_service import DAY
from app.api.routers import mira_host_bot as api
from app.services import mira_host as service
from app.models.mira_host import Mira1HMeeting, MiraHostSettings
import mira_host as controller


class FinalAuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_shutdown_bounds_and_cancels_a_tool_that_never_returns(self):
        entered = asyncio.Event()
        async def stalled(*_):
            entered.set()
            await asyncio.Event().wait()
        bridge = AsyncMock(return_value={})
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        state = {**session(), 'meeting': str(uuid.uuid4()), 'finished': False, 'reason': 'completed'}
        host.session = state
        with tempfile.TemporaryDirectory() as directory, patch.object(controller, 'RECOVERY_DIR', Path(directory)), \
             patch.object(controller, 'WRITE_TIMEOUT_SECONDS', 0.05), patch.object(host, '_tool', stalled):
            await host.on_worker(state, {'type': 'tool_call', 'name': 'add_meeting_note', 'call_id': 'stalled', 'arguments': '{}'})
            await entered.wait()
            task = next(iter(state['tool_tasks']))
            await asyncio.wait_for(host.finish(state), 2)
        self.assertTrue(task.cancelled())
        self.assertFalse(state['tool_tasks'])
        self.assertIsNone(host.session)
        self.assertTrue(bridge.await_args.args[0].endswith('/finish'))

    async def test_shutdown_waits_for_an_inflight_write_and_uploads_its_metric(self):
        entered, release, tool_done = asyncio.Event(), asyncio.Event(), asyncio.Event()
        events, metrics = [], []
        async def bridge(path, body):
            if '/tools/' in path:
                entered.set()
                await release.wait()
                events.append('write')
                return {'ok': True}
            if path.endswith('/transcript'):
                metrics.extend(body.get('metrics', []))
            if path.endswith('/finish'):
                events.append('finish')
            return {}
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        state = {**session(), 'meeting': str(uuid.uuid4()), 'finished': False, 'reason': 'completed'}
        original_tool = host.tool
        async def tracked_tool(*args):
            try:
                return await original_tool(*args)
            finally:
                tool_done.set()
        voice_closed = asyncio.Event()
        state['process'].close.side_effect = lambda: voice_closed.set()
        with tempfile.TemporaryDirectory() as directory, patch.object(controller, 'RECOVERY_DIR', Path(directory)), \
             patch.object(host, 'tool', tracked_tool):
            await host.on_worker(state, {'type': 'tool_call', 'name': 'add_meeting_note', 'call_id': 'pending', 'arguments': '{}'})
            await entered.wait()
            finishing = asyncio.create_task(host.finish(state))
            await voice_closed.wait()
            await asyncio.sleep(0)
            prematurely_finished = 'finish' in events
            release.set()
            await asyncio.wait_for(finishing, 2)
            await asyncio.wait_for(tool_done.wait(), 2)
        self.assertFalse(prematurely_finished, 'The server was finalized before the write returned')
        self.assertEqual(events, ['write', 'finish'])
        self.assertEqual([metric['tool'] for metric in metrics], ['add_meeting_note'])

    async def test_failed_first_twenty_recovery_files_cannot_starve_the_next_meeting(self):
        uploads = []
        async def bridge(path, body):
            if path.endswith('/transcript'):
                uploads.extend(body['lines'])
            return {}
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        with tempfile.TemporaryDirectory() as directory, patch.object(controller, 'RECOVERY_DIR', Path(directory)):
            paths = []
            for i in range(21):
                mid = str(uuid.UUID(int=i + 1))
                path = Path(directory) / (mid + '.json')
                path.write_text('broken' if i < 20 else json.dumps({'meeting': mid,
                    'lines': [{'id': 'healthy', 'text': 'Raportimi'}]}), encoding='utf-8')
                paths.append(path)
            with patch.object(Path, 'glob', lambda *_: iter([path for path in paths if path.exists()])):
                with self.assertLogs(controller.log, level='WARNING'):
                    await host.recover_transcripts()
                    await host.recover_transcripts()
        self.assertEqual([line['id'] for line in uploads], ['healthy'])

    async def test_stalled_recovery_request_is_bounded_and_other_meetings_continue(self):
        blocked_mid, healthy_mid = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))
        uploads = []
        async def bridge(path, body):
            if blocked_mid in path:
                await asyncio.Event().wait()
            if path.endswith('/transcript'):
                uploads.extend(body['lines'])
            return {}
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        with tempfile.TemporaryDirectory() as directory, patch.object(controller, 'RECOVERY_DIR', Path(directory)), \
             patch.object(controller, 'WRITE_TIMEOUT_SECONDS', 0.05):
            for mid in (blocked_mid, healthy_mid):
                (Path(directory) / (mid + '.json')).write_text(json.dumps({'meeting': mid,
                    'lines': [{'id': mid, 'text': 'Raportimi'}]}), encoding='utf-8')
            with self.assertLogs(controller.log, level='WARNING'):
                await asyncio.wait_for(host.recover_transcripts(), 2)
            self.assertTrue((Path(directory) / (blocked_mid + '.json')).exists())
        self.assertEqual([line['id'] for line in uploads], [healthy_mid])


class StartupFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_realtime_credentials_fail_immediately(self):
        for body in ({}, {'value': None}, {'value': 123}, [], ValueError('invalid JSON')):
            with self.subTest(body=body):
                class Client:
                    def __init__(self, **_): pass
                    async def __aenter__(self): return self
                    async def __aexit__(self, *_): return False
                    async def post(self, *_args, **_kwargs):
                        def response_body():
                            if isinstance(body, Exception): raise body
                            return body
                        return SimpleNamespace(is_error=False, json=response_body)
                with patch.object(service.settings, 'MIRA_HOST_OPENAI_API_KEY', 'synthetic'), \
                     patch('httpx.AsyncClient', Client), \
                     patch.object(service, 'get_settings', AsyncMock(return_value=MiraHostSettings())), \
                     patch.object(service, 'instructions', AsyncMock(return_value='Synthetic policy')):
                    with self.assertRaises(HTTPException) as raised:
                        await service.realtime_session(SimpleNamespace(), Mira1HMeeting())
                self.assertEqual(raised.exception.status_code, 502)

    async def test_failed_start_is_aborted_only_if_its_attempt_is_still_current(self):
        for error in (RuntimeError('provider failed'), HTTPException(502, 'provider failed')):
            for current_attempt in (1, 2):
                with self.subTest(error=type(error).__name__, current_attempt=current_attempt):
                    first = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='GA_PHASE', join_attempts=1)
                    current = Mira1HMeeting(id=first.id, meeting_date=DAY, slot='11:00', status='GA_PHASE', join_attempts=current_attempt)
                    db = AsyncMock()
                    with patch.object(service.settings, 'MIRA_HOST_OPENAI_API_KEY', 'synthetic'), \
                         patch.object(service, 'get_settings', AsyncMock(return_value=SimpleNamespace())), \
                         patch.object(service, 'is_enabled', return_value=True), \
                         patch.object(service, 'start_meeting', AsyncMock(return_value=first)), \
                         patch.object(service, 'meeting_for', AsyncMock(return_value=current)), \
                         patch.object(service, 'realtime_session', AsyncMock(side_effect=error)), \
                         patch.object(service, 'finish_meeting', AsyncMock()) as finish:
                        with self.assertRaises(HTTPException) as raised:
                            await api.start(api.Start(slot='11:00'), db)
                    self.assertEqual(raised.exception.status_code, 502)
                    self.assertEqual(finish.await_count, 1 if current_attempt == 1 else 0)
                    db.rollback.assert_awaited_once()

    async def test_a_successful_but_superseded_start_cannot_return_the_old_session(self):
        first = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='GA_PHASE', join_attempts=1)
        db = AsyncMock()
        async def refresh(*_args, **_kwargs):
            first.join_attempts = 2
        db.refresh.side_effect = refresh
        with patch.object(service.settings, 'MIRA_HOST_OPENAI_API_KEY', 'synthetic'), \
             patch.object(service, 'get_settings', AsyncMock(return_value=SimpleNamespace(target_minutes_per_person=4))), \
             patch.object(service, 'is_enabled', return_value=True), \
             patch.object(service, 'start_meeting', AsyncMock(return_value=first)), \
             patch.object(service, 'realtime_session', AsyncMock(return_value={'client_secret': 'synthetic', 'model': 'synthetic'})):
            with self.assertRaises(HTTPException) as raised:
                await api.start(api.Start(slot='11:00'), db)
        self.assertEqual(raised.exception.status_code, 409)
