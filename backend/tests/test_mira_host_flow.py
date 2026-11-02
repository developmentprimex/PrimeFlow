"""Reported meeting flow regressions, using synthetic staff and Notes."""
import uuid
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from tests.test_mira_host_bot import session, BRIEF
from tests.test_mira_host_service import DAY, IDS, payload, item
from app.models.mira_host import Mira1HMeeting
from app.services import mira_host as service
from app.services.mira_host_speech import speech_text
import mira_host as controller


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def test_speech_formatting_leaves_words_and_source_codes_intact(self):
        self.assertEqual(speech_text('FG: PDF OFERTA EF', ['EF']), 'fë gë: pë dë fë OFERTA e fë')
        self.assertEqual(speech_text('OFERTA GENT PROJEKTI'), 'OFERTA GENT PROJEKTI')

    async def test_uncertain_first_handoff_still_announces_the_people_it_skipped(self):
        current = {'id': 'present', 'name': 'Rinesa', 'initials': 'RA', 'discord': None, 'brief': BRIEF}
        absent = {'id': 'absent', 'name': 'Elsa', 'status': 'DEFERRED'}
        bridge = AsyncMock(side_effect=[TimeoutError(), {'current': current, 'deferred': [absent], 'turns': [absent]}])
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        state = {**session(), 'current_turn': None}
        result = await host.advance(state, None, announce=False)
        self.assertEqual(result.get('mungojne'), ['Elsa'])

    async def test_deferred_late_arrival_is_reinserted_without_being_reported_early(self):
        late = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.UUID(IDS['EF']), status='DEFERRED',
                               invited_at=None, started_at=None, ended_at=None, notes='')
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [late]))), flush=AsyncMock())
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='STAFF_PHASE')
        async def view(*args):
            return [{'id': str(late.id), 'user_id': str(late.user_id), 'name': 'Elsa', 'status': late.status}]
        with patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))), \
             patch.object(service, 'turns_view', view), patch.object(service, 'person_context', AsyncMock(return_value=BRIEF)):
            result = await service.next_turn(db, meeting, None, available_user_ids=[late.user_id])
        self.assertEqual(late.status, 'ACTIVE')
        self.assertEqual(result['current']['id'], str(late.id))
        self.assertEqual(result['deferred'], [])

    async def test_existing_notes_supply_the_first_reading_without_a_permission_question(self):
        notes = [{'note_id': 'n1', 'number': 1, 'text': 'FG: kontrollo ofertën.'},
                 {'note_id': 'n2', 'number': 2, 'text': 'Dërgo raportin.'}]
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='GA_PHASE')
        with patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))), \
             patch.object(service, 'open_notes', AsyncMock(return_value=notes)):
            result = await service.run_tool(SimpleNamespace(), meeting, 'list_new_px_notes', {})
        self.assertIn('fë gë: kontrollo ofertën.', result.get('read_aloud', ''))
        self.assertNotIn('Dërgo raportin.', result['read_aloud'])
        self.assertEqual(result.get('current_note_id'), 'n1')
        self.assertEqual(result['notes'][0]['text'], notes[0]['text'])

    async def test_no_notes_continues_to_progress_without_asking_for_notes(self):
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='GA_PHASE')
        with patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))), \
             patch.object(service, 'open_notes', AsyncMock(return_value=[])):
            result = await service.run_tool(SimpleNamespace(), meeting, 'list_new_px_notes', {})
        self.assertFalse(result.get('read_aloud'))
        self.assertEqual(result.get('next_step'), 'list_new_done_and_strikes')

    def test_task_reading_spells_known_codes_without_changing_the_source_title(self):
        task = service.task_line(item('EF', '11:00', 'FG PDF OFERTA', rank=0))
        self.assertEqual(task['title'], 'EF: FG PDF OFERTA')
        self.assertEqual(task.get('read_aloud'), 'fë gë pë dë fë OFERTA')
        brief = {**BRIEF, 'current': [task]}
        result = controller.turn_brief({'id': 'turn', 'name': 'Elsa', 'initials': 'EF', 'brief': brief})
        self.assertEqual(result['plan_discutimi'][0]['detyra'], 'fë gë pë dë fë OFERTA')

    async def test_absent_current_person_is_deferred_on_the_first_presence_check(self):
        host = controller.MiraHost(SimpleNamespace())
        state = {**session(), 'current_turn': {'id': 'absent', 'name': 'Elsa', 'discord': {'discord_user_id': '11'}},
                 'turn_started': controller.datetime.now(controller.tz()), 'turn_nudged': False}
        with patch.object(host, 'in_voice', return_value=False), patch.object(host, 'advance', AsyncMock()) as advance:
            await host.watch_turn(state)
        advance.assert_awaited_once()
        self.assertEqual(advance.await_args.kwargs['outcome'], 'DEFERRED')
        self.assertEqual(advance.await_args.kwargs['expected_turn_id'], 'absent')

    async def test_waiting_absentees_are_skipped_together_and_present_order_is_preserved(self):
        turns = [SimpleNamespace(id=uuid.uuid4(), user_id=uuid.UUID(IDS[key]), status='WAITING',
                    invited_at=None, started_at=None, ended_at=None, notes='') for key in ('EF', 'RA', 'EH')]
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: turns))), flush=AsyncMock())
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='STAFF_PHASE')
        async def view(*args):
            return [{'id': str(t.id), 'user_id': str(t.user_id), 'name': ['Elsa', 'Rinesa', 'Endrit'][i], 'status': t.status}
                    for i, t in enumerate(turns)]
        with patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))), \
             patch.object(service, 'turns_view', view), patch.object(service, 'person_context', AsyncMock(return_value=BRIEF)):
            result = await service.next_turn(db, meeting, None, available_user_ids=[turns[1].user_id, turns[2].user_id])
        self.assertEqual([t.status for t in turns], ['DEFERRED', 'ACTIVE', 'WAITING'])
        self.assertEqual(result['current']['id'], str(turns[1].id))
        self.assertEqual(result['upcoming']['id'], str(turns[2].id))
        self.assertEqual([t['id'] for t in result.get('skipped', [])], [str(turns[0].id)])

    async def test_test_handoff_does_not_send_staff_availability(self):
        bridge = AsyncMock(return_value={'current': None, 'deferred': []})
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        state = {**session(), 'test_mode': True, 'turns': []}
        await host.advance(state, None, announce=False)
        self.assertNotIn('available_user_ids', bridge.await_args.args[1])

    async def test_unknown_discord_mapping_is_not_claimed_as_absence(self):
        bridge = AsyncMock(return_value={'current': None})
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        state = {**session(), 'turns': [{'user_id': IDS['EF'], 'discord': None}]}
        await host.advance(state, None, announce=False)
        self.assertIn(IDS['EF'], bridge.await_args.args[1]['available_user_ids'])

    async def test_skip_announcement_identifies_absence_and_continues_to_the_present_person(self):
        current = {'id': 'present', 'name': 'Rinesa', 'initials': 'RA', 'discord': None, 'brief': BRIEF}
        bridge = AsyncMock(return_value={'current': current, 'skipped': [{'id': 'absent', 'name': 'Elsa', 'status': 'DEFERRED'}],
                                        'deferred': [{'id': 'absent', 'name': 'Elsa', 'status': 'DEFERRED'}]})
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        result = await host.advance(session(), None, announce=False)
        self.assertEqual(result.get('mungojne'), ['Elsa'])
        self.assertIn('nuk është në kanalin zanor', result.get('udhezim', ''))
        self.assertEqual(result['RADHA']['turn_id'], 'present')

    async def test_all_remaining_staff_absent_does_not_wait_a_full_minute(self):
        host = controller.MiraHost(SimpleNamespace())
        state = {**session(), 'current_turn': None, 'deferred': [{'id': 'absent', 'user_id': IDS['EF'], 'name': 'Elsa'}],
                 'missing_since': controller.datetime.now(controller.tz()) - timedelta(seconds=6)}
        with patch.object(host, 'say', AsyncMock()) as say:
            await host.watch_turn(state)
        self.assertTrue(state['ending'])
        self.assertEqual(state['reason'], 'missing_staff')
        say.assert_awaited_once()
