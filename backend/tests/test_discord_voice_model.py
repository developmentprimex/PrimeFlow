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
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting
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
        self.schema = 'mira_test_' + uuid.uuid4().hex
        self.engine = create_async_engine(os.environ['VOICE_TEST_DATABASE_URL'], execution_options={'schema_translate_map':{None:self.schema}})
        tables = {Meeting.__table__, GaNote.__table__, DiscordLink.__table__}
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
