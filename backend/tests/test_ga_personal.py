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
    SCHEMA, GaPersonalSpace as Space, GaPersonalMember as Member, GaPersonalUnlock as Unlock,
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

    async def unlock(self):
        r = await self.client.post("/api/ga-personal/unlock", json={"password": self.password})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("HttpOnly", r.headers["set-cookie"])
        self.assertIn("Secure", r.headers["set-cookie"])
        self.assertEqual(r.headers["cache-control"], "private, no-store")

    async def add_template(self, d=None):
        r = await self.client.post("/api/ga-personal/templates", json={"definition": d or definition()})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def generate(self, day="2026-11-07"):
        r = await self.client.post("/api/ga-personal/generate", json={"day": day})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def test_nonmember_including_work_admin_cannot_read_or_unlock(self):
        self.as_person("outsider")
        self.assertEqual((await self.client.get("/api/ga-personal/access")).json(), {"available": False, "unlocked": False})
        for path in ["workspace", "templates", "occurrences", "history"]:
            self.assertEqual((await self.client.get("/api/ga-personal/"+path)).status_code, 403)
        self.assertEqual((await self.client.post("/api/ga-personal/unlock", json={"password": self.password})).status_code, 403)

    async def test_lock_expiry_logout_and_session_binding(self):
        self.assertEqual((await self.client.get("/api/ga-personal/templates")).status_code, 423)
        await self.unlock()
        self.assertEqual((await self.client.get("/api/ga-personal/workspace")).status_code, 200)
        self.as_person("mrika")
        self.assertEqual((await self.client.get("/api/ga-personal/templates")).status_code, 423)
        self.as_person("gane")
        async with self.sessions() as db:
            row = (await db.execute(select(Unlock))).scalar_one()
            row.expires_at = service.utcnow()-timedelta(seconds=1); await db.commit()
        self.assertEqual((await self.client.get("/api/ga-personal/templates")).status_code, 423)
        await self.unlock()
        from app.auth.security import create_refresh_token
        token, _ = create_refresh_token(user_id=self.ids["gane"], jti=self.sids["gane"])
        self.client.cookies.set(auth.REFRESH_COOKIE_NAME, token, domain="test.local", path="/api/auth")
        self.assertEqual((await self.client.post("/api/auth/logout")).status_code, 200)
        self.assertEqual((await self.client.get("/api/ga-personal/templates")).status_code, 409)
        self.assertEqual((await self.client.post("/api/ga-personal/unlock", json={"password": self.password})).status_code, 409)

    async def test_password_attempts_persist_and_wrong_password_is_not_echoed(self):
        for _ in range(5):
            r = await self.client.post("/api/ga-personal/unlock", json={"password": "wrong-secret"})
            self.assertEqual(r.status_code, 403)
            self.assertNotIn("wrong-secret", r.text)
        self.assertEqual((await self.client.post("/api/ga-personal/unlock", json={"password": self.password})).status_code, 429)

    async def test_first_password_setup_requires_module_admin_and_cannot_overwrite(self):
        async with self.sessions() as db:
            space = await db.get(Space, self.space_id)
            space.password_hash = None
            member = (await db.execute(select(Member).where(Member.user_id == self.ids["rrita"])) ).scalar_one()
            member.is_admin = True
            await db.commit()
        self.as_person("outsider")
        body = {"password": "first-test-password-only"}
        self.assertEqual((await self.client.post("/api/ga-personal/password/setup", json=body)).status_code, 403)
        self.as_person("mrika")
        self.assertFalse((await self.client.get("/api/ga-personal/access")).json()["setup_allowed"])
        self.assertEqual((await self.client.post("/api/ga-personal/password/setup", json=body)).status_code, 403)
        self.as_person("rrita")
        self.assertTrue((await self.client.get("/api/ga-personal/access")).json()["setup_allowed"])
        self.assertEqual((await self.client.get("/api/ga-personal/workspace")).status_code, 423)
        response = await self.client.post("/api/ga-personal/password/setup", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(body["password"], response.text)
        self.assertEqual((await self.client.post("/api/ga-personal/password/setup", json={"password": "must-not-overwrite-this"})).status_code, 409)
        self.password = body["password"]
        await self.unlock()
        self.assertEqual((await self.client.get("/api/ga-personal/workspace")).status_code, 200)

    async def test_password_setup_requires_current_login_and_uses_serialized_first_write(self):
        async with self.sessions() as db:
            space = await db.get(Space, self.space_id)
            space.password_hash = None
            await db.commit()
        old = self.client.headers["Authorization"]
        self.client.headers["Authorization"] = "Bearer " + create_access_token(user_id=self.ids["gane"], role="STAFF", department_id=None)
        access = (await self.client.get("/api/ga-personal/access")).json()
        self.assertTrue(access["requires_login"])
        self.assertFalse(access["setup_allowed"])
        body = {"password": "first-test-password-only"}
        self.assertEqual((await self.client.post("/api/ga-personal/password/setup", json=body)).status_code, 409)
        self.client.headers["Authorization"] = old
        results = await asyncio.gather(*[self.client.post("/api/ga-personal/password/setup", json=body) for _ in range(2)])
        self.assertEqual(sorted(r.status_code for r in results), [200, 409])

    async def test_validation_never_echoes_passwords_and_errors_are_not_cached(self):
        secret = "malformed-private-value"
        r = await self.client.post("/api/ga-personal/unlock", json={"password": {"value": secret}})
        self.assertEqual(r.status_code, 422)
        self.assertNotIn(secret, r.text)
        self.assertEqual(r.headers["cache-control"], "private, no-store")
        await self.unlock()
        invalid = dataset(); invalid["rotations"] = [None]
        r = await self.client.post("/api/ga-personal/import/preview", json={"dataset": invalid})
        self.assertEqual(r.status_code, 422)

    async def test_individual_multi_assignment_completion_and_reminder_cancellation(self):
        await self.unlock()
        d = definition(); d["assignees"] = ["mrika", "rrita"]
        await self.add_template(d)
        self.assertEqual((await self.generate())["created"], 2)
        self.assertEqual((await self.generate())["created"], 0)
        rows = (await self.client.get("/api/ga-personal/occurrences")).json()
        target = next(o for o in rows if o["snapshot"]["assignees"] == ["mrika"])
        async with self.sessions() as db:
            db.add(Delivery(occurrence_id=uuid.UUID(target["id"]), scheduled_at=service.utcnow()))
            await db.commit()
        self.as_person("mrika"); await self.unlock()
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
        await self.unlock()
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
        await self.unlock()
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
        self.as_person("mrika"); await self.unlock()
        t = await self.add_template()
        d = definition(); d["assignees"] = ["rrita"]
        self.assertEqual((await self.client.post("/api/ga-personal/templates", json={"definition": d})).status_code, 403)
        self.assertEqual((await self.client.get("/api/ga-personal/templates")).status_code, 200)

    async def test_concurrent_generation_and_stale_actions_are_serialized(self):
        await self.unlock(); await self.add_template()
        results = await asyncio.gather(*[self.client.post("/api/ga-personal/generate", json={"day": "2026-11-07"}) for _ in range(2)])
        self.assertEqual(sorted(r.json()["created"] for r in results), [0, 1])
        row = (await self.client.get("/api/ga-personal/occurrences")).json()[0]
        path = f'/api/ga-personal/occurrences/{row["id"]}/actions'
        results = await asyncio.gather(*[self.client.post(path, json={"status": "done", "expected_version": 1, "request_id": str(uuid.uuid4())}) for _ in range(2)])
        self.assertEqual(sorted(r.status_code for r in results), [200, 409])

    async def test_password_change_and_membership_revocation_relock(self):
        await self.unlock()
        r = await self.client.put("/api/ga-personal/password", json={"password": "another-test-password"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((await self.client.get("/api/ga-personal/templates")).status_code, 423)
        self.password = "another-test-password"; await self.unlock()
        async with self.sessions() as db:
            member = (await db.execute(select(Member).where(Member.user_id == self.ids["gane"]))).scalar_one()
            member.active = False; await db.commit()
        self.assertEqual((await self.client.get("/api/ga-personal/templates")).status_code, 403)

    async def test_one_off_creates_individual_occurrences_without_admin_generation(self):
        self.as_person("mrika"); await self.unlock()
        d = definition(); d.update(frequency="once", on_date="2026-11-07")
        await self.add_template(d)
        rows = (await self.client.get("/api/ga-personal/occurrences")).json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["snapshot"]["assignees"], ["mrika"])

    async def test_weekday_api_excludes_weekend_duties(self):
        await self.unlock()
        d = definition(); d.update(frequency="weekly", weekdays=[5, 6])
        await self.add_template(d); await self.generate()
        self.assertEqual((await self.client.get("/api/ga-personal/occurrences?day=2026-11-06")).json(), [])
        self.assertEqual(len((await self.client.get("/api/ga-personal/occurrences?day=2026-11-08")).json()), 1)

    async def test_quick_edit_changes_only_instance_and_retains_authorization_and_history(self):
        await self.unlock(); template = await self.add_template(); await self.generate()
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
        self.as_person("mrika"); await self.unlock()
        self.assertEqual((await self.client.patch(path, json={**body, "expected_version": 2, "request_id": str(uuid.uuid4())})).status_code, 403)

    async def test_quick_edit_future_updates_template_without_duplicate_or_resolved_history_edits(self):
        await self.unlock(); template = await self.add_template(); await self.generate()
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
        await self.unlock()
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

    async def test_access_token_refresh_keeps_module_unlock_and_expiry(self):
        await self.unlock()
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
        self.assertEqual(before["expires_at"], after["expires_at"])
        self.assertEqual((await self.client.get("/api/ga-personal/workspace")).status_code, 200)

    async def test_future_assignment_after_instance_override_replaces_original_slot(self):
        await self.unlock(); await self.add_template(); await self.generate()
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
        await self.unlock()
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
        await self.unlock()
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
        await self.unlock()
        d = definition(); d["due_time"] = None
        await self.add_template(d)
        self.assertEqual((await self.generate())["created"], 1)
        rows = (await self.client.get("/api/ga-personal/occurrences")).json()
        self.assertIsNone(rows[0]["due_at"])
        self.assertEqual((await self.generate())["created"], 0)
        async with self.sessions() as db:
            self.assertEqual((await db.execute(select(func.count(Delivery.id)))).scalar_one(), 0)

    async def test_automatic_tick_creates_each_local_day_once_and_stops_when_disabled(self):
        from app.services.ga_personal_scheduler import generation_tick
        await self.unlock()
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
