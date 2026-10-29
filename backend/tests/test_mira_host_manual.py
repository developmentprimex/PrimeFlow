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
