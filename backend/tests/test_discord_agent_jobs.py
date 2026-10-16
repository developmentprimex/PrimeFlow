import importlib
import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from tests.test_discord_agent_api import run_fixture


class AgentJobTests(unittest.IsolatedAsyncioTestCase):
    def job(self):
        self.assertIsNotNone(importlib.util.find_spec("app.jobs.discord_agents"), "Agent job missing")
        return importlib.import_module("app.jobs.discord_agents")

    async def execute(self, run, *, submit=None, retrieve=None, cancel=None, revoked=False):
        job = self.job()
        self.remote = SimpleNamespace(submit=AsyncMock(return_value=submit or {"id": "resp_new", "status": "queued"}),
            retrieve=AsyncMock(return_value=retrieve or {"status": "in_progress"}),
            cancel=AsyncMock(return_value=cancel or {"status": "cancelled"}))
        self.saves = []
        async def save(work, values):
            self.saves.append(dict(values))
            for k, v in values.items(): setattr(run, k, v)
            return True
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder, patch.object(job, "RECOVERY_DIR", Path(folder)), patch.object(job, "remember_response", AsyncMock(return_value=True)), patch.object(job, "save_claim", side_effect=save), patch.object(job, "is_authorized", AsyncMock(return_value=not revoked)), patch.object(job, "provider", self.remote):
            await job.process_claim(run)
        return run

    async def test_new_submission_preserves_response_id_and_background_state(self):
        run = await self.execute(run_fixture(status="QUEUED", response_id=None))
        self.remote.submit.assert_awaited_once()
        self.assertEqual(run.response_id, "resp_new")
        self.assertEqual(run.status, "RUNNING")
        self.assertEqual(self.saves[0]["status"], "SUBMITTING")

    async def test_restart_polls_same_response_without_resubmission(self):
        run = await self.execute(run_fixture(status="RUNNING"))
        self.remote.submit.assert_not_called()
        self.remote.retrieve.assert_awaited_once_with("resp_123")
        self.assertEqual(run.status, "RUNNING")

    async def test_expired_ambiguous_submission_never_resubmits(self):
        run = await self.execute(run_fixture(status="SUBMITTING", response_id=None))
        self.remote.submit.assert_not_called()
        self.assertEqual(run.status, "FAILED")
        self.assertIn("paqartë", run.error)

    async def test_revocation_requests_remote_cancel_but_never_submits(self):
        run = await self.execute(run_fixture(status="RUNNING"), revoked=True)
        self.remote.submit.assert_not_called()
        self.remote.cancel.assert_awaited_once_with("resp_123")
        self.assertEqual(run.status, "CANCELLED")
        run = await self.execute(run_fixture(status="QUEUED", response_id=None), revoked=True)
        self.remote.submit.assert_not_called()
        self.assertEqual(run.status, "CANCELLED")

    async def test_cancellation_after_provider_completed_keeps_real_result(self):
        data = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "Actual result"}]}]}
        run = await self.execute(run_fixture(status="CANCEL_REQUESTED", mode="DRAFT"), cancel=data)
        self.assertEqual(run.status, "READY")
        self.assertEqual(run.result_text, "Actual result")

    async def test_transient_poll_failure_is_resumable(self):
        import httpx
        job = self.job()
        run = run_fixture(status="RUNNING")
        async def failing(_): raise httpx.ReadTimeout("secret provider text")
        with patch.object(job, "is_authorized", AsyncMock(return_value=True)), patch.object(job.provider, "retrieve", side_effect=failing), patch.object(job, "save_claim", AsyncMock()) as save:
            await job.process_claim(run)
        self.assertEqual(save.call_args.args[1]["status"], "RUNNING")
        self.assertNotIn("secret", str(save.call_args))

    async def test_unsupported_model_fails_without_fallback(self):
        import httpx
        job = self.job()
        run = run_fixture(status="QUEUED", response_id=None)
        failure = httpx.HTTPStatusError("secret body", request=httpx.Request("POST", "https://api.openai.com"), response=httpx.Response(404))
        with patch.object(job, "is_authorized", AsyncMock(return_value=True)), patch.object(job.provider, "submit", AsyncMock(side_effect=failure)) as submit, patch.object(job, "save_claim", AsyncMock(return_value=True)) as save:
            await job.process_claim(run)
        submit.assert_awaited_once()
        self.assertEqual(save.call_args.args[1]["status"], "FAILED")
        self.assertNotIn("secret", str(save.call_args))

    async def test_processing_claim_query_skips_locked_rows_and_sets_lease(self):
        job = self.job()
        from sqlalchemy.dialects import postgresql
        sql = str(job.claim_query(datetime.now(timezone.utc)).compile(dialect=postgresql.dialect()))
        self.assertIn("SKIP LOCKED", sql)
        self.assertIn("lease_until", sql)

    async def test_schedule_uses_30_seconds_and_existing_async_wrapper(self):
        self.job()
        from app.celery_app import celery_app
        from app import celery_tasks
        self.assertEqual(celery_app.conf.beat_schedule["process-discord-agent-runs"]["schedule"], 30.0)
        with patch.object(celery_tasks, "_run_async", return_value={"processed": 1}) as wrapper:
            result = celery_tasks.process_discord_agent_runs()
            wrapper.call_args.args[0].close()
        self.assertEqual(result, {"processed": 1})

    async def test_late_response_id_is_durable_even_after_lease_reclaimed(self):
        job = self.job()
        self.assertTrue(callable(getattr(job, "remember_response", None)), "Missing lease-independent response persistence")
        run = run_fixture(status="FAILED", response_id=None, lease_token=__import__("uuid").uuid4())
        original = SimpleNamespace(id=run.id, lease_token=__import__("uuid").uuid4())
        db = SimpleNamespace(get=AsyncMock(return_value=run), commit=AsyncMock())
        context = AsyncMock()
        context.__aenter__.return_value = db
        with patch.object(job, "SessionLocal", return_value=context):
            owned = await job.remember_response(original, "resp_late")
        self.assertFalse(owned)
        self.assertEqual(run.response_id, "resp_late")
        self.assertEqual(run.cleanup_response_id, "resp_late")
        self.assertEqual(run.status, "FAILED")
        db.commit.assert_awaited_once()

    async def test_cleanup_timeout_remains_retryable_on_terminal_run(self):
        job = self.job()
        self.assertTrue(callable(getattr(job, "process_cleanup", None)), "Missing durable cleanup")
        import httpx
        run = run_fixture(status="FAILED", response_id="resp_late")
        run.cleanup_response_id = "resp_late"
        with patch.object(job.provider, "cancel", AsyncMock(side_effect=httpx.ReadTimeout("timeout"))), patch.object(job, "finish_cleanup", AsyncMock()) as finished:
            await job.process_cleanup(run)
        finished.assert_not_called()
        self.assertEqual(run.cleanup_response_id, "resp_late")
        from sqlalchemy.dialects import postgresql
        sql = str(job.claim_query(datetime.now(timezone.utc)).compile(dialect=postgresql.dialect()))
        self.assertIn("cleanup_response_id IS NOT NULL", sql)

    async def test_provider_id_is_spooled_before_database_failure_and_recovered(self):
        job = self.job()
        self.assertTrue(callable(getattr(job, "recover_responses", None)), "Missing response recovery")
        import tempfile
        from pathlib import Path
        run = run_fixture(status="QUEUED", response_id=None)
        with tempfile.TemporaryDirectory() as folder, patch.object(job, "RECOVERY_DIR", Path(folder)), patch.object(job, "save_claim", AsyncMock(return_value=True)), patch.object(job, "is_authorized", AsyncMock(return_value=True)), patch.object(job.provider, "submit", AsyncMock(return_value={"id": "resp_late", "status": "queued"})), patch.object(job, "remember_response", AsyncMock(side_effect=RuntimeError("database offline"))):
            await job.process_claim(run)
            self.assertEqual(len(list(Path(folder).glob("*.json"))), 1)
            with patch.object(job, "remember_response", AsyncMock(return_value=False)) as remember:
                await job.recover_responses()
            self.assertEqual(remember.call_args.args[1], "resp_late")
            self.assertEqual(list(Path(folder).glob("*.json")), [])

    async def test_late_response_never_overwrites_completed_result(self):
        job = self.job()
        self.assertTrue(callable(getattr(job, "remember_response", None)), "Missing lease-independent response persistence")
        run = run_fixture(status="READY", response_id="resp_original", result_text="Keep result")
        db = SimpleNamespace(get=AsyncMock(return_value=run), commit=AsyncMock())
        context = AsyncMock()
        context.__aenter__.return_value = db
        with patch.object(job, "SessionLocal", return_value=context):
            await job.remember_response(SimpleNamespace(id=run.id, lease_token=__import__("uuid").uuid4()), "resp_late")
        self.assertEqual(run.status, "READY")
        self.assertEqual(run.response_id, "resp_original")
        self.assertEqual(run.result_text, "Keep result")
        self.assertEqual(run.cleanup_response_id, "resp_late")
