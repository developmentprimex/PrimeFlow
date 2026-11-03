"""Parity with the actual 1H Report builder/blue-strike filter, without network or model calls."""
import uuid
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from app.models.ga_note import GaNote

from tests.test_mira_host_service import DAY, IDS, NAMES, payload, item, report_rows
from tests.test_mira_host_bot import session
from app.models.mira_host import Mira1HMeeting
from app.services import mira_host as host
from app.services.primeflow_report_delivery import generate_fresh, strike_interval_start, strike_interval_end
from app.services.task_strike_events import point_key, render_text_for_interval, struck_points_for_interval
import mira_host as controller


def event(tid, text, at, *, field='DESCRIPTION', action='STRUCK', actor='EF'):
    return SimpleNamespace(id=uuid.uuid4(),task_id=uuid.UUID(tid),point_text=text,
        point_key=point_key(text,field_name=field),field_name=field,occurred_at=at,action=action,
        actor_user_id=uuid.UUID(IDS[actor]) if actor else None)


class ReportParity(unittest.IsolatedAsyncioTestCase):
    async def test_haxhere_tasks_never_enter_done_strike_speech_or_acknowledgements(self):
        at=strike_interval_start(DAY,'11:00')+timedelta(minutes=20)
        hidden=item('EF','11:00','FINANCA PRIVATE',rank=0,status='DONE',completed_at=at.isoformat(),
                    description='[[done]]1. Finance[[/done]]',assignees=['Haxhere Spahiu'])
        visible=item('RA','11:00','RAPORTI STAFIT',rank=1,status='DONE',completed_at=at.isoformat(),
                     description='[[done]]1. Stafi[[/done]]')
        source=payload([hidden,visible])
        source['users'][0]['full_name']='Haxhere Spahiu'
        source['users'][0]['department_id']=source['users'][1]['department_id']='finance'
        # The DB snapshot still contains both tasks; the host's scope selects only the visible one.
        rows=report_rows(SimpleNamespace(payload=source),[event(hidden['task_id'],'1. Finance',at),event(visible['task_id'],'1. Stafi',at,actor='RA')])
        db=SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda:rows)),add=Mock())
        meeting=Mira1HMeeting(id=uuid.uuid4(),meeting_date=DAY,slot='11:00',status='GA_PHASE')
        data=host.SlotData(source,DAY)
        facts=await host.new_progress(db,meeting,data)
        self.assertEqual([r['task_id'] for r in facts['done']],[visible['task_id']])
        self.assertEqual([r['task_id'] for r in facts['strikes']],[visible['task_id']])
        self.assertEqual(facts['strike_count'],1)
        with patch.object(host,'common_payload',AsyncMock(return_value=source)):
            out=await host.run_tool(db,meeting,'list_new_done_and_strikes',{})
        self.assertNotIn('Haxhere',out['read_aloud'])
        self.assertNotIn('FINANCA PRIVATE',out['read_aloud'])
        self.assertIn('RAPORTI STAFIT',out['read_aloud'])
        for call in db.add.call_args_list:
            self.assertEqual({m['task_id'] for m in call.args[0].data['mentions']},{visible['task_id']})

    def test_reading_a_staff_note_does_not_reclassify_it_as_a_mira_authored_note(self):
        query=select(GaNote.id).where(GaNote.from_mira).compile(dialect=postgresql.dialect())
        values=[value for value in query.params.values() if isinstance(value,(list,tuple))]
        self.assertIn(('PX_NOTE','SUMMARY_NOTE'),[tuple(value) for value in values])
        self.assertNotIn('NOTE_MENTION',str(query.params))
    async def compare(self, source, slot, events):
        for bucket in source['items'].values():
            for row in bucket:
                if row.get('task_id'):
                    row['person']=', '.join(row.get('assignees') or [])
        data=host.SlotData(source,DAY)
        rows=report_rows(data,[e for e in events if e.occurred_at<=strike_interval_end(DAY,slot)])
        db=SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda:rows)))
        class Session:
            async def __aenter__(self):return db
            async def __aexit__(self,*_):pass
        with patch('app.services.primeflow_report_delivery.SessionLocal',return_value=Session()), \
             patch('app.services.primeflow_report_delivery.load_1h_reminder_questions',AsyncMock(return_value=[])), \
             patch('app.services.primeflow_report_delivery.load_undiscussed_notes',AsyncMock(return_value=[])):
            report=await generate_fresh(DAY,slot,{'to':[]},data=source)
        meeting=Mira1HMeeting(id=uuid.uuid4(),meeting_date=DAY,slot=slot,status='GA_PHASE')
        facts=await host.new_progress(db,meeting,data)
        self.assertEqual(facts['strike_count'],report.strike_total)
        expected_done={task.task_id for section in report.sections for person in section.employees
                       for task in person.tasks if task.status in ('DONE','COMPLETED')}
        self.assertEqual({line['task_id'] for line in facts['done']},expected_done)
        expected_strikes={task.task_id for section in report.sections for person in section.employees
                          for task in person.tasks if task.strike_count}
        self.assertEqual({line['task_id'] for line in facts['strikes']},expected_strikes)
        return facts,report,db,meeting

    async def test_all_five_slots_match_the_reports_completion_and_strike_boundaries(self):
        for slot in host.SLOTS:
            with self.subTest(slot=slot):
                start,end=strike_interval_start(DAY,slot),strike_interval_end(DAY,slot)
                current=item('EF',slot,'OFERTA',rank=0,description='[[done]]1. Në fillim[[/done]]\n[[done]]2. Brenda[[/done]]\n[[done]]3. Në fund[[/done]]')
                done=item('RA',slot,'RAPORTI',rank=1,status='DONE',completed_at=end.isoformat())
                early=item('EF',slot,'E HERSHME',rank=2,status='DONE',completed_at=start.isoformat())
                future=item('EF',slot,'E VONSHME',rank=3,status='DONE',completed_at=(end+timedelta(seconds=1)).isoformat())
                events=[event(current['task_id'],'1. Në fillim',start),event(current['task_id'],'2. Brenda',start+timedelta(minutes=1)),
                        event(current['task_id'],'3. Në fund',end)]
                facts,*_=await self.compare(payload([current,done,early,future]),slot,events)
                self.assertEqual(facts['strike_count'],2)
                self.assertEqual(facts['done_count'],1)
                self.assertEqual(facts['interval_start'],start.isoformat())
                self.assertEqual(facts['interval_end'],end.isoformat())

    async def test_reopened_deleted_green_and_grey_points_do_not_become_new_strikes(self):
        start,end=strike_interval_start(DAY,'11:00'),strike_interval_end(DAY,'11:00')
        task=item('EF','11:00','OFERTA',rank=0,description='[[done]]1. E hershme[[/done]]\n2. Rihapur\n[[done]]3. Brenda[[/done]]\n[[done]]4. Dje[[/done]]')
        tid=task['task_id']
        events=[event(tid,'1. E hershme',start-timedelta(minutes=1)),event(tid,'2. Rihapur',start+timedelta(minutes=1)),
                event(tid,'2. Rihapur',start+timedelta(minutes=2),action='UNSTRUCK'),event(tid,'3. Brenda',end),
                event(tid,'4. Dje',start-timedelta(days=1)),event(tid,'5. Fshirë',end)]
        facts,*_=await self.compare(payload([task]),'11:00',events)
        self.assertEqual([p['text'] for p in facts['strikes'][0]['points']],['3. Brenda'])

    async def test_legacy_visible_timestamp_counts_without_an_event_or_invented_actor(self):
        start,end=strike_interval_start(DAY,'11:00'),strike_interval_end(DAY,'11:00')
        task=item('EF','11:00','OFERTA',rank=0,description=f'[[done]]1. Legacy 10:30 {DAY:%d.%m}[[/done]]\n[[done]]2. Pa kohë[[/done]]')
        facts,*_=await self.compare(payload([task]),'11:00',[])
        self.assertEqual(facts['strike_count'],1)
        point=facts['strikes'][0]['points'][0]
        self.assertEqual(point['at'],'10:30');self.assertIsNone(point['by'])

    async def test_title_and_description_strikes_preserve_time_and_actual_actor(self):
        at=strike_interval_start(DAY,'11:00')+timedelta(minutes=20)
        task=item('EF','11:00','OFERTA\n[[done]]1. Titulli[[/done]]',rank=0,description='[[done]]1. Përshkrimi[[/done]]')
        events=[event(task['task_id'],'1. Titulli',at,field='TITLE',actor='RA'),event(task['task_id'],'1. Përshkrimi',at,actor='EF')]
        facts,_,db,meeting=await self.compare(payload([task]),'11:00',events)
        self.assertEqual(facts['strike_count'],2)
        points=facts['strikes'][0]['points']
        self.assertEqual({p['field'] for p in points},{'TITLE','DESCRIPTION'})
        self.assertEqual({p['by'] for p in points},{NAMES['EF'],NAMES['RA']})
        self.assertTrue(all(p['at']=='10:20' for p in points))
        db.add=Mock()
        with patch.object(host,'common_payload',AsyncMock(return_value=payload([task]))):
            out=await host.run_tool(db,meeting,'list_new_done_and_strikes',{})
        self.assertIn('2 strike',out['read_aloud']);self.assertNotIn('10:20',out['read_aloud'])
        self.assertIn('Rinesa',out['read_aloud'])

    async def test_done_speech_omits_recorded_and_missing_times(self):
        at=strike_interval_start(DAY,'11:00')+timedelta(minutes=20)
        for completed_at in (at.isoformat(),None):
            with self.subTest(completed_at=completed_at):
                task=item('EF','11:00','OFERTA',rank=0,status='DONE',completed_at=completed_at)
                facts,_,db,meeting=await self.compare(payload([task]),'11:00',[])
                self.assertEqual(facts['done_count'],1)
                db.add=Mock()
                with patch.object(host,'common_payload',AsyncMock(return_value=payload([task]))):
                    out=await host.run_tool(db,meeting,'list_new_done_and_strikes',{})
                self.assertIn('e kryer OFERTA',out['read_aloud'])
                self.assertIn(NAMES['EF'],out['read_aloud'])
                self.assertNotRegex(out['read_aloud'],r'\d{1,2}:\d{2}')
                self.assertNotIn('koha',out['read_aloud'])

    async def test_shared_task_counts_once_and_keeps_both_owners(self):
        at=strike_interval_start(DAY,'11:00')+timedelta(minutes=1)
        first=item('EF','11:00','OFERTA',rank=0,description='[[done]]1. Pika[[/done]]')
        second=item('RA','11:00','OFERTA',rank=1,task_id=first['task_id'],description=first['description'])
        facts,*_=await self.compare(payload([first,second]),'11:00',[event(first['task_id'],'1. Pika',at)])
        self.assertEqual(facts['strike_count'],1)
        self.assertEqual(facts['strikes'][0]['owners'],['EF','RA'])

    async def test_wrong_report_section_is_not_announced_even_if_it_has_a_strike(self):
        at=strike_interval_start(DAY,'11:00')+timedelta(minutes=10)
        task=item('EF','16:00','DETYRA E PASDITES',rank=0,description='[[done]]1. Pika[[/done]]')
        facts,*_=await self.compare(payload([task]),'11:00',[event(task['task_id'],'1. Pika',at)])
        self.assertEqual(facts['strike_count'],0)

    async def test_legacy_done_remains_visible_but_does_not_invent_a_completion_time(self):
        task=item('EF','11:00','LEGACY DONE',rank=0,status='DONE')
        facts,*_=await self.compare(payload([task]),'11:00',[])
        self.assertEqual(facts['done_count'],1)
        self.assertTrue(facts['done'][0]['time_unknown'])
        self.assertIsNone(facts['done'][0]['completed_at'])

    async def test_early_opening_reads_progress_immediately_before_the_staff_start(self):
        bot=SimpleNamespace(bridge=AsyncMock(return_value={'announcements':[{'token':'p','read_aloud':'Elsa: e kryer OFERTA.'}],
                                                          'read_aloud':'Elsa: e kryer OFERTA.'}))
        presenter=controller.MiraHost(bot)
        state={**session(),'ga_checks':{'list_new_px_notes':'DONE'},'ga_results':{},'starts_at':host.now()+timedelta(minutes=1)}
        out=await presenter._tool(state,{'name':'list_new_done_and_strikes','arguments':'{}'})
        self.assertTrue(out['read_aloud'])
        self.assertEqual(state['ga_checks']['list_new_done_and_strikes'],'PENDING')
        self.assertEqual(state['pending_progress'],{'p'})
        bot.bridge.assert_awaited_once()
        self.assertTrue(bot.bridge.await_args.args[0].endswith('/tools/list_new_done_and_strikes'))

    async def test_progress_cannot_skip_notes_at_the_start(self):
        bot=SimpleNamespace(bridge=AsyncMock())
        presenter=controller.MiraHost(bot)
        state={**session(),'ga_checks':{},'ga_results':{}}
        out=await presenter._tool(state,{'name':'list_new_done_and_strikes','arguments':'{}'})
        self.assertEqual(out['next_step'],'list_new_px_notes')
        bot.bridge.assert_not_awaited()

    def test_shared_blue_extraction_equals_rendered_filter_count(self):
        start,end=strike_interval_start(DAY,'10:00'),strike_interval_end(DAY,'10:00')
        text='[[done]]1. Pika 09:20 '+DAY.strftime('%d.%m')+'[[/done]]\n[[done]]2. Pa datë[[/done]]'
        plain,marked=render_text_for_interval(text,[],interval_start=start,interval_end=end)
        points=struck_points_for_interval(text,[],interval_start=start,interval_end=end)
        self.assertEqual(len(points),marked.count('[[done:blue]]'))
        self.assertEqual(points[0]['text'],'1. Pika')
