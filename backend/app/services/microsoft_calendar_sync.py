from __future__ import annotations

import asyncio
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
import httpx

from app.integrations.microsoft import (
    compute_expires_at,
    fetch_calendar_events,
    fetch_user_profile,
    microsoft_account_email,
    refresh_access_token,
)
from app.models.department import Department
from app.models.meeting import Meeting, MeetingParticipant
from app.models.microsoft_token import MicrosoftToken
from app.models.user import User
from app.services.meeting_cancellation import external_meeting_is_canceled


_sync_lock = asyncio.Lock()
CALENDAR_PREPARATION_DELAY = timedelta(hours=2)
CALENDAR_PREPARATION_INTERVAL = timedelta(minutes=15)
SAME_DAY_PREPARATION_FIRST_TIME = time(8, 15)
ADVANCE_PREPARATION_FIRST_TIME = time(8, 15)
EARLY_EXTERNAL_MEETING_TIME = time(8, 0)
PREVIOUS_WORKDAY_PREPARATION_TIME = time(16, 0)
WORKDAY_END_TIME = time(16, 30)
BREAK_START_TIME = time(12, 0)
BREAK_END_TIME = time(13, 15)
ONE_H_SLOT_TIMES = (
    time(9, 0),
    time(10, 0),
    time(11, 0),
    time(11, 50),
    time(14, 20),
    time(15, 50),
)
ONE_H_PROTECTED_TIMES = frozenset((slot.hour, slot.minute) for slot in ONE_H_SLOT_TIMES)
ROUTINE_EXTERNAL_CATEGORY_MARKERS = ("daily", "weekly", "standup", "brown")


@dataclass(frozen=True)
class MicrosoftCalendarSyncResult:
    fetched: int
    created: int
    updated: int
    cancelled: int
    skipped: int


def microsoft_calendar_sync_window(now: datetime) -> tuple[datetime, datetime]:
    """Return Monday-Friday for this week and the configured following weeks."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    try:
        app_timezone = ZoneInfo(settings.APP_TIMEZONE)
    except Exception:
        app_timezone = timezone.utc
    local_now = now.astimezone(app_timezone)
    current_monday = (local_now - timedelta(days=local_now.weekday())).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    following_weeks = max((settings.MS_CALENDAR_SYNC_FUTURE_DAYS + 6) // 7, 0)
    end_after_last_friday = current_monday + timedelta(days=5 + following_weeks * 7)
    return current_monday.astimezone(timezone.utc), end_after_last_friday.astimezone(timezone.utc)


def meeting_overlaps_sync_window(
    starts_at: datetime | None,
    ends_at: datetime | None,
    window_start: datetime,
    window_end: datetime,
) -> bool:
    """Return whether a meeting occupies any time inside the sync window."""
    if starts_at is None:
        return False
    if ends_at is not None and ends_at > starts_at:
        return starts_at < window_end and ends_at > window_start
    return window_start <= starts_at < window_end


async def get_shared_calendar_token(
    db: AsyncSession,
    *,
    redirect_uri: str,
) -> MicrosoftToken | None:
    rows = (
        await db.execute(
            select(MicrosoftToken).order_by(MicrosoftToken.updated_at.desc(), MicrosoftToken.created_at.desc())
        )
    ).scalars().all()
    expected_email = settings.MS_ORGANIZER_EMAIL.strip().casefold()
    refreshed = False
    for row in rows:
        try:
            if row.expires_at <= datetime.now(timezone.utc) + timedelta(seconds=30):
                token_data = await refresh_access_token(row.refresh_token, redirect_uri)
                row.access_token = token_data["access_token"]
                if token_data.get("refresh_token"):
                    row.refresh_token = token_data["refresh_token"]
                row.scope = token_data.get("scope")
                row.expires_at = compute_expires_at(int(token_data.get("expires_in", 3600)))
                refreshed = True
            profile = await fetch_user_profile(row.access_token)
        except httpx.HTTPError:
            continue
        if microsoft_account_email(profile) == expected_email:
            if refreshed:
                await db.commit()
            return row
    if refreshed:
        await db.commit()
    return None


def parse_graph_datetime(value: Any) -> datetime | None:
    raw = value.get("dateTime") if isinstance(value, dict) else value
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def graph_attendee_emails(event: dict[str, Any], organizer_email: str) -> list[str]:
    organizer_key = organizer_email.strip().casefold()
    result: list[str] = []
    seen: set[str] = set()
    for attendee in event.get("attendees") or []:
        address = str((attendee.get("emailAddress") or {}).get("address") or "").strip()
        key = address.casefold()
        if not key or key == organizer_key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def graph_meeting_url(event: dict[str, Any]) -> str | None:
    online = event.get("onlineMeeting") or {}
    return online.get("joinUrl") or event.get("onlineMeetingUrl") or event.get("webLink")


def graph_platform(event: dict[str, Any]) -> str:
    if event.get("isOnlineMeeting") or (event.get("onlineMeeting") or {}).get("joinUrl"):
        return "TEAMS"
    location = str((event.get("location") or {}).get("displayName") or "").strip()
    return location or "OUTLOOK"


def graph_event_categories(event: dict[str, Any]) -> list[str]:
    return [
        str(category).strip()
        for category in (event.get("categories") or [])
        if str(category).strip()
    ]


def is_annual_leave_title_or_categories(title: str | None, categories: list[str] | None) -> bool:
    normalized_categories = {
        str(category).strip().casefold()
        for category in (categories or [])
        if str(category).strip()
    }
    if "pv" in normalized_categories:
        return True
    return re.search(r"(?<![A-Z0-9])PV(?![A-Z0-9])", str(title or ""), flags=re.IGNORECASE) is not None


def is_common_view_visible_meeting(meeting: Meeting) -> bool:
    """Keep report/export meeting visibility identical to Common View."""
    if str(getattr(meeting, "calendar_sync_status", None) or "").strip().lower() in {
        "cancelled",
        "excluded",
        "out_of_window",
    }:
        return False
    is_calendar_meeting = bool(
        getattr(meeting, "calendar_imported", False)
        or getattr(meeting, "microsoft_event_id", None)
    )
    if is_calendar_meeting and is_annual_leave_title_or_categories(
        getattr(meeting, "title", None),
        getattr(meeting, "calendar_categories", None),
    ):
        return False
    return True


def is_annual_leave_event(event: dict[str, Any]) -> bool:
    categories = graph_event_categories(event)
    return is_annual_leave_title_or_categories(event.get("subject"), categories)


def is_routine_external_meeting(
    categories: list[str] | None,
    recurrence_type: str | None = None,
) -> bool:
    """Match TAK EXT meetings rendered with the brown Common View tone."""
    normalized_categories = [
        str(category).strip().casefold()
        for category in (categories or [])
        if str(category).strip()
    ]
    if any(
        marker in category
        for category in normalized_categories
        for marker in ROUTINE_EXTERNAL_CATEGORY_MARKERS
    ):
        return True
    return str(recurrence_type or "").strip().casefold() in {"daily", "weekly"}


def choose_department_id(
    participants: list[User],
    departments: list[Department],
) -> Any | None:
    counts = Counter(user.department_id for user in participants if user.department_id is not None)
    if counts:
        return sorted(counts.items(), key=lambda item: (-item[1], str(item[0])))[0][0]
    default_code = settings.MS_CALENDAR_DEFAULT_DEPARTMENT_CODE.strip().casefold()
    default = next((department for department in departments if department.code.casefold() == default_code), None)
    return default.id if default is not None else (departments[0].id if departments else None)


def sync_calendar_internal_pair_fields(
    internal_meeting: Meeting,
    external_meeting: Meeting,
    *,
    starts_at: datetime,
    synced_at: datetime,
) -> None:
    """Keep the PrimeFlow-only TAK INT aligned with its Microsoft TAK EXT."""
    internal_meeting.title = external_meeting.title
    internal_meeting.platform = external_meeting.platform
    internal_meeting.starts_at = starts_at
    internal_meeting.ends_at = None
    internal_meeting.meeting_url = external_meeting.meeting_url
    internal_meeting.meeting_type = "internal"
    internal_meeting.recurrence_type = external_meeting.recurrence_type
    internal_meeting.recurrence_days_of_week = external_meeting.recurrence_days_of_week
    internal_meeting.recurrence_days_of_month = external_meeting.recurrence_days_of_month
    internal_meeting.department_id = external_meeting.department_id
    internal_meeting.project_id = external_meeting.project_id
    internal_meeting.calendar_imported = False
    internal_meeting.calendar_sync_status = external_meeting.calendar_sync_status
    internal_meeting.calendar_last_synced_at = synced_at


def _next_working_day(day: datetime) -> datetime:
    candidate = day + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _previous_working_day(day: datetime) -> datetime:
    candidate = day - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def calendar_follow_up_start(
    external_starts_at: datetime,
    external_ends_at: datetime | None,
) -> datetime:
    """Return the next official 1H slot after a Microsoft TAK EXT finishes."""
    try:
        app_timezone = ZoneInfo(settings.APP_TIMEZONE)
    except Exception:
        app_timezone = timezone.utc

    reference = external_ends_at or external_starts_at
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference_local = reference.astimezone(app_timezone)
    for slot in ONE_H_SLOT_TIMES:
        candidate = reference_local.replace(
            hour=slot.hour,
            minute=slot.minute,
            second=0,
            microsecond=0,
        )
        if candidate >= reference_local:
            return candidate.astimezone(timezone.utc)

    next_day = _next_working_day(reference_local)
    return next_day.replace(
        hour=ONE_H_SLOT_TIMES[0].hour,
        minute=ONE_H_SLOT_TIMES[0].minute,
        second=0,
        microsecond=0,
    ).astimezone(timezone.utc)


def calendar_preparation_start(
    external_starts_at: datetime,
    event_created_at: datetime,
    *,
    reserved_starts: set[datetime] | None = None,
) -> datetime:
    """Schedule the TAK INT before a Microsoft TAK EXT in the app timezone."""
    try:
        app_timezone = ZoneInfo(settings.APP_TIMEZONE)
    except Exception:
        app_timezone = timezone.utc

    if external_starts_at.tzinfo is None:
        external_starts_at = external_starts_at.replace(tzinfo=timezone.utc)
    if event_created_at.tzinfo is None:
        event_created_at = event_created_at.replace(tzinfo=timezone.utc)
    external_local = external_starts_at.astimezone(app_timezone)
    created_local = event_created_at.astimezone(app_timezone)
    if external_local.time().replace(tzinfo=None) == EARLY_EXTERNAL_MEETING_TIME:
        previous_workday = _previous_working_day(external_local)
        candidate = previous_workday.replace(
            hour=PREVIOUS_WORKDAY_PREPARATION_TIME.hour,
            minute=PREVIOUS_WORKDAY_PREPARATION_TIME.minute,
            second=0,
            microsecond=0,
        )
        if created_local > candidate:
            candidate = external_local.replace(second=0, microsecond=0)
        # Multiple TAK EXT meetings at 08:00 intentionally share the same TAK
        # INT preparation slot instead of pushing one another past 08:00.
        return candidate.astimezone(timezone.utc)
    elif created_local.date() == external_local.date():
        earliest = external_local.replace(
            hour=SAME_DAY_PREPARATION_FIRST_TIME.hour,
            minute=SAME_DAY_PREPARATION_FIRST_TIME.minute,
            second=0,
            microsecond=0,
        )
        candidate = max(external_local - CALENDAR_PREPARATION_DELAY, earliest)
    else:
        candidate = _previous_working_day(external_local).replace(
            hour=ADVANCE_PREPARATION_FIRST_TIME.hour,
            minute=ADVANCE_PREPARATION_FIRST_TIME.minute,
            second=0,
            microsecond=0,
        )

    # A late-created event must not schedule preparation in the past. Keep
    # the existing 15-minute allocation, starting strictly after creation.
    if candidate <= created_local:
        candidate = created_local.replace(second=0, microsecond=0)
        candidate += timedelta(minutes=15 - candidate.minute % 15)

    reserved = reserved_starts or set()
    while True:
        if candidate.weekday() >= 5:
            candidate = _next_working_day(candidate).replace(
                hour=SAME_DAY_PREPARATION_FIRST_TIME.hour,
                minute=SAME_DAY_PREPARATION_FIRST_TIME.minute,
                second=0,
                microsecond=0,
            )
            continue
        candidate_time = candidate.time().replace(tzinfo=None)
        if BREAK_START_TIME <= candidate_time < BREAK_END_TIME:
            candidate = candidate.replace(
                hour=BREAK_END_TIME.hour,
                minute=BREAK_END_TIME.minute,
                second=0,
                microsecond=0,
            )
            continue
        if candidate_time > WORKDAY_END_TIME:
            candidate = _next_working_day(candidate).replace(
                hour=SAME_DAY_PREPARATION_FIRST_TIME.hour,
                minute=SAME_DAY_PREPARATION_FIRST_TIME.minute,
                second=0,
                microsecond=0,
            )
            continue
        candidate_utc = candidate.astimezone(timezone.utc)
        touches_one_h_slot = (candidate.hour, candidate.minute) in ONE_H_PROTECTED_TIMES
        overlaps_preparation = any(
            abs(candidate_utc - reserved_start) < CALENDAR_PREPARATION_INTERVAL
            for reserved_start in reserved
        )
        if not touches_one_h_slot and not overlaps_preparation:
            return candidate_utc
        candidate += CALENDAR_PREPARATION_INTERVAL


async def ensure_calendar_internal_pair(
    db: AsyncSession,
    *,
    external_meeting: Meeting,
    participant_ids: set[Any],
    paired_by_external_id: dict[Any, Meeting],
    participant_ids_by_meeting: dict[Any, set[Any]],
    synced_at: datetime,
) -> Meeting:
    """Create or update the single TAK INT paired with a Microsoft event."""
    internal_meeting = paired_by_external_id.get(external_meeting.id)
    if internal_meeting is None:
        internal_meeting = Meeting(
            title=external_meeting.title,
            meeting_type="internal",
            department_id=external_meeting.department_id,
            paired_external_meeting_id=external_meeting.id,
            created_by=external_meeting.created_by,
        )
        db.add(internal_meeting)
        await db.flush()
        paired_by_external_id[external_meeting.id] = internal_meeting
        participant_ids_by_meeting[internal_meeting.id] = set()

    sync_calendar_internal_pair_fields(
        internal_meeting,
        external_meeting,
        starts_at=calendar_follow_up_start(
            external_meeting.starts_at,
            external_meeting.ends_at,
        ),
        synced_at=synced_at,
    )
    existing_participant_ids = participant_ids_by_meeting.setdefault(internal_meeting.id, set())
    for user_id in participant_ids:
        if user_id in existing_participant_ids:
            continue
        db.add(MeetingParticipant(
            meeting_id=internal_meeting.id,
            user_id=user_id,
            assignment_source="manual",
            assigned_by_user_id=external_meeting.created_by,
        ))
        existing_participant_ids.add(user_id)
    return internal_meeting


async def ensure_calendar_preparation_pair(
    db: AsyncSession,
    *,
    external_meeting: Meeting,
    starts_at: datetime,
    participant_ids: set[Any],
    paired_by_external_id: dict[Any, Meeting],
    participant_ids_by_meeting: dict[Any, set[Any]],
    synced_at: datetime,
) -> Meeting:
    """Create or update the TAK INT held before a Microsoft TAK EXT."""
    internal_meeting = paired_by_external_id.get(external_meeting.id)
    if internal_meeting is None:
        internal_meeting = Meeting(
            title=external_meeting.title,
            meeting_type="internal",
            department_id=external_meeting.department_id,
            pre_external_meeting_id=external_meeting.id,
            created_by=external_meeting.created_by,
        )
        db.add(internal_meeting)
        await db.flush()
        paired_by_external_id[external_meeting.id] = internal_meeting
        participant_ids_by_meeting[internal_meeting.id] = set()

    sync_calendar_internal_pair_fields(
        internal_meeting,
        external_meeting,
        starts_at=starts_at,
        synced_at=synced_at,
    )
    existing_participant_ids = participant_ids_by_meeting.setdefault(internal_meeting.id, set())
    for user_id in participant_ids:
        if user_id in existing_participant_ids:
            continue
        db.add(MeetingParticipant(
            meeting_id=internal_meeting.id,
            user_id=user_id,
            assignment_source="manual",
            assigned_by_user_id=external_meeting.created_by,
        ))
        existing_participant_ids.add(user_id)
    return internal_meeting


def sync_calendar_internal_pair_status(
    external_meeting: Meeting,
    paired_by_external_id: dict[Any, Meeting],
    *,
    synced_at: datetime,
) -> None:
    internal_meeting = paired_by_external_id.get(external_meeting.id)
    if internal_meeting is None:
        return
    internal_meeting.calendar_sync_status = external_meeting.calendar_sync_status
    internal_meeting.calendar_last_synced_at = synced_at


async def delete_calendar_internal_pair(
    db: AsyncSession,
    external_meeting: Meeting,
    paired_by_external_id: dict[Any, Meeting],
) -> None:
    """Delete an automatic TAK INT when its TAK EXT is routine/brown."""
    internal_meeting = paired_by_external_id.pop(external_meeting.id, None)
    if internal_meeting is None:
        return
    await db.delete(internal_meeting)


async def sync_external_calendar_events(
    db: AsyncSession,
    *,
    access_token: str,
    connected_by_user_id: Any,
    start: datetime,
    end: datetime,
) -> MicrosoftCalendarSyncResult:
    async with _sync_lock:
        events = await fetch_calendar_events(access_token, start, end)
        events.sort(
            key=lambda event: parse_graph_datetime(event.get("start"))
            or datetime.max.replace(tzinfo=timezone.utc)
        )
        users = list((await db.execute(select(User).where(User.is_active.is_(True)))).scalars().all())
        departments = list((await db.execute(select(Department).order_by(Department.name))).scalars().all())
        users_by_email = {user.email.strip().casefold(): user for user in users if user.email}

        existing_rows = list(
            (
                await db.execute(
                    select(Meeting).where(Meeting.microsoft_event_id.is_not(None))
                )
            ).scalars().all()
        )
        existing_by_event_id = {
            str(row.microsoft_event_id): row for row in existing_rows if row.microsoft_event_id
        }
        if existing_rows:
            existing_pairs = list(
                (
                    await db.execute(
                        select(Meeting).where(
                            Meeting.paired_external_meeting_id.in_([row.id for row in existing_rows])
                        )
                    )
                ).scalars().all()
            )
            existing_preparation_pairs = list(
                (
                    await db.execute(
                        select(Meeting).where(
                            Meeting.pre_external_meeting_id.in_([row.id for row in existing_rows])
                        )
                    )
                ).scalars().all()
            )
        else:
            existing_pairs = []
            existing_preparation_pairs = []
        paired_by_external_id = {
            row.paired_external_meeting_id: row
            for row in existing_pairs
            if row.paired_external_meeting_id is not None
        }
        preparation_by_external_id = {
            row.pre_external_meeting_id: row
            for row in existing_preparation_pairs
            if row.pre_external_meeting_id is not None
        }
        existing_participant_ids_by_meeting: dict[Any, set[Any]] = {}
        participant_meetings = [*existing_rows, *existing_pairs, *existing_preparation_pairs]
        if participant_meetings:
            participant_rows = list(
                (
                    await db.execute(
                        select(MeetingParticipant).where(
                            MeetingParticipant.meeting_id.in_([row.id for row in participant_meetings]),
                            MeetingParticipant.assignment_source == "manual",
                        )
                    )
                ).scalars().all()
            )
            for participant_row in participant_rows:
                existing_participant_ids_by_meeting.setdefault(
                    participant_row.meeting_id, set()
                ).add(participant_row.user_id)
        seen_event_ids: set[str] = set()
        unchanged_meeting_ids: list[Any] = []
        reserved_preparation_starts: set[datetime] = set()
        now = datetime.now(timezone.utc)
        created = updated = cancelled = skipped = 0

        for event in events:
            event_id = str(event.get("id") or "").strip()
            if not event_id:
                skipped += 1
                continue
            seen_event_ids.add(event_id)
            row = existing_by_event_id.get(event_id)
            categories = graph_event_categories(event)
            if is_annual_leave_event(event):
                if row is not None:
                    row.calendar_imported = True
                    row.calendar_sync_status = "excluded"
                    row.calendar_categories = categories
                    row.calendar_change_key = event.get("changeKey")
                    row.calendar_last_synced_at = now
                    sync_calendar_internal_pair_status(
                        row,
                        paired_by_external_id,
                        synced_at=now,
                    )
                    sync_calendar_internal_pair_status(
                        row,
                        preparation_by_external_id,
                        synced_at=now,
                    )
                skipped += 1
                continue
            if event.get("isCancelled"):
                if row is not None:
                    was_cancelled = row.calendar_sync_status == "cancelled"
                    row.calendar_imported = True
                    row.calendar_sync_status = "cancelled"
                    row.calendar_last_synced_at = now
                    sync_calendar_internal_pair_status(
                        row,
                        paired_by_external_id,
                        synced_at=now,
                    )
                    sync_calendar_internal_pair_status(
                        row,
                        preparation_by_external_id,
                        synced_at=now,
                    )
                    if not was_cancelled:
                        cancelled += 1
                continue

            starts_at = parse_graph_datetime(event.get("start"))
            ends_at = parse_graph_datetime(event.get("end"))
            if starts_at is None:
                skipped += 1
                continue

            attendee_emails = graph_attendee_emails(event, settings.MS_ORGANIZER_EMAIL)
            participants = [users_by_email[email] for email in attendee_emails if email in users_by_email]
            mapped_department_id = choose_department_id(participants, departments)
            change_key = event.get("changeKey")
            unchanged = (
                row is not None
                and row.calendar_imported
                and row.calendar_sync_status == "active"
                and change_key
                and row.calendar_change_key == change_key
                and (row.calendar_categories or []) == categories
            )
            if unchanged:
                unchanged_meeting_ids.append(row.id)
            elif row is None:
                if mapped_department_id is None:
                    skipped += 1
                    continue
                row = Meeting(
                    title=str(event.get("subject") or "External meeting")[:200],
                    platform=graph_platform(event),
                    starts_at=starts_at,
                    ends_at=ends_at,
                    meeting_url=graph_meeting_url(event),
                    microsoft_event_id=event_id,
                    meeting_type="external",
                    department_id=mapped_department_id,
                    created_by=connected_by_user_id,
                    calendar_imported=True,
                    calendar_sync_status="active",
                    calendar_change_key=change_key,
                    calendar_categories=categories,
                    calendar_last_synced_at=now,
                )
                db.add(row)
                await db.flush()
                existing_by_event_id[event_id] = row
                created += 1
            else:
                was_calendar_imported = bool(row.calendar_imported)
                row.title = str(event.get("subject") or "External meeting")[:200]
                row.platform = graph_platform(event)
                row.starts_at = starts_at
                row.ends_at = ends_at
                row.meeting_url = graph_meeting_url(event)
                row.meeting_type = "external"
                row.calendar_imported = True
                row.calendar_sync_status = "active"
                row.calendar_change_key = change_key
                row.calendar_categories = categories
                row.calendar_last_synced_at = now
                if was_calendar_imported and mapped_department_id is not None:
                    row.department_id = mapped_department_id
                updated += 1

            # Outlook attendees are deliberately not PrimeFlow participants.
            # This set contains only users assigned manually in PrimeFlow and is
            # preserved across subsequent calendar syncs.
            existing_participant_ids = existing_participant_ids_by_meeting.setdefault(row.id, set())

            if await external_meeting_is_canceled(db, row):
                continue

            await ensure_calendar_internal_pair(
                db,
                external_meeting=row,
                participant_ids=existing_participant_ids,
                paired_by_external_id=paired_by_external_id,
                participant_ids_by_meeting=existing_participant_ids_by_meeting,
                synced_at=now,
            )

            if is_routine_external_meeting(categories, row.recurrence_type):
                await delete_calendar_internal_pair(
                    db,
                    row,
                    preparation_by_external_id,
                )
            else:
                event_created_at = (
                    parse_graph_datetime(event.get("createdDateTime"))
                    or getattr(row, "created_at", None)
                    or now
                )
                preparation_starts_at = calendar_preparation_start(
                    row.starts_at,
                    event_created_at,
                    reserved_starts=reserved_preparation_starts,
                )
                reserved_preparation_starts.add(preparation_starts_at)
                await ensure_calendar_preparation_pair(
                    db,
                    external_meeting=row,
                    starts_at=preparation_starts_at,
                    participant_ids=existing_participant_ids,
                    paired_by_external_id=preparation_by_external_id,
                    participant_ids_by_meeting=existing_participant_ids_by_meeting,
                    synced_at=now,
                )

        if unchanged_meeting_ids:
            await db.execute(
                update(Meeting)
                .where(Meeting.id.in_(unchanged_meeting_ids))
                .values(calendar_last_synced_at=now)
            )

        for row in existing_rows:
            if not row.calendar_imported or not row.microsoft_event_id or row.calendar_sync_status == "cancelled":
                continue
            if not meeting_overlaps_sync_window(row.starts_at, row.ends_at, start, end):
                row.calendar_sync_status = "out_of_window"
                row.calendar_last_synced_at = now
                sync_calendar_internal_pair_status(
                    row,
                    paired_by_external_id,
                    synced_at=now,
                )
                sync_calendar_internal_pair_status(
                    row,
                    preparation_by_external_id,
                    synced_at=now,
                )
                continue
            if str(row.microsoft_event_id) not in seen_event_ids:
                row.calendar_sync_status = "cancelled"
                row.calendar_last_synced_at = now
                sync_calendar_internal_pair_status(
                    row,
                    paired_by_external_id,
                    synced_at=now,
                )
                sync_calendar_internal_pair_status(
                    row,
                    preparation_by_external_id,
                    synced_at=now,
                )
                cancelled += 1

        await db.commit()
        return MicrosoftCalendarSyncResult(
            fetched=len(events),
            created=created,
            updated=updated,
            cancelled=cancelled,
            skipped=skipped,
        )
