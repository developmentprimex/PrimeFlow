from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RecordingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    meeting_id: UUID | None = None
    project_id: UUID | None = None
    capture_source_type: Literal["monitor", "window", "browser", "unknown", "microphone"]
    mime_type: Literal["video/webm", "video/mp4", "audio/webm", "audio/mp4"]
    has_microphone_audio: bool = False
    has_system_audio: bool = False
    consent_acknowledged: Literal[True]

    @model_validator(mode="after")
    def validate_capture_source(self):
        audio_only = self.mime_type.startswith("audio/")
        if audio_only != (self.capture_source_type == "microphone"):
            raise ValueError("Recording format does not match the capture source")
        if audio_only and (not self.has_microphone_audio or self.has_system_audio):
            raise ValueError("Audio-only recordings require microphone audio")
        return self

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Title is required")
        return value.strip()


class RecordingUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    project_id: UUID | None = None
    # Takimet: link an existing recording to its meeting (sent only when changed).
    meeting_id: UUID | None = None

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
    project_id: UUID | None = None
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
    project_title: str | None = None
    media_available: bool | None = None
