from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.integrations.microsoft import SCOPES, microsoft_account_email
from app.schemas.meeting_scheduler import MeetingScheduleRequestCreate, MeetingSchedulingStandardCreate
from app.models.meeting import Meeting
from app.schemas.meeting_scheduler import MeetingScheduleValidationIn
from app.services.meeting_scheduler import (
    meeting_occurrence_window,
    microsoft_schedule_conflicts,
    one_h_schedule_conflicts,
    suggest_first_free_slot,
    validate_meeting_schedule,
)


class _Result:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self.values[0] if self.values else None


class _ValidationDb:
    def __init__(self, results):
        self.results = iter(results)
        self.statements = []

    async def execute(self, _statement):
        self.statements.append(str(_statement))
        return _Result(next(self.results))


def _base_payload(**overrides):
    start = (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=6, minute=0, second=0, microsecond=0)
    values = {
        "title": "TAK EXT | Client | Demo",
        "meeting_type": "external",
        "starts_at": start,
        "ends_at": start + timedelta(hours=1),
        "client_email": "client@example.com",
        "department_id": "00000000-0000-0000-0000-000000000001",
        "participant_ids": ["00000000-0000-0000-0000-000000000002"],
    }
    values.update(overrides)
    return values


def test_external_validation_does_not_require_client_email() -> None:
    request = MeetingScheduleRequestCreate(**_base_payload(client_email=None))

    assert request.client_email is None


def test_request_end_must_be_after_start() -> None:
    start = datetime.now(timezone.utc) + timedelta(days=2)
    with pytest.raises(ValidationError):
        MeetingScheduleRequestCreate(**_base_payload(starts_at=start, ends_at=start))


def test_meeting_standard_has_no_title_format_field() -> None:
    standard = MeetingSchedulingStandardCreate(name="Takim klienti", meeting_type="external")

    assert "title_prefix" not in standard.model_dump()


def test_calendar_write_scope_is_requested() -> None:
    assert "https://graph.microsoft.com/Calendars.ReadWrite" in SCOPES
    assert "https://graph.microsoft.com/Calendars.Read" not in SCOPES


def test_microsoft_account_email_prefers_mail_and_normalizes_case() -> None:
    assert microsoft_account_email(
        {"mail": "Info@PrimexEU.com ", "userPrincipalName": "fallback@primexeu.com"}
    ) == "info@primexeu.com"


def test_microsoft_account_email_falls_back_to_user_principal_name() -> None:
    assert microsoft_account_email({"mail": None, "userPrincipalName": "INFO@PRIMEXEU.COM"}) == "info@primexeu.com"


def test_weekly_meeting_occurrence_preserves_time_and_duration() -> None:
    meeting = SimpleNamespace(
        meeting_type="external",
        starts_at=datetime(2026, 9, 1, 9, 30, tzinfo=timezone.utc),
        ends_at=datetime(2026, 9, 1, 10, 15, tzinfo=timezone.utc),
        recurrence_type="weekly",
        recurrence_days_of_week=[1],
        recurrence_days_of_month=None,
    )
    window = meeting_occurrence_window(meeting, datetime(2026, 9, 8, 8, 0, tzinfo=timezone.utc))
    assert window is not None
    assert window[1] - window[0] == timedelta(minutes=45)


def test_microsoft_busy_item_becomes_conflict() -> None:
    start = datetime(2026, 9, 4, 9, 0, tzinfo=timezone.utc)
    conflicts = microsoft_schedule_conflicts(
        [{
            "scheduleId": "person@primexeu.com",
            "scheduleItems": [{
                "status": "busy",
                "start": {"dateTime": "2026-09-04T09:15:00+00:00"},
                "end": {"dateTime": "2026-09-04T09:45:00+00:00"},
            }],
        }],
        starts_at=start,
        ends_at=start + timedelta(hours=1),
    )
    assert len(conflicts) == 1
    assert conflicts[0].source == "microsoft"


def test_duplicate_microsoft_busy_items_are_returned_once() -> None:
    start = datetime(2026, 9, 4, 9, 0, tzinfo=timezone.utc)
    busy_item = {
        "status": "busy",
        "start": {"dateTime": "2026-09-04T09:15:00+00:00"},
        "end": {"dateTime": "2026-09-04T09:45:00+00:00"},
    }

    conflicts = microsoft_schedule_conflicts(
        [{"scheduleId": "info@primexeu.com", "scheduleItems": [busy_item, busy_item]}],
        starts_at=start,
        ends_at=start + timedelta(hours=1),
    )

    assert len(conflicts) == 1


def test_microsoft_pv_item_is_visible_calendar_info_not_a_conflict() -> None:
    start = datetime(2026, 9, 8, 8, 0, tzinfo=timezone.utc)
    conflicts = microsoft_schedule_conflicts(
        [{
            "scheduleId": "info@primexeu.com",
            "scheduleItems": [{
                "status": "busy",
                "subject": "DV PV 07.09-20.09.2026",
                "start": {"dateTime": "2026-09-08T08:00:00+00:00"},
                "end": {"dateTime": "2026-09-08T08:30:00+00:00"},
            }],
        }],
        starts_at=start,
        ends_at=start + timedelta(hours=1),
    )

    assert conflicts == []


def test_primeflow_pv_meeting_does_not_block_external_meeting() -> None:
    start = (datetime.now(timezone.utc) + timedelta(days=10)).replace(hour=6, minute=0, second=0, microsecond=0)
    pv = Meeting(
        title="DV PV 07.09-20.09.2026",
        meeting_type="external",
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        department_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        calendar_imported=True,
        calendar_sync_status="excluded",
    )
    pv.id = uuid.UUID("00000000-0000-0000-0000-000000000011")
    participant = SimpleNamespace(
        id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        is_active=True,
    )
    db = _ValidationDb([
        [participant],
        [(pv, participant.id)],
        [pv],
        [],
        [],
    ])
    payload = MeetingScheduleValidationIn(**_base_payload(
        starts_at=start,
        ends_at=start + timedelta(minutes=30),
    ))

    result = asyncio.run(validate_meeting_schedule(db, payload))

    assert result.can_create is True
    assert result.conflicts == []


def test_external_meeting_blocks_overlapping_external_without_shared_participants() -> None:
    start = (datetime.now(timezone.utc) + timedelta(days=10)).replace(hour=6, minute=0, second=0, microsecond=0)
    existing = Meeting(
        title="TAK EXT | Existing client",
        meeting_type="external",
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        department_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
    )
    existing.id = uuid.UUID("00000000-0000-0000-0000-000000000010")
    participant = SimpleNamespace(
        id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        is_active=True,
    )
    db = _ValidationDb([
        [participant],  # selected users
        [],             # meetings sharing a participant
        [existing],     # every existing TAK EXT
        [],             # requests sharing a participant
        [],             # every pending TAK EXT request
    ])
    payload = MeetingScheduleValidationIn(**_base_payload(
        starts_at=start + timedelta(minutes=30),
        ends_at=start + timedelta(minutes=45),
    ))

    result = asyncio.run(validate_meeting_schedule(db, payload))

    assert result.can_create is False
    assert any(conflict.source == "tak_ext" for conflict in result.conflicts)
    assert any("TAK EXT" in error for error in result.errors)


def test_global_one_h_conflict_uses_fifteen_minute_window_and_boundaries() -> None:
    participant_id = uuid.uuid4()
    # Europe/Budapest is UTC+2 on this date, so 10:00 local is 08:00 UTC.
    db = _ValidationDb([])
    conflicts, _ = asyncio.run(one_h_schedule_conflicts(
        db,
        participant_ids={participant_id},
        starts_at=datetime(2026, 9, 21, 7, 50, tzinfo=timezone.utc),
        ends_at=datetime(2026, 9, 21, 8, 20, tzinfo=timezone.utc),
    ))
    assert len(conflicts) == 1
    assert conflicts[0].source == "one_h"
    assert conflicts[0].ends_at - conflicts[0].starts_at == timedelta(minutes=15)

    db = _ValidationDb([])
    conflicts, _ = asyncio.run(one_h_schedule_conflicts(
        db,
        participant_ids={participant_id},
        starts_at=datetime(2026, 9, 21, 8, 15, tzinfo=timezone.utc),
        ends_at=datetime(2026, 9, 21, 8, 45, tzinfo=timezone.utc),
    ))
    assert conflicts == []


@pytest.mark.parametrize("meeting_type", ["internal", "external"])
@pytest.mark.parametrize("has_participant", [True, False])
def test_manual_internal_checks_other_users_and_unassigned_meetings(meeting_type, has_participant) -> None:
    start = (datetime.now(timezone.utc) + timedelta(days=10)).replace(hour=6, minute=0, second=0, microsecond=0)
    selected_id, other_id = uuid.uuid4(), uuid.uuid4()
    existing = Meeting(
        id=uuid.uuid4(), title="Existing meeting", meeting_type=meeting_type,
        starts_at=start, ends_at=start + timedelta(minutes=30),
        department_id=uuid.uuid4(),
    )
    participant = SimpleNamespace(id=selected_id, is_active=True)
    db = _ValidationDb([[participant], [(existing, other_id if has_participant else None)], []])
    payload = MeetingScheduleValidationIn(**_base_payload(
        meeting_type="internal", participant_ids=[selected_id], check_all_meetings=True,
        starts_at=start + timedelta(minutes=15), ends_at=start + timedelta(minutes=45),
    ))
    result = asyncio.run(validate_meeting_schedule(db, payload))
    assert len(result.conflicts) == 1
    assert result.conflicts[0].source == ("tak_int" if meeting_type == "internal" else "tak_ext")
    assert result.conflicts[0].participant_ids == ([other_id] if has_participant else [])
    assert "LEFT OUTER JOIN" in db.statements[1]
    assert "NOT (EXISTS" in db.statements[1]
    assert "meeting_occurrence_statuses.status" in db.statements[1]
    assert "meeting_participants.user_id IN" not in db.statements[1]
    assert not any("Nuk mund të krijohet TAK EXT" in error for error in result.errors)


@pytest.mark.parametrize("offset, cancelled", [(30, False), (15, True)])
def test_manual_internal_ignores_adjacent_and_cancelled_meetings(offset, cancelled) -> None:
    start = (datetime.now(timezone.utc) + timedelta(days=10)).replace(hour=6, minute=0, second=0, microsecond=0)
    selected_id = uuid.uuid4()
    existing = Meeting(
        id=uuid.uuid4(), title="Existing internal", meeting_type="internal",
        starts_at=start, department_id=uuid.uuid4(),
        calendar_sync_status="cancelled" if cancelled else None,
    )
    db = _ValidationDb([[SimpleNamespace(id=selected_id, is_active=True)], [(existing, uuid.uuid4())], []])
    payload = MeetingScheduleValidationIn(**_base_payload(
        meeting_type="internal", participant_ids=[selected_id], check_all_meetings=True,
        starts_at=start + timedelta(minutes=offset), ends_at=start + timedelta(minutes=offset + 30),
    ))
    result = asyncio.run(validate_meeting_schedule(db, payload))
    assert result.conflicts == []


def test_suggestion_moves_in_fifteen_minute_steps_until_free() -> None:
    conflict_start = datetime(2026, 9, 21, 8, 0, tzinfo=timezone.utc)
    conflict = SimpleNamespace(starts_at=conflict_start, ends_at=conflict_start + timedelta(minutes=15))
    suggestion = suggest_first_free_slot(
        starts_at=conflict_start,
        ends_at=conflict_start + timedelta(minutes=30),
        one_h_conflicts=[conflict],
        blockers=[
            (conflict_start, conflict_start + timedelta(minutes=15)),
            (conflict_start + timedelta(minutes=15), conflict_start + timedelta(minutes=45)),
        ],
    )
    assert suggestion is not None
    assert suggestion.starts_at == conflict_start + timedelta(minutes=45)
    assert suggestion.ends_at == conflict_start + timedelta(minutes=75)


def test_validation_returns_one_h_conflict_and_first_free_suggestion() -> None:
    participant_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    local_tz = ZoneInfo("Europe/Tirane")
    local_start = datetime.now(local_tz).replace(hour=9, minute=50, second=0, microsecond=0) + timedelta(days=10)
    while local_start.weekday() >= 5:
        local_start += timedelta(days=1)
    participant = SimpleNamespace(id=participant_id, is_active=True)
    db = _ValidationDb([
        [participant],
        [],
        [],
        [],
    ])
    payload = MeetingScheduleValidationIn(**_base_payload(
        meeting_type="internal",
        starts_at=local_start.astimezone(timezone.utc),
        ends_at=(local_start + timedelta(minutes=30)).astimezone(timezone.utc),
    ))

    result = asyncio.run(validate_meeting_schedule(db, payload))

    assert result.can_create is False
    assert any(conflict.source == "one_h" for conflict in result.conflicts)
    assert result.suggested_slot is not None
    assert result.suggested_slot.starts_at.astimezone(local_tz).strftime("%H:%M") == "10:15"
