import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/test')
os.environ.setdefault('JWT_SECRET', 'mira-note-groups-test-secret')
from app.services import mira_note_groups as groups


class MiraNoteGroupsTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_titles_and_host_notes_keep_distinct_groups(self):
        for note, expected in [({'kind':'1H','title':'Summary'}, '1H'),
                ({'source':'DISCORD','title':'1H 820/10/11 · 29.10.2026'}, '1H'),
                ({'source':'DISCORD','title':'AI AGENT 08-05 & 12-00'}, 'AI_AGENT'),
                ({'source':'DESKTOP','title':'AI Agent interview'}, 'OTHER'),
                ({'source':'DISCORD','title':'Internal meeting'}, 'OTHER')]:
            self.assertEqual(groups.note_group(note), expected)

    async def test_channel_identity_classifies_custom_titles_and_preserves_note_actions(self):
        note_id = str(uuid.uuid4())
        row = {'id': note_id, 'note_id': note_id, 'kind':'PX_NOTE', 'source':'DISCORD',
            'title':'Takimi me ekipin', 'content':'Notes', 'shared_to_px':True}
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock(all=Mock(return_value=[(uuid.UUID(note_id),'66')]))))
        with patch.object(groups.mira_host, 'mira_notes', AsyncMock(return_value=[row])) as listed, \
             patch.object(groups.settings, 'DISCORD_AI_AGENT_VOICE_CHANNEL_ID', '66'):
            result = await groups.grouped_notes(db, 100, 200)
        listed.assert_awaited_once_with(db, 100, 200)
        self.assertEqual(result, [{**row, 'meeting_group':'AI_AGENT'}])
        self.assertNotIn('meeting_group', row)
