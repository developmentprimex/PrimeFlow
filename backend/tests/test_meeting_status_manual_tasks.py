from __future__ import annotations

import os
import unittest
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/primex_test")
os.environ.setdefault("JWT_SECRET", "test-secret")

from app.api.routers.meetings import update_meeting_occurrence_status
from app.models.meeting import Meeting
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.schemas.meeting import MeetingOccurrenceStatusUpdate


class TestMeetingStatusManualTasks(unittest.IsolatedAsyncioTestCase):
    async def test_meeting_status_never_completes_or_reopens_tasks(self):
        now = datetime.now(timezone.utc)
        day = date(2026, 10, 15)
        for link in ("external", "pre", "post"):
            for previous, status in (("", "held"), ("held", "canceled"), ("held", ""), ("canceled", "held")):
                with self.subTest(link=link, previous=previous, status=status):
                    external_id = uuid.uuid4()
                    meeting = Meeting(
                        id=external_id if link == "external" else uuid.uuid4(),
                        meeting_type="external" if link == "external" else "internal",
                        pre_external_meeting_id=external_id if link == "pre" else None,
                        paired_external_meeting_id=external_id if link == "post" else None,
                    )
                    row = MeetingOccurrenceStatus(
                        id=uuid.uuid4(), meeting_id=meeting.id, occurrence_date=day,
                        status=previous, created_at=now, updated_at=now,
                    )
                    async def execute(statement):
                        # Any task query by the status endpoint is a regression.
                        table = statement.column_descriptions[0]["entity"]
                        self.assertIn(table, (Meeting, MeetingOccurrenceStatus))
                        result = Mock()
                        result.scalar_one_or_none.return_value = meeting if table is Meeting else row
                        return result

                    db = AsyncMock()
                    db.execute.side_effect = execute
                    with patch("app.api.routers.meetings.delete_external_meeting_dependents", new_callable=AsyncMock) as cleanup, patch(
                        "app.api.routers.meetings.delete_internal_meeting_tasks", new_callable=AsyncMock
                    ) as internal_cleanup:
                        result = await update_meeting_occurrence_status(
                            meeting.id, MeetingOccurrenceStatusUpdate(occurrence_date=day, status=status),
                            db=db, user=SimpleNamespace(id=uuid.uuid4()),
                        )
                        if link == "external" and status == "canceled":
                            cleanup.assert_awaited_once_with(db, meeting)
                        else:
                            cleanup.assert_not_awaited()
                        if link != "external" and status == "canceled":
                            internal_cleanup.assert_awaited_once_with(db, meeting, day)
                        else:
                            internal_cleanup.assert_not_awaited()
                    self.assertEqual(result.status, status)
                    self.assertEqual(db.execute.await_count, 2)
                    db.commit.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
