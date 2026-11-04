"""Host audit regressions: durable delivery, phase control and speech provenance."""
import asyncio
import uuid
import unittest
import tempfile
import json
from pathlib import Path
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from tests.test_mira_host_service import DAY, TZ, IDS, payload, item, report_rows
from tests.test_mira_host_bot import session, BRIEF
from app.models.mira_host import Mira1HEvent, Mira1HMeeting, MiraHostSettings
from app.services import mira_host as service, mira_host_runtime as runtime
from app.api.routers import mira as api
import mira_host as controller


def result(value=None, rows=()):
    return SimpleNamespace(scalar_one_or_none=lambda: value, scalar_one=lambda: value,
        scalars=lambda: SimpleNamespace(all=lambda: list(rows)), all=lambda: list(rows))


def meeting(**kw):
    return Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:50', status='STAFF_PHASE', is_test=False, **kw)


class NotesTests(unittest.IsolatedAsyncioTestCase):
    async def test_notes_query_uses_last_edit_discussion_and_real_reading(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=result()))
        await service.open_notes(db)
        query = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
        self.assertIn('ga_notes.is_discussed IS false', query)
        self.assertIn('tasks.ga_note_origin_id = ga_notes.id', query)
        self.assertIn('tasks.is_active IS true', query)
        self.assertIn('mira_desktop_sessions.note_id = ga_notes.id', query)
        self.assertIn('mira_1h_events.note_id = ga_notes.id', query)
        self.assertIn('mira_1h_events.sent_at >= ga_notes.updated_at', query)
        self.assertIn('ORDER BY ga_notes.created_at DESC', query)

    async def test_large_backlog_has_bounded_reading_and_only_acknowledges_selected_notes(self):
        notes = [{'note_id': str(uuid.uuid4()), 'number': i, 'text': 'kontrollo ofertën dhe raportin ' * 20} for i in range(41)]
        events = []
        db = SimpleNamespace(add=events.append)
        m = meeting();m.status='GA_PHASE'
        with patch.object(service, 'common_payload', AsyncMock(return_value=payload([]))), \
             patch.object(service, 'open_notes', AsyncMock(return_value=notes)):
            out = await service.run_tool(db, m, 'list_new_px_notes', {})
        self.assertLessEqual(len(out['notes']), 5)
        self.assertLessEqual(len(out['read_aloud'].split()), 69)
        self.assertTrue(out['has_more'])
        self.assertNotIn('?', out['read_aloud'])
        self.assertEqual(events[0].data['note_ids'], [n['note_id'] for n in out['notes']])
        self.assertEqual(events[0].kind, 'NOTES_PENDING')

    async def test_notes_are_not_consumed_by_fetch_or_test_mode_and_ack_is_idempotent(self):
        m = meeting();m.is_test=True
        event = Mira1HEvent(id=uuid.uuid4(), meeting_id=m.id, kind='NOTES_PENDING',
            data={'note_ids': [str(uuid.uuid4())], 'fetched_at': service.now().isoformat()})
        db = SimpleNamespace(get=AsyncMock(return_value=event), execute=AsyncMock())
        await runtime.acknowledge_notes(db, m, event.id)
        await runtime.acknowledge_notes(db, m, event.id)
        self.assertEqual(event.kind, 'NOTES_READ')
        db.execute.assert_not_awaited()

    async def test_real_ack_uses_fetch_time_so_an_edit_during_reading_stays_new(self):
        m = meeting()
        fetched = service.now() - timedelta(minutes=1)
        event = Mira1HEvent(id=uuid.uuid4(), meeting_id=m.id, kind='NOTES_PENDING',
            data={'note_ids': [str(uuid.uuid4())], 'fetched_at': fetched.isoformat()})
        db = SimpleNamespace(get=AsyncMock(return_value=event), execute=AsyncMock())
        await runtime.acknowledge_notes(db, m, event.id)
        params = db.execute.await_args.args[0].compile(dialect=postgresql.dialect()).params
        self.assertEqual(params['sent_at'], fetched)
        self.assertEqual(params['kind'], 'NOTE_MENTION')
        self.assertEqual(event.kind, 'NOTES_READ')
        await runtime.acknowledge_notes(db, m, event.id)
        self.assertEqual(db.execute.await_count, 1)

    async def test_deferred_progress_remains_unread(self):
        m = meeting()
        event = Mira1HEvent(id=uuid.uuid4(), meeting_id=m.id, kind='PROGRESS_PENDING', data={'mentions': []})
        db = SimpleNamespace(get=AsyncMock(return_value=event))
        await runtime.defer_announcement(db, m, event.id)
        self.assertEqual(event.kind, 'PROGRESS_DEFERRED')


class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_stop_request_does_not_stop_a_later_restart(self):
        db=SimpleNamespace(execute=AsyncMock(return_value=result(rows=[])))
        await runtime.stop_requests(db)
        query=str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
        self.assertIn('mira_1h_events.sent_at >= mira_1h_meetings.started_at',query)

    async def test_manual_live_meeting_stop_closes_voice_before_waiting_for_cleanup(self):
        host=controller.MiraHost(SimpleNamespace())
        state=session();host.session=state
        await host.stop('stopped_by_command')
        self.assertTrue(state['closed'].is_set())
        state['process'].close.assert_awaited_once()

    async def test_web_stop_requests_shutdown_and_does_not_claim_it_already_finished(self):
        row = MiraHostSettings(ga_participants=[], protocol_text='P', target_minutes_per_person=2, knowledge_char_budget=8000)
        db = SimpleNamespace(commit=AsyncMock())
        with patch.object(service, 'get_settings', AsyncMock(return_value=row)), \
             patch.object(runtime, 'request_stop', AsyncMock(return_value=1)) as stop:
            out = await api.switch_host(api.HostSwitch(enabled=False), db, SimpleNamespace(id=uuid.uuid4()))
        self.assertTrue(out['stop_requested'])
        self.assertIsNone(row.enabled_until)
        stop.assert_awaited_once()

    async def test_stop_request_targets_only_the_matching_live_session(self):
        fake = SimpleNamespace(bridge=AsyncMock(return_value={'jobs': [], 'stop_meetings': ['m1']}), get_guild=Mock(return_value=None))
        host = controller.MiraHost(fake);host.session=session()
        with patch.object(host, 'recover_transcripts', AsyncMock()), patch.object(host, 'stop', AsyncMock()) as stop, \
             patch.object(controller.settings, 'DISCORD_GUILD_ID', '1'):
            await host.tick(service.now());await asyncio.sleep(0)
        stop.assert_awaited_once_with('stopped_by_command')

    async def test_ga_cannot_finish_before_required_lookups_and_playback(self):
        host = controller.MiraHost(SimpleNamespace())
        state = {**session(), 'ga_checks': {}, 'ga_done': asyncio.Event(), 'staff_started': False,
                 'starts_at': service.now()-timedelta(minutes=1)}
        with patch.object(host, 'start_staff', AsyncMock(return_value={'ok': True})) as staff:
            out = await host._tool(state, {'name': 'end_ga_phase', 'arguments': '{}'})
            self.assertEqual(out['next_step'], 'list_new_px_notes')
            self.assertFalse(state['ga_done'].is_set())
            state['ga_checks']={'list_ga_tasks':'DONE','list_new_px_notes':'PENDING','list_new_done_and_strikes':'DONE'}
            out = await host._tool(state, {'name': 'end_ga_phase', 'arguments': '{}'})
            self.assertEqual(out['next_step'], 'list_new_px_notes')
            await host.on_worker(state, {'type':'note_played','token':str(uuid.uuid4())})
            await host._tool(state, {'name': 'end_ga_phase', 'arguments': '{}'})
        staff.assert_awaited_once()

    async def test_progress_handoff_waits_for_all_chunks(self):
        host = controller.MiraHost(SimpleNamespace())
        state = {**session(), 'staff_started': False, 'pending_progress': {'a', 'b'}}
        await host.on_worker(state, {'type':'progress_played','token':'a'})
        state['process'].send.assert_not_awaited()
        await host.on_worker(state, {'type':'progress_played','token':'b'})
        self.assertIn('end_ga_phase', state['process'].send.await_args.args[0]['text'])

    async def test_lookup_outage_is_explicitly_deferred_so_it_cannot_deadlock_ga(self):
        host = controller.MiraHost(SimpleNamespace(bridge=AsyncMock(side_effect=TimeoutError())))
        state = {**session(), 'ga_checks': {}, 'ga_results': {}}
        out = await host._tool(state, {'name':'list_new_px_notes','arguments':'{}'})
        self.assertTrue(out['retry_safe'])
        self.assertEqual(state['ga_checks']['list_new_px_notes'], 'DEFERRED')

    async def test_repeated_ga_lookup_does_not_replay_completed_or_inflight_audio(self):
        fake=SimpleNamespace(bridge=AsyncMock())
        host=controller.MiraHost(fake)
        state={**session(),'ga_checks':{'list_new_px_notes':'PENDING'},
            'ga_results':{'list_new_px_notes':{'read_aloud':'Shënimi 1: Oferta'}}}
        out=await host._tool(state,{'name':'list_new_px_notes','arguments':'{}'})
        self.assertTrue(out['pending_playback'])
        self.assertNotIn('read_aloud',out)
        state['ga_checks']['list_new_px_notes']='DONE'
        out=await host._tool(state,{'name':'list_new_px_notes','arguments':'{}'})
        self.assertEqual(out['next_step'],'list_new_done_and_strikes')
        self.assertTrue(out['already_completed'])
        fake.bridge.assert_not_awaited()

    async def test_audio_failure_holds_the_person_budget_then_records_technical_timeout(self):
        host = controller.MiraHost(SimpleNamespace())
        state = {**session(), 'turn_started': service.now()-timedelta(minutes=10), 'turn_nudged': False,
                 'current_turn': {'id':'t1','discord':{'discord_user_id':'11'}}, 'audio_failures': {'11':service.now()}}
        with patch.object(host, 'in_voice', return_value=True), patch.object(host, 'advance', AsyncMock()) as advance:
            await host.watch_turn(state)
            advance.assert_not_awaited()
            state['audio_failures']['11']=service.now()-timedelta(seconds=31)
            await host.watch_turn(state)
        self.assertEqual(advance.await_args.kwargs['outcome'], 'TIMEOUT')
        self.assertIn('teknik', advance.await_args.args[1])


class PmTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_haxhere_pm_turn_is_not_invited_or_reported_as_missing(self):
        m,event=self.state()
        event.data['queue'][0].update(name='Haxhere Spahiu',person='Haxhere Spahiu',status='WAITING')
        self.assertEqual([p['user_id'] for p in runtime.pm_state(event)['turns']],[IDS['RA']])
        with patch.object(runtime,'pm_event',AsyncMock(return_value=event)):
            out=await runtime.next_pm_turn(SimpleNamespace(),m,expected_turn_id=None,available_discord_ids=['12'])
        self.assertEqual(out['current']['user_id'],IDS['RA'])
        self.assertEqual(event.data['queue'][0]['status'],'SKIPPED')
        self.assertEqual(out['skipped'],[]);self.assertEqual(out['deferred'],[])

    def state(self):
        m=meeting()
        queue=[{'id':'PM_'+IDS[k], 'user_id':IDS[k], 'person':k,'name':k,
                'status':'ACTIVE' if i==0 else 'WAITING', 'discord':{'discord_user_id':str(i+11)}} for i,k in enumerate(('EF','RA'))]
        return m, Mira1HEvent(id=uuid.uuid4(),meeting_id=m.id,kind='PM_REVIEW',data={'queue':queue})

    async def test_pm_requires_a_report_and_moves_one_person_at_a_time(self):
        m,event=self.state();db=SimpleNamespace()
        with patch.object(runtime,'pm_event',AsyncMock(return_value=event)):
            with self.assertRaises(HTTPException):
                await runtime.next_pm_turn(db,m,expected_turn_id='PM_'+IDS['EF'])
            out=await runtime.record_pm_review(db,m,service.PmDiscussion(turn_id='PM_'+IDS['EF'],continuation='E vazhdoj pas pushimit'),SimpleNamespace(id=uuid.UUID(IDS['EF'])))
            self.assertTrue(out['success'])
            next_person=await runtime.next_pm_turn(db,m,expected_turn_id='PM_'+IDS['EF'])
            self.assertEqual(next_person['current']['user_id'],IDS['RA'])
            with self.assertRaises(HTTPException):
                await runtime.next_pm_turn(db,m,expected_turn_id='PM_'+IDS['EF'])
            await runtime.record_pm_review(db,m,service.PmDiscussion(turn_id='PM_'+IDS['RA'],postponement='Nesër; pres furnitorin'),SimpleNamespace(id=uuid.UUID(IDS['RA'])))
            done=await runtime.next_pm_turn(db,m,expected_turn_id='PM_'+IDS['RA'])
        self.assertIsNone(done['current'])
        self.assertTrue(all(p['status']=='DONE' for p in event.data['queue']))

    async def test_pm_refuses_another_speakers_facts(self):
        m,event=self.state()
        with patch.object(runtime,'pm_event',AsyncMock(return_value=event)):
            out=await runtime.record_pm_review(SimpleNamespace(),m,service.PmDiscussion(turn_id='PM_'+IDS['EF'],continuation='Gati'),SimpleNamespace(id=uuid.UUID(IDS['RA'])))
        self.assertFalse(out['success'])
        self.assertNotIn('discussion',event.data['queue'][0])

    async def test_stopping_pm_marks_unfinished_people_skipped_and_retains_their_facts(self):
        m,event=self.state()
        event.data['queue'][0]['discussion']={'continuation':'E vazhdoj pas pushimit'}
        db=SimpleNamespace(execute=AsyncMock(return_value=result(event)))
        await runtime.finish_pm(db,m,service.now())
        self.assertTrue(all(p['status']=='SKIPPED' for p in event.data['queue']))
        self.assertEqual(event.data['queue'][0]['discussion']['continuation'],'E vazhdoj pas pushimit')

    async def test_pm_presence_skips_verified_absence_but_test_mode_keeps_role_players(self):
        for test in (False,True):
            m,event=self.state();m.is_test=test
            for p in event.data['queue']:p['status']='WAITING'
            with patch.object(runtime,'pm_event',AsyncMock(return_value=event)):
                out=await runtime.next_pm_turn(SimpleNamespace(),m,expected_turn_id=None,available_discord_ids=['12'])
            self.assertEqual(out['current']['user_id'],IDS['EF'] if test else IDS['RA'])
            self.assertEqual(len(out['deferred']),0 if test else 1)

    async def test_pm_lookup_recovery_cannot_consume_the_next_person(self):
        current={'id':'PM_'+IDS['RA'],'person':'RA','discord':None}
        bridge=AsyncMock(side_effect=[TimeoutError(),{'current':current,'turns':[current],'deferred':[]}])
        host=controller.MiraHost(SimpleNamespace(bridge=bridge))
        state={**session(),'current_turn':None,'pm_reviewed':True,'pm_current':{'id':'PM_'+IDS['EF']}}
        out=await host.advance(state,None,announce=False,expected_turn_id='PM_'+IDS['EF'])
        self.assertEqual(out['turn_id'],'PM_'+IDS['RA'])
        self.assertEqual(bridge.await_count,2)
        self.assertTrue(bridge.await_args.args[0].endswith('/pm/current'))

    async def test_lost_pm_initialization_cannot_pretend_the_whole_review_is_finished(self):
        bridge=AsyncMock(side_effect=[TimeoutError(),{'current':None,'initialized':False}])
        host=controller.MiraHost(SimpleNamespace(bridge=bridge))
        state={**session(),'current_turn':None,'pm_reviewed':True}
        with self.assertRaises(ValueError):
            await host.advance(state,None,announce=False)
        self.assertFalse(state['ending'])

    async def test_pm_is_started_even_without_any_main_slot_turns(self):
        fake=SimpleNamespace(bridge=AsyncMock(return_value={'turns':[]}))
        host=controller.MiraHost(fake)
        state={**session(),'slot':'11:50'}
        with patch.object(host,'advance',AsyncMock(return_value={'PM_RISHIKIMI':[]})) as advance:
            await host._start_staff(state,announce=False)
        advance.assert_awaited_once()
        self.assertFalse(state['ending'])


class DataTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_progress_part_only_acknowledges_its_own_task_and_points(self):
        ids=[str(uuid.uuid4()),str(uuid.uuid4())]
        done=service.task_line(item('EF','11:00','OFERTA',rank=0,task_id=ids[0],status='DONE'))
        strike=service.task_line(item('RA','11:00','RAPORTI',rank=1,task_id=ids[1]))
        done['owners']=['EF'];strike.update(owners=['RA'],points=[{'key':str(i),'text':f'Pika {i}'} for i in range(4)])
        mentions=[{'task_id':ids[0],'kind':'DONE','point_key':'','text':'OFERTA'}]+[
            {'task_id':ids[1],'kind':'STRIKE','point_key':str(i),'text':f'Pika {i}'} for i in range(4)]
        events=[]
        with patch.object(service,'common_payload',AsyncMock(return_value=payload([]))), \
             patch.object(service,'progress_since',AsyncMock(return_value=service.now())), \
             patch.object(service,'new_progress',AsyncMock(return_value={'done':[done],'strikes':[strike],'mentions':mentions})):
            m=meeting();m.status='GA_PHASE'
            out=await service.run_tool(SimpleNamespace(add=events.append),m,'list_new_done_and_strikes',{})
        self.assertEqual(len(out['announcements']),2)
        self.assertEqual([len(e.data['mentions']) for e in events],[1,4])
        self.assertEqual(len({part['token'] for part in out['announcements']}),2)
        self.assertEqual({m['point_key'] for m in events[1].data['mentions']},{'0','1','2','3'})
        self.assertIn('4 strike',out['announcements'][1]['read_aloud'])
        self.assertTrue(out['announcements'][0]['read_aloud'].startswith('Done: '))

    async def test_same_title_does_not_merge_distinct_tasks_or_read_receipts(self):
        done_at=datetime(2026,10,21,10,30,tzinfo=TZ).isoformat()
        data=service.SlotData(payload([item('EF','11:00','OFERTA',rank=i,status='DONE',completed_at=done_at,description=f'Klienti {i}') for i in range(2)]),DAY)
        db=SimpleNamespace(execute=AsyncMock(return_value=result(rows=report_rows(data))))
        with patch.object(service,'mentioned',AsyncMock(return_value=set())):
            m=meeting();m.slot='11:00'
            progress=await service.new_progress(db,m,data)
        self.assertEqual(len(progress['done']),2)
        self.assertEqual(len({m['task_id'] for m in progress['mentions']}),2)
        self.assertNotEqual(progress['done'][0]['spoken'],progress['done'][1]['spoken'])

    async def test_delayed_transcript_preserves_turn_and_actual_speech_time(self):
        host=controller.MiraHost(SimpleNamespace())
        state=session();state['meeting']=str(uuid.uuid4())
        spoken=service.now()-timedelta(minutes=1)
        with patch.object(host,'persist_transcript'):
            await host.on_worker(state,{'type':'transcript','role':'staff','speaker_id':'11','text':'Oferta u dërgua',
                'speech_id':'s','turn_id':'old','started_at':spoken.isoformat(),'ended_at':(spoken+timedelta(seconds=2)).isoformat()})
        self.assertEqual(state['lines'][0]['at'],spoken.isoformat())
        m=meeting();m.host_transcript=[]
        await service.append_transcript(SimpleNamespace(),m,state['lines'])
        self.assertEqual(m.host_transcript[0]['turn_id'],'old')
        later=spoken+timedelta(seconds=5)
        self.assertTrue(service.lines_during(m.host_transcript,later.isoformat(),None,turn_id='old'))
        self.assertFalse(service.lines_during(m.host_transcript,later.isoformat(),None,turn_id='new'))

    def test_task_handoff_keeps_important_description_and_marker_comment(self):
        task=service.task_line(item('EF','11:00','OFERTA',rank=0,description='Mos e dërgo pa kontroll',one_h_marker_comment='Prit furnitorin'))
        out=controller.turn_brief({'id':'t','name':'Elsa','initials':'EF','brief':{**BRIEF,'current':[task]}})
        self.assertEqual(out['plan_discutimi'][0]['pershkrimi'],'Mos e dërgo pa kontroll')
        self.assertEqual(out['plan_discutimi'][0]['komenti_simbolit'],'Prit furnitorin')

    async def test_prompts_include_only_the_current_workflow(self):
        row=MiraHostSettings(ga_participants=[],protocol_text=service.DEFAULT_PROTOCOL,target_minutes_per_person=2,knowledge_char_budget=8000)
        with patch.object(service,'common_payload',AsyncMock(return_value=payload([]))), \
             patch.object(service,'knowledge_context',AsyncMock(return_value=('',False))),patch.object(service,'memory_context',AsyncMock(return_value='')):
            policies=await service.instructions(SimpleNamespace(),meeting(),row,all_phases=True)
        self.assertIn('list_new_px_notes',policies['GA_PHASE'])
        self.assertNotIn('list_new_px_notes',policies['STAFF_PHASE'])
        self.assertIn('record_pm_review',policies['PM_REVIEW'])
        self.assertNotIn('record_task_discussion',policies['PM_REVIEW'])
        self.assertNotIn('save_px_note',policies['ENDING'])
        self.assertNotIn('BZ Det nga Stafi për GA',policies['STAFF_PHASE'])


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_receipts_survive_a_crash_and_are_retried_without_replaying_audio(self):
        mid=str(uuid.uuid4());token=str(uuid.uuid4())
        state={**session(),'meeting':mid,'notes_acks':{token},'finished':False}
        calls=[]
        async def bridge(path,body):
            calls.append((path,body));return {}
        host=controller.MiraHost(SimpleNamespace(bridge=bridge))
        with tempfile.TemporaryDirectory() as directory,patch.object(controller,'RECOVERY_DIR',Path(directory)):
            host.persist_transcript(state)
            saved=json.loads((Path(directory)/(mid+'.json')).read_text(encoding='utf-8'))
            self.assertEqual(saved['acknowledgements']['notes_acks'],[token])
            await host.recover_transcripts()
            self.assertFalse(list(Path(directory).glob('*.json')))
        self.assertTrue(calls[0][0].endswith('/notes/ack'))
        self.assertEqual(calls[0][1],{'token':token})

    async def test_failed_ack_retains_recovery_file_even_when_finish_succeeds(self):
        mid=str(uuid.uuid4());token=str(uuid.uuid4())
        state={**session(),'meeting':mid,'notes_acks':{token},'process':None,'finished':False,'reason':'completed'}
        async def bridge(path,body):
            if path.endswith('/notes/ack'):raise ValueError('offline')
            return {}
        host=controller.MiraHost(SimpleNamespace(bridge=bridge))
        with tempfile.TemporaryDirectory() as directory,patch.object(controller,'RECOVERY_DIR',Path(directory)):
            await host.finish(state)
            self.assertTrue((Path(directory)/(mid+'.json')).exists())

    async def test_notification_lease_retry_and_acknowledgement(self):
        at=service.now()
        event=Mira1HEvent(kind='BRIEF',data={'attempts':0,'delivery_status':'PENDING','expires_at':(at+timedelta(minutes=2)).isoformat()},sent_at=None)
        db=SimpleNamespace(execute=AsyncMock(return_value=result(event)))
        args=dict(day=DAY,slot='11:00',kind='BRIEF',user_id=IDS['EF'])
        self.assertTrue(await service.claim_event(db,'key',at=at,**args))
        self.assertFalse(await service.claim_event(db,'key',at=at+timedelta(seconds=1),**args))
        await runtime.notification_result(db,'key',False,at=at+timedelta(seconds=2))
        self.assertTrue(await service.claim_event(db,'key',at=at+timedelta(seconds=3),**args))
        await runtime.notification_result(db,'key',True,at=at+timedelta(seconds=4))
        self.assertFalse(await service.claim_event(db,'key',at=at+timedelta(seconds=40),**args))
        self.assertEqual(event.data['attempts'],2)
        self.assertEqual(event.data['delivery_status'],'SENT')

    async def test_lost_notification_ack_retries_ack_without_resending_message(self):
        job={'kind':'brief','slot':'11:00','text':'Takimi','notification_key':'brief:key'}
        acks=0
        async def bridge(path,body):
            nonlocal acks
            if path.endswith('/tick'):return {'jobs':[job]}
            acks+=1
            if acks==1:raise ValueError('lost response')
            return {'ok':True}
        host=controller.MiraHost(SimpleNamespace(bridge=bridge,get_guild=Mock(return_value=None)))
        with patch.object(host,'recover_transcripts',AsyncMock()),patch.object(host,'notify',AsyncMock()) as notify, \
             patch.object(controller.settings,'DISCORD_GUILD_ID','1'):
            await host.tick(service.now());await asyncio.sleep(0)
            await host.tick(service.now());await asyncio.sleep(0)
        self.assertEqual(notify.await_count,1)
        self.assertEqual(acks,2)
