"""Proposal diamonds are derived from the current saved answer, never its revisions."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
import uuid
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.realization import RealizationPeriod, RealizationPersonResult, RealizationQuestionAnswer
from app.models.user import User
from app.schemas.task_review import TaskReviewOut, TaskReviewOverviewRow


def proposal_diamond_score(answer: RealizationQuestionAnswer) -> int:
    value = answer.value_json or {}
    return int(getattr(answer, "question_key", None) == "gave_proposal" and value.get("value") is True
               and not value.get("cleared") and bool((answer.comment or "").strip()))


def proposal_diamond_rows(records: Iterable[tuple[RealizationQuestionAnswer, RealizationPeriod, User, User]],
                          *, date_from: date, date_to: date, app_timezone) -> list[TaskReviewOverviewRow]:
    # Also deduplicate here so callers cannot award a second diamond for an edit.
    latest = {}
    for record in records:
        answer = record[0]
        previous = latest.get(answer.result_id)
        if previous is None or (answer.answered_at, str(answer.id)) > (previous[0].answered_at, str(previous[0].id)):
            latest[answer.result_id] = record
    eligible = [record for record in latest.values() if proposal_diamond_score(record[0])]
    daily_weeks = {
        (subject.id, period.start_date - timedelta(days=period.start_date.weekday()))
        for _, period, subject, _ in eligible if period.period_type == "DAILY"
    }
    rows = []
    for answer, period, subject, reviewer in eligible:
        # An explicit weekly Yes summarizes the day's proposals; it must not
        # award the same contribution again when a daily diamond already exists.
        week = period.start_date - timedelta(days=period.start_date.weekday())
        if period.period_type == "WEEKLY" and (subject.id, week) in daily_weeks:
            continue
        if not date_from <= period.start_date <= date_to:
            continue
        title = "Propozim për përmirësim"
        subject_name = subject.full_name or subject.username or subject.email
        reviewer_name = reviewer.full_name or reviewer.username or reviewer.email
        review = TaskReviewOut(
            id=answer.result_id, task_id=None, source="REALIZATION_PROPOSAL",
            realization_period_id=period.id, reviewee_user_id=subject.id, reviewee_name=subject_name,
            reviewer_user_id=reviewer.id, reviewer_name=reviewer_name, diamond_score=1,
            comment=answer.comment.strip(), task_title=title, project_title=None,
            created_at=answer.answered_at, updated_at=answer.updated_at,
        )
        rows.append(TaskReviewOverviewRow(
            task_id=None, task_title=title, source="REALIZATION_PROPOSAL",
            realization_period_id=period.id, department_id=period.department_id,
            reviewee_user_id=subject.id, reviewee_name=subject_name,
            completed_at=datetime.combine(period.start_date, time(12), tzinfo=app_timezone), review=review,
        ))
    return rows


async def load_proposal_diamonds(db: AsyncSession, *, date_from: date, date_to: date,
                                department_id: uuid.UUID | None, reviewee_user_id: uuid.UUID | None,
                                app_timezone) -> list[TaskReviewOverviewRow]:
    reviewer = aliased(User)
    scope_start = date_from - timedelta(days=date_from.weekday())
    scope_end = date_to + timedelta(days=6 - date_to.weekday())
    statement = (
        select(RealizationQuestionAnswer, RealizationPeriod, User, reviewer)
        .join(RealizationPersonResult, RealizationPersonResult.id == RealizationQuestionAnswer.result_id)
        .join(RealizationPeriod, RealizationPeriod.id == RealizationQuestionAnswer.period_id)
        .join(User, User.id == RealizationPersonResult.user_id)
        .join(reviewer, reviewer.id == RealizationQuestionAnswer.answered_by)
        .where(RealizationQuestionAnswer.question_key == "gave_proposal",
               RealizationPeriod.period_type.in_(["DAILY", "WEEKLY"]),
               RealizationPeriod.start_date >= scope_start, RealizationPeriod.start_date <= scope_end)
        .distinct(RealizationQuestionAnswer.result_id)
        .order_by(RealizationQuestionAnswer.result_id, RealizationQuestionAnswer.answered_at.desc(),
                  RealizationQuestionAnswer.id.desc())
    )
    if department_id is not None:
        statement = statement.where(RealizationPeriod.department_id == department_id)
    if reviewee_user_id is not None:
        statement = statement.where(RealizationPersonResult.user_id == reviewee_user_id)
    records = (await db.execute(statement)).all()
    return proposal_diamond_rows(records, date_from=date_from, date_to=date_to, app_timezone=app_timezone)
