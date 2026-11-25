"""Exercise the assistant comment feed with real PostgreSQL data."""

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

os.environ.setdefault("JWT_SECRET", "test-only-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")

from app.api.deps import get_current_user
from app.config import settings
from app.db import get_db
from app.models.enums import UserRole
from app.models.task import Task
from app.models.task_marker_comment_inbox import TaskMarkerCommentInbox
from app.models.task_user_comment import TaskUserComment
from app.models.user import User

FEED = "/api/ga-assistant/1h/comments"


def test_1h_comment_routes_are_registered():
    from app.main import app

    paths = app.openapi()["paths"]
    assert "get" in paths.get(FEED, {})
    assert "post" in paths.get(f"{FEED}/mark", {})


@pytest.mark.skipif(
    os.environ.get("PRIMEFLOW_DB_TESTS") != "1"
    or not (make_url(settings.DATABASE_URL).database or "").endswith("_test"),
    reason="Needs a migrated *_test PostgreSQL database",
)
def test_list_and_mark_current_1h_comment_revisions(monkeypatch):
    monkeypatch.setattr(settings, "GA_USER_EMAIL", f"ga-{uuid.uuid4()}@example.test")
    asyncio.run(_exercise_feed())


async def _exercise_feed():
    from app.main import app

    now = datetime(2099, 11, 25, 10, tzinfo=timezone.utc)
    earlier = now - timedelta(days=1)
    feed_scope = {"since": earlier.isoformat()}
    new_scope = {**feed_scope, "only_new": True}
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as connection, connection.begin() as transaction:
            async with AsyncSession(
                bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint",
            ) as db:
                ga, admin, staff = [
                    User(email=email, full_name=name, password_hash="test", role=role)
                    for email, name, role in (
                        (settings.GA_USER_EMAIL, "GA Account", UserRole.STAFF),
                        (f"admin-{uuid.uuid4()}@example.test", "Admin Account", UserRole.ADMIN),
                        (f"staff-{uuid.uuid4()}@example.test", "Ana Berisha", UserRole.STAFF),
                    )
                ]
                db.add_all([ga, admin, staff])
                await db.flush()
                task = Task(title="1H task", is_1h_report=True, assigned_to=staff.id,
                            one_h_marker="QUESTION", one_h_marker_comment="Marker comment")
                plain_task = Task(title="Ordinary task", is_1h_report=False, assigned_to=staff.id)
                db.add_all([task, plain_task])
                await db.flush()
                ordinary = TaskUserComment(task_id=task.id, user_id=staff.id, comment="Staff comment",
                                           created_at=earlier, updated_at=earlier)
                revision = uuid.uuid4()
                marker = TaskMarkerCommentInbox(
                    source_key=f"task:{task.id}", user_id=staff.id, task_id=task.id,
                    task_ids=[str(task.id)], author_id=admin.id, revision=revision, marker="QUESTION",
                    comment="Marker comment", updated_at=now, comment_created_at=now, read_at=now,
                )
                db.add_all([
                    ordinary, marker,
                    TaskUserComment(task_id=plain_task.id, user_id=staff.id, comment="Skip", updated_at=now),
                    TaskUserComment(task_id=task.id, user_id=admin.id, comment="   ", updated_at=now),
                    TaskMarkerCommentInbox(
                        source_key=f"task:{task.id}", user_id=admin.id, task_id=task.id,
                        task_ids=[str(task.id)], author_id=admin.id, revision=revision, marker="QUESTION",
                        comment="Marker comment", updated_at=now, comment_created_at=now,
                    ),
                ])
                await db.commit()

                viewer = ga
                app.dependency_overrides.update({get_current_user: lambda: viewer, get_db: lambda: db})
                try:
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                        response = await client.get(FEED, params=feed_scope)
                        assert response.status_code == 200, response.text
                        symbol, personal = response.json()["items"]
                        assert symbol["text"] == "Marker comment"
                        assert symbol["author"] == {"name": "Admin Account", "initials": "AA"}
                        assert personal["text"] == "Staff comment"
                        assert personal["author"] == {"name": "Ana Berisha", "initials": "AB"}
                        assert personal["task"] == {
                            "id": str(task.id), "title": "1H task",
                            "link": f"{settings.FRONTEND_URL.rstrip('/')}/tasks/{task.id}",
                        }
                        assert personal["status"] == symbol["status"] == "new"
                        assert datetime.fromisoformat(personal["time"]) == earlier
                        filtered = await client.get(FEED, params={"since": now.isoformat()})
                        assert filtered.json()["items"] == [symbol]

                        for comment in (personal, symbol):
                            mark = {"id": comment["id"], "status": "seen"}
                            response = await client.post(f"{FEED}/mark", json=mark)
                            assert response.status_code == 200, response.text
                            assert response.json() == mark
                        response = await client.get(FEED, params=new_scope)
                        assert response.json()["items"] == []

                        viewer = admin
                        response = await client.get(FEED, params=new_scope)
                        assert response.json()["items"] == [symbol, personal]
                        viewer = staff
                        assert (await client.get(FEED)).status_code == 403
                        assert (await client.post(f"{FEED}/mark", json=mark)).status_code == 403
                        viewer = ga

                        response = await client.post(f"{FEED}/mark", json={"id": symbol["id"], "status": "new"})
                        assert response.status_code == 200, response.text
                        rows = (await db.execute(select(TaskMarkerCommentInbox).where(
                            TaskMarkerCommentInbox.task_id == task.id,
                        ))).scalars().all()
                        assert {row.user_id: row.read_at for row in rows} == {staff.id: now, admin.id: None}

                        ordinary.comment = "Edited staff comment"
                        ordinary.updated_at = now + timedelta(minutes=1)
                        await db.commit()
                        stale = await client.post(f"{FEED}/mark", json={"id": personal["id"], "status": "seen"})
                        assert stale.status_code == 409, stale.text
                        response = await client.get(FEED, params=new_scope)
                        edited, reset = response.json()["items"]
                        assert reset == symbol
                        assert edited["text"] == "Edited staff comment" and edited["status"] == "new"
                        assert edited["id"] != personal["id"]

                        response = await client.post(f"{FEED}/mark", json={"id": symbol["id"], "status": "seen"})
                        assert response.status_code == 200, response.text
                        task.one_h_marker_comment = "Edited marker comment"
                        marker_revision = uuid.uuid4()
                        for row in rows:
                            row.revision = marker_revision
                            row.comment = task.one_h_marker_comment
                            row.updated_at = now + timedelta(minutes=2)
                            row.read_at = None
                        await db.commit()
                        stale = await client.post(f"{FEED}/mark", json={"id": symbol["id"], "status": "seen"})
                        assert stale.status_code == 409, stale.text
                        response = await client.get(FEED, params={"only_new": True, "since": now.isoformat()})
                        changed_marker, changed_personal = response.json()["items"]
                        assert changed_personal == edited
                        assert changed_marker["text"] == "Edited marker comment"
                        assert changed_marker["status"] == "new" and changed_marker["id"] != symbol["id"]
                finally:
                    app.dependency_overrides.pop(get_current_user, None)
                    app.dependency_overrides.pop(get_db, None)
            await transaction.rollback()
    finally:
        await engine.dispose()
