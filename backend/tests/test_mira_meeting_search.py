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
            self.assertTrue(citation['url'].endswith(f'meeting={sid}&source=discord&view=transcript#segment-{segment_id}'))
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
        url = 'https://primeflow.example/mira?tab=notetaker&meeting=meeting&view=transcript#segment-record'
        bot = SimpleNamespace(tree=SimpleNamespace(get_command=Mock(return_value=group), add_command=Mock()),
            bridge=AsyncMock(return_value={'answer': 'U kërkua kontrolli i ofertës.', 'sources': [
                {'date': '16.11.2026', 'speaker': 'GA', 'time': '09:00–09:10', 'url': url},
            ]}))
        interaction = SimpleNamespace(user=SimpleNamespace(id=42), guild_id=123,
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        with patch.object(search.settings, 'DISCORD_MEETING_NOTES_ENABLED', True):
            discord_mira_ask.register(bot, object())
        bot.tree.add_command.assert_not_called()
        await group.get_command('pyet').callback(interaction, 'Çfarë tha GA?')
        interaction.response.defer.assert_awaited_once_with(thinking=True, ephemeral=True)
        response = interaction.followup.send.await_args.kwargs
        self.assertTrue(response['ephemeral'])
        self.assertEqual(len(response['embeds']), 1)
        self.assertEqual(response['embeds'][0].description,
            '**Pyetja**\nÇfarë tha GA?\n\n**Përgjigjja**\nU kërkua kontrolli i ofertës.\n\n'
            f'**Burimi**\n[16.11.2026 – GA – 09:00–09:10]({url})')

    async def test_answer_without_evidence_displays_question_and_no_sources(self):
        bot = SimpleNamespace(bridge=AsyncMock(return_value={'answer': search.NO_EVIDENCE, 'sources': []}))
        content, cards = await discord_mira_ask.answer(bot, 42, 123, '  Çfarë u vendos për **Modeco**?  ')
        self.assertIsNone(content)
        question = discord.utils.escape_markdown('Çfarë u vendos për **Modeco**?')
        self.assertEqual(cards[0].description, f'**Pyetja**\n{question}\n\n**Përgjigjja**\n{search.NO_EVIDENCE}')

    async def test_long_answer_preserves_all_source_links_in_one_message(self):
        urls = [f'https://primeflow.example/mira?tab=notetaker&meeting={uuid.uuid4()}'
                f'&view=transcript#segment-{uuid.uuid4()}' for _ in range(8)]
        sources = [{'date': '16.11.2026', 'speaker': 'A' * 100, 'time': '09:00–09:10', 'url': url} for url in urls]
        bot = SimpleNamespace(bridge=AsyncMock(return_value={'answer': '*' * 1200, 'sources': sources}))
        _, cards = await discord_mira_ask.answer(bot, 42, 123, 'A' * 500)
        self.assertEqual(len(cards), 2)
        self.assertLessEqual(sum(map(len, cards)), 6000)
        for url in urls:
            self.assertIn(f'({url})', cards[1].description)

    async def test_failed_dm_only_sends_generic_instruction_to_channel(self):
        dm = SimpleNamespace(send=AsyncMock(side_effect=discord.Forbidden(
            SimpleNamespace(status=403, reason='Forbidden'), 'DM closed')))
        bot = SimpleNamespace(user=SimpleNamespace(id=400), bridge=AsyncMock(
            return_value={'answer': 'Informacion nga takimi.', 'sources': []}))
        message = SimpleNamespace(content='<@400> Çfarë tha GA?', guild=SimpleNamespace(id=123),
            author=SimpleNamespace(id=42, create_dm=AsyncMock(return_value=dm)), channel=SimpleNamespace(send=AsyncMock()))
        with patch.object(search.settings, 'DISCORD_MEETING_NOTES_ENABLED', True):
            self.assertTrue(await discord_mira_ask.handle_mention(bot, message))
        self.assertEqual(dm.send.await_args.kwargs['embeds'][0].description,
            '**Pyetja**\nÇfarë tha GA?\n\n**Përgjigjja**\nInformacion nga takimi.')
        self.assertEqual(message.channel.send.await_args.args[0], discord_mira_ask.FALLBACK)
