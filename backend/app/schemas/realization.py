from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    RealizationDailyCloseAction,
    RealizationLevel,
    RealizationMarker,
    RealizationObservationCategory,
    RealizationObservationVisibility,
    RealizationPeriodSlot,
    RealizationPeriodStatus,
    RealizationPeriodType,
    RealizationOperatingMode,
    RealizationPulse,
    RealizationScopeType,
    RealizationSymbol,
)


class RealizationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RealizationPolicyVersionCreate(RealizationSchema):
    name: str = Field(min_length=1, max_length=120)
    version: int = Field(gt=0)
    effective_from: date
    effective_to: date | None = None
    criteria_json: dict
    bonus_json: dict = Field(default_factory=dict, exclude=True)
    am_cutoff: time
    pm_cutoff: time

    @model_validator(mode="after")
    def validate_policy(self) -> "RealizationPolicyVersionCreate":
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from")
        if self.am_cutoff >= self.pm_cutoff:
            raise ValueError("am_cutoff must be before pm_cutoff")
        return self


class RealizationPolicyVersionOut(RealizationPolicyVersionCreate):
    id: uuid.UUID
    created_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    created_at: datetime
    approved_at: datetime | None


class RealizationPeriodCreate(RealizationSchema):
    period_type: RealizationPeriodType
    slot: RealizationPeriodSlot
    start_date: date
    end_date: date
    department_id: uuid.UUID | None = None
    policy_version_id: uuid.UUID
    planned_snapshot_id: uuid.UUID | None = None
    final_snapshot_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def validate_period_shape(self) -> "RealizationPeriodCreate":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.period_type is RealizationPeriodType.DAILY:
            if self.slot not in {
                RealizationPeriodSlot.AM,
                RealizationPeriodSlot.PM,
                RealizationPeriodSlot.ALL,
            }:
                raise ValueError("daily periods require an AM, PM, or ALL slot")
            if self.start_date != self.end_date:
                raise ValueError("daily periods must cover one date")
        elif self.slot is not RealizationPeriodSlot.ALL:
            raise ValueError("weekly and monthly periods require the ALL slot")
        return self


class RealizationPeriodOut(RealizationPeriodCreate):
    id: uuid.UUID
    status: RealizationPeriodStatus
    calculated_at: datetime | None
    approved_at: datetime | None
    locked_at: datetime | None
    created_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    created_at: datetime


class RealizationObservationCreate(RealizationSchema):
    period_id: uuid.UUID | None = None
    scope_type: RealizationScopeType
    task_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    marker: RealizationMarker
    category: RealizationObservationCategory
    impact_minutes: int | None = Field(default=None, ge=0)
    repeat_key: str | None = Field(default=None, max_length=200)
    comment: str | None = Field(default=None, max_length=4000)
    evidence_json: dict = Field(default_factory=dict)
    source_type: str | None = Field(default=None, max_length=80)
    source_id: uuid.UUID | None = None
    visibility: RealizationObservationVisibility = (
        RealizationObservationVisibility.PERSON_AND_MANAGER
    )

    @model_validator(mode="after")
    def validate_evidence(self) -> "RealizationObservationCreate":
        scope_reference = {
            RealizationScopeType.TASK: self.task_id,
            RealizationScopeType.SYSTEM_TASK: self.task_id,
            RealizationScopeType.PERSON: self.user_id,
            RealizationScopeType.PROJECT: self.project_id,
            RealizationScopeType.DEPARTMENT: self.department_id,
        }[self.scope_type]
        if scope_reference is None:
            raise ValueError(f"{self.scope_type.value} scope requires its matching reference")

        has_comment = bool(self.comment and self.comment.strip())
        if self.marker in {RealizationMarker.NEGATIVE, RealizationMarker.DIAMOND} and not has_comment:
            raise ValueError(f"{self.marker.value} observations require a comment")
        if self.category is RealizationObservationCategory.TIME_SAVED:
            if not self.impact_minutes or not has_comment:
                raise ValueError("TIME_SAVED requires positive impact_minutes and a comment")
        if self.category is RealizationObservationCategory.REPEATED_PROBLEM:
            if not (self.repeat_key and self.repeat_key.strip()) or not has_comment:
                raise ValueError("REPEATED_PROBLEM requires repeat_key and a comment")
        if self.evidence_json.get("high_impact") is True and not has_comment:
            raise ValueError("high-impact evidence requires a comment")
        if self.category is RealizationObservationCategory.HELPED_COLLEAGUE:
            if not self.evidence_json.get("helped_user_id"):
                raise ValueError("HELPED_COLLEAGUE requires evidence_json.helped_user_id")
            if self.marker is not RealizationMarker.POSITIVE:
                raise ValueError("HELPED_COLLEAGUE must be a POSITIVE observation")
        if self.category is RealizationObservationCategory.BLOCKER:
            impact = self.evidence_json.get("impact_level")
            if not self.evidence_json.get("affected_user_id") or impact not in {
                "MINOR",
                "MAJOR",
                "MULTIPLE_PEOPLE",
            }:
                raise ValueError(
                    "BLOCKER requires affected_user_id and a valid impact_level"
                )
            if self.marker is not RealizationMarker.NEGATIVE:
                raise ValueError("BLOCKER must be a NEGATIVE observation")
        if self.category is RealizationObservationCategory.ABSENCE:
            if self.user_id is None:
                raise ValueError("ABSENCE requires user_id attribution")
            if self.evidence_json.get("classification") not in {
                "UNEXCUSED",
                "APPROVED_PERSONAL",
                "ANNUAL_LEAVE",
            }:
                raise ValueError("ABSENCE requires a supported classification")
            if not self.evidence_json.get("date"):
                raise ValueError("ABSENCE requires evidence_json.date")
        if self.category is RealizationObservationCategory.MISSED_MEETING:
            if self.marker is not RealizationMarker.NEGATIVE:
                raise ValueError("MISSED_MEETING must be a NEGATIVE observation")
            if not self.evidence_json.get("meeting_id") or not self.evidence_json.get(
                "occurrence_date"
            ):
                raise ValueError(
                    "MISSED_MEETING requires meeting_id and occurrence_date evidence"
                )
        if self.category is RealizationObservationCategory.EXTRA_TASK:
            kind = self.evidence_json.get("kind")
            if kind not in {"REQUESTED_EXTRA_TASK", "COMPLETED_EXTRA_TASK"}:
                raise ValueError("EXTRA_TASK requires a supported evidence_json.kind")
            if self.marker is not RealizationMarker.POSITIVE:
                raise ValueError("EXTRA_TASK must be a POSITIVE observation")
            if kind == "COMPLETED_EXTRA_TASK":
                if self.scope_type not in {
                    RealizationScopeType.TASK,
                    RealizationScopeType.SYSTEM_TASK,
                } or self.task_id is None:
                    raise ValueError("COMPLETED_EXTRA_TASK requires task scope evidence")
                for key in ("replaces_unfinished_planned_task", "duplicate"):
                    if not isinstance(self.evidence_json.get(key), bool):
                        raise ValueError(
                            f"COMPLETED_EXTRA_TASK requires boolean evidence_json.{key}"
                        )
        if self.category in {
            RealizationObservationCategory.PROPOSAL,
            RealizationObservationCategory.TIME_SAVED,
        } and self.marker is not RealizationMarker.POSITIVE:
            raise ValueError(f"{self.category.value} must be a POSITIVE observation")
        if (
            self.category is RealizationObservationCategory.REPEATED_PROBLEM
            and self.marker is not RealizationMarker.NEGATIVE
        ):
            raise ValueError("REPEATED_PROBLEM must be a NEGATIVE observation")
        return self


class RealizationObservationOut(RealizationObservationCreate):
    id: uuid.UUID
    repeat_count_at_creation: int
    is_system_generated: bool
    created_by: uuid.UUID | None
    created_at: datetime
    voided_at: datetime | None
    voided_by: uuid.UUID | None
    void_reason: str | None


class RealizationObservationVoid(RealizationSchema):
    reason: str = Field(min_length=1, max_length=4000)


class RealizationDailyPersonCommentUpsert(RealizationSchema):
    comment: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def normalize_comment(self) -> "RealizationDailyPersonCommentUpsert":
        self.comment = (self.comment or "").strip() or None
        return self


class RealizationDailyPersonCommentOut(RealizationSchema):
    period_id: uuid.UUID
    user_id: uuid.UUID
    day: date
    comment: str | None
    can_edit: bool
    updated_by: uuid.UUID | None = None
    updated_at: datetime | None = None


class RealizationManagerReviewUpsert(RealizationSchema):
    level: Literal["A+", "A", "B", "C", "M", "D", "E"] | None = None
    rating: Literal["GOOD", "VERY_GOOD", "ACTION_REQUIRED", "BAD"] | None = None
    marker: Literal["POSITIVE", "NEGATIVE"]
    comment: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_comment(self) -> "RealizationManagerReviewUpsert":
        self.comment = self.comment.strip() if self.comment else None
        return self


class RealizationManagerReviewItem(RealizationSchema):
    level: Literal["A+", "A", "B", "C", "M", "D", "E"] | None = None
    rating: Literal["GOOD", "VERY_GOOD", "ACTION_REQUIRED", "BAD"] | None = None
    id: uuid.UUID
    dimension: Literal["PLANNING", "REALIZATION"]
    marker: Literal["POSITIVE", "NEGATIVE"]
    label: str
    comment: str
    created_by_user_id: uuid.UUID | None
    created_by_name: str
    created_at: datetime
    active: bool
    voided_at: datetime | None = None


class RealizationManagerReviewOut(RealizationSchema):
    period_id: uuid.UUID
    user_id: uuid.UUID
    can_edit: bool
    planning: RealizationManagerReviewItem | None
    realization: RealizationManagerReviewItem | None
    history: list[RealizationManagerReviewItem] = Field(default_factory=list)


class RealizationFinalDecision(RealizationSchema):
    final_symbol: RealizationSymbol | None = None
    final_level: RealizationLevel | None = None
    manager_comment: str | None = Field(default=None, max_length=4000)
    override_reason: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_complete_final(self) -> "RealizationFinalDecision":
        final_fields = (self.final_symbol, self.final_level)
        if any(value is not None for value in final_fields) and not all(
            value is not None for value in final_fields
        ):
            raise ValueError("final symbol and level must be supplied together")
        return self

    def validate_against_suggestion(
        self,
        *,
        suggested_symbol: RealizationSymbol | None,
        suggested_level: RealizationLevel | None,
    ) -> None:
        if self.final_level is None:
            return
        changed = (
            self.final_symbol != suggested_symbol
            or self.final_level != suggested_level
        )
        if changed and not (self.override_reason and self.override_reason.strip()):
            raise ValueError("an override_reason is required when final differs from suggested")


class RealizationPersonResultOut(RealizationSchema):
    id: uuid.UUID
    period_id: uuid.UUID
    user_id: uuid.UUID
    department_id: uuid.UUID | None
    facts_json: dict
    planned_count: int
    completed_on_time_count: int
    completed_late_count: int
    in_progress_count: int
    pending_count: int
    no_progress_count: int
    additional_count: int
    approved_postponement_count: int
    unapproved_postponement_count: int
    system_task_count: int
    system_task_completed_count: int
    meeting_missed_count: int
    tardiness_count: int
    approved_absence_days: int
    unexcused_absence_days: int
    diamond_count: int
    positive_count: int
    negative_count: int
    neutral_count: int
    proposal_count: int
    helped_colleague_count: int
    time_saved_minutes: int
    repeated_problem_count: int
    suggested_symbol: RealizationSymbol | None
    suggested_level: RealizationLevel | None
    ai_suggested_level: RealizationLevel | None = None
    ai_generated_at: datetime | None = None
    ai_analysis_stale: bool = True
    final_symbol: RealizationSymbol | None
    final_level: RealizationLevel | None
    auto_narrative: str | None
    manager_comment: str | None
    override_reason: str | None
    reviewed_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    reviewed_at: datetime | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RealizationDepartmentResultOut(RealizationSchema):
    id: uuid.UUID
    period_id: uuid.UUID
    department_id: uuid.UUID
    facts_json: dict
    a_plus_count: int
    a_count: int
    b_count: int
    c_count: int
    m_count: int
    d_count: int
    e_count: int
    a_rate: Decimal | None
    proposal_count: int
    time_saved_minutes: int
    repeated_problem_count: int
    trend_percent: Decimal | None
    department_suggestion: str | None
    final_comment: str | None
    created_at: datetime
    updated_at: datetime


class RealizationReviewRequest(RealizationFinalDecision):
    # Retained for backwards-compatible AUTO confirmations. Formal MANUAL
    # answers are persisted through the question-answer endpoint.
    question_values: dict[str, object] = Field(default_factory=dict)


class RealizationQuestionAnswerCreate(RealizationSchema):
    value: bool | str | None
    clear: bool = False
    comment: str | None = Field(default=None, max_length=4000)
    evidence_ids: list[uuid.UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_comment_for_yes(self) -> "RealizationQuestionAnswerCreate":
        if not self.clear and self.value is True and not (self.comment and self.comment.strip()):
            raise ValueError("Komenti është i detyrueshëm kur përgjigjja është Po")
        return self


class RealizationQuestionAnswerOut(RealizationSchema):
    id: uuid.UUID
    period_id: uuid.UUID
    result_id: uuid.UUID
    question_key: str
    value: bool | str | None
    comment: str | None
    evidence_ids: list[uuid.UUID]
    answered_by: uuid.UUID
    answered_by_name: str | None = None
    answered_at: datetime
    supersedes_answer_id: uuid.UUID | None
    updated_at: datetime


class RealizationObservationVerify(RealizationSchema):
    comment: str | None = Field(default=None, max_length=4000)


class RealizationPersonWorkflowOut(RealizationPersonResultOut):
    user_name: str


class RealizationWeeklyOut(RealizationSchema):
    period: RealizationPeriodOut
    department_name: str | None = None
    has_planned_snapshot: bool
    planned_snapshot_captured_day: date | None = None
    has_final_snapshot: bool
    can_calculate: bool
    message: str | None = None
    people: list[RealizationPersonWorkflowOut] = Field(default_factory=list)
    department_result: RealizationDepartmentResultOut | None = None
    unassigned: list[dict] = Field(default_factory=list)


class RealizationDailyOut(RealizationSchema):
    period: RealizationPeriodOut
    department_name: str | None = None
    has_planned_snapshot: bool
    can_calculate: bool
    message: str | None = None
    people: list[RealizationPersonWorkflowOut] = Field(default_factory=list)
    department_result: RealizationDepartmentResultOut | None = None
    live: dict | None = None


class DailyPlanAdjustmentDecision(RealizationSchema):
    audit_event_id: uuid.UUID
    user_id: uuid.UUID
    status: str
    reason: str = Field(min_length=1, max_length=4000)
    comment: str | None = Field(default=None, max_length=4000)


class RealizationAIAnalysisOut(RealizationSchema):
    summary: str
    positives: list[str]
    problems: list[str]
    missing_evidence: list[str]
    suggested_level: RealizationLevel
    grade_reason: str
    grade_drivers: list[dict]
    caps: list[dict]
    question_keys_used: list[str]
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str]
    model: str
    advisory_only: bool = True


class RealizationDailyCloseRequest(RealizationSchema):
    daily_comment: str | None = Field(default=None, max_length=2000)
    confirmed_pulse: RealizationPulse | None = None
    reason: str | None = Field(default=None, max_length=4000)


class RealizationDailyReopenRequest(RealizationSchema):
    reason: str = Field(min_length=1, max_length=4000)


class RealizationDailyApprovalRequest(RealizationSchema):
    approval_comment: str | None = Field(default=None, max_length=2000)


class RealizationDailyApprovalRevokeRequest(RealizationSchema):
    reason: str = Field(min_length=1, max_length=4000)


class RealizationDailyApprovalOut(RealizationSchema):
    id: uuid.UUID
    period_id: uuid.UUID
    result_id: uuid.UUID
    user_id: uuid.UUID
    department_id: uuid.UUID
    action: str
    source_close_event_id: uuid.UUID | None
    approval_comment: str | None
    reason: str | None
    actor_user_id: uuid.UUID
    created_at: datetime
    status: str


class RealizationDailyCloseEventOut(RealizationSchema):
    id: uuid.UUID
    period_id: uuid.UUID
    result_id: uuid.UUID
    user_id: uuid.UUID
    department_id: uuid.UUID
    action: RealizationDailyCloseAction
    mode: RealizationOperatingMode
    suggested_pulse: RealizationPulse
    confirmed_pulse: RealizationPulse | None
    daily_comment: str | None
    reason: str | None
    facts_json: dict
    supersedes_event_id: uuid.UUID | None
    actor_user_id: uuid.UUID
    created_at: datetime


class RealizationMonthlyPersonOut(RealizationSchema):
    user_id: uuid.UUID
    user_name: str
    department_id: uuid.UUID | None
    aggregation: dict


class RealizationMonthlyOut(RealizationSchema):
    month_start: date
    month_end: date
    department_id: uuid.UUID
    department_name: str | None = None
    people: list[RealizationMonthlyPersonOut] = Field(default_factory=list)
