"""Meeting pacing and transport regressions; uses synthetic data and no live services."""
import asyncio
import uuid
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from pydantic import ValidationError
from tests.test_mira_host_bot import session
from tests.test_mira_host_service import DAY, IDS, payload, item
import mira_host as controller
from app.services import mira_host as service
from app.models.mira_host import Mira1HMeeting
from app.api.routers.mira_host_bot import Lines
from app.config import Settings


class PacingTests(unittest.IsolatedAsyncioTestCase):
    async def test_warns_fifteen_seconds_before_target_once(self):
        host = controller.MiraHost(SimpleNamespace())
        state = {**session(), 'target': 2, 'turn_started': controller.datetime.now(controller.tz()) - timedelta(seconds=106),
                 'turn_nudged': False}
        with patch.object(host, 'say', AsyncMock()) as say:
            await host.watch_turn(state)
            await host.watch_turn(state)
        self.assertEqual(say.await_count, 1)
        self.assertIn('15 sekonda', say.await_args.args[1])

    async def test_hard_limit_advances_as_timeout_with_the_expected_turn(self):
        host = controller.MiraHost(SimpleNamespace())
        state = {**session(), 'target': 2, 'turn_started': controller.datetime.now(controller.tz()) - timedelta(seconds=151),
                 'turn_nudged': True, 'current_turn': {'id': 'turn1'}}
        with patch.object(host, 'advance', AsyncMock()) as advance:
            await host.watch_turn(state)
        self.assertEqual(advance.await_args.kwargs['outcome'], 'TIMEOUT')
        self.assertEqual(advance.await_args.kwargs['expected_turn_id'], 'turn1')

    async def test_metric_upload_retry_keeps_samples_and_identifiers(self):
        bridge = AsyncMock(side_effect=[ValueError('offline'), {}])
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        state = session()
        host.add_metric(state, 'generated_audio', 1250)
        metric_id = state['metrics'][0]['id']
        await host.flush_lines(state)
        self.assertEqual(state['metrics'][0]['id'], metric_id)
        await host.flush_lines(state)
        self.assertEqual(state['metrics'], [])
        self.assertEqual(bridge.await_args.args[1]['metrics'][0]['id'], metric_id)

    async def test_replayed_tool_does_not_execute_or_measure_twice(self):
        host = controller.MiraHost(SimpleNamespace())
        state = session()
        message = {'name': 'find_user', 'call_id': 'same'}
        with patch.object(host, '_tool', AsyncMock(return_value={'name': 'Elsa'})) as tool:
            await asyncio.gather(host.tool(state, message), host.tool(state, message))
        self.assertEqual(tool.await_count, 1)
        self.assertEqual(len(state['metrics']), 1)

    async def test_incomplete_task_cannot_be_silently_reported_as_done(self):
        turn = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.UUID(IDS['EF']), status='ACTIVE')
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [turn]))))
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='STAFF_PHASE')
        source = payload([item('EF', '11:00', 'OFERTA', rank=0)])
        with patch.object(service, 'common_payload', AsyncMock(return_value=source)), \
             patch.object(service, 'discussion_context', AsyncMock(return_value={})):
            with self.assertRaises(HTTPException) as raised:
                await service.next_turn(db, meeting, None, expected_turn_id=turn.id)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(turn.status, 'ACTIVE')

    async def test_unclear_report_can_flag_a_task_without_inventing_speaker_facts(self):
        task_id = uuid.uuid4()
        turn = SimpleNamespace(id=uuid.uuid4(), meeting_id=uuid.uuid4(), status='ACTIVE', user_id=uuid.UUID(IDS['EF']))
        db = SimpleNamespace(get=AsyncMock(return_value=turn), add=Mock(),
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)))
        meeting = Mira1HMeeting(id=turn.meeting_id, meeting_date=DAY, slot='11:00', status='STAFF_PHASE')
        source = payload([item('EF', '11:00', 'OFERTA', rank=0, task_id=str(task_id))])
        with patch.object(service, 'common_payload', AsyncMock(return_value=source)):
            result = await service.run_tool(db, meeting, 'record_task_discussion',
                {'turn_id': str(turn.id), 'task_id': str(task_id), 'unclear': True})
        self.assertTrue(result['success'])
        self.assertNotIn('progress', result['discussion'])

    async def test_unclear_flag_cannot_bypass_authorization_to_invent_progress(self):
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='STAFF_PHASE')
        with patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))):
            with self.assertRaises(HTTPException):
                await service.run_tool(SimpleNamespace(), meeting, 'record_task_discussion',
                    {'turn_id': str(uuid.uuid4()), 'task_id': str(uuid.uuid4()), 'unclear': True, 'progress': 'Gati'})

    async def test_ga_task_creation_is_unavailable_in_staff_phase(self):
        meeting = Mira1HMeeting(status='STAFF_PHASE')
        with self.assertRaises(HTTPException) as raised:
            await service.run_tool(SimpleNamespace(), meeting, 'prepare_task_from_note', {})
        self.assertEqual(raised.exception.status_code, 409)

    def test_model_is_pinned_and_legacy_protocol_is_normalized(self):
        self.assertEqual(Settings.model_fields['MIRA_HOST_MODEL'].default, 'gpt-realtime-2.1')
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, DATABASE_URL='postgresql+asyncpg://test:test@localhost/test',
                     JWT_SECRET='synthetic', MIRA_HOST_MODEL='gpt-realtime-2.1-mini')
        self.assertIn('aktual pastaj', service.effective_protocol('3. Sqaro slotin paraprak pastaj aktual'))

    def test_metric_schema_rejects_nonfinite_or_excessive_durations(self):
        for value in (float('nan'), float('inf'), -1, 180001):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Lines(lines=[], metrics=[{'id': str(uuid.uuid4()), 'kind': 'generated_audio', 'duration_ms': value}])

    def test_each_phase_exposes_only_its_tools(self):
        ga = {t['name'] for t in service.tool_definitions('GA_PHASE')}
        staff = {t['name'] for t in service.tool_definitions('STAFF_PHASE')}
        self.assertIn('create_task_from_note', ga)
        self.assertNotIn('create_task_from_note', staff)
        self.assertIn('record_task_discussion', staff)
        self.assertNotIn('end_person_turn', ga)
