from __future__ import annotations

import math
from collections import Counter
from datetime import date, timedelta
from typing import Iterable, Mapping

COMPLETED_CLASSIFICATIONS = {"ADDITIONAL_COMPLETED", "COMPLETED_LATE", "COMPLETED_EARLY"}
# A task waiting for the client (WFE) is done on our side except for the client's answer.
WFE_CREDIT = 0.9


def row_has_progress(row: Mapping[str, object]) -> bool:
    """Any sign the person moved the task forward, beyond a status label."""
    quantity = row.get("quantity")
    return bool(
        row.get("classification") == "IN_PROGRESS"
        or row.get("current_status") == "IN_PROGRESS"
        or float(row.get("progress_today") or 0) > 0
        or float(row.get("completed_delta") or 0) > 0
        or (quantity and quantity["source"] == "title" and quantity["completed"] > 0)
    )


def deadline_state(row: Mapping[str, object]) -> str:
    """The four mutually exclusive answers to "what happened to this deadline?"."""
    if row.get("deadline_completed"):
        return "COMPLETED"
    if row.get("postponed_today"):
        return "POSTPONED"
    return "IN_PROGRESS" if row_has_progress(row) else "NO_PROGRESS"


def deadline_task_card(row: Mapping[str, object], *, state: str, day: str | None = None) -> dict:
    """Row shown in the deadline popover of the daily and weekly tables."""
    return {
        "task_id": str(row["task_id"]) if row.get("task_id") else None,
        "title": str(row.get("title") or "Pa titull"),
        "day": day,
        "state": state,
        "critical": bool(row.get("deadline_critical")),
    }


DEADLINE_STATE_ORDER = {"NO_PROGRESS": 0, "POSTPONED": 1, "IN_PROGRESS": 2, "COMPLETED": 3}


def sort_deadline_cards(cards: list[dict]) -> list[dict]:
    """Unfinished and critical deadlines first, since those need an explanation."""
    return sorted(
        cards,
        key=lambda card: (
            DEADLINE_STATE_ORDER.get(card["state"], len(DEADLINE_STATE_ORDER)),
            not card["critical"],
            card.get("day") or "",
            card["title"],
        ),
    )


def working_days(start: date, end: date) -> int:
    """Monday-Friday days from start to end, both included."""
    return sum(
        1 for offset in range((end - start).days + 1)
        if (start + timedelta(days=offset)).weekday() < 5
    )


def multi_day_share(start: date | None, due: date | None, day: date) -> tuple[float, bool]:
    """A task spread over several working days weighs 1/N of a task on each of them.

    Returns the day's share and whether the day comes before the deadline, the
    only days on which being in progress means the task is on schedule.
    """
    if not start or not due or start >= due or not start <= day <= due:
        return 1.0, False
    days = working_days(start, due)
    if days <= 1:
        return 1.0, False
    return 1.0 / days, day < due


POSTPONED_PENALTY = 25.0
POSTPONED_DEADLINE_PENALTY = 20.0
POSTPONED_CRITICAL_DEADLINE_PENALTY = 60.0
MISSED_DEADLINE_PENALTY = 30.0
MISSED_CRITICAL_DEADLINE_PENALTY = 70.0
# Leaving a plan task untouched must not cost less than postponing it honestly.
NO_PROGRESS_PENALTY = POSTPONED_PENALTY


def plan_task_penalty(
    *, postponed: bool, deadline: bool, critical: bool, completed: bool, no_progress: bool = False,
) -> float:
    """Points one unfinished plan task deducts; a missed deadline costs more than an honest postponement."""
    if completed:
        return 0.0
    if postponed:
        if deadline:
            return POSTPONED_CRITICAL_DEADLINE_PENALTY if critical else POSTPONED_DEADLINE_PENALTY
        return POSTPONED_PENALTY
    if deadline:
        return MISSED_CRITICAL_DEADLINE_PENALTY if critical else MISSED_DEADLINE_PENALTY
    return NO_PROGRESS_PENALTY if no_progress else 0.0


def extra_task_penalty(*, postponed: bool, deadline: bool, critical: bool, completed: bool) -> float:
    """Extra work is only penalised for a deadline it let slip without postponing."""
    if completed or postponed or not deadline:
        return 0.0
    return MISSED_CRITICAL_DEADLINE_PENALTY if critical else MISSED_DEADLINE_PENALTY


def realization_percent(
    credit: float, plan_weight: float, extra: int, penalty_points: float, penalty_base: int,
) -> float | None:
    """Daily and weekly realization: credit capped at 100, then penalty points per task deducted."""
    denominator = plan_weight or extra
    if not denominator:
        return None
    base = min(100.0, credit * 100.0 / denominator)
    penalty = penalty_points / penalty_base if penalty_base else 0.0
    # Half up, like the frontend's Math.round, so both sides show the same figure.
    return math.floor(max(0.0, base - penalty) * 10 + 0.5) / 10


def combine_daily_metrics(departments: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Combine authoritative department metrics as the Realization dashboard does.

    Preserve the department's credit and extra-task weights; flattening its tasks
    and calculating again changes the total. Matches combineDailyRealization.
    """
    reports = list(departments)
    if not reports:
        return calculate_daily_metrics([])
    if len(reports) == 1:
        return dict(reports[0])
    derived = {
        "raw_plan_realization", "adjusted_plan_realization", "deadline_compliance_percentage",
        "daily_control_state", "deadline_tasks", "realization_items",
    }
    metrics = {
        key: sum(report.get(key) or 0 for report in reports)
        for key in reports[0] if key not in derived
    }
    for key in ("deadline_tasks", "realization_items"):
        metrics[key] = [item for report in reports for item in (report.get(key) or [])]
    extra = metrics["additional_count"]
    metrics["raw_plan_realization"] = realization_percent(
        metrics["realization_credit"], metrics["realization_plan_weight"], extra,
        metrics["realization_penalty_points"], metrics["original_planned_count"] or extra,
    )
    metrics["adjusted_plan_realization"] = realization_percent(
        metrics["realization_credit"], metrics["adjusted_realization_plan_weight"], extra,
        metrics["adjusted_realization_penalty_points"], metrics["adjusted_denominator"] or extra,
    )
    deadlines = metrics["deadlines_today_count"]
    metrics["deadline_compliance_percentage"] = (
        min(100, math.floor(metrics["deadlines_completed_count"] * 1000 / deadlines + 0.5) / 10)
        if deadlines else None
    )
    metrics["daily_control_state"] = (
        "ACTION_REQUIRED" if any(report.get("daily_control_state") == "ACTION_REQUIRED" for report in reports)
        else "CLEAN_DAY"
    )
    return metrics


def _realization_item(row: Mapping[str, object], *, extra_weight: float) -> dict:
    """How one row moved the daily percent, for the Plan RLZ explanation."""
    classification = str(row.get("classification") or "")
    planned = bool(row.get("in_original_plan"))
    share = float(row.get("daily_share") or 1.0) if planned else extra_weight
    postponed = classification.startswith("POSTPONED") or (not planned and bool(row.get("postponed_today")))
    completed = classification in {"REALIZED_AS_PLANNED", *COMPLETED_CLASSIFICATIONS}
    deadline = bool(row.get("deadline_was_today"))
    critical = bool(row.get("deadline_critical"))
    wfe = bool(row.get("wfe")) and not completed and not postponed and classification != "REASSIGNED_OUT"
    if wfe:
        kind = "WFE" if planned else "EXTRA_WFE"
        credit = share * WFE_CREDIT
    elif not planned:
        kind = "EXTRA_COMPLETED" if completed else "EXTRA_OPEN"
        credit = share if completed else 0.0
    elif completed:
        kind, credit = "COMPLETED", share
    elif postponed:
        kind, credit = "POSTPONED", 0.0
    elif classification == "IN_PROGRESS":
        kind = "IN_PROGRESS"
        # Multi-day work earns its daily share for every day it is still running before the deadline.
        credit = share if row.get("multi_day_before_deadline") else 0.0
    elif classification == "REASSIGNED_OUT":
        kind, credit = "REASSIGNED_OUT", 0.0
    else:
        kind, credit = "NO_PROGRESS", 0.0
    if wfe or classification == "REASSIGNED_OUT":
        penalty = 0.0
    elif not planned:
        penalty = extra_task_penalty(postponed=postponed, deadline=deadline, critical=critical, completed=completed)
    else:
        penalty = plan_task_penalty(
            postponed=postponed, deadline=deadline, critical=critical, completed=completed,
            no_progress=classification == "NO_PROGRESS",
        )
    return {
        "task_id": str(row["task_id"]) if row.get("task_id") else None,
        "title": str(row.get("title") or "Pa titull"),
        "kind": kind,
        "planned": planned,
        "share": round(share, 4),
        "credit": round(credit, 4),
        "penalty": penalty,
        "approved": classification == "POSTPONED_APPROVED",
        "deadline": deadline,
        "critical": critical,
    }


def calculate_daily_metrics(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    items = list(rows)
    outcomes = Counter(str(row.get("classification") or "") for row in items)
    original = sum(bool(row.get("in_original_plan")) for row in items)
    planned_done = outcomes["REALIZED_AS_PLANNED"]
    approved_scope = outcomes["POSTPONED_APPROVED"]
    adjusted_denominator = max(0, original - approved_scope)
    total_completed = sum(
        outcomes[name]
        for name in (
            "REALIZED_AS_PLANNED", "ADDITIONAL_COMPLETED", "COMPLETED_LATE", "COMPLETED_EARLY"
        )
    )
    extras = [row for row in items if not row.get("in_original_plan")]
    extra_completed = sum(
        row.get("classification") in {"ADDITIONAL_COMPLETED", "COMPLETED_LATE", "COMPLETED_EARLY"}
        for row in extras
    )
    extra_progress = sum(
        row.get("classification") not in COMPLETED_CLASSIFICATIONS and row_has_progress(row)
        for row in extras
    )
    plan_weight = round(sum(float(row.get("daily_share") or 1.0) for row in items if row.get("in_original_plan")), 4)
    # An extra weighs as much as the day's average plan task, so small extras
    # cannot cover multi-day plan work that only weighs a fraction of a task.
    extra_weight = plan_weight / original if original else 1.0
    realization_items = [_realization_item(row, extra_weight=extra_weight) for row in items]
    planned_items = [item for item in realization_items if item["planned"]]
    credit = round(sum(item["credit"] for item in realization_items), 4)
    penalty_points = sum(item["penalty"] for item in realization_items)
    # Approved postponements leave the adjusted plan, together with their penalty.
    approved_items = [item for item in planned_items if item["approved"]]
    adjusted_plan_weight = round(plan_weight - sum(item["share"] for item in approved_items), 4)
    adjusted_penalty_points = penalty_points - sum(item["penalty"] for item in approved_items)
    raw = realization_percent(credit, plan_weight, len(extras), penalty_points, original or len(extras))
    adjusted = realization_percent(
        credit, adjusted_plan_weight, len(extras), adjusted_penalty_points, adjusted_denominator or len(extras),
    )
    deadline_rows = [row for row in items if row.get("deadline_was_today")]
    deadline_cards = [
        deadline_task_card(row, state=deadline_state(row)) for row in deadline_rows
    ]
    deadline_states = Counter(card["state"] for card in deadline_cards)
    deadline_completed = deadline_states["COMPLETED"]
    deadline_postponed = deadline_states["POSTPONED"]
    deadline_in_progress = deadline_states["IN_PROGRESS"]
    deadline_no_progress = deadline_states["NO_PROGRESS"]
    deadline_open = deadline_in_progress + deadline_no_progress
    overdue_open = sum(bool(row.get("deadline_is_overdue")) and not bool(row.get("deadline_completed")) for row in items)
    critical_rows = [row for row in deadline_rows if row.get("deadline_critical")]
    critical_completed = sum(bool(row.get("deadline_completed")) for row in critical_rows)
    critical_open = max(0, len(critical_rows) - critical_completed - sum(bool(row.get("postponed_today")) for row in critical_rows))
    action_required = any(bool(row.get("action_required")) for row in items) or deadline_open > 0 or overdue_open > 0
    quantities = [row["quantity"] for row in items if row.get("quantity") and row.get("classification") != "REASSIGNED_OUT"]
    quantity_planned = sum(int(quantity["planned"]) for quantity in quantities)
    quantity_completed = sum(int(quantity["completed"]) for quantity in quantities)
    return {
        "quantity_task_count": len(quantities),
        "quantity_planned_count": quantity_planned,
        "quantity_completed_count": quantity_completed,
        "quantity_delta": quantity_completed - quantity_planned,
        "original_planned_count": original,
        "planned_completed_today_count": planned_done,
        "in_progress_count": outcomes["IN_PROGRESS"],
        "no_progress_count": outcomes["NO_PROGRESS"],
        "postponed_count": outcomes["POSTPONED_APPROVED"] + outcomes["POSTPONED_UNAPPROVED"],
        "approved_postponement_count": outcomes["POSTPONED_APPROVED"],
        "unapproved_postponement_count": outcomes["POSTPONED_UNAPPROVED"],
        "waiting_confirmation_count": outcomes["WAITING_CONFIRMATION"],
        "additional_count": len(extras),
        "additional_completed_count": extra_completed,
        "additional_in_progress_count": extra_progress,
        "additional_no_progress_count": len(extras) - extra_completed - extra_progress,
        "completed_late_count": outcomes["COMPLETED_LATE"],
        "completed_early_count": outcomes["COMPLETED_EARLY"],
        "reopened_count": outcomes["REOPENED"],
        "reassigned_out_count": outcomes["REASSIGNED_OUT"],
        "reassigned_in_count": outcomes["REASSIGNED_IN"],
        "total_completed_today_count": total_completed,
        "adjusted_exclusion_count": approved_scope,
        "adjusted_denominator": adjusted_denominator,
        "raw_plan_realization": raw,
        "adjusted_plan_realization": adjusted,
        "realization_plan_weight": plan_weight,
        "realization_credit": credit,
        "realization_penalty_points": penalty_points,
        "adjusted_realization_plan_weight": adjusted_plan_weight,
        "adjusted_realization_penalty_points": adjusted_penalty_points,
        "realization_items": [
            item for item in realization_items if item["kind"] != "EXTRA_OPEN" or item["penalty"]
        ],
        "deadline_tasks": sort_deadline_cards(deadline_cards),
        "deadlines_today_count": len(deadline_rows),
        "deadlines_completed_count": deadline_completed,
        "deadlines_postponed_count": deadline_postponed,
        "deadlines_in_progress_count": deadline_in_progress,
        "deadlines_no_progress_count": deadline_no_progress,
        "deadlines_open_count": deadline_open,
        "overdue_open_count": overdue_open,
        "deadline_compliance_percentage": round(deadline_completed * 100.0 / len(deadline_rows), 1) if deadline_rows else None,
        "critical_deadlines_today_count": len(critical_rows),
        "critical_deadlines_completed_count": critical_completed,
        "critical_deadlines_open_count": critical_open,
        "daily_control_state": "ACTION_REQUIRED" if action_required else "CLEAN_DAY",
    }
