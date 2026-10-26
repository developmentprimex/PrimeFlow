"""Opt-in disposable PostgreSQL tests. Never use the application's DATABASE_URL.

MIRA_DESKTOP_TEST_DATABASE_URL must name localhost's mira_desktop_test database.
The fixture creates and drops only a fresh random schema inside that database.
"""
import asyncio
import os
import uuid
import unittest
import importlib.util
from pathlib import Path
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.engine import make_url

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET', 'desktop-test-secret')
from fastapi import HTTPException
from app.db import Base
from app.models.user import User
from app.models.enums import UserRole
from app.models.ga_note import GaNote
from app.models.mira_desktop import MiraDesktopSession, MiraDesktopSegment
from app.schemas.mira_desktop import DesktopStart, DesktopFinish
from app.services import mira_desktop as service
from backend.tests.test_mira_desktop import wav

URL = os.environ.get('MIRA_DESKTOP_TEST_DATABASE_URL')


@unittest.skipUnless(URL, 'requires explicit disposable local PostgreSQL URL')
class DesktopIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        parsed = make_url(URL)
        if parsed.host not in ('127.0.0.1', 'localhost') or parsed.database != 'mira_desktop_test':
            raise RuntimeError('Refusing any database except local mira_desktop_test')
        cls.schema = 'desktop_test_'+uuid.uuid4().hex
        cls.engine = create_async_engine(URL, poolclass=NullPool,
            connect_args={'server_settings': {'search_path': cls.schema}})
        cls.sessions = async_sessionmaker(cls.engine, expire_on_commit=False)
        async def create():
            async with cls.engine.begin() as conn:
                await conn.execute(text('CREATE SCHEMA '+cls.schema))
                await conn.run_sync(Base.metadata.create_all)
                # Exercise the shipped migration rather than testing only ORM DDL.
                await conn.run_sync(MiraDesktopSegment.__table__.drop)
                await conn.run_sync(MiraDesktopSession.__table__.drop)
                def migration(sync):
                    from alembic.migration import MigrationContext
                    from alembic.operations import Operations
                    path = Path(__file__).parents[1]/'alembic/versions/0165_mira_desktop.py'
                    spec = importlib.util.spec_from_file_location('desktop_migration', path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    with Operations.context(MigrationContext.configure(sync)):
                        module.upgrade()
                        module.downgrade()
                        module.upgrade()
                await conn.run_sync(migration)
        asyncio.run(create())

    @classmethod
    def tearDownClass(cls):
        async def drop():
            async with cls.engine.begin() as conn:
                await conn.execute(text('DROP SCHEMA '+cls.schema+' CASCADE'))
            await cls.engine.dispose()
        asyncio.run(drop())

    async def asyncSetUp(self):
        self.db = self.sessions()
        self.user = User(id=uuid.uuid4(), email=uuid.uuid4().hex+'@test.invalid', full_name='Test',
            role=UserRole.ADMIN, password_hash='not-a-password')
        self.other = User(id=uuid.uuid4(), email=uuid.uuid4().hex+'@test.invalid', full_name='Other',
            role=UserRole.ADMIN, password_hash='not-a-password')
        self.db.add_all([self.user, self.other])
        await self.db.commit()
        self.flag = patch.object(service.settings, 'OPENAI_API_KEY', 'fake-not-sent')
        self.flag.start()
        self.payload = DesktopStart(id=uuid.uuid4(), title='Call', consent_acknowledged=True)
        await service.create_session(self.db, self.user, self.payload)

    async def asyncTearDown(self):
        self.flag.stop()
        await self.db.close()

    async def upload(self, sequence=0, start=0, end=10, data=None):
        return await service.upload_segment(self.db, self.user, self.payload.id, sequence,
            start, end, data or wav())

    async def finish(self, count=1):
        return await service.finish_session(self.db, self.user, self.payload.id,
            DesktopFinish(segment_count=count))

    async def test_owner_is_enforced_on_read_upload_finish_and_create_replay(self):
        operations = [lambda: service.get_session(self.db, self.other, self.payload.id),
            lambda: service.upload_segment(self.db, self.other, self.payload.id, 0, 0, 10, wav()),
            lambda: service.finish_session(self.db, self.other, self.payload.id, DesktopFinish(segment_count=0)),
            lambda: service.create_session(self.db, self.other, self.payload)]
        for operation in operations:
            with self.assertRaises(HTTPException) as caught:
                await operation()
            self.assertEqual(caught.exception.status_code, 404)
            await self.db.rollback()
            await self.db.refresh(self.other)

    async def test_router_owner_scope_with_real_sessions(self):
        import httpx
        from fastapi import FastAPI
        from app.api.routers.mira_desktop import router
        from app.api.deps import get_current_user
        from app.db import get_db
        app = FastAPI()
        app.include_router(router, prefix='/api/mira-desktop')
        app.dependency_overrides[get_current_user] = lambda: self.other
        async def database():
            yield self.db
        app.dependency_overrides[get_db] = database
        base = '/api/mira-desktop/sessions/'+str(self.payload.id)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as api:
            assert (await api.get(base)).status_code == 404
            assert (await api.post(base+'/finish', json={'segment_count': 0})).status_code == 404
            assert (await api.post(base+'/segments/0?start_ms=0&end_ms=10', content=wav(),
                headers={'Content-Type': 'audio/wav'})).status_code == 404

    async def test_duplicate_hash_conflict_and_provider_retry(self):
        with patch.object(service.provider, 'transcribe_segment', AsyncMock(side_effect=ValueError())):
            with self.assertRaises(HTTPException): await self.upload()
        with patch.object(service.provider, 'transcribe_segment', AsyncMock(return_value='Po')) as call:
            self.assertEqual((await self.upload())['transcript'], 'Po')
            self.assertEqual((await self.upload())['transcript'], 'Po')
            self.assertEqual(call.await_count, 1)
            with self.assertRaises(HTTPException) as caught: await self.upload(data=wav(481))
            self.assertEqual(caught.exception.status_code, 409)

    async def test_missing_or_out_of_order_segments_cannot_finish(self):
        with self.assertRaises(HTTPException): await self.upload(sequence=1)
        await self.db.rollback()
        await self.db.refresh(self.user)
        with self.assertRaises(HTTPException) as caught: await self.finish()
        self.assertEqual(caught.exception.detail, 'missing_segments')
        await self.db.rollback()
        await self.db.refresh(self.user)
        with patch.object(service.provider, 'transcribe_segment', AsyncMock(return_value='Po')):
            await self.upload()
        with self.assertRaises(HTTPException): await self.finish(2)

    async def test_finished_replay_saves_exactly_one_note_and_exposes_text(self):
        with patch.object(service.provider, 'transcribe_segment', AsyncMock(return_value='Po')):
            await self.upload()
        with patch.object(service, 'summarize', AsyncMock(return_value='Call\n\nNotes')) as call:
            first = await self.finish()
            second = await self.finish()
        self.assertEqual(first['note_id'], second['note_id'])
        self.assertIsNotNone(first['note_id'])
        self.assertIn('Po', first['transcript'])
        self.assertEqual(call.await_count, 1)
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(GaNote).where(
            GaNote.created_by == self.user.id)), 1)

    async def test_px_note_has_mira_display_marker_and_owner_can_open_unnamed_transcript(self):
        from app.api.routers.ga_notes import _note_out
        with patch.object(service.provider, 'transcribe_segment', AsyncMock(return_value='Vendimi u mor.')):
            await self.upload()
        with patch.object(service, 'summarize', AsyncMock(return_value='Call\n\n**Përmbledhja:** Po.')):
            result=await self.finish()
        note_id=uuid.UUID(result['note_id'])
        note=(await self.db.execute(select(GaNote).where(GaNote.id==note_id))).scalar_one()
        self.assertTrue(_note_out(note).from_mira)
        transcript=await service.note_transcript_for_note(self.db,self.user,note_id)
        self.assertEqual(transcript['passages'][0]['speaker'],'')
        self.assertEqual(transcript['passages'][0]['text'],'Vendimi u mor.')
        self.assertEqual(transcript['note_id'],str(note_id))
        with self.assertRaises(HTTPException) as caught:
            await service.note_transcript_for_note(self.db,self.other,note_id)
        self.assertEqual(caught.exception.status_code,404)

    async def test_silence_finishes_without_note_or_summary(self):
        with patch.object(service.provider, 'transcribe_segment', AsyncMock(return_value='')):
            await self.upload()
        with patch.object(service.provider, 'cached', AsyncMock()) as call:
            result = await self.finish()
        self.assertEqual(result['status'], 'DONE')
        self.assertEqual(result['notes'], '')
        self.assertIsNone(result['note_id'])
        call.assert_not_awaited()

    async def test_concurrent_segment_replay_does_not_call_provider_twice(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def transcribe(data):
            entered.set()
            await release.wait()
            return 'Po'
        with patch.object(service.provider, 'transcribe_segment', transcribe):
            pending = asyncio.create_task(self.upload())
            await asyncio.wait_for(entered.wait(), 5)
            async with self.sessions() as otherdb:
                with self.assertRaises(HTTPException) as caught:
                    await service.upload_segment(otherdb, self.user, self.payload.id, 0, 0, 10, wav())
                self.assertEqual(caught.exception.detail, 'segment_busy')
            release.set()
            self.assertEqual((await pending)['transcript'], 'Po')

    async def test_summary_checkpoint_survives_failure_and_retry(self):
        with patch.object(service.provider, 'transcribe_segment', AsyncMock(return_value='Po')):
            await self.upload()
        async def fails(title, chunks, cache, checkpoint):
            await checkpoint({'cached-part': 'preserved'})
            raise ValueError('provider crash')
        with patch.object(service, 'summarize', fails):
            with self.assertRaises(HTTPException): await self.finish()
        async def succeeds(title, chunks, cache, checkpoint):
            self.assertEqual(cache, {'cached-part': 'preserved'})
            return 'Notes'
        with patch.object(service, 'summarize', succeeds):
            self.assertEqual((await self.finish())['status'], 'DONE')

    async def test_live_summary_lease_rejects_duplicate_finish(self):
        row = await service.owner(self.db, self.user, self.payload.id)
        row.lease_until = service.now()+timedelta(minutes=5)
        await self.db.commit()
        with self.assertRaises(HTTPException) as caught: await self.finish(0)
        self.assertEqual(caught.exception.detail, 'finalization_busy')

    async def test_lost_summary_lease_cannot_save_after_provider_returns(self):
        with patch.object(service.provider, 'transcribe_segment', AsyncMock(return_value='Po')):
            await self.upload()
        async def replaced(title, chunks, cache, checkpoint):
            async with self.sessions() as contender:
                row = await service.owner(contender, self.user, self.payload.id, lock=True)
                row.lease_token = uuid.uuid4()
                await contender.commit()
            return 'Stale notes'
        with patch.object(service, 'summarize', replaced):
            with self.assertRaises(HTTPException) as caught: await self.finish()
        self.assertEqual(caught.exception.detail, 'finalization_lease_lost')
        await self.db.refresh(self.user)
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(GaNote).where(
            GaNote.created_by == self.user.id)), 0)

    async def test_saved_session_create_replay_and_zero_segment_finish(self):
        result = await self.finish(0)
        self.assertEqual(result['status'], 'DONE')
        replay = await service.create_session(self.db, self.user, self.payload)
        self.assertEqual(replay, result)

    async def test_authorization_failure_during_save_is_retryable_after_rollback(self):
        with patch.object(service.provider, 'transcribe_segment', AsyncMock(return_value='Po')):
            await self.upload()
        with patch.object(service, 'summarize', AsyncMock(return_value='Notes')):
            with patch.object(service, 'build_ga_note', AsyncMock(side_effect=HTTPException(403, 'Forbidden'))):
                with self.assertRaises(HTTPException) as caught: await self.finish()
            self.assertEqual(caught.exception.status_code, 403)
            await self.db.refresh(self.user)
            result = await self.finish()
            self.assertEqual(result['status'], 'DONE')

    async def test_staff_without_department_fails_before_capture(self):
        self.other.role = UserRole.STAFF
        await self.db.commit()
        with self.assertRaises(HTTPException) as caught:
            await service.create_session(self.db, self.other,
                DesktopStart(id=uuid.uuid4(), title='No dept', consent_acknowledged=True))
        self.assertEqual(caught.exception.status_code, 400)

    async def test_quota_serializes_and_limits_unfinished_sessions(self):
        for _ in range(2):
            await service.create_session(self.db, self.user,
                DesktopStart(id=uuid.uuid4(), title='Another', consent_acknowledged=True))
        with self.assertRaises(HTTPException) as caught:
            await service.create_session(self.db, self.user,
                DesktopStart(id=uuid.uuid4(), title='Fourth', consent_acknowledged=True))
        self.assertEqual(caught.exception.status_code, 429)
