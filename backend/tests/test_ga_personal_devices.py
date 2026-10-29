"""Tablet credentials use generated disposable schemas, never the application DB."""
import asyncio
import os
import unittest
import uuid
from io import StringIO
from unittest.mock import patch

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import Depends
from sqlalchemy import select

from app.api.routers.ga_personal_devices import device_access
from app.config import settings
from app.models.ga_personal import GaPersonalDevice as Device, GaPersonalMember as Member
from app.models.ga_personal import GaPersonalDeviceOp as Operation, GaPersonalDeviceRecord as Record, GaPersonalOccurrence as Occurrence, GaPersonalEvent as Event
from app.models.user import User
from app.services import ga_personal as tasks
from tests import test_ga_personal as fixtures

TABLET = "11111111-1111-4111-8111-111111111111"
OTHER_TABLET = "22222222-2222-4222-8222-222222222222"


class DeviceMigrationTests(unittest.TestCase):
    def test_devices_migration_stays_in_private_schema(self):
        config = Config(); config.set_main_option("script_location", "alembic")
        scripts = ScriptDirectory.from_config(config)
        revision = scripts.get_revision("0176_ga_personal_devices")
        self.assertEqual(revision.down_revision, "0175_merge_discord_ga_personal")
        output = StringIO()
        operations = Operations(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}))
        with patch.object(revision.module, "op", operations):
            revision.module.upgrade()
        sql = output.getvalue()
        self.assertIn("CREATE TABLE IF NOT EXISTS ga_personal.devices", sql)
        self.assertIn("FOREIGN KEY(authorized_by) REFERENCES ga_personal.memberships", sql)
        self.assertNotIn("GRANT", sql)
        self.assertNotIn("INSERT", sql)


@unittest.skipUnless(os.getenv("GA_PERSONAL_TEST_DATABASE_URL"), "Set GA_PERSONAL_TEST_DATABASE_URL to a disposable PostgreSQL database")
class DeviceDatabaseTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = fixtures.GaPersonalDatabaseTests.asyncTearDown
    as_person = fixtures.GaPersonalDatabaseTests.as_person
    add_template = fixtures.GaPersonalDatabaseTests.add_template
    generate = fixtures.GaPersonalDatabaseTests.generate

    async def asyncSetUp(self):
        await fixtures.GaPersonalDatabaseTests.asyncSetUp(self)

        @self.app.get("/api/tablet-probe")
        async def probe(device=Depends(device_access)):
            return {"space_id": str(device.space_id)}

    async def create(self):
        response = await self.client.post("/api/ga-personal/devices", json={"name": "Tableti i familjes"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        return response.json()

    def headers(self, code, device_id=TABLET):
        return {"Authorization": "Bearer " + code, "X-Device-Id": device_id}

    async def test_admin_issues_one_time_secret_and_only_hash_is_stored(self):
        created = await self.create()
        rows = (await self.client.get("/api/ga-personal/devices")).json()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("code", rows[0])
        self.assertNotIn("token_hash", rows[0])
        async with self.sessions() as db:
            row = await db.get(Device, uuid.UUID(created["id"]))
            self.assertEqual(row.token_hash, tasks.digest(created["code"]))
            self.assertNotEqual(row.token_hash, created["code"])

    async def test_migration_creates_and_re_adopts_tables_in_the_disposable_schema(self):
        from sqlalchemy import inspect
        config = Config(); config.set_main_option("script_location", "alembic")
        migration = ScriptDirectory.from_config(config).get_revision("0176_ga_personal_devices").module
        async with self.engine.begin() as connection:
            def migrate(sync_connection):
                # These are only the generated per-test tables, via schema_translate_map.
                for table in [Record.__table__, Operation.__table__, Device.__table__]:
                    table.drop(sync_connection)
                with patch.object(migration, "op", Operations(MigrationContext.configure(sync_connection))):
                    migration.upgrade()
                    migration.upgrade()
                self.assertTrue({"devices", "device_ops", "device_records"}.issubset(
                    inspect(sync_connection).get_table_names(schema=self.private)))
            await connection.run_sync(migrate)
        await self.create()

    async def test_normal_members_and_company_admins_cannot_manage_devices(self):
        created = await self.create()
        for person in ["mrika", "outsider"]:
            self.as_person(person)
            self.assertEqual((await self.client.get("/api/ga-personal/devices")).status_code, 403)
            self.assertEqual((await self.client.post("/api/ga-personal/devices", json={"name": "Tablet"})).status_code, 403)
            self.assertEqual((await self.client.post(f'/api/ga-personal/devices/{created["id"]}/revoke')).status_code, 403)

    async def test_both_headers_required_binding_persists_and_device_has_no_work_access(self):
        created = await self.create()
        code = created["code"]
        for headers in [{}, {"Authorization": "Bearer " + code}, {"X-Device-Id": TABLET},
                        self.headers("wrong-token"), self.headers(code, "bad device id")]:
            self.assertEqual((await self.client.get("/api/tablet-probe", headers=headers)).status_code, 401)
        response = await self.client.get("/api/tablet-probe", headers=self.headers(code))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["space_id"], str(self.space_id))
        self.assertEqual((await self.client.get("/api/tablet-probe", headers=self.headers(code))).status_code, 200)
        self.assertEqual((await self.client.get("/api/tablet-probe", headers=self.headers(code, OTHER_TABLET))).status_code, 401)
        for path in ["/api/auth/me", "/api/ga-personal/templates", "/api/ga-personal/discord/settings"]:
            self.assertEqual((await self.client.get(path, headers=self.headers(code))).status_code, 401)
        rows = (await self.client.get("/api/ga-personal/devices")).json()
        self.assertEqual(rows[0]["device_id"], TABLET)
        self.assertIsNotNone(rows[0]["last_seen_at"])

    async def test_only_one_device_can_claim_the_same_code_concurrently(self):
        code = (await self.create())["code"]
        responses = await asyncio.gather(*[
            self.client.get("/api/tablet-probe", headers=self.headers(code, name)) for name in [TABLET, OTHER_TABLET]
        ])
        self.assertEqual(sorted(response.status_code for response in responses), [200, 401])

    async def test_revocation_disabling_module_and_authorizer_changes_reject_access(self):
        created = await self.create()
        headers = self.headers(created["code"])
        with patch.object(settings, "GA_PERSONAL_ENABLED", False):
            self.assertEqual((await self.client.get("/api/tablet-probe", headers=headers)).status_code, 404)
        for model, attribute in [(Member, "is_admin"), (Member, "active"), (User, "is_active")]:
            async with self.sessions() as db:
                row = (await db.execute(select(model).where(
                    model.user_id == self.ids["gane"] if model is Member else model.id == self.ids["gane"]
                ))).scalar_one()
                setattr(row, attribute, False); await db.commit()
            self.assertEqual((await self.client.get("/api/tablet-probe", headers=headers)).status_code, 401)
            async with self.sessions() as db:
                row = (await db.execute(select(model).where(
                    model.user_id == self.ids["gane"] if model is Member else model.id == self.ids["gane"]
                ))).scalar_one()
                setattr(row, attribute, True); await db.commit()
        for _ in range(2):
            response = await self.client.post(f'/api/ga-personal/devices/{created["id"]}/revoke')
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((await self.client.get("/api/tablet-probe", headers=headers)).status_code, 401)

    async def state(self, code, since=None, tablet=TABLET):
        response = await self.client.get("/api/ga-personal/device/state", params={"since": since} if since else {},
                                         headers=self.headers(code, tablet))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        return response.json()

    async def send(self, code, ops, tablet=TABLET):
        return await self.client.post("/api/ga-personal/device/ops", json={"device_id": tablet, "ops": ops}, headers=self.headers(code, tablet))

    def op(self, kind, at=1000, **data):
        return {"op_id": str(uuid.uuid4()), "type": kind, "at": at, **data}

    async def test_state_exports_kujtesa_cards_without_inventing_time_or_school_days(self):
        timed = fixtures.definition(area_id="rrita_room", estimated_minutes=45)
        timed["steps"] = ["Rregullo shtratin.", "Vendosi teshat në vend."]
        await self.add_template(timed)
        untimed = fixtures.definition(); untimed["due_time"] = None
        await self.add_template(untimed)
        school = fixtures.definition(); school["frequency"] = "school_day"
        await self.add_template(school)
        code = (await self.create())["code"]
        state = await self.state(code)
        self.assertEqual(len(state["tasks"]), 2)
        card = next(card for card in state["tasks"] if card["start"])
        self.assertEqual({key: card[key] for key in ["person_id", "start", "end", "area", "kind", "group", "speech", "days", "date", "alarm"]},
            {"person_id": "mrika", "start": "17:00", "end": "17:45", "area": "room", "kind": "task", "group": "upkeep", "speech": "Tidy your room", "days": None, "date": None, "alarm": True})
        self.assertEqual(card["steps"], timed["steps"])
        self.assertFalse(next(card for card in state["tasks"] if not card["start"])["alarm"])
        self.assertEqual((await self.state(code, state["cursor"]))["tasks"], state["tasks"])

    async def test_ops_sync_events_tombstones_arrivals_and_stale_offline_retries(self):
        code = (await self.create())["code"]
        initial = await self.state(code)
        event = {"id": "ev_hollywood_rrita", "title": "Hollywood", "person_id": "rrita", "start": "19:00", "end": "20:00", "kind": "activity", "area": "activity", "date": "2026-10-29", "speech": "Get ready for Hollywood"}
        upsert = self.op("event_upsert", 2000, event=event)
        arrival = self.op("arrival", 2000, person_id="rrita", day="2026-10-29")
        response = await self.send(code, [upsert, arrival])
        self.assertEqual(response.json(), {"accepted": [upsert["op_id"], arrival["op_id"]]})
        self.assertEqual((await self.send(code, [upsert, arrival])).json(), response.json())
        state = await self.state(code, initial["cursor"])
        self.assertEqual(state["events"][0]["title"], "Hollywood")
        self.assertEqual(state["arrivals"], [{"person_id": "rrita", "day": "2026-10-29", "at": 2000}])
        self.assertEqual((await self.state(code, state["cursor"]))["events"], [])
        deletion = self.op("event_delete", 3000, id=event["id"])
        stale = self.op("event_upsert", 1000, event={**event, "title": "Old title"})
        await self.send(code, [deletion, stale, self.op("arrival", 1000, person_id="rrita", day="2026-10-29")])
        current = await self.state(code)
        self.assertEqual(current["events"], [{"id": event["id"], "deleted": True, "at": 3000}])
        self.assertEqual(current["arrivals"][0]["at"], 2000)
        async with self.sessions() as db:
            self.assertEqual(len((await db.execute(select(Operation))).scalars().all()), 5)
            self.assertEqual(len((await db.execute(select(Record))).scalars().all()), 2)

    async def test_status_updates_primeflow_and_is_shared_with_another_device(self):
        definition = fixtures.definition(); definition["steps"] = ["Hapi 1", "Hapi 2"]
        await self.add_template(definition)
        code = (await self.create())["code"]
        state = await self.state(code)
        identity = state["tasks"][0]["id"]
        progress = self.op("status", 1000, task_id=identity, period="2026-11-07", status="in_progress", step=1)
        response = await self.send(code, [progress])
        self.assertEqual(response.status_code, 200, response.text)
        done = self.op("status", 2000, task_id=identity, period="2026-11-07", status="done", step=2)
        self.assertEqual((await self.send(code, [done, done])).status_code, 200)
        checkpoint = (await self.state(code))["cursor"]
        stale = self.op("status", 500, task_id=identity, period="2026-11-07", status="needs_help", step=0)
        self.assertEqual((await self.send(code, [stale])).status_code, 200)
        other = (await self.create())["code"]
        result = await self.state(other, checkpoint, tablet=OTHER_TABLET)
        self.assertEqual(result["statuses"], [{"task_id": identity, "period": "2026-11-07", "status": "done", "step": 2, "at": 2000}])
        async with self.sessions() as db:
            row = (await db.execute(select(Occurrence))).scalar_one()
            self.assertEqual(row.status, "done")
            events = (await db.execute(select(Event).where(Event.kind == "device_status"))).scalars().all()
            self.assertEqual(len(events), 2)
            record = (await db.execute(select(Record).where(Record.kind == "status"))).scalar_one()
            self.assertEqual(record.payload["step"], 2)

    async def test_weekend_uses_saturday_period_even_when_scheduled_for_sunday(self):
        d = fixtures.definition(); d.update(frequency="weekly", weekdays=[6])
        await self.add_template(d)
        code = (await self.create())["code"]
        card = (await self.state(code))["tasks"][0]
        self.assertTrue(card["weekend"])
        self.assertEqual(card["days"], [6])
        op = self.op("status", task_id=card["id"], period="2026-11-07", status="done", step=0)
        response = await self.send(code, [op])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((await self.state(code))["statuses"][0]["period"], "2026-11-07")

    async def test_legacy_source_ids_and_v1_aliases_update_the_canonical_task_without_duplicates(self):
        from app.models.ga_personal import GaPersonalTemplate as Template
        template = await self.add_template()
        async with self.sessions() as db:
            row = await db.get(Template, uuid.UUID(template["id"]))
            row.source_id = "mrika_room_daily"
            await db.commit()
        code = (await self.create())["code"]
        identity = (await self.state(code))["tasks"][0]["id"]
        for timestamp, source in enumerate(["mrika_room_daily", "mrika_room"], start=1):
            op = self.op("status", timestamp * 1000, task_id=source, period="2026-11-07", status="done")
            response = await self.send(code, [op])
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"accepted": [op["op_id"]]})
            checkpoint = (await self.state(code))["cursor"]
            self.assertEqual((await self.send(code, [op])).status_code, 200)
            state = await self.state(code, checkpoint)
            self.assertEqual([value["task_id"] for value in state["statuses"]], [identity])
        async with self.sessions() as db:
            self.assertEqual(len((await db.execute(select(Operation))).scalars().all()), 2)
            self.assertEqual(len((await db.execute(select(Occurrence))).scalars().all()), 1)
            self.assertEqual(len((await db.execute(select(Record).where(Record.kind == "status"))).scalars().all()), 1)

            row = await db.get(Template, uuid.UUID(template["id"]))
            row.archived = True
            await db.commit()
        self.assertEqual((await self.send(code, [op])).status_code, 200)

    async def test_legacy_ids_do_not_guess_an_assignee_or_cross_family_spaces(self):
        from app.models.ga_personal import GaPersonalTemplate as Template
        template = await self.add_template(fixtures.definition())
        async with self.sessions() as db:
            row = await db.get(Template, uuid.UUID(template["id"]))
            row.source_id = "ambiguous-task"
            row.definition = {**row.definition, "assignees": ["mrika", "lirza"]}
            other = fixtures.Space(key="other-family", password_hash="unused", config={})
            db.add(other)
            await db.flush()
            db.add(Template(space_id=other.id, source_id="private-other-task", created_by=self.ids["gane"],
                            definition=fixtures.definition()))
            await db.commit()
        code = (await self.create())["code"]
        for identity in ["ambiguous-task", "private-other-task"]:
            op = self.op("status", task_id=identity, period="2026-11-07", status="done")
            response = await self.send(code, [op])
            self.assertEqual(response.status_code, 422, response.text)
            self.assertIn(identity, response.json()["detail"])
        async with self.sessions() as db:
            self.assertEqual(len((await db.execute(select(Operation))).scalars().all()), 0)
            self.assertEqual(len((await db.execute(select(Occurrence))).scalars().all()), 0)

    async def test_status_before_event_upsert_is_atomic_and_retryable(self):
        code = (await self.create())["code"]
        status = self.op("status", 2000, task_id="offline-event", period="2026-11-07", status="done")
        upsert = self.op("event_upsert", 1000, event={"id": "offline-event", "title": "Activity", "steps": ["One", "Two"]})
        ops = [status, upsert]
        for _ in range(2):
            response = await self.send(code, ops)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"accepted": [op["op_id"] for op in ops]})
        state = await self.state(code)
        self.assertEqual(state["statuses"][0]["task_id"], "offline-event")
        self.assertEqual(state["statuses"][0]["step"], 2)
        invalid = self.op("status", task_id="missing-task", period="2026-11-07", status="done")
        later = self.op("event_upsert", event={"id": "rolled-back-event", "title": "Never committed"})
        response = await self.send(code, [invalid, later])
        self.assertEqual(response.status_code, 422)
        self.assertIn(invalid["task_id"], response.json()["detail"])
        self.assertIn(invalid["op_id"], response.json()["detail"])
        self.assertEqual([event["id"] for event in (await self.state(code))["events"]], ["offline-event"])

    async def test_concurrent_retries_commit_one_operation_and_one_completion(self):
        await self.add_template()
        code = (await self.create())["code"]
        task_id = (await self.state(code))["tasks"][0]["id"]
        op = self.op("status", task_id=task_id, period="2026-11-07", status="done", step=0)
        responses = await asyncio.gather(self.send(code, [op]), self.send(code, [op]))
        for response in responses:
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json(), {"accepted": [op["op_id"]]})
        async with self.sessions() as db:
            self.assertEqual(len((await db.execute(select(Operation))).scalars().all()), 1)
            self.assertEqual(len((await db.execute(select(Event).where(Event.kind == "device_status"))).scalars().all()), 1)

    async def test_newer_status_wins_and_event_status_retains_step_progress(self):
        await self.add_template()
        code = (await self.create())["code"]
        task_id = (await self.state(code))["tasks"][0]["id"]
        done = self.op("status", 1000, task_id=task_id, period="2026-11-07", status="done", step=0)
        progress = self.op("status", 2000, task_id=task_id, period="2026-11-07", status="in_progress", step=1)
        event = self.op("event_upsert", event={"id": "event-1", "title": "Activity", "steps": ["One", "Two"]})
        event_status = self.op("status", 2000, task_id="event-1", period="2026-11-07", status="in_progress", step=1)
        response = await self.send(code, [done, progress, event, event_status])
        self.assertEqual(response.status_code, 200, response.text)
        statuses = (await self.state(code))["statuses"]
        self.assertEqual({item["status"] for item in statuses}, {"in_progress"})
        self.assertEqual({item["step"] for item in statuses}, {1})
        async with self.sessions() as db:
            row = (await db.execute(select(Occurrence))).scalar_one()
            self.assertEqual(row.status, "in_progress")
            self.assertIsNone(row.completed_at)
    async def test_primeflow_status_changes_appear_in_incremental_state(self):
        await self.add_template()
        await self.generate()
        code = (await self.create())["code"]
        before = await self.state(code)
        rows = (await self.client.get("/api/ga-personal/occurrences")).json()
        response = await self.client.post(f'/api/ga-personal/occurrences/{rows[0]["id"]}/actions',
            json={"status": "done", "expected_version": 1, "request_id": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 200, response.text)
        result = await self.state(code, before["cursor"])
        self.assertEqual(result["statuses"][0]["status"], "done")
        self.assertEqual(result["statuses"][0]["task_id"], result["tasks"][0]["id"])

    async def test_retried_pending_op_resends_a_newer_primeflow_status_after_cursor_advanced(self):
        await self.add_template()
        code = (await self.create())["code"]
        identity = (await self.state(code))["tasks"][0]["id"]
        progress = self.op("status", task_id=identity, period="2026-11-07", status="in_progress", step=0)
        self.assertEqual((await self.send(code, [progress])).status_code, 200)
        row = (await self.client.get("/api/ga-personal/occurrences")).json()[0]
        response = await self.client.post(f'/api/ga-personal/occurrences/{row["id"]}/actions',
            json={"status": "done", "expected_version": row["version"], "request_id": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 200, response.text)
        skipped_while_pending = await self.state(code)
        self.assertEqual((await self.send(code, [progress])).status_code, 200)
        repeated = await self.state(code, skipped_while_pending["cursor"])
        self.assertEqual(repeated["statuses"][0]["status"], "done")

    async def test_conflicting_op_id_or_invalid_batch_rolls_back_every_new_operation(self):
        code = (await self.create())["code"]
        first = self.op("arrival", person_id="rrita", day="2026-10-29")
        self.assertEqual((await self.send(code, [first])).status_code, 200)
        conflict = {**first, "person_id": "mrika"}
        newer = self.op("arrival", 3000, person_id="gane", day="2026-10-29")
        self.assertEqual((await self.send(code, [newer, conflict])).status_code, 409)
        state = await self.state(code)
        self.assertEqual(len(state["arrivals"]), 1)
        invalid = self.op("status", task_id="not-a-task", period="2026-10-29", status="done")
        self.assertEqual((await self.send(code, [newer, invalid])).status_code, 422)
        self.assertEqual(len((await self.state(code))["arrivals"]), 1)
        mismatch = await self.client.post("/api/ga-personal/device/ops", headers=self.headers(code),
            json={"device_id": OTHER_TABLET, "ops": []})
        self.assertEqual(mismatch.status_code, 403)

    async def test_rotation_exports_explicit_three_day_recurrence(self):
        d = fixtures.definition(); d.update(assignment="rotation", assignees=[], rotation_id="nala", reminder_group="nala")
        await self.add_template(d)
        code = (await self.create())["code"]
        cards = (await self.state(code))["tasks"]
        self.assertEqual(len(cards), 3)
        card = next(card for card in cards if card["person_id"] == "rrita")
        self.assertEqual(card["date"], "2026-10-30")
        self.assertEqual(card["repeat"], {"every": 3, "unit": "day", "days": None, "until": None})
        wrong = self.op("status", task_id=card["id"], period="2026-10-31", status="done")
        self.assertEqual((await self.send(code, [wrong])).status_code, 422)
        valid = self.op("status", task_id=card["id"], period="2026-10-30", status="done")
        response = await self.send(code, [valid])
        self.assertEqual(response.status_code, 200, response.text)
