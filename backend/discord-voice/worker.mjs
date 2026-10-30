import {pathToFileURL} from 'node:url';
import {Console} from 'node:console';
import {SegmentBuffer} from './audio.mjs';
import {decodeMessage,MAX_LINE} from './protocol.mjs';

// Undecodable audio from everyone for this long means capture is broken, not hiccuping.
const UNDECODABLE_LIMIT_MS=30000;

// No player, encoder, TTS or audio-sending API is used by this worker.
export function createReceiver({sessionId,instanceId,guildId,channelId,userId,emit,voice,makeDecoder,now=()=>performance.now()}) {
  const began=now(),streams=new Map(),decoders=new Map(),timers=new Set();
  let adapter,closed=false,partial=false,recovering=false,troubleSince=null;
  const out=m=>emit({...m,session_id:sessionId,instance_id:instanceId});
  const buffer=new SegmentBuffer(out);
  const connection=voice.joinVoiceChannel({guildId,channelId,selfMute:true,selfDeaf:false,daveEncryption:true,
    adapterCreator:methods=>{adapter=methods;return {sendPayload:payload=>{out({type:'gateway_send',payload});return true;},destroy:()=>{}};}});
  function stop(){
    if(closed)return;closed=true;
    for(const timer of timers)clearTimeout(timer);
    for(const stream of streams.values())stream.destroy?.();
    try{buffer.stop();}catch{partial=true;buffer.clear();}
    for(const decoder of decoders.values())decoder.delete?.();decoders.clear();
    connection.destroy();out({type:'stopped',last_sequence:buffer.sequence,partial});
  }
  function fail(reason,details={}){if(closed)return;partial=true;out({type:'interrupted',reason,...details});stop();}
  // Lost audio is always reported; only audio lost from everyone for a long time stops the meeting.
  function trouble(reason){
    partial=true;troubleSince??=now();
    if(now()-troubleSince>=UNDECODABLE_LIMIT_MS){fail(reason);return true;}
    return false;
  }
  async function recover(closeCode){
    recovering=true;partial=true;out({type:'audio_gap',reason:'voice_reconnecting'});
    try{
      try{await voice.entersState(connection,voice.VoiceConnectionStatus.Ready,5000);}
      catch{
        if(closed)return;
        // Discord did not reconnect by itself (e.g. close code 4014 on a voice server change):
        // ask once to rejoin the same channel, still muted.
        if(!connection.rejoin())throw Error('rejoin_unavailable');
        await voice.entersState(connection,voice.VoiceConnectionStatus.Ready,20000);
      }
    }catch{fail('voice_disconnected',{close_code:closeCode});}
    finally{recovering=false;}
  }
  // The library reconnects on its own after transport errors; they are not fatal.
  connection.on('error',()=>{if(!closed)out({type:'audio_gap',reason:'voice_error'});});
  connection.on('stateChange',(_old,state)=>{
    if(closed)return;
    if(state.status==='destroyed')fail('voice_disconnected',{close_code:state.closeCode});
    else if(state.status==='disconnected'&&!recovering)recover(state.closeCode);
  });
  connection.receiver.speaking.on('start',id=>{
    if(closed||streams.has(id))return;
    let decoded=false,badPackets=0,released=false,decoder;
    const stream=connection.receiver.subscribe(id,{end:{behavior:voice.EndBehaviorType.AfterSilence,duration:1200}});
    streams.set(id,stream);
    const watchdog=setTimeout(()=>{timers.delete(watchdog);if(!decoded)drop('no_decoded_audio');},10000);timers.add(watchdog);
    function release(){
      if(released)return;released=true;
      if(streams.get(id)===stream)streams.delete(id);
      clearTimeout(watchdog);timers.delete(watchdog);
      if(!closed){try{buffer.flush(id);}catch{fail('audio_backpressure');}}
      // stop() may already have freed it; a WASM decoder must not be freed twice.
      if(decoder&&decoders.get(id)===decoder){decoders.delete(id);decoder.delete?.();}
    }
    // A problem with one speaker's stream ends only that stream; the next
    // speaking start subscribes them again.
    function drop(reason){
      if(released||closed)return;
      if(trouble(reason))return;
      out({type:'audio_gap',reason});release();stream.destroy?.();
    }
    try{decoder=makeDecoder();decoders.set(id,decoder);}catch{drop('decoder_error');return;}
    stream.on('data',packet=>{
      if(closed||released)return;
      let pcm;
      try{pcm=decoder.decode(packet);}
      catch(error){
        const reason=new Map([
          ['Decode error: Invalid packet','decode_invalid_packet'],
          ['Decode error: Bad argument','decode_bad_argument'],
          ['Decode error: Buffer too small','decode_frame_too_large']
        ]).get(error?.message);
        if(!reason){drop('decode_error');return;}
        // A transient malformed packet must not disconnect every participant.
        // Report any loss, and keep a finite recovery budget per speaker.
        badPackets++;
        if(trouble('decode_error'))return;
        if(badPackets===1)out({type:'audio_gap',reason});
        if(badPackets>=100)drop('decode_error');
        return;
      }
      badPackets=0;
      if(pcm.length){decoded=true;troubleSince=null;try{buffer.push(id,pcm,now()-began);}catch{fail('audio_backpressure');}}
    });
    stream.once('end',release);
    stream.once('close',release);
    stream.on('error',()=>drop('receive_error'));
  });
  const ready=voice.entersState(connection,voice.VoiceConnectionStatus.Ready,15000).then(()=>{if(!closed)out({type:'ready'});}).catch(()=>fail('connect_timeout'));
  return {ready,stop,destroy:stop,credit:sequence=>buffer.credit(sequence),gateway:event=>{
    if(closed||event?.d?.guild_id!==guildId)return;
    if(event.t==='VOICE_SERVER_UPDATE')adapter.onVoiceServerUpdate(event.d);
    if(event.t==='VOICE_STATE_UPDATE'&&event.d.user_id===userId){
      if(event.d.channel_id!==channelId){fail('voice_moved');return;}
      adapter.onVoiceStateUpdate(event.d);
    }
  }};
}

async function main(){
  // stdout is exclusively framed IPC. Dependency diagnostics (including WASM
  // console output) must not be interpreted as audio protocol messages.
  globalThis.console=new Console({stdout:process.stderr,stderr:process.stderr});
  const voice=await import('@discordjs/voice');const {createOpusDecoder}=await import('./opus.mjs');await import('@snazzah/davey');
  const makeDecoder=createOpusDecoder;
  const probe=makeDecoder();probe.delete();
  if(process.argv.includes('--check')){process.stdout.write('{"voice_ready":true}\n');return;}
  let receiver,session,instance,carry='';
  const emit=m=>{const line=JSON.stringify(m)+'\n';if(Buffer.byteLength(line)>MAX_LINE)throw Error('ipc_size');if(!process.stdout.write(line)&&process.stdout.writableLength>24*1024*1024)throw Error('ipc_backpressure');};
  emit({type:'hello',version:1});
  function command(m){
    if(m.type==='shutdown'){receiver?.stop();process.stdin.pause();process.exitCode=0;return;}
    if(m.type==='start'){
      if(receiver)throw Error('already_started');session=m.session_id;instance=m.instance_id;
      receiver=createReceiver({sessionId:session,instanceId:instance,guildId:m.guild_id,channelId:m.channel_id,userId:m.user_id,voice,makeDecoder,emit});return;
    }
    if(m.session_id!==session||m.instance_id!==instance)throw Error('ipc_session');
    if(m.type==='gateway')receiver.gateway(m.event);
    if(m.type==='credit')receiver.credit(m.sequence);
    if(m.type==='stop')receiver.stop();
  }
  process.stdin.setEncoding('utf8');process.stdin.on('data',chunk=>{
    try{carry+=chunk;let end;while((end=carry.indexOf('\n'))>=0){const line=carry.slice(0,end);carry=carry.slice(end+1);command(decodeMessage(line));}if(Buffer.byteLength(carry)>MAX_LINE)throw Error('ipc_size');}
    catch{if(session)emit({type:'interrupted',reason:'worker_command_failed',session_id:session,instance_id:instance});receiver?.destroy();process.exitCode=1;process.stdin.destroy();}
  });
  process.stdin.on('end',()=>receiver?.destroy());
  process.on('SIGTERM',()=>{receiver?.destroy();process.exit(0);});
}
if(import.meta.url===pathToFileURL(process.argv[1]||'').href)main().catch(()=>{process.stderr.write('voice_preflight_failed\n');process.exitCode=1;});
