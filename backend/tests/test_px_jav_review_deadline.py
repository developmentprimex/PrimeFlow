import asyncio
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic import ValidationError

from app.api.routers.plan_notes import update_plan_note
from app.models.enums import GaNoteStatus
from app.schemas.plan_note import PlanNoteUpdate


@pytest.mark.parametrize(
    ("brief", "comment", "review_date", "expected_dl"),
    [
        (None, "31.12.2026", "2026-12-31", "31.12.2026"),
        ({"dl": "20.12.2026", "sq": "Existing detail"}, "31.12.2026", "2026-12-31", "31.12.2026"),
        ({"dl": "15.01", "sq": "Existing detail"}, "31.12.2026", "2026-12-31", "15.01"),
        ({"dl": "20.12.2026"}, "Presim nga klienti", None, "20.12.2026"),
    ],
)
def test_review_comment_persists_with_deadline(brief, comment, review_date, expected_dl):
    note = SimpleNamespace(
        id=uuid.uuid4(),
        content="PX JAV note",
        comment=None,
        status=GaNoteStatus.OPEN,
        is_converted_to_task=False,
        updated_at=datetime(2026, 11, 27, 10, tzinfo=timezone.utc),
        planning_brief=brief,
    )
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[
            Mock(scalar_one_or_none=Mock(return_value=note)),
            Mock(all=Mock(return_value=[])),
        ]),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    payload = PlanNoteUpdate(
        comment=comment, comment_review_date=date.fromisoformat(review_date) if review_date else None,
    )

    with (
        patch("app.api.routers.plan_notes._ensure_note_access", new_callable=AsyncMock),
        patch("app.api.routers.plan_notes._note_out", side_effect=lambda saved: saved),
        patch("app.api.routers.plan_notes.add_audit_log") as audit,
    ):
        saved = asyncio.run(update_plan_note(note.id, payload, db=db, user=SimpleNamespace(id=uuid.uuid4())))

    assert saved.comment == comment
    assert saved.planning_brief == {**(brief or {}), "dl": expected_dl}
    assert audit.call_count == int(saved.planning_brief != brief)
    db.commit.assert_awaited_once()


def test_review_date_requires_comment():
    with pytest.raises(ValidationError, match="A review date requires a comment"):
        PlanNoteUpdate(comment_review_date=date(2026, 12, 31))
