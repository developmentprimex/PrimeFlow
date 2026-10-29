import os
import uuid
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
os.environ.setdefault('DATABASE_URL','postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET','control-test-secret')
import discord
from fastapi import HTTPException
from app.config import settings
from app.schemas.discord_voice_meeting import VoiceActor, VoiceStart, ControlScope
from app.services import discord_meeting_control as service
from app.services import discord_voice_meetings as meetings
from discord_voice_meetings import MeetingCaptureCoordinator
from discord_meeting_control import panel_content
from tests.test_discord_voice_model import PostgresMeetingTests


class PanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_actions_and_notes_are_visible_to_everyone_in_control_channel(self):
        from discord_meeting_control import MeetingControlPanel
        sid=str(uuid.uuid4())
        for action in ('start','stop','view','save'):
            with self.subTest(action=action),patch.object(settings,'DISCORD_GUILD_ID','123'), \
                patch.object(settings,'DISCORD_MEETING_CONTROL_CHANNEL_ID','77'):
                bot=SimpleNamespace(voice_recorder='ai_agent',bridge=AsyncMock(return_value={
                    'id':sid,'status':'READY','draft_text':'Shënimet për të gjithë'}))
                coordinator=SimpleNamespace(bot=bot,stop=AsyncMock())
                panel=MeetingControlPanel(coordinator)
                interaction=SimpleNamespace(guild_id=123,channel_id=77,user=SimpleNamespace(id=12,voice=None,bot=False),
                    channel=SimpleNamespace(permissions_for=lambda _:SimpleNamespace(view_channel=True)),
                    data={'custom_id':f'pf:mc:ai_agent:{action}:{sid}'},
                    response=SimpleNamespace(defer=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
                with patch.object(panel,'refresh',AsyncMock()),patch.object(panel,'start',AsyncMock()):
                    await panel.handle(interaction)
                interaction.response.defer.assert_awaited_once_with(thinking=True,ephemeral=False)
                if action in ('view','save'):
                    self.assertFalse(interaction.followup.send.await_args.kwargs['ephemeral'])

    async def test_result_buttons_share_only_in_control_and_keep_personal_notes_private(self):
        from discord_voice_meetings import handle_meeting_interaction
        sid=str(uuid.uuid4())
        for shared in (True,False):
            with self.subTest(shared=shared),patch.object(settings,'DISCORD_GUILD_ID','123'), \
                patch.object(settings,'DISCORD_MEETING_CONTROL_CHANNEL_ID','77'):
                bot=SimpleNamespace(private_channel=AsyncMock(),bridge=AsyncMock(return_value={
                    'id':sid,'status':'READY','draft_text':'Takimi'}))
                interaction=SimpleNamespace(guild_id=123,channel_id=77 if shared else 44,
                    user=SimpleNamespace(id=12,voice=None,bot=False),
                    channel=SimpleNamespace(permissions_for=lambda _:SimpleNamespace(view_channel=True)),
                    data={'custom_id':f'pf:vm:view:{sid}'},
                    response=SimpleNamespace(defer=AsyncMock()),followup=SimpleNamespace(send=AsyncMock()))
                await handle_meeting_interaction(bot,interaction)
                interaction.response.defer.assert_awaited_once_with(thinking=True,ephemeral=not shared)
                self.assertEqual(interaction.followup.send.await_args.kwargs['ephemeral'],not shared)

    async def test_start_from_text_without_voice_routes_each_bot_to_its_own_voice(self):
        for recorder, voice_id in [('primary','55'),('ai_agent','66')]:
            with self.subTest(recorder=recorder), patch.object(settings,'DISCORD_GUILD_ID','123'), \
                patch.object(settings,'DISCORD_MEETING_CONTROL_CHANNEL_ID','77'), \
                patch.object(settings,'DISCORD_1H_VOICE_CHANNEL_ID','55'), \
                patch.object(settings,'DISCORD_AI_AGENT_VOICE_CHANNEL_ID','66'):
                bot=SimpleNamespace(voice_recorder=recorder)
                from discord_ai_agent_bot import AIAgentCapture
                coordinator=(AIAgentCapture if recorder=='ai_agent' else MeetingCaptureCoordinator)(bot)
                channel=Mock(spec=discord.VoiceChannel);channel.id=int(voice_id)
                interaction=SimpleNamespace(guild_id=123,channel_id=77,id=999,
                    user=SimpleNamespace(id=12,voice=None,bot=False),
                    channel=SimpleNamespace(permissions_for=lambda _:SimpleNamespace(view_channel=True)),
                    guild=SimpleNamespace(get_channel=Mock(return_value=channel)),
                    followup=SimpleNamespace(send=AsyncMock()))
                with patch.object(coordinator,'begin',AsyncMock()) as begin, \
                     patch.object(coordinator.panel,'refresh',AsyncMock()):
                    await coordinator.start(interaction,None,None)
                self.assertEqual(begin.await_args.kwargs['actor']['voice_channel_id'],voice_id)
                self.assertEqual(begin.await_args.kwargs['actor']['channel_id'],'77')

    async def test_second_person_stops_shared_recording_without_private_or_voice_membership(self):
        bot=SimpleNamespace(bridge=AsyncMock(),private_channel=AsyncMock())
        c=MeetingCaptureCoordinator(bot);c.active={'id':'session','finishing':False}
        i=SimpleNamespace(guild_id=123,channel_id=77,user=SimpleNamespace(id=13,voice=None,bot=False),
            channel=SimpleNamespace(permissions_for=lambda _:SimpleNamespace(view_channel=True)),followup=SimpleNamespace(send=AsyncMock()))
        with patch.object(settings,'DISCORD_GUILD_ID','123'),patch.object(settings,'DISCORD_MEETING_CONTROL_CHANNEL_ID','77'), \
             patch.object(c,'end',AsyncMock()) as end:
            await c.stop(i,'session')
        bot.private_channel.assert_not_awaited()
        self.assertIsNone(bot.bridge.await_args.args[1]['voice_channel_id'])
        end.assert_awaited_once()
        with self.assertRaises(ValueError):await c.stop(i,'old-session')

    async def test_other_channels_cannot_use_panel_start(self):
        c=MeetingCaptureCoordinator(SimpleNamespace())
        i=SimpleNamespace(channel_id=88,guild_id=123,user=SimpleNamespace(bot=False))
        with patch.object(settings,'DISCORD_GUILD_ID','123'),patch.object(settings,'DISCORD_MEETING_CONTROL_CHANNEL_ID','77'), \
             patch.object(c,'begin',AsyncMock()) as begin:
            with self.assertRaises(ValueError):await c.panel.start(i)
        begin.assert_not_awaited()

    def test_panel_buttons_are_bound_to_session_and_reflect_saved_state(self):
        sid=str(uuid.uuid4())
        for status in ('LISTENING','FINALIZING','READY','SAVED'):
            with self.subTest(status=status):
                embed,view=panel_content('ai_agent',{'voice_channel_id':'66','meeting':{'id':sid,'status':status},'activity':[]})
                items={button.custom_id.split(':')[3]:button for button in view.children if button.custom_id}
                self.assertEqual(items['save'].disabled,status!='READY')
                self.assertEqual(items['stop'].disabled,status!='LISTENING')
                self.assertTrue(items['save'].custom_id.endswith(sid))
                self.assertIn('AI Agent',embed.description)


class SharedDatabaseTests(PostgresMeetingTests):
    async def test_different_staff_start_stop_and_save_same_shared_meeting_once(self):
        import asyncio
        from sqlalchemy import select,func
        from app.models.audit_log import AuditLog
        from app.models.user import User
        from app.models.department import Department
        from app.models.discord_assistant import DiscordLink
        from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting
        from app.models.ga_note import GaNote
        from app.models.enums import UserRole
        other=uuid.uuid4();department=uuid.uuid4()
        async with self.sessions() as db:
            db.add(Department(id=department,name='Other',code='OTHER'));await db.flush()
            db.add(User(id=other,username='other',full_name='Other Staff',email='other@example.test',password_hash='test',role=UserRole.STAFF,department_id=department));await db.flush()
            db.add(DiscordLink(user_id=other,discord_user_id='13',guild_id='123',channel_id='45'));await db.commit()
        patches=[patch.object(settings,name,value) for name,value in {
            'DISCORD_GUILD_ID':'123','DISCORD_MEETING_CONTROL_CHANNEL_ID':'77',
            'DISCORD_1H_VOICE_CHANNEL_ID':'55','DISCORD_AI_AGENT_VOICE_CHANNEL_ID':'66',
            'DISCORD_MEETING_NOTES_ENABLED':True,'OPENAI_API_KEY':'test'}.items()]
        for p in patches:p.start()
        self.addCleanup(lambda:[p.stop() for p in reversed(patches)])
        actor=VoiceActor(discord_user_id='13',guild_id='123',channel_id='77')
        async with self.sessions() as db:
            row=await meetings.start_session(db,VoiceStart(discord_user_id='12',guild_id='123',channel_id='77',
                voice_channel_id='66',recorder='ai_agent',request_id='991',instance_id=uuid.uuid4(),capture_token='t'*40,title='AI Agent shared'))
        sid=uuid.UUID(row['id'])
        async with self.sessions() as db:
            await meetings.authorize_stop(db,actor,sid)
        async with self.sessions() as db:
            row=await db.get(Meeting,sid);row.status='READY';row.draft_text='Vendimet e takimit';await db.commit()
        async def save():
            async with self.sessions() as db:return await meetings.save_notes(db,actor,sid)
        a,b=await asyncio.gather(save(),save())
        self.assertEqual(a['saved_note_id'],b['saved_note_id'])
        async with self.sessions() as db:
            self.assertEqual((await db.execute(select(func.count()).select_from(GaNote))).scalar_one(),1)
            note=await db.get(GaNote,uuid.UUID(a['saved_note_id']))
            self.assertEqual(note.department_id,self.did)
            events=(await db.execute(select(AuditLog).order_by(AuditLog.created_at))).scalars().all()
            self.assertEqual([e.action for e in events],['CONTROL_START','CONTROL_STOP','CONTROL_SAVE'])
            self.assertEqual(events[-1].actor_user_id,other)
            self.assertEqual(events[0].actor_user_id,self.uid)
            data=await service.panel_state(db,ControlScope(guild_id='123',channel_id='77'),'ai_agent')
            self.assertEqual(data['meeting']['status'],'SAVED')
            self.assertEqual(len(data['activity']),3)
        for bad in [actor.model_copy(update={'channel_id':'88'}),actor.model_copy(update={'guild_id':'999'}),actor.model_copy(update={'discord_user_id':'14'})]:
            async with self.sessions() as db:
                with self.assertRaises(HTTPException):await meetings.save_notes(db,bad,sid)
        async with self.sessions() as db:
            with self.assertRaises(HTTPException):
                await meetings.start_session(db,VoiceStart(discord_user_id='12',guild_id='123',channel_id='77',
                    voice_channel_id='55',recorder='ai_agent',request_id='992',instance_id=uuid.uuid4(),capture_token='t'*40,title='Wrong channel'))

    async def test_panel_never_reveals_personal_notes_and_cannot_save_them(self):
        from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting
        with patch.object(settings,'DISCORD_GUILD_ID','123'),patch.object(settings,'DISCORD_MEETING_CONTROL_CHANNEL_ID','77'), \
             patch.object(settings,'DISCORD_1H_VOICE_CHANNEL_ID','55'):
            sid=uuid.uuid4()
            async with self.sessions() as db:
                db.add(Meeting(id=sid,link_id=self.lid,user_id=self.uid,department_id=self.did,guild_id='123',
                    recorder='primary',voice_channel_id='55',private_channel_id='44',request_id='990',
                    instance_id=uuid.uuid4(),capture_token_hash='x'*64,title='Personal',status='LISTENING',draft_text='Private note'))
                await db.commit()
            async with self.sessions() as db:
                state=await service.panel_state(db,ControlScope(guild_id='123',channel_id='77'),'primary')
                self.assertNotIn('draft_text',state['meeting'])
                self.assertTrue(state['meeting']['private'])
                with self.assertRaises(HTTPException):await meetings.save_notes(db,VoiceActor(discord_user_id='12',guild_id='123',channel_id='77'),sid)

    async def test_each_recorder_claims_only_its_own_ready_or_failed_notes(self):
        import asyncio
        from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting
        ids={}
        async with self.sessions() as db:
            for recorder,channel,status in [('primary','55','READY'),('ai_agent','66','FAILED')]:
                sid=uuid.uuid4();ids[recorder]=str(sid)
                db.add(Meeting(id=sid,link_id=self.lid,user_id=self.uid,department_id=self.did,guild_id='123',
                    recorder=recorder,voice_channel_id=channel,private_channel_id='44',request_id=str(800+len(ids)),
                    instance_id=uuid.uuid4(),capture_token_hash='x'*64,title=recorder,status=status))
            await db.commit()
        async def claim(recorder):
            async with self.sessions() as db:return await meetings.claim_deliveries(db,recorder=recorder)
        with patch.object(settings,'DISCORD_GUILD_ID','123'),patch.object(settings,'DISCORD_AI_AGENT_VOICE_CHANNEL_ID','66'):
            first,second=await asyncio.gather(claim('primary'),claim('ai_agent'))
            self.assertEqual([(job['id'],job['recorder']) for job in first['jobs']],[(ids['primary'],'primary')])
            self.assertEqual([(job['id'],job['recorder']) for job in second['jobs']],[(ids['ai_agent'],'ai_agent')])
            self.assertEqual((await claim('primary'))['jobs'],[])
            self.assertEqual((await claim('ai_agent'))['jobs'],[])
