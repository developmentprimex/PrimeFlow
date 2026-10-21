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
        text = host.brief_message(brief, host.DEFAULT_PROTOCOL)
        self.assertIn('Share screen side by side', text)
        self.assertIn('Nga sloti paraprak 10:00', text)

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
        self.db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None))),
                                  commit=AsyncMock())
        self.data = payload([item('EF', '10:00', 'A', rank=0), item('RA', '11:00', 'B', rank=0)])
        targets = {uid: {'discord_user_id': str(n), 'guild_id': '1', 'channel_id': str(100 + n)} for n, uid in enumerate(IDS.values())}
        self.patches = [patch.object(host, 'get_settings', AsyncMock(return_value=self.row)),
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
        self.assertEqual(await self.kinds(9, 55), [])
        self.assertEqual(await self.kinds(10, 55), [('brief', '11:00')])

    async def test_ga_is_called_two_minutes_before_and_mira_joins(self):
        kinds = await self.kinds(9, 58)
        self.assertEqual(kinds.count(('ga_call', '10:00')), 3)
        self.assertIn(('join', '10:00'), kinds)

    async def test_nothing_happens_until_mira_is_started(self):
        self.row.enabled_until = None
        self.assertEqual(await self.kinds(9, 58), [])


class ProgressTests(unittest.IsolatedAsyncioTestCase):
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
