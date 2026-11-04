"""Restart persistence and cancellation regressions; no live services."""
import asyncio
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from tests.test_mira_host_bot import session
import mira_host as controller


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_recovery_file_with_an_attempt_is_still_uploaded(self):
        mid = str(uuid.uuid4())
        bridge = AsyncMock(return_value={})
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        with tempfile.TemporaryDirectory() as directory, patch.object(controller, 'RECOVERY_DIR', Path(directory)):
            legacy = Path(directory) / (mid + '.json')
            legacy.write_text(json.dumps({'meeting': mid, 'join_attempt': 1,
                'lines': [{'id': 'legacy', 'text': 'Fakt i ruajtur'}]}), encoding='utf-8')
            await host.recover_transcripts()
            self.assertFalse(legacy.exists())
        self.assertEqual(bridge.await_args_list[0].args[1]['lines'][0]['id'], 'legacy')
        self.assertEqual(bridge.await_args.args[1]['expected_join_attempt'], 1)

    async def test_successful_cleanup_removes_only_its_own_attempt(self):
        mid = str(uuid.uuid4())
        first = {**session(), 'meeting': mid, 'join_attempt': 1, 'finished': True, 'reason': 'interrupted:test',
                 'lines': [{'id': 'old', 'text': 'Raportimi i parë'}]}
        second = {**session(), 'meeting': mid, 'join_attempt': 2, 'finished': False, 'reason': 'completed'}
        host = controller.MiraHost(SimpleNamespace(bridge=AsyncMock(return_value={})))
        with tempfile.TemporaryDirectory() as directory, patch.object(controller, 'RECOVERY_DIR', Path(directory)):
            host.persist_transcript(first)
            await host.finish(second)
            records = [json.loads(path.read_text(encoding='utf-8')) for path in Path(directory).glob('*.json')]
        self.assertEqual([record['join_attempt'] for record in records], [1])
        self.assertEqual(records[0]['lines'][0]['id'], 'old')

    async def test_a_changed_snapshot_of_the_same_attempt_is_not_deleted(self):
        mid = str(uuid.uuid4())
        state = {**session(), 'meeting': mid, 'join_attempt': 1, 'finished': True, 'reason': 'interrupted:test'}
        async def bridge(path, body):
            if path.endswith('/finish'):
                state['lines'] = [{'id': 'late', 'text': 'Fakt i vonuar'}]
                host.persist_transcript(state)
            return {}
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        with tempfile.TemporaryDirectory() as directory, patch.object(controller, 'RECOVERY_DIR', Path(directory)):
            host.persist_transcript(state)
            await host.recover_transcripts()
            records = [json.loads(path.read_text(encoding='utf-8')) for path in Path(directory).glob('*.json')]
        self.assertEqual(records[0]['lines'][0]['id'], 'late')

    async def test_restart_preserves_pending_data_from_both_attempts_before_any_upload(self):
        mid = str(uuid.uuid4())
        first = {**session(), 'meeting': mid, 'join_attempt': 1, 'finished': True, 'reason': 'interrupted:test',
                 'lines': [{'id': 'old', 'text': 'Raportimi i parë'}], 'notes_acks': {'old-receipt'}}
        second = {**session(), 'meeting': mid, 'join_attempt': 2, 'finished': False,
                  'lines': [{'id': 'new', 'text': 'Raportimi i ri'}]}
        uploads, finishes, receipts = [], [], []
        async def bridge(path, body):
            if path.endswith('/transcript'):
                uploads.extend(body['lines'])
            if path.endswith('/finish'):
                finishes.append(body)
            if path.endswith('/notes/ack'):
                receipts.append(body['token'])
            return {}
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        with tempfile.TemporaryDirectory() as directory, patch.object(controller, 'RECOVERY_DIR', Path(directory)):
            host.persist_transcript(first)
            host.persist_transcript(second)
            await host.recover_transcripts()
            self.assertFalse(list(Path(directory).glob('*.json')))
        self.assertEqual({line['id'] for line in uploads}, {'old', 'new'})
        self.assertEqual({body['expected_join_attempt'] for body in finishes}, {1, 2})
        self.assertEqual(receipts, ['old-receipt'])

    async def test_a_late_write_from_the_old_attempt_cannot_overwrite_the_new_snapshot(self):
        mid = str(uuid.uuid4())
        old = {**session(), 'meeting': mid, 'join_attempt': 1, 'finished': True, 'reason': 'interrupted:test',
               'lines': [{'id': 'old', 'text': 'Raportimi i parë'}]}
        new = {**session(), 'meeting': mid, 'join_attempt': 2, 'finished': False,
               'lines': [{'id': 'new', 'text': 'Raportimi i ri'}]}
        host = controller.MiraHost(SimpleNamespace())
        with tempfile.TemporaryDirectory() as directory, patch.object(controller, 'RECOVERY_DIR', Path(directory)):
            host.persist_transcript(new)
            host.persist_transcript(old)
            records = [json.loads(path.read_text(encoding='utf-8')) for path in Path(directory).glob('*.json')]
        self.assertEqual({record['join_attempt'] for record in records}, {1, 2})
        self.assertEqual({line['id'] for record in records for line in record['lines']}, {'old', 'new'})

    async def test_cancelling_the_meeting_task_cannot_report_success(self):
        for existing_reason in ('completed', 'stopped_by_command'):
            with self.subTest(existing_reason=existing_reason):
                entered = asyncio.Event()
                host = controller.MiraHost(SimpleNamespace())
                async def connect(state, *_args, **_kwargs):
                    state['reason'] = existing_reason
                    entered.set()
                    await asyncio.Event().wait()
                with patch.object(host, 'connect', connect), patch.object(host, 'finish', AsyncMock()) as finish:
                    task = asyncio.create_task(host.run('11:00', SimpleNamespace(), SimpleNamespace()))
                    await entered.wait()
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                state = finish.await_args.args[0]
                self.assertEqual(state['reason'], 'interrupted:task_cancelled' if existing_reason == 'completed' else existing_reason)

    async def test_cancellation_before_connect_keeps_the_prepared_attempt_for_cleanup(self):
        host = controller.MiraHost(SimpleNamespace())
        prepared = {'meeting': {'id': str(uuid.uuid4())}, 'join_attempt': 1}
        with patch.object(host, 'finish', AsyncMock()) as finish:
            await host.run('11:00', SimpleNamespace(), SimpleNamespace(), prepared=prepared, start_generation=-1)
        state = finish.await_args.args[0]
        self.assertEqual(state.get('join_attempt'), 1)
        self.assertEqual(state['reason'], 'stopped_by_command')

    async def test_manual_start_stopped_during_preparation_finishes_only_its_attempt(self):
        mid = str(uuid.uuid4())
        calls = []
        async def bridge(path, body):
            calls.append((path, body))
            if path.endswith('/session/start'):
                host.start_generation += 1
                return {'meeting': {'id': mid}, 'join_attempt': 1}
            return {}
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        with patch.object(controller.settings, 'DISCORD_GUILD_ID', '1'), \
             patch.object(host, 'voice_channel', return_value=SimpleNamespace(id=5)), \
             patch.object(host, 'preflight', AsyncMock()):
            with self.assertRaises(ValueError):
                await host.join_now(SimpleNamespace(id=1), '11:00', '11')
        self.assertTrue(calls[-1][0].endswith('/finish'))
        self.assertEqual(calls[-1][1]['expected_join_attempt'], 1)
