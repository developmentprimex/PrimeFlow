from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


class MeetingClientIdentification(BaseModel):
    client_id: uuid.UUID | None = None
    client_name: str | None = Field(default=None, max_length=200)

    @field_validator("client_name")
    @classmethod
    def normalize_client_name(cls, value: str | None) -> str | None:
        return " ".join((value or "").split()) or None


class MeetingClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        name = " ".join(value.split())
        if not name:
            raise ValueError("Shkruaj emrin e klientit.")
        return name


class MeetingClientOut(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class MeetingOut(BaseModel):
    id: uuid.UUID
    title: str
    client_name: str | None = None
    client_id: uuid.UUID | None = None
    platform: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    meeting_url: str | None = None
    microsoft_event_id: str | None = None
    calendar_imported: bool = False
    calendar_sync_status: str | None = None
    calendar_categories: list[str] = Field(default_factory=list)
    calendar_last_synced_at: datetime | None = None
    reminder_minutes_before: int | None = 15
    meeting_type: str
    recurrence_type: str | None = None
    recurrence_days_of_week: list[int] | None = None
    recurrence_days_of_month: list[int] | None = None
    external_agent_test_task_requested: bool = False
    external_pim_image_test_task_requested: bool = False
    is_training: bool = False
    department_id: uuid.UUID
    project_id: uuid.UUID | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    participant_ids: list[uuid.UUID] = Field(default_factory=list)
    paired_external_meeting_id: uuid.UUID | None = None
    pre_external_meeting_id: uuid.UUID | None = None


class MeetingCreateOut(MeetingOut):
    paired_internal_meeting: MeetingOut | None = None


class MeetingCreate(MeetingClientIdentification):
    title: str = Field(min_length=2, max_length=200)
    platform: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    meeting_url: str | None = None
    meeting_type: str | None = None
    recurrence_type: str | None = None
    recurrence_days_of_week: list[int] | None = None
    recurrence_days_of_month: list[int] | None = None
    department_id: uuid.UUID
    project_id: uuid.UUID | None = None
    participant_ids: list[uuid.UUID] = Field(default_factory=list)
    create_internal_meeting: bool | None = None
    internal_starts_at: datetime | None = None
    paired_external_meeting_id: uuid.UUID | None = None
    allow_one_h_conflict: bool = False


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=200)
    platform: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    meeting_url: str | None = None
    meeting_type: str | None = None
    recurrence_type: str | None = None
    recurrence_days_of_week: list[int] | None = None
    recurrence_days_of_month: list[int] | None = None
    project_id: uuid.UUID | None = None
    participant_ids: list[uuid.UUID] | None = None


class MeetingReminderSettingsUpdate(BaseModel):
    participant_ids: list[uuid.UUID] = Field(default_factory=list)
    reminder_minutes_before: int | None = Field(default=15, ge=0, le=1440)


class MeetingOccurrenceStatusOut(BaseModel):
    id: uuid.UUID
    meeting_id: uuid.UUID
    occurrence_date: date
    status: str
    note: str | None = None
    checked_by_user_id: uuid.UUID | None = None
    checked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MeetingOccurrenceStatusUpdate(BaseModel):
    occurrence_date: date
    status: str = Field(pattern="^(|held|canceled)$")
    note: str | None = None
