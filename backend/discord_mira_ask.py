"""Read-only Notetaker questions, delivered through private Discord responses."""

import discord
from discord import app_commands

from app.config import settings

FALLBACK = 'Për përgjigjen private përdor **/mira pyet**.'


def _answer_card(question, answer, sources):
    question = discord.utils.escape_markdown(question, ignore_links=False)
    answer = discord.utils.escape_markdown(answer, ignore_links=False)
    description = f'**Pyetja**\n{question}\n\n**Përgjigjja**\n{answer}'
    card = discord.Embed(title='MIRA · Pyet për takimet', description=description)
    if not sources:
        return [card]

    lines = []
    for source in sources:
        speaker = discord.utils.escape_markdown(source['speaker'], ignore_links=False)
        label = f"{source['date']} – {speaker} – {source['time']}".replace('[', '').replace(']', '')
        lines.append(f"[{label}]({source['url']})")
    source_title = 'Burimi' if len(lines) == 1 else 'Burimet'
    source_list = '\n'.join(lines)
    with_sources = f'{description}\n\n**{source_title}**\n{source_list}'
    if len(with_sources) <= 4096:
        card.description = with_sources
        return [card]

    # Keep links intact when the sources don't fit in the main embed.
    return [card, discord.Embed(title=source_title, description=source_list)]


async def answer(bot, user_id, guild_id, question):
    question = question.strip()
    if not question:
        return 'Shkruaj një pyetje për takimet e MIRA-s.', []
    if len(question) > 500:
        return 'Shkurtoje pyetjen në 500 shenja.', []
    try:
        result = await bot.bridge('/bot/voice-meetings/ask', {
            'discord_user_id': str(user_id), 'guild_id': str(guild_id), 'question': question,
        })
    except Exception as exc:
        return bot.error_message(exc), []
    return None, _answer_card(question, result['answer'], result['sources'])


def register(bot, guild):
    if not settings.DISCORD_MEETING_NOTES_ENABLED:
        return
    group = bot.tree.get_command('mira', guild=guild)
    if group is None:
        group = app_commands.Group(name='mira', description='MIRA dhe takimet në PrimeFlow')
        bot.tree.add_command(group, guild=guild)

    @group.command(name='pyet', description='Pyete MIRA-n për takimet e mëparshme')
    async def ask(interaction: discord.Interaction, pyetja: app_commands.Range[str, 3, 500]):
        await interaction.response.defer(thinking=True, ephemeral=True)
        content, embeds = await answer(bot, interaction.user.id, interaction.guild_id, pyetja)
        await interaction.followup.send(content, embeds=embeds, ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())


async def handle_mention(bot, message):
    """Consume direct questions even when DM delivery is blocked."""
    if not settings.DISCORD_MEETING_NOTES_ENABLED:
        return False
    content = message.content.strip()
    if not content.startswith('<@'):
        return False
    user = getattr(bot, 'user', None)
    if user is None:
        return False
    for prefix in (f'<@{user.id}>', f'<@!{user.id}>'):
        if content.startswith(prefix):
            question = content[len(prefix):].strip()
            break
    else:
        return False
    try:
        channel = await message.author.create_dm()
        text, embeds = await answer(bot, message.author.id, message.guild.id, question)
        await channel.send(text, embeds=embeds, allowed_mentions=discord.AllowedMentions.none(), suppress_embeds=False)
    except discord.HTTPException:
        await message.channel.send(FALLBACK, allowed_mentions=discord.AllowedMentions.none())
    return True
