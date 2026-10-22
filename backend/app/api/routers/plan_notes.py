from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.access import ensure_department_access, ensure_task_editor
from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models.enums import GaNoteStatus, GaNoteType, NotificationType, TaskStatus, UserRole
from app.models.plan_note import PlanNote
from app.models.plan_note_attachment import PlanNoteAttachment
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.models.task_user_comment import TaskUserComment
from app.schemas.plan_note import (
    PlanNoteAttachmentOut,
    PlanNoteCreate,
    PlanNoteOut,
    PlanNoteTaskBundleResponse,
    PlanNoteTaskBundleUpdate,
    PlanNoteTaskDeadlineUpdate,
    PlanNoteUpdate,
)
from app.services.audit import add_audit_log
from app.services.daily_realization_baseline import ensure_daily_baselines_for_departments
from app.services.daily_realization_events import record_task_semantic_events, task_semantic_state
from app.services.task_postponement import check_note_postponement_explanations, save_postponement_daily_explanation
from app.services.ga_note_task_instances import (
    GaNoteAssigneeExecutionState,
    apply_ga_note_assignee_execution_states,
    apply_ga_note_shared_task_fields,
    reconcile_plan_note_task_assignees,
    sync_ga_note_assignee_report_slots,
)
from app.services.task_strike_events import record_description_strike_events, record_title_strike_events
from app.services.task_daily_progress import sync_task_daily_finish_period, upsert_explicit_task_daily_status
from app.services.task_marker import active_one_h_marker, current_effective_marker_date, marker_is_by_ga, normalize_marker_comment, note_bundle_marker_update, sync_note_task_marker
from app.services.marker_comments import record_initial_marker_comments
from app.services.notifications import (
    add_notification,
    notification_task_preview,
    publish_notification,
)

router = APIRouter()


class MarkWaitingDoneResponse(BaseModel):
    updated_count: int
    skipped_count: int


class PlanNoteTaskDeadlineResponse(BaseModel):
    updated_count: int
    due_date: datetime | None = None
    is_deadline_important: bool | None = None


def _plan_note_task_title(content: str | None) -> str:
    normalized = (content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return normalized or "Plan note task"


def _plan_note_default_task_description(content: str | None) -> str | None:
    trimmed = (content or "").strip()
    return trimmed or None


def _attachment_out(attachment: PlanNoteAttachment) -> PlanNoteAttachmentOut:
    return PlanNoteAttachmentOut(
        id=attachment.id,
        note_id=attachment.note_id,
        original_filename=attachment.original_filename,
        stored_filename=attachment.stored_filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        created_by=attachment.created_by,
        created_at=attachment.created_at,
    )


def _note_out(
    note: PlanNote,
    *,
    include_attachments: bool = True,
    attachment_count: int | None = None,
) -> PlanNoteOut:
    attachments = [_attachment_out(a) for a in (note.attachments or [])] if include_attachments else []
    return PlanNoteOut(
        id=note.id,
        content=note.content,
        comment=note.comment,
        created_by=note.created_by,
        note_type=note.note_type,
        status=note.status,
        priority=note.priority,
        start_date=note.start_date,
        due_date=note.due_date,
        completed_at=note.completed_at,
        is_converted_to_task=note.is_converted_to_task,
        is_discussed=note.is_discussed,
        one_h_marker=active_one_h_marker(note),
        one_h_marker_by_ga=bool(active_one_h_marker(note) and note.one_h_marker_by_ga),
        one_h_marker_comment=note.one_h_marker_comment,
        next_week=note.next_week,
        project_id=note.project_id,
        department_id=note.department_id,
        planned_for_date=note.planned_for_date,
        planning_brief=note.planning_brief,
        created_at=note.created_at,
        updated_at=note.updated_at,
        attachments=attachments,
        attachment_count=len(attachments) if attachment_count is None else attachment_count,
    )


def _plan_note_upload_base_dir() -> Path:
    upload_base = Path(settings.PLAN_NOTES_UPLOAD_DIR)
    if not upload_base.is_absolute():
        upload_base = Path(__file__).resolve().parents[3] / upload_base
    return upload_base


async def _ensure_note_access(note: PlanNote, user, db: AsyncSession) -> None:
    # Every authenticated PrimeFlow user may view, edit, and strike PX JAV notes.
    return


async def _get_note_or_404(note_id: uuid.UUID, db: AsyncSession) -> PlanNote:
    note = (await db.execute(select(PlanNote).where(PlanNote.id == note_id))).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan note not found")
    return note


async def _save_plan_note_attachments(
    note: PlanNote,
    files: list[UploadFile],
    db: AsyncSession,
    user,
) -> list[PlanNoteAttachmentOut]:
    await _ensure_note_access(note, user, db)

    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files uploaded")
    if len(files) > settings.GA_NOTES_MAX_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many files. Max {settings.GA_NOTES_MAX_FILES}.",
        )

    max_bytes = settings.GA_NOTES_MAX_FILE_MB * 1024 * 1024
    upload_base = _plan_note_upload_base_dir()
    note_dir = upload_base / str(note.id)
    note_dir.mkdir(parents=True, exist_ok=True)

    created: list[PlanNoteAttachment] = []
    stored_paths: list[Path] = []
    try:
        for upload in files:
            attachment_id = uuid.uuid4()
            original_name = (upload.filename or "file").strip()
            extension = Path(original_name).suffix
            stored_name = f"{attachment_id}{extension}"
            stored_path = note_dir / stored_name

            size_bytes = 0
            with stored_path.open("wb") as buffer:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size_bytes += len(chunk)
                    if size_bytes > max_bytes:
                        buffer.close()
                        if stored_path.exists():
                            stored_path.unlink()
                        await upload.close()
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"File too large. Max {settings.GA_NOTES_MAX_FILE_MB}MB.",
                        )
                    buffer.write(chunk)
            stored_paths.append(stored_path)

            attachment = PlanNoteAttachment(
                id=attachment_id,
                note_id=note.id,
                original_filename=original_name,
                stored_filename=stored_name,
                content_type=upload.content_type,
                size_bytes=size_bytes,
                created_by=user.id,
            )
            db.add(attachment)
            created.append(attachment)
            await upload.close()

        await db.commit()
    except Exception:
        for path in stored_paths:
            if path.exists():
                path.unlink()
        await db.rollback()
        raise

    return [_attachment_out(a) for a in created]


@router.get("", response_model=list[PlanNoteOut])
async def list_plan_notes(
    project_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    include_attachments: bool = True,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[PlanNoteOut]:
    closed_cutoff = datetime.utcnow() - timedelta(days=30)

    stmt = select(PlanNote).order_by(PlanNote.created_at.desc(), PlanNote.id.desc())
    if include_attachments:
        stmt = stmt.options(selectinload(PlanNote.attachments))

    stmt = stmt.where(
        or_(
            PlanNote.status != GaNoteStatus.CLOSED,
            PlanNote.completed_at.is_(None),
            PlanNote.completed_at >= closed_cutoff,
        )
    )

    if project_id is not None:
        project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        stmt = stmt.where(PlanNote.project_id == project_id)
    elif department_id is not None:
        stmt = stmt.where(PlanNote.department_id == department_id)

    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)

    notes = (await db.execute(stmt)).scalars().all()
    if include_attachments or not notes:
        return [_note_out(note) for note in notes]

    attachment_counts = dict(
        (
            await db.execute(
                select(PlanNoteAttachment.note_id, func.count(PlanNoteAttachment.id))
                .where(PlanNoteAttachment.note_id.in_([note.id for note in notes]))
                .group_by(PlanNoteAttachment.note_id)
            )
        ).all()
    )
    return [
        _note_out(
            note,
            include_attachments=False,
            attachment_count=int(attachment_counts.get(note.id, 0)),
        )
        for note in notes
    ]


@router.post("", response_model=PlanNoteOut, status_code=status.HTTP_201_CREATED)
async def create_plan_note(
    payload: PlanNoteCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> PlanNoteOut:
    if payload.project_id is None and payload.department_id is None:
        if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="project_id or department_id required")

    project = None
    department_id = payload.department_id
    if payload.project_id is not None:
        project = (await db.execute(select(Project).where(Project.id == payload.project_id))).scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if project.department_id is not None:
            ensure_department_access(user, project.department_id)
        if department_id is not None and project.department_id != department_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project department mismatch")
        department_id = project.department_id
    elif department_id is not None:
        ensure_department_access(user, department_id)

    note = PlanNote(
        content=payload.content,
        comment=payload.comment,
        created_by=payload.created_by or user.id,
        note_type=payload.note_type or GaNoteType.GA,
        status=payload.status or GaNoteStatus.OPEN,
        priority=payload.priority,
        start_date=payload.start_date,
        due_date=payload.due_date,
        completed_at=payload.completed_at,
        is_converted_to_task=payload.is_converted_to_task or False,
        is_discussed=payload.is_discussed or False,
        one_h_marker=payload.one_h_marker,
        one_h_marker_date=current_effective_marker_date() if payload.one_h_marker else None,
        one_h_marker_by_ga=bool(payload.one_h_marker and marker_is_by_ga(user.email)),
        one_h_marker_comment=normalize_marker_comment(payload.one_h_marker, payload.one_h_marker_comment),
        next_week=payload.next_week or False,
        project_id=payload.project_id,
        department_id=department_id,
        planned_for_date=payload.planned_for_date,
        planning_brief=(payload.planning_brief.model_dump(mode="json") if payload.planning_brief else None),
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return _note_out(note)


@router.patch("/{note_id}", response_model=PlanNoteOut)
async def update_plan_note(
    note_id: uuid.UUID,
    payload: PlanNoteUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> PlanNoteOut:
    note = (await db.execute(select(PlanNote).where(PlanNote.id == note_id))).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan note not found")
    await _ensure_note_access(note, user, db)

    old_content = note.content
    old_planning_brief = note.planning_brief
    update_data = payload.model_dump(exclude_unset=True)

    if "content" in update_data:
        note.content = update_data["content"]
    if "comment" in update_data:
        comment = update_data["comment"]
        note.comment = comment.strip() if comment else None
    if "status" in update_data:
        note.status = update_data["status"]
        if update_data["status"] == GaNoteStatus.CLOSED:
            note.completed_at = note.completed_at or datetime.utcnow()
    if "priority" in update_data:
        note.priority = update_data["priority"]
    if "is_converted_to_task" in update_data:
        note.is_converted_to_task = update_data["is_converted_to_task"]
    if "is_discussed" in update_data:
        note.is_discussed = update_data["is_discussed"]
    if "one_h_marker" in update_data:
        await sync_note_task_marker(
            db, note, update_data["one_h_marker"], actor_email=user.email,
            marker_comment=payload.one_h_marker_comment,
        )
    if "next_week" in update_data:
        note.next_week = bool(update_data["next_week"])
    if "planned_for_date" in update_data:
        note.planned_for_date = update_data["planned_for_date"]
    planning_brief_changed = "planning_brief" in update_data and update_data["planning_brief"] != old_planning_brief
    if "planning_brief" in update_data:
        brief = payload.planning_brief
        note.planning_brief = brief.model_dump(mode="json") if brief else None

    planning_notifications = []
    if planning_brief_changed:
        add_audit_log(
            db=db,
            actor_user_id=user.id,
            entity_type="plan_note",
            entity_id=note.id,
            action="planning_brief_updated",
            before=old_planning_brief,
            after=note.planning_brief,
        )
        assigned_tasks = (
            await db.execute(
                select(Task.id, Task.assigned_to)
                .where(Task.plan_note_origin_id == note.id)
                .where(Task.is_active.is_(True))
                .where(Task.assigned_to.is_not(None))
            )
        ).all()
        notified_user_ids = set()
        for task_id, assigned_user_id in assigned_tasks:
            if assigned_user_id in notified_user_ids:
                continue
            notified_user_ids.add(assigned_user_id)
            if assigned_user_id == user.id:
                continue
            planning_notifications.append(
                add_notification(
                    db=db,
                    user_id=assigned_user_id,
                    type=NotificationType.status_change,
                    title="PX JAV planning updated",
                    body=notification_task_preview(note.content),
                    data={"task_id": str(task_id), "plan_note_id": str(note.id)},
                )
            )

    if "content" in update_data and update_data["content"] != old_content:
        new_task_title = _plan_note_task_title(note.content)
        old_default_description = _plan_note_default_task_description(old_content)
        new_default_description = _plan_note_default_task_description(note.content)

        linked_tasks = (
            await db.execute(select(Task).where(Task.plan_note_origin_id == note.id))
        ).scalars().all()

        for task in linked_tasks:
            task.title = new_task_title
            record_title_strike_events(
                db,
                task_id=task.id,
                actor_user_id=user.id,
                before_title=old_content,
                after_title=note.content,
            )
            if task.description == old_default_description:
                task.description = new_default_description
                record_description_strike_events(
                    db,
                    task_id=task.id,
                    actor_user_id=user.id,
                    before_description=old_default_description,
                    after_description=new_default_description,
                )

    await db.commit()
    for notification in planning_notifications:
        try:
            await publish_notification(user_id=notification.user_id, notification=notification)
        except Exception:
            pass
    await db.refresh(note)
    return _note_out(note)


def _same_timestamp(left: datetime, right: datetime) -> bool:
    def as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    return abs((as_utc(left) - as_utc(right)).total_seconds()) < 0.001


@router.patch("/{note_id}/task-bundle", response_model=PlanNoteTaskBundleResponse)
async def update_plan_note_task_bundle(
    note_id: uuid.UUID,
    payload: PlanNoteTaskBundleUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> PlanNoteTaskBundleResponse:
    """Atomically edit a PX JAV note and all independent assignee task copies."""

    note = (
        await db.execute(
            select(PlanNote)
            .options(selectinload(PlanNote.attachments))
            .where(PlanNote.id == note_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan note not found")
    await _ensure_note_access(note, user, db)

    existing_tasks = (
        await db.execute(select(Task).where(Task.plan_note_origin_id == note.id).order_by(Task.id))
    ).scalars().all()
    date_updates = {
        item.assignee_id: {"start_date": item.start_date, "due_date": item.due_date}
        for item in payload.assignee_states or []
        if payload.assignee_ids is None or item.assignee_id in payload.assignee_ids
    }
    await check_note_postponement_explanations(
        db,
        tasks=existing_tasks, updates_by_assignee=date_updates,
        explanations=payload.postponement_explanations,
    )
    affected_department_ids = {task.department_id for task in existing_tasks if task.department_id}
    if note.department_id:
        affected_department_ids.add(note.department_id)
    if payload.assignee_ids:
        affected_department_ids.update(
            department_id for department_id in (
                await db.execute(select(User.department_id).where(User.id.in_(payload.assignee_ids)))
            ).scalars().all() if department_id
        )
    await ensure_daily_baselines_for_departments(
        db, department_ids=affected_department_ids, actor=user,
        day=datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date(),
    )

    existing_tasks = (await db.execute(select(Task).where(Task.plan_note_origin_id == note.id)
        .order_by(Task.id).with_for_update().execution_options(populate_existing=True))).scalars().all()
    if any(task.department_id and task.department_id not in affected_department_ids for task in existing_tasks):
        raise HTTPException(status_code=409, detail="Përgjegjësi ndryshoi. Rifresko dhe provo përsëri.")
    postponements = await check_note_postponement_explanations(
        db,
        tasks=existing_tasks, updates_by_assignee=date_updates, explanations=payload.postponement_explanations,
    )
    try:
        marker_changed, shared_marker = note_bundle_marker_update(note, payload, existing_tasks)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    semantic_before = {task.id: task_semantic_state(task) for task in existing_tasks}

    if (
        payload.expected_updated_at is not None
        and note.updated_at is not None
        and not _same_timestamp(payload.expected_updated_at, note.updated_at)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This PX JAV note was changed by another user. Reload it before saving.",
        )

    fields_set = getattr(payload, "model_fields_set", getattr(payload, "__fields_set__", set()))
    old_content = note.content
    old_project_id = note.project_id
    if "content" in fields_set:
        cleaned_content = (payload.content or "").strip()
        if not cleaned_content:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Note text cannot be empty")
        note.content = cleaned_content
    if "one_h_marker" in fields_set:
        note.one_h_marker = payload.one_h_marker

    if "project_id" in fields_set:
        project = None
        if payload.project_id is not None:
            project = (await db.execute(select(Project).where(Project.id == payload.project_id))).scalar_one_or_none()
            if project is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        note.project_id = payload.project_id
        if project is not None:
            note.department_id = project.department_id

    if payload.assignee_ids is not None:
        if not payload.assignee_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A converted PX JAV note must keep at least one task assignee",
            )
        try:
            reconcile_result = await reconcile_plan_note_task_assignees(
                db,
                note=note,
                desired_assignee_ids=payload.assignee_ids,
                actor_user_id=user.id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        active_tasks = reconcile_result.active_tasks
    else:
        active_tasks = (
            await db.execute(
                select(Task)
                .where(Task.plan_note_origin_id == note.id, Task.is_active.is_(True))
                .order_by(Task.created_at.asc(), Task.id.asc())
                .with_for_update()
            )
        ).scalars().all()
        for task in active_tasks:
            task.fast_task_group_id = None
        reconcile_result = None

    title_before = {
        task.id: old_content if "content" in fields_set else task.title
        for task in active_tasks
    }
    description_before = {task.id: task.description for task in active_tasks}

    description_is_set = "description" in fields_set
    updated_count = apply_ga_note_shared_task_fields(
        active_tasks,
        title=_plan_note_task_title(note.content) if "content" in fields_set else None,
        description_is_set=description_is_set,
        description=payload.description,
    )
    if "project_id" in fields_set:
        for task in active_tasks:
            changed = False
            if task.project_id != payload.project_id:
                task.project_id = payload.project_id
                changed = True
            if project is not None and task.department_id != project.department_id:
                task.department_id = project.department_id
                changed = True
            if changed:
                updated_count += 1

    if payload.assignee_states is not None:
        try:
            from app.api.routers.tasks import _validate_waiting_confirmation_assignee

            status_before_by_task_id = {
                task.id: task.status.value if isinstance(task.status, TaskStatus) else str(task.status)
                for task in active_tasks
            }
            period_before_by_task_id = {
                task.id: getattr(task.finish_period, "value", task.finish_period)
                for task in active_tasks
            }
            for item in payload.assignee_states:
                if item.status == TaskStatus.WAITING_CONFIRMATION:
                    await _validate_waiting_confirmation_assignee(db, item.confirmation_assignee_id)
            updated_count += apply_ga_note_assignee_execution_states(
                active_tasks,
                [
                    GaNoteAssigneeExecutionState(
                        assignee_id=item.assignee_id,
                        status=item.status,
                        confirmation_assignee_id=item.confirmation_assignee_id,
                        start_date=item.start_date,
                        due_date=item.due_date,
                        finish_period=item.finish_period,
                        one_h_report_slot=item.one_h_report_slot,
                        one_h_report_slot_is_set="one_h_report_slot" in item.model_fields_set,
                        one_h_marker=item.one_h_marker,
                        one_h_marker_is_set="one_h_marker" in item.model_fields_set,
                        is_deadline_important=item.is_deadline_important,
                        priority=item.priority,
                        is_bllok=item.is_bllok,
                        is_1h_report=item.is_1h_report,
                        is_r1=item.is_r1,
                        is_personal=item.is_personal,
                    )
                    for item in payload.assignee_states
                ],
            )
            await sync_ga_note_assignee_report_slots(
                db,
                active_tasks,
                [
                    item.assignee_id
                    for item in payload.assignee_states
                    if "one_h_report_slot" in item.model_fields_set
                ],
            )
            tasks_by_assignee = {
                task.assigned_to: task
                for task in active_tasks
                if task.is_active and task.assigned_to is not None
            }
            today = datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date()
            for item in payload.assignee_states:
                matching_task = tasks_by_assignee.get(item.assignee_id)
                if matching_task is None:
                    continue
                if status_before_by_task_id.get(matching_task.id) == item.status.value:
                    next_period = item.finish_period.value if item.finish_period else None
                    if period_before_by_task_id.get(matching_task.id) != next_period:
                        await sync_task_daily_finish_period(
                            db,
                            task_id=matching_task.id,
                            day_date=today,
                            finish_period=next_period,
                        )
                    continue
                await upsert_explicit_task_daily_status(
                    db,
                    task_id=matching_task.id,
                    day_date=today,
                    status=item.status,
                    finish_period=item.finish_period.value if item.finish_period else None,
                    finish_period_is_set="finish_period" in item.model_fields_set,
                )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if "content" in fields_set and not description_is_set:
        old_default = _plan_note_default_task_description(old_content)
        new_default = _plan_note_default_task_description(note.content)
        for task in active_tasks:
            if task.description == old_default and task.description != new_default:
                task.description = new_default
                updated_count += 1

    for task in active_tasks:
        previous_title = title_before.get(task.id)
        current_title = note.content if "content" in fields_set else task.title
        if previous_title != current_title:
            record_title_strike_events(
                db,
                task_id=task.id,
                actor_user_id=user.id,
                before_title=previous_title,
                after_title=current_title,
            )
        previous_description = description_before.get(task.id)
        if previous_description != task.description:
            record_description_strike_events(
                db,
                task_id=task.id,
                actor_user_id=user.id,
                before_description=previous_description,
                after_description=task.description,
            )

    if payload.assignee_ids is not None or payload.assignee_states is not None:
        from app.api.routers.tasks import _clear_task_planner_exclusions_for_current_plan

        for task in active_tasks:
            if task.assigned_to is None:
                continue
            await _clear_task_planner_exclusions_for_current_plan(
                db,
                task=task,
                user_ids=[task.assigned_to],
            )

    if marker_changed:
        await sync_note_task_marker(
            db, note, shared_marker, actor_email=user.email,
            marker_comment=payload.one_h_marker_comment,
        )
        for task in active_tasks:
            task.one_h_marker = shared_marker

    semantic_tasks = {task.id: task for task in existing_tasks}
    semantic_tasks.update({task.id: task for task in active_tasks})
    if reconcile_result is not None:
        semantic_tasks.update({task.id: task for task in reconcile_result.deactivated_tasks})
    for task in semantic_tasks.values():
        after_state = task_semantic_state(task)
        before_state = semantic_before.get(task.id, {**after_state, "is_active": False, "assigned_to": None})
        old_owner = before_state.get("assigned_to") if before_state.get("is_active") else None
        new_owner = after_state.get("assigned_to") if after_state.get("is_active") else None
        record_task_semantic_events(
            db=db, task_id=task.id, actor_user_id=user.id,
            before=before_state, after=after_state,
            old_assignee_ids=[old_owner] if old_owner else [],
            new_assignee_ids=[new_owner] if new_owner else [],
            **postponements.get(task.id, {}),
        )
        await save_postponement_daily_explanation(
            db, task_id=task.id, user_ids={owner for owner in (old_owner, new_owner) if owner},
            explanation=postponements.get(task.id, {}),
        )

    add_audit_log(
        db=db,
        actor_user_id=user.id,
        entity_type="plan_note",
        entity_id=note.id,
        action="task_bundle_updated",
        before={
            "content": old_content,
            "project_id": str(old_project_id) if old_project_id else None,
        },
        after={
            "content": note.content,
            "project_id": str(note.project_id) if note.project_id else None,
            "assignees": [str(task.assigned_to) for task in active_tasks if task.assigned_to],
        },
    )

    created_notifications = []
    if reconcile_result is not None:
        await record_initial_marker_comments(db, reconcile_result.created_tasks, actor_email=user.email)
        for created_task in reconcile_result.created_tasks:
            if created_task.assigned_to is not None:
                created_notifications.append(
                    add_notification(
                        db=db,
                        user_id=created_task.assigned_to,
                        type=NotificationType.assignment,
                        title="Task assigned",
                        body=notification_task_preview(created_task.title),
                        data={"task_id": str(created_task.id)},
                    )
                )

    await db.commit()
    for notification in created_notifications:
        try:
            await publish_notification(user_id=notification.user_id, notification=notification)
        except Exception:
            pass
    await db.refresh(note)
    return PlanNoteTaskBundleResponse(
        note=_note_out(note),
        active_task_ids=[task.id for task in active_tasks],
        assignee_ids=[task.assigned_to for task in active_tasks if task.assigned_to is not None],
        created_count=reconcile_result.created_count if reconcile_result else 0,
        deactivated_count=reconcile_result.deactivated_count if reconcile_result else 0,
        deduplicated_count=reconcile_result.deduplicated_count if reconcile_result else 0,
        updated_count=updated_count,
    )


@router.patch("/{note_id}/task-deadline", response_model=PlanNoteTaskDeadlineResponse)
async def update_plan_note_task_deadline(
    note_id: uuid.UUID,
    payload: PlanNoteTaskDeadlineUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> PlanNoteTaskDeadlineResponse:
    note = await _get_note_or_404(note_id, db)
    await _ensure_note_access(note, user, db)

    linked_tasks = (
        await db.execute(
            select(Task).where(Task.plan_note_origin_id == note_id).where(Task.is_active.is_(True))
        )
    ).scalars().all()

    if not linked_tasks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active tasks found for this plan note",
        )

    can_edit = False
    forbidden_error: HTTPException | None = None
    for task in linked_tasks:
        try:
            ensure_task_editor(user, task)
            can_edit = True
            break
        except HTTPException as exc:
            forbidden_error = exc
            continue
    if not can_edit:
        raise forbidden_error or HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    new_due_date = None if payload.clear else payload.due_date
    update_due = payload.clear or payload.due_date is not None
    update_important = payload.is_deadline_important is not None

    if not update_due and not update_important:
        return PlanNoteTaskDeadlineResponse(
            updated_count=0,
            due_date=linked_tasks[0].due_date,
            is_deadline_important=linked_tasks[0].is_deadline_important,
        )

    updates = {"due_date": new_due_date} if update_due else {}
    await check_note_postponement_explanations(
        db,
        tasks=linked_tasks, updates_by_assignee={task.assigned_to: updates for task in linked_tasks},
        explanations=payload.postponement_explanations,
    )
    await ensure_daily_baselines_for_departments(
        db, department_ids={task.department_id for task in linked_tasks}, actor=user,
        day=datetime.now(ZoneInfo(settings.REALIZATION_TIMEZONE)).date(),
    )
    linked_tasks = (await db.execute(select(Task).where(
        Task.plan_note_origin_id == note_id, Task.is_active.is_(True),
    ).order_by(Task.id).with_for_update().execution_options(populate_existing=True))).scalars().all()
    if not linked_tasks:
        raise HTTPException(status_code=404, detail="No active tasks found for this plan note")
    postponements = await check_note_postponement_explanations(
        db,
        tasks=linked_tasks, updates_by_assignee={task.assigned_to: updates for task in linked_tasks},
        explanations=payload.postponement_explanations,
    )

    updated_count = 0
    for task in linked_tasks:
        before = {
            "due_date": task.due_date.isoformat() if task.due_date else None,
            "is_deadline_important": task.is_deadline_important,
        }
        changed = False

        if update_due:
            if (
                task.due_date is not None
                and new_due_date is not None
                and new_due_date != task.due_date
                and task.original_due_date is None
            ):
                task.original_due_date = task.due_date
            if task.due_date != new_due_date:
                task.due_date = new_due_date
                changed = True

        if update_important and task.is_deadline_important != payload.is_deadline_important:
            task.is_deadline_important = bool(payload.is_deadline_important)
            changed = True

        if changed:
            updated_count += 1
            after = {
                "due_date": task.due_date.isoformat() if task.due_date else None,
                "is_deadline_important": task.is_deadline_important,
            }
            record_task_semantic_events(
                db=db, task_id=task.id, actor_user_id=user.id, before=before, after=after,
                old_assignee_ids=[task.assigned_to] if task.assigned_to else [],
                new_assignee_ids=[task.assigned_to] if task.assigned_to else [],
                **postponements.get(task.id, {}),
            )
            await save_postponement_daily_explanation(
                db, task_id=task.id, user_ids={task.assigned_to or user.id}, explanation=postponements.get(task.id, {}),
            )
            add_audit_log(
                db=db,
                actor_user_id=user.id,
                entity_type="task",
                entity_id=task.id,
                action="plan_note_deadline_update",
                before=before,
                after=after,
            )

    await db.commit()

    sample = linked_tasks[0]
    return PlanNoteTaskDeadlineResponse(
        updated_count=updated_count,
        due_date=sample.due_date,
        is_deadline_important=sample.is_deadline_important,
    )


@router.post("/{note_id}/mark-waiting-done", response_model=MarkWaitingDoneResponse)
async def mark_plan_note_waiting_tasks_done(
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> MarkWaitingDoneResponse:
    note = await _get_note_or_404(note_id, db)
    await _ensure_note_access(note, user, db)

    tasks = (await db.execute(select(Task).where(Task.plan_note_origin_id == note_id))).scalars().all()

    waiting = [task for task in tasks if task.status == TaskStatus.WAITING_CONFIRMATION]
    comments = {
        row.task_id: (row.comment or "").strip()
        for row in (
            await db.execute(
                select(TaskUserComment).where(
                    TaskUserComment.task_id.in_([task.id for task in waiting]),
                    TaskUserComment.user_id == user.id,
                )
            )
        ).scalars().all()
    } if waiting else {}
    if any(task.assigned_to != user.id or not comments.get(task.id) for task in waiting):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "RLZ_TASK_COMMENT_REQUIRED",
                "message": "Para mbylljes, shto komentin personal për secilën detyrë; përjashtimet mbyllen individualisht me arsye.",
            },
        )

    updated_count = 0
    for task in tasks:
        if task.status == TaskStatus.WAITING_CONFIRMATION:
            task.status = TaskStatus.DONE
            task.completed_at = task.completed_at or datetime.now(timezone.utc)
            await upsert_explicit_task_daily_status(
                db,
                task_id=task.id,
                day_date=datetime.now(timezone.utc).date(),
                status=TaskStatus.DONE,
                finish_period=task.finish_period.value if hasattr(task.finish_period, "value") else task.finish_period,
            )
            updated_count += 1

    await db.commit()

    return MarkWaitingDoneResponse(
        updated_count=updated_count,
        skipped_count=len(tasks) - updated_count,
    )


@router.get("/{note_id}", response_model=PlanNoteOut)
async def get_plan_note(
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> PlanNoteOut:
    note = (
        await db.execute(
            select(PlanNote).options(selectinload(PlanNote.attachments)).where(PlanNote.id == note_id)
        )
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan note not found")
    await _ensure_note_access(note, user, db)
    return _note_out(note)


@router.post("/{note_id}/attachments", response_model=list[PlanNoteAttachmentOut], status_code=status.HTTP_201_CREATED)
async def upload_plan_note_attachments(
    note_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[PlanNoteAttachmentOut]:
    note = await _get_note_or_404(note_id, db)
    return await _save_plan_note_attachments(note, files, db, user)


@router.post("/attachments", response_model=list[PlanNoteAttachmentOut], status_code=status.HTTP_201_CREATED)
async def upload_plan_note_attachments_by_form(
    note_id: uuid.UUID = Form(...),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[PlanNoteAttachmentOut]:
    note = await _get_note_or_404(note_id, db)
    return await _save_plan_note_attachments(note, files, db, user)


@router.get("/attachments/{attachment_id}")
async def download_plan_note_attachment(
    attachment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    attachment = (
        await db.execute(
            select(PlanNoteAttachment)
            .options(selectinload(PlanNoteAttachment.note))
            .where(PlanNoteAttachment.id == attachment_id)
        )
    ).scalar_one_or_none()
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    await _ensure_note_access(attachment.note, user, db)

    upload_base = _plan_note_upload_base_dir()
    stored_path = upload_base / str(attachment.note_id) / attachment.stored_filename
    if not stored_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found on server")

    from fastapi.responses import FileResponse

    return FileResponse(
        stored_path,
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.original_filename,
    )


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_plan_note_attachment(
    attachment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    attachment = (
        await db.execute(
            select(PlanNoteAttachment)
            .options(selectinload(PlanNoteAttachment.note))
            .where(PlanNoteAttachment.id == attachment_id)
        )
    ).scalar_one_or_none()
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    await _ensure_note_access(attachment.note, user, db)

    upload_base = _plan_note_upload_base_dir()
    note_dir = upload_base / str(attachment.note_id)
    stored_path = note_dir / attachment.stored_filename

    await db.delete(attachment)
    await db.commit()

    try:
        if stored_path.exists():
            stored_path.unlink()
        if note_dir.exists() and not any(note_dir.iterdir()):
            note_dir.rmdir()
    except OSError:
        pass
