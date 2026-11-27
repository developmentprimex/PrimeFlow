"""Single source of truth for Daily Report explanation requirements."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

WEEKLY_PLANNING_REASON = "WEEKLY_PLANNING"


def reason_requires_comment(reason_code: str | None) -> bool:
    return reason_code not in {"PV", WEEKLY_PLANNING_REASON}


@dataclass(frozen=True)
class DailyExplanationRequirement:
    reason_required: bool
    comment_required: bool

    @property
    def requires_explanation(self) -> bool:
        return self.reason_required or self.comment_required


def requires_daily_explanation(
    *,
    status: str,
    selected_day: date,
    deadline: date | None,
    deadline_was_today: bool = False,
    postponed_today: bool = False,
    reason_code: str | None = None,
) -> DailyExplanationRequirement:
    """Return the final reason/comment rule for one task/day.

    TODO, postponed work, and IN_PROGRESS work due today/overdue require a
    reason and, depending on the reason, a comment. Future IN_PROGRESS and DONE do not.
    """
    normalized = (status or "TODO").upper()
    if normalized == "DONE":
        return DailyExplanationRequirement(False, False)
    if postponed_today or normalized == "TODO":
        return DailyExplanationRequirement(True, reason_requires_comment(reason_code))
    if normalized == "IN_PROGRESS" and (
        deadline_was_today or deadline is None or deadline <= selected_day
    ):
        return DailyExplanationRequirement(True, reason_requires_comment(reason_code))
    return DailyExplanationRequirement(False, False)

