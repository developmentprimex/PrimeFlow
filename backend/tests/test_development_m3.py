import asyncio
import io
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch
from uuid import uuid4

from openpyxl import load_workbook

from app.api.routers.exports import export_department_internal_meetings_xlsx
from app.models.checklist_item import ChecklistItem
from app.models.enums import ChecklistItemType, UserRole
from app.models.task import Task
from app.models.user import User
from app.services.development_m1 import DEVELOPMENT_CHECKLIST_KEY
from app.services.development_m3 import INTERNAL_MEETINGS_TITLE, build_development_m3


def test_m3_live_answers_and_excel_share_the_development_checklist():
    now = datetime(2026, 11, 26, 15, tzinfo=timezone.utc)
    friday, monday = date(2026, 11, 27), date(2026, 11, 30)
    department = SimpleNamespace(id=uuid4(), name="Development")
    staff = User(id=uuid4(), department_id=department.id, full_name="Dev Person", role=UserRole.ADMIN)
    gent = User(id=uuid4(), full_name="Gent Arifaj")
    titles = [
        "A KA SHENIME TE REJA PF PX NOTES / ZHVILLIM TEAMS?",
        "CKA U PERFUNDU DHE CKA MBETET PER NESER?",
        "PV NESER PASNESER",
        "A KA DOC ME U DERGU TEK KA/GA? SIMBOLET COMMON VIEW?",
        "A KA TAKIME INTERNE ME GA/KA/GENT",
        "TAKIME EXT PER NESER",
    ]
    items = [ChecklistItem(id=uuid4(), day="M3", item_type=ChecklistItemType.CHECKBOX,
                           title=title, position=index, is_checked=index == 1)
             for index, title in enumerate(titles)]
    tasks = [
        Task(id=uuid4(), title=title, status="TODO", one_h_marker=marker, start_date=now,
             due_date=now.replace(day=due), assigned_to=staff.id)
        for title, marker, due in [("Dokumenti M3", "M3", 26), ("Dokumenti M2/3", "M2_M3", 27),
                                   ("Vetëm M2", "M2", 26), ("Jashtë afatit", "M3", 25)]
    ]
    external_id, internal_id, unrelated_id = uuid4(), uuid4(), uuid4()
    meeting = {"date": friday.isoformat(), "time": "09:00", "department": "Development",
               "assigneeUserIds": [str(gent.id)]}
    leave = {"id": "entry:pv", "person": "Dev Person", "userId": str(staff.id),
             "startDate": friday.isoformat(), "endDate": monday.isoformat(), "fullDay": True}
    first_week = SimpleNamespace(
        leave=[leave],
        external=[{**meeting, "id": f"meeting:{external_id}:{friday}", "title": "Klienti",
                   "calendarImported": True, "occurrenceStatus": "canceled"},
                  {**meeting, "id": f"meeting:{external_id}:{monday}", "title": "Dita e gabuar", "date": monday.isoformat()}],
        internal=[{**meeting, "id": f"meeting:{internal_id}:{friday}", "title": "Plan me Gentin"},
                  {**meeting, "id": f"meeting:{unrelated_id}:{friday}", "title": "Takim i Finance", "department": "Finance",
                   "assigneeUserIds": [str(staff.id)]}],
    )
    db = AsyncMock()
    db.scalar.return_value = department
    db.scalars.side_effect = [Mock(**{"all.return_value": rows}) for rows in ([staff, gent], tasks)]
    db.execute.side_effect = [Mock(**{"all.return_value": []}), Mock(**{"all.return_value": [(internal_id, staff.id, None)]})]

    with (
        patch("app.services.development_m3.datetime") as clock,
        patch("app.services.development_m3.load_blue_notes", new=AsyncMock(return_value=[
            ("note-id", ["1", "NO", "Shënim për diskutim", "DP", "08:00"]),
        ])) as notes,
        patch("app.services.development_m3.load_development_common_view", new=AsyncMock(
            side_effect=[first_week, SimpleNamespace(leave=[leave])],
        )) as common_view,
    ):
        clock.now.return_value = now
        report = asyncio.run(build_development_m3(db, staff, checklist_items=items))

    assert common_view.await_args_list == [call(db, friday), call(db, monday)]
    notes.assert_awaited_once_with(db, created_before=now)
    assert list(report["item_sections"].values()) == ["notes", "leave", "delivery", "internal", "external"]
    sections = {section["key"]: section["rows"] for section in report["sections"]}
    assert [row["labels"][0] for row in sections["leave"]] == ["27.11.2026", "30.11.2026"]
    assert [row["title"] for row in sections["delivery"]] == ["Dokumenti M3", "Dokumenti M2/3"]
    assert report["item_titles"] == {str(items[4].id): INTERNAL_MEETINGS_TITLE}
    assert [row["title"] for row in sections["internal"]] == ["Plan me Gentin", "Takim i Finance"]
    assert len(sections["external"]) == 1
    assert sections["external"][0]["meeting"]["date"] == friday.isoformat()
    assert sections["external"][0]["canceled"] is True

    db.execute.side_effect = None
    db.execute.return_value = Mock(**{"scalars.return_value.all.return_value": [SimpleNamespace(items=items)]})

    async def download():
        response = await export_department_internal_meetings_xlsx(
            group_key=DEVELOPMENT_CHECKLIST_KEY, title="Development Internal Meetings", db=db, user=staff,
        )
        return b"".join([part async for part in response.body_iterator])

    with (
        patch("app.api.routers.exports.build_development_m1", new=AsyncMock(return_value=None)),
        patch("app.api.routers.exports.build_development_m3", new=AsyncMock(return_value=report)) as build,
    ):
        data = asyncio.run(download())
    build.assert_awaited_once_with(db, staff, checklist_items=items)
    rows = list(load_workbook(io.BytesIO(data)).active.values)
    manual = rows.index((2, titles[1], "✓"))
    assert rows[manual + 1][1] == titles[2]
    internal = rows.index((5, INTERNAL_MEETINGS_TITLE, None))
    assert rows[internal + 2][1].startswith("Takim i Finance\n")
    assert any(str(row[1]).startswith("Shënim për diskutim") for row in rows)
    assert any(str(row[1]).startswith("Klienti\n") and "Anuluar" in row[1] for row in rows)
