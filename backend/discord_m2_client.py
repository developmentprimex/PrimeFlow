"""Discord controls for M2; every reply is bound to a durable question ID."""
from __future__ import annotations

import hashlib
import asyncio
import discord
import discord_ui as task_ui
from discord_interactions import prepare_modal, open_modal
from app.services.discord_m2 import KINDS, MOVEMENTS


def actor(interaction):
    return {'discord_user_id': str(interaction.user.id), 'guild_id': str(interaction.guild_id),
            'channel_id': str(interaction.channel_id)}


def prompt(job):
    row = job['snapshot']
    if job.get('platform_status'):
        choice = ''
        if job.get('platform_answered') and job.get('choice'):
            choice = ('Vazhdon në PM: ' if job['kind'] == 'continuation' else 'Dorëzuar: ') + job['choice'] + '\n'
        return f"**M2 · {KINDS[job['kind']]}**\n**{row['title']}**\n\n{choice}✅ {job['platform_status']}"[:1900]
    if job['kind'] in {'delivery', 'continuation'}:
        pm = job['kind'] == 'continuation'
        text = f"<@{job['discord_user_id']}> **M2 · {'PM' if pm else 'Dorëzimi'}**\n**{row['title']}**"
        if pm and job.get('postponement', {}).get('status') == 'APPROVED':
            return text + '\n\n✅ **Shtyrja u konfirmua nga Diellza.**'
        if job.get('answered'):
            text += ('\n\n✅ **Vazhdon në PM**' if pm else '\n\n✅ **E dorëzuar**') if job.get('choice') == 'PO' else ('\n\n⏸ **Nuk vazhdon në PM**' if pm else '\n\n⏳ **Ende pa dorëzuar**')
        else:
            text += '\n\nA vazhdon në PM?' if pm else '\n\nA e ke dorëzuar detyrën?'
        if job.get('postponement'):
            from app.services.discord_m2_postponements import STATUS_LABELS
            text += '\n' + STATUS_LABELS[job['postponement']['status']]
        return text[:1900]
    text = f"<@{job['discord_user_id']}> **M2 · {KINDS[job['kind']]}**\n{row['title']}"
    if job['kind'] == 'postponed':
        text += f"\n**{MOVEMENTS.get(row.get('postponement_kind'), 'Shtyrje')}**"
        for field, label in (('start', 'Start'), ('due', 'Due')):
            if row.get(f'old_{field}_date') != row.get(f'{field}_date'):
                text += f"\n{label}: {row.get(f'old_{field}_date') or '—'} → {row.get(f'{field}_date') or '—'}"
        text += '\nZgjidh arsyen dhe shpjego pse u shty.'
    elif job['kind'] == 'progress':
        text += f"\nStatusi: {row.get('status', '—')} · Progresi: {row.get('progress', 0)}%\nShëno progresin, arsyen dhe çfarë ka mbetur."
    else:
        text += '\nPse nuk është kryer? Shëno arsyen dhe komentin.'
    if job.get('answered'):
        value = job.get('choice') or next((reason['label'] for reason in job['reasons'] if reason['value'] == job.get('reason_code')), '')
        text += f"\n\n**Përgjigjja e fundit: {value}**"
    return text[:1900]


def controls(job):
    view = discord.ui.View(timeout=None)
    def finish():
        view.add_item(discord.ui.Button(label='Raporti M2', custom_id='pf:reports:m2:0', row=4))
        return view
    open_task = discord.ui.Button(label='Hap detyrën', custom_id=f"pf:m2:open:{job['id']}")
    if job.get('platform_status'):
        view.add_item(open_task)
        return finish()
    if job['kind'] == 'continuation' and job.get('postponement', {}).get('status') == 'APPROVED':
        view.add_item(open_task)
        return finish()
    if job['kind'] in {'delivery', 'continuation'}:
        view.add_item(discord.ui.Button(label='Po, vazhdon' if job['kind'] == 'continuation' else 'Po, e dorëzova', style=discord.ButtonStyle.success,
            custom_id=f"pf:m2:reply:{job['id']}:PO"))
        if job.get('choice') == 'PO':
            view.add_item(discord.ui.Button(label='Ndrysho komentin' if job.get('comment') else 'Shto koment (opsional)',
                style=discord.ButtonStyle.secondary, custom_id=f"pf:m2:comment:{job['id']}"))
        view.add_item(discord.ui.Button(label='Jo — shëno pse', style=discord.ButtonStyle.secondary,
            custom_id=f"pf:m2:reply:{job['id']}:JO"))
        if job['kind'] == 'continuation':
            pending = job.get('postponement', {}).get('status') == 'PENDING'
            view.add_item(discord.ui.Button(label='Në pritje të konfirmimit' if pending else 'Kërko shtyrje',
                style=discord.ButtonStyle.secondary, custom_id=f"pf:m2a:request:{job['id']}", disabled=pending))
    else:
        view.add_item(discord.ui.Select(placeholder='Zgjidh arsyen dhe shto komentin',
            custom_id=f"pf:m2:reason:{job['id']}",
            options=[discord.SelectOption(label=reason['label'][:100], value=reason['value']) for reason in job['reasons']]))
    view.add_item(open_task)
    return finish()


def report_content(job, message):
    return task_ui.report_card_content(job, message, report_kind='m2', prompt=prompt)


async def show_detail(bot, interaction, job, detail, page=0, *, notice=None):
    await task_ui.show_report_card(bot, interaction, job, detail, page, report_kind='m2', prompt=prompt, notice=notice)


async def save_reply(bot, interaction, job, *, reason=None, comment='', choice=None, source_message=None):
    """Save and update the original question; only failures create a notice."""
    await bot.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
    await bot.bridge(f"/bot/m2/{job['id']}/answer", {**actor(interaction),
        'reason_code': reason, 'comment': comment, 'choice': choice,
        'expected_answered_at': job.get('answered_at')})
    latest = None
    try:
        latest = await bot.bridge(f"/bot/m2/{job['id']}/open", actor(interaction))
        message = source_message or getattr(interaction, 'message', None)
        if message:
            await message.edit(content=report_content(latest, message), embeds=[], view=controls(latest),
                suppress=True, allowed_mentions=discord.AllowedMentions.none())
        else:
            await interaction.edit_original_response(content=prompt(latest), embeds=[], view=controls(latest), allowed_mentions=discord.AllowedMentions.none())
    except Exception:
        import logging
        logging.getLogger(__name__).warning('M2 answer saved, message refresh failed: %s', job['id'])
        await interaction.followup.send('U ruajt në PrimeFlow, por pyetja nuk u rifreskua. Provo përsëri.', ephemeral=True)
    return latest


class ReplyModal(discord.ui.Modal):
    def __init__(self, bot, job, *, reason=None, choice=None, source_message=None):
        super().__init__(title='Komenti për PM' if job['kind'] == 'continuation' else 'Komenti për dorëzimin' if choice == 'PO' else 'Përgjigjja për M2', timeout=900)
        self.bot, self.job, self.reason, self.choice = bot, job, reason, choice
        self.source_message = source_message
        self.initial_save = None
        self.comment = discord.ui.TextInput(label=('Pse nuk vazhdon në PM?' if job['kind'] == 'continuation' else 'Pse nuk u dorëzua?') if choice == 'JO' else 'Komenti (opsional)' if choice == 'PO' else 'Komenti / progresi',
            style=discord.TextStyle.paragraph, required=choice != 'PO', max_length=4000,
            default=(job.get('comment') or None) if choice == job.get('choice') else None)
        self.add_item(self.comment)

    async def on_submit(self, interaction):
        await interaction.response.defer()
        try:
            if self.initial_save is not None:
                latest = await asyncio.shield(self.initial_save)
                if isinstance(latest, Exception):
                    raise latest
                self.job = latest or await self.bot.bridge(f"/bot/m2/{self.job['id']}/open", actor(interaction))
            await save_reply(self.bot, interaction, self.job, reason=self.reason, comment=str(self.comment),
                             choice=self.choice, source_message=self.source_message)
        except Exception as exc:
            await interaction.followup.send(self.bot.error_message(exc), ephemeral=True)


async def handle(bot, interaction):
    parts = interaction.data['custom_id'].split(':')
    direct_yes = parts[2] == 'reply' and parts[4] == 'PO'
    async def load():
        await bot.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
        return await bot.bridge(f'/bot/m2/{parts[3]}/open', actor(interaction))

    deferred = False
    if parts[2] in {'open', 'detail', 'return', 'question'}:
        await interaction.response.defer()
        job = await load()
    else:
        job, deferred = await prepare_modal(interaction, load)
    if parts[2] == 'question':
        await interaction.edit_original_response(content=prompt(job), embeds=[], view=controls(job),
            allowed_mentions=discord.AllowedMentions.none())
        return
    if parts[2] in {'open', 'detail'}:
        detail = await bot.current_detail(interaction, job['task_id'])
        await show_detail(bot, interaction, job, detail, int(parts[4]) if parts[2] == 'detail' else 0)
        return
    if parts[2] == 'return':
        await interaction.message.edit(content=report_content(job, interaction.message), embeds=[],
            view=controls(job), suppress=True, allowed_mentions=discord.AllowedMentions.none())
        return
    if direct_yes:
        modal = ReplyModal(bot, job, choice='PO', source_message=getattr(interaction, 'message', None))
        modal.initial_save = asyncio.get_running_loop().create_future()
        # Open the optional comment immediately. The yes answer is saved even
        # when the person closes the form; an early submit waits for its version.
        await open_modal(interaction, modal, deferred=deferred)
        try:
            latest = await save_reply(bot, interaction, job, choice='PO',
                comment=(job.get('comment') or '') if job.get('choice') == 'PO' else '')
            modal.initial_save.set_result(latest)
        except Exception as exc:
            modal.initial_save.set_result(exc)
            raise
        return
    if parts[2] == 'comment' and job.get('choice') != 'PO':
        send = interaction.followup.send if deferred else interaction.response.send_message
        await send('Përgjigjja ka ndryshuar. Zgjidh Po ose Jo përsëri.', ephemeral=True)
        return
    reason = interaction.data['values'][0] if parts[2] == 'reason' else None
    choice = parts[4] if parts[2] == 'reply' else 'PO' if parts[2] == 'comment' else None
    await open_modal(interaction, ReplyModal(bot, job, reason=reason, choice=choice,
        source_message=getattr(interaction, 'message', None)), deferred=deferred)


async def deliver(bot):
    jobs = (await bot.bridge('/bot/m2/claim', {}))['jobs']
    semaphore = asyncio.Semaphore(3)
    async def send(job):
        async with semaphore:
            await send_one(bot, job)
    await asyncio.gather(*(send(job) for job in jobs))


async def send_one(bot, job):
    try:
        channel = await bot.private_channel(job['guild_id'], job['channel_id'], job['discord_user_id'])
        # Recheck the link and assignment immediately before delivery.
        job = await bot.bridge(f"/bot/m2/{job['id']}/open", {key: job[key] for key in ('discord_user_id', 'guild_id', 'channel_id')})
        if job['answered']:
            return
        nonce = hashlib.sha256(f"m2:{job['id']}".encode()).hexdigest()[:24]
        message = await bot.http.request(discord.http.Route('POST', '/channels/{channel_id}/messages', channel_id=channel.id),
            json={'content': prompt(job), 'components': controls(job).to_components(),
                  'allowed_mentions': {'parse': [], 'users': [job['discord_user_id']]},
                  'nonce': nonce, 'enforce_nonce': True})
        await bot.bridge(f"/bot/m2/{job['id']}/ack", {key: job[key] for key in ('discord_user_id', 'guild_id', 'channel_id')} | {'message_id': str(message['id'])})
    except Exception as exc:
        # Do not log task text, replies, or credentials.
        import logging
        logging.getLogger(__name__).warning('M2 delivery %s failed: %s', job['id'], type(exc).__name__)
