"""Persistent shared text-channel panels for the two silent recorders."""
import asyncio
import json
import logging
import time
import discord
from app.config import settings

log = logging.getLogger('primeflow.discord.control')
PREFIX = '/bot/voice-meetings'


def panel_recorder(message):
    """Recognize panels so the two bots never keep moving past each other."""
    for row in getattr(message, 'components', ()):
        for button in row.children:
            parts = (getattr(button, 'custom_id', '') or '').split(':')
            if len(parts) == 5 and parts[:2] == ['pf', 'mc'] and parts[2] in ('primary', 'ai_agent'):
                return parts[2]
    return None


def in_control(interaction):
    return bool(settings.DISCORD_MEETING_CONTROL_CHANNEL_ID and
        str(interaction.channel_id) == settings.DISCORD_MEETING_CONTROL_CHANNEL_ID and
        str(interaction.guild_id) == settings.DISCORD_GUILD_ID)


def require_control(interaction):
    if not in_control(interaction) or getattr(interaction.user, 'bot', False):
        raise ValueError('Përdor panelin te mira-kontrolli.')
    if not interaction.channel.permissions_for(interaction.user).view_channel:
        raise ValueError('Nuk ke qasje në këtë kanal.')


def panel_content(recorder, data):
    label = '1H' if recorder == 'primary' else 'AI Agent'
    meeting = data.get('meeting') or {}
    status = meeting.get('status')
    states = {'STARTING':'Duke u lidhur', 'LISTENING':'Duke regjistruar', 'FINALIZING':'Duke përgatitur shënimet',
        'READY':'Përfunduar · shënimet janë gati', 'SAVED':'Ruajtur', 'FAILED':'Shënimet nuk u përgatitën',
        'INTERRUPTED':'Regjistrimi u ndërpre'}
    text = f'**🎧 Shënimet {label}**\n'
    text += f'**Gjendja: {states.get(status, "Gati")}**\n'
    if meeting.get('private'):
        text += '\nRegjistrimi u nis jashtë panelit; shënimet mbeten në kanalin e organizatorit.'
    if meeting.get('partial'):
        text += '\n⚠ Shënimet mund të jenë të pjesshme.'
    embed = discord.Embed(description=text[:3900], color=0x5865F2)
    view = discord.ui.View(timeout=None)
    sid = meeting.get('id', '-')
    running = status in ('STARTING','LISTENING','FINALIZING')
    for title, action, style, disabled in [
        ('▶ Fillo','start',discord.ButtonStyle.success,running),
        ('⏹ Përfundo','stop',discord.ButtonStyle.danger,status not in ('STARTING','LISTENING')),
        ('💾 Ruaj shënimet','save',discord.ButtonStyle.primary,status != 'READY' or meeting.get('private',False)),
        ('Shiko shënimet','view',discord.ButtonStyle.secondary,status not in ('READY','SAVED') or meeting.get('private',False)),
        ('Rifresko','refresh',discord.ButtonStyle.secondary,False)]:
        view.add_item(discord.ui.Button(label=title, style=style, disabled=disabled,
            custom_id=f'pf:mc:{recorder}:{action}:{"-" if action in ("start","refresh") else sid}'))
    if status == 'SAVED':
        view.add_item(discord.ui.Button(label='Hap shënimet në PrimeFlow',
            url=settings.FRONTEND_URL.rstrip('/')+'/mira?tab=shenimet',row=1))
    return embed, view


class MeetingControlPanel:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.bot = coordinator.bot
        self.recorder = getattr(self.bot, 'voice_recorder', 'primary')
        self.message = None
        self.signature = None
        self.checked_at = 0
        self.lock = asyncio.Lock()
        self.retired = []

    async def remove_retired(self):
        for message in self.retired[:]:
            if message.author.id != self.bot.user.id or panel_recorder(message) != self.recorder:
                self.retired.remove(message)
                continue
            try:
                await message.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException:
                continue
            self.retired.remove(message)

    async def channel(self):
        if not settings.DISCORD_MEETING_CONTROL_CHANNEL_ID:
            raise ValueError('Kanali mira-kontrolli nuk është konfiguruar.')
        channel = self.bot.get_channel(int(settings.DISCORD_MEETING_CONTROL_CHANNEL_ID))
        channel = channel or await self.bot.fetch_channel(int(settings.DISCORD_MEETING_CONTROL_CHANNEL_ID))
        if not isinstance(channel, discord.TextChannel) or str(channel.guild.id) != settings.DISCORD_GUILD_ID:
            raise ValueError('Kanali mira-kontrolli nuk përputhet.')
        return channel

    async def state(self):
        return await self.bot.bridge(PREFIX+f'/control/{self.recorder}/status', {
            'guild_id':settings.DISCORD_GUILD_ID,'channel_id':settings.DISCORD_MEETING_CONTROL_CHANNEL_ID})

    async def refresh(self, *, force=False):
        if not settings.DISCORD_MEETING_CONTROL_CHANNEL_ID or (not force and time.monotonic()-self.checked_at < 15):
            return
        async with self.lock:
            data = await self.state()
            signature = json.dumps(data,sort_keys=True)
            self.checked_at = time.monotonic()
            channel = await self.channel()
            await self.remove_retired()
            if self.message is None:
                marker = f'PrimeFlow shared recorder · {self.recorder}'
                async for message in channel.history(limit=None):
                    owns_panel = panel_recorder(message) == self.recorder
                    if message.author.id == self.bot.user.id and (owns_panel or any(e.footer.text == marker for e in message.embeds)):
                        if self.message is None:
                            self.message = message
                        else:
                            self.retired.append(message)
                await self.remove_retired()
            move = bool(self.message and not self.message.flags.suppress_notifications)
            if self.message:
                async for newer in channel.history(limit=100, after=self.message, oldest_first=False):
                    if panel_recorder(newer) is None:
                        move = True
                        break
            if not force and signature == self.signature and self.message and not move:
                return
            embed, view = panel_content(self.recorder, data)
            try:
                if self.message and not move:
                    await self.message.edit(content=None,embed=embed,view=view,allowed_mentions=discord.AllowedMentions.none())
                else:
                    previous = self.message
                    self.message = await channel.send(embed=embed,view=view,allowed_mentions=discord.AllowedMentions.none(),silent=True)
                    if previous:
                        self.retired.append(previous)
                        await self.remove_retired()
            except discord.NotFound:
                self.message = None
                self.signature = None
                raise
            self.signature = signature

    async def tick(self):
        try:
            await self.refresh()
        except Exception as exc:
            log.warning('Shared meeting panel update failed: %s',type(exc).__name__)

    async def start(self, interaction, title=None, department_id=None):
        require_control(interaction)
        voice_id = settings.DISCORD_1H_VOICE_CHANNEL_ID if self.recorder == 'primary' else settings.DISCORD_AI_AGENT_VOICE_CHANNEL_ID
        channel = interaction.guild.get_channel(int(voice_id or 0))
        if not isinstance(channel,discord.VoiceChannel):
            raise ValueError('Kanali zanor i panelit nuk u gjet.')
        actor = {'discord_user_id':str(interaction.user.id),'guild_id':str(interaction.guild_id),
            'channel_id':str(interaction.channel_id),'voice_channel_id':str(channel.id)}
        async def notify(*args, **kwargs):
            return await interaction.followup.send(*args, **kwargs, wait=True)
        await self.coordinator.begin(actor=actor,guild=interaction.guild,voice=channel,
            request_id=str(interaction.id),title=title,department_id=department_id,notify=notify)
        await self.refresh(force=True)

    async def handle(self, interaction):
        _, _, recorder, action, sid = interaction.data['custom_id'].split(':')
        if recorder != self.recorder:
            return
        await interaction.response.defer(thinking=True,ephemeral=action == 'refresh')
        require_control(interaction)
        if action == 'start':
            await self.start(interaction)
        elif action == 'stop':
            await self.coordinator.stop(interaction,sid)
        elif action in ('save','view'):
            from discord_voice_meetings import identity
            from discord_voice_ui import result_message
            import uuid
            uuid.UUID(sid)
            row = await self.bot.bridge(PREFIX+f'/{sid}/'+('save' if action == 'save' else 'detail'),identity(interaction))
            parts = result_message(row)
            try:
                await interaction.followup.send('Shënimet u ruajtën.' if action == 'save' else None,**parts,ephemeral=False)
            finally:
                if 'file' in parts:parts['file'].close()
        elif action != 'refresh':
            raise ValueError('Veprim i panjohur.')
        await self.refresh(force=True)
        if action == 'refresh':
            await interaction.followup.send('Paneli u rifreskua.',ephemeral=True)
