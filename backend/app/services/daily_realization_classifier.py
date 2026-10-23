from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DailyClassificationInput:
    day: date
    in_baseline: bool
    original_due_date: date | None
    current_due_date: date | None
    created_date: date | None
    completed_date: date | None
    status: str
    progress_delta: float = 0
    postponed: bool = False
    postponement_approved: bool = False
    reopened: bool = False
    reassigned_out: bool = False
    reassigned_in: bool = False


def classify_daily_task(value: DailyClassificationInput) -> str:
    """Classify one user/task/day using stable, documented precedence."""
    status = (value.status or "TODO").upper()
    # Current DONE is not enough for a historical day; completion must be
    # attributed by a timestamp or day-scoped progress/event record.
    completed_today = value.completed_date == value.day

    if value.in_baseline and value.reassigned_out:
        return "REASSIGNED_OUT"
    # A reopening remains an exception only until the task is completed again.
    if value.in_baseline and value.reopened and not completed_today:
        return "REOPENED"
    if value.in_baseline and value.postponed:
        return "POSTPONED_APPROVED" if value.postponement_approved else "POSTPONED_UNAPPROVED"
    if value.in_baseline and completed_today:
        return "REALIZED_AS_PLANNED"
    if value.in_baseline and status == "WAITING_CONFIRMATION":
        return "WAITING_CONFIRMATION"
    if value.in_baseline and (status == "IN_PROGRESS" or value.progress_delta > 0):
        return "IN_PROGRESS"
    if value.in_baseline:
        return "NO_PROGRESS"

    if value.reassigned_in:
        return "ADDITIONAL_COMPLETED" if completed_today else "REASSIGNED_IN"
    if completed_today:
        if value.original_due_date and value.original_due_date < value.day:
            return "COMPLETED_LATE"
        if value.original_due_date and value.original_due_date > value.day:
            return "COMPLETED_EARLY"
        return "ADDITIONAL_COMPLETED"
    if value.current_due_date and value.current_due_date < value.day:
        if status == "WAITING_CONFIRMATION":
            return "WAITING_CONFIRMATION"
        if status == "IN_PROGRESS" or value.progress_delta > 0:
            return "IN_PROGRESS"
        return "NO_PROGRESS"
    return "ADDED_DURING_DAY"


EXCEPTION_CLASSIFICATIONS = {
    "POSTPONED", "POSTPONED_APPROVED", "POSTPONED_UNAPPROVED", "NO_PROGRESS",
    "REOPENED", "REASSIGNED_OUT", "REASSIGNED_IN",
}
