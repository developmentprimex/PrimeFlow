import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/test')
os.environ.setdefault('JWT_SECRET', 'wfe-question-tests-not-production')

import mira_host as controller
from app.models.mira_host import Mira1HMeeting
from app.models.enums import TaskStatus
from app.services import mira_host as host, discord_m2, discord_m3, discord_one_h
from app.api.routers import discord_m3 as m3_api
from tests.test_mira_host_service import DAY, IDS, item, payload
from tests.test_discord_m3 import task


class WfeQuestionRules(unittest.TestCase):
    def test_host_marks_wfe_settled_without_rewriting_status_or_asking_about_it(self):
        waiting = item('EF', '11:00', 'OFERTA', rank=0, status='WAITING_CLIENT')
        data = host.SlotData(payload([waiting]), DAY)
        # The normal report selector already omits WFE. Also cover a retained
        # turn snapshot from before a live status update reached the Host.
        data.slots['11:00'] = [waiting]
        brief = host.person_brief(data, '11:00', IDS['EF'])
        self.assertTrue(brief['all_done'])
        self.assertEqual(brief['current'][0]['status'], 'WAITING_CLIENT')
        out = controller.turn_brief({'id': 'turn', 'name': 'Elsa', 'initials': 'EF', 'brief': brief})
        self.assertTrue(out['plan_discutimi'][0]['kryer'])
        self.assertTrue(out['te_gjitha_kryer'])
        self.assertFalse(out['aktual_dhe_paraprak_todo'])

    def test_mixed_host_plan_keeps_only_open_work_eligible(self):
        waiting = item('EF', '11:00', 'OFERTA', rank=0, status='WAITING_CLIENT')
        active = item('EF', '11:00', 'SKEMA', rank=1, status='TODO')
        brief = host.person_brief(host.SlotData(payload([waiting, active]), DAY), '11:00', IDS['EF'])
        out = controller.turn_brief({'name': 'Elsa', 'initials': 'EF', 'brief': brief})
        self.assertEqual([row['detyra'] for row in out['plan_discutimi'] if not row['kryer']], ['SKEMA'])
        self.assertFalse(out['te_gjitha_kryer'])

    def test_wfe_is_not_in_blocked_or_ga_or_pm_followups(self):
        waiting = item('DV', '14:20', 'OFERTA', rank=0, status='WAITING_CLIENT', finish_period='PM', one_h_marker='FLAG')
        source = payload([waiting])
        source['items']['blocked'] = [item('DV', None, 'BLLOK WFE', rank=0, status='WAITING_CLIENT')]
        data = host.SlotData(source, DAY)
        data.blocked = list(source['items']['blocked'])
        self.assertEqual(data.pm_open(), [])
        self.assertEqual(data.ga_flagged(), [])
        self.assertEqual(data.blocked_tasks(IDS['DV']), [])
        self.assertNotIn(IDS['DV'], data.participants('16:00'))

    def test_m2_excludes_wfe_from_every_kind_including_delivery(self):
        for status in ('WAITING_CLIENT', 'WFE', TaskStatus.WAITING_CLIENT):
            row = {'task_id': str(uuid.uuid4()), 'status': status}
            data = {section: [row] for section in ('unfinished_priority', 'postponed', 'postponed_am', 'ga_progress', 'delivery', 'pm_continuation')}
            self.assertEqual(discord_m2.question_rows(data), [])

    def test_m3_tomorrow_excludes_wfe_but_keeps_active_work(self):
        waiting, active = task(status='WAITING_CLIENT'), task(status='IN_PROGRESS')
        rows = discord_m3.tomorrow_rows([waiting, active], active.due_date, {})
        self.assertEqual([row['task_id'] for row in rows], [str(active.id)])
        self.assertEqual(waiting.status, 'WAITING_CLIENT')

    def test_personal_1h_wfe_is_done_for_questions_only(self):
        report = {'tasks': [{'status': 'WAITING_CLIENT'}, {'status': 'DONE'}]}
        self.assertTrue(discord_one_h.all_done(report))
        self.assertIsNone(discord_one_h.question('WAITING_CLIENT', 'OFERTA'))
        self.assertEqual(report['tasks'][0]['status'], 'WAITING_CLIENT')


class WfeLiveGuards(unittest.IsolatedAsyncioTestCase):
    async def test_wfe_only_handoff_does_not_instruct_mira_to_ask_task_questions(self):
        from tests.test_mira_host_bot import BRIEF, session
        waiting = {'task_id': 'wfe', 'title': 'OFERTA', 'status': 'WAITING_CLIENT', 'period': 'AM'}
        current = {'id': 'turn', 'name': 'Elsa', 'initials': 'EF', 'discord': None,
                   'brief': {**BRIEF, 'current': [waiting]}}
        bot = controller.MiraHost(SimpleNamespace(bridge=AsyncMock(return_value={'current': current})))
        result = await bot.advance(session(), None, announce=False)
        self.assertTrue(result['RADHA']['te_gjitha_kryer'])
        self.assertIn('Mos bëj pyetje për këto detyra', result['udhezim'])
        self.assertNotIn('hyr direkt te detyra e parë', result['udhezim'])
        self.assertNotIn('Pyet shkurt vetëm çka mungon', result['udhezim'])

    async def test_old_m2_delivery_card_disables_questions_after_wfe(self):
        from app.services import discord_answer_sync as sync
        from app.api.routers import discord_m2 as m2_api
        uid, tid = uuid.uuid4(), uuid.uuid4()
        waiting = SimpleNamespace(id=tid, status='WAITING_CLIENT', is_active=True, assigned_to=uid)
        q = SimpleNamespace(task_id=tid, kind='delivery')
        with patch.object(m2_api, 'question_payload', return_value={'kind': 'delivery'}):
            result = await sync.m2_payload(SimpleNamespace(get=AsyncMock(return_value=waiting)), q, SimpleNamespace(user_id=uid))
        self.assertIn('WFE', result['platform_status'])
        self.assertFalse(result.get('task_actionable', False))

    async def test_host_can_end_turn_without_a_wfe_discussion_record(self):
        turn = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.UUID(IDS['EF']), status='ACTIVE', ended_at=None, notes='')
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00', status='STAFF_PHASE')
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [turn]))), flush=AsyncMock())
        brief = {'current': [{'task_id': 'wfe', 'status': 'WAITING_CLIENT', 'spoken': 'OFERTA'}], 'previous_open': [], 'blocked': []}
        with patch.object(host, 'common_payload', AsyncMock(return_value=payload([]))), \
             patch.object(host, 'person_brief', return_value=brief), \
             patch.object(host, 'discussion_context', AsyncMock(return_value={})), \
             patch.object(host, 'turns_view', AsyncMock(return_value=[])):
            await host.next_turn(db, meeting, None, expected_turn_id=turn.id)
        self.assertEqual(turn.status, 'DONE')

    async def test_old_m3_delivery_card_resolves_after_task_becomes_wfe(self):
        waiting = task(status='WAITING_CLIENT', progress_percentage=50)
        q = SimpleNamespace(id=uuid.uuid4(), task_id=waiting.id, meeting_id=None, kind='delivery', answer={})
        with patch.object(m3_api, 'question_payload', return_value={'kind': 'delivery'}), \
             patch.object(m3_api, 'task_owned', AsyncMock(return_value=waiting)):
            result = await m3_api.live_payload(SimpleNamespace(), q, None, SimpleNamespace(id=uuid.uuid4()))
        self.assertIn('WFE', result['resolved'])
