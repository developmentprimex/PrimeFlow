"""M2 schedule, classification, validation, and Discord reply controls."""
import asyncio
import importlib.util
import os
import unittest
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/primeflow_test')
os.environ.setdefault('JWT_SECRET', 'discord-m2-tests-not-for-production')

from fastapi import HTTPException
from app.services import discord_m2 as service
from app.api.routers import discord_m2 as api


class M2RulesTests(unittest.TestCase):
    def test_migration_has_the_model_columns_and_one_head(self):
        from io import StringIO
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from tests.test_migration_graph import migration_scripts
        from app.models.discord_m2_question import DiscordM2Question
        scripts = migration_scripts()
        self.assertEqual(len(scripts.get_heads()), 1)
        self.assertIn('0162_discord_m2_questions', {
            revision.revision for revision in scripts.iterate_revisions(scripts.get_current_head(), 'base')
        })
        migration = scripts.get_revision('0162_discord_m2_questions').module
        output = StringIO()
        operations = Operations(MigrationContext.configure(dialect_name='postgresql', opts={'as_sql': True, 'output_buffer': output}))
        with patch.object(migration, 'op', operations):
            migration.upgrade()
        sync_migration = scripts.get_revision('0168_discord_answer_sync').module
        with patch.object(sync_migration, 'op', operations):
            sync_migration.upgrade()
        for column in DiscordM2Question.__table__.c:
            self.assertIn(column.name, output.getvalue())
        self.assertIn('uq_discord_m2_question', output.getvalue())

    def test_1145_weekday_window_uses_report_timezone(self):
        with patch.object(service, 'report_timezone', return_value=ZoneInfo('Europe/Budapest')):
            for stamp, expected in [('2026-10-26T11:44:59+01:00', False), ('2026-10-26T11:45:00+01:00', True),
                                    ('2026-10-26T11:59:59+01:00', True), ('2026-10-26T12:00:00+01:00', False),
                                    ('2026-10-25T11:45:00+01:00', False), ('2026-10-23T09:45:00+00:00', True)]:
                self.assertEqual(service.collection_open(datetime.fromisoformat(stamp)), expected, stamp)

    def test_postponements_deduplicate_across_sections_and_bind_to_latest_move(self):
        row = {'task_id': str(uuid.uuid4()), 'postponement_kind': 'start_due', 'due_date': '2026-10-27'}
        self.assertEqual(service.question_rows({'postponed': [row], 'postponed_am': [row]}), [('postponed', row)])
        self.assertNotEqual(service.context_key('postponed', row), service.context_key('postponed', {**row, 'last_move_at': 'new'}))
        for kind in ('start', 'due', 'start_due'):
            self.assertIn(kind, service.MOVEMENTS)

    def test_explained_moves_and_done_work_do_not_request_redundant_answers(self):
        row = {'task_id': str(uuid.uuid4()), 'status': 'DONE'}
        self.assertEqual(service.question_rows({'unfinished_priority': [row], 'delivery': [row]}), [('delivery', row)])
        explained = {**row, 'status': 'TODO', 'postponement_explanation': True, 'comment': 'Already explained'}
        self.assertEqual(service.question_rows({'postponed': [explained]}), [])

    def test_no_delivery_requires_explanation_and_reason_codes_are_platform_codes(self):
        for choice in (None, 'JO'):
            with self.assertRaises(ValueError):
                service.validate_answer('delivery', None, '  ', choice)
        self.assertEqual(service.validate_answer('delivery', None, '', 'PO'), (None, '', 'PO'))
        self.assertEqual(service.validate_answer('delivery', None, ' Waiting for QA ', 'JO'), (None, 'Waiting for QA', 'JO'))
        for kind in ('unfinished', 'postponed', 'progress'):
            with self.assertRaises(ValueError):
                service.validate_answer(kind, 'invented', 'Text', None)
            with self.assertRaises(ValueError):
                service.validate_answer(kind, 'OTHER', '', None)
            self.assertEqual(service.validate_answer(kind, 'OTHER', 'Text', None), ('OTHER', 'Text', None))

    def test_duplicate_submission_does_not_append_comment_again(self):
        question = SimpleNamespace(answered_at=datetime.now(), task_id=uuid.uuid4(), kind='delivery',
                                   reason_code=None, comment='', choice='PO', platform_answered_at=None)
        db = SimpleNamespace(commit=AsyncMock(), execute=AsyncMock())
        with patch.object(api, 'own_question', AsyncMock(return_value=(question, None, SimpleNamespace(id=uuid.uuid4())))), \
             patch.object(api, 'task_owned', AsyncMock(return_value=SimpleNamespace(status='TODO'))):
            result = asyncio.run(api.answer(uuid.uuid4(), api.Answer(discord_user_id='1', guild_id='2', channel_id='3', choice='PO'), db))
        self.assertTrue(result['ok'])
        db.execute.assert_not_awaited()

    def test_foreign_question_is_rejected_before_task_access(self):
        link = SimpleNamespace(id=uuid.uuid4())
        question = SimpleNamespace(link_id=uuid.uuid4())
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: question)))
        with patch.object(api, 'identity', AsyncMock(return_value=(link, SimpleNamespace()))), \
             patch.object(api, 'task_owned', AsyncMock()) as owned:
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(api.own_question(db, uuid.uuid4(), None))
        self.assertEqual(raised.exception.status_code, 403)
        owned.assert_not_awaited()

    def test_postponement_reply_never_writes_or_overwrites_manual_report_comment(self):
        task_id = uuid.uuid4()
        question = SimpleNamespace(day=datetime.now().date(), task_id=task_id, kind='postponed',
                                   context_key='test', comment='Discord explanation', reason_code='OTHER')
        user = SimpleNamespace(full_name='Rinesa', username='rinesa')
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(question, user)])))
        for existing in ({}, {f'postponed_comment:{task_id}': 'Independent meeting comment'}):
            report = SimpleNamespace(manual_answers=dict(existing))
            asyncio.run(api.update_report_answers(db, report, question))
            self.assertEqual(report.manual_answers.get(f'postponed_comment:{task_id}'), existing.get(f'postponed_comment:{task_id}'))
            self.assertEqual(report.manual_answers[f'postponed_reason:{task_id}'], 'OTHER')


@unittest.skipUnless(importlib.util.find_spec('discord'), 'discord.py is optional')
class M2DiscordTests(unittest.TestCase):
    def test_yes_opens_optional_comment_and_saves_even_without_submitting_it(self):
        import discord_m2_client as client
        async def check():
            job = {'id': str(uuid.uuid4()), 'task_id': str(uuid.uuid4()), 'kind': 'delivery',
                   'discord_user_id': '3', 'snapshot': {'title': 'Delivery'}, 'answered': True, 'choice': 'JO',
                   'comment': 'Not ready yet', 'answered_at': datetime.now().isoformat()}
            latest = {**job, 'choice': 'PO', 'comment': ''}
            interaction = SimpleNamespace(guild_id=1, channel_id=2, user=SimpleNamespace(id=3),
                data={'custom_id': f"pf:m2:reply:{job['id']}:PO"},
                message=SimpleNamespace(content='Original M2 question', edit=AsyncMock()),
                response=SimpleNamespace(send_modal=AsyncMock(), defer=AsyncMock()),
                followup=SimpleNamespace(send=AsyncMock()))
            bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(side_effect=[job, {'ok': True}, latest]))
            await client.handle(bot, interaction)
            interaction.response.defer.assert_not_awaited()
            interaction.response.send_modal.assert_awaited_once()
            modal = interaction.response.send_modal.call_args.args[0]
            self.assertFalse(modal.comment.required)
            self.assertEqual(modal.initial_save.result(), latest)
            interaction.followup.send.assert_not_awaited()
            interaction.message.edit.assert_awaited_once()
            payload = bot.bridge.call_args_list[1].args[1]
            self.assertEqual(payload['choice'], 'PO')
            self.assertEqual(payload['comment'], '')
            self.assertIn('E dorëzuar', interaction.message.edit.call_args.kwargs['content'])
        asyncio.run(check())

    def test_comment_submit_waits_for_yes_save_and_uses_its_new_version(self):
        import discord_m2_client as client
        async def check():
            job = {'id': str(uuid.uuid4()), 'kind': 'delivery', 'choice': 'JO', 'answered_at': 'old'}
            latest = {**job, 'choice': 'PO', 'answered_at': 'new'}
            bot = SimpleNamespace(error_message=str)
            modal = client.ReplyModal(bot, job, choice='PO')
            modal.initial_save = asyncio.get_running_loop().create_future()
            interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
            with patch.object(client, 'save_reply', AsyncMock()) as save:
                submission = asyncio.create_task(modal.on_submit(interaction))
                await asyncio.sleep(0)
                save.assert_not_awaited()
                modal.initial_save.set_result(latest)
                await submission
                self.assertEqual(save.call_args.args[2]['answered_at'], 'new')
                interaction.followup.send.assert_not_awaited()
        asyncio.run(check())

    def test_yes_comment_is_optional_and_separate_from_the_yes_button(self):
        import discord_m2_client as client
        async def check():
            job = {'id': str(uuid.uuid4()), 'kind': 'delivery', 'answered': True, 'choice': 'PO',
                   'comment': 'Delivered later', 'answered_at': datetime.now().isoformat()}
            interaction = SimpleNamespace(guild_id=1, channel_id=2, user=SimpleNamespace(id=3),
                data={'custom_id': f"pf:m2:comment:{job['id']}"}, response=SimpleNamespace(send_modal=AsyncMock()))
            bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(return_value=job))
            await client.handle(bot, interaction)
            modal = interaction.response.send_modal.call_args.args[0]
            self.assertEqual(modal.choice, 'PO')
            self.assertFalse(modal.comment.required)
            self.assertEqual(modal.comment.default, 'Delivered later')
            self.assertEqual(modal.comment.label, 'Komenti (opsional)')
            self.assertTrue(client.ReplyModal(bot, {**job, 'choice': 'JO'}, choice='JO').comment.required)
        asyncio.run(check())

    def test_modal_success_updates_question_without_a_success_bubble(self):
        import discord_m2_client as client
        async def check():
            job = {'id': str(uuid.uuid4()), 'task_id': str(uuid.uuid4()), 'kind': 'delivery', 'answered': True,
                   'choice': 'PO', 'comment': 'Delivered', 'discord_user_id': '3', 'snapshot': {'title': 'Delivery'}}
            message = SimpleNamespace(content='M2', edit=AsyncMock())
            interaction = SimpleNamespace(guild_id=1, channel_id=2, user=SimpleNamespace(id=3),
                response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
            bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(side_effect=[{'ok': True}, job]), error_message=str)
            modal = client.ReplyModal(bot, job, choice='PO', source_message=message)
            await modal.on_submit(interaction)
            message.edit.assert_awaited_once()
            interaction.followup.send.assert_not_awaited()
        asyncio.run(check())

    def test_question_controls_preserve_task_identity_and_platform_reasons(self):
        import discord_m2_client as client
        async def check():
            for kind in ('unfinished', 'postponed', 'progress', 'delivery', 'continuation'):
                job = {'id': str(uuid.uuid4()), 'task_id': str(uuid.uuid4()), 'kind': kind, 'discord_user_id': '12',
                       'snapshot': {'title': 'Task', 'postponement_kind': 'start_due', 'old_start_date': '2026-10-26',
                                    'start_date': '2026-10-27', 'old_due_date': '2026-10-26', 'due_date': '2026-10-28'},
                       'reasons': [{'value': code, 'label': label} for code, label in service.REASON_LABELS.items()]}
                view = client.controls(job)
                self.assertEqual(view.children[-2].custom_id, f"pf:m2:open:{job['id']}")
                self.assertIsNone(view.children[-2].url)
                self.assertEqual(view.children[-1].custom_id, 'pf:reports:m2:0')
                self.assertTrue(view.is_persistent())
                if kind in {'delivery', 'continuation'}:
                    self.assertEqual(len(view.children), 5 if kind == 'continuation' else 4)
                else:
                    self.assertEqual({option.value for option in view.children[0].options}, set(service.REASON_LABELS))
                if kind == 'postponed':
                    self.assertIn('Start dhe Due', client.prompt(job))
                    self.assertIn('2026-10-28', client.prompt(job))
        asyncio.run(check())

    def test_answered_and_approved_questions_still_open_in_discord(self):
        import discord_m2_client as client
        async def check():
            job = {'id': str(uuid.uuid4()), 'task_id': str(uuid.uuid4()), 'kind': 'continuation'}
            for state in ({'platform_status': 'Saved'}, {'postponement': {'status': 'APPROVED'}}):
                view = client.controls(job | state)
                self.assertEqual(len(view.children), 2)
                self.assertEqual(view.children[0].custom_id, f"pf:m2:open:{job['id']}")
                self.assertIsNone(view.children[0].url)
        asyncio.run(check())

    def test_open_and_page_full_task_in_same_message_then_return_to_latest_m2_answer(self):
        import discord_m2_client as client
        import discord_ui as ui
        from unittest.mock import Mock
        async def check():
            job = {'id': str(uuid.uuid4()), 'task_id': str(uuid.uuid4()), 'kind': 'delivery',
                'discord_user_id': '3', 'snapshot': {'title': 'Task'}, 'answered': False}
            detail = {'task': {'id': job['task_id'], 'title': 'Task', 'status': 'TODO'}, 'fingerprint': 'a' * 16,
                'title_points': [{'number': index, 'text': f'Line {index}', 'done': False} for index in range(1, 401)],
                'description_points': []}
            message = SimpleNamespace(content='**TEST M2 · sot, sikur ora 11:50**\nQuestion', edit=AsyncMock())
            interaction = SimpleNamespace(guild_id=1, channel_id=2, user=SimpleNamespace(id=3), message=message,
                data={'custom_id': f"pf:m2:open:{job['id']}"},
                response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
            bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(return_value=job),
                current_detail=AsyncMock(return_value=detail), remember_task=Mock(), task_cards={})
            await client.handle(bot, interaction)
            interaction.response.defer.assert_awaited_once_with()
            first = message.edit.call_args.kwargs
            self.assertFalse(first['suppress'])
            self.assertTrue(first['content'].startswith('**TEST M2'))
            self.assertTrue(any(button.custom_id == f"pf:m2:return:{job['id']}" for button in first['view'].children))
            self.assertTrue(any(button.label == 'Kërko shtyrje' for button in first['view'].children if hasattr(button, 'label')))
            pages = ui.full_cards(detail['task'], detail)
            self.assertGreater(len(pages), 1)
            rendered = [first['embeds'][0].description]
            for page in range(1, len(pages)):
                interaction.data = {'custom_id': f"pf:m2:detail:{job['id']}:{page}"}
                await client.handle(bot, interaction)
                rendered.append(message.edit.call_args.kwargs['embeds'][0].description)
            self.assertEqual(''.join(rendered).count('⬜ Line '), 400)
            bot.bridge.return_value = job | {'answered': True, 'choice': 'PO', 'comment': 'Saved'}
            interaction.data = {'custom_id': f"pf:m2:return:{job['id']}"}
            await client.handle(bot, interaction)
            restored = message.edit.call_args.kwargs
            self.assertEqual(restored['embeds'], [])
            self.assertIn('E dorëzuar', restored['content'])
            self.assertTrue(restored['content'].startswith('**TEST M2'))
            self.assertTrue(restored['suppress'])
            interaction.followup.send.assert_not_awaited()
            self.assertTrue(all(call.args[0] == f"/bot/m2/{job['id']}/open" for call in bot.bridge.call_args_list))
        asyncio.run(check())
