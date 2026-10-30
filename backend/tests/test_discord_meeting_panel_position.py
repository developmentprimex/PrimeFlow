"""Exercise both moving panels in one channel, including restart and send failure."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
os.environ.setdefault('DATABASE_URL','postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET','panel-position-tests-only')
from app.config import settings
from discord_meeting_control import MeetingControlPanel,panel_recorder


class Channel:
    def __init__(self):
        self.messages=[];self.counter=0;self.sends=0

    def add(self,author,recorder=None):
        self.counter+=1
        buttons=[SimpleNamespace(custom_id=f'pf:mc:{recorder}:start:-')] if recorder else []
        message=SimpleNamespace(id=self.counter,author=SimpleNamespace(id=author),
            flags=SimpleNamespace(suppress_notifications=True),
            components=[SimpleNamespace(children=buttons)] if buttons else [],embeds=[],edit=AsyncMock())
        async def delete():self.messages.remove(message)
        message.delete=AsyncMock(side_effect=delete)
        self.messages.append(message)
        return message

    def history(self,*,limit=None,after=None,oldest_first=False):
        async def iterate():
            messages=sorted((m for m in self.messages if after is None or m.id>after.id),
                key=lambda m:m.id,reverse=not oldest_first)
            for message in messages[:limit] if limit is not None else messages:
                yield message
        return iterate()

    async def send(self,**kwargs):
        assert kwargs.get('silent') is True, 'Reposted panels must suppress notifications'
        self.sends+=1
        buttons=kwargs['view'].children
        recorder=buttons[0].custom_id.split(':')[2]
        return self.add(1 if recorder=='primary' else 2,recorder)


class PositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_non_silent_panel_is_replaced_once_with_a_silent_one(self):
        old=self.channel.add(1,'primary');old.flags.suppress_notifications=False
        panel=self.panel('primary')
        await self.refresh(panel)
        old.delete.assert_awaited_once()
        self.assertEqual(self.channel.sends,1)
        await self.refresh(panel)
        self.assertEqual(self.channel.sends,1)

    def setUp(self):
        self.patch=patch.object(settings,'DISCORD_MEETING_CONTROL_CHANNEL_ID','77')
        self.patch.start();self.addCleanup(self.patch.stop)
        self.channel=Channel()

    def panel(self,recorder):
        bot=SimpleNamespace(voice_recorder=recorder,user=SimpleNamespace(id=1 if recorder=='primary' else 2))
        panel=MeetingControlPanel(SimpleNamespace(bot=bot))
        panel.channel=AsyncMock(return_value=self.channel)
        panel.state=AsyncMock(return_value={'voice_channel_id':'55' if recorder=='primary' else '66','meeting':None,'activity':[]})
        return panel

    async def refresh(self,*panels):
        for panel in panels:
            panel.checked_at=0
            await panel.refresh()

    async def test_both_panels_follow_new_messages_without_leapfrogging_each_other(self):
        old_primary=self.channel.add(1,'primary');old_ai=self.channel.add(2,'ai_agent')
        note=self.channel.add(2)
        primary,ai=self.panel('primary'),self.panel('ai_agent')
        await self.refresh(primary,ai)
        self.assertEqual([panel_recorder(m) for m in self.channel.messages],[None,'primary','ai_agent'])
        old_primary.delete.assert_awaited_once();old_ai.delete.assert_awaited_once()
        note.delete.assert_not_awaited()
        sends=self.channel.sends
        for _ in range(4):await self.refresh(primary,ai)
        self.assertEqual(self.channel.sends,sends)
        reply=self.channel.add(999)
        await self.refresh(ai,primary)
        self.assertEqual({panel_recorder(m) for m in self.channel.messages[-2:]},{'primary','ai_agent'})
        self.assertTrue(all(m.id>reply.id for m in self.channel.messages[-2:]))
        self.assertIn(note,self.channel.messages);self.assertIn(reply,self.channel.messages)

    async def test_restart_finds_existing_panels_and_removes_only_own_duplicates(self):
        old=self.channel.add(1,'primary');new=self.channel.add(1,'primary')
        other=self.channel.add(2,'ai_agent')
        for _ in range(205):self.channel.add(999)
        panel=self.panel('primary')
        await self.refresh(panel)
        self.assertEqual(sum(panel_recorder(m)=='primary' for m in self.channel.messages),1)
        self.assertIn(other,self.channel.messages);other.delete.assert_not_awaited()
        old.delete.assert_awaited_once();new.delete.assert_awaited_once()
        restarted=self.panel('primary');sends=self.channel.sends
        await self.refresh(restarted)
        self.assertEqual(self.channel.sends,sends)

    async def test_failed_replacement_keeps_old_controls_available(self):
        old=self.channel.add(1,'primary');self.channel.add(999)
        panel=self.panel('primary')
        with patch.object(self.channel,'send',AsyncMock(side_effect=RuntimeError('temporary outage'))):
            with self.assertRaises(RuntimeError):await self.refresh(panel)
        old.delete.assert_not_awaited();self.assertIn(old,self.channel.messages)
        await self.refresh(panel)
        old.delete.assert_awaited_once()
