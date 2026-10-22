import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from unittest.mock import AsyncMock, patch

from tests.test_m3_reporting_points import task, DAY
from app.api.routers import m3_reporting_points as api
from app.models.enums import UserRole
from app.services import m3_reporting_points as service
from app.services.m3_reporting_points_attachments import export_blocks
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase


@pytest.mark.parametrize("marker", ["M3", "M2_M3"])
@pytest.mark.parametrize("status", ["TODO", "IN_PROGRESS", "DONE"])
def test_delivery_selects_requested_symbols_in_inclusive_plan_interval(marker, status):
    items = [task(one_h_marker=marker, status=status, start_date=DAY, due_date=date(2026, 10, 9)),
             task(one_h_marker=marker, status=status, start_date=date(2026, 10, 1), due_date=DAY)]
    rows = service.select_task_sections(items, [], DAY)["delivery"]
    assert [row["task_id"] for row in rows] == [str(item.id) for item in items]
    assert rows[0]["marker"] == ("M2/3" if marker == "M2_M3" else marker)


def test_delivery_excludes_other_symbols_and_invalid_or_other_day_intervals():
    items = [task(one_h_marker="M2"), task(one_h_marker="FLAG"),
             task(one_h_marker="M3", start_date=None), task(one_h_marker="M3", due_date=None),
             task(one_h_marker="M3", start_date=date(2026, 10, 6)),
             task(one_h_marker="M3", due_date=date(2026, 10, 4)),
             task(one_h_marker="M3", created_at=date(2026, 10, 6))]
    assert service.select_task_sections(items, [], DAY)["delivery"] == []


def test_delivery_answers_validate_choice_and_export_across_report_formats():
    task_id = str(uuid.uuid4())
    answers = {f"delivery_choice:{task_id}": "PO", f"delivery:{task_id}": "Dorezuar"}
    assert api.ManualAnswersPayload(manual_answers=answers).manual_answers == answers
    with pytest.raises(ValidationError):
        api.ManualAnswersPayload(manual_answers={f"delivery_choice:{task_id}": "YES"})
    with pytest.raises(ValidationError):
        api.ManualAnswersPayload(manual_answers={"delivery:invalid": "text"})
    report = {"report_date": DAY.isoformat(), "manual_answers": answers, "realization": None,
              "data": {"delivery": [{"task_id": task_id, "title": "M3 delivery task", "marker": "M3",
                                      "status": "TODO"}]}}
    for output in (service.render_html(report), service.render_plain_text(report), str(export_blocks(report))):
        assert "5. SA PER DOREZIM M3?" in output
        assert "SA/TOTALI: 1/1" in output
        assert "M3 delivery task" in output
        assert "Dorezuar" in output
        assert output.index("5. SA PER DOREZIM M3?") < output.index("6. REALIZIMI")
    delivery_table = next(block for block in export_blocks(report)
                          if block["kind"] == "table" and any(column[0] == "choice" for column in block["columns"]))
    assert delivery_table["rows"][0][-2]["fill"] == "#16a34a"
    assert delivery_table["rows"][0][-1]["fill"] == "#ffffff"


class DeliveryAnswerTests(IsolatedAsyncioTestCase):
    async def test_delivery_answers_save_only_for_report_tasks(self):
        task_id, missing_id = str(uuid.uuid4()), str(uuid.uuid4())
        row = SimpleNamespace(id=uuid.uuid4(), report_date=DAY, manual_answers={},
                              data={"delivery": [{"task_id": task_id}]})
        user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN)
        db = AsyncMock()
        with patch.object(api, "_by_id", AsyncMock(return_value=row)), \
             patch.object(api, "locked_report", AsyncMock(return_value=row)), \
             patch.object(api, "current_report_payload", AsyncMock(return_value={})), \
             patch.object(api, "add_audit_log"):
            payload = api.ManualAnswersPayload(manual_answers={f"delivery_choice:{task_id}": "PO"})
            await api.save_answers(row.id, payload, db, user)
            assert row.manual_answers == payload.manual_answers
            with pytest.raises(HTTPException) as error:
                await api.save_answers(row.id, api.ManualAnswersPayload(
                    manual_answers={f"delivery:{missing_id}": "Invalid task"}), db, user)
            assert error.value.status_code == 422
