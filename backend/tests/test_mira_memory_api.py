import uuid
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from tests.test_mira_memory_service import MemoryServiceTests
from app.models.enums import UserRole
from app.models.user import User
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting
from app.models.mira_memory import MiraMemoryItem as Item, MiraMemoryEvent as Event
from app.schemas.mira_memory import MemoryEdit, MemoryStatusChange
from app.services import discord_voice_meetings as voice
from app.services import mira_memory


class MemoryApiTests(MemoryServiceTests):
    # The service tests already run in their own module.
    test_snapshot_includes_open_recent_closed_and_wrong_titles = None
    test_snapshot_marks_quiet_after_30_days = None
    test_snapshot_truncates_to_context_limit = None
    test_add_mention_change_close_apply_and_record_history = None
    test_unknown_ids_and_incomplete_operations_are_rejected = None
    test_version_mismatch_keeps_mention_drops_change = None
    test_wrong_title_is_not_recreated = None

    async def user(self, role=UserRole.STAFF):
        async with self.sessions() as db:
            return await db.get(User, self.uid) if role == UserRole.STAFF else await self.make_user(db, role)

    async def make_user(self, db, role):
        row = User(id=uuid.uuid4(), username='mira_admin_' + uuid.uuid4().hex[:6], full_name='Admin Test',
            email=uuid.uuid4().hex[:8] + '@example.test', password_hash='not-a-password', department_id=self.did, role=role)
        db.add(row)
        await db.commit()
        return row

    async def test_list_filters_and_counts(self):
        await self.item('E hapur', mentioned_days_ago=1)
        await self.item('E heshtur', mentioned_days_ago=40)
        await self.item('E mbyllur', status='CLOSED')
        await self.item('E gabuar', status='WRONG')
        await self.meeting(memory_status='FAILED')
        async with self.sessions() as db:
            opened = await mira_memory.list_items(db, 'open')
            closed = await mira_memory.list_items(db, 'closed')
            everything = await mira_memory.list_items(db, 'all')
        self.assertEqual([i['title'] for i in opened['items']], ['E hapur', 'E heshtur'])
        self.assertEqual([i['quiet'] for i in opened['items']], [False, True])
        self.assertEqual({i['title'] for i in closed['items']}, {'E mbyllur', 'E gabuar'})
        self.assertEqual(len(everything['items']), 4)
        self.assertEqual(opened['counts'], {'open': 2, 'closed': 2})
        self.assertEqual(opened['failed_meetings'], 1)

    async def test_detail_returns_events_with_sources(self):
        meeting = await self.meeting(title='1H 10:58')
        item = await self.item('Oferta')
        await self.apply(meeting, [{'action': 'mention', 'item_id': str(item.id), 'title': None, 'description': None,
            'kind': None, 'people': [], 'said': 'Arta pret çmimet.', 'segments': [1]}], {str(item.id): 1})
        async with self.sessions() as db:
            await mira_memory.edit_item(db, await db.get(User, self.uid), item.id, MemoryEdit(version=1, title='Oferta', description='E korrigjuar.'))
            detail = await mira_memory.get_item(db, item.id)
        self.assertEqual([e['kind'] for e in detail['events']], ['EDIT', 'MENTION'])
        self.assertEqual(detail['events'][0]['user_name'], 'Mira Test')
        self.assertEqual((detail['events'][1]['meeting_title'], detail['events'][1]['text']), ('1H 10:58', 'Arta pret çmimet.'))
        with self.assertRaises(HTTPException) as missing:
            async with self.sessions() as db:
                await mira_memory.get_item(db, uuid.uuid4())
        self.assertEqual(missing.exception.status_code, 404)

    async def test_edit_marks_human_and_records_event(self):
        item = await self.item('Oferta')
        async with self.sessions() as db:
            detail = await mira_memory.edit_item(db, await db.get(User, self.uid), item.id,
                MemoryEdit(version=1, title='Oferta Albaniaplast', description='Arta, deri të premten.'))
        self.assertEqual((detail['title'], detail['description'], detail['version'], detail['human_edited']),
            ('Oferta Albaniaplast', 'Arta, deri të premten.', 2, True))
        async with self.sessions() as db:
            row = await db.get(Item, item.id)
            self.assertEqual(row.updated_by_user_id, self.uid)

    async def test_close_reopen_wrong_record_events(self):
        item = await self.item('Printeri')
        async with self.sessions() as db:
            user = await db.get(User, self.uid)
            closed = await mira_memory.set_status(db, user, item.id, MemoryStatusChange(version=1, action='close'))
            reopened = await mira_memory.set_status(db, user, item.id, MemoryStatusChange(version=2, action='reopen'))
            wrong = await mira_memory.set_status(db, user, item.id, MemoryStatusChange(version=3, action='wrong'))
        self.assertEqual((closed['status'], reopened['status'], wrong['status']), ('CLOSED', 'OPEN', 'WRONG'))
        async with self.sessions() as db:
            kinds = (await db.execute(select(Event.kind).where(Event.item_id == item.id).order_by(Event.created_at))).scalars().all()
        self.assertEqual(kinds, ['CLOSE', 'REOPEN', 'WRONG'])

    async def test_stale_version_is_rejected_with_409(self):
        item = await self.item('Oferta')
        async with self.sessions() as db:
            user = await db.get(User, self.uid)
            await mira_memory.edit_item(db, user, item.id, MemoryEdit(version=1, title='A', description='B'))
        for change in (lambda db, user: mira_memory.edit_item(db, user, item.id, MemoryEdit(version=1, title='C', description='D')),
                lambda db, user: mira_memory.set_status(db, user, item.id, MemoryStatusChange(version=1, action='close'))):
            with self.assertRaises(HTTPException) as conflict:
                async with self.sessions() as db:
                    await change(db, await db.get(User, self.uid))
            self.assertEqual((conflict.exception.status_code, conflict.exception.detail),
                (409, 'Pika është ndryshuar ndërkohë. U rifreskua.'))
        async with self.sessions() as db:
            self.assertEqual((await db.get(Item, item.id)).title, 'A')

    async def test_retry_failed_requires_admin_or_manager(self):
        sid = (await self.meeting(memory_status='FAILED', memory_attempts=5, memory_error='x')).id
        async with self.sessions() as db:
            with self.assertRaises(HTTPException) as denied:
                await mira_memory.retry_failed(db, await db.get(User, self.uid))
            self.assertEqual(denied.exception.status_code, 403)
            admin = await self.make_user(db, UserRole.ADMIN)
            self.assertEqual(await mira_memory.retry_failed(db, admin), {'retried': 1})
        async with self.sessions() as db:
            row = await db.get(Meeting, sid)
            self.assertEqual((row.memory_status, row.memory_attempts, row.memory_error), ('PENDING', 0, None))

    async def test_router_requires_authentication(self):
        import httpx
        from fastapi import FastAPI
        from app.api.routers.mira_memory import router
        app = FastAPI()
        app.include_router(router, prefix='/api/mira-memory')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.get('/api/mira-memory/items')
        self.assertEqual(response.status_code, 401)
