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

    async def test_summary_pages_include_every_task_and_bounded_controls(self):
        import discord_m3_client as client
        rows = rules.tomorrow_rows([task(title='x' * 500) for _ in range(63)], date(2026, 10, 28), {})
        job = self.job('tomorrow', snapshot={'title': 'Plani', 'tasks': rows}, task_id=None)
        found = []
        for page in range(7):
            text, view = client.prompt(job, page), client.controls(job, page)
            self.assertLessEqual(len(text), 2000)
            select = next(item for item in view.children if item.custom_id.startswith('pf:m3:task:'))
            found.extend(item.value for item in select.options)
            self.assertTrue(all(len(item.custom_id or '') <= 100 for item in view.children))
            self.assertTrue(view.is_persistent())
        self.assertEqual(found, [row['task_id'] for row in rows])

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
