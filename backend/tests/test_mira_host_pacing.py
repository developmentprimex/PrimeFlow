"""Meeting pacing and transport regressions; uses synthetic data and no live services."""
import asyncio
import uuid
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from pydantic import ValidationError
from tests.test_mira_host_bot import session, BRIEF
from tests.test_mira_host_service import DAY, IDS, payload, item
import mira_host as controller
from app.services import mira_host as service
from app.models.mira_host import Mira1HMeeting
from app.api.routers.mira_host_bot import Lines
from app.config import Settings


class PacingTests(unittest.IsolatedAsyncioTestCase):
    async def test_discord_invitation_does_not_block_the_tool_continuation(self):
        async def slow(*args):
            await asyncio.Event().wait()
        host = controller.MiraHost(SimpleNamespace())
        state = {**session(), 'upcoming': {'id': 'next', 'name': 'Elsa', 'discord': {'discord_user_id': '11'}}}
        with patch.object(host, 'notify', slow):
            result = await asyncio.wait_for(host._tool(state, {'name': 'call_next_person', 'arguments': '{}'}), 0.5)
            self.assertEqual(result['njoftim_ne_dergim'], 'Elsa')
            pending = list(state['notification_tasks'])
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    async def test_uncertain_handoff_reads_server_state_instead_of_advancing_twice(self):
        calls = []
        async def bridge(path, body):
            calls.append(path)
            if path.endswith('/turns/next'):
                raise asyncio.TimeoutError()
            return {'current': {'id': 'new', 'user_id': IDS['EF'], 'name': 'Elsa', 'initials': 'EF',
                                'discord': None, 'brief': BRIEF}, 'upcoming': None, 'deferred': [],
                    'turns': [{'id': 'old', 'status': 'TIMEOUT'}]}
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        state = {**session(), 'current_turn': {'id': 'old'}}
        result = await host.advance(state, None, announce=False, outcome='TIMEOUT', expected_turn_id='old')
        self.assertEqual(result['RADHA']['turn_id'], 'new')
        self.assertEqual(state['incomplete_turns'], ['old'])
        self.assertEqual(sum(path.endswith('/turns/next') for path in calls), 1)
        self.assertTrue(calls[-1].endswith('/turns/current'))

    async def test_staff_phase_is_not_marked_started_when_the_request_times_out(self):
        async def slow(*args):
            await asyncio.Event().wait()
        host = controller.MiraHost(SimpleNamespace(bridge=slow))
        state = session()
        with patch.object(controller, 'LOOKUP_TIMEOUT_SECONDS', 0.01), self.assertRaises(asyncio.TimeoutError):
            await host.start_staff(state, announce=False)
        self.assertFalse(state.get('staff_started', False))

    async def test_current_turn_snapshot_does_not_advance_or_write(self):
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='STAFF_PHASE')
        turns = [{'id': 'active', 'user_id': IDS['EF'], 'status': 'ACTIVE'},
                 {'id': 'waiting', 'user_id': IDS['RA'], 'status': 'WAITING'}]
        with patch.object(service, 'turns_view', AsyncMock(return_value=turns)), \
             patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))), \
             patch.object(service, 'person_context', AsyncMock(return_value={'current': []})):
            result = await service.current_turn_state(SimpleNamespace(), meeting)
        self.assertEqual(result['current']['id'], 'active')
        self.assertEqual(result['upcoming']['id'], 'waiting')
        self.assertEqual(turns[0]['status'], 'ACTIVE')

    async def test_slow_lookup_returns_an_explicit_error_instead_of_waiting_indefinitely(self):
        async def slow(*args):
            await asyncio.Event().wait()
        host = controller.MiraHost(SimpleNamespace(bridge=slow))
        with patch.object(controller, 'LOOKUP_TIMEOUT_SECONDS', 0.01):
            result = await asyncio.wait_for(host._tool(session(), {'name': 'get_person_brief', 'arguments': '{}'}), 1)
        self.assertTrue(result['retry_safe'])
        self.assertFalse(result['result_unknown'])
        self.assertIn('error', result)

    async def test_a_timed_out_write_is_unknown_and_is_not_replayed_with_a_new_call_id(self):
        calls = []
        async def slow(*args):
            calls.append(args)
            await asyncio.Event().wait()
        host = controller.MiraHost(SimpleNamespace(bridge=slow))
        state = session()
        message = {'name': 'save_px_note', 'call_id': 'first', 'speech_id': 'dictation', 'arguments': '{"text":"Oferta u dërgua"}'}
        with patch.object(controller, 'WRITE_TIMEOUT_SECONDS', 0.01):
            await asyncio.wait_for(host.tool(state, message), 1)
            first = state['process'].send.await_args.args[0]['output']
            await host.tool(state, {**message, 'call_id': 'recovery'})
        self.assertTrue(first['result_unknown'])
        self.assertFalse(first['retry_safe'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(state['process'].send.await_args.args[0]['output'], first)

    async def test_successful_dictation_is_not_saved_again_after_response_recovery(self):
        host = controller.MiraHost(SimpleNamespace())
        state = session()
        message = {'name': 'save_px_note', 'call_id': 'first', 'speech_id': 'dictation', 'arguments': '{"text":"Oferta u dërgua"}'}
        with patch.object(host, '_tool', AsyncMock(return_value={'success': True})) as tool:
            await host.tool(state, message)
            await host.tool(state, {**message, 'call_id': 'recovery'})
        self.assertEqual(tool.await_count, 1)

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
        self.assertNotIn('prepare_task_from_note', ga)
        self.assertNotIn('create_task_from_note', ga)
        self.assertNotIn('create_task_from_note', staff)
        self.assertIn('record_task_discussion', staff)
        self.assertNotIn('end_person_turn', ga)
