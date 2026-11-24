from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import Response

from app.api.routers.ga_notes import get_ga_note_email
from app.services import after_break_report, morning_report
from app.services.m1_reporting_points import _newest_notes_first
from app.services.meetings_report import _section_report_table_rows
from app.services.morning_report import SECTION_TITLES, _notes_section
from app.services.primeflow_report import ReportDocument
from app.services.px_note_email import email_preview, manual_original_email_url
from app.services.report_note_attachments import NOTE_REFERENCES, match_note_rows, section_note_attachments, section_note_controls


class ReportNoteAttachmentsTests(IsolatedAsyncioTestCase):
    async def test_new_reports_load_ordinary_notes_before_email_notes(self):
        now = datetime(2026, 11, 24, 10, tzinfo=timezone.utc)
        notes = [
            SimpleNamespace(
                id=uuid4(), content=content, created_at=now - timedelta(minutes=offset),
                created_by=None, is_discussed=False,
            )
            for content, offset in (
                ("Ordinary later", 1), ("EM GA: 08:00 Manual email", 4),
                ("Ordinary earlier", 3), ("EM IT - Imported email", 2),
            )
        ]
        db = AsyncMock()
        db.execute.side_effect = [
            SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: notes)),
            SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [])),
        ]
        references = await after_break_report.load_blue_notes(db, created_before=now)
        assert [note_id for note_id, _ in references] == [str(notes[i].id) for i in (2, 0, 1, 3)]
        assert [row[0] for _, row in references] == ["1", "2", "3", "4"]

    async def test_saved_m1_and_m2_move_emails_last_and_keep_note_ids(self):
        titles = ["EM IT: 08:00 Imported", "Ordinary first", "EM GA: 08:00 Manual", "Ordinary second"]
        note_ids = [str(uuid4()) for _ in titles]
        values = [[str(index), "NO", title, "GA", "09:00"] for index, title in enumerate(titles, 1)]
        snapshot = {NOTE_REFERENCES: list(zip(note_ids, values))}
        expected_order = [1, 3, 0, 2]
        for report, index, normalize in (
            (morning_report, 3, morning_report.normalize_morning_report_sections),
            (after_break_report, 9, after_break_report.normalize_after_break_report_sections),
        ):
            with self.subTest(report=report.__name__):
                title = report.SECTION_TITLES[index]
                sections = normalize([{"title": title, "body": _notes_section(values)}])
                body = next(section["body"] for section in sections if section["section_key"] == title)
                _, ordered_rows = _section_report_table_rows(body.splitlines())
                assert [(row[0], row[2]) for row in ordered_rows] == [
                    (str(number), titles[position]) for number, position in enumerate(expected_order, 1)
                ]
                assert await match_note_rows(AsyncMock(), ordered_rows, snapshot) == {
                    str(number): note_ids[position] for number, position in enumerate(expected_order, 1)
                }

    def test_report_points_and_1h_group_email_notes_last(self):
        notes = [
            {"id": "1", "content": "EM IT: 08:00 Order", "created_at": "2026-11-24T10:30:00+01:00"},
            {"id": "2", "content": "Normal note", "created_at": "2026-11-24T10:00:00+01:00"},
            {"id": "3", "content": "EM GA: 08:00 Project", "created_at": "2026-11-24T09:30:00+01:00"},
        ]
        ordered = _newest_notes_first(notes)
        assert [note["id"] for note in ordered] == ["2", "1", "3"]
        document = ReportDocument.model_validate({
            "subject": "1H report",
            "report_date": "2026-11-24",
            "report_slot": "10:00",
            "generated_at": "2026-11-24T11:00:00+01:00",
            "source_generated_at": "2026-11-24T11:00:00+01:00",
            "recipients": {},
            "sections": [],
            "undiscussed_notes": notes,
        })
        assert [note.content for note in document.undiscussed_notes] == [note["content"] for note in ordered]

    async def test_old_snapshot_email_has_compact_metadata_and_original_id(self):
        note_id = uuid4()
        note = SimpleNamespace(
            id=note_id, knowledge_type="IT_MAIL", created_at=datetime(2026, 11, 24, 9, tzinfo=timezone.utc),
            content="EM IT - Porosia\nDërguesi: Drita <drita@example.test>\n\nOriginal email body.",
            email_metadata=None,
        )
        values = [["1", "NO", " ".join(note.content.split()), "-", "10:00"]]
        sections = [{"title": SECTION_TITLES[3], "body": _notes_section(values)}]
        db = AsyncMock()
        db.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
        db.scalars.return_value = SimpleNamespace(all=lambda: [note])

        controls = await section_note_controls(db, sections, SECTION_TITLES[3], {
            NOTE_REFERENCES: [[str(note_id), values[0]]],
        })

        assert controls["note_emails"]["1"] == {
            "id": str(note_id), "title": "EM IT: 08:00 POROSIA", "subject": "Porosia", "sender": "Drita <drita@example.test>",
        }
        assert not controls["note_attachments"]

        response = Response()
        db.execute.return_value = SimpleNamespace(one_or_none=lambda: (note, None))
        requested = await get_ga_note_email(note_id, response, db, SimpleNamespace())
        assert requested["body"] == "Original email body."
        assert response.headers["cache-control"] == "no-store"

        db.execute.return_value = SimpleNamespace(one_or_none=lambda: (note, "Complete source"))
        requested = await get_ga_note_email(note_id, response, db, SimpleNamespace())
        assert requested["body"] == "Complete source"

    def test_email_title_keeps_the_received_time_and_named_project(self):
        note = SimpleNamespace(
            id=uuid4(), knowledge_type="INFO_PX_MAIL",
            created_at=datetime(2026, 11, 24, 7, tzinfo=timezone.utc),
            content="EM INFO PX: 09:50 Puris – Home24\nKlienti kërkon automatizim.",
            email_metadata={"subject": "Re: Kërkesë", "sender": "Drita"},
        )
        preview = email_preview(note)
        assert preview["title"] == "EM INFO PX: 08:00 PURIS – HOME24"
        assert preview["subject"] == "Re: Kërkesë"

    async def test_report_matches_a_manual_email_heading_without_changing_its_body(self):
        note_id = uuid4()
        title = "EM GA: 09:50 STD-STAUD"
        url = "https://outlook.office.com/mail/deeplink/read/abc"
        content = f"{title}\nKontrollo dokumentet.\nEmail origjinal: {url}"
        values = ["1", "NO", f"{title} Kontrollo dokumentet.", "GA", "10:04"]
        sections = [{"title": SECTION_TITLES[3], "body": _notes_section([values])}]
        db = AsyncMock()
        db.execute.side_effect = [
            SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [])),
            SimpleNamespace(all=lambda: [(note_id, content)]),
        ]
        db.scalars.return_value = SimpleNamespace(all=lambda: [])
        controls = await section_note_controls(db, sections, SECTION_TITLES[3], {
            NOTE_REFERENCES: [[str(note_id), values]],
        })
        assert controls["note_email_headings"]["1"] == {
            "original": title, "title": "EM GA: 08:00 STD-STAUD", "original_email_url": url,
        }
        assert manual_original_email_url("Note\nEmail origjinal: javascript:alert(1)") is None
        assert manual_original_email_url("Note\nEmail origjinal: https://mail.google.com@example.test/") is None
        assert controls["note_emails"] == {}

    async def test_snapshot_uses_ids_and_hides_files_for_an_edited_row(self):
        note_ids = [uuid4(), uuid4()]
        files = [
            SimpleNamespace(id=uuid4(), note_id=note_id, original_filename=f"{index}.docx")
            for index, note_id in enumerate(note_ids, start=1)
        ]
        content = "Text long enough to wrap across multiple lines in the report notes table."
        values = [[str(index), "NO", content, "GA", "09:15"] for index in (1, 2)]
        snapshot = {NOTE_REFERENCES: [[str(note_id), row] for note_id, row in zip(note_ids, values)]}
        db = AsyncMock()
        db.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: files))

        async def attachments(rows):
            sections = [{"section_key": SECTION_TITLES[3], "title": "Edited title", "body": _notes_section(rows)}]
            return await section_note_attachments(db, sections, SECTION_TITLES[3], snapshot)

        self.assertEqual(await attachments(values), {
            str(index): [{"id": str(file.id), "original_filename": file.original_filename}]
            for index, file in enumerate(files, start=1)
        })
        self.assertEqual(await attachments([["1", "NO", "Edited note", "GA", "09:15"], values[1]]), {
            "2": [{"id": str(files[1].id), "original_filename": "2.docx"}],
        })

    async def test_legacy_matches_by_content_instead_of_order_and_skips_ambiguous_notes(self):
        valid_id = uuid4()
        file = SimpleNamespace(id=uuid4(), note_id=valid_id, original_filename="original.xlsx")
        values = [["1", "NO", "First note", "GA", "09:15"], ["2", "NO", "Duplicate note", "GA", "09:16"]]
        references = [
            (str(uuid4()), values[1]),
            (str(valid_id), ["3", *values[0][1:]]),
            (str(uuid4()), ["4", *values[1][1:]]),
        ]
        captured = datetime(2026, 11, 23, 9, tzinfo=timezone.utc)
        db = AsyncMock()
        db.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [file]))
        sections = [{"title": SECTION_TITLES[3], "body": _notes_section(values)}]
        with patch("app.services.report_note_attachments.load_blue_notes", AsyncMock(return_value=references)) as load:
            result = await section_note_attachments(db, sections, SECTION_TITLES[3], {
                "ga_replies_generated_at": captured.isoformat(),
            })
        load.assert_awaited_once_with(db, created_before=captured, compact_email=False)
        self.assertEqual(result, {"1": [{"id": str(file.id), "original_filename": "original.xlsx"}]})
