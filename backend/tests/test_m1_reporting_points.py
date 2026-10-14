from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.services import m1_reporting_points as service
from app.models.enums import CommonCategory
from app.api.routers.m1_reporting_points import ManualAnswersPayload


DAY = date(2026, 10, 13)


def at(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=service.report_timezone())


def test_morning_windows_include_boundaries_and_exclude_later_creations():
    yesterday = date(2026, 10, 12)
    notes = [
        SimpleNamespace(id="before", content="Too early", created_at=at(yesterday, 16, 29)),
        SimpleNamespace(id="start", content="Start", created_at=at(yesterday, 16, 30)),
        SimpleNamespace(id="end", content="End", created_at=at(DAY, 8, 30)),
        SimpleNamespace(id="end_minute", content="End minute", created_at=at(DAY, 8, 30).replace(second=59)),
        SimpleNamespace(id="after", content="Too late", created_at=at(DAY, 8, 31)),
    ]
    tasks = [
        SimpleNamespace(id="old", title="Yesterday", created_at=at(yesterday, 23), status="TODO"),
        SimpleNamespace(id="today", title="Today", created_at=at(DAY, 0), status="TODO"),
        SimpleNamespace(id="cutoff", title="Cutoff", created_at=at(DAY, 8, 30), status="TODO"),
        SimpleNamespace(id="later", title="Later", created_at=at(DAY, 8, 31), status="TODO"),
    ]
    data = service.select_morning_sections([], notes, [], tasks, DAY)
    assert [row["content"] for row in data["notes"]] == ["Start", "End", "End minute"]
    assert [row["title"] for row in data["tasks"]] == ["Today", "Cutoff"]


def test_new_tasks_include_meetings_owner_department_period_and_type():
    task = SimpleNamespace(id="new", title="Detyra\nPërshkrimi", created_at=at(DAY, 8), status="TODO",
                           assigned_to="ada", department_id="other", finish_period="PM", project_id=None,
                           system_template_origin_id=None, system_task_slot_id=None,
                           is_bllok=False, is_r1=False, is_1h_report=False, is_personal=False)
    users = {"ada": SimpleNamespace(full_name="Ada Test", username="ada")}
    data = service.select_morning_sections([], [], [], [task], DAY, users=users,
                                           departments={"other": "DEV"}, assignees={"new": {"ada"}})
    row = data["tasks"][0]
    assert (row["assignees"], row["department"], row["am_pm"], row["task_type"]) == ("AT", "DEV", "PM", "FT")


def test_new_notes_include_their_creator_for_both_note_sources():
    yesterday = date(2026, 10, 12)
    ga_note = SimpleNamespace(id="ga", content="PX note", created_at=at(yesterday, 17), created_by="ada")
    plan_note = SimpleNamespace(id="plan", content="JAV note", created_at=at(DAY, 8), created_by="beni")
    users = {"ada": SimpleNamespace(full_name="Ada Test"), "beni": SimpleNamespace(full_name="Beni Test")}

    data = service.select_morning_sections([], [ga_note], [plan_note], [], DAY, users=users)

    assert [(row["source"], row["author"]) for row in data["notes"]] == [
        ("PX Notes", "Ada Test"), ("PX JAV", "Beni Test"),
    ]


def test_saved_notes_gain_authors_without_changing_their_content_or_order():
    data = {"notes": [
        {"id": "ga", "source": "PX Notes", "content": "First"},
        {"id": "plan", "source": "PX JAV", "content": "Second"},
        {"id": "old", "source": "PX Notes", "content": "Third", "author": "Gane Arifaj"},
    ], "tasks": [{"id": "task"}]}

    updated = service.add_saved_note_authors(data, {("PX Notes", "ga"): "Ada Test", ("PX JAV", "plan"): "Beni Test"})

    assert [row["author"] for row in updated["notes"]] == ["Ada Test", "Beni Test", "Gane Arifaj"]
    assert [row["content"] for row in updated["notes"]] == ["First", "Second", "Third"]
    assert updated["tasks"] == data["tasks"]
    assert "author" not in data["notes"][0]


def test_new_tasks_follow_weekly_planner_order():
    def task(name, order):
        return SimpleNamespace(id=name, title=name, created_at=at(DAY, 8), assigned_to=name,
                               is_deadline_important=False, fast_task_order=None,
                               system_template_origin_id=None, system_task_slot_id=None,
                               _weekly_planner_report_sort=order)

    tasks = [task("pcm", (2, "pcm", 0, 1, "pcm")), task("dev-last", (0, "dev", 0, 2, "dev-last")),
             task("dev-first", (0, "dev", 0, 1, "dev-first"))]
    assert [item.id for item in service.sort_tasks_for_report(tasks, {}, {})] == ["dev-first", "dev-last", "pcm"]


def test_saved_unsent_report_tasks_can_be_reordered_without_replacing_answers_or_rows():
    data = {"notes": [{"id": "note"}], "tasks": [
        {"id": "pcm", "title": "First", "status": "TODO"},
        {"id": "dev-last", "title": "Second", "status": "DONE"},
        {"id": "dev-first", "title": "Third", "status": "TODO"},
    ]}
    updated = service.reorder_saved_task_rows(data, ["dev-first", "dev-last", "pcm"])
    assert [row["id"] for row in updated["tasks"]] == ["dev-first", "dev-last", "pcm"]
    assert updated["notes"] == data["notes"]
    assert updated["tasks"][1]["status"] == "DONE"
    assert updated["task_order_version"] == 1
    assert [row["id"] for row in data["tasks"]] == ["pcm", "dev-last", "dev-first"]


def test_common_view_absences_and_delays_use_report_day_and_person():
    entries = [
        SimpleNamespace(id="a", category=CommonCategory.absences, entry_date=DAY, created_at=at(DAY, 7),
                        assigned_to_user_id="person", created_by_user_id="creator", title="Other", description="From: 08:00 - To: 12:00 Sick"),
        SimpleNamespace(id="b", category=CommonCategory.delays, entry_date=DAY, created_at=at(DAY, 7),
                        assigned_to_user_id="person", created_by_user_id="creator", title="Other", description="Start: 08:00 Until: 09:00 Traffic"),
        SimpleNamespace(id="c", category="absences", entry_date=date(2026, 10, 12), created_at=at(DAY, 7),
                        assigned_to_user_id="person", created_by_user_id="creator", title="Other", description=None),
    ]
    users = {"person": SimpleNamespace(full_name="Ada Test", username="ada")}
    data = service.select_morning_sections(entries, [], [], [], DAY, users=users)
    assert [(row["person"], row["from"], row["to"]) for row in data["absences"]] == [("Ada Test", "08:00", "12:00")]
    assert [(row["person"], row["start"], row["until"]) for row in data["delays"]] == [("Ada Test", "08:00", "09:00")]


def test_render_includes_all_six_points_and_manual_comments_escaped():
    report = {"report_date": DAY.isoformat(), "manual_answers": {"plan_changes": "Po <sot>", "reorganization": "Jo"},
              "data": {"absences": [{"id": "absence", "person": "Ada", "from": "08:00", "to": "12:00", "note": "Sëmurë"}],
                       "delays": [], "notes": [{"id": "note", "source": "PX Notes", "content": "Shënim i ri", "created_at": at(DAY, 8).isoformat()}],
                       "tasks": [{"id": "task", "title": "Detyrë e re", "status": "TODO", "created_at": at(DAY, 8).isoformat()}]}}
    html = service.render_html(report)
    assert all(f"{number}." in html for number in range(1, 7))
    assert "Po &lt;sot&gt;" in html and "Po <sot>" not in html
    assert "Jo" in service.render_plain_text(report)


def test_only_the_two_manual_points_can_be_saved():
    payload = ManualAnswersPayload(manual_answers={"plan_changes": "Ndryshim", "reorganization": "Po"})
    assert len(payload.manual_answers) == 2
    with pytest.raises(ValidationError):
        ManualAnswersPayload(manual_answers={"notes": "Nuk lejohet"})


def test_report_exports_include_the_six_points():
    report = {"report_date": DAY.isoformat(), "subject": service.subject_for(DAY),
              "manual_answers": {"plan_changes": "Po", "reorganization": "Jo"},
              "data": {"absences": [], "delays": [],
                       "notes": [{"id": "note", "source": "PX Notes", "content": "Shënim i ri", "created_at": at(DAY, 8).isoformat()}],
                       "tasks": [{"id": "task", "title": "Detyrë e re", "status": "TODO",
                                  "created_at": at(DAY, 8).isoformat(), "assignees": "AT",
                                  "department": "DEV", "am_pm": "PM", "task_type": "FT"}]}}
    attachments = service.report_attachments(report)
    assert [name.rsplit(".", 1)[-1] for name, _, _ in attachments] == ["docx", "png", "xlsx"]
    assert all(content for _, content, _ in attachments)


def test_report_tables_keep_meetings_columns_and_category_colors():
    report = {"report_date": DAY.isoformat(), "manual_answers": {"plan_changes": "Po", "reorganization": "Jo"},
              "data": {
                  "absences": [{"id": "a", "person": "Ada", "from": "08:00", "to": "12:00", "note": "Sëmurë"}],
                  "delays": [{"id": "b", "person": "Beni", "start": "08:00", "until": "09:00", "note": "Trafik"}],
                  "notes": [{"id": "n", "source": "PX Notes", "author": "Ada Test", "content": "[[added]]Shënim i ri[[/added]]", "created_at": at(DAY, 8).isoformat()}],
                  "tasks": [{"id": "t", "title": "Detyrë e re", "status": "IN_PROGRESS", "created_at": at(DAY, 8).isoformat(),
                             "assignees": "AT", "department": "DEV", "am_pm": "PM", "task_type": "FT"}],
              }}
    tables = [block for block in service.export_blocks(report) if block["kind"] == "table"]
    assert [[column[1] for column in table["columns"]] for table in tables] == [
        ["NR", "PERSONI", "ORA"],
        ["NR", "PERSONI", "ORA"],
        ["NR", "KUSH", "NOTE", "KRIJUAR"],
        ["NR", "KUSH", "DEP", "AM/PM", "LLOJI", "DETYRA", "KRIJUAR"],
    ]
    assert [cell["text"] for cell in tables[3]["rows"][0][1:5]] == ["AT", "DEV", "PM", "FT"]
    assert [cell["text"] for cell in tables[2]["rows"][0][1:]] == ["AT", "Shënim i ri", "13.10.2026 08:00"]
    assert tables[3]["rows"][0][5]["text"] == "Detyrë e re"
    assert tables[3]["rows"][0][6]["text"] == "13.10.2026 08:00"
    assert [len(table["rows"][0]) for table in tables[:2]] == [3, 3]
    assert [table["rows"][0][0]["fill"] for table in tables] == ["#fee2e2", "#fef3c7", "#dbeafe", "#ffff00"]
    html = service.render_html(report)
    assert "background:#e2e8f0" in html
    assert "background:#fee2e2" in html
    assert "PERSONI" in html and "KUSH" in html and "BURIMI" not in html and "STATUSI" not in html
    assert "SHËNIMI" not in html and "Trafik" not in html and "Sëmurë" not in html
    assert "[[added]]" not in html and "Shënim i ri" in html


def test_task_exports_show_only_the_first_title_line():
    report = {"report_date": DAY.isoformat(), "manual_answers": {},
              "data": {"absences": [], "delays": [], "notes": [], "tasks": [
                  {"id": "t", "title": "\nOH: [[added]]08:00[[/added]] EM: CC EMAIL CLAIM\nPërshkrimi i gjatë i detyrës",
                   "status": "TODO", "created_at": at(DAY, 8).isoformat()},
              ]}}
    task_table = next(block for block in service.export_blocks(report) if block["kind"] == "table")
    assert task_table["rows"][0][5]["text"] == "OH: 08:00 EM: CC EMAIL CLAIM"
    html = service.render_html(report)
    assert "Përshkrimi i gjatë" not in html
    assert "[[added]]" not in html


def test_m1_migration_creates_independent_report_storage():
    from io import StringIO
    from unittest.mock import patch
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from tests.test_migration_graph import migration_scripts

    migration = migration_scripts().get_revision("0147_m1_reporting_points").module
    output = StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with patch.object(migration, "op", Operations(context)):
        migration.upgrade()
    sql = output.getvalue()
    assert "CREATE TABLE m1_reporting_points_reports" in sql
    assert "manual_answers JSONB" in sql
    assert "auto_sent_at TIMESTAMP WITH TIME ZONE" in sql
