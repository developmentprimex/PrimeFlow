import asyncio
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import Column, MetaData, Table, Uuid, create_engine, select
from sqlalchemy.orm import Session

from app.api.routers.realization import confirm_daily_realization_task, decide_daily_plan_adjustment
from app.models.enums import UserRole
from app.models.realization_task_confirmation import RealizationTaskConfirmation
from app.schemas.realization import RealizationTaskConfirmationRequest, DailyPlanAdjustmentDecision
from app.services.daily_realization_metrics import calculate_daily_metrics
from app.services.realization_task_confirmation import can_confirm_realization_task, task_confirmation_evidence
from app.services.realization_weekly_metrics import build_weekly_task_metrics


@pytest.mark.parametrize("name,username,active,expected", [
    ("Laurent Hoxha", "laurent", True, True),
    ("Diellza Veliu", "diellza.veliu", True, True),
    ("Other admin", "admin", True, False),
    ("Other manager", "manager", True, False),
    ("Diellza Veliu", "diellza.veliu", False, False),
])
def test_only_designated_active_accounts_can_confirm(name, username, active, expected):
    actor = SimpleNamespace(full_name=name, username=username, is_active=active, role=UserRole.ADMIN)
    assert can_confirm_realization_task(actor) is expected


@pytest.mark.parametrize("role", list(UserRole))
def test_other_roles_cannot_bypass_either_confirmation_endpoint(role):
    actor = SimpleNamespace(role=role, full_name="Someone else", username="other")
    db = SimpleNamespace(execute=AsyncMock())
    task_id, user_id = uuid.uuid4(), uuid.uuid4()
    payload = RealizationTaskConfirmationRequest(user_id=user_id, day=date(2026, 9, 1), confirmed=True, evidence_key="a"*64)
    adjustment = DailyPlanAdjustmentDecision(user_id=user_id, audit_event_id=uuid.uuid4(), status="APPROVED", reason="checked")
    for call in (confirm_daily_realization_task(task_id, payload, db, actor), decide_daily_plan_adjustment(task_id, adjustment, db, actor)):
        with pytest.raises(HTTPException) as error:
            asyncio.run(call)
        assert error.value.status_code == 403
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("classification,deadline,critical,penalty", [
    ("NO_PROGRESS", False, False, 25),
    ("POSTPONED_UNAPPROVED", False, False, 25),
    ("IN_PROGRESS", True, False, 30),
    ("POSTPONED_UNAPPROVED", True, True, 60),
])
def test_confirmation_removes_only_penalty_and_revocation_restores_it(classification, deadline, critical, penalty):
    done = {"task_id": "done", "classification": "REALIZED_AS_PLANNED", "in_original_plan": True}
    pending = {"task_id": "open", "classification": classification, "in_original_plan": True,
               "deadline_was_today": deadline, "deadline_critical": critical}
    original = calculate_daily_metrics([done, pending])
    confirmed = calculate_daily_metrics([done, {**pending, "penalty_confirmation": {"confirmed": True}}])
    revoked = calculate_daily_metrics([done, {**pending, "penalty_confirmation": {"confirmed": False}}])
    assert original["realization_penalty_points"] == penalty
    assert confirmed["realization_penalty_points"] == 0
    assert confirmed["raw_plan_realization"] == 50
    assert confirmed["total_completed_today_count"] == original["total_completed_today_count"] == 1
    assert confirmed["realization_plan_weight"] == original["realization_plan_weight"] == 2
    assert revoked["raw_plan_realization"] == original["raw_plan_realization"]
    week = build_weekly_task_metrics([], [{"date": "2026-09-01", "tasks": [done, {**pending, "penalty_confirmation": {"confirmed": True}}]}])
    assert week["weekly_penalty_points"] == 0
    assert week["weekly_progress_percent"] == 50


def test_new_deadline_progress_or_postponement_invalidates_confirmation_evidence():
    row = {"classification": "POSTPONED_UNAPPROVED", "current_due_date": "2026-09-02", "progress_today": 0,
           "timeline": [{"id": "first", "type": "POSTPONED"}]}
    key = task_confirmation_evidence(row)
    for changed in ({"current_due_date": "2026-09-03"}, {"progress_today": 20}, {"classification": "IN_PROGRESS"},
                    {"timeline": [*row["timeline"], {"id": "second", "type": "POSTPONED_AGAIN"}]}):
        assert task_confirmation_evidence({**row, **changed}) != key
    assert task_confirmation_evidence({**row, "penalty_confirmation": {"confirmed": True}}) == key


def test_confirmed_extra_deadline_remains_visible_for_revocation():
    item = calculate_daily_metrics([{
        "task_id": "extra", "classification": "ADDED_DURING_DAY", "in_original_plan": False,
        "deadline_was_today": True, "penalty_confirmation": {"confirmed": True},
    }])["realization_items"][0]
    assert item["kind"] == "EXTRA_OPEN"
    assert item["unconfirmed_penalty"] == 30
    assert item["penalty"] == 0


def test_endpoint_persists_confirmation_revocation_and_rejects_stale_evidence():
    metadata = MetaData()
    for name in ("tasks", "users"):
        Table(name, metadata, Column("id", Uuid, primary_key=True))
    RealizationTaskConfirmation.__table__.to_metadata(metadata)
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    subject = SimpleNamespace(id=uuid.uuid4(), department_id=uuid.uuid4())
    actor = SimpleNamespace(id=uuid.uuid4(), full_name="Laurent Hoxha", username="laurent")
    task_id = uuid.uuid4()
    item = {"task_id": str(task_id), "unconfirmed_penalty": 25, "confirmation_evidence_key": "a"*64}
    live = {"people": [{"metrics": {"realization_items": [item]}}]}

    class Result:
        def scalar_one_or_none(self): return subject

    with Session(engine) as session:
        class AsyncSession:
            def __init__(self): self.calls = 0
            async def execute(self, stmt):
                self.calls += 1
                return Result() if self.calls % 2 == 1 else session.execute(stmt)
            def add(self, obj): session.add(obj)
            async def flush(self): session.flush()
            async def commit(self): session.commit()
        db = AsyncSession()
        with patch("app.api.routers.realization.build_live_daily_realization", AsyncMock(return_value=live)), patch("app.api.routers.realization.add_audit_log") as audit:
            for confirmed in (True, False, True):
                payload = RealizationTaskConfirmationRequest(user_id=subject.id, day=date(2026, 9, 1), confirmed=confirmed, evidence_key="a"*64)
                response = asyncio.run(confirm_daily_realization_task(task_id, payload, db, actor))
                assert response["confirmed"] is confirmed
                stored = session.execute(select(RealizationTaskConfirmation)).scalar_one()
                assert stored.confirmed is confirmed
                assert stored.user_id == subject.id and stored.task_id == task_id
                assert stored.decided_by == actor.id
            assert audit.call_count == 3
            assert audit.call_args_list[1].kwargs["action"] == "revoke"
            item["confirmation_evidence_key"] = "b"*64
            with pytest.raises(HTTPException) as error:
                asyncio.run(confirm_daily_realization_task(task_id, payload, db, actor))
            assert error.value.status_code == 409
            assert audit.call_count == 3
