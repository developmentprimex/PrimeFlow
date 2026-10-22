from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import get_db
from app.models.project import Project
from app.models.task import Task
from app.services.task_marker import active_one_h_marker
from app.schemas.search import SearchProjectResult, SearchResponse, SearchTaskResult


router = APIRouter()


@router.get("", response_model=SearchResponse)
async def search(
    q: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
) -> SearchResponse:
    query = q.strip()
    if not query:
        return SearchResponse(tasks=[], projects=[])

    pattern = f"%{query}%"
    task_stmt = (
        select(Task)
        .where(
            or_(
                Task.title.ilike(pattern),
                Task.description.ilike(pattern),
                Task.internal_notes.ilike(pattern),
            )
        )
        .where(Task.is_active.is_(True))
    )
    project_stmt = (
        select(Project)
        .where(or_(Project.title.ilike(pattern), Project.description.ilike(pattern)))
        .where(Project.is_template.is_(False))
    )

    tasks = (await db.execute(task_stmt.limit(20))).scalars().all()
    projects = (await db.execute(project_stmt.limit(20))).scalars().all()

    return SearchResponse(
        tasks=[
            SearchTaskResult(
                id=t.id,
                title=t.title,
                project_id=t.project_id,
                department_id=t.department_id,
                one_h_marker=active_one_h_marker(t),
                one_h_marker_by_ga=bool(active_one_h_marker(t) and t.one_h_marker_by_ga),
                one_h_marker_comment=t.one_h_marker_comment,
            )
            for t in tasks
        ],
        projects=[SearchProjectResult(id=p.id, title=p.title, department_id=p.department_id) for p in projects],
    )


