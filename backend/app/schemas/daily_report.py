from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.task import TaskOut
from app.models.enums import GaNotePriority, GaNoteStatus, GaNoteType


class DailyRlzTaskStateOut(BaseModel):
    reason_code: str | None = None
    reason_label: str | None = None
    comment: str | None = None
    updated_at: datetime | None = None
    is_editable: bool
    editable_until: datetime | None = None
    requires_explanation: bool = False
    reason_required: bool = False
    comment_required: bool = False
    reason_missing: bool = False
    comment_missing: bool = False
    deadline_was_today: bool = False
    deadline_is_overdue: bool = False
    postponed_today: bool = False


class DailyRlzCloseStateOut(BaseModel):
    status: str
    saved: bool = False
    stale: bool = False
    saved_at: datetime | None = None
    is_editable: bool = False
    closable_from: datetime | None = None
    editable_until: datetime | None = None


class DailyRlzStateUpsert(BaseModel):
    day: date
    user_id: uuid.UUID | None = None
    reason_code: str | None = None
    comment: str | None = Field(default=None, max_length=10000)

    @field_validator("reason_code")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        from app.services.daily_rlz_compliance import REASON_LABELS
        if value is not None and value not in REASON_LABELS:
            raise ValueError("Invalid Daily RLZ reason code")
        return value


class DailyRlzStateCorrection(DailyRlzStateUpsert):
    user_id: uuid.UUID
    correction_reason: str = Field(min_length=3, max_length=2000)


class DailyReportTaskItem(BaseModel):
    task: TaskOut
    project_title: str | None = None
    planned_start: date | None = None
    planned_end: date | None = None
    original_planned_end: date | None = None
    is_overdue: bool
    late_days: int | None = None
    rlz_daily_state: DailyRlzTaskStateOut | None = None


class DailyReportSystemOccurrence(BaseModel):
    task: TaskOut
    template_id: uuid.UUID
    title: str
    frequency: str | None = None
    department_id: uuid.UUID | None = None
    scope: str | None = None
    occurrence_date: date
    status: str
    comment: str | None = None
    acted_at: datetime | None = None
    is_overdue: bool
    late_days: int | None = None
    rlz_daily_state: DailyRlzTaskStateOut | None = None


class DailyReportResponse(BaseModel):
    day: date
    tasks_today: list[DailyReportTaskItem]
    tasks_overdue: list[DailyReportTaskItem]
    system_today: list[DailyReportSystemOccurrence]
    system_overdue: list[DailyReportSystemOccurrence]
    rlz_close_state: DailyRlzCloseStateOut | None = None


class DailyReportGaEntryOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    department_id: uuid.UUID
    entry_date: date
    content: str
    created_at: datetime
    updated_at: datetime


class DailyReportGaEntryUpsert(BaseModel):
    day: date
    department_id: uuid.UUID
    content: str
    user_id: uuid.UUID | None = None


class DailyReportGaNoteOut(BaseModel):
    id: uuid.UUID
    content: str
    note_type: GaNoteType
    status: GaNoteStatus
    priority: GaNotePriority | None = None
    created_at: datetime
    project_id: uuid.UUID | None = None
    project_name: str | None = None


class DailyReportGaTableResponse(BaseModel):
    entry: DailyReportGaEntryOut | None = None
    notes: list[DailyReportGaNoteOut]

