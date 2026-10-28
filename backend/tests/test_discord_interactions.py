"""Exercise slow network preparation and the fresh modal interaction."""
import asyncio
import os
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('DATABASE_URL', 'postgresql+asyncpg://test:test@127.0.0.1/test')
os.environ.setdefault('JWT_SECRET', 'discord-deadline-tests')

import discord_interactions as replies
import discord_m2_client as m2
import discord_m3_client as m3


class InteractionDeadlineTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self, custom_id):
        return SimpleNamespace(guild_id=1, channel_id=2, user=SimpleNamespace(id=3),
            data={'custom_id': custom_id}, message=SimpleNamespace(edit=AsyncMock(), content=''),
            response=SimpleNamespace(defer=AsyncMock(), send_modal=AsyncMock()),
            edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))

    async def test_slow_m2_and_m3_forms_acknowledge_before_loading_finishes(self):
        for client, prefix in ((m2, 'm2'), (m3, 'm3')):
            for choice in ('PO', 'JO'):
                with self.subTest(prefix=prefix, choice=choice):
                    job = {'id': str(uuid.uuid4()), 'kind': 'delivery', 'snapshot': {'title': 'Task'},
                           'choice': None, 'answered_at': None}
                    custom_id = f"pf:m2:reply:{job['id']}:{choice}" if prefix == 'm2' else f"pf:m3:{choice}:{job['id']}"
                    interaction = self.interaction(custom_id)
                    release = asyncio.Event()

                    async def load(*args):
                        await release.wait()
                        return job

                    bot = SimpleNamespace(private_channel=AsyncMock(), bridge=AsyncMock(side_effect=load))
                    save_name = 'save_reply' if prefix == 'm2' else 'save'
                    with patch.object(replies, 'MODAL_PREPARE_SECONDS', 0), \
                         patch.object(client, save_name, AsyncMock(return_value=job)) as save:
                        running = asyncio.create_task(client.handle(bot, interaction))
                        for _ in range(20):
                            await asyncio.sleep(0)
                            if interaction.response.defer.await_count:
                                break
                        interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
                        self.assertFalse(running.done())
                        release.set()
                        await running
                        interaction.response.send_modal.assert_not_awaited()
                        view = interaction.edit_original_response.call_args.kwargs['view']
                        click = self.interaction('prepared')
                        await view.children[0].callback(click)
                        modal = click.response.send_modal.call_args.args[0]
                        self.assertIs(modal.source_message, interaction.message)
                        if choice == 'PO':
                            save.assert_awaited_once()
                            self.assertIs(modal.initial_save.result(), job)
                            self.assertFalse(modal.comment.required)
                        else:
                            save.assert_not_awaited()
                            self.assertTrue(modal.comment.required)

    async def test_task_open_acknowledges_even_before_discord_permission_lookup(self):
        for client, prefix in ((m2, 'm2'), (m3, 'm3')):
            interaction = self.interaction(f'pf:{prefix}:open:{uuid.uuid4()}')
            async def permissions(*args):
                interaction.response.defer.assert_awaited_once_with()
                raise ValueError('Access denied')
            bot = SimpleNamespace(private_channel=AsyncMock(side_effect=permissions), bridge=AsyncMock())
            with self.assertRaisesRegex(ValueError, 'Access denied'):
                await client.handle(bot, interaction)
            bot.bridge.assert_not_awaited()

    async def test_slow_loader_failure_is_propagated_after_acknowledgement(self):
        interaction = self.interaction('prepared')
        async def fail():
            await asyncio.sleep(0.01)
            raise ValueError('Revoked link')
        with patch.object(replies, 'MODAL_PREPARE_SECONDS', 0):
            with self.assertRaisesRegex(ValueError, 'Revoked link'):
                await replies.prepare_modal(interaction, fail)
        interaction.response.defer.assert_awaited_once()
        interaction.edit_original_response.assert_not_awaited()

    async def test_prepared_form_rejects_another_user(self):
        interaction = self.interaction('prepared')
        modal = SimpleNamespace()
        await replies.open_modal(interaction, modal, deferred=True)
        view = interaction.edit_original_response.call_args.kwargs['view']
        click = self.interaction('prepared')
        click.user.id = 99
        click.response.send_message = AsyncMock()
        await view.children[0].callback(click)
        click.response.send_modal.assert_not_awaited()
        click.response.send_message.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
