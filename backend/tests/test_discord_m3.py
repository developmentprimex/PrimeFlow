"""Scheduling, task selection, ownership, and complete Discord M3 controls."""
import asyncio
import os
import unittest
import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/test')
os.environ.setdefault('JWT_SECRET', 'm3-tests-not-production')
from fastapi import HTTPException
from app.services import discord_m3 as rules
from app.api.routers import discord_m3 as api


def task(**fields):
    defaults = dict(id=uuid.uuid4(), title='Detyrë', status='TODO', phase='MEETINGS', is_active=True,
        completed_at=None, start_date=date(2026, 10, 27), due_date=date(2026, 10, 28), created_at=date(2026, 10, 26),
        system_template_origin_id=None, system_task_slot_id=None, origin_run_at=None,
        fast_task_group_id=None, is_deadline_important=False, is_1h_report=True, is_r1=False, one_h_report_slot=None)
    return SimpleNamespace(**(defaults | fields))


class M3RulesTests(unittest.TestCase):
    def test_early_test_does_not_consume_regular_delivery_or_its_future_lease(self):
        now = datetime.fromisoformat('2026-10-28T15:50:00+01:00')
        q = SimpleNamespace(day=now.date(), sent_at=now.replace(hour=11, minute=25),
            lease_until=now + timedelta(minutes=2), answered_at=None)
        self.assertTrue(rules.delivery_is_pending(q, now, 'm3'))
        q.sent_at = now
        self.assertFalse(rules.delivery_is_pending(q, now, 'm3'))
        q.sent_at = now.replace(hour=11)
        q.answered_at = now.replace(hour=12)
        self.assertFalse(rules.delivery_is_pending(q, now, 'm3'))
        q.answered_at, q.sent_at = None, now.replace(hour=16, minute=5)
        self.assertTrue(rules.delivery_is_pending(q, now.replace(hour=16, minute=10), 'tomorrow'))

    def test_schedule_boundaries_weekends_and_dst(self):
        with patch.object(rules, 'report_timezone', return_value=ZoneInfo('Europe/Budapest')):
            for stamp, expected in [('2026-10-27T15:49:59+01:00', None), ('2026-10-27T15:50:00+01:00', 'm3'),
                ('2026-10-27T16:09:59+01:00', 'm3'), ('2026-10-27T16:10:00+01:00', 'tomorrow'),
                ('2026-10-27T17:00:00+01:00', None), ('2026-10-24T16:10:00+02:00', None),
                ('2026-10-23T13:50:00+00:00', 'm3')]:
                self.assertEqual(rules.collection_phase(datetime.fromisoformat(stamp)), expected, stamp)
        self.assertEqual(rules.target_day(date(2026, 10, 30)), date(2026, 11, 2))

    def test_tomorrow_keeps_all_task_types_date_overrides_and_due_flags(self):
        day = date(2026, 10, 28)
        items = [task(), task(system_template_origin_id=uuid.uuid4(), is_deadline_important=True),
                 task(is_1h_report=False), task(status='DONE'), task(start_date=day + timedelta(days=1), due_date=day + timedelta(days=2)),
                 task(due_date=day - timedelta(days=1)), task(is_active=False)]
        rows = rules.tomorrow_rows(items, day, {items[0].id: '11:00'})
        self.assertEqual({row['task_id'] for row in rows}, {str(item.id) for item in items[:3]})
        self.assertEqual(next(row for row in rows if row['task_id'] == str(items[0].id))['slot'], '11:00')
        self.assertTrue(all(row['due_tomorrow'] for row in rows))
        self.assertTrue(any(row['is_system_task'] and row['deadline_important'] for row in rows))

    def test_missing_and_conflicting_slots_use_logical_groups_not_titles(self):
        group = uuid.uuid4()
        items = [task(fast_task_group_id=group, one_h_report_slot='11:00'),
                 task(fast_task_group_id=group, one_h_report_slot='10:00'),
                 task(one_h_report_slot='14:20'), task(), task(is_1h_report=False)]
        rows = rules.tomorrow_rows(items, date(2026, 10, 28), {})
        owners = {str(item.id): {f'uid{i}'} for i, item in enumerate(items)}
        questions = rules.slot_questions(rows, owners, {'uid0': 'RA', 'uid1': 'DV'})
        self.assertEqual({row['task_id'] for row in questions}, {str(items[i].id) for i in (0, 1, 3)})
        ra = next(row for row in questions if row['task_id'] == str(items[0].id))
        self.assertEqual(ra['peers'], [{'task_id': str(items[1].id), 'slot': '10:00', 'people': 'DV'}])
        self.assertFalse(ra['missing_slot'])
        items[1].one_h_report_slot = '11:00'
        questions = rules.slot_questions(rules.tomorrow_rows(items, date(2026, 10, 28), {}), owners, {})
        self.assertEqual([row['task_id'] for row in questions], [str(items[3].id)])

    def test_choices_require_comments_and_reject_wrong_action_and_invalid_dates(self):
        actor = dict(discord_user_id='1', guild_id='2', channel_id='3')
        for kind, action in [('delivery', 'JO'), ('untouched', 'done'), ('untouched', 'progress'), ('meeting', 'canceled')]:
            with self.assertRaises(HTTPException):
                api.validate_answer(SimpleNamespace(kind=kind), api.Answer(**actor, action=action))
        with self.assertRaises(HTTPException):
            api.validate_answer(SimpleNamespace(kind='delivery'), api.Answer(**actor, action='done', comment='x'))
        api.validate_answer(SimpleNamespace(kind='delivery'), api.Answer(**actor, action='PO'))
        with self.assertRaises(HTTPException):
            api.validate_answer(SimpleNamespace(kind='tomorrow_task'), api.Answer(**actor, action='postpone', comment='why'))

    def test_migration_has_one_head_and_all_model_columns(self):
        from io import StringIO
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from tests.test_migration_graph import migration_scripts
        from app.models.discord_m3_question import DiscordM3Question
        scripts = migration_scripts()
        self.assertEqual(len(scripts.get_heads()), 1)
        migration = scripts.get_revision('0169_discord_m3_questions').module
        output = StringIO()
        ops = Operations(MigrationContext.configure(dialect_name='postgresql', opts={'as_sql': True, 'output_buffer': output}))
        with patch.object(migration, 'op', ops):
            migration.upgrade()
        for column in DiscordM3Question.__table__.c:
            self.assertIn(column.name, output.getvalue())


class M3ControlsTests(unittest.IsolatedAsyncioTestCase):
    def job(self, kind, **values):
        return {'id': str(uuid.uuid4()), 'task_id': str(uuid.uuid4()), 'kind': kind,
            'target_date': '2026-10-28', 'discord_user_id': '11', 'snapshot': {'title': 'RA: Detyrë',
                'slot': '11:00', 'peers': [{'slot': '10:00', 'people': 'DV'}], 'due_tomorrow': True},
            'live_dates': {'start_date': '2026-10-27T08:00:25+01:00', 'due_date': '2026-10-28T16:00:00+01:00'}, **values}

    async def test_footer_has_only_bulk_yes_and_task_cards_have_four_actions(self):
        import discord_m3_client as client
        rows = rules.tomorrow_rows([task(title='x' * 500) for _ in range(63)], date(2026, 10, 28), {})
        job = self.job('tomorrow', snapshot={'title': 'Plani', 'tasks': rows}, task_id=None)
        self.assertLessEqual(len(client.prompt(job)), 2000)
        view = client.controls(job)
        self.assertEqual([item.label for item in view.children], ['Po për të gjitha'])
        self.assertTrue(view.is_persistent())
        for due in (False, True):
            item = self.job('tomorrow_task')
            item['snapshot']['due_tomorrow'] = due
            text = client.prompt(item)
            self.assertNotIn('\n', text)
            self.assertIn('RA: Detyrë', text)
            self.assertEqual([button.label for button in client.controls(item).children],
                ['Po, kryhet' if due else 'Po, punohet', 'Jo — shtyje', 'Hap detyrën', 'Koment'])

    async def test_m3_open_button_follows_postpone_in_same_row_and_stays_in_discord(self):
        import discord_m3_client as client
        for kind in ('untouched', 'delivery', 'tomorrow_task', 'slot'):
            for resolved in (None, 'Detyra është përfunduar.'):
                with self.subTest(kind=kind, resolved=resolved):
                    job = self.job(kind, resolved=resolved)
                    buttons = client.controls(job).children
                    opened = next(button for button in buttons if getattr(button, 'label', None) == 'Hap detyrën')
                    self.assertEqual(opened.custom_id, f"pf:m3:open:{job['id']}")
                    self.assertIsNone(opened.url)
                    self.assertEqual(opened.row, 2 if kind == 'slot' else 0)
                    postpone = next((button for button in buttons if getattr(button, 'custom_id', '') == f"pf:m3:postpone:{job['id']}"), None)
                    if postpone:
                        self.assertIs(buttons[buttons.index(postpone) + 1], opened)

    async def test_compact_task_shows_only_clean_first_line_and_link(self):
        import discord_m3_client as client
        job = self.job('tomorrow_task', comment='Long comment\n' * 100, answered=True, answer={'action': 'PO'})
        job['snapshot']['title'] = 'EH:[[added]]LH:[[/added]] 8/6 VS DIGITALIZIM\n[[done]]\nVery long task body'
        content = client.prompt(job)
        self.assertNotIn('\n', content)
        self.assertNotIn('[[added]]', content)
        self.assertNotIn('Very long', content)
        self.assertNotIn('Long comment', content)
        self.assertIn('8/6 VS DIGITALIZIM', content)
        self.assertIn('/tasks/' + job['task_id'], content)
        self.assertIn('](<', content)
        self.assertIn('>)', content)
        self.assertTrue(all(item.row == 0 for item in client.controls(job).children))

    async def test_open_task_pages_all_text_in_original_message_without_new_replies(self):
        import discord_m3_client as client
        job = self.job('untouched')
        from app.services.discord_task_tools import text_points
        title = 'Title\n' + '\n'.join(f'{index}. Full text {index}' for index in range(1, 401))
        description = 'Description first line\nDescription last line'
        detail = {'task': {'id': job['task_id'], 'title': title, 'description': description}, 'fingerprint': 'a' * 16,
            'title_points': text_points(title, 'title'), 'description_points': text_points(description, 'description')}
        interaction = Mock()
        interaction.guild_id, interaction.channel_id, interaction.user.id = 22, 33, 11
        interaction.data = {'custom_id': f"pf:m3:open:{job['id']}"}
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.message.edit = AsyncMock()
        interaction.message.content = '**TEST M3 · Rinesa Ahmedi · sikur ora 15:50**\nReport'
        bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(return_value=job),
            current_detail=AsyncMock(return_value=detail), remember_task=Mock(), task_cards={})
        await client.handle(bot, interaction)
        bot.current_detail.assert_awaited_once_with(interaction, job['task_id'])
        interaction.response.defer.assert_awaited_once_with()
        cards = client.task_ui.full_cards(detail['task'] | {'id': job['task_id']}, detail)
        self.assertGreater(len(cards), 1)
        first = interaction.message.edit.call_args.kwargs
        self.assertFalse(first['suppress'])
        self.assertTrue(first['content'].startswith('**TEST M3'))
        self.assertTrue(any(button.custom_id == f"pf:m3:return:{job['id']}" for button in first['view'].children))
        rendered = [first['embeds'][0].description]
        for page in range(1, len(cards)):
            interaction.data = {'custom_id': f"pf:m3:detail:{job['id']}:{page}"}
            await client.handle(bot, interaction)
            rendered.append(interaction.message.edit.call_args.kwargs['embeds'][0].description)
        combined = ''.join(rendered)
        self.assertEqual(combined.count('Full text'), 400)
        self.assertIn('Description first line', combined)
        self.assertIn('Description last line', combined)
        for card in cards:
            self.assertLessEqual(len(card.description), 4000)
            self.assertLessEqual(len(card), 6000)
        interaction.followup.send.assert_not_awaited()
        self.assertEqual(interaction.message.edit.await_count, len(cards))

    async def test_return_to_m3_restores_latest_answer_and_removes_expanded_card(self):
        import discord_m3_client as client
        job = self.job('tomorrow_task', answered=True, answer={'action': 'PO'}, comment='Saved')
        interaction = Mock()
        interaction.guild_id, interaction.channel_id, interaction.user.id = 22, 33, 11
        interaction.data = {'custom_id': f"pf:m3:return:{job['id']}"}
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        interaction.message.edit = AsyncMock()
        interaction.message.content = ''
        bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(return_value=job))
        await client.handle(bot, interaction)
        restored = interaction.message.edit.call_args.kwargs
        self.assertEqual(restored['content'], client.prompt(job))
        self.assertEqual(restored['embeds'], [])
        self.assertTrue(restored['suppress'])
        self.assertIn('✅ Po', restored['content'])
        self.assertTrue(any(button.custom_id == f"pf:m3:open:{job['id']}" for button in restored['view'].children))
        interaction.followup.send.assert_not_awaited()
        bot.bridge.assert_awaited_once_with(f"/bot/m3/{job['id']}/open", {'discord_user_id': '11', 'guild_id': '22', 'channel_id': '33'})

    async def test_date_form_autofills_both_and_preserves_untouched_instant(self):
        import discord_m3_client as client
        job = self.job('untouched')
        modal = client.AnswerModal(None, job, 'postpone')
        self.assertEqual(modal.dates['start_date'].default, '27.10.2026 08:00')
        self.assertEqual(modal.dates['due_date'].default, '28.10.2026 16:00')
        self.assertEqual(client.form_date(modal.dates['start_date'].default, job['live_dates']['start_date']), job['live_dates']['start_date'])
        self.assertTrue(modal.comment.required)

    async def test_slot_buttons_parse_colons_and_allow_keep_or_peer(self):
        import discord_m3_client as client
        job = self.job('slot')
        view = client.controls(job)
        self.assertEqual([item.label for item in view.children[:2]], ['Konfirmoj 11:00', 'Si kolegu: 10:00'])
        interaction = Mock()
        interaction.guild_id, interaction.channel_id, interaction.user.id = 22, 33, 11
        interaction.data = {'custom_id': view.children[1].custom_id}
        interaction.response.defer = AsyncMock()
        bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(return_value=job))
        with patch.object(client, 'save', AsyncMock()) as save:
            await client.handle(bot, interaction)
        self.assertEqual(bot.bridge.call_args.args[0], f"/bot/m3/{job['id']}/open")
        self.assertEqual(save.call_args.kwargs['slot'], '10:00')

    async def test_postpone_opens_modal_immediately_without_date_kind_question(self):
        import discord_m3_client as client
        job = self.job('tomorrow_task')
        interaction = Mock()
        interaction.guild_id, interaction.channel_id, interaction.user.id = 22, 33, 11
        interaction.data = {'custom_id': f"pf:m3:postpone:{job['id']}"}
        interaction.response.send_modal = AsyncMock()
        bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(return_value=job))
        await client.handle(bot, interaction)
        self.assertEqual(set(interaction.response.send_modal.call_args.args[0].dates), {'start_date', 'due_date'})

    async def test_old_no_button_also_opens_postponement_form(self):
        import discord_m3_client as client
        job = self.job('tomorrow_task')
        interaction = Mock()
        interaction.guild_id, interaction.channel_id, interaction.user.id = 22, 33, 11
        interaction.data = {'custom_id': f"pf:m3:JO:{job['id']}"}
        interaction.response.send_modal = AsyncMock()
        bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(return_value=job))
        await client.handle(bot, interaction)
        modal = interaction.response.send_modal.call_args.args[0]
        self.assertEqual(modal.action, 'postpone')
        self.assertEqual(set(modal.dates), {'start_date', 'due_date'})
        self.assertTrue(modal.comment.required)

    async def test_yes_is_saved_even_if_optional_comment_modal_is_closed(self):
        import discord_m3_client as client
        job = self.job('delivery')
        interaction = Mock()
        interaction.guild_id, interaction.channel_id, interaction.user.id = 22, 33, 11
        interaction.data = {'custom_id': f"pf:m3:PO:{job['id']}"}
        interaction.response.send_modal = AsyncMock()
        bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(return_value=job))
        with patch.object(client, 'save', AsyncMock(return_value=job)) as save:
            await client.handle(bot, interaction)
        self.assertEqual(save.call_args.args[3], 'PO')
        self.assertFalse(interaction.response.send_modal.call_args.args[0].comment.required)

    async def test_held_meeting_saves_with_one_click(self):
        import discord_m3_client as client
        job = self.job('meeting')
        interaction = Mock()
        interaction.guild_id, interaction.channel_id, interaction.user.id = 22, 33, 11
        interaction.data = {'custom_id': f"pf:m3:held:{job['id']}"}
        interaction.response.defer = AsyncMock()
        bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(return_value=job))
        with patch.object(client, 'save', AsyncMock()) as save:
            await client.handle(bot, interaction)
        self.assertEqual(save.call_args.args[3], 'held')
        interaction.response.send_modal.assert_not_called()
