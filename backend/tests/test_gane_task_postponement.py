import asyncio
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine

from app.services.task_postponement import (
    check_task_postponement_explanation,
    check_note_postponement_explanations,
)


@pytest.mark.parametrize("field", ["start_date", "due_date"])
@pytest.mark.parametrize("identity", [
    (" GA@PRIMEXEU.COM ", "ga", "GA"),
    ("other@example.com", " Gane.Arifaj ", "GA"),
    ("other@example.com", "gane_arifaj", "GA"),
    ("other@example.com", "gane", "GA"),
    ("other@example.com", "ga", " Gane Arifaj "),
    ("other@example.com", "other", "Other User"),
])
def test_gane_identity_allows_postponement_and_preserves_voluntary_explanations(field, identity):
    owner_id = uuid.uuid4()
    task = SimpleNamespace(id=uuid.uuid4(), title="Task", assigned_to=owner_id,
                           start_date=date(2026, 10, 20), due_date=date(2026, 10, 20),
                           project_id=None, is_active=True)
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id CHAR(32) PRIMARY KEY, email TEXT, username TEXT, full_name TEXT)")
        connection.exec_driver_sql("INSERT INTO users VALUES (?, ?, ?, ?)", (owner_id.hex, *identity))
        db = AsyncMock()
        db.execute.side_effect = connection.execute
        updates = {field: "2026-10-21"}
        call = check_task_postponement_explanation(db, task=task, updates=updates, reason_code=None, comment=None)
        if identity[1] == "other":
            with pytest.raises(HTTPException):
                asyncio.run(call)
        else:
            assert asyncio.run(call) == {}
            assert asyncio.run(check_note_postponement_explanations(
                db, tasks=[task], updates_by_assignee={owner_id: updates}, explanations={},
            )) == {task.id: {}}
        explanation = asyncio.run(check_task_postponement_explanation(
            db, task=task, updates=updates, reason_code="OTHER", comment=" Optional explanation ",
        ))
        assert explanation["comment"] == "Optional explanation"
    engine.dispose()
