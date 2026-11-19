import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/primeflow_test")
os.environ.setdefault("JWT_SECRET", "voice-tests-not-a-production-secret")

from app.services.mira_voice_dictation import consume


class DictationCommandTests(unittest.TestCase):
    def test_commands_split_across_segments_preserve_spoken_words(self):
        pending, notes = consume("Po, mirë. Mira,", 0, 1000, None)
        self.assertEqual(notes, [])
        pending, notes = consume("shëno. Po, po, e kam dërgu. Fund", 1000, 2000, pending)
        self.assertEqual(notes, [])
        pending, notes = consume("shënimi. Tjetër temë.", 2000, 3000, pending)
        self.assertEqual(notes, ["Po, po, e kam dërgu."])
        self.assertIsNone(pending)

    def test_multiple_commands_and_empty_dictation(self):
        pending, notes = consume(
            "Fund shënimi. Mira sheno, A. Fund shenimi. Mira shëno. Fund shënimi. Mira shëno, B. Fund shënimi.",
            0, 1000, None,
        )
        self.assertEqual(notes, ["A.", "B."])
        self.assertIsNone(pending)

    def test_abandoned_dictation_does_not_close_later(self):
        pending, _ = consume("Mira shëno. Teksti i vjetër.", 0, 1000, None)
        pending, notes = consume("Fund shënimi.", 30_000, 31_000, pending)
        self.assertEqual(notes, [])
        self.assertIsNone(pending)
