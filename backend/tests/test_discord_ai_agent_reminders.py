import os
import unittest
import uuid
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
from zoneinfo import ZoneInfo
os.environ.setdefault('DATABASE_URL','postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET','reminder-tests-only')
from app.services import discord_ai_agent_reminders as service
from tests.test_discord_voice_model import PostgresMeetingTests

CONFIG={'enabled':True,'times':['08:05','12:00','14:10'],'timezone':'Europe/Budapest',
    'guild_id':'123','voice_channel_id':'66','user_ids':[]}

class InvitationTests(unittest.IsolatedAsyncioTestCase):
    def test_only_exact_weekday_windows_in_local_time(self):
        tz=ZoneInfo(CONFIG['timezone'])
        for slot in CONFIG['times']:
            hour,minute=map(int,slot.split(':'));at=datetime(2026,10,29,hour,minute,tzinfo=tz)
            self.assertTrue(service.due(at.astimezone(timezone.utc),slot,CONFIG))
            self.assertTrue(service.due(at+timedelta(minutes=4,seconds=59),slot,CONFIG))
            self.assertFalse(service.due(at-timedelta(seconds=1),slot,CONFIG))
            self.assertFalse(service.due(at+timedelta(minutes=5),slot,CONFIG))
            self.assertFalse(service.due(at.replace(day=31),slot,CONFIG))
        self.assertFalse(service.due(at,'16:10',CONFIG))
        self.assertFalse(service.due(at,slot,{**CONFIG,'enabled':False}))
        # The same local 08:05 follows DST rather than a fixed UTC time.
        self.assertTrue(service.due(datetime(2026,7,1,6,5,tzinfo=timezone.utc),'08:05',CONFIG))
        self.assertFalse(service.due(datetime(2026,7,1,7,5,tzinfo=timezone.utc),'08:05',CONFIG))

    def job(self):
        return {'id':str(uuid.uuid4()),'day':'2026-10-29','slot':'14:10','discord_user_id':'12',
            'guild_id':'123','channel_id':'44','voice_channel_id':'66'}

    async def test_invitation_mentions_only_recipient_and_retries_do_not_duplicate(self):
        job=self.job();payload=service.invitation(job)
        self.assertEqual(payload['allowed_mentions']['users'],['12'])
        self.assertEqual(payload['components'][0]['components'][0]['url'],'https://discord.com/channels/123/66')
        self.assertEqual(payload['nonce'],service.invitation(job)['nonce'])
        marker=payload['embeds'][0]['footer']['text']
        response=Mock();response.json.return_value=[{'id':'999','author':{'id':'777'},'embeds':[{'footer':{'text':marker}}]}]
        client=SimpleNamespace(get=AsyncMock(return_value=response),post=AsyncMock())
        self.assertEqual(await service.deliver(client,job,bot_id='777'),'999')
        client.post.assert_not_awaited()
        response.json.return_value=[]
        sent=Mock();sent.json.return_value={'id':'1000'};client.post.return_value=sent
        self.assertEqual(await service.deliver(client,job,bot_id='777'),'1000')
        self.assertEqual(client.post.await_args.kwargs['json']['allowed_mentions']['parse'],[])


class ReminderDatabaseTests(PostgresMeetingTests):
    async def test_claim_is_recipient_scoped_durable_and_one_per_slot(self):
        import asyncio
        from sqlalchemy import select
        from app.models.discord_assistant import DiscordReminder,DiscordLink
        from app.models.user import User
        async with self.engine.begin() as c:
            await c.run_sync(lambda sync:DiscordReminder.__table__.create(sync))
        other,unrelated=uuid.uuid4(),uuid.uuid4()
        async with self.sessions() as db:
            for uid,discord_id in [(other,'13'),(unrelated,'14')]:
                db.add(User(id=uid,username='staff'+discord_id,full_name='Staff '+discord_id,email=discord_id+'@example.test',password_hash='test',department_id=self.did))
            await db.flush()
            for uid,discord_id,channel in [(other,'13','45'),(unrelated,'14','46')]:
                db.add(DiscordLink(user_id=uid,discord_user_id=discord_id,guild_id='123',channel_id=channel))
            await db.commit()
        config={**CONFIG,'user_ids':[str(self.uid),str(other)]}
        at=datetime(2026,10,29,13,10,tzinfo=timezone.utc)
        async def claim(slot='14:10',when=at):
            async with self.sessions() as db:return await service.claim(db,when,slot,config)
        a,b=await asyncio.gather(claim(),claim());jobs=a+b
        self.assertEqual(len(jobs),2)
        self.assertEqual({job['discord_user_id'] for job in jobs},{'12','13'})
        self.assertEqual(await claim(),[])
        for index,job in enumerate(jobs):
            async with self.sessions() as db:
                self.assertTrue(await service.acknowledge(db,job,str(1000+index),at))
        self.assertEqual(await claim(when=at+timedelta(minutes=2)),[])
        self.assertEqual(len(await claim(when=at+timedelta(days=1))),2)
        later=await claim(slot='12:00',when=at.replace(hour=11,minute=0))
        self.assertEqual(len(later),2)
        async with self.sessions() as db:
            await service.release(db,later[0],at.replace(hour=11,minute=0))
        retried=await claim(slot='12:00',when=at.replace(hour=11,minute=0,second=2))
        self.assertEqual([job['id'] for job in retried],[later[0]['id']])
