"""Concise opening data and silent, clock-controlled handoff regressions."""
import asyncio
import unittest
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.test_mira_host_bot import session
from tests.test_mira_host_service import DAY, IDS, item, payload
from app.models.mira_host import Mira1HMeeting, Mira1HTurn
from app.services import mira_host as service, mira_host_runtime as runtime
import mira_host as controller


class ConciseOpeningTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_deadlines_are_kept_verbatim_with_the_existing_progress(self):
        task_id = str(uuid.uuid4())
        data = service.SlotData(payload([item('EF', '10:00', 'OFERTA', rank=0, task_id=task_id)]), DAY)
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='10:00', status='STAFF_PHASE', is_test=False)
        turn = Mira1HTurn(id=uuid.uuid4(), meeting_id=meeting.id, user_id=uuid.UUID(IDS['EF']), status='ACTIVE')
        for answer in ('sot', 'të premten', 'gjatë javës', 'nuk e di ende'):
            with self.subTest(answer=answer):
                existing = SimpleNamespace(data={'task_id': task_id, 'progress': 'Mbetet kontrolli', 'resume_at': 'pas pushimit'})
                db = SimpleNamespace(get=AsyncMock(return_value=turn), execute=AsyncMock(return_value=
                    SimpleNamespace(scalar_one_or_none=lambda: existing)))
                args = service.Discussion(task_id=task_id, turn_id=str(turn.id), finish_at=answer)
                result = await service.record_discussion(db, meeting, data, args, speech_id='answer', actor=SimpleNamespace(id=turn.user_id))
                self.assertTrue(result['success'])
                self.assertEqual(result['discussion']['finish_at'], answer)
                self.assertEqual(result['discussion']['progress'], 'Mbetet kontrolli')
                self.assertEqual(result['discussion']['resume_at'], 'pas pushimit')

    async def test_completed_opening_cannot_revert_staff_initialization_after_the_official_time(self):
        host = controller.MiraHost(SimpleNamespace())
        state = {**session(), 'staff_started': False, 'ga_done': asyncio.Event(),
                 'ga_checks': {'list_new_px_notes': 'DONE', 'list_new_done_and_strikes': 'DONE'},
                 'starts_at': controller.datetime.now(controller.tz()) - timedelta(seconds=1)}
        self.assertFalse(await host.hold_completed_opening(state))
        self.assertFalse(state['ga_done'].is_set())
        state['process'].send.assert_not_awaited()

    async def test_last_progress_receipt_holds_early_opening_without_an_extra_model_turn(self):
        host = controller.MiraHost(SimpleNamespace())
        state = {**session(), 'staff_started': False, 'ga_done': asyncio.Event(),
                 'pending_progress': {'first', 'last'}, 'ga_checks': {'list_new_px_notes': 'DONE'},
                 'starts_at': controller.datetime.now(controller.tz()) + timedelta(minutes=1)}
        with patch.object(host, 'say', AsyncMock()) as say:
            await host.on_worker(state, {'type': 'progress_played', 'token': 'first'})
            self.assertFalse(state['ga_done'].is_set())
            await host.on_worker(state, {'type': 'progress_played', 'token': 'last'})
        say.assert_not_awaited()
        self.assertTrue(state['ga_done'].is_set())
        self.assertTrue(state['process'].send.await_args.args[0]['wait_for_staff'])
        self.assertEqual(state['progress_acks'], {'first', 'last'})

    async def test_empty_progress_waits_for_both_absence_announcements_before_holding(self):
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='10:00', status='GA_PHASE')
        events = []
        with patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))), \
             patch.object(service, 'progress_since', AsyncMock(return_value=service.now())), \
             patch.object(service, 'new_progress', AsyncMock(return_value={'done': [], 'strikes': [], 'mentions': []})):
            out = await service.run_tool(SimpleNamespace(add=events.append), meeting, 'list_new_done_and_strikes', {})
        self.assertEqual(out['read_aloud'], 'Done të reja nuk ka. Strikes të reja nuk ka.')
        self.assertEqual(len(events), 2)
        self.assertTrue(all(event.kind == 'PROGRESS_PENDING' and not event.data['mentions'] for event in events))
        host = controller.MiraHost(SimpleNamespace(bridge=AsyncMock(return_value=out)))
        state = {**session(), 'staff_started': False, 'ga_done': asyncio.Event(),
                 'ga_checks': {'list_new_px_notes': 'DONE'},
                 'starts_at': controller.datetime.now(controller.tz()) + timedelta(minutes=1)}
        await host._tool(state, {'name': 'list_new_done_and_strikes', 'arguments': '{}'})
        self.assertFalse(state['ga_done'].is_set())
        state['process'].send.assert_not_awaited()
        with patch.object(host, 'say', AsyncMock()):
            await host.on_worker(state, {'type': 'progress_played', 'token': out['announcements'][0]['token']})
            self.assertFalse(state['ga_done'].is_set())
            await host.on_worker(state, {'type': 'progress_played', 'token': out['announcements'][1]['token']})
        self.assertTrue(state['ga_done'].is_set())
        self.assertTrue(state['process'].send.await_args.args[0]['wait_for_staff'])

    async def test_unreadable_notes_report_the_problem_without_marking_notes_as_read(self):
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='10:00', status='GA_PHASE')
        notes = [{'note_id': str(uuid.uuid4()), 'number': 1, 'text': '  \n  '}]
        events = []
        with patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))), \
             patch.object(service, 'open_notes', AsyncMock(return_value=notes)):
            out = await service.run_tool(SimpleNamespace(add=events.append), meeting, 'list_new_px_notes', {})
        self.assertIn('pa tekst të lexueshëm', out['read_aloud'])
        self.assertEqual(events[0].data['note_ids'], [])
        self.assertTrue(out['notes_token'])

    async def test_empty_notes_announcement_is_acknowledged_without_creating_a_note_mention(self):
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='10:00', status='GA_PHASE', is_test=False)
        events = []
        with patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))), \
             patch.object(service, 'open_notes', AsyncMock(return_value=[])):
            out = await service.run_tool(SimpleNamespace(add=events.append), meeting, 'list_new_px_notes', {})
        self.assertEqual(out['read_aloud'], 'Notes të reja nuk ka.')
        self.assertEqual(out['notes'], [])
        self.assertEqual(events[0].data['note_ids'], [])
        self.assertEqual(str(events[0].id), out['notes_token'])
        db = SimpleNamespace(get=AsyncMock(return_value=events[0]), execute=AsyncMock())
        await runtime.acknowledge_notes(db, meeting, events[0].id)
        self.assertEqual(events[0].kind, 'NOTES_READ')
        db.execute.assert_not_awaited()

    async def test_absent_progress_group_is_announced_without_hiding_the_nonempty_group(self):
        done = service.task_line(item('EF', '10:00', 'OFERTA', rank=0, status='DONE'))
        strike = service.task_line(item('RA', '10:00', 'RAPORTI', rank=1))
        done['owners'] = ['EF']
        strike.update(owners=['RA'], points=[{'text': 'Drafti'}])
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='10:00', status='GA_PHASE')
        for progress, empty_text, content in (
            ({'done': [done], 'strikes': [], 'mentions': []}, 'Strikes të reja nuk ka.', 'OFERTA'),
            ({'done': [], 'strikes': [strike], 'mentions': []}, 'Done të reja nuk ka.', 'RAPORTI'),
        ):
            with self.subTest(empty=empty_text), \
                 patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))), \
                 patch.object(service, 'progress_since', AsyncMock(return_value=service.now())), \
                 patch.object(service, 'new_progress', AsyncMock(return_value=progress)):
                out = await service.run_tool(SimpleNamespace(add=lambda _: None), meeting, 'list_new_done_and_strikes', {})
                self.assertEqual(len(out['announcements']), 2)
                self.assertEqual(out['read_aloud'].count(empty_text), 1)
                self.assertIn(content, out['read_aloud'])

    async def test_notes_start_with_the_content_label_and_no_item_numbers(self):
        notes = [{'note_id': str(uuid.uuid4()), 'number': 1, 'text': 'Kontrollo ofertën.'},
                 {'note_id': str(uuid.uuid4()), 'number': 2, 'text': 'Dërgo raportin.'}]
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='10:00', status='GA_PHASE')
        with patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))), \
             patch.object(service, 'open_notes', AsyncMock(return_value=notes)):
            out = await service.run_tool(SimpleNamespace(add=lambda _: None), meeting, 'list_new_px_notes', {})
        self.assertEqual(out['read_aloud'], 'Notes të reja: Kontrollo ofertën; Dërgo raportin.')
        self.assertEqual(out['next_step'], 'list_new_done_and_strikes')

    async def test_done_then_strikes_have_one_heading_per_group_and_separate_receipts(self):
        done = service.task_line(item('EF', '10:00', 'OFERTA', rank=0, status='DONE'))
        strike = service.task_line(item('RA', '10:00', 'RAPORTI', rank=1))
        done['people'] = ['Elsa'];done['owners'] = ['EF']
        second_done = {**done, 'task_id': str(uuid.uuid4()), 'spoken': 'SKEMA'}
        strike.update(people=['Rinesa'], owners=['RA'], points=[{'text': 'Drafti'}])
        mentions = [{'task_id': done['task_id'], 'kind': 'DONE', 'point_key': '', 'text': 'OFERTA'},
                    {'task_id': second_done['task_id'], 'kind': 'DONE', 'point_key': '', 'text': 'SKEMA'},
                    {'task_id': strike['task_id'], 'kind': 'STRIKE', 'point_key': 'draft', 'text': 'Drafti'}]
        events = []
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='10:00', status='GA_PHASE')
        with patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))), \
             patch.object(service, 'progress_since', AsyncMock(return_value=service.now())), \
             patch.object(service, 'new_progress', AsyncMock(return_value={'done': [done, second_done], 'strikes': [strike], 'mentions': mentions})):
            out = await service.run_tool(SimpleNamespace(add=events.append), meeting, 'list_new_done_and_strikes', {})
        spoken = [part['read_aloud'] for part in out['announcements']]
        self.assertTrue(spoken[0].startswith('Done: '))
        self.assertFalse(spoken[1].startswith('Done: '))
        self.assertTrue(spoken[2].startswith('Strikes: '))
        self.assertEqual([event.data['mentions'][0]['kind'] for event in events], ['DONE', 'DONE', 'STRIKE'])
        self.assertEqual(len({part['token'] for part in out['announcements']}), 3)

    async def test_early_ga_completion_returns_a_silent_wait_without_narration(self):
        host = controller.MiraHost(SimpleNamespace())
        state = {**session(), 'staff_started': False, 'ga_done': asyncio.Event(),
                 'ga_checks': {'list_new_px_notes': 'DONE', 'list_new_done_and_strikes': 'DONE'},
                 'starts_at': controller.datetime.now(controller.tz()) + timedelta(minutes=1)}
        out = await host._tool(state, {'name': 'end_ga_phase', 'arguments': '{}'})
        self.assertTrue(out.get('wait_for_staff'))
        self.assertTrue(out.get('silent'))
        state['process'].send.assert_not_awaited()
        self.assertTrue(state['ga_done'].is_set())
