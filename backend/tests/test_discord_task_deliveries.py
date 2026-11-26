import asyncio
from datetime import date, datetime
from io import BytesIO
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


def test_difference_rows_share_a_group_across_task_copies_and_fields(monkeypatch):
    shared_group = uuid4()
    title = "Detyra e përbashkët"
    tasks = [SimpleNamespace(id=uuid4(), fast_task_group_id=group, is_deadline_important=False, fast_task_order=None)
             for group in (shared_group, shared_group, uuid4())]
    database = SimpleNamespace(scalars=AsyncMock(return_value=tasks))
    monkeypatch.setattr(deliveries, "weekly_planner_user_sort_keys", AsyncMock(return_value={}))
    monkeypatch.setattr(deliveries, "_task_appearance", lambda task, title: ("", "", False))
    differences = [
        {"task_id": str(task.id), "field": field, "owner_id": str(uuid4()),
         "task_title": title, "person": "Punonjësi", "peers": []}
        for task, field in zip(tasks, ("slot", "marker", "slot"))
    ]

    rows = asyncio.run(deliveries._format_reporting_differences(database, differences))

    assert rows[0]["task_group_id"] == rows[1]["task_group_id"]
    assert rows[0]["task_group_id"] != rows[2]["task_group_id"]


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


def test_bz_m3_shows_only_the_matching_posts_and_discord_files(monkeypatch):
    monkeypatch.setattr(deliveries.settings, "DISCORD_GA_REPLIES_CHANNEL_ID", "123")
    file_url = "https://cdn.discordapp.com/attachments/123/456/result.txt"
    first = post("1", local_time(12), title=task()["title"] + "\nM2 result", attachments=[
        {"filename": "result.txt", "url": file_url},
        {"filename": "other.txt", "url": "https://example.com/attachments/123/789/other.txt"},
    ])
    second = post("2", local_time(16), title=task()["title"] + "\nM3 result")
    rows = [task("M2", "M3")]
    now = local_time(17)

    result = _delivery_results(rows, [second, first], DAY, now, include_details=True)[0]["deliveries"]

    assert result["M2"]["details"] == {
        "content": first["content"],
        "attachments": [{"name": "result.txt", "url": file_url}, {"name": "other.txt"}],
    }
    assert result["M3"]["details"] == {"content": second["content"], "attachments": []}
    shared = _delivery_results(rows, [first, second], DAY, now)[0]["deliveries"]
    assert all("details" not in record for record in shared.values())


def test_bz_m3_archive_retains_file_names_when_live_links_are_unavailable():
    content = task()["title"] + "\nArchived result"
    db = SimpleNamespace(execute=AsyncMock(return_value=Mock(
        **{"all.return_value": [("1", "42", content, local_time(16), None, [
            {"name": "archived.txt", "url": "https://cdn.discordapp.com/attachments/123/456/archived.txt"},
        ])]},
    )))
    now = local_time(17)

    messages = asyncio.run(deliveries._archived_messages(db, "123", {"42"}, DAY, now))
    result = _delivery_results([task("M3")], messages, DAY, now, complete=False,
                               include_details=True)[0]["deliveries"]["M3"]

    assert result["details"] == {"content": content, "attachments": [{"name": "archived.txt"}]}
    assert result["url"].endswith("/1")


def test_reporting_points_reuse_each_persons_discord_result_for_their_slot(monkeypatch):
    from app.services import m1_reporting_points as m1, m2_reporting_points as m2, m3_reporting_points as m3
    from app.services.m3_reporting_points_attachments import export_blocks
    from app.services.report_attendance import ReportAttendance

    now = local_time(17)
    first = dict(task("M2", "M3"), id="task:one", task_id="task", person="One Person", initials="OP",
                 user_id="one", symbol="M2/3", status="TODO")
    second = dict(first, id="task:two", discord_id="43", person="Two Person", initials="TP", user_id="two")
    third = dict(first, id="task:three", discord_id="44", person="Absent Person", initials="AP", user_id="three")
    monkeypatch.setattr(deliveries.settings, "DISCORD_GA_REPLIES_CHANNEL_ID", "123")
    file_url = "https://cdn.discordapp.com/attachments/123/456/result.txt"
    messages = [
        post("1", local_time(12), title=first["title"] + "\nMorning <result>", attachments=[
            {"filename": "morning.txt", "url": file_url},
        ]),
        post("2", local_time(16), author="43", title=first["title"] + "\nAfternoon result"),
    ]
    checked = _delivery_results([first, second, third], messages, DAY, now, include_details=True)
    check = AsyncMock(return_value=(now, "live", True, checked))
    monkeypatch.setattr(deliveries, "checked_deliveries", check)
    monkeypatch.setattr(deliveries, "load_report_attendance", AsyncMock(return_value=ReportAttendance(user_ids={"three"})))
    report = {"report_date": DAY.isoformat(), "data": {"delivery": [first]}, "manual_answers": {"delivery_choice:task": "PO"}}

    for slot, expected, render_blocks, render_html, render_plain in (
        ("M2", ["on_time", "missing"], m1.export_blocks, m1.render_html, m1.render_plain_text),
        ("M2", ["on_time", "missing"], m2.export_blocks, m2.render_html, m2.render_plain_text),
        ("M3", ["missing", "on_time"], export_blocks, m3.render_html, m3.render_plain_text),
    ):
        connected = asyncio.run(deliveries.with_discord_delivery(None, report, slot))
        delivery_rows = connected["data"]["delivery"]
        assert [row["assignees"] for row in delivery_rows] == ["OP", "TP"]
        assert [row["discord_delivery"]["status"] for row in delivery_rows] == expected
        assert m3.delivery_summary(connected) == "SA/TOTALI: 1/2"
        rendered_html = render_html(connected)
        assert "PO/JO · DISCORD" in rendered_html
        table = next(block for block in render_blocks(connected) if block["kind"] == "table"
                     and any(label == "PO/JO · DISCORD" for _, label, _ in block["columns"]))
        assert [row[-2]["text"] for row in table["rows"]] == (["PO · 12:00", "JO"] if slot == "M2" else ["JO", "PO · 16:00"])
        delivered_index = 0 if slot == "M2" else 1
        evidence = delivery_rows[delivered_index]["discord_delivery"]
        assert evidence["details"]["content"] == messages[delivered_index]["content"]
        assert "details" not in delivery_rows[1 - delivered_index]["discord_delivery"]
        details_column = next(i for i, (key, _, _) in enumerate(table["columns"]) if key == "delivery_details")
        details = table["rows"][delivered_index][details_column]
        assert details["url"] == evidence["url"]
        assert evidence["url"] in details["text"]
        assert evidence["url"] in render_plain(connected)
        if slot == "M2":
            assert "Morning &lt;result&gt;" in rendered_html
            assert file_url in rendered_html and "morning.txt" in details["text"]
        else:
            assert "Afternoon result" in rendered_html
    assert all(call.kwargs == {"include_details": True} for call in check.await_args_list)


def test_report_files_export_the_discord_delivery_and_source_links():
    from docx import Document
    from openpyxl import load_workbook
    from PIL import Image

    from app.services import m1_reporting_points as m1, m2_reporting_points as m2
    from app.services.m3_reporting_points_attachments import report_attachments as m3_attachments
    from app.services.task_pause import TASK_PAUSE_BACKGROUND, TASK_PAUSE_LABEL

    source = "https://discord.com/channels/123/456/789"
    file_url = "https://cdn.discordapp.com/attachments/456/789/results.txt"
    row = dict(task("M2", "M3"), task_id="task", assignees="OP", status="TODO", symbol="M2/3", is_paused=True,
               discord_delivery={"status": "on_time", "url": source, "details": {
                   "content": "Discord result\nSecond line",
                   "attachments": [{"name": "results.txt", "url": file_url}],
               }})
    for slot, attachments in (("M2", m1.report_attachments), ("M2", m2.report_attachments), ("M3", m3_attachments)):
        report = {"report_date": DAY.isoformat(), "discord_delivery_slot": slot, "data": {"delivery": [row]}}
        files = {filename.rsplit(".", 1)[-1]: content for filename, content, _ in attachments(report)}
        document = Document(BytesIO(files["docx"]))
        assert any("Discord result\nSecond line" in cell.text
                   for table in document.tables for row_cells in table.rows for cell in row_cells.cells)
        assert {source, file_url} <= {rel.target_ref for rel in document.part.rels.values() if rel.is_external}
        workbook = load_workbook(BytesIO(files["xlsx"]))
        title_cell = next(cell for cells in workbook.active.iter_rows() for cell in cells
                          if isinstance(cell.value, str) and TASK_PAUSE_LABEL in cell.value)
        assert title_cell.fill.fgColor.rgb.endswith(TASK_PAUSE_BACKGROUND[1:])
        cell = next(cell for cells in workbook.active.iter_rows() for cell in cells
                    if isinstance(cell.value, str) and "Discord result" in cell.value)
        assert "results.txt" in cell.value and source in cell.value
        assert cell.hyperlink.target == source
        workbook.close()
        with Image.open(BytesIO(files["png"])) as image:
            image.verify()

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

    def report_task(id, owner, title, *, deadline=False, system=False, paused=False):
        return SimpleNamespace(
            id=id, assigned_to=owner.id, department_id=owner.department_id, title=title,
            is_deadline_important=deadline, status="IN_PROGRESS", due_date=local_time(16),
            created_at=local_time(9), fast_task_order=None, system_template_origin_id=system,
            system_task_slot_id=None,
            pause_periods=[{"from": DAY.isoformat(), "until": DAY.isoformat()}] if paused else [],
        )

    results = iter((
        [
            (report_task("regular", dev, "A e zakonshme", paused=True), None, "M3", False),
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
    assert rows[2]["is_paused"] is True
    assert rows[2]["fill"] == "#F1F3F5"
    assert rows[2]["title"] == "A e zakonshme"
