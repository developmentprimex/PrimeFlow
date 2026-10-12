import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret")

from app.api.routers import knowledge as api
from app.models.enums import UserRole
from app.schemas.knowledge import PromptNoteCreate, PromptReviewAction
from app.services.knowledge_task_guard import locked_reason


@pytest.mark.parametrize("kind,route,prefix", [("PROMPT", "prompts", "PROMPT: TESTO"), ("DEFINITION", "definime", "DEFINIM: KONTROLLO"), ("REGULATION", "rregullore", "RREGULLORE: KONTROLLO")])
def test_category_lists_and_task_links(kind, route, prefix):
    db = SimpleNamespace(execute=AsyncMock(return_value=MagicMock()))
    db.execute.return_value.scalars.return_value.all.return_value = []
    asyncio.run(api.list_prompts(knowledge_type=kind, status_filter=None, db=db, user=None))
    statement = db.execute.call_args.args[0]
    assert statement.compile().params["knowledge_type_1"] == kind
    asyncio.run(api.list_prompt_notes(knowledge_type=kind, db=db, user=None))
    statement = db.execute.call_args.args[0]
    assert statement.compile().params["knowledge_type_1"] == kind
    assert api.test_task_title("Title", kind) == f"{prefix}: Title"
    assert f"/knowledge/{route}?prompt=" in api.prompt_link(None, uuid.uuid4(), kind)


def test_existing_notes_default_to_prompts_and_unknown_category_is_rejected():
    assert PromptNoteCreate(content="Request").knowledge_type == "PROMPT"
    with pytest.raises(ValidationError):
        PromptNoteCreate(content="Request", knowledge_type="OTHER")


@pytest.mark.parametrize("kind", ["DEFINITION", "REGULATION"])
def test_saved_material_keeps_category_and_creates_control_task(kind, monkeypatch):
    author = SimpleNamespace(id=uuid.uuid4())
    reviewer = SimpleNamespace(id=uuid.uuid4())
    db = SimpleNamespace(add=MagicMock(), commit=AsyncMock())
    monkeypatch.setattr(api, "_validate_tester", AsyncMock(return_value=reviewer))
    monkeypatch.setattr(api, "_get_prompt_or_404", AsyncMock(side_effect=lambda *_: db.add.call_args.args[0]))
    monkeypatch.setattr(api, "_sync_creator_tasks", AsyncMock())
    control_task = AsyncMock(return_value=uuid.uuid4())
    monkeypatch.setattr(api, "_create_test_task", control_task)
    monkeypatch.setattr(api, "_single_prompt_out", AsyncMock(side_effect=lambda _, entry: entry))
    saved = asyncio.run(api.create_prompt(request=None, title="Title", knowledge_type=kind, content="Body", keywords="word", files_path="", source_note_id=None, tester_id=reviewer.id, file=None, db=db, user=author))
    assert saved.knowledge_type == kind
    assert saved.content == "Body"
    assert saved.status == "PENDING_TEST"
    assert saved.test_task_id == control_task.return_value
    assert "KONTROLLO" in api.test_task_title(saved.title, saved.knowledge_type)


def test_material_cannot_link_to_a_different_category_request(monkeypatch):
    note = SimpleNamespace(knowledge_type="DEFINITION")
    monkeypatch.setattr(api, "_get_prompt_note_or_404", AsyncMock(return_value=note))
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.create_prompt(request=None, title="Title", knowledge_type="REGULATION", content="Body", keywords="", files_path="", source_note_id=uuid.uuid4(), tester_id=None, file=None, db=None, user=None))
    assert error.value.status_code == 400


@pytest.mark.parametrize("kind", ["DEFINITION", "REGULATION"])
def test_only_assigned_controller_can_confirm_then_independent_manager_approves(kind, monkeypatch):
    author_id, reviewer_id = uuid.uuid4(), uuid.uuid4()
    entry = SimpleNamespace(id=uuid.uuid4(), title="Title", knowledge_type=kind, status="PENDING_TEST", created_by=author_id, tester_id=reviewer_id, source_note_id=None, tested_by=None)
    monkeypatch.setattr(api, "_get_prompt_or_404", AsyncMock(return_value=entry))
    monkeypatch.setattr(api, "_single_prompt_out", AsyncMock(side_effect=lambda _, item: item))
    for name in ["_complete_test_task", "_complete_author_tasks"]:
        monkeypatch.setattr(api, name, AsyncMock())
    db = SimpleNamespace(commit=AsyncMock())
    for user_id in [author_id, uuid.uuid4()]:
        with pytest.raises(HTTPException) as error:
            asyncio.run(api.confirm_prompt_test(entry.id, PromptReviewAction(), db, SimpleNamespace(id=user_id)))
        assert error.value.status_code == 403
    asyncio.run(api.confirm_prompt_test(entry.id, PromptReviewAction(comment="Checked"), db, SimpleNamespace(id=reviewer_id)))
    assert entry.status == "PENDING_APPROVAL"
    assert entry.test_comment == "Checked"
    api._complete_test_task.assert_awaited_once()
    api._complete_author_tasks.assert_awaited_once()
    for user_id in [author_id, reviewer_id]:
        with pytest.raises(HTTPException) as error:
            asyncio.run(api.approve_prompt(entry.id, db, SimpleNamespace(id=user_id, role=UserRole.MANAGER)))
        assert error.value.status_code == 403
    asyncio.run(api.approve_prompt(entry.id, db, SimpleNamespace(id=uuid.uuid4(), role=UserRole.MANAGER)))
    assert entry.status == "APPROVED"


@pytest.mark.parametrize("kind", ["DEFINITION", "REGULATION"])
def test_control_and_author_tasks_cannot_close_before_control(kind):
    task = SimpleNamespace(id=uuid.uuid4(), ga_note_origin_id=uuid.uuid4())
    db = MagicMock()
    db.execute.return_value.one_or_none.return_value = SimpleNamespace(status="PENDING_TEST", knowledge_type=kind)
    assert "E kontrollova" in locked_reason(db, task)
    db.execute.side_effect = [
        SimpleNamespace(one_or_none=lambda: None),
        SimpleNamespace(one_or_none=lambda: SimpleNamespace(status="OPEN", knowledge_type=kind)),
        SimpleNamespace(scalar_one_or_none=lambda: None),
    ]
    assert "kontrollohet" in locked_reason(db, task)
