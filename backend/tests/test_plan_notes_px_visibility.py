import asyncio
import io
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from openpyxl import load_workbook
from sqlalchemy import create_engine, text

from app.api.routers.exports import export_ga_notes_xlsx
from app.api.routers.plan_notes import list_plan_notes
from app.models.enums import GaNoteStatus, TaskStatus, UserRole
from app.models.plan_note import PlanNote


def note_list_query(**kwargs):
    db = SimpleNamespace(execute=AsyncMock(return_value=Mock(
        scalars=Mock(return_value=Mock(all=Mock(return_value=[])))
    )))
    asyncio.run(list_plan_notes(
        db=db, user=SimpleNamespace(), limit=None, offset=0,
        **kwargs,
    ))
    return db.execute.call_args.args[0].with_only_columns(PlanNote.id)


def test_px_notes_find_existing_tasks_even_when_conversion_flag_is_stale():
    engine = create_engine("sqlite://")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE plan_notes (id TEXT, is_converted_to_task BOOLEAN, "
                        "status TEXT, completed_at DATETIME, created_at DATETIME)"))
        db.execute(text("CREATE TABLE tasks (id TEXT, plan_note_origin_id TEXT, is_active BOOLEAN)"))
        ids = [f"{number:032x}" for number in range(1, 5)]
        for index, note_id in enumerate(ids):
            db.execute(text("INSERT INTO plan_notes VALUES (:id, :converted, 'OPEN', NULL, "
                            "'2026-11-13')"), dict(id=note_id, converted=index == 3))
        for task_id, origin, active in [("a", ids[0], True), ("b", ids[0], True),
                                        ("c", ids[1], False)]:
            db.execute(text("INSERT INTO tasks VALUES (:id, :origin, :active)"),
                       dict(id=task_id, origin=origin, active=active))

        px_rows = db.execute(note_list_query(converted_to_task_only=True)).scalars().all()
        assert [row.hex for row in px_rows] == [ids[3], ids[0]]
        # Ordinary PX JAV listing still includes notes that have no task.
        all_rows = db.execute(note_list_query()).scalars().all()
        assert len(all_rows) == 4
    engine.dispose()


def test_excel_includes_px_jav_task_with_assignee_and_status():
    note_id, owner_id = uuid.uuid4(), uuid.uuid4()
    note = SimpleNamespace(
        id=note_id, content="Detyra nga PX JAV", created_by=None,
        created_at=datetime.now(timezone.utc), department_id=None, project_id=None,
        is_converted_to_task=False, status=GaNoteStatus.OPEN, is_discussed=False,
    )
    task = SimpleNamespace(
        ga_note_origin_id=None, plan_note_origin_id=note_id, assigned_to=owner_id,
        assignees=[], status=TaskStatus.IN_PROGRESS,
    )
    owner = SimpleNamespace(id=owner_id, full_name="Test Person", username="test")
    def result(values):
        return Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=values))))
    db = SimpleNamespace(execute=AsyncMock(side_effect=[
        result([]), result([task]), result([owner]),
    ]))
    user = SimpleNamespace(role=UserRole.ADMIN, full_name="Admin", username="admin")

    async def export():
        response = await export_ga_notes_xlsx(db=db, user=user)
        return b"".join([chunk async for chunk in response.body_iterator])

    with patch("app.api.routers.plan_notes.list_plan_notes", AsyncMock(return_value=[note])) as listing:
        workbook = load_workbook(io.BytesIO(asyncio.run(export())))
    assert listing.call_args.kwargs["converted_to_task_only"] is True
    sheet = workbook.active
    assert sheet["B5"].value == "Detyra nga PX JAV"
    assert sheet["E5"].value == "TP"
    assert sheet["H5"].value == "Task Created"
    assert sheet["B5"].fill.fgColor.rgb.endswith("FDE68A")
