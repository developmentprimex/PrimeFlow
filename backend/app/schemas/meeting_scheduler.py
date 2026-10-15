from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, model_validator


class MeetingSchedulingStandardBase(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    meeting_type: str = Field(pattern="^(internal|external)$")
    default_duration_minutes: int = Field(default=60, ge=5, le=480)
    buffer_minutes: int = Field(default=0, ge=0, le=180)
    workday_start: str = Field(default="08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    workday_end: str = Field(default="17:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    is_active: bool = True


class MeetingSchedulingStandardCreate(MeetingSchedulingStandardBase):
    pass


class MeetingSchedulingStandardOut(MeetingSchedulingStandardBase):
    id: uuid.UUID
    created_by_user_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MeetingScheduleRequestBase(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    meeting_type: str = Field(pattern="^(internal|external)$")
    starts_at: datetime
    ends_at: datetime
    platform: str | None = Field(default=None, max_length=100)
    client_name: str | None = Field(default=None, max_length=200)
    client_email: EmailStr | None = None
    notes: str | None = None
    department_id: uuid.UUID
    project_id: uuid.UUID | None = None
    standard_id: uuid.UUID | None = None
    participant_ids: list[uuid.UUID] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_window(self):
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("Meeting start and end must include a timezone")
        if self.ends_at <= self.starts_at:
            raise ValueError("Meeting end time must be after its start time")
        return self


class MeetingScheduleValidationIn(MeetingScheduleRequestBase):
    exclude_request_id: uuid.UUID | None = None
    check_all_meetings: bool = False


class MeetingScheduleConflict(BaseModel):
    source: str
    title: str
    starts_at: datetime
    ends_at: datetime
    participant_ids: list[uuid.UUID] = []


class MeetingScheduleSuggestion(BaseModel):
    starts_at: datetime
    ends_at: datetime


class MeetingScheduleValidationOut(BaseModel):
    can_create: bool
    errors: list[str] = []
    warnings: list[str] = []
    conflicts: list[MeetingScheduleConflict] = []
    suggested_slot: MeetingScheduleSuggestion | None = None
    checked_at: datetime


class MeetingScheduleRequestCreate(MeetingScheduleRequestBase):
    pass


class MeetingScheduleApprovalOut(BaseModel):
    user_id: uuid.UUID
    user_name: str
    approved_at: datetime


class MeetingScheduleRequestOut(MeetingScheduleRequestBase):
    id: uuid.UUID
    status: str
    approval_count: int
    approvals: list[MeetingScheduleApprovalOut] = []
    validation: MeetingScheduleValidationOut | None = None
    microsoft_event_id: str | None = None
    teams_url: str | None = None
    final_meeting_id: uuid.UUID | None = None
    last_error: str | None = None
    rejection_reason: str | None = None
    rejected_by_user_id: uuid.UUID | None = None
    rejected_at: datetime | None = None
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class MeetingScheduleCalendarItem(BaseModel):
    id: str
    source: str
    title: str
    meeting_type: str
    starts_at: datetime
    ends_at: datetime
    status: str
    participant_ids: list[uuid.UUID] = []
    teams_url: str | None = None
    microsoft_event_id: str | None = None
    calendar_categories: list[str] = Field(default_factory=list)


class MeetingScheduleRejectIn(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)
