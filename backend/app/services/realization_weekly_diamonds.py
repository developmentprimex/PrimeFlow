"""Group the same awarded diamonds shown in Reviews for the weekly report."""
from __future__ import annotations

import uuid

from app.schemas.task_review import TaskReviewOverviewRow


def empty_weekly_diamonds() -> dict:
    return {"weekly_diamond_count": 0, "weekly_task_diamond_count": 0,
            "weekly_proposal_diamond_count": 0, "weekly_diamonds": []}


def group_weekly_diamonds(rows: list[TaskReviewOverviewRow]) -> dict[uuid.UUID, dict]:
    grouped = {}
    seen = set()
    for row in rows:
        if row.review is None or row.review.diamond_score < 1:
            continue
        key = (row.source, row.review.id, row.reviewee_user_id)
        if key in seen:
            continue
        seen.add(key)
        facts = grouped.setdefault(row.reviewee_user_id, empty_weekly_diamonds())
        facts["weekly_diamond_count"] += row.review.diamond_score
        source_key = "weekly_proposal_diamond_count" if row.source == "REALIZATION_PROPOSAL" else "weekly_task_diamond_count"
        facts[source_key] += row.review.diamond_score
        facts["weekly_diamonds"].append(row.model_dump(mode="json"))
    return grouped
