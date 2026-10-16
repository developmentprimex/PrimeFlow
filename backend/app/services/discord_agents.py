"""Targets and authorized lifecycle of delegated Discord work."""
from __future__ import annotations

from app.services.task_strike_events import _point_entries

TERMINAL = {"READY", "FAILED", "CANCELLED"}


def resolve_target(task: dict, field: str | None, number: int | None) -> dict:
    if field is None and number is None:
        return {"field": None, "number": None, "key": None, "text": None}
    if field not in {"title", "description"} or type(number) is not int:
        raise ValueError("Zgjidh një pikë titulli ose përshkrimi.")
    entries = _point_entries(task.get(field), field_name=field.upper())
    if not 1 <= number <= len(entries):
        raise ValueError("Pika nuk ekziston më; rifresko detyrën.")
    point = entries[number - 1][0]
    return {"field": field, "number": number, "key": point.key, "text": point.text}


def snapshot_context(task: dict, target: dict) -> dict:
    return {**{key: task.get(key) for key in ("id", "title", "description", "user_comment")}, "target": target}


def serialize_run(run) -> dict:
    def date(value):
        return value.isoformat() if value else None
    return {"id": str(run.id), "task_id": str(run.task_id) if run.task_id else None,
        "parent_run_id": str(run.parent_run_id) if run.parent_run_id else None,
        "mode": run.mode, "model": run.model, "instruction": run.instruction,
        "target": run.target, "fingerprint": run.fingerprint[:16], "status": run.status,
        "result_text": run.result_text, "sources": run.sources or [], "error": run.error,
        "accepted_at": date(run.accepted_at), "created_at": date(run.created_at),
        "started_at": date(run.started_at), "finished_at": date(run.finished_at)}

