"""Admin Tasks shows one shared comment per task: the latest one, whoever wrote it."""
import os
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/test")
os.environ.setdefault("JWT_SECRET", "shared-comments-secret")

from sqlalchemy.dialects import postgresql

from app.api.routers import tasks as api


class SharedCommentTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_comment_per_task_from_any_user(self):
        task_id, ga = uuid.uuid4(), uuid.uuid4()
        when = datetime(2026, 10, 19, 11, tzinfo=timezone.utc)
        result = Mock(all=Mock(return_value=[(task_id, "Pritet konfirmimi", ga, when)]))
        db = SimpleNamespace(execute=AsyncMock(return_value=result))
        rows = await api.shared_task_comments(api.SharedCommentsRequest(task_ids=[task_id]), db, SimpleNamespace(id=uuid.uuid4()))
        self.assertEqual([(row.task_id, row.comment, row.user_id) for row in rows], [(task_id, "Pritet konfirmimi", ga)])
        sql = str(db.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
        self.assertIn("DISTINCT ON (task_user_comments.task_id)", sql)
        self.assertIn("updated_at DESC", sql)
        self.assertNotIn("user_id =", sql)

    async def test_no_ids_skips_the_query(self):
        db = SimpleNamespace(execute=AsyncMock())
        self.assertEqual(await api.shared_task_comments(api.SharedCommentsRequest(), db, SimpleNamespace(id=uuid.uuid4())), [])
        db.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
