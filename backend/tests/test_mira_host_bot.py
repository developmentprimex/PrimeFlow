import os
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET', 'mira-host-tests-not-a-production-secret')

import mira_host

TARGET = {'discord_user_id': '11', 'guild_id': '1', 'channel_id': '22'}
BRIEF = {'current': [{'title': 'EF: ASISTENTI', 'status': 'IN_PROGRESS', 'period': 'AM', 'symbol': 'M2/3', 'deadline': False, 'due': '2026-10-23'}],
         'previous_slot': '10:00', 'previous_open': [], 'new_progress': {'done': [], 'strikes': []}}


def bot(responses):
    calls = []

    async def bridge(path, payload):
        calls.append((path, payload))
        for key, value in responses.items():
            if path.endswith(key):
                return value
        return {}
    return SimpleNamespace(bridge=bridge, calls=calls, private_channel=AsyncMock(return_value=SimpleNamespace(send=AsyncMock()))), calls


def session(guild=None):
    return {'slot': '11:00', 'meeting': 'm1', 'guild': guild or SimpleNamespace(get_member=Mock(return_value=None)),
            'voice': SimpleNamespace(id=5), 'process': SimpleNamespace(send=AsyncMock()), 'lines': [], 'target': 4,
            'ending': False, 'closed': asyncio.Event(), 'ready': asyncio.Event(), 'upcoming': None}


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_connection_failure_reaches_manual_caller_and_closes_prepared_meeting(self):
        fake, calls = bot({})
        host = mira_host.MiraHost(fake)
        host.connect = AsyncMock(side_effect=ValueError('connect_failed'))
        ready = asyncio.get_running_loop().create_future()
        await host.run('11:00', SimpleNamespace(id=1), SimpleNamespace(id=5),
                       manual_by='11', prepared={'meeting': {'id': 'm1'}}, ready=ready)
        with self.assertRaisesRegex(ValueError, 'nuk u lidh'):
            await ready
        self.assertIsNone(host.session)
        self.assertEqual(calls[-1][0], '/bot/mira-host/meetings/m1/finish')

    async def test_stop_while_api_prepares_closes_meeting_without_joining(self):
        fake, calls = bot({})
        host = mira_host.MiraHost(fake)
        host.preflight = AsyncMock()
        host.voice_channel = Mock(return_value=SimpleNamespace(id=5))

        async def bridge(path, body):
            calls.append((path, body))
            if path.endswith('/session/start'):
                await host.stop('stopped_by_command')
                return {'meeting': {'id': 'm1'}}
            return {}

        fake.bridge = bridge
        with patch.object(mira_host.settings, 'DISCORD_GUILD_ID', '1'):
            with self.assertRaisesRegex(ValueError, 'anulua'):
                await host.join_now(SimpleNamespace(id=1), '11:00', '11')
        self.assertEqual(calls[-1], ('/bot/mira-host/meetings/m1/finish', {'reason': 'stopped_by_command'}))
        self.assertIsNone(host.task)

    def test_status_reports_active_manual_meeting_with_daily_schedule_disabled(self):
        text = mira_host.status_text({'enabled': False, 'live': {'slot': '11:00', 'status': 'GA_PHASE', 'people': []}})
        self.assertIn('11:00', text)
        self.assertNotIn('nuk** po i mban', text)

    async def test_registered_join_command_invokes_manual_entry(self):
        fake = SimpleNamespace(tree=Mock(), mira_host=SimpleNamespace(join_now=AsyncMock()), error_message=str)
        interaction = SimpleNamespace(guild=SimpleNamespace(id=1), user=SimpleNamespace(id=11),
                                      response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        with patch.object(mira_host.settings, 'MIRA_HOST_ENABLED', True), \
             patch.object(mira_host.settings, 'MIRA_HOST_BOT_TOKEN', 'test-token'):
            mira_host.register_host_commands(fake, mira_host.discord.Object(id=1))
        command = fake.tree.add_command.call_args.args[0].get_command('hyr')
        self.assertIsNotNone(command)
        await command.callback(interaction, '11:00')
        fake.mira_host.join_now.assert_awaited_once_with(interaction.guild, '11:00', '11')
        self.assertIn('u kyç', interaction.followup.send.await_args.args[0])

    async def test_stop_during_manual_preflight_cancels_entry(self):
        prepared = {'meeting': {'id': 'm1'}, 'client_secret': 'ek', 'model': 'm'}
        fake, calls = bot({'/session/start': prepared})
        host = mira_host.MiraHost(fake)
        host.voice_channel = Mock(return_value=SimpleNamespace(id=5))

        async def stop_during_preflight():
            await host.stop('stopped_by_command')

        async def run(*args, **kwargs):
            kwargs['ready'].set_result(None)

        host.preflight = stop_during_preflight
        host.run = run
        with patch.object(mira_host.settings, 'DISCORD_GUILD_ID', '1'):
            with self.assertRaises(ValueError):
                await host.join_now(SimpleNamespace(id=1), '11:00', '11')
        self.assertFalse(calls)

    async def test_manual_join_prepares_one_session_and_waits_until_connected(self):
        prepared = {'meeting': {'id': 'm1'}, 'client_secret': 'ek', 'model': 'm', 'target_minutes': 4,
                    'starts_at': mira_host.datetime.now(mira_host.tz()).isoformat()}
        fake, calls = bot({'/session/start': prepared})
        host = mira_host.MiraHost(fake)
        host.preflight = AsyncMock()
        voice = SimpleNamespace(id=5)
        host.voice_channel = Mock(return_value=voice)
        captured = {}

        async def run(slot, guild, channel, **kwargs):
            captured.update(slot=slot, channel=channel, **kwargs)
            kwargs['ready'].set_result(None)

        host.run = run
        with patch.object(mira_host.settings, 'DISCORD_GUILD_ID', '1'):
            await host.join_now(SimpleNamespace(id=1), '11:00', '11')
        self.assertEqual(calls, [('/bot/mira-host/session/start', {'slot': '11:00', 'discord_user_id': '11'})])
        self.assertEqual(captured['slot'], '11:00')
        self.assertIs(captured['channel'], voice)
        self.assertIs(captured['prepared'], prepared)
        self.assertEqual(captured['manual_by'], '11')
        self.assertFalse(host.starting)

    async def test_second_join_and_scheduler_cannot_start_during_manual_preparation(self):
        fake, calls = bot({'/tick': {'jobs': [{'kind': 'join', 'slot': '11:00'}]}})
        fake.get_guild = Mock(return_value=SimpleNamespace(id=1))
        host = mira_host.MiraHost(fake)
        host.voice_channel = Mock(return_value=SimpleNamespace(id=5))
        host.starting = True
        host.run = AsyncMock()
        with patch.object(mira_host.settings, 'DISCORD_GUILD_ID', '1'):
            with self.assertRaises(ValueError):
                await host.join_now(SimpleNamespace(id=1), '11:00', '11')
            await host.tick(None)
        await asyncio.sleep(0)
        self.assertEqual(calls, [('/bot/mira-host/tick', {})])
        host.run.assert_not_awaited()

    async def test_manual_join_rejects_missing_channel_before_creating_a_meeting(self):
        fake, calls = bot({})
        host = mira_host.MiraHost(fake)
        host.voice_channel = Mock(return_value=None)
        with patch.object(mira_host.settings, 'DISCORD_GUILD_ID', '1'):
            with self.assertRaises(ValueError):
                await host.join_now(SimpleNamespace(id=1), '11:00', '11')
        self.assertFalse(calls)

    async def test_long_structured_handoff_reaches_worker_as_complete_json(self):
        fake, _ = bot({})
        host = mira_host.MiraHost(fake)
        state = session()
        tasks = [{'task_id': str(i), 'detyra': 'Oferta për klientin ' + str(i) + ' ' + 'detaje ' * 50}
                 for i in range(60)]
        await host.say(state, 'SISTEMI: ' + json.dumps({'RADHA': {'plan_discutimi': tasks}}, ensure_ascii=False))
        message = state['process'].send.await_args.args[0]
        delivered = json.loads(message['text'].removeprefix('SISTEMI: '))
        self.assertEqual(len(delivered['RADHA']['plan_discutimi']), 60)
        self.assertEqual(delivered['RADHA']['plan_discutimi'][-1]['task_id'], '59')

    def test_discussion_is_current_first_with_task_specific_progress_and_no_duplicates(self):
        current = [
            {'task_id': 'a', 'title': 'OFERTA', 'status': 'IN_PROGRESS', 'period': 'AM'},
            {'task_id': 'b', 'title': 'RAPORTI', 'status': 'TODO', 'period': 'AM'},
            {'task_id': 'd', 'title': 'PDF', 'status': 'IN_PROGRESS', 'period': 'AM'},
        ]
        previous = [current[0], {'task_id': 'c', 'title': 'EMAIL', 'status': 'IN_PROGRESS', 'period': 'AM'}]
        brief = {**BRIEF, 'current': current, 'previous_open': previous,
                 'progress_percentages': {'a': 0, 'b': 0, 'c': 0, 'd': 25},
                 'new_progress': {'done': [], 'strikes': [
                     {'task_id': 'a', 'title': 'OFERTA', 'points': [{'text': 'Drafti'}]}]}}
        result = mira_host.turn_brief({'name': 'Elsa Ferati', 'initials': 'EF', 'brief': brief})
        discussion = result['plan_discutimi']
        self.assertEqual([(t['task_id'], t['grupi']) for t in discussion],
                         [('a', 'AKTUAL'), ('b', 'AKTUAL'), ('d', 'AKTUAL'), ('c', 'PARAPRAK')])
        self.assertTrue(discussion[0]['ka_progres_te_regjistruar'])
        self.assertEqual(discussion[0]['strike_ne_interval'], ['Drafti'])
        self.assertFalse(discussion[1]['ka_progres_te_regjistruar'])
        self.assertEqual(discussion[1]['strike_ne_interval'], [])
        self.assertTrue(discussion[2]['ka_progres_te_regjistruar'])
        self.assertEqual(discussion[2]['progres_perqindje'], 25)

    async def test_ending_a_turn_hands_mira_the_next_person_and_invites_them(self):
        fake, calls = bot({'/turns/next': {'current': {'id': 't2', 'name': 'Rinesa Ahmeti', 'initials': 'RA', 'discord': TARGET, 'brief': BRIEF},
                                           'upcoming': {'id': 't3', 'name': 'Endrit Hoxha', 'discord': TARGET}}})
        host = mira_host.MiraHost(fake)
        state = session()
        await host.tool(state, {'type': 'tool_call', 'name': 'end_person_turn', 'call_id': 'c1', 'arguments': '{"summary":"EF kreu PDF-të"}'})
        self.assertEqual(calls[0], ('/bot/mira-host/meetings/m1/turns/next', {'summary': 'EF kreu PDF-të'}))
        result = state['process'].send.await_args.args[0]
        self.assertEqual(result['call_id'], 'c1')
        self.assertEqual(result['output']['RADHA']['initials'], 'RA')
        self.assertIn('M2/3', result['output']['RADHA']['detyrat_e_slotit'])
        fake.private_channel.assert_awaited()  # RA was not in the voice channel, so she is called
        self.assertEqual(state['upcoming']['id'], 't3')

    async def test_last_turn_ends_the_meeting(self):
        fake, _ = bot({'/turns/next': {'current': None, 'upcoming': None}})
        host = mira_host.MiraHost(fake)
        state = session()
        await host.tool(state, {'type': 'tool_call', 'name': 'end_person_turn', 'call_id': 'c1', 'arguments': '{}'})
        self.assertTrue(state['ending'])
        self.assertTrue(state['process'].send.await_args.args[0]['output']['FUNDI'])

    async def test_at_1150_the_last_turn_leads_to_the_pm_review_and_then_the_end(self):
        pm = [{'person': 'Elsa Ferati', 'initials': 'EF', 'detyrat_pm': ['oferta (e verdhë)']}]
        fake, _ = bot({'/turns/next': {'current': None, 'upcoming': None, 'pm_review': pm}})
        host = mira_host.MiraHost(fake)
        state = {**session(), 'slot': '11:50', 'pm_reviewed': False}
        await host.tool(state, {'type': 'tool_call', 'name': 'end_person_turn', 'call_id': 'c1', 'arguments': '{}'})
        self.assertEqual(state['process'].send.await_args.args[0]['output']['PM_RISHIKIMI'], pm)
        self.assertFalse(state['ending'])
        await host.tool(state, {'type': 'tool_call', 'name': 'end_person_turn', 'call_id': 'c2', 'arguments': '{}'})
        self.assertTrue(state['process'].send.await_args.args[0]['output']['FUNDI'])
        self.assertTrue(state['ending'])

    async def test_staff_starts_when_ga_is_done_but_not_before_the_hour(self):
        fake, calls = bot({'/staff': {'turns': [{'id': 't1'}]},
                           '/turns/next': {'current': {'id': 't1', 'name': 'Rinesa Ahmeti', 'initials': 'RA', 'discord': None,
                                                       'brief': BRIEF}, 'upcoming': None}})
        host = mira_host.MiraHost(fake)
        state = {**session(), 'ga_done': asyncio.Event(), 'staff_started': False,
                 'starts_at': mira_host.datetime.now(mira_host.tz()) + mira_host.timedelta(minutes=1)}
        await host.tool(state, {'type': 'tool_call', 'name': 'end_ga_phase', 'call_id': 'g1', 'arguments': '{}'})
        self.assertTrue(state['process'].send.await_args.args[0]['output']['prit'])
        self.assertTrue(state['ga_done'].is_set())
        self.assertFalse(calls)
        # GA ran past the hour: the first person comes back in the same answer.
        state = {**session(), 'ga_done': asyncio.Event(), 'staff_started': False,
                 'starts_at': mira_host.datetime.now(mira_host.tz()) - mira_host.timedelta(minutes=1)}
        await host.tool(state, {'type': 'tool_call', 'name': 'end_ga_phase', 'call_id': 'g2', 'arguments': '{}'})
        self.assertEqual(state['process'].send.await_args.args[0]['output']['RADHA']['initials'], 'RA')
        self.assertTrue(state['staff_started'])

    async def test_other_tools_are_answered_by_primeflow(self):
        fake, calls = bot({'/tools/list_new_px_notes': {'total': 0, 'notes': []}})
        host = mira_host.MiraHost(fake)
        state = session()
        await host.tool(state, {'type': 'tool_call', 'name': 'list_new_px_notes', 'call_id': 'c9', 'arguments': '{}'})
        self.assertEqual(calls[0][0], '/bot/mira-host/meetings/m1/tools/list_new_px_notes')
        self.assertEqual(state['process'].send.await_args.args[0]['output'], {'total': 0, 'notes': []})

    async def test_fallback_is_called_only_when_the_primary_is_not_in_the_1h(self):
        member = SimpleNamespace(voice=SimpleNamespace(channel=SimpleNamespace(id=5)))
        guild = SimpleNamespace(get_member=Mock(return_value=member), get_channel=Mock(return_value=None), voice_channels=[])
        fake, _ = bot({'/tick': {'jobs': [{'kind': 'ga_fallback', 'slot': '10:00', 'primary_discord_user_id': '7', **TARGET}]}})
        fake.get_guild = Mock(return_value=guild)
        host = mira_host.MiraHost(fake)
        host.voice_channel = Mock(return_value=SimpleNamespace(id=5))
        with patch.object(mira_host.settings, 'DISCORD_GUILD_ID', '1'):
            await host.tick(None)
            fake.private_channel.assert_not_awaited()
            member.voice = None
            await host.tick(None)
        fake.private_channel.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()


class ConnectRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_during_retry_or_api_never_launches_another_worker(self):
        for phase in ('retry', 'api'):
            with self.subTest(phase=phase):
                prepared = {'meeting': {'id': 'm1'}, 'client_secret': 'ek', 'model': 'm', 'target_minutes': 4}
                state = {**session(), 'manual_by': '11', 'attempt': 0, 'failed': asyncio.Event(), 'reason': 'completed'}
                started = []

                class FakeProcess:
                    def __init__(self, on_message): self.on_message = on_message
                    async def start(self, **kwargs):
                        started.append(state['closed'].is_set())
                        await self.on_message({'type': 'interrupted', 'reason': 'connect_timeout'})
                    async def close(self): pass

                async def retry_wait(*args):
                    if phase == 'retry': state['closed'].set()

                fake, calls = bot({'/session/start': prepared})
                original_bridge = fake.bridge

                async def bridge(path, body):
                    if phase == 'api': state['closed'].set()
                    return await original_bridge(path, body)

                fake.bridge = bridge
                host = mira_host.MiraHost(fake)
                with patch.object(mira_host, 'HostProcess', FakeProcess), patch.object(mira_host.asyncio, 'sleep', retry_wait):
                    with self.assertRaisesRegex(ValueError, 'stopped'):
                        await host.connect(state, '11:00', SimpleNamespace(id=1), SimpleNamespace(id=5), prepared=prepared)
                self.assertEqual(started, [False])
                self.assertEqual(len(calls), 0 if phase == 'retry' else 1)

    async def test_manual_retry_preserves_caller_and_does_not_prepare_first_attempt_twice(self):
        outcomes = iter([{'type': 'interrupted', 'reason': 'connect_timeout'}, {'type': 'ready'}])

        class FakeProcess:
            def __init__(self, on_message): self.on_message = on_message
            async def start(self, **kwargs):
                await self.on_message(next(outcomes))
            async def close(self): pass

        prepared = {'meeting': {'id': 'm1'}, 'client_secret': 'ek', 'model': 'm', 'target_minutes': 4}
        fake, calls = bot({'/session/start': prepared})
        host = mira_host.MiraHost(fake)
        state = {**session(), 'manual_by': '11', 'attempt': 0, 'failed': asyncio.Event(), 'reason': 'completed'}
        with patch.object(mira_host, 'HostProcess', FakeProcess), patch.object(mira_host.asyncio, 'sleep', AsyncMock()):
            await host.connect(state, '11:00', SimpleNamespace(id=1), SimpleNamespace(id=5), prepared=prepared)
        self.assertEqual(calls, [('/bot/mira-host/session/start', {'slot': '11:00', 'discord_user_id': '11'})])

    async def test_a_failed_connection_is_retried_before_mira_must_talk(self):
        outcomes = iter([{'type': 'interrupted', 'reason': 'connect_timeout'}, {'type': 'ready'}])
        started = []

        class FakeProcess:
            def __init__(self, on_message):
                self.on_message = on_message
                started.append(self)

            async def start(self, **kwargs):
                asyncio.get_running_loop().call_soon(lambda: asyncio.ensure_future(self.on_message(next(outcomes))))

            async def send(self, message):
                pass

            async def close(self):
                await self.on_message({'type': 'process_exit'})  # a late event of the failed attempt

        fake, calls = bot({'/session/start': {'meeting': {'id': 'm1'}, 'client_secret': 'ek', 'model': 'm', 'target_minutes': 4}})
        host = mira_host.MiraHost(fake)
        state = session()
        state.update(attempt=0, failed=asyncio.Event(), reason='completed')
        with patch.object(mira_host, 'HostProcess', FakeProcess), patch.object(mira_host.asyncio, 'sleep', AsyncMock()):
            result = await host.connect(state, '10:00', SimpleNamespace(id=1), SimpleNamespace(id=5))
        self.assertEqual(result['meeting']['id'], 'm1')
        self.assertEqual(len(started), 2)
        self.assertEqual([c[0] for c in calls].count('/bot/mira-host/session/start'), 2)
        self.assertFalse(state['closed'].is_set())
        self.assertEqual(state['reason'], 'completed')
