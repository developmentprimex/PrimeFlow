import tempfile
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.api.routers import ga_notes


def upload(filename, content, media_type):
    return UploadFile(BytesIO(content), filename=filename, headers=Headers({"content-type": media_type}))


class AttachmentStorageTests(IsolatedAsyncioTestCase):
    async def test_upload_can_be_previewed_and_downloaded_from_a_second_backend(self):
        owner = SimpleNamespace(id=uuid.uuid4())
        note = ga_notes.GaNote(id=uuid.uuid4(), content="Preview storage test")
        contents = b"test image bytes"
        records = []

        def add(record):
            record.created_at = datetime.now(timezone.utc)
            record.note = note
            records.append(record)

        writer_db = SimpleNamespace(add=add, flush=AsyncMock(), execute=AsyncMock(),
                                    commit=AsyncMock(), rollback=AsyncMock())
        with tempfile.TemporaryDirectory() as writer_dir, tempfile.TemporaryDirectory() as reader_dir:
            with patch.object(ga_notes.settings, "GA_NOTES_UPLOAD_DIR", writer_dir):
                uploaded = await ga_notes._save_ga_note_attachments(
                    note, [upload("example.jpg", contents, "image/jpeg")], writer_db, owner,
                )
            writer_db.commit.assert_awaited_once()
            writer_db.rollback.assert_not_awaited()
            record = records[0]
            self.assertEqual(uploaded[0].id, record.id)
            self.assertEqual((Path(writer_dir) / str(note.id) / record.stored_filename).read_bytes(), contents)
            saved = writer_db.execute.call_args.args[0].compile().params
            self.assertEqual(saved, {"attachment_id": record.id, "data": contents})

            reader_db = SimpleNamespace(
                execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: record)),
                scalar=AsyncMock(return_value=saved["data"]),
            )
            with patch.object(ga_notes.settings, "GA_NOTES_UPLOAD_DIR", reader_dir):
                preview = await ga_notes.preview_ga_note_attachment(record.id, reader_db, owner)
                self.assertEqual(preview.media_type, "image/jpeg")
                self.assertEqual(await self.response_body(preview), contents)
                self.assertFalse(Path(preview.path).exists())

                download = await ga_notes.download_ga_note_attachment(record.id, reader_db, owner)
                self.assertIn('filename="example.jpg"', download.headers["content-disposition"])
                self.assertEqual(await self.response_body(download, [(b"range", b"bytes=0-3")]), contents[:4])
                self.assertFalse(Path(download.path).exists())

    async def test_legacy_disk_file_still_opens_without_shared_content(self):
        attachment = SimpleNamespace(id=uuid.uuid4(), note_id=uuid.uuid4(), stored_filename="legacy.txt", size_bytes=3)
        db = SimpleNamespace(scalar=AsyncMock())
        with tempfile.TemporaryDirectory() as legacy_dir, patch.object(ga_notes.settings, "GA_NOTES_UPLOAD_DIR", legacy_dir):
            legacy_file = Path(legacy_dir) / str(attachment.note_id) / attachment.stored_filename
            legacy_file.parent.mkdir()
            legacy_file.write_bytes(b"old")
            path, temporary = await ga_notes._open_ga_note_attachment(db, attachment)
            self.assertEqual(path, legacy_file)
            self.assertIsNone(temporary)
        db.scalar.assert_not_awaited()

    async def test_failed_batch_rolls_back_shared_writes_and_removes_local_copies(self):
        db = SimpleNamespace(add=Mock(), flush=AsyncMock(), execute=AsyncMock(side_effect=[None, RuntimeError("write failed")]),
                             commit=AsyncMock(), rollback=AsyncMock())
        note = SimpleNamespace(id=uuid.uuid4())
        with tempfile.TemporaryDirectory() as root, patch.object(ga_notes.settings, "GA_NOTES_UPLOAD_DIR", root):
            with self.assertRaises(RuntimeError):
                await ga_notes._save_ga_note_attachments(
                    note, [upload("one.txt", b"one", "text/plain"), upload("two.txt", b"two", "text/plain")],
                    db, SimpleNamespace(id=uuid.uuid4()),
                )
            self.assertEqual(list((Path(root) / str(note.id)).iterdir()), [])
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()

    async def test_missing_file_in_both_locations_returns_not_found(self):
        attachment = SimpleNamespace(id=uuid.uuid4(), note_id=uuid.uuid4(), stored_filename="missing.jpg", size_bytes=17)
        with tempfile.TemporaryDirectory() as root, patch.object(ga_notes.settings, "GA_NOTES_UPLOAD_DIR", root):
            with self.assertRaises(HTTPException) as error:
                await ga_notes._open_ga_note_attachment(SimpleNamespace(scalar=AsyncMock(return_value=None)), attachment)
        self.assertEqual(error.exception.status_code, 404)

    async def response_body(self, response, headers=None):
        messages = []

        async def send(message):
            messages.append(message)

        await response({"type": "http", "method": "GET", "headers": headers or []}, AsyncMock(), send)
        return b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
