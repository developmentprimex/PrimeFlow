"""Exercise private family host authorization and SQL with disposable in-memory data."""
import json
import os
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/primeflow_test")
os.environ.setdefault("JWT_SECRET", "kujtesa-host-test-secret")

import httpx
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.api.routers import ga_personal_discord as api
from app.config import settings
from app.db import Base, get_db
from app.models.department import Department
from app.models.enums import UserRole
from app.models.user import User
from app.models.ga_personal import GaPersonalSpace as Space, GaPersonalMember as Member
from app.models.ga_personal import GaPersonalTemplate as Template, GaPersonalOccurrence as Occurrence
from app.services import ga_personal as tasks

IDS = {"gane": "100000000000000001", "rrita": "100000000000000002", "mrika": "100000000000000003"}
GUILD, CHANNEL = "100000000000000011", "100000000000000012"
NOW = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)


class KujtesaHostApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = sa.create_engine("sqlite://")
        self.connection = self.engine.connect()
        self.connection.execute(sa.text("ATTACH DATABASE ':memory:' AS ga_personal"))
        Base.metadata.create_all(self.connection, tables=[Department.__table__, User.__table__, Space.__table__,
            Member.__table__, Template.__table__, Occurrence.__table__])
        self.session = Session(self.connection, expire_on_commit=False)
        self.users = {}
        for person in IDS:
            user = User(id=uuid.uuid4(), email=person + "@test.invalid", full_name=person.title(),
                        password_hash="fixture", role=UserRole.STAFF, is_active=True)
            self.session.add(user)
            self.users[person] = user
        self.space = Space(id=uuid.uuid4(), key="ga_personal", password_hash="fixture", password_version=1,
            config={"discord": {"enabled": True, "guild_id": GUILD, "channel_id": CHANNEL, "user_ids": IDS,
                "version": 3, "password_version": 1, "authorized_by": str(self.users["gane"].id)}})
        self.session.add(self.space)
        self.session.flush()
        self.members = {}
        for person in IDS:
            member = Member(space_id=self.space.id, user_id=self.users[person].id, person_key=person,
                            active=True, is_admin=person == "gane")
            self.session.add(member)
            self.members[person] = member
        self.add_task("Rregullo tavolinen", ["rrita"])
        self.add_task("Lexo librin", ["mrika"], status="done")
        self.add_task("Dje", ["rrita"], day="2026-11-02")
        self.add_task("Arkivuar", ["rrita"], archived=True)
        self.add_task("Anuluar", ["rrita"], status="cancelled")
        other = Space(id=uuid.uuid4(), key="other", password_hash="fixture", password_version=1, config={})
        self.session.add(other)
        self.add_task("OTHER SPACE SECRET", ["rrita"], space_id=other.id)
        self.session.commit()

        async def execute(statement):
            return self.session.execute(statement)

        async def db():
            yield SimpleNamespace(execute=execute)

        self.app = FastAPI()
        self.app.include_router(api.router, prefix="/api/ga-personal")
        self.app.dependency_overrides[get_db] = db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test",
            headers={"X-GA-Bridge-Key": "b" * 40})
        self.config = patch.dict(settings.__dict__, {"GA_PERSONAL_ENABLED": True,
            "GA_PERSONAL_DISCORD_BRIDGE_SECRET": "b" * 40, "KUJTESA_HOST_ENABLED": True,
            "KUJTESA_OPENAI_API_KEY": "family-only-key", "OPENAI_API_KEY": "general-key",
            "MIRA_HOST_OPENAI_API_KEY": "work-host-key", "MIRA_NOTES_OPENAI_API_KEY": "work-notes-key",
            "KUJTESA_HOST_MODEL": "test-realtime", "KUJTESA_HOST_VOICE": "marin"})
        self.config.start()
        self.clock = patch.object(tasks, "utcnow", return_value=NOW)
        self.clock.start()

    def add_task(self, title, people, *, status="pending", day="2026-11-03", archived=False, space_id=None):
        space_id = space_id or self.space.id
        template = Template(id=uuid.uuid4(), space_id=space_id, created_by=self.users["gane"].id,
                            definition={}, archived=archived)
        self.session.add(template)
        self.session.add(Occurrence(space_id=space_id, template_id=template.id, period_key=day,
            assignment_key=title, local_date=day, snapshot={"title": title, "assignees": people}, status=status))

    async def asyncTearDown(self):
        self.clock.stop()
        self.config.stop()
        await self.client.aclose()
        self.session.close()
        self.connection.close()
        self.engine.dispose()

    def payload(self, **changes):
        return {"actor_id": IDS["gane"], "guild_id": GUILD, "channel_id": CHANNEL,
                "present_user_ids": list(IDS.values()), **changes}

    async def post(self, endpoint="context", **changes):
        return await self.client.post("/api/ga-personal/bridge/host/" + endpoint, json=self.payload(**changes))

    async def test_context_contains_only_todays_private_tasks_for_present_family(self):
        response = await self.post()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(set(body["allowed_user_ids"]), set(IDS.values()))
        entries = {person["person"]: person for person in body["participants"]}
        self.assertEqual([t["title"] for t in entries["rrita"]["tasks"]], ["Rregullo tavolinen"])
        self.assertEqual(entries["mrika"]["tasks"][0]["status"], "done")
        for secret in ("OTHER SPACE SECRET", "Dje", "Arkivuar", "Anuluar", "family-only-key", "work-host-key"):
            self.assertNotIn(secret, response.text)
        self.assertNotIn("client_secret", body)
        self.assertFalse(self.session.new or self.session.dirty or self.session.deleted)

    async def test_bad_bridge_non_admin_foreign_guild_unknown_listener_are_denied(self):
        cases = [dict(actor_id=IDS["rrita"]), dict(guild_id="100000000000000099"),
                 dict(present_user_ids=[IDS["gane"], "100000000000000099"]),
                 dict(present_user_ids=[IDS["rrita"]])]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertEqual((await self.post(**changes)).status_code, 403)
        response = await self.client.post("/api/ga-personal/bridge/host/context", json=self.payload(),
                                          headers={"X-GA-Bridge-Key": "wrong"})
        self.assertEqual(response.status_code, 401)

    async def test_removed_admin_password_change_disabled_grant_and_host_switch_revoke_context(self):
        for person, field, value in ((self.members["gane"], "active", False),
                                    (self.users["gane"], "is_active", False),
                                    (self.space, "password_version", 2)):
            old = getattr(person, field)
            setattr(person, field, value)
            self.session.flush()
            self.assertEqual((await self.post()).status_code, 403)
            setattr(person, field, old)
            self.session.flush()
        old = self.space.config
        self.space.config = {"discord": {**old["discord"], "enabled": False}}
        self.session.flush()
        self.assertEqual((await self.post()).status_code, 403)
        self.space.config = old
        self.session.flush()
        with patch.dict(settings.__dict__, KUJTESA_HOST_ENABLED=False):
            self.assertEqual((await self.post()).status_code, 503)

    async def test_absent_family_is_not_in_conversation_and_inactive_member_cannot_listen(self):
        response = await self.post(present_user_ids=[IDS["gane"], IDS["rrita"]])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual({p["person"] for p in response.json()["participants"]}, {"gane", "rrita"})
        self.members["mrika"].active = False
        self.session.flush()
        self.assertEqual((await self.post()).status_code, 403)

    async def test_start_uses_family_key_and_returns_only_ephemeral_secret(self):
        from app.services import kujtesa_host
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"value": "ephemeral-family-secret"})
        real_client = httpx.AsyncClient
        with patch.object(kujtesa_host.httpx, "AsyncClient",
                          lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
            response = await self.post("start")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["client_secret"], "ephemeral-family-secret")
        self.assertEqual(seen[0].headers["authorization"], "Bearer family-only-key")
        body = json.loads(seen[0].content)
        self.assertEqual(body["session"]["model"], "test-realtime")
        self.assertEqual({t["name"] for t in body["session"]["tools"]}, {"wait_for_user", "finish_meeting"})
        self.assertIn("Rregullo tavolinen", body["session"]["instructions"])
        self.assertNotIn("OTHER SPACE SECRET", body["session"]["instructions"])

    async def test_missing_family_key_does_not_fall_back_to_any_work_key(self):
        with patch.dict(settings.__dict__, KUJTESA_OPENAI_API_KEY=None):
            response = await self.post("start")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("general-key", response.text)

    async def test_provider_error_or_missing_ephemeral_value_is_sanitized(self):
        from app.services import kujtesa_host
        real_client = httpx.AsyncClient
        for status, body in ((401, {"error": {"message": "family-only-key"}}), (200, {})):
            with self.subTest(status=status), patch.object(kujtesa_host.httpx, "AsyncClient",
                    lambda **kw: real_client(transport=httpx.MockTransport(lambda req: httpx.Response(status, json=body)), **kw)):
                response = await self.post("start")
                self.assertEqual(response.status_code, 502)
                self.assertNotIn("family-only-key", response.text)

    async def test_payload_validation_does_not_echo_private_input(self):
        response = await self.post(actor_id="private-invalid-input")
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("private-invalid-input", response.text)


if __name__ == "__main__":
    unittest.main()
