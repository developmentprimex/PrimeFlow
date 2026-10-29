import os
import uuid
import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET', 'mira-host-tests-not-a-production-secret')

from fastapi import HTTPException
from app.config import settings
from app.models.mira_host import Mira1HMeeting, MiraHostSettings
from app.services import mira_host as host

DAY = date(2026, 10, 21)  # a Wednesday
TZ = ZoneInfo(settings.APP_TIMEZONE)
IDS = {name: str(uuid.uuid4()) for name in ('EF', 'RA', 'EH', 'GA', 'DV', 'EP', 'OH')}
NAMES = {'EF': 'Elsa Ferati', 'RA': 'Rinesa Ahmeti', 'EH': 'Endrit Hoxha', 'GA': 'Gane Arifaj',
         'DV': 'Diellza Veliu', 'EP': 'Elza Preniqi', 'OH': 'Olsa Hajdari'}


def item(owner, slot, title, *, rank, status='IN_PROGRESS', task_id=None, **extra):
    return {'task_id': task_id or str(uuid.uuid4()), 'title': f'{owner}: {title}', 'assignees': [NAMES[owner]],
            'user_id': IDS[owner], 'date': DAY.isoformat(), 'one_h_report_slot': slot, 'status': status,
            'finish_period': 'AM', 'weekly_planner_sort': (rank,), **extra}


def payload(items, absent=()):
    return {'users': [{'id': IDS[k], 'full_name': v, 'is_active': True, 'department_id': str(uuid.uuid4())} for k, v in NAMES.items()],
            'items': {'oneH': items, 'absent': [{'userId': IDS[k], 'date': DAY.isoformat(), 'fullDay': True} for k in absent]}}


class SlotDataTests(unittest.TestCase):
    def test_current_task_is_not_asked_again_as_an_earlier_task(self):
        shared = str(uuid.uuid4())
        data = host.SlotData(payload([
            item('EF', '10:00', 'OFERTA', rank=0, task_id=shared),
            item('EF', '10:00', 'RAPORTI', rank=1),
            item('EF', '11:00', 'OFERTA', rank=0, task_id=shared),
        ]), DAY)
        brief = host.person_brief(data, '11:00', IDS['EF'])
        self.assertEqual([t['spoken'] for t in brief['current']], ['OFERTA'])
        self.assertEqual([t['spoken'] for t in brief['previous_open']], ['RAPORTI'])

    def test_participants_follow_common_view_order_without_ga_and_absent_people(self):
        data = host.SlotData(payload([
            item('RA', '10:00', 'ASISTENTI PER TAK', rank=1),
            item('EF', '10:00', 'ASISTENTI PER TAK', rank=0),
            item('GA', '10:00', 'CH PRGD', rank=2),
            item('EH', '10:00', 'CODEX ACC', rank=3),
            item('EF', '10:00', 'TJETER', rank=4),
        ], absent=('EH',)), DAY)
        self.assertEqual(data.participants('10:00'), [IDS['EF'], IDS['RA']])

    def test_brief_lists_current_tasks_and_open_tasks_of_the_previous_slot(self):
        data = host.SlotData(payload([
            item('EF', '10:00', 'E PAPERFUNDUAR', rank=0, status='TODO'),
            item('EF', '10:00', 'E KRYER', rank=1, status='DONE', completed_at=datetime(2026, 10, 21, 9, tzinfo=TZ).isoformat()),
            item('EF', '11:00', '6 PDF PRZ', rank=0, one_h_marker='M2_M3', is_deadline_important=True),
        ]), DAY)
        brief = host.person_brief(data, '11:00', IDS['EF'])
        self.assertEqual([t['title'] for t in brief['current']], ['EF: 6 PDF PRZ'])
        self.assertEqual(brief['current'][0]['symbol'], 'M2/3')
        self.assertTrue(brief['current'][0]['deadline'])
        self.assertEqual([t['title'] for t in brief['previous_open']], ['EF: E PAPERFUNDUAR'])
        self.assertEqual(brief['current'][0]['status_label'], 'në proces')
        text = host.brief_message(brief, host.DEFAULT_PROTOCOL)
        self.assertIn('Share screen side by side', text)
        self.assertIn('Nga sloti paraprak 10:00', text)

    def test_at_1150_open_tasks_of_every_earlier_slot_are_asked_and_colours_are_given(self):
        data = host.SlotData(payload([
            item('EF', '10:00', 'NGA DHJETA', rank=0, status='TODO'),
            item('EF', '11:00', 'NGA NJEMBEDHJETA', rank=0, status='IN_PROGRESS'),
            item('EF', '11:50', 'E KRYER', rank=0, status='DONE', completed_at=datetime(2026, 10, 21, 11, 20, tzinfo=TZ).isoformat()),
        ]), DAY)
        brief = host.person_brief(data, '11:50', IDS['EF'])
        self.assertEqual([t['color'] for t in brief['previous_open']], ['rozë', 'e verdhë'])
        self.assertEqual(brief['previous_slot'], '10:00, 11:00')
        self.assertTrue(brief['all_done'])
        # Other slots ask only the slot right before them.
        self.assertEqual(host.person_brief(data, '11:00', IDS['EF'])['previous_slot'], '10:00')

    def test_blocked_tasks_are_asked_only_at_1600(self):
        source = payload([item('EF', '16:00', 'MBYLLJA', rank=0)])
        blocked = item('EF', None, 'BLLOK RAPORTI', rank=0)
        blocked.pop('one_h_report_slot')
        source['items']['blocked'] = [blocked]
        data = host.SlotData(source, DAY)
        self.assertEqual([t['spoken'] for t in host.person_brief(data, '16:00', IDS['EF'])['blocked']], ['BLLOK RAPORTI'])
        self.assertEqual(host.person_brief(data, '14:20', IDS['EF'])['blocked'], [])

    def test_ga_tasks_pm_review_and_progress_follow_the_common_view_order(self):
        data = host.SlotData(payload([
            item('RA', '10:00', 'PER GA', rank=0, one_h_marker='FLAG'),
            item('EF', '11:00', 'PM PUNE', rank=0, finish_period='PM'),
            item('EF', '11:00', 'PER GA EDHE', rank=1, one_h_marker='FLAG'),
        ]), DAY)
        self.assertEqual([p['person'] for p in data.ga_flagged()], ['RA', 'EF'])
        self.assertEqual(data.pm_open()[0]['initials'], 'EF')
        self.assertEqual(data.pm_open()[0]['detyrat_pm'], ['PM PUNE (e verdhë)'])
        progress = {'done': [{'spoken': 'A', 'owners': ['EF']}],
                    'strikes': [{'spoken': 'B', 'owners': ['RA'], 'points': [{'text': 'p1'}]}]}
        self.assertEqual([g['person'] for g in host.by_person(data, progress)], ['RA', 'EF'])

    def test_ga_fallback_is_used_when_the_primary_is_absent_today(self):
        row = MiraHostSettings(ga_participants=host.DEFAULT_GA_PARTICIPANTS)
        present = host.ga_people(host.SlotData(payload([]), DAY), row)
        self.assertEqual([p['user_id'] for p in present], [IDS['DV'], IDS['GA'], IDS['EP']])
        self.assertEqual(present[2]['fallback_user_id'], IDS['OH'])
        absent = host.ga_people(host.SlotData(payload([], absent=('EP',)), DAY), row)
        self.assertEqual(absent[2], {'user_id': IDS['OH'], 'fallback_user_id': None})


class EnableTests(unittest.TestCase):
    def test_enable_until_requires_a_later_time(self):
        at = datetime(2026, 10, 21, 9, 30, tzinfo=TZ)
        self.assertEqual(host.enable_until(at, '12:00').hour, 12)
        self.assertEqual(host.enable_until(at, None).strftime('%H:%M'), '16:45')
        with self.assertRaises(HTTPException):
            host.enable_until(at, '09:00')


class TickTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.row = MiraHostSettings(id=1, enabled_until=datetime(2026, 10, 21, 16, 45, tzinfo=TZ),
                                    ga_participants=host.DEFAULT_GA_PARTICIPANTS, protocol_text=host.DEFAULT_PROTOCOL)
        self.db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None),
                                                                     scalars=Mock(return_value=[]))),
                                  commit=AsyncMock())
        self.data = payload([item('EF', '10:00', 'A', rank=0), item('RA', '11:00', 'B', rank=0)])
        targets = {uid: {'discord_user_id': str(n), 'guild_id': '1', 'channel_id': str(100 + n)} for n, uid in enumerate(IDS.values())}
        self.patches = [patch.object(host, 'get_settings', AsyncMock(return_value=self.row)),
                        patch.object(settings, 'MIRA_HOST_OPENAI_API_KEY', 'host-test'),
                        patch.object(host, 'common_payload', AsyncMock(return_value=self.data)),
                        patch.object(host, 'claim_event', AsyncMock(return_value=True)),
                        patch.object(host, 'discord_targets', AsyncMock(side_effect=lambda db, ids: {i: targets[i] for i in ids}))]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    async def kinds(self, hour, minute):
        result = await host.tick(self.db, datetime(2026, 10, 21, hour, minute, 10, tzinfo=TZ))
        return [(j['kind'], j['slot']) for j in result['jobs']]

    async def test_no_pre_brief_for_10_but_for_11(self):
        self.assertNotIn(('brief', '10:00'), await self.kinds(9, 55))
        self.assertIn(('brief', '11:00'), await self.kinds(10, 55))

    async def test_mira_connects_six_minutes_early_and_talks_two_minutes_before(self):
        self.assertEqual(await self.kinds(9, 53), [])
        result = await host.tick(self.db, datetime(2026, 10, 21, 9, 54, 10, tzinfo=TZ))
        join = next(j for j in result['jobs'] if j['kind'] == 'join')
        self.assertEqual(datetime.fromisoformat(join['talk_at']).strftime('%H:%M'), '09:58')

    async def test_ga_is_called_two_minutes_before_and_mira_joins(self):
        kinds = await self.kinds(9, 58)
        self.assertEqual(kinds.count(('ga_call', '10:00')), 3)
        self.assertIn(('join', '10:00'), kinds)

    async def test_nothing_happens_until_mira_is_started(self):
        self.row.enabled_until = None
        self.assertEqual(await self.kinds(9, 58), [])


class RealtimeSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_fixed_language_because_openai_rejects_sq(self):
        sent = {}

        class Client:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            async def post(self, url, headers, json):
                sent.update(json)
                return SimpleNamespace(is_error=False, json=lambda: {'value': 'ek_test'})
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:50')
        with patch.object(settings, 'MIRA_HOST_OPENAI_API_KEY', 'sk-test'), patch('httpx.AsyncClient', Client),              patch.object(host, 'get_settings', AsyncMock(return_value=MiraHostSettings(knowledge_char_budget=1000))),              patch.object(host, 'instructions', AsyncMock(return_value='Test')):
            result = await host.realtime_session(SimpleNamespace(), meeting)
        self.assertEqual(result['client_secret'], 'ek_test')
        self.assertNotIn('language', sent['session']['audio']['input']['transcription'])
        # Balanced endpointing avoids the long low-eagerness pause; interruptions stay with the worker.
        self.assertEqual(sent['session']['audio']['input']['turn_detection'],
                         {'type': 'semantic_vad', 'eagerness': 'medium', 'create_response': True, 'interrupt_response': False})
        self.assertEqual(sent['session']['reasoning'], {'effort': settings.MIRA_HOST_REASONING_EFFORT})
        self.assertIn('wait_for_user', [tool['name'] for tool in sent['session']['tools']])


class ProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_only_strike_is_staff_evidence_without_becoming_a_ga_announcement(self):
        task_id = str(uuid.uuid4())
        source = payload([])
        source['items']['blocked'] = [item('EF', None, 'BLLOK RAPORTI', rank=0, task_id=task_id)]
        data = host.SlotData(source, DAY)
        strike = SimpleNamespace(task_id=uuid.UUID(task_id), point_key='p1', action='STRUCK',
                                 point_text='Tabela', occurred_at=datetime(2026, 10, 21, 15, 30, tzinfo=TZ))
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock(
            scalars=Mock(return_value=Mock(all=Mock(return_value=[strike]))))))
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='16:00')
        self.assertEqual(await host.new_progress(db, meeting, data), {'done': [], 'strikes': []})
        evidence = await host.new_progress(db, meeting, data, [IDS['EF']], for_brief=True)
        self.assertEqual([(t['task_id'], t['points'][0]['text']) for t in evidence['strikes']],
                         [(task_id, 'Tabela')])

    async def test_staff_evidence_keeps_announced_strikes_separate_for_same_named_tasks(self):
        first, second = str(uuid.uuid4()), str(uuid.uuid4())
        data = host.SlotData(payload([
            item('EF', '11:00', 'OFERTA', rank=0, task_id=first),
            item('EF', '11:00', 'OFERTA', rank=1, task_id=second),
        ]), DAY)
        events = [SimpleNamespace(task_id=uuid.UUID(tid), point_key='p1', action='STRUCK',
                                  point_text=text, occurred_at=datetime(2026, 10, 21, 10, 30, tzinfo=TZ))
                  for tid, text in ((first, 'Klienti A'), (second, 'Klienti B'))]
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock(
            scalars=Mock(return_value=Mock(all=Mock(return_value=events))))))
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00')
        seen = {(first, 'STRIKE', 'p1'), (second, 'STRIKE', 'p1')}
        with patch.object(host, 'mentioned', AsyncMock(return_value=seen)):
            announcements = await host.new_progress(db, meeting, data)
            evidence = await host.new_progress(db, meeting, data, for_brief=True)
        self.assertEqual(announcements['strikes'], [])
        self.assertEqual([(t['task_id'], t['points'][0]['text']) for t in evidence['strikes']],
                         [(first, 'Klienti A'), (second, 'Klienti B')])

    async def test_person_context_keeps_recorded_percentage_and_window_evidence(self):
        task_id, untouched = str(uuid.uuid4()), str(uuid.uuid4())
        data = host.SlotData(payload([
            item('EF', '11:00', 'OFERTA', rank=0, task_id=task_id),
            item('EF', '11:00', 'RAPORTI', rank=1, task_id=untouched, status='TODO'),
        ]), DAY)
        since = datetime(2026, 10, 21, 10, tzinfo=TZ)
        strike = SimpleNamespace(task_id=uuid.UUID(task_id), point_key='p1', action='STRUCK',
                                 point_text='Drafti', occurred_at=datetime(2026, 10, 21, 10, 30, tzinfo=TZ))
        db = SimpleNamespace(execute=AsyncMock(side_effect=[
            Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[strike])))),
            Mock(all=Mock(return_value=[(uuid.UUID(task_id), 40), (uuid.UUID(untouched), 0)])),
        ]))
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00')
        with patch.object(host, 'progress_since', AsyncMock(return_value=since)):
            brief = await host.person_context(db, meeting, data, IDS['EF'])
        self.assertEqual(brief['progress_since'], since.isoformat())
        self.assertEqual(brief['progress_percentages'], {task_id: 40, untouched: 0})
        self.assertEqual([s['task_id'] for s in brief['new_progress']['strikes']], [task_id])

    async def test_done_reported_in_an_earlier_1h_is_not_repeated(self):
        done_id, new_id = str(uuid.uuid4()), str(uuid.uuid4())
        data = host.SlotData(payload([
            item('EF', '10:00', 'OLD', rank=0, status='DONE', task_id=done_id, completed_at=datetime(2026, 10, 21, 9, tzinfo=TZ).isoformat()),
            item('RA', '10:00', 'NEW', rank=1, status='DONE', task_id=new_id, completed_at=datetime(2026, 10, 21, 10, 30, tzinfo=TZ).isoformat()),
        ]), DAY)
        strike = SimpleNamespace(task_id=uuid.UUID(new_id), point_key='k1', action='STRUCK',
                                 point_text='Me u nxerr transkripta 10:54 20.10', occurred_at=datetime(2026, 10, 21, 9, tzinfo=timezone.utc))
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[strike]))))))
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00')
        with patch.object(host, 'mentioned', AsyncMock(return_value={(done_id, 'DONE', '')})):
            progress = await host.new_progress(db, meeting, data)
        self.assertEqual([d['title'] for d in progress['done']], ['RA: NEW'])
        self.assertEqual(progress['strikes'][0]['points'][0]['text'], 'Me u nxerr transkripta')

    async def test_only_work_done_in_the_1h_report_window_is_new(self):
        data = host.SlotData(payload([
            item('EF', '11:00', 'BEFORE 10', rank=0, status='DONE', completed_at=datetime(2026, 10, 21, 9, 40, tzinfo=TZ).isoformat()),
            item('RA', '16:00', 'AT 10:30', rank=1, status='DONE', completed_at=datetime(2026, 10, 21, 10, 30, tzinfo=TZ).isoformat()),
        ]), DAY)
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[]))))))
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00')
        with patch.object(host, 'mentioned', AsyncMock(return_value=set())):
            progress = await host.new_progress(db, meeting, data, since=datetime(2026, 10, 21, 10, tzinfo=TZ))
        # Like the 11:00 1H report: 10:00-11:00 only, from any slot.
        self.assertEqual([d['title'] for d in progress['done']], ['RA: AT 10:30'])

    async def test_the_window_follows_the_1h_report_and_closes_the_gap_after_miras_last_reading(self):
        def db(read_at):
            return SimpleNamespace(execute=AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=read_at))))
        at = lambda h, m: datetime(2026, 10, 21, h, m, tzinfo=TZ)
        first = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='10:00')
        self.assertEqual(await host.progress_since(db(None), first), at(8, 0))
        later = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:50')
        self.assertEqual(await host.progress_since(db(None), later), at(11, 0))
        # Mira read the 11:00 progress at 10:58; what was done 10:58-11:00 is still new at 11:50.
        self.assertEqual(await host.progress_since(db(at(10, 58)), later), at(10, 58))


class CreateTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_task_from_a_px_note_is_always_1h_in_the_current_slot(self):
        note = SimpleNamespace(id=uuid.uuid4(), is_converted_to_task=False, content='Thirr klientin per oferten\nDetaje', department_id=None)
        db = SimpleNamespace(get=AsyncMock(return_value=note), commit=AsyncMock(), add=Mock())
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:50')
        data = host.SlotData(payload([]), DAY)
        args = host.CreateTask(note_id=str(note.id), assignees=['EF'], due_date='2026-10-23', finish_period='pm',
                               deadline=True, symbol='M2/3')
        api = AsyncMock(return_value={'id': str(uuid.uuid4())})
        with patch('app.services.discord_task_tools.user_api', api), \
             patch.object(host, 'acting_user', AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))):
            result = await host.create_task(db, meeting, data, args)
        self.assertTrue(result['success'])
        body = api.await_args.kwargs['body']
        self.assertEqual((body['is_1h_report'], body['one_h_report_slot'], body['finish_period'], body['one_h_marker']),
                         (True, '11:50', 'PM', 'M2_M3'))
        self.assertEqual(body['title'], 'Thirr klientin per oferten')
        self.assertEqual(body['assignees'], [IDS['EF']])
        self.assertTrue(body['is_deadline_important'])

    async def test_a_dictated_px_note_is_saved_through_the_api_and_linked_to_mira(self):
        db = SimpleNamespace(commit=AsyncMock(), add=Mock())
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:50')
        note_id = str(uuid.uuid4())
        api = AsyncMock(return_value={'id': note_id})
        actor = SimpleNamespace(id=uuid.uuid4(), role=host.UserRole.ADMIN, department_id=None)
        with patch('app.services.discord_task_tools.user_api', api), \
             patch.object(host, 'acting_user', AsyncMock(return_value=actor)):
            result = await host.save_px_note(db, meeting, host.PxNote(text=' Oferta per klientin X ', symbol='?'))
        self.assertTrue(result['success'])
        self.assertEqual(api.await_args.args[1:], ('POST', '/api/ga-notes'))
        self.assertEqual(api.await_args.kwargs['body'], {'content': 'Oferta per klientin X', 'one_h_marker': 'QUESTION',
                                                         'department_id': None})
        event = db.add.call_args.args[0]
        self.assertEqual((event.kind, str(event.note_id), event.meeting_id), ('PX_NOTE', note_id, meeting.id))

    def test_people_named_in_a_note_are_proposed_but_markers_are_not(self):
        data = host.SlotData(payload([]), DAY)
        self.assertEqual(host.note_people(data, 'EF: oferta per klientin, GA !, M2'), ['EF'])
        self.assertEqual(host.note_people(data, 'Ta thirr Rinesa Ahmeti dhe OH per PDF'), ['OH', 'RA'])
        self.assertEqual(host.note_people(data, 'Thirr klientin ZZ'), [])

    async def test_unknown_person_is_asked_again_not_guessed(self):
        note = SimpleNamespace(id=uuid.uuid4(), is_converted_to_task=False, content='X', department_id=None)
        db = SimpleNamespace(get=AsyncMock(return_value=note), commit=AsyncMock(), add=Mock())
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:50')
        args = host.CreateTask(note_id=str(note.id), assignees=['Zzz'], due_date='2026-10-23', deadline=False)
        result = await host.create_task(db, meeting, host.SlotData(payload([]), DAY), args)
        self.assertFalse(result['success'])


class KnowledgeTests(unittest.TestCase):
    def test_text_files_are_read_and_pdf_is_refused(self):
        self.assertEqual(host.extract_text('a.md', 'Rregullore'.encode()), 'Rregullore')
        with self.assertRaises(HTTPException):
            host.extract_text('a.pdf', b'%PDF')


if __name__ == '__main__':
    unittest.main()


class SpokenTitleTests(unittest.TestCase):
    def test_owners_and_leading_numbers_are_not_read_aloud(self):
        self.assertEqual(host.spoken_title('RA/OH: 13 EVENTE ASISTENT'), 'EVENTE ASISTENT')
        self.assertEqual(host.spoken_title('EH: 39/10 WKF VS API'), 'WKF VS API')
        self.assertEqual(host.spoken_title('OH: 08:00 OH: FRG: EM: SB', ['OH']), 'FRG: EM: SB')
        self.assertEqual(host.spoken_title('EH: EH: CODEX ACC', ['EH']), 'CODEX ACC')
        self.assertEqual(host.spoken_title('EP/ESH/DV: 5 PIM- IDENTIFIKIMI'), 'PIM- IDENTIFIKIMI')
        self.assertEqual(host.spoken_title('LH: SRV DE DEAKTIVIZIM'), 'SRV DE DEAKTIVIZIM')
        self.assertEqual(host.spoken_title('2026'), '2026')


class SharedTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_task_shared_by_two_people_is_reported_once(self):
        first, second = str(uuid.uuid4()), str(uuid.uuid4())
        done_at = datetime(2026, 10, 21, 10, 30, tzinfo=TZ).isoformat()
        data = host.SlotData(payload([
            item('EF', '10:00', 'ASISTENTI PER TAK', rank=0, status='DONE', task_id=first, completed_at=done_at),
            item('RA', '10:00', 'ASISTENTI PER TAK', rank=1, status='DONE', task_id=second, completed_at=done_at),
        ]), DAY)
        strikes = [SimpleNamespace(task_id=uuid.UUID(t), point_key=f'k{t}', action='STRUCK', point_text='Sekuenca vetem kur duhet',
                                   occurred_at=datetime(2026, 10, 21, 9, tzinfo=timezone.utc)) for t in (first, second)]
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=strikes))))))
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00')
        with patch.object(host, 'mentioned', AsyncMock(return_value=set())):
            progress = await host.new_progress(db, meeting, data)
        self.assertEqual(len(progress['done']), 1)
        self.assertEqual(progress['done'][0]['owners'], ['EF', 'RA'])
        self.assertEqual(len(progress['strikes']), 1)
        self.assertEqual([p['text'] for p in progress['strikes'][0]['points']], ['Sekuenca vetem kur duhet'])


class TurnNotesTests(unittest.TestCase):
    def test_only_the_lines_spoken_during_a_turn_belong_to_it(self):
        transcript = [{'at': f'2026-10-21T14:2{m}:00+02:00', 'speaker': s, 'text': t}
                      for m, s, t in ((0, 'Mira', 'Rinesa?'), (1, 'Rinesa', '299 kompani'), (3, 'Endi', 'skema'))]
        lines = host.lines_during(transcript, '2026-10-21T14:20:30+02:00', '2026-10-21T14:22:00+02:00')
        self.assertEqual([l['speaker'] for l in lines], ['Rinesa'])


class JoinRetryTests(unittest.TestCase):
    def setUp(self):
        self.row = MiraHostSettings(updated_at=datetime(2026, 10, 21, 16, 1, tzinfo=TZ))

    def meeting(self, error, attempts=1, ended=datetime(2026, 10, 21, 15, 58, 39, tzinfo=TZ), status='ABORTED'):
        return Mira1HMeeting(status=status, error=error, join_attempts=attempts, ended_at=ended)

    def test_a_failed_voice_connection_is_retried_a_few_times(self):
        self.assertTrue(host.can_retry(self.meeting('interrupted:connect_timeout'), self.row))
        self.assertTrue(host.can_retry(self.meeting('realtime:OpenAI refuzoi'), self.row))
        self.assertFalse(host.can_retry(self.meeting('interrupted:connect_timeout', attempts=3), self.row))

    def test_restarting_after_mira_ndalo_rejoins_but_a_held_meeting_never_repeats(self):
        self.assertTrue(host.can_retry(self.meeting('stopped_by_command'), self.row))
        self.assertFalse(host.can_retry(self.meeting('stopped_by_command', ended=datetime(2026, 10, 21, 16, 5, tzinfo=TZ)), self.row))
        self.assertFalse(host.can_retry(self.meeting(None, status='DONE'), self.row))
        self.assertFalse(host.can_retry(self.meeting('stale'), self.row))
