from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import uuid

import pytest
from pydantic import ValidationError

from app.api.routers import meeting_notes as api
from app.models.meeting_note import MeetingNote


def make_note(manual_status="TODO"):
    return MeetingNote(
        id=uuid.uuid4(), meeting_id=uuid.uuid4(), ga_note_id=uuid.uuid4(),
        occurrence_date=date.today(), kind="NOTE", content="Case",
        source="MANUAL", manual_status=manual_status, is_closed=False,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        attachments=[],
    )


@pytest.mark.parametrize("linked_status", ["TODO", "IN_PROGRESS", "DONE"])
@pytest.mark.parametrize("manual_status", ["TODO", "WAITING_CLIENT", "DONE"])
def test_note_status_and_open_filter_are_independent_of_tasks(linked_status, manual_status):
    note = make_note(manual_status)
    tasks = {note.ga_note_id: (linked_status, [uuid.uuid4()])}
    result = api._note_out(note, tasks)
    assert result.manual_status == manual_status
    assert api._is_open(note, tasks) == (manual_status != "DONE")
    note.is_closed = True
    assert not api._is_open(note, tasks)


@pytest.mark.parametrize("status", ["TODO", "IN_PROGRESS", "WAITING_CLIENT", "DONE"])
@pytest.mark.parametrize("linked", [True, False])
def test_manual_patch_saves_only_note_and_survives_reload(monkeypatch, status, linked):
    note = make_note()
    if not linked:
        note.ga_note_id = None
    original_link = note.ga_note_id
    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(api, "_get_note", AsyncMock(return_value=note))
    monkeypatch.setattr(api, "_reload", AsyncMock(return_value=note))
    # Production serialization verifies the persisted field rather than an optimistic UI value.
    async def notes_out(db, notes):
        return [api._note_out(n, {}) for n in notes]
    monkeypatch.setattr(api, "_notes_out", notes_out)
    result = asyncio.run(api.update_note(
        note.id, api.MeetingNoteUpdate(manual_status=status), db=db, user=SimpleNamespace(),
    ))
    assert result.manual_status == status
    assert note.manual_status == status
    assert note.ga_note_id == original_link
    assert note.content == "Case"
    db.commit.assert_awaited_once()
    # No task lookup/update capability is present on db: a task write would fail this test.


@pytest.mark.parametrize("invalid", [None, "INVALID", "done", ""])
def test_invalid_status_is_rejected(invalid):
    with pytest.raises(ValidationError):
        api.MeetingNoteUpdate(manual_status=invalid)


def test_other_edits_do_not_reset_manual_status():
    assert "manual_status" not in api.MeetingNoteUpdate(content="Edited").model_dump(exclude_unset=True)


@pytest.mark.parametrize("merge", [True, False])
def test_send_to_px_numbers_merged_notes_in_selection_order(monkeypatch, merge):
    first, second = make_note(), make_note()
    second.meeting_id = first.meeting_id
    first.ga_note_id = second.ga_note_id = None
    first.content, second.content = "First case", "Second case"
    first.answer = "Answer on another line"
    first.manual_status = "DONE"
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [first, second]))
    db = SimpleNamespace(execute=AsyncMock(return_value=result), flush=AsyncMock(),
                         commit=AsyncMock(), rollback=AsyncMock(), expire_all=lambda: None)
    meeting = SimpleNamespace(title="Client meeting", project_id=uuid.uuid4(), department_id=None)
    monkeypatch.setattr(api, "_get_meeting", AsyncMock(return_value=meeting))
    build = AsyncMock(side_effect=lambda *args: SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(api, "build_ga_note", build)
    monkeypatch.setattr(api, "_copy_attachments_to_px", AsyncMock(return_value=[]))
    monkeypatch.setattr(api, "_notes_out", AsyncMock(return_value=[]))
    asyncio.run(api.send_to_px(api.SendToPxIn(note_ids=[second.id, first.id], merge=merge),
                               db=db, user=SimpleNamespace(id=uuid.uuid4())))
    if merge:
        content = build.await_args.args[2].content
        assert content == f"Client meeting · {first.occurrence_date:%d.%m.%Y}\n1. Second case\n2. First case\nVendimi: Answer on another line"
        assert "•" not in content
        assert first.ga_note_id == second.ga_note_id
    else:
        assert [call.args[2].content for call in build.await_args_list] == [
            "Second case", "First case\nVendimi: Answer on another line",
        ]
        assert first.ga_note_id != second.ga_note_id
    assert first.content == "First case"
    assert first.manual_status == "DONE"
