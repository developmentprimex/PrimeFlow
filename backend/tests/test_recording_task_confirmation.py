"""Owner-reviewed recording tasks forward the full form to existing Tasks."""
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routers import recording_analysis as router


class RecordingTaskConfirmationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sid, self.aid, self.uid, self.did, self.second = [uuid.uuid4() for _ in range(5)]
        self.proposal = SimpleNamespace(id=self.aid, confirmed_at=None, created_task_id=None, segment_index=0)
        self.row = SimpleNamespace(id=self.sid)
        self.user = SimpleNamespace(id=self.uid)
        self.db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=self.proposal))),
                                  get=AsyncMock(return_value=SimpleNamespace(is_active=True)))

    def payload(self, **overrides):
        return router.TaskConfirmation(**{'title': 'Përgatit raportin', 'description': 'Raporti i kontrolluar.',
            'department_id': self.did, 'assigned_to': self.uid, 'assignees': [self.uid, self.second], **overrides})

    async def test_full_form_is_forwarded_and_duplicate_does_not_create_twice(self):
        payload = self.payload(title='Përgatit raportin\nRaporti i kontrolluar.', description='', project_id=uuid.uuid4(), priority='NORMAL', finish_period='AM',
            start_date='2026-11-01T00:00:00+00:00', due_date='2026-11-03T17:00:00+00:00',
            is_deadline_important=True, is_1h_report=True, one_h_report_slot='11:50',
            one_h_marker='QUESTION', one_h_marker_comment='Kontrollo', skill_category='management')
        created = SimpleNamespace(id=uuid.uuid4())
        async def create(task, db, user, *, before_commit):
            before_commit(created)
            return created
        with patch.object(router, 'load_recording', new=AsyncMock(return_value=self.row)), \
                patch.object(router, 'audit'), \
                patch('app.api.routers.tasks.create_task_in_session', new=AsyncMock(side_effect=create)) as create_task:
            result = await router.confirm_task(self.sid, self.aid, payload, self.db, self.user)
            task = create_task.call_args.args[0]
            self.assertEqual(task.title, 'PËRGATIT RAPORTIN\nRaporti i kontrolluar.')
            self.assertEqual(task.assignees, [self.uid, self.second])
            for field in ('project_id', 'priority', 'finish_period', 'start_date', 'due_date',
                          'is_deadline_important', 'is_1h_report', 'one_h_report_slot',
                          'one_h_marker', 'one_h_marker_comment', 'skill_category'):
                self.assertEqual(getattr(task, field), getattr(payload, field), field)
            self.assertIsNone(task.description)
            duplicate = await router.confirm_task(self.sid, self.aid, payload, self.db, self.user)
            self.assertTrue(duplicate['duplicate'])
            self.assertEqual(result['task_id'], duplicate['task_id'])
            create_task.assert_awaited_once()

    async def test_inactive_additional_assignee_is_rejected(self):
        async def get(model, key):
            return SimpleNamespace(is_active=key != self.second)
        self.db.get.side_effect = get
        with patch.object(router, 'load_recording', new=AsyncMock(return_value=self.row)):
            with self.assertRaises(HTTPException) as caught:
                await router.confirm_task(self.sid, self.aid, self.payload(), self.db, self.user)
        self.assertEqual(caught.exception.status_code, 422)

    def test_privileged_origin_fields_are_still_rejected(self):
        with self.assertRaises(ValidationError):
            self.payload(ga_note_origin_id=uuid.uuid4())


if __name__ == '__main__':
    unittest.main()
