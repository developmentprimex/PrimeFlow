import uuid
from datetime import timedelta
from unittest.mock import patch
from sqlalchemy import select
from tests.test_mira_memory_model import MemoryTests
from app.config import settings
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting
from app.models.mira_memory import MiraMemoryItem as Item, MiraMemoryEvent as Event
from app.services import discord_voice_meetings as voice
from app.services import mira_memory


def op(action, item_id=None, title=None, description=None, kind=None, people=(), said='U përmend.', segments=(0,)):
    return {'action': action, 'item_id': item_id, 'title': title, 'description': description, 'kind': kind,
        'people': list(people), 'said': said, 'segments': list(segments)}


class MemoryServiceTests(MemoryTests):
    async def meeting(self, minutes_ago=0, **values):
        row = Meeting(id=uuid.uuid4(), user_id=self.uid, link_id=self.lid, department_id=self.did, guild_id='123',
            voice_channel_id='55', private_channel_id='44', request_id=uuid.uuid4().hex[:20], instance_id=uuid.uuid4(),
            capture_token_hash='h', title='1H', status='READY', partial=False, stop_authorized=True,
            started_at=voice.now()-timedelta(minutes=minutes_ago), **values)
        async with self.sessions() as db:
            db.add(row)
            await db.commit()
        return row

    async def item(self, title, *, status='OPEN', mentioned_days_ago=0, updated_days_ago=0, **values):
        moment = voice.now()
        row = Item(id=uuid.uuid4(), title=title, description=values.pop('description', 'Gjendja.'), kind='TASK',
            status=status, people=[], version=1, mention_count=values.pop('mention_count', 1), human_edited=False,
            last_mentioned_at=moment-timedelta(days=mentioned_days_ago),
            updated_at=moment-timedelta(days=updated_days_ago), **values)
        async with self.sessions() as db:
            db.add(row)
            await db.commit()
        return row

    async def apply(self, meeting, operations, versions):
        async with self.sessions() as db:
            row = await db.get(Meeting, meeting.id)
            stats = await mira_memory.apply_operations(db, row, operations, versions)
            await db.commit()
        return stats

    async def test_snapshot_includes_open_recent_closed_and_wrong_titles(self):
        await self.item('Oferta')
        await self.item('Fatura', status='CLOSED', updated_days_ago=3)
        await self.item('Raporti i vjetër', status='CLOSED', updated_days_ago=20)
        await self.item('Gabim', status='WRONG', updated_days_ago=90)
        async with self.sessions() as db:
            result = await mira_memory.snapshot(db)
        self.assertEqual({i['title'] for i in result['items']}, {'Oferta', 'Fatura'})
        self.assertEqual(result['wrong_titles'], ['Gabim'])
        self.assertEqual(result['omitted'], 0)

    async def test_snapshot_marks_quiet_after_30_days(self):
        await self.item('Printeri', mentioned_days_ago=31)
        await self.item('Oferta', mentioned_days_ago=29)
        async with self.sessions() as db:
            items = {i['title']: i for i in (await mira_memory.snapshot(db))['items']}
        self.assertTrue(items['Printeri']['quiet'])
        self.assertFalse(items['Oferta']['quiet'])

    async def test_snapshot_truncates_to_context_limit(self):
        await self.item('E vjetër', mentioned_days_ago=5, description='x'*400)
        await self.item('E re', mentioned_days_ago=1, description='y'*400)
        with patch.object(settings, 'MIRA_MEMORY_CONTEXT_CHARS', 700):
            async with self.sessions() as db:
                result = await mira_memory.snapshot(db)
        self.assertEqual([i['title'] for i in result['items']], ['E re'])
        self.assertEqual(result['omitted'], 1)

    async def test_add_mention_change_close_apply_and_record_history(self):
        meeting = await self.meeting()
        a, b, c = await self.item('A'), await self.item('B'), await self.item('C')
        versions = {str(a.id): 1, str(b.id): 1, str(c.id): 1}
        stats = await self.apply(meeting, [
            op('add', title='Oferta Albaniaplast', description='Arta e përgatit.', kind='TASK', people=['Arta'], segments=(2, 3)),
            op('mention', str(a.id), people=['Besnik']),
            op('change', str(b.id), description='Afati u shty në 30 tetor.'),
            op('close', str(c.id), said='U dërgua.')], versions)
        self.assertEqual(stats, {'applied': 4, 'rejected': 0, 'dropped': 0})
        async with self.sessions() as db:
            new = (await db.execute(select(Item).where(Item.title == 'Oferta Albaniaplast'))).scalar_one()
            self.assertEqual((new.status, new.mention_count, new.people), ('OPEN', 1, ['Arta']))
            a, b, c = await db.get(Item, a.id), await db.get(Item, b.id), await db.get(Item, c.id)
            self.assertEqual((a.mention_count, a.version, a.people), (2, 1, ['Besnik']))
            self.assertEqual((b.description, b.version), ('Afati u shty në 30 tetor.', 2))
            self.assertEqual((c.status, c.version), ('CLOSED', 2))
            events = (await db.execute(select(Event).where(Event.meeting_id == meeting.id))).scalars().all()
            self.assertEqual(sorted(e.kind for e in events), ['CHANGE', 'CLOSE', 'MENTION', 'MENTION'])
            self.assertEqual(next(e for e in events if e.item_id == new.id).refs, [2, 3])

    async def test_unknown_ids_and_incomplete_operations_are_rejected(self):
        meeting = await self.meeting()
        a = await self.item('A')
        stats = await self.apply(meeting, [
            op('mention', str(uuid.uuid4())),
            op('add', description='Pa titull.', kind='TASK'),
            op('add', title='Lloj i gabuar', description='x', kind='OTHER'),
            op('mention', str(a.id))], {str(a.id): 1})
        self.assertEqual(stats, {'applied': 1, 'rejected': 3, 'dropped': 0})

    async def test_version_mismatch_keeps_mention_drops_change(self):
        meeting = await self.meeting()
        a = await self.item('A', description='Nga njeriu.')
        async with self.sessions() as db:
            row = await db.get(Item, a.id)
            row.version = 2
            await db.commit()
        stats = await self.apply(meeting, [op('change', str(a.id), description='Nga Mira.')], {str(a.id): 1})
        self.assertEqual(stats, {'applied': 0, 'rejected': 0, 'dropped': 1})
        async with self.sessions() as db:
            row = await db.get(Item, a.id)
            self.assertEqual((row.description, row.mention_count), ('Nga njeriu.', 2))
            kinds = (await db.execute(select(Event.kind).where(Event.item_id == a.id))).scalars().all()
            self.assertEqual(kinds, ['MENTION'])

    async def test_wrong_title_is_not_recreated(self):
        meeting = await self.meeting()
        await self.item('Printeri i ri', status='WRONG')
        stats = await self.apply(meeting, [op('add', title=' printeri i RI ', description='x', kind='TOPIC')], {})
        self.assertEqual(stats['rejected'], 1)
        async with self.sessions() as db:
            self.assertEqual(len((await db.execute(select(Item))).scalars().all()), 1)
