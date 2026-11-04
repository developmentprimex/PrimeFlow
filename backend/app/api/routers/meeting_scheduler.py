from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from html import escape

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_department_access, ensure_manager_or_admin
from app.api.deps import get_current_user
from app.api.routers.microsoft import resolve_redirect_uri
from app.config import settings
from app.db import get_db
from app.integrations.microsoft import (
    create_calendar_event,
    fetch_calendar_schedule,
)
from app.models.meeting import Meeting, MeetingParticipant
from app.models.enums import NotificationType, UserRole
from app.models.meeting_schedule_request import (
    MeetingScheduleApproval,
    MeetingScheduleRequest,
    MeetingScheduleRequestParticipant,
    MeetingSchedulingStandard,
)
from app.models.user import User
from app.schemas.meeting_scheduler import (
    MeetingScheduleApprovalOut,
    MeetingScheduleCalendarItem,
    MeetingScheduleRequestCreate,
    MeetingScheduleRequestOut,
    MeetingScheduleRejectIn,
    MeetingScheduleValidationIn,
    MeetingScheduleValidationOut,
    MeetingSchedulingStandardCreate,
    MeetingSchedulingStandardOut,
)
from app.services.meeting_scheduler import meeting_occurrence_window, microsoft_schedule_conflicts, validate_meeting_schedule
from app.services.microsoft_calendar_sync import get_shared_calendar_token
from app.services.notifications import add_notification, publish_notification


router = APIRouter()
APPROVALS_REQUIRED = 2


def _role_value(user) -> str:
    role = getattr(user, "role", None)
    return str(getattr(role, "value", role) or "")


async def _participant_ids(db: AsyncSession, request_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        (await db.execute(
            select(MeetingScheduleRequestParticipant.user_id)
            .where(MeetingScheduleRequestParticipant.request_id == request_id)
            .order_by(MeetingScheduleRequestParticipant.created_at)
        )).scalars().all()
    )


async def _request_out(db: AsyncSession, row: MeetingScheduleRequest) -> MeetingScheduleRequestOut:
    participant_ids = await _participant_ids(db, row.id)
    approval_rows = (
        await db.execute(
            select(MeetingScheduleApproval, User).where(User.work_staff_filter())
            .join(User, MeetingScheduleApproval.approved_by_user_id == User.id)
            .where(MeetingScheduleApproval.request_id == row.id)
            .order_by(MeetingScheduleApproval.created_at)
        )
    ).all()
    validation = None
    if row.validation_snapshot:
        try:
            validation = MeetingScheduleValidationOut.model_validate(row.validation_snapshot)
        except Exception:
            validation = None
    return MeetingScheduleRequestOut(
        id=row.id,
        title=row.title,
        meeting_type=row.meeting_type,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        platform=row.platform,
        client_name=row.client_name,
        client_email=row.client_email,
        notes=row.notes,
        department_id=row.department_id,
        project_id=row.project_id,
        standard_id=row.standard_id,
        participant_ids=participant_ids,
        is_training=bool(getattr(row, "is_training", False)),
        status=row.status,
        approval_count=len(approval_rows),
        approvals=[
            MeetingScheduleApprovalOut(
                user_id=approval.approved_by_user_id,
                user_name=approver.full_name or approver.username or approver.email,
                approved_at=approval.created_at,
            )
            for approval, approver in approval_rows
        ],
        validation=validation,
        microsoft_event_id=row.microsoft_event_id,
        teams_url=row.teams_url,
        final_meeting_id=row.final_meeting_id,
        last_error=row.last_error,
        rejection_reason=row.rejection_reason,
        rejected_by_user_id=row.rejected_by_user_id,
        rejected_at=row.rejected_at,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _with_microsoft_validation(
    db: AsyncSession,
    *,
    payload: MeetingScheduleValidationIn | MeetingScheduleRequestCreate,
    request: Request,
    validation: MeetingScheduleValidationOut,
) -> MeetingScheduleValidationOut:
    try:
        token = await get_shared_calendar_token(db, redirect_uri=resolve_redirect_uri(request))
    except httpx.HTTPError:
        token = None
    if token is None:
        if payload.meeting_type == "external":
            return validation.model_copy(
                update={
                    "can_create": False,
                    "errors": [
                        *validation.errors,
                        "Kalendari qendror Microsoft nuk është lidhur. TAK EXT nuk mund të dërgohet për aprovim.",
                    ],
                }
            )
        return validation.model_copy(
            update={
                "warnings": [
                    *validation.warnings,
                    "Kalendari qendror Microsoft nuk është lidhur; free/busy nuk u kontrollua.",
                ]
            }
        )
    emails = list(
        (await db.execute(select(User.email).where(User.work_staff_filter()).where(User.id.in_(payload.participant_ids)))).scalars().all()
    )
    if payload.meeting_type == "external":
        emails.append(settings.MS_ORGANIZER_EMAIL)
    emails = list(dict.fromkeys(email.strip().casefold() for email in emails if email and email.strip()))
    buffer_minutes = 0
    if payload.standard_id is not None:
        standard = (
            await db.execute(
                select(MeetingSchedulingStandard).where(MeetingSchedulingStandard.id == payload.standard_id)
            )
        ).scalar_one_or_none()
        buffer_minutes = int(getattr(standard, "buffer_minutes", 0) or 0)
    checked_start = payload.starts_at - timedelta(minutes=buffer_minutes)
    checked_end = payload.ends_at + timedelta(minutes=buffer_minutes)
    try:
        schedule = await fetch_calendar_schedule(token.access_token, emails, checked_start, checked_end)
        microsoft_conflicts = microsoft_schedule_conflicts(
            schedule, starts_at=checked_start, ends_at=checked_end
        )
    except httpx.HTTPError:
        if payload.meeting_type == "external":
            return validation.model_copy(
                update={
                    "can_create": False,
                    "errors": [
                        *validation.errors,
                        "Microsoft Calendar nuk është i disponueshëm. TAK EXT nuk mund të dërgohet për aprovim.",
                    ],
                }
            )
        return validation.model_copy(
            update={"warnings": [*validation.warnings, "Microsoft free/busy nuk mundi të kontrollohej."]}
        )
    if not microsoft_conflicts:
        return validation
    return validation.model_copy(
        update={
            "can_create": False,
            "errors": [*validation.errors, "Intervali është i zënë në Microsoft Calendar."],
            "conflicts": [*validation.conflicts, *microsoft_conflicts],
        }
    )


@router.get("/standards", response_model=list[MeetingSchedulingStandardOut])
async def list_standards(
    meeting_type: str | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[MeetingSchedulingStandardOut]:
    stmt = select(MeetingSchedulingStandard).where(MeetingSchedulingStandard.is_active.is_(True))
    if meeting_type:
        stmt = stmt.where(MeetingSchedulingStandard.meeting_type == meeting_type)
    rows = (await db.execute(stmt.order_by(MeetingSchedulingStandard.meeting_type, MeetingSchedulingStandard.name))).scalars().all()
    return [MeetingSchedulingStandardOut.model_validate(row) for row in rows]


@router.post("/standards", response_model=MeetingSchedulingStandardOut, status_code=status.HTTP_201_CREATED)
async def create_standard(
    payload: MeetingSchedulingStandardCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MeetingSchedulingStandardOut:
    ensure_manager_or_admin(user)
    if payload.workday_start >= payload.workday_end:
        raise HTTPException(status_code=400, detail="Workday end must be after its start")
    row = MeetingSchedulingStandard(**payload.model_dump(), created_by_user_id=user.id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return MeetingSchedulingStandardOut.model_validate(row)


@router.post("/validate", response_model=MeetingScheduleValidationOut)
async def validate_slot(
    payload: MeetingScheduleValidationIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MeetingScheduleValidationOut:
    ensure_department_access(user, payload.department_id)
    validation = await validate_meeting_schedule(
        db, payload, exclude_request_id=payload.exclude_request_id
    )
    return await _with_microsoft_validation(
        db,
        payload=payload,
        request=request,
        validation=validation,
    )


@router.post("/requests", response_model=MeetingScheduleRequestOut, status_code=status.HTTP_201_CREATED)
async def create_request(
    payload: MeetingScheduleRequestCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MeetingScheduleRequestOut:
    ensure_department_access(user, payload.department_id)
    validation = await validate_meeting_schedule(db, payload)
    validation = await _with_microsoft_validation(
        db, payload=payload, request=request, validation=validation
    )
    if not validation.can_create:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=validation.model_dump(mode="json"))
    values = payload.model_dump(exclude={"participant_ids"})
    row = MeetingScheduleRequest(
        **values,
        status="PENDING_APPROVAL",
        validation_snapshot=validation.model_dump(mode="json"),
        created_by_user_id=user.id,
    )
    db.add(row)
    await db.flush()
    for participant_id in dict.fromkeys(payload.participant_ids):
        db.add(MeetingScheduleRequestParticipant(request_id=row.id, user_id=participant_id))
    approvers = list(
        (
            await db.execute(
                select(User).where(User.work_staff_filter()).where(
                    User.is_active.is_(True),
                    User.role.in_([UserRole.ADMIN, UserRole.MANAGER]),
                    User.id != user.id,
                )
            )
        ).scalars().all()
    )
    notifications = [
        add_notification(
            db=db,
            user_id=approver.id,
            type=NotificationType.assignment,
            title="Meeting request waiting for approval",
            body=f'{user.full_name or user.username or user.email} requested "{row.title}".',
            data={"href": "/meeting-scheduler", "meeting_request_id": str(row.id)},
        )
        for approver in approvers
    ]
    await db.commit()
    await db.refresh(row)
    for approver, notification in zip(approvers, notifications):
        await publish_notification(user_id=approver.id, notification=notification)
    return await _request_out(db, row)


@router.get("/requests", response_model=list[MeetingScheduleRequestOut])
async def list_requests(
    start: datetime | None = None,
    end: datetime | None = None,
    department_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[MeetingScheduleRequestOut]:
    stmt = select(MeetingScheduleRequest)
    if department_id is not None:
        ensure_department_access(user, department_id)
        stmt = stmt.where(MeetingScheduleRequest.department_id == department_id)
    elif _role_value(user) == "STAFF":
        stmt = stmt.where(MeetingScheduleRequest.department_id == user.department_id)
    if start is not None:
        stmt = stmt.where(MeetingScheduleRequest.ends_at > start)
    if end is not None:
        stmt = stmt.where(MeetingScheduleRequest.starts_at < end)
    rows = (await db.execute(stmt.order_by(MeetingScheduleRequest.starts_at))).scalars().all()
    return [await _request_out(db, row) for row in rows]


async def _provision_request(
    db: AsyncSession, *, row: MeetingScheduleRequest, request: Request
) -> None:
    participant_ids = await _participant_ids(db, row.id)
    payload = MeetingScheduleValidationIn(
        title=row.title,
        meeting_type=row.meeting_type,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        platform=row.platform,
        client_name=row.client_name,
        client_email=row.client_email,
        notes=row.notes,
        department_id=row.department_id,
        project_id=row.project_id,
        standard_id=row.standard_id,
        participant_ids=participant_ids,
        exclude_request_id=row.id,
    )
    validation = await validate_meeting_schedule(db, payload, exclude_request_id=row.id)
    validation = await _with_microsoft_validation(
        db,
        payload=payload,
        request=request,
        validation=validation,
    )
    row.validation_snapshot = validation.model_dump(mode="json")
    if not validation.can_create:
        row.status = "VALIDATION_FAILED"
        row.last_error = " ".join(validation.errors)
        return

    teams_url = None
    microsoft_event_id = None
    if row.meeting_type == "external":
        await _provision_external_calendar_event(db, row=row, request=request, participant_ids=participant_ids)
        if row.status == "CREATION_FAILED":
            return
        # The helper stores the Graph result temporarily on the request so the
        # local TAK EXT row and the imported calendar row share the same ID.
        microsoft_event_id = row.microsoft_event_id
        teams_url = row.teams_url

    meeting = Meeting(
        title=row.title,
        platform="Teams" if row.meeting_type == "external" else (row.platform or None),
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        meeting_url=teams_url,
        microsoft_event_id=microsoft_event_id,
        meeting_type=row.meeting_type,
        is_training=bool(getattr(row, "is_training", False)),
        department_id=row.department_id,
        project_id=row.project_id,
        created_by=row.created_by_user_id,
    )
    db.add(meeting)
    await db.flush()
    for participant_id in participant_ids:
        db.add(MeetingParticipant(
            meeting_id=meeting.id,
            user_id=participant_id,
            assignment_source="manual",
            assigned_by_user_id=row.created_by_user_id,
        ))
    row.final_meeting_id = meeting.id
    row.status = "CREATED"
    row.last_error = None


async def _provision_external_calendar_event(
    db: AsyncSession,
    *,
    row: MeetingScheduleRequest,
    request: Request,
    participant_ids: list[uuid.UUID],
) -> None:
    try:
        token = await get_shared_calendar_token(db, redirect_uri=resolve_redirect_uri(request))
    except httpx.HTTPError:
        token = None
    if token is None:
        row.status = "CREATION_FAILED"
        row.last_error = "Administratori duhet ta lidhë calendar-in info@primexeu.com para krijimit të takimit."
        return
    participants = (
        await db.execute(select(User).where(User.work_staff_filter()).where(User.id.in_(participant_ids)))
    ).scalars().all()
    attendee_map = {
        user.email.casefold(): {"email": user.email, "name": user.full_name}
        for user in participants
        if user.email
    }
    row.status = "CREATING_TEAMS"
    try:
        event = await create_calendar_event(
            token.access_token,
            subject=row.title,
            start=row.starts_at,
            end=row.ends_at,
            attendees=list(attendee_map.values()),
            body_html=f"<p>{escape(row.notes or '')}</p>",
            transaction_id=str(row.id),
            create_online_meeting=True,
        )
    except httpx.HTTPStatusError as exc:
        row.status = "CREATION_FAILED"
        row.last_error = f"Microsoft Graph returned {exc.response.status_code}. Reconnect Microsoft and retry."
        return
    except httpx.HTTPError as exc:
        row.status = "CREATION_FAILED"
        row.last_error = f"Microsoft Graph connection failed: {exc.__class__.__name__}"
        return
    row.microsoft_event_id = str(event.get("id") or "") or None
    row.teams_url = (event.get("onlineMeeting") or {}).get("joinUrl") or event.get("onlineMeetingUrl")


@router.post("/requests/{request_id}/approve", response_model=MeetingScheduleRequestOut)
async def approve_request(
    request_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MeetingScheduleRequestOut:
    ensure_manager_or_admin(user)
    row = (
        await db.execute(
            select(MeetingScheduleRequest).where(MeetingScheduleRequest.id == request_id).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting request not found")
    if row.status in {"CREATED", "REJECTED", "CANCELED"}:
        raise HTTPException(status_code=409, detail=f"Request is already {row.status.lower()}")
    if row.created_by_user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The request creator cannot approve their own meeting request",
        )
    ensure_department_access(user, row.department_id)
    existing = (
        await db.execute(
            select(MeetingScheduleApproval).where(
                MeetingScheduleApproval.request_id == row.id,
                MeetingScheduleApproval.approved_by_user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(MeetingScheduleApproval(request_id=row.id, approved_by_user_id=user.id))
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            row = (await db.execute(select(MeetingScheduleRequest).where(MeetingScheduleRequest.id == request_id))).scalar_one()
    approval_count = int(
        (await db.execute(
            select(func.count()).select_from(MeetingScheduleApproval).where(MeetingScheduleApproval.request_id == row.id)
        )).scalar_one()
    )
    if approval_count >= APPROVALS_REQUIRED and row.status != "CREATED":
        row.status = "APPROVED"
        await _provision_request(db, row=row, request=request)
    notification = add_notification(
        db=db,
        user_id=row.created_by_user_id,
        type=NotificationType.status_change,
        title=("Meeting created" if row.status == "CREATED" else "Meeting request approved"),
        body=(
            f'"{row.title}" was created after two approvals.'
            if row.status == "CREATED"
            else f'"{row.title}" now has {approval_count}/{APPROVALS_REQUIRED} approvals.'
        ),
        data={"href": "/meeting-scheduler", "meeting_request_id": str(row.id)},
    )
    await db.commit()
    await db.refresh(row)
    await publish_notification(user_id=row.created_by_user_id, notification=notification)
    return await _request_out(db, row)


@router.post("/requests/{request_id}/retry", response_model=MeetingScheduleRequestOut)
async def retry_request(
    request_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MeetingScheduleRequestOut:
    ensure_manager_or_admin(user)
    row = (await db.execute(select(MeetingScheduleRequest).where(MeetingScheduleRequest.id == request_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting request not found")
    approval_count = int((await db.execute(select(func.count()).select_from(MeetingScheduleApproval).where(MeetingScheduleApproval.request_id == row.id))).scalar_one())
    if approval_count < APPROVALS_REQUIRED:
        raise HTTPException(status_code=409, detail="Two approvals are required")
    if row.status not in {"CREATION_FAILED", "VALIDATION_FAILED", "APPROVED"}:
        raise HTTPException(status_code=409, detail="This request cannot be retried")
    await _provision_request(db, row=row, request=request)
    await db.commit()
    await db.refresh(row)
    return await _request_out(db, row)


@router.post("/requests/{request_id}/reject", response_model=MeetingScheduleRequestOut)
async def reject_request(
    request_id: uuid.UUID,
    payload: MeetingScheduleRejectIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MeetingScheduleRequestOut:
    ensure_manager_or_admin(user)
    row = (await db.execute(select(MeetingScheduleRequest).where(MeetingScheduleRequest.id == request_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting request not found")
    if row.status == "CREATED":
        raise HTTPException(status_code=409, detail="Created meetings cannot be rejected")
    ensure_department_access(user, row.department_id)
    row.status = "REJECTED"
    row.rejection_reason = payload.reason.strip()
    row.rejected_by_user_id = user.id
    row.rejected_at = datetime.now(timezone.utc)
    await db.execute(delete(MeetingScheduleApproval).where(MeetingScheduleApproval.request_id == row.id))
    notification = add_notification(
        db=db,
        user_id=row.created_by_user_id,
        type=NotificationType.status_change,
        title="Meeting request rejected",
        body=f'"{row.title}" was rejected: {row.rejection_reason}',
        data={"href": "/meeting-scheduler", "meeting_request_id": str(row.id)},
    )
    await db.commit()
    await db.refresh(row)
    await publish_notification(user_id=row.created_by_user_id, notification=notification)
    return await _request_out(db, row)


@router.get("/calendar", response_model=list[MeetingScheduleCalendarItem])
async def calendar_items(
    start: datetime,
    end: datetime,
    department_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[MeetingScheduleCalendarItem]:
    if department_id is not None:
        ensure_department_access(user, department_id)
    meeting_stmt = select(Meeting).where(Meeting.starts_at.is_not(None), Meeting.starts_at >= start, Meeting.starts_at < end)
    request_stmt = select(MeetingScheduleRequest).where(MeetingScheduleRequest.starts_at < end, MeetingScheduleRequest.ends_at > start)
    if department_id is not None:
        meeting_stmt = meeting_stmt.where(Meeting.department_id == department_id)
        request_stmt = request_stmt.where(MeetingScheduleRequest.department_id == department_id)
    elif _role_value(user) == "STAFF":
        meeting_stmt = meeting_stmt.where(Meeting.department_id == user.department_id)
        request_stmt = request_stmt.where(MeetingScheduleRequest.department_id == user.department_id)
    # Recurring PrimeFlow meetings can have a master start outside this range.
    recurring_stmt = select(Meeting).where(
        Meeting.starts_at.is_not(None),
        Meeting.recurrence_type.in_(["weekly", "monthly", "yearly"]),
    )
    if department_id is not None:
        recurring_stmt = recurring_stmt.where(Meeting.department_id == department_id)
    elif _role_value(user) == "STAFF":
        recurring_stmt = recurring_stmt.where(Meeting.department_id == user.department_id)
    meetings = list((await db.execute(meeting_stmt)).scalars().all())
    recurring = (await db.execute(recurring_stmt)).scalars().all()
    meetings_by_id = {meeting.id: meeting for meeting in [*meetings, *recurring]}
    requests = (await db.execute(request_stmt)).scalars().all()
    result: list[MeetingScheduleCalendarItem] = []
    day_cursor = start
    while day_cursor < end:
        for meeting in meetings_by_id.values():
            window = meeting_occurrence_window(meeting, day_cursor)
            if window is None or window[0] < start or window[0] >= end:
                continue
            result.append(
                MeetingScheduleCalendarItem(
                    id=f"{meeting.id}:{window[0].date().isoformat()}", source="meeting", title=meeting.title,
                    meeting_type=meeting.meeting_type, starts_at=window[0], ends_at=window[1], status="CREATED",
                    participant_ids=[], teams_url=meeting.meeting_url,
                    microsoft_event_id=meeting.microsoft_event_id,
                    calendar_categories=meeting.calendar_categories or [],
                )
            )
        day_cursor += timedelta(days=1)
    for row in requests:
        if row.final_meeting_id is not None:
            continue
        result.append(
            MeetingScheduleCalendarItem(
                id=str(row.id), source="request", title=row.title, meeting_type=row.meeting_type,
                starts_at=row.starts_at, ends_at=row.ends_at, status=row.status,
                participant_ids=await _participant_ids(db, row.id), teams_url=row.teams_url,
                microsoft_event_id=row.microsoft_event_id,
                calendar_categories=[],
            )
        )
    return sorted(result, key=lambda item: item.starts_at)
