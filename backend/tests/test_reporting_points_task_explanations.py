import asyncio
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routers import m2_reporting_points as m2_api, m3_reporting_points as m3_api
from app.api.routers.reports import _daily_rlz_state_out
from app.models.enums import TaskStatus
from app.models.m2_reporting_points import M2ReportingPointsReport
from app.models.m3_reporting_points import M3ReportingPointsReport
from app.models.task import Task
from app.services import m2_reporting_points as m2, m3_reporting_points as m3
from app.services.after_break_report import _unfinished_priority_task_rows
from app.services.m3_reporting_points_attachments import export_blocks
from app.services.primeflow_report import report_timezone


DAY = date(2026, 10, 19)


def result(values):
    value = MagicMock()
    value.scalars.return_value.all.return_value = values
    value.all.return_value = values
    return value


def task(**changes):
    return Task(**{
        "id": uuid.uuid4(), "title": "08:00 Same title", "status": TaskStatus.TODO,
        "start_date": datetime(2026, 10, 19, tzinfo=timezone.utc),
        "due_date": datetime(2026, 10, 19, 9, tzinfo=timezone.utc),
        "created_at": datetime(2026, 10, 18, tzinfo=timezone.utc),
        "finish_period": "AM", "is_active": True, "progress_percentage": 0,
        "completed_at": None, "is_deadline_important": False, "one_h_marker": None, **changes,
    })


@pytest.mark.parametrize("status", [TaskStatus.TODO, TaskStatus.IN_PROGRESS])
@pytest.mark.parametrize("system", [False, True])
def test_my_view_requires_both_fields_for_point_two_tasks(status, system):
    item = task(status=status, system_template_origin_id=uuid.uuid4() if system else None)
    state = _daily_rlz_state_out(None, DAY, task=item)
    assert state.reason_required and state.comment_required
    assert state.reason_missing and state.comment_missing
    saved = SimpleNamespace(reason_code="OTHER", comment="Sqarim ditor", updated_at=None)
    state = _daily_rlz_state_out(saved, DAY, task=item)
    assert not state.reason_missing and not state.comment_missing


def test_shared_morning_table_preserves_duplicate_title_task_identities():
    tasks = [task(), task()]
    cutoff = datetime(2026, 10, 19, 13, 20, tzinfo=report_timezone())
    regular = _unfinished_priority_task_rows(tasks, {}, {}, DAY, cutoff, report_timezone())
    identified = _unfinished_priority_task_rows(tasks, {}, {}, DAY, cutoff, report_timezone(), include_task_id=True)
    assert [row[:9] for row in identified] == regular
    assert {row[9] for row in identified} == {str(item.id) for item in tasks}


def test_m2_enriches_each_task_by_id_and_keeps_priority_order():
    department = SimpleNamespace(id=uuid.uuid4(), code="DEV")
    users = [SimpleNamespace(id=uuid.uuid4(), full_name=name, username=None, email=None,
                             department_id=department.id, weekly_planner_sort_order=index)
             for index, name in enumerate(("Alpha User", "Zoe User"))]
    tasks = [task(assigned_to=user.id, department_id=department.id) for user in users]
    # Reverse the shared table's order to distinguish it from common enrichment.
    shared = [[str(i), "", "DEV", "AM", "TODO", "08:00", "FT", item.title, "SOT", str(item.id)]
              for i, item in enumerate(reversed(tasks), 1)]
    states = [SimpleNamespace(task_id=item.id, user_id=user.id, reason_code="OTHER", comment=f"Comment {index}")
              for index, (item, user) in enumerate(zip(tasks, users))]
    db = AsyncMock()
    db.execute.side_effect = [result([]), result([]), result(tasks), result([]), result(users),
                              result([department]), result([]), result([]), result(users), result(states), result([])]
    with patch.object(m2, "build_unfinished_priority_task_rows", new=AsyncMock(return_value=shared)):
        data = asyncio.run(m2.build_task_data(db, DAY))
    rows = data["unfinished_priority"]
    assert [row["task_id"] for row in rows] == [str(item.id) for item in reversed(tasks)]
    assert [row["comment"] for row in rows] == ["Comment 1", "Comment 0"]
    assert all(row["reason"] == m3.REASON_LABELS["OTHER"] for row in rows)


@pytest.mark.parametrize("service,api,model,section,prefix", [
    (m2, m2_api, M2ReportingPointsReport, "unfinished_priority", "unfinished_comment"),
    (m3, m3_api, M3ReportingPointsReport, "untouched", "untouched_comment"),
])
@pytest.mark.parametrize("original_comment", ["Komenti nga My View", "-"])
def test_report_comment_edits_save_and_export_in_the_existing_column(service, api, model, section, prefix, original_comment):
    task_id = str(uuid.uuid4())
    key = f"{prefix}:{task_id}"
    data = {section: [{"task_id": task_id, "title": "Task", "status": "TODO", "reason": "Arsyeja nga My View", "comment": original_comment}]}
    row = model(id=uuid.uuid4(), report_date=DAY, manual_answers={}, data=data, status="DRAFT")
    payload = api.ManualAnswersPayload(manual_answers={key: "Manual <test>\nVazhdimi"})
    with patch.object(api, "_by_id", new=AsyncMock(return_value=row)), \
         patch.object(api, "locked_report", new=AsyncMock(return_value=row)), \
         patch.object(api, "require_report_manager", new=AsyncMock()), patch.object(api, "add_audit_log"), \
         patch.object(m3, "with_current_task_explanations", new=AsyncMock(side_effect=lambda db, payload, section: payload)):
        report = asyncio.run(api.save_answers(row.id, payload, AsyncMock(), SimpleNamespace(id=uuid.uuid4())))
    assert row.manual_answers[key] == "Manual <test>\nVazhdimi"
    assert row.data == data
    html = service.render_html(report)
    assert "Manual &lt;test&gt;" in html and "Arsyeja nga My View" in html
    assert "Komenti nga My View" not in html
    assert "Manual <test>\nVazhdimi" in service.render_plain_text(report)
    blocks = service.export_blocks(report) if service is m2 else export_blocks(report)
    table = next(block for block in blocks if block["kind"] == "table")
    assert table["rows"][0][-1]["text"] == "Manual <test>\nVazhdimi"
    assert [column[1] for column in table["columns"]].count("KOMENTI") == 1
    assert "KOMENT MANUAL" not in [column[1] for column in table["columns"]]
    # Clearing an edited report comment must not restore the My View text.
    report["manual_answers"][key] = ""
    blocks = service.export_blocks(report) if service is m2 else export_blocks(report)
    assert next(block for block in blocks if block["kind"] == "table")["rows"][0][-1]["text"] == "-"
    invalid = api.ManualAnswersPayload(manual_answers={f"{prefix}:{uuid.uuid4()}": "Other task"})
    with patch.object(api, "_by_id", new=AsyncMock(return_value=row)), \
         patch.object(api, "locked_report", new=AsyncMock(return_value=row)), \
         patch.object(api, "require_report_manager", new=AsyncMock()):
        with pytest.raises(HTTPException) as error:
            asyncio.run(api.save_answers(row.id, invalid, AsyncMock(), SimpleNamespace(id=uuid.uuid4())))
    assert error.value.status_code == 422
    with pytest.raises(ValidationError):
        api.ManualAnswersPayload(manual_answers={f"{prefix}:invalid": "Invalid"})


def test_today_m2_legacy_rows_are_refreshed_to_make_comment_cells_editable():
    today = datetime.now(report_timezone()).date()
    task_id = str(uuid.uuid4())
    row = M2ReportingPointsReport(id=uuid.uuid4(), report_date=today, data={"unfinished_priority": [{"title": "Legacy task"}]}, manual_answers={"reorganization": "Keep answer"})
    db = AsyncMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=lambda: row)

    async def refresh(db, report):
        report.data = {"unfinished_priority": [{"task_id": task_id, "title": "Legacy task"}]}

    with patch.object(m2_api, "refresh_report", new=AsyncMock(side_effect=refresh)) as regenerate, \
         patch.object(m2_api, "current_report_payload", new=AsyncMock(side_effect=lambda db, report: m2.report_payload(report))):
        payload = asyncio.run(m2_api.get_report(today, db, SimpleNamespace()))
    assert payload["data"]["unfinished_priority"][0]["task_id"] == task_id
    assert payload["manual_answers"]["reorganization"] == "Keep answer"
    regenerate.assert_awaited_once_with(db, row)
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("section", ["untouched", "unfinished_priority"])
def test_today_reads_latest_day_evidence_without_mutating_snapshot_or_manual_comment(section):
    today = datetime.now(report_timezone()).date()
    task_id, user_id = uuid.uuid4(), uuid.uuid4()
    rows = [{"task_id": str(task_id), "reason": "Old reason", "comment": "Old comment"}]
    payload = {"report_date": today.isoformat(), "data": {section: rows}, "manual_answers": {"some_key": "Manual"}}
    db = AsyncMock()
    db.execute.side_effect = [result([SimpleNamespace(task_id=task_id, user_id=user_id, reason_code="OTHER", comment="New comment")]),
                              result([SimpleNamespace(id=user_id, full_name="User", username=None, email=None)])]
    updated = asyncio.run(m3.with_current_task_explanations(db, payload, section))
    assert updated["data"][section][0]["comment"] == "New comment"
    assert rows[0]["comment"] == "Old comment"
    assert updated["manual_answers"] == payload["manual_answers"]
    query = db.execute.await_args_list[0].args[0]
    assert "task_daily_rlz_states.day_date" in str(query)
    assert today in query.compile().params.values()
    historical = {**payload, "report_date": "2026-01-01"}
    db.reset_mock()
    assert asyncio.run(m3.with_current_task_explanations(db, historical, section)) is historical
    db.execute.assert_not_awaited()
