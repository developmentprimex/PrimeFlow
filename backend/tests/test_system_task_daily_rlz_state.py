import asyncio
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException

from app.api.routers.reports import _daily_rlz_state_out, upsert_daily_rlz_state
from app.models.enums import TaskStatus, UserRole
from app.models.task import Task
from app.schemas.daily_report import DailyRlzStateUpsert
from app.services.daily_rlz_compliance import task_issue_codes


DAY = date(2026, 10, 1)


def test_todo_system_task_daily_reason_and_comment_can_be_saved():
    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF)
    task = Task(
        id=uuid.uuid4(), assigned_to=user.id, is_active=True, status=TaskStatus.TODO,
        system_template_origin_id=uuid.uuid4(),
    )
    db = SimpleNamespace(
        get=AsyncMock(return_value=task),
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)),
        add=Mock(), commit=AsyncMock(), refresh=AsyncMock(),
    )
    payload = DailyRlzStateUpsert(
        day=DAY, reason_code="TECHNICAL_PROBLEM", comment="  U kontrollua sistemi  ",
    )

    with patch("app.api.routers.reports.is_explanation_editable_day", return_value=True):
        response = asyncio.run(upsert_daily_rlz_state(task.id, payload, db=db, user=user))
        saved = db.add.call_args.args[0]
        reloaded = _daily_rlz_state_out(saved, DAY, system_task=task)

    assert (saved.task_id, saved.user_id, saved.day_date) == (task.id, user.id, DAY)
    assert response.reason_code == reloaded.reason_code == "TECHNICAL_PROBLEM"
    assert response.comment == reloaded.comment == "U kontrollua sistemi"
    assert response.reason_required and response.comment_required
    assert reloaded.reason_required and reloaded.comment_required
    assert not reloaded.reason_missing and not reloaded.comment_missing
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(saved)


@pytest.mark.parametrize("status", list(TaskStatus))
def test_open_system_tasks_require_explanation_even_without_rlz_membership(status):
    task = Task(status=status, system_template_origin_id=uuid.uuid4())
    system = _daily_rlz_state_out(None, DAY, system_task=task)
    regular = _daily_rlz_state_out(None, DAY)

    expected = status in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}
    assert system.requires_explanation == expected
    assert system.reason_required == system.comment_required == expected
    assert system.reason_missing == system.comment_missing == expected
    assert not regular.reason_required and not regular.comment_required
    assert task_issue_codes(
        status="DONE", due_date=DAY, requires_one_h_slot=False,
        one_h_report_slot=None, reason_code=None, comment=None, day=DAY,
        is_system_task=True,
    ) == []


def test_completed_system_task_keeps_saved_evidence_without_editable_fields():
    task = Task(
        status=TaskStatus.TODO, system_template_origin_id=uuid.uuid4(),
        completed_at=datetime(2026, 10, 1, 9, tzinfo=timezone.utc),
    )
    saved = SimpleNamespace(reason_code="OTHER", comment="Koment i ruajtur", updated_at=None)
    state = _daily_rlz_state_out(saved, DAY, system_task=task)

    assert not state.reason_required and not state.comment_required
    assert state.reason_code == "OTHER" and state.comment == "Koment i ruajtur"


def test_system_explanation_rejects_future_day():
    db = SimpleNamespace(get=AsyncMock())
    task = Task(status=TaskStatus.TODO, system_template_origin_id=uuid.uuid4())
    with patch("app.api.routers.reports.is_explanation_editable_day", return_value=False):
        state = _daily_rlz_state_out(None, DAY, system_task=task)
        with pytest.raises(HTTPException) as error:
            asyncio.run(upsert_daily_rlz_state(
                uuid.uuid4(), DailyRlzStateUpsert(day=DAY, comment="Koment"),
                db=db, user=SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF),
            ))

    assert state.reason_required and state.comment_required and not state.is_editable
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "DAILY_RLZ_FUTURE_DAY"
    db.get.assert_not_awaited()


def test_staff_cannot_comment_another_employees_system_task():
    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF)
    task = Task(
        id=uuid.uuid4(), assigned_to=uuid.uuid4(), is_active=True,
        system_template_origin_id=uuid.uuid4(), status=TaskStatus.DONE,
        completed_at=datetime(2026, 10, 1, 9, tzinfo=timezone.utc),
    )
    db = SimpleNamespace(get=AsyncMock(return_value=task), scalar=AsyncMock(return_value=None))

    with patch("app.api.routers.reports.is_explanation_editable_day", return_value=True):
        with pytest.raises(HTTPException) as error:
            asyncio.run(upsert_daily_rlz_state(
                task.id, DailyRlzStateUpsert(day=DAY, comment="Koment"), db=db, user=user,
            ))

    assert error.value.status_code == 403
