"""Local receive-only Node transport. No credentials are inherited by the child."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

MAX_LINE = 3_000_000
VOICE_DIR = Path(__file__).resolve().parent / 'discord-voice'


class VoiceCaptureClient:
    def __init__(self, send_gateway, on_segment, on_interruption):
        self.send_gateway, self.on_segment, self.on_interruption = send_gateway, on_segment, on_interruption
        self.process = None
        self.reader = None
        self.uploads = set()
        self.upload_limit = asyncio.Semaphore(2)
        self.closing = False
        self.failed = False
        self.last_sequence = 0
        self.session_id = self.instance_id = self.guild_id = self.channel_id = None
        self.ready = self.stopped = None

    @staticmethod
    def child_env():
        return {key: value for key, value in os.environ.items()
            if key.upper() in {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','USERPROFILE','LOCALAPPDATA'}}

    async def start(self, *, session_id, instance_id, guild_id, channel_id, bot_user_id, node='node'):
        self.session_id, self.instance_id, self.guild_id, self.channel_id = str(session_id), str(instance_id), str(guild_id), str(channel_id)
        loop = asyncio.get_running_loop()
        self.ready, self.stopped = loop.create_future(), loop.create_future()
        self.process = await asyncio.create_subprocess_exec(node, str(VOICE_DIR / 'worker.mjs'),
            cwd=str(VOICE_DIR), env=self.child_env(), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=MAX_LINE+1)
        if self.closing:
            self.process.kill();await self.process.wait()
            raise ValueError('capture_cancelled')
        self.reader = asyncio.create_task(self._read())
        await self.send({'type':'start', 'guild_id':self.guild_id, 'channel_id':self.channel_id, 'user_id':str(bot_user_id)})
        await asyncio.wait_for(asyncio.shield(self.ready), 20)

    async def send(self, message):
        if not self.process or self.process.returncode is not None:
            raise ValueError('voice_process_unavailable')
        payload = {'session_id':self.session_id, 'instance_id':self.instance_id, **message}
        line = (json.dumps(payload, separators=(',',':'))+'\n').encode()
        if len(line)>MAX_LINE: raise ValueError('ipc_size')
        self.process.stdin.write(line)
        await self.process.stdin.drain()

    async def gateway(self, event):
        if self.closing or not self.process or event.get('t') not in ('VOICE_STATE_UPDATE','VOICE_SERVER_UPDATE'):
            return
        if str(event.get('d',{}).get('guild_id')) != self.guild_id: return
        await self.send({'type':'gateway','event':event})

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                if len(line)>MAX_LINE: raise ValueError('ipc_size')
                await self.handle(json.loads(line))
            if not self.closing: await self._fail('voice_process_closed')
        except (ValueError, OSError, asyncio.IncompleteReadError):
            if not self.closing: await self._fail('voice_protocol_error')

    async def handle(self, message):
        if not isinstance(message,dict): raise ValueError('ipc_type')
        kind=message.get('type')
        if kind=='hello':
            if message.get('version')!=1: raise ValueError('ipc_version')
            return
        if message.get('session_id')!=self.session_id or message.get('instance_id')!=self.instance_id:
            raise ValueError('ipc_session')
        if kind=='gateway_send':
            payload=message.get('payload')
            if not isinstance(payload,dict) or not isinstance(payload.get('d'),dict):raise ValueError('gateway_shape')
            data=payload['d']
            if payload.get('op')!=4 or set(payload)!={'op','d'} or set(data)-{'guild_id','channel_id','self_mute','self_deaf'}:
                raise ValueError('gateway_operation')
            if data.get('guild_id')!=self.guild_id or data.get('channel_id') not in (None,self.channel_id) or data.get('self_mute') is not True or data.get('self_deaf') is not False:
                raise ValueError('gateway_scope')
            await self.send_gateway(payload)
        elif kind=='ready':
            if self.ready and not self.ready.done(): self.ready.set_result(None)
        elif kind=='stopped':
            count=message.get('last_sequence')
            if type(count) is not int or count<0: raise ValueError('ipc_sequence')
            if self.stopped and not self.stopped.done(): self.stopped.set_result(message)
        elif kind=='segment':
            if type(message.get('sequence')) is not int or message['sequence']!=self.last_sequence:raise ValueError('ipc_sequence')
            self.last_sequence+=1
            if len(self.uploads)>=8: await self._fail('audio_backpressure');return
            task=asyncio.create_task(self._upload(message));self.uploads.add(task);task.add_done_callback(self.uploads.discard)
        elif kind=='interrupted':
            await self._fail('audio_interrupted')
        else: raise ValueError('ipc_type')

    async def _upload(self, message):
        try:
            async with self.upload_limit: await self.on_segment(message)
            await self.send({'type':'credit','sequence':message['sequence']})
        except Exception:
            await self._fail('transcription_failed')

    async def _fail(self, reason):
        if self.failed: return
        self.failed=True
        if self.ready and not self.ready.done(): self.ready.set_exception(ValueError(reason))
        # Callback must be independent of the reader, otherwise stop waits on itself.
        task=asyncio.create_task(self.on_interruption(reason))
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    async def stop(self):
        if self.stopped and self.stopped.done(): return self.stopped.result()
        await self.send({'type':'stop'})
        return await asyncio.wait_for(asyncio.shield(self.stopped),20)

    async def drain(self):
        if self.uploads: await asyncio.wait_for(asyncio.gather(*list(self.uploads),return_exceptions=True),300)

    async def close(self):
        if self.closing:return
        self.closing=True
        if self.process:
            try: await self.send({'type':'shutdown'})
            except (ValueError,OSError,ConnectionError): pass
            try: await asyncio.wait_for(self.process.wait(),3)
            except asyncio.TimeoutError:
                self.process.kill();await self.process.wait()
        if self.guild_id:
            try:await asyncio.wait_for(self.send_gateway({'op':4,'d':{'guild_id':self.guild_id,'channel_id':None,'self_mute':True,'self_deaf':False}}),3)
            except Exception:pass
        if self.reader:
            self.reader.cancel();await asyncio.gather(self.reader,return_exceptions=True)
        for task in list(self.uploads):task.cancel()
        await asyncio.gather(*list(self.uploads),return_exceptions=True)
        for future in (self.ready,self.stopped):
            if future and future.done() and not future.cancelled():future.exception()
