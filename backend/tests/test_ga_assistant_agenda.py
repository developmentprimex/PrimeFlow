import asyncio
import os
from datetime import date, datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
from zoneinfo import ZoneInfo

os.environ.setdefault("JWT_SECRET", "test-only-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")

from app.services import ga_assistant as svc
from app.services.ga_time_table import DEFAULT_GA_TIME_TABLE_ROWS, get_ga_time_table_tasks

DAY = date(2026, 11, 19)
TZ = ZoneInfo("Europe/Belgrade")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(DAY, time(hour, minute), tzinfo=TZ)


class Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


def session(*rows):
    return SimpleNamespace(execute=AsyncMock(side_effect=[Result(values) for values in rows]))


def task(title, *, assignee=None, marker=None, period=None, due=None):
    return SimpleNamespace(
        id=uuid4(), title=title, assigned_to=assignee, one_h_marker=marker, finish_period=period,
        start_date=at(0), due_date=due or at(0), status="TODO", completed_at=None,
        system_template_origin_id=None, confirmation_assignee_id=None, project_id=None,
        fast_task_group_id=None, original_due_date=None, is_bllok=False, priority="NORMAL",
        is_1h_report=False, one_h_report_slot=None,
    )


def test_time_table_projects_existing_ga_tasks_by_date_and_effective_time():
    owner = SimpleNamespace(id=uuid4(), full_name="GA")
    timed = task("Review order", assignee=owner.id, due=at(8, 15))
    untimed = task("Read notes", assignee=owner.id)
    removed = task("Removed for today", assignee=owner.id)
    flagged = task("Marked for GA", marker="FLAG")
    overrides = [
        SimpleNamespace(item_key=f"pf_task:{timed.id}", day_date=DAY, has_time_override=True,
                        time_value="11:20", removed=False),
        SimpleNamespace(item_key=f"pf_task:{removed.id}", day_date=DAY, has_time_override=False,
                        time_value=None, removed=True),
    ]
    db = session([], [timed, untimed, removed, flagged], [], [], [], [owner], overrides)

    entries = asyncio.run(get_ga_time_table_tasks(db, owner, DAY, DAY, list(DEFAULT_GA_TIME_TABLE_ROWS)))

    assert [(entry.task_id, entry.day, entry.row_start, entry.text) for entry in entries] == [
        (timed.id, DAY, time(11), "11:20 Review order"),
        (untimed.id, DAY, time(0), "Read notes"),
    ]


def test_agenda_emits_ga_symbol_and_preserves_existing_f_marker():
    owner = SimpleNamespace(id=uuid4(), full_name="GA")
    flagged = task("Marked for GA", marker="FLAG")
    dual = task("For GA in person", marker="FLAG,F")
    db = session([], [flagged, dual], [], [], [])

    values = asyncio.run(svc.collect_task_items(db, owner, DAY, DAY, today=DAY, tz=TZ))

    items = {value.title: value.to_dict() for value in values}
    assert items["Marked for GA"]["symbols"] == ["GA"]
    assert items["Marked for GA"]["can_complete"] is False
    assert items["For GA in person"]["kind"] == "F_TASK"
    assert items["For GA in person"]["markers"] == ["FLAG", "F"]
    assert items["For GA in person"]["symbols"] == ["GA", "F"]


def test_agenda_schedules_finish_period_without_overriding_a_real_time():
    owner = SimpleNamespace(id=uuid4(), full_name="GA")
    tasks = [
        task("morning", assignee=owner.id, period="AM"),
        task("afternoon", assignee=owner.id, period="PM"),
        task("without period", assignee=owner.id),
        task("timed", assignee=owner.id, period="AM", due=at(10, 45)),
        task("before AM", assignee=owner.id, due=at(8, 59)),
        task("at PM", assignee=owner.id, due=at(13, 30)),
    ]
    db = session([], tasks, [], [], [], [owner])

    values = asyncio.run(svc.collect_task_items(db, owner, DAY, DAY, today=DAY, tz=TZ))

    items = {value.title: value for value in values}
    assert items["morning"].to_dict()["daypart"] == "AM"
    assert items["morning"].start == at(9)
    assert items["afternoon"].to_dict()["daypart"] == "PM"
    assert items["afternoon"].start == at(13, 30)
    assert items["without period"].to_dict()["daypart"] is None
    assert items["without period"].start is None
    assert items["timed"].start == at(10, 45)
    assert items["timed"].time_basis == "due"
    assert items["before AM"].to_dict()["daypart"] is None
    assert items["at PM"].to_dict()["daypart"] == "PM"


def test_agenda_meeting_links_and_held_status_are_per_occurrence():
    external = SimpleNamespace(
        id=uuid4(), title="Client", meeting_type="external", starts_at=at(9), ends_at=at(10),
        recurrence_type=None, meeting_url="https://teams.microsoft.com/l/meetup-join/link",
    )
    internal = SimpleNamespace(
        id=uuid4(), title="Team", meeting_type="internal", starts_at=at(14), ends_at=at(15),
        recurrence_type=None, meeting_url="https://outlook.office.com/calendar/item",
    )
    status = SimpleNamespace(meeting_id=external.id, occurrence_date=DAY, status="held")
    db = session([external, internal], [status], [(external.id, DAY)])

    values = asyncio.run(svc.collect_meeting_items(db, SimpleNamespace(id=uuid4()), DAY, DAY, tz=TZ))

    ext, intr = (value.to_dict() for value in values)
    assert (ext["type"], ext["held"], ext["status"]) == ("EXT", True, "Mbajtur")
    assert ext["join_url"] == "https://teams.microsoft.com/l/meetup-join/link"
    assert ext["notes_url"].endswith(f"/meetings/{external.id}?date=2026-11-19")
    assert (intr["type"], intr["held"], intr["status"]) == ("INT", False, "PLANNED")
    assert intr["join_url"] is None
    assert intr["notes_url"] is None


def test_bz_held_status_does_not_close_the_underlying_task():
    owner = SimpleNamespace(id=uuid4(), full_name="GA")
    alignment = task("BZ appointment")
    db = session([], [alignment], [], [(alignment.id, owner.id)], [], [alignment.id])

    values = asyncio.run(svc.collect_task_items(db, owner, DAY, DAY, today=DAY, tz=TZ))

    item = values[0].to_dict()
    assert (item["type"], item["held"], item["status"]) == ("BZ", True, "TODO")


def test_agenda_can_skip_live_graph_without_losing_local_items(monkeypatch):
    from app.api.routers import ga_assistant as routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    owner = SimpleNamespace(id=uuid4(), username=routes.settings.GA_USERNAME)
    local_meeting = svc.AgendaItem("pf_meeting:m", "primeflow", "MEETING", "Calendar sync", DAY)
    local_reminder = svc.AgendaItem("tt:r", "iphone_sync", "REMINDER", "iPhone", DAY)
    local_discord = svc.AgendaItem("dc:d", "discord", "DISCORD", "Mention", DAY)
    live_event = svc.AgendaItem("ms_event:e", "outlook", "EVENT", "Live", DAY)
    monkeypatch.setattr(svc, "collect_task_items", AsyncMock(return_value=[]))
    monkeypatch.setattr(svc, "collect_meeting_items", AsyncMock(return_value=[local_meeting]))
    monkeypatch.setattr(svc, "collect_microsoft_items", AsyncMock(return_value=([live_event], ["live warning"])))
    monkeypatch.setattr(svc, "collect_time_table_reminders", AsyncMock(return_value=([local_reminder], [])))
    monkeypatch.setattr(svc, "collect_discord_items", AsyncMock(return_value=[local_discord]))
    monkeypatch.setattr(svc, "load_day_states", AsyncMock(return_value={}))
    app = FastAPI()
    app.include_router(routes.router, prefix="/ga-assistant")
    app.dependency_overrides[routes.get_current_user] = lambda: owner
    app.dependency_overrides[routes.get_db] = lambda: None
    params = {"start": "2026-11-19", "end": "2026-11-20", "include_untimed": True}

    with TestClient(app) as client:
        cached = client.get("/ga-assistant/agenda", params={**params, "include_live_microsoft": False})
        live = client.get("/ga-assistant/agenda", params=params)

    assert cached.status_code == live.status_code == 200
    assert {value["id"] for value in cached.json()["items"]} == {"pf_meeting:m", "tt:r", "dc:d"}
    assert cached.json()["warnings"] == []
    assert {value["id"] for value in live.json()["items"]} == {"pf_meeting:m", "tt:r", "dc:d", "ms_event:e"}
