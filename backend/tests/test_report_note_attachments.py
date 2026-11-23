from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.services.morning_report import SECTION_TITLES, _notes_section
from app.services.report_note_attachments import NOTE_REFERENCES, section_note_attachments


class ReportNoteAttachmentsTests(IsolatedAsyncioTestCase):
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
        load.assert_awaited_once_with(db, created_before=captured)
        self.assertEqual(result, {"1": [{"id": str(file.id), "original_filename": "original.xlsx"}]})
