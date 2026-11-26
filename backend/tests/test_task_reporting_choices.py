import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services import task_reporting_choices as choices

DAY = date(2026, 11, 25)


def test_slot_differences_compare_current_choices_and_drop_resolved_history(monkeypatch):
    first, second = uuid4(), uuid4()
    group_id = uuid4()
    tasks = [
        SimpleNamespace(id=uuid4(), assigned_to=owner, fast_task_group_id=group_id,
                        title="Detyrë e përbashkët", one_h_report_slot=None, one_h_marker=None, is_active=True)
        for owner in (first, second)
    ]
    names = {first: "First Person", second: "Second Person"}
    owners = {task.id: {task.assigned_to} for task in tasks}
    now = datetime(2026, 11, 25, 14, tzinfo=timezone.utc)
    history = SimpleNamespace(
        id=uuid4(), entity_id=tasks[0].id, action="slot", before={"value": "09:00"}, created_at=now,
        after={"date": DAY.isoformat(), "owner_id": str(first), "person": names[first],
               "field": "slot", "value": "10:00", "label": "10:00", "reason": "Arsye e vjetër",
               "peers": [{"person": names[second], "label": "11:00"}]},
    )
    monkeypatch.setattr(choices, "choice_members", AsyncMock(return_value=(owners, names)))
    monkeypatch.setattr(choices, "personal_choices", AsyncMock(return_value={}))
    slots = {tasks[0].id: "14:20", tasks[1].id: "11:00"}
    monkeypatch.setattr(choices, "slot_values", AsyncMock(return_value=slots))

    async def run_report():
        db = SimpleNamespace(scalars=AsyncMock(side_effect=[
            SimpleNamespace(all=lambda: [history]), SimpleNamespace(all=lambda: tasks),
        ]))
        return await choices.reporting_differences(db, DAY, now, marker_day=DAY, slot_day=DAY)

    rows = asyncio.run(run_report())
    assert {(row["person"], row["label"]) for row in rows} == {
        (names[first], "14:20"), (names[second], "11:00"),
    }
    assert all(row["previous"] is None and not row["reason"] for row in rows)
    assert rows[0]["peers"] == [{"person": names[second], "label": "11:00"}]

    slots[tasks[0].id] = "10:00"
    assert asyncio.run(run_report())[0]["reason"] == history.after["reason"]

    slots[tasks[0].id] = "14:20"
    slots[tasks[1].id] = "14:20"
    assert asyncio.run(run_report()) == []


def test_shared_task_assignees_reads_active_siblings_by_identity(monkeypatch):
    first, second, unrelated = uuid4(), uuid4(), uuid4()
    group_id = uuid4()
    task = SimpleNamespace(id=uuid4(), assigned_to=first, fast_task_group_id=group_id)
    sibling = SimpleNamespace(id=uuid4(), assigned_to=second, fast_task_group_id=group_id)
    other = SimpleNamespace(id=uuid4(), assigned_to=unrelated, fast_task_group_id=uuid4())
    db = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [task, sibling, other])))
    monkeypatch.setattr(choices, "choice_members", AsyncMock(return_value=(
        {task.id: {first}, sibling.id: {second}, other.id: {unrelated}},
        {first: "Haxhere Spahiu", second: "Gane Arifaj", unrelated: "Other"},
    )))

    result = asyncio.run(choices.shared_task_assignee_ids(db, [task]))

    assert set(result[task.id]) == {first, second}
    assert "tasks.is_active IS true" in str(db.scalars.await_args.args[0])


def test_slot_difference_requires_reason_and_keeps_the_first_assignees_slot(monkeypatch):
    first, second = uuid4(), uuid4()
    task = SimpleNamespace(id=uuid4(), title="Detyra e përbashkët", assigned_to=first, is_active=True,
                           one_h_report_slot=None, one_h_marker=None)
    actor = SimpleNamespace(id=second, full_name="Punonjësi i dytë")
    owners = {task.id: {first, second}}
    monkeypatch.setattr(choices, "choice_members", AsyncMock(return_value=(owners, {first: "Endi Hyseni", second: "Punonjësi i dytë"})))
    monkeypatch.setattr(choices, "slot_values", AsyncMock(return_value={}))
    monkeypatch.setattr(choices, "personal_choices", AsyncMock(return_value={
        (task.id, str(first), "slot"): {"value": "10:00"},
    }))
    saved = []
    db = SimpleNamespace(add=saved.append)

    async def change(confirmation=None):
        return await choices.record_choice(
            db, task, [task], actor, field="slot", value="11:00", day=DAY, confirmation=confirmation,
        )

    with pytest.raises(HTTPException) as conflict:
        asyncio.run(change())
    detail = conflict.value.detail
    assert conflict.value.status_code == 409
    assert detail["peers"][0]["person"] == "Endi Hyseni"
    assert detail["peers"][0]["value"] == "10:00"
    assert not saved

    with pytest.raises(HTTPException):
        asyncio.run(change({"key": detail["key"], "reason": "   "}))
    assert not saved
    assert asyncio.run(change({"key": detail["key"], "reason": "Takim deri në 10:30"})) is True
    assert task.one_h_report_slot is None
    assert saved[0].after["owner_id"] == str(second)
    assert saved[0].after["reason"] == "Takim deri në 10:30"


def test_marker_removal_from_one_copy_warns_and_display_applies_explicit_null(monkeypatch):
    first, second = uuid4(), uuid4()
    one = SimpleNamespace(id=uuid4(), assigned_to=first, is_active=True, one_h_marker="M2")
    two = SimpleNamespace(id=uuid4(), assigned_to=second, is_active=True, one_h_marker="M3", title="Dorëzimi")
    actor = SimpleNamespace(id=second)
    monkeypatch.setattr(choices, "choice_members", AsyncMock(return_value=(
        {one.id: {first}, two.id: {second}}, {first: "Endi Hyseni", second: "Personi tjetër"},
    )))
    monkeypatch.setattr(choices, "personal_choices", AsyncMock(return_value={}))
    with pytest.raises(HTTPException) as conflict:
        asyncio.run(choices.record_choice(None, two, [one, two], actor, field="marker", value=None, day=DAY))
    assert conflict.value.detail["label"] == "Pa simbol"
    assert conflict.value.detail["peers"][0]["label"] == "M2"

    dto = SimpleNamespace(id=two.id, one_h_marker="M3", one_h_report_slot="10:00")
    choices.apply_personal_choices(dto, {
        (two.id, str(second), "marker"): {"value": None},
        (two.id, str(second), "slot"): {"value": None},
    }, second)
    assert dto.one_h_marker is None
    assert dto.one_h_report_slot is None
