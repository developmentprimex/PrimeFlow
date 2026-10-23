from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RecordingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    meeting_id: UUID | None = None
    capture_source_type: Literal["monitor", "window", "browser", "unknown"]
    mime_type: Literal["video/webm", "video/mp4"]
    has_microphone_audio: bool = False
    has_system_audio: bool = False
    consent_acknowledged: Literal[True]

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Title is required")
        return value.strip()


class RecordingComplete(BaseModel):
    chunks: int = Field(ge=1, le=100000)
    partial: bool = False


class RecordingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    meeting_id: UUID | None
    created_by: UUID
    title: str
    description: str | None
    capture_source_type: str
    status: str
    recording_started_at: datetime
    recording_stopped_at: datetime | None
    duration_seconds: float | None
    mime_type: str
    video_width: int | None
    video_height: int | None
    has_microphone_audio: bool
    has_system_audio: bool
    is_partial: bool
    size_bytes: int
    chunks_received: int
    upload_completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    error_message: str | None
    recorded_by_name: str | None = None
    meeting_title: str | None = None
    media_available: bool | None = None
