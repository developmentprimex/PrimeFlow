from __future__ import annotations

from datetime import date

from app.services.daily_realization_metrics import (
    WFE_CREDIT,
    deadline_task_card,
    extra_task_penalty,
    plan_task_penalty,
    realization_percent,
    sort_deadline_cards,
)

PLANNED_ATTRIBUTIONS = {"planned_owner", "planned_today", "system_schedule"}
ADDITIONAL_ATTRIBUTIONS = {
    "additional_owner", "completed_outside_weekly_plan", "added_after_weekly_plan",
}
COMPLETED_CLASSIFICATIONS = {
    "COMPLETED", "COMPLETED_ON_TIME", "COMPLETED_LATE", "COMPLETED_EARLY",
    "REALIZED_AS_PLANNED", "ADDITIONAL_COMPLETED",
}


def _identity(task: dict) -> str | None:
    if task.get("task_id"):
        return f"id:{task['task_id']}"
    return str(task.get("match_key") or task.get("title") or "").strip() or None


def _classification(task: dict) -> str:
    return str(task.get("classification") or "").strip().upper()


def _status(task: dict) -> str:
    return str(task.get("current_status") or task.get("status") or "").strip().upper()


def _is_completed(task: dict) -> bool:
    return _classification(task) in COMPLETED_CLASSIFICATIONS or _status(task) == "DONE"


def _is_postponed(task: dict) -> bool:
    return (
        _classification(task).startswith("POSTPONED")
        or bool(task.get("postponement"))
        # The push itself happened on a day of this week, whatever the day's
        # classification ended up being.
        or bool(task.get("postponed_today"))
    )


def _is_in_progress(task: dict) -> bool:
    return (
        _classification(task) in {"IN_PROGRESS", "ADDITIONAL_IN_PROGRESS"}
        or _status(task) == "IN_PROGRESS"
        or float(task.get("progress_today") or 0) > 0
        or float(task.get("completed_delta") or 0) > 0
    )


def _deadline_state(task: dict) -> str:
    if task.get("deadline_completed"):
        return "COMPLETED"
    if task.get("postponed_today"):
        return "POSTPONED"
    return "IN_PROGRESS" if _is_in_progress(task) else "NO_PROGRESS"


def _created_on_or_after(task: dict, week_start: date) -> bool | None:
    raw = str(task.get("created_date") or "")[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw) >= week_start
    except ValueError:
        return None


def _task_kind(task: dict, week_start: date | None = None) -> str | None:
    """Work born during the week is extra; work that predates it is the plan.

    The weekly plan snapshot cannot decide this, because it is sometimes
    captured mid-week and then already contains the week's new work.
    """
    if week_start is not None:
        created_during_week = _created_on_or_after(task, week_start)
        if created_during_week is not None:
            return "additional" if created_during_week else "planned"
    attribution = str(task.get("attribution") or "").strip()
    if attribution in PLANNED_ATTRIBUTIONS:
        return "planned"
    if attribution in ADDITIONAL_ATTRIBUTIONS:
        return "additional"
    # Live daily snapshots do not always carry the legacy attribution field.
    if task.get("in_original_plan") is True:
        return "planned"
    if task.get("in_original_plan") is False:
        return "additional"
    return None


def _prefer_state(previous: dict | None, current: dict) -> dict:
    """Keep the strongest useful state when a task occurs on several days."""
    if previous is None:
        return current
    def rank(task: dict) -> int:
        if _is_completed(task):
            return 3
        if _is_postponed(task):
            return 2
        if _is_in_progress(task):
            return 1
        return 0
    return current if rank(current) >= rank(previous) else previous


def build_weekly_task_metrics(
    snapshot_tasks: list[dict],
    daily_timeline: list[dict],
    *,
    week_start: date | None = None,
) -> dict[str, object]:
    """Aggregate unique obligations from the weekly snapshot and every daily snapshot."""
    planned_keys: set[str] = set()
    additional_keys: set[str] = set()
    states: dict[str, dict] = {}
    quantity_occurrences: dict[tuple[str, str], dict] = {}
    deadline_occurrences: dict[tuple[str, str], dict] = {}
    # Whether each task was waiting for the client (WFE) on the last day it appeared.
    latest_wfe: dict[str, tuple[str, bool]] = {}

    def collect(task: dict) -> str | None:
        identity = _identity(task)
        if identity is None:
            return None
        kind = _task_kind(task, week_start)
        if kind == "planned":
            planned_keys.add(identity)
        elif kind == "additional":
            additional_keys.add(identity)
        states[identity] = _prefer_state(states.get(identity), task)
        return identity

    for task in snapshot_tasks:
        collect(task)

    for timeline_item in daily_timeline:
        day = str(timeline_item.get("date") or "")
        planned_today: set[str] = set()
        completed_today: set[str] = set()
        for task in timeline_item.get("tasks") or []:
            identity = collect(task)
            if identity is not None and "wfe" in task and day >= latest_wfe.get(identity, ("", False))[0]:
                latest_wfe[identity] = (day, bool(task["wfe"]))
            if identity is not None and isinstance(task.get("quantity"), dict):
                quantity_occurrences[(day, identity)] = task["quantity"]
            if identity is not None and task.get("deadline_was_today"):
                deadline_occurrences[(day, identity)] = task
            if identity is None or _task_kind(task, week_start) != "planned":
                continue
            planned_today.add(identity)
            if _is_completed(task):
                completed_today.add(identity)
        # Daily metrics come from the same report as the Daily table. Weekly
        # task attribution (creation date) must not rewrite a day's baseline.
        timeline_item.setdefault("planned_count", len(planned_today))
        timeline_item.setdefault("completed_count", len(completed_today))
        timeline_item.setdefault("daily_progress_percent", None)

    # A task known to belong to the plan can never also be an extra. Legacy data
    # without either marker is treated as extra only when it was completed.
    completed_keys = {key for key, task in states.items() if _is_completed(task)}
    additional_keys.update(completed_keys - planned_keys - additional_keys)
    additional_keys.difference_update(planned_keys)
    planned_completed = planned_keys & completed_keys
    additional_completed = additional_keys & completed_keys

    # Extra work that was added, never touched, and then pushed to a later date
    # was never this week's work. It belongs to the week it actually gets done,
    # so the week reports it apart instead of inflating its own extra count.
    additional_deferred = {
        key
        for key in additional_keys - additional_completed
        if _is_postponed(states[key]) and not _is_in_progress(states[key])
    }
    additional_keys -= additional_deferred

    additional_postponed = {
        key for key in additional_keys - additional_completed if _is_postponed(states[key])
    }
    additional_in_progress = {
        key for key in additional_keys - additional_completed - additional_postponed
        if _is_in_progress(states[key])
    }
    additional_todo = additional_keys - additional_completed - additional_postponed - additional_in_progress

    # WFE work is done on our side: 90% credit and no penalty for the week.
    wfe_keys = {
        key for key, (_day, wfe) in latest_wfe.items()
        if wfe and key not in completed_keys and (key in planned_keys or key in additional_keys)
    }
    pending_planned = planned_keys - planned_completed
    planned_postponed = {key for key in pending_planned if _is_postponed(states[key])}
    planned_in_progress = {
        key for key in pending_planned - planned_postponed if _is_in_progress(states[key])
    }
    planned_no_progress = pending_planned - planned_postponed - planned_in_progress
    quantity_planned = sum(int(item.get("planned") or 0) for item in quantity_occurrences.values())
    quantity_completed = sum(int(item.get("completed") or 0) for item in quantity_occurrences.values())
    deadlines_by_task: dict[str, list[tuple[str, dict]]] = {}
    for (day, task_key), task in sorted(deadline_occurrences.items()):
        deadlines_by_task.setdefault(task_key, []).append((day, task))
    deadline_cards = []
    for task_key, occurrences in deadlines_by_task.items():
        day, task = occurrences[-1]
        # The weekly total counts tasks. Earlier missed/moved deadlines remain
        # dated history, even when the task was completed later in the week.
        state = "COMPLETED" if task_key in completed_keys else _deadline_state(task)
        card = deadline_task_card(task, state=state, day=day or None)
        card["critical"] = any(item.get("deadline_critical") for _, item in occurrences)
        if task.get("match_key"):
            card["match_key"] = str(task["match_key"])
        card["history"] = [
            {"day": occurrence_day or None, "state": _deadline_state(item),
             "critical": bool(item.get("deadline_critical"))}
            for occurrence_day, item in occurrences
        ]
        deadline_cards.append(card)
    deadlines_completed = sum(1 for card in deadline_cards if card["state"] == "COMPLETED")
    deadlines_postponed = sum(1 for card in deadline_cards if card["state"] == "POSTPONED")
    deadlines_in_progress = sum(1 for card in deadline_cards if card["state"] == "IN_PROGRESS")
    deadlines_no_progress = sum(1 for card in deadline_cards if card["state"] == "NO_PROGRESS")
    critical_deadlines = [card for card in deadline_cards if card["critical"]]
    critical_deadlines_completed = sum(1 for card in critical_deadlines if card["state"] == "COMPLETED")

    metrics: dict[str, object] = {
        "weekly_deadline_tasks": sort_deadline_cards(deadline_cards),
        "weekly_planned_count": len(planned_keys),
        "weekly_completed_count": len(planned_completed),
        "weekly_all_completed_count": len(planned_completed | additional_completed),
        "weekly_in_progress_task_count": len(planned_in_progress),
        "weekly_postponed_task_count": len(planned_postponed),
        "weekly_approved_postponed_task_count": sum(
            states[key].get("adjustment_status") == "APPROVED"
            or (not states[key].get("adjustment_status") and _classification(states[key]) == "POSTPONED_APPROVED")
            for key in planned_postponed
        ),
        "weekly_no_progress_task_count": len(planned_no_progress),
        "weekly_additional_count": len(additional_keys),
        "weekly_additional_deferred_count": len(additional_deferred),
        "weekly_additional_completed_count": len(additional_completed),
        "weekly_additional_in_progress_count": len(additional_in_progress),
        "weekly_additional_postponed_count": len(additional_postponed),
        "weekly_additional_todo_count": len(additional_todo),
        "weekly_additional_no_progress_count": len(additional_todo),
        "weekly_quantity_task_count": len(quantity_occurrences),
        "weekly_quantity_planned_count": quantity_planned,
        "weekly_quantity_completed_count": quantity_completed,
        "weekly_quantity_delta": quantity_completed - quantity_planned,
        "weekly_deadline_count": len(deadline_cards),
        "weekly_deadline_completed_count": deadlines_completed,
        "weekly_deadline_postponed_count": deadlines_postponed,
        "weekly_deadline_in_progress_count": deadlines_in_progress,
        "weekly_deadline_no_progress_count": deadlines_no_progress,
        "weekly_critical_deadline_count": len(critical_deadlines),
        "weekly_critical_deadline_completed_count": critical_deadlines_completed,
    }
    deadline_keys = {key for _day, key in deadline_occurrences}
    critical_keys = {key for (_day, key), task in deadline_occurrences.items() if task.get("deadline_critical")}
    # Only work still unfinished at the end of the week is penalised: every
    # open plan task, and extras only for a deadline they let slip.
    penalty_points = sum(
        plan_task_penalty(
            postponed=key in planned_postponed,
            deadline=key in deadline_keys,
            critical=key in critical_keys,
            completed=False,
            no_progress=key in planned_no_progress,
        )
        for key in pending_planned - wfe_keys
    ) + sum(
        extra_task_penalty(
            postponed=key in additional_postponed,
            deadline=key in deadline_keys,
            critical=key in critical_keys,
            completed=False,
        )
        for key in additional_keys - additional_completed - wfe_keys
    )
    metrics["weekly_wfe_count"] = len(wfe_keys)
    metrics["weekly_penalty_points"] = penalty_points
    metrics["weekly_progress_percent"] = realization_percent(
        len(planned_completed | additional_completed) + WFE_CREDIT * len(wfe_keys),
        len(planned_keys), len(additional_keys),
        penalty_points, len(planned_keys) or len(additional_keys),
    ) or 0.0
    return metrics


def build_weekly_question_metrics(daily_timeline: list[dict]) -> dict[str, int]:
    """Aggregate day-level counters used by the weekly automatic questions."""
    snapshot_days = [item for item in daily_timeline if item.get("has_snapshot")]
    return {
        "weekly_in_progress_count": sum(int(item.get("in_progress_count", 0) or 0) for item in snapshot_days),
        "weekly_no_progress_count": sum(int(item.get("no_progress_count", 0) or 0) for item in snapshot_days),
        "weekly_pending_count": sum(int(item.get("pending_count", 0) or 0) for item in snapshot_days),
        "weekly_fast_task_count": sum(int(item.get("fast_task_count", 0) or 0) for item in snapshot_days),
        "weekly_snapshot_days": len(snapshot_days),
    }
