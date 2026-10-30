"""Personal-channel 1H cards. One durable message, only the relevant questions."""
import uuid
import asyncio
import logging

import discord

import discord_ui as ui
import discord_m2_approvals as approvals

log = logging.getLogger(__name__)


def actor(interaction):
    return {key: str(value) for key, value in (
        ('discord_user_id', interaction.user.id), ('guild_id', interaction.guild_id), ('channel_id', interaction.channel_id))}


def message_context(message):
    for row in getattr(message, 'components', []) or []:
        for component in row.children:
            parts = (getattr(component, 'custom_id', '') or '').split(':')
            if len(parts) == 5 and parts[:2] == ['pf', '1h'] and parts[3] != '-':
                return parts[2], parts[3]
    return None


NEXT_HEADING = '**Me çka ke me vazhdu në slotin tjetër?**'


def is_continuation(message):
    return (getattr(message, 'content', '') or '').startswith(NEXT_HEADING)


def continuation_card(data, *, notice=None, next_page=0):
    return card(data, notice=notice, next_page=next_page, continuation=True)


def card(data, *, user_id=None, join_url=None, requested=None, notice=None, next_page=0, continuation=False):
    # Selecting an already answered item is useful for corrections, without restarting the report.
    questions = [t for t in data['questions'] if t['id'] != 'next']
    item = next((t for t in questions if t['id'] == requested), None) if requested else data['current']
    rid = uuid.UUID(data['id']).hex
    text = f'⏰ **Sloti {data["bucket"]}** · {len(data["tasks"])} detyra\n'
    if notice:
        text += discord.utils.escape_markdown(notice[:150]) + '\n'
    view = discord.ui.View(timeout=None)
    if item:
        item_id = uuid.UUID(item['id']).hex
        text += f'{ui.icon(item["status"])} **{discord.utils.escape_markdown(ui.heading(item))}**\n'
        text += f'Start: {approvals.date_text(item.get("start_date"))} · Due: {approvals.date_text(item.get("due_date"))}\n'
        text += '\n' + discord.utils.escape_markdown(item['question'][:400])
        if item.get('answer'):
            text += '\n✅ ' + discord.utils.escape_markdown(item['answer'][:150])
            if item.get('expected_at'):
                text += ' · ' + discord.utils.escape_markdown(item['expected_at'][:100])
        for label, action in [('☑ Strike', 'task'),
                               ('✅ U krye', 'done'), ('📅 Shtyje', 'postpone')]:
            view.add_item(discord.ui.Button(label=label, custom_id=f'pf:1h:{rid}:{item_id}:{action}', row=0))
        view.add_item(discord.ui.Button(label='💬 Koment', custom_id=f'pf:1h:{rid}:{item_id}:answer',
                                       style=discord.ButtonStyle.primary, row=0))
    else:
        text += {'DONE': '✅ Raportimi u ruajt.', 'PARTIAL': '◐ Raportimi u ruajt pjesërisht.',
                 'WAITING': 'Raportimi ka pyetje pa përgjigje.'}[data['state']]
        text += '\nPërgjigjet i gjen te Mira → Takimet 1H.'
        for done in [t for t in data['tasks'] if t['status'] == 'DONE'][:5]:
            text += '\n✅ ' + discord.utils.escape_markdown(ui.heading(done)) + ' · E kryer'
        view.add_item(discord.ui.Button(label='💬 Koment', custom_id=f'pf:1h:{rid}:next:answer',
                                       style=discord.ButtonStyle.primary, row=0))
    if join_url:
        view.add_item(discord.ui.Button(label='🎧 Kyçu në 1H', url=join_url, row=0))
    text += '\n\n**Me çka ke me vazhdu në slotin tjetër?**'
    if data['next'].get('answer'):
        text += '\n✅ ' + discord.utils.escape_markdown(ui.label(data['next']['answer'], 180))
    choices = data.get('next_options', [])
    pages = max(1, (len(choices) + 24) // 25)
    next_page = max(0, min(next_page, pages - 1))
    chosen_ids = {t['id'] for t in data['next'].get('selected_tasks', [])}
    groups = {'CURRENT': 'Vazhdo aktualen', 'LATER': 'E planifikuar më pas', 'UNSTARTED': 'Pa progres',
              'UNSCHEDULED': 'Bllok / Personale'}
    options = [discord.SelectOption(label=ui.label(ui.heading(q), 90), value=q['id'], default=q['id'] in chosen_ids,
        emoji=ui.icon(q['status']), description=(q.get('task_type', '1H') +
            (' · ' + groups[q['group']] if q['group'] != 'UNSCHEDULED' else '') +
            (f' · {q["slot"]}' if q.get('slot') else ''))[:100])
        for q in choices[next_page * 25:(next_page + 1) * 25]]
    if options:
        text += '\nZgjidh një ose disa detyra; zgjedhjet ruhen menjëherë.'
        view.add_item(discord.ui.Select(placeholder=f'Vazhdimi · zgjidh detyrat ({next_page + 1}/{pages})',
            options=options, min_values=0, max_values=len(options),
            custom_id=f'pf:1h:{rid}:next:nselect{next_page}-{data["next_options_key"]}', row=1))
    else:
        text += '\nNuk ka detyra për vazhdim.'
    if pages > 1:
        for label, target, disabled in [('← Vazhdimi', next_page - 1, next_page == 0), ('Vazhdimi →', next_page + 1, next_page == pages - 1)]:
            view.add_item(discord.ui.Button(label=label, custom_id=f'pf:1h:{rid}:-:npage{max(0, target)}', disabled=disabled, row=2))
    index = next((i for i, q in enumerate(questions) if item and q['id'] == item['id']), 0)
    if item and len(questions) > 1:
        text += f'\n\nDetyra {index + 1}/{len(questions)}'
        for label, target, disabled in [('← Detyra', index - 1, index == 0), ('Detyra →', index + 1, index == len(questions) - 1)]:
            view.add_item(discord.ui.Button(label=label, custom_id=f'pf:1h:{rid}:-:q{max(0, target)}', disabled=disabled, row=3))
    elif questions and not item:
        view.add_item(discord.ui.Button(label='Rishiko detyrat', custom_id=f'pf:1h:{rid}:-:q0', row=3))
    task_text, _, next_text = text.partition('\n\n' + NEXT_HEADING)
    # The navigation caption belongs with the task, not the continuation.
    next_text, separator, navigation = next_text.rpartition('\n\nDetyra ') if '\n\nDetyra ' in next_text else (next_text, '', '')
    if separator:
        task_text += separator + navigation
    for control in list(view.children):
        parts = (getattr(control, 'custom_id', '') or '').split(':')
        next_control = len(parts) == 5 and (parts[3] == 'next' or parts[4].startswith('npage'))
        if next_control != continuation:
            view.remove_item(control)
    if continuation:
        for control in list(view.children):
            if (getattr(control, 'custom_id', '') or '').endswith(':next:answer'):
                view.remove_item(control)
        if not options:
            view.add_item(discord.ui.Select(placeholder='Nuk ka detyra për vazhdim',
                custom_id=f'pf:1h:{rid}:next:nempty', disabled=True, row=1,
                options=[discord.SelectOption(label='Nuk ka detyra për vazhdim', value='empty')]))
        text = NEXT_HEADING + next_text
        if notice:
            text += '\n' + discord.utils.escape_markdown(notice[:150])
    else:
        text = task_text
    return text[:2000], view


class AnswerModal(discord.ui.Modal):
    def __init__(self, bot, data, item, message):
        super().__init__(title=f'Raporto · 1H {data["bucket"]}', timeout=600)
        self.bot, self.data, self.item, self.message = bot, data, item, message
        self.answer = discord.ui.TextInput(label='Vazhdimi' if item['id'] == 'next' else 'Përgjigjja për detyrën', style=discord.TextStyle.paragraph,
            default=(item.get('answer') or '')[:4000] or None, max_length=4000)
        self.has_expected = item['id'] != 'next' and (item['status'] == 'TODO' or item.get('asks_completion', False))
        self.expected = discord.ui.TextInput(label='Vazhdimi i planifikuar' if item['status'] == 'TODO' else 'Përfundimi i pritshëm', required=False,
            placeholder='p.sh. sot 14:30',
            default=item.get('expected_at') or None, max_length=200)
        self.add_item(self.answer)
        if self.has_expected:
            self.add_item(self.expected)
        self.continuation = None
        if item['id'] != 'next':
            self.continuation = discord.ui.TextInput(label='Me çfarë vazhdon më pas? (opsionale)', required=False,
                style=discord.TextStyle.paragraph, max_length=4000,
                placeholder='Lëre bosh për të mbajtur vazhdimin e zgjedhur nga lista.',
                default=(data['next'].get('answer') or '')[:4000] or None
                    if data['next'].get('selection_kind') == 'OTHER' else None)
            self.add_item(self.continuation)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.bot.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
            data = await self.bot.bridge(f'/bot/reminders/{self.data["id"]}/one-h-answer', {
                **actor(interaction), 'item_id': self.item['id'], 'request_id': str(interaction.id),
                'answer': str(self.answer), 'expected_at': str(self.expected) if self.has_expected else '',
                'question_status': self.item['status'], 'asks_completion': self.item.get('asks_completion'),
                'continuation': str(self.continuation) if self.continuation is not None else None})
            text, view = card(data, continuation=is_continuation(self.message), join_url=self.bot.one_h_url(data['bucket'], interaction.guild_id), notice='✅ Përgjigjja u ruajt.')
            await self.message.edit(content=text, embed=None, view=view)
            receipt = '✅ U ruajt te Mira → Takimet 1H'
            if self.item['id'] != 'next':
                receipt += ' dhe te komenti i detyrës'
            await interaction.followup.send(receipt + '.', ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(self.bot.error_message(exc), ephemeral=True)


class TaskActionModal(ui.CommentModal):
    """Reuse validated task commands while preserving the report's own message."""
    def __init__(self, bot, detail, data, message, *, complete=False):
        super().__init__(bot, detail['task']['id'], detail['fingerprint'], complete=complete)
        self.report_id, self.message = data['id'], message

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            actions = []
            if str(self.comment).strip():
                actions.append(ui.action('comment', {'comment': str(self.comment).strip()}))
            if self.complete:
                actions.append(ui.action('update_task', {'status': 'DONE'}))
            result = await self.bot.apply(interaction, self.task_id, self.fingerprint, actions,
                'Raportimi 1H: ' + ('mbylle detyrën' if self.complete else 'shto koment') +
                (': ' + str(self.comment).strip() if str(self.comment).strip() else ''))
            data = (await self.bot.bridge(f'/bot/reminders/{self.report_id}/tasks', actor(interaction)))['one_h']
            text, view = card(data, notice=('✅ ' if result['status'] == 'DONE' else '⚠ ') + result['message'],
                join_url=self.bot.one_h_url(data['bucket'], interaction.guild_id))
            await self.message.edit(content=text, embed=None, view=view)
            await interaction.followup.send(result['message'][:1800], ephemeral=True)
        except Exception as exc:
            await interaction.followup.send(self.bot.error_message(exc), ephemeral=True)


async def handle(bot, interaction):
    _, _, rid, item_id, action = interaction.data['custom_id'].split(':')
    rid = str(uuid.UUID(rid))
    item_id = item_id if item_id in {'next', '-'} else str(uuid.UUID(item_id))
    await bot.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
    # Modal-open responses must be immediate; these are actor-checked again on submit.
    if action not in {'answer', 'other', 'comment', 'done', 'postpone'}:
        await bot.ack(interaction)
    data = (await bot.bridge(f'/bot/reminders/{rid}/tasks', actor(interaction))).get('one_h')
    if not data:
        raise ValueError('Ky slot nuk ka pyetje për ty.')
    item = next((t for t in data['questions'] if t['id'] == item_id), None)
    if action in {'answer', 'other', 'comment'}:
        if action == 'other':
            item = data['current'] or next(t for t in data['questions'] if t['id'] == 'next')
        if item is None:
            raise ValueError('Gjendja ndryshoi. Rifresko raportimin.')
        await interaction.response.send_modal(AnswerModal(bot, data, item, interaction.message))
        return
    if action in {'task', 'comment', 'done', 'postpone'}:
        if item_id not in {t['id'] for t in data['tasks'] if t['available']}:
            raise ValueError('Detyra nuk është më e disponueshme.')
        current_task = next(t for t in data['tasks'] if t['id'] == item_id)
        if action in {'done', 'postpone'} and current_task['status'] == 'DONE':
            text, view = card(data, notice='✅ Detyra është e kryer.',
                              join_url=bot.one_h_url(data['bucket'], interaction.guild_id))
            await interaction.response.edit_message(content=text, embed=None, view=view,
                                                     allowed_mentions=discord.AllowedMentions.none())
            return
        detail = await bot.select(interaction, item_id)
        if action == 'task':
            next_page = 0
            for row in getattr(interaction.message, 'components', []) or []:
                for component in row.children:
                    cid = getattr(component, 'custom_id', '') or ''
                    if ':nselect' in cid:
                        next_page = int(cid.split(':nselect')[1].split('-')[0])
            back = f'pf:1h:{uuid.UUID(rid).hex}:{uuid.UUID(item_id).hex}:backn{next_page}'
            view = ui.with_one_h_return(ui.points_view(detail), back)
            content = 'Zgjidh pikat për strike / heqje strike:' if any(isinstance(c, discord.ui.Select) for c in view.children) else 'Kjo detyrë nuk ka pika për strike.'
            await interaction.edit_original_response(content=content,
                embed=ui.card(detail['task'], detail=detail), view=view,
                allowed_mentions=discord.AllowedMentions.none())
        elif action == 'postpone':
            job = await bot.bridge(f'/bot/m2/postponements/tasks/{item_id}/open', actor(interaction))
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Select(placeholder='Zgjidh arsyen e shtyrjes',
                custom_id=f'pf:m2a:taskreason:{item_id}:start_due',
                options=[discord.SelectOption(label=r['label'], value=r['value']) for r in job['reasons']]))
            view.add_item(discord.ui.Button(label='← Kthehu te raportimi',
                custom_id=f'pf:1h:{uuid.UUID(rid).hex}:{uuid.UUID(item_id).hex}:back', row=1))
            await interaction.response.send_message(content=approvals.task_context(job) + '\n\nZgjidh arsyen. Shtyrja dërgohet për konfirmim.',
                view=view, ephemeral=True)
        else:
            await interaction.response.send_modal(TaskActionModal(bot, detail, data, interaction.message, complete=action == 'done'))
        return
    requested, next_page, notice = None, 0, None
    if action == 'skip':
        data = await bot.bridge(f'/bot/reminders/{rid}/one-h-answer', {**actor(interaction),
            'item_id': item_id, 'request_id': str(interaction.id), 'skip': True})
    elif action == 'back' or (action.startswith('backn') and action[5:].isdigit()):
        requested = item_id
        next_page = int(action[5:]) if action != 'back' else 0
    elif action == 'review':
        requested = interaction.data['values'][0]
    elif action == 'none' or (action.startswith('nselect') and action[7:].split('-')[0].isdigit()):
        next_page = int(action[7:].split('-')[0]) if action != 'none' else 0
        data = await bot.bridge(f'/bot/reminders/{rid}/one-h-answer', {**actor(interaction),
            'item_id': 'next', 'request_id': str(interaction.id), 'selection_mode': 'NONE' if action == 'none' else 'TASKS',
            'next_task_ids': interaction.data.get('values', []) if action != 'none' else [], 'next_page': next_page,
            'next_options_key': action.partition('-')[2] or None})
        notice = '✅ Vazhdimi u ruajt.' if data['next'].get('answer') else 'Zgjedhja u pastrua. Zgjidh vazhdimin.'
        context = message_context(interaction.message)
        if context and context[1] != 'next':
            requested = str(uuid.UUID(context[1]))
    elif action.startswith('npage') and action[5:].isdigit():
        next_page = int(action[5:])
        context = message_context(interaction.message)
        if context and context[1] != 'next':
            requested = str(uuid.UUID(context[1]))
    elif action.startswith('q') and action[1:].isdigit():
        questions = [t for t in data['questions'] if t['id'] != 'next']
        index = int(action[1:])
        if index >= len(questions):
            raise ValueError('Gjendja ndryshoi. Rifresko raportimin.')
        requested = questions[index]['id']
    elif action.startswith('page') and action[4:].isdigit():
        offset = int(action[4:]) * 25
        if offset >= len(data['questions']):
            raise ValueError('Faqja nuk është e disponueshme. Rifresko raportimin.')
        requested = data['questions'][offset]['id']
    elif action not in {'refresh', 'choices', 'closechoices'}:
        raise ValueError('Veprim i panjohur.')
    text, view = card(data, continuation=is_continuation(interaction.message),
        requested=requested,
        next_page=next_page, notice=notice, join_url=bot.one_h_url(data['bucket'], interaction.guild_id))
    await interaction.edit_original_response(content=text, embed=None, view=view)


async def reply(bot, message):
    """Only explicit replies to a 1H card are report answers; normal chat keeps its task tools."""
    reference = getattr(message, 'reference', None)
    if not reference or not reference.message_id:
        return False
    source = reference.resolved if isinstance(reference.resolved, discord.Message) else await message.channel.fetch_message(reference.message_id)
    if source.author.id != bot.user.id or not (context := message_context(source)):
        return False
    rid, item_id = context
    data = await bot.bridge(f'/bot/reminders/{uuid.UUID(rid)}/one-h-answer', {
        'discord_user_id': str(message.author.id), 'guild_id': str(message.guild.id), 'channel_id': str(message.channel.id),
        'item_id': 'next' if item_id == 'next' else str(uuid.UUID(item_id)), 'request_id': str(message.id), 'answer': message.content[:4000],
        'question_status': 'TODO' if 'Pse s’ke vazhdu' in source.content else 'IN_PROGRESS' if 'A ke me vazhdu' in source.content else None})
    text, view = card(data, continuation=is_continuation(source), notice='✅ Përgjigjja u ruajt.', join_url=bot.one_h_url(data['bucket'], message.guild.id))
    await source.edit(content=text, embed=None, view=view)
    return True


async def sync(bot):
    """Refresh existing public 1H cards after platform edits, without sending any."""
    jobs = (await bot.bridge('/bot/one-h-sync/jobs', {}))['jobs']
    cache = getattr(bot, 'one_h_sync_cache', None)
    if cache is None:
        cache = bot.one_h_sync_cache = {}
    active_keys = {(job['id'], str(mid)) for job in jobs for mid in job['message_ids']}
    for key in list(cache):
        if key not in active_keys:
            del cache[key]
    semaphore = asyncio.Semaphore(3)

    async def update(job):
        async with semaphore:
            pending = [str(mid) for mid in job['message_ids']
                       if cache.get((job['id'], str(mid))) != job['revision']]
            if not pending:
                return
            try:
                actor_data = {key: job[key] for key in ('discord_user_id', 'guild_id', 'channel_id')}
                data = (await bot.bridge(f'/bot/reminders/{job["id"]}/tasks', actor_data))['one_h']
                channel = await bot.private_channel(job['guild_id'], job['channel_id'], job['discord_user_id'])
                for mid in pending:
                    key = (job['id'], mid)
                    try:
                        message = await channel.fetch_message(int(mid))
                        context = message_context(message)
                        if not context and message.components and message.content.startswith('⏰ **Sloti '):
                            context = (uuid.UUID(job['id']).hex, '-')
                        # Do not replace an open strike picker during a task
                        # revision scan. Returning reads the fresh report.
                        if ui.one_h_strike_return(message):
                            continue
                        # Retired cards and other bots' messages remain untouched.
                        if message.author.id != bot.user.id or not context or context[0] != uuid.UUID(job['id']).hex:
                            cache[key] = job['revision']
                            continue
                        page = 0
                        for row in message.components:
                            for component in row.children:
                                cid = getattr(component, 'custom_id', '') or ''
                                if ':nselect' in cid:
                                    page = int(cid.split(':nselect')[1].split('-')[0])
                        selected = str(uuid.UUID(context[1])) if context[1] not in {'next', '-'} else None
                        content, view = card(data, continuation=is_continuation(message), user_id=job['discord_user_id'], requested=selected, next_page=page,
                            join_url=bot.one_h_url(job['bucket'], job['guild_id']))
                        components = [row.to_dict() for row in message.components]
                        if content != message.content or components != view.to_components():
                            await message.edit(content=content, embed=None, view=view,
                                               allowed_mentions=discord.AllowedMentions.none())
                        cache[key] = job['revision']
                    except discord.NotFound:
                        # Do not recreate a message the user deleted.
                        cache[key] = job['revision']
            except Exception as exc:
                log.warning('1H card sync %s failed: %s', job['id'], type(exc).__name__)

    await asyncio.gather(*(update(job) for job in jobs))
