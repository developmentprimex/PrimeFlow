"""Few-step Discord controls for M3 and tomorrow, backed by durable questions."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import discord
import discord_ui as task_ui
from app.config import settings
from app.services.discord_m3 import KINDS, SLOTS, context_key
from app.services.primeflow_report import report_timezone
from datetime import datetime
from discord_m2_client import actor
from discord_m2_approvals import parse_date

log = logging.getLogger(__name__)


def date_default(value):
    return datetime.fromisoformat(value).astimezone(report_timezone()).strftime('%d.%m.%Y %H:%M') if value else ''


def form_date(value, current):
    # Preserve the complete instant when an autofilled field is left untouched.
    return current if current and value.strip() == date_default(current) else parse_date(value, current)


def prompt(job, page=0):
    row, kind = job['snapshot'], job['kind']
    if kind == 'tomorrow_task':
        title = discord.utils.escape_markdown(task_ui.heading(row))
        text = f"**[{title}](<{task_ui.task_url(job['task_id'])}>)**"
        if job.get('resolved'):
            text += ' · ✅ ' + job['resolved'][:80]
        elif job.get('answered'):
            label = {'PO': 'Po', 'JO': 'Jo', 'postpone': 'U shty'}.get(job.get('answer', {}).get('action'), '')
            text += ' · ✅ ' + label
        if job.get('comment'):
            text += ' · 💬'
        return text
    text = f"<@{job['discord_user_id']}> **{'M3' if kind in {'untouched', 'delivery', 'meeting'} else 'NESËR'} · {KINDS[kind]}**\n"
    if kind == 'tomorrow':
        text += f"**{job['target_date']} · {len(row['tasks'])} detyra**\n"
        text += 'Po për të gjitha plotëson vetëm detyrat ende pa përgjigje. Përgjigjet dhe komentet individuale ruhen.'
    else:
        text += '**' + discord.utils.escape_markdown(row['title'][:500]) + '**\n'
        if kind == 'untouched':
            text += 'Detyra është TODO. Pse nuk ka progres sot? Komento, shëno progresin, mbylle ose shtyje.'
        elif kind == 'delivery':
            text += 'A është dorëzuar për M3? Zgjidh Po ose Jo dhe shto komentin.'
        elif kind == 'meeting':
            if row.get('time'):
                text += 'Ora: ' + datetime.fromisoformat(row['time']).astimezone(report_timezone()).strftime('%H:%M') + '\n'
            text += 'A është mbajtur takimi apo është anuluar?'
        elif kind == 'tomorrow_task':
            if row.get('due_tomorrow'):
                text += '\n⏰ **Due nesër**\n'
            if row.get('deadline_important'):
                text += '🔴 **Deadline Important**\n'
            text += '\n'
            text += f"Start: {row.get('start_date') or '—'} · Due: {row.get('due_date') or '—'}\n"
            text += 'A kryhet nesër?' if row.get('due_tomorrow') else 'A punohet nesër?'
            text += '\nNëse jo, komento ose shtyje menjëherë.'
        elif kind == 'slot':
            text += f"Data: {job['target_date']} · Sloti yt: **{row.get('slot') or 'PA SLOT'}**\n"
            for peer in row.get('peers', []):
                text += f"{peer['people']}: **{peer['slot'] or 'PA SLOT'}**\n"
            text += 'Vendos slotin.' if row.get('missing_slot') else 'A e konfirmon slotin tënd, apo e ndryshon sipas kolegut?'
    if job.get('resolved'):
        text += '\n\n✅ ' + job['resolved']
    elif job.get('plan_changed'):
        text += '\n\n⚠️ Plani ka ndryshuar pas përgjigjes. Kontrolloje dhe konfirmoje përsëri.'
    elif job.get('answered'):
        answer = job.get('answer', {})
        label = {'PO': 'Po', 'JO': 'Jo', 'done': 'U mbyll', 'progress': 'Në progres',
                 'postpone': 'U shty', 'comment': 'U komentua', 'held': 'Mbajtur', 'canceled': 'Anuluar',
                 'slot': answer.get('slot', '')}.get(answer.get('action'), '')
        text += '\n\n✅ **Përgjigjja: ' + label + '**'
        if job.get('comment'):
            text += '\n' + discord.utils.escape_markdown(job['comment'][:250])
    elif job.get('comment'):
        text += '\n\n💬 ' + discord.utils.escape_markdown(job['comment'][:250])
    return text[:1950]


def controls(job, page=0):
    view = discord.ui.View(timeout=None)
    kind, qid, row = job['kind'], job['id'], job['snapshot']

    def button(label, action, style=discord.ButtonStyle.secondary, row=0):
        view.add_item(discord.ui.Button(label=label, custom_id=f'pf:m3:{action}:{qid}', style=style, row=row))

    if not job.get('resolved'):
        if kind == 'untouched':
            for label, action in [('Komento', 'comment'), ('Në progres', 'progress'), ('Mbylle', 'done'), ('Shtyje', 'postpone')]:
                button(label, action)
        elif kind == 'tomorrow':
            button('Po për të gjitha', 'PO', discord.ButtonStyle.success)
        elif kind == 'tomorrow_task':
            button('Po, kryhet' if row.get('due_tomorrow') else 'Po, punohet', 'PO', discord.ButtonStyle.success)
            button('Jo — shtyje', 'postpone')
            button('Koment', 'comment')
        elif kind == 'delivery':
            button('Po, e dorëzova', 'PO', discord.ButtonStyle.success)
            button('Jo — komento', 'JO')
            if job.get('answer', {}).get('action') == 'PO':
                button('Ndrysho / shto koment', 'yescomment')
        elif kind == 'meeting':
            button('Po, u mbajt', 'held', discord.ButtonStyle.success)
            button('Jo, u anulua', 'canceled')
        elif kind == 'slot':
            slot = row.get('slot')
            if slot in SLOTS:
                button(f'Konfirmoj {slot}', f'slot:{slot}', discord.ButtonStyle.success)
            peer_slots = sorted({p['slot'] for p in row.get('peers', []) if p.get('slot') in SLOTS} - {slot})
            for alternate in peer_slots[:4]:
                button(f'Si kolegu: {alternate}', f'slot:{alternate}')
            view.add_item(discord.ui.Select(placeholder='Vendos / ndrysho slotin', custom_id=f'pf:m3:pickslot:{qid}', row=1,
                options=[discord.SelectOption(label=value, value=value) for value in SLOTS]))
    if job.get('task_id') and kind == 'tomorrow_task':
        button('Hap detyrën', 'open')
    elif job.get('task_id'):
        view.add_item(discord.ui.Button(label='Hap detyrën', url=f"{settings.FRONTEND_URL.rstrip('/')}/tasks/{job['task_id']}", row=3))
    return view


async def save(bot, interaction, job, action, comment='', *, source_message=None, **fields):
    result = await bot.bridge(f"/bot/m3/{job['id']}/answer", {**actor(interaction), 'action': action, 'comment': comment,
        'expected_answered_at': job.get('answered_at'), 'plan_key': job.get('plan_key'), **fields})
    latest = await bot.bridge(f"/bot/m3/{job['id']}/open", actor(interaction))
    message = source_message or getattr(interaction, 'message', None)
    if message:
        await message.edit(content=prompt(latest), view=controls(latest), suppress=True, allowed_mentions=discord.AllowedMentions.none())
    else:
        original = await interaction.edit_original_response(content=prompt(latest), view=controls(latest), embeds=[], allowed_mentions=discord.AllowedMentions.none())
        await original.edit(suppress=True)
    for child in result.get('updates', []):
        try:
            channel = await bot.private_channel(child['guild_id'], child['channel_id'], child['discord_user_id'])
            related = await channel.fetch_message(int(child['message_id']))
            await related.edit(content=prompt(child), view=controls(child), suppress=True, allowed_mentions=discord.AllowedMentions.none())
        except Exception as exc:
            log.warning('Tomorrow confirmation refresh %s failed: %s', child['id'], type(exc).__name__)
    return latest


class AnswerModal(discord.ui.Modal):
    def __init__(self, bot, job, action, source_message=None):
        super().__init__(title=('M3 · ' + job['snapshot']['title'])[:45], timeout=900)
        self.bot, self.job, self.action, self.source_message = bot, job, action, source_message
        self.initial_save = None
        self.dates = {}
        if action == 'postpone':
            for field, label in (('start_date', 'Start'), ('due_date', 'Due')):
                item = discord.ui.TextInput(label=label, default=date_default(job['live_dates'].get(field)),
                    placeholder='DD.MM.YYYY HH:MM', required=True, max_length=32)
                self.dates[field] = item
                self.add_item(item)
        if action == 'progress':
            self.progress = discord.ui.TextInput(label='Progresi % (1–99)', default=str(max(1, min(job.get('progress', 1), 99))), max_length=2)
            self.add_item(self.progress)
        optional = action in {'PO', 'held'}
        self.comment = discord.ui.TextInput(label='Komenti (opsional)' if optional else 'Komenti / arsyeja',
            style=discord.TextStyle.paragraph, required=not optional, max_length=4000,
            default=job.get('comment') or None)
        self.add_item(self.comment)

    async def on_submit(self, interaction):
        await interaction.response.defer()
        try:
            if self.initial_save is not None:
                latest = await asyncio.shield(self.initial_save)
                if isinstance(latest, Exception):
                    raise latest
                self.job = latest
            fields = {}
            if self.action == 'postpone':
                fields = {field: form_date(str(item), self.job['live_dates'].get(field)) for field, item in self.dates.items()}
                fields['expected_dates'] = self.job['live_dates']
            if self.action == 'progress':
                fields['progress'] = int(str(self.progress))
            await save(self.bot, interaction, self.job, self.action, str(self.comment), source_message=self.source_message, **fields)
        except Exception as exc:
            await interaction.followup.send(self.bot.error_message(exc), ephemeral=True)


async def handle(bot, interaction):
    _, _, action, qid, *extra = interaction.data['custom_id'].split(':')
    # Slots include colons in their value; the question id is last in those IDs.
    if action in {'slot', 'page'}:
        qid, extra = extra[-1], [':'.join([qid, *extra[:-1]])]
    await bot.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
    job = await bot.bridge(f'/bot/m3/{qid}/open', actor(interaction))
    # Older task cards used a separate No button. It now opens the same date
    # form, so existing messages follow the combined flow as well.
    if job['kind'] == 'tomorrow_task' and action == 'JO':
        action = 'postpone'
    if action == 'open' and job.get('task_id'):
        await interaction.response.defer(ephemeral=True, thinking=True)
        detail = await bot.current_detail(interaction, job['task_id'])
        full = task_ui.full_text(detail['task'], detail)
        while full:
            split = full.rfind('\n', 0, 1900) if len(full) > 1900 else len(full)
            if split <= 0:
                split = min(len(full), 1900)
            await interaction.followup.send(full[:split], ephemeral=True, suppress_embeds=True,
                allowed_mentions=discord.AllowedMentions.none())
            full = full[split:].lstrip('\n')
        return
    if job.get('resolved'):
        await interaction.response.edit_message(content=prompt(job), view=controls(job), suppress_embeds=True)
        return
    if action == 'page':
        await interaction.response.edit_message(content=prompt(job, int(extra[0])), view=controls(job, int(extra[0])), suppress_embeds=True)
    elif action == 'task':
        task_id = interaction.data['values'][0]
        selected = await bot.bridge(f'/bot/m3/{qid}/tasks/{task_id}', actor(interaction))
        await interaction.response.send_message(content=prompt(selected), view=controls(selected), ephemeral=True, suppress_embeds=True)
    elif action in {'slot', 'pickslot'}:
        await interaction.response.defer()
        slot = extra[0] if action == 'slot' else interaction.data['values'][0]
        await save(bot, interaction, job, 'slot', slot=slot, expected_slot_key=context_key('slot', job['snapshot']))
    elif action == 'held':
        await interaction.response.defer()
        await save(bot, interaction, job, 'held')
    elif action == 'PO' and job['kind'] in {'tomorrow', 'tomorrow_task'}:
        await interaction.response.defer()
        await save(bot, interaction, job, 'PO', job.get('comment', ''))
    elif action == 'PO':
        # As in M2, yes is saved immediately; the comment form is optional.
        modal = AnswerModal(bot, job, 'PO', getattr(interaction, 'message', None))
        modal.initial_save = asyncio.get_running_loop().create_future()
        await interaction.response.send_modal(modal)
        try:
            modal.initial_save.set_result(await save(bot, interaction, job, 'PO', job.get('comment', '') if job.get('answer', {}).get('action') == 'PO' else ''))
        except Exception as exc:
            modal.initial_save.set_result(exc)
            raise
    else:
        await interaction.response.send_modal(AnswerModal(bot, job, 'PO' if action == 'yescomment' else action,
            getattr(interaction, 'message', None)))


async def deliver(bot):
    jobs = (await bot.bridge('/bot/m3/claim', {}))['jobs']
    semaphore = asyncio.Semaphore(3)

    async def send(job):
        async with semaphore:
            try:
                channel = await bot.private_channel(job['guild_id'], job['channel_id'], job['discord_user_id'])
                job = await bot.bridge(f"/bot/m3/{job['id']}/open", {key: job[key] for key in ('discord_user_id', 'guild_id', 'channel_id')})
                if job.get('answered') or job.get('resolved'):
                    return
                nonce = hashlib.sha256(f"m3:{job['id']}".encode()).hexdigest()[:24]
                message = await bot.http.request(discord.http.Route('POST', '/channels/{channel_id}/messages', channel_id=channel.id),
                    json={'content': prompt(job), 'components': controls(job).to_components(), 'flags': 4,
                        'allowed_mentions': {'parse': [], 'users': [job['discord_user_id']]}, 'nonce': nonce, 'enforce_nonce': True})
                await bot.bridge(f"/bot/m3/{job['id']}/ack", {key: job[key] for key in ('discord_user_id', 'guild_id', 'channel_id')} | {'message_id': str(message['id'])})
            except Exception as exc:
                log.warning('M3 delivery %s failed: %s', job['id'], type(exc).__name__)
    # Preserve task order and send the final confirmation after task cards.
    for job in jobs:
        await send(job)
