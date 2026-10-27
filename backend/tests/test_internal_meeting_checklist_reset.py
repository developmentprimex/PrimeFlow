from __future__ import annotations

import os
import re
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost/primex_test")
os.environ.setdefault("JWT_SECRET", "test-secret")

from sqlalchemy import Boolean, Column, MetaData, String, Table, Uuid, create_engine, select

from app.services.internal_meeting_sessions import reset_internal_meeting_checklist


class TestInternalMeetingChecklistReset(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        metadata = MetaData()
        self.checklists = Table("checklists", metadata,
            Column("id", Uuid, primary_key=True), Column("title", String), Column("group_key", String))
        self.items = Table("checklist_items", metadata,
            Column("id", Uuid, primary_key=True), Column("checklist_id", Uuid),
            Column("item_type", String), Column("is_checked", Boolean), Column("comment", String))
        metadata.create_all(self.engine)
        self.connection = self.engine.connect()
        self.connection.connection.create_function("regexp_replace", 4,
            lambda value, pattern, replacement, flags: None if value is None else re.sub(
                pattern, replacement, value, flags=re.IGNORECASE if "i" in flags else 0))
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.connection.close)
        self.db = SimpleNamespace(execute=AsyncMock(side_effect=self.connection.execute))

    def checklist(self, title="PLNF JAV SHORT- E ENJTE", group="board"):
        checklist_id = uuid.uuid4()
        self.connection.execute(self.checklists.insert().values(id=checklist_id, title=title, group_key=group))
        return checklist_id

    def item(self, checklist_id, comment, checked=False, item_type="CHECKBOX"):
        item_id = uuid.uuid4()
        self.connection.execute(self.items.insert().values(id=item_id, checklist_id=checklist_id,
            item_type=item_type, is_checked=checked, comment=comment))
        return item_id

    def row(self, item_id):
        return self.connection.execute(select(self.items).where(self.items.c.id == item_id)).mappings().one()

    async def test_check_o_x_reset_together_preserving_comments_and_null(self):
        checklist_id = self.checklist()
        cases = [(None, True, None), ("[MEETING_CHECK_STATUS:O]", False, ""),
            ("Shenim\n[MEETING_CHECK_STATUS:X]", False, "Shenim\n"),
            ("[meeting_check_status:o]Tekst[MEETING_CHECK_STATUS:CHECK]", True, "Tekst"),
            ("Koment pa simbol", False, "Koment pa simbol")]
        ids = [self.item(checklist_id, comment, checked) for comment, checked, _ in cases]
        await reset_internal_meeting_checklist(self.db, checklist_id=checklist_id)
        for item_id, (_, _, expected) in zip(ids, cases):
            self.assertFalse(self.row(item_id)["is_checked"])
            self.assertEqual(self.row(item_id)["comment"], expected)
        # Repeated expiration/opening resets have the same result.
        await reset_internal_meeting_checklist(self.db, checklist_id=checklist_id)
        self.assertEqual([self.row(item_id)["comment"] for item_id in ids], [case[2] for case in cases])

    async def test_other_checklists_keep_existing_status_marker_behavior(self):
        for title, group in (("Another meeting", "board"), ("PLNF JAV SHORT- E ENJTE", "staff")):
            checklist_id = self.checklist(title, group)
            item_id = self.item(checklist_id, "Note [MEETING_CHECK_STATUS:X]", True)
            await reset_internal_meeting_checklist(self.db, checklist_id=checklist_id)
            self.assertFalse(self.row(item_id)["is_checked"])
            self.assertEqual(self.row(item_id)["comment"], "Note [MEETING_CHECK_STATUS:X]")

    async def test_reset_does_not_touch_other_checklist_or_non_checkbox_items(self):
        target = self.checklist()
        other = self.checklist("Another meeting")
        ids = [self.item(other, "[MEETING_CHECK_STATUS:O]", True),
               self.item(target, "[MEETING_CHECK_STATUS:X]", True, "COMMENT")]
        await reset_internal_meeting_checklist(self.db, checklist_id=target)
        for item_id in ids:
            self.assertTrue(self.row(item_id)["is_checked"])
            self.assertIn("[MEETING_CHECK_STATUS:", self.row(item_id)["comment"])
