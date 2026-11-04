"""Development staff do not report or count as absent in the two exempt slots."""
import uuid
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from tests.test_mira_host_service import DAY, IDS, NAMES, item, payload
from tests.test_mira_host_runtime import result
from app.models.mira_host import Mira1HEvent, Mira1HMeeting
from app.services import mira_host as host, mira_host_runtime as runtime

LH_ID = str(uuid.uuid4())


class SlotExclusionTests(unittest.IsolatedAsyncioTestCase):
    def source(self):
        source = payload([item(key, slot, 'Work', rank=i, finish_period='PM')
                          for slot in host.SLOTS for i, key in enumerate(('EH', 'EF', 'RA', 'OH'))])
        source['users'].append({'id': LH_ID, 'full_name': 'Laurent Hoxha', 'is_active': True})
        for slot in host.SLOTS:
            source['items']['oneH'].append({**item('EH', slot, 'LH work', rank=9, finish_period='PM'),
                                            'user_id': LH_ID, 'assignees': ['Laurent Hoxha']})
        source['items']['blocked'] = [item('EF', None, 'Blocked', rank=0)]
        return source

    def test_only_the_two_slots_exclude_development_from_current_earlier_and_blocked_work(self):
        source = self.source()
        data = host.SlotData(source, DAY)
        for slot in ('11:50', '16:00'):
            with self.subTest(slot=slot):
                self.assertEqual(data.participants(slot), [IDS['OH']])
        for slot in ('10:00', '11:00', '14:20'):
            with self.subTest(slot=slot):
                self.assertEqual(set(data.participants(slot)), {IDS['EH'], IDS['EF'], IDS['RA'], IDS['OH'], LH_ID})
        self.assertTrue(data.user_tasks('11:50', IDS['EF']))
        self.assertEqual(len(source['items']['oneH']), 25)

    def test_pm_review_excludes_the_same_people_without_dropping_other_staff(self):
        data = host.SlotData(self.source(), DAY)
        self.assertEqual([p['user_id'] for p in data.pm_open()], [IDS['OH']])

    async def test_new_and_restarted_meetings_do_not_enqueue_exempt_staff(self):
        for slot in ('11:50', '16:00'):
            for attempt in (1, 2):
                with self.subTest(slot=slot, attempt=attempt):
                    old = [SimpleNamespace(user_id=uuid.UUID(IDS[key]), status='SKIPPED') for key in ('EF', 'EH', 'RA')]
                    added = []
                    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: old)),
                                         add=added.append, flush=AsyncMock())
                    meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot=slot, status='GA_PHASE', join_attempts=attempt)
                    with patch.object(host, 'common_payload', AsyncMock(return_value=self.source())), \
                         patch.object(host, 'turns_view', AsyncMock(return_value=[])):
                        await host.begin_staff(db, meeting)
                    self.assertEqual([str(t.user_id) for t in added], [IDS['OH']])
                    self.assertEqual([t.status for t in old], ['SKIPPED', 'SKIPPED', 'SKIPPED'])

    async def test_saved_turns_are_skipped_without_absence_and_without_losing_notes(self):
        for slot in ('11:50', '16:00'):
            for status in ('WAITING', 'ACTIVE', 'DEFERRED'):
                with self.subTest(slot=slot, status=status):
                    turns = [SimpleNamespace(id=uuid.uuid4(), user_id=uuid.UUID(IDS[key]),
                              status=status if key == 'EF' else 'WAITING', ended_at=None,
                              started_at=None, invited_at=None, notes='Saved facts') for key in ('EF', 'OH')]
                    db = SimpleNamespace(execute=AsyncMock(return_value=result(rows=turns)), flush=AsyncMock())
                    meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot=slot, status='STAFF_PHASE')
                    async def view(*_):
                        return [{'id': str(t.id), 'user_id': str(t.user_id), 'name': NAMES[key], 'status': t.status}
                                for t, key in zip(turns, ('EF', 'OH'))]
                    with patch.object(host, 'common_payload', AsyncMock(return_value=payload([]))), \
                         patch.object(host, 'discussion_context', AsyncMock(return_value={})), \
                         patch.object(host, 'turns_view', view), patch.object(host, 'person_context', AsyncMock(return_value={})):
                        out = await host.next_turn(db, meeting, None,
                            expected_turn_id=turns[0].id if status == 'ACTIVE' else None,
                            available_user_ids=[turns[1].user_id])
                    self.assertEqual(turns[0].status, 'SKIPPED')
                    self.assertEqual(turns[0].notes, 'Saved facts')
                    self.assertEqual(out['current']['user_id'], IDS['OH'])
                    self.assertEqual(out['skipped'], [])
                    self.assertEqual(out['deferred'], [])

    async def test_meeting_detail_hides_exempt_staff_only_in_the_two_slots(self):
        rows = [(SimpleNamespace(id=uuid.uuid4(), user_id=uuid.UUID(IDS[key]), status='DEFERRED',
                 order_idx=i, invited_at=None, started_at=None, ended_at=None, notes=''), NAMES[key])
                for i, key in enumerate(('EF', 'OH'))]
        db = SimpleNamespace(execute=AsyncMock(return_value=result(rows=rows)))
        with patch.object(host, 'discord_targets', AsyncMock(return_value={})):
            for slot, expected in (('11:50', [IDS['OH']]), ('16:00', [IDS['OH']]), ('11:00', [IDS['EF'], IDS['OH']])):
                meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot=slot)
                self.assertEqual([t['user_id'] for t in await host.turns_view(db, meeting)], expected)

    async def test_existing_person_notes_are_preserved_when_sharing_a_meeting_to_px(self):
        turn = SimpleNamespace(id=uuid.uuid4(), user_id=uuid.UUID(IDS['EF']), status='DONE', order_idx=0,
                               invited_at=None, started_at=None, ended_at=None, notes='Saved reporting facts')
        db = SimpleNamespace(execute=AsyncMock(return_value=result(rows=[(turn, NAMES['EF'])])))
        meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:50', summary='Meeting summary')
        with patch.object(host, 'discord_targets', AsyncMock(return_value={})):
            content = await host._meeting_note_content(db, meeting)
        self.assertIn('EF: Saved reporting facts', content)

    async def test_pm_restart_does_not_restore_or_announce_exempt_saved_turns(self):
        for status in ('WAITING', 'ACTIVE', 'DEFERRED', 'SKIPPED'):
            with self.subTest(status=status):
                meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:50', status='STAFF_PHASE', join_attempts=2)
                queue = [{'id': 'PM_' + IDS[key], 'user_id': IDS[key], 'name': NAMES[key], 'person': NAMES[key],
                          'status': status if key == 'EF' else 'WAITING', 'discussion': {'continuation': 'Saved facts'}}
                         for key in ('EF', 'OH')]
                event = Mira1HEvent(id=uuid.uuid4(), slot='11:50', data={'queue': queue, 'join_attempt': 1})
                self.assertEqual([t['user_id'] for t in runtime.pm_state(event)['turns']], [IDS['OH']])
                with patch.object(runtime, 'pm_event', AsyncMock(return_value=event)):
                    out = await runtime.next_pm_turn(SimpleNamespace(), meeting,
                        expected_turn_id='PM_' + IDS['EF'] if status == 'ACTIVE' else None)
                self.assertEqual(out['current']['user_id'], IDS['OH'])
                self.assertEqual(out['deferred'], [])
                self.assertEqual(out['skipped'], [])
                self.assertEqual(event.data['queue'][0]['status'], 'SKIPPED')
                self.assertEqual(event.data['queue'][0]['discussion'], {'continuation': 'Saved facts'})

    async def test_pm_initialization_ignores_only_exempt_unfinished_main_turns(self):
        for key in ('EF', 'DV'):
            with self.subTest(key=key):
                turn_id = uuid.uuid4()
                added = []
                db = SimpleNamespace(execute=AsyncMock(return_value=result(turn_id, rows=[(turn_id, NAMES[key])])), add=added.append)
                meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:50', status='STAFF_PHASE')
                with patch.object(runtime, 'pm_event', AsyncMock(return_value=None)), \
                     patch.object(host, 'common_payload', AsyncMock(return_value=self.source())), \
                     patch.object(host, 'discord_targets', AsyncMock(return_value={})):
                    if key == 'DV':
                        with self.assertRaises(HTTPException) as error:
                            await runtime.next_pm_turn(db, meeting, expected_turn_id=None)
                        self.assertEqual(error.exception.status_code, 409)
                        self.assertEqual(added, [])
                    else:
                        out = await runtime.next_pm_turn(db, meeting, expected_turn_id=None)
                        self.assertEqual(out['current']['user_id'], IDS['OH'])
                        self.assertEqual([t['user_id'] for t in out['turns']], [IDS['OH']])
