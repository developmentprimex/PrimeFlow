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
    async def test_task_dates_are_displayed_between_title_and_question(self):
        data = data_of('IN_PROGRESS', due_date='2026-10-30T00:00:00+00:00')
        data['current']['start_date'] = '2026-10-26T00:00:00+00:00'
        text, _ = client.card(data)
        self.assertIn('Start: 26.10.2026 · Due: 30.10.2026\n\nA ke me vazhdu', text)
        self.assertNotIn('00:00', text)
        self.assertNotIn('Start:', client.continuation_card(data)[0])

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
        for status, expected in [('TODO', 'Pse s’ke vazhdu'), ('IN_PROGRESS', 'A ke me vazhdu'), ('DONE', 'E kryer')]:
            data = data_of(status)
            text, view = client.card(data, user_id='11', join_url='https://discord.com/channels/22/44')
            self.assertTrue(text.startswith('⏰ **Sloti 10:00**'))
            self.assertNotIn('<@11>', text)
            self.assertNotIn('Takimi 1H i orës', text)
            self.assertNotIn('Progresi:', text)
            self.assertIn(expected, text)
            self.assertNotIn(service.NEXT_QUESTION, text)
            next_text, next_view = client.continuation_card(data)
            self.assertEqual(next_text.count(service.NEXT_QUESTION), 1)
            self.assertTrue(next_text.startswith(client.NEXT_HEADING))
            self.assertFalse(any(isinstance(c, discord.ui.Select) for c in view.children))
            self.assertNotIn('Notes të reja', text)
            self.assertNotIn('Pika e parë?', text)
            self.assertLessEqual(len(text), 2000)
            for control in view.children:
                if control.custom_id:
                    self.assertLessEqual(len(control.custom_id), 100)
            labels = [getattr(c, 'label', None) for c in view.children]
            self.assertEqual(labels.count('💬 Koment'), int(status != 'DONE'))
            self.assertNotIn('✍️ Raporto', labels)
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
                self.assertEqual(labels[:5], ['☑ Strike', '✅ U krye', '📅 Shtyje', '💬 Koment', '🎧 Kyçu në 1H'])

    async def test_more_than_25_tasks_remain_revisable(self):
        data = data_of(count=31)
        _, view = client.continuation_card(data, next_page=1)
        menu = next(c for c in view.children if isinstance(c, discord.ui.Select))
        self.assertEqual(len(menu.options), 6)
        self.assertEqual(menu.options[-1].value, data['questions'][30]['id'])
        self.assertLessEqual(len(view.to_components()), 5)

    async def test_choices_use_discord_emoji_objects_instead_of_codes_in_descriptions(self):
        data = data_of()
        with patch.dict(client.ui.STATUS_ICONS, {'TODO': '<:pf_todo:123456789012345678>'}):
            _, view = client.continuation_card(data)
        menu = next(c for c in view.children if isinstance(c, discord.ui.Select))
        self.assertEqual(menu.options[0].emoji.id, 123456789012345678)
        self.assertNotIn('<:', menu.options[0].description)

    async def test_strike_opens_picker_in_same_message_and_returns_to_same_task(self):
        data = data_of()
        click = interaction(data, 'task')
        detail = {'task': data['tasks'][0], 'fingerprint': 'a' * 16,
            'title_points': [{'number': 1, 'text': 'Pika e parë', 'done': False}], 'description_points': []}
        bot = SimpleNamespace(private_channel=AsyncMock(), ack=AsyncMock(),
            bridge=AsyncMock(return_value={'one_h': data}), select=AsyncMock(return_value=detail),
            one_h_url=Mock(return_value=None), show_task=AsyncMock())
        await client.handle(bot, click)
        bot.show_task.assert_not_awaited()
        args = click.edit_original_response.call_args.kwargs
        picker = next(c for c in args['view'].children if isinstance(c, discord.ui.Select))
        self.assertTrue(picker.custom_id.startswith('pf:pointset:'))
        self.assertEqual(picker.options[0].value, '1')
        back = next(c for c in args['view'].children if getattr(c, 'label', '') == '← Kthehu te raportimi')
        self.assertFalse(any((c.custom_id or '').startswith('pf:back:') for c in args['view'].children))
        click.data['custom_id'] = back.custom_id
        await client.handle(bot, click)
        self.assertIn('Sloti 10:00', click.edit_original_response.call_args.kwargs['content'])
        self.assertIn(data['current']['title'].splitlines()[0], click.edit_original_response.call_args.kwargs['content'])
        self.assertIn('☑ Strike', [getattr(c, 'label', '') for c in click.edit_original_response.call_args.kwargs['view'].children])

    async def test_strike_write_and_pagination_keep_report_return(self):
        data = data_of()
        tid, rid = data['current']['id'], uuid.UUID(data['id']).hex
        detail = {'task': data['tasks'][0], 'fingerprint': 'a' * 16,
            'title_points': [{'number': i, 'text': f'Pika {i}', 'done': False} for i in range(1, 32)], 'description_points': []}
        back = f'pf:1h:{rid}:{uuid.UUID(tid).hex}:backn1'
        view = client.ui.with_one_h_return(client.ui.points_view(detail, 1), back)
        click = interaction(data, 'task')
        click.message.components = [discord.components.ActionRow(row) for row in view.to_components()]
        click.data['custom_id'] = next(c.custom_id for c in view.children if isinstance(c, discord.ui.Select))
        result = {**detail, 'status': 'DONE', 'message': 'Pikat u përditësuan'}
        bot = SimpleNamespace(apply=AsyncMock(return_value=result), remember_task=Mock(), select=AsyncMock(return_value=detail))
        await PrimeFlowBot.run_direct(bot, click, tid, detail['fingerprint'], [], 'Bëj strike pika 26')
        updated = click.edit_original_response.call_args.kwargs['view']
        self.assertIn(back, [c.custom_id for c in updated.children])
        picker = next(c for c in updated.children if isinstance(c, discord.ui.Select))
        self.assertEqual(picker.options[0].value, '26')
        message = SimpleNamespace(components=[discord.components.ActionRow(row) for row in updated.to_components()])
        paged = client.ui.report_return(client.ui.points_view(detail, 0), message)
        self.assertIn(back, [c.custom_id for c in paged.children])

    async def test_empty_strike_picker_has_return_and_never_mutates_report(self):
        data = data_of()
        click = interaction(data, 'task')
        detail = {'task': data['tasks'][0], 'fingerprint': 'a' * 16, 'title_points': [], 'description_points': []}
        bot = SimpleNamespace(private_channel=AsyncMock(), ack=AsyncMock(), bridge=AsyncMock(return_value={'one_h': data}),
            select=AsyncMock(return_value=detail))
        await client.handle(bot, click)
        self.assertIn('nuk ka pika', click.edit_original_response.call_args.kwargs['content'])
        self.assertEqual(bot.bridge.await_count, 1)

    async def test_return_keeps_selected_task_and_continuation_page(self):
        data = data_of(count=31)
        selected = data['questions'][2]
        data['current'] = selected
        click = interaction(data, 'task')
        _, original = client.card(data, requested=selected['id'])
        click.message.components = [discord.components.ActionRow(row) for row in original.to_components()]
        detail = {'task': selected, 'fingerprint': 'a' * 16, 'title_points': [], 'description_points': []}
        bot = SimpleNamespace(private_channel=AsyncMock(), ack=AsyncMock(),
            bridge=AsyncMock(return_value={'one_h': data}), select=AsyncMock(return_value=detail), one_h_url=Mock(return_value=None))
        await client.handle(bot, click)
        back = next(c for c in click.edit_original_response.call_args.kwargs['view'].children if c.custom_id.endswith('backn0'))
        click.data['custom_id'] = back.custom_id
        await client.handle(bot, click)
        view = click.edit_original_response.call_args.kwargs['view']
        self.assertFalse(any(isinstance(c, discord.ui.Select) for c in view.children))
        self.assertIn(uuid.UUID(selected['id']).hex, next(c.custom_id for c in view.children if getattr(c, 'label', '') == '☑ Strike'))

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
        self.assertNotIn(service.NEXT_QUESTION, click.message.edit.call_args.kwargs['content'])
        self.assertIn('E kryer', click.message.edit.call_args.kwargs['content'])
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
        self.assertEqual(bot.http.request.await_count, 6)
        payload = bot.http.request.call_args_list[0].kwargs['json']
        self.assertIn('Pse s’ke vazhdu', payload['content'])
        self.assertEqual(payload['allowed_mentions']['users'], ['11'])
        self.assertTrue(payload['enforce_nonce'])
        for index in range(0, 6, 2):
            main, following = [c.kwargs['json'] for c in bot.http.request.call_args_list[index:index + 2]]
            self.assertNotIn(service.NEXT_QUESTION, main['content'])
            self.assertIn(service.NEXT_QUESTION, following['content'])
            self.assertNotEqual(main['nonce'], following['nonce'])

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
        click.message.content = client.continuation_card(data)[0]
        click.data['values'] = [data['next_options'][0]['id']]
        bot = SimpleNamespace(private_channel=AsyncMock(), ack=AsyncMock(), bridge=AsyncMock(side_effect=[{'one_h': data}, data]),
            one_h_url=Mock(return_value=None))
        await client.handle(bot, click)
        payload = bot.bridge.call_args.args[1]
        self.assertEqual(payload['selection_mode'], 'TASKS')
        self.assertEqual(payload['next_task_ids'], click.data['values'])
        self.assertEqual(payload['next_options_key'], data['next_options_key'])
        self.assertTrue(click.edit_original_response.call_args.kwargs['content'].startswith(client.NEXT_HEADING))
        self.assertNotIn('Pse s’ke vazhdu', click.edit_original_response.call_args.kwargs['content'])

    async def test_continuation_comment_and_paging_stay_on_separate_message(self):
        data = data_of(count=31)
        click = interaction(data, 'npage1')
        click.message.content = client.continuation_card(data)[0]
        bot = SimpleNamespace(private_channel=AsyncMock(), ack=AsyncMock(), bridge=AsyncMock(return_value={'one_h': data}),
            one_h_url=Mock(return_value=None), error_message=str)
        await client.handle(bot, click)
        args = click.edit_original_response.call_args.kwargs
        self.assertTrue(args['content'].startswith(client.NEXT_HEADING))
        self.assertEqual(len(next(c for c in args['view'].children if isinstance(c, discord.ui.Select)).options), 6)
        modal = client.AnswerModal(bot, data, data['questions'][-1], click.message)
        modal.answer._value = 'Vazhdoj me testimin'
        bot.bridge.return_value = data
        await modal.on_submit(click)
        self.assertEqual(bot.bridge.call_args.args[1]['item_id'], 'next')
        self.assertTrue(click.message.edit.call_args.kwargs['content'].startswith(client.NEXT_HEADING))
        self.assertNotIn('komenti i detyrës', click.followup.send.call_args.args[0])

    async def test_continuation_directly_shows_picker_and_keeps_it_after_save(self):
        data = data_of()
        content, view = client.continuation_card(data)
        buttons = [c for c in view.children if isinstance(c, discord.ui.Button)]
        self.assertEqual(buttons, [])
        self.assertNotIn('Sloti ', content)
        select = next(c for c in view.children if isinstance(c, discord.ui.Select))
        click = interaction(data, 'nselect0-' + data['next_options_key'])
        click.message.content = content
        bot = SimpleNamespace(private_channel=AsyncMock(), ack=AsyncMock(), bridge=AsyncMock(return_value={'one_h': data}),
            one_h_url=Mock(return_value=None))
        click.data = {'custom_id': select.custom_id, 'values': [data['next_options'][0]['id']]}
        bot.bridge.side_effect = [{'one_h': data}, data]
        await client.handle(bot, click)
        closed = click.edit_original_response.call_args.kwargs['view']
        self.assertTrue(any(isinstance(c, discord.ui.Select) for c in closed.children))
        self.assertFalse(any(isinstance(c, discord.ui.Button) for c in closed.children))
        self.assertEqual(bot.bridge.call_args.args[1]['next_task_ids'], click.data['values'])


@unittest.skipUnless(AVAILABLE, 'Install requirements-discord.txt')
class SyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_keeps_task_and_continuation_copies_in_their_roles(self):
        bot, channel, messages, job = self.setup_sync()
        data = data_of('IN_PROGRESS')
        data['id'] = job['id']
        content, view = client.continuation_card(data)
        messages['901'].content = content
        messages['901'].components = [discord.components.ActionRow(row) for row in view.to_components()]
        await client.sync(bot)
        self.assertNotIn(service.NEXT_QUESTION, messages['900'].edit.call_args.kwargs['content'])
        following = messages['901'].edit.call_args.kwargs['content'] if messages['901'].edit.called else messages['901'].content
        self.assertTrue(following.startswith(client.NEXT_HEADING))
    async def test_revision_sync_does_not_replace_open_strike_picker(self):
        bot, channel, messages, job = self.setup_sync()
        rid, tid = client.message_context(messages['900'])
        for message in messages.values():
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label='← Kthehu te raportimi', custom_id=f'pf:1h:{rid}:{tid}:backn0'))
            message.components = [discord.components.ActionRow(row) for row in view.to_components()]
        await client.sync(bot)
        for message in messages.values():
            message.edit.assert_not_awaited()
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
