from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def can_confirm_realization_task(user) -> bool:
    # Account identities, never a general ADMIN/MANAGER permission.
    return bool(getattr(user, "is_active", True)) and (
        (getattr(user, "username", None) or "").strip().casefold() in {"laurent.hoxha", "laurent", "diellza.veliu"}
        or (getattr(user, "full_name", None) or "").strip().casefold() in {"laurent hoxha", "diellza veliu"}
    )


def task_confirmation_evidence(row: Mapping) -> str:
    """A changed deadline/status/progress needs a new confirmation."""
    evidence = {key: row.get(key) for key in (
        "classification", "current_status", "current_due_date", "in_original_plan",
        "progress_today", "completed_delta", "deadline_was_today", "deadline_critical",
        "reason_code", "comment", "quantity", "daily_share", "baseline_due_date",
    )}
    evidence["events"] = [item["id"] for item in row.get("timeline", []) if not item["type"].startswith("POSTPONEMENT_")]
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()
