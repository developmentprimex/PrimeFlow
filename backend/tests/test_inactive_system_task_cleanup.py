"""Exercise deletion, sharing and FK behavior against a real isolated database."""
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.api.routers.users import deactivate_user, update_user
from app.models.enums import UserRole
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.schemas.user import UserUpdate
from app.services.inactive_system_tasks import (
    apply_inactive_system_task_cleanup, cleanup_inactive_user_system_tasks,
    plan_inactive_system_task_cleanup,
)


class AsyncSessionAdapter:
    def __init__(self, session):
        self.session = session

    async def execute(self, statement):
        return self.session.execute(statement)

    def add(self, instance):
        self.session.add(instance)

    async def run_sync(self, callback):
        return callback(self.session)


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            for ddl in (
                "CREATE TABLE users (id CHAR(32) PRIMARY KEY, is_active BOOLEAN NOT NULL)",
                "CREATE TABLE tasks (id CHAR(32) PRIMARY KEY, title TEXT, status TEXT, assigned_to CHAR(32) REFERENCES users(id), system_template_origin_id CHAR(32), system_task_slot_id CHAR(32), updated_at DATETIME, dependency_task_id CHAR(32) REFERENCES tasks(id) ON DELETE SET NULL)",
                "CREATE TABLE task_assignees (task_id CHAR(32) REFERENCES tasks(id) ON DELETE CASCADE, user_id CHAR(32) REFERENCES users(id), PRIMARY KEY(task_id,user_id))",
                "CREATE TABLE system_task_occurrences (id CHAR(32) PRIMARY KEY, user_id CHAR(32) REFERENCES users(id), status TEXT)",
                "CREATE TABLE task_children (id INTEGER PRIMARY KEY, task_id CHAR(32) REFERENCES tasks(id) ON DELETE CASCADE)",
                'CREATE TABLE audit_logs (id CHAR(32) PRIMARY KEY, actor_user_id CHAR(32), entity_type TEXT, entity_id CHAR(32), action TEXT, "before" JSON, "after" JSON, created_at DATETIME)',
            ):
                conn.exec_driver_sql(ddl)
        self.session = Session(self.engine)
        self.db = AsyncSessionAdapter(self.session)
        self.old, self.active, self.other_old = (uuid.uuid4() for _ in range(3))
        for user_id, active in ((self.old, False), (self.active, True), (self.other_old, False)):
            self.session.execute(text("INSERT INTO users VALUES (:id,:active)"), {"id": user_id.hex, "active": active})
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def task(self, owner, *, system=True, links=(), status="TODO", slot_only=False):
        task_id = uuid.uuid4()
        self.session.execute(text("INSERT INTO tasks (id,title,status,assigned_to,system_template_origin_id,system_task_slot_id) VALUES (:id,'Example',:status,:owner,:template,:slot)"), {
            "id": task_id.hex, "status": status, "owner": owner.hex if owner else None,
            "template": uuid.uuid4().hex if system and not slot_only else None,
            "slot": uuid.uuid4().hex if slot_only else None,
        })
        for user_id in links:
            self.session.execute(text("INSERT INTO task_assignees VALUES (:task,:user)"), {"task": task_id.hex, "user": user_id.hex})
        return task_id

    async def test_delete_all_statuses_and_legacy_rows_preserving_active_and_shared_work(self):
        deleted = {self.task(self.old, links=[self.old], status=status) for status in ("TODO", "DONE", "IN_PROGRESS")}
        deleted.add(self.task(None, links=[self.old]))
        deleted.add(self.task(self.old, slot_only=True))
        shared = self.task(self.old, links=[self.old, self.active])
        active = self.task(self.active, links=[self.old, self.active])
        ordinary = self.task(self.old, system=False, links=[self.old])
        replacement = self.task(self.active, links=[self.active])
        unassigned = self.task(None)
        # Cascades remove children; references from surviving tasks become NULL.
        root = next(iter(deleted))
        self.session.execute(text("INSERT INTO task_children VALUES (1,:task)"), {"task": root.hex})
        self.session.execute(text("UPDATE tasks SET dependency_task_id=:root WHERE id=:task"), {"root": root.hex, "task": active.hex})
        for owner in (self.old, self.active):
            self.session.execute(text("INSERT INTO system_task_occurrences VALUES (:id,:owner,'DONE')"), {"id": uuid.uuid4().hex, "owner": owner.hex})
        self.session.commit()

        plan = await plan_inactive_system_task_cleanup(self.db)
        self.assertEqual(set(plan.task_ids), deleted)
        self.assertEqual(set(self.session.scalars(select(Task.id))), deleted | {shared, active, ordinary, replacement, unassigned})
        result = await apply_inactive_system_task_cleanup(self.db, plan)
        self.session.commit()
        self.assertEqual(result, {"deleted_tasks": 5, "deleted_occurrences": 1, "preserved_shared_tasks": 2, "reassigned_tasks": 1})
        self.assertEqual(set(self.session.scalars(select(Task.id))), {shared, active, ordinary, replacement, unassigned})
        self.assertEqual(self.session.scalar(select(Task.assigned_to).where(Task.id == shared)), self.active)
        self.assertEqual(set(self.session.execute(select(TaskAssignee.task_id, TaskAssignee.user_id))), {(shared, self.active), (active, self.active), (ordinary, self.old), (replacement, self.active)})
        self.assertEqual(self.session.scalar(text("SELECT count(*) FROM task_children")), 0)
        self.assertIsNone(self.session.scalar(text("SELECT dependency_task_id FROM tasks WHERE id=:id"), {"id": active.hex}))
        self.assertEqual(self.session.scalar(text("SELECT count(*) FROM audit_logs")), 5)
        self.assertEqual((await cleanup_inactive_user_system_tasks(self.db))["deleted_tasks"], 0)

    async def test_scoped_cleanup_and_rollback(self):
        first, second = self.task(self.old), self.task(self.other_old)
        self.session.commit()
        await cleanup_inactive_user_system_tasks(self.db, user_ids=[self.old])
        self.assertEqual(set(self.session.scalars(select(Task.id))), {second})
        self.session.rollback()
        self.assertEqual(set(self.session.scalars(select(Task.id))), {first, second})
        result = await cleanup_inactive_user_system_tasks(self.db, user_ids=[self.active])
        self.assertEqual(result["deleted_tasks"], 0)

    async def test_current_installation_without_legacy_table(self):
        self.session.execute(text("DROP TABLE system_task_occurrences"))
        task_id = self.task(self.old)
        self.session.commit()
        result = await cleanup_inactive_user_system_tasks(self.db)
        self.session.commit()
        self.assertEqual(result["deleted_tasks"], 1)
        self.assertEqual(result["deleted_occurrences"], 0)
        self.assertNotIn(task_id, set(self.session.scalars(select(Task.id))))


class DeactivationTests(unittest.IsolatedAsyncioTestCase):
    async def test_patch_and_delete_cleanup_before_commit_only_when_inactive(self):
        for mode in ("patch-off", "delete", "patch-on"):
            target = SimpleNamespace(id=uuid.uuid4(), email="old@example.com", username="old", full_name="Old", role=UserRole.STAFF,
                                     department_id=None, is_active=True, weekly_planner_sort_order=None, weekly_planner_hidden=False)
            current = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN)
            db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: target)),
                                 flush=AsyncMock(), commit=AsyncMock(), refresh=AsyncMock())
            with patch("app.api.routers.users.cleanup_inactive_user_system_tasks", new=AsyncMock()) as cleanup:
                if mode == "delete":
                    await deactivate_user(target.id, db=db, current=current)
                else:
                    await update_user(target.id, UserUpdate(is_active=mode == "patch-on"), db=db, current=current)
                if mode == "patch-on":
                    cleanup.assert_not_awaited()
                else:
                    db.flush.assert_awaited_once()
                    cleanup.assert_awaited_once_with(db, user_ids=[target.id], actor_user_id=current.id)
                db.commit.assert_awaited_once()
