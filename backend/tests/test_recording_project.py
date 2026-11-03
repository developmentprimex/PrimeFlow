import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from app.api.routers.meeting_recordings import update_recording, validate_project
from app.schemas.meeting_recording import RecordingCreate, RecordingUpdate


class RecordingProjectTests(unittest.IsolatedAsyncioTestCase):
    async def test_assignment_unlink_and_title_only_edit(self):
        project_id = uuid.uuid4()
        for payload, expected in [
            (RecordingUpdate(title="Title", project_id=project_id), project_id),
            (RecordingUpdate(title="Title", project_id=None), None),
            (RecordingUpdate(title="Title"), project_id),
        ]:
            row = SimpleNamespace(id=uuid.uuid4(), title="Old", project_id=project_id)
            result = Mock()
            result.scalar_one_or_none.return_value = row
            db = SimpleNamespace(execute=AsyncMock(return_value=result),
                                 scalar=AsyncMock(return_value=project_id),
                                 commit=AsyncMock(), refresh=AsyncMock())
            with patch("app.api.routers.meeting_recordings.audit"), patch(
                "app.api.routers.meeting_recordings.get_recording", AsyncMock(return_value=row)
            ):
                await update_recording(row.id, payload, db, SimpleNamespace(id=uuid.uuid4()))
            self.assertEqual(row.project_id, expected)
            db.commit.assert_awaited_once()

    async def test_missing_or_template_project_rejected(self):
        db = SimpleNamespace(scalar=AsyncMock(return_value=None))
        with self.assertRaises(HTTPException) as error:
            await validate_project(db, uuid.uuid4())
        self.assertEqual(error.exception.status_code, 404)
        self.assertIn("projects.is_template IS false", str(db.scalar.call_args.args[0]))
        db.scalar.reset_mock()
        await validate_project(db, None)
        db.scalar.assert_not_awaited()

    def test_creation_accepts_project(self):
        project_id = uuid.uuid4()
        payload = RecordingCreate(title="Recording", project_id=project_id,
                                  capture_source_type="monitor", mime_type="video/webm",
                                  consent_acknowledged=True)
        self.assertEqual(payload.project_id, project_id)
