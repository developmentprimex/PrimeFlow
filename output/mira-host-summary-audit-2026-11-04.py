"""Read-only reproducer for the summary race, left unchanged by the user's scope decision.

Run: backend/.venv/Scripts/python.exe output/mira-host-summary-audit-2026-11-04.py
A failing assertion confirms the known race; this is outside the regression suite.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import unittest
import uuid
from unittest.mock import AsyncMock, patch
from tests.test_mira_host_service import DAY
from app.models.mira_host import Mira1HMeeting
from app.services import mira_host as service, discord_voice_openai as provider

class SummaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_in_flight_cannot_overwrite_a_new_attempt_or_new_transcript(self):
        for change in ('restart', 'transcript'):
            with self.subTest(change=change):
                meeting = Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot='11:00',
                    status='ABORTED', join_attempts=1, summary_status='PENDING', summary='Previous summary',
                    host_transcript=[{'speaker': 'Elsa', 'at': service.now().isoformat(), 'text': 'Original'}])
                db = AsyncMock()
                db.__aenter__.return_value = db
                async def summarize(*_, **__):
                    if change == 'restart':
                        meeting.join_attempts = 2
                        meeting.status = 'STAFF_PHASE'
                        meeting.summary_status = None
                    else:
                        meeting.host_transcript = [*meeting.host_transcript,
                            {'speaker': 'Elsa', 'at': service.now().isoformat(), 'text': 'Late transcript'}]
                    return 'Stale generated summary'
                with patch('app.db.SessionLocal', return_value=db), \
                     patch.object(service, 'meeting_for', AsyncMock(return_value=meeting)), \
                     patch.object(service, 'turns_view', AsyncMock(return_value=[])), \
                     patch.object(service, 'meeting_events', AsyncMock(return_value=[])), \
                     patch.object(service, 'write_turn_notes', AsyncMock()) as notes, \
                     patch.object(provider, 'summarize_meeting', summarize):
                    await service.summarize(meeting.id)
                self.assertEqual(meeting.summary, 'Previous summary')
                self.assertEqual(meeting.summary_status, None if change == 'restart' else 'PENDING')
                notes.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
