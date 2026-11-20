import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from fastapi import HTTPException

from tests.test_mira_memory_model import MemoryTests
from app.models.discord_assistant import DiscordLink
from app.models.discord_voice_meeting import DiscordVoiceMeeting as Meeting, DiscordVoiceSegment as Segment
from app.models.mira_memory import MiraMemoryEvent, MiraMemoryItem
from app.schemas.discord_voice_meeting import MeetingQuestion
from app.services import mira_meeting_search as search
import discord_mira_ask


class MeetingSearchTests(MemoryTests):
    async def sample(self, *, guild='123', speaker='GA', text='Modeco: kontrolloni fotografitë e PrimEx.',
                     date=datetime(2026, 11, 19, 9, tzinfo=timezone.utc), status='READY'):
        sid, segment_id = uuid.uuid4(), uuid.uuid4()
        async with self.sessions() as db:
            db.add(Meeting(id=sid, user_id=self.uid, link_id=self.lid, guild_id=guild, voice_channel_id='55',
                private_channel_id='44', request_id=sid.hex, instance_id=uuid.uuid4(), capture_token_hash='test',
                title='Takimi i ekipit', status=status, started_at=date))
            await db.flush()
            db.add(Segment(id=segment_id, session_id=sid, sequence=0, speaker_id='32', speaker_name=speaker,
                start_ms=316000, end_ms=330000, content_hash='hash', status='DONE', transcript=text))
            await db.commit()
        return sid, segment_id

    async def test_search_date_speaker_project_alias_and_citations(self):
        sid, segment_id = await self.sample()
        await self.sample(guild='999', text='Modeco PrimEx. Takim jashtë serverit.')
        await self.sample(status='LISTENING', text='Modeco PrimEx. Takim në vazhdim.')
        await self.sample(speaker='Arta', text='Modeco, takimi i vjetër.', date=datetime(2026, 11, 18, tzinfo=timezone.utc))
        await self.sample(speaker='Arta', text='Modeco u diskutua edhe sot.')
        request = MeetingQuestion(discord_user_id='12', guild_id='123',
            question='Çfarë tha GA për Modeco dhe Primeks më 19.11.2026?')
        with patch.object(search.settings, 'DISCORD_GUILD_ID', '123'), \
             patch.object(search.settings, 'DISCORD_MEETING_NOTES_ENABLED', True), \
             patch.object(search, 'limit_question', AsyncMock()), \
             patch.object(search, 'generate_answer', AsyncMock(
                 return_value={'answer': 'GA kërkoi kontrollin e fotografive.', 'refs': [1]})) as model:
            async with self.sessions() as db:
                result = await search.ask_meetings(db, request)
            sources = model.await_args.args[1]
            self.assertEqual(sources[0]['speaker'], 'GA')
            self.assertIn('PrimEx', sources[0]['text'])
            self.assertTrue(all(source['date'] == '2026-11-19' for source in sources))
            self.assertEqual(len(sources), 2)
            citation = result['sources'][0]
            self.assertEqual((citation['speaker'], citation['date'], citation['time']), ('GA', '19.11.2026', '05:16–05:30'))
            self.assertTrue(citation['url'].endswith(f'meeting={sid}&view=transcript#segment-{segment_id}'))
            model.return_value = {'answer': 'Burim i gabuar.', 'refs': [99]}
            async with self.sessions() as db:
                self.assertEqual((await search.ask_meetings(db, request))['answer'], search.NO_EVIDENCE)
                missing = request.model_copy(update={'question': 'Versanel më 19.11.2026?'})
                self.assertEqual(await search.ask_meetings(db, missing), {'answer': search.NO_EVIDENCE, 'sources': []})
            self.assertEqual(model.await_count, 2)

    async def test_unlinked_and_revoked_account_never_get_answer(self):
        await self.sample()

        async def revoke(*args):
            async with self.sessions() as db:
                (await db.get(DiscordLink, self.lid)).enabled = False
                await db.commit()
            return {'answer': 'Përgjigjja.', 'refs': [1]}

        with patch.object(search.settings, 'DISCORD_GUILD_ID', '123'), \
             patch.object(search.settings, 'DISCORD_MEETING_NOTES_ENABLED', True), \
             patch.object(search, 'limit_question', AsyncMock()), \
             patch.object(search, 'generate_answer', AsyncMock(side_effect=revoke)) as model:
            async with self.sessions() as db:
                with self.assertRaises(HTTPException) as unlinked:
                    await search.ask_meetings(db, MeetingQuestion(discord_user_id='999', guild_id='123', question='Modeco'))
            self.assertEqual(unlinked.exception.status_code, 403)
            model.assert_not_awaited()
            async with self.sessions() as db:
                with self.assertRaises(HTTPException) as revoked:
                    await search.ask_meetings(db, MeetingQuestion(discord_user_id='12', guild_id='123', question='Modeco'))
            self.assertEqual(revoked.exception.status_code, 403)
            model.assert_awaited_once()

    async def test_open_points_retrieve_original_source_from_memory(self):
        from zoneinfo import ZoneInfo

        sid, segment_id = await self.sample()
        point = MiraMemoryItem(id=uuid.uuid4(), title='Fotografitë e Modeco', kind='ACTION', status='OPEN')
        async with self.sessions() as db:
            db.add(point)
            await db.flush()
            db.add(MiraMemoryEvent(item_id=point.id, meeting_id=sid, kind='MENTION', refs=[0], text='Kontrollohen fotografitë.'))
            await db.commit()
            tz = ZoneInfo(search.settings.APP_TIMEZONE)
            rows, memory = await search.find_evidence(db, '123', 'Cilat çështje mbetën të hapura?',
                datetime(2026, 11, 20).date(), tz)
        self.assertEqual([segment.id for segment, _ in rows], [segment_id])
        self.assertEqual(memory, [{'title': 'Fotografitë e Modeco', 'status': 'OPEN'}])


class DiscordQuestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_slash_reuses_mira_group_and_replies_ephemerally(self):
        group = discord.app_commands.Group(name='mira', description='Existing Host group')
        bot = SimpleNamespace(tree=SimpleNamespace(get_command=Mock(return_value=group), add_command=Mock()),
            bridge=AsyncMock(return_value={'answer': 'Përgjigjja.', 'sources': []}))
        interaction = SimpleNamespace(user=SimpleNamespace(id=42), guild_id=123,
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        with patch.object(search.settings, 'DISCORD_MEETING_NOTES_ENABLED', True):
            discord_mira_ask.register(bot, object())
        bot.tree.add_command.assert_not_called()
        await group.get_command('pyet').callback(interaction, 'Çfarë tha GA?')
        interaction.response.defer.assert_awaited_once_with(thinking=True, ephemeral=True)
        self.assertTrue(interaction.followup.send.await_args.kwargs['ephemeral'])

    async def test_failed_dm_only_sends_generic_instruction_to_channel(self):
        dm = SimpleNamespace(send=AsyncMock(side_effect=discord.Forbidden(
            SimpleNamespace(status=403, reason='Forbidden'), 'DM closed')))
        bot = SimpleNamespace(user=SimpleNamespace(id=400), bridge=AsyncMock(
            return_value={'answer': 'Informacion nga takimi.', 'sources': []}))
        message = SimpleNamespace(content='<@400> Çfarë tha GA?', guild=SimpleNamespace(id=123),
            author=SimpleNamespace(id=42, create_dm=AsyncMock(return_value=dm)), channel=SimpleNamespace(send=AsyncMock()))
        with patch.object(search.settings, 'DISCORD_MEETING_NOTES_ENABLED', True):
            self.assertTrue(await discord_mira_ask.handle_mention(bot, message))
        self.assertEqual(dm.send.await_args.args[0], 'Informacion nga takimi.')
        self.assertEqual(message.channel.send.await_args.args[0], discord_mira_ask.FALLBACK)
