import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routers.meeting_recordings import update_recording
from app.models.enums import UserRole
from app.schemas.meeting_recording import RecordingUpdate


class RecordingTitleTests(unittest.IsolatedAsyncioTestCase):
    def database(self, row):
        db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock(), refresh=AsyncMock())
        db.execute.return_value = Mock()
        db.execute.return_value.scalar_one_or_none.return_value = row
        return db

    async def test_creator_admin_and_manager_can_rename_with_audit(self):
        owner_id = uuid.uuid4()
        for role, user_id in ((UserRole.STAFF, owner_id), (UserRole.ADMIN, uuid.uuid4()),
                              (UserRole.MANAGER, uuid.uuid4())):
            row = SimpleNamespace(id=uuid.uuid4(), created_by=owner_id, title="Old title")
            user = SimpleNamespace(id=user_id, role=role)
            db = self.database(row)
            with patch("app.api.routers.meeting_recordings.audit") as audit, \
                    patch("app.api.routers.meeting_recordings.get_recording", new_callable=AsyncMock) as output:
                output.return_value = row
                result = await update_recording(row.id, RecordingUpdate(title="  Titulli i ri ë  "), db, user)
            self.assertEqual(result.title, "Titulli i ri ë")
            db.commit.assert_awaited_once()
            db.refresh.assert_awaited_once_with(row)
            audit.assert_called_once_with(db, user, row, "recording_title_updated",
                                          previous_title="Old title", title="Titulli i ri ë")
            query = str(db.execute.call_args.args[0])
            self.assertIn("deleted_at IS NULL", query)
            self.assertIn("FOR UPDATE", query)

    async def test_other_staff_cannot_rename(self):
        row = SimpleNamespace(id=uuid.uuid4(), created_by=uuid.uuid4(), title="Original")
        db = self.database(row)
        with self.assertRaises(HTTPException) as error:
            await update_recording(row.id, RecordingUpdate(title="Changed"), db,
                                   SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF))
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(row.title, "Original")
        db.commit.assert_not_awaited()

    async def test_missing_or_deleted_recording_is_not_editable(self):
        db = self.database(None)
        with self.assertRaises(HTTPException) as error:
            await update_recording(uuid.uuid4(), RecordingUpdate(title="Changed"), db,
                                   SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN))
        self.assertEqual(error.exception.status_code, 404)
        db.commit.assert_not_awaited()

    def test_title_validation(self):
        for title in ("", "   ", "\n\t", "x" * 201):
            with self.assertRaises(ValidationError):
                RecordingUpdate(title=title)
        self.assertEqual(RecordingUpdate(title="x" * 200).title, "x" * 200)
