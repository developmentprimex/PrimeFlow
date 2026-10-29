import uuid
from datetime import date as Date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.ga_personal import Person


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CardRepeat(StrictModel):
    every: int = Field(ge=1, le=365)
    unit: Literal["day", "week", "month"]
    days: list[int] | None = Field(default=None, max_length=7)
    until: Date | None = None

    @field_validator("days")
    @classmethod
    def valid_days(cls, value):
        if value is not None and (any(day not in range(7) for day in value) or len(set(value)) != len(value)):
            raise ValueError("Ditët duhet të jenë 0–6, pa përsëritje.")
        return value


class DeviceCard(StrictModel):
    id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    person_id: Person | None = None
    start: str | None = Field(default=None, pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    end: str | None = Field(default=None, pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    steps: list[str] = Field(default_factory=list, max_length=100)
    kind: Literal["task", "nala", "roki", "activity", "appointment", "event"] = "task"
    area: Literal["room", "bathroom", "kitchen", "school", "home", "nala", "roki", "activity", "appointment", "event"] = "home"
    group: str | None = Field(default=None, max_length=200)
    speech: str = Field(default="", max_length=500)
    days: list[int] | None = Field(default=None, max_length=7)
    weekend: bool = False
    date: Date | None = None
    alarm: bool = True
    lead: int = Field(default=0, ge=0, le=1440)
    note: str | None = Field(default=None, max_length=10000)
    repeat: CardRepeat | None = None

    _days = field_validator("days")(CardRepeat.valid_days.__func__)

    @field_validator("id", "title")
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("ID dhe titulli janë të detyrueshëm.")
        return value

    @field_validator("steps")
    @classmethod
    def bounded_steps(cls, value):
        if any(not step.strip() or len(step) > 2000 for step in value):
            raise ValueError("Hapat duhet të kenë tekst deri në 2000 karaktere.")
        return value

    @model_validator(mode="after")
    def untimed_has_no_alarm(self):
        if self.start is None:
            self.alarm = False
        return self


class DeviceOp(StrictModel):
    op_id: uuid.UUID
    at: int = Field(strict=True, ge=0, le=253402300799999)


class StatusOp(DeviceOp):
    type: Literal["status"]
    task_id: str = Field(min_length=1, max_length=200)
    period: Date
    status: Literal["in_progress", "needs_help", "done"]
    step: int = Field(default=0, ge=0, le=10000)


class EventUpsertOp(DeviceOp):
    type: Literal["event_upsert"]
    event: DeviceCard


class EventDeleteOp(DeviceOp):
    type: Literal["event_delete"]
    id: str = Field(min_length=1, max_length=200)


class ArrivalOp(DeviceOp):
    type: Literal["arrival"]
    person_id: Person
    day: Date


Operation = Annotated[StatusOp | EventUpsertOp | EventDeleteOp | ArrivalOp, Field(discriminator="type")]


class DeviceOpsRequest(StrictModel):
    device_id: uuid.UUID
    ops: list[Operation] = Field(max_length=200)


class DeviceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Vendos emrin e pajisjes.")
        return value
