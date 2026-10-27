from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from datetime import datetime
from pydantic import BaseModel
from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.access import ensure_department_access, ensure_manager_or_admin, ensure_project_creator
from app.api.deps import get_current_user
from app.db import get_db
from app.models.enums import ProjectPhaseStatus, ProjectType, TaskPriority, TaskStatus, UserRole
from app.models.checklist import Checklist
from app.models.checklist_item import ChecklistItem, ChecklistItemAssignee
from app.models.department import Department
from app.models.ga_note import GaNote
from app.models.internal_note import InternalNote
from app.models.meeting import Meeting
from app.models.project import Project
from app.models.project_planner_exclusion import ProjectPlannerExclusion
from app.models.task import Task
from app.models.task_template import TaskTemplate
from app.models.user import User
from app.models.vs_workflow_item import VsWorkflowItem
from app.models.task_assignee import TaskAssignee
from app.schemas.project import ProjectCreate, ProjectOut, ProjectRemoveFromDayRequest, ProjectUpdate
from app.schemas.vs_workflow_item import VsWorkflowItemOut, VsWorkflowItemUpdate
from app.services.workflow_service import (
    initialize_vs_workflow,
    get_active_workflow_items,
    dependency_item_ids_from_info,
)
from app.services.project_display_title import build_project_display_title_map
from app.services.audit import add_audit_log
from app.services.daily_realization_baseline import ensure_daily_baselines_for_departments
from app.services.project_classification import (
    has_mst_identity,
    is_vs_or_vl_project,
)
from datetime import datetime, timedelta


router = APIRouter()


class ProjectTitleLookupOut(BaseModel):
    id: uuid.UUID
    title: str
    display_title: str | None = None
    project_type: str | None = None
    total_products: int | None = None
    department_id: uuid.UUID | None = None
    due_date: datetime | None = None
    is_active: bool = True


@router.get("/lookup", response_model=list[ProjectTitleLookupOut])
async def lookup_project_titles(
    ids: list[uuid.UUID] | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[ProjectTitleLookupOut]:
    # Title-only lookup for UI display (safe to return across departments).
    if not ids:
        return []
    projects = (
        await db.execute(
            select(Project)
            .where(Project.is_template == False)
            .where(Project.id.in_(list(dict.fromkeys(ids))))
        )
    ).scalars().all()
    display_title_by_id = await build_project_display_title_map(db, projects)
    return [
        ProjectTitleLookupOut(
            id=project.id,
            title=project.title,
            display_title=display_title_by_id.get(project.id) or project.title,
            project_type=project.project_type,
            total_products=project.total_products,
            department_id=project.department_id,
            due_date=project.due_date,
            is_active=project.is_active,
        )
        for project in projects
        if project.title
    ]


def _project_to_out(project: Project, display_title: str | None = None) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        title=project.title,
        display_title=display_title,
        description=project.description,
        department_id=project.department_id,
        manager_id=project.manager_id,
        created_by=project.created_by,
        project_type=project.project_type,
        current_phase=project.current_phase,
        status=project.status,
        progress_percentage=project.progress_percentage,
        total_products=project.total_products,
        is_template=project.is_template,
        is_active=project.is_active,
        start_date=project.start_date,
        due_date=project.due_date,
        completed_at=project.completed_at,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


async def _copy_tasks_from_template_project(
    db: AsyncSession, project: Project, created_by_id: uuid.UUID
) -> None:
    """Copy tasks from a VS/VL template project to a newly created project."""
    # Find the template project (is_template=True and contains VS or VL in title)
    stmt = select(Project).where(
        Project.is_template == True,
    )
    template_projects = (await db.execute(stmt)).scalars().all()
    
    # Find the best matching VS/VL template project based on the new project's title
    template_project = None
    project_title_upper = project.title.upper()
    
    # First, try to find an exact match or closest match
    vs_vl_templates = [tp for tp in template_projects if is_vs_or_vl_project(tp)]
    
    if not vs_vl_templates:
        return
    
    # Match logic:
    # 1. If project title contains "VOGEL" or "TEMPLATE 2", use "VS/VL PROJEKT I VOGEL TEMPLATE 2"
    # 2. If project title contains "MADH", use "VS/VL PROJEKT I MADH"
    # 3. Otherwise, prefer "MADH" (large project) as default
    
    if "VOGEL" in project_title_upper or "TEMPLATE 2" in project_title_upper:
        # Look for the small project template
        for tp in vs_vl_templates:
            if "VOGEL" in tp.title.upper() or "TEMPLATE 2" in tp.title.upper():
                template_project = tp
                break
    elif "MADH" in project_title_upper:
        # Look for the large project template
        for tp in vs_vl_templates:
            if "MADH" in tp.title.upper():
                template_project = tp
                break
    
    # If no specific match found, use the first "MADH" template, or any VS/VL template
    if not template_project:
        for tp in vs_vl_templates:
            if "MADH" in tp.title.upper():
                template_project = tp
                break
        
        if not template_project:
            template_project = vs_vl_templates[0]
    
    if not template_project:
        return
    
    # Fetch all tasks from the template project
    template_tasks = (await db.execute(
        select(Task).where(Task.project_id == template_project.id).order_by(Task.created_at)
    )).scalars().all()
    
    if not template_tasks:
        return
    
    # Map old task IDs to new task IDs for dependency linking
    old_to_new_task_id: dict[uuid.UUID, uuid.UUID] = {}
    
    # Fetch all task assignees from template tasks
    template_task_ids = [t.id for t in template_tasks]
    template_assignees = {}
    if template_task_ids:
        assignee_records = (await db.execute(
            select(TaskAssignee).where(TaskAssignee.task_id.in_(template_task_ids))
        )).scalars().all()
        for assignee in assignee_records:
            if assignee.task_id not in template_assignees:
                template_assignees[assignee.task_id] = []
            template_assignees[assignee.task_id].append(assignee.user_id)
    
    for template_task in template_tasks:
        # Create new task based on template - copy ALL fields
        new_task = Task(
            title=template_task.title,
            description=template_task.description,
            internal_notes=template_task.internal_notes,
            priority=template_task.priority or "NORMAL",
            status=template_task.status or "TODO",  # Copy status from template
            phase=template_task.phase or "AMAZON",
            project_id=project.id,
            department_id=project.department_id,
            created_by=created_by_id,
            # Copy all date fields
            start_date=template_task.start_date,
            due_date=template_task.due_date,  # Copy due_date from template
            # Copy all other fields
            finish_period=template_task.finish_period,
            progress_percentage=template_task.progress_percentage or 0,
            daily_products=template_task.daily_products,
            assigned_to=template_task.assigned_to,  # Copy assigned_to from template
            is_deadline_important=template_task.is_deadline_important,
            is_bllok=template_task.is_bllok,
            is_1h_report=template_task.is_1h_report,
            is_r1=template_task.is_r1,
            is_personal=template_task.is_personal,
            is_active=template_task.is_active,
        )
        db.add(new_task)
        await db.flush()  # Get the new task ID
        
        old_to_new_task_id[template_task.id] = new_task.id
        
        # Copy task assignees (multiple assignees from task_assignees table)
        if template_task.id in template_assignees:
            assignee_values = [
                {"task_id": new_task.id, "user_id": user_id}
                for user_id in template_assignees[template_task.id]
            ]
            if assignee_values:
                await db.execute(insert(TaskAssignee), assignee_values)
    
    # Second pass: set dependencies using the mapping
    for template_task in template_tasks:
        if template_task.dependency_task_id and template_task.dependency_task_id in old_to_new_task_id:
            new_task_id = old_to_new_task_id[template_task.id]
            new_dependency_id = old_to_new_task_id[template_task.dependency_task_id]
            await db.execute(
                update(Task).where(Task.id == new_task_id).values(dependency_task_id=new_dependency_id)
            )


async def _copy_project_template_data(
    db: AsyncSession,
    project: Project,
    created_by_id: uuid.UUID,
    template_project: Project,
    *,
    default_phase: ProjectPhaseStatus,
    reset_task_status_to_todo: bool,
) -> None:
    if project.is_template or template_project.id == project.id:
        return

    template_tasks = (
        await db.execute(
            select(Task).where(Task.project_id == template_project.id).order_by(Task.created_at)
        )
    ).scalars().all()

    template_task_ids = [task.id for task in template_tasks]
    task_assignees_by_task_id: dict[uuid.UUID, list[uuid.UUID]] = {}
    if template_task_ids:
        assignee_records = (
            await db.execute(select(TaskAssignee).where(TaskAssignee.task_id.in_(template_task_ids)))
        ).scalars().all()
        for assignee in assignee_records:
            task_assignees_by_task_id.setdefault(assignee.task_id, []).append(assignee.user_id)

    old_to_new_task_id: dict[uuid.UUID, uuid.UUID] = {}
    for template_task in template_tasks:
        new_task = Task(
            title=template_task.title,
            description=template_task.description,
            internal_notes=template_task.internal_notes,
            priority=template_task.priority or TaskPriority.NORMAL,
            status=TaskStatus.TODO if reset_task_status_to_todo else (template_task.status or TaskStatus.TODO),
            phase=template_task.phase or project.current_phase or default_phase,
            project_id=project.id,
            department_id=project.department_id,
            created_by=created_by_id,
            start_date=template_task.start_date,
            due_date=template_task.due_date,
            finish_period=template_task.finish_period,
            progress_percentage=template_task.progress_percentage or 0,
            daily_products=template_task.daily_products,
            assigned_to=template_task.assigned_to,
            is_deadline_important=template_task.is_deadline_important,
            is_bllok=template_task.is_bllok,
            is_1h_report=template_task.is_1h_report,
            is_r1=template_task.is_r1,
            is_personal=template_task.is_personal,
            is_active=template_task.is_active,
        )
        db.add(new_task)
        await db.flush()
        old_to_new_task_id[template_task.id] = new_task.id

        task_assignee_values = [
            {"task_id": new_task.id, "user_id": user_id}
            for user_id in task_assignees_by_task_id.get(template_task.id, [])
        ]
        if task_assignee_values:
            await db.execute(insert(TaskAssignee), task_assignee_values)

    for template_task in template_tasks:
        if template_task.dependency_task_id and template_task.dependency_task_id in old_to_new_task_id:
            new_task_id = old_to_new_task_id[template_task.id]
            new_dependency_id = old_to_new_task_id[template_task.dependency_task_id]
            await db.execute(
                update(Task).where(Task.id == new_task_id).values(dependency_task_id=new_dependency_id)
            )

    template_checklists = (
        await db.execute(
            select(Checklist).where(Checklist.project_id == template_project.id).order_by(Checklist.created_at)
        )
    ).scalars().all()
    if not template_checklists:
        return

    template_checklist_ids = [checklist.id for checklist in template_checklists]
    template_items = []
    if template_checklist_ids:
        template_items = (
            await db.execute(
                select(ChecklistItem)
                .where(ChecklistItem.checklist_id.in_(template_checklist_ids))
                .order_by(ChecklistItem.position, ChecklistItem.id)
            )
        ).scalars().all()

    item_assignees_by_item_id: dict[uuid.UUID, list[uuid.UUID]] = {}
    template_item_ids = [item.id for item in template_items]
    if template_item_ids:
        item_assignee_records = (
            await db.execute(
                select(ChecklistItemAssignee).where(
                    ChecklistItemAssignee.checklist_item_id.in_(template_item_ids)
                )
            )
        ).scalars().all()
        for assignee in item_assignee_records:
            item_assignees_by_item_id.setdefault(assignee.checklist_item_id, []).append(assignee.user_id)

    items_by_checklist_id: dict[uuid.UUID, list[ChecklistItem]] = {}
    for item in template_items:
        items_by_checklist_id.setdefault(item.checklist_id, []).append(item)

    for template_checklist in template_checklists:
        new_task_id = (
            old_to_new_task_id.get(template_checklist.task_id)
            if template_checklist.task_id is not None
            else None
        )
        if template_checklist.task_id is not None and new_task_id is None:
            continue

        new_checklist = Checklist(
            title=template_checklist.title,
            task_id=new_task_id,
            project_id=project.id,
            note=template_checklist.note,
            default_owner=template_checklist.default_owner,
            default_time=template_checklist.default_time,
            group_key=template_checklist.group_key,
            columns=template_checklist.columns,
            position=template_checklist.position,
        )
        db.add(new_checklist)
        await db.flush()

        for template_item in items_by_checklist_id.get(template_checklist.id, []):
            new_item = ChecklistItem(
                checklist_id=new_checklist.id,
                item_type=template_item.item_type,
                position=template_item.position,
                path=template_item.path,
                keyword=template_item.keyword,
                description=template_item.description,
                category=template_item.category,
                original=template_item.original,
                day=template_item.day,
                owner=template_item.owner,
                time=template_item.time,
                title=template_item.title,
                comment=template_item.comment,
                is_checked=template_item.is_checked,
            )
            db.add(new_item)
            await db.flush()

            item_assignee_values = [
                {"checklist_item_id": new_item.id, "user_id": user_id}
                for user_id in item_assignees_by_item_id.get(template_item.id, [])
            ]
            if item_assignee_values:
                await db.execute(insert(ChecklistItemAssignee), item_assignee_values)


DEV_PHASES = [
    ProjectPhaseStatus.MEETINGS,
    ProjectPhaseStatus.PLANNING,
    ProjectPhaseStatus.DEVELOPMENT,
    ProjectPhaseStatus.TESTING,
    ProjectPhaseStatus.DOCUMENTATION,
    ProjectPhaseStatus.CLOSED,
]

MST_PHASES = [
    ProjectPhaseStatus.PLANNING,
    ProjectPhaseStatus.PRODUCT,
    ProjectPhaseStatus.CONTROL,
    ProjectPhaseStatus.FINAL,
    ProjectPhaseStatus.CLOSED,
]

VS_PHASES = [
    ProjectPhaseStatus.PLANNING,
    ProjectPhaseStatus.AMAZON,
    ProjectPhaseStatus.CHECK,
    ProjectPhaseStatus.DREAMROBOT,
    ProjectPhaseStatus.CLOSED,
]

# Standard/Fallback sequence
PHASE_SEQUENCE = [
    ProjectPhaseStatus.MEETINGS,
    ProjectPhaseStatus.PLANNING,
    ProjectPhaseStatus.DEVELOPMENT,
    ProjectPhaseStatus.TESTING,
    ProjectPhaseStatus.DOCUMENTATION,
    ProjectPhaseStatus.PRODUCT,
    ProjectPhaseStatus.CONTROL,
    ProjectPhaseStatus.FINAL,
    ProjectPhaseStatus.AMAZON,
    ProjectPhaseStatus.CHECK,
    ProjectPhaseStatus.DREAMROBOT,
    ProjectPhaseStatus.CLOSED,
]


def get_project_sequence(project: Project, department_name: str | None = None) -> list[ProjectPhaseStatus]:
    if project.project_type == ProjectType.MST.value:
        return MST_PHASES
    if project.project_type in {ProjectType.GENERAL.value, ProjectType.GD_DEVELOPMENT.value}:
        return DEV_PHASES

    # Legacy fallback based on title/department
    department_label = (department_name or "").upper()
    if is_vs_or_vl_project(project):
        return VS_PHASES
    if has_mst_identity(project):
        return MST_PHASES
    if department_label in {"PROJECT CONTENT MANAGER", "GRAPHIC DESIGN", "PCM", "GD"}:
        return MST_PHASES
    return DEV_PHASES


def phase_index(phase: ProjectPhaseStatus) -> int:
    try:
        return PHASE_SEQUENCE.index(phase)
    except ValueError:
        return -1


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    department_id: uuid.UUID | None = None,
    include_all_departments: bool = False,
    include_templates: bool = False,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[ProjectOut]:
    stmt = select(Project)
    
    # Exclude template projects by default
    if not include_templates:
        stmt = stmt.where(Project.is_template == False)
    
    if department_id:
        stmt = stmt.where(Project.department_id == department_id)

    projects = (await db.execute(stmt.order_by(Project.created_at))).scalars().all()
    projects_for_display_title = [project for project in projects if not project.is_template]
    display_title_by_id: dict[uuid.UUID, str] = {}
    if projects_for_display_title:
        display_title_by_id = await build_project_display_title_map(
            db, projects_for_display_title, department_id=department_id
        )
    return [_project_to_out(p, display_title_by_id.get(p.id) or p.title) for p in projects]


@router.post("", response_model=ProjectOut)
async def create_project(
    payload: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ProjectOut:
    # Allow Admin, Manager, and Staff to create projects
    ensure_project_creator(user)
    ensure_department_access(user, payload.department_id)

    if payload.manager_id is not None:
        manager = (await db.execute(select(User).where(User.id == payload.manager_id))).scalar_one_or_none()
        if manager is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found")
        if manager.department_id != payload.department_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Manager must be in department")

    current_phase = payload.current_phase or ProjectPhaseStatus.MEETINGS
    status_value = payload.status or TaskStatus.TODO
    project_type_value = payload.project_type.value if payload.project_type else None
    template_project: Project | None = None
    if payload.template_project_id is not None:
        template_project = (
            await db.execute(select(Project).where(Project.id == payload.template_project_id))
        ).scalar_one_or_none()
        if template_project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template project not found")
        if template_project.department_id is not None and template_project.department_id != payload.department_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Template project department mismatch")
        if not template_project.is_template:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected project is not a template")
        if project_type_value is None:
            project_type_value = ProjectType.MST.value
        elif project_type_value != ProjectType.MST.value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Template project requires MST type")
        if template_project.project_type is not None and template_project.project_type != ProjectType.MST.value:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Template project must be MST type")
        if template_project.project_type is None and not has_mst_identity(template_project):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Template project must be MST type")
    if project_type_value == ProjectType.GD_DEVELOPMENT.value and template_project is None:
        gd_template_stmt = select(Project).where(
            Project.is_template == True,
            Project.project_type == ProjectType.GD_DEVELOPMENT.value,
        )
        if payload.department_id is not None:
            gd_template_stmt = gd_template_stmt.where(Project.department_id == payload.department_id)
        template_project = (
            await db.execute(gd_template_stmt.order_by(Project.created_at))
        ).scalars().first()

    project = Project(
        title=payload.title,
        description=payload.description,
        department_id=payload.department_id,
        manager_id=payload.manager_id,
        created_by=user.id,
        project_type=project_type_value,
        current_phase=current_phase,
        status=status_value,
        progress_percentage=payload.progress_percentage or 0,
        total_products=payload.total_products,
        start_date=payload.start_date,
        due_date=payload.due_date,
        completed_at=payload.completed_at,
    )
    db.add(project)
    await db.flush() # Ensure project ID is generated
    
    # Trigger VS Amazon Workflow if applicable
    title_upper = project.title.upper()
    if "VS/VL AMAZON" in title_upper or "VS AMAZON" in title_upper:
        await initialize_vs_workflow(db, project.id)
    
    # Copy tasks from template project if this is a VS/VL project
    is_vs_vl_project = is_vs_or_vl_project(project)
    if is_vs_vl_project:
        await _copy_tasks_from_template_project(db, project, user.id)
    # Copy tasks from MST template project only if explicitly selected
    if project.project_type == ProjectType.MST.value and template_project is not None:
        await _copy_project_template_data(
            db,
            project,
            user.id,
            template_project,
            default_phase=ProjectPhaseStatus.PLANNING,
            reset_task_status_to_todo=True,
        )
    if project.project_type == ProjectType.GD_DEVELOPMENT.value and template_project is not None:
        await _copy_project_template_data(
            db,
            project,
            user.id,
            template_project,
            default_phase=ProjectPhaseStatus.MEETINGS,
            reset_task_status_to_todo=True,
        )
    
    await db.commit()
    await db.refresh(project)
    display_title_by_id = await build_project_display_title_map(db, [project])
    return _project_to_out(project, display_title_by_id.get(project.id) or project.title)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ProjectOut:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    display_title_by_id = await build_project_display_title_map(db, [project])
    return _project_to_out(project, display_title_by_id.get(project.id) or project.title)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ProjectOut:
    ensure_project_creator(user)
    if payload.is_active is not None:
        ensure_manager_or_admin(user)
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.department_id is not None:
        ensure_department_access(user, project.department_id)

    if payload.title is not None:
        project.title = payload.title
    if payload.description is not None:
        project.description = payload.description
    if payload.manager_id is not None:
        manager = (await db.execute(select(User).where(User.id == payload.manager_id))).scalar_one_or_none()
        if manager is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager not found")
        if project.department_id is not None and manager.department_id != project.department_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Manager must be in department")
        project.manager_id = payload.manager_id
    if payload.project_type is not None:
        project.project_type = payload.project_type.value
    if payload.current_phase is not None:
        current_idx = phase_index(project.current_phase)
        next_idx = phase_index(payload.current_phase)
        if current_idx == -1 or next_idx == -1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid project phase")
        if next_idx > current_idx:  # Allow moving backward, but not skipping forward
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot skip phases forward. Use advance-phase endpoint to move to the next phase.",
            )
        project.current_phase = payload.current_phase
        if payload.current_phase == ProjectPhaseStatus.PLANNING and next_idx < current_idx:
            checklist_ids = select(Checklist.id).where(Checklist.project_id == project.id)
            await db.execute(
                update(ChecklistItem)
                .where(ChecklistItem.checklist_id.in_(checklist_ids))
                .values(is_checked=False)
            )
    if payload.status is not None:
        project.status = payload.status
    if payload.progress_percentage is not None:
        project.progress_percentage = payload.progress_percentage
    if payload.total_products is not None:
        project.total_products = payload.total_products
    if payload.is_template is not None:
        project.is_template = payload.is_template
    if payload.is_active is not None:
        project.is_active = payload.is_active
    if payload.start_date is not None:
        project.start_date = payload.start_date
    if payload.due_date is not None:
        project.due_date = payload.due_date
    if payload.completed_at is not None:
        project.completed_at = payload.completed_at

    await db.commit()
    await db.refresh(project)
    display_title_by_id = await build_project_display_title_map(db, [project])
    return _project_to_out(project, display_title_by_id.get(project.id) or project.title)


@router.post("/{project_id}/advance-phase", response_model=ProjectOut)
async def advance_project_phase(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ProjectOut:
    # Allow any role to advance/close phases
    ensure_project_creator(user)
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.department_id is not None:
        ensure_department_access(user, project.department_id)

    department_name = None
    if project.department_id is not None:
        department = (
            await db.execute(select(Department).where(Department.id == project.department_id))
        ).scalar_one_or_none()
        department_name = department.name if department else None

    sequence = get_project_sequence(project, department_name)
    try:
        current_idx = sequence.index(project.current_phase)
    except ValueError:
        # If not in its specific sequence, fallback to general
        try:
            current_idx = PHASE_SEQUENCE.index(project.current_phase)
            sequence = PHASE_SEQUENCE
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid project phase")
            
    if current_idx >= len(sequence) - 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project is already in the final phase")

    open_tasks = (
        await db.execute(
            select(func.count(Task.id)).where(
                Task.project_id == project.id,
                Task.phase == project.current_phase,
                Task.status != TaskStatus.DONE.value,
            )
        )
    ).scalar_one()
    unchecked_items = 0
    checklist_query = (
        select(func.count(ChecklistItem.id))
        .join(Checklist, ChecklistItem.checklist_id == Checklist.id)
        .where(
            Checklist.project_id == project.id,
            ChecklistItem.is_checked.is_(False),
        )
    )
    checklist_filter = None
    if sequence == MST_PHASES:
        if project.current_phase == ProjectPhaseStatus.PLANNING:
            checklist_filter = or_(
                ChecklistItem.path.in_(["project acceptance", "ga/dv meeting"]),
            )
        elif project.current_phase == ProjectPhaseStatus.PRODUCT:
            checklist_filter = ChecklistItem.path.in_(["propozim ko1/ko2", "punimi"])
        elif project.current_phase == ProjectPhaseStatus.CONTROL:
            checklist_filter = ChecklistItem.path == "control ko1/ko2"
        elif project.current_phase == ProjectPhaseStatus.FINAL:
            checklist_filter = ChecklistItem.path == "finalization"
    else:
        checklist_filter = ChecklistItem.path == project.current_phase
    unchecked_items = (await db.execute(checklist_query.where(checklist_filter))).scalar_one()
    if open_tasks or unchecked_items:
        detail = "Complete all tasks and checklist items before advancing the phase."
        if open_tasks and unchecked_items:
            detail = f"Cannot advance phase: {open_tasks} open tasks and {unchecked_items} unchecked checklist items."
        elif open_tasks:
            detail = f"Cannot advance phase: {open_tasks} open tasks."
        else:
            detail = f"Cannot advance phase: {unchecked_items} unchecked checklist items."
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    project.current_phase = sequence[current_idx + 1]
    await db.commit()
    await db.refresh(project)
    display_title_by_id = await build_project_display_title_map(db, [project])
    return _project_to_out(project, display_title_by_id.get(project.id) or project.title)


@router.post("/{project_id}/close", response_model=ProjectOut)
async def close_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> ProjectOut:
    ensure_project_creator(user)
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.department_id is not None:
        ensure_department_access(user, project.department_id)

    project.current_phase = ProjectPhaseStatus.CLOSED
    project.status = TaskStatus.DONE
    project.completed_at = datetime.utcnow()

    await db.commit()
    await db.refresh(project)
    display_title_by_id = await build_project_display_title_map(db, [project])
    return _project_to_out(project, display_title_by_id.get(project.id) or project.title)


@router.delete("/{project_id}", status_code=status.HTTP_200_OK)
async def delete_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> dict:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can delete projects")
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.department_id is not None:
        ensure_department_access(user, project.department_id)

    await db.execute(delete(Task).where(Task.project_id == project.id))
    await db.execute(delete(TaskTemplate).where(TaskTemplate.project_id == project.id))
    await db.execute(delete(Meeting).where(Meeting.project_id == project.id))
    await db.execute(delete(GaNote).where(GaNote.project_id == project.id))
    await db.execute(delete(InternalNote).where(InternalNote.project_id == project.id))

    await db.delete(project)
    await db.commit()
    return {"status": "deleted"}


@router.post("/{project_id}/remove-from-day", response_model=None)
async def remove_project_from_day(
    project_id: uuid.UUID,
    payload: ProjectRemoveFromDayRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can remove projects from days")
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.department_id is not None:
        ensure_department_access(user, project.department_id)

    slot = (payload.time_slot or "ALL").strip().upper()
    if slot not in ("AM", "PM", "ALL"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid time slot")

    existing = (
        await db.execute(
            select(ProjectPlannerExclusion).where(
                ProjectPlannerExclusion.project_id == project.id,
                ProjectPlannerExclusion.user_id == payload.user_id,
                ProjectPlannerExclusion.day_date == payload.day_date,
                ProjectPlannerExclusion.time_slot == slot,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    await ensure_daily_baselines_for_departments(
        db=db, department_ids={project.department_id}, day=payload.day_date, actor=user,
    )

    exclusion = ProjectPlannerExclusion(
        project_id=project.id,
        user_id=payload.user_id,
        day_date=payload.day_date,
        time_slot=slot,
        created_by=user.id,
    )
    db.add(exclusion)
    affected_task_ids = (await db.execute(
        select(Task.id).outerjoin(TaskAssignee, TaskAssignee.task_id == Task.id).where(
            Task.project_id == project.id,
            or_(Task.assigned_to == payload.user_id, TaskAssignee.user_id == payload.user_id),
        ).distinct()
    )).scalars().all()
    for task_id in affected_task_ids:
        add_audit_log(
            db=db, actor_user_id=user.id, entity_type="task", entity_id=task_id,
            action="task.removed_from_day",
            before={"excluded": False, "day": payload.day_date.isoformat(), "user_id": str(payload.user_id), "time_slot": slot, "project_id": str(project.id)},
            after={"excluded": True, "day": payload.day_date.isoformat(), "user_id": str(payload.user_id), "time_slot": slot, "project_id": str(project.id)},
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/workflow-items", response_model=list[VsWorkflowItemOut])
async def list_workflow_items(
    project_id: uuid.UUID,
    phase: str | None = None,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> list[VsWorkflowItemOut]:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.department_id is not None:
        ensure_department_access(user, project.department_id)
    
    # We need to bridge AsyncSession to Session if the service uses sync DB calls, 
    # but here we'll assume the service function is adapted or we use the async pattern.
    # For now, let's keep it consistent with the existing codebase's DB patterns.
    # Note: get_active_workflow_items in the service was written as sync, let's make it async in the service and call it here.
    items = await get_active_workflow_items(db, project_id, phase)
    return items


@router.patch("/workflow-items/{item_id}", response_model=VsWorkflowItemOut)
async def update_workflow_item(
    item_id: uuid.UUID,
    payload: VsWorkflowItemUpdate,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> VsWorkflowItemOut:
    item = (await db.execute(select(VsWorkflowItem).where(VsWorkflowItem.id == item_id))).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow item not found")
    
    project = (await db.execute(select(Project).where(Project.id == item.project_id))).scalar_one_or_none()
    if project and project.department_id:
        ensure_department_access(user, project.department_id)
    
    if payload.status is not None:
        if payload.status == "DONE" and item.dependency_info:
            project_items = (
                await db.execute(
                    select(VsWorkflowItem).where(VsWorkflowItem.project_id == item.project_id)
                )
            ).scalars().all()
            dependency_ids = dependency_item_ids_from_info(item.dependency_info, project_items)
            if dependency_ids:
                pending = (
                    await db.execute(
                        select(VsWorkflowItem)
                        .where(
                            VsWorkflowItem.project_id == item.project_id,
                            VsWorkflowItem.id.in_(dependency_ids),
                            VsWorkflowItem.status != "DONE",
                        )
                    )
                ).scalars().first()
                if pending is not None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot mark as done before dependencies are completed.",
                    )
        item.status = payload.status
    if payload.assigned_to is not None:
        item.assigned_to = payload.assigned_to
    if payload.internal_notes is not None:
        item.internal_notes = payload.internal_notes
        
    await db.commit()
    await db.refresh(item)
    return item
