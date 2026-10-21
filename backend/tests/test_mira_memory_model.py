"""Mira's memory register tables in an explicitly disposable PostgreSQL schema."""
import importlib.util
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import inspect, text
from alembic.operations import Operations
from alembic.migration import MigrationContext
from tests.test_discord_voice_model import PostgresMeetingTests
from app.config import Settings
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting
from app.models.mira_memory import MiraMemoryItem as Item, MiraMemoryEvent as Event

MEETING_COLUMNS = {'memory_status', 'memory_attempts', 'memory_error', 'memory_lease_until'}


class MemoryTests(PostgresMeetingTests):
    """Meeting tables plus the memory register."""
    # Inherited meeting tests already run in their own module.
    test_concurrent_start_and_save_use_real_database_locks = None
    test_frozen_migration_creates_matching_columns_in_postgresql = None

    async def asyncSetUp(self):
        await super().asyncSetUp()
        async with self.engine.begin() as conn:
            await conn.run_sync(lambda c: Item.metadata.create_all(c, tables=[Item.__table__, Event.__table__]))


def migration():
    path = Path(__file__).resolve().parents[1]/'alembic/versions/0156_mira_memory.py'
    spec = importlib.util.spec_from_file_location('memory_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MemoryMigrationTests(MemoryTests):
    async def run_upgrade(self, before=None):
        module = migration()
        async with self.engine.begin() as conn:
            await conn.run_sync(lambda c: Event.__table__.drop(c))
            await conn.run_sync(lambda c: Item.__table__.drop(c))
            await conn.execute(text(f'SET LOCAL search_path TO {self.schema},public'))
            for column in MEETING_COLUMNS:
                await conn.execute(text(f'ALTER TABLE discord_voice_meetings DROP COLUMN {column}'))
            if before:
                await before(conn)
            def upgrade(c):
                with patch.object(module, 'op', Operations(MigrationContext.configure(c))):
                    module.upgrade()
            await conn.run_sync(upgrade)
            return await conn.run_sync(lambda c: {
                table: {x['name'] for x in inspect(c).get_columns(table, schema=self.schema)}
                for table in (Item.__tablename__, Event.__tablename__, Meeting.__tablename__)})

    async def test_frozen_migration_creates_matching_columns(self):
        columns = await self.run_upgrade()
        self.assertEqual(columns[Item.__tablename__], set(Item.__table__.c.keys()))
        self.assertEqual(columns[Event.__tablename__], set(Event.__table__.c.keys()))
        self.assertEqual(columns[Meeting.__tablename__], set(Meeting.__table__.c.keys()))

    async def test_migration_marks_existing_meetings_skipped(self):
        sid = uuid.uuid4()
        async def existing(conn):
            await conn.execute(text(
                "INSERT INTO discord_voice_meetings (id, link_id, user_id, guild_id, voice_channel_id, private_channel_id,"
                " request_id, instance_id, capture_token_hash, title, status, partial, stop_authorized)"
                " VALUES (:id, :lid, :uid, '123', '55', '44', 'old', :iid, 'h', 'Old', 'SAVED', false, true)"),
                {'id': sid, 'lid': self.lid, 'uid': self.uid, 'iid': uuid.uuid4()})
        await self.run_upgrade(existing)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Meeting, sid)).memory_status, 'SKIPPED')

    def test_flag_defaults_off(self):
        settings = Settings(DATABASE_URL='postgresql+asyncpg://x@y/z', JWT_SECRET='x' * 32, _env_file=None)
        self.assertFalse(settings.MIRA_MEMORY_ENABLED)
        self.assertEqual((settings.MIRA_MEMORY_QUIET_DAYS, settings.MIRA_MEMORY_RECENT_CLOSED_DAYS,
            settings.MIRA_MEMORY_MAX_ATTEMPTS, settings.MIRA_MEMORY_WAIT_MINUTES), (30, 14, 5, 15))


class MemoryDeployTests(unittest.TestCase):
    def test_memory_flag_is_opt_in_and_reaches_the_server(self):
        from scripts import configure_discord
        self.assertEqual(configure_discord.build_config({})['MIRA_MEMORY_ENABLED'], 'false')
        self.assertEqual(configure_discord.build_config({'MIRA_MEMORY_ENABLED': 'TRUE'})['MIRA_MEMORY_ENABLED'], 'true')
        with self.assertRaises(ValueError):
            configure_discord.build_config({'MIRA_MEMORY_ENABLED': 'sometimes'})
        workflow = (Path(__file__).resolve().parents[2]/'.github/workflows/deploy.yml').read_text()
        self.assertIn('MIRA_MEMORY_ENABLED: ${{ vars.MIRA_MEMORY_ENABLED }}', workflow)
