import asyncio
import importlib.util
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import create_engine

from app.api.routers import projects
from app.models.enums import UserRole
from app.models.project import Project
from app.schemas.project import ProjectUpdate


def test_migration_keeps_existing_and_new_projects_active():
    path = Path(__file__).parents[1] / "alembic/versions/0164_project_is_active.py"
    spec = importlib.util.spec_from_file_location("project_activity_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE projects (id INTEGER PRIMARY KEY, current_phase TEXT)")
        connection.exec_driver_sql("INSERT INTO projects VALUES (1, 'CLOSED')")
        with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.upgrade()
        connection.exec_driver_sql("INSERT INTO projects (id, current_phase) VALUES (2, 'PLANNING')")
        assert connection.exec_driver_sql("SELECT is_active FROM projects ORDER BY id").scalars().all() == [1, 1]
        assert connection.exec_driver_sql("SELECT current_phase FROM projects WHERE id = 1").scalar() == "CLOSED"
    engine.dispose()


@pytest.mark.parametrize("active", [True, False])
def test_staff_cannot_change_activity(active):
    db = AsyncMock()
    with pytest.raises(HTTPException) as error:
        asyncio.run(projects.update_project(uuid.uuid4(), ProjectUpdate(is_active=active), db,
                                            SimpleNamespace(role=UserRole.STAFF)))
    assert error.value.status_code == 403
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("role", [UserRole.ADMIN, UserRole.MANAGER])
@pytest.mark.parametrize("active", [True, False])
def test_authorized_activity_change_preserves_workflow(role, active):
    now = datetime.now(timezone.utc)
    project = Project(id=uuid.uuid4(), title="Test project", department_id=uuid.uuid4(),
                      current_phase="PLANNING", status="IN_PROGRESS", progress_percentage=42,
                      is_template=False, is_active=not active, completed_at=now,
                      created_at=now, updated_at=now)
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    db.execute.return_value = result
    with patch.object(projects, "build_project_display_title_map", AsyncMock(return_value={})):
        output = asyncio.run(projects.update_project(project.id, ProjectUpdate(is_active=active), db,
                                                     SimpleNamespace(role=role)))
    assert output.is_active is active
    assert project.current_phase == "PLANNING"
    assert project.status == "IN_PROGRESS"
    assert project.progress_percentage == 42
    assert project.completed_at == now
    db.commit.assert_awaited_once()
    # Activity updates never issue task or workflow updates.
    db.execute.assert_awaited_once()


def test_staff_can_still_edit_other_project_fields():
    now = datetime.now(timezone.utc)
    department_id = uuid.uuid4()
    project = Project(id=uuid.uuid4(), title="Before", department_id=department_id,
                      current_phase="PLANNING", status="TODO", progress_percentage=0,
                      is_template=False, is_active=False, created_at=now, updated_at=now)
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = project
    db.execute.return_value = result
    with patch.object(projects, "build_project_display_title_map", AsyncMock(return_value={})):
        output = asyncio.run(projects.update_project(project.id, ProjectUpdate(title="After"), db,
                             SimpleNamespace(role=UserRole.STAFF, department_id=department_id)))
    assert output.title == "After"
    assert output.is_active is False
