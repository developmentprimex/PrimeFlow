import os
import uuid
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET', 'voice-tests-not-a-production-secret')

from fastapi import HTTPException
from app.models.enums import UserRole
from app.models.discord_voice_meeting import DiscordVoiceMeeting
from app.schemas.discord_voice_meeting import VoiceActor, VoiceStart
from app.services import discord_voice_meetings as service


class VoiceAccessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.uid = uuid.uuid4()
        self.user = SimpleNamespace(id=self.uid, role=UserRole.STAFF, department_id=uuid.uuid4(), is_active=True)
        self.link = SimpleNamespace(id=uuid.uuid4(), user_id=self.uid, channel_id='44', enabled=True)
        self.actor = VoiceActor(discord_user_id='12', guild_id='123', channel_id='44', voice_channel_id='55')
        self.row = DiscordVoiceMeeting(id=uuid.uuid4(), user_id=self.uid, link_id=self.link.id,
            guild_id='123', voice_channel_id='55', private_channel_id='44', status='READY',
            title='Staff', draft_text='Vendimet', partial=False, created_at=datetime.now(timezone.utc))
        self.db = SimpleNamespace(execute=AsyncMock(), add=Mock(), flush=AsyncMock(), commit=AsyncMock())
        self.db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=self.row))

    async def test_owner_access_and_other_staff_cannot_read(self):
        with patch.object(service.bridge, 'identity', AsyncMock(return_value=(self.link, self.user))):
            row, _ = await service.authorize_session(self.db, self.actor, self.row.id, operation='read')
            self.assertIs(row, self.row)
            self.user.id = uuid.uuid4()
            with self.assertRaises(HTTPException):
                await service.authorize_session(self.db, self.actor, self.row.id, operation='read')

    async def test_manager_stop_requires_same_voice_but_cannot_save_another_users_notes(self):
        self.user.id = uuid.uuid4()
        self.user.role = UserRole.MANAGER
        with patch.object(service.bridge, 'identity', AsyncMock(return_value=(self.link, self.user))):
            await service.authorize_session(self.db, self.actor, self.row.id, operation='stop')
            with self.assertRaises(HTTPException):
                await service.authorize_session(self.db, self.actor.model_copy(update={'voice_channel_id':'66'}), self.row.id, operation='stop')
            with self.assertRaises(HTTPException):
                await service.authorize_session(self.db, self.actor, self.row.id, operation='save')

    async def test_save_replay_returns_existing_note_without_new_insert(self):
        self.row.saved_note_id = uuid.uuid4()
        with patch.object(service.bridge, 'identity', AsyncMock(return_value=(self.link, self.user))):
            result = await service.save_notes(self.db, self.actor, self.row.id)
        self.assertEqual(result['saved_note_id'], str(self.row.saved_note_id))
        self.db.add.assert_not_called()

    async def test_worker_token_and_instance_must_match(self):
        self.row.capture_token_hash = service.token_hash('x'*40)
        self.row.instance_id = uuid.uuid4()
        from datetime import timedelta
        self.row.heartbeat_at = datetime.now(timezone.utc) + timedelta(seconds=10)
        service.check_worker(self.row, 'x'*40, self.row.instance_id)
        for token, instance in [('wrong', self.row.instance_id), ('x'*40, uuid.uuid4())]:
            with self.assertRaises(HTTPException):
                service.check_worker(self.row, token, instance)

    def test_invalid_actor_and_extra_fields_rejected(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            VoiceStart(**self.actor.model_dump(), request_id='99', arbitrary_url='https://bad')

