from __future__ import annotations

import uuid
from datetime import date, time
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr, model_validator

Person = Literal["mrika", "lirza", "rrita", "gane"]
Group = Literal["morning", "daily_upkeep", "nala", "weekend_deep_clean"]
Status = Literal["pending", "acknowledged", "in_progress", "needs_help", "rescheduled", "done", "cancelled"]


class UnlockRequest(BaseModel):
    password: SecretStr


class ScheduleHint(BaseModel):
    trigger_type: str = Field(max_length=40)
    start_time: time | None = None
    end_time: time | None = None
    notes: str = Field(default="", max_length=3000)


class TemplateDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    completion_definition: str = Field(default="Kryerja konfirmohet nga përgjegjësi.", max_length=3000)
    schedule_hints: list[ScheduleHint] = Field(default_factory=list, max_length=20)
    area_id: str = Field(default="home", max_length=100)
    assignment: Literal["fixed", "rotation", "first_home", "unassigned"] = "fixed"
    assignees: list[Person] = Field(default_factory=list, max_length=4)
    completion_mode: Literal["individual", "shared"] = "individual"
    frequency: Literal["once", "daily", "weekly", "school_day", "conditional", "near_daily", "unresolved"] = "once"
    on_date: date | None = None
    due_time: time | None = None
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    steps: list[str] = Field(default_factory=list, max_length=100)
    estimated_minutes: int | None = Field(default=None, ge=1, le=1440)
    reminder_group: Group = "daily_upkeep"
    enabled: bool = False
    readiness: Literal["ready_after_setup", "needs_confirmation"] = "ready_after_setup"
    rotation_id: Literal["nala"] | None = None
    # Explicitly configured coverage prevents morning/arrival and robot duplicates.
    coverage_key: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def valid(self):
        self.title = self.title.strip()
        if not self.title or len(set(self.assignees)) != len(self.assignees):
            raise ValueError("Titulli dhe përgjegjësit duhet të jenë të vlefshëm.")
        if any(d not in range(7) for d in self.weekdays) or len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError("Ditët duhet të jenë 0–6, pa përsëritje.")
        if any(not step.strip() or len(step) > 2000 for step in self.steps):
            raise ValueError("Hapat duhet të kenë tekst deri në 2000 karaktere.")
        if self.assignment == "fixed" and not self.assignees:
            raise ValueError("Zgjidh përgjegjësin.")
        if self.assignment != "fixed" and self.assignees:
            raise ValueError("Caktimi automatik nuk merr përgjegjës fiks.")
        if self.enabled and self.frequency == "once" and self.assignment != "fixed":
            raise ValueError("Detyra njëherëshe duhet të ketë përgjegjës të zgjedhur.")
        if (self.assignment == "rotation") != (self.rotation_id is not None):
            raise ValueError("Rotacioni duhet të jetë i përcaktuar.")
        if self.enabled:
            if self.readiness != "ready_after_setup" or self.frequency == "unresolved" or self.assignment == "unassigned":
                raise ValueError("Plotëso konfigurimin para aktivizimit.")
            if self.frequency == "once" and (self.on_date is None or self.due_time is None):
                raise ValueError("Cakto datën/orën para aktivizimit.")
            if self.frequency in {"weekly", "near_daily"} and not self.weekdays:
                raise ValueError("Zgjidh ditët.")
            if self.frequency == "weekly" and any(d not in (5, 6) for d in self.weekdays):
                raise ValueError("Pastrimi javor është brenda vikendit.")
        return self


class TemplateWrite(BaseModel):
    definition: TemplateDefinition
    expected_version: int | None = Field(default=None, ge=1)


class ActionRequest(BaseModel):
    status: Status
    expected_version: int = Field(ge=1)
    request_id: uuid.UUID
    reschedule_at: AwareDatetime | None = None
    comment: str = Field(default="", max_length=2000)


class GenerateRequest(BaseModel):
    day: date
    # No sensor inference: these are explicit confirmations by an authorized adult.
    school_day: bool = False
    conditions: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    first_home: Person | None = None


class ArchiveRequest(BaseModel):
    expected_version: int = Field(ge=1)
    archived: bool = True


class PasswordRequest(BaseModel):
    password: SecretStr


class ImportRequest(BaseModel):
    dataset: dict
    expected_hash: str | None = None


class AutomationRequest(BaseModel):
    enabled: bool


class OccurrenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    request_id: uuid.UUID
    local_date: date
    due_time: time | None = None
    assignees: list[Person] = Field(min_length=1, max_length=4)
    apply_to_future: bool = False
    expected_template_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def valid(self):
        if len(set(self.assignees)) != len(self.assignees):
            raise ValueError("Përgjegjësit nuk mund të përsëriten.")
        if self.due_time and self.due_time.tzinfo is not None:
            raise ValueError("Ora jepet sipas Europe/Belgrade.")
        if self.apply_to_future and self.expected_template_version is None:
            raise ValueError("Rifresko modelin para ndryshimit të përsëritjeve.")
        return self
