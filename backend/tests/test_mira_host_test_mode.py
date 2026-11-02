"""Test rehearsals are repeatable and cannot consume or mutate real meeting data."""
import uuid
import asyncio
import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex
from tests.test_mira_host_service import DAY, TZ, IDS, payload
from tests.test_mira_host_bot import session
import mira_host as controller
from app.services import mira_host as service
from app.api.routers import mira_host_bot as api
from app.models.mira_host import Mira1HMeeting, Mira1HEvent


def meeting(*, test=True, slot='14:20', **extra):
    return Mira1HMeeting(id=uuid.uuid4(), meeting_date=DAY, slot=slot, is_test=test,
        started_at=datetime.combine(DAY, datetime.min.time(), TZ), status='GA_PHASE', **extra)


class TestModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_rehearsals_cannot_interrupt_real_meetings_in_any_slot(self):
        for slot in controller.SLOTS:
            with self.subTest(slot=slot):
                real = {**session(), 'test_mode': False, 'slot': slot}
                fake = SimpleNamespace(bridge=AsyncMock())
                host = controller.MiraHost(fake)
                host.session = real
                with patch.object(controller.settings, 'DISCORD_GUILD_ID', '1'), \
                     patch.object(host, 'voice_channel', return_value=SimpleNamespace(id=5)), self.assertRaises(ValueError):
                    await host.join_now(SimpleNamespace(id=1), slot, '11', test_mode=True)
                self.assertIs(host.session, real)
                self.assertFalse(real['closed'].is_set())
                fake.bridge.assert_not_awaited()

    async def test_recovery_skips_test_uploads_that_are_still_finishing_in_background(self):
        uploading = asyncio.Event()
        meeting_id = str(uuid.uuid4())
        old = {**session(), 'test_mode': True, 'meeting': meeting_id}
        fake = SimpleNamespace(bridge=AsyncMock(return_value={}))
        host = controller.MiraHost(fake)
        host.session = old
        task = host.task = asyncio.create_task(uploading.wait())
        with tempfile.TemporaryDirectory() as directory, patch.object(controller, 'RECOVERY_DIR', Path(directory)):
            path = Path(directory) / (meeting_id + '.json')
            path.write_text('{"meeting": "' + meeting_id + '", "lines": []}', encoding='utf-8')
            try:
                await host.preempt_test()
                await host.recover_transcripts()
                fake.bridge.assert_not_awaited()
                self.assertTrue(path.exists())
            finally:
                uploading.set()
                await task
            await host.recover_transcripts()
            self.assertFalse(path.exists())
            self.assertEqual(fake.bridge.await_args.args[0], '/bot/mira-host/meetings/' + meeting_id + '/finish')

    async def test_stalled_transcript_recovery_does_not_delay_scheduled_meetings(self):
        entered, release = asyncio.Event(), asyncio.Event()
        guild, voice = SimpleNamespace(id=1), SimpleNamespace(id=5)
        fake = SimpleNamespace(bridge=AsyncMock(return_value={'jobs': [{'kind': 'join', 'slot': '14:20'}]}),
                               get_guild=Mock(return_value=guild))
        host = controller.MiraHost(fake)
        async def recover():
            entered.set()
            await release.wait()
        with patch.object(controller.settings, 'DISCORD_GUILD_ID', '1'), \
             patch.object(host, 'voice_channel', return_value=voice), patch.object(host, 'recover_transcripts', recover), \
             patch.object(host, 'run', AsyncMock()) as run:
            try:
                await asyncio.wait_for(host.tick(service.now()), 0.2)
                await asyncio.sleep(0)
                run.assert_awaited_once_with('14:20', guild, voice, None)
                self.assertTrue(entered.is_set())
            finally:
                release.set()
                recovery = getattr(host, 'recovery_task', None)
                if recovery:
                    await recovery

    async def test_retry_worker_must_release_voice_before_preemption_finishes(self):
        entered, release = asyncio.Event(), asyncio.Event()
        state = {**session(), 'test_mode': True, 'reason': 'interrupted:test'}
        class Worker:
            def __init__(self, callback): pass
            async def start(self, **kwargs): state['failed'].set()
            async def close(self):
                entered.set()
                await release.wait()
        host = controller.MiraHost(SimpleNamespace())
        host.session = state
        prepared = {'meeting': {'id': 'test', 'is_test': True}, 'client_secret': 'synthetic', 'model': 'test'}
        with patch.object(controller, 'HostProcess', Worker):
            connecting = asyncio.create_task(host.connect(state, '11:00', SimpleNamespace(id=1), SimpleNamespace(id=5), prepared))
            handoff = None
            try:
                await asyncio.wait_for(entered.wait(), 0.5)
                handoff = asyncio.create_task(host.preempt_test())
                await asyncio.sleep(0)
                self.assertFalse(handoff.done())
            finally:
                release.set()
                connecting.cancel()
                await asyncio.gather(connecting, *([handoff] if handoff else []), return_exceptions=True)

    async def test_worker_shutdown_kills_a_worker_with_blocked_stdin(self):
        process = SimpleNamespace(returncode=None, stdin=SimpleNamespace(write=Mock(), drain=AsyncMock(side_effect=asyncio.Event().wait)),
                                  wait=AsyncMock(), kill=Mock())
        worker = controller.HostProcess(AsyncMock())
        worker.process = process
        with patch.object(controller, 'WORKER_SHUTDOWN_SECONDS', 0.01, create=True):
            await asyncio.wait_for(worker.close(), 2)
        process.kill.assert_called_once()

    async def test_close_can_interrupt_a_worker_blocked_on_its_initial_frame(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def drain():
            entered.set()
            await release.wait()
        process = SimpleNamespace(returncode=None, stdin=SimpleNamespace(write=Mock(), drain=drain),
            stdout=SimpleNamespace(readline=AsyncMock(side_effect=asyncio.Event().wait)),
            wait=AsyncMock(), kill=Mock(side_effect=release.set))
        worker = controller.HostProcess(AsyncMock())
        with patch.object(controller.asyncio, 'create_subprocess_exec', AsyncMock(return_value=process)), \
             patch.object(controller, 'WORKER_SHUTDOWN_SECONDS', 0.01):
            starting = asyncio.create_task(worker.start())
            try:
                await asyncio.wait_for(entered.wait(), 1)
                await asyncio.wait_for(worker.close(), 2)
                process.kill.assert_called_once()
            finally:
                release.set()
                starting.cancel()
                if worker.reader:
                    worker.reader.cancel()
                await asyncio.gather(starting, *([worker.reader] if worker.reader else []), return_exceptions=True)

    async def test_preflight_cancellation_cleans_up_its_child(self):
        entered = asyncio.Event()
        async def communicate():
            entered.set()
            await asyncio.Event().wait()
        process = SimpleNamespace(communicate=communicate, kill=Mock(), wait=AsyncMock())
        host = controller.MiraHost(SimpleNamespace())
        with patch.object(controller.asyncio, 'create_subprocess_exec', AsyncMock(return_value=process)):
            checking = asyncio.create_task(host.preflight())
            await entered.wait()
            checking.cancel()
            await asyncio.gather(checking, return_exceptions=True)
        process.kill.assert_called_once()

    async def test_cancelled_preflight_releases_startup_for_both_modes(self):
        for test_mode in (False, True):
            with self.subTest(test_mode=test_mode):
                entered, release = asyncio.Event(), asyncio.Event()
                host = controller.MiraHost(SimpleNamespace())
                async def preflight():
                    entered.set()
                    await release.wait()
                with patch.object(controller.settings, 'DISCORD_GUILD_ID', '1'), \
                     patch.object(host, 'voice_channel', return_value=SimpleNamespace(id=5)), \
                     patch.object(host, 'preflight', preflight):
                    joining = asyncio.create_task(host.join_now(SimpleNamespace(id=1), '14:20', '11', test_mode=test_mode))
                    await entered.wait()
                    await host.stop()
                    release.set()
                    with self.assertRaises(ValueError):
                        await joining
                self.assertFalse(host.running())
                self.assertIsNone(host.startup_task)
                self.assertFalse(host.pending_test_mode)

    async def test_voice_handoff_stays_busy_until_the_test_worker_has_closed(self):
        entered, release = asyncio.Event(), asyncio.Event()
        old = {**session(), 'test_mode': True}
        async def close():
            entered.set()
            await release.wait()
        old['process'].close = close
        host = controller.MiraHost(SimpleNamespace())
        host.session = old
        handoff = asyncio.create_task(host.preempt_test())
        await entered.wait()
        try:
            host.session = None  # The retiring run may already have finished.
            self.assertTrue(host.running())
        finally:
            release.set()
            await handoff

    async def test_stale_pending_test_flag_cannot_preempt_a_real_session(self):
        real = {**session(), 'test_mode': False}
        host = controller.MiraHost(SimpleNamespace())
        host.session, host.pending_test_mode = real, True
        release = asyncio.Event()
        task = host.task = asyncio.create_task(release.wait())
        try:
            await host.preempt_test()
            await asyncio.sleep(0)
            self.assertIs(host.session, real)
            self.assertIs(host.task, task)
            self.assertFalse(task.cancelled())
            self.assertFalse(real['closed'].is_set())
            real['process'].close.assert_not_awaited()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    async def test_real_manual_meeting_preempts_a_test_in_every_slot(self):
        for slot in controller.SLOTS:
            with self.subTest(slot=slot):
                old = {**session(), 'test_mode': True}
                calls = []
                async def bridge(path, body):
                    calls.append(path)
                    return {'meeting': {'id': 'real', 'is_test': False}}
                fake = SimpleNamespace(bridge=bridge)
                host = controller.MiraHost(fake)
                host.session = old
                async def run(*args, **kwargs):
                    kwargs['ready'].set_result(None)
                with patch.object(controller.settings, 'DISCORD_GUILD_ID', '1'), \
                     patch.object(host, 'voice_channel', return_value=SimpleNamespace(id=5)), \
                     patch.object(host, 'preflight', AsyncMock()), patch.object(host, 'run', run):
                    await host.join_now(SimpleNamespace(id=1), slot, '11')
                    await host.task
                self.assertTrue(old['closed'].is_set())
                self.assertEqual(old['reason'], 'test_preempted_for_real_meeting')
                self.assertLess(calls.index('/bot/mira-host/authorize'), calls.index('/bot/mira-host/session/start'))

    async def test_unauthorized_real_start_cannot_interrupt_a_test(self):
        old = {**session(), 'test_mode': True}
        async def denied(*args):
            raise ValueError('Not authorized')
        host = controller.MiraHost(SimpleNamespace(bridge=denied))
        host.session = old
        with patch.object(controller.settings, 'DISCORD_GUILD_ID', '1'), \
             patch.object(host, 'voice_channel', return_value=SimpleNamespace(id=5)), self.assertRaises(ValueError):
            await host.join_now(SimpleNamespace(id=1), '14:20', '11')
        self.assertFalse(old['closed'].is_set())

    async def test_scheduled_real_meeting_cancels_a_test_stuck_in_preflight(self):
        entered, blocked = asyncio.Event(), asyncio.Event()
        guild, voice = SimpleNamespace(id=1), SimpleNamespace(id=5)
        fake = SimpleNamespace(bridge=AsyncMock(return_value={'jobs': [{'kind': 'join', 'slot': '14:20'}]}),
                               get_guild=Mock(return_value=guild))
        host = controller.MiraHost(fake)
        async def preflight():
            entered.set()
            await blocked.wait()
        with patch.object(controller.settings, 'DISCORD_GUILD_ID', '1'), \
             patch.object(host, 'voice_channel', return_value=voice), patch.object(host, 'preflight', preflight), \
             patch.object(host, 'recover_transcripts', AsyncMock()), patch.object(host, 'run', AsyncMock()) as run:
            starting = asyncio.create_task(host.join_now(guild, '11:00', '11', test_mode=True))
            await entered.wait()
            try:
                await asyncio.wait_for(host.tick(service.now()), 0.5)
                await asyncio.sleep(0)
                run.assert_awaited_once_with('14:20', guild, voice, None)
            finally:
                blocked.set()
                starting.cancel()
                await asyncio.gather(starting, return_exceptions=True)

    async def test_real_start_does_not_wait_for_test_history_upload(self):
        uploading = asyncio.Event()
        old = {**session(), 'test_mode': True}
        old['process'].close = AsyncMock()
        async def bridge(path, body):
            return {'meeting': {'id': 'real', 'is_test': False}}
        host = controller.MiraHost(SimpleNamespace(bridge=bridge))
        host.session = old
        old_task = host.task = asyncio.create_task(uploading.wait())
        async def run(*args, **kwargs):
            kwargs['ready'].set_result(None)
        with patch.object(controller.settings, 'DISCORD_GUILD_ID', '1'), \
             patch.object(host, 'voice_channel', return_value=SimpleNamespace(id=5)), \
             patch.object(host, 'preflight', AsyncMock()), patch.object(host, 'run', run):
            try:
                await asyncio.wait_for(host.join_now(SimpleNamespace(id=1), '16:00', '11'), 0.5)
                old['process'].close.assert_awaited()
                self.assertFalse(old_task.done())
            finally:
                uploading.set()
                await asyncio.gather(old_task, return_exceptions=True)

    async def test_authorization_delay_cannot_stop_a_real_meeting_that_replaced_the_test(self):
        real = {**session(), 'test_mode': False}
        async def bridge(*args):
            host.session = real
            return {}
        fake = SimpleNamespace(tree=Mock(), bridge=bridge, error_message=str)
        host = fake.mira_host = controller.MiraHost(fake)
        host.session = {**session(), 'test_mode': True}
        interaction = SimpleNamespace(guild=SimpleNamespace(id=1), guild_id=1, channel_id=77, user=SimpleNamespace(id=11),
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        with patch.object(controller.settings, 'MIRA_HOST_ENABLED', True), \
             patch.object(controller.settings, 'MIRA_HOST_BOT_TOKEN', 'synthetic'), \
             patch.object(controller.settings, 'DISCORD_GUILD_ID', '1'), \
             patch.object(controller.settings, 'DISCORD_MEETING_CONTROL_CHANNEL_ID', '77'):
            controller.register_host_commands(fake, controller.discord.Object(id=1))
            group = fake.tree.add_command.call_args.args[0]
            await group.get_command('ndalo').callback(interaction)
        self.assertFalse(real['closed'].is_set())

    async def test_stop_during_test_preflight_preserves_daily_schedule(self):
        entered, release = asyncio.Event(), asyncio.Event()
        fake = SimpleNamespace(tree=Mock(), bridge=AsyncMock(return_value={}), error_message=str)
        host = fake.mira_host = controller.MiraHost(fake)
        interaction = SimpleNamespace(guild=SimpleNamespace(id=1), guild_id=1, channel_id=77, user=SimpleNamespace(id=11),
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        async def preflight():
            entered.set()
            await release.wait()
        with patch.object(controller.settings, 'MIRA_HOST_ENABLED', True), \
             patch.object(controller.settings, 'MIRA_HOST_BOT_TOKEN', 'synthetic'), \
             patch.object(controller.settings, 'DISCORD_GUILD_ID', '1'), \
             patch.object(controller.settings, 'DISCORD_MEETING_CONTROL_CHANNEL_ID', '77'), \
             patch.object(host, 'voice_channel', return_value=SimpleNamespace(id=5)), \
             patch.object(host, 'preflight', preflight):
            controller.register_host_commands(fake, controller.discord.Object(id=1))
            joining = asyncio.create_task(host.join_now(interaction.guild, '14:20', '11', test_mode=True))
            await entered.wait()
            try:
                group = fake.tree.add_command.call_args.args[0]
                await group.get_command('ndalo').callback(interaction)
                self.assertTrue(fake.bridge.await_args.args[1].get('test_only'))
            finally:
                release.set()
                with self.assertRaises(ValueError):
                    await joining

    async def test_history_pages_use_same_order_for_retried_real_meeting_and_rehearsal(self):
        real, test = meeting(test=False), meeting()
        real.created_at, real.started_at = real.started_at, real.started_at.replace(hour=15)
        test.created_at = test.started_at = test.started_at.replace(hour=14)
        rows = [real, test]
        def database():
            async def execute(statement):
                if statement._order_by_clauses:
                    clauses = str(statement)
                    by_started = 'mira_1h_meetings.started_at DESC' in clauses
                    ordered = sorted(rows, key=lambda row: row.started_at if by_started else row.created_at, reverse=True)
                    prefix = ordered[:statement._limit_clause.value]
                    return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: prefix))
                if 'count(' in str(statement):
                    return SimpleNamespace(scalar_one=lambda: 2)
                return SimpleNamespace(all=lambda: [(DAY, '14:20')])
            return SimpleNamespace(execute=execute)
        with patch.object(service, 'turns_view', AsyncMock(return_value=[])), \
             patch('app.services.discord_one_h.slot_groups', AsyncMock(return_value=[])):
            first = await service.list_meetings(database(), 1, 0)
            second = await service.list_meetings(database(), 1, 1)
        self.assertEqual(first['items'][0]['id'], str(real.id))
        self.assertEqual(second['items'][0]['id'], str(test.id))

    async def test_manual_api_starts_test_now_without_enabling_the_schedule(self):
        at = datetime.combine(DAY, datetime.min.time(), TZ).replace(hour=9)
        test = meeting()
        row = SimpleNamespace(enabled_until=None, target_minutes_per_person=2)
        db = SimpleNamespace(commit=AsyncMock())
        with patch.object(api, 'command_user', AsyncMock()) as authorize, \
             patch.object(service, 'get_settings', AsyncMock(return_value=row)), \
             patch.object(service, 'start_meeting', AsyncMock(return_value=test)) as start, \
             patch.object(service, 'realtime_session', AsyncMock(return_value={'client_secret': 'synthetic', 'model': 'gpt-realtime-2.1'})), \
             patch.object(service, 'now', return_value=at), \
             patch.object(api.settings, 'MIRA_HOST_ENABLED', True), \
             patch.object(api.settings, 'MIRA_HOST_BOT_TOKEN', 'synthetic'), \
             patch.object(api.settings, 'MIRA_HOST_OPENAI_API_KEY', 'synthetic'):
            result = await api.start(api.Start(slot='14:20', discord_user_id='11', test_mode=True), db)
        start.assert_awaited_once_with(db, '14:20', test_mode=True)
        authorize.assert_awaited_once()
        self.assertEqual(result['starts_at'], at.isoformat())
        self.assertTrue(result['meeting']['is_test'])
        self.assertIsNone(row.enabled_until)

    async def test_due_real_meeting_takes_priority_over_a_rehearsal(self):
        guild, voice = SimpleNamespace(id=1), SimpleNamespace(id=5)
        fake = SimpleNamespace(bridge=AsyncMock(return_value={'jobs': [{'kind': 'join', 'slot': '14:20'}]}),
                               get_guild=Mock(return_value=guild))
        host = controller.MiraHost(fake)
        old = host.session = {**session(), 'test_mode': True}
        with patch.object(host, 'recover_transcripts', AsyncMock()), patch.object(host, 'voice_channel', return_value=voice), \
             patch.object(host, 'run', AsyncMock()) as run, patch.object(controller.settings, 'DISCORD_GUILD_ID', '1'):
            await host.tick(service.now())
            await host.task
        self.assertTrue(old['closed'].is_set())
        self.assertEqual(old['reason'], 'test_preempted_for_real_meeting')
        run.assert_awaited_once_with('14:20', guild, voice, None)

    async def test_test_summary_cannot_be_shared_into_real_px_notes(self):
        test = meeting(summary='Vetëm provë')
        with patch.object(service, 'meeting_for', AsyncMock(return_value=test)), self.assertRaises(HTTPException) as caught:
            await service.show_mira_note_in_px(SimpleNamespace(), '1H', test.id, SimpleNamespace())
        self.assertEqual(caught.exception.status_code, 409)

    async def test_same_slot_can_be_rehearsed_repeatedly_outside_its_hour(self):
        db = SimpleNamespace(add=Mock(), flush=AsyncMock(), execute=AsyncMock(side_effect=AssertionError('Real slot must not be claimed')))
        at = datetime.combine(DAY, datetime.min.time(), TZ).replace(hour=9)
        first = await service.start_meeting(db, '14:20', at, test_mode=True)
        second = await service.start_meeting(db, '14:20', at, test_mode=True)
        self.assertNotEqual(first.id, second.id)
        self.assertTrue(first.is_test and second.is_test)
        self.assertEqual(first.started_at.hour, 9)
        self.assertIsNone(first.voice_meeting_id)
        self.assertEqual(first.slot, '14:20')

    async def test_real_held_slot_still_rejects_normal_start(self):
        real = meeting(test=False)
        real.status = 'DONE'
        db = SimpleNamespace(execute=AsyncMock(side_effect=[None, SimpleNamespace(scalar_one=lambda: real)]))
        with self.assertRaises(HTTPException) as error:
            await service.start_meeting(db, real.slot)
        self.assertEqual(error.exception.status_code, 409)
        select_sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
        self.assertIn('is_test IS false', select_sql)
        self.assertEqual(real.status, 'DONE')

    async def test_connection_retry_reuses_only_the_test_id(self):
        test = meeting(join_attempts=1)
        at = test.started_at
        with patch.object(service, 'meeting_for', AsyncMock(return_value=test)):
            result = await service.start_meeting(SimpleNamespace(), test.slot, at, test_mode=True, test_meeting_id=test.id)
        self.assertIs(result, test)
        self.assertEqual(result.join_attempts, 2)
        real = meeting(test=False, join_attempts=1)
        with patch.object(service, 'meeting_for', AsyncMock(return_value=real)), self.assertRaises(HTTPException):
            await service.start_meeting(SimpleNamespace(), real.slot, at, test_mode=True, test_meeting_id=real.id)
        self.assertEqual(real.join_attempts, 1)

    async def test_test_progress_never_becomes_a_real_global_mention(self):
        db = SimpleNamespace(execute=AsyncMock(side_effect=AssertionError('Real progress must not change')))
        test = meeting()
        await service.remember(db, test, str(uuid.uuid4()), 'DONE', '', 'Oferta')
        self.assertEqual(await service.mentioned(db, test), set())
        self.assertEqual(await service.progress_since(db, test), service.report_window_start(DAY, test.slot))

    async def test_test_progress_ack_changes_only_its_own_event(self):
        test = meeting()
        event = SimpleNamespace(meeting_id=test.id, kind='PROGRESS_PENDING', sent_at=service.now(),
            data={'mentions': [{'task_id': str(uuid.uuid4()), 'kind': 'DONE', 'point_key': '', 'text': 'Oferta'}],
                  'fetched_at': service.now().isoformat()})
        db = SimpleNamespace(get=AsyncMock(return_value=event), execute=AsyncMock())
        await service.acknowledge_progress(db, test, uuid.uuid4())
        db.execute.assert_not_awaited()
        self.assertEqual(event.kind, 'PROGRESS_READ')

    async def test_px_notes_are_simulated_without_calling_the_real_api(self):
        db = SimpleNamespace(add=Mock(), commit=AsyncMock())
        with patch('app.services.discord_task_tools.user_api', AsyncMock()) as real_api:
            result = await service.save_px_note(db, meeting(), service.PxNote(text='Vetëm provë'))
        self.assertTrue(result['simulated'])
        real_api.assert_not_awaited()
        db.commit.assert_not_awaited()
        self.assertEqual(db.add.call_args.args[0].kind, 'TEST_PX_NOTE')

    async def test_task_creation_is_simulated_without_converting_the_note(self):
        note = SimpleNamespace(id=uuid.uuid4(), content='Oferta\nDetajet', is_converted_to_task=False, department_id=None)
        db = SimpleNamespace(get=AsyncMock(return_value=note), add=Mock(), commit=AsyncMock())
        args = service.CreateTask(note_id=str(note.id), assignees=['EF'], due_date=DAY.isoformat(), deadline=False)
        with patch('app.services.discord_task_tools.user_api', AsyncMock()) as real_api:
            result = await service.create_task(db, meeting(), service.SlotData(payload([]), DAY), args)
        self.assertTrue(result['simulated'])
        self.assertFalse(note.is_converted_to_task)
        real_api.assert_not_awaited()
        db.commit.assert_not_awaited()
        self.assertEqual(db.add.call_args.args[0].kind, 'TEST_TASK_CREATED')

    async def test_test_finish_does_not_attach_a_real_recorder(self):
        test = meeting()
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [])))
        with patch.object(service, 'recorder_session', AsyncMock()) as recorder:
            await service.finish_meeting(db, test, 'completed')
        recorder.assert_not_awaited()
        self.assertIsNone(test.voice_meeting_id)

    async def test_test_history_keeps_multiple_rehearsals_and_real_discord_reports(self):
        rows = [meeting(slot='11:00'), meeting(slot='11:00'), meeting(test=False)]
        db = SimpleNamespace(execute=AsyncMock(side_effect=[
            SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows)),
            SimpleNamespace(scalar_one=lambda: 3), SimpleNamespace(all=lambda: [(DAY, '14:20')])]))
        with patch.object(service, 'turns_view', AsyncMock(return_value=[])), \
             patch('app.services.discord_one_h.slot_groups', AsyncMock(return_value=[(DAY, '11:00'), (DAY, '14:20')])):
            result = await service.list_meetings(db, 20, 0)
        self.assertEqual(result['total'], 4)
        self.assertEqual(len(result['items']), 4)
        self.assertEqual(sum(bool(row.get('is_test')) for row in result['items']), 2)
        self.assertEqual(sum(row['status'] == 'DISCORD_REPORT' for row in result['items']), 1)

    async def test_scheduled_requests_cannot_enable_test_mode(self):
        with self.assertRaises(HTTPException) as error:
            await api.start(api.Start(slot='14:20', test_mode=True), SimpleNamespace())
        self.assertEqual(error.exception.status_code, 422)

    async def test_stopping_test_does_not_disable_real_schedule(self):
        until = service.now() + timedelta(hours=2)
        row = SimpleNamespace(enabled_until=until)
        with patch.object(api, 'command_user', AsyncMock()) as authorize, \
             patch.object(service, 'get_settings', AsyncMock(return_value=row)), \
             patch.object(service, 'settings_view', return_value={'enabled': True}):
            await api.disable(api.Stop(discord_user_id='11', test_only=True), SimpleNamespace(commit=AsyncMock()))
        authorize.assert_awaited_once()
        self.assertEqual(row.enabled_until, until)

    async def test_test_does_not_invite_staff_or_defer_the_person_the_tester_is_playing(self):
        host = controller.MiraHost(SimpleNamespace())
        state = {**session(), 'test_mode': True, 'current_turn': {'id': 'turn', 'discord': {'discord_user_id': '22'}},
            'turn_started': controller.datetime.now(controller.tz()) - timedelta(seconds=40), 'turn_nudged': False, 'target': 2}
        operation = AsyncMock()
        host.background_notification(state, operation)
        operation.assert_not_called()
        with patch.object(host, 'advance', AsyncMock()) as advance:
            await host.watch_turn(state)
        advance.assert_not_awaited()

    async def test_shared_slash_command_forwards_test_option(self):
        fake = SimpleNamespace(tree=Mock(), mira_host=SimpleNamespace(join_now=AsyncMock()), error_message=str)
        interaction = SimpleNamespace(guild=SimpleNamespace(id=1), guild_id=1, channel_id=77, user=SimpleNamespace(id=11),
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        with patch.object(controller.settings, 'MIRA_HOST_ENABLED', True), \
             patch.object(controller.settings, 'MIRA_HOST_BOT_TOKEN', 'synthetic'), \
             patch.object(controller.settings, 'DISCORD_GUILD_ID', '1'), \
             patch.object(controller.settings, 'DISCORD_MEETING_CONTROL_CHANNEL_ID', '77'):
            controller.register_host_commands(fake, controller.discord.Object(id=1))
            group = fake.tree.add_command.call_args.args[0]
            await group.get_command('hyr').callback(interaction, '14:20', True)
        self.assertTrue(fake.mira_host.join_now.await_args.kwargs['test_mode'])
        self.assertIn('TEST MODE', interaction.followup.send.await_args.args[0])

    def test_only_real_slots_have_a_unique_date_slot_index(self):
        index = next(index for index in Mira1HMeeting.__table__.indexes if index.name == 'uq_mira_1h_meeting_slot')
        sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        self.assertIn('CREATE UNIQUE INDEX', sql)
        self.assertIn('WHERE is_test IS FALSE', sql)
