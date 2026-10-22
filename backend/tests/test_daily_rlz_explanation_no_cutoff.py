import asyncio
import uuid
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from app.api.routers import reports
from app.models.enums import TaskStatus, UserRole
from app.models.task import Task
from app.schemas.daily_report import DailyRlzStateUpsert

TZ = ZoneInfo("Europe/Tirane")


@pytest.mark.parametrize("day,now", [
    (date(2026, 10, 22), datetime(2026, 10, 22, 16, 11, tzinfo=TZ)),
    (date(2026, 10, 22), datetime(2026, 10, 22, 17, 0, tzinfo=TZ)),
    (date(2026, 10, 22), datetime(2026, 10, 22, 23, 59, tzinfo=TZ)),
    (date(2026, 10, 22), datetime(2026, 10, 23, 9, 0, tzinfo=TZ)),
    (date(2026, 10, 17), datetime(2026, 10, 18, 18, 0, tzinfo=TZ)),
])
@pytest.mark.parametrize("system", [False, True])
def test_staff_can_save_and_reload_daily_explanations_after_cutoff_and_on_past_days(day, now, system):
    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF)
    task = Task(id=uuid.uuid4(), assigned_to=user.id, is_active=True, status=TaskStatus.TODO,
                system_template_origin_id=uuid.uuid4() if system else None, due_date=day)
    db = SimpleNamespace(get=AsyncMock(return_value=task),
                         execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)),
                         add=Mock(), commit=AsyncMock(), refresh=AsyncMock())
    with patch("app.services.daily_rlz_compliance.tirana_now", return_value=now):
        response = asyncio.run(reports.upsert_daily_rlz_state(
            task.id, DailyRlzStateUpsert(day=day, reason_code="TOOK_LONGER", comment="  Mori më shumë kohë  "),
            db, user))
        saved = db.add.call_args.args[0]
        reloaded = reports._daily_rlz_state_out(saved, day, task=task)
    assert response.is_editable and reloaded.is_editable
    assert response.editable_until is None and reloaded.editable_until is None
    assert response.reason_code == "TOOK_LONGER"
    assert reloaded.comment == "Mori më shumë kohë"
    assert saved.day_date == day and saved.user_id == user.id
    db.commit.assert_awaited_once()


def test_future_day_remains_unavailable_for_daily_evidence():
    day = date(2026, 10, 23)
    db = SimpleNamespace(get=AsyncMock())
    with patch("app.services.daily_rlz_compliance.tirana_now", return_value=datetime(2026, 10, 22, 18, tzinfo=TZ)):
        assert not reports._daily_rlz_state_out(None, day).is_editable
        with pytest.raises(HTTPException) as error:
            asyncio.run(reports.upsert_daily_rlz_state(
                uuid.uuid4(), DailyRlzStateUpsert(day=day, reason_code="OTHER"), db,
                SimpleNamespace(id=uuid.uuid4(), role=UserRole.STAFF)))
    assert error.value.status_code == 409
    db.get.assert_not_awaited()
