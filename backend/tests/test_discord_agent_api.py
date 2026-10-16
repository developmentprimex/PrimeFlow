import os
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/primeflow_test")
os.environ.setdefault("JWT_SECRET", "test-discord-secret-not-for-production")

from fastapi import HTTPException
from app.services import discord_agents as service
from app.services import discord_task_tools as tools
from app.api.routers import discord_assistant as bridge
from app.models.discord_agent_run import DiscordAgentRun
from app.schemas.discord_agent import AgentActor, AgentCreate, AgentAccept, AgentDelivery, AgentReceipt

TASK = {"id": str(uuid.uuid4()), "title": "Task", "description": "• Same\n• Same", "user_comment": None}
ACTOR = dict(discord_user_id="12", guild_id="123", channel_id="44")


def run_fixture(**changes):
    values = dict(id=uuid.uuid4(), link_id=uuid.uuid4(), user_id=uuid.uuid4(), task_id=uuid.UUID(TASK["id"]),
        parent_run_id=None, request_id="777", mode="RESEARCH", model="gpt-6-luna", instruction="Research",
        fingerprint=tools.fingerprint(TASK), target=service.resolve_target(TASK, "description", 2),
        context=service.snapshot_context(TASK, service.resolve_target(TASK, "description", 2)),
        status="READY", result_text="Result", sources=[], usage=None, error=None, response_id="resp_123",
        lease_token=None, lease_until=None, delivery_token=None, delivery_until=None, delivered_at=None,
        accepted_at=None, acceptance_request_id=None, acceptance_status=None, message_ids=None,
        created_at=datetime.now(timezone.utc), started_at=None, finished_at=None)
    return DiscordAgentRun(**(values | changes))


class AgentApiTests(unittest.IsolatedAsyncioTestCase):
    def function(self, name):
        self.assertTrue(callable(getattr(service, name, None)), f"Missing {name}")
        return getattr(service, name)

    def setup_actor(self, run=None):
        self.run = run or run_fixture()
        self.link = SimpleNamespace(id=self.run.link_id, user_id=self.run.user_id)
        self.user = SimpleNamespace(id=self.run.user_id)
        self.db = SimpleNamespace(get=AsyncMock(return_value=self.run), execute=AsyncMock(), add=Mock(), commit=AsyncMock(), flush=AsyncMock(), refresh=AsyncMock(), rollback=AsyncMock())
        self.db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=None))
        return patch.object(bridge, "identity", AsyncMock(return_value=(self.link, self.user))), patch.object(bridge, "owned_task", AsyncMock(return_value=TASK))

    async def test_create_snapshots_target_without_mutating_task(self):
        create = self.function("create_run")
        identity, owned = self.setup_actor()
        payload = AgentCreate(**ACTOR, request_id="1234", task_id=TASK["id"], expected_fingerprint=tools.fingerprint(TASK)[:16], mode="RESEARCH", instruction="Find sources", field="description", number=2)
        with identity, owned, patch.object(tools, "user_api", AsyncMock()) as api:
            result = await create(self.db, payload)
        saved = self.db.add.call_args.args[0]
        self.assertEqual(saved.target["number"], 2)
        self.assertEqual(saved.model, "gpt-6-luna")
        self.assertEqual(saved.status, "QUEUED")
        self.assertEqual(result["status"], "QUEUED")
        api.assert_not_called()

    async def test_stale_creation_and_cross_identity_replay_rejected(self):
        create = self.function("create_run")
        identity, owned = self.setup_actor()
        payload = AgentCreate(**ACTOR, request_id="1234", task_id=TASK["id"], expected_fingerprint="a"*16, mode="DRAFT", instruction="Write draft")
        with identity, owned, self.assertRaises(HTTPException) as error:
            await create(self.db, payload)
        self.assertEqual(error.exception.status_code, 409)
        self.db.add.assert_not_called()
        self.db.execute.return_value.scalar_one_or_none.return_value = self.run
        self.run.link_id = uuid.uuid4()
        identity, owned = self.setup_actor(self.run)
        self.link.id = uuid.uuid4()
        self.db.execute.return_value.scalar_one_or_none.return_value = self.run
        with identity, owned, self.assertRaises(HTTPException) as error:
            await create(self.db, payload)
        self.assertEqual(error.exception.status_code, 409)

    async def test_creation_replay_returns_original_run(self):
        create = self.function("create_run")
        identity, owned = self.setup_actor()
        self.db.execute.return_value.scalar_one_or_none.return_value = self.run
        payload = AgentCreate(**ACTOR, request_id=self.run.request_id, task_id=TASK["id"], expected_fingerprint="a"*16, mode="DRAFT", instruction="Duplicate")
        with identity, owned:
            result = await create(self.db, payload)
        self.assertEqual(result["id"], str(self.run.id))
        self.db.add.assert_not_called()

    async def test_wrong_owner_revoked_identity_and_missing_task_denied(self):
        authorize = self.function("authorized_run")
        for reason in ("owner", "revoked", "task", "other_run"):
            with self.subTest(reason=reason):
                identity, owned = self.setup_actor()
                if reason == "owner": self.link.id = uuid.uuid4()
                if reason == "other_run": self.run.user_id = uuid.uuid4()
                if reason == "task": self.run.task_id = None
                with identity, owned, patch.object(bridge, "identity", AsyncMock(side_effect=HTTPException(403, "revoked"))) if reason == "revoked" else patch.object(bridge, "owned_task", AsyncMock(side_effect=HTTPException(403, "reassigned"))) if reason == "task" else patch.object(tools, "user_api", AsyncMock()), self.assertRaises(HTTPException):
                    await authorize(self.db, AgentActor(**ACTOR), self.run.id)

    async def test_plain_acceptance_never_writes_task(self):
        accept = self.function("accept_run")
        identity, owned = self.setup_actor()
        with identity, owned, patch.object(bridge, "command", AsyncMock()) as command:
            await accept(self.db, self.run.id, AgentAccept(**ACTOR, request_id="2000"))
        self.assertIsNotNone(self.run.accepted_at)
        command.assert_not_called()

    async def test_point_acceptance_uses_exact_normal_api_and_is_idempotent(self):
        accept = self.function("accept_run")
        identity, owned = self.setup_actor()
        with identity, owned, patch.object(bridge, "command", AsyncMock(return_value={"status": "DONE", "task": TASK})) as command:
            await accept(self.db, self.run.id, AgentAccept(**ACTOR, request_id="2000", mark_point_done=True))
            await accept(self.db, self.run.id, AgentAccept(**ACTOR, request_id="2001", mark_point_done=True))
        command.assert_awaited_once()
        payload = command.call_args.args[0]
        import json
        self.assertEqual(json.loads(payload.direct_actions[0].arguments_json), {"field": "description", "numbers": [2], "done": True})
        self.assertEqual(payload.expected_fingerprint, tools.fingerprint(TASK)[:16])
        self.assertIsNotNone(self.run.accepted_at)

    async def test_changed_target_and_rejected_write_never_mark_accepted(self):
        accept = self.function("accept_run")
        for changed in (True, False):
            identity, owned = self.setup_actor()
            if changed: self.run.fingerprint = "b" * 64
            with identity, owned, patch.object(bridge, "command", AsyncMock(return_value={"status": "ERROR", "message": "Denied"})) as command, self.assertRaises(HTTPException):
                await accept(self.db, self.run.id, AgentAccept(**ACTOR, request_id="2000", mark_point_done=True))
            self.assertIsNone(self.run.accepted_at)
            if changed: command.assert_not_called()

    async def test_pending_acceptance_cannot_start_second_write(self):
        accept = self.function("accept_run")
        identity, owned = self.setup_actor(run_fixture(acceptance_request_id="2000", acceptance_status="APPLYING"))
        self.db.get.side_effect = [self.run, None]
        with identity, owned, patch.object(bridge, "command", AsyncMock()) as command, self.assertRaises(HTTPException) as error:
            await accept(self.db, self.run.id, AgentAccept(**ACTOR, request_id="2001", mark_point_done=True))
        self.assertEqual(error.exception.status_code, 409)
        command.assert_not_called()

    async def test_cancel_preserves_remote_id_and_ready_result(self):
        cancel = self.function("cancel_run")
        for initial, expected in (("QUEUED", "CANCELLED"), ("SUBMITTING", "CANCEL_REQUESTED"), ("RUNNING", "CANCEL_REQUESTED"), ("READY", "READY")):
            identity, owned = self.setup_actor(run_fixture(status=initial))
            with identity, owned:
                await cancel(self.db, self.run.id, AgentActor(**ACTOR))
            self.assertEqual(self.run.status, expected)
            self.assertEqual(self.run.response_id, "resp_123")

    async def test_revision_cannot_reference_other_target_or_task(self):
        create = self.function("create_run")
        identity, owned = self.setup_actor()
        payload = AgentCreate(**ACTOR, request_id="1234", task_id=TASK["id"], expected_fingerprint=tools.fingerprint(TASK)[:16], mode="RESEARCH", instruction="Improve", parent_run_id=self.run.id)
        with identity, owned, self.assertRaises(HTTPException):
            await create(self.db, payload)
        self.db.add.assert_not_called()

    async def test_delivery_requires_matching_live_lease_and_actor(self):
        delivery = self.function("delivery_run")
        from datetime import timedelta
        token = uuid.uuid4()
        identity, owned = self.setup_actor(run_fixture(delivery_token=token, delivery_until=datetime.now(timezone.utc)+timedelta(minutes=2)))
        with identity, owned:
            result = await delivery(self.db, self.run.id, AgentDelivery(**ACTOR, lease_token=token))
        self.assertEqual(result["id"], str(self.run.id))
        for token_value, until in ((uuid.uuid4(), self.run.delivery_until), (token, datetime.now(timezone.utc)-timedelta(seconds=1))):
            self.run.delivery_until = until
            identity, owned = self.setup_actor(self.run)
            with identity, owned, self.assertRaises(HTTPException) as error:
                await delivery(self.db, self.run.id, AgentDelivery(**ACTOR, lease_token=token_value))
            self.assertEqual(error.exception.status_code, 409)

    async def test_ack_is_idempotent_and_stale_token_cannot_overwrite(self):
        ack = self.function("ack_delivery")
        from datetime import timedelta
        token = uuid.uuid4()
        identity, owned = self.setup_actor(run_fixture(delivery_token=token, delivery_until=datetime.now(timezone.utc)+timedelta(minutes=2)))
        receipt = AgentReceipt(**ACTOR, lease_token=token, message_ids=["123"])
        with identity, owned:
            await ack(self.db, self.run.id, receipt)
            await ack(self.db, self.run.id, receipt)
        self.assertEqual(self.run.message_ids, ["123"])
        self.assertIsNotNone(self.run.delivered_at)
        identity, owned = self.setup_actor(self.run)
        with identity, owned, self.assertRaises(HTTPException):
            await ack(self.db, self.run.id, AgentReceipt(**ACTOR, lease_token=uuid.uuid4(), message_ids=["456"]))
        self.assertEqual(self.run.message_ids, ["123"])

    async def test_delivery_claims_only_authorized_runs_without_exposing_results(self):
        claim = self.function("claim_deliveries")
        identity, owned = self.setup_actor()
        self.link.discord_user_id, self.link.guild_id, self.link.channel_id = "12", "123", "44"
        self.db.execute.return_value = Mock(all=Mock(return_value=[(self.run, self.link)]))
        with identity, owned:
            result = await claim(self.db)
        job = result["jobs"][0]
        self.assertEqual(job["run_id"], str(self.run.id))
        self.assertNotIn("result_text", job)
        self.assertEqual(job["lease_token"], str(self.run.delivery_token))
        from sqlalchemy.dialects import postgresql
        sql = str(self.db.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
        self.assertIn("SKIP LOCKED", sql)
        self.assertIn("delivered_at IS NULL", sql)
        self.assertIn("discord_links.enabled IS true", sql)

    async def test_revocation_between_delivery_claim_and_read_blocks_result(self):
        delivery = self.function("delivery_run")
        identity, owned = self.setup_actor()
        with patch.object(bridge, "identity", AsyncMock(side_effect=HTTPException(403, "revoked"))), owned, self.assertRaises(HTTPException):
            await delivery(self.db, self.run.id, AgentDelivery(**ACTOR, lease_token=uuid.uuid4()))
