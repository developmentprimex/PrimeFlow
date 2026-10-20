"""Silent staff meetings controlled by the existing Discord bot."""
import asyncio
import base64
import secrets
import uuid
from datetime import datetime
from contextlib import suppress
import discord
from discord import app_commands
from discord.ext import tasks
from app.config import settings
from discord_voice_client import VoiceCaptureClient, VOICE_DIR
from discord_voice_ui import meeting_view, result_message, send_durable

PREFIX='/bot/voice-meetings'


def identity(interaction):
    channel=getattr(getattr(interaction.user,'voice',None),'channel',None)
    return dict(discord_user_id=str(interaction.user.id),guild_id=str(interaction.guild_id),
        channel_id=str(interaction.channel_id),voice_channel_id=str(channel.id) if channel else None)


class MeetingCaptureCoordinator:
    def __init__(self,bot):
        self.bot=bot;self.active=None;self.lock=asyncio.Lock();self.finalization=None;self.background=set()

    async def preflight(self):
        process=await asyncio.create_subprocess_exec(settings.DISCORD_VOICE_NODE_BINARY,str(VOICE_DIR/'worker.mjs'),'--check',
            cwd=str(VOICE_DIR),env=VoiceCaptureClient.child_env(),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
        try:output,_=await asyncio.wait_for(process.communicate(),20)
        except asyncio.TimeoutError:
            process.kill();await process.wait();raise ValueError('Shërbimi i audios nuk u nis.') from None
        if process.returncode or b'"voice_ready":true' not in output:raise ValueError('Shërbimi i audios nuk është gati.')

    async def start(self,interaction,title,department_id):
        async with self.lock:
            if self.active:raise ValueError('Një takim po dëgjohet tashmë.')
            channel=getattr(getattr(interaction.user,'voice',None),'channel',None)
            if not isinstance(channel,discord.VoiceChannel):raise ValueError('Hyr në një voice channel të zakonshëm.')
            await self.bot.private_channel(interaction.guild_id,interaction.channel_id,interaction.user.id)
            permissions=channel.permissions_for(interaction.guild.me)
            if not all((permissions.view_channel,permissions.connect,permissions.send_messages)):
                raise ValueError('Mira ka nevojë për View Channel, Connect dhe Send Messages.')
            await self.preflight()
            worker={'capture_token':secrets.token_urlsafe(32),'instance_id':str(uuid.uuid4())}
            row=await self.bot.bridge(PREFIX+'/start',{**identity(interaction),**worker,
                'request_id':str(interaction.id),'title':(title or f'{channel.name} · {datetime.now().strftime("%d.%m.%Y %H:%M")}')[:200],
                'department_id':department_id})
            active={'id':row['id'],'worker':worker,'actor':identity(interaction),'capture':None,
                'partial':False,'heartbeat':None,'finishing':False,'voice_channel':channel}
            self.active=active
            try:
                # A visible notice is a prerequisite, never a best-effort afterthought.
                await channel.send('Mira po merr shënime për këtë takim. Nuk do të flasë.',allowed_mentions=discord.AllowedMentions.none())
                if active['finishing'] or self.active is not active:raise ValueError('Nisja e takimit u anulua.')
                active['heartbeat']=asyncio.create_task(self.heartbeat(active))
                async def upload(message):await self.upload(active,message)
                async def interrupted(reason):await self.interrupt(reason)
                capture=VoiceCaptureClient(self.bot.ws.send_as_json,upload,interrupted);active['capture']=capture
                await capture.start(session_id=row['id'],instance_id=worker['instance_id'],guild_id=interaction.guild_id,
                    channel_id=channel.id,bot_user_id=self.bot.user.id,node=settings.DISCORD_VOICE_NODE_BINARY)
                if active['finishing'] or self.active is not active:raise ValueError('Nisja e takimit u anulua.')
                await self.bot.bridge(PREFIX+f"/{row['id']}/listening",worker)
                row['status']='LISTENING'
                await interaction.followup.send('Mira po dëgjon në heshtje.',view=meeting_view(row))
            except Exception:
                if active['capture']:
                    with suppress(Exception):await active['capture'].close()
                if active['heartbeat']:active['heartbeat'].cancel()
                with suppress(Exception):await self.bot.bridge(PREFIX+f"/{row['id']}/interrupt",{**worker,'reason':'startup_failed'})
                if self.active is active:self.active=None
                raise

    async def heartbeat(self,active):
        # The API expires a session after 60 s without a heartbeat; three missed
        # 10 s beats in a row still fit inside that window.
        failures=0
        try:
            while self.active is active:
                await asyncio.sleep(10)
                try:
                    await self.bot.bridge(PREFIX+f"/{active['id']}/heartbeat",active['worker']);failures=0
                except asyncio.CancelledError:raise
                except Exception:
                    failures+=1
                    if failures>=3:await self.interrupt('heartbeat_failed');return
        except asyncio.CancelledError:pass

    async def upload(self,active,message):
        import httpx
        seq=message.get('sequence');speaker=message.get('speaker_id')
        if type(seq) is not int or seq<0 or not isinstance(speaker,str) or not speaker.isdigit():raise ValueError('invalid_segment')
        audio=base64.b64decode(message['audio_base64'],validate=True)
        if len(audio)>2_000_000:raise ValueError('invalid_audio_size')
        guild=self.bot.get_guild(int(active['actor']['guild_id']))
        person=guild.get_member(int(speaker)) if guild else None
        fields={**active['worker'],'sequence':str(seq),'speaker_id':speaker,
            'speaker_name':(person.display_name if person else 'Discord '+speaker)[:100],
            'start_ms':str(message['start_ms']),'end_ms':str(message['end_ms'])}
        for attempt in range(3):
            try:
                response=await self.bot.http_bridge.post(PREFIX+f"/{active['id']}/segments",data=fields,
                    files={'file':('meeting.wav',audio,'audio/wav')})
                response.raise_for_status();receipt=response.json()
                if receipt.get('status')=='ERROR':
                    # The API stored this segment as failed; a retry returns the same answer.
                    active['partial']=True;raise RuntimeError('transcription_failed')
                if receipt.get('status')!='DONE':raise ValueError('transcription_failed')
                return
            except (httpx.HTTPError,ValueError):
                if attempt==2:active['partial']=True;raise
                await asyncio.sleep(attempt+1)

    async def stop(self,interaction,session_id=None):
        active=self.active
        if not active or (session_id and session_id!=active['id']):raise ValueError('Nuk ka takim aktiv në këtë proces.')
        await self.bot.private_channel(interaction.guild_id,interaction.channel_id,interaction.user.id)
        await self.bot.bridge(PREFIX+f"/{active['id']}/authorize-stop",identity(interaction))
        if active['finishing']:
            await interaction.followup.send('Shënimet po përgatiten.');return
        active['finishing']=True
        try:
            end=await active['capture'].stop() if active['capture'] else {'last_sequence':0,'partial':False}
        except Exception:
            active['partial']=True
            with suppress(Exception):await active['capture'].close()
            with suppress(Exception):await self.bot.bridge(PREFIX+f"/{active['id']}/interrupt",{**active['worker'],'reason':'stop_failed'})
            end={'last_sequence':getattr(active['capture'],'last_sequence',0),'partial':True}
        self.finalization=asyncio.create_task(self.finalize(active,end))
        self.background.add(self.finalization);self.finalization.add_done_callback(self.background.discard)
        await interaction.followup.send('Dëgjimi u ndal. Po përgatis shënimet.')

    async def finalize(self,active,end):
        try:
            if active['capture']:await active['capture'].drain()
            await self.bot.bridge(PREFIX+f"/{active['id']}/finish",{**active['worker'],
                'segment_count':end['last_sequence'],'partial':bool(end['partial'] or active['partial'] or getattr(active['capture'],'failed',False))})
        except Exception:
            with suppress(Exception):await self.bot.bridge(PREFIX+f"/{active['id']}/interrupt",{**active['worker'],'reason':'finalization_failed'})
        finally:
            if active.get('heartbeat'):active['heartbeat'].cancel()
            try:
                if active['capture']:await active['capture'].close()
            finally:
                if self.active is active:self.active=None

    async def interrupt(self,reason):
        active=self.active
        if not active or active['finishing']:return
        active['finishing']=True;active['partial']=True
        # Interrupt/leave takes precedence over every provider call.
        try:end=await active['capture'].stop() if active['capture'] else {'last_sequence':0,'partial':True}
        except Exception:
            if active['capture']:await active['capture'].close()
            end={'last_sequence':getattr(active['capture'],'last_sequence',0),'partial':True}
        with suppress(Exception):await self.bot.bridge(PREFIX+f"/{active['id']}/interrupt",{**active['worker'],'reason':'audio_interrupted'})
        self.finalization=asyncio.create_task(self.finalize(active,end)) if active['capture'] else None
        if self.finalization:self.background.add(self.finalization);self.finalization.add_done_callback(self.background.discard)
        with suppress(Exception):
            channel=await self.bot.private_channel(active['actor']['guild_id'],active['actor']['channel_id'],active['actor']['discord_user_id'])
            await channel.send('Dëgjimi u ndërpre. Shënimet mund të jenë të pjesshme.')

    async def gateway(self,event):
        if self.active and self.active.get('capture'):
            try:await self.active['capture'].gateway(event)
            except Exception:await self.interrupt('gateway_failed')

    async def close(self):
        if self.active:await self.interrupt('shutdown')
        if self.background:
            try:await asyncio.wait_for(asyncio.gather(*list(self.background),return_exceptions=True),5)
            except asyncio.TimeoutError:pass
        if self.active and self.active.get('capture'):await self.active['capture'].close()


def register_meeting_commands(bot,guild):
    if not settings.DISCORD_MEETING_NOTES_ENABLED:return
    group=app_commands.Group(name='takimi',description='Mira dëgjon takimin dhe merr shënime')
    @group.command(name='fillo',description='Fto Mira-n të dëgjojë pa folur')
    async def start(interaction:discord.Interaction,titulli:str|None=None,departamenti:str|None=None):
        await interaction.response.defer(thinking=True)
        try:
            department=str(uuid.UUID(departamenti)) if departamenti else None
            await bot.meeting_capture.start(interaction,titulli,department)
        except Exception as exc:await interaction.followup.send(bot.error_message(exc),ephemeral=True)
    @group.command(name='mbaro',description='Ndalo dëgjimin dhe përgatit shënimet')
    async def stop(interaction:discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:await bot.meeting_capture.stop(interaction)
        except Exception as exc:await interaction.followup.send(bot.error_message(exc),ephemeral=True)
    bot.tree.add_command(group,guild=guild)


async def handle_meeting_interaction(bot,interaction):
    _,_,action,sid=interaction.data['custom_id'].split(':');uuid.UUID(sid)
    await interaction.response.defer(thinking=True,ephemeral=True)
    await bot.private_channel(interaction.guild_id,interaction.channel_id,interaction.user.id)
    if action=='stop':await bot.meeting_capture.stop(interaction,sid);return
    if action not in ('view','save'):raise ValueError('Veprim i panjohur.')
    row=await bot.bridge(PREFIX+f'/{sid}/'+('save' if action=='save' else 'detail'),identity(interaction))
    parts=result_message(row)
    try:await interaction.followup.send('U ruajt.' if action=='save' else None,**parts,ephemeral=True)
    finally:
        if 'file' in parts:parts['file'].close()


async def deliver_meeting_results(bot):
    jobs=(await bot.bridge(PREFIX+'/delivery/claim',{}))['jobs']
    for job in jobs:
        try:
            channel=await bot.private_channel(job['guild_id'],job['channel_id'],job['discord_user_id'])
            row=await bot.bridge(PREFIX+f"/{job['id']}/detail",{k:job[k] for k in ('discord_user_id','guild_id','channel_id')})
            ids=await send_durable(bot,channel,row)
            await bot.bridge(PREFIX+f"/{job['id']}/delivery/ack",{'delivery_token':job['delivery_token'],'message_ids':ids})
        except Exception:
            # Leave the lease unacknowledged; next claim retries without public fallback.
            continue
