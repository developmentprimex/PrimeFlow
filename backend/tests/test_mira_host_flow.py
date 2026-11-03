"""Reported meeting flow regressions, using synthetic staff and Notes."""
import uuid
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from fastapi import HTTPException

from tests.test_mira_host_bot import session, BRIEF
from tests.test_mira_host_service import DAY, IDS, payload, item
from app.models.mira_host import Mira1HMeeting
from app.services import mira_host as service
from app.services.mira_host_speech import speech_text
import mira_host as controller


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_person_refresh_bypasses_the_common_view_cache(self):
        meeting=Mira1HMeeting(id=uuid.uuid4(),meeting_date=DAY,slot='11:00',status='STAFF_PHASE')
        with patch.object(service,'common_payload',AsyncMock(return_value=payload([]))) as source, \
             patch.object(service,'person_context',AsyncMock(return_value={'user_id':IDS['EF']})):
            await service.run_tool(SimpleNamespace(),meeting,'get_person_brief',{'person':'EF'})
        self.assertTrue(source.await_args.kwargs['fresh'])

    async def test_recorded_discussion_is_preserved_in_the_current_turn_context(self):
        facts={'task_id':'task','turn_id':'turn','progress':'Nuk kam filluar; isha me raportin tjetër.'}
        host=controller.MiraHost(SimpleNamespace(bridge=AsyncMock(return_value={'success':True,'discussion':facts})))
        state={**session(),'current_turn':{'id':'turn','brief':BRIEF.copy()}}
        out=await host._tool(state,{'name':'record_task_discussion','arguments':'{}'})
        self.assertTrue(out['success'])
        self.assertEqual(state['current_turn']['brief']['discussion']['task'],facts)

    async def test_saved_haxhere_turns_are_skipped_without_announcing_absence(self):
        for old_status in ('WAITING','ACTIVE','DEFERRED'):
            with self.subTest(old_status=old_status):
                source=payload([]);source['users'][0]['full_name']='Haxhere Spahiu'
                turns=[SimpleNamespace(id=uuid.uuid4(),user_id=uuid.UUID(IDS[key]),status=old_status if key=='EF' else 'WAITING',
                         invited_at=None,started_at=None,ended_at=None,notes='') for key in ('EF','RA')]
                db=SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda:SimpleNamespace(all=lambda:turns))),flush=AsyncMock())
                meeting=Mira1HMeeting(id=uuid.uuid4(),meeting_date=DAY,slot='11:00',status='STAFF_PHASE')
                async def view(*args):
                    return [{'id':str(turns[1].id),'user_id':IDS['RA'],'name':'Rinesa','status':turns[1].status}]
                with patch.object(service,'common_payload',AsyncMock(return_value=source)), \
                     patch.object(service,'turns_view',view),patch.object(service,'person_context',AsyncMock(return_value=BRIEF)):
                    out=await service.next_turn(db,meeting,None,available_user_ids=[turns[1].user_id])
                self.assertEqual(turns[0].status,'SKIPPED')
                self.assertEqual(out['current']['user_id'],IDS['RA'])
                self.assertEqual(out['skipped'],[]);self.assertEqual(out['deferred'],[])

    async def test_refresh_recomputes_todo_question_for_the_same_person(self):
        task={'task_id':'a','title':'OFERTA','status':'IN_PROGRESS','period':'AM'}
        refreshed={**BRIEF,'user_id':IDS['EF'],'current':[{**task,'status':'TODO'}]}
        host=controller.MiraHost(SimpleNamespace(bridge=AsyncMock(return_value=refreshed)))
        state={**session(),'current_turn':{'id':'turn','user_id':IDS['EF'],'name':'Elsa','initials':'EF',
                                         'brief':{**BRIEF,'current':[task]}}}
        out=await host._tool(state,{'name':'get_person_brief','arguments':'{"person":"EF"}'})
        self.assertTrue(out['RADHA']['aktual_dhe_paraprak_todo'])
        self.assertEqual(state['current_turn']['brief'],refreshed)

    async def test_refresh_that_arrives_after_a_handoff_cannot_replace_the_new_person(self):
        state=session()
        async def bridge(*args):
            state['current_turn']={'id':'new','user_id':IDS['RA']}
            return {**BRIEF,'user_id':IDS['EF']}
        host=controller.MiraHost(SimpleNamespace(bridge=bridge))
        out=await host._tool(state,{'name':'get_person_brief','arguments':'{"person":"EF"}'})
        self.assertTrue(out['stale_turn'])
        self.assertNotIn('brief',state['current_turn'])

    async def test_delayed_opening_request_does_not_restart_ga_after_staff_has_started(self):
        bridge=AsyncMock()
        host=controller.MiraHost(SimpleNamespace(bridge=bridge))
        state={**session(),'staff_started':True,'ga_checks':{},'ga_results':{}}
        out=await host._tool(state,{'name':'list_new_done_and_strikes','arguments':'{}'})
        self.assertTrue(out['deferred']);bridge.assert_not_awaited()
        async def late(*args):
            state['staff_started']=True
            return {'progress_token':'late','read_aloud':'Progresi i vjetër.'}
        state.update(staff_started=False,ga_checks={'list_new_px_notes':'DONE'})
        host.bot.bridge=late
        out=await host._tool(state,{'name':'list_new_done_and_strikes','arguments':'{}'})
        self.assertTrue(out['deferred'])
        self.assertEqual(state['announcement_deferrals'],{'late'})
        self.assertNotIn('list_new_done_and_strikes',state['ga_results'])

    def test_continuation_question_uses_todo_status_in_both_slots(self):
        current={'task_id':'current','title':'OFERTA','status':'TODO','period':'AM'}
        previous={'task_id':'previous','title':'RAPORTI','status':'TODO','period':'AM'}
        blocked={'task_id':'blocked','title':'BLLOK','status':'DONE','period':'PM'}
        base={**BRIEF,'current':[current],'previous_open':[previous],'blocked':[blocked]}
        cases=[
            ('both slots todo',{},True),
            ('current percentage does not override todo',{'progress_percentages':{'current':20}},True),
            ('previous percentage does not override todo',{'progress_percentages':{'previous':20}},True),
            ('current strike does not override todo',{'new_progress':{'strikes':[{'task_id':'current','title':'OFERTA','points':[{'text':'Drafti'}]}]}},True),
            ('previous strike does not override todo',{'new_progress':{'strikes':[{'task_id':'previous','title':'RAPORTI','points':[{'text':'Drafti'}]}]}},True),
            ('current in progress without other evidence',{'current':[{**current,'status':'IN_PROGRESS'}]},False),
            ('previous in progress without other evidence',{'previous_open':[{**previous,'status':'IN_PROGRESS'}]},False),
            ('previous waiting client',{'previous_open':[{**previous,'status':'WAITING_CLIENT'}]},False),
            ('current completed',{'current':[{**current,'status':'DONE'}]},False),
            ('previous completed outside the spoken plan',{'continuation_check_tasks':[current,{**previous,'status':'DONE'}],
                                                           'previous_open':[]},False),
            ('old completion does not override current todo',{'new_progress':{'done':[{'task_id':'previous','title':'RAPORTI'}]}},True),
            ('unrelated completed task',{'new_progress':{'done':[{'task_id':'other','title':'TJETER'}]}},True),
            ('no eligible tasks',{'current':[],'previous_open':[]},False),
        ]
        for label,changes,expected in cases:
            with self.subTest(label=label):
                out=controller.turn_brief({'id':'turn','name':'Elsa','initials':'EF','brief':{**base,**changes}})
                self.assertEqual(out['aktual_dhe_paraprak_todo'],expected)
                self.assertEqual(out['pyetja_vazhdimit'],'Me çka ke vazhduar?' if expected else None)

    async def test_handoff_asks_what_the_person_worked_on_when_tasks_are_todo(self):
        task={'task_id':'current','title':'OFERTA','status':'TODO','period':'AM'}
        current={'id':'turn','name':'Elsa','initials':'EF','discord':None,'brief':{**BRIEF,'current':[task]}}
        host=controller.MiraHost(SimpleNamespace(bridge=AsyncMock(return_value={'current':current})))
        out=await host.advance(session(),None,announce=False)
        self.assertTrue(out['RADHA']['aktual_dhe_paraprak_todo'])
        self.assertIn('Me çka ke vazhduar?',out['udhezim'])
        self.assertIn("s'e ka sqaruar ende",out['udhezim'])
        self.assertIn('vetëm një herë për personin',out['udhezim'])

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

    async def test_notes_are_mentioned_together_then_continue_without_approval(self):
        notes = [{'note_id': 'n1', 'number': 1, 'text': 'FG: kontrollo ofertën.'},
                 {'note_id': 'n2', 'number': 2, 'text': 'Dërgo raportin.'}]
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='GA_PHASE')
        with patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))), \
             patch.object(service, 'open_notes', AsyncMock(return_value=notes)):
            result = await service.run_tool(SimpleNamespace(add=Mock()), meeting, 'list_new_px_notes', {})
        self.assertIn('fë gë: kontrollo ofertën.', result.get('read_aloud', ''))
        self.assertIn('Dërgo raportin.', result['read_aloud'])
        self.assertNotIn('?', result['read_aloud'])
        self.assertEqual(result['next_step'], 'list_new_done_and_strikes')
        self.assertEqual(result['notes'][0]['text'], notes[0]['text'])

    async def test_long_notes_only_mention_the_heading_and_keep_the_source_text(self):
        text = 'Oferta ' * 50 + '\nDetajet për stafin.'
        notes = [{'note_id': 'n1', 'number': 1, 'text': text}]
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='GA_PHASE')
        with patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))), \
             patch.object(service, 'open_notes', AsyncMock(return_value=notes)):
            result = await service.run_tool(SimpleNamespace(add=Mock()), meeting, 'list_new_px_notes', {})
        self.assertLessEqual(len(result['notes'][0]['read_aloud']), 180)
        self.assertNotIn('Detajet për stafin.', result['read_aloud'])
        self.assertEqual(result['notes'][0]['text'], text)

    async def test_note_conversion_is_rejected_in_every_meeting_phase(self):
        for phase in ('GA_PHASE', 'STAFF_PHASE'):
            for tool in ('prepare_task_from_note', 'create_task_from_note'):
                with self.subTest(phase=phase, tool=tool):
                    with self.assertRaises(HTTPException) as raised:
                        await service.run_tool(SimpleNamespace(), Mira1HMeeting(status=phase), tool, {})
                    self.assertEqual(raised.exception.status_code, 409)

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
                 'missing_since': controller.datetime.now(controller.tz()) - timedelta(seconds=controller.settings.MIRA_HOST_MISSING_STAFF_GRACE_SECONDS + 1)}
        with patch.object(host, 'say', AsyncMock()) as say:
            await host.watch_turn(state)
        self.assertTrue(state['ending'])
        self.assertEqual(state['reason'], 'missing_staff')
        say.assert_awaited_once()
