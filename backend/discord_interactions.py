"""Keep slow form preparation within Discord's initial response deadline."""
import asyncio

import discord

MODAL_PREPARE_SECONDS = 1.25


async def prepare_modal(interaction, load):
    """Return (data, deferred), leaving room to send the initial response."""
    pending = asyncio.create_task(load())
    try:
        done, _ = await asyncio.wait({pending}, timeout=MODAL_PREPARE_SECONDS)
        deferred = not done
        if deferred:
            await interaction.response.defer(ephemeral=True, thinking=True)
        return await pending, deferred
    finally:
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


async def open_modal(interaction, modal, *, deferred=False):
    if not deferred:
        await interaction.response.send_modal(modal)
        return
    # Discord cannot open a modal after defer. A fresh click opens the already
    # prepared form without repeating the slow network calls.
    view = discord.ui.View(timeout=600)
    button = discord.ui.Button(label='Hap formularin', style=discord.ButtonStyle.primary)
    owner = interaction.user.id

    async def open_prepared(click):
        if click.user.id != owner:
            await click.response.send_message('Ky formular është për personin që e kërkoi.', ephemeral=True)
            return
        await click.response.send_modal(modal)
        button.disabled = True
        view.stop()
        await click.message.edit(view=view)

    button.callback = open_prepared
    view.add_item(button)
    await interaction.edit_original_response(content='Formulari është gati.', view=view)
