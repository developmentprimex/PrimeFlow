from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.ga_calendar_feed import build_ga_calendar


def _meeting(**overrides):
    values = {
        "id": uuid.uuid4(),
        "title": "Team sync",
        "platform": None,
        "meeting_url": None,
        "meeting_type": "internal",
        # Monday 2026-10-12 10:00 in Tirane (CEST, UTC+2).
        "starts_at": datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc),
        "ends_at": None,
        "recurrence_type": "none",
        "recurrence_days_of_week": None,
        "recurrence_days_of_month": None,
        "paired_external_meeting_id": None,
        "pre_external_meeting_id": None,
        "calendar_imported": False,
        "microsoft_event_id": None,
        "calendar_sync_status": None,
        "calendar_categories": None,
        "reminder_minutes_before": 15,
        "updated_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
        "created_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestGaCalendarFeedMeetings(unittest.TestCase):
    def test_one_time_internal_meeting_is_exported_in_local_time(self) -> None:
        meeting = _meeting()
        feed = build_ga_calendar([], [meeting])

        self.assertIn(f"UID:ga-meeting-{meeting.id}@primeflow.primexeu.com", feed)
        self.assertIn("DTSTART;TZID=Europe/Tirane:20261012T100000", feed)
        self.assertIn("DTEND;TZID=Europe/Tirane:20261012T103000", feed)
        self.assertIn("SUMMARY:TAK INT: Team sync", feed)
        self.assertIn("TRIGGER:-PT15M", feed)
        self.assertNotIn("RRULE", feed.split("BEGIN:VEVENT", 1)[1])

    def test_weekly_meeting_starts_on_first_matching_weekday(self) -> None:
        # Starts on a Monday but repeats on Wednesday and Friday.
        feed = build_ga_calendar([], [_meeting(recurrence_type="weekly", recurrence_days_of_week=[2, 4])])

        self.assertIn("RRULE:FREQ=WEEKLY;BYDAY=WE,FR", feed)
        self.assertIn("DTSTART;TZID=Europe/Tirane:20261014T100000", feed)

    def test_monthly_meeting_uses_month_days(self) -> None:
        feed = build_ga_calendar([], [_meeting(recurrence_type="monthly", recurrence_days_of_month=[20])])

        self.assertIn("RRULE:FREQ=MONTHLY;BYMONTHDAY=20", feed)
        self.assertIn("DTSTART;TZID=Europe/Tirane:20261020T100000", feed)

    def test_linked_external_and_hidden_meetings_are_skipped(self) -> None:
        feed = build_ga_calendar(
            [],
            [
                _meeting(paired_external_meeting_id=uuid.uuid4()),
                _meeting(pre_external_meeting_id=uuid.uuid4()),
                _meeting(meeting_type="external"),
                _meeting(calendar_sync_status="cancelled"),
                _meeting(starts_at=None),
            ],
        )

        self.assertNotIn("BEGIN:VEVENT", feed)


if __name__ == "__main__":
    unittest.main()
