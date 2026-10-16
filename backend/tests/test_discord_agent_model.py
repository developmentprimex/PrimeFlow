import importlib
import importlib.util
import os
import unittest
import uuid
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@127.0.0.1/primeflow_test")
os.environ.setdefault("JWT_SECRET", "test-discord-secret-not-for-production")


class AgentModelTests(unittest.TestCase):
    def service(self):
        self.assertIsNotNone(importlib.util.find_spec("app.services.discord_agents"), "Agent target service is missing")
        return importlib.import_module("app.services.discord_agents")

    def test_full_task_and_duplicate_point_identity(self):
        service = self.service()
        task = {"id": str(uuid.uuid4()), "title": "Task", "description": "• Same\n• Same"}
        self.assertEqual(service.resolve_target(task, None, None), {"field": None, "number": None, "key": None, "text": None})
        self.assertNotEqual(service.resolve_target(task, "description", 1)["key"], service.resolve_target(task, "description", 2)["key"])
        self.assertEqual(service.resolve_target(task, "title", 1)["text"], "Task")

    def test_invalid_target_is_rejected(self):
        service = self.service()
        for field, number in (("internal_notes", 1), (None, 1), ("title", 0), ("title", True), ("title", 99)):
            with self.subTest(field=field, number=number), self.assertRaises(ValueError):
                service.resolve_target({"title": "Task"}, field, number)

    def test_context_is_allowlisted(self):
        service = self.service()
        task = {"id": "t", "title": "Title", "description": "Body", "user_comment": "Mine", "other_comments": "private", "access_token": "secret"}
        snapshot = service.snapshot_context(task, service.resolve_target(task, None, None))
        self.assertEqual(set(snapshot), {"id", "title", "description", "user_comment", "target"})
        self.assertNotIn("private", str(snapshot))
        self.assertNotIn("secret", str(snapshot))

    def test_model_and_migration_columns_match(self):
        self.service()
        from app.models.discord_agent_run import DiscordAgentRun
        from tests.test_migration_graph import migration_scripts
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from io import StringIO
        from unittest.mock import patch
        scripts = migration_scripts()
        self.assertEqual(scripts.get_heads(), ["0149_discord_agent_runs"])
        migration = scripts.get_revision("0149_discord_agent_runs").module
        output = StringIO()
        operations = Operations(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}))
        with patch.object(migration, "op", operations):
            migration.upgrade()
        for column in DiscordAgentRun.__table__.c:
            self.assertIn(column.name, output.getvalue())
        self.assertTrue(DiscordAgentRun.__table__.c.request_id.unique)

    def test_agent_model_defaults_independently(self):
        from app.config import settings
        self.assertEqual(getattr(settings, "DISCORD_AGENT_MODEL", None), "gpt-6-luna")
        from scripts.configure_discord import build_config
        self.assertEqual(build_config({})["DISCORD_AGENT_MODEL"], "gpt-6-luna")

    def test_create_requires_exact_version_and_valid_target(self):
        self.service()
        from app.schemas.discord_agent import AgentCreate
        from pydantic import ValidationError
        payload = dict(discord_user_id="12", guild_id="123", channel_id="44", request_id="999", task_id=str(uuid.uuid4()), expected_fingerprint="a" * 16, mode="RESEARCH", instruction="Find competitors")
        self.assertEqual(AgentCreate(**payload).mode, "RESEARCH")
        for changes in ({"expected_fingerprint": ""}, {"field": "title"}, {"field": None, "number": 1}, {"mode": "SHELL"}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                AgentCreate(**(payload | changes))
