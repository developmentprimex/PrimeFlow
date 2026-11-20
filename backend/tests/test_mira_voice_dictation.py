import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/primeflow_test")
os.environ.setdefault("JWT_SECRET", "voice-tests-not-a-production-secret")

from app.services.mira_voice_dictation import consume, task_fields


class DictationCommandTests(unittest.TestCase):
    def test_commands_split_across_segments_preserve_spoken_words(self):
        pending, notes = consume("Po, mirë. Mira,", 0, 1000, None)
        self.assertEqual(notes, [])
        pending, notes = consume("shëno. Po, po, e kam dërgu. Fund", 1000, 2000, pending)
        self.assertEqual(notes, [])
        pending, notes = consume("shënimi. Tjetër temë.", 2000, 3000, pending)
        self.assertEqual(notes, [("note", "Po, po, e kam dërgu.")])
        self.assertIsNone(pending)

    def test_multiple_commands_and_empty_dictation(self):
        pending, notes = consume(
            "Fund shënimi. Mira sheno, A. Fund shenimi. Mira shëno. Fund shënimi. Mira shëno, B. Fund shënimi.",
            0, 1000, None,
        )
        self.assertEqual(notes, [("note", "A."), ("note", "B.")])
        self.assertIsNone(pending)

    def test_abandoned_dictation_does_not_close_later(self):
        pending, _ = consume("Mira shëno. Teksti i vjetër.", 0, 1000, None)
        pending, notes = consume("Fund shënimi.", 30_000, 31_000, pending)
        self.assertEqual(notes, [])
        self.assertIsNone(pending)

    def test_task_and_note_use_separate_end_markers(self):
        pending, commands = consume("Mira, detyrë për E. F. Kontrollo ofertën. Fund shënimi.", 0, 1000, None)
        self.assertEqual(commands, [])
        pending, commands = consume("Fund", 1000, 2000, pending)
        self.assertEqual(commands, [])
        pending, commands = consume("detyrës. Mira, shëno. U diskutua. Fund shënimi.", 2000, 3000, pending)
        self.assertIsNone(pending)
        self.assertEqual(commands, [("task", "për E. F. Kontrollo ofertën. Fund shënimi."), ("note", "U diskutua.")])

    def test_task_requires_initials_and_a_title(self):
        for body in ("EF, Kontrollo ofertën.", "për E. F. Kontrollo ofertën.", "e f kontrollo ofertën"):
            with self.subTest(body=body):
                self.assertEqual(task_fields(body), ("EF", body[body.lower().index("kontrollo"):].rstrip(".")))
        for body in ("EF", "Për EF.", "Kontrollo ofertën."):
            self.assertIsNone(task_fields(body))

    def test_pending_note_from_previous_release_still_works(self):
        pending, commands = consume("Fund shënimi.", 1000, 2000, {
            "started": 0, "end_ms": 1000, "text": "Shënim i diktuar.",
        })
        self.assertIsNone(pending)
        self.assertEqual(commands, [("note", "Shënim i diktuar.")])

    def test_task_command_quoted_inside_note_stays_in_note(self):
        quoted = "Shembulli ishte Mira, detyrë EF, Kontrollo ofertën. Fund detyre."
        pending, commands = consume(f"Mira, shëno. {quoted} Fund shënimi.", 0, 1000, None)
        self.assertIsNone(pending)
        self.assertEqual(commands, [("note", quoted)])
