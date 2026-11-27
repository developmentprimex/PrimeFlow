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

    def test_note_accepts_fond_shenime_across_segments(self):
        pending, commands = consume("Mira, shëno. Oferta e re. Fund titulli. Presim përgjigjen. Fond,", 0, 1000, None)
        self.assertEqual(commands, [])
        self.assertEqual(consume("shënime.", 1000, 2000, pending),
                         (None, [("note", "OFERTA E RE\nPresim përgjigjen.")]))

    def test_note_title_markers_uppercase_only_the_first_line(self):
        for marker in ("Fund titulli", "fund titullit", "fund titull", "fund titulle", "fund titullë", "Fund, titulli",
                       "fundtitull", "fundtitulli", "fundtitullë"):
            with self.subTest(marker=marker):
                self.assertEqual(
                    consume(f"Mira, shëno. Çështja e re. {marker}. Presim përgjigjen. Fund shënimi.", 0, 1000, None),
                    (None, [("note", "ÇËSHTJA E RE\nPresim përgjigjen.")]),
                )

    def test_note_title_marker_split_across_segments_is_used_only_once(self):
        pending, commands = consume("Mira, shëno. Oferta e re. Fund.", 0, 1000, None)
        self.assertEqual(commands, [])
        self.assertEqual(
            consume("Titulli. Thuaj fund titulli edhe një herë. Fund shënimi.", 1000, 2000, pending),
            (None, [("note", "OFERTA E RE\nThuaj fund titulli edhe një herë.")]),
        )

    def test_nd_title_markers_are_shared_by_all_dictation_commands(self):
        for marker in ("nd titullin", "nd titulli", "nd titull", "nd titullit", "nd titulle", "nd titullë", "ndtitulli"):
            with self.subTest(marker=marker):
                body = f"Oferta e re. {marker} Presim përgjigjen."
                expected = "OFERTA E RE\nPresim përgjigjen."
                self.assertEqual(consume(f"Mira, shëno. {body} Fund shënimi.", 0, 1000, None),
                                 (None, [("note", expected)]))
                self.assertEqual(consume(f"Mira, planifiko. {body} Fund shënimi.", 0, 1000, None),
                                 (None, [("plan_note", expected)]))
                self.assertEqual(task_fields(f"Për EFA. {body}"), ("EFA", expected))

    def test_plan_note_uses_a_distinct_start_and_the_same_title_and_end_markers(self):
        pending, commands = consume("Mira,", 0, 1000, None)
        self.assertEqual(commands, [])
        self.assertEqual(
            consume("planifiko. Çështja e re. Fundtitullë. Kontrollo ofertën. Fund shënime.", 1000, 2000, pending),
            (None, [("plan_note", "ÇËSHTJA E RE\nKontrollo ofertën.")]),
        )
        self.assertEqual(
            consume("Mira, planifiko. Oferta e re. Fund tit. Presim përgjigjen. Fund shënimi.", 0, 1000, None),
            (None, [("plan_note", "Oferta e re. Fund tit. Presim përgjigjen.")]),
        )

    def test_plan_note_accepts_transcribed_start_variants(self):
        for command in ("planifikoë", "planifikoe", "planfiko", "planfikoë", "planfikoe",
                        "planifko", "planifkoë", "planifkoe"):
            with self.subTest(command=command):
                self.assertEqual(
                    consume(f"Mira, {command}. Kontrollo ofertën. Fund shënimi.", 0, 1000, None),
                    (None, [("plan_note", "Kontrollo ofertën.")]),
                )

    def test_plan_note_recovers_the_reported_transcript_after_an_incomplete_task(self):
        pending, commands = consume("Mira detyrë për.", 0, 1000, None)
        self.assertEqual(commands, [])
        transcript = (
            "Planifiko. Tërendi do të përfundojë më së voni. Nd titullin. "
            "Tërendi do të vazhdojë më së voni dhe besoj. Që do të kryhet. Fond, shënime. Bondshënig."
        )
        expected = "TËRENDI DO TË PËRFUNDOJË MË SË VONI\nTërendi do të vazhdojë më së voni dhe besoj. Që do të kryhet."
        self.assertEqual(consume(transcript, 1000, 2000, pending), (None, [("plan_note", expected)]))

    def test_plan_note_accepts_fond_title_but_requires_a_full_closing_marker(self):
        start = "Mira, planifiko. Oferta e Modeco. Fond titulle. Krahaso çmimet."
        self.assertEqual(consume(f"{start} Fond shënime.", 0, 1000, None),
                         (None, [("plan_note", "OFERTA E MODECO\nKrahaso çmimet.")]))
        self.assertEqual(consume(f"{start} Shënime.", 0, 1000, None)[1], [])
        self.assertEqual(consume("Planifiko. Po diskutojmë planin.", 0, 1000, None), (None, []))
        self.assertEqual(consume("Planifiko takimin. Fond shënime.", 0, 1000, None), (None, []))
        self.assertEqual(consume("Planifiko. Mira, shëno. Oferta u dërgua. Fund shënimi.", 0, 1000, None),
                         (None, [("note", "Oferta u dërgua.")]))

    def test_note_is_saved_whole_without_a_recognized_title_marker(self):
        for body in ("Oferta e re. Presim përgjigjen.", "Oferta e re. Fund tit. Presim përgjigjen.",
                     "Kontrollo fjalën në fund të titullit.", "Projekti Fundtitullar.", "Projekti Ndtitullar.",
                     "Fund titulli. Pa titull të diktuar."):
            with self.subTest(body=body):
                self.assertEqual(
                    consume(f"Mira, shëno. {body} Fund shënimi.", 0, 1000, None),
                    (None, [("note", body)]),
                )

    def test_abandoned_dictation_does_not_close_later(self):
        pending, _ = consume("Mira shëno. Teksti i vjetër.", 0, 1000, None)
        pending, notes = consume("Fund shënimi.", 30_000, 31_000, pending)
        self.assertEqual(notes, [])
        self.assertIsNone(pending)

    def test_task_and_note_use_separate_end_markers(self):
        pending, commands = consume("Mira, detyrë për E. F. Kontrollo ofertën. Fond, shënime.", 0, 1000, None)
        self.assertEqual(commands, [])
        pending, commands = consume("Fund", 1000, 2000, pending)
        self.assertEqual(commands, [])
        pending, commands = consume("detyrës. Mira, shëno. U diskutua. Fund shënimi.", 2000, 3000, pending)
        self.assertIsNone(pending)
        self.assertEqual(commands, [("task", "për E. F. Kontrollo ofertën. Fond, shënime."), ("note", "U diskutua.")])

    def test_task_requires_initials_and_a_title(self):
        for body in ("EF, Kontrollo ofertën.", "për E. F. Kontrollo ofertën.", "e f kontrollo ofertën"):
            with self.subTest(body=body):
                self.assertEqual(task_fields(body), ("EF", body[body.lower().index("kontrollo"):].rstrip(".")))
        for body in ("EF", "Për EF.", "Kontrollo ofertën."):
            self.assertIsNone(task_fields(body))

    def test_task_title_uses_the_note_title_marker_variants(self):
        for marker in ("Fund titulli", "fundtitull", "fundtitulli", "fundtitullë"):
            with self.subTest(marker=marker):
                self.assertEqual(
                    task_fields(f"Për EFA. Çështja e re. {marker}. Kontrollo edhe ofertën."),
                    ("EFA", "ÇËSHTJA E RE\nKontrollo edhe ofertën."),
                )
        self.assertEqual(
            task_fields("Për EFA. Çështja e re. Fund tit. Kontrollo edhe ofertën."),
            ("EFA", "Çështja e re. Fund tit. Kontrollo edhe ofertën"),
        )

    def test_transcribed_variants_from_discord(self):
        pending, commands = consume(
            "Po. Mira, detyrë për EFA. Kontrollo ofertën e Modeco. Fund detyra.", 0, 1000, None,
        )
        self.assertIsNone(pending)
        self.assertEqual([kind for kind, _ in commands], ["task"])
        self.assertEqual(task_fields(commands[0][1]), ("EFA", "Kontrollo ofertën e Modeco"))

        pending, commands = consume(
            "Mira Shëna, përmodako presim përgjigjen nga Juliana. Fund shënime.", 0, 1000, None,
        )
        self.assertIsNone(pending)
        self.assertEqual(commands, [("note", "përmodako presim përgjigjen nga Juliana.")])

    def test_short_task_start_requires_word_boundary(self):
        for start in ("Mira detyr", "Mira detyrë", "Mira detyre"):
            with self.subTest(start=start):
                self.assertEqual(
                    consume(f"{start} për EF. Kontrollo ofertën. Fund detyre.", 0, 1000, None),
                    (None, [("task", "për EF. Kontrollo ofertën.")]),
                )

        self.assertEqual(consume("Mira detyra për EF. Fund detyre.", 0, 1000, None), (None, []))

    def test_note_start_with_mistranscribed_name_or_joined_words(self):
        examples = (
            ("Mirëa shëno. Elsa ka vazhdu me një detyrë për modako. Fund shënimi.",
             "Elsa ka vazhdu me një detyrë për modako."),
            ("Mirashënë, Rinisa ka një detyrë për fragmentin. Bël shënime. Fund shënime.",
             "Rinisa ka një detyrë për fragmentin. Bël shënime."),
        )
        for transcript, content in examples:
            with self.subTest(transcript=transcript):
                self.assertEqual(consume(transcript, 0, 1000, None), (None, [("note", content)]))

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
