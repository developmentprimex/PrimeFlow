"""Real PostgreSQL locks/indexes in an explicitly disposable test database."""
import os
import unittest
import uuid
from unittest.mock import patch

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET', 'voice-tests-not-a-production-secret')
from sqlalchemy import text, select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.db import Base
from app import models
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting, DiscordVoiceSegment as Segment
from app.models.ga_note import GaNote
from app.models.department import Department
from app.models.user import User
from app.models.discord_assistant import DiscordLink
from app.schemas.discord_voice_meeting import VoiceStart, VoiceActor
from app.services import discord_voice_meetings as service
from app.config import settings

@unittest.skipUnless(os.environ.get('VOICE_TEST_DATABASE_URL'), 'Set VOICE_TEST_DATABASE_URL to disposable PostgreSQL')
class PostgresMeetingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        notes_key = patch.object(settings, 'MIRA_NOTES_OPENAI_API_KEY', 'voice-test-key')
        notes_key.start()
        self.addCleanup(notes_key.stop)
        self.schema = 'mira_test_' + uuid.uuid4().hex
        self.engine = create_async_engine(os.environ['VOICE_TEST_DATABASE_URL'], execution_options={'schema_translate_map':{None:self.schema}})
        from app.models.ga_note_attachment import GaNoteAttachment
        from app.models.mira_host import Mira1HEvent
        from app.models.mira_desktop import MiraDesktopSession
        from app.models.audit_log import AuditLog
        # GaNote always loads its attachments and asks whether Mira wrote it (mira_1h_events),
        # which no foreign key from these tables reaches.
        tables = {Segment.__table__, Meeting.__table__, GaNote.__table__, DiscordLink.__table__, GaNoteAttachment.__table__,
            Mira1HEvent.__table__, MiraDesktopSession.__table__, AuditLog.__table__}
        while True:
            expanded = tables | {fk.column.table for t in tables for fk in t.foreign_keys}
            if expanded == tables: break
            tables = expanded
        async with self.engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA {self.schema}'))
            await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=list(tables)))
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.uid, self.did, self.lid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with self.sessions() as db:
            db.add(Department(id=self.did, name='Mira test', code='TEST'))
            await db.flush()
            db.add(User(id=self.uid, username='mira_test', full_name='Mira Test', email='mira@example.test', password_hash='not-a-password', department_id=self.did))
            await db.flush()
            db.add(DiscordLink(id=self.lid, user_id=self.uid, discord_user_id='12', guild_id='123', channel_id='44'))
            await db.commit()

    async def asyncTearDown(self):
        async with self.engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA {self.schema} CASCADE'))
        await self.engine.dispose()

    async def test_concurrent_start_and_save_use_real_database_locks(self):
        import asyncio
        async def start(request):
            async with self.sessions() as db:
                try:
                    return await service.start_session(db, VoiceStart(discord_user_id='12', guild_id='123', channel_id='44',
                        voice_channel_id='55', request_id=request, instance_id=uuid.uuid4(), capture_token='a'*40, title='Staff'))
                except Exception as exc:
                    return exc
        with patch.object(settings, 'DISCORD_MEETING_NOTES_ENABLED', True), patch.object(settings, 'OPENAI_API_KEY', 'test'), patch.object(settings, 'DISCORD_GUILD_ID', '123'):
            results = await asyncio.gather(start('100'), start('101'))
            successes = [r for r in results if isinstance(r, dict)]
            self.assertEqual(len(successes), 1)
            self.assertEqual([r.status_code for r in results if not isinstance(r,dict)], [409])
            sid = uuid.UUID(successes[0]['id'])
            async with self.sessions() as db:
                row = await db.get(Meeting, sid)
                row.status, row.draft_text = 'READY', 'Staff\nVendime: kontrollo raportin.'
                await db.commit()
            actor = VoiceActor(discord_user_id='12', guild_id='123', channel_id='44', voice_channel_id='55')
            async def save():
                async with self.sessions() as db:
                    return await service.save_notes(db, actor, sid)
            a,b = await asyncio.gather(save(), save())
            self.assertEqual(a['saved_note_id'], b['saved_note_id'])
            async with self.sessions() as db:
                self.assertEqual((await db.execute(select(func.count()).select_from(GaNote))).scalar_one(), 1)

    async def test_frozen_migration_creates_matching_columns_in_postgresql(self):
        import importlib.util
        from pathlib import Path
        from alembic.operations import Operations
        from alembic.migration import MigrationContext
        from sqlalchemy import inspect
        path=Path(__file__).resolve().parents[1]/'alembic/versions/0152_discord_voice_meetings.py'
        spec=importlib.util.spec_from_file_location('voice_migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        async with self.engine.begin() as conn:
            # CASCADE only drops the Mira Host foreign keys that point at these tables.
            await conn.execute(text(f'DROP TABLE {self.schema}.{Segment.__tablename__}, {self.schema}.{Meeting.__tablename__} CASCADE'))
            await conn.execute(text(f'SET LOCAL search_path TO {self.schema},public'))
            def upgrade(c):
                with patch.object(module,'op',Operations(MigrationContext.configure(c))):module.upgrade()
                # 0156_mira_memory adds the memory columns after this frozen migration.
                later={'memory_status','memory_attempts','memory_error','memory_lease_until','recorder'}
                self.assertEqual({x['name'] for x in inspect(c).get_columns(Meeting.__tablename__,schema=self.schema)},set(Meeting.__table__.c.keys())-later)
                self.assertTrue(any(x['name']=='uq_discord_voice_active_guild' and x['unique'] for x in inspect(c).get_indexes(Meeting.__tablename__,schema=self.schema)))
            await conn.run_sync(upgrade)

    async def test_two_recorders_run_concurrently_but_each_keeps_its_own_lock_and_notes(self):
        import asyncio
        from fastapi import HTTPException
        from app.schemas.discord_voice_meeting import Worker
        async def start(request, recorder, channel):
            async with self.sessions() as db:
                return await service.start_session(db, VoiceStart(discord_user_id='12', guild_id='123', channel_id='44',
                    voice_channel_id=channel, recorder=recorder, request_id=request,
                    instance_id=uuid.uuid4(), capture_token=('a' if recorder == 'primary' else 'b') * 40, title=recorder))
        with patch.object(settings, 'DISCORD_MEETING_NOTES_ENABLED', True), \
             patch.object(settings, 'OPENAI_API_KEY', 'test'), patch.object(settings, 'DISCORD_GUILD_ID', '123'), \
             patch.object(settings, 'DISCORD_AI_AGENT_VOICE_CHANNEL_ID', '66'):
            one, two = await asyncio.gather(start('201', 'primary', '55'), start('202', 'ai_agent', '66'))
            self.assertNotEqual(one['id'], two['id'])
            for request, recorder, channel, code in [('203','primary','55',409), ('204','ai_agent','66',409),
                    ('205','ai_agent','55',403), ('206','primary','66',409)]:
                with self.assertRaises(HTTPException) as error:
                    await start(request, recorder, channel)
                self.assertEqual(error.exception.status_code, code)
            async with self.sessions() as db:
                row1 = await db.get(Meeting, uuid.UUID(one['id']))
                row2 = await db.get(Meeting, uuid.UUID(two['id']))
                with self.assertRaises(HTTPException):
                    await service.worker_row(db, row2.id, Worker(capture_token='a'*40, instance_id=row1.instance_id))
                row1.status, row1.draft_text = 'READY', 'Shënime vetëm nga 1H.'
                row2.status, row2.draft_text = 'READY', 'Shënime vetëm nga AI Agent.'
                await db.commit()
            actor = VoiceActor(discord_user_id='12', guild_id='123', channel_id='44')
            async with self.sessions() as db:
                saved1 = await service.save_notes(db, actor, uuid.UUID(one['id']))
            async with self.sessions() as db:
                saved2 = await service.save_notes(db, actor, uuid.UUID(two['id']))
            self.assertNotEqual(saved1['saved_note_id'], saved2['saved_note_id'])
            self.assertEqual(saved1['draft_text'], 'Shënime vetëm nga 1H.')
            self.assertEqual(saved2['draft_text'], 'Shënime vetëm nga AI Agent.')

    async def test_new_migration_replaces_the_guild_lock_with_per_recorder_uniqueness(self):
        from importlib.util import spec_from_file_location, module_from_spec
        from pathlib import Path
        from sqlalchemy import inspect
        from alembic.operations import Operations
        from alembic.migration import MigrationContext
        path = Path(__file__).resolve().parents[1] / 'alembic/versions/0174_discord_separate_recorders.py'
        spec = spec_from_file_location('separate_recorders_migration', path)
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        async with self.engine.begin() as conn:
            await conn.execute(text(f'SET LOCAL search_path TO {self.schema},public'))
            await conn.execute(text(f'DROP INDEX {self.schema}.uq_discord_voice_active_recorder'))
            await conn.execute(text(f'ALTER TABLE {self.schema}.discord_voice_meetings DROP COLUMN recorder'))
            await conn.execute(text(f"CREATE UNIQUE INDEX uq_discord_voice_active_guild ON {self.schema}.discord_voice_meetings (guild_id) WHERE status IN ('STARTING','LISTENING')"))
            def upgrade(connection):
                with patch.object(migration, 'op', Operations(MigrationContext.configure(connection))):
                    migration.upgrade()
                indices = inspect(connection).get_indexes('discord_voice_meetings', schema=self.schema)
                new = next(index for index in indices if index['name'] == 'uq_discord_voice_active_recorder')
                self.assertEqual(new['column_names'], ['guild_id', 'recorder'])
                self.assertTrue(new['unique'])
            await conn.run_sync(upgrade)
