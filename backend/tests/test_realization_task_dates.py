import uuid
import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.realization_task_dates import start_dates_for_day
from app.api.routers.realization import get_daily_task_timeline
from app.models.enums import UserRole


def event(day, old, new):
    return SimpleNamespace(id=uuid.uuid4(), created_at=datetime(2026, 11, day, 10, tzinfo=timezone.utc),
                           before={"value": old}, after={"value": new})


def test_start_dates_recover_original_and_final_after_multiple_moves():
    result = start_dates_for_day(events=[event(3, "2026-11-02", "2026-11-04"), event(3, "2026-11-04", "2026-11-05")],
                                 day=date(2026, 11, 3), current_start=date(2026, 11, 8))
    assert result == {"original_start_date": "2026-11-02", "start_date_on_day": "2026-11-05"}


def test_later_move_does_not_rewrite_start_date_for_historical_day():
    result = start_dates_for_day(events=[event(4, "2026-11-02", "2026-11-08")],
                                 day=date(2026, 11, 3), current_start=date(2026, 11, 8))
    assert result == {"original_start_date": "2026-11-02", "start_date_on_day": "2026-11-02"}


def test_existing_start_and_missing_start_have_distinct_evidence():
    result = start_dates_for_day(events=[event(2, None, "2026-11-03")], day=date(2026, 11, 3), current_start=None)
    assert result["original_start_date"] == result["start_date_on_day"] == "2026-11-03"
    result = start_dates_for_day(events=[event(3, None, "2026-11-04")], day=date(2026, 11, 3), current_start=date(2026, 11, 4))
    assert result["original_start_date"] is None
    assert result["start_date_on_day"] == "2026-11-04"


def test_task_details_exposes_historical_dates_and_latest_confirmation_item():
    task_id, user_id, department_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    item = {"task_id": str(task_id), "confirmation_evidence_key": "a" * 64}
    task = {"task_id": str(task_id), "timeline": [{"id": "move", "type": "POSTPONED", "old_value": "2026-11-03", "new_value": "2026-11-05"}]}
    live = {"people": [{"tasks": [task], "metrics": {"realization_items": [item]}}]}
    class Result:
        def scalars(self): return self
        def all(self): return [event(3, "2026-11-01", "2026-11-04")]
    db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(start_date=datetime(2026, 11, 9, tzinfo=timezone.utc))), execute=AsyncMock(return_value=Result()))
    actor = SimpleNamespace(role=UserRole.ADMIN, id=uuid.uuid4())
    with patch("app.api.routers.realization.build_live_daily_realization", AsyncMock(return_value=live)):
        result = asyncio.run(get_daily_task_timeline(task_id, date(2026, 11, 3), user_id, department_id, db, actor))
    assert result["task"]["original_start_date"] == "2026-11-01"
    assert result["task"]["start_date_on_day"] == "2026-11-04"
    assert result["confirmation_item"] == item
    assert result["task"]["timeline"][0]["new_value"] == "2026-11-05"
