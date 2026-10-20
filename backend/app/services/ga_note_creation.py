from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.access import ensure_department_access
from app.models.enums import GaNoteType, GaNoteStatus, UserRole
from app.models.ga_note import GaNote
from app.models.project import Project
from app.models.user import User
from app.schemas.ga_note import GaNoteCreate
from app.services.task_marker import current_effective_marker_date, marker_is_by_ga, normalize_marker_comment


async def build_ga_note(db: AsyncSession, user: User, payload: GaNoteCreate) -> GaNote:
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


    note = GaNote(
        content=payload.content,
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
        project_id=payload.project_id,
        department_id=department_id,
    )
    db.add(note)
    return note
