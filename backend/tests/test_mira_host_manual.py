import os
import unittest
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET', 'mira-manual-tests-not-a-production-secret')

from fastapi import HTTPException
from app.api.routers import mira_host_bot as api
from app.models.enums import UserRole


class ManualStartTests(unittest.IsolatedAsyncioTestCase):
    async def test_staff_in_shared_control_can_start_without_enabling_schedule(self):
        meeting=SimpleNamespace(id=uuid.uuid4())
        user=SimpleNamespace(id=uuid.uuid4(),role=UserRole.STAFF,is_active=True)
        row=SimpleNamespace(enabled_until=None,target_minutes_per_person=4)
        db=SimpleNamespace(commit=AsyncMock())
        from app.services import discord_meeting_control as control
        with patch.object(api.settings,'DISCORD_GUILD_ID','123'), \
             patch.object(api.settings,'DISCORD_MEETING_CONTROL_CHANNEL_ID','77'), \
             patch.object(api.settings,'MIRA_HOST_ENABLED',True), \
             patch.object(api.settings,'MIRA_HOST_BOT_TOKEN','host-test'), \
             patch.object(api.settings,'MIRA_HOST_OPENAI_API_KEY','host-test-key'), \
             patch.object(control,'control_identity',AsyncMock(return_value=(SimpleNamespace(),user))) as identify, \
             patch.object(api.host,'get_settings',AsyncMock(return_value=row)), \
             patch.object(api.host,'start_meeting',AsyncMock(return_value=meeting)), \
             patch.object(api.host,'realtime_session',AsyncMock(return_value={'client_secret':'synthetic','model':'test'})), \
             patch.object(api.host,'meeting_row',return_value={'id':str(meeting.id)}):
            result=await api.start(api.Start(slot='14:20',discord_user_id='11',guild_id='123',channel_id='77'),db)
        self.assertEqual(result['meeting']['id'],str(meeting.id))
        self.assertIsNone(row.enabled_until)
        identify.assert_awaited_once()
        self.assertEqual(identify.await_args.args[1].channel_id,'77')

    async def test_different_staff_member_can_disable_from_shared_control(self):
        from app.services import discord_meeting_control as control
        user=SimpleNamespace(id=uuid.uuid4(),role=UserRole.STAFF,is_active=True)
        row=SimpleNamespace(enabled_until=datetime.now(ZoneInfo('Europe/Budapest')))
        db=SimpleNamespace(commit=AsyncMock())
        with patch.object(api.settings,'DISCORD_GUILD_ID','123'), \
             patch.object(api.settings,'DISCORD_MEETING_CONTROL_CHANNEL_ID','77'), \
             patch.object(control,'control_identity',AsyncMock(return_value=(SimpleNamespace(),user))), \
             patch.object(api.host,'get_settings',AsyncMock(return_value=row)), \
             patch.object(api.host,'settings_view',return_value={'enabled':False}):
            result=await api.disable(api.Caller(discord_user_id='22',guild_id='123',channel_id='77'),db)
        self.assertIsNone(row.enabled_until)
        self.assertEqual(result,{'enabled':False})
        db.commit.assert_awaited_once()

    async def test_wrong_channel_guild_and_unlinked_users_cannot_bypass_authorization(self):
        from app.services import discord_meeting_control as control
        with patch.object(api.settings,'DISCORD_GUILD_ID','123'),patch.object(api.settings,'DISCORD_MEETING_CONTROL_CHANNEL_ID','77'), \
             patch.object(api.host,'user_for_discord',AsyncMock(return_value=SimpleNamespace(role=UserRole.STAFF))), \
             patch.object(control,'control_identity',AsyncMock(side_effect=HTTPException(403,'Not linked'))):
            for context in ({'guild_id':'123','channel_id':'88'},{'guild_id':'999','channel_id':'77'},
                            {'guild_id':'123','channel_id':'77'},{'channel_id':'77'}):
                with self.subTest(context=context),self.assertRaises(HTTPException) as error:
                    await api.command_user(SimpleNamespace(),api.Caller(discord_user_id='11',**context))
                self.assertEqual(error.exception.status_code,403)

    async def test_linked_manager_can_start_now_without_enabling_daily_schedule(self):
        at = datetime(2026, 10, 29, 9, 15, tzinfo=ZoneInfo('Europe/Budapest'))
        meeting = SimpleNamespace(id=uuid.uuid4())
        row = SimpleNamespace(enabled_until=None, target_minutes_per_person=4)
        db = SimpleNamespace(commit=AsyncMock())
        manager = SimpleNamespace(role=UserRole.MANAGER)
        with patch.object(api.host, 'user_for_discord', AsyncMock(return_value=manager)), \
             patch.object(api.host, 'get_settings', AsyncMock(return_value=row)), \
             patch.object(api.host, 'start_meeting', AsyncMock(return_value=meeting)), \
             patch.object(api.host, 'realtime_session', AsyncMock(return_value={'client_secret': 'ek', 'model': 'm'})), \
             patch.object(api.host, 'meeting_row', return_value={'id': str(meeting.id)}), \
             patch.object(api.host, 'now', return_value=at), \
             patch.object(api.settings, 'MIRA_HOST_ENABLED', True), \
             patch.object(api.settings, 'MIRA_HOST_OPENAI_API_KEY', 'host-test'), \
             patch.object(api.settings, 'MIRA_HOST_BOT_TOKEN', 'test-token'):
            result = await api.start(api.Start(slot='11:00', discord_user_id='11'), db)
        self.assertEqual(result['starts_at'], at.isoformat())
        self.assertIsNone(row.enabled_until)
        self.assertEqual(result['meeting']['id'], str(meeting.id))

    async def test_staff_cannot_use_manual_start_to_bypass_manager_permission(self):
        db = SimpleNamespace(commit=AsyncMock())
        with patch.object(api.host, 'user_for_discord', AsyncMock(return_value=SimpleNamespace(role=UserRole.STAFF))):
            with self.assertRaises(HTTPException) as caught:
                await api.start(api.Start(slot='11:00', discord_user_id='11'), db)
        self.assertEqual(caught.exception.status_code, 403)

    async def test_scheduled_start_still_requires_daily_enablement(self):
        db = SimpleNamespace(commit=AsyncMock())
        with patch.object(api.host, 'get_settings', AsyncMock(return_value=SimpleNamespace(enabled_until=None))):
            with self.assertRaises(HTTPException) as caught:
                await api.start(api.Start(slot='11:00'), db)
        self.assertEqual(caught.exception.status_code, 409)
