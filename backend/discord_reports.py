"""Personal report questions use the same cards as scheduled delivery."""
import math
import discord
import discord_ui as ui
import discord_m2_client as m2_client
import discord_m3_client as m3_client
from app.services.discord_m2 import KINDS as M2_KINDS
from app.services.discord_m3 import KINDS as M3_KINDS


def report_view(data, kind, page=0):
    jobs = data['jobs']
    title = f"📋 **Raporti yt {kind.upper()} · {data['day']}**"
    if not jobs:
        return title + '\nNuk ke pika për raportim sot.', None
    size = 12
    pages = math.ceil(len(jobs) / size)
    page = max(0, min(page, pages - 1))
    labels = M2_KINDS if kind == 'm2' else M3_KINDS
    lines, view = [], discord.ui.View(timeout=None)
    for index, job in enumerate(jobs[page * size:(page + 1) * size], page * size + 1):
        heading = ' '.join(ui.heading(job['snapshot']).split())[:40]
        state = '✅' if job.get('answered') or job.get('resolved') or job.get('platform_status') else '⏳'
        lines.append(f"`{index}.` {state} **{discord.utils.escape_markdown(heading)}** · {labels[job['kind']]}")
        view.add_item(discord.ui.Button(label=f"{index}. {heading}"[:80], row=(index - 1) % size // 4,
            custom_id=f"pf:{kind}:question:{job['id']}"))
    for label, target in [('◀', page - 1), ('▶', page + 1)]:
        view.add_item(discord.ui.Button(label=label, row=4, disabled=not 0 <= target < pages,
            custom_id=f'pf:reports:{kind}:{target}'))
    view.add_item(discord.ui.Button(label='Rifresko', row=4, custom_id=f'pf:reports:{kind}:{page}'))
    text = title + f'\n{len(jobs)} pika · Faqja {page + 1}/{pages}\nZgjidh një pikë për të parë ose plotësuar përgjigjen.\n\n' + '\n'.join(lines)
    return text, view


async def show(bot, interaction, kind, page=0, *, update=False):
    if kind not in {'m2', 'm3'}:
        raise ValueError('Zgjidh raportin M2 ose M3.')
    await bot.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
    actor = {
        'discord_user_id': str(interaction.user.id), 'guild_id': str(interaction.guild_id),
        'channel_id': str(interaction.channel_id)}
    data = await bot.bridge(f'/bot/{kind}/report', actor)
    if update:
        # Keep navigation on older report lists usable after the command change.
        content, view = report_view(data, kind, page)
        await interaction.edit_original_response(content=content, embeds=[], view=view,
            allowed_mentions=discord.AllowedMentions.none())
        return
    if not data['jobs']:
        await interaction.followup.send(
            f"📋 **Raporti yt {kind.upper()} · {data['day']}**\nNuk ke pika për raportim sot.",
            allowed_mentions=discord.AllowedMentions.none())
        return
    client = m2_client if kind == 'm2' else m3_client
    for job in data['jobs']:
        # Recheck ownership and answers just before showing each question.
        latest = await bot.bridge(f"/bot/{kind}/{job['id']}/open", actor)
        await interaction.followup.send(client.prompt(latest), view=client.controls(latest),
            suppress_embeds=True, allowed_mentions=discord.AllowedMentions.none())
