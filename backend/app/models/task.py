from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, event, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import ProjectPhaseStatus, TaskFinishPeriod, TaskPriority, TaskSkillCategory, TaskStatus


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("question_origin_id", name="uq_tasks_question_origin"),
    )
    # Unique constraint removed - now allows multiple tasks per template (one per user)
    # Database has unique index: uq_tasks_system_template_user_date

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(String)
    internal_notes: Mapped[str | None] = mapped_column(String)
    skill_category: Mapped[TaskSkillCategory | None] = mapped_column(
        Enum(TaskSkillCategory, name="task_skill_category"), nullable=True, index=True
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    dependency_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id")
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    confirmation_assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    ga_note_origin_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ga_notes.id"))
    plan_note_origin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan_notes.id"), index=True
    )
    question_origin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("question_definitions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    question_batch_date: Mapped[date | None] = mapped_column(Date, nullable=True, unique=True, index=True)
    system_template_origin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("system_task_templates.id")
    )
    origin_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    system_task_slot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("system_task_template_assignee_slots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    meeting_origin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    meeting_occurrence_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    meeting_system_task_kind: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # Groups per-user copies of a single "logical" standalone task.
    # Used for multi-assignee standalone tasks (e.g. fast tasks and GA/KA note tasks without a project).
    fast_task_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)

    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="TODO"
    )
    priority: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="NORMAL"
    )
    finish_period: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    phase: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="MEETINGS",
    )
    progress_percentage: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    daily_products: Mapped[int | None] = mapped_column(Integer, nullable=True)

    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Keeps the original planned end date when a task is postponed (due_date changed).
    # Late/overdue is always computed against current due_date; this field is for reporting/history only.
    original_due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    is_repetitive: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_deadline_important: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_bllok: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_1h_report: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    one_h_report_slot: Mapped[str | None] = mapped_column(String(5), nullable=True)
    one_h_marker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    one_h_marker_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    one_h_marker_by_ga: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    one_h_marker_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_r1: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_personal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    fast_task_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Assignees are loaded explicitly by the endpoints that return them. Keeping
    # this relationship unloaded prevents a second, duplicate SELECT on every
    # ordinary Task query.
    assignees = relationship("TaskAssignee", backref="task", lazy="noload", passive_deletes=True)


@event.listens_for(Task, "before_insert")
@event.listens_for(Task, "before_update")
def normalize_completed_task_dates(mapper, connection, task: Task) -> None:
    """Keep completion dates consistent across all task-writing workflows."""
    from datetime import timezone
    from zoneinfo import ZoneInfo

    from app.config import settings

    status = getattr(task.status, "value", task.status)
    if str(status or "").upper() != "DONE" or task.completed_at is None:
        return
    tz = ZoneInfo(settings.APP_TIMEZONE)

    def local_day(value):
        if value is None:
            return None
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(tz).date()

    completed_day = local_day(task.completed_at)
    if local_day(task.due_date) != completed_day:
        if task.due_date is not None and task.original_due_date is None:
            task.original_due_date = task.due_date
        task.due_date = task.completed_at
    if task.start_date is not None and local_day(task.start_date) > completed_day:
        task.start_date = task.completed_at
