import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from app.api.routers.meeting_recordings import create_recording
from app.models.enums import UserRole
from app.schemas.meeting_recording import RecordingCreate


class RecordingMeetingLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_role_can_link_another_users_meeting(self):
        for role in UserRole:
            meeting_id = uuid.uuid4()
            meeting = SimpleNamespace(id=meeting_id, created_by=uuid.uuid4())
            db = self.database(meeting)
            user = SimpleNamespace(id=uuid.uuid4(), role=role)
            with patch("app.api.routers.meeting_recordings.storage"), patch("app.api.routers.meeting_recordings.audit"):
                row = await create_recording(self.payload(meeting_id), db, user)
            self.assertEqual(row.meeting_id, meeting_id)
            self.assertEqual(row.created_by, user.id)
            query = str(db.execute.call_args.args[0])
            self.assertNotIn("created_by =", query)
            self.assertNotIn("meeting_participants", query)
            db.commit.assert_awaited_once()

    async def test_nonexistent_meeting_is_rejected(self):
        db = self.database(None)
        with patch("app.api.routers.meeting_recordings.storage"), self.assertRaises(HTTPException) as error:
            await create_recording(self.payload(uuid.uuid4()), db,
                                   SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF))
        self.assertEqual(error.exception.status_code, 404)
        db.commit.assert_not_awaited()

    def database(self, meeting):
        result = Mock()
        result.scalar_one_or_none.return_value = meeting
        return SimpleNamespace(execute=AsyncMock(return_value=result), scalar=AsyncMock(return_value=0),
                               add=Mock(), commit=AsyncMock(), refresh=AsyncMock())

    def payload(self, meeting_id):
        return RecordingCreate(title="Recording", meeting_id=meeting_id, capture_source_type="monitor",
                               mime_type="video/webm", consent_acknowledged=True)
