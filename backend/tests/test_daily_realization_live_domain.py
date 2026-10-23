from __future__ import annotations

import inspect
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.daily_planner_snapshot import DailyPlannerSnapshot
from app.services.daily_realization_baseline import _daily_payload, ensure_daily_baseline
from app.services.daily_realization_classifier import DailyClassificationInput, classify_daily_task
from app.services.daily_realization_events import semantic_local_day
from app.services.daily_realization_explanation import requires_daily_explanation
from app.services.daily_realization_live import (
    additional_task_has_day_evidence, candidate_task_ids_for_person,
    credited_completion_day, day_bounds, local_day,
    manager_decision_timeline_item, timeline_from_events,
)
from app.services.daily_realization_metrics import calculate_daily_metrics, multi_day_share
from app.services.daily_realization_close_state import resolve_daily_close_state


DAY = date(2026, 8, 26)


@pytest.mark.parametrize("leave_day, expected_planned", [(DAY, 1), (date(2026, 8, 27), 3)])
def test_live_daily_labels_full_day_leave_without_counting_its_tasks(monkeypatch, leave_day, expected_planned):
    import asyncio
    from app.models.user import User
    from app.services import daily_realization_live as live_service
    from app.services.realization_people import CommonLeaveCoverage

    department_id = uuid.uuid4()
    active, on_leave, empty = [
        SimpleNamespace(id=uuid.uuid4(), full_name=name)
        for name in ("Active", "PV", "Empty")
    ]
    users = [active, on_leave, empty]
    def planned_task():
        return {"task_id": str(uuid.uuid4()), "planned_due_date": DAY.isoformat()}
    baseline = SimpleNamespace(id=uuid.uuid4(), captured_at=datetime(2026, 8, 26, tzinfo=timezone.utc), payload={"people": [
        {"user_id": str(active.id), "tasks": [planned_task()]},
        {"user_id": str(on_leave.id), "tasks": [planned_task(), planned_task()]},
    ]})

    async def load_people(*args, **kwargs):
        return users, {on_leave.id: CommonLeaveCoverage(frozenset({leave_day}), ())}
    monkeypatch.setattr(live_service, "load_active_users_and_common_leave", load_people)

    class Result:
        def __init__(self, rows=(), scalar=None):
            self.rows, self.scalar = rows, scalar
        def scalar_one_or_none(self): return self.scalar
        def scalars(self): return self
        def all(self): return self.rows

    class Session:
        async def execute(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            if entity is DailyPlannerSnapshot: return Result(scalar=baseline)
            if entity is User: return Result(users)
            return Result()

    result = asyncio.run(live_service.build_live_daily_realization(
        Session(), department_id=department_id, day=DAY,
    ))
    expected_users = {str(active.id), str(on_leave.id)}
    assert {person["user_id"] for person in result["people"]} == expected_users
    leave_person = next(person for person in result["people"] if person["user_id"] == str(on_leave.id))
    assert leave_person.get("availability_status") == ("PV" if leave_day == DAY else None)
    assert result["metrics"]["original_planned_count"] == expected_planned
    assert result["metrics"]["raw_plan_realization"] == 0


@pytest.mark.parametrize("historical_status, current_status, expected", [
    ("IN_PROGRESS", "DONE", "IN_PROGRESS"),
    ("TODO", "IN_PROGRESS", "NO_PROGRESS"),
    ("WAITING_CLIENT", "DONE", "NO_PROGRESS"),
    (None, "IN_PROGRESS", "IN_PROGRESS"),
])
def test_later_status_changes_preserve_daily_outcomes(monkeypatch, historical_status, current_status, expected):
    import asyncio
    from sqlalchemy.dialects import postgresql
    from app.models.audit_log import AuditLog
    from app.models.task import Task
    from app.models.user import User
    from app.services import daily_realization_live as live_service

    person_id, task_id, department_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    person = SimpleNamespace(id=person_id, full_name="Daily history")
    next_day = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)
    task = Task(
        id=task_id, title="Historical task", assigned_to=person_id,
        status=current_status, created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        updated_at=next_day, due_date=next_day,
        completed_at=next_day if current_status == "DONE" else None,
    )
    baseline = SimpleNamespace(
        id=uuid.uuid4(), captured_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        payload={"people": [{"user_id": str(person_id), "tasks": [
            {"task_id": str(task_id), "planned_due_date": "2026-08-27"},
        ]}]},
    )

    async def load_people(*args, **kwargs):
        return [person], {}
    monkeypatch.setattr(live_service, "load_active_users_and_common_leave", load_people)

    class Result:
        def __init__(self, rows=(), scalar=None):
            self.rows, self.scalar = rows, scalar
        def scalar_one_or_none(self): return self.scalar
        def scalars(self): return self
        def all(self): return self.rows

    class Session:
        async def execute(self, statement):
            column = statement.column_descriptions[0]
            entity = column["entity"]
            if entity is DailyPlannerSnapshot: return Result(scalar=baseline)
            if entity is User: return Result([person])
            if entity is Task: return Result([task_id] if column["name"] == "id" else [task])
            if entity is AuditLog and "audit_logs.created_at > " in str(statement.compile(dialect=postgresql.dialect())) and historical_status:
                return Result([SimpleNamespace(entity_id=task_id, before={"value": historical_status})])
            return Result()

    report = asyncio.run(live_service.build_live_daily_realization(
        Session(), department_id=department_id, day=DAY,
    ))
    person_report = report["people"][0]
    row = person_report["tasks"][0]
    assert row["current_status"] == (historical_status or current_status)
    assert row["classification"] == expected
    assert row["completion_credited"] is False
    assert row["wfe"] is (historical_status == "WAITING_CLIENT")
    assert person_report["metrics"]["no_progress_count"] == (expected == "NO_PROGRESS")
    if expected == "IN_PROGRESS":
        assert person_report["metrics"]["realization_penalty_points"] == 0


def case(**overrides):
    values = dict(
        day=DAY, in_baseline=True, original_due_date=DAY, current_due_date=DAY,
        created_date=date(2026, 8, 1), completed_date=None, status="TODO",
    )
    values.update(overrides)
    return DailyClassificationInput(**values)


@pytest.mark.parametrize("statuses, expected, completed", [
    (["DONE", "IN_PROGRESS", "DONE"], "REALIZED_AS_PLANNED", True),
    (["DONE", "IN_PROGRESS"], "REOPENED", False),
    (["DONE", "IN_PROGRESS", "DONE", "TODO"], "REOPENED", False),
])
def test_reopened_task_uses_final_daily_completion(monkeypatch, statuses, expected, completed):
    import asyncio
    from sqlalchemy.dialects import postgresql
    from app.models.audit_log import AuditLog
    from app.models.task import Task
    from app.models.user import User
    from app.services import daily_realization_live as live_service

    person_id, task_id, department_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    person = SimpleNamespace(id=person_id, full_name="Recompleted task")
    events = []
    old_status = "IN_PROGRESS"
    last_done_at = None
    for index, status in enumerate(statuses):
        at = datetime(2026, 8, 26, 10, index, tzinfo=timezone.utc)
        if status == "DONE":
            last_done_at = at
        events.append(SimpleNamespace(
            id=uuid.uuid4(), entity_id=task_id, actor_user_id=person_id,
            action="task.reopened" if old_status == "DONE" else "task.status_changed",
            before={"value": old_status}, after={"value": status}, created_at=at,
        ))
        old_status = status
    task = Task(
        id=task_id, title="Recompleted plan task", assigned_to=person_id,
        status=statuses[-1], created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        updated_at=events[-1].created_at,
        completed_at=last_done_at if completed else None,
    )
    baseline = SimpleNamespace(
        id=uuid.uuid4(), captured_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        payload={"people": [{"user_id": str(person_id), "tasks": [{"task_id": str(task_id)}]}]},
    )
    async def load_people(*args, **kwargs):
        return [person], {}
    monkeypatch.setattr(live_service, "load_active_users_and_common_leave", load_people)

    class Result:
        def __init__(self, rows=(), scalar=None):
            self.rows, self.scalar = rows, scalar
        def scalar_one_or_none(self): return self.scalar
        def scalars(self): return self
        def all(self): return self.rows

    class Session:
        async def execute(self, statement):
            column = statement.column_descriptions[0]
            entity = column["entity"]
            if entity is DailyPlannerSnapshot: return Result(scalar=baseline)
            if entity is User: return Result([person])
            if entity is Task: return Result([task_id] if column["name"] == "id" else [task])
            if entity is AuditLog and "audit_logs.created_at <= " in str(statement.compile(dialect=postgresql.dialect())):
                return Result(events)
            return Result()

    report = asyncio.run(live_service.build_live_daily_realization(
        Session(), department_id=department_id, day=DAY,
    ))
    row = report["people"][0]["tasks"][0]
    assert row["classification"] == expected
    assert row["completion_credited"] is completed
    assert report["metrics"]["planned_completed_today_count"] == int(completed)
    assert report["metrics"]["raw_plan_realization"] == (100 if completed else 0)
    assert any(item["type"] == "REOPENED" for item in row["timeline"])


@pytest.mark.parametrize(("value", "expected"), [
    (case(completed_date=DAY, status="DONE"), "REALIZED_AS_PLANNED"),
    (case(), "NO_PROGRESS"),
    (case(status="IN_PROGRESS"), "IN_PROGRESS"),
    (case(status="WAITING_CONFIRMATION"), "WAITING_CONFIRMATION"),
    (case(current_due_date=date(2026, 8, 27), postponed=True), "POSTPONED_UNAPPROVED"),
    (case(current_due_date=date(2026, 8, 29), postponed=True), "POSTPONED_UNAPPROVED"),
    (case(current_due_date=DAY, postponed=False), "NO_PROGRESS"),
    (case(in_baseline=False, original_due_date=date(2026, 8, 25), completed_date=DAY, status="DONE"), "COMPLETED_LATE"),
    (case(in_baseline=False, original_due_date=date(2026, 8, 27), completed_date=DAY, status="DONE"), "COMPLETED_EARLY"),
    (case(in_baseline=False, original_due_date=None, created_date=DAY, completed_date=DAY, status="DONE"), "ADDITIONAL_COMPLETED"),
    (case(in_baseline=False, original_due_date=None, created_date=DAY), "ADDED_DURING_DAY"),
    (case(reopened=True), "REOPENED"),
    (case(reassigned_out=True), "REASSIGNED_OUT"),
    (case(in_baseline=False, reassigned_in=True), "REASSIGNED_IN"),
    (case(progress_delta=35), "IN_PROGRESS"),
    (case(current_due_date=date(2026, 8, 27), postponed=True, postponement_approved=True), "POSTPONED_APPROVED"),
])
def test_classification_matrix(value, expected):
    assert classify_daily_task(value) == expected


def test_definition_of_done_metrics_keeps_extra_out_of_raw_denominator():
    rows = (
        [{"classification": "REALIZED_AS_PLANNED", "in_original_plan": True}] * 5
        + [{"classification": "IN_PROGRESS", "in_original_plan": True}]
        + [{"classification": "POSTPONED_UNAPPROVED", "in_original_plan": True}]
        + [{"classification": "NO_PROGRESS", "in_original_plan": True}]
        + [{"classification": "ADDITIONAL_COMPLETED", "in_original_plan": False}] * 2
    )
    metrics = calculate_daily_metrics(rows)
    assert metrics["original_planned_count"] == 8
    assert metrics["planned_completed_today_count"] == 5
    assert metrics["in_progress_count"] == 1
    assert metrics["postponed_count"] == 1
    assert metrics["no_progress_count"] == 1
    assert metrics["additional_completed_count"] == 2
    # 7 / 8 = 87.5% base, minus (25 postponed + 25 untouched) / 8.
    assert metrics["raw_plan_realization"] == 81.3
    assert metrics["total_completed_today_count"] == 7


def test_extra_total_includes_open_tasks_and_extra_done_includes_early_and_late():
    metrics = calculate_daily_metrics([
        {"classification": "REALIZED_AS_PLANNED", "in_original_plan": True},
        {"classification": "ADDITIONAL_COMPLETED", "in_original_plan": False},
        {"classification": "COMPLETED_LATE", "in_original_plan": False},
        {"classification": "COMPLETED_EARLY", "in_original_plan": False},
        {"classification": "IN_PROGRESS", "in_original_plan": False},
        {"classification": "ADDED_DURING_DAY", "in_original_plan": False},
        {"classification": "ADDED_DURING_DAY", "in_original_plan": False, "current_status": "IN_PROGRESS"},
        {"classification": "REASSIGNED_IN", "in_original_plan": False, "completed_delta": 1},
        {"classification": "WAITING_CONFIRMATION", "in_original_plan": False},
    ])
    assert metrics["additional_count"] == 8
    assert metrics["additional_completed_count"] == 3
    assert metrics["additional_in_progress_count"] == 3
    assert metrics["additional_no_progress_count"] == 2
    assert metrics["additional_count"] == sum(metrics[key] for key in (
        "additional_completed_count", "additional_in_progress_count", "additional_no_progress_count"
    ))
    assert metrics["total_completed_today_count"] == 4
    assert metrics["original_planned_count"] == 1


def test_adjusted_metric_excludes_only_approved_scope_change():
    rows = (
        [{"classification": "REALIZED_AS_PLANNED", "in_original_plan": True}] * 7
        + [{"classification": "POSTPONED_APPROVED", "in_original_plan": True}] * 2
        + [{"classification": "NO_PROGRESS", "in_original_plan": True}]
    )
    metrics = calculate_daily_metrics(rows)
    # 70 - (2 * 25 postponed + 25 untouched) / 10; adjusted drops the approved ones: 87.5 - 25 / 8.
    assert metrics["raw_plan_realization"] == 62.5
    assert metrics["adjusted_denominator"] == 8
    assert metrics["adjusted_plan_realization"] == 84.4


def test_daily_extra_completions_count_but_realization_never_exceeds_100():
    rows = [
        {"classification": "REALIZED_AS_PLANNED", "in_original_plan": True},
        {"classification": "NO_PROGRESS", "in_original_plan": True},
        {"classification": "ADDITIONAL_COMPLETED", "in_original_plan": False},
    ]
    # Base is capped at 100 before the untouched task deducts 25 / 2.
    assert calculate_daily_metrics(rows)["raw_plan_realization"] == 87.5
    rows.append({"classification": "ADDITIONAL_COMPLETED", "in_original_plan": False})
    metrics = calculate_daily_metrics(rows)
    assert metrics["total_completed_today_count"] == 3
    assert metrics["additional_completed_count"] == 2
    assert metrics["raw_plan_realization"] == 87.5
    assert metrics["adjusted_plan_realization"] == 87.5


def test_daily_realization_uses_weekly_formula():
    rows = (
        [{"classification": "REALIZED_AS_PLANNED", "in_original_plan": True}] * 3
        + [{"classification": "POSTPONED_UNAPPROVED", "in_original_plan": True}] * 2
        + [{"classification": "ADDITIONAL_COMPLETED", "in_original_plan": False}] * 2
    )
    metrics = calculate_daily_metrics(rows)
    assert metrics["raw_plan_realization"] == 90.0
    assert metrics["adjusted_plan_realization"] == 90.0


def test_daily_realization_without_plan_uses_extras_as_base():
    rows = [
        {"classification": "ADDITIONAL_COMPLETED", "in_original_plan": False},
        {"classification": "ADDED_DURING_DAY", "in_original_plan": False},
    ]
    assert calculate_daily_metrics(rows)["raw_plan_realization"] == 50.0


def test_zero_denominators_are_na_not_false_success():
    metrics = calculate_daily_metrics([])
    assert metrics["raw_plan_realization"] is None
    assert metrics["adjusted_plan_realization"] is None


def test_deadline_metrics_keep_postponed_original_deadline_in_population():
    metrics = calculate_daily_metrics([
        {"classification": "REALIZED_AS_PLANNED", "in_original_plan": True,
         "deadline_was_today": True, "deadline_completed": True},
        {"classification": "POSTPONED_APPROVED", "in_original_plan": True,
         "deadline_was_today": True, "postponed_today": True},
        {"classification": "NO_PROGRESS", "in_original_plan": True,
         "deadline_was_today": True, "action_required": True},
    ])
    assert metrics["deadlines_today_count"] == 3
    assert metrics["deadlines_completed_count"] == 1
    assert metrics["deadlines_postponed_count"] == 1
    assert metrics["deadlines_in_progress_count"] == 0
    assert metrics["deadlines_no_progress_count"] == 1
    assert metrics["deadlines_open_count"] == 1
    assert metrics["deadline_compliance_percentage"] == 33.3
    assert metrics["daily_control_state"] == "ACTION_REQUIRED"


def test_deadline_states_are_exclusive_and_include_progress():
    metrics = calculate_daily_metrics([
        {"classification": "REALIZED_AS_PLANNED", "deadline_was_today": True, "deadline_completed": True},
        {"classification": "IN_PROGRESS", "deadline_was_today": True, "current_status": "IN_PROGRESS"},
        {"classification": "POSTPONED_UNAPPROVED", "deadline_was_today": True, "postponed_today": True},
        {"classification": "NO_PROGRESS", "deadline_was_today": True},
    ])
    assert metrics["deadlines_today_count"] == 4
    assert metrics["deadlines_completed_count"] == 1
    assert metrics["deadlines_in_progress_count"] == 1
    assert metrics["deadlines_postponed_count"] == 1
    assert metrics["deadlines_no_progress_count"] == 1
    assert sum(metrics[key] for key in (
        "deadlines_completed_count",
        "deadlines_in_progress_count",
        "deadlines_postponed_count",
        "deadlines_no_progress_count",
    )) == metrics["deadlines_today_count"]


def test_deadline_tasks_name_every_deadline_and_list_the_unfinished_first():
    metrics = calculate_daily_metrics([
        {"task_id": "1", "title": "Raporti", "deadline_was_today": True, "deadline_completed": True},
        {"task_id": "2", "title": "Oferta", "deadline_was_today": True, "postponed_today": True},
        {"task_id": "3", "title": "Kontrata", "deadline_was_today": True, "deadline_critical": True},
        {"task_id": "4", "title": "Pa afat", "classification": "NO_PROGRESS"},
    ])

    assert [(card["title"], card["state"]) for card in metrics["deadline_tasks"]] == [
        ("Kontrata", "NO_PROGRESS"),
        ("Oferta", "POSTPONED"),
        ("Raporti", "COMPLETED"),
    ]
    assert metrics["deadline_tasks"][0]["critical"] is True


def audit(action, at, old, new):
    return SimpleNamespace(
        id=uuid.uuid4(), action=action, created_at=at, actor_user_id=uuid.uuid4(),
        before={"value": old}, after={"value": new},
    )


def test_timeline_preserves_every_postponement_in_deterministic_order():
    events = [
        audit("task.due_date_changed", datetime(2026, 8, 26, 13, 27, tzinfo=timezone.utc), "2026-08-26", "2026-08-27"),
        audit("task.due_date_changed", datetime(2026, 8, 26, 15, 48, tzinfo=timezone.utc), "2026-08-27", "2026-08-29"),
        audit("task.due_date_changed", datetime(2026, 8, 26, 16, 0, tzinfo=timezone.utc), "2026-08-29", "2026-08-30"),
    ]
    rows = timeline_from_events(
        day=DAY, baseline_task={"match_key": "id:1", "original_daily_plan": DAY.isoformat()},
        events=list(reversed(events)),
    )
    assert [row["type"] for row in rows] == ["PLANNED_FOR_DAY", "POSTPONED", "POSTPONED_AGAIN", "POSTPONED_AGAIN"]
    assert [(row["old_value"], row["new_value"]) for row in rows[1:]] == [
        ("2026-08-26", "2026-08-27"), ("2026-08-27", "2026-08-29"), ("2026-08-29", "2026-08-30"),
    ]


@pytest.mark.parametrize(("status", "event_type"), [
    ("APPROVED", "POSTPONEMENT_APPROVED"), ("REJECTED", "POSTPONEMENT_REJECTED"),
])
def test_manager_decision_becomes_human_timeline_evidence(status, event_type):
    manager_id = uuid.uuid4()
    adjustment = SimpleNamespace(
        id=uuid.uuid4(), status=status,
        decided_at=datetime(2026, 8, 26, 15, 5, tzinfo=timezone.utc),
        decided_by=manager_id, reason="Kapaciteti", decision_comment="Vazhdo më 28.08",
    )
    item = manager_decision_timeline_item(adjustment, decided_by_name="Marie")
    assert item["type"] == event_type
    assert item["actor_user_id"] == str(manager_id)
    assert item["actor_name"] == "Marie"
    assert item["metadata"] == {"reason": "Kapaciteti", "comment": "Vazhdo më 28.08"}


def test_timeline_recognizes_move_back_to_today():
    rows = timeline_from_events(day=DAY, baseline_task=None, events=[
        audit("task.due_date_changed", datetime(2026, 8, 26, 14, tzinfo=timezone.utc), "2026-08-27", "2026-08-26")
    ])
    assert rows[0]["type"] == "MOVED_BACK_TO_TODAY"


def test_daily_payload_uses_canonical_occurrences_and_multi_assignees():
    task_id, a_id, b_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    payload = _daily_payload({
        "week_start": "2026-08-24",
        "task_items": [{
            "match_key": f"id:{task_id}", "task_id": str(task_id), "title": "Shared",
            "source_type": "project", "planned_due_date": DAY.isoformat(),
            "occurrences": [
                {"day": DAY.isoformat(), "time_slot": "AM", "assignee_id": str(a_id), "assignee_name": "A"},
                {"day": DAY.isoformat(), "time_slot": "PM", "assignee_id": str(b_id), "assignee_name": "B"},
                {"day": "2026-08-27", "time_slot": "AM", "assignee_id": str(a_id), "assignee_name": "A"},
            ],
        }],
    }, DAY)
    assert {row["user_id"] for row in payload["people"]} == {str(a_id), str(b_id)}
    assert all(len(row["tasks"]) == 1 for row in payload["people"])


def test_baseline_model_and_service_enforce_immutability_by_construction():
    constraints = {constraint.name for constraint in DailyPlannerSnapshot.__table__.constraints}
    assert "uq_daily_planner_snapshot_department_day" in constraints
    source = inspect.getsource(ensure_daily_baseline)
    assert "on_conflict_do_nothing" in source
    assert ".payload =" not in source


def test_plan_counts_a_postponement_on_its_decision_day_but_deadlines_do_not():
    """Moving a deadline early is a postponement today, not a missed deadline."""
    from app.services.daily_realization_live import build_live_daily_realization

    source = inspect.getsource(build_live_daily_realization)

    assert "postponed=postponed_on_day," in source
    # The deadline population still waits for the obligation's own day.
    assert "postponed_today = bool(had_postponement_event" in source
    assert 'semantic_local_day((event.before or {}).get("value")) == day' in source


def test_tirana_midnight_boundary_is_not_naive_utc():
    # 22:30 UTC is 00:30 on the next local summer day in Tirana.
    assert local_day(datetime(2026, 8, 25, 22, 30, tzinfo=timezone.utc)) == DAY
    start, end = day_bounds(DAY)
    assert start == datetime(2026, 8, 25, 22, 0, tzinfo=timezone.utc)
    assert end.date() == DAY


def test_semantic_due_date_direction_uses_local_day_not_iso_string_order():
    assert semantic_local_day("2026-08-25T22:30:00+00:00") == DAY
    assert semantic_local_day("2026-08-27T00:30:00+02:00") == date(2026, 8, 27)


@pytest.mark.parametrize(("status", "deadline", "was_today", "postponed", "required"), [
    ("TODO", date(2026, 8, 27), False, False, True),
    ("TODO", DAY, False, False, True),
    ("IN_PROGRESS", date(2026, 8, 27), False, False, False),
    ("IN_PROGRESS", DAY, False, False, True),
    ("IN_PROGRESS", date(2026, 8, 25), False, False, True),
    ("IN_PROGRESS", date(2026, 8, 27), True, False, True),
    ("DONE", DAY, True, True, False),
    ("TODO", date(2026, 8, 27), True, True, True),
])
def test_daily_explanation_matrix(status, deadline, was_today, postponed, required):
    requirement = requires_daily_explanation(
        status=status, selected_day=DAY, deadline=deadline,
        deadline_was_today=was_today, postponed_today=postponed,
    )
    assert requirement.requires_explanation is required
    assert requirement.reason_required is required
    assert requirement.comment_required is required


def test_reassignment_a_to_b_to_c_keeps_intermediate_owner_candidate():
    task_id = uuid.uuid4()
    a_id, b_id, c_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    events = [
        SimpleNamespace(id=uuid.uuid4(), action="task.assignee_changed", created_at=datetime(2026, 8, 26, 10, tzinfo=timezone.utc), actor_user_id=None,
                        before={"assignee_ids": [str(a_id)]}, after={"assignee_ids": [str(b_id)]}),
        SimpleNamespace(id=uuid.uuid4(), action="task.assignee_changed", created_at=datetime(2026, 8, 26, 14, tzinfo=timezone.utc), actor_user_id=None,
                        before={"assignee_ids": [str(b_id)]}, after={"assignee_ids": [str(c_id)]}),
    ]
    events_by_task = {task_id: events}
    current = {task_id: {c_id}}
    for owner in (a_id, b_id, c_id):
        assert task_id in candidate_task_ids_for_person(
            owner, baseline_by_user={a_id: {task_id: {}}},
            current_assignees=current, tasks={}, events_by_task=events_by_task, day=DAY,
        )


def test_overdue_todo_without_day_evidence_is_not_a_daily_extra():
    task_id, person_id = uuid.uuid4(), uuid.uuid4()
    task = SimpleNamespace(
        id=task_id, is_active=True, status="TODO",
        due_date=datetime(2026, 8, 25, 12, tzinfo=timezone.utc),
        created_at=datetime(2026, 8, 1, 8, tzinfo=timezone.utc),
        completed_at=None,
    )
    candidates = candidate_task_ids_for_person(
        person_id, baseline_by_user={}, current_assignees={task_id: {person_id}},
        tasks={task_id: task}, events_by_task={}, day=DAY,
    )
    assert candidates == set()


def test_future_task_created_during_planning_is_not_a_daily_extra():
    task = SimpleNamespace(
        created_at=datetime(2026, 8, 26, 10, tzinfo=timezone.utc),
        start_date=datetime(2026, 8, 27, 8, tzinfo=timezone.utc),
        due_date=datetime(2026, 8, 28, 16, tzinfo=timezone.utc),
    )
    assert not additional_task_has_day_evidence(
        task=task, day=DAY, completion_credited=False, progress=None, state=None,
        events=[SimpleNamespace(action="created", before={}, after={})],
    )


def test_task_started_today_outside_baseline_is_a_daily_extra():
    task = SimpleNamespace(
        created_at=datetime(2026, 8, 26, 8, tzinfo=timezone.utc),
        start_date=datetime(2026, 8, 26, 8, tzinfo=timezone.utc),
        due_date=datetime(2026, 8, 28, 16, tzinfo=timezone.utc),
    )
    assert additional_task_has_day_evidence(
        task=task, day=DAY, completion_credited=False, progress=None, state=None,
        events=[SimpleNamespace(action="created", before={}, after={})],
    )


def test_resolved_overdue_task_is_completed_late():
    task_id, person_id = uuid.uuid4(), uuid.uuid4()
    completed_at = datetime(2026, 8, 26, 15, tzinfo=timezone.utc)
    task = SimpleNamespace(
        id=task_id, is_active=True, status="DONE",
        due_date=datetime(2026, 8, 25, 12, tzinfo=timezone.utc),
        created_at=datetime(2026, 8, 1, 8, tzinfo=timezone.utc),
        completed_at=completed_at,
    )
    assert candidate_task_ids_for_person(
        person_id, baseline_by_user={}, current_assignees={task_id: {person_id}},
        tasks={task_id: task}, events_by_task={}, day=DAY,
    ) == {task_id}
    assert classify_daily_task(case(
        in_baseline=False, original_due_date=date(2026, 8, 25),
        current_due_date=date(2026, 8, 25), completed_date=DAY, status="DONE",
    )) == "COMPLETED_LATE"


def test_a_to_b_to_c_completion_is_credited_only_to_owner_at_completion():
    a_id, b_id, c_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    events = [
        SimpleNamespace(id=uuid.uuid4(), action="task.assignee_changed", created_at=datetime(2026, 8, 26, 10, tzinfo=timezone.utc),
                        before={"assignee_ids": [str(a_id)]}, after={"assignee_ids": [str(b_id)]}),
        SimpleNamespace(id=uuid.uuid4(), action="task.assignee_changed", created_at=datetime(2026, 8, 26, 14, tzinfo=timezone.utc),
                        before={"assignee_ids": [str(b_id)]}, after={"assignee_ids": [str(c_id)]}),
    ]
    completed_at = datetime(2026, 8, 26, 15, tzinfo=timezone.utc)
    credited = {
        owner: credited_completion_day(
            person_id=owner, day=DAY, completion_at=completed_at,
            current_assignees={c_id}, assignee_events=events,
            baseline_owner=owner == a_id,
        )
        for owner in (a_id, b_id, c_id)
    }
    assert credited == {a_id: None, b_id: None, c_id: DAY}

    rows = [
        {"classification": "REASSIGNED_OUT", "in_original_plan": True},
        {"classification": "REASSIGNED_IN", "in_original_plan": False},
        {"classification": "ADDITIONAL_COMPLETED", "in_original_plan": False},
    ]
    metrics = calculate_daily_metrics(rows)
    assert metrics["original_planned_count"] == 1
    assert metrics["additional_completed_count"] == 1
    assert metrics["total_completed_today_count"] == 1


def test_a_to_b_completion_before_transfer_away_is_credited_to_b():
    a_id, b_id, c_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    events = [
        SimpleNamespace(id=uuid.uuid4(), action="task.assignee_changed", created_at=datetime(2026, 8, 26, 10, tzinfo=timezone.utc),
                        before={"assignee_ids": [str(a_id)]}, after={"assignee_ids": [str(b_id)]}),
        SimpleNamespace(id=uuid.uuid4(), action="task.assignee_changed", created_at=datetime(2026, 8, 26, 14, tzinfo=timezone.utc),
                        before={"assignee_ids": [str(b_id)]}, after={"assignee_ids": [str(c_id)]}),
    ]
    completed_at = datetime(2026, 8, 26, 13, tzinfo=timezone.utc)
    assert credited_completion_day(
        person_id=b_id, day=DAY, completion_at=completed_at,
        current_assignees={c_id}, assignee_events=events,
    ) == DAY
    assert credited_completion_day(
        person_id=c_id, day=DAY, completion_at=completed_at,
        current_assignees={c_id}, assignee_events=events,
    ) is None


def test_shared_close_state_resolver_agrees_on_stale_and_reopened():
    closed_at = datetime(2026, 8, 26, 16, 40, tzinfo=timezone.utc)
    changed_at = datetime(2026, 8, 26, 16, 41, tzinfo=timezone.utc)
    assert resolve_daily_close_state(
        latest_action="CLOSE", close_created_at=closed_at,
        latest_relevant_change=changed_at, editable=False,
    ) == ("STALE", True, True)
    assert resolve_daily_close_state(
        latest_action="REOPEN", close_created_at=closed_at,
        latest_relevant_change=changed_at, editable=False,
    ) == ("REOPENED", False, False)


def test_move_away_and_back_is_not_final_postponement_but_keeps_history():
    events = [
        audit("task.due_date_changed", datetime(2026, 8, 26, 12, tzinfo=timezone.utc), "2026-08-26", "2026-08-27"),
        audit("task.due_date_changed", datetime(2026, 8, 26, 14, tzinfo=timezone.utc), "2026-08-27", "2026-08-26"),
    ]
    timeline = timeline_from_events(day=DAY, baseline_task=None, events=events)
    assert [row["type"] for row in timeline] == ["POSTPONED", "MOVED_BACK_TO_TODAY"]
    assert classify_daily_task(case(current_due_date=DAY, postponed=False, status="TODO")) == "NO_PROGRESS"
    assert classify_daily_task(case(current_due_date=DAY, postponed=False, status="IN_PROGRESS")) == "IN_PROGRESS"


def test_multi_day_task_weighs_its_daily_share_across_working_days():
    monday, wednesday, friday = date(2026, 10, 5), date(2026, 10, 7), date(2026, 10, 9)
    assert multi_day_share(monday, friday, wednesday) == (0.2, True)
    assert multi_day_share(monday, friday, friday) == (0.2, False)
    assert multi_day_share(friday, date(2026, 10, 13), date(2026, 10, 12)) == (1 / 3, True)
    assert multi_day_share(friday, friday, friday) == (1.0, False)
    assert multi_day_share(None, friday, wednesday) == (1.0, False)


def test_multi_day_task_in_progress_counts_as_its_daily_share():
    rows = [
        {"classification": "REALIZED_AS_PLANNED", "in_original_plan": True},
        {"classification": "REALIZED_AS_PLANNED", "in_original_plan": True},
        {"classification": "IN_PROGRESS", "in_original_plan": True, "daily_share": 0.2, "multi_day_before_deadline": True},
    ]
    metrics = calculate_daily_metrics(rows)
    assert metrics["realization_plan_weight"] == 2.2
    assert metrics["realization_credit"] == 2.2
    assert metrics["raw_plan_realization"] == 100


def test_single_day_task_in_progress_earns_nothing():
    rows = [
        {"classification": "REALIZED_AS_PLANNED", "in_original_plan": True},
        {"classification": "IN_PROGRESS", "in_original_plan": True},
    ]
    assert calculate_daily_metrics(rows)["raw_plan_realization"] == 50


@pytest.mark.parametrize(("row", "expected"), [
    ({"classification": "POSTPONED_UNAPPROVED"}, 68.8),
    ({"classification": "POSTPONED_UNAPPROVED", "deadline_was_today": True}, 65.0),
    ({"classification": "POSTPONED_UNAPPROVED", "deadline_was_today": True, "deadline_critical": True}, 60.0),
    ({"classification": "NO_PROGRESS"}, 68.8),
    ({"classification": "NO_PROGRESS", "deadline_was_today": True}, 62.5),
    ({"classification": "IN_PROGRESS", "deadline_was_today": True, "deadline_critical": True}, 57.5),
])
def test_deadlines_raise_the_penalty(row, expected):
    # Base 3 / 4 = 75; penalty points / 4: 25 postponed or untouched, 40/60 postponed with deadline, 50/70 missed deadline.
    rows = [{"classification": "REALIZED_AS_PLANNED", "in_original_plan": True}] * 3 + [
        {"in_original_plan": True, "task_id": "x", "title": "Detyra", **row},
    ]
    assert calculate_daily_metrics(rows)["raw_plan_realization"] == expected


def test_realization_items_explain_the_percent():
    metrics = calculate_daily_metrics([
        {"task_id": "a", "title": "Raport\nshënime", "classification": "REALIZED_AS_PLANNED", "in_original_plan": True},
        {"task_id": "b", "title": "Oferta", "classification": "POSTPONED_APPROVED", "in_original_plan": True, "deadline_was_today": True},
        {"task_id": "c", "title": "Ekstra", "classification": "ADDITIONAL_COMPLETED", "in_original_plan": False},
        {"task_id": "d", "title": "E hapur", "classification": "ADDED_DURING_DAY", "in_original_plan": False},
    ])
    items = {item["task_id"]: item for item in metrics["realization_items"]}
    assert set(items) == {"a", "b", "c"}
    assert items["a"]["kind"] == "COMPLETED" and items["a"]["credit"] == 1
    assert items["b"]["kind"] == "POSTPONED" and items["b"]["penalty"] == 40 and items["b"]["approved"]
    assert items["c"]["kind"] == "EXTRA_COMPLETED"
    # Base 2 / 2 = 100, penalty 40 / 2 = 20; adjusted drops the approved postponement.
    assert metrics["raw_plan_realization"] == 80.0
    assert metrics["adjusted_plan_realization"] == 100.0


def test_system_tasks_hidden_from_weekly_planner_are_not_extra(monkeypatch):
    import asyncio
    from app.models.system_task_template import SystemTaskTemplate
    from app.models.task import Task
    from app.models.task_assignee import TaskAssignee
    from app.models.user import User
    from app.services import daily_realization_live as live_service

    department_id, user_id = uuid.uuid4(), uuid.uuid4()
    hidden_template, visible_template = uuid.uuid4(), uuid.uuid4()
    person = SimpleNamespace(id=user_id, full_name="Laurent Hoxha")
    done_today = datetime(2026, 8, 26, 10, tzinfo=timezone.utc)

    def system_task(title, template_id):
        return Task(id=uuid.uuid4(), title=title, assigned_to=user_id, department_id=department_id,
                    status="DONE", is_active=True, system_template_origin_id=template_id,
                    created_at=done_today, updated_at=done_today, completed_at=done_today,
                    start_date=done_today, due_date=done_today)

    hidden = system_task("KONTROLLI DITOR I SERVERIT", hidden_template)
    visible = system_task("TICKETS STD", visible_template)
    baseline = SimpleNamespace(id=uuid.uuid4(), captured_at=done_today, payload={"people": [
        {"user_id": str(user_id), "tasks": []},
    ]})

    async def load_people(*args, **kwargs): return [person], {}
    monkeypatch.setattr(live_service, "load_active_users_and_common_leave", load_people)

    class Result:
        def __init__(self, rows=(), scalar=None): self.rows, self.scalar = rows, scalar
        def scalar_one_or_none(self): return self.scalar
        def scalars(self): return self
        def all(self): return self.rows

    class Session:
        async def execute(self, statement):
            column = statement.column_descriptions[0]
            if column["entity"] is DailyPlannerSnapshot: return Result(scalar=baseline)
            if column["entity"] is User: return Result([person])
            if column["entity"] is Task:
                return Result([hidden.id, visible.id] if column["name"] == "id" else [hidden, visible])
            if column["entity"] is TaskAssignee:
                return Result([SimpleNamespace(task_id=item.id, user_id=user_id) for item in (hidden, visible)])
            if column["entity"] is SystemTaskTemplate: return Result([hidden_template])
            return Result()

    report = asyncio.run(live_service.build_live_daily_realization(Session(), department_id=department_id, day=DAY))
    titles = [row["title"] for row in report["people"][0]["tasks"]]
    assert titles == ["TICKETS STD"]
    assert report["people"][0]["metrics"]["additional_completed_count"] == 1


def test_extras_weigh_as_much_as_the_average_plan_task():
    rows = (
        [{"classification": "IN_PROGRESS", "in_original_plan": True, "daily_share": 0.2, "multi_day_before_deadline": True}] * 2
        + [{"classification": "ADDITIONAL_COMPLETED", "in_original_plan": False}] * 2
    )
    metrics = calculate_daily_metrics(rows)
    # Plan 0.4 over 2 tasks: each extra weighs 0.2 instead of a whole task.
    assert metrics["realization_plan_weight"] == 0.4
    assert metrics["realization_credit"] == 0.8
    assert metrics["raw_plan_realization"] == 100
    metrics = calculate_daily_metrics(rows[:1] + [{"classification": "NO_PROGRESS", "in_original_plan": True, "daily_share": 0.2}] + rows[2:])
    # 0.2 + 2 * 0.2 = 0.6 over 0.4 caps at 100, minus 25 / 2 for the untouched task.
    assert metrics["raw_plan_realization"] == 87.5


def test_extra_that_misses_its_deadline_is_penalised():
    rows = [
        {"classification": "REALIZED_AS_PLANNED", "in_original_plan": True},
        {"classification": "REALIZED_AS_PLANNED", "in_original_plan": True},
        {"task_id": "x", "title": "Lutz", "classification": "ADDED_DURING_DAY", "in_original_plan": False,
         "deadline_was_today": True, "deadline_critical": True},
    ]
    metrics = calculate_daily_metrics(rows)
    assert metrics["raw_plan_realization"] == 65.0
    assert [item["kind"] for item in metrics["realization_items"] if not item["planned"]] == ["EXTRA_OPEN"]
    rows[2] = {**rows[2], "postponed_today": True}
    assert calculate_daily_metrics(rows)["raw_plan_realization"] == 100
