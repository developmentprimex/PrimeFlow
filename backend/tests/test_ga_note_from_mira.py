import os
import unittest
import uuid
from datetime import datetime, timezone

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET', 'voice-tests-not-a-production-secret')

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

import app.models  # noqa: F401  registers every mapper, including the Mira property
from app.api.routers.ga_notes import _note_out
from app.models.enums import GaNoteStatus, GaNoteType
from app.models.ga_note import GaNote


class GaNoteFromMiraTests(unittest.TestCase):
    def test_every_note_query_loads_whether_a_mira_meeting_saved_it(self):
        sql = str(select(GaNote).compile(dialect=postgresql.dialect()))
        self.assertIn('EXISTS', sql)
        self.assertIn('discord_voice_meetings.saved_note_id = ga_notes.id', sql)

    def note(self, **loaded):
        now = datetime.now(timezone.utc)
        note = GaNote(id=uuid.uuid4(), content='Shënime', note_type=GaNoteType.GA, status=GaNoteStatus.OPEN,
            start_date=now, is_converted_to_task=False, is_discussed=False, one_h_marker_by_ga=False,
            created_at=now, updated_at=now)
        note.__dict__.update(loaded)
        return note

    def test_api_marks_mira_notes_and_never_lazy_loads_new_notes(self):
        self.assertTrue(_note_out(self.note(from_mira=True)).from_mira)
        self.assertTrue(_note_out(self.note(from_mira_desktop=True)).from_mira)
        self.assertFalse(_note_out(self.note()).from_mira)

    def test_desktop_note_marker_is_loaded_with_the_existing_note_query(self):
        sql = str(select(GaNote).compile(dialect=postgresql.dialect()))
        self.assertIn('mira_desktop_sessions.note_id = ga_notes.id', sql)


if __name__ == '__main__':
    unittest.main()
