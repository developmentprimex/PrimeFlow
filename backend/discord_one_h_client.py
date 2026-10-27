"""Personal-channel 1H cards. One durable message, only the relevant questions."""
import uuid

import discord

import discord_ui as ui
import discord_m2_approvals as approvals


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


def card(data, *, user_id=None, join_url=None, requested=None, notice=None):
    # Selecting an already answered item is useful for corrections, without restarting the report.
    item = next((t for t in data['questions'] if t['id'] == requested), None) if requested else data['current']
    rid = uuid.UUID(data['id']).hex
    text = (f'<@{user_id}> ' if user_id else '') + f'⏰ **Sloti {data["bucket"]}** · {len(data["tasks"])} detyra\n'
    text += f'🎧 **Takimi 1H i orës {data["bucket"]}.**\n'
    if notice:
        text += discord.utils.escape_markdown(notice[:300]) + '\n'
    view = discord.ui.View(timeout=None)
    if item:
        item_id = 'next' if item['id'] == 'next' else uuid.UUID(item['id']).hex
        if item['id'] != 'next':
            text += f'{ui.icon(item["status"])} **{discord.utils.escape_markdown(ui.label(item["title"], 180))}**\n'
        text += discord.utils.escape_markdown(item['question'][:1000])
        if item.get('answer'):
            text += '\n✅ ' + discord.utils.escape_markdown(item['answer'][:300])
            if item.get('expected_at'):
                text += ' · ' + discord.utils.escape_markdown(item['expected_at'][:100])
        text += '\nPërdor **Përgjigju** ose Reply te ky mesazh. Ndryshimet e detyrës bëhen me butonat.'
        for label, action, style in [('✍️ Përgjigju', 'answer', discord.ButtonStyle.primary),
                                     ('⏭ Kalo', 'skip', discord.ButtonStyle.secondary)]:
            view.add_item(discord.ui.Button(label=label, custom_id=f'pf:1h:{rid}:{item_id}:{action}', style=style, row=0))
        if item['id'] != 'next':
            for label, action in [('📊 Progres / strike', 'task'), ('💬 Koment', 'comment'),
                                   ('✅ U krye', 'done'), ('📅 Shtyje', 'postpone')]:
                view.add_item(discord.ui.Button(label=label, custom_id=f'pf:1h:{rid}:{item_id}:{action}', row=1))
    else:
        text += {'DONE': '✅ Raportimi u ruajt.', 'PARTIAL': '◐ Raportimi u ruajt pjesërisht.',
                 'WAITING': 'Raportimi ka pyetje pa përgjigje.'}[data['state']]
        text += '\nPërgjigjet i gjen te Mira → Takimet 1H.'
    index = next((i for i, q in enumerate(data['questions']) if item and q['id'] == item['id']), 0)
    page = index // 25
    options = [discord.SelectOption(label=ui.label(q['title'], 90), value=q['id']) for q in data['questions'][page * 25:(page + 1) * 25]]
    if options:
        view.add_item(discord.ui.Select(placeholder='Rishiko / ndrysho përgjigjen', options=options,
            custom_id=f'pf:1h:{rid}:-:review', row=2))
    view.add_item(discord.ui.Button(label='🔄 Rifresko', custom_id=f'pf:1h:{rid}:-:refresh', row=3))
    if join_url:
        view.add_item(discord.ui.Button(label='🎧 Kyçu në takimin 1H', url=join_url, row=3))
    if len(data['questions']) > 25:
        for label, target, disabled in [('←', page - 1, page == 0), ('→', page + 1, (page + 1) * 25 >= len(data['questions']))]:
            view.add_item(discord.ui.Button(label=label, custom_id=f'pf:1h:{rid}:-:page{max(0, target)}', disabled=disabled, row=4))
    return text[:2000], view


class AnswerModal(discord.ui.Modal):
    def __init__(self, bot, data, item, message):
        super().__init__(title=f'Raportimi 1H {data["bucket"]}', timeout=600)
        self.bot, self.data, self.item, self.message = bot, data, item, message
        self.answer = discord.ui.TextInput(label='Përgjigjja / arsyeja', style=discord.TextStyle.paragraph,
            default=(item.get('answer') or '')[:4000] or None, max_length=4000)
        self.expected = discord.ui.TextInput(label='Vazhdimi / përfundimi i pritshëm', required=False,
            placeholder='p.sh. vazhdoj sot 14:30, përfundoj 16:00',
            default=item.get('expected_at') or None, max_length=200)
        self.add_item(self.answer)
        if item['id'] != 'next':
            self.add_item(self.expected)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.bot.private_channel(interaction.guild_id, interaction.channel_id, interaction.user.id)
            data = await self.bot.bridge(f'/bot/reminders/{self.data["id"]}/one-h-answer', {
                **actor(interaction), 'item_id': self.item['id'], 'request_id': str(interaction.id),
                'answer': str(self.answer), 'expected_at': str(self.expected) if self.item['id'] != 'next' else '',
                'question_status': self.item['status']})
            text, view = card(data, join_url=self.bot.one_h_url(data['bucket'], interaction.guild_id), notice='✅ Përgjigjja u ruajt.')
            await self.message.edit(content=text, embed=None, view=view)
            await interaction.followup.send('✅ Përgjigjja u ruajt te Mira → Takimet 1H.', ephemeral=True)
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
    if action not in {'answer', 'comment', 'done', 'postpone'}:
        await bot.ack(interaction)
    data = (await bot.bridge(f'/bot/reminders/{rid}/tasks', actor(interaction))).get('one_h')
    if not data:
        raise ValueError('Ky slot nuk ka pyetje për ty.')
    item = next((t for t in data['questions'] if t['id'] == item_id), None)
    if action == 'answer':
        if item is None:
            raise ValueError('Gjendja ndryshoi. Rifresko raportimin.')
        await interaction.response.send_modal(AnswerModal(bot, data, item, interaction.message))
        return
    if action in {'task', 'comment', 'done', 'postpone'}:
        if item_id not in {t['id'] for t in data['tasks'] if t['available']}:
            raise ValueError('Detyra nuk është më e disponueshme.')
        detail = await bot.select(interaction, item_id)
        if action == 'task':
            await bot.show_task(interaction, detail, new=True)
        elif action == 'postpone':
            job = await bot.bridge(f'/bot/m2/postponements/tasks/{item_id}/open', actor(interaction))
            view = discord.ui.View(timeout=None)
            view.add_item(discord.ui.Select(placeholder='Zgjidh arsyen e shtyrjes',
                custom_id=f'pf:m2a:taskreason:{item_id}:start_due',
                options=[discord.SelectOption(label=r['label'], value=r['value']) for r in job['reasons']]))
            await interaction.response.send_message(content=approvals.task_context(job) + '\n\nZgjidh arsyen. Shtyrja dërgohet për konfirmim.',
                view=view, ephemeral=True)
        else:
            await interaction.response.send_modal(TaskActionModal(bot, detail, data, interaction.message, complete=action == 'done'))
        return
    requested = None
    if action == 'skip':
        data = await bot.bridge(f'/bot/reminders/{rid}/one-h-answer', {**actor(interaction),
            'item_id': item_id, 'request_id': str(interaction.id), 'skip': True})
    elif action == 'review':
        requested = interaction.data['values'][0]
    elif action.startswith('page') and action[4:].isdigit():
        offset = int(action[4:]) * 25
        if offset >= len(data['questions']):
            raise ValueError('Faqja nuk është e disponueshme. Rifresko raportimin.')
        requested = data['questions'][offset]['id']
    elif action != 'refresh':
        raise ValueError('Veprim i panjohur.')
    text, view = card(data, requested=requested, join_url=bot.one_h_url(data['bucket'], interaction.guild_id))
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
    text, view = card(data, notice='✅ Përgjigjja u ruajt.', join_url=bot.one_h_url(data['bucket'], message.guild.id))
    await source.edit(content=text, embed=None, view=view)
    return True
