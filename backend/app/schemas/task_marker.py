"""Backward-compatible storage for zero, one or two distinct task symbols."""
from typing import Annotated

from pydantic import AfterValidator

MARKER_CODES = frozenset((
    "EXCLAMATION", "DOUBLE_EXCLAM", "CLIENT_URGENT", "QUESTION", "KA", "GENT",
    "FLAG", "F", "BZ1N1", "M2", "M3", "M2_M3", "MONITOR", "CLOSE", "SHARE",
))


def validate_task_marker(value: str) -> str:
    parts = value.split(",")
    if not 1 <= len(parts) <= 2 or len(set(parts)) != len(parts) or any(part not in MARKER_CODES for part in parts):
        raise ValueError("Select at most two distinct task symbols")
    return value


TaskMarkerValue = Annotated[str, AfterValidator(validate_task_marker)]
