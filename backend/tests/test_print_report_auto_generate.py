import asyncio
from datetime import date
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from app.api.routers import tomorrow_print_report as routes


class ConcurrentGenerationTests(IsolatedAsyncioTestCase):
    async def test_simultaneous_first_visitors_both_receive_a_generated_report(self):
        gate = asyncio.Lock()
        exists = False
        saves = []

        class Connection:
            locked = False

            async def execute(self, query, parameters):
                assert "pg_advisory_xact_lock" in str(query)
                assert parameters == {"key": "tomorrow_print_generate|2026-10-22"}
                await gate.acquire()
                self.locked = True

            async def commit(self):
                if self.locked:
                    self.locked = False
                    gate.release()

        async def build(day, db):
            await asyncio.sleep(0)
            return {"target_date": "2026-10-23", "html": "Latest tasks"}

        async def save(db, **values):
            nonlocal exists
            was_present = exists
            await asyncio.sleep(0)
            if not was_present and exists:
                raise RuntimeError("Duplicate report kind/date")
            exists = True
            saves.append(values["user"].id)
            await db.commit()
            return SimpleNamespace(report_payload=values["report"])

        async def serialize(db, row):
            return row.report_payload

        with patch.object(routes, "build_tomorrow_print_report", side_effect=build), \
             patch.object(routes, "save_one_h_print_snapshot", side_effect=save), \
             patch.object(routes, "serialize_one_h_print_snapshot", side_effect=serialize):
            results = await asyncio.gather(*[
                routes.generate_snapshot(date(2026, 10, 22), Connection(), SimpleNamespace(id=visitor))
                for visitor in ("first", "second")
            ])
        self.assertEqual([result["html"] for result in results], ["Latest tasks", "Latest tasks"])
        self.assertEqual(saves, ["first", "second"])
