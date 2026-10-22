from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

from app.services.meeting_system_tasks import (
    TAK_INT_POST_ONE_H_TASK_KIND,
    TAK_INT_PRE_ONE_H_TASK_KIND,
    _reconcile_tak_int_one_h_task_kind,
    qualifies_for_tak_int_one_h_tasks,
    reconcile_tak_int_one_h_tasks_for_meeting,
    tak_int_post_one_h_slot,
    tak_int_pre_one_h_slot,
)
from app.models.task import Task
from app.models.enums import TaskStatus

TZ = ZoneInfo("Europe/Budapest")


def _meeting(start: datetime, end: datetime | None = None, **extra) -> SimpleNamespace:
    values = {
        "meeting_type": "external",
        "recurrence_type": None,
        "calendar_sync_status": None,
        "starts_at": start,
        "ends_at": end,
    }
    values.update(extra)
    return SimpleNamespace(**values)


@patch("app.services.meeting_system_tasks.settings.APP_TIMEZONE", "Europe/Budapest")
class TestTakIntOneHSlots(unittest.TestCase):
    def test_pre_slot_is_last_slot_before_meeting(self) -> None:
        meeting = _meeting(datetime(2026, 10, 6, 13, 0, tzinfo=TZ))
        self.assertEqual(tak_int_pre_one_h_slot(meeting), (date(2026, 10, 6), "11:50"))

    def test_pre_slot_is_strictly_before_start(self) -> None:
        meeting = _meeting(datetime(2026, 10, 6, 11, 50, tzinfo=TZ))
        self.assertEqual(tak_int_pre_one_h_slot(meeting), (date(2026, 10, 6), "11:00"))

    def test_early_meeting_uses_previous_workday_last_slot(self) -> None:
        meeting = _meeting(datetime(2026, 10, 5, 8, 0, tzinfo=TZ))  # Monday
        self.assertEqual(tak_int_pre_one_h_slot(meeting), (date(2026, 10, 2), "16:00"))

    def test_post_slot_is_first_slot_after_meeting_ends(self) -> None:
        meeting = _meeting(datetime(2026, 10, 6, 13, 0, tzinfo=TZ), datetime(2026, 10, 6, 13, 30, tzinfo=TZ))
        self.assertEqual(tak_int_post_one_h_slot(meeting), (date(2026, 10, 6), "14:20"))

    def test_post_slot_is_the_slot_the_tak_int_falls_in(self) -> None:
        meeting = _meeting(datetime(2026, 10, 6, 13, 0, tzinfo=TZ))
        internal = SimpleNamespace(starts_at=datetime(2026, 10, 6, 14, 30, tzinfo=TZ))
        self.assertEqual(tak_int_post_one_h_slot(meeting, internal), (date(2026, 10, 6), "14:20"))

    def test_post_slot_for_tak_int_on_the_1550_slot(self) -> None:
        meeting = _meeting(datetime(2026, 10, 6, 14, 0, tzinfo=TZ), datetime(2026, 10, 6, 15, 0, tzinfo=TZ))
        internal = SimpleNamespace(starts_at=datetime(2026, 10, 6, 15, 50, tzinfo=TZ))
        self.assertEqual(tak_int_post_one_h_slot(meeting, internal), (date(2026, 10, 6), "16:00"))

    def test_pre_slot_for_meeting_at_1600_is_the_1600_row(self) -> None:
        meeting = _meeting(datetime(2026, 10, 6, 16, 0, tzinfo=TZ))
        self.assertEqual(tak_int_pre_one_h_slot(meeting), (date(2026, 10, 6), "16:00"))

    def test_post_slot_defaults_to_one_hour_meeting(self) -> None:
        meeting = _meeting(datetime(2026, 10, 6, 9, 0, tzinfo=TZ))
        self.assertEqual(tak_int_post_one_h_slot(meeting), (date(2026, 10, 6), "10:00"))

    def test_late_meeting_post_slot_moves_to_next_workday(self) -> None:
        meeting = _meeting(datetime(2026, 10, 9, 15, 30, tzinfo=TZ))  # Friday, ends 16:30
        self.assertEqual(tak_int_post_one_h_slot(meeting), (date(2026, 10, 12), "10:00"))

    def test_qualification(self) -> None:
        start = datetime(2026, 10, 6, 13, 0, tzinfo=TZ)
        self.assertTrue(qualifies_for_tak_int_one_h_tasks(_meeting(start)))
        self.assertFalse(qualifies_for_tak_int_one_h_tasks(_meeting(start, meeting_type="internal")))
        self.assertFalse(qualifies_for_tak_int_one_h_tasks(_meeting(start, recurrence_type="weekly")))
        self.assertFalse(qualifies_for_tak_int_one_h_tasks(_meeting(start, calendar_sync_status="cancelled")))


@patch("app.services.meeting_system_tasks.settings.APP_TIMEZONE", "Europe/Budapest")
class TestTakIntOneHReconciliation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        cancellation = patch("app.services.meeting_system_tasks.external_meeting_is_canceled", new_callable=AsyncMock, return_value=False)
        cancellation.start()
        self.addCleanup(cancellation.stop)
        internal_cancellation = patch("app.services.meeting_system_tasks.internal_meeting_task_is_canceled", new_callable=AsyncMock, return_value=False)
        self.internal_cancellation = internal_cancellation.start()
        self.addCleanup(internal_cancellation.stop)

    async def test_weekly_category_creates_only_post_tasks_and_regular_meeting_keeps_both(self) -> None:
        for categories, expects_pre in ((["Weekly"], False), (["Team WEEKLY"], False), (["Online"], True)):
            with self.subTest(categories=categories):
                external = _meeting(
                    datetime(2026, 10, 15, 13, 0, tzinfo=TZ),
                    id=uuid.uuid4(), title="Team meeting", calendar_categories=categories,
                )
                participant_id = uuid.uuid4()
                internal = SimpleNamespace(starts_at=datetime(2026, 10, 15, 14, 20, tzinfo=TZ))
                with (
                    patch("app.services.meeting_system_tasks._resolve_external_meeting", new=AsyncMock(return_value=external)),
                    patch("app.services.meeting_system_tasks.manual_participant_ids", new=AsyncMock(return_value={external.id: [participant_id]})),
                    patch("app.services.meeting_system_tasks._post_internal_meeting", new=AsyncMock(return_value=internal)),
                    patch("app.services.meeting_system_tasks._reconcile_tak_int_one_h_task_kind", new=AsyncMock(return_value=0)) as reconcile,
                ):
                    await reconcile_tak_int_one_h_tasks_for_meeting(AsyncMock(), external)

                pre, post = reconcile.await_args_list
                self.assertEqual(pre.kwargs["task_kind"], TAK_INT_PRE_ONE_H_TASK_KIND)
                self.assertEqual(pre.kwargs["slot"] is not None, expects_pre)
                self.assertEqual(post.kwargs["task_kind"], TAK_INT_POST_ONE_H_TASK_KIND)
                self.assertEqual(post.kwargs["slot"], (date(2026, 10, 15), "14:20"))
                self.assertEqual(post.kwargs["participant_ids"], [participant_id])

    async def test_canceled_internal_task_kind_is_not_recreated(self) -> None:
        external = _meeting(datetime(2026, 10, 22, 13, 0, tzinfo=TZ),
            id=uuid.uuid4(), title="Customer meeting", calendar_categories=[])
        internal = SimpleNamespace(starts_at=datetime(2026, 10, 22, 14, 20, tzinfo=TZ))
        for canceled_kind in (TAK_INT_PRE_ONE_H_TASK_KIND, TAK_INT_POST_ONE_H_TASK_KIND):
            with self.subTest(canceled_kind=canceled_kind):
                self.internal_cancellation.side_effect = lambda db, external_id, kind, day: kind == canceled_kind
                with (
                    patch("app.services.meeting_system_tasks.manual_participant_ids", new=AsyncMock(return_value={external.id: [uuid.uuid4()]})),
                    patch("app.services.meeting_system_tasks._post_internal_meeting", new=AsyncMock(return_value=internal)),
                    patch("app.services.meeting_system_tasks._reconcile_tak_int_one_h_task_kind", new=AsyncMock(return_value=0)) as reconcile,
                ):
                    await reconcile_tak_int_one_h_tasks_for_meeting(AsyncMock(), external)
                reconcile.assert_awaited_once()
                self.assertNotEqual(reconcile.await_args.kwargs["task_kind"], canceled_kind)

    async def test_unneeded_preparation_deactivates_open_tasks_and_preserves_completed_tasks(self) -> None:
        participant_id = uuid.uuid4()
        tasks = [
            Task(id=uuid.uuid4(), assigned_to=participant_id, status=status, is_active=True)
            for status in (TaskStatus.TODO.value, TaskStatus.DONE.value)
        ]
        result = Mock()
        result.scalars.return_value.all.return_value = tasks
        db = AsyncMock()
        db.execute.return_value = result
        await _reconcile_tak_int_one_h_task_kind(
            db, SimpleNamespace(id=uuid.uuid4()),
            task_kind=TAK_INT_PRE_ONE_H_TASK_KIND, task_title="Preparation",
            description="", slot=None, participant_ids=[participant_id],
            now_utc=datetime(2026, 10, 15, 8, 0, tzinfo=TZ),
        )
        self.assertFalse(tasks[0].is_active)
        self.assertTrue(tasks[1].is_active)
        self.assertEqual(db.execute.await_count, 1)


if __name__ == "__main__":
    unittest.main()
