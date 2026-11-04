import re
from datetime import tzinfo
from typing import Any


def calendar_meeting_time_range(meeting: Any, local_timezone: tzinfo) -> str | None:
    """Return the calendar's planned window without inventing a missing end."""
    if getattr(meeting, "meeting_type", None) != "external" or not (
        getattr(meeting, "calendar_imported", False) or getattr(meeting, "microsoft_event_id", None)
    ):
        return None
    start = getattr(meeting, "starts_at", None)
    end = getattr(meeting, "ends_at", None)
    if start is None or end is None:
        return None
    start = start.astimezone(local_timezone) if start.tzinfo else start.replace(tzinfo=local_timezone)
    end = end.astimezone(local_timezone) if end.tzinfo else end.replace(tzinfo=local_timezone)
    if end.timestamp() <= start.timestamp():
        return None
    return f"{start:%H:%M} - {end:%H:%M}"


def meeting_time_columns(value: Any) -> tuple[str, str]:
    clean = re.sub(r"\s*\(\+\d+d\)", "", str(value or "")).strip()
    parts = re.split(r"\s*[-–—]\s*", clean, maxsplit=1)
    return parts[0] or "-", (parts[1] or "-") if len(parts) > 1 else "-"
