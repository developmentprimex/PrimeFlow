from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import (
    ensure_admin,
    ensure_department_access,
    ensure_manager_or_admin,
    ensure_meeting_editor,
    ensure_meeting_participant_editor,
)
from app.api.deps import get_current_user
from app.db import get_db
from app.integrations.microsoft import delete_calendar_event, update_calendar_event
from app.models.meeting import Meeting, MeetingParticipant
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.models.project import Project
from app.models.user import User
from app.schemas.meeting import (
    MeetingCreate,
    MeetingCreateOut,
    MeetingOccurrenceStatusOut,
    MeetingOccurrenceStatusUpdate,
    MeetingOut,
    MeetingReminderSettingsUpdate,
    MeetingUpdate,
)
from app.services.meeting_system_tasks import (
    deactivate_external_meeting_system_tasks,
    reconcile_agent_test_task_for_meeting,
    reconcile_external_meeting_system_tasks_for_meeting,
    reconcile_pim_image_test_task_for_meeting,
    reconcile_tak_int_one_h_tasks,
    reconcile_tak_int_one_h_tasks_for_meeting,
)
from app.services.meeting_scheduler import one_h_schedule_conflicts
from app.services.meeting_cancellation import delete_external_meeting_dependents
from app.services.audit import add_audit_log
from app.services.meeting_participants import (
    add_participants_to_linked_internal_meetings,
    manual_participant_ids,
    meeting_to_out,
    replace_manual_participants,
)
from app.services.microsoft_calendar_sync import (
    get_shared_calendar_token,
    is_common_view_visible_meeting,
    microsoft_calendar_sync_window,
    sync_external_calendar_events,
)
from app.api.routers.microsoft import resolve_redirect_uri


router = APIRouter()


def _occurrence_status_out(row: MeetingOccurrenceStatus) -> MeetingOccurrenceStatusOut:
    return MeetingOccurrenceStatusOut(
        id=row.id,
        meeting_id=row.meeting_id,
        occurrence_date=row.occurrence_date,
        status=row.status,
        note=row.note,
        checked_by_user_id=row.checked_by_user_id,
        checked_at=row.checked_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[MeetingOut])
async def list_meetings(
    department_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    participant_user_id: uuid.UUID | None = None,
    include_all_departments: bool = False,
    meeting_type: str | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[MeetingOut]:
    stmt = select(Meeting).where(
        or_(
            Meeting.calendar_sync_status.is_(None),
            Meeting.calendar_sync_status.notin_(("excluded", "out_of_window")),
        )
    )
    if department_id is None and project_id is None and participant_user_id is None:
        if include_all_departments:
            # Allow all users to see all meetings in common view
            pass
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="department_id, project_id, or participant_user_id required",
            )
    elif include_all_departments:
        # Allow all users to see all meetings in common view
        pass
    if project_id is not None:
        project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        stmt = stmt.where(Meeting.project_id == project_id)
    if department_id is not None:
        if not include_all_departments:
            ensure_department_access(user, department_id)
        stmt = stmt.where(Meeting.department_id == department_id)
    if participant_user_id is not None:
        stmt = stmt.join(MeetingParticipant).where(
            MeetingParticipant.user_id == participant_user_id,
            MeetingParticipant.assignment_source == "manual",
        )
    if meeting_type is not None:
        stmt = stmt.where(Meeting.meeting_type == meeting_type)

    meetings = (await db.execute(stmt.order_by(Meeting.starts_at, Meeting.created_at.desc()))).scalars().all()
    # Older Microsoft rows may predate the sync-status/category migration. Keep
    # PV calendar events out of TAK EXT even before the next background sync has
    # had a chance to mark them as excluded.
    meetings = [meeting for meeting in meetings if is_common_view_visible_meeting(meeting)]
    
    # Load participants for all meetings
    meeting_ids = [m.id for m in meetings]
    participants_by_meeting = await manual_participant_ids(db, meeting_ids)
    
    return [
        meeting_to_out(m, participant_ids=participants_by_meeting.get(m.id, []))
        for m in meetings
    ]


@router.post("/sync-microsoft-calendar")
async def sync_microsoft_calendar(
    request: Request,
    start: datetime | None = None,
    end: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    """Import every event from the shared info calendar as a TAK EXT."""
    now = datetime.now(timezone.utc)
    allowed_start, allowed_end = microsoft_calendar_sync_window(now)
    requested_start = start or allowed_start
    requested_end = end or allowed_end
    if requested_start.tzinfo is None:
        requested_start = requested_start.replace(tzinfo=timezone.utc)
    if requested_end.tzinfo is None:
        requested_end = requested_end.replace(tzinfo=timezone.utc)
    sync_start = max(requested_start, allowed_start)
    sync_end = min(requested_end, allowed_end)
    if sync_end <= sync_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Calendar sync is limited to the next 14 days.",
        )

    try:
        token = await get_shared_calendar_token(db, redirect_uri=resolve_redirect_uri(request))
        if token is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The shared Microsoft calendar is not connected.",
            )
        result = await sync_external_calendar_events(
            db,
            access_token=token.access_token,
            connected_by_user_id=token.user_id,
            start=sync_start,
            end=sync_end,
        )
        await reconcile_tak_int_one_h_tasks(
            db,
            start=sync_start.date(),
            end=sync_end.date(),
        )
        await db.commit()
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Microsoft Calendar sync failed: {exc.__class__.__name__}",
        ) from exc
    return asdict(result)


@router.get("/occurrence-statuses", response_model=list[MeetingOccurrenceStatusOut])
async def list_meeting_occurrence_statuses(
    occurrence_date: date,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[MeetingOccurrenceStatusOut]:
    rows = (
        await db.execute(
            select(MeetingOccurrenceStatus).where(MeetingOccurrenceStatus.occurrence_date == occurrence_date)
        )
    ).scalars().all()
    return [_occurrence_status_out(row) for row in rows]


@router.patch("/{meeting_id}/occurrence-status", response_model=MeetingOccurrenceStatusOut)
async def update_meeting_occurrence_status(
    meeting_id: uuid.UUID,
    payload: MeetingOccurrenceStatusUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MeetingOccurrenceStatusOut:
    meeting = (await db.execute(select(Meeting).where(Meeting.id == meeting_id))).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    row = (
        await db.execute(
            select(MeetingOccurrenceStatus).where(
                MeetingOccurrenceStatus.meeting_id == meeting_id,
                MeetingOccurrenceStatus.occurrence_date == payload.occurrence_date,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = MeetingOccurrenceStatus(
            meeting_id=meeting_id,
            occurrence_date=payload.occurrence_date,
        )
        db.add(row)
    row.status = payload.status
    row.note = payload.note
    row.checked_by_user_id = user.id
    row.checked_at = datetime.now().astimezone()
    if meeting.meeting_type == "external" and payload.status == "canceled":
        await delete_external_meeting_dependents(db, meeting)
    await db.commit()
    await db.refresh(row)
    return _occurrence_status_out(row)


@router.post("", response_model=MeetingCreateOut, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    payload: MeetingCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MeetingCreateOut:
    ensure_department_access(user, payload.department_id)
    requested_meeting_type = payload.meeting_type or "external"
    paired_external: Meeting | None = None
    if payload.paired_external_meeting_id is not None:
        if requested_meeting_type != "internal":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only a TAK INT can be linked to a TAK EXT",
            )
        paired_external = (
            await db.execute(
                select(Meeting).where(Meeting.id == payload.paired_external_meeting_id)
            )
        ).scalar_one_or_none()
        if paired_external is None or paired_external.meeting_type != "external":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TAK EXT not found")
        existing_pair = (
            await db.execute(
                select(Meeting.id).where(
                    Meeting.paired_external_meeting_id == payload.paired_external_meeting_id
                )
            )
        ).scalar_one_or_none()
        if existing_pair is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This TAK EXT already has a linked TAK INT",
            )
    should_create_internal_meeting = (
        payload.create_internal_meeting
        if payload.create_internal_meeting is not None
        else payload.internal_starts_at is not None
    )
    if (
        requested_meeting_type == "external"
        and should_create_internal_meeting
        and payload.internal_starts_at is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Internal meeting date and time are required when creating TAK INT",
        )
    if payload.project_id is not None:
        project = (await db.execute(select(Project).where(Project.id == payload.project_id))).scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if project.department_id != payload.department_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project must be in department")

    # Every meeting must belong to at least one person's view.
    participant_ids = payload.participant_ids or []
    if paired_external is not None:
        external_participant_ids = (
            await manual_participant_ids(db, [paired_external.id])
        ).get(paired_external.id, [])
        participant_ids = list(dict.fromkeys([*participant_ids, *external_participant_ids]))
    if not participant_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Select at least one person for the meeting",
        )
    users_stmt = select(User).where(User.id.in_(participant_ids))
    existing_users = (await db.execute(users_stmt)).scalars().all()
    existing_user_ids = {u.id for u in existing_users}
    invalid_ids = set(participant_ids) - existing_user_ids
    if invalid_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid user IDs: {list(invalid_ids)}"
        )

    one_h_conflicts = []
    if payload.starts_at is not None:
        default_duration = timedelta(minutes=30 if requested_meeting_type == "internal" else 60)
        primary_end = payload.ends_at or payload.starts_at + default_duration
        primary_conflicts, _ = await one_h_schedule_conflicts(
            db,
            participant_ids=set(participant_ids),
            starts_at=payload.starts_at.astimezone(timezone.utc),
            ends_at=primary_end.astimezone(timezone.utc),
        )
        one_h_conflicts.extend(primary_conflicts)
    if requested_meeting_type == "external" and should_create_internal_meeting and payload.internal_starts_at is not None:
        internal_start = payload.internal_starts_at.astimezone(timezone.utc)
        internal_conflicts, _ = await one_h_schedule_conflicts(
            db,
            participant_ids=set(participant_ids),
            starts_at=internal_start,
            ends_at=internal_start + timedelta(minutes=30),
        )
        one_h_conflicts.extend(internal_conflicts)
    if one_h_conflicts and not payload.allow_one_h_conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "one_h_conflict",
                "message": "Ky orar përputhet me 1H.",
                "conflicts": [conflict.model_dump(mode="json") for conflict in one_h_conflicts],
            },
        )

    meeting = Meeting(
        title=payload.title,
        platform=payload.platform,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        meeting_url=payload.meeting_url,
        meeting_type=requested_meeting_type,
        recurrence_type=payload.recurrence_type,
        recurrence_days_of_week=payload.recurrence_days_of_week,
        recurrence_days_of_month=payload.recurrence_days_of_month,
        department_id=payload.department_id,
        project_id=payload.project_id,
        paired_external_meeting_id=payload.paired_external_meeting_id,
        created_by=user.id,
    )
    db.add(meeting)
    await db.flush()  # Flush to get the meeting ID

    paired_internal_meeting: Meeting | None = None
    if (
        meeting.meeting_type == "external"
        and should_create_internal_meeting
        and payload.internal_starts_at is not None
    ):
        paired_internal_meeting = Meeting(
            title=payload.title,
            platform=payload.platform,
            starts_at=payload.internal_starts_at,
            ends_at=None,
            meeting_url=payload.meeting_url,
            meeting_type="internal",
            recurrence_type=payload.recurrence_type,
            recurrence_days_of_week=payload.recurrence_days_of_week,
            recurrence_days_of_month=payload.recurrence_days_of_month,
            department_id=payload.department_id,
            project_id=payload.project_id,
            paired_external_meeting_id=meeting.id,
            created_by=user.id,
        )
        db.add(paired_internal_meeting)
        await db.flush()
    
    # Create participants
    for user_id in participant_ids:
        participant = MeetingParticipant(
            meeting_id=meeting.id,
            user_id=user_id,
            assignment_source="manual",
            assigned_by_user_id=user.id,
        )
        db.add(participant)
        if paired_internal_meeting is not None:
            db.add(MeetingParticipant(
                meeting_id=paired_internal_meeting.id,
                user_id=user_id,
                assignment_source="manual",
                assigned_by_user_id=user.id,
            ))

    await db.flush()
    await reconcile_tak_int_one_h_tasks_for_meeting(db, meeting)
    await db.commit()
    await db.refresh(meeting)
    if paired_internal_meeting is not None:
        await db.refresh(paired_internal_meeting)
    
    # Load participants for response
    participant_ids_list = list(dict.fromkeys(participant_ids))
    paired_internal_out = (
        meeting_to_out(paired_internal_meeting, participant_ids=participant_ids_list)
        if paired_internal_meeting is not None
        else None
    )
    return MeetingCreateOut(
        **meeting_to_out(meeting, participant_ids=participant_ids_list).model_dump(),
        paired_internal_meeting=paired_internal_out,
    )


@router.patch("/{meeting_id}/reminder-settings", response_model=MeetingOut)
async def update_meeting_reminder_settings(
    meeting_id: uuid.UUID,
    payload: MeetingReminderSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MeetingOut:
    """Update PrimeFlow-only participants and reminders without modifying the source calendar."""
    meeting = (await db.execute(select(Meeting).where(Meeting.id == meeting_id))).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    ensure_meeting_participant_editor(user, meeting)
    before_ids = (await manual_participant_ids(db, [meeting.id])).get(meeting.id, [])
    before = {
        "participant_ids": [str(value) for value in before_ids],
        "reminder_minutes_before": meeting.reminder_minutes_before,
    }
    participant_ids = await replace_manual_participants(
        db,
        meeting_id=meeting.id,
        participant_ids=payload.participant_ids,
        actor_user_id=user.id,
    )
    before_id_set = set(before_ids)
    added_participant_ids = [
        participant_id for participant_id in participant_ids if participant_id not in before_id_set
    ]
    linked_internal_ids: list[uuid.UUID] = []
    if meeting.meeting_type == "external" and added_participant_ids:
        linked_internal_ids = await add_participants_to_linked_internal_meetings(
            db,
            external_meeting_id=meeting.id,
            participant_ids=added_participant_ids,
            actor_user_id=user.id,
        )
    meeting.reminder_minutes_before = payload.reminder_minutes_before
    await db.flush()
    await reconcile_tak_int_one_h_tasks_for_meeting(db, meeting)
    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="meeting",
        entity_id=meeting.id,
        action="UPDATE_PARTICIPANTS_AND_REMINDER",
        before=before,
        after={
            "participant_ids": [str(value) for value in participant_ids],
            "reminder_minutes_before": payload.reminder_minutes_before,
            "participants_added_to_linked_internal_meeting_ids": [
                str(value) for value in linked_internal_ids
            ],
        },
    )
    await db.commit()
    await db.refresh(meeting)
    return meeting_to_out(meeting, participant_ids=participant_ids)


@router.patch("/{meeting_id}", response_model=MeetingOut)
async def update_meeting(
    meeting_id: uuid.UUID,
    payload: MeetingUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MeetingOut:
    meeting = (await db.execute(select(Meeting).where(Meeting.id == meeting_id))).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    # Allow admin, manager, or the person that created it to edit
    ensure_meeting_editor(user, meeting)

    # Get fields that were explicitly set in the request
    payload_dict = payload.model_dump(exclude_unset=True)

    calendar_fields = {"title", "platform", "starts_at", "ends_at"}
    if meeting.calendar_imported and meeting.microsoft_event_id and calendar_fields.intersection(payload_dict):
        token = await get_shared_calendar_token(db, redirect_uri=resolve_redirect_uri(request))
        if token is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The shared Microsoft calendar is not connected.",
            )
        graph_start = payload.starts_at if "starts_at" in payload_dict else meeting.starts_at
        graph_end = payload.ends_at if "ends_at" in payload_dict else meeting.ends_at
        if "starts_at" in payload_dict and "ends_at" not in payload_dict and graph_start is not None:
            current_duration = (
                meeting.ends_at - meeting.starts_at
                if meeting.starts_at is not None and meeting.ends_at is not None
                else timedelta(hours=1)
            )
            graph_end = graph_start + current_duration
            meeting.ends_at = graph_end
        try:
            await update_calendar_event(
                token.access_token,
                meeting.microsoft_event_id,
                subject=payload.title if "title" in payload_dict else None,
                start=graph_start if "starts_at" in payload_dict else None,
                end=graph_end if "starts_at" in payload_dict or "ends_at" in payload_dict else None,
                location=payload.platform if "platform" in payload_dict else None,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Microsoft Calendar event could not be updated.",
            ) from exc
        meeting.calendar_change_key = None
    
    if "title" in payload_dict and payload.title is not None:
        meeting.title = payload.title
    if "platform" in payload_dict:
        meeting.platform = payload.platform
    if "starts_at" in payload_dict:
        meeting.starts_at = payload.starts_at
    if "ends_at" in payload_dict:
        meeting.ends_at = payload.ends_at
    if "meeting_url" in payload_dict:
        meeting.meeting_url = payload.meeting_url
    if "meeting_type" in payload_dict and payload.meeting_type is not None:
        meeting.meeting_type = payload.meeting_type
    if "recurrence_type" in payload_dict:
        # If recurrence_type is None/null, clear all recurrence fields
        meeting.recurrence_type = payload.recurrence_type
        if payload.recurrence_type is None:
            meeting.recurrence_days_of_week = None
            meeting.recurrence_days_of_month = None
    if "recurrence_days_of_week" in payload_dict:
        meeting.recurrence_days_of_week = payload.recurrence_days_of_week
    if "recurrence_days_of_month" in payload_dict:
        meeting.recurrence_days_of_month = payload.recurrence_days_of_month
    # Handle project_id update - can be set to None or a valid project
    if "project_id" in payload_dict:
        if payload.project_id is not None:
            project = (await db.execute(select(Project).where(Project.id == payload.project_id))).scalar_one_or_none()
            if project is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
            if project.department_id != meeting.department_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project must be in department")
            meeting.project_id = payload.project_id
        else:
            meeting.project_id = None
    
    # Update participants if provided
    if "participant_ids" in payload_dict:
        participant_ids = payload.participant_ids or []
        if not participant_ids and not meeting.calendar_imported:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Select at least one person for the meeting",
            )
        before_participant_ids = (
            await manual_participant_ids(db, [meeting.id])
        ).get(meeting.id, [])
        updated_participant_ids = await replace_manual_participants(
            db,
            meeting_id=meeting.id,
            participant_ids=participant_ids,
            actor_user_id=user.id,
        )
        if meeting.meeting_type == "external":
            before_participant_id_set = set(before_participant_ids)
            added_participant_ids = [
                participant_id
                for participant_id in updated_participant_ids
                if participant_id not in before_participant_id_set
            ]
            if added_participant_ids:
                await add_participants_to_linked_internal_meetings(
                    db,
                    external_meeting_id=meeting.id,
                    participant_ids=added_participant_ids,
                    actor_user_id=user.id,
                )

    await db.flush()
    await reconcile_external_meeting_system_tasks_for_meeting(db, meeting)
    await reconcile_tak_int_one_h_tasks_for_meeting(db, meeting)

    await db.commit()
    await db.refresh(meeting)
    
    # Load participants for response
    participant_ids_list = (await manual_participant_ids(db, [meeting.id])).get(meeting.id, [])
    return meeting_to_out(meeting, participant_ids=participant_ids_list)


@router.post("/{meeting_id}/agent-test-task", response_model=MeetingOut)
async def create_agent_test_task_for_meeting(
    meeting_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MeetingOut:
    meeting = (await db.execute(select(Meeting).where(Meeting.id == meeting_id))).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    ensure_manager_or_admin(user)
    ensure_department_access(user, meeting.department_id)
    if meeting.meeting_type != "external":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent test task is only available for external meetings")

    meeting.external_agent_test_task_requested = True
    await db.flush()
    created = await reconcile_agent_test_task_for_meeting(db, meeting)
    if created == 0 and meeting.starts_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Meeting start date is required")
    if created == 0 and (meeting.recurrence_type or "").strip().lower() not in ("", "none"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent test task is only available for one-time meetings")

    await db.commit()
    await db.refresh(meeting)

    participant_ids_list = (await manual_participant_ids(db, [meeting.id])).get(meeting.id, [])
    return meeting_to_out(meeting, participant_ids=participant_ids_list)


@router.post("/{meeting_id}/pim-image-test-task", response_model=MeetingOut)
async def create_pim_image_test_task_for_meeting(
    meeting_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MeetingOut:
    meeting = (await db.execute(select(Meeting).where(Meeting.id == meeting_id))).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    ensure_manager_or_admin(user)
    ensure_department_access(user, meeting.department_id)
    if meeting.meeting_type != "external":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PIM image test task is only available for external meetings")
    if meeting.starts_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Meeting start date is required")
    if (meeting.recurrence_type or "").strip().lower() not in ("", "none"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PIM image test task is only available for one-time meetings")

    meeting.external_pim_image_test_task_requested = True
    await db.flush()
    await reconcile_pim_image_test_task_for_meeting(db, meeting)
    await db.commit()
    await db.refresh(meeting)

    participant_ids_list = (await manual_participant_ids(db, [meeting.id])).get(meeting.id, [])
    return meeting_to_out(meeting, participant_ids=participant_ids_list)


@router.delete("/{meeting_id}", status_code=status.HTTP_200_OK)
async def delete_meeting(
    meeting_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    meeting = (await db.execute(select(Meeting).where(Meeting.id == meeting_id))).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
    # Only admins can delete external meetings
    ensure_admin(user)
    if meeting.calendar_imported and meeting.microsoft_event_id:
        token = await get_shared_calendar_token(db, redirect_uri=resolve_redirect_uri(request))
        if token is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The shared Microsoft calendar is not connected.",
            )
        try:
            await delete_calendar_event(token.access_token, meeting.microsoft_event_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != status.HTTP_404_NOT_FOUND:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Microsoft Calendar event could not be deleted.",
                ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Microsoft Calendar event could not be deleted.",
            ) from exc
    await deactivate_external_meeting_system_tasks(db, meeting.id)
    await db.delete(meeting)
    await db.commit()
    return {"ok": True}
