"""Postponement form and Diellza's approval controls; no task edit before approval."""
import hashlib
import logging
from datetime import datetime
import discord
from app.config import settings
from app.services.primeflow_report import report_timezone
from app.services.discord_m2_postponements import FIELDS, STATUS_LABELS
import discord_m2_client as questions

log = logging.getLogger(__name__)


def date_text(value):
    return datetime.fromisoformat(value).astimezone(report_timezone()).strftime('%d.%m.%Y') if value else '—'


def review_prompt(job):
    text = f"**M2 · Kërkesë për shtyrje**\n**{job['original_tasks'][0]['title']}**\nNga: {job['requester']}"
    original = next(row for row in job['original_tasks'] if row['id'] == job['task_id'])
    for field, value in job['proposed_dates'].items():
        text += f"\n{'Start' if field == 'start_date' else 'Due'}: {date_text(original[field])} → **{date_text(value)}**"
    if len(job['original_tasks']) > 1:
        text += '\nNdikon edhe te kopjet e përbashkëta: ' + '; '.join(row['people'] for row in job['original_tasks'])
    text += '\nArsyeja: ' + job['reason'] + '\nKomenti: ' + job['comment'][:900]
    return (text + '\n\n**' + job['status_label'] + '**')[:1950]


def review_controls(job):
    view = discord.ui.View(timeout=None)
    if job['status'] == 'PENDING':
        view.add_item(discord.ui.Button(label='Konfirmo shtyrjen', style=discord.ButtonStyle.success, custom_id=f"pf:m2a:approve:{job['id']}"))
        view.add_item(discord.ui.Button(label='Mos e konfirmo', style=discord.ButtonStyle.danger, custom_id=f"pf:m2a:reject:{job['id']}"))
    view.add_item(discord.ui.Button(label='Hap detyrën', url=f"{settings.FRONTEND_URL.rstrip('/')}/tasks/{job['task_id']}"))
    return view


def parse_date(value, current):
    value = value.strip()
    parsed = None
    for pattern in ('%Y-%m-%d', '%d.%m.%Y', '%Y-%m-%d %H:%M', '%d.%m.%Y %H:%M'):
        try:
            parsed = datetime.strptime(value, pattern)
            break
        except ValueError:
            continue
    if parsed is None:
        raise ValueError('Shkruaj datën si DD.MM.YYYY ose YYYY-MM-DD.')
    if ':' not in value and current:
        old = datetime.fromisoformat(current).astimezone(report_timezone())
        parsed = parsed.replace(hour=old.hour, minute=old.minute)
    return parsed.replace(tzinfo=report_timezone()).isoformat()


class ProposalModal(discord.ui.Modal):
    def __init__(self, bot, job, change_kind, reason):
        super().__init__(title='Kërko shtyrje nga Diellza', timeout=900)
        self.bot, self.job, self.change_kind, self.reason = bot, job, change_kind, reason
        self.dates = {}
        for field in FIELDS[change_kind]:
            item = discord.ui.TextInput(label='Start i ri · DD.MM.YYYY' if field == 'start_date' else 'Due i ri · DD.MM.YYYY',
                placeholder='DD.MM.YYYY', required=True, max_length=32)
            self.dates[field] = item
            self.add_item(item)
        self.comment = discord.ui.TextInput(label='Pse po shtyhet? Komenti', required=True, max_length=4000, style=discord.TextStyle.paragraph)
        self.add_item(self.comment)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            dates = {field: parse_date(str(item), self.job.get('live_dates', {}).get(field)) for field, item in self.dates.items()}
            result = await self.bot.bridge(f"/bot/m2/postponements/questions/{self.job['id']}", {
                **questions.actor(interaction), **dates, 'request_id': str(interaction.id), 'change_kind': self.change_kind,
                'reason_code': self.reason, 'comment': str(self.comment)})
            await interaction.edit_original_response(content='⏳ Kërkesa është në pritje të Diellza Veliut. Datat ndryshojnë vetëm pas konfirmimit.', view=None)
            # Update the normal question, without echoing its comment in the channel.
            try:
                channel = await self.bot.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
                latest = await self.bot.bridge(f"/bot/m2/{self.job['id']}/open", questions.actor(interaction))
                if self.job.get('message_id'):
                    message = await channel.fetch_message(int(self.job['message_id']))
                    await message.edit(content=questions.prompt(latest), view=questions.controls(latest), allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                log.warning('M2 proposal saved; question refresh deferred: %s', result['id'])
        except Exception as exc:
            await interaction.edit_original_response(content=self.bot.error_message(exc), view=None)


async def handle(bot, interaction):
    _, _, action, object_id, *extra = interaction.data['custom_id'].split(':')
    await bot.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
    actor = questions.actor(interaction)
    if action in {'approve', 'reject'}:
        await interaction.response.defer()
        result = await bot.bridge(f'/bot/m2/postponements/{object_id}/decision', {
            **actor, 'decision': 'APPROVED' if action == 'approve' else 'REJECTED'})
        await interaction.edit_original_response(content=review_prompt(result), view=review_controls(result))
        await bot.bridge(f'/bot/m2/postponements/{object_id}/ack', {**actor, 'role': 'review_update', 'message_id': str(interaction.message.id)})
        return
    job = await bot.bridge(f'/bot/m2/{object_id}/open', actor)
    if action == 'request':
        view = discord.ui.View(timeout=None)
        for kind, label in (('start', 'Vetëm Start'), ('due', 'Vetëm Due'), ('start_due', 'Start dhe Due')):
            view.add_item(discord.ui.Button(label=label, custom_id=f'pf:m2a:dates:{object_id}:{kind}'))
        await interaction.response.send_message('Çfarë dëshiron të shtysh?', view=view, ephemeral=True)
    elif action == 'dates':
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Select(placeholder='Zgjidh arsyen e shtyrjes', custom_id=f'pf:m2a:reason:{object_id}:{extra[0]}',
            options=[discord.SelectOption(label=item['label'], value=item['value']) for item in job['reasons']]))
        await interaction.response.edit_message(content='Zgjidh arsyen; pastaj cakto datën dhe komentin.', view=view)
    elif action == 'reason':
        await interaction.response.send_modal(ProposalModal(bot, job, extra[0], interaction.data['values'][0]))


async def deliver(bot):
    jobs = (await bot.bridge('/bot/m2/postponements/claim', {}))['jobs']
    for job in jobs:
        try:
            channel = await bot.private_channel(job['guild_id'], job['channel_id'], job['discord_user_id'])
            actor = {key: job[key] for key in ('discord_user_id', 'guild_id', 'channel_id')}
            if job['role'] == 'requester' and job.get('message_id'):
                message = await channel.fetch_message(int(job['message_id']))
                await message.edit(content=questions.prompt(job['question']), view=questions.controls(job['question']), allowed_mentions=discord.AllowedMentions.none())
                message_id = str(message.id)
            elif job['role'] == 'review_update':
                message = await channel.fetch_message(int(job['message_id']))
                await message.edit(content=review_prompt(job), view=review_controls(job), allowed_mentions=discord.AllowedMentions.none())
                message_id = str(message.id)
            else:
                content = (f"<@{job['discord_user_id']}>\n" + review_prompt(job)) if job['role'] == 'review' else job['status_label']
                view = review_controls(job)
                nonce = hashlib.sha256(f"m2approval:{job['id']}:{job['role']}".encode()).hexdigest()[:24]
                message = await bot.http.request(discord.http.Route('POST', '/channels/{channel_id}/messages', channel_id=channel.id),
                    json={'content': content, 'components': view.to_components(), 'allowed_mentions': {'parse': [], 'users': [job['discord_user_id']]},
                          'nonce': nonce, 'enforce_nonce': True})
                message_id = message['id']
            await bot.bridge(f"/bot/m2/postponements/{job['id']}/ack", {**actor, 'role': job['role'], 'message_id': message_id})
        except Exception as exc:
            log.warning('M2 approval notification %s failed: %s', job['id'], type(exc).__name__)
