from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from app.schemas.task_postponement import TaskPostponementExplanations

from app.models.enums import (
    GaNotePriority,
    GaNoteStatus,
    GaNoteType,
    TaskFinishPeriod,
    TaskPriority,
    TaskStatus,
)


class PlanNoteAttachmentOut(BaseModel):
    id: uuid.UUID
    note_id: uuid.UUID
    original_filename: str
    stored_filename: str
    content_type: str | None = None
    size_bytes: int
    created_by: uuid.UUID | None = None
    created_at: datetime


class PxJavPlanningBrief(BaseModel):
    dl: str | None = Field(default=None, max_length=4000)
    lloji_det: Literal["1H", "P", "BLLOK", "R1"] | None = None
    dg: bool | None = None
    dg_kush: str | None = Field(default=None, max_length=4000)
    dg_kush_user_ids: list[uuid.UUID] = Field(default_factory=list)
    hapat: str | None = Field(default=None, max_length=10000)
    kush: str | None = Field(default=None, max_length=4000)
    kush_user_ids: list[uuid.UUID] = Field(default_factory=list)
    sq: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def normalize_conditional_fields(self):
        for field_name in ("dl", "dg_kush", "hapat", "kush", "sq"):
            value = getattr(self, field_name)
            setattr(self, field_name, value.strip() if value and value.strip() else None)
        if self.dg is not True:
            self.dg_kush = None
            self.dg_kush_user_ids = []
        self.dg_kush_user_ids = list(dict.fromkeys(self.dg_kush_user_ids))
        self.kush_user_ids = list(dict.fromkeys(self.kush_user_ids))
        return self


class PlanNoteOut(BaseModel):
    id: uuid.UUID
    content: str
    comment: str | None = None
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
    next_week: bool = False
    project_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    planned_for_date: date | None = None
    planning_brief: PxJavPlanningBrief | None = None
    created_at: datetime
    updated_at: datetime
    attachments: list[PlanNoteAttachmentOut] = []
    attachment_count: int = 0


class PlanNoteCreate(BaseModel):
    content: str
    comment: str | None = None
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
    next_week: bool | None = None
    project_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    planned_for_date: date | None = None
    planning_brief: PxJavPlanningBrief | None = None


class PlanNoteUpdate(BaseModel):
    content: str | None = None
    comment: str | None = None
    status: GaNoteStatus | None = None
    priority: GaNotePriority | None = None
    is_converted_to_task: bool | None = None
    is_discussed: bool | None = None
    one_h_marker: str | None = Field(default=None, pattern=r"^(EXCLAMATION|QUESTION|KA|GENT|FLAG|F|BZ1N1|M2|M3|M2_M3|MONITOR|CLOSE|CLIENT_URGENT|SHARE)$")
    one_h_marker_comment: str | None = Field(default=None, max_length=1000)
    next_week: bool | None = None
    planned_for_date: date | None = None
    planning_brief: PxJavPlanningBrief | None = None


class PlanNoteTaskDeadlineUpdate(TaskPostponementExplanations):
    due_date: datetime | None = None
    is_deadline_important: bool | None = None
    clear: bool = False


class PlanNoteTaskAssigneeStateUpdate(BaseModel):
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


class PlanNoteTaskBundleUpdate(TaskPostponementExplanations):
    content: str | None = None
    description: str | None = None
    is_repetitive: bool | None = None
    project_id: uuid.UUID | None = None
    one_h_marker: str | None = Field(default=None, pattern=r"^(EXCLAMATION|QUESTION|KA|GENT|FLAG|F|BZ1N1|M2|M3|M2_M3|MONITOR|CLOSE|CLIENT_URGENT|SHARE)$")
    one_h_marker_comment: str | None = Field(default=None, max_length=1000)
    assignee_ids: list[uuid.UUID] | None = None
    assignee_states: list[PlanNoteTaskAssigneeStateUpdate] | None = None
    expected_updated_at: datetime | None = None


class PlanNoteTaskBundleResponse(BaseModel):
    note: PlanNoteOut
    active_task_ids: list[uuid.UUID]
    assignee_ids: list[uuid.UUID]
    created_count: int = 0
    deactivated_count: int = 0
    deduplicated_count: int = 0
    updated_count: int = 0
