"""Meeting restart, PM initialization and nonblocking upload regressions (no live services)."""
import asyncio
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from tests.test_mira_host_service import DAY, IDS, NAMES, item, payload
from tests.test_mira_host_bot import BRIEF, session
from tests.test_mira_host_runtime import result
from app.models.mira_host import Mira1HMeeting, Mira1HEvent
from app.services import mira_host as service, mira_host_runtime as runtime
import mira_host as controller


class RestartTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_rejoin_resumes_only_unfinished_available_staff_and_preserves_facts(self):
        statuses={'EF':'ACTIVE','RA':'DONE','EH':'WAITING','DV':'DEFERRED','EP':'TIMEOUT','OH':'SKIPPED'}
        turns=[SimpleNamespace(id=uuid.uuid4(),user_id=uuid.UUID(IDS[key]),status=status,
            notes='Raportimi i ruajtur',order_idx=index,started_at=None,invited_at=None,ended_at=None)
            for index,(key,status) in enumerate(statuses.items())]
        by_user={str(t.user_id):t for t in turns}
        meeting=Mira1HMeeting(id=uuid.uuid4(),meeting_date=DAY,slot='11:00',status='STAFF_PHASE',
            join_attempts=1,host_transcript=[],voice_meeting_id=uuid.uuid4())
        source=payload([item(key,'11:00',key,rank=i) for i,key in enumerate(statuses)],absent=('DV',))
        next(u for u in source['users'] if u['id']==IDS['OH'])['full_name']='Haxhere Spahiu'
        db=SimpleNamespace(execute=AsyncMock(side_effect=[SimpleNamespace(scalars=lambda:iter(turns[:1]+turns[2:4])),None,
            SimpleNamespace(scalar_one=lambda:meeting),SimpleNamespace(scalars=lambda:iter(turns)),result(rows=turns)]),
            add=Mock(),flush=AsyncMock())
        async def view(*_):
            return [{'id':str(t.id),'user_id':str(t.user_id),'status':t.status,'name':'Synthetic staff'}
                    for t in turns if str(t.user_id)!=IDS['OH']]
        with patch.object(service,'common_payload',AsyncMock(return_value=source)), \
             patch.object(service,'get_settings',AsyncMock(return_value=SimpleNamespace())), \
             patch.object(service,'turns_view',view),patch.object(service,'person_context',AsyncMock(return_value=BRIEF)):
            await service.finish_meeting(db,meeting,'interrupted:voice_disconnected')
            self.assertEqual(meeting.status,'ABORTED')
            await service.start_meeting(db,'11:00',at=service.slot_at(DAY,'11:05'))
            await service.begin_staff(db,meeting)
            self.assertEqual([t.status for t in turns],['WAITING','DONE','WAITING','SKIPPED','TIMEOUT','SKIPPED'])
            out=await service.next_turn(db,meeting,None,available_user_ids=[uuid.UUID(IDS['EF']),uuid.UUID(IDS['EH'])])
        self.assertEqual(out['current']['user_id'],IDS['EF'])
        self.assertEqual(out['upcoming']['user_id'],IDS['EH'])
        self.assertEqual(by_user[IDS['EF']].notes,'Raportimi i ruajtur')
        self.assertEqual(meeting.join_attempts,2)
        db.add.assert_not_called()

    async def test_pm_rejoin_restores_unfinished_people_once_and_keeps_completed_reviews(self):
        meeting=Mira1HMeeting(id=uuid.uuid4(),meeting_date=DAY,slot='11:50',status='STAFF_PHASE',join_attempts=1)
        queue=[{'id':'PM_'+IDS[key],'user_id':IDS[key],'name':NAMES[key],'person':NAMES[key],
                'status':status,'discussion':{'continuation':'Fakt i ruajtur'}}
               for key,status in (('DV','ACTIVE'),('EP','DONE'),('OH','WAITING'),('RA','TIMEOUT'),('EF','SKIPPED'))]
        queue[-1].update(name='Haxhere Spahiu',person='Haxhere Spahiu')
        event=Mira1HEvent(id=uuid.uuid4(),kind='PM_REVIEW',data={'queue':queue,'join_attempt':1})
        await runtime.finish_pm(SimpleNamespace(execute=AsyncMock(return_value=result(event))),meeting,service.now())
        meeting.join_attempts=2
        with patch.object(runtime,'pm_event',AsyncMock(return_value=event)):
            out=await runtime.next_pm_turn(SimpleNamespace(),meeting,expected_turn_id=None)
            self.assertEqual(out['current']['user_id'],IDS['DV'])
            self.assertEqual(out['current']['discussion']['continuation'],'Fakt i ruajtur')
            out=await runtime.next_pm_turn(SimpleNamespace(),meeting,expected_turn_id='PM_'+IDS['DV'])
        self.assertEqual(out['current']['user_id'],IDS['OH'])
        self.assertEqual([p['status'] for p in event.data['queue']],['DONE','DONE','ACTIVE','TIMEOUT','SKIPPED'])
        self.assertEqual(event.data['join_attempt'],2)


class PmInitializationTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_pending_checks_cannot_advance_the_newly_started_pm_person(self):
        entered=asyncio.Event();release=asyncio.Event()
        person={'id':'PM_'+IDS['EF'],'user_id':IDS['EF'],'name':'Elsa','person':'Elsa','discord':None}
        async def bridge(*_):
            entered.set();await release.wait()
            return {'initialized':True,'current':person,'turns':[person]}
        bridge_mock=AsyncMock(side_effect=bridge)
        host=controller.MiraHost(SimpleNamespace(bridge=bridge_mock))
        state={**session(),'current_turn':None,'pm_pending':True,'pm_reviewed':False}
        first=asyncio.create_task(host.watch_turn(state));await entered.wait()
        second=asyncio.create_task(host.watch_turn(state));await asyncio.sleep(0)
        release.set();await asyncio.gather(first,second)
        bridge_mock.assert_awaited_once()
        self.assertEqual(state['pm_current']['id'],person['id'])

    async def test_failed_initialization_is_retried_by_the_watcher_without_repeating_staff(self):
        person={'id':'PM_'+IDS['EF'],'user_id':IDS['EF'],'name':'Elsa','person':'Elsa','discord':None}
        bridge=AsyncMock(side_effect=[{'current':None,'pm_review':[person]},TimeoutError(),
                                     {'initialized':False,'current':None},
                                     {'initialized':True,'current':person,'turns':[person],'deferred':[]}])
        host=controller.MiraHost(SimpleNamespace(bridge=bridge))
        state={**session(),'slot':'11:50','pm_reviewed':False,'staff_started':True}
        out=await host._tool(state,{'name':'end_person_turn','arguments':'{"turn_id":"t1"}'})
        self.assertIn('error',out)
        self.assertTrue(state['pm_pending']);self.assertFalse(state['pm_reviewed'])
        self.assertFalse(state['ending'])
        await host.watch_turn(state)
        self.assertFalse(state['pm_pending']);self.assertTrue(state['pm_reviewed'])
        self.assertEqual(state['pm_current']['id'],person['id'])
        paths=[c.args[0] for c in bridge.await_args_list]
        self.assertEqual(sum(p.endswith('/turns/next') for p in paths),1)
        self.assertEqual(sum(p.endswith('/pm/next') for p in paths),2)

    async def test_retry_adopts_a_committed_pm_person_without_ending_them(self):
        person={'id':'PM_'+IDS['EF'],'user_id':IDS['EF'],'name':'Elsa','person':'Elsa','discord':None}
        bridge=AsyncMock(side_effect=[ValueError('Radha PM ka ndryshuar'),
                                     {'initialized':True,'current':person,'turns':[person]}])
        host=controller.MiraHost(SimpleNamespace(bridge=bridge))
        state={**session(),'current_turn':None,'pm_pending':True,'pm_reviewed':False}
        await host.watch_turn(state)
        self.assertEqual(bridge.await_args_list[0].args[1]['expected_turn_id'],None)
        self.assertEqual(state['pm_current']['id'],person['id'])
        self.assertFalse(state['ending']);self.assertFalse(state['pm_pending'])

    async def test_recovery_with_waiting_people_is_not_mistaken_for_finished_pm(self):
        bridge=AsyncMock(side_effect=[TimeoutError(),{'initialized':True,'current':None,
            'turns':[{'id':'PM_first','status':'WAITING'}],'deferred':[]}])
        host=controller.MiraHost(SimpleNamespace(bridge=bridge))
        state={**session(),'current_turn':None,'pm_pending':True,'pm_reviewed':False}
        with self.assertRaises(ValueError):await host.watch_turn(state)
        self.assertTrue(state['pm_pending']);self.assertFalse(state['pm_reviewed'])
        self.assertFalse(state['ending'])


class BlockedAndUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_running_staff_checks_continue_while_the_transcript_bridge_is_blocked(self):
        original_wait=asyncio.wait_for
        entered=asyncio.Event();release=asyncio.Event();watched=[]
        async def fast_wait(coro,timeout):
            if timeout==5:
                coro.close();await asyncio.sleep(0);return
            return await original_wait(coro,timeout)
        async def bridge(*_):entered.set();await release.wait();return {'ok':True}
        host=controller.MiraHost(SimpleNamespace(bridge=bridge))
        async def connect(state,*args,**kwargs):
            state.update(meeting='synthetic',staff_started=True,lines=[{'id':'1','text':'Fakt'}])
            return {'starts_at':controller.datetime.now(controller.tz()).isoformat()}
        async def watch(state):
            watched.append(True)
            if len(watched)==2:
                await entered.wait()
                self.assertFalse(state['timed_upload'].done())
                self.assertFalse(release.is_set())
                state['closed'].set()
        with patch.object(host,'connect',connect),patch.object(host,'wait_until',AsyncMock()), \
             patch.object(host,'watch_turn',watch),patch.object(host,'say',AsyncMock()), \
             patch.object(host,'finish',AsyncMock()),patch.object(controller.asyncio,'wait_for',fast_wait):
            await original_wait(host.run('11:00',SimpleNamespace(),SimpleNamespace()),1)
            release.set();await host.session['timed_upload']
        self.assertEqual(len(watched),2)

    def test_blocked_only_staff_join_the_1600_queue_after_slot_staff_with_all_exclusions(self):
        source=payload([item('EP','16:00','AKTUAL',rank=0)],absent=('DV',))
        source['items']['blocked']=[item(key,None,'BLLOK',rank=i) for i,key in enumerate(('OH','EP','GA','RA','DV'))]
        source['items']['blocked'].append(item('EH',None,'BLLOK DONE',rank=9,status='DONE',completed_at=service.now().isoformat()))
        next(u for u in source['users'] if u['id']==IDS['RA'])['full_name']='Haxhere Spahiu'
        data=service.SlotData(source,DAY)
        self.assertEqual(data.participants('16:00'),[IDS['EP'],IDS['OH']])
        self.assertEqual(data.participants('14:20'),[])
        brief=service.person_brief(data,'16:00',IDS['OH'])
        out=controller.turn_brief({'id':'t','name':'Elsa','initials':'EF','brief':brief})
        self.assertEqual(out['plan_discutimi'][0]['grupi'],'BLLOK')
        self.assertFalse(out['te_gjitha_kryer'])
        self.assertIn('Detyrat e bllokuara',service.brief_message(brief,service.DEFAULT_PROTOCOL))

    async def test_blocked_only_turn_starts_with_the_blocked_task(self):
        brief=service.person_brief(service.SlotData({**payload([]),'items':{'blocked':[item('EF',None,'BLLOK',rank=0)]}},DAY),
                                   '16:00',IDS['EF'])
        current={'id':'t','user_id':IDS['EF'],'name':'Elsa','initials':'EF','discord':None,'brief':brief}
        host=controller.MiraHost(SimpleNamespace(bridge=AsyncMock(return_value={'current':current})))
        out=await host.advance({**session(),'slot':'16:00','current_turn':None},None,announce=False)
        self.assertIn('parë BLLOK',out['udhezim'])

    async def test_upload_is_single_and_cancellation_keeps_unsent_lines_metrics_and_receipts(self):
        started=asyncio.Event()
        async def bridge(*_):started.set();await asyncio.Event().wait()
        host=controller.MiraHost(SimpleNamespace(bridge=bridge))
        state={**session(),'meeting':str(uuid.uuid4()),'lines':[{'id':'1','text':'Fakti'}],
               'metrics':[{'id':'metric'}],'notes_acks':{'receipt'}}
        with tempfile.TemporaryDirectory() as directory,patch.object(controller,'RECOVERY_DIR',Path(directory)), \
             patch.object(controller,'WRITE_TIMEOUT_SECONDS',0.03):
            host.schedule_upload(state);first=state['timed_upload']
            host.schedule_upload(state);self.assertIs(state['timed_upload'],first)
            await started.wait()
            state['lines'].append({'id':'2','text':'Fakti i ri'})
            await first
            self.assertEqual([line['id'] for line in state['lines']],['1','2'])
            self.assertEqual(state['notes_acks'],{'receipt'})
            self.assertEqual(len(state['metrics']),1)

    async def test_transcript_cancellation_after_a_successful_batch_restores_only_the_tail(self):
        host=controller.MiraHost(SimpleNamespace())
        state={**session(),'lines':[{'id':str(i),'text':'Fakt'} for i in range(205)]}
        calls=[]
        async def bridge(path,body):
            calls.append(body)
            if len(calls)==2:raise asyncio.CancelledError()
            return {'ok':True}
        host.bot.bridge=bridge
        with self.assertRaises(asyncio.CancelledError):await host.flush_lines(state)
        self.assertEqual([line['id'] for line in state['lines']],[str(i) for i in range(200,205)])
        self.assertEqual(state['uploading_lines'],[])
