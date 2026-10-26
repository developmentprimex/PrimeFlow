"""M2 uses the report selectors and the same reason codes as My View."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, time
from app.services.daily_rlz_compliance import REASON_LABELS
from app.services.primeflow_report import report_timezone

KINDS = {"unfinished": "Detyrë AM / 08:00 / Deadline e pakryer",
         "postponed": "Pse u shty detyra?", "progress": "Progresi me GA / F / personalisht",
         "delivery": "A e ke dorëzuar për M2?", "continuation": "A vazhdon në PM?"}
MOVEMENTS = {"start_due": "Shtyrë Start dhe Due Date", "start": "Shtyrë vetëm Start Date", "due": "Shtyrë vetëm Due Date"}


def collection_open(now: datetime) -> bool:
    local = now.astimezone(report_timezone())
    return local.weekday() < 5 and time(11, 45) <= local.time().replace(tzinfo=None) < time(12)


def context_key(kind: str, row: dict) -> str:
    # Dates bind a reply to the actual postponement, not a later move.
    fields = ("task_id", "postponement_kind", "old_start_date", "old_due_date", "start_date", "due_date", "last_move_at") if kind == "postponed" else ("task_id",)
    return hashlib.sha256(json.dumps([kind, *[row.get(field) for field in fields]], default=str).encode()).hexdigest()


def question_rows(data: dict) -> list[tuple[str, dict]]:
    seen, result = set(), []
    for section, kind in (("unfinished_priority", "unfinished"), ("postponed", "postponed"),
                          ("postponed_am", "postponed"), ("ga_progress", "progress"), ("delivery", "delivery"),
                          ("pm_continuation", "continuation")):
        for row in data.get(section, []):
            if not row.get("task_id") or (kind != "delivery" and row.get("status") == "DONE"):
                continue
            key = context_key(kind, row)
            if key in seen:
                continue
            # An explanation already recorded on the actual date-change event
            # needs no second request, irrespective of who made that change.
            if kind == "postponed" and row.get("postponement_explanation") and row.get("comment") not in {None, "", "-", "—"}:
                continue
            seen.add(key)
            result.append((kind, row))
    return result


def validate_answer(kind: str, reason: str | None, comment: str | None, choice: str | None):
    reason, comment = (reason or "").strip(), (comment or "").strip()
    if kind in {"delivery", "continuation"}:
        if choice not in {"PO", "JO"}:
            raise ValueError("Zgjidh PO ose JO.")
        if choice == "JO" and not comment:
            raise ValueError("Shëno pse nuk vazhdon në PM." if kind == 'continuation' else "Shëno pse nuk është dorëzuar detyra.")
    elif reason not in REASON_LABELS or not comment:
        raise ValueError("Zgjidh arsyen nga lista dhe plotëso komentin.")
    return (None if kind in {'delivery', 'continuation'} else reason or None), comment, choice if kind in {"delivery", "continuation"} else None
