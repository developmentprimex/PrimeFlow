"""Postponement form and Diellza's approval controls; no task edit before approval."""
import hashlib
import logging
from datetime import datetime
import discord
from app.config import settings
from app.services.primeflow_report import report_timezone
from app.services.discord_m2_postponements import FIELDS, STATUS_LABELS, iso
import discord_m2_client as questions
import discord_ui as task_ui

log = logging.getLogger(__name__)


def task_name(job):
    return task_ui.heading({'title': job.get('title') or job.get('snapshot', {}).get('title') or 'Detyra'})


def task_context(job):
    dates = job.get('live_dates', {})
    return '**Detyra: ' + discord.utils.escape_markdown(task_name(job)) + '**\n' + (
        'Start: ' + date_text(dates.get('start_date')) + ' · Due: ' + date_text(dates.get('due_date')))


def back_button(job):
    custom_id = f"pf:back:{job['id']}" if job.get('source') == 'task' else f"pf:m2a:cancel:{job['id']}"
    return discord.ui.Button(label='← Kthehu te detyra', custom_id=custom_id, row=1)


def back_view(job):
    return discord.ui.View(timeout=None).add_item(back_button(job))


def date_text(value):
    return datetime.fromisoformat(value).astimezone(report_timezone()).strftime('%d.%m.%Y') if value else '—'


def review_prompt(job):
    heading = 'M3' if job.get('source') == 'm3' else 'M2' if job.get('question_id') else 'PrimeFlow'
    text = f"**{heading} · Kërkesë për shtyrje**\n**{job['original_tasks'][0]['title']}**\nNga: {job['requester']}"
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
        parsed = parsed.replace(hour=old.hour, minute=old.minute, second=old.second, microsecond=old.microsecond)
    return parsed.replace(tzinfo=report_timezone()).isoformat()


def current_date_text(value):
    return datetime.fromisoformat(value).astimezone(report_timezone()).strftime('%d.%m.%Y') if value else ''


def changed_dates(job, values):
    changed = {}
    for field, value in values.items():
        current = job.get('live_dates', {}).get(field)
        if value.strip() == current_date_text(current):
            continue
        parsed = parse_date(value, current)
        # Reformatting an unchanged date must not turn a Due-only request into
        # Start+Due. Compare actual timestamps, not the user's text format.
        if iso(parsed) != iso(current):
            changed[field] = parsed
    if not changed:
        raise ValueError('Ndrysho të paktën Start ose Due për ta shtyrë detyrën.')
    kind = 'start_due' if len(changed) == 2 else 'start' if 'start_date' in changed else 'due'
    return kind, changed


class ProposalModal(discord.ui.Modal):
    def __init__(self, bot, job, change_kind, reason):
        super().__init__(title=('Shtyrje: ' + task_name(job))[:45], timeout=900)
        self.bot, self.job, self.change_kind, self.reason = bot, job, change_kind, reason
        self.dates = {}
        for field in FIELDS[change_kind]:
            name = 'Fillimi i ri' if field == 'start_date' else 'Përfundimi i ri'
            current = date_text(job.get('live_dates', {}).get(field))
            item = discord.ui.TextInput(label=f'{name} · aktual: {current}', default=current_date_text(job.get('live_dates', {}).get(field)),
                placeholder='Ndrysho datën nëse dëshiron · DD.MM.YYYY', required=True, max_length=32)
            self.dates[field] = item
            self.add_item(item)
        self.comment = discord.ui.TextInput(label='Pse të duhet shtyrja?',
            placeholder='P.sh. Pres të dhënat nga klienti. Më duhet edhe një ditë.',
            required=True, max_length=4000, style=discord.TextStyle.paragraph)
        self.add_item(self.comment)

    async def on_submit(self, interaction):
        # Modal submissions originate from the same task message. Acknowledge
        # its update instead of creating a separate response below it.
        await interaction.response.defer()
        try:
            change_kind, dates = changed_dates(self.job, {field: str(item) for field, item in self.dates.items()})
            source = 'tasks' if self.job.get('source') == 'task' else 'questions'
            result = await self.bot.bridge(f"/bot/m2/postponements/{source}/{self.job['id']}", {
                **questions.actor(interaction), **dates, 'request_id': str(interaction.id), 'change_kind': change_kind,
                'reason_code': self.reason, 'comment': str(self.comment)})
            await interaction.edit_original_response(content=task_context(self.job) + '\n\n⏳ Kërkesa është në pritje të Diellza Veliut. Datat ndryshojnë vetëm pas konfirmimit.', embed=None, view=back_view(self.job))
            if source == 'tasks':
                return
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
            await interaction.edit_original_response(content=task_context(self.job) + '\n\n' + self.bot.error_message(exc), embed=None, view=back_view(self.job))


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
    general = action.startswith('task')
    if general:
        action = action[4:]
    prefix = 'task' if general else ''
    job = await bot.bridge(f'/bot/m2/postponements/tasks/{object_id}/open' if general else f'/bot/m2/{object_id}/open', actor)
    if action == 'cancel':
        await interaction.response.edit_message(content=questions.prompt(job), embed=None, view=questions.controls(job))
        return
    if action in {'request', 'dates'}:
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Select(placeholder='Zgjidh arsyen e shtyrjes', custom_id=f'pf:m2a:{prefix}reason:{object_id}:start_due',
            options=[discord.SelectOption(label=item['label'], value=item['value']) for item in job['reasons']], row=0))
        view.add_item(back_button(job))
        await interaction.response.edit_message(content=task_context(job) + '\n\nZgjidh arsyen e shtyrjes. Në formular ndrysho vetëm datën që dëshiron të shtysh; tjetrën lëre siç është.', embed=None, view=view)
    elif action == 'reason':
        await interaction.response.send_modal(ProposalModal(bot, job, 'start_due', interaction.data['values'][0]))


async def deliver(bot):
    jobs = (await bot.bridge('/bot/m2/postponements/claim', {}))['jobs']
    for job in jobs:
        try:
            channel = await bot.private_channel(job['guild_id'], job['channel_id'], job['discord_user_id'])
            actor = {key: job[key] for key in ('discord_user_id', 'guild_id', 'channel_id')}
            if job['role'] == 'requester' and job.get('message_id'):
                message = await channel.fetch_message(int(job['message_id']))
                if job.get('source') == 'm3':
                    import discord_m3_client as m3
                    await message.edit(content=m3.prompt(job['m3_question']), view=m3.controls(job['m3_question']),
                                       allowed_mentions=discord.AllowedMentions.none())
                else:
                    await message.edit(content=questions.prompt(job['question']), view=questions.controls(job['question']), allowed_mentions=discord.AllowedMentions.none())
                message_id = str(message.id)
            elif job['role'] == 'review_update':
                message = await channel.fetch_message(int(job['message_id']))
                await message.edit(content=review_prompt(job), view=review_controls(job), allowed_mentions=discord.AllowedMentions.none())
                message_id = str(message.id)
            else:
                content = (f"<@{job['discord_user_id']}>\n" + review_prompt(job)) if job['role'] == 'review' else (
                    '**' + job['original_tasks'][0]['title'][:300] + '**\n' + job['status_label'])
                view = review_controls(job)
                nonce = hashlib.sha256(f"m2approval:{job['id']}:{job['role']}".encode()).hexdigest()[:24]
                message = await bot.http.request(discord.http.Route('POST', '/channels/{channel_id}/messages', channel_id=channel.id),
                    json={'content': content, 'components': view.to_components(), 'allowed_mentions': {'parse': [], 'users': [job['discord_user_id']]},
                          'nonce': nonce, 'enforce_nonce': True})
                message_id = message['id']
            await bot.bridge(f"/bot/m2/postponements/{job['id']}/ack", {**actor, 'role': job['role'], 'message_id': message_id})
        except Exception as exc:
            log.warning('M2 approval notification %s failed: %s', job['id'], type(exc).__name__)
