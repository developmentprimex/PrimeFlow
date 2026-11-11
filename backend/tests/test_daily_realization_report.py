import pytest
import os
import asyncio
import copy
import re
import uuid
from datetime import date
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-long-enough-for-tests")

from app.services import daily_realization_report as report_service
from app.services.daily_realization_report import _build_authoritative_report, _summary, report_delta
from app.services.daily_rlz_control_delivery import (
    DEFAULT_VARIANT_TIMES, _deadline_display, final_recipient_map, render_html, render_plain, subject_for,
)
from app.services.note_markup import marked_task_html, marked_task_plain_lines, parse_marked_note_content

DAY = date(2026, 8, 17)


def _metrics():
    return {
        "original_planned_count": 1, "planned_completed_today_count": 0,
        "in_progress_count": 1, "postponed_count": 0, "no_progress_count": 0,
        "additional_completed_count": 0, "total_completed_today_count": 0,
        "raw_plan_realization": 0.0, "adjusted_plan_realization": 0.0,
        "deadlines_today_count": 1, "deadlines_completed_count": 0,
        "deadlines_postponed_count": 0, "deadlines_open_count": 1,
        "overdue_open_count": 0, "critical_deadlines_open_count": 0,
        "deadline_compliance_percentage": 0.0, "daily_control_state": "ACTION_REQUIRED",
    }


def _report(comment="Fillestar"):
    task = {
        "task_id": "task-1", "title": "Integrimi", "status": "IN_PROGRESS",
        "current_status": "IN_PROGRESS", "classification": "IN_PROGRESS",
        "in_original_plan": True, "planned_today": True, "completed_today": False,
        "extra": False, "postponed": False, "postponed_today": False,
        "original_daily_plan": DAY.isoformat(), "planned_due_date": DAY.isoformat(),
        "due_date": "2026-08-18", "reason_code": "WAITING_CLIENT",
        "reason_label": "Në pritje të klientit", "comment": comment,
        "one_h_report_slot": None, "issues": [], "flags": [],
        "deadline_was_today": True, "deadline_completed": False,
        "deadline_is_overdue": False, "deadline_critical": False,
        "action_required": True, "is_bllok": False,
    }
    metrics = _metrics()
    return {
        "content_version": 3, "variant": "FINAL", "day": DAY.isoformat(),
        "summary": {**metrics, "employees_checked": 1}, "all_good": False,
        "people": [{
            "user_id": "user-1", "employee": "Elsa", "department_id": "dep-1",
            "department": "Development", "daily_progress_percent": 0,
            "weekly_progress_percent": 0, "rlz_close_state": {"status": "SAVED"},
            "manager_approval": {"status": "APPROVED"}, "control_state": "ACTION_REQUIRED",
            "metrics": metrics, "tasks": [task], "narrative": None,
        }], "narrative": None,
    }


def test_report_variant_schedule_and_required_recipients():
    assert DEFAULT_VARIANT_TIMES == {"PRECHECK": "16:10", "FINAL": "16:40", "CORRECTION": "17:05"}
    merged = final_recipient_map({"to": ["GA@primexeu.com"], "cc": ["ga@primexeu.com"], "bcc": ["extra@example.com"]})
    flattened = [email.casefold() for values in merged.values() for email in values]
    assert flattened.count("ga@primexeu.com") == 1
    assert flattened.count("130primex.eu@gmail.com") == 1


def test_authoritative_summary_uses_shared_daily_metrics():
    summary = _summary(_report()["people"])
    assert summary["original_planned_count"] == 1
    assert summary["in_progress_count"] == 1
    assert summary["deadlines_today_count"] == 1
    assert summary["deadline_compliance_percentage"] == 0.0


def test_correction_contains_only_material_changes():
    before = _report()
    assert report_delta(before, _report())["people"] == []
    changed = report_delta(before, _report(comment="Klienti u përgjigj"))
    assert changed["people"][0]["tasks"][0]["change_type"] == "UPDATED"


def test_final_email_contains_complete_manager_story_and_semantic_colors():
    report = _report()
    plain, html = render_plain(report, "16:40"), render_html(report, "16:40")
    assert subject_for(DAY, "16:40", "FINAL") == "[PrimeFlow] Realizimi ditor FINAL - 17/08/2026 - 16:40"
    for value in ("Plan RLZ", "Deadline Compliance", "KËRKON VEPRIM", "Aprovimi", "Integrimi", "Në pritje të klientit", "Fillestar"):
        assert value in plain
    for value in ("KRYER NGA PLANI", "NË PROGRES", "DEADLINE SOT", "KONTROLLI I AFATEVE", "Elsa", "Development"):
        assert value in html
    assert "#FFFF00" in html
    assert "BLOCKED" not in html


def test_marked_task_renderer_preserves_px_notes_semantics_and_structure():
    content = "LH: RLZ DITOR\n[[done]]Kontrollo planin[[/done]]\n[[added]]Dërgo raportin[[/added]]"
    parsed = parse_marked_note_content(content)
    rendered = marked_task_html(content, 1)
    assert parsed.text.splitlines() == ["LH: RLZ DITOR", "Kontrollo planin", "Dërgo raportin"]
    assert marked_task_plain_lines(content, 1) == ["1. LH: RLZ DITOR", "   Kontrollo planin", "   Dërgo raportin"]
    assert "font:700 11px" in rendered
    assert "text-decoration:line-through" in rendered
    assert "background:#BFDBFE" in rendered
    assert "[[done]]" not in rendered and "[[added]]" not in rendered


def test_final_email_numbers_tasks_per_employee_and_shows_manager_decision_evidence():
    report = _report()
    first = report["people"][0]
    first["rlz_close_state"] = {
        "status": "SAVED", "saved_at": "2026-08-17T14:18:00+00:00", "closed_by_name": "Elsa",
    }
    task = first["tasks"][0]
    task.update({
        "title": "Titulli\n[[done]]Pika e kryer[[/done]]\n[[added]]Pika e re[[/added]]",
        "adjustment_status": "APPROVED",
        "manager_decision": {
            "status": "APPROVED", "reason": "Kapaciteti", "comment": "Vazhdo më 28.08.",
            "decided_by_name": "Marie", "decided_at": "2026-08-17T13:05:00+00:00",
        },
    })
    second = copy.deepcopy(first)
    second.update({"user_id": "user-2", "employee": "Laurent"})
    second["tasks"] = [{**task, "task_id": "task-2", "title": "Detyra e dytë"}]
    report["people"].append(second)
    rendered = render_html(report, "16:40")
    assert rendered.count('width="22"') == 2
    assert rendered.count(">1.</td>") == 2
    assert "text-decoration:line-through" in rendered and "background:#BFDBFE" in rendered
    assert "Aprovuar" in rendered and "Marie" in rendered and "15:05" in rendered
    assert "Vazhdo më 28.08." in rendered
    assert "DITA E MBYLLUR" in rendered and "Elsa · 16:18" in rendered
    assert "[[done]]" not in rendered and "[[added]]" not in rendered


def test_bll_is_metadata_not_blocked_or_red():
    report = _report()
    report["people"][0]["tasks"][0]["is_bllok"] = True
    html = render_html(report, "16:40")
    assert "BLL" in html and "BLOCKED" not in html and "#FFFF00" in html


def test_final_email_uses_done_todo_and_critical_deadline_colors():
    report = _report()
    base = report["people"][0]["tasks"][0]
    done = {**base, "task_id": "done", "title": "Done", "status": "DONE", "classification": "REALIZED_AS_PLANNED", "deadline_completed": True}
    todo = {**base, "task_id": "todo", "title": "Todo", "status": "TODO", "classification": "NO_PROGRESS", "deadline_critical": True}
    report["people"][0]["tasks"] = [done, todo]
    html = render_html(report, "16:40")
    assert "#C4FDC4" in html and "#FFC4ED" in html and "#DC2626" in html


def test_deadline_display_distinguishes_future_plan_and_move_back_history():
    assert _deadline_display({"planned_due_date": "2026-08-29", "due_date": "2026-08-29", "timeline": []}) == "2026-08-29"
    assert _deadline_display({"timeline": [
        {"type": "POSTPONED", "old_value": "2026-08-26", "new_value": "2026-08-27"},
        {"type": "MOVED_BACK_TO_TODAY", "old_value": "2026-08-27", "new_value": "2026-08-26"},
    ]}) == "2026-08-26 → 2026-08-27 → 2026-08-26"


def test_final_manager_report_shows_overdue_task_causing_action_required():
    report = _report()
    overdue = {
        **report["people"][0]["tasks"][0],
        "task_id": "overdue-1", "title": "Detyrë e vonuar",
        "status": "TODO", "current_status": "TODO", "classification": "NO_PROGRESS",
        "in_original_plan": False, "planned_today": False,
        "planned_due_date": None, "due_date": "2026-08-16",
        "deadline_was_today": False, "deadline_is_overdue": True,
        "deadline_completed": False, "action_required": True,
    }
    report["people"][0]["tasks"] = [overdue]
    report["people"][0]["metrics"].update({
        "original_planned_count": 0, "no_progress_count": 1,
        "overdue_open_count": 1, "daily_control_state": "ACTION_REQUIRED",
    })
    report["summary"].update(report["people"][0]["metrics"])
    plain, html = render_plain(report, "16:40"), render_html(report, "16:40")
    assert "Detyrë e vonuar" in plain and "Detyrë e vonuar" in html
    assert "KËRKON VEPRIM" in plain and "KËRKON VEPRIM" in html
    assert "ACTION_REQUIRED" not in plain and "ACTION_REQUIRED" not in html
    assert "2026-08-16" in plain and "16.08" in html


def test_final_html_is_compact_humanized_and_retains_manager_evidence():
    report = _report()
    base = report["people"][0]["tasks"][0]
    base.update({
        "reason_code": "REQUEST_CHANGE", "reason_label": "Ndryshim kërkese",
        "comment": "Klienti kërkoi që fillimisht të ndryshojë plani.",
        "one_h_report_slot": "14:20", "adjustment_status": "PENDING",
        "timeline": [{"type": "POSTPONED", "old_value": "2026-08-17", "new_value": "2026-08-18"}],
    })
    missing = {
        **base, "task_id": "task-missing", "title": "Detyrë që kërkon sqarim",
        "status": "TODO", "classification": "NO_PROGRESS", "reason_code": None,
        "reason_label": None, "comment": None, "reason_missing": True, "comment_missing": True,
        "issues": ["MISSING_REASON", "MISSING_REQUIRED_COMMENT", "DUE_DATE_NOT_MOVED", "ONE_H_SLOT_MISSING"],
        "deadline_is_overdue": True, "deadline_critical": True, "one_h_report_slot": None,
    }
    done = {**base, "task_id": "task-done", "title": "Detyrë e kryer", "classification": "REALIZED_AS_PLANNED", "status": "DONE"}
    report["people"][0]["tasks"] = [base, missing, done]
    report["people"][0]["rlz_close_state"] = {"status": "NOT_SAVED"}
    second = copy.deepcopy(report["people"][0])
    second.update({"user_id": "user-2", "employee": "Laurent Hoxha"})
    second["tasks"] = [{**base, "task_id": "task-second", "title": "Detyra e Laurent"}]
    report["people"].append(second)

    rendered = render_html(report, "16:40")

    assert 'width="940"' in rendered
    assert "PËRMBLEDHJA E REALIZIMIT" in rendered
    assert "PËRMBLEDHJA SIPAS STAFIT" in rendered
    assert "DETAJET SIPAS STAFIT" in rendered
    header_rows = re.findall(r"<tr[^>]*>(?:(?!</tr>).)*<th(?:(?!</tr>).)*</tr>", rendered)
    assert header_rows and max(row.count("<th") for row in header_rows) == 8
    assert any(row.count("<th") == 5 for row in header_rows)
    for label in ("STAFI", "PLAN", "KRYER", "NË PROGRES", "PA PROGRES", "EKSTRA", "PLAN RLZ", "GJENDJA"):
        assert f">{label}</th>" in rendered
    for label in ("DETYRA", "REZULTATI", "PLAN / AFATI", "SQARIMI", "KONTROLLI"):
        assert f">{label}</th>" in rendered
    for color in ("#2563EB", "#C4FDC4", "#FFFF00", "#FFC4ED", "#DC2626"):
        assert color in rendered
    for forbidden in ("MISSING_REASON", "COMMENT_MISSING", "MISSING_REQUIRED_COMMENT", "DUE_DATE_NOT_MOVED", "ONE_H_SLOT_MISSING", "NOT_SAVED", "ACTION_REQUIRED", "REQUEST_CHANGE", "PRIORITY_CHANGE"):
        assert forbidden not in rendered
    for visible in ("Kërkon sqarim", "Mungon arsyeja dhe komenti", "DITA E HAPUR", "KËRKON VEPRIM", "Elsa", "Laurent Hoxha", "Integrimi", "Detyrë që kërkon sqarim", "Detyrë e kryer", "Detyra e Laurent", "Plan RLZ", "DEADLINE COMPLIANCE", "Ndryshim kërkese", "Klienti kërkoi", "17.08 → 18.08", "1H 14:20", "Pret aprovim"):
        assert visible in rendered


def test_final_builder_consumes_live_metrics_and_day_scoped_compliance(monkeypatch):
    user_id, department_id = uuid.uuid4(), uuid.uuid4()
    user = SimpleNamespace(id=user_id, department_id=department_id, full_name="DV", username="dv", email="dv@example.com")
    department = SimpleNamespace(id=department_id, name="PCM")

    class Scalars:
        def __init__(self, values): self.values = values
        def all(self): return self.values
    class Result:
        def __init__(self, values): self.values = values
        def scalars(self): return Scalars(self.values)
    class Db:
        def __init__(self): self.results = [[user], [department]]
        async def execute(self, _statement): return Result(self.results.pop(0))

    task = dict(_report()["people"][0]["tasks"][0])
    task.update({
        "current_status": "IN_PROGRESS", "baseline_due_date": DAY.isoformat(),
        "current_due_date": "2026-08-18", "project_title": "PrimeFlow",
    })
    live_metrics = _metrics()

    async def live(*_args, **_kwargs):
        return {"baseline_available": True, "people": [{"user_id": str(user_id), "tasks": [task], "metrics": live_metrics}]}
    async def compliance(*_args, **_kwargs):
        return {
            "tasks": [{"task_id": "task-1", "reason_label": "Në pritje të klientit", "one_h_report_slot": None}],
            "blockers": [], "rlz_close_state": {"status": "SAVED"},
            "manager_approval": {"status": "APPROVED"},
        }
    monkeypatch.setattr(report_service, "build_live_daily_realization", live)
    monkeypatch.setattr(report_service, "build_daily_rlz_compliance", compliance)

    report = asyncio.run(_build_authoritative_report(Db(), day=DAY, variant="FINAL"))
    person = report["people"][0]
    assert person["metrics"] == live_metrics
    assert person["tasks"][0]["comment"] == "Fillestar"
    assert person["tasks"][0]["reason_label"] == "Në pritje të klientit"
    assert report["summary"]["original_planned_count"] == live_metrics["original_planned_count"]


from tests.report_attendance_fixtures import present_report_population
