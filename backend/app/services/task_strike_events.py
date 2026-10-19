from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task_strike_event import TaskStrikeEvent


DONE_BLOCK = re.compile(r"\[\[\s*done\s*\]\](.*?)\[\[\s*/\s*done\s*\]\]", re.IGNORECASE | re.DOTALL)
TECHNICAL_TAGS = re.compile(r"\[\[\s*/?\s*(?:added|done)\s*\]\]", re.IGNORECASE)
# Checklist points can be numbered or use the bullet controls in PX/GA notes.
STRIKE_TIMESTAMP_SUFFIX = re.compile(
    r"\s+(?P<hour>\d{2}):(?P<minute>\d{2})\s+(?P<day>\d{2})\.(?P<month>\d{2})\s*$"
)
CHECKLIST_ITEM = re.compile(r"(?m)^\s*(?:\d+\.\s+|[•*-]\s+)")


@dataclass(frozen=True)
class StrikePoint:
    key: str
    text: str
    legacy_key: str = ""


@dataclass(frozen=True)
class StrikeState:
    action: str
    occurred_at: datetime


def _normalise(value: str) -> str:
    return " ".join(STRIKE_TIMESTAMP_SUFFIX.sub("", value).split())


def split_strike_timestamp(value: str) -> tuple[str, str]:
    """Separate a point's visible completion timestamp from its task text."""

    match = STRIKE_TIMESTAMP_SUFFIX.search(value)
    if match is None:
        return value, ""
    return value[:match.start()].rstrip(), match.group(0).strip()


def strike_timestamp_datetime(value: str, *, report_at: datetime) -> datetime | None:
    """Read the UI's `HH:MM DD.MM` completion timestamp when no event exists."""

    match = STRIKE_TIMESTAMP_SUFFIX.search(value)
    if match is None:
        return None
    try:
        return datetime(
            report_at.year,
            int(match.group("month")),
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
            tzinfo=report_at.tzinfo,
        )
    except ValueError:
        return None


def _strike_colour(occurred_at: datetime | None, *, interval_start: datetime, interval_end: datetime) -> str:
    if occurred_at is None:
        return "grey"
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=interval_end.tzinfo)
    local_occurred_at = occurred_at.astimezone(interval_end.tzinfo)
    if local_occurred_at.date() < interval_end.date():
        return "grey"
    if interval_start < occurred_at <= interval_end:
        return "blue"
    return "green"


def point_key(value: str, *, field_name: str = "DESCRIPTION") -> str:
    # Keep existing description keys stable. New title keys are deliberately
    # separate because a title and description can contain identical text.
    source = _normalise(value).casefold()
    if field_name != "DESCRIPTION":
        source = f"{field_name}|{source}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _point_identity_key(value: str, occurrence: int, *, field_name: str) -> str:
    """Key a point by its content and duplicate occurrence, so bullets differ."""

    source = f"{field_name}|{occurrence}|{_normalise(value).casefold()}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _numbered_points(value: str) -> list[str]:
    cleaned = TECHNICAL_TAGS.sub("", value or "").strip()
    matches = list(CHECKLIST_ITEM.finditer(cleaned))
    if not matches:
        return [cleaned] if cleaned else []
    return [
        cleaned[match.start():matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)].strip()
        for index, match in enumerate(matches)
    ]


def _numbered_point_spans(value: str) -> list[tuple[int, int]]:
    """Return checklist-line ranges using offsets from the original marked text.

    The browser may wrap only the selected part of a numbered line in
    ``[[done]]`` tags.  Replacing tags with spaces preserves its offsets so a
    partial selection can still be associated with its complete checklist item.
    """

    raw = value or ""
    masked = TECHNICAL_TAGS.sub(lambda match: " " * len(match.group(0)), raw)
    matches = list(CHECKLIST_ITEM.finditer(masked))
    return [
        (match.start(), matches[index + 1].start() if index + 1 < len(matches) else len(raw))
        for index, match in enumerate(matches)
    ]


def _point_entries(value: str | None, *, field_name: str) -> list[tuple[StrikePoint, int, int]]:
    """Return point text with offsets so selected lines can be identified."""

    raw = value or ""
    masked = TECHNICAL_TAGS.sub(lambda match: " " * len(match.group(0)), raw)
    checklist_matches = list(CHECKLIST_ITEM.finditer(masked))
    if checklist_matches:
        spans = [
            (match.start(), checklist_matches[index + 1].start() if index + 1 < len(checklist_matches) else len(raw))
            for index, match in enumerate(checklist_matches)
        ]
    else:
        # Plain multiline text has one independently strikable point per line.
        spans = [(match.start(), match.end()) for match in re.finditer(r"(?m)^.*\S.*$", masked)]

    entries: list[tuple[StrikePoint, int, int]] = []
    occurrences: dict[str, int] = {}
    for start, end in spans:
        text = TECHNICAL_TAGS.sub("", raw[start:end]).strip()
        if not text:
            continue
        normalized = _normalise(text).casefold()
        occurrence = occurrences.get(normalized, 0)
        occurrences[normalized] = occurrence + 1
        entries.append((
            StrikePoint(
                _point_identity_key(text, occurrence, field_name=field_name),
                text,
                point_key(text, field_name=field_name),
            ),
            start,
            end,
        ))
    return entries


def _struck_points_by_identity(value: str | None, *, field_name: str) -> dict[str, StrikePoint]:
    """Return currently struck points using the position-aware key."""

    raw = value or ""
    entries = _point_entries(raw, field_name=field_name)
    result: dict[str, StrikePoint] = {}
    for match in DONE_BLOCK.finditer(raw):
        # Only the content inside the markers is struck. Including the closing
        # marker can overlap the following numbered point on the next line.
        done_start, done_end = match.span(1)
        for point, start, end in entries:
            if start < done_end and done_start < end:
                result[point.key] = point
    return result


def struck_points(value: str | None, *, field_name: str = "DESCRIPTION") -> dict[str, StrikePoint]:
    """Return the individual checklist points currently wrapped in [[done]]."""

    raw = value or ""
    result: dict[str, StrikePoint] = {}
    numbered_spans = _numbered_point_spans(raw)
    for match in DONE_BLOCK.finditer(raw):
        done_start, done_end = match.span(1)
        affected_spans = [
            (start, end)
            for start, end in numbered_spans
            if start < done_end and done_start < end
        ]
        # A partial selection still represents the complete numbered line.
        # For non-numbered text, retain the existing selection-level behavior.
        texts = (
            [TECHNICAL_TAGS.sub("", raw[start:end]).strip() for start, end in affected_spans]
            if affected_spans else _numbered_points(match.group(1))
        )
        for text in texts:
            if not text:
                continue
            key = point_key(text, field_name=field_name)
            result[key] = StrikePoint(key, text)
    return result


def record_text_strike_events(
    db: AsyncSession,
    *,
    task_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    before_text: str | None,
    after_text: str | None,
    field_name: str,
) -> None:
    """Queue events only for actual done/un-done transitions in task points."""

    before = _struck_points_by_identity(before_text, field_name=field_name)
    after = _struck_points_by_identity(after_text, field_name=field_name)
    for key in after.keys() - before.keys():
        point = after[key]
        db.add(TaskStrikeEvent(
            task_id=task_id,
            actor_user_id=actor_user_id,
            field_name=field_name,
            point_key=key,
            point_text=point.text,
            action="STRUCK",
        ))
    for key in before.keys() - after.keys():
        point = before[key]
        db.add(TaskStrikeEvent(
            task_id=task_id,
            actor_user_id=actor_user_id,
            field_name=field_name,
            point_key=key,
            point_text=point.text,
            action="UNSTRUCK",
        ))


def record_description_strike_events(
    db: AsyncSession,
    *,
    task_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    before_description: str | None,
    after_description: str | None,
) -> None:
    record_text_strike_events(
        db,
        task_id=task_id,
        actor_user_id=actor_user_id,
        before_text=before_description,
        after_text=after_description,
        field_name="DESCRIPTION",
    )


def record_title_strike_events(
    db: AsyncSession,
    *,
    task_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    before_title: str | None,
    after_title: str | None,
) -> None:
    record_text_strike_events(
        db,
        task_id=task_id,
        actor_user_id=actor_user_id,
        before_text=before_title,
        after_text=after_title,
        field_name="TITLE",
    )


def _text_points(value: str | None, *, field_name: str) -> tuple[str, list[StrikePoint], set[str]]:
    """Split text into report points, keeping numbered headings out of the list."""

    raw = value or ""
    # Use the same tag masking as _point_entries so an empty marked item
    # (e.g. [[added]]1.[[/added]]) cannot hide the heading. Removing tags
    # first changes whether that item matches the checklist pattern.
    masked = TECHNICAL_TAGS.sub(lambda match: " " * len(match.group(0)), raw)
    matches = list(CHECKLIST_ITEM.finditer(masked))
    heading = TECHNICAL_TAGS.sub("", raw[:matches[0].start()]).strip() if matches else ""
    points = [point for point, _start, _end in _point_entries(raw, field_name=field_name)]
    current_done = set(_struck_points_by_identity(raw, field_name=field_name))
    return heading, points, current_done


def count_struck_points_for_interval(
    text: str | None, events: Iterable[TaskStrikeEvent], *,
    interval_start: datetime, interval_end: datetime, field_name: str = "DESCRIPTION",
) -> int:
    """Count the blue points shown by the existing 1H interval renderer."""
    if interval_end <= interval_start:
        return 0
    _, marked = render_text_for_interval(
        text, events, interval_start=interval_start, interval_end=interval_end,
        field_name=field_name,
    )
    return len(re.findall(r"\[\[done:blue\]\]", marked))


def count_struck_points_for_day(
    text: str | None, events: Iterable[TaskStrikeEvent], *, day: date,
    field_name: str = "DESCRIPTION", allow_undated: bool = False,
) -> int:
    """Count distinct struck points for this local day, including legacy notes."""
    from zoneinfo import ZoneInfo
    from app.config import settings

    zone = ZoneInfo(settings.REALIZATION_TIMEZONE)
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day, time.max, tzinfo=zone)
    events = list(events)
    _, marked = render_text_for_interval(text, events, interval_start=start, interval_end=end, field_name=field_name)
    completed = 0
    for match in re.finditer(r"\[\[done:(?:blue|green)\]\](.*?)\[\[/done\]\]([^\n]*)", marked, re.DOTALL):
        timestamp = strike_timestamp_datetime(match.group(1) + match.group(2), report_at=end)
        if timestamp is None or timestamp.date() <= day:
            completed += 1
    if allow_undated:
        # Grey can mean a known previous day or an undated legacy strike.
        # Only the latter may fall back to this task's scheduled day.
        _, points, current_done = _text_points(text, field_name=field_name)
        known = {event.point_key for event in events if getattr(event, "field_name", "DESCRIPTION") == field_name}
        known_texts = {
            _normalise(getattr(event, "point_text", "")).casefold()
            for event in events if getattr(event, "field_name", "DESCRIPTION") == field_name
        }
        for point in points:
            if point.key in current_done and point.key not in known and point.legacy_key not in known:
                full = _normalise(point.text).casefold()
                without_marker = re.sub(r"^(?:\d+\.|[•*-])\s*", "", full)
                if not ({full, without_marker} & known_texts) and strike_timestamp_datetime(point.text, report_at=end) is None:
                    completed += 1
    return completed


def render_text_for_interval(
    text: str | None,
    events: Iterable[TaskStrikeEvent],
    *,
    interval_start: datetime,
    interval_end: datetime,
    field_name: str = "DESCRIPTION",
) -> tuple[str, str]:
    """Return plain and colour-marked text for a 1H report interval.

    Open points are always shown. Current-day strikes from this reporting
    interval are blue; earlier strikes from the same day are green; strikes
    from an earlier day are grey. Reopening a point makes it open immediately.
    """

    latest: dict[str, TaskStrikeEvent] = {}
    relevant_events: list[TaskStrikeEvent] = []
    for event in sorted(events, key=lambda item: (item.occurred_at, str(item.id))):
        event_field = getattr(event, "field_name", "DESCRIPTION")
        if event_field == field_name and event.occurred_at <= interval_end:
            latest[event.point_key] = event
            relevant_events.append(event)

    def event_for_point(point: StrikePoint) -> TaskStrikeEvent | None:
        """Find an event even when an older UI save omitted ``1.`` from it."""

        exact = latest.get(point.key)
        if exact is not None:
            return exact
        # Old events only have a text-based key. One such event cannot identify
        # which of several identical bullets was actually struck.
        if sum(candidate.legacy_key == point.legacy_key for candidate in points) != 1:
            return None
        legacy = latest.get(point.legacy_key)
        if legacy is not None:
            return legacy
        full = _normalise(point.text).casefold()
        without_marker = re.sub(r"^(?:\d+\.|[•*-])\s*", "", full)
        compatible = []
        for event in relevant_events:
            event_text = _normalise(getattr(event, "point_text", "")).casefold()
            if not event_text:
                continue
            if event_text in {full, without_marker}:
                compatible.append(event)
        return compatible[-1] if compatible else None

    heading, points, current_done = _text_points(text, field_name=field_name)
    plain_parts = [heading] if heading else []
    marked_parts = [heading] if heading else []
    for point in points:
        # The current note text is authoritative. Historical events must never
        # re-strike a point that is presently open (including legacy malformed
        # selections that were later repaired).
        if point.key not in current_done:
            plain_parts.append(point.text)
            marked_parts.append(point.text)
            continue
        event = event_for_point(point)
        if event is None:
            strike_text, timestamp = split_strike_timestamp(point.text)
            colour = _strike_colour(
                strike_timestamp_datetime(point.text, report_at=interval_end),
                interval_start=interval_start,
                interval_end=interval_end,
            )
            plain_parts.append(point.text)
            marked_parts.append(
                f"[[done:{colour}]]{strike_text}[[/done]]"
                f"{' ' + timestamp if timestamp else ''}"
            )
            continue
        if event.action == "STRUCK":
            colour = _strike_colour(
                event.occurred_at, interval_start=interval_start, interval_end=interval_end
            )
            strike_text, timestamp = split_strike_timestamp(point.text)
            plain_parts.append(point.text)
            marked_parts.append(
                f"[[done:{colour}]]{strike_text}[[/done]]"
                f"{' ' + timestamp if timestamp else ''}"
            )
            continue
        plain_parts.append(point.text)
        marked_parts.append(point.text)
    return "\n".join(plain_parts), "\n".join(marked_parts)


def render_description_for_interval(
    description: str | None,
    events: Iterable[TaskStrikeEvent],
    *,
    interval_start: datetime,
    interval_end: datetime,
) -> tuple[str, str]:
    """Backward-compatible description-specific wrapper."""

    return render_text_for_interval(
        description,
        events,
        interval_start=interval_start,
        interval_end=interval_end,
        field_name="DESCRIPTION",
    )
