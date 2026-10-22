import os
import asyncio
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
