from __future__ import annotations

import unittest
import uuid
from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from app.api.routers import ga_time_slots
from app.schemas.ga_time_slot import GaIcloudSyncImport
from app.services.ga_icloud_sync import (
    TimeRow,
    connection_id_from_token,
    generate_connection_token,
    hash_connection_token,
    prepare_calendar_item,
    prepare_reminder_item,
    resolve_timezone,
)


ROWS = [
    TimeRow(time(7, 30), time(8, 0)),
    TimeRow(time(8, 0), time(9, 0)),
    TimeRow(time(9, 0), time(10, 0)),
    TimeRow(time(10, 0), time(11, 0)),
    TimeRow(time(21, 0), time(22, 0)),
]


class TestGaIcloudSync(unittest.TestCase):
    def test_pairing_token_contains_connection_id_and_hashes_deterministically(self) -> None:
        connection_id = uuid.uuid4()
        token, digest = generate_connection_token(connection_id)

        self.assertEqual(connection_id_from_token(token), connection_id)
        self.assertEqual(hash_connection_token(token), digest)
        self.assertIsNone(connection_id_from_token("invalid"))

    def test_calendar_event_uses_local_day_and_containing_timetable_row(self) -> None:
        item = prepare_calendar_item(
            external_id="event-1",
            title="Customer call",
            starts_at=datetime(2026, 9, 7, 7, 15, tzinfo=timezone.utc),
            ends_at=datetime(2026, 9, 7, 8, 0, tzinfo=timezone.utc),
            is_all_day=False,
            calendar_name="ganimete.ar@gmail.com",
            location="Teams",
            zone=resolve_timezone("Europe/Berlin"),
            rows=ROWS,
        )

        self.assertEqual(item.day_date, date(2026, 9, 7))
        self.assertEqual((item.start_time, item.end_time), (time(9, 0), time(10, 0)))
        self.assertEqual(item.source_type, "calendar")
        self.assertIn("09:15–10:00", item.content)
        self.assertIn("Customer call", item.content)
        self.assertIn("Teams", item.content)

    def test_all_day_event_goes_to_untimed_day_row(self) -> None:
        item = prepare_calendar_item(
            external_id=None,
            title="Office closed",
            starts_at=datetime(2026, 9, 8),
            ends_at=None,
            is_all_day=True,
            calendar_name="ganimete.ar@gmail.com",
            location=None,
            zone=resolve_timezone("Europe/Berlin"),
            rows=ROWS,
        )

        self.assertEqual((item.start_time, item.end_time), (time(0, 0), time(0, 1)))
        self.assertEqual(item.content, "CALENDAR: Office closed")

    def test_timed_reminder_uses_slot_and_untimed_uses_comment_row(self) -> None:
        zone = resolve_timezone("Europe/Berlin")
        timed = prepare_reminder_item(
            external_id="reminder-1",
            title="Call supplier",
            due_at=datetime(2026, 9, 9, 8, 30, tzinfo=timezone.utc),
            due_date=None,
            reminder_list_name="REMINDER",
            notes=None,
            fallback_date=date(2026, 9, 7),
            zone=zone,
            rows=ROWS,
        )
        untimed = prepare_reminder_item(
            external_id="reminder-2",
            title="Review documents",
            due_at=None,
            due_date=date(2026, 9, 10),
            reminder_list_name="REMINDER",
            notes="Before lunch",
            fallback_date=date(2026, 9, 7),
            zone=zone,
            rows=ROWS,
        )

        self.assertEqual(timed.day_date, date(2026, 9, 9))
        self.assertEqual((timed.start_time, timed.end_time), (time(10, 0), time(11, 0)))
        self.assertIn("10:30", timed.content)
        self.assertEqual((untimed.start_time, untimed.end_time), (time(0, 0), time(0, 1)))
        self.assertIn("Before lunch", untimed.content)

    def test_undated_open_reminder_is_shown_on_sync_start_day(self) -> None:
        item = prepare_reminder_item(
            external_id="reminder-3",
            title="Unscheduled follow-up",
            due_at=None,
            due_date=None,
            reminder_list_name="REMINDER",
            notes=None,
            fallback_date=date(2026, 9, 7),
            zone=resolve_timezone("Europe/Berlin"),
            rows=ROWS,
        )

        self.assertEqual(item.day_date, date(2026, 9, 7))
        self.assertEqual(item.source_name, "REMINDER")


class TestGaIcloudReminderImport(unittest.IsolatedAsyncioTestCase):
    async def test_import_stores_weekend_items_within_sync_window(self) -> None:
        saturday = date(2026, 9, 5)
        sunday = date(2026, 9, 6)
        connection = SimpleNamespace(
            id=uuid.uuid4(), ga_user_id=uuid.uuid4(), calendar_name="Calendar", reminder_list_name="REMINDER"
        )
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock(all=Mock(return_value=[]))), add_all=Mock(), commit=AsyncMock())
        payload = GaIcloudSyncImport.model_validate({
            "sync_window_start": saturday,
            "sync_window_end": sunday,
            "calendar_name": "Calendar",
            "reminder_list_name": "REMINDER",
            "events": [
                {"title": "Weekend event", "starts_at": f"{day}T09:00:00+02:00"}
                for day in (saturday, sunday, date(2026, 9, 7))
            ],
            "reminders": [
                {"title": "Weekend reminder", "due_date": day}
                for day in (saturday, sunday, date(2026, 9, 4))
            ],
        })
        with (
            patch.object(ga_time_slots, "_connection_from_sync_token", AsyncMock(return_value=connection)),
            patch.object(ga_time_slots, "get_ga_time_table_rows", AsyncMock(return_value=[])),
        ):
            result = await ga_time_slots.import_icloud_timetable_data(payload, "test-token", db)

        self.assertEqual((result.calendar_imported, result.reminders_imported, result.skipped), (2, 2, 2))
        self.assertCountEqual(
            [(entry.source_type, entry.day_date) for entry in db.add_all.call_args.args[0]],
            [(source, day) for source in ("calendar", "reminder") for day in (saturday, sunday)],
        )
        db.commit.assert_awaited_once()

    async def test_import_preserves_completed_reopened_and_legacy_reminders(self) -> None:
        connection = SimpleNamespace(
            id=uuid.uuid4(), ga_user_id=uuid.uuid4(), calendar_name="Calendar", reminder_list_name="REMINDER"
        )
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock(all=Mock(return_value=[]))), add_all=Mock(), commit=AsyncMock())
        day = date(2026, 9, 7)
        with (
            patch.object(ga_time_slots, "_connection_from_sync_token", AsyncMock(return_value=connection)),
            patch.object(ga_time_slots, "get_ga_time_table_rows", AsyncMock(return_value=[])),
        ):
            for status, expected_completed in (({"is_completed": "true"}, True), ({"is_completed": "false"}, False), ({}, False)):
                payload = GaIcloudSyncImport.model_validate({
                    "sync_window_start": day,
                    "sync_window_end": day,
                    "calendar_name": "Calendar",
                    "reminder_list_name": "REMINDER",
                    "reminders": [{"title": "Follow up", "due_date": day, **status}],
                })
                result = await ga_time_slots.import_icloud_timetable_data(payload, "test-token", db)
                self.assertEqual((result.reminders_imported, result.skipped), (1, 0))

                entry, = db.add_all.call_args.args[0]
                entry.id = uuid.uuid4()
                entry.created_at = entry.updated_at = datetime(2026, 9, 7, 9, tzinfo=timezone.utc)
                response = ga_time_slots._dated_entry_out(entry)
                self.assertIs(response.is_completed, expected_completed)
                self.assertEqual(response.background_color, "#DCFCE7" if expected_completed else "#FEF3C7")


if __name__ == "__main__":
    unittest.main()
