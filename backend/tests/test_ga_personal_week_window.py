"""Selected-week reads use actual occurrences in disposable database schemas."""
import os
import unittest
from datetime import datetime
from unittest.mock import patch

from tests import test_ga_personal as fixtures
from app.services import ga_personal as service


@unittest.skipUnless(os.getenv("GA_PERSONAL_TEST_DATABASE_URL"), "Disposable PostgreSQL required")
class WeekWindowTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.GaPersonalDatabaseTests.asyncSetUp
    asyncTearDown = fixtures.GaPersonalDatabaseTests.asyncTearDown
    as_person = fixtures.GaPersonalDatabaseTests.as_person
    add_template = fixtures.GaPersonalDatabaseTests.add_template

    async def enable(self, enabled=True, starts_on="2026-11-02"):
        async with self.sessions() as db:
            space = await db.get(fixtures.Space, self.space_id)
            space.config = {**space.config, "automatic_generation": {"enabled": enabled, "starts_on": starts_on}}
            await db.commit()

    async def window(self, start="2026-11-16", end="2026-11-22"):
        # Freeze only the scheduler's clock, leaving real date arithmetic intact.
        with patch("app.services.ga_personal_scheduler.datetime") as clock:
            clock.now.return_value = datetime(2026, 11, 2, 12, tzinfo=service.TZ)
            return await self.client.get("/api/ga-personal/occurrences", params={"start": start, "end": end})

    async def test_future_week_is_prepared_for_members_once_without_inferring_conditions(self):
        await self.add_template()
        for changes in [dict(frequency="school_day"), dict(frequency="conditional"), dict(enabled=False)]:
            d = fixtures.definition()
            d.update(changes)
            await self.add_template(d)
        await self.enable()
        self.as_person("mrika")
        first = await self.window()
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(sorted(row["local_date"] for row in first.json()),
                         [f"2026-11-{day}" for day in range(16, 23)])
        second = await self.window()
        self.assertEqual({row["id"] for row in first.json()}, {row["id"] for row in second.json()})
        self.assertTrue(all(row["snapshot"]["frequency"] == "daily" for row in second.json()))
        compact = await self.window("20261116", "20261122")
        self.assertEqual({row["id"] for row in compact.json()}, {row["id"] for row in first.json()})

    async def test_paused_automation_and_past_dates_do_not_generate(self):
        await self.add_template()
        await self.enable(False)
        self.assertEqual((await self.window()).json(), [])
        await self.enable()
        self.assertEqual((await self.window("2026-10-19", "2026-10-25")).json(), [])
        await self.enable(starts_on="2026-11-20")
        rows = (await self.window()).json()
        self.assertEqual(sorted(row["local_date"] for row in rows), ["2026-11-20", "2026-11-21", "2026-11-22"])

    async def test_invalid_or_unbounded_ranges_are_rejected(self):
        for params in [{"start": "2026-11-16"}, {"end": "2026-11-22"},
                       {"start": "invalid", "end": "2026-11-22"},
                       {"start": "2026-11-22", "end": "2026-11-16"},
                       {"start": "2026-11-16", "end": "2026-11-23"},
                       {"day": "2026-11-16", "start": "2026-11-16", "end": "2026-11-22"}]:
            response = await self.client.get("/api/ga-personal/occurrences", params=params)
            self.assertEqual(response.status_code, 422, params)

    async def test_bounded_week_is_complete_even_above_global_500_row_limit(self):
        template = await self.add_template()
        import uuid
        async with self.sessions() as db:
            for i in range(510):
                day = "2026-11-16" if i < 505 else "2026-12-01"
                db.add(fixtures.Occurrence(space_id=self.space_id, template_id=uuid.UUID(template["id"]),
                    local_date=day, period_key=f"fixture-{i}", assignment_key="mrika", snapshot=fixtures.definition()))
            await db.commit()
        response = await self.window()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()), 505)
        self.assertEqual({row["local_date"] for row in response.json()}, {"2026-11-16"})
