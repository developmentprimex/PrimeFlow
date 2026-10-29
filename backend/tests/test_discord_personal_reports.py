"""Personal report commands reuse current-day answers without claiming pushes."""
import unittest
import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
import discord_reports
import discord_m2_client
import discord_m3_client
from app.api.routers import discord_m2, discord_m3
from tests import test_discord_m2_database as m2_fixtures
from tests import test_discord_m3_database as m3_fixtures


class ReportUITests(unittest.IsolatedAsyncioTestCase):
    async def test_slash_reports_send_each_live_question_with_scheduled_text_and_controls(self):
        for kind, client in [('m2', discord_m2_client), ('m3', discord_m3_client)]:
            jobs = [{'id': str(uuid.uuid4()), 'kind': 'delivery', 'snapshot': {'title': f'Task {i}'},
                'discord_user_id': '11', 'task_id': str(uuid.uuid4()), 'answered': False} for i in range(3)]
            live = [dict(job, answered=True, choice='PO', answer={'action': 'PO'}) for job in jobs]
            channel = SimpleNamespace(send=AsyncMock())
            bot = SimpleNamespace(private_channel=AsyncMock(return_value=channel),
                bridge=AsyncMock(side_effect=[{'jobs': jobs, 'day': '2026-10-29'}, *live]))
            interaction = SimpleNamespace(guild_id=22, channel_id=33, user=SimpleNamespace(id=11),
                followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock())
            await discord_reports.show(bot, interaction, kind)
            self.assertEqual(channel.send.await_count, 3)
            for call, job in zip(channel.send.await_args_list, live):
                self.assertEqual(call.args[0], client.prompt(job))
                self.assertEqual(call.kwargs['view'].to_components(), client.controls(job).to_components())
                self.assertTrue(call.kwargs['suppress_embeds'])
                self.assertNotIn('reference', call.kwargs)
            self.assertEqual([call.args[0] for call in bot.bridge.await_args_list],
                [f'/bot/{kind}/report', *[f"/bot/{kind}/{job['id']}/open" for job in jobs]])
            interaction.followup.send.assert_not_awaited()
            interaction.edit_original_response.assert_awaited_once()

    async def test_empty_report_is_a_single_notice(self):
        bot = SimpleNamespace(private_channel=AsyncMock(),
            bridge=AsyncMock(return_value={'jobs': [], 'day': '2026-10-29'}))
        interaction = SimpleNamespace(guild_id=22, channel_id=33, user=SimpleNamespace(id=11),
            followup=SimpleNamespace(send=AsyncMock()))
        await discord_reports.show(bot, interaction, 'm2')
        interaction.followup.send.assert_awaited_once()
        self.assertIn('Nuk ke pika', interaction.followup.send.call_args.args[0])

    async def test_every_question_is_reachable_with_long_titles_and_persistent_controls(self):
        for kind in ('m2', 'm3'):
            jobs = [{'id': str(uuid.uuid4()), 'kind': 'delivery', 'snapshot': {'title': '*' * 200},
                'answered': index % 2 == 0} for index in range(65)]
            ids = []
            for page in range(6):
                content, view = discord_reports.report_view({'jobs': jobs, 'day': '2026-10-29'}, kind, page)
                self.assertLessEqual(len(content), 2000)
                self.assertTrue(view.is_persistent())
                self.assertLessEqual(len(view.children), 25)
                self.assertTrue(all(len(item.custom_id) <= 100 for item in view.children))
                ids.extend(item.custom_id.split(':')[-1] for item in view.children if ':question:' in item.custom_id)
            self.assertEqual(ids, [job['id'] for job in jobs])

    async def test_report_checks_private_channel_before_requesting_personal_data(self):
        bot = SimpleNamespace(private_channel=AsyncMock(side_effect=ValueError('private')), bridge=AsyncMock())
        interaction = SimpleNamespace(guild_id=22, channel_id=33, user=SimpleNamespace(id=11))
        with self.assertRaises(ValueError):
            await discord_reports.show(bot, interaction, 'm2')
        bot.bridge.assert_not_awaited()

    async def test_question_buttons_load_fresh_answers_in_the_same_message(self):
        for kind, client in [('m2', discord_m2_client), ('m3', discord_m3_client)]:
            qid = str(uuid.uuid4())
            job = {'id': qid, 'kind': 'delivery', 'snapshot': {'title': 'Delivery'},
                'discord_user_id': '11', 'task_id': str(uuid.uuid4()), 'answered': True,
                'choice': 'PO', 'answer': {'action': 'PO'}}
            interaction = SimpleNamespace(guild_id=22, channel_id=33, user=SimpleNamespace(id=11),
                data={'custom_id': f'pf:{kind}:question:{qid}'}, response=SimpleNamespace(defer=AsyncMock()),
                edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))
            bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(return_value=job))
            await client.handle(bot, interaction)
            bot.bridge.assert_awaited_once_with(f'/bot/{kind}/{qid}/open',
                {'discord_user_id': '11', 'guild_id': '22', 'channel_id': '33'})
            interaction.edit_original_response.assert_awaited_once()
            interaction.followup.send.assert_not_awaited()


@unittest.skipUnless(os.getenv('M2_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL schema')
class M2PersonalReportTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = m2_fixtures.M2DatabaseTests.asyncSetUp
    asyncTearDown = m2_fixtures.M2DatabaseTests.asyncTearDown
    fresh_data = m2_fixtures.M2DatabaseTests.fresh_data
    claim = m2_fixtures.M2DatabaseTests.claim
    reply = m2_fixtures.M2DatabaseTests.reply

    async def test_manual_report_is_personal_repeatable_and_does_not_claim_notifications(self):
        with patch.object(discord_m2.service, 'collection_open', return_value=False):
            async with self.sessions() as db:
                first = await discord_m2.personal_report(self.actor, db)
                q = await db.get(discord_m2.Question, uuid.UUID(first['jobs'][0]['id']))
                self.assertLessEqual(q.lease_until, datetime.now(timezone.utc))
                second = await discord_m2.personal_report(self.actor, db)
            self.assertEqual(len(first['jobs']), 1)
            self.assertEqual(first['jobs'][0]['id'], second['jobs'][0]['id'])
            self.assertTrue(all(job['discord_user_id'] == '11' for job in first['jobs']))
        scheduled = await self.claim()
        self.assertIn(first['jobs'][0]['id'], [job['id'] for job in scheduled])
        await self.reply(first['jobs'][0]['id'], reason_code='OTHER', comment='Saved answer')
        async with self.sessions() as db:
            reopened = await discord_m2.personal_report(self.actor, db)
        self.assertEqual(reopened['jobs'][0]['comment'], 'Saved answer')

    async def test_more_than_fifty_items_are_available_and_sent_message_is_preserved(self):
        from datetime import datetime, timezone
        from app.models.task import Task
        from app.models.discord_m2_question import DiscordM2Question
        async with self.sessions() as db:
            for index in range(55):
                task_id = uuid.uuid4()
                db.add(Task(id=task_id, title=f'Delivery {index}', assigned_to=self.uid,
                    status='TODO', is_active=True))
                self.data.setdefault('delivery', []).append({'task_id': str(task_id), 'title': f'Delivery {index}'})
            await db.commit()
            first = await discord_m2.personal_report(self.actor, db)
            self.assertEqual(len(first['jobs']), 56)
            q = await db.get(DiscordM2Question, uuid.UUID(first['jobs'][0]['id']))
            q.message_id, q.sent_at = '123456', datetime.now(timezone.utc)
            stamp, lease = q.sent_at, q.lease_until
            await db.commit()
            await discord_m2.personal_report(self.actor, db)
            self.assertEqual((q.message_id, q.sent_at, q.lease_until), ('123456', stamp, lease))

    async def test_wrong_channel_cannot_open_a_report(self):
        from fastapi import HTTPException
        actor = self.actor.model_copy(update={'channel_id': '999'})
        async with self.sessions() as db:
            with self.assertRaises(HTTPException) as raised:
                await discord_m2.personal_report(actor, db)
        self.assertEqual(raised.exception.status_code, 403)


@unittest.skipUnless(os.getenv('M2_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL schema')
class M3PersonalReportTests(unittest.IsolatedAsyncioTestCase):
    full_schema = True
    asyncSetUp = m3_fixtures.M3DatabaseTests.asyncSetUp
    asyncTearDown = m3_fixtures.M3DatabaseTests.asyncTearDown
    fresh_data = m3_fixtures.M3DatabaseTests.fresh_data
    claim = m3_fixtures.M3DatabaseTests.claim
    reply = m3_fixtures.M3DatabaseTests.reply
    setup_tomorrow = m3_fixtures.M3DatabaseTests.setup_tomorrow

    async def test_manual_report_outside_window_preserves_answers_and_scheduled_delivery(self):
        with patch.object(discord_m3.rules, 'collection_phase', return_value=None):
            async with self.sessions() as db:
                first = await discord_m3.personal_report(self.actor, db)
                for job in first['jobs']:
                    q = await db.get(discord_m3.Question, uuid.UUID(job['id']))
                    self.assertLessEqual(q.lease_until, datetime.now(timezone.utc))
                repeated = await discord_m3.personal_report(self.actor, db)
            self.assertTrue(first['jobs'])
            self.assertEqual([job['id'] for job in first['jobs']], [job['id'] for job in repeated['jobs']])
            self.assertTrue(all(job['discord_user_id'] == '11' for job in first['jobs']))
        scheduled = await self.claim()
        m3_ids = {job['id'] for job in first['jobs'] if job['kind'] in {'untouched', 'delivery', 'meeting'}}
        self.assertTrue(m3_ids <= {job['id'] for job in scheduled})
        tomorrow_ids = {job['id'] for job in first['jobs'] if job['kind'] not in {'untouched', 'delivery', 'meeting'}}
        self.assertTrue(tomorrow_ids <= {job['id'] for job in await self.claim('tomorrow')})
        job = next(job for job in first['jobs'] if job['kind'] == 'delivery')
        await self.reply(job, 'PO')
        async with self.sessions() as db:
            reopened = await discord_m3.personal_report(self.actor, db)
        saved = next(item for item in reopened['jobs'] if item['id'] == job['id'])
        self.assertEqual(saved['answer']['action'], 'PO')

    async def test_m3_command_includes_both_windows_and_bulk_confirmation_preserves_individual_reply(self):
        from datetime import time
        from app.models.task import Task
        from app.services.primeflow_report import report_timezone
        target = await self.setup_tomorrow(shared=True)
        today_id = uuid.uuid4()
        async with self.sessions() as db:
            db.add(Task(id=today_id, title='Today M3', assigned_to=self.uid, status='TODO', is_active=True,
                start_date=datetime.combine(self.day, time(8), report_timezone()),
                due_date=datetime.combine(self.day, time(16), report_timezone()), one_h_marker='M3'))
            await db.commit()
            first = await discord_m3.personal_report(self.actor, db)
            repeated = await discord_m3.personal_report(self.actor, db)
        jobs = first['jobs']
        self.assertEqual([job['id'] for job in jobs], [job['id'] for job in repeated['jobs']])
        self.assertTrue({'untouched', 'delivery', 'tomorrow_task', 'slot', 'tomorrow'} <= {job['kind'] for job in jobs})
        self.assertTrue(all(job['discord_user_id'] == '11' for job in jobs))
        tomorrow_start = next(i for i, job in enumerate(jobs) if job['kind'] in {'tomorrow_task', 'slot', 'tomorrow'})
        self.assertTrue(all(job['kind'] in {'untouched', 'delivery', 'meeting'} for job in jobs[:tomorrow_start]))
        self.assertEqual(jobs[-1]['kind'], 'tomorrow')
        child = next(job for job in jobs if job['kind'] == 'tomorrow_task')
        self.assertEqual(child['target_date'], target.isoformat())
        await self.reply(child, 'JO', comment='Needs more time')
        async with self.sessions() as db:
            report = await discord_m3.personal_report(self.actor, db)
            footer = report['jobs'][-1]
            live = await discord_m3.open_question(uuid.UUID(footer['id']), self.actor, db)
        await self.reply(footer, 'PO', plan_key=live['plan_key'])
        async with self.sessions() as db:
            saved = await discord_m3.open_question(uuid.UUID(child['id']), self.actor, db)
        self.assertEqual((saved['answer']['action'], saved['comment']), ('JO', 'Needs more time'))

    async def test_answer_remains_visible_when_progress_removes_task_from_section(self):
        async with self.sessions() as db:
            first = await discord_m3.personal_report(self.actor, db)
        job = next(job for job in first['jobs'] if job['kind'] == 'untouched')
        await self.reply(job, 'progress', progress=50, comment='Half done')
        async with self.sessions() as db:
            report = await discord_m3.personal_report(self.actor, db)
        saved = next(item for item in report['jobs'] if item['id'] == job['id'])
        self.assertEqual(saved['comment'], 'Half done')
        self.assertTrue(saved.get('resolved'))
