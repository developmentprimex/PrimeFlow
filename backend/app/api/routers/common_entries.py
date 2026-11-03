from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_department_access
from app.api.deps import get_current_user
from app.db import get_db
from app.models.board import Board
from app.models.common_entry import CommonEntry
from app.models.enums import CommonApprovalStatus, CommonCategory, NotificationType, TaskType, UserRole
from app.models.notification import Notification
from app.models.project import Project
from app.models.task import Task
from app.models.task_status import TaskStatus
from app.models.user import User
from app.schemas.common_entry import (
    CommonEntryApprove,
    CommonEntryAssign,
    CommonEntryCreate,
    CommonLeaveBlockOut,
    CommonEntryOut,
    CommonEntryReject,
)
from app.services.audit import add_audit_log
from app.services.notifications import add_notification, publish_notification


router = APIRouter()
FEEDBACK_DAILY_MARKER = "[EVERYDAY]"


def _safe_iso_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback


def _daily_feedback_filter():
    return and_(
        CommonEntry.category.in_(
            [
                CommonCategory.complaints,
                CommonCategory.requests,
                CommonCategory.proposals,
                CommonCategory.problems,
            ]
        ),
        CommonEntry.description.isnot(None),
        CommonEntry.description.ilike(f"%{FEEDBACK_DAILY_MARKER}%"),
    )


def _parse_annual_leave(entry: CommonEntry) -> tuple[date, date, bool, str | None, str | None, str | None]:
    note = entry.description or ""
    base_date = entry.entry_date or entry.created_at.date()
    start_date = base_date
    end_date = base_date
    full_day = True
    start_time: str | None = None
    end_time: str | None = None

    date_range_match = re.search(r"Date range:\s*(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})", note, re.I)
    if date_range_match:
        start_date = _safe_iso_date(date_range_match.group(1), start_date)
        end_date = _safe_iso_date(date_range_match.group(2), end_date)
        note = re.sub(
            r"Date range:\s*\d{4}-\d{2}-\d{2}\s+to\s+\d{4}-\d{2}-\d{2}",
            "",
            note,
            flags=re.I,
        ).strip()
    else:
        date_match = re.search(r"Date:\s*(\d{4}-\d{2}-\d{2})", note, re.I)
        if date_match:
            parsed = _safe_iso_date(date_match.group(1), start_date)
            start_date = parsed
            end_date = parsed
            note = re.sub(r"Date:\s*\d{4}-\d{2}-\d{2}", "", note, flags=re.I).strip()
        else:
            date_matches = re.findall(r"\d{4}-\d{2}-\d{2}", note)
            if date_matches:
                start_date = _safe_iso_date(date_matches[0], start_date)
                end_date = _safe_iso_date(date_matches[1] if len(date_matches) > 1 else date_matches[0], end_date)

    if re.search(r"\(Full day\)", note, re.I):
        full_day = True
        note = re.sub(r"\(Full day\)", "", note, flags=re.I).strip()
    else:
        time_match = re.search(r"\((\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\)", note)
        if time_match:
            full_day = False
            start_time = time_match.group(1)
            end_time = time_match.group(2)
            note = re.sub(r"\(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\)", "", note).strip()

    cleaned_note = note.strip() if note.strip() else None
    return start_date, end_date, full_day, start_time, end_time, cleaned_note


def _to_out(e: CommonEntry) -> CommonEntryOut:
    return CommonEntryOut(
        id=e.id,
        category=e.category,
        title=e.title,
        description=e.description,
        entry_date=e.entry_date,
        created_by_user_id=e.created_by_user_id,
        assigned_to_user_id=e.assigned_to_user_id,
        approval_status=e.approval_status,
        approved_by_user_id=e.approved_by_user_id,
        approved_at=e.approved_at,
        rejected_by_user_id=e.rejected_by_user_id,
        rejected_at=e.rejected_at,
        rejection_reason=e.rejection_reason,
        generated_task_id=e.generated_task_id,
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


@router.get("", response_model=list[CommonEntryOut])
async def list_entries(
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None, alias="to"),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[CommonEntryOut]:
    if from_ is None and to is None:
        stmt = select(CommonEntry).order_by(CommonEntry.created_at.desc())
        entries = (await db.execute(stmt)).scalars().all()
        return [_to_out(e) for e in entries]

    effective_date = func.coalesce(CommonEntry.entry_date, func.date(CommonEntry.created_at))
    date_filters = []
    if from_ is not None:
        date_filters.append(effective_date >= from_)
    if to is not None:
        date_filters.append(effective_date <= to)
    date_filter = and_(*date_filters) if date_filters else None
    daily_filter = _daily_feedback_filter()

    non_annual_stmt = select(CommonEntry).where(CommonEntry.category != CommonCategory.annual_leave)
    if date_filter is not None:
        non_annual_stmt = non_annual_stmt.where(or_(date_filter, daily_filter))
    non_annual_entries = (await db.execute(non_annual_stmt)).scalars().all()

    annual_stmt = select(CommonEntry).where(CommonEntry.category == CommonCategory.annual_leave)
    annual_entries = (await db.execute(annual_stmt)).scalars().all()
    annual_overlapping: list[CommonEntry] = []
    for entry in annual_entries:
        start_date, end_date, _, _, _, _ = _parse_annual_leave(entry)
        if from_ is not None and end_date < from_:
            continue
        if to is not None and start_date > to:
            continue
        annual_overlapping.append(entry)

    merged = non_annual_entries + annual_overlapping
    merged.sort(key=lambda e: e.created_at, reverse=True)
    return [_to_out(e) for e in merged]


@router.get("/blocks", response_model=list[CommonLeaveBlockOut])
async def list_leave_blocks(
    type: str = "PV_FEST",
    start: date | None = None,
    end: date | None = None,
    department_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[CommonLeaveBlockOut]:
    if type not in {"PV_FEST", "ANNUAL_LEAVE"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported block type")

    if start is None or end is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="start and end are required")

    if department_id is not None:
        ensure_department_access(user, department_id)
    elif user.role != UserRole.ADMIN:
        department_id = user.department_id
        if department_id is None:
            return []

    users_in_department: list[uuid.UUID] | None = None
    if department_id is not None:
        users_in_department = (
            await db.execute(
                select(User.id).where(User.work_staff_filter()).where(User.department_id == department_id, User.is_active == True)
            )
        ).scalars().all()
        if not users_in_department:
            return []

    entries_stmt = select(CommonEntry).where(CommonEntry.category == CommonCategory.annual_leave)
    if users_in_department is not None:
        entries_stmt = entries_stmt.where(
            (CommonEntry.assigned_to_user_id.in_(users_in_department))
            | (
                (CommonEntry.assigned_to_user_id.is_(None))
                & (CommonEntry.created_by_user_id.in_(users_in_department))
            )
        )

    entries = (await db.execute(entries_stmt.order_by(CommonEntry.created_at.desc()))).scalars().all()
    blocks: list[CommonLeaveBlockOut] = []

    for entry in entries:
        entry_user_id = entry.assigned_to_user_id or entry.created_by_user_id
        start_date, end_date, full_day, start_time, end_time, note = _parse_annual_leave(entry)
        if end_date < start or start_date > end:
            continue
        blocks.append(
            CommonLeaveBlockOut(
                entry_id=entry.id,
                user_id=entry_user_id,
                start_date=start_date,
                end_date=end_date,
                full_day=full_day,
                start_time=start_time,
                end_time=end_time,
                note=note,
            )
        )

    return blocks


@router.post("", response_model=CommonEntryOut)
async def create_entry(
    payload: CommonEntryCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> CommonEntryOut:
    # Validate assigned user if provided
    assigned_to_user_id = payload.assigned_to_user_id
    if assigned_to_user_id is not None:
        assigned_user = (await db.execute(select(User).where(User.work_staff_filter()).where(User.id == assigned_to_user_id))).scalar_one_or_none()
        if assigned_user is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user not found")
    
    entry = CommonEntry(
        category=payload.category,
        title=payload.title,
        description=payload.description,
        entry_date=payload.entry_date,
        created_by_user_id=user.id,
        assigned_to_user_id=assigned_to_user_id,
        approval_status=CommonApprovalStatus.pending,
    )
    db.add(entry)
    await db.flush()

    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="common_entry",
        entity_id=entry.id,
        action="created",
        after={"category": entry.category.value, "title": entry.title, "assigned_to_user_id": str(assigned_to_user_id) if assigned_to_user_id else None},
    )

    # Send notification to assigned user if entry is created for someone else
    created_notifications: list[Notification] = []
    if assigned_to_user_id is not None and assigned_to_user_id != user.id:
        created_notifications.append(
            add_notification(
                db=db,
                user_id=assigned_to_user_id,
                type=NotificationType.assignment,
                title="Common entry assigned",
                body=entry.title,
                data={"common_entry_id": str(entry.id)},
            )
        )

    await db.commit()
    await db.refresh(entry)

    # Publish notifications
    for n in created_notifications:
        try:
            await publish_notification(user_id=n.user_id, notification=n)
        except Exception:
            pass

    return _to_out(entry)


@router.patch("/{entry_id}/assign", response_model=CommonEntryOut)
async def assign_entry(
    entry_id: uuid.UUID,
    payload: CommonEntryAssign,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> CommonEntryOut:
    if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    entry = (await db.execute(select(CommonEntry).where(CommonEntry.id == entry_id))).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")

    before = {"assigned_to_user_id": str(entry.assigned_to_user_id) if entry.assigned_to_user_id else None}
    entry.assigned_to_user_id = payload.assigned_to_user_id
    after = {"assigned_to_user_id": str(entry.assigned_to_user_id) if entry.assigned_to_user_id else None}

    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="common_entry",
        entity_id=entry.id,
        action="assigned",
        before=before,
        after=after,
    )

    created_notifications: list[Notification] = []
    if payload.assigned_to_user_id is not None:
        target = (await db.execute(select(User).where(User.work_staff_filter()).where(User.id == payload.assigned_to_user_id))).scalar_one_or_none()
        if target:
            created_notifications.append(
                add_notification(
                    db=db,
                    user_id=target.id,
                    type=NotificationType.assignment,
                    title="Common entry assigned",
                    body=entry.title,
                    data={"common_entry_id": str(entry.id)},
                )
            )

    await db.commit()
    await db.refresh(entry)

    for n in created_notifications:
        try:
            await publish_notification(user_id=n.user_id, notification=n)
        except Exception:
            pass

    return _to_out(entry)


@router.post("/{entry_id}/approve", response_model=CommonEntryOut)
async def approve_entry(
    entry_id: uuid.UUID,
    payload: CommonEntryApprove,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> CommonEntryOut:
    if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    entry = (await db.execute(select(CommonEntry).where(CommonEntry.id == entry_id))).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    if entry.approval_status != CommonApprovalStatus.pending:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Entry already processed")

    created_notifications: list[Notification] = []

    entry.approval_status = CommonApprovalStatus.approved
    entry.approved_by_user_id = user.id
    entry.approved_at = datetime.now(timezone.utc)

    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="common_entry",
        entity_id=entry.id,
        action="approved",
        after={"approved_at": entry.approved_at.isoformat()},
    )

    if payload.create_task:
        if payload.project_id is None or payload.status_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="project_id and status_id required")

        project = (await db.execute(select(Project).where(Project.id == payload.project_id))).scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        board = (await db.execute(select(Board).where(Board.id == project.board_id))).scalar_one_or_none()
        if board is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Board not found")

        status_row = (
            await db.execute(
                select(TaskStatus).where(TaskStatus.id == payload.status_id, TaskStatus.department_id == board.department_id)
            )
        ).scalar_one_or_none()
        if status_row is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status")

        assigned_to = payload.assigned_to_user_id or entry.assigned_to_user_id
        if assigned_to is not None:
            assigned_user = (await db.execute(select(User).where(User.work_staff_filter()).where(User.id == assigned_to))).scalar_one_or_none()
            if assigned_user is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user not found")
            if assigned_user.department_id != board.department_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assigned user must be in department")

        task = Task(
            department_id=board.department_id,
            board_id=board.id,
            project_id=project.id,
            title=entry.title,
            description=entry.description,
            task_type=TaskType.adhoc,
            status_id=payload.status_id,
            position=0,
            assigned_to_user_id=assigned_to,
            created_by_user_id=user.id,
        )
        db.add(task)
        await db.flush()
        entry.generated_task_id = task.id

        add_audit_log(
            db=db,
            actor_user_id=user.id,
            entity_type="task",
            entity_id=task.id,
            action="created_from_common_entry",
            after={"common_entry_id": str(entry.id)},
        )

        if assigned_to is not None:
            created_notifications.append(
                add_notification(
                    db=db,
                    user_id=assigned_to,
                    type=NotificationType.assignment,
                    title="Task assigned",
                    body=task.title,
                    data={"task_id": str(task.id)},
                )
            )

    await db.commit()
    await db.refresh(entry)

    for n in created_notifications:
        try:
            await publish_notification(user_id=n.user_id, notification=n)
        except Exception:
            pass

    return _to_out(entry)


@router.post("/{entry_id}/reject", response_model=CommonEntryOut)
async def reject_entry(
    entry_id: uuid.UUID,
    payload: CommonEntryReject,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> CommonEntryOut:
    if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    entry = (await db.execute(select(CommonEntry).where(CommonEntry.id == entry_id))).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")
    if entry.approval_status != CommonApprovalStatus.pending:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Entry already processed")

    entry.approval_status = CommonApprovalStatus.rejected
    entry.rejected_by_user_id = user.id
    entry.rejected_at = datetime.now(timezone.utc)
    entry.rejection_reason = payload.reason

    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="common_entry",
        entity_id=entry.id,
        action="rejected",
        after={"reason": payload.reason},
    )

    await db.commit()
    await db.refresh(entry)
    return _to_out(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_entry(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> None:
    if user.role not in (UserRole.ADMIN, UserRole.MANAGER, UserRole.STAFF):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    entry = (await db.execute(select(CommonEntry).where(CommonEntry.id == entry_id))).scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found")

    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="common_entry",
        entity_id=entry.id,
        action="deleted",
        before={"category": entry.category.value, "title": entry.title},
    )

    await db.delete(entry)
    await db.commit()
    return None

