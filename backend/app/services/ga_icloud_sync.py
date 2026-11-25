from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TOKEN_PREFIX = "pfga"
PENDING_COMPLETE = "pending_complete"
UNTIMED_START = time(0, 0)
UNTIMED_END = time(0, 1)


@dataclass(frozen=True)
class TimeRow:
    start: time
    end: time


@dataclass(frozen=True)
class PreparedSyncItem:
    day_date: date
    start_time: time
    end_time: time
    content: str
    source_type: str
    source_external_id: str
    source_name: str
    is_completed: bool = False
    reminder_source: dict[str, str | None] | None = None


def generate_connection_token(connection_id: uuid.UUID) -> tuple[str, str]:
    secret = secrets.token_urlsafe(32)
    token = f"{TOKEN_PREFIX}_{connection_id.hex}.{secret}"
    return token, hash_connection_token(token)


def hash_connection_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def connection_id_from_token(token: str) -> uuid.UUID | None:
    try:
        prefix_and_id, _secret = token.split(".", 1)
        prefix, raw_id = prefix_and_id.split("_", 1)
        if prefix != TOKEN_PREFIX:
            return None
        return uuid.UUID(hex=raw_id)
    except (ValueError, AttributeError):
        return None


def resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {name}") from exc


def localize(value: datetime, zone: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=zone)
    return value.astimezone(zone)


def clean_text(value: str, *, limit: int) -> str:
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", value or "")
    return re.sub(r"\s+", " ", cleaned).strip()[:limit]


def source_key(*parts: object) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def resolve_row(value: time, rows: list[TimeRow]) -> TimeRow | None:
    normal_rows = sorted((row for row in rows if row.start >= time(0, 2)), key=lambda row: row.start)
    if not normal_rows:
        return None
    for row in normal_rows:
        if row.start <= value < row.end:
            return row
    return normal_rows[0] if value < normal_rows[0].start else normal_rows[-1]


def format_clock(value: datetime) -> str:
    return value.strftime("%H:%M")


def prepare_calendar_item(
    *,
    external_id: str | None,
    title: str,
    starts_at: datetime,
    ends_at: datetime | None,
    is_all_day: bool,
    calendar_name: str,
    location: str | None,
    zone: ZoneInfo,
    rows: list[TimeRow],
) -> PreparedSyncItem:
    local_start = localize(starts_at, zone)
    local_end = localize(ends_at, zone) if ends_at else local_start + timedelta(minutes=30)
    safe_title = clean_text(title, limit=600) or "Untitled event"
    safe_location = clean_text(location or "", limit=200)
    stable_id = source_key(external_id, safe_title, local_start.isoformat(), local_end.isoformat())
    if is_all_day:
        content = f"CALENDAR: {safe_title}"
        start_value, end_value = UNTIMED_START, UNTIMED_END
    else:
        if local_end <= local_start:
            local_end = local_start + timedelta(minutes=30)
        window = f"{format_clock(local_start)}–{format_clock(local_end)}"
        content = f"CALENDAR {window}: {safe_title}"
        row = resolve_row(local_start.timetz().replace(tzinfo=None), rows)
        start_value = row.start if row else local_start.timetz().replace(tzinfo=None)
        end_value = row.end if row else local_end.timetz().replace(tzinfo=None)
    if safe_location:
        content = f"{content} · {safe_location}"
    return PreparedSyncItem(
        day_date=local_start.date(),
        start_time=start_value,
        end_time=end_value,
        content=content[:8000],
        source_type="calendar",
        source_external_id=stable_id,
        source_name=calendar_name,
    )


def prepare_reminder_item(
    *,
    external_id: str | None,
    title: str,
    due_at: datetime | None,
    due_date: date | None,
    reminder_list_name: str,
    notes: str | None,
    fallback_date: date,
    zone: ZoneInfo,
    rows: list[TimeRow],
    is_completed: bool = False,
    original_due_at: str | None = None,
) -> PreparedSyncItem:
    safe_title = clean_text(title, limit=600) or "Untitled reminder"
    safe_notes = clean_text(notes or "", limit=300)
    if due_at is not None:
        local_due = localize(due_at, zone)
        item_date = local_due.date()
        row = resolve_row(local_due.timetz().replace(tzinfo=None), rows)
        start_value = row.start if row else local_due.timetz().replace(tzinfo=None)
        end_value = row.end if row else (datetime.combine(item_date, start_value) + timedelta(minutes=30)).time()
        content = f"REMINDER {format_clock(local_due)}: {safe_title}"
        due_key = local_due.isoformat()
    else:
        item_date = due_date or fallback_date
        start_value, end_value = UNTIMED_START, UNTIMED_END
        content = f"REMINDER: {safe_title}"
        due_key = due_date.isoformat() if due_date else None
    if safe_notes:
        content = f"{content} · {safe_notes}"
    return PreparedSyncItem(
        day_date=item_date,
        start_time=start_value,
        end_time=end_value,
        content=content[:8000],
        source_type="reminder",
        source_external_id=source_key(external_id, safe_title, due_key),
        source_name=reminder_list_name,
        is_completed=is_completed,
        reminder_source={
            "title": title,
            "due_at": (original_due_at or due_at.isoformat()) if due_at else due_key,
            "id": external_id,
        },
    )
