import os
import importlib.util
import unittest
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET', 'one-h-client-test-only')

AVAILABLE = importlib.util.find_spec('discord') is not None
if AVAILABLE:
    import discord
    import discord_one_h_client as client
    from discord_bot import PrimeFlowBot
from app.services import discord_one_h as service

AT = datetime(2026, 10, 27, 10, tzinfo=ZoneInfo('Europe/Budapest'))


def data_of(status='TODO', count=1, due_date=None):
    tasks = [{'id': str(uuid.uuid4()), 'title': 'EF: Oferta\n1. Pika e parë', 'status': status,
              'one_h_report_slot': '10:00', 'due_date': due_date} for _ in range(count)]
    return service.presentation(SimpleNamespace(id=uuid.uuid4(), day=AT.date(), bucket='10:00', one_h_report=service.snapshot(tasks, AT)))


def interaction(data, action):
    item = data['current'] or data['questions'][-1]
    tid = 'next' if item['id'] == 'next' else uuid.UUID(item['id']).hex
    return SimpleNamespace(user=SimpleNamespace(id=11), guild_id=22, channel_id=33, id=555,
        message=SimpleNamespace(edit=AsyncMock()), data={'custom_id': f'pf:1h:{uuid.UUID(data["id"]).hex}:{tid}:{action}'},
        response=SimpleNamespace(send_modal=AsyncMock(), send_message=AsyncMock(), defer=AsyncMock(), edit_message=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())


@unittest.skipUnless(AVAILABLE, 'Install requirements-discord.txt')
class CardTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_done_button_refreshes_instead_of_closing_again(self):
        data = data_of()
        click = interaction(data, 'done')
        final = {**data, 'current': None, 'questions': [data['questions'][-1]],
                 'tasks': [{**t, 'status': 'DONE'} for t in data['tasks']]}
        bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(return_value={'one_h': final}),
            select=AsyncMock(), one_h_url=Mock(return_value=None))
        await client.handle(bot, click)
        bot.select.assert_not_awaited()
        click.response.send_modal.assert_not_awaited()
        self.assertIn('E kryer', click.response.edit_message.call_args.kwargs['content'])
        labels = [getattr(c, 'label', '') for c in click.response.edit_message.call_args.kwargs['view'].children]
        self.assertNotIn('✅ U krye', labels)

    async def test_cards_keep_structure_and_only_relevant_question(self):
        for status, expected in [('TODO', 'Pse s’ke vazhdu'), ('IN_PROGRESS', 'A ke me vazhdu'), ('DONE', service.NEXT_QUESTION)]:
            data = data_of(status)
            text, view = client.card(data, user_id='11', join_url='https://discord.com/channels/22/44')
            self.assertIn('<@11> ⏰ **Sloti 10:00**', text)
            self.assertIn(expected, text)
            self.assertEqual(text.count('Me çka ke me vazhdu në slotin tjetër?'), 1)
            self.assertNotIn('Notes të reja', text)
            self.assertNotIn('Pika e parë?', text)
            self.assertLessEqual(len(text), 2000)
            for control in view.children:
                if control.custom_id:
                    self.assertLessEqual(len(control.custom_id), 100)
            labels = [getattr(c, 'label', None) for c in view.children]
            self.assertEqual(labels.count('✍️ Raporto'), 1)
            self.assertNotIn('💬 Koment', labels)
            self.assertNotIn('✍️ Punë tjetër', labels)
            self.assertNotIn('Pa vazhdim', labels)
            self.assertNotIn('🔄 Rifresko', labels)
            self.assertNotIn('⏭ Kalo', labels)
            buttons = [c for c in view.children if isinstance(c, discord.ui.Button)]
            self.assertTrue(all(c.row == 0 for c in buttons))
            if status == 'DONE':
                self.assertNotIn('📅 Shtyje', labels)
            else:
                self.assertIn('📅 Shtyje', labels)

    async def test_more_than_25_tasks_remain_revisable(self):
        data = data_of(count=31)
        _, view = client.card(data, requested=data['questions'][30]['id'], next_page=1)
        menu = next(c for c in view.children if isinstance(c, discord.ui.Select))
        self.assertEqual(len(menu.options), 6)
        self.assertEqual(menu.options[-1].value, data['questions'][30]['id'])
        self.assertLessEqual(len(view.to_components()), 5)

    async def test_choices_use_discord_emoji_objects_instead_of_codes_in_descriptions(self):
        data = data_of()
        with patch.dict(client.ui.STATUS_ICONS, {'TODO': '<:pf_todo:123456789012345678>'}):
            _, view = client.card(data)
        menu = next(c for c in view.children if isinstance(c, discord.ui.Select))
        self.assertEqual(menu.options[0].emoji.id, 123456789012345678)
        self.assertNotIn('<:', menu.options[0].description)

    async def test_progress_opens_existing_task_controls_and_preserves_report(self):
        data = data_of()
        click = interaction(data, 'task')
        bot = SimpleNamespace(private_channel=AsyncMock(), ack=AsyncMock(),
            bridge=AsyncMock(return_value={'one_h': data}), select=AsyncMock(return_value={'task': {'id': data['current']['id']}}), show_task=AsyncMock())
        await client.handle(bot, click)
        bot.show_task.assert_awaited_once_with(click, bot.select.return_value, new=True)
        click.edit_original_response.assert_not_awaited()

    async def test_postponement_uses_existing_reviewer_flow(self):
        data = data_of()
        click = interaction(data, 'postpone')
        job = {'id': data['current']['id'], 'source': 'task', 'title': 'Oferta', 'live_dates': {},
               'reasons': [{'label': 'Tjetër', 'value': 'OTHER'}]}
        bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(side_effect=[{'one_h': data}, job]),
            select=AsyncMock(return_value={}), ack=AsyncMock())
        await client.handle(bot, click)
        bot.ack.assert_not_awaited()
        args = click.response.send_message.call_args.kwargs
        self.assertTrue(args['ephemeral'])
        self.assertIn('konfirmim', args['content'])
        menu = args['view'].children[0]
        self.assertTrue(menu.custom_id.startswith('pf:m2a:taskreason:'))
        back = args['view'].children[1]
        self.assertEqual(back.label, '← Kthehu te raportimi')
        self.assertTrue(back.custom_id.endswith(':back'))
        click.data['custom_id'] = back.custom_id
        bot.bridge.reset_mock(side_effect=True)
        bot.bridge.return_value = {'one_h': data}
        bot.one_h_url = Mock(return_value=None)
        await client.handle(bot, click)
        self.assertIn('Pse s’ke vazhdu', click.edit_original_response.call_args.kwargs['content'])
        self.assertTrue(bot.bridge.call_args.args[0].endswith('/tasks'))
        self.assertEqual(bot.bridge.await_count, 1)

    async def test_answer_modal_saves_text_and_time_without_changing_task_dates(self):
        data = data_of()
        click = interaction(data, 'answer')
        bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(return_value=data),
            one_h_url=Mock(return_value=None), error_message=str)
        modal = client.AnswerModal(bot, data, data['current'], click.message)
        modal.answer._value = 'Pres materialet'
        modal.expected._value = 'Nesër 10:00'
        modal.continuation._value = 'Pastaj testoj ofertën'
        await modal.on_submit(click)
        path, payload = bot.bridge.call_args.args
        self.assertTrue(path.endswith('/one-h-answer'))
        self.assertEqual(payload['answer'], 'Pres materialet')
        self.assertEqual(payload['expected_at'], 'Nesër 10:00')
        self.assertEqual(payload['continuation'], 'Pastaj testoj ofertën')
        self.assertIn('komenti i detyrës', click.followup.send.call_args.args[0])
        self.assertNotIn('direct_actions', payload)
        click.message.edit.assert_awaited_once()

    async def test_complete_preserves_the_already_visible_next_slot_question(self):
        data = data_of()
        click = interaction(data, 'done')
        final = {**data, 'tasks': [{**t, 'status': 'DONE'} for t in data['tasks']]}
        final = service.presentation(SimpleNamespace(id=uuid.UUID(data['id']), day=AT.date(), bucket='10:00',
            one_h_report={'tasks': final['tasks'], 'next': data['next']}))
        detail = {'task': {'id': data['current']['id']}, 'fingerprint': 'f' * 16}
        bot = SimpleNamespace(apply=AsyncMock(return_value={'status': 'DONE', 'message': 'U krye'}),
            bridge=AsyncMock(return_value={'one_h': final}), one_h_url=Mock(return_value=None), error_message=str)
        modal = client.TaskActionModal(bot, detail, data, click.message, complete=True)
        modal.comment._value = 'Rezultati u dorëzua'
        await modal.on_submit(click)
        self.assertIn(service.NEXT_QUESTION, click.message.edit.call_args.kwargs['content'])
        self.assertIn('Rezultati u dorëzua', bot.apply.call_args.args[-1])
        click.edit_original_response.assert_not_awaited()
        self.assertTrue(click.response.defer.call_args.kwargs['thinking'])

    async def test_scheduler_sends_next_question_even_with_no_current_tasks(self):
        question, waiting, empty = data_of(), data_of('WAITING_CLIENT'), data_of(count=0)
        datasets = {d['id']: d for d in [question, waiting, empty]}
        jobs = [{'id': d['id'], 'bucket': '10:00', 'discord_user_id': str(11 + i), 'guild_id': '22', 'channel_id': str(33 + i)}
                for i, d in enumerate([question, waiting, empty])]
        async def bridge(path, payload):
            if path.endswith('/claim'):
                return {'jobs': jobs}
            if path.endswith('/tasks'):
                d = next(d for rid, d in datasets.items() if rid in path)
                return {'tasks': d['tasks'], 'bucket': '10:00', 'one_h': d}
            return {'ok': True}
        bot = SimpleNamespace(bridge=AsyncMock(side_effect=bridge), private_channel=AsyncMock(return_value=SimpleNamespace(id=33)),
            one_h_url=Mock(return_value=None), http=SimpleNamespace(request=AsyncMock(return_value={'id': '900'})))
        await PrimeFlowBot.reminders.coro(bot)
        self.assertEqual(bot.http.request.await_count, 3)
        payload = bot.http.request.call_args_list[0].kwargs['json']
        self.assertIn('Pse s’ke vazhdu', payload['content'])
        self.assertEqual(payload['allowed_mentions']['users'], ['11'])
        self.assertTrue(payload['enforce_nonce'])
        for call in bot.http.request.call_args_list:
            self.assertIn('Me çka ke me vazhdu në slotin tjetër?', call.kwargs['json']['content'])

    async def test_future_due_has_no_completion_time_field(self):
        for due, count in [('2026-10-27', 2), ('2026-10-30', 1), (None, 1)]:
            data = data_of('IN_PROGRESS', due_date=due)
            modal = client.AnswerModal(SimpleNamespace(), data, data['current'], SimpleNamespace())
            self.assertEqual(len(modal.children), count + 1)
            text, _ = client.card(data)
            self.assertEqual('Kur pritet me u kry?' in text, count == 2)

    async def test_dropdown_selection_is_saved_while_task_question_is_unanswered(self):
        data = data_of()
        click = interaction(data, 'nselect0-' + data['next_options_key'])
        click.data['values'] = [data['next_options'][0]['id']]
        bot = SimpleNamespace(private_channel=AsyncMock(), ack=AsyncMock(), bridge=AsyncMock(side_effect=[{'one_h': data}, data]),
            one_h_url=Mock(return_value=None))
        await client.handle(bot, click)
        payload = bot.bridge.call_args.args[1]
        self.assertEqual(payload['selection_mode'], 'TASKS')
        self.assertEqual(payload['next_task_ids'], click.data['values'])
        self.assertEqual(payload['next_options_key'], data['next_options_key'])
        self.assertIn('Pse s’ke vazhdu', click.edit_original_response.call_args.kwargs['content'])


@unittest.skipUnless(AVAILABLE, 'Install requirements-discord.txt')
class SyncTests(unittest.IsolatedAsyncioTestCase):
    def setup_sync(self):
        data = data_of('IN_PROGRESS')
        content, view = client.card(data, user_id='11')
        messages = {mid: SimpleNamespace(author=SimpleNamespace(id=99), content=content,
            components=[discord.components.ActionRow(row) for row in view.to_components()], edit=AsyncMock())
            for mid in ('900', '901')}
        fresh = {**data, 'current': None, 'questions': [data['questions'][-1]],
                 'tasks': [{**t, 'status': 'DONE'} for t in data['tasks']]}
        job = {'id': data['id'], 'bucket': '10:00', 'revision': 'revision-1', 'message_ids': ['900', '901'],
               'discord_user_id': '11', 'guild_id': '22', 'channel_id': '33'}
        async def bridge(path, payload):
            return {'jobs': [job]} if path.endswith('/jobs') else {'one_h': fresh}
        async def fetch(mid):
            return messages[str(mid)]
        channel = SimpleNamespace(fetch_message=AsyncMock(side_effect=fetch), send=AsyncMock())
        bot = SimpleNamespace(bridge=AsyncMock(side_effect=bridge), private_channel=AsyncMock(return_value=channel),
                              user=SimpleNamespace(id=99), one_h_url=Mock(return_value=None))
        return bot, channel, messages, job

    async def test_platform_completion_edits_all_existing_copies_once_and_keeps_silent(self):
        bot, channel, messages, job = self.setup_sync()
        await client.sync(bot)
        for message in messages.values():
            message.edit.assert_awaited_once()
            kwargs = message.edit.call_args.kwargs
            self.assertIn('E kryer', kwargs['content'])
            self.assertNotIn('✅ U krye', [getattr(c, 'label', '') for c in kwargs['view'].children])
            self.assertEqual(kwargs['allowed_mentions'].to_dict(), {'parse': []})
        calls = bot.bridge.await_count
        await client.sync(bot)
        self.assertEqual(bot.bridge.await_count, calls + 1)  # Only the revision scan runs.
        self.assertEqual(channel.fetch_message.await_count, 2)
        channel.send.assert_not_awaited()

    async def test_retired_and_deleted_messages_are_not_recreated(self):
        bot, channel, messages, job = self.setup_sync()
        messages['900'].components = []
        async def fetch(mid):
            if mid == 901:
                raise discord.NotFound(SimpleNamespace(status=404, reason='Not Found'), 'Unknown message')
            return messages[str(mid)]
        channel.fetch_message.side_effect = fetch
        await client.sync(bot)
        for message in messages.values():
            message.edit.assert_not_awaited()
        channel.send.assert_not_awaited()
        await client.sync(bot)
        self.assertEqual(channel.fetch_message.await_count, 2)

    async def test_failed_edit_is_retried_and_privacy_check_precedes_discord_reads(self):
        bot, channel, messages, job = self.setup_sync()
        messages['900'].edit.side_effect = RuntimeError('Temporary failure')
        await client.sync(bot)
        self.assertNotIn((job['id'], '900'), bot.one_h_sync_cache)
        messages['900'].edit.side_effect = None
        await client.sync(bot)
        self.assertEqual(messages['900'].edit.await_count, 2)
        bot.one_h_sync_cache.clear()
        channel.fetch_message.reset_mock()
        bot.private_channel.side_effect = ValueError('Wrong private channel')
        await client.sync(bot)
        channel.fetch_message.assert_not_awaited()
