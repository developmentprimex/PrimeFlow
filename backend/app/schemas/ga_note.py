from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field
from app.schemas.task_postponement import TaskPostponementExplanations


class GaNoteAttachmentOut(BaseModel):
    id: uuid.UUID
    note_id: uuid.UUID
    original_filename: str
    stored_filename: str
    content_type: str | None = None
    size_bytes: int
    created_by: uuid.UUID | None = None
    created_at: datetime

from app.models.enums import GaNotePriority, GaNoteStatus, GaNoteType, TaskFinishPeriod, TaskPriority, TaskStatus

class GaNoteOut(BaseModel):
    id: uuid.UUID
    content: str
    created_by: uuid.UUID | None = None
    note_type: GaNoteType
    status: GaNoteStatus
    priority: GaNotePriority | None = None
    start_date: datetime
    due_date: datetime | None = None
    completed_at: datetime | None = None
    is_converted_to_task: bool
    is_discussed: bool = False
    one_h_marker: str | None = None
    one_h_marker_by_ga: bool = False
    one_h_marker_comment: str | None = None
    project_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    knowledge_type: str | None = None
    knowledge_tester_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    attachments: list[GaNoteAttachmentOut] = []
    from_mira: bool = False
    mira_shared_to_px: bool = False


class GaNotePublicOut(BaseModel):
    id: uuid.UUID
    content: str
    note_type: GaNoteType
    status: GaNoteStatus
    created_at: datetime


class GaNoteCreate(BaseModel):
    content: str
    created_by: uuid.UUID | None = None
    note_type: GaNoteType | None = None
    status: GaNoteStatus | None = None
    priority: GaNotePriority | None = None
    start_date: datetime | None = None
    due_date: datetime | None = None
    completed_at: datetime | None = None
    is_converted_to_task: bool | None = None
    is_discussed: bool | None = None
    one_h_marker: str | None = Field(default=None, pattern=r"^(EXCLAMATION|QUESTION|KA|GENT|FLAG|F|BZ1N1|M2|M3|M2_M3|MONITOR|CLOSE|CLIENT_URGENT|SHARE)$")
    one_h_marker_comment: str | None = Field(default=None, max_length=1000)
    project_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None


class GaNoteUpdate(BaseModel):
    content: str | None = None
    status: GaNoteStatus | None = None
    priority: GaNotePriority | None = None
    is_converted_to_task: bool | None = None
    is_discussed: bool | None = None
    one_h_marker: str | None = Field(default=None, pattern=r"^(EXCLAMATION|QUESTION|KA|GENT|FLAG|F|BZ1N1|M2|M3|M2_M3|MONITOR|CLOSE|CLIENT_URGENT|SHARE)$")
    one_h_marker_comment: str | None = Field(default=None, max_length=1000)


class GaNoteTaskDeadlineUpdate(BaseModel):
    start_date: datetime | None = None
    due_date: datetime | None = None
    is_deadline_important: bool | None = None
    clear_start: bool = False
    clear: bool = False


class GaNoteTaskAssigneeStateUpdate(BaseModel):
    """Execution state owned by one independent GA-task assignee copy."""

    assignee_id: uuid.UUID
    status: TaskStatus
    confirmation_assignee_id: uuid.UUID | None = None
    start_date: datetime | None = None
    due_date: datetime | None = None
    finish_period: TaskFinishPeriod | None = None
    one_h_report_slot: str | None = Field(default=None, pattern=r"^(10:00|11:00|11:50|14:20|16:00)$")
    one_h_marker: str | None = Field(default=None, pattern=r"^(EXCLAMATION|QUESTION|KA|GENT|FLAG|F|BZ1N1|M2|M3|M2_M3|MONITOR|CLOSE|CLIENT_URGENT|SHARE)$")
    one_h_marker_comment: str | None = Field(default=None, max_length=1000)
    is_deadline_important: bool = False
    priority: TaskPriority = TaskPriority.NORMAL
    is_bllok: bool = False
    is_1h_report: bool = False
    is_r1: bool = False
    is_personal: bool = False


class GaNoteTaskBundleUpdate(TaskPostponementExplanations):
    """Atomic update for a GA note and its independent assignee copies."""

    content: str | None = None
    description: str | None = None
    is_repetitive: bool | None = None
    project_id: uuid.UUID | None = None
    one_h_marker: str | None = Field(default=None, pattern=r"^(EXCLAMATION|QUESTION|KA|GENT|FLAG|F|BZ1N1|M2|M3|M2_M3|MONITOR|CLOSE|CLIENT_URGENT|SHARE)$")
    one_h_marker_comment: str | None = Field(default=None, max_length=1000)
    assignee_ids: list[uuid.UUID] | None = None
    assignee_states: list[GaNoteTaskAssigneeStateUpdate] | None = None
    expected_updated_at: datetime | None = None


class GaNoteTaskBundleResponse(BaseModel):
    note: GaNoteOut
    active_task_ids: list[uuid.UUID]
    assignee_ids: list[uuid.UUID]
    created_count: int = 0
    deactivated_count: int = 0
    deduplicated_count: int = 0
    updated_count: int = 0
