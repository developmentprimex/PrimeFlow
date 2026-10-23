import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.services.recording_task_notes import sync_recording_note_from_task


class RecordingTaskNotesTests(unittest.IsolatedAsyncioTestCase):
    async def test_recording_edit_and_strike_reach_note_and_other_assignee_copy(self):
        note = SimpleNamespace(id=uuid.uuid4(), content='OLD', knowledge_type='RECORDING')
        task = SimpleNamespace(id=uuid.uuid4(), title='TITLE\n[[done]]Completed point[[/done]]')
        sibling = SimpleNamespace(id=uuid.uuid4(), title='OLD')
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=[sibling]))))))
        with patch('app.services.recording_task_notes.record_title_strike_events') as strikes:
            await sync_recording_note_from_task(db, note, task, {'title'}, uuid.uuid4())
        self.assertEqual(note.content, task.title)
        self.assertEqual(sibling.title, task.title)
        strikes.assert_called_once()
        self.assertEqual(strikes.call_args.kwargs['after_title'], task.title)

    async def test_ordinary_notes_are_unchanged_and_status_does_not_replace_content(self):
        db = SimpleNamespace(execute=AsyncMock())
        note = SimpleNamespace(content='PX note', knowledge_type=None)
        task = SimpleNamespace(title='Other title')
        await sync_recording_note_from_task(db, note, task, {'title'}, uuid.uuid4())
        self.assertEqual(note.content, 'PX note')
        db.execute.assert_not_called()
        note.knowledge_type = 'RECORDING'
        await sync_recording_note_from_task(db, note, task, {'status'}, uuid.uuid4())
        self.assertEqual(note.content, 'PX note')
        db.execute.assert_not_called()
