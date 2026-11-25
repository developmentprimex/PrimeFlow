import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.services import discord_task_deliveries as deliveries
from app.services.discord_task_deliveries import _delivery_results, _message_titles, _task_rows

DAY = date(2026, 11, 25)
ZONE = ZoneInfo("Europe/Tirane")


def local_time(hour, minute=0, second=0):
    return datetime(2026, 11, 25, hour, minute, second, tzinfo=ZONE)


def test_morning_coverage_accepts_any_of_the_three_requested_cases():
    check = deliveries._covers_morning
    assert check(is_one_h=True, slot="10:00", personal_with_someone=False, period="PM", marker=None)
    assert check(is_one_h=False, slot=None, personal_with_someone=True, period="AM", marker=None)
    assert check(is_one_h=False, slot=None, personal_with_someone=False, period="AM/PM", marker="QUESTION,F")
    assert not check(is_one_h=True, slot="11:00", personal_with_someone=False, period="AM", marker="FLAG")
    assert not check(is_one_h=False, slot=None, personal_with_someone=True, period="PM", marker="F")


def test_missing_slots_respect_daily_and_personal_choices(monkeypatch):
    first, second = uuid4(), uuid4()
    shared = SimpleNamespace(id=uuid4(), assigned_to=first, one_h_report_slot="11:00")
    empty = SimpleNamespace(id=uuid4(), assigned_to=None, one_h_report_slot=None)
    dated = SimpleNamespace(id=uuid4(), assigned_to=first, one_h_report_slot=None)
    personal_only = SimpleNamespace(id=uuid4(), assigned_to=first, one_h_report_slot=None)
    database = SimpleNamespace(scalars=AsyncMock(return_value=Mock(**{
        "all.return_value": [shared, empty, dated, personal_only],
    })))
    monkeypatch.setattr(deliveries, "choice_members", AsyncMock(return_value=(
        {shared.id: {first, second}, empty.id: set(), dated.id: {first}, personal_only.id: {first, second}},
        {first: "First Person", second: "Second Person"},
    )))
    monkeypatch.setattr(deliveries, "slot_values", AsyncMock(return_value={dated.id: "10:00"}))
    monkeypatch.setattr(deliveries, "personal_choices", AsyncMock(return_value={
        (shared.id, str(second), "slot"): {"value": None},
        (personal_only.id, str(first), "slot"): {"value": "14:20"},
    }))
    monkeypatch.setattr(deliveries, "_format_missing_slots", AsyncMock(side_effect=lambda db, rows: rows), raising=False)

    rows = asyncio.run(deliveries._missing_slot_tasks(database, DAY, DAY))
    assert {(task.id, owner) for task, _, owner, _ in rows} == {
        (shared.id, second), (empty.id, None), (personal_only.id, second),
    }


def task(*slots, author="42", title="ZHV: JJ TAK JAV CYBER SEC"):
    return {"id": "task", "discord_id": author, "title": title, "slots": slots}


def post(message_id, at, *, author="42", title="ZHV: JJ TAK JAV CYBER SEC", edited=None, **fields):
    return {
        "author": {"id": author}, "id": message_id, "timestamp": at.isoformat(),
        "content": title, "edited_timestamp": edited.isoformat() if edited else None, **fields,
    }


def test_mixed_marker_requires_two_posts_and_cutoffs_are_inclusive():
    first = post("1", local_time(12, 15))
    second = post("2", local_time(16, 30))
    rows = [task("M2", "M3")]
    result = _delivery_results(rows, [first], DAY, local_time(17))[0]["deliveries"]
    assert result["M2"]["status"] == "on_time"
    assert result["M3"]["status"] == "missing"

    result = _delivery_results(rows, [second, first], DAY, local_time(17))[0]["deliveries"]
    assert result["M2"]["url"].endswith("/1")
    assert result["M3"]["url"].endswith("/2")
    assert result["M3"]["status"] == "on_time"


def test_linked_author_full_title_and_report_date_must_match():
    messages = [
        post("1", local_time(11), author="99"),
        post("2", local_time(11), title="ZHV: JJ TAK JAV CYBER SEC PLUS"),
        post("3", local_time(11).replace(day=24)),
        post("4", local_time(11), webhook_id="98"),
        post("5", local_time(11), type=20),
    ]
    rows = [task("M2")]
    assert _delivery_results(rows, messages, DAY, local_time(12))[0]["deliveries"]["M2"]["status"] == "pending"
    assert _delivery_results(rows, messages, DAY, local_time(13))[0]["deliveries"]["M2"]["status"] == "missing"

    messages.append(post("6", local_time(12, 15, 1), title="<@123> **zhv: jj tak   jav cyber sec**\nhttps://example.com"))
    result = _delivery_results(rows, messages, DAY, local_time(13))[0]["deliveries"]["M2"]
    assert result["status"] == "late"
    assert result["url"].endswith("/6")


def test_edited_title_cannot_prove_an_earlier_delivery():
    message = post("1", local_time(11), edited=local_time(12, 16))
    result = _delivery_results([task("M2")], [message], DAY, local_time(14))[0]["deliveries"]["M2"]
    assert result["status"] == "late"
    assert result["verified_at"] == local_time(12, 16).isoformat()


def test_unknown_checks_do_not_report_a_negative():
    rows = [task("M3"), task("M3", author=None)]
    result = _delivery_results(rows, None, DAY, local_time(17))
    assert [row["deliveries"]["M3"]["status"] for row in result] == ["unavailable", "unlinked"]
    duplicate = {**rows[0], "id": "another-task"}
    result = _delivery_results([rows[0], duplicate], [post("1", local_time(15))], DAY, local_time(17))
    assert all(row["deliveries"]["M3"]["status"] == "ambiguous" for row in result)
    assert all("discord_id" not in row for row in result)


def test_archived_message_proves_delivery_but_does_not_prove_absence():
    rows = [task("M2", "M3")]
    first = post("1", local_time(12, 15))
    result = _delivery_results(rows, [first], DAY, local_time(17), guild_id="123", complete=False)[0]["deliveries"]

    assert result["M2"]["status"] == "on_time"
    assert result["M2"]["url"].startswith("https://discord.com/channels/123/")
    assert result["M3"]["status"] == "unavailable"


def test_comment_save_upserts_and_empty_comment_clears_the_same_row(monkeypatch):
    task_id = uuid4()
    row_id = f"{task_id}:{uuid4()}"
    monkeypatch.setattr(deliveries, "_task_rows", AsyncMock(return_value=[{"id": row_id, "task_id": str(task_id)}]))
    database = SimpleNamespace(scalar=AsyncMock(return_value="discord_task_delivery_comments"),
                               execute=AsyncMock(), commit=AsyncMock())

    assert asyncio.run(deliveries.save_comment(database, DAY, row_id, "Kontrolluar")) == "Kontrolluar"
    update = database.execute.call_args.args[0].compile()
    assert "ON CONFLICT (report_date, row_id) DO UPDATE" in str(update)
    assert update.params["comment"] == "Kontrolluar"
    assert update.params["report_date"] == DAY
    assert update.params["row_id"] == row_id

    assert asyncio.run(deliveries.save_comment(database, DAY, row_id, "")) == ""
    clear = database.execute.call_args.args[0].compile()
    assert "DELETE FROM discord_task_delivery_comments" in str(clear)
    assert DAY in clear.params.values()
    assert row_id in clear.params.values()
    assert database.commit.await_count == 2


def test_forwarded_quote_does_not_match_the_original_title():
    assert "detyrë e ekipit" not in _message_titles("> detyrë e ekipit")
    assert "detyrë e ekipit" in _message_titles("- Dorëzim: **Detyrë e ekipit** https://example.com")


def test_report_rows_use_planner_order_and_standard_task_appearance():
    dev = SimpleNamespace(id="dev", department_id="DEV", full_name="Endi Hyseni", weekly_planner_sort_order=2)
    gd = SimpleNamespace(id="gd", department_id="GD", full_name="Test Design", weekly_planner_sort_order=1)

    def report_task(id, owner, title, *, deadline=False, system=False):
        return SimpleNamespace(
            id=id, assigned_to=owner.id, department_id=owner.department_id, title=title,
            is_deadline_important=deadline, status="IN_PROGRESS", due_date=local_time(16),
            created_at=local_time(9), fast_task_order=None, system_template_origin_id=system,
            system_task_slot_id=None,
        )

    results = iter((
        [
            (report_task("regular", dev, "A e zakonshme"), None, "M3", False),
            (report_task("design", gd, "A e dizajnit"), None, "M3", False),
            (report_task("deadline", dev, "Z Deadline", deadline=True), None, "M2_M3", True),
            (report_task("em", dev, "EM: Porosia"), None, "M3", False),
        ],
        [],
        [(dev, "42"), (gd, "43")],
        [("DEV", "DEV"), ("GD", "GD")],
        [dev, gd],
    ))

    class Result(list):
        def all(self):
            return list(self)

        def tuples(self):
            return self

        def scalars(self):
            return self

    class Database:
        async def execute(self, statement):
            return Result(next(results))

    rows = asyncio.run(_task_rows(Database(), DAY, DAY))
    assert [row["task_id"] for row in rows] == ["deadline", "em", "regular", "design"]
    assert rows[0]["initials"] == "EH"
    assert rows[0]["symbol"] == "(M2/3)"
    assert (rows[0]["fill"], rows[0]["foreground"]) == ("#dc2626", "#ffffff")
    assert rows[1]["fill"] == "#FFFF00"
    assert rows[1]["eight_am"] is True
    assert rows[1]["title"] == "08:00 EM: Porosia"
