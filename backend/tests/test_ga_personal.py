"""Real transactions in generated schemas; never uses the configured app DB."""
import os
import asyncio
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.api.routers import auth
from app.api.routers import ga_personal as api
from app.auth.security import create_access_token, create_refresh_token, decode_token, get_password_hash
from app.config import settings
from app.db import Base, get_db
from app.models.department import Department
from app.models.enums import UserRole
from app.models.ga_personal import (
    SCHEMA, GaPersonalSpace as Space, GaPersonalMember as Member,
    GaPersonalTemplate as Template, GaPersonalOccurrence as Occurrence, GaPersonalEvent as Event,
    GaPersonalDelivery as Delivery,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.ga_personal import TemplateDefinition
from app.services import ga_personal as service


def definition(**extra):
    return TemplateDefinition(title="Puna e provës", assignees=["mrika"], frequency="daily", due_time="17:00", enabled=True, **extra).model_dump(mode="json")


def dataset():
    return {"format": "mira.ga_personal.dataset", "format_version": 1, "module": {"timezone": "Europe/Belgrade"},
        "people": [{"id": p} for p in sorted(service.PEOPLE)], "areas": [{"id": "home"}],
        "rotations": [{"id": "nala", "anchor_date": "2026-10-30", "members": [
            {"position": i, "person_id": p} for i, p in enumerate(["rrita", "mrika", "lirza"])]}],
        "task_templates": [{"id": "sample", "title": "Model prove", "area_id": "home", "assignment": "fixed",
            "person_id": "mrika", "frequency": "daily", "readiness": "ready_after_setup", "steps": [
                {"position": 1, "instruction": "Hap ndihmën kur të duhet."}], "details": {"reminder_group": "daily_upkeep"}}]}


class GaPersonalRulesTests(unittest.TestCase):
    def test_rotation_crosses_week_and_dst_using_dates(self):
        for day, expected in [("2026-11-01", "lirza"), ("2026-11-02", "rrita"), ("2026-11-08", "rrita")]:
            self.assertEqual(service.rotation_owner(date.fromisoformat(day), "2026-10-30"), expected)
        self.assertIsNone(service.rotation_owner(date(2026, 10, 29), "2026-10-30"))
        # 25h DST day must advance rotation by one calendar day, not seconds.
        self.assertEqual(service.rotation_owner(date(2026, 10, 26), "2026-10-24"), "lirza")

    def test_unknown_schedule_and_school_day_are_not_guessed(self):
        d = definition()
        d.update(frequency="school_day")
        self.assertFalse(service.scheduled(d, date(2026, 11, 2)))
        self.assertTrue(service.scheduled(d, date(2026, 11, 2), school_day=True))
        with self.assertRaises(ValueError):
            TemplateDefinition(title="Roki", assignees=["rrita"], frequency="near_daily", due_time="17:00", enabled=True)
        self.assertEqual(service.period_key({"frequency": "weekly"}, date(2026, 11, 7)), service.period_key({"frequency": "weekly"}, date(2026, 11, 8)))

    def test_migration_is_private_and_has_no_seed_or_public_grants(self):
        config = Config(); config.set_main_option("script_location", "alembic")
        migration = ScriptDirectory.from_config(config).get_revision("0171_ga_personal").module
        output = StringIO()
        operations = Operations(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}))
        with patch.object(migration, "op", operations):
            migration.upgrade()
        sql = output.getvalue()
        self.assertIn("CREATE SCHEMA IF NOT EXISTS ga_personal", sql)
        self.assertIn("REVOKE ALL ON SCHEMA ga_personal FROM PUBLIC", sql)
        self.assertIn("UNIQUE (space_id, template_id, period_key, assignment_key)", sql)
        self.assertNotIn("INSERT INTO", sql)
        self.assertNotIn("GRANT SELECT", sql)


@unittest.skipUnless(os.getenv("GA_PERSONAL_TEST_DATABASE_URL"), "Set GA_PERSONAL_TEST_DATABASE_URL to a disposable PostgreSQL database")
class GaPersonalDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        asyncio.get_running_loop().slow_callback_duration = 2
        self.public = "ga_test_" + uuid.uuid4().hex
        self.private = "ga_private_test_" + uuid.uuid4().hex
        self.engine = create_async_engine(os.environ["GA_PERSONAL_TEST_DATABASE_URL"],
            connect_args={"server_settings": {"search_path": self.public}},
            execution_options={"schema_translate_map": {None: self.public, SCHEMA: self.private}})
        tables = [t for t in Base.metadata.tables.values() if t.schema == SCHEMA] + [Department.__table__, User.__table__, RefreshToken.__table__]
        async with self.engine.begin() as c:
            await c.execute(text(f'CREATE SCHEMA "{self.public}"'))
            await c.execute(text(f'CREATE SCHEMA "{self.private}"'))
            await c.run_sync(lambda conn: Base.metadata.create_all(conn, tables=tables))
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.ids = {p: uuid.uuid4() for p in ["mrika", "lirza", "rrita", "gane", "outsider"]}
        self.sids = {p: uuid.uuid4().hex for p in self.ids}
        self.password = "local-test-password-only"
        async with self.sessions() as db:
            space = Space(key="ga_personal", password_hash=get_password_hash(self.password), config={"rotation_anchor": "2026-10-30"})
            db.add(space)
            for p, uid in self.ids.items():
                db.add(User(id=uid, email=p+"@example.test", full_name="Test "+p, password_hash="unused", is_active=True,
                            role=UserRole.ADMIN if p == "outsider" else UserRole.STAFF))
            await db.flush()
            self.space_id = space.id
            for p, uid in self.ids.items():
                db.add(RefreshToken(user_id=uid, jti=self.sids[p], expires_at=service.utcnow()+timedelta(days=1)))
                if p != "outsider":
                    db.add(Member(space_id=space.id, user_id=uid, person_key=p, is_admin=p=="gane", active=True))
            await db.commit()
        app = FastAPI()
        app.include_router(api.router, prefix="/api/ga-personal")
        app.include_router(auth.router, prefix="/api/auth")
        self.app = app
        async def database():
            async with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = database
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test.local")
        self.patchers = [patch.object(settings, "GA_PERSONAL_ENABLED", True), patch.object(settings, "AUTH_COOKIE_SECURE", True)]
        for p in self.patchers: p.start()
        self.as_person("gane")

    async def asyncTearDown(self):
        await self.client.aclose()
        for p in reversed(self.patchers): p.stop()
        async with self.engine.begin() as c:
            await c.execute(text(f'DROP SCHEMA "{self.private}" CASCADE'))
            await c.execute(text(f'DROP SCHEMA "{self.public}" CASCADE'))
        await self.engine.dispose()

    def as_person(self, person):
        self.person = person
        self.client.headers["Authorization"] = "Bearer " + create_access_token(
            user_id=self.ids[person], role="ADMIN" if person == "outsider" else "STAFF", department_id=None, session_id=self.sids[person])

    async def add_template(self, d=None):
        r = await self.client.post("/api/ga-personal/templates", json={"definition": d or definition()})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def generate(self, day="2026-11-07"):
        r = await self.client.post("/api/ga-personal/generate", json={"day": day})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def test_nonmember_including_work_admin_cannot_read(self):
        self.as_person("outsider")
        self.assertEqual((await self.client.get("/api/ga-personal/access")).json(), {"available": False, "unlocked": False})
        for path in ["workspace", "templates", "occurrences", "history", "discord/settings"]:
            self.assertEqual((await self.client.get("/api/ga-personal/"+path)).status_code, 403)

    async def test_members_use_normal_login_without_password_cookie_or_session_id(self):
        for person in ["gane", "mrika", "lirza", "rrita"]:
            self.client.headers["Authorization"] = "Bearer " + create_access_token(
                user_id=self.ids[person], role="STAFF", department_id=None)
            self.client.cookies.clear()
            access = await self.client.get("/api/ga-personal/access")
            self.assertEqual(access.json(), {"available": True, "unlocked": True})
            self.assertEqual(access.headers["cache-control"], "private, no-store")
            self.assertNotIn("set-cookie", access.headers)
            for path in ["workspace", "templates", "occurrences", "history"]:
                self.assertEqual((await self.client.get("/api/ga-personal/"+path)).status_code, 200)
        async with self.sessions() as db:
            space = await db.get(Space, self.space_id)
            space.password_hash = None
            await db.commit()
        self.assertEqual((await self.client.get("/api/ga-personal/workspace")).status_code, 200)

    async def test_normal_authentication_and_feature_flag_are_required(self):
        self.client.headers.pop("Authorization")
        for path in ["access", "workspace", "templates", "occurrences", "history"]:
            self.assertEqual((await self.client.get("/api/ga-personal/"+path)).status_code, 401)
        self.client.headers["Authorization"] = "Bearer invalid-token"
        self.assertEqual((await self.client.get("/api/ga-personal/workspace")).status_code, 401)
        self.as_person("gane")
        with patch.object(settings, "GA_PERSONAL_ENABLED", False):
            self.assertEqual((await self.client.get("/api/ga-personal/access")).json(), {"available": False, "unlocked": False})
            self.assertEqual((await self.client.get("/api/ga-personal/workspace")).status_code, 404)
        async with self.sessions() as db:
            user = await db.get(User, self.ids["gane"])
            user.is_active = False
            await db.commit()
        self.assertEqual((await self.client.get("/api/ga-personal/workspace")).status_code, 401)

    async def test_removed_extra_login_endpoints_and_private_validation(self):
        for method, path in [("POST", "unlock"), ("POST", "lock"), ("POST", "password/setup"), ("PUT", "password")]:
            self.assertEqual((await self.client.request(method, "/api/ga-personal/"+path, json={"password": "unused"})).status_code, 404)
        invalid = dataset(); invalid["rotations"] = [None]
        response = await self.client.post("/api/ga-personal/import/preview", json={"dataset": invalid})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.headers["cache-control"], "private, no-store")

    async def test_individual_multi_assignment_completion_and_reminder_cancellation(self):
        d = definition(); d["assignees"] = ["mrika", "rrita"]
        await self.add_template(d)
        self.assertEqual((await self.generate())["created"], 2)
        self.assertEqual((await self.generate())["created"], 0)
        rows = (await self.client.get("/api/ga-personal/occurrences")).json()
        target = next(o for o in rows if o["snapshot"]["assignees"] == ["mrika"])
        async with self.sessions() as db:
            db.add(Delivery(occurrence_id=uuid.UUID(target["id"]), scheduled_at=service.utcnow()))
            await db.commit()
        self.as_person("mrika")
        payload = {"status": "done", "expected_version": 1, "request_id": str(uuid.uuid4())}
        endpoint = f'/api/ga-personal/occurrences/{target["id"]}/actions'
        r = await self.client.post(endpoint, json=payload)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((await self.client.post(endpoint, json=payload)).status_code, 200)
        async with self.sessions() as db:
            self.assertEqual((await db.execute(select(Delivery.status))).scalar_one(), "cancelled")
            count = (await db.execute(select(func.count(Event.id)).where(Event.occurrence_id == uuid.UUID(target["id"])))).scalar_one()
            self.assertEqual(count, 1)
        rows = (await self.client.get("/api/ga-personal/occurrences")).json()
        self.assertEqual(sum(o["status"] == "done" for o in rows), 1)
        other = next(o for o in rows if o["snapshot"]["assignees"] == ["rrita"])
        self.assertEqual((await self.client.post(f'/api/ga-personal/occurrences/{other["id"]}/actions', json={**payload, "request_id": str(uuid.uuid4())})).status_code, 403)

    async def test_weekend_dedup_and_template_edits_preserve_snapshots(self):
        d = definition(); d.update(frequency="weekly", weekdays=[5, 6], reminder_group="weekend_deep_clean")
        t = await self.add_template(d)
        self.assertEqual((await self.generate("2026-11-06"))["created"], 0)
        self.assertEqual((await self.generate("2026-11-07"))["created"], 1)
        self.assertEqual((await self.generate("2026-11-08"))["created"], 0)
        d["title"] = "Titull i ri"
        self.assertEqual((await self.client.put('/api/ga-personal/templates/'+t["id"], json={"definition": d, "expected_version": 1})).status_code, 200)
        old = (await self.client.get("/api/ga-personal/occurrences")).json()[0]
        self.assertEqual(old["snapshot"]["title"], "Puna e provës")
        self.assertEqual((await self.client.put('/api/ga-personal/templates/'+t["id"], json={"definition": d, "expected_version": 1})).status_code, 409)

    async def test_import_is_previewed_idempotent_and_preserves_edits(self):
        data = dataset()
        preview = (await self.client.post("/api/ga-personal/import/preview", json={"dataset": data})).json()
        self.assertEqual(preview["templates"], 1)
        self.assertEqual(preview["unresolved_members"], [])
        for _ in range(2):
            r = await self.client.post("/api/ga-personal/import/apply", json={"dataset": data, "expected_hash": preview["dataset_hash"]})
            self.assertEqual(r.status_code, 200, r.text)
        rows = (await self.client.get("/api/ga-personal/templates")).json()
        self.assertEqual(len(rows), 1); self.assertFalse(rows[0]["definition"]["enabled"])
        t = rows[0]; d = t["definition"]; d["title"] = "Ndryshim manual"
        await self.client.put('/api/ga-personal/templates/'+t["id"], json={"definition": d, "expected_version": 1})
        self.assertEqual((await self.client.post("/api/ga-personal/import/apply", json={"dataset": data, "expected_hash": preview["dataset_hash"]})).status_code, 409)

    async def test_member_can_only_create_and_manage_own_models(self):
        self.as_person("mrika")
        t = await self.add_template()
        d = definition(); d["assignees"] = ["rrita"]
        self.assertEqual((await self.client.post("/api/ga-personal/templates", json={"definition": d})).status_code, 403)
        self.assertEqual((await self.client.get("/api/ga-personal/templates")).status_code, 200)

    async def test_concurrent_generation_and_stale_actions_are_serialized(self):
        await self.add_template()
        results = await asyncio.gather(*[self.client.post("/api/ga-personal/generate", json={"day": "2026-11-07"}) for _ in range(2)])
        self.assertEqual(sorted(r.json()["created"] for r in results), [0, 1])
        row = (await self.client.get("/api/ga-personal/occurrences")).json()[0]
        path = f'/api/ga-personal/occurrences/{row["id"]}/actions'
        results = await asyncio.gather(*[self.client.post(path, json={"status": "done", "expected_version": 1, "request_id": str(uuid.uuid4())}) for _ in range(2)])
        self.assertEqual(sorted(r.status_code for r in results), [200, 409])

    async def test_membership_revocation_removes_access(self):
        async with self.sessions() as db:
            member = (await db.execute(select(Member).where(Member.user_id == self.ids["gane"]))).scalar_one()
            member.active = False; await db.commit()
        self.assertEqual((await self.client.get("/api/ga-personal/templates")).status_code, 403)

    async def test_one_off_creates_individual_occurrences_without_admin_generation(self):
        self.as_person("mrika")
        d = definition(); d.update(frequency="once", on_date="2026-11-07")
        await self.add_template(d)
        rows = (await self.client.get("/api/ga-personal/occurrences")).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["snapshot"]["assignees"], ["mrika"])

    async def test_untimed_one_off_persists_immediately_without_reminders_or_duplicates(self):
        self.as_person("mrika")
        d = definition()
        d.update(frequency="once", on_date="2026-11-07", due_time=None)
        template = await self.add_template(d)
        # A separate GET/session must see the committed task, not just a response echo.
        rows = (await self.client.get("/api/ga-personal/occurrences?day=2026-11-07")).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["template_id"], template["id"])
        self.assertEqual(rows[0]["snapshot"]["assignees"], ["mrika"])
        self.assertIsNone(rows[0]["due_at"])
        self.assertEqual((await self.client.get("/api/ga-personal/templates")).json()[0]["definition"], template["definition"])
        self.as_person("gane")
        self.assertEqual((await self.generate())["created"], 0)
        async with self.sessions() as db:
            self.assertEqual((await db.execute(select(func.count(Delivery.id)))).scalar_one(), 0)
            self.assertEqual((await db.execute(select(func.count(Occurrence.id)))).scalar_one(), 1)

    async def test_one_off_still_requires_a_date_to_be_activated(self):
        d = definition()
        d.update(frequency="once", on_date=None, due_time=None)
        response = await self.client.post("/api/ga-personal/templates", json={"definition": d})
        self.assertEqual(response.status_code, 422)
        self.assertEqual((await self.client.get("/api/ga-personal/templates")).json(), [])

    async def test_weekday_api_excludes_weekend_duties(self):
        d = definition(); d.update(frequency="weekly", weekdays=[5, 6])
        await self.add_template(d); await self.generate()
        self.assertEqual((await self.client.get("/api/ga-personal/occurrences?day=2026-11-06")).json(), [])
        self.assertEqual(len((await self.client.get("/api/ga-personal/occurrences?day=2026-11-08")).json()), 1)

    async def test_quick_edit_changes_only_instance_and_retains_authorization_and_history(self):
        template = await self.add_template(); await self.generate()
        row = (await self.client.get("/api/ga-personal/occurrences")).json()[0]
        self.assertTrue(row["can_edit"])
        path = f'/api/ga-personal/occurrences/{row["id"]}'
        body = {"expected_version": row["version"], "request_id": str(uuid.uuid4()),
                "local_date": row["local_date"], "due_time": "18:30", "assignees": ["rrita"]}
        async with self.sessions() as db:
            db.add(Delivery(occurrence_id=uuid.UUID(row["id"]), scheduled_at=service.utcnow()))
            await db.commit()
        response = await self.client.patch(path, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["snapshot"]["assignees"], ["rrita"])
        self.assertEqual(result["due_at"], "2026-11-07T17:30:00+00:00")
        self.assertEqual(result["period_key"], row["period_key"])
        self.assertEqual((await self.client.patch(path, json=body)).status_code, 200)
        models = (await self.client.get("/api/ga-personal/templates")).json()
        self.assertEqual(models[0]["definition"], template["definition"])
        self.assertEqual((await self.generate())["created"], 0)
        async with self.sessions() as db:
            self.assertEqual((await db.execute(select(Delivery.status))).scalar_one(), "cancelled")
            events = (await db.execute(select(Event).where(Event.kind == "occurrence_updated"))).scalars().all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].payload["before"]["assignees"], ["mrika"])
        self.as_person("mrika")
        self.assertEqual((await self.client.patch(path, json={**body, "expected_version": 2, "request_id": str(uuid.uuid4())})).status_code, 403)

    async def test_quick_edit_future_updates_template_without_duplicate_or_resolved_history_edits(self):
        template = await self.add_template(); await self.generate()
        row = (await self.client.get("/api/ga-personal/occurrences")).json()[0]
        body = {"expected_version": 1, "request_id": str(uuid.uuid4()), "local_date": row["local_date"],
                "due_time": "18:30", "assignees": ["rrita"], "apply_to_future": True, "expected_template_version": 1}
        path = f'/api/ga-personal/occurrences/{row["id"]}'
        self.assertEqual((await self.client.patch(path, json=body)).status_code, 200)
        self.assertEqual((await self.generate())["created"], 0)
        self.assertEqual((await self.generate("2026-11-08"))["created"], 1)
        rows = (await self.client.get("/api/ga-personal/occurrences")).json()
        tomorrow = next(o for o in rows if o["local_date"] == "2026-11-08")
        self.assertEqual(tomorrow["snapshot"]["assignees"], ["rrita"])
        self.assertEqual(tomorrow["snapshot"]["due_time"], "18:30:00")
        closed = await self.client.post(f'/api/ga-personal/occurrences/{tomorrow["id"]}/actions', json={"status": "done", "expected_version": 1, "request_id": str(uuid.uuid4())})
        self.assertEqual(closed.status_code, 200)
        response = await self.client.patch(f'/api/ga-personal/occurrences/{tomorrow["id"]}', json={**body, "expected_version": 2, "request_id": str(uuid.uuid4()), "apply_to_future": False})
        self.assertEqual(response.status_code, 409)
        self.assertEqual((await self.client.patch(path, json={**body, "request_id": str(uuid.uuid4())})).status_code, 409)

    async def test_quick_edit_rejects_duplicate_assignment_inactive_owner_and_invalid_dst_time(self):
        d = definition(); d["assignees"] = ["mrika", "rrita"]
        await self.add_template(d); await self.generate()
        rows = (await self.client.get("/api/ga-personal/occurrences")).json()
        row = next(o for o in rows if o["snapshot"]["assignees"] == ["mrika"])
        body = {"expected_version": 1, "request_id": str(uuid.uuid4()), "local_date": row["local_date"], "due_time": None, "assignees": ["rrita"]}
        path = f'/api/ga-personal/occurrences/{row["id"]}'
        self.assertEqual((await self.client.patch(path, json=body)).status_code, 409)
        async with self.sessions() as db:
            member = (await db.execute(select(Member).where(Member.person_key == "lirza"))).scalar_one()
            member.active = False; await db.commit()
        self.assertEqual((await self.client.patch(path, json={**body, "assignees": ["lirza"]})).status_code, 422)
        self.assertEqual((await self.client.patch(path, json={**body, "local_date": "2026-03-29", "due_time": "02:30", "assignees": ["mrika"]})).status_code, 422)

    async def test_access_token_refresh_keeps_module_access(self):
        before = (await self.client.get("/api/ga-personal/access")).json()
        token, _ = create_refresh_token(user_id=self.ids["gane"], jti=self.sids["gane"])
        self.client.cookies.set(auth.REFRESH_COOKIE_NAME, token)
        response = await self.client.post("/api/auth/refresh")
        self.assertEqual(response.status_code, 200, response.text)
        access_token = response.json()["access_token"]
        self.assertEqual(decode_token(access_token)["sid"], self.sids["gane"])
        self.client.headers["Authorization"] = "Bearer " + access_token
        after = (await self.client.get("/api/ga-personal/access")).json()
        self.assertTrue(after["unlocked"])
        self.assertEqual(before, after)
        self.assertEqual((await self.client.get("/api/ga-personal/workspace")).status_code, 200)

    async def test_future_assignment_after_instance_override_replaces_original_slot(self):
        await self.add_template(); await self.generate()
        row = (await self.client.get("/api/ga-personal/occurrences")).json()[0]
        path = f'/api/ga-personal/occurrences/{row["id"]}'
        body = {"expected_version": 1, "request_id": str(uuid.uuid4()), "local_date": row["local_date"],
                "due_time": "18:00", "assignees": ["rrita"]}
        self.assertEqual((await self.client.patch(path, json=body)).status_code, 200)
        response = await self.client.patch(path, json={**body, "expected_version": 2,
            "request_id": str(uuid.uuid4()), "assignees": ["lirza"], "apply_to_future": True,
            "expected_template_version": 1})
        self.assertEqual(response.status_code, 200, response.text)
        models = (await self.client.get("/api/ga-personal/templates")).json()
        self.assertEqual(models[0]["definition"]["assignees"], ["lirza"])
        self.assertEqual((await self.generate())["created"], 0)
        self.assertEqual((await self.generate("2026-11-08"))["created"], 1)

    async def test_rotation_instance_reassignment_leaves_future_rotation_intact(self):
        d = definition(); d.update(assignment="rotation", assignees=[], rotation_id="nala")
        await self.add_template(d); await self.generate()
        row = (await self.client.get("/api/ga-personal/occurrences")).json()[0]
        path = f'/api/ga-personal/occurrences/{row["id"]}'
        body = {"expected_version": 1, "request_id": str(uuid.uuid4()), "local_date": row["local_date"],
                "due_time": "18:00", "assignees": ["mrika"]}
        response = await self.client.patch(path, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((await self.generate())["created"], 0)
        self.assertEqual((await self.generate("2026-11-08"))["created"], 1)
        rows = (await self.client.get("/api/ga-personal/occurrences")).json()
        self.assertEqual(next(o for o in rows if o["local_date"] == "2026-11-08")["snapshot"]["assignees"], ["rrita"])
        response = await self.client.patch(path, json={**body, "expected_version": 2,
            "request_id": str(uuid.uuid4()), "apply_to_future": True, "expected_template_version": 1})
        self.assertEqual(response.status_code, 422)

    async def test_one_off_date_change_does_not_regenerate_a_second_occurrence(self):
        d = definition(); d.update(frequency="once", on_date="2026-11-07")
        t = await self.add_template(d)
        row = (await self.client.get("/api/ga-personal/occurrences")).json()[0]
        result = await self.client.patch(f'/api/ga-personal/occurrences/{row["id"]}', json={"expected_version": 1,
            "request_id": str(uuid.uuid4()), "local_date": "2026-11-08", "due_time": "18:00", "assignees": ["rrita"],
            "apply_to_future": True, "expected_template_version": t["version"]})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual((await self.generate("2026-11-08"))["created"], 0)
        self.assertEqual(len((await self.client.get("/api/ga-personal/occurrences")).json()), 1)

    async def test_untimed_daily_tasks_generate_without_invented_deadline(self):
        d = definition(); d["due_time"] = None
        await self.add_template(d)
        self.assertEqual((await self.generate())["created"], 1)
        rows = (await self.client.get("/api/ga-personal/occurrences")).json()
        self.assertIsNone(rows[0]["due_at"])
        self.assertEqual((await self.generate())["created"], 0)
        async with self.sessions() as db:
            self.assertEqual((await db.execute(select(func.count(Delivery.id)))).scalar_one(), 0)

    async def bridge_setup(self, *, destination="dm", owner="rrita"):
        secret_patch = patch.dict(settings.__dict__, {"GA_PERSONAL_DISCORD_BRIDGE_SECRET": "test-only-bridge-secret-which-is-long-enough"})
        secret_patch.start(); self.patchers.append(secret_patch)
        config = {"enabled": True, "guild_id": "111111111111111111", "channel_id": "222222222222222222",
                  "user_ids": {"rrita": "333333333333333333", "gane": "444444444444444444"}, "expected_version": 0}
        response = await self.client.put("/api/ga-personal/discord/settings", json=config)
        self.assertEqual(response.status_code, 200, response.text)
        d = definition(); d.update(assignees=[owner], due_time="17:00", discord_destination=destination)
        await self.add_template(d); await self.generate()
        return (await self.client.get("/api/ga-personal/occurrences")).json()[0]

    async def bridge_poll(self, at):
        with patch("app.services.ga_personal_discord.utcnow", return_value=datetime.fromisoformat(at)):
            return await self.client.post("/api/ga-personal/bridge/poll", headers={"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"})

    async def test_bridge_requires_its_own_secret_and_explicit_admin_grant(self):
        response = await self.client.post("/api/ga-personal/bridge/poll")
        self.assertEqual(response.status_code, 401)
        row = await self.bridge_setup()
        self.assertTrue(row)
        self.as_person("outsider")
        response = await self.client.put("/api/ga-personal/discord/settings", json={"enabled": False, "expected_version": 1})
        self.assertEqual(response.status_code, 403)
        self.as_person("mrika")
        self.assertEqual((await self.client.get("/api/ga-personal/discord/settings")).status_code, 403)
        self.assertEqual((await self.client.post("/api/ga-personal/bridge/poll", headers={"X-GA-Bridge-Key": "wrong"})).status_code, 401)

    async def test_bridge_three_phases_are_not_duplicated_by_poll_or_acknowledgement(self):
        await self.bridge_setup()
        first = await self.bridge_poll("2026-11-07T15:55:00+00:00")
        self.assertEqual(first.status_code, 200, first.text)
        delivery = first.json()["deliveries"][0]
        self.assertEqual(delivery["phase"], "before")
        self.assertEqual(delivery["target"], {"kind": "dm", "user_id": "333333333333333333"})
        headers = {"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"}
        root = f'/api/ga-personal/bridge/deliveries/{delivery["id"]}'
        report = {"lease": delivery["lease"], "outcome": "sent", "channel_id": "555555555555555555", "message_id": "666666666666666666"}
        self.assertEqual((await self.client.post(root+"/result", headers=headers, json=report)).status_code, 200)
        action = {"actor_id": "333333333333333333", "guild_id": None, "channel_id": report["channel_id"],
                  "message_id": report["message_id"], "interaction_id": "777777777777777777", "action": "acknowledged"}
        self.assertEqual((await self.client.post(root+"/action", headers=headers, json=action)).status_code, 200)
        self.assertEqual((await self.bridge_poll("2026-11-07T15:55:10+00:00")).json()["deliveries"], [])
        self.assertEqual((await self.bridge_poll("2026-11-07T16:00:00+00:00")).json()["deliveries"][0]["phase"], "due")
        self.assertEqual((await self.bridge_poll("2026-11-07T16:05:00+00:00")).json()["deliveries"][0]["phase"], "after")
        self.assertEqual((await self.bridge_poll("2026-11-07T16:10:00+00:00")).json()["deliveries"], [])

    async def test_bridge_missing_id_does_not_block_other_people_or_leak_to_channel(self):
        await self.bridge_setup(owner="mrika")
        d = definition(); d.update(assignees=["rrita"], due_time="17:00")
        await self.add_template(d); await self.generate()
        result = (await self.bridge_poll("2026-11-07T15:55:00+00:00")).json()
        self.assertEqual(len(result["deliveries"]), 1)
        self.assertEqual(result["deliveries"][0]["assignees"], ["rrita"])
        self.assertIn("mrika", result["missing_people"])

    async def test_bridge_reassignment_invalidates_claim_and_never_uses_old_schedule(self):
        row = await self.bridge_setup()
        delivery = (await self.bridge_poll("2026-11-07T15:55:00+00:00")).json()["deliveries"][0]
        response = await self.client.patch(f'/api/ga-personal/occurrences/{row["id"]}', json={"expected_version": 1,
            "request_id": str(uuid.uuid4()), "local_date": row["local_date"], "due_time": "18:30", "assignees": ["gane"]})
        self.assertEqual(response.status_code, 200, response.text)
        response = await self.client.post(f'/api/ga-personal/bridge/deliveries/{delivery["id"]}/prepare',
            headers={"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"}, json={"lease": delivery["lease"]})
        self.assertEqual(response.status_code, 409)
        fresh = (await self.bridge_poll("2026-11-07T17:25:00+00:00")).json()["deliveries"]
        self.assertEqual(len(fresh), 1)
        self.assertEqual(fresh[0]["target"]["user_id"], "444444444444444444")

    async def test_bridge_completion_checks_exact_message_actor_and_is_idempotent(self):
        row = await self.bridge_setup()
        headers = {"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"}
        delivery = (await self.bridge_poll("2026-11-07T15:55:00+00:00")).json()["deliveries"][0]
        root = f'/api/ga-personal/bridge/deliveries/{delivery["id"]}'
        report = {"lease": delivery["lease"], "outcome": "sent", "channel_id": "555555555555555555", "message_id": "666666666666666666"}
        self.assertEqual((await self.client.post(root+"/result", headers=headers, json=report)).status_code, 200)
        self.assertEqual((await self.client.post(root+"/result", headers=headers, json=report)).status_code, 200)
        action = {"actor_id": "333333333333333333", "guild_id": None, "channel_id": report["channel_id"],
                  "message_id": report["message_id"], "interaction_id": "777777777777777777", "action": "done"}
        self.assertEqual((await self.client.post(root+"/action", headers=headers, json={**action, "actor_id": "444444444444444444"})).status_code, 403)
        self.assertEqual((await self.client.post(root+"/action", headers=headers, json={**action, "message_id": "888888888888888888"})).status_code, 403)
        response = await self.client.post(root+"/action", headers=headers, json=action)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "done")
        self.assertEqual((await self.client.post(root+"/action", headers=headers, json=action)).status_code, 200)
        self.assertEqual((await self.bridge_poll("2026-11-07T16:05:00+00:00")).json()["deliveries"], [])
        async with self.sessions() as db:
            self.assertEqual((await db.get(Occurrence, uuid.UUID(row["id"]))).status, "done")
            count = (await db.execute(select(func.count(Event.id)).where(Event.request_id == "discord:777777777777777777"))).scalar_one()
            self.assertEqual(count, 1)

    async def test_bridge_untimed_and_finished_tasks_never_notify_and_lirza_uses_adult_contact(self):
        row = await self.bridge_setup(owner="lirza")
        first = (await self.bridge_poll("2026-11-07T15:55:00+00:00")).json()["deliveries"][0]
        self.assertEqual(first["target"]["user_id"], "444444444444444444")
        self.assertEqual(first["assignees"], ["lirza"])
        response = await self.client.patch(f'/api/ga-personal/occurrences/{row["id"]}', json={"expected_version": 1,
            "request_id": str(uuid.uuid4()), "local_date": row["local_date"], "due_time": None, "assignees": ["lirza"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual((await self.bridge_poll("2026-11-07T16:00:00+00:00")).json()["deliveries"], [])

    async def test_bridge_snooze_retry_is_idempotent_and_does_not_repeat_old_phase(self):
        await self.bridge_setup()
        headers = {"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"}
        delivery = (await self.bridge_poll("2026-11-07T15:55:00+00:00")).json()["deliveries"][0]
        root = f'/api/ga-personal/bridge/deliveries/{delivery["id"]}'
        report = {"lease": delivery["lease"], "outcome": "sent", "channel_id": "555555555555555555", "message_id": "666666666666666666"}
        await self.client.post(root+"/result", headers=headers, json=report)
        action = {"actor_id": "333333333333333333", "guild_id": None, "channel_id": report["channel_id"],
                  "message_id": report["message_id"], "interaction_id": "777777777777777777", "action": "later15"}
        response = await self.client.post(root+"/action", headers=headers, json=action)
        self.assertEqual(response.status_code, 200, response.text)
        retry = await self.client.post(root+"/action", headers=headers, json=action)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(response.json()["card"]["due_at"], retry.json()["card"]["due_at"])
        finish = await self.client.post(root+"/action", headers=headers, json={**action,
            "interaction_id": "888888888888888888", "action": "done"})
        self.assertEqual(finish.status_code, 200, finish.text)

    async def test_bridge_returning_to_an_old_schedule_does_not_revive_old_cards(self):
        row = await self.bridge_setup()
        headers = {"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"}
        delivery = (await self.bridge_poll("2026-11-07T15:55:00+00:00")).json()["deliveries"][0]
        root = f'/api/ga-personal/bridge/deliveries/{delivery["id"]}'
        report = {"lease": delivery["lease"], "outcome": "sent", "channel_id": "555555555555555555", "message_id": "666666666666666666"}
        await self.client.post(root+"/result", headers=headers, json=report)
        endpoint = f'/api/ga-personal/occurrences/{row["id"]}'
        for version, time in ((1, "18:00"), (2, "17:00")):
            response = await self.client.patch(endpoint, json={"expected_version": version, "request_id": str(uuid.uuid4()),
                "local_date": row["local_date"], "due_time": time, "assignees": ["rrita"]})
            self.assertEqual(response.status_code, 200, response.text)
        action = {"actor_id": "333333333333333333", "guild_id": None, "channel_id": report["channel_id"],
                  "message_id": report["message_id"], "interaction_id": "777777777777777777", "action": "done"}
        self.assertEqual((await self.client.post(root+"/action", headers=headers, json=action)).status_code, 409)
        replacement = (await self.bridge_poll("2026-11-07T15:55:10+00:00")).json()["deliveries"]
        self.assertEqual(len(replacement), 1)
        self.assertNotEqual(replacement[0]["id"], delivery["id"])

    async def test_bridge_acknowledged_card_updates_include_old_history_and_stop_after_sync(self):
        row = await self.bridge_setup()
        headers = {"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"}
        delivery = (await self.bridge_poll("2026-11-07T15:55:00+00:00")).json()["deliveries"][0]
        root = f'/api/ga-personal/bridge/deliveries/{delivery["id"]}'
        report = {"lease": delivery["lease"], "outcome": "sent", "channel_id": "555555555555555555", "message_id": "666666666666666666"}
        await self.client.post(root+"/result", headers=headers, json=report)
        from app.models.ga_personal import GaPersonalDiscordDelivery
        async with self.sessions() as db:
            for i in range(201):
                db.add(GaPersonalDiscordDelivery(occurrence_id=uuid.UUID(row["id"]), schedule_key="x"+str(i), phase="before",
                    recipient="channel", scheduled_at=datetime.fromisoformat("2026-11-07T16:00:00+00:00"), status="sent",
                    channel_id="555555555555555555", message_id=str(700000000000000000+i),
                    details={"target": {"kind": "dm", "user_id": "333333333333333333"}, "guild_id": "111111111111111111"}))
            await db.commit()
        updates = (await self.bridge_poll("2026-11-07T15:55:10+00:00")).json()["updates"]
        target = next((u for u in updates if u["id"] == delivery["id"]), None)
        self.assertIsNotNone(target)
        sync = {"channel_id": report["channel_id"], "message_id": report["message_id"], "sync_key": target["sync_key"]}
        self.assertEqual((await self.client.post(root+"/sync", headers=headers, json=sync)).status_code, 200)
        updates = (await self.bridge_poll("2026-11-07T15:55:20+00:00")).json()["updates"]
        self.assertNotIn(delivery["id"], [u["id"] for u in updates])

    async def test_bridge_health_and_disabled_delivery_never_claim_and_revoked_grant_stops(self):
        await self.bridge_setup()
        headers = {"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"}
        moment = datetime.fromisoformat("2026-11-07T15:55:00+00:00")
        with patch("app.services.ga_personal_discord.utcnow", return_value=moment):
            for payload in ({"health_only": True}, {"delivery_enabled": False}):
                response = await self.client.post("/api/ga-personal/bridge/poll", headers=headers, json=payload)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["deliveries"], [])
        self.assertEqual(len((await self.bridge_poll(moment.isoformat())).json()["deliveries"]), 1)
        async with self.sessions() as db:
            space = await db.get(Space, self.space_id)
            space.password_version += 1
            await db.commit()
        self.assertFalse((await self.bridge_poll("2026-11-07T16:00:00+00:00")).json()["enabled"])

    async def test_bridge_inaccessible_message_backoff_does_not_starve_later_updates(self):
        row = await self.bridge_setup()
        headers = {"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"}
        original = (await self.bridge_poll("2026-11-07T15:55:00+00:00")).json()["deliveries"][0]
        root = f'/api/ga-personal/bridge/deliveries/{original["id"]}'
        await self.client.post(root+"/result", headers=headers, json={"lease": original["lease"], "outcome": "sent",
            "channel_id": "555555555555555555", "message_id": "666666666666666666"})
        from app.models.ga_personal import GaPersonalDiscordDelivery
        async with self.sessions() as db:
            older = GaPersonalDiscordDelivery(occurrence_id=uuid.UUID(row["id"]), schedule_key="old", phase="before",
                recipient="channel", scheduled_at=datetime.fromisoformat("2026-11-07T15:54:00+00:00"), status="sent",
                channel_id="555555555555555555", message_id="777777777777777777",
                details={"target": {"kind": "dm", "user_id": "333333333333333333"}, "guild_id": "111111111111111111"})
            db.add(older); await db.commit(); older_id = str(older.id)
        with patch("app.services.ga_personal_discord.UPDATE_BATCH_LIMIT", 1, create=True):
            first = (await self.bridge_poll("2026-11-07T15:55:10+00:00")).json()["updates"]
            target = next(u for u in first if u["id"] == older_id)
            with patch("app.services.ga_personal_discord.utcnow", return_value=datetime.fromisoformat("2026-11-07T15:55:10+00:00")):
                response = await self.client.post(f'/api/ga-personal/bridge/deliveries/{older_id}/sync', headers=headers, json={
                    "channel_id": target["channel_id"], "message_id": target["message_id"], "sync_key": target["sync_key"], "error": "permissions"})
                self.assertEqual(response.status_code, 200, response.text)
            second = (await self.bridge_poll("2026-11-07T15:55:20+00:00")).json()["updates"]
            self.assertEqual(second[0]["id"], original["id"])
            retry = (await self.bridge_poll("2026-11-07T16:01:00+00:00")).json()["updates"]
            self.assertEqual(retry[0]["id"], older_id)

    async def test_bridge_expired_claim_is_visible_and_never_replayed(self):
        await self.bridge_setup()
        first = (await self.bridge_poll("2026-11-07T15:55:00+00:00")).json()["deliveries"][0]
        second = (await self.bridge_poll("2026-11-07T15:57:00+00:00")).json()["deliveries"]
        self.assertEqual(second, [])
        from app.models.ga_personal import GaPersonalDiscordDelivery
        async with self.sessions() as db:
            self.assertEqual((await db.get(GaPersonalDiscordDelivery, uuid.UUID(first["id"]))).status, "uncertain")

    async def test_bridge_channel_action_requires_configured_guild_and_channel(self):
        await self.bridge_setup(destination="channel")
        headers = {"X-GA-Bridge-Key": "test-only-bridge-secret-which-is-long-enough"}
        delivery = (await self.bridge_poll("2026-11-07T15:55:00+00:00")).json()["deliveries"][0]
        root = f'/api/ga-personal/bridge/deliveries/{delivery["id"]}'
        report = {"lease": delivery["lease"], "outcome": "sent", "channel_id": "222222222222222222", "message_id": "666666666666666666"}
        self.assertEqual((await self.client.post(root+"/result", headers=headers, json={**report, "channel_id": "555555555555555555"})).status_code, 403)
        self.assertEqual((await self.client.post(root+"/result", headers=headers, json=report)).status_code, 200)
        action = {"actor_id": "333333333333333333", "guild_id": "999999999999999999", "channel_id": report["channel_id"],
                  "message_id": report["message_id"], "interaction_id": "777777777777777777", "action": "done"}
        self.assertEqual((await self.client.post(root+"/action", headers=headers, json=action)).status_code, 403)
        self.assertEqual((await self.client.post(root+"/action", headers=headers, json={**action, "guild_id": "111111111111111111"})).status_code, 200)

    async def test_automatic_tick_creates_each_local_day_once_and_stops_when_disabled(self):
        from app.services.ga_personal_scheduler import generation_tick
        await self.add_template()
        async with self.sessions() as db:
            self.assertEqual(await generation_tick(db, day=date(2026, 11, 7)), 0)
            space = await db.get(Space, self.space_id)
            space.config = {**space.config, "automatic_generation": {"enabled": True, "starts_on": "2026-11-07"}}
            await db.commit()
            self.assertEqual(await generation_tick(db, day=date(2026, 11, 6)), 0)
            self.assertEqual(await generation_tick(db, day=date(2026, 11, 7)), 1)
            self.assertEqual(await generation_tick(db, day=date(2026, 11, 7)), 0)
            self.assertEqual(await generation_tick(db, day=date(2026, 11, 8)), 1)
            self.assertEqual((await db.execute(select(func.count(Event.id)).where(Event.kind == "auto_generated"))).scalar_one(), 2)
            response = await self.client.put("/api/ga-personal/automation", json={"enabled": False})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(await generation_tick(db, day=date(2026, 11, 9)), 0)

    async def test_seed_command_preserves_password_history_and_local_edits_on_repeat(self):
        from scripts.seed_ga_personal import seed, USERNAMES
        data = dataset()
        async with self.sessions() as db:
            for person in service.PEOPLE:
                (await db.get(User, self.ids[person])).username = USERNAMES[person]
            for member in (await db.execute(select(Member).where(Member.person_key != "gane"))).scalars():
                await db.delete(member)
            await db.commit()
            before_password = (await db.get(Space, self.space_id)).password_hash
            mapping = {p: self.ids[p] for p in service.PEOPLE}
            preview = await seed(db, data, mapping, admin_person="gane", day=date(2026, 11, 7))
            self.assertEqual(preview["templates"], 1)
            self.assertEqual(len(preview["memberships_to_add"]), 3)
            self.assertEqual((await db.execute(select(func.count(Template.id)))).scalar_one(), 0)
            result = await seed(db, data, mapping, admin_person="gane", apply=True, day=date(2026, 11, 7))
            self.assertEqual(result["created_occurrences"], 1)
            self.assertEqual(result["daily_models_active"], 1)
            self.assertEqual((await db.execute(select(func.count(Member.id)))).scalar_one(), 4)
            administrator = (await db.execute(select(Member).where(Member.person_key == "gane"))).scalar_one()
            reimport_preview = await service.import_dataset(db, administrator, data)
            self.assertEqual(reimport_preview["conflicts"], [])
            self.assertEqual(reimport_preview["unchanged"], ["sample"])
            row = (await db.execute(select(Template))).scalar_one()
            row.definition = {**row.definition, "title": "Ndryshim manual që ruhet"}
            row.import_hash = None
            await db.commit()
            result = await seed(db, data, mapping, admin_person="gane", apply=True, day=date(2026, 11, 7))
            self.assertEqual(result["created_occurrences"], 0)
            self.assertEqual(result["preserved_local_edits"], ["sample"])
            self.assertEqual((await db.execute(select(func.count(Template.id)))).scalar_one(), 1)
            self.assertEqual((await db.execute(select(func.count(Occurrence.id)))).scalar_one(), 1)
            self.assertEqual((await db.get(Space, self.space_id)).password_hash, before_password)
            self.assertEqual((await db.execute(select(Occurrence))).scalar_one().snapshot["title"], "Model prove")

    async def test_explicit_module_admin_assignment_preserves_staff_role_and_other_members(self):
        from scripts.set_ga_personal_admin import assign_admin
        async with self.sessions() as db:
            target = await db.get(User, self.ids["rrita"])
            target.username = "rrita.canolli"
            await db.flush()
            for _ in range(2):
                result = await assign_admin(db, "rrita", target.id)
                self.assertTrue(result["module_admin"])
                self.assertEqual(result["primeflow_role"], "STAFF")
            await db.commit()
        async with self.sessions() as db:
            target = await db.get(User, self.ids["rrita"])
            self.assertEqual(target.role, UserRole.STAFF)
            members = {m.person_key: m for m in (await db.execute(select(Member))).scalars()}
            self.assertEqual(len(members), 4)
            self.assertTrue(members["rrita"].is_admin)
            self.assertFalse(members["mrika"].is_admin)
            self.assertFalse(members["lirza"].is_admin)
