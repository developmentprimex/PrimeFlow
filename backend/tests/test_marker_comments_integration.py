"""Real PostgreSQL tests using connection-local temporary tables and rollback.

Run explicitly with MARKER_COMMENTS_DATABASE_TESTS=1. No application rows are
modified, and the actual inbox migration is exercised against temporary tables.
"""
import asyncio
import importlib.util
import os
from pathlib import Path
import uuid
from unittest.mock import patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.api.routers.marker_comments import ReadComment, list_marker_comments, read_marker_comment
from app.api.routers.notifications import delete_all_notifications_post, mark_all_read
from app.config import settings
from app.models.enums import UserRole
from app.models.notification import Notification
from app.models.ga_note import GaNote
from app.models.plan_note import PlanNote
from app.models.task import Task
from app.models.task_assignee import TaskAssignee
from app.models.task_marker_comment_inbox import TaskMarkerCommentInbox as Inbox
from app.models.user import User
from app.services.marker_comments import record_initial_marker_comments
from app.services.task_marker import sync_note_task_marker, sync_task_marker

pytestmark = pytest.mark.skipif(os.environ.get("MARKER_COMMENTS_DATABASE_TESTS") != "1", reason="Explicit temporary-table PostgreSQL integration run")


def test_migration_inbox_recipients_read_receipts_edits_and_notifications():
    asyncio.run(_exercise_inbox())


async def _exercise_inbox():
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                for table in ("users", "tasks", "task_assignees", "notifications", "ga_notes", "plan_notes"):
                    await connection.execute(text(f"CREATE TEMPORARY TABLE {table} (LIKE public.{table} INCLUDING ALL)"))
                async with AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as db:
                    actor, first, second, outsider = [User(
                        id=uuid.uuid4(), email=f"marker-test-{uuid.uuid4()}@example.test", full_name=name,
                        password_hash="test-only", role=UserRole.STAFF, is_active=True,
                    ) for name in ("Author", "First", "Second", "Outsider")]
                    actor.role = UserRole.ADMIN
                    db.add_all([actor, first, second, outsider])
                    await db.flush()
                    group = uuid.uuid4()
                    tasks = [Task(
                        id=uuid.uuid4(), title="Shared test task", assigned_to=person.id, created_by=actor.id,
                        fast_task_group_id=group, is_active=True, one_h_marker="QUESTION", one_h_marker_comment="Existing comment",
                    ) for person in (first, second)]
                    db.add_all(tasks)
                    await db.flush()
                    db.add_all([TaskAssignee(task_id=tasks[0].id, user_id=person.id) for person in (first, second)])
                    await db.flush()

                    def migrate(sync_connection):
                        migration_file = Path(__file__).parents[1] / "alembic/versions/0150_marker_comment_inbox.py"
                        spec = importlib.util.spec_from_file_location("inbox_migration", migration_file)
                        migration = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(migration)
                        ops = Operations(MigrationContext.configure(sync_connection))
                        def create_temp_table(name, *columns, **kwargs):
                            return ops.create_table(name, *columns, prefixes=["TEMPORARY"], **kwargs)
                        with Operations.context(MigrationContext.configure(sync_connection)):
                            with patch("alembic.op.create_table", side_effect=create_temp_table):
                                migration.upgrade()
                    await connection.run_sync(migrate)

                    # Backfill groups copies, includes both assignees and creator,
                    # and never guesses an author or sends historical notifications.
                    seeded = list((await db.execute(select(Inbox))).scalars())
                    assert len(seeded) == 3
                    assert all(item.author_id is None and item.read_at is None for item in seeded)
                    assert all(set(item.task_ids) == {str(task.id) for task in tasks} for item in seeded)
                    assert not list((await db.execute(select(Notification))).scalars())

                    # Merely saving the old comment must not import it into titles.
                    await sync_task_marker(db, tasks[0], "QUESTION", marker_comment="Existing comment", actor_email=actor.email)
                    assert all("COM:" not in task.title for task in tasks)

                    await sync_task_marker(db, tasks[0], "QUESTION", marker_comment="New comment", actor_email=actor.email)
                    await db.flush()
                    assert len(db.info["pending_marker_notifications"]) == 2
                    notifications = list((await db.execute(select(Notification))).scalars())
                    assert {item.user_id for item in notifications} == {first.id, second.id}
                    assert all(item.data["kind"] == "task_marker_comment" and item.data["open_url"].startswith("/comments?") for item in notifications)
                    assert len((await list_marker_comments(db, outsider))["items"]) == 0
                    author_items = (await list_marker_comments(db, actor))["items"]
                    assert not author_items  # Creating/writing a task is not responsibility.
                    first_item = (await list_marker_comments(db, first))["items"][0]
                    second_item = (await list_marker_comments(db, second))["items"][0]
                    assert first_item["task_id"] == str(tasks[0].id)
                    assert second_item["task_id"] == str(tasks[1].id)
                    assert first_item["read_at"] is None and second_item["read_at"] is None
                    assert first_item["author_name"] == actor.full_name
                    assert all(task.title == "Shared test task\nCOM: New comment" for task in tasks)
                    assert first_item["title"] == "Shared test task\nCOM: New comment"
                    assert first_item["is_mine"] is True
                    # Team acknowledgement counts only distinct active assignees,
                    # never the creator or unrelated viewers.
                    all_for_outsider = (await list_marker_comments(db, outsider, scope="all"))["items"]
                    assert len(all_for_outsider) == 1
                    assert all_for_outsider[0]["comment"] == "New comment"
                    assert all_for_outsider[0]["is_mine"] is False
                    assert all_for_outsider[0]["read_at"] is None
                    assert all_for_outsider[0]["can_mark_read"] is False
                    assert all_for_outsider[0]["recipient_count"] == 2
                    assert all_for_outsider[0]["read_count"] == 0
                    assert all_for_outsider[0]["all_read"] is False
                    all_for_first = (await list_marker_comments(db, first, scope="all"))["items"]
                    assert len(all_for_first) == 1 and all_for_first[0]["id"] == first_item["id"]

                    with pytest.raises(HTTPException) as forbidden:
                        await read_marker_comment(uuid.UUID(first_item["id"]), ReadComment(revision=uuid.UUID(first_item["revision"])), db, outsider)
                    assert forbidden.value.status_code == 404

                    # Scope=all cannot bypass responsibility, including creators.
                    for viewer in (outsider, actor):
                        with pytest.raises(HTTPException) as forbidden:
                            await read_marker_comment(
                                uuid.UUID(all_for_outsider[0]["id"]),
                                ReadComment(revision=uuid.UUID(all_for_outsider[0]["revision"]), scope="all"), db, viewer,
                            )
                        assert forbidden.value.status_code == 404
                    observer_items = (await list_marker_comments(db, outsider, scope="all"))["items"]
                    assert len(observer_items) == 1 and observer_items[0]["read_at"] is None
                    assert len(list((await db.execute(select(Inbox))).scalars())) == 3
                    assert observer_items[0]["is_mine"] is False
                    assert not (await list_marker_comments(db, outsider))["items"]
                    assert (await list_marker_comments(db, first))["items"][0]["read_at"] is None
                    assert (await list_marker_comments(db, second))["items"][0]["read_at"] is None
                    assert len(db.info["pending_marker_notifications"]) == 2

                    # Ignore observer receipts saved under the earlier policy.
                    legacy_observer = Inbox(
                        id=uuid.uuid4(), source_key=first_item["source_key"], user_id=outsider.id,
                        task_id=tasks[0].id, task_ids=first_item["task_ids"],
                        revision=uuid.UUID(first_item["revision"]), marker="QUESTION", comment="New comment",
                        updated_at=first_item["updated_at"], read_at=first_item["updated_at"],
                    )
                    db.add(legacy_observer)
                    await db.flush()
                    progress = (await list_marker_comments(db, outsider, scope="all"))["items"][0]
                    assert progress["read_count"] == 0 and progress["recipient_count"] == 2
                    assert progress["can_mark_read"] is False and progress["read_at"] is None
                    with pytest.raises(HTTPException) as legacy_forbidden:
                        await read_marker_comment(legacy_observer.id, ReadComment(revision=legacy_observer.revision, scope="all"), db, outsider)
                    assert legacy_forbidden.value.status_code == 404
                    await db.delete(legacy_observer)
                    await db.flush()

                    await read_marker_comment(uuid.UUID(first_item["id"]), ReadComment(revision=uuid.UUID(first_item["revision"])), db, first)
                    assert (await list_marker_comments(db, first))["items"][0]["read_at"] is not None
                    assert (await list_marker_comments(db, second))["items"][0]["read_at"] is None
                    assert (await list_marker_comments(db, first, scope="all"))["items"][0]["read_at"] is not None
                    progress = (await list_marker_comments(db, outsider, scope="all"))["items"][0]
                    assert progress["read_at"] is None
                    assert progress["read_count"] == 1 and progress["recipient_count"] == 2
                    assert progress["all_read"] is False
                    assert {person["name"] for person in progress["recipients"] if person["read_at"]} == {"First"}

                    await read_marker_comment(uuid.UUID(second_item["id"]), ReadComment(revision=uuid.UUID(second_item["revision"]), scope="all"), db, second)
                    progress = (await list_marker_comments(db, outsider, scope="all"))["items"][0]
                    assert progress["read_count"] == 2 and progress["all_read"] is True

                    # Saving the same value does not reset receipts or send duplicates.
                    await sync_task_marker(db, tasks[1], "QUESTION", marker_comment="New comment", actor_email=actor.email)
                    assert len(db.info["pending_marker_notifications"]) == 2
                    assert (await list_marker_comments(db, first))["items"][0]["read_at"] is not None

                    await sync_task_marker(db, tasks[0], "QUESTION", marker_comment="Edited comment", actor_email=actor.email)
                    assert all(task.title == "Shared test task\nCOM: Edited comment" for task in tasks)
                    assert (await list_marker_comments(db, first))["items"][0]["read_at"] is None
                    assert (await list_marker_comments(db, outsider, scope="all"))["items"][0]["read_at"] is None
                    with pytest.raises(HTTPException) as stale:
                        await read_marker_comment(uuid.UUID(first_item["id"]), ReadComment(revision=uuid.UUID(first_item["revision"])), db, first)
                    assert stale.value.status_code == 409
                    assert (await list_marker_comments(db, first))["items"][0]["read_at"] is None

                    # Notification dismissal is independent from comment receipts.
                    await mark_all_read(db, first)
                    await delete_all_notifications_post(db, first)
                    assert (await list_marker_comments(db, first))["items"][0]["read_at"] is None

                    # Authors must explicitly read their own comments too,
                    # including when they use an admin account.
                    for role in (UserRole.STAFF, UserRole.ADMIN):
                        first.role = role
                        await sync_task_marker(db, tasks[0], "QUESTION", marker_comment=f"Written by assigned {role.value}", actor_email=first.email)
                        own_comment = (await list_marker_comments(db, first))["items"][0]
                        assert own_comment["author_name"] == first.full_name
                        assert own_comment["read_at"] is None
                        assert (await list_marker_comments(db, second))["items"][0]["read_at"] is None
                        progress = (await list_marker_comments(db, outsider, scope="all"))["items"][0]
                        assert progress["read_count"] == 0 and progress["recipient_count"] == 2
                        assert progress["all_read"] is False
                        await read_marker_comment(uuid.UUID(own_comment["id"]), ReadComment(revision=uuid.UUID(own_comment["revision"])), db, first)
                        progress = (await list_marker_comments(db, outsider, scope="all"))["items"][0]
                        assert progress["read_count"] == 1 and progress["all_read"] is False
                    first.role = UserRole.STAFF

                    await sync_task_marker(db, tasks[0], "QUESTION", marker_comment=None, actor_email=actor.email)
                    assert all(task.title == "Shared test task" for task in tasks)
                    symbol_only = (await list_marker_comments(db, first))["items"][0]
                    assert symbol_only["marker"] == "QUESTION" and symbol_only["comment"] == ""
                    assert symbol_only["read_at"] is None
                    progress = (await list_marker_comments(db, outsider, scope="all"))["items"][0]
                    assert progress["read_count"] == 0 and progress["recipient_count"] == 2
                    assert {person["name"] for person in progress["recipients"]} == {"First", "Second"}
                    symbol_notifications = list((await db.execute(select(Notification).where(Notification.data["kind"].astext == "task_marker"))).scalars())
                    assert symbol_notifications
                    assert all(item.data["comment_id"] and item.data["open_url"].startswith("/comments?") for item in symbol_notifications)

                    await read_marker_comment(uuid.UUID(symbol_only["id"]), ReadComment(revision=uuid.UUID(symbol_only["revision"])), db, first)
                    queued = len(db.info["pending_marker_notifications"])
                    await sync_task_marker(db, tasks[0], "QUESTION", marker_comment=None, actor_email=first.email)
                    assert len(db.info["pending_marker_notifications"]) == queued
                    progress = (await list_marker_comments(db, outsider, scope="all"))["items"][0]
                    assert progress["read_count"] == 1 and progress["all_read"] is False

                    # A different symbol is new for everyone, even without text.
                    await sync_task_marker(db, tasks[0], "M3", marker_comment=None, actor_email=first.email)
                    changed_symbol = (await list_marker_comments(db, first))["items"][0]
                    assert changed_symbol["marker"] == "M3" and changed_symbol["comment"] == ""
                    assert changed_symbol["revision"] != symbol_only["revision"]
                    assert changed_symbol["read_at"] is None
                    assert (await list_marker_comments(db, second))["items"][0]["read_at"] is None
                    with pytest.raises(HTTPException) as stale_symbol:
                        await read_marker_comment(uuid.UUID(symbol_only["id"]), ReadComment(revision=uuid.UUID(symbol_only["revision"])), db, first)
                    assert stale_symbol.value.status_code == 409

                    await sync_task_marker(db, tasks[0], None, marker_comment=None, actor_email=actor.email)
                    assert not (await list_marker_comments(db, first))["items"]
                    assert not (await list_marker_comments(db, second))["items"]

                    # Symbols present when a task is created also enter the inbox.
                    for task in tasks:
                        task.one_h_marker = "F"
                        task.one_h_marker_comment = None
                    await record_initial_marker_comments(db, tasks, actor_email=first.email)
                    await record_initial_marker_comments(db, tasks, actor_email=first.email)
                    initial_symbol = (await list_marker_comments(db, first))["items"][0]
                    assert initial_symbol["marker"] == "F" and initial_symbol["comment"] == ""
                    assert initial_symbol["read_at"] is None
                    assert len(list((await db.execute(select(Inbox))).scalars())) == 3

                    # Initial comments on newly created tasks also enter the inbox.
                    tasks[0].one_h_marker_comment = "Initial comment"
                    tasks[1].one_h_marker_comment = "Initial comment"
                    await record_initial_marker_comments(db, tasks, actor_email=first.email)
                    await record_initial_marker_comments(db, tasks, actor_email=first.email)
                    assert len((await list_marker_comments(db, first))["items"]) == 1
                    assert (await list_marker_comments(db, first))["items"][0]["read_at"] is None
                    assert (await list_marker_comments(db, second))["items"][0]["read_at"] is None
                    assert len(list((await db.execute(select(Inbox))).scalars())) == 3

                    # Losing task membership removes visibility without exposing old text.
                    tasks[0].assigned_to = None
                    await db.execute(delete(TaskAssignee).where(TaskAssignee.user_id == first.id))
                    assert not (await list_marker_comments(db, first))["items"]
                    progress = (await list_marker_comments(db, outsider, scope="all"))["items"][0]
                    assert progress["recipient_count"] == 1 and progress["read_count"] == 0
                    assert progress["recipients"][0]["name"] == "Second"
                    with pytest.raises(HTTPException) as removed:
                        await read_marker_comment(uuid.UUID(first_item["id"]), ReadComment(revision=uuid.UUID(first_item["revision"]), scope="all"), db, first)
                    assert removed.value.status_code == 404
                    second.is_active = False
                    progress = (await list_marker_comments(db, outsider, scope="all"))["items"][0]
                    assert progress["recipient_count"] == 0 and progress["all_read"] is False

                    # New comments are stored below the headline in both task
                    # copies and their PX Notes/PX JAV source. Existing comments
                    # stay untouched, including when only their symbol changes.
                    second.is_active = True
                    for model, origin in ((GaNote, "ga_note_origin_id"), (PlanNote, "plan_note_origin_id")):
                        original = "RA/OH: Shared note task\n\n[[added]]Original details[[/added]]"
                        note = model(id=uuid.uuid4(), content=original, created_by=actor.id,
                                     one_h_marker="QUESTION", one_h_marker_comment="Legacy comment")
                        db.add(note)
                        await db.flush()
                        copies = [Task(id=uuid.uuid4(), title=original, assigned_to=person.id, created_by=actor.id,
                                       is_active=True, one_h_marker="QUESTION", one_h_marker_comment="Legacy comment",
                                       **{origin: note.id}) for person in (first, second)]
                        db.add_all(copies)
                        await db.flush()
                        await sync_task_marker(db, copies[0], "M2", marker_comment="Legacy comment", actor_email=actor.email)
                        await db.flush()
                        assert all(copy.title == original for copy in copies)
                        await db.refresh(note, ["content"])
                        assert note.content == original
                        await sync_task_marker(db, copies[0], "M2", marker_comment="New inline comment", actor_email=actor.email)
                        await db.flush()
                        await db.refresh(note, ["content"])
                        expected = original.replace("\n", "\nCOM: New inline comment\n", 1)
                        assert note.content == expected
                        assert all(copy.title == expected for copy in copies)
                        await sync_note_task_marker(db, note, "M2", marker_comment="Edited in note", actor_email=actor.email)
                        await db.flush()
                        assert note.content.count("COM:") == 1
                        assert "COM: Edited in note" in note.content
                        assert all(copy.title == note.content for copy in copies)
                        await sync_note_task_marker(db, note, "M2", marker_comment=None, actor_email=actor.email)
                        await db.flush()
                        assert note.content == original
                        assert all(copy.title == original for copy in copies)
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
