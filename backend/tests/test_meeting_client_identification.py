from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.routers.meeting_notes import router, set_client_identification
from app.db import get_db
from app.models.enums import UserRole
from app.schemas.meeting import MeetingClientIdentification, MeetingClientCreate


@pytest.mark.parametrize("value, expected", [("  Kettler  ", "Kettler"), ("   ", None), (None, None)])
def test_client_identification_normalizes_optional_text(value, expected):
    assert MeetingClientIdentification(client_name=value).client_name == expected


def test_client_identification_limits_name_length():
    with pytest.raises(ValidationError):
        MeetingClientIdentification(client_name="x" * 201)


@pytest.mark.parametrize("role, creator", [(UserRole.ADMIN, False), (UserRole.MANAGER, False), (UserRole.STAFF, True), (UserRole.STAFF, False)])
@pytest.mark.parametrize("label", ["Kettler", None])
def test_label_save_and_clear_change_only_identification(monkeypatch, role, creator, label):
    user_id, project_id = uuid.uuid4(), uuid.uuid4()
    meeting = SimpleNamespace(
        id=uuid.uuid4(), client_name="Old name", project_id=project_id,
        created_by=user_id if creator else uuid.uuid4(),
        title="Original title", microsoft_event_id="calendar-event",
    )
    db = SimpleNamespace(get=AsyncMock(return_value=meeting), commit=AsyncMock())
    client = SimpleNamespace(id=uuid.uuid4(), name=label) if label else None
    monkeypatch.setattr("app.api.routers.meeting_notes.resolve_meeting_client", AsyncMock(return_value=client))
    result = asyncio.run(set_client_identification(
        meeting.id, MeetingClientIdentification(client_name=label), db=db,
        user=SimpleNamespace(id=user_id, role=role),
    ))
    assert result == {"id": meeting.id, "client_id": client.id if client else None, "client_name": label}
    assert meeting.project_id == project_id
    assert meeting.title == "Original title"
    assert meeting.microsoft_event_id == "calendar-event"
    db.commit.assert_awaited_once()


def test_staff_can_identify_imported_meetings_without_a_creator():
    meeting = SimpleNamespace(id=uuid.uuid4(), client_name="Old", created_by=None)
    client = SimpleNamespace(id=uuid.uuid4(), name="New")
    db = SimpleNamespace(get=AsyncMock(side_effect=[meeting, client]), commit=AsyncMock())
    result = asyncio.run(set_client_identification(
        meeting.id, MeetingClientIdentification(client_id=client.id), db=db,
        user=SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF),
    ))
    assert result["client_name"] == "New"
    assert meeting.client_name == "New"
    assert meeting.client_id == client.id
    db.commit.assert_awaited_once()


def test_missing_meeting_cannot_be_labeled():
    db = SimpleNamespace(get=AsyncMock(return_value=None), commit=AsyncMock())
    with pytest.raises(HTTPException) as raised:
        asyncio.run(set_client_identification(
            uuid.uuid4(), MeetingClientIdentification(client_name="Kettler"), db=db,
            user=SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN),
        ))
    assert raised.value.status_code == 404
    db.commit.assert_not_awaited()


def test_multiple_meetings_share_the_same_client_identity():
    client = SimpleNamespace(id=uuid.uuid4(), name="Kettler")
    first = SimpleNamespace(id=uuid.uuid4(), client_name=None, client_id=None)
    second = SimpleNamespace(id=uuid.uuid4(), client_name=None, client_id=None)
    db = SimpleNamespace(get=AsyncMock(side_effect=[first, client, second, client]), commit=AsyncMock())
    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF)
    for meeting in [first, second]:
        asyncio.run(set_client_identification(meeting.id, MeetingClientIdentification(client_id=client.id), db=db, user=user))
    assert first.client_id == second.client_id == client.id
    assert first.client_name == second.client_name == "Kettler"
    assert db.commit.await_count == 2


def test_unknown_client_is_rejected_without_changing_the_meeting():
    meeting = SimpleNamespace(id=uuid.uuid4(), client_name="Original", client_id=uuid.uuid4())
    original_id = meeting.client_id
    db = SimpleNamespace(get=AsyncMock(side_effect=[meeting, None]), commit=AsyncMock())
    with pytest.raises(HTTPException) as raised:
        asyncio.run(set_client_identification(
            meeting.id, MeetingClientIdentification(client_id=uuid.uuid4()), db=db,
            user=SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF),
        ))
    assert raised.value.status_code == 404
    assert meeting.client_name == "Original"
    assert meeting.client_id == original_id
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("name", ["   ", "x" * 201])
def test_new_client_name_must_be_valid(name):
    with pytest.raises(ValidationError):
        MeetingClientCreate(name=name)


def test_client_identification_still_requires_login():
    app = FastAPI()
    app.include_router(router, prefix="/meeting-notes")
    db = SimpleNamespace(get=AsyncMock(), commit=AsyncMock())
    app.dependency_overrides[get_db] = lambda: db
    response = TestClient(app).patch(
        f"/meeting-notes/meetings/{uuid.uuid4()}/client", json={"client_name": "Kettler"},
    )
    assert response.status_code == 401
    db.get.assert_not_awaited()
    db.commit.assert_not_awaited()
