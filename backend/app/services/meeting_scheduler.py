from __future__ import annotations

import re
import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.meeting import Meeting, MeetingParticipant
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.models.common_entry import CommonEntry
from app.models.enums import CommonCategory
from app.models.meeting_schedule_request import (
    MeetingScheduleRequest,
    MeetingScheduleRequestParticipant,
    MeetingSchedulingStandard,
)
from app.models.project import Project
from app.models.user import User
from app.services.microsoft_calendar_sync import is_annual_leave_title_or_categories
from app.services.common_leave import parse_common_view_annual_leave
from app.schemas.meeting_scheduler import (
    MeetingScheduleConflict,
    MeetingScheduleRequestBase,
    MeetingScheduleSuggestion,
    MeetingScheduleValidationOut,
)


ACTIVE_REQUEST_STATUSES = {"PENDING_APPROVAL", "APPROVED", "CREATING_TEAMS", "CREATION_FAILED"}
FINAL_REQUEST_STATUSES = {"CREATED", "REJECTED", "CANCELED"}
DEFAULT_EXISTING_MEETING_DURATION = timedelta(minutes=60)
ONE_H_SLOT_DURATION = timedelta(minutes=15)
ONE_H_VALID_SLOTS = {"10:00", "11:00", "11:50", "14:20", "16:00"}


def _blocks_meeting_schedule(meeting: Meeting) -> bool:
    """PV/leave entries stay visible on the calendar but never reserve a meeting slot."""
    if str(getattr(meeting, "calendar_sync_status", None) or "").strip().lower() in {
        "cancelled",
        "excluded",
        "out_of_window",
    }:
        return False
    return not is_annual_leave_title_or_categories(
        getattr(meeting, "title", None),
        getattr(meeting, "calendar_categories", None),
    )


def _app_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.APP_TIMEZONE)
    except Exception:
        return ZoneInfo("UTC")


def _overlaps(left_start: datetime, left_end: datetime, right_start: datetime, right_end: datetime) -> bool:
    return left_start < right_end and right_start < left_end


async def one_h_schedule_conflicts(
    db: AsyncSession,
    *,
    participant_ids: set[uuid.UUID],
    starts_at: datetime,
    ends_at: datetime,
) -> tuple[list[MeetingScheduleConflict], list[tuple[datetime, datetime]]]:
    """Return the global 15-minute 1H windows for the local meeting day."""
    tz = _app_timezone()
    target_date = starts_at.astimezone(tz).date()
    conflicts: list[MeetingScheduleConflict] = []
    all_windows: list[tuple[datetime, datetime]] = []
    for slot in sorted(ONE_H_VALID_SLOTS):
        hour, minute = (int(part) for part in slot.split(":"))
        local_start = datetime.combine(target_date, time(hour, minute), tzinfo=tz)
        window_start = local_start.astimezone(timezone.utc)
        window_end = window_start + ONE_H_SLOT_DURATION
        all_windows.append((window_start, window_end))
        if not _overlaps(starts_at, ends_at, window_start, window_end):
            continue
        conflicts.append(
            MeetingScheduleConflict(
                source="one_h",
                title="Orari 1H",
                starts_at=window_start,
                ends_at=window_end,
                participant_ids=[],
            )
        )
    return conflicts, all_windows


def suggest_first_free_slot(
    *,
    starts_at: datetime,
    ends_at: datetime,
    one_h_conflicts: list[MeetingScheduleConflict],
    blockers: list[tuple[datetime, datetime]],
    workday_end: str = "17:00",
) -> MeetingScheduleSuggestion | None:
    if not one_h_conflicts:
        return None
    duration = ends_at - starts_at
    candidate_start = max(conflict.ends_at for conflict in one_h_conflicts)
    tz = _app_timezone()
    local_day = candidate_start.astimezone(tz).date()
    end_hour, end_minute = (int(part) for part in workday_end.split(":"))
    local_limit = datetime.combine(local_day, time(end_hour, end_minute), tzinfo=tz)
    limit = local_limit.astimezone(timezone.utc)
    while candidate_start + duration <= limit:
        candidate_end = candidate_start + duration
        if not any(_overlaps(candidate_start, candidate_end, block_start, block_end) for block_start, block_end in blockers):
            return MeetingScheduleSuggestion(starts_at=candidate_start, ends_at=candidate_end)
        candidate_start += timedelta(minutes=15)
    return None


async def common_availability_blockers(
    db: AsyncSession,
    *,
    participant_ids: set[uuid.UUID],
    target_date,
) -> list[tuple[datetime, datetime]]:
    """Return absence/leave/holiday windows already represented in Common View."""
    rows = (
        await db.execute(
            select(CommonEntry).where(
                CommonEntry.category.in_([
                    CommonCategory.delays,
                    CommonCategory.absences,
                    CommonCategory.annual_leave,
                    CommonCategory.external_holiday,
                ]),
                or_(
                    CommonEntry.category == CommonCategory.external_holiday,
                    CommonEntry.assigned_to_user_id.in_(participant_ids),
                    CommonEntry.created_by_user_id.in_(participant_ids),
                    CommonEntry.description.ilike("%[ALL_USERS]%"),
                ),
            )
        )
    ).scalars().all()
    tz = _app_timezone()

    def window(from_value: str, to_value: str) -> tuple[datetime, datetime]:
        start_hour, start_minute = (int(part) for part in from_value.split(":"))
        end_hour, end_minute = (int(part) for part in to_value.split(":"))
        start = datetime.combine(target_date, time(start_hour, start_minute), tzinfo=tz).astimezone(timezone.utc)
        end = datetime.combine(target_date, time(end_hour, end_minute), tzinfo=tz).astimezone(timezone.utc)
        return start, end

    result: list[tuple[datetime, datetime]] = []
    for entry in rows:
        if entry.category == CommonCategory.external_holiday:
            if (entry.entry_date or entry.created_at.date()) == target_date:
                result.append(window("00:00", "23:59"))
            continue
        if entry.category == CommonCategory.annual_leave:
            start_date, end_date, full_day, start_time, end_time, _, _ = parse_common_view_annual_leave(entry)
            if start_date <= target_date <= end_date:
                result.append(window("00:00", "23:59") if full_day else window(start_time or "00:00", end_time or "23:59"))
            continue
        entry_date = entry.entry_date or entry.created_at.date()
        date_match = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", entry.description or "", re.I)
        if date_match:
            try:
                entry_date = datetime.fromisoformat(date_match.group(1)).date()
            except ValueError:
                pass
        if entry_date != target_date:
            continue
        details = entry.description or ""
        if entry.category == CommonCategory.absences:
            match = re.search(r"From:\s*(\d{1,2}:\d{2})\s*-\s*To:\s*(\d{1,2}:\d{2})", details, re.I)
            result.append(window(match.group(1), match.group(2)) if match else window("08:00", "23:00"))
        elif entry.category == CommonCategory.delays:
            start_match = re.search(r"Start:\s*(\d{1,2}:\d{2})", details, re.I)
            until_match = re.search(r"Until:\s*(\d{1,2}:\d{2})", details, re.I)
            result.append(window(start_match.group(1) if start_match else "08:00", until_match.group(1) if until_match else "09:00"))
    return result


def meeting_occurrence_window(meeting: Meeting, target: datetime) -> tuple[datetime, datetime] | None:
    if meeting.starts_at is None:
        return None
    tz = _app_timezone()
    target_local = target.astimezone(tz)
    source_local = meeting.starts_at.astimezone(tz)
    recurrence = (meeting.recurrence_type or "").strip().lower()
    occurs = False
    if recurrence == "weekly":
        occurs = bool(meeting.recurrence_days_of_week and target_local.weekday() in meeting.recurrence_days_of_week)
    elif recurrence == "monthly":
        occurs = bool(meeting.recurrence_days_of_month and target_local.day in meeting.recurrence_days_of_month)
    elif recurrence == "yearly":
        occurs = target_local.month == source_local.month and target_local.day == source_local.day
    else:
        occurs = target_local.date() == source_local.date()
    if not occurs:
        return None
    start_local = datetime.combine(target_local.date(), source_local.timetz(), tzinfo=tz)
    start = start_local.astimezone(timezone.utc)
    default_duration = timedelta(minutes=30) if getattr(meeting, "meeting_type", None) == "internal" else DEFAULT_EXISTING_MEETING_DURATION
    duration = (
        meeting.ends_at - meeting.starts_at
        if meeting.ends_at is not None and meeting.ends_at > meeting.starts_at
        else default_duration
    )
    return start, start + duration


async def validate_meeting_schedule(
    db: AsyncSession,
    payload: MeetingScheduleRequestBase,
    *,
    exclude_request_id: uuid.UUID | None = None,
) -> MeetingScheduleValidationOut:
    errors: list[str] = []
    warnings: list[str] = []
    conflicts: list[MeetingScheduleConflict] = []
    now = datetime.now(timezone.utc)
    starts_at = payload.starts_at.astimezone(timezone.utc)
    ends_at = payload.ends_at.astimezone(timezone.utc)

    users = (await db.execute(select(User).where(User.id.in_(payload.participant_ids)))).scalars().all()
    valid_user_ids = {user.id for user in users if user.is_active}
    missing_users = set(payload.participant_ids) - valid_user_ids
    if missing_users:
        errors.append("Një ose më shumë pjesëmarrës nuk ekzistojnë ose nuk janë aktivë.")

    if payload.project_id is not None:
        project = (await db.execute(select(Project).where(Project.id == payload.project_id))).scalar_one_or_none()
        if project is None:
            errors.append("Projekti i zgjedhur nuk ekziston.")
        elif project.department_id != payload.department_id:
            errors.append("Projekti duhet t'i përkasë departamentit të zgjedhur.")

    standard = None
    if payload.standard_id is not None:
        standard = (
            await db.execute(
                select(MeetingSchedulingStandard).where(
                    MeetingSchedulingStandard.id == payload.standard_id,
                    MeetingSchedulingStandard.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if standard is None:
            errors.append("Standardi i zgjedhur nuk ekziston ose nuk është aktiv.")
        elif standard.meeting_type != payload.meeting_type:
            errors.append("Standardi nuk përputhet me llojin e takimit.")

    if standard is not None:
        tz = _app_timezone()
        local_start = starts_at.astimezone(tz)
        local_end = ends_at.astimezone(tz)
        allowed_start = time.fromisoformat(standard.workday_start)
        allowed_end = time.fromisoformat(standard.workday_end)
        if local_start.weekday() > 4:
            errors.append("Takimi nuk mund të planifikohet në fundjavë.")
        if local_start.time().replace(tzinfo=None) < allowed_start or local_end.time().replace(tzinfo=None) > allowed_end:
            errors.append(f"Takimi duhet të jetë brenda orarit {standard.workday_start}–{standard.workday_end}.")
        duration = int((ends_at - starts_at).total_seconds() // 60)
        if duration != standard.default_duration_minutes:
            warnings.append(
                f"Standardi rekomandon {standard.default_duration_minutes} minuta; u zgjodhën {duration} minuta."
            )

    buffer_minutes = int(getattr(standard, "buffer_minutes", 0) or 0)
    conflict_window_start = starts_at - timedelta(minutes=buffer_minutes)
    conflict_window_end = ends_at + timedelta(minutes=buffer_minutes)

    if starts_at < now:
        errors.append("Takimi nuk mund të planifikohet në të kaluarën.")

    participant_ids = set(payload.participant_ids)
    one_h_conflicts, one_h_windows = await one_h_schedule_conflicts(
        db,
        participant_ids=participant_ids,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    conflicts.extend(one_h_conflicts)

    local_day = starts_at.astimezone(_app_timezone()).date()
    local_day_start = datetime.combine(local_day, time.min, tzinfo=_app_timezone()).astimezone(timezone.utc)
    local_day_end = (datetime.combine(local_day, time.min, tzinfo=_app_timezone()) + timedelta(days=1)).astimezone(timezone.utc)
    check_all_meetings = payload.meeting_type == "internal" and getattr(payload, "check_all_meetings", False)
    meeting_stmt = select(Meeting, MeetingParticipant.user_id).where(Meeting.starts_at.is_not(None))
    if check_all_meetings:
        # Manual TAK INT checks the shared calendar, including other users
        # and meetings that have no manually assigned participants.
        meeting_stmt = meeting_stmt.outerjoin(MeetingParticipant, MeetingParticipant.meeting_id == Meeting.id)
        meeting_stmt = meeting_stmt.where(~select(MeetingOccurrenceStatus.id).where(
            MeetingOccurrenceStatus.meeting_id == Meeting.id,
            MeetingOccurrenceStatus.occurrence_date == local_day,
            MeetingOccurrenceStatus.status == "canceled",
        ).exists())
    else:
        meeting_stmt = meeting_stmt.join(MeetingParticipant, MeetingParticipant.meeting_id == Meeting.id).where(
            MeetingParticipant.user_id.in_(participant_ids),
            MeetingParticipant.assignment_source == "manual",
        )
    meeting_rows = (await db.execute(meeting_stmt)).all()
    meeting_participants: dict[uuid.UUID, set[uuid.UUID]] = {}
    meetings: dict[uuid.UUID, Meeting] = {}
    for meeting, participant_id in meeting_rows:
        if not _blocks_meeting_schedule(meeting):
            continue
        meetings[meeting.id] = meeting
        if participant_id is not None:
            meeting_participants.setdefault(meeting.id, set()).add(participant_id)

    # A single shared organizer cannot host overlapping TAK EXT meetings.
    # Check every TAK EXT, regardless of whether participants overlap.
    if payload.meeting_type == "external":
        external_meetings = (
            await db.execute(
                select(Meeting).where(
                    Meeting.meeting_type == "external",
                    Meeting.starts_at.is_not(None),
                    or_(
                        Meeting.calendar_sync_status.is_(None),
                        Meeting.calendar_sync_status != "cancelled",
                    ),
                )
            )
        ).scalars().all()
        for external_meeting in external_meetings:
            if not _blocks_meeting_schedule(external_meeting):
                continue
            meetings.setdefault(external_meeting.id, external_meeting)

    for meeting_id, meeting in meetings.items():
        window = meeting_occurrence_window(meeting, starts_at)
        if window and _overlaps(conflict_window_start, conflict_window_end, *window):
            source = "primeflow"
            if check_all_meetings:
                source = "tak_ext" if meeting.meeting_type == "external" else "tak_int"
            elif payload.meeting_type == "external" and meeting.meeting_type == "external":
                source = "tak_ext"
            conflicts.append(
                MeetingScheduleConflict(
                    source=source,
                    title=meeting.title,
                    starts_at=window[0],
                    ends_at=window[1],
                    participant_ids=sorted(meeting_participants.get(meeting_id, set()), key=str),
                )
            )

    request_stmt = (
        select(MeetingScheduleRequest, MeetingScheduleRequestParticipant.user_id)
        .join(
            MeetingScheduleRequestParticipant,
            MeetingScheduleRequestParticipant.request_id == MeetingScheduleRequest.id,
        )
        .where(MeetingScheduleRequestParticipant.user_id.in_(participant_ids))
        .where(MeetingScheduleRequest.status.in_(ACTIVE_REQUEST_STATUSES))
        .where(
            MeetingScheduleRequest.starts_at < local_day_end,
            MeetingScheduleRequest.ends_at > local_day_start,
        )
    )
    if exclude_request_id is not None:
        request_stmt = request_stmt.where(MeetingScheduleRequest.id != exclude_request_id)
    request_rows = (await db.execute(request_stmt)).all()
    request_participants: dict[uuid.UUID, set[uuid.UUID]] = {}
    requests: dict[uuid.UUID, MeetingScheduleRequest] = {}
    for request_row, participant_id in request_rows:
        requests[request_row.id] = request_row
        request_participants.setdefault(request_row.id, set()).add(participant_id)

    # Pending TAK EXT requests also reserve their interval. Otherwise two
    # requests with different participants could both reach approval.
    if payload.meeting_type == "external":
        external_request_stmt = (
            select(MeetingScheduleRequest)
            .where(MeetingScheduleRequest.meeting_type == "external")
            .where(MeetingScheduleRequest.status.in_(ACTIVE_REQUEST_STATUSES))
            .where(
                MeetingScheduleRequest.starts_at < local_day_end,
                MeetingScheduleRequest.ends_at > local_day_start,
            )
        )
        if exclude_request_id is not None:
            external_request_stmt = external_request_stmt.where(
                MeetingScheduleRequest.id != exclude_request_id
            )
        external_requests = (await db.execute(external_request_stmt)).scalars().all()
        for external_request in external_requests:
            requests.setdefault(external_request.id, external_request)

    for request_id, request_row in requests.items():
        if not _overlaps(
            conflict_window_start,
            conflict_window_end,
            request_row.starts_at,
            request_row.ends_at,
        ):
            continue
        conflicts.append(
            MeetingScheduleConflict(
                source=(
                    "tak_ext_request"
                    if payload.meeting_type == "external" and request_row.meeting_type == "external"
                    else "request"
                ),
                title=request_row.title,
                starts_at=request_row.starts_at,
                ends_at=request_row.ends_at,
                participant_ids=sorted(request_participants.get(request_id, set()), key=str),
            )
        )

    blockers = list(one_h_windows)
    for meeting in meetings.values():
        window = meeting_occurrence_window(meeting, starts_at)
        if window is not None:
            blockers.append(window)
    blockers.extend((row.starts_at, row.ends_at) for row in requests.values())
    if one_h_conflicts:
        blockers.extend(
            await common_availability_blockers(
                db,
                participant_ids=participant_ids,
                target_date=local_day,
            )
        )
    suggested_slot = suggest_first_free_slot(
        starts_at=starts_at,
        ends_at=ends_at,
        one_h_conflicts=one_h_conflicts,
        blockers=list(dict.fromkeys(blockers)),
        workday_end=standard.workday_end if standard is not None else "17:00",
    )

    external_conflict = next(
        (conflict for conflict in conflicts if conflict.source in {"tak_ext", "tak_ext_request"}),
        None,
    )
    if external_conflict is not None and payload.meeting_type == "external":
        conflict_start = external_conflict.starts_at.astimezone(_app_timezone()).strftime("%d.%m.%Y %H:%M")
        conflict_end = external_conflict.ends_at.astimezone(_app_timezone()).strftime("%H:%M")
        errors.append(
            f'Nuk mund të krijohet TAK EXT. Intervali konflikton me "{external_conflict.title}" '
            f'({conflict_start}–{conflict_end}).'
        )
    elif one_h_conflicts:
        errors.append("Ky orar përputhet me 1H.")
    elif check_all_meetings and conflicts:
        errors.append("Në këtë interval ka TAK INT ose TAK EXT në kalendar.")
    elif conflicts:
        errors.append("Një ose më shumë pjesëmarrës janë të zënë në këtë orar.")

    return MeetingScheduleValidationOut(
        can_create=not errors,
        errors=errors,
        warnings=warnings,
        conflicts=conflicts,
        suggested_slot=suggested_slot,
        checked_at=now,
    )


def microsoft_schedule_conflicts(
    schedule_rows: list[dict],
    *,
    starts_at: datetime,
    ends_at: datetime,
) -> list[MeetingScheduleConflict]:
    result: list[MeetingScheduleConflict] = []
    seen: set[tuple[str, str, datetime, datetime]] = set()
    for schedule in schedule_rows:
        email = str(schedule.get("scheduleId") or "Microsoft calendar")
        for item in schedule.get("scheduleItems") or []:
            status = str(item.get("status") or "").lower()
            if status in {"free", "unknown"}:
                continue
            if is_annual_leave_title_or_categories(
                item.get("subject"), item.get("categories")
            ):
                continue
            try:
                item_start = datetime.fromisoformat(str(item["start"]["dateTime"]).replace("Z", "+00:00"))
                item_end = datetime.fromisoformat(str(item["end"]["dateTime"]).replace("Z", "+00:00"))
                if item_start.tzinfo is None:
                    item_start = item_start.replace(tzinfo=timezone.utc)
                if item_end.tzinfo is None:
                    item_end = item_end.replace(tzinfo=timezone.utc)
            except (KeyError, TypeError, ValueError):
                continue
            if _overlaps(starts_at, ends_at, item_start, item_end):
                conflict_key = (email.casefold(), status, item_start, item_end)
                if conflict_key in seen:
                    continue
                seen.add(conflict_key)
                result.append(
                    MeetingScheduleConflict(
                        source="microsoft",
                        title=f"{email} — {status}",
                        starts_at=item_start,
                        ends_at=item_end,
                    )
                )
    return result
