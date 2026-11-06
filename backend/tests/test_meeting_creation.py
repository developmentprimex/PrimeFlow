from __future__ import annotations

import os
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from fastapi import HTTPException

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/primex_test")
os.environ.setdefault("JWT_SECRET", "test-secret")

from app.api.routers.meetings import create_meeting
from app.models.enums import UserRole
from app.models.meeting import Meeting, MeetingParticipant
from app.schemas.meeting import MeetingCreate


class _ListResult:
    def __init__(self, values):
        self.values = list(values)

    def scalars(self):
        return self

    def all(self):
        return list(self.values)

    def scalar_one_or_none(self):
        if not self.values:
            return None
        if len(self.values) != 1:
            raise AssertionError(f"Expected at most one value, received {len(self.values)}")
        return self.values[0]


class _FakeDb:
    def __init__(self, valid_user_ids: list[uuid.UUID] | None = None):
        self.added: list[object] = []
        self.commit_count = 0
        self.valid_user_ids = valid_user_ids or []
        self.pre_creation_execute_count = 0

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        now = datetime.now(timezone.utc)
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid.uuid4()
            if isinstance(value, Meeting):
                if getattr(value, "external_agent_test_task_requested", None) is None:
                    value.external_agent_test_task_requested = False
                if getattr(value, "external_pim_image_test_task_requested", None) is None:
                    value.external_pim_image_test_task_requested = False
                if getattr(value, "created_at", None) is None:
                    value.created_at = now
                if getattr(value, "updated_at", None) is None:
                    value.updated_at = now

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, _value):
        return None

    async def execute(self, _statement):
        meetings = [value for value in self.added if isinstance(value, Meeting)]
        if not meetings:
            self.pre_creation_execute_count += 1
            if self.pre_creation_execute_count == 1:
                return _ListResult([SimpleNamespace(id=user_id) for user_id in self.valid_user_ids])
            return _ListResult([])
        primary_meeting = meetings[0]
        participants = [
            value
            for value in self.added
            if isinstance(value, MeetingParticipant) and value.meeting_id == primary_meeting.id
        ]
        return _ListResult(participants)


class TestMeetingCreation(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # The fake DB only models meeting/participant inserts; TAK INT 1H tasks are covered elsewhere.
        reconcile_patch = patch(
            "app.api.routers.meetings.reconcile_tak_int_one_h_tasks_for_meeting",
            new=AsyncMock(return_value=0),
        )
        reconcile_patch.start()
        self.addCleanup(reconcile_patch.stop)

    def test_paired_internal_meeting_is_deleted_with_its_external_meeting(self) -> None:
        foreign_key = next(iter(Meeting.__table__.c.paired_external_meeting_id.foreign_keys))
        self.assertEqual(foreign_key.target_fullname, "meetings.id")
        self.assertEqual(foreign_key.ondelete, "CASCADE")

    def test_preparation_internal_meeting_is_deleted_with_its_external_meeting(self) -> None:
        foreign_key = next(iter(Meeting.__table__.c.pre_external_meeting_id.foreign_keys))
        self.assertEqual(foreign_key.target_fullname, "meetings.id")
        self.assertEqual(foreign_key.ondelete, "CASCADE")

    async def test_external_meeting_with_internal_time_creates_both_atomically(self) -> None:
        department_id = uuid.uuid4()
        participant_id = uuid.uuid4()
        creator_id = uuid.uuid4()
        external_starts_at = datetime(2026, 8, 25, 13, 0, tzinfo=timezone.utc)
        internal_starts_at = datetime(2026, 8, 25, 11, 30, tzinfo=timezone.utc)
        payload = MeetingCreate(
            title="Customer review",
            platform="Teams",
            starts_at=external_starts_at,
            internal_starts_at=internal_starts_at,
            meeting_type="external",
            recurrence_type="weekly",
            recurrence_days_of_week=[1],
            department_id=department_id,
            participant_ids=[participant_id],
        )
        user = SimpleNamespace(id=creator_id, role=UserRole.ADMIN, department_id=None)
        db = _FakeDb(valid_user_ids=[participant_id])

        result = await create_meeting(payload=payload, db=db, user=user)

        meetings = [value for value in db.added if isinstance(value, Meeting)]
        participants = [value for value in db.added if isinstance(value, MeetingParticipant)]
        self.assertEqual(len(meetings), 2)
        self.assertEqual({meeting.meeting_type for meeting in meetings}, {"external", "internal"})
        external_meeting = next(meeting for meeting in meetings if meeting.meeting_type == "external")
        internal_meeting = next(meeting for meeting in meetings if meeting.meeting_type == "internal")
        self.assertEqual(internal_meeting.paired_external_meeting_id, external_meeting.id)
        self.assertEqual(len(participants), 2)
        self.assertEqual({participant.meeting_id for participant in participants}, {meeting.id for meeting in meetings})
        self.assertEqual(db.commit_count, 1)
        self.assertEqual(result.starts_at, external_starts_at)
        self.assertIsNotNone(result.paired_internal_meeting)
        self.assertEqual(result.paired_internal_meeting.starts_at, internal_starts_at)
        self.assertEqual(result.paired_internal_meeting.participant_ids, [participant_id])

    async def test_linked_internal_creation_includes_external_and_direct_participants(self) -> None:
        inherited_user_id = uuid.uuid4()
        direct_user_id = uuid.uuid4()
        external = Meeting(
            id=uuid.uuid4(),
            title="Customer review",
            meeting_type="external",
            department_id=uuid.uuid4(),
            created_by=uuid.uuid4(),
        )

        class _LinkedFakeDb(_FakeDb):
            def __init__(self):
                super().__init__(valid_user_ids=[inherited_user_id, direct_user_id])
                self.lookup_count = 0

            async def execute(self, statement):
                meetings = [value for value in self.added if isinstance(value, Meeting)]
                if meetings:
                    return await super().execute(statement)
                self.lookup_count += 1
                if self.lookup_count == 1:
                    return _ListResult([external])
                if self.lookup_count == 2:
                    return _ListResult([])
                if self.lookup_count == 3:
                    return _ListResult([(external.id, inherited_user_id)])
                if self.lookup_count == 4:
                    return _ListResult([
                        SimpleNamespace(id=inherited_user_id),
                        SimpleNamespace(id=direct_user_id),
                    ])
                raise AssertionError("Unexpected database query")

        payload = MeetingCreate(
            title="Customer review preparation",
            meeting_type="internal",
            department_id=external.department_id,
            participant_ids=[direct_user_id],
            paired_external_meeting_id=external.id,
        )
        db = _LinkedFakeDb()

        result = await create_meeting(
            payload=payload,
            db=db,
            user=SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN, department_id=None),
        )

        self.assertEqual(set(result.participant_ids), {inherited_user_id, direct_user_id})
        self.assertEqual(
            {value.user_id for value in db.added if isinstance(value, MeetingParticipant)},
            {inherited_user_id, direct_user_id},
        )

    async def test_global_one_h_conflict_requires_explicit_override(self) -> None:
        department_id = uuid.uuid4()
        participant_id = uuid.uuid4()
        local_start = datetime(2026, 9, 21, 10, 0, tzinfo=ZoneInfo("Europe/Tirane"))
        user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN, department_id=None)
        payload = MeetingCreate(
            title="Team sync",
            starts_at=local_start,
            meeting_type="internal",
            department_id=department_id,
            participant_ids=[participant_id],
        )
        db = _FakeDb(valid_user_ids=[participant_id])

        with self.assertRaises(HTTPException) as raised:
            await create_meeting(payload=payload, db=db, user=user)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["code"], "one_h_conflict")

        override_payload = payload.model_copy(update={"allow_one_h_conflict": True})
        override_db = _FakeDb(valid_user_ids=[participant_id])
        result = await create_meeting(payload=override_payload, db=override_db, user=user)
        self.assertEqual(result.title, "Team sync")
        self.assertEqual(override_db.commit_count, 1)

    async def test_internal_meeting_does_not_create_another_internal_meeting(self) -> None:
        department_id = uuid.uuid4()
        participant_id = uuid.uuid4()
        payload = MeetingCreate(
            title="Team sync",
            starts_at=datetime(2026, 8, 25, 13, 0, tzinfo=timezone.utc),
            internal_starts_at=datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc),
            meeting_type="internal",
            department_id=department_id,
            participant_ids=[participant_id],
        )
        user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN, department_id=None)
        db = _FakeDb(valid_user_ids=[participant_id])

        result = await create_meeting(payload=payload, db=db, user=user)

        meetings = [value for value in db.added if isinstance(value, Meeting)]
        self.assertEqual(len(meetings), 1)
        self.assertEqual(meetings[0].meeting_type, "internal")
        self.assertIsNone(result.paired_internal_meeting)

    async def test_external_meeting_can_skip_internal_meeting(self) -> None:
        department_id = uuid.uuid4()
        participant_id = uuid.uuid4()
        external_starts_at = datetime(2026, 8, 25, 13, 0, tzinfo=timezone.utc)
        payload = MeetingCreate(
            title="Customer review",
            client_name="  Kettler  ",
            starts_at=external_starts_at,
            internal_starts_at=datetime(2026, 8, 25, 12, 30, tzinfo=timezone.utc),
            create_internal_meeting=False,
            meeting_type="external",
            department_id=department_id,
            participant_ids=[participant_id],
        )
        user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN, department_id=None)
        db = _FakeDb(valid_user_ids=[participant_id])

        client = SimpleNamespace(id=uuid.uuid4(), name="Kettler")
        with patch("app.api.routers.meetings.resolve_meeting_client", new=AsyncMock(return_value=client)):
            result = await create_meeting(payload=payload, db=db, user=user)

        meetings = [value for value in db.added if isinstance(value, Meeting)]
        self.assertEqual(len(meetings), 1)
        self.assertEqual(meetings[0].meeting_type, "external")
        self.assertEqual(meetings[0].client_id, client.id)
        self.assertEqual(result.client_id, client.id)
        self.assertEqual(meetings[0].client_name, "Kettler")
        self.assertEqual(result.client_name, "Kettler")
        self.assertIsNone(meetings[0].project_id)
        self.assertIsNone(result.paired_internal_meeting)

    async def test_meeting_requires_at_least_one_person(self) -> None:
        payload = MeetingCreate(
            title="Team sync",
            meeting_type="internal",
            department_id=uuid.uuid4(),
        )
        user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN, department_id=None)

        with self.assertRaises(HTTPException) as raised:
            await create_meeting(payload=payload, db=_FakeDb(), user=user)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "Select at least one person for the meeting")

    async def test_external_meeting_requires_internal_time_when_pair_is_enabled(self) -> None:
        payload = MeetingCreate(
            title="Customer review",
            starts_at=datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc),
            create_internal_meeting=True,
            meeting_type="external",
            department_id=uuid.uuid4(),
        )
        user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN, department_id=None)

        with self.assertRaises(HTTPException) as raised:
            await create_meeting(payload=payload, db=_FakeDb(), user=user)

        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
