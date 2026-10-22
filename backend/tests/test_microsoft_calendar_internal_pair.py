from __future__ import annotations

import os
import unittest
import uuid
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/primex_test")
os.environ.setdefault("JWT_SECRET", "test-secret")

from app.models.meeting import Meeting, MeetingParticipant
from app.services.microsoft_calendar_sync import (
    calendar_follow_up_start,
    calendar_preparation_start,
    ensure_calendar_internal_pair,
    ensure_calendar_preparation_pair,
    is_routine_external_meeting,
    sync_external_calendar_events,
    sync_calendar_internal_pair_status,
)


class _ListResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def scalars(self) -> _ListResult:
        return self

    def all(self) -> list[object]:
        return self.values


class _FakeDb:
    def __init__(self, execute_results: list[list[object]] | None = None) -> None:
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.execute_results = list(execute_results or [])
        self.commit_count = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid.uuid4()

    async def execute(self, _statement: object) -> _ListResult:
        return _ListResult(self.execute_results.pop(0))

    async def delete(self, value: object) -> None:
        self.deleted.append(value)

    async def commit(self) -> None:
        self.commit_count += 1


class TestMicrosoftCalendarInternalPair(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        cancellation = patch("app.services.microsoft_calendar_sync.external_meeting_is_canceled", new_callable=AsyncMock, return_value=False)
        self.cancellation = cancellation.start()
        self.addCleanup(cancellation.stop)

    async def test_sync_does_not_recreate_pairs_after_common_view_cancellation(self):
        self.cancellation.return_value = True
        department = SimpleNamespace(id=uuid.uuid4(), code="DEV", name="Development")
        db = _FakeDb(execute_results=[[], [department], []])
        event = {
            "id": "canceled-in-common-view", "subject": "Customer review",
            "start": {"dateTime": "2026-09-08T10:00:00Z"},
            "end": {"dateTime": "2026-09-08T11:00:00Z"},
        }
        with patch("app.services.microsoft_calendar_sync.fetch_calendar_events", new=AsyncMock(return_value=[event])):
            await sync_external_calendar_events(db, access_token="mock", connected_by_user_id=uuid.uuid4(),
                start=datetime(2026, 9, 8, tzinfo=timezone.utc), end=datetime(2026, 9, 9, tzinfo=timezone.utc))
        meetings = [row for row in db.added if isinstance(row, Meeting)]
        self.assertEqual(len(meetings), 1)
        self.assertEqual(meetings[0].meeting_type, "external")
        self.cancellation.assert_awaited_once()

    async def test_calendar_sync_creates_external_before_and_after_meetings(self) -> None:
        participant_id = uuid.uuid4()
        department_id = uuid.uuid4()
        user = SimpleNamespace(
            id=participant_id,
            email="person@primexeu.com",
            department_id=department_id,
            is_active=True,
        )
        department = SimpleNamespace(id=department_id, code="DEV", name="Development")
        db = _FakeDb(execute_results=[[user], [department], []])
        event = {
            "id": "microsoft-event-1",
            "changeKey": "change-1",
            "createdDateTime": "2026-09-08T07:00:00Z",
            "subject": "Customer review",
            "start": {"dateTime": "2026-09-08T10:00:00Z"},
            "end": {"dateTime": "2026-09-08T11:00:00Z"},
            "location": {"displayName": "Teams"},
            "attendees": [{"emailAddress": {"address": user.email}}],
        }

        with patch(
            "app.services.microsoft_calendar_sync.fetch_calendar_events",
            new=AsyncMock(return_value=[event]),
        ):
            result = await sync_external_calendar_events(
                db,
                access_token="not-used-by-mock",
                connected_by_user_id=uuid.uuid4(),
                start=datetime(2026, 9, 8, tzinfo=timezone.utc),
                end=datetime(2026, 9, 9, tzinfo=timezone.utc),
            )

        meetings = [row for row in db.added if isinstance(row, Meeting)]
        external = next(row for row in meetings if row.meeting_type == "external")
        after = next(row for row in meetings if row.paired_external_meeting_id == external.id)
        before = next(row for row in meetings if row.pre_external_meeting_id == external.id)
        local_timezone = ZoneInfo("Europe/Budapest")

        self.assertEqual(result.created, 1)
        self.assertEqual(len(meetings), 3)
        self.assertEqual(after.starts_at.astimezone(local_timezone).time(), time(14, 20))
        self.assertEqual(before.starts_at.astimezone(local_timezone).time(), time(10, 15))
        self.assertEqual(db.commit_count, 1)

    async def test_brown_routine_external_meeting_creates_only_follow_up_pair(self) -> None:
        department_id = uuid.uuid4()
        department = SimpleNamespace(id=department_id, code="DEV", name="Development")
        db = _FakeDb(execute_results=[[], [department], []])
        event = {
            "id": "routine-weekly-event",
            "changeKey": "change-1",
            "createdDateTime": "2026-09-08T07:00:00Z",
            "subject": "Weekly team meeting",
            "categories": ["Weekly"],
            "start": {"dateTime": "2026-09-09T11:30:00Z"},
            "end": {"dateTime": "2026-09-09T12:00:00Z"},
        }

        with patch(
            "app.services.microsoft_calendar_sync.fetch_calendar_events",
            new=AsyncMock(return_value=[event]),
        ):
            await sync_external_calendar_events(
                db,
                access_token="not-used-by-mock",
                connected_by_user_id=uuid.uuid4(),
                start=datetime(2026, 9, 9, tzinfo=timezone.utc),
                end=datetime(2026, 9, 10, tzinfo=timezone.utc),
            )

        meetings = [row for row in db.added if isinstance(row, Meeting)]
        self.assertEqual(len(meetings), 2)
        external = next(row for row in meetings if row.meeting_type == "external")
        follow_up = next(row for row in meetings if row.meeting_type == "internal")
        self.assertEqual(follow_up.paired_external_meeting_id, external.id)
        self.assertIsNone(follow_up.pre_external_meeting_id)

    async def test_only_existing_preparation_pair_is_deleted_when_external_becomes_brown(self) -> None:
        department_id = uuid.uuid4()
        external = Meeting(
            id=uuid.uuid4(),
            title="Weekly team meeting",
            starts_at=datetime(2026, 9, 9, 11, 30, tzinfo=timezone.utc),
            ends_at=datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc),
            microsoft_event_id="routine-weekly-event",
            meeting_type="external",
            department_id=department_id,
            created_by=uuid.uuid4(),
            calendar_imported=True,
            calendar_sync_status="active",
            calendar_change_key="old-change",
        )
        after = Meeting(
            id=uuid.uuid4(),
            title=external.title,
            starts_at=datetime(2026, 9, 9, 12, 20, tzinfo=timezone.utc),
            meeting_type="internal",
            department_id=department_id,
            created_by=external.created_by,
            paired_external_meeting_id=external.id,
            calendar_sync_status="active",
        )
        before = Meeting(
            id=uuid.uuid4(),
            title=external.title,
            starts_at=datetime(2026, 9, 9, 6, 20, tzinfo=timezone.utc),
            meeting_type="internal",
            department_id=department_id,
            created_by=external.created_by,
            pre_external_meeting_id=external.id,
            calendar_sync_status="active",
        )
        department = SimpleNamespace(id=department_id, code="DEV", name="Development")
        db = _FakeDb(execute_results=[[], [department], [external], [after], [before], []])
        event = {
            "id": external.microsoft_event_id,
            "changeKey": "new-change",
            "subject": external.title,
            "categories": ["Brown"],
            "start": {"dateTime": "2026-09-09T11:30:00Z"},
            "end": {"dateTime": "2026-09-09T12:00:00Z"},
        }

        with patch(
            "app.services.microsoft_calendar_sync.fetch_calendar_events",
            new=AsyncMock(return_value=[event]),
        ):
            await sync_external_calendar_events(
                db,
                access_token="not-used-by-mock",
                connected_by_user_id=external.created_by,
                start=datetime(2026, 9, 9, tzinfo=timezone.utc),
                end=datetime(2026, 9, 10, tzinfo=timezone.utc),
            )

        self.assertEqual(db.deleted, [before])
        self.assertEqual(after.calendar_sync_status, "active")
        self.assertEqual([row for row in db.added if isinstance(row, Meeting)], [])

    async def test_creates_one_internal_meeting_in_the_next_one_h_slot_and_reuses_it(self) -> None:
        external_id = uuid.uuid4()
        participant_id = uuid.uuid4()
        starts_at = datetime(2026, 9, 8, 9, 30, tzinfo=timezone.utc)
        synced_at = datetime(2026, 9, 8, 8, 0, tzinfo=timezone.utc)
        external = Meeting(
            id=external_id,
            title="Microsoft customer meeting",
            platform="TEAMS",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=30),
            meeting_url="https://teams.example/join",
            meeting_type="external",
            department_id=uuid.uuid4(),
            created_by=uuid.uuid4(),
            calendar_imported=True,
            calendar_sync_status="active",
        )
        db = _FakeDb()
        pairs: dict[object, Meeting] = {}
        participant_map = {external.id: {participant_id}}

        internal = await ensure_calendar_internal_pair(
            db,
            external_meeting=external,
            participant_ids=participant_map[external.id],
            paired_by_external_id=pairs,
            participant_ids_by_meeting=participant_map,
            synced_at=synced_at,
        )

        self.assertEqual(internal.meeting_type, "internal")
        self.assertEqual(internal.paired_external_meeting_id, external.id)
        self.assertEqual(
            internal.starts_at.astimezone(ZoneInfo("Europe/Budapest")).time(),
            time(14, 20),
        )
        self.assertIsNone(internal.ends_at)
        self.assertFalse(internal.calendar_imported)
        self.assertEqual(internal.calendar_sync_status, "active")
        participants = [row for row in db.added if isinstance(row, MeetingParticipant)]
        self.assertEqual(len(participants), 1)
        self.assertEqual(participants[0].meeting_id, internal.id)
        self.assertEqual(participants[0].user_id, participant_id)

        external.title = "Updated Microsoft meeting"
        external.starts_at = starts_at + timedelta(hours=2)
        same_internal = await ensure_calendar_internal_pair(
            db,
            external_meeting=external,
            participant_ids=participant_map[external.id],
            paired_by_external_id=pairs,
            participant_ids_by_meeting=participant_map,
            synced_at=synced_at,
        )

        self.assertIs(same_internal, internal)
        self.assertEqual(internal.title, "Updated Microsoft meeting")
        self.assertEqual(
            internal.starts_at.astimezone(ZoneInfo("Europe/Budapest")).time(),
            time(14, 20),
        )
        self.assertEqual(len([row for row in db.added if isinstance(row, Meeting)]), 1)
        self.assertEqual(len([row for row in db.added if isinstance(row, MeetingParticipant)]), 1)

        external.calendar_sync_status = "cancelled"
        sync_calendar_internal_pair_status(external, pairs, synced_at=synced_at)
        self.assertEqual(internal.calendar_sync_status, "cancelled")

    async def test_creates_a_distinct_preparation_meeting(self) -> None:
        external = Meeting(
            id=uuid.uuid4(),
            title="Microsoft customer meeting",
            platform="TEAMS",
            starts_at=datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc),
            meeting_type="external",
            department_id=uuid.uuid4(),
            created_by=uuid.uuid4(),
            calendar_imported=True,
            calendar_sync_status="active",
        )
        participant_id = uuid.uuid4()
        preparation_start = datetime(2026, 9, 8, 8, 15, tzinfo=timezone.utc)
        db = _FakeDb()
        pairs: dict[object, Meeting] = {}
        participant_map = {external.id: {participant_id}}

        preparation = await ensure_calendar_preparation_pair(
            db,
            external_meeting=external,
            starts_at=preparation_start,
            participant_ids=participant_map[external.id],
            paired_by_external_id=pairs,
            participant_ids_by_meeting=participant_map,
            synced_at=datetime.now(timezone.utc),
        )

        self.assertEqual(preparation.meeting_type, "internal")
        self.assertEqual(preparation.pre_external_meeting_id, external.id)
        self.assertIsNone(preparation.paired_external_meeting_id)
        self.assertEqual(preparation.starts_at, preparation_start)


class TestCalendarPreparationSchedule(unittest.TestCase):
    timezone = ZoneInfo("Europe/Budapest")

    def local_datetime(self, day: int, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 9, day, hour, minute, tzinfo=self.timezone)

    def test_same_day_meeting_is_two_hours_earlier_and_skips_one_h_slot(self) -> None:
        result = calendar_preparation_start(
            self.local_datetime(8, 12),
            self.local_datetime(8, 9),
        ).astimezone(self.timezone)

        self.assertEqual(result.time(), time(10, 15))

    def test_same_day_early_meeting_uses_0815_floor(self) -> None:
        result = calendar_preparation_start(
            self.local_datetime(8, 9),
            self.local_datetime(8, 7),
        ).astimezone(self.timezone)

        self.assertEqual(result.time(), time(8, 15))

    def test_0800_meeting_uses_previous_workday_at_1600(self) -> None:
        result = calendar_preparation_start(
            self.local_datetime(14, 8),
            self.local_datetime(10, 9),
        ).astimezone(self.timezone)

        self.assertEqual(result.date(), self.local_datetime(11, 16).date())
        self.assertEqual(result.time(), time(16, 0))

    def test_0800_meeting_uses_0800_when_previous_workday_slot_has_passed(self) -> None:
        result = calendar_preparation_start(
            self.local_datetime(14, 8),
            self.local_datetime(11, 17),
        ).astimezone(self.timezone)

        self.assertEqual(result.date(), self.local_datetime(14, 8).date())
        self.assertEqual(result.time(), time(8, 0))

    def test_advance_meetings_start_at_0815_and_continue_every_15_minutes(self) -> None:
        external_start = self.local_datetime(10, 12)
        created_at = self.local_datetime(8, 9)
        first = calendar_preparation_start(external_start, created_at)
        second = calendar_preparation_start(
            external_start + timedelta(hours=1),
            created_at,
            reserved_starts={first},
        )

        self.assertEqual(first.astimezone(self.timezone).time(), time(8, 15))
        self.assertEqual(second.astimezone(self.timezone).time(), time(8, 30))
        self.assertEqual(first.astimezone(self.timezone).date(), self.local_datetime(9, 8).date())
        self.assertEqual(second.astimezone(self.timezone).date(), self.local_datetime(9, 8).date())

    def test_advance_monday_meeting_prepares_on_friday(self) -> None:
        result = calendar_preparation_start(
            self.local_datetime(14, 10),
            self.local_datetime(10, 9),
        ).astimezone(self.timezone)

        self.assertEqual(result.date(), self.local_datetime(11, 8).date())
        self.assertEqual(result.time(), time(8, 15))

    def test_multiple_0800_meetings_share_the_0800_fallback_slot(self) -> None:
        external_start = self.local_datetime(14, 8)
        created_at = self.local_datetime(11, 17)
        first = calendar_preparation_start(external_start, created_at)
        second = calendar_preparation_start(
            external_start,
            created_at,
            reserved_starts={first},
        )

        self.assertEqual(first.astimezone(self.timezone).time(), time(8, 0))
        self.assertEqual(second.astimezone(self.timezone).time(), time(8, 0))

    def test_created_at_noon_prepares_today_after_break(self) -> None:
        result = calendar_preparation_start(
            self.local_datetime(10, 16),
            self.local_datetime(9, 12),
        ).astimezone(self.timezone)

        self.assertEqual(result, self.local_datetime(9, 13, 15))

    def test_late_creation_rounds_forward_and_respects_reserved_slots(self) -> None:
        result = calendar_preparation_start(
            self.local_datetime(10, 16),
            self.local_datetime(9, 10, 2),
            reserved_starts={self.local_datetime(9, 10, 15).astimezone(timezone.utc)},
        ).astimezone(self.timezone)

        self.assertEqual(result, self.local_datetime(9, 10, 30))

    def test_creation_at_end_of_day_prepares_next_workday(self) -> None:
        result = calendar_preparation_start(
            self.local_datetime(10, 16),
            self.local_datetime(9, 16, 30),
        ).astimezone(self.timezone)

        self.assertEqual(result, self.local_datetime(10, 8, 15))

    def test_same_day_creation_never_prepares_before_creation(self) -> None:
        result = calendar_preparation_start(
            self.local_datetime(9, 16),
            self.local_datetime(9, 15),
        ).astimezone(self.timezone)

        self.assertEqual(result, self.local_datetime(9, 15, 15))

    def test_later_meeting_uses_0815_after_an_0800_preparation(self) -> None:
        result = calendar_preparation_start(
            self.local_datetime(14, 10),
            self.local_datetime(11, 17),
            reserved_starts={self.local_datetime(14, 8).astimezone(timezone.utc)},
        ).astimezone(self.timezone)

        self.assertEqual(result.time(), time(8, 15))

    def test_advance_sequence_skips_an_official_one_h_slot(self) -> None:
        external_start = self.local_datetime(10, 15)
        created_at = self.local_datetime(8, 9)
        reserved = {
            self.local_datetime(9, 8, 20).astimezone(timezone.utc)
            + timedelta(minutes=15 * index)
            for index in range(14)
        }

        result = calendar_preparation_start(
            external_start,
            created_at,
            reserved_starts=reserved,
        ).astimezone(self.timezone)

        self.assertEqual(result.time(), time(13, 15))

    def test_preparation_meeting_skips_the_midday_break(self) -> None:
        result = calendar_preparation_start(
            self.local_datetime(8, 14),
            self.local_datetime(8, 9),
        ).astimezone(self.timezone)

        self.assertEqual(result.time(), time(13, 15))

    def test_preparation_after_1630_moves_to_next_working_morning(self) -> None:
        result = calendar_preparation_start(
            self.local_datetime(11, 19),
            self.local_datetime(11, 9),
        ).astimezone(self.timezone)

        self.assertEqual(result.date(), self.local_datetime(14, 8, 15).date())
        self.assertEqual(result.time(), time(8, 15))


class TestRoutineExternalMeeting(unittest.TestCase):
    def test_matches_the_same_categories_as_the_brown_common_view_tone(self) -> None:
        for category in ("Weekly", "DAILY", "Team standup", "Brown category"):
            with self.subTest(category=category):
                self.assertTrue(is_routine_external_meeting([category]))

    def test_regular_red_external_meeting_is_not_routine(self) -> None:
        self.assertFalse(is_routine_external_meeting(["Online"]))
        self.assertFalse(is_routine_external_meeting([]))


class TestCalendarFollowUpSchedule(unittest.TestCase):
    timezone = ZoneInfo("Europe/Budapest")

    def local_datetime(self, day: int, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 9, day, hour, minute, tzinfo=self.timezone)

    def follow_up_time(self, end_hour: int, end_minute: int = 0) -> time:
        starts_at = self.local_datetime(8, max(end_hour - 1, 0), end_minute)
        ends_at = self.local_datetime(8, end_hour, end_minute)
        return calendar_follow_up_start(starts_at, ends_at).astimezone(self.timezone).time()

    def test_selects_the_next_official_one_h_slot(self) -> None:
        self.assertEqual(self.follow_up_time(8, 45), time(9, 0))
        self.assertEqual(self.follow_up_time(9, 1), time(10, 0))
        self.assertEqual(self.follow_up_time(11, 30), time(11, 50))
        self.assertEqual(self.follow_up_time(12, 30), time(14, 20))
        self.assertEqual(self.follow_up_time(15, 30), time(15, 50))

    def test_exact_slot_is_allowed_when_external_meeting_ends_then(self) -> None:
        self.assertEqual(self.follow_up_time(11, 0), time(11, 0))

    def test_after_last_slot_moves_to_next_working_day_at_0900(self) -> None:
        starts_at = self.local_datetime(11, 15)
        ends_at = self.local_datetime(11, 16)
        result = calendar_follow_up_start(starts_at, ends_at).astimezone(self.timezone)

        self.assertEqual(result.date(), self.local_datetime(14, 9).date())
        self.assertEqual(result.time(), time(9, 0))


if __name__ == "__main__":
    unittest.main()
