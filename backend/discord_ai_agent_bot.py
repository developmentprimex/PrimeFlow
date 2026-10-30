"""Receive-only Mira AI Agent, isolated from the 1H recorder and Mira Host."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import discord
import httpx
from discord import app_commands
from discord.ext import tasks
from dotenv import dotenv_values

# Keep the new bot credential outside the runner checkout so routine releases
# cannot replace it with the primary bot's Actions settings.
private_env = Path(os.environ.get('DISCORD_AI_AGENT_ENV_FILE', r'C:\PrimeFlowOps\MiraAIAgent\.env'))
if private_env.exists():
    for key, value in dotenv_values(private_env, interpolate=False).items():
        if key in {'DISCORD_AI_AGENT_BOT_TOKEN', 'DISCORD_AI_AGENT_VOICE_CHANNEL_ID', 'DISCORD_AI_AGENT_BOT_USER_ID'} and value:
            os.environ.setdefault(key, value)
from app.config import settings
import discord_voice_meetings as voice

log = logging.getLogger('primeflow.discord.ai_agent')
STATUS_FILE = Path(__file__).with_name('.discord-ai-agent-status.json')


def validate_configuration():
    token = settings.DISCORD_AI_AGENT_BOT_TOKEN
    if not token or not settings.DISCORD_GUILD_ID or not settings.DISCORD_AI_AGENT_VOICE_CHANNEL_ID:
        raise ValueError('Configure the AI Agent bot token, guild and voice channel.')
    if token in {settings.DISCORD_BOT_TOKEN, settings.MIRA_HOST_BOT_TOKEN}:
        raise ValueError('AI Agent must use a separate bot identity from 1H and Mira Host.')


class AIAgentBot(discord.Client):
    voice_recorder = 'ai_agent'

    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none(), enable_debug_events=True)
        self.tree = app_commands.CommandTree(self)
        self.meeting_capture = AIAgentCapture(self)
        self.http_bridge = httpx.AsyncClient(base_url=settings.PRIMEFLOW_API_BASE_URL.rstrip('/') + '/api/discord',
            timeout=90, headers={'X-Primeflow-Discord-Secret': settings.DISCORD_BRIDGE_SECRET or ''})
        self.admin_http = httpx.AsyncClient(base_url='https://discord.com/api/v10', timeout=30,
            headers={'Authorization': 'Bot ' + (settings.DISCORD_BOT_TOKEN or '')})
        self.primary_user_id = None

    async def bridge(self, path, payload):
        response = await self.http_bridge.post(path, json=payload)
        if response.is_error:
            try:
                detail = response.json().get('detail', 'PrimeFlow e refuzoi kërkesën.')
            except ValueError:
                detail = 'PrimeFlow nuk është i disponueshëm.'
            raise ValueError(str(detail)[:1500])
        return response.json()

    @staticmethod
    def error_message(exc):
        if isinstance(exc, ValueError):
            return str(exc)[:1800]
        log.warning('AI Agent operation failed: %s', type(exc).__name__)
        return 'Veprimi nuk u përfundua. Provo përsëri ose kontrollo gjendjen në PrimeFlow.'

    async def private_channel(self, guild_id, channel_id, user_id):
        if str(guild_id) != settings.DISCORD_GUILD_ID:
            raise ValueError('Përdor serverin Discord të PrimeFlow.')
        response = await self.admin_http.get(f'/channels/{channel_id}')
        response.raise_for_status()
        channel = response.json()
        if channel.get('guild_id') != str(guild_id) or channel.get('type') != 0 or channel.get('topic') != f'PrimeFlow personal workspace: {user_id}':
            raise ValueError('Përdor kanalin tënd personal PrimeFlow.')
        if self.primary_user_id is None:
            me = await self.admin_http.get('/users/@me')
            me.raise_for_status()
            self.primary_user_id = me.json()['id']
        basic = discord.Permissions(view_channel=True, send_messages=True, read_message_history=True).value
        primary = basic | discord.Permissions(manage_channels=True).value
        expected = [{'id': str(guild_id), 'type': 0, 'allow': '0', 'deny': str(discord.Permissions(view_channel=True).value)},
            {'id': str(user_id), 'type': 1, 'allow': str(basic), 'deny': '0'},
            {'id': self.primary_user_id, 'type': 1, 'allow': str(primary), 'deny': '0'},
            {'id': str(self.user.id), 'type': 1, 'allow': str(basic), 'deny': '0'}]
        def signature(values):
            return sorted((item['id'], item['type'], int(item['allow']), int(item['deny'])) for item in values)
        if signature(channel.get('permission_overwrites', [])) != signature(expected):
            repaired = await self.admin_http.patch(f'/channels/{channel_id}', json={'permission_overwrites': expected})
            repaired.raise_for_status()
        return await self.fetch_channel(int(channel_id))

    async def setup_hook(self):
        guild = discord.Object(id=int(settings.DISCORD_GUILD_ID))
        voice.register_meeting_commands(self, guild, name='ai-agent')
        group = self.tree.get_command('ai-agent', guild=guild)
        @group.command(name='statusi', description='Gjendja e regjistrimit të Mira AI Agent')
        async def status(interaction: discord.Interaction):
            active = self.meeting_capture.active
            text = 'Mira AI Agent po merr shënime.' if active and active.get('listening') and not active.get('finishing') else 'Mira AI Agent është gati. Hyr në AI Agent dhe përdor /ai-agent fillo.'
            await interaction.response.send_message(text, ephemeral=True)
        await self.tree.sync(guild=guild)
        self.watch_capture.start()

    @tasks.loop(seconds=15)
    async def watch_capture(self):
        try:
            await self.meeting_capture.check_presence(datetime.now(timezone.utc))
            self.publish_status()
            await self.meeting_capture.panel.tick()
            await voice.deliver_meeting_results(self)
        except Exception as exc:
            log.warning('AI Agent capture check failed: %s', type(exc).__name__)

    @watch_capture.before_loop
    async def before_watch_capture(self):
        await self.wait_until_ready()

    async def on_socket_raw_receive(self, payload):
        try:
            event = json.loads(payload)
        except (TypeError, ValueError):
            return
        if isinstance(event, dict) and event.get('op') == 0 and event.get('t') in ('VOICE_STATE_UPDATE', 'VOICE_SERVER_UPDATE') and isinstance(event.get('d'), dict):
            await self.meeting_capture.gateway(event)

    async def on_interaction(self, interaction):
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = (interaction.data or {}).get('custom_id', '')
        if not custom_id.startswith(('pf:vm:', 'pf:mc:ai_agent:')):return
        try:
            if custom_id.startswith('pf:mc:'):
                await self.meeting_capture.panel.handle(interaction)
            else:
                await voice.handle_meeting_interaction(self, interaction)
        except Exception as exc:
            if interaction.response.is_done():
                await interaction.followup.send(self.error_message(exc), ephemeral=True)
            else:
                await interaction.response.send_message(self.error_message(exc), ephemeral=True)

    def clear_status(self):
        try:
            if json.loads(STATUS_FILE.read_text(encoding='utf-8')).get('pid') == os.getpid():
                STATUS_FILE.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass

    def publish_status(self):
        guild = self.get_guild(int(settings.DISCORD_GUILD_ID))
        channel = guild.get_channel(int(settings.DISCORD_AI_AGENT_VOICE_CHANNEL_ID)) if guild else None
        if not guild or not isinstance(channel, discord.VoiceChannel) or not self.user:
            self.clear_status()
            log.error('AI Agent bot is missing its configured guild or voice channel')
            return
        permissions = channel.permissions_for(guild.me)
        voice_permissions = {name: bool(getattr(permissions, name)) for name in ('view_channel', 'connect', 'send_messages')}
        status = {'ready': all(voice_permissions.values()), 'pid': os.getpid(), 'bot_user_id': str(self.user.id),
            'guild_id': str(guild.id), 'voice_channel_id': str(channel.id), 'voice_channel_name': channel.name,
            'permissions': voice_permissions, 'connected_at': datetime.now(timezone.utc).isoformat(),
            'commands_configured': True, 'recording_enabled': True,
            'recording': bool(self.meeting_capture.active and self.meeting_capture.active.get('listening') and not self.meeting_capture.active.get('finishing'))}
        temporary = STATUS_FILE.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(status, ensure_ascii=False), encoding='utf-8')
        temporary.replace(STATUS_FILE)
        log.info('Mira AI Agent connected; voice permissions ready=%s', status['ready'])

    async def on_ready(self):
        await self.meeting_capture.cleanup_idle_voice()
        self.publish_status()

    async def on_resumed(self):
        await self.meeting_capture.cleanup_idle_voice()
        self.publish_status()

    async def on_disconnect(self):
        self.clear_status()
        await self.meeting_capture.interrupt('gateway_disconnected')

    async def close(self):
        self.clear_status()
        self.watch_capture.cancel()
        await self.meeting_capture.close()
        await self.http_bridge.aclose()
        await self.admin_http.aclose()
        await super().close()


class AIAgentCapture(voice.MeetingCaptureCoordinator):
    async def start(self, interaction, title, department_id):
        from discord_meeting_control import in_control
        if in_control(interaction):
            return await super().start(interaction,title,department_id)
        channel = getattr(getattr(interaction.user, 'voice', None), 'channel', None)
        if str(getattr(channel, 'id', '')) != settings.DISCORD_AI_AGENT_VOICE_CHANNEL_ID:
            raise ValueError('Hyr në kanalin zanor AI Agent, pastaj përdor /ai-agent fillo.')
        await super().start(interaction, title, department_id)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    validate_configuration()
    AIAgentBot().run(settings.DISCORD_AI_AGENT_BOT_TOKEN, log_handler=None)
