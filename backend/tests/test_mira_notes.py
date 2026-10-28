import os
import importlib.util
import io
import unittest
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/primeflow_test")
os.environ.setdefault("JWT_SECRET", "mira-notes-tests-only")

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from app.models.enums import GaNoteStatus
from app.models.ga_note import GaNote
from app.services import mira_host as host


class MiraNotesMigrationTests(unittest.TestCase):
    def test_migration_defaults_existing_notes_to_unshared_and_can_be_reversed(self):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        path = Path(__file__).parents[1] / "alembic/versions/0171_mira_notes_px_visibility.py"
        spec = importlib.util.spec_from_file_location("mira_visibility_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        output = io.StringIO()
        operations = Operations(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}))
        with patch.object(migration, "op", operations):
            migration.upgrade()
            migration.downgrade()
        sql = output.getvalue()
        self.assertIn("ADD COLUMN mira_shared_to_px BOOLEAN DEFAULT false NOT NULL", sql)
        self.assertIn("DROP COLUMN mira_shared_to_px", sql)


class MiraNotesTests(unittest.IsolatedAsyncioTestCase):
    def note(self, **values):
        return SimpleNamespace(**{
            "id": uuid.uuid4(), "content": "Desktop notes", "status": GaNoteStatus.CLOSED,
            "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc), "from_mira_desktop": True,
            "mira_shared_to_px": False, **values,
        })

    async def test_list_includes_desktop_host_and_old_closed_notes_with_global_pagination(self):
        desktop = self.note()
        host_note = self.note(from_mira_desktop=False, content="Host note\n\nDetails",
                              created_at=datetime(2026, 10, 28, tzinfo=timezone.utc))
        meeting = SimpleNamespace(id=uuid.uuid4(), slot="10:00", meeting_date=date(2026, 10, 20),
            summary="Summary", status="DONE", ended_at=datetime(2026, 10, 20, tzinfo=timezone.utc), created_at=None)
        statements = []

        async def execute(statement):
            # Compile the actual ORM statements, including every correlated Mira source property.
            statements.append(str(statement.compile(dialect=postgresql.dialect())))
            return Mock(all=Mock(return_value=[(meeting, None)] if len(statements) % 2 else [(desktop, "Desktop"), (host_note, None)]))

        db = SimpleNamespace(execute=execute)
        with patch.object(host, "turns_view", AsyncMock(return_value=[])):
            rows = await host.mira_notes(db, 10)
            page = await host.mira_notes(db, 1, 1)
        self.assertEqual([row["id"] for row in rows], [str(host_note.id), str(meeting.id), str(desktop.id)])
        self.assertEqual(rows[-1]["source"], "DESKTOP")
        self.assertEqual(rows[-1]["status"], "CLOSED")
        self.assertEqual(page, rows[1:2])
        self.assertIn("mira_desktop_sessions", statements[1])
        self.assertIn("mira_1h_events", statements[1])
        self.assertIn("NOT (EXISTS", statements[1])
        self.assertNotIn("completed_at >=", statements[1])

    async def test_existing_note_is_shared_in_place_and_repeated_clicks_create_nothing(self):
        note = self.note()
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=note))),
                             commit=AsyncMock(), add=Mock())
        for _ in range(2):
            result = await host.show_mira_note_in_px(db, "PX_NOTE", note.id, SimpleNamespace(id=uuid.uuid4()))
            self.assertEqual(result["note_id"], str(note.id))
        self.assertTrue(note.mira_shared_to_px)
        db.add.assert_not_called()
        self.assertEqual(db.commit.await_count, 2)

    async def test_non_mira_note_cannot_be_shared_through_mira(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=None))), commit=AsyncMock())
        with self.assertRaises(HTTPException) as caught:
            await host.show_mira_note_in_px(db, "PX_NOTE", uuid.uuid4(), SimpleNamespace(id=uuid.uuid4()))
        self.assertEqual(caught.exception.status_code, 404)
        db.commit.assert_not_called()

    async def test_summary_is_materialized_once_and_remains_linked_to_the_meeting(self):
        meeting = SimpleNamespace(id=uuid.uuid4(), slot="11:00", meeting_date=date(2026, 10, 28), summary="Summary")
        user = SimpleNamespace(id=uuid.uuid4())
        stored = {"event": None, "note": None}

        def add(row):
            if isinstance(row, GaNote):
                row.id = uuid.uuid4()
                stored["note"] = row
            else:
                stored["event"] = row

        async def execute(statement):
            return Mock(scalar_one_or_none=Mock(return_value=stored["event"]))

        db = SimpleNamespace(execute=execute, add=Mock(side_effect=add), flush=AsyncMock(), commit=AsyncMock(),
                             get=AsyncMock(side_effect=lambda *args: stored["note"]))
        with patch.object(host, "meeting_for", AsyncMock(return_value=meeting)) as get_meeting, \
             patch.object(host, "turns_view", AsyncMock(return_value=[{"initials": "EF", "notes": "Follow up"}])):
            first = await host.show_mira_note_in_px(db, "1H", meeting.id, user)
            again = await host.show_mira_note_in_px(db, "1H", meeting.id, user)
        self.assertEqual(first, again)
        self.assertEqual(db.add.call_count, 2)  # one note, one linkage event
        self.assertEqual(stored["event"].note_id, stored["note"].id)
        self.assertIn("EF: Follow up", stored["note"].content)
        self.assertTrue(stored["note"].mira_shared_to_px)
        get_meeting.assert_called_with(db, meeting.id, lock=True)

    async def test_shared_summary_stays_a_single_mira_row_and_keeps_px_edits(self):
        meeting = SimpleNamespace(id=uuid.uuid4(), slot="10:00", meeting_date=date(2026, 10, 28),
            summary="Original", status="DONE", ended_at=datetime.now(timezone.utc), created_at=None)
        note = self.note(content="Edited in PX", mira_shared_to_px=True)
        db = SimpleNamespace(execute=AsyncMock(side_effect=[Mock(all=Mock(return_value=[(meeting, note)])),
                                                          Mock(all=Mock(return_value=[]))]))
        rows = await host.mira_notes(db, 100)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"], "Edited in PX")
        self.assertTrue(rows[0]["shared_to_px"])
        self.assertEqual(rows[0]["note_id"], str(note.id))
