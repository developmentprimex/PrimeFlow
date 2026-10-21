from __future__ import annotations

import os
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/primex_test")
os.environ.setdefault("JWT_SECRET", "test-secret")

from sqlalchemy import Column, Date, MetaData, String, Table, Uuid, create_engine, select
from app.services.meeting_cancellation import delete_external_meeting_dependents, external_meeting_is_canceled
from app.services.meeting_system_tasks import (
    reconcile_agent_test_task_for_meeting, reconcile_pim_image_test_task_for_meeting,
    reconcile_tak_int_one_h_tasks_for_meeting,
)


class TestMeetingCancellation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        metadata = MetaData()
        self.meetings = Table("meetings", metadata,
            Column("id", Uuid, primary_key=True), Column("meeting_type", String),
            Column("pre_external_meeting_id", Uuid), Column("paired_external_meeting_id", Uuid))
        self.tasks = Table("tasks", metadata,
            Column("id", Uuid, primary_key=True), Column("meeting_origin_id", Uuid),
            Column("meeting_system_task_kind", String), Column("status", String))
        self.statuses = Table("meeting_occurrence_statuses", metadata,
            Column("id", Uuid, primary_key=True), Column("meeting_id", Uuid),
            Column("occurrence_date", Date), Column("status", String))
        metadata.create_all(self.engine)
        self.connection = self.engine.connect()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.connection.close)
        self.db = SimpleNamespace(execute=AsyncMock(side_effect=self.connection.execute))

    async def test_deletes_both_links_and_generated_tasks_on_other_days(self):
        external, pre, post, unrelated = [uuid.uuid4() for _ in range(4)]
        for meeting_id, before, after in ((external, None, None), (pre, external, None),
                                           (post, None, external), (unrelated, None, None)):
            self.connection.execute(self.meetings.insert().values(id=meeting_id,
                meeting_type="external" if meeting_id == external else "internal",
                pre_external_meeting_id=before, paired_external_meeting_id=after))
        retained = []
        for origin, kind, status in ((external, "tak_int_pre_one_h", "TODO"),
                (external, "tak_int_post_one_h", "DONE"), (pre, "generated", "TODO"),
                (post, "generated", "TODO"), (external, None, "TODO"),
                (unrelated, "tak_int_pre_one_h", "TODO")):
            task_id = uuid.uuid4()
            self.connection.execute(self.tasks.insert().values(id=task_id,
                meeting_origin_id=origin, meeting_system_task_kind=kind, status=status))
            if kind is None or origin == unrelated:
                retained.append(task_id)
        await delete_external_meeting_dependents(self.db, SimpleNamespace(id=external))
        self.assertEqual(set(self.connection.execute(select(self.meetings.c.id)).scalars()), {external, unrelated})
        self.assertEqual(set(self.connection.execute(select(self.tasks.c.id)).scalars()), set(retained))
        # Repeated cancellation is safe.
        await delete_external_meeting_dependents(self.db, SimpleNamespace(id=external))

    async def test_cancellation_query_uses_meeting_and_local_date(self):
        meeting = SimpleNamespace(id=uuid.uuid4(), meeting_type="external",
            starts_at=datetime(2026, 10, 21, 23, 30, tzinfo=timezone.utc), ends_at=None)
        from datetime import date
        with patch("app.services.meeting_cancellation.settings.APP_TIMEZONE", "Europe/Budapest"):
            self.assertFalse(await external_meeting_is_canceled(self.db, meeting))
            self.connection.execute(self.statuses.insert().values(id=uuid.uuid4(), meeting_id=meeting.id,
                occurrence_date=date(2026, 10, 21), status="canceled"))
            self.assertFalse(await external_meeting_is_canceled(self.db, meeting))
            self.connection.execute(self.statuses.insert().values(id=uuid.uuid4(), meeting_id=meeting.id,
                occurrence_date=date(2026, 10, 22), status="canceled"))
            self.assertTrue(await external_meeting_is_canceled(self.db, meeting))

    async def test_canceled_meeting_never_recreates_any_generated_task_kind(self):
        meeting = SimpleNamespace(id=uuid.uuid4(), meeting_type="external", recurrence_type=None,
            starts_at=datetime(2026, 10, 22, 10, tzinfo=timezone.utc),
            external_agent_test_task_requested=True, external_pim_image_test_task_requested=True)
        with patch("app.services.meeting_system_tasks.external_meeting_is_canceled", new_callable=AsyncMock, return_value=True):
            for reconcile in (reconcile_agent_test_task_for_meeting, reconcile_pim_image_test_task_for_meeting,
                              reconcile_tak_int_one_h_tasks_for_meeting):
                self.assertEqual(await reconcile(self.db, meeting), 0)
        self.db.execute.assert_not_awaited()
