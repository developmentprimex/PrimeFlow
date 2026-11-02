"""Recognize an observed deployed revision without changing its recorded stamp."""
import os
from pathlib import Path
import unittest
import uuid

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from unittest.mock import patch


def scripts():
    config=Config()
    config.set_main_option('script_location',str(Path(__file__).resolve().parents[1]/'alembic'))
    return ScriptDirectory.from_config(config)


class DeployedNoteMigrationTests(unittest.TestCase):
    def test_deployed_revision_is_recognized_and_is_the_single_head(self):
        graph=scripts()
        observed='0178_ga_note_is_repetitive'
        self.assertEqual(graph.get_revision(observed).down_revision,'0177_task_is_repetitive')
        self.assertEqual(graph.get_heads(),[observed])
        self.assertEqual(graph._upgrade_revs('head',observed),[])
        self.assertEqual([step.revision.revision for step in graph._upgrade_revs('head','0177_task_is_repetitive')],[observed])


@unittest.skipUnless(os.getenv('GA_PERSONAL_TEST_DATABASE_URL'),'Explicit disposable PostgreSQL required')
class DeployedNoteMigrationDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_upgrade_is_repeatable_and_preserves_existing_note_flags(self):
        engine=create_async_engine(os.environ['GA_PERSONAL_TEST_DATABASE_URL'])
        schema='ga_revision_test_'+uuid.uuid4().hex
        migration=scripts().get_revision('0178_ga_note_is_repetitive').module
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await conn.execute(text('CREATE TABLE ga_notes (id integer PRIMARY KEY, content text NOT NULL)'))
                await conn.execute(text("INSERT INTO ga_notes (id,content) VALUES (1,'Existing synthetic note')"))
                def upgrade(sync):
                    operations=Operations(MigrationContext.configure(sync))
                    with patch.object(migration,'op',operations):migration.upgrade()
                await conn.run_sync(upgrade)
                self.assertEqual((await conn.execute(text('SELECT is_repetitive FROM ga_notes'))).scalar_one(),False)
                await conn.execute(text('UPDATE ga_notes SET is_repetitive=true WHERE id=1'))
                await conn.run_sync(upgrade)
                row=(await conn.execute(text('SELECT content,is_repetitive FROM ga_notes'))).one()
                self.assertEqual(tuple(row),('Existing synthetic note',True))
                await conn.execute(text('INSERT INTO ga_notes (id,content) VALUES (2,\'New synthetic note\')'))
                self.assertFalse((await conn.execute(text('SELECT is_repetitive FROM ga_notes WHERE id=2'))).scalar_one())
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            await engine.dispose()
