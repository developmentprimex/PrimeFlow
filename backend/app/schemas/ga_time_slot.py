import uuid
import re
from datetime import date, datetime, time
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator


class GaTimeSlotFormatting(BaseModel):
    background_color: str = "#FFFFFF"
    text_color: str = "#0F172A"
    is_bold: bool = False
    is_italic: bool = False

    @field_validator("background_color", "text_color")
    @classmethod
    def validate_hex_color(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"#[0-9A-F]{6}", normalized):
            raise ValueError("Color must use #RRGGBB format")
        return normalized


class GaTimeSlotEntryIn(GaTimeSlotFormatting):
    day_of_week: int
    start_time: time
    end_time: time
    content: str = Field(max_length=8000)
    user_id: uuid.UUID | None = None
    sort_order: int = Field(default=0, ge=0)


class GaTimeSlotEntryUpdate(BaseModel):
    content: str = Field(max_length=8000)
    background_color: str | None = None
    text_color: str | None = None
    is_bold: bool | None = None
    is_italic: bool | None = None

    @field_validator("background_color", "text_color")
    @classmethod
    def validate_optional_hex_color(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not re.fullmatch(r"#[0-9A-F]{6}", normalized):
            raise ValueError("Color must use #RRGGBB format")
        return normalized


class GaTimeSlotEntryOut(GaTimeSlotFormatting):
    id: uuid.UUID
    user_id: uuid.UUID
    day_of_week: int
    start_time: time
    end_time: time
    content: str
    sort_order: int
    created_at: datetime
    updated_at: datetime
    occurrence_date: date | None = None
    source_type: Literal["calendar", "reminder"] | None = None
    source_name: str | None = None
    is_completed: bool = False


class GaTimeSlotEntryPosition(BaseModel):
    id: uuid.UUID
    day_of_week: int = Field(ge=0, le=6)
    start_time: time
    end_time: time
    sort_order: int = Field(ge=0)


class GaTimeSlotEntriesReorder(BaseModel):
    entries: list[GaTimeSlotEntryPosition] = Field(min_length=1, max_length=500)


class GaTimeTableRowCommentFormatting(BaseModel):
    comment_background_color: str = "#FFFFFF"
    comment_text_color: str = "#0F172A"
    comment_is_bold: bool = False
    comment_is_italic: bool = False

    @field_validator("comment_background_color", "comment_text_color")
    @classmethod
    def validate_comment_hex_color(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not re.fullmatch(r"#[0-9A-F]{6}", normalized):
            raise ValueError("Color must use #RRGGBB format")
        return normalized


class GaTimeTableRowIn(GaTimeTableRowCommentFormatting):
    start_time: time
    end_time: time
    comment: str = Field(default="", max_length=2000)


class GaTimeTableRowCommentUpdate(GaTimeTableRowCommentFormatting):
    start_time: time
    end_time: time
    comment: str = Field(default="", max_length=2000)


class GaTimeTableRowComment(GaTimeTableRowCommentFormatting):
    id: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=2000)
    column: Literal["start", "end"] = "start"


class GaTimeTableRowCommentsUpdate(BaseModel):
    start_time: time
    end_time: time
    column: Literal["start", "end"] = "start"
    comments: list[GaTimeTableRowComment] = Field(default_factory=list, max_length=50)


class GaTimeTableRowCommentMove(BaseModel):
    comment_id: str = Field(min_length=1, max_length=100)
    source_start_time: time
    source_end_time: time
    source_column: Literal["start", "end"] = "start"
    target_start_time: time
    target_end_time: time
    target_column: Literal["start", "end"] = "start"
    before_comment_id: str | None = Field(default=None, min_length=1, max_length=100)


class GaTimeTableCommentToSlotMove(BaseModel):
    comment_id: str = Field(min_length=1, max_length=100)
    source_start_time: time
    source_end_time: time
    source_column: Literal["start", "end"] = "start"
    target_day_of_week: int = Field(ge=0, le=6)
    target_start_time: time
    target_end_time: time
    before_entry_id: uuid.UUID | None = None


class GaTimeTableEntryToCommentMove(BaseModel):
    entry_id: uuid.UUID
    target_start_time: time
    target_end_time: time
    target_column: Literal["start", "end"] = "start"
    before_comment_id: str | None = Field(default=None, min_length=1, max_length=100)


class GaTimeTableRowsUpdate(BaseModel):
    rows: list[GaTimeTableRowIn]


class GaTimeTableRowOut(GaTimeTableRowCommentFormatting):
    id: uuid.UUID | None = None
    sort_order: int
    nr_label: str
    label: str
    start_time: time
    end_time: time
    is_special: bool = False
    comment: str = ""
    comments: list[GaTimeTableRowComment] = Field(default_factory=list)
    end_comments: list[GaTimeTableRowComment] = Field(default_factory=list)


class GaTimeTableCrossCellMoveOut(BaseModel):
    rows: list[GaTimeTableRowOut] = Field(default_factory=list)
    entries: list[GaTimeSlotEntryOut] = Field(default_factory=list)


class GaIcloudSyncConnectionCreate(BaseModel):
    device_name: str = Field(default="iPhone GA", min_length=1, max_length=120)
    calendar_name: str = Field(default="ganimete.ar@gmail.com", min_length=1, max_length=320)
    reminder_list_name: str = Field(default="REMINDER", min_length=1, max_length=320)


class GaIcloudSyncConnectionOut(BaseModel):
    id: uuid.UUID
    device_name: str
    calendar_name: str
    reminder_list_name: str
    last_synced_at: datetime | None = None
    last_imported_count: int = 0
    created_at: datetime


class GaIcloudSyncPairingOut(GaIcloudSyncConnectionOut):
    import_url: str
    pairing_token: str


class GaIcloudCalendarItem(BaseModel):
    id: str | None = Field(default=None, max_length=512)
    title: str = Field(min_length=1, max_length=2000)
    starts_at: datetime
    ends_at: datetime | None = None
    is_all_day: bool = False
    calendar_name: str | None = Field(default=None, max_length=320)
    location: str | None = Field(default=None, max_length=1000)


class GaIcloudReminderItem(BaseModel):
    id: str | None = Field(default=None, max_length=512)
    title: str = Field(min_length=1, max_length=2000)
    due_at: datetime | None = None
    due_date: date | None = None
    is_completed: bool = False
    reminder_list_name: str | None = Field(default=None, max_length=320)
    notes: str | None = Field(default=None, max_length=2000)
    _original_due_at: str | None = PrivateAttr(default=None)

    @model_validator(mode="wrap")
    @classmethod
    def preserve_due_at(cls, data, handler):
        item = handler(data)
        if isinstance(data, dict) and isinstance(data.get("due_at"), str):
            item._original_due_at = data["due_at"]
        return item

    @property
    def original_due_at(self) -> str | None:
        return self._original_due_at


class GaIcloudSyncImport(BaseModel):
    sync_window_start: date
    sync_window_end: date
    timezone: str = Field(default="Europe/Berlin", min_length=1, max_length=80)
    calendar_name: str = Field(min_length=1, max_length=320)
    reminder_list_name: str = Field(min_length=1, max_length=320)
    events: list[GaIcloudCalendarItem] = Field(default_factory=list, max_length=500)
    reminders: list[GaIcloudReminderItem] = Field(default_factory=list, max_length=500)


class GaIcloudSyncImportOut(BaseModel):
    imported: int
    calendar_imported: int
    reminders_imported: int
    skipped: int
    synced_at: datetime


class GaIcloudReminderCompletion(BaseModel):
    id: str
    title: str
    due_at: str | None


class GaIcloudReminderCompletionAck(BaseModel):
    ids: list[Annotated[str, Field(pattern=r"^tt:[0-9a-f]{64}$")]] = Field(max_length=500)
