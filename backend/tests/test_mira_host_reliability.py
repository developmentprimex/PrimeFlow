"""Regression cases at the controller/service boundaries; no network or database writes."""
import asyncio
import uuid
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from tests.test_mira_host_service import DAY, IDS, payload
from tests.test_mira_host_bot import session, BRIEF
import mira_host as controller
from app.services import mira_host as service
from app.models.mira_host import Mira1HMeeting
from fastapi import HTTPException
from datetime import timedelta


class TurnGuards(unittest.IsolatedAsyncioTestCase):
    async def test_waiting_staff_keep_their_order_before_they_are_invited(self):
        first = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.UUID(IDS['EF']), status='WAITING', invited_at=None,
                                started_at=None, ended_at=None, notes='')
        second = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.UUID(IDS['RA']), status='WAITING', invited_at=None,
                                 started_at=None, ended_at=None, notes='')
        turns = [first, second]
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: turns))), flush=AsyncMock())
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='STAFF_PHASE')
        async def view(*args): return [{'id':str(t.id), 'user_id':str(t.user_id), 'status':t.status} for t in turns]
        with patch.object(service,'common_payload',AsyncMock(return_value=payload([]))), \
             patch.object(service,'turns_view',view), patch.object(service,'person_context',AsyncMock(return_value={})):
            result = await service.next_turn(db, meeting, None, available_user_ids=[second.user_id])
        self.assertEqual(result['current']['id'], str(first.id))
        self.assertEqual(result['upcoming']['id'], str(second.id))

    async def test_deferred_people_receive_an_invitation_before_waiting(self):
        targets = []
        deferred = {'id': 't2', 'user_id': IDS['EF'], 'name': 'Elsa', 'discord': {'discord_user_id': '11'}}
        async def bridge(path, payload): return {'current': None, 'deferred': [deferred]}
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        async def notify(target, text): targets.append(target['discord_user_id'])
        state = session()
        state['current_turn'] = None
        with patch.object(host, 'notify', notify):
            await host.advance(state, None, announce=False)
            await host.advance(state, None, announce=False)
            await asyncio.gather(*list(state.get('notification_tasks', set())))
        self.assertEqual(targets, ['11'])

    async def test_handoff_cannot_consume_a_turn_changed_while_waiting_for_the_lock(self):
        moves = []
        async def bridge(path, payload):
            moves.append(payload)
            return {'current': None}
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        state = session()
        lock = state['transition_lock'] = asyncio.Lock()
        await lock.acquire()
        task = asyncio.create_task(host.tool(state, {'name': 'end_person_turn', 'call_id': 'race', 'arguments': '{"turn_id":"t1"}'}))
        await asyncio.sleep(0)
        state['current_turn'] = {'id': 't2'}
        lock.release()
        await task
        self.assertEqual(moves, [])
        self.assertIn('error', state['process'].send.await_args.args[0]['output'])

    async def test_time_limit_aborts_instead_of_reporting_success(self):
        finishes = []
        async def bridge(path, payload):
            if path.endswith('/finish'): finishes.append(payload['reason'])
            return {}
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        async def connect(state, *args, **kwargs):
            state.update(meeting='m1', staff_started=True)
            return {'starts_at': (controller.datetime.now(controller.tz())-timedelta(minutes=10)).isoformat()}
        with patch.object(host, 'connect', connect), patch.object(controller, 'MAX_MEETING_MINUTES', -1):
            await host.run('11:00', SimpleNamespace(), SimpleNamespace())
        self.assertEqual(finishes, ['timeout'])

    async def test_stale_expected_turn_cannot_finish_the_next_person(self):
        turn = SimpleNamespace(id=uuid.uuid4(), status='ACTIVE')
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [turn]))))
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='STAFF_PHASE')
        with self.assertRaises(HTTPException) as raised:
            await service.next_turn(db, meeting, None, expected_turn_id=uuid.uuid4())
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(turn.status, 'ACTIVE')

    async def test_ended_meeting_rejects_a_handoff(self):
        meeting = Mira1HMeeting(id=uuid.uuid4(), status='DONE')
        with self.assertRaises(HTTPException):
            await service.next_turn(SimpleNamespace(), meeting, None)

    async def test_missing_staff_are_deferred_without_being_reported(self):
        turn = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.UUID(IDS['EF']), status='DEFERRED', invited_at=None,
                               started_at=None, ended_at=None, notes='')
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [turn]))), flush=AsyncMock())
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='STAFF_PHASE')
        async def view(*args): return [{'id': str(turn.id), 'user_id': str(turn.user_id), 'status': turn.status}]
        with patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))), patch.object(service, 'turns_view', view):
            result = await service.next_turn(db, meeting, None, available_user_ids=[])
        self.assertIsNone(result['current'])
        self.assertEqual(turn.status, 'DEFERRED')
        self.assertEqual(len(result['deferred']), 1)

    async def test_aborted_active_turn_is_not_marked_reported(self):
        turn = SimpleNamespace(status='ACTIVE', ended_at=None)
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: iter([turn]))))
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='STAFF_PHASE', host_transcript=[], voice_meeting_id=uuid.uuid4())
        await service.finish_meeting(db, meeting, 'timeout')
        self.assertEqual((meeting.status, turn.status), ('ABORTED', 'SKIPPED'))

    async def test_replayed_call_runs_the_transition_once(self):
        moves = []
        async def bridge(path, payload):
            moves.append(payload)
            return {'current': {'id': 't2', 'name': 'Rinesa', 'initials': 'RA', 'brief': BRIEF}, 'upcoming': None}
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        state = session()
        state['current_turn'] = {'id': 't1'}
        message = {'name': 'end_person_turn', 'call_id': 'same', 'arguments': '{"turn_id":"t1"}'}
        await asyncio.gather(host.tool(state, message), host.tool(state, message))
        self.assertEqual(len(moves), 1)

    async def test_stale_model_turn_id_cannot_advance(self):
        host = controller.MiraHost(SimpleNamespace(bridge=AsyncMock(return_value={'current': None})))
        state = session()
        state['current_turn'] = {'id': 't2'}
        await host.tool(state, {'name': 'end_person_turn', 'call_id': 'stale', 'arguments': '{"turn_id":"t1"}'})
        self.assertIn('error', state['process'].send.await_args.args[0]['output'])


class WriteGuards(unittest.IsolatedAsyncioTestCase):
    async def test_negative_new_utterance_cannot_confirm_a_task(self):
        proposal = SimpleNamespace(id=uuid.uuid4(), meeting_id=uuid.uuid4(), kind='TASK_PROPOSAL', data={
            'speech_id': 'first', 'presented_at': service.now().isoformat(), 'expires_at': (service.now()+timedelta(minutes=5)).isoformat(),
            'arguments': {'note_id': str(uuid.uuid4()), 'assignees': ['EF'], 'due_date': DAY.isoformat(), 'deadline': False}})
        db = SimpleNamespace(get=AsyncMock(return_value=proposal))
        meeting = Mira1HMeeting(id=proposal.meeting_id, status='GA_PHASE')
        result = await service.confirm_task_proposal(db, meeting, SimpleNamespace(), str(proposal.id),
            speech_id='second', speech_text='Jo, mos e krijo', speech_started_at=service.now().isoformat())
        self.assertFalse(result['success'])

    async def test_prepared_task_needs_new_ga_confirmation_and_cannot_be_created_twice(self):
        note = SimpleNamespace(id=uuid.uuid4(), is_converted_to_task=False, content='Oferta\nDetajet e plota', department_id=None)
        events, created = {}, []
        async def get(model, key, **kwargs):
            return note if model is service.GaNote else events.get(key)
        def add(event):
            if event.id: events[event.id] = event
        async def user_api(actor, method, path, *, body):
            created.append(body)
            return {'id': str(uuid.uuid4())}
        db = SimpleNamespace(get=get, add=add, commit=AsyncMock(), execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(events.values())))))
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='GA_PHASE')
        actor = SimpleNamespace(id=uuid.UUID(IDS['DV']))
        with patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))), \
             patch.object(service, 'user_for_discord', AsyncMock(return_value=actor)), \
             patch.object(service, 'get_settings', AsyncMock(return_value=SimpleNamespace(ga_participants=None))), \
             patch.object(service, 'acting_user', AsyncMock(return_value=actor)), \
             patch('app.services.discord_task_tools.user_api', user_api):
            proposal = await service.run_tool(db, meeting, 'prepare_task_from_note',
                {'note_id': str(note.id), 'assignees': ['EF'], 'due_date': DAY.isoformat(), 'deadline': False},
                speaker_id='11', speech_id='first')
            args = {'proposal_id': proposal['proposal_id']}
            denied = await service.run_tool(db, meeting, 'create_task_from_note', args, speaker_id='11', speech_id='first')
            unread = await service.run_tool(db, meeting, 'create_task_from_note', args, speaker_id='11', speech_id='second',
                speech_text='Po, krijoje', speech_started_at=service.now().isoformat())
            self.assertFalse(unread['success'])
            await service.acknowledge_proposal(db, meeting, uuid.UUID(proposal['proposal_id']), service.now().isoformat())
            first = await service.run_tool(db, meeting, 'create_task_from_note', args, speaker_id='11', speech_id='third',
                speech_text='Po, krijoje', speech_started_at=(service.now()+timedelta(milliseconds=1)).isoformat())
            repeat = await service.run_tool(db, meeting, 'create_task_from_note', args, speaker_id='11', speech_id='second')
        self.assertFalse(denied['success'])
        self.assertTrue(first['success'])
        self.assertEqual(repeat, first)
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]['description'], 'Oferta\nDetajet e plota')
        self.assertEqual(created[0]['assignees'], [IDS['EF']])

    async def test_a_superseded_proposal_cannot_be_confirmed(self):
        proposal = SimpleNamespace(meeting_id=uuid.uuid4(), kind='TASK_PROPOSAL', data={'speech_id':'old', 'superseded':True})
        result = await service.confirm_task_proposal(SimpleNamespace(get=AsyncMock(return_value=proposal)),
            Mira1HMeeting(id=proposal.meeting_id), SimpleNamespace(), str(uuid.uuid4()), speech_id='new',
            speech_text='po krijoje', speech_started_at=service.now().isoformat())
        self.assertFalse(result['success'])
        self.assertIn('zëvendësuar', result['error'])

    async def test_unknown_speaker_cannot_prepare_or_save_notes(self):
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='GA_PHASE')
        with self.assertRaises(HTTPException):
            await service.authorize_speaker(SimpleNamespace(), meeting, service.SlotData(payload([]), DAY),
                                            speaker_id=None, speech_id=None, ga_only=True)

    async def test_non_ga_speaker_cannot_confirm_a_task(self):
        meeting = Mira1HMeeting(id=uuid.uuid4(), status='GA_PHASE')
        actor = SimpleNamespace(id=uuid.UUID(IDS['EF']))
        row = SimpleNamespace(ga_participants=None)
        with patch.object(service, 'user_for_discord', AsyncMock(return_value=actor)), patch.object(service, 'get_settings', AsyncMock(return_value=row)):
            with self.assertRaises(HTTPException):
                await service.authorize_speaker(SimpleNamespace(), meeting, service.SlotData(payload([]), DAY),
                                                speaker_id='11', speech_id='utterance1', ga_only=True)

    async def test_confirmation_needs_a_new_utterance_and_preserves_exact_proposal(self):
        request = {'note_id': str(uuid.uuid4()), 'assignees': ['EF'], 'due_date': DAY.isoformat(), 'deadline': False}
        proposal = SimpleNamespace(id=uuid.uuid4(), meeting_id=uuid.uuid4(), kind='TASK_PROPOSAL',
            data={'arguments': request, 'speech_id': 'first', 'expires_at': (service.now()+timedelta(minutes=5)).isoformat(), 'note_text': 'note'})
        db = SimpleNamespace(get=AsyncMock(return_value=proposal))
        meeting = Mira1HMeeting(id=proposal.meeting_id, status='GA_PHASE')
        with patch.object(service, 'create_task', AsyncMock(return_value={'success': True})):
            result = await service.confirm_task_proposal(db, meeting, SimpleNamespace(), str(proposal.id), speech_id='first')
        self.assertFalse(result['success'])


class ProgressDelivery(unittest.IsolatedAsyncioTestCase):
    async def test_completed_progress_playback_resumes_the_meeting_without_user_prompting(self):
        host = controller.MiraHost(SimpleNamespace())
        state = {**session(), 'staff_started': False}
        await host.on_worker(state, {'type':'progress_played', 'token':'progress-token'})
        command = state['process'].send.await_args.args[0]
        self.assertEqual(command['type'], 'say')
        self.assertIn('end_ga_phase', command['text'])
        self.assertIn('progress-token', state['progress_acks'])

    async def test_late_recovered_lines_invalidate_the_old_summary(self):
        meeting = Mira1HMeeting(status='ABORTED', summary_status='READY', host_transcript=[])
        await service.append_transcript(SimpleNamespace(), meeting, [{'id': 'line1', 'text': 'Raportimi u ruajt me vonesë'}])
        self.assertEqual(meeting.summary_status, 'PENDING')

    async def test_final_upload_outage_is_recovered_by_the_next_controller(self):
        meeting_id = str(uuid.uuid4())
        state = {**session(), 'meeting': meeting_id, 'finished': False, 'reason': 'completed', 'process': None,
                 'lines': [{'id': str(uuid.uuid4()), 'text': 'Oferta u dërgua'}]}
        async def offline(path, payload): raise ValueError('offline')
        received = []
        async def online(path, payload):
            received.append((path, payload))
            return {'ok': True}
        with tempfile.TemporaryDirectory() as directory, patch.object(controller, 'RECOVERY_DIR', Path(directory)):
            host = controller.MiraHost(SimpleNamespace(bridge=offline))
            await host.finish(state)
            self.assertTrue(list(Path(directory).glob('*.json')))
            restarted = controller.MiraHost(SimpleNamespace(bridge=online))
            await restarted.recover_transcripts()
            self.assertEqual(received[0][1]['lines'][0]['text'], 'Oferta u dërgua')
            self.assertTrue(received[-1][0].endswith('/finish'))
            self.assertFalse(list(Path(directory).glob('*.json')))

    async def test_lost_upload_response_does_not_duplicate_transcript_lines(self):
        meeting = Mira1HMeeting(host_transcript=[])
        line = {'id': str(uuid.uuid4()), 'at': service.now().isoformat(), 'role': 'staff', 'speaker': 'Elsa', 'text': 'Oferta u dërgua'}
        await service.append_transcript(SimpleNamespace(), meeting, [line])
        await service.append_transcript(SimpleNamespace(), meeting, [line])
        self.assertEqual(len(meeting.host_transcript), 1)

    def test_recorded_discussion_is_visible_with_the_next_person_brief(self):
        brief = {**BRIEF, 'current': [{**BRIEF['current'][0], 'task_id': IDS['EF']}],
                 'discussion': {IDS['EF']: {'progress': 'Oferta u dërgua', 'finish_at': 'nesër'}}}
        result = controller.turn_brief({'id': 'turn', 'name': 'Elsa', 'initials': 'EF', 'brief': brief})
        self.assertEqual(result['plan_discutimi'][0]['diskutuar']['finish_at'], 'nesër')

    async def test_acknowledgement_marks_exactly_the_fetched_batch_once(self):
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='GA_PHASE')
        event = SimpleNamespace(meeting_id=meeting.id, kind='PROGRESS_PENDING', sent_at=service.now(), data={
            'fetched_at': service.now().isoformat(), 'mentions': [
                {'task_id': IDS['EF'], 'kind': 'DONE', 'point_key': '', 'text': 'Oferta'}]})
        db = SimpleNamespace(get=AsyncMock(return_value=event))
        marked = []
        async def remember(*args): marked.append(args[2:])
        with patch.object(service, 'remember', remember):
            first = await service.acknowledge_progress(db, meeting, uuid.uuid4())
            second = await service.acknowledge_progress(db, meeting, uuid.uuid4())
        self.assertTrue(first['ok'])
        self.assertTrue(second['ok'])
        self.assertEqual(len(marked), 1)
        self.assertEqual(event.kind, 'PROGRESS_READ')

    async def test_other_meetings_cannot_acknowledge_a_batch(self):
        db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(meeting_id=uuid.uuid4(), kind='PROGRESS_PENDING')))
        with self.assertRaises(HTTPException):
            await service.acknowledge_progress(db, Mira1HMeeting(id=uuid.uuid4()), uuid.uuid4())

    async def test_changed_note_invalidates_proposal(self):
        proposal = SimpleNamespace(meeting_id=uuid.uuid4(), kind='TASK_PROPOSAL', data={
            'arguments': {'note_id': str(uuid.uuid4()), 'assignees': ['EF'], 'due_date': DAY.isoformat(), 'deadline': False},
            'speech_id': 'first', 'presented_at': (service.now()-timedelta(seconds=1)).isoformat(),
            'expires_at': (service.now()+timedelta(minutes=5)).isoformat(), 'note_text': 'old'})
        note = SimpleNamespace(content='new', is_converted_to_task=False)
        db = SimpleNamespace(get=AsyncMock(side_effect=[proposal, note]))
        meeting = Mira1HMeeting(id=proposal.meeting_id, status='GA_PHASE')
        result = await service.confirm_task_proposal(db, meeting, SimpleNamespace(), str(uuid.uuid4()), speech_id='second',
            speech_text='Po, krijoje', speech_started_at=service.now().isoformat())
        self.assertFalse(result['success'])
        self.assertIn('ndryshuar', result['error'])

    async def test_discussion_is_limited_to_the_active_persons_tasks(self):
        turn = SimpleNamespace(id=uuid.uuid4(), meeting_id=uuid.uuid4(), status='ACTIVE', user_id=uuid.UUID(IDS['EF']))
        db = SimpleNamespace(get=AsyncMock(return_value=turn))
        meeting = Mira1HMeeting(id=turn.meeting_id, meeting_date=DAY, slot='11:00', status='STAFF_PHASE')
        args = service.Discussion(turn_id=str(turn.id), task_id=str(uuid.uuid4()), progress='Progres')
        result = await service.record_discussion(db, meeting, service.SlotData(payload([]), DAY), args, speech_id='speech')
        self.assertFalse(result['success'])

