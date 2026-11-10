"""Only scheduled recorder sessions enter automatic note saving."""
import os
import unittest
from types import SimpleNamespace

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET', 'scheduled-notes-test-secret')
from app.services.discord_voice_meetings import is_scheduled


class ScheduledNotesTests(unittest.TestCase):
    def test_automatic_saving_is_scoped_to_schedule_and_recorder(self):
        for recorder, request_id, expected in (
            ('primary', 'auto1h-202611100958', True),
            ('ai_agent', 'autoai-202611100804', True),
            ('ai_agent', 'autoai-202611100804-2', True),
            ('primary', 'autoai-202611100804', False),
            ('primary', '1560234482232201228', False),
            ('ai_agent', '1565287350915960882', False),
        ):
            with self.subTest(recorder=recorder, request_id=request_id):
                self.assertEqual(is_scheduled(SimpleNamespace(recorder=recorder, request_id=request_id)), expected)
