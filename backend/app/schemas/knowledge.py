from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field
from app.models.knowledge_kind import KnowledgeType


class KnowledgeUserRef(BaseModel):
    id: uuid.UUID
    full_name: str | None = None


class KnowledgePromptOut(BaseModel):
    knowledge_type: KnowledgeType = "PROMPT"
    id: uuid.UUID
    title: str
    content: str
    keywords: list[str] = []
    files_path: str | None = None
    source_note_id: uuid.UUID | None = None
    status: str
    created_by: KnowledgeUserRef | None = None
    tester: KnowledgeUserRef | None = None
    test_task_id: uuid.UUID | None = None
    test_task_status: str | None = None
    tested_by: KnowledgeUserRef | None = None
    tested_at: datetime | None = None
    test_comment: str | None = None
    approved_by: KnowledgeUserRef | None = None
    approved_at: datetime | None = None
    rejected_by: KnowledgeUserRef | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    file_original_name: str | None = None
    file_content_type: str | None = None
    file_size: int | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgePromptBrief(BaseModel):
    knowledge_type: KnowledgeType = "PROMPT"
    id: uuid.UUID
    title: str
    status: str
    created_by: KnowledgeUserRef | None = None
    tested_by: KnowledgeUserRef | None = None
    tested_at: datetime | None = None
    tester: KnowledgeUserRef | None = None
    test_task_status: str | None = None


class PromptNoteTaskOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    assignee: KnowledgeUserRef | None = None
    due_date: datetime | None = None
    completed_at: datetime | None = None


class PromptNoteOut(BaseModel):
    knowledge_type: KnowledgeType = "PROMPT"
    id: uuid.UUID
    content: str
    status: str
    priority: str | None = None
    department_id: uuid.UUID | None = None
    is_converted_to_task: bool
    created_by: KnowledgeUserRef | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    tasks: list[PromptNoteTaskOut] = []
    prompts: list[KnowledgePromptBrief] = []
    tester: KnowledgeUserRef | None = None


class PromptNoteCreate(BaseModel):
    knowledge_type: KnowledgeType = "PROMPT"
    content: str = Field(min_length=2, max_length=10000)
    department_id: uuid.UUID | None = None
    priority: str | None = Field(default=None, pattern=r"^(NORMAL|HIGH)$")


class PromptNoteUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=2, max_length=10000)
    status: str | None = Field(default=None, pattern=r"^(OPEN|CLOSED)$")
    tester_id: uuid.UUID | None = None


class PromptReviewAction(BaseModel):
    comment: str | None = Field(default=None, max_length=4000)
