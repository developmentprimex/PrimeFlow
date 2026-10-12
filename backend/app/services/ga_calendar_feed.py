"""Apple Calendar (ICS) feed for the GA time table.

GA subscribes to the feed once on the iPhone (Settings > Calendar > Accounts >
Add Subscribed Calendar). Each typed time table entry becomes a weekly event
with an alarm at the row start, so the phone shows a native reminder that GA
can close.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings
from app.models.ga_time_slot_template import GaTimeSlotTemplate
from app.models.meeting import Meeting
from app.services.meeting_occurrence import meeting_occurs_on_date
from app.services.microsoft_calendar_sync import is_common_view_visible_meeting

FEED_TIMEZONE = "Europe/Tirane"
FEED_NAME = "PrimeFlow GA Time Table"
_FEED_TZ = ZoneInfo(FEED_TIMEZONE)
_DEFAULT_MEETING_DURATION = timedelta(minutes=30)

_ICS_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

# Central European Time rules, so iOS does not have to guess the zone.
_VTIMEZONE = [
    "BEGIN:VTIMEZONE",
    f"TZID:{FEED_TIMEZONE}",
    "BEGIN:DAYLIGHT",
    "TZOFFSETFROM:+0100",
    "TZOFFSETTO:+0200",
    "TZNAME:CEST",
    "DTSTART:19700329T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
    "END:DAYLIGHT",
    "BEGIN:STANDARD",
    "TZOFFSETFROM:+0200",
    "TZOFFSETTO:+0100",
    "TZNAME:CET",
    "DTSTART:19701025T030000",
    "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU",
    "END:STANDARD",
    "END:VTIMEZONE",
]


def feed_token(user_id: uuid.UUID) -> str:
    message = f"ga-calendar-feed:{user_id}".encode()
    return hmac.new(settings.JWT_SECRET.encode(), message, hashlib.sha256).hexdigest()[:40]


def is_valid_feed_token(token: str, user_id: uuid.UUID) -> bool:
    return hmac.compare_digest(token, feed_token(user_id))


def _plain_text(value: str) -> str:
    text = re.sub(r"<\s*br\s*/?>|</\s*(div|p|li)\s*>", "\n", value or "", flags=re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    # RFC 5545: lines longer than 75 octets continue on the next line after a space.
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    parts: list[str] = []
    current = ""
    limit = 75
    for char in line:
        if len((current + char).encode("utf-8")) > limit:
            parts.append(current)
            current = char
            limit = 74
        else:
            current += char
    parts.append(current)
    return "\r\n ".join(parts)


def _utc_stamp(value: datetime | None) -> str:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _first_occurrence(entry: GaTimeSlotTemplate) -> date:
    # Start the weekly series on the entry's weekday in the week it was created.
    created = (entry.created_at or datetime.now(timezone.utc)).date()
    week_start = created - timedelta(days=created.weekday())
    return week_start + timedelta(days=entry.day_of_week)


def is_ga_time_table_meeting(meeting: Meeting) -> bool:
    # Same rule as the time table: manual TAK INT only. Linked internal meetings
    # follow their TAK EXT, which already reaches the phone through Outlook.
    return (
        str(meeting.meeting_type or "").lower() == "internal"
        and meeting.paired_external_meeting_id is None
        and meeting.pre_external_meeting_id is None
        and meeting.starts_at is not None
        and is_common_view_visible_meeting(meeting)
    )


def _meeting_rrule(meeting: Meeting, local_start: datetime) -> tuple[str | None, bool]:
    """Return the RRULE (if any) and whether the meeting can be exported."""
    recurrence = str(meeting.recurrence_type or "").lower()
    if recurrence == "weekly":
        days = sorted({day for day in (meeting.recurrence_days_of_week or []) if 0 <= day <= 6})
        return (f"RRULE:FREQ=WEEKLY;BYDAY={','.join(_ICS_DAYS[day] for day in days)}", True) if days else (None, False)
    if recurrence == "monthly":
        days = sorted({day for day in (meeting.recurrence_days_of_month or []) if 1 <= day <= 31})
        return (f"RRULE:FREQ=MONTHLY;BYMONTHDAY={','.join(map(str, days))}", True) if days else (None, False)
    if recurrence == "yearly":
        days = [day for day in (meeting.recurrence_days_of_month or []) if 1 <= day <= 31]
        if not days:
            return None, False
        return f"RRULE:FREQ=YEARLY;BYMONTH={local_start.month};BYMONTHDAY={days[0]}", True
    return None, True


def _meeting_first_day(meeting: Meeting, local_start: datetime, has_rrule: bool) -> date | None:
    # DTSTART has to be a real occurrence, otherwise iOS adds a stray first event.
    start_day = local_start.date()
    if not has_rrule:
        return start_day
    for offset in range(366 * 4 + 1):
        day = start_day + timedelta(days=offset)
        if meeting_occurs_on_date(meeting, day, local_timezone=_FEED_TZ):
            return day
    return None


def _meeting_event_lines(meeting: Meeting) -> list[str]:
    starts_at = meeting.starts_at
    local_start = starts_at.astimezone(_FEED_TZ) if starts_at.tzinfo is not None else starts_at
    rrule, exportable = _meeting_rrule(meeting, local_start)
    if not exportable:
        return []
    first_day = _meeting_first_day(meeting, local_start, rrule is not None)
    if first_day is None:
        return []
    duration = (meeting.ends_at - starts_at) if meeting.ends_at else timedelta(0)
    if not timedelta(0) < duration < timedelta(days=1):
        duration = _DEFAULT_MEETING_DURATION
    start = datetime.combine(first_day, local_start.time().replace(microsecond=0))
    title = f"TAK INT: {(meeting.title or 'Internal meeting').strip()}"
    minutes_before = meeting.reminder_minutes_before or 0
    lines = [
        "BEGIN:VEVENT",
        f"UID:ga-meeting-{meeting.id}@primeflow.primexeu.com",
        f"DTSTAMP:{_utc_stamp(meeting.updated_at)}",
        f"LAST-MODIFIED:{_utc_stamp(meeting.updated_at)}",
        f"DTSTART;TZID={FEED_TIMEZONE}:{start.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND;TZID={FEED_TIMEZONE}:{(start + duration).strftime('%Y%m%dT%H%M%S')}",
    ]
    if rrule:
        lines.append(rrule)
    lines.append(f"SUMMARY:{_escape(title)}")
    if meeting.platform:
        lines.append(f"LOCATION:{_escape(meeting.platform.strip())}")
    if meeting.meeting_url:
        lines.append(f"URL:{meeting.meeting_url.strip()}")
    lines += [
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_escape(title)}",
        f"TRIGGER:-PT{minutes_before}M" if minutes_before > 0 else "TRIGGER:PT0M",
        "END:VALARM",
        "END:VEVENT",
    ]
    return lines


def build_ga_calendar(entries: list[GaTimeSlotTemplate], meetings: list[Meeting] | None = None) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//PrimeFlow//GA Time Table//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{FEED_NAME}",
        f"X-WR-TIMEZONE:{FEED_TIMEZONE}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT15M",
        "X-PUBLISHED-TTL:PT15M",
        *_VTIMEZONE,
    ]
    for entry in entries:
        summary = _plain_text(entry.content)
        if not summary or not 0 <= entry.day_of_week <= 6:
            continue
        title = summary.splitlines()[0]
        start_day = _first_occurrence(entry)
        end_time = entry.end_time if entry.end_time > entry.start_time else entry.start_time
        start = datetime.combine(start_day, entry.start_time).strftime("%Y%m%dT%H%M%S")
        end = datetime.combine(start_day, end_time).strftime("%Y%m%dT%H%M%S")
        lines += [
            "BEGIN:VEVENT",
            f"UID:ga-time-slot-{entry.id}@primeflow.primexeu.com",
            f"DTSTAMP:{_utc_stamp(entry.updated_at)}",
            f"LAST-MODIFIED:{_utc_stamp(entry.updated_at)}",
            f"DTSTART;TZID={FEED_TIMEZONE}:{start}",
            f"DTEND;TZID={FEED_TIMEZONE}:{end}",
            f"RRULE:FREQ=WEEKLY;BYDAY={_ICS_DAYS[entry.day_of_week]}",
            f"SUMMARY:{_escape(title)}",
            f"DESCRIPTION:{_escape(summary)}",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_escape(title)}",
            "TRIGGER:PT0M",
            "END:VALARM",
            "END:VEVENT",
        ]
    for meeting in meetings or []:
        if is_ga_time_table_meeting(meeting):
            lines += _meeting_event_lines(meeting)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
