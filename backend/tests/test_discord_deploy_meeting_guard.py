import json
import os
import tempfile
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from scripts import wait_for_mira_deploy as guard


class MeetingGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_stops_both_bots_only_after_finalization(self):
        events = []
        occupied = iter([1, 1, 0])

        class Connection:
            @asynccontextmanager
            async def transaction(self):
                events.append("begin")
                yield
                events.append("commit")

            async def execute(self, sql):
                self_test.assertIn("IN SHARE MODE", sql)
                events.append("lock")

            async def fetchval(self, sql):
                if "to_regclass" in sql:
                    return True
                self_test.assertIn("FINALIZING", sql)
                self_test.assertIn("STAFF_PHASE", sql)
                return next(occupied)

            async def close(self):
                events.append("close")

        self_test = self
        names = ["primeflow-discord", "primeflow-discord-ai-agent"]

        def pm2(command, *args):
            if command == "jlist":
                return json.dumps([{"name": n, "pm2_env": {"status": "online"}} for n in names])
            events.append((command, *args))

        async def wait(_):
            self.assertEqual(events[-1], "commit")
            events.append("wait")

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "RUNNER_TEMP": tmp, "GITHUB_RUN_ID": "1", "GITHUB_RUN_ATTEMPT": "1"
        }), patch.object(guard, "pm2", pm2), patch.object(guard, "dotenv_values", return_value={"DATABASE_URL": "postgresql://test"}), patch.object(
            guard.asyncpg, "connect", AsyncMock(return_value=Connection())
        ), patch.object(guard.asyncio, "sleep", wait):
            await guard.wait_and_stop()
        self.assertEqual(events, ["begin","lock","commit","wait"] * 2
                         + ["begin","lock",("stop", names[0]),("stop", names[1]),"commit","close"])
