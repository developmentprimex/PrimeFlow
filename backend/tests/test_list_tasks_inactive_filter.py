import unittest
import uuid
from types import SimpleNamespace

from app.api.routers.tasks import list_tasks


class _EmptyScalars:
    def all(self):
        return []


class _EmptyResult:
    def scalars(self):
        return _EmptyScalars()


class FakeAsyncSession:
    def __init__(self) -> None:
        self.executed = []

    async def execute(self, stmt):
        self.executed.append(stmt)
        return _EmptyResult()


class TestListTasksInactiveFilter(unittest.IsolatedAsyncioTestCase):
    async def test_default_filters_inactive(self) -> None:
        db = FakeAsyncSession()
        await list_tasks(db=db, user=SimpleNamespace(id=uuid.uuid4()), ga_note_origin_ids=None, plan_note_origin_ids=None)
        self.assertTrue(db.executed, "Expected at least one statement to be executed")
        where = getattr(db.executed[0], "whereclause", None)
        self.assertIsNotNone(where, "Expected a WHERE clause when include_inactive is default/False")
        self.assertIn("is_active", str(where))

    async def test_include_inactive_true_skips_filter(self) -> None:
        db = FakeAsyncSession()
        await list_tasks(db=db, user=SimpleNamespace(id=uuid.uuid4()), include_inactive=True, ga_note_origin_ids=None, plan_note_origin_ids=None)
        self.assertTrue(db.executed, "Expected at least one statement to be executed")
        where = getattr(db.executed[0], "whereclause", None)
        self.assertNotIn("tasks.is_active", str(where))
        self.assertIn("departments", str(where), "Household staff exclusion also applies to inactive tasks")


if __name__ == "__main__":
    unittest.main()
