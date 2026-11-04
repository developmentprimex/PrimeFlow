"""Meeting lifecycle regressions using synthetic data, without external services."""
import asyncio
import json
import tempfile
import unittest
import uuid
from fastapi import BackgroundTasks
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.test_mira_host_bot import session
from tests.test_mira_host_service import DAY, IDS, item, payload
from app.services import mira_host as service
from app.api.routers import mira_host_bot as api
from app.models.mira_host import Mira1HMeeting
import mira_host as controller


class QueueTests(unittest.IsolatedAsyncioTestCase):
    def test_1150_includes_owners_of_unfinished_earlier_work_without_current_tasks(self):
        data = service.SlotData(payload([
            item('EF', '10:00', 'Earlier unfinished', status='TODO', rank=0),
            item('RA', '11:00', 'Earlier completed', status='DONE', rank=0),
            item('EH', '11:50', 'Current work', rank=0),
        ]), DAY)
        self.assertEqual(data.participants('11:50'), [IDS['EH'], IDS['EF']])
        self.assertEqual(data.participants('11:00'), [])

    def test_1150_preserves_deduplication_absence_and_excluded_staff(self):
        source = payload([
            item('EH', '11:50', 'Current', rank=0),
            item('EH', '10:00', 'Also earlier', rank=0),
            item('EF', '10:00', 'Absent', rank=1),
            item('RA', '11:00', 'Excluded', rank=0),
        ], absent=('EF',))
        next(u for u in source['users'] if u['id'] == IDS['RA'])['full_name'] = 'Haxhere Spahiu'
        self.assertEqual(service.SlotData(source, DAY).participants('11:50'), [IDS['EH']])

    async def test_pm_initializes_from_fresh_data_even_when_staff_snapshot_is_empty(self):
        person = {'id': 'PM_person', 'user_id': IDS['EF'], 'name': 'Elsa', 'discord': None}
        bridge = AsyncMock(return_value={'initialized': True, 'current': person, 'turns': [person]})
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        state = {**session(), 'slot': '11:50', 'pm_reviewed': False}
        out = await host.present_turn(state, {'current': None, 'pm_review': []}, announce=False)
        self.assertEqual(out.get('turn_id'), person['id'])
        self.assertFalse(state['ending'])
        bridge.assert_awaited_once()


class ShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_old_cleanup_cannot_finish_a_restarted_meeting(self):
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00',
                                status='STAFF_PHASE', join_attempts=2)
        db = SimpleNamespace(commit=AsyncMock())
        background = BackgroundTasks()
        with patch.object(service, 'meeting_for', AsyncMock(return_value=meeting)), \
             patch.object(service, 'finish_meeting', AsyncMock()) as finish:
            out = await api.finish(meeting.id, api.Finish(reason='interrupted:process_exit',
                                   expected_join_attempt=1), background, db)
        finish.assert_not_awaited()
        self.assertTrue(out['superseded'])
        self.assertEqual(meeting.status, 'STAFF_PHASE')
        self.assertFalse(background.tasks)

    async def test_current_attempt_and_legacy_clients_can_still_finish(self):
        for expected in (2, None):
            with self.subTest(expected=expected):
                meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00',
                                        status='STAFF_PHASE', join_attempts=2)
                db = SimpleNamespace(commit=AsyncMock())
                with patch.object(service, 'meeting_for', AsyncMock(return_value=meeting)), \
                     patch.object(service, 'finish_meeting', AsyncMock()) as finish:
                    await api.finish(meeting.id, api.Finish(expected_join_attempt=expected), BackgroundTasks(), db)
                finish.assert_awaited_once_with(db, meeting, 'completed')

    async def test_recovery_preserves_the_original_attempt_in_its_finish_request(self):
        mid = str(uuid.uuid4())
        state = {**session(), 'meeting': mid, 'join_attempt': 1, 'finished': True, 'reason': 'completed'}
        calls = []
        async def bridge(path, body):
            calls.append((path, body))
            return {'superseded': True}
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        with tempfile.TemporaryDirectory() as directory, patch.object(controller, 'RECOVERY_DIR', Path(directory)):
            host.persist_transcript(state)
            await host.recover_transcripts()
            self.assertFalse(list(Path(directory).glob('*.json')))
        self.assertEqual(calls[-1][1]['expected_join_attempt'], 1)

    async def test_stalled_final_upload_cannot_block_shutdown_and_keeps_recovery(self):
        mid = str(uuid.uuid4())
        state = {**session(), 'meeting': mid, 'finished': False, 'reason': 'stopped_by_command',
                 'lines': [{'id': 'one', 'text': 'Raportimi'}]}
        async def bridge(path, body):
            if path.endswith('/transcript'):
                await asyncio.Event().wait()
            return {}
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        host.session = state
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(controller, 'RECOVERY_DIR', Path(directory)), \
             patch.object(controller, 'WRITE_TIMEOUT_SECONDS', 0.05):
            await asyncio.wait_for(host.finish(state), 2)
            saved = json.loads((Path(directory) / (mid + '.json')).read_text(encoding='utf-8'))
        self.assertIsNone(host.session)
        self.assertEqual(saved['finish_reason'], 'stopped_by_command')
        self.assertEqual([line['id'] for line in saved['lines']], ['one'])
        self.assertTrue(state['closed'].is_set())

    async def test_stalled_finish_request_also_releases_the_controller(self):
        mid = str(uuid.uuid4())
        state = {**session(), 'meeting': mid, 'finished': False, 'reason': 'completed'}
        async def stalled(*_):
            await asyncio.Event().wait()
        host = controller.MiraHost(SimpleNamespace(bridge=stalled))
        host.session = state
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(controller, 'RECOVERY_DIR', Path(directory)), \
             patch.object(controller, 'WRITE_TIMEOUT_SECONDS', 0.05):
            await asyncio.wait_for(host.finish(state), 2)
            self.assertTrue((Path(directory) / (mid + '.json')).exists())
        self.assertIsNone(host.session)
