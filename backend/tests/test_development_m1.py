import asyncio
import io
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from openpyxl import load_workbook

from app.api.routers.exports import export_department_internal_meetings_xlsx
from app.models.checklist_item import ChecklistItem
from app.models.enums import ChecklistItemType, UserRole
from app.models.task import Task
from app.models.user import User
from app.services.development_m1 import (
    DEVELOPMENT_CHECKLIST_KEY, build_development_m1, development_m1_item_sections,
    ensure_development_m1_internal_item,
)


def test_existing_checklist_questions_match_by_topic_after_reordering():
    questions = {
        "Vonesa/mungesa, a ndryshon plani per sot?": "attendance",
        "Takimet externe?": "external",
        "Takimet interne?": "internal_all",
        "Takimet int me KA + det P?": "internal",
        "A ka pyetjet per KA/Gentin?": "questions",
        "Shenime ne Teams Zhvillim / a ka ndryshim te planit?": "teams",
        "PX NOTES te reja ne PrimeFlow?": "notes",
        "EF/RA: FRG: a ka vizitore te ri?": "visitors",
        "Diskutohen detyrat e secilit per AM/PM": "plan",
        "Fizikisht me GA det ne AM??": "physical",
    }
    items = [
        ChecklistItem(id=uuid4(), item_type=ChecklistItemType.CHECKBOX, title=title, day="M1", position=position)
        for position, title in enumerate(reversed(questions))
    ]
    renamed = ChecklistItem(id=uuid4(), item_type=ChecklistItemType.CHECKBOX, title="Mesazhet", day="M1",
                            keyword="development-m1:notes")
    m2 = ChecklistItem(id=uuid4(), item_type=ChecklistItemType.CHECKBOX, title="Takimet externe?", day="M2")
    assert development_m1_item_sections([*items, renamed, m2]) == {
        **{str(item.id): questions[item.title] for item in items},
        str(renamed.id): "notes",
    }


def test_m1_shows_company_external_meetings_and_development_internal_meetings_with_ka():
    now = datetime(2026, 11, 25, 7, 5, tzinfo=timezone.utc)
    day = now.date().isoformat()
    department = SimpleNamespace(id=uuid4(), name="Development")
    staff = User(id=uuid4(), department_id=department.id, full_name="Dev Person", role=UserRole.STAFF)
    colleague = User(id=uuid4(), department_id=department.id, full_name="Dev Colleague")
    ka = User(id=uuid4(), full_name="Kosove Arifaj")
    shared = uuid4()
    tasks = [
        Task(id=uuid4(), title="Verifiko prototipin", status="TODO", due_date=now, one_h_marker="GENT,F"),
        Task(id=uuid4(), title="GT: Rishiko planin", description="Kontrollo afatet", status="IN_PROGRESS", due_date=now,
             is_personal=True, fast_task_group_id=shared, assigned_to=staff.id, one_h_marker="KA"),
        Task(id=uuid4(), title="GT: Rishiko planin", status="TODO", due_date=now,
             is_personal=True, fast_task_group_id=shared, assigned_to=colleague.id, one_h_marker="GENT"),
        Task(id=uuid4(), title="GT: Rishiko planin", status="TODO", due_date=now,
             is_personal=True, assigned_to=staff.id),
        Task(id=uuid4(), title="Jashtë ditës", status="TODO", due_date=now.replace(day=26), one_h_marker="KA"),
        Task(id=uuid4(), title="Detyrë e zakonshme", status="TODO", due_date=now),
    ]
    meeting, canceled, other_external, internal, other_internal = (uuid4() for _ in range(5))
    external_row = {"date": day, "time": "09:00", "platform": "Teams", "department": "Finance",
                    "assigneeUserIds": [str(staff.id)], "id": f"meeting:{meeting}:{day}", "title": "Klienti",
                    "calendarImported": True, "calendarCategories": ["Blue"]}
    common = SimpleNamespace(
        guardrails=SimpleNamespace(truncated={}),
        items=SimpleNamespace(
            absent=[{"id": "absence", "date": day, "userId": str(staff.id), "person": staff.full_name}],
            late=[{"id": "other-delay", "date": day, "userId": str(ka.id), "person": ka.full_name}],
            leave=[],
            external=[
                external_row,
                {**external_row, "id": f"meeting:{canceled}:{day}", "title": "Takim i anuluar",
                 "occurrenceStatus": "canceled", "recurrence_type": "weekly"},
                {**external_row, "id": f"meeting:{other_external}:{day}", "title": "Klient i Finance",
                 "time": "10:00", "assigneeUserIds": []},
            ],
            internal=[
                {**external_row, "id": f"meeting:{internal}:{day}", "title": "Plan me KA"},
                {**external_row, "id": f"meeting:{other_internal}:{day}", "title": "Finance me KA",
                 "assigneeUserIds": [str(ka.id)]},
            ],
        ),
    )
    db = AsyncMock()
    db.scalar.return_value = department
    db.scalars.side_effect = [Mock(**{"all.return_value": [staff, colleague, ka]}), Mock(**{"all.return_value": tasks})]
    db.execute.side_effect = [
        Mock(**{"all.return_value": [(internal, ka.id, None), (meeting, staff.id, "https://example.com/meeting")]}),
        Mock(**{"all.return_value": []}),
    ]
    ka_meetings = ChecklistItem(id=uuid4(), item_type=ChecklistItemType.CHECKBOX, title="Takimet int me KA?",
                                day="M1", position=3)
    ka_tasks = ChecklistItem(id=uuid4(), item_type=ChecklistItemType.CHECKBOX, title="A ka pyetje për KA/Gentin?",
                             day="M1", position=4)
    with (
        patch("app.services.development_m1.datetime") as clock,
        patch("app.services.development_m1._build_common_view", new=AsyncMock(return_value=common)),
        patch("app.services.development_m1.load_blue_notes", new=AsyncMock(
            return_value=[
                ("note-id", ["1", "NO", "Shënim", "DP", "08:00"]),
                ("email-id", ["2", "NO", "EM IT: 08:00 PURIS · Puris follow-up · Sender", "-", "09:02"]),
                ("legacy-id", ["3", "NO", "EM: GMAIL: Inbox subject Dërguesi: Sender Original body", "-", "09:07"]),
            ]
        )),
    ):
        clock.now.return_value = now
        report = asyncio.run(build_development_m1(db, staff, checklist_items=[ka_tasks, ka_meetings]))

    rows = {section["key"]: section["rows"] for section in report["sections"]}
    assert report["date"] == day
    assert [row["id"] for row in rows["attendance"]] == ["absence"]
    assert [row["title"] for row in rows["external"]] == ["Klienti", "Takim i anuluar", "Klient i Finance"]
    assert rows["external"][0]["color"] == "#DCECFF"
    assert rows["external"][0]["labels"] == ["09:00", "Teams", "CAL", "Blue"]
    assert rows["external"][0]["meeting"] == {
        "id": str(meeting), "date": day,
        "type": "external", "time": "09:00", "calendarImported": True, "calendarCategories": ["Blue"],
    }
    assert rows["external"][0]["meeting_url"] == "https://example.com/meeting"
    assert rows["external"][1]["canceled"]
    assert rows["external"][1]["labels"] == ["09:00", "Teams", "CAL", "Anuluar", "weekly", "Blue"]
    assert rows["external"][1]["meeting"] == {
        **rows["external"][0]["meeting"], "id": str(canceled), "recurrence_type": "weekly",
        "occurrenceStatus": "canceled",
    }
    assert [row["title"] for row in rows["internal"]] == ["Plan me KA"]
    assert rows["internal"][0]["meeting"]["id"] == str(internal)
    assert rows["internal"][0]["meeting"]["date"] == day
    assert [row["title"] for row in rows["internal_all"]] == ["Plan me KA", "Finance me KA"]
    assert [row["id"] for row in rows["questions"]] == [str(tasks[index].id) for index in (0, 1, 3)]
    assert "Personal me GENTI" in rows["questions"][1]["labels"]
    assert rows["questions"][1]["task_status_labels"] == ["In progress", "To do"]
    assert {"In progress", "To do"} <= set(rows["questions"][1]["labels"])
    assert rows["questions"][1]["task_assignees"] == ["Dev Colleague", "Dev Person"]
    assert rows["questions"][1]["detail"] == "Kontrollo afatet"
    assert rows["questions"][1]["marker"] == "KA,GENT"
    assert rows["questions"][0]["marker"] == "GENT,F"
    assert [row["id"] for row in rows["physical"]] == [str(tasks[0].id)]
    assert rows["physical"][0]["task_status_labels"] == ["To do"]
    assert [row["id"] for row in rows["notes"]] == ["note-id", "email-id", "legacy-id"]
    assert "email_heading" not in rows["notes"][0]
    assert rows["notes"][1]["email_heading"] == "EM IT: 08:00 PURIS"
    assert rows["notes"][1]["title"] == "EM IT: 08:00 PURIS · Puris follow-up · Sender"
    assert rows["notes"][2]["email_heading"] == "EM: GMAIL: Inbox subject"
    assert rows["plan"] == []
    assert report["item_sections"][str(ka_meetings.id)] == "ka_gent"
    assert report["hidden_item_ids"] == [str(ka_tasks.id)]
    assert rows["ka_gent"] == [
        {"id": "internal", "title": "Takimet interne me KA", "detail": "", "heading": True},
        *rows["internal"],
        {"id": "questions", "title": "Pyetjet dhe detyrat për KA / Gentin", "detail": "", "heading": True},
        *rows["questions"],
    ]


def test_m1_excel_places_the_colored_answer_directly_under_the_checked_question():
    checked = ChecklistItem(id=uuid4(), item_type=ChecklistItemType.CHECKBOX, title="PX Notes të reja?",
                            day="M1", is_checked=True, position=1)
    manual = ChecklistItem(id=uuid4(), item_type=ChecklistItemType.CHECKBOX, title="Pyetje shtesë",
                            day="M1", is_checked=False, position=2)
    combined = ChecklistItem(id=uuid4(), item_type=ChecklistItemType.CHECKBOX, title="Takimet KA?",
                              day="M1", is_checked=True, position=3)
    hidden = ChecklistItem(id=uuid4(), item_type=ChecklistItemType.CHECKBOX, title="Pyetje KA?",
                            day="M1", position=4)
    report = {"date": "2026-11-25", "item_sections": {str(checked.id): "notes", str(combined.id): "ka_gent"},
              "hidden_item_ids": [str(hidden.id)], "sections": [
        {"key": "notes", "title": "PX Notes", "message": None,
         "rows": [{"title": "=1+1", "detail": "DP", "labels": ["AM"], "color": "#DCECFF"}]},
        {"key": "ka_gent", "title": "Çfarë kemi me KA / Gentin sot?", "message": None,
         "rows": [
             {"title": "Takimet interne me KA", "detail": "", "heading": True},
             {"title": "Rishiko planin", "detail": "Kontrollo afatet",
              "task_assignees": ["Dev Colleague", "Dev Person"], "labels": ["In progress"]},
         ]},
    ]}
    db = AsyncMock()
    db.execute.return_value = Mock(**{"scalars.return_value.all.return_value": [
        SimpleNamespace(items=[manual, checked, hidden, combined]),
    ]})
    user = SimpleNamespace(role=UserRole.ADMIN, full_name="Dev Person", username="dev")

    async def download():
        response = await export_department_internal_meetings_xlsx(
            group_key=DEVELOPMENT_CHECKLIST_KEY, title="Development Internal Meetings", db=db, user=user,
        )
        return b"".join([part async for part in response.body_iterator])

    with patch("app.api.routers.exports.build_development_m1", new=AsyncMock(return_value=report)):
        workbook = load_workbook(io.BytesIO(asyncio.run(download())))

    assert workbook.sheetnames == ["Internal Meetings"]
    assert workbook.active["B5"].value == checked.title
    assert workbook.active["C5"].value == "✓"
    assert workbook.active["B6"].value == "=1+1\nAM · DP"
    assert workbook.active["B6"].data_type == "s"
    assert workbook.active["B6"].fill.fgColor.rgb == "00DCECFF"
    assert workbook.active["B7"].value == manual.title
    assert workbook.active["B8"].value == "Çfarë kemi me KA / Gentin sot?"
    assert workbook.active["C8"].value == "✓"
    assert workbook.active["B9"].value == "Takimet interne me KA"
    assert workbook.active["B10"].value == "Rishiko planin\nIn progress · Dev Colleague, Dev Person\nKontrollo afatet"
    assert hidden.title not in [cell.value for cell in workbook.active["B"]]


def test_existing_m1_checklist_inserts_internal_meetings_once_after_external():
    checklist_id = uuid4()
    external = ChecklistItem(id=uuid4(), item_type=ChecklistItemType.CHECKBOX,
                             title="Takimet externe?", day="M1", position=2, path="INTERNAL_MEETINGS")
    db = AsyncMock()
    db.scalar.return_value = checklist_id
    items = [external]
    db.scalars.return_value = Mock(**{"all.return_value": items})
    db.add = Mock(side_effect=items.append)

    assert asyncio.run(ensure_development_m1_internal_item(db, checklist_id))
    assert items[-1].position == 3
    assert items[-1].path == external.path
    assert items[-1].keyword == "development-m1:internal_all"
    assert not items[-1].is_checked
    assert not asyncio.run(ensure_development_m1_internal_item(db, checklist_id))
    db.execute.assert_awaited_once()
