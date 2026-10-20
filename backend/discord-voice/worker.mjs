import {pathToFileURL} from 'node:url';
import {SegmentBuffer} from './audio.mjs';
import {decodeMessage,MAX_LINE} from './protocol.mjs';

// No player, encoder, TTS or audio-sending API is used by this worker.
export function createReceiver({sessionId,instanceId,guildId,channelId,userId,emit,voice,makeDecoder,now=()=>performance.now()}) {
  const began=now(),streams=new Map(),decoders=new Map(),timers=new Set();let adapter,closed=false,partial=false;
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
  function fail(reason){if(closed)return;partial=true;out({type:'interrupted',reason});stop();}
  connection.on('error',()=>fail('voice_error'));
  connection.on('stateChange',(_old,state)=>{if(!closed&&['disconnected','destroyed'].includes(state.status))fail('voice_disconnected');});
  connection.receiver.speaking.on('start',id=>{
    if(closed||streams.has(id))return;
    let decoded=false;
    const watchdog=setTimeout(()=>{timers.delete(watchdog);if(!decoded)fail('no_decoded_audio');},10000);timers.add(watchdog);
    const stream=connection.receiver.subscribe(id,{end:{behavior:voice.EndBehaviorType.AfterSilence,duration:700}});
    streams.set(id,stream);
    let decoder;
    try{decoder=makeDecoder();decoders.set(id,decoder);}catch{fail('decoder_error');return;}
    stream.on('data',packet=>{if(closed)return;try{const pcm=decoder.decode(packet);if(pcm.length){decoded=true;buffer.push(id,pcm,now()-began);}}catch{fail('decode_error');}});
    stream.once('end',()=>{streams.delete(id);clearTimeout(watchdog);timers.delete(watchdog);try{buffer.flush(id);}catch{fail('audio_backpressure');}decoder.delete?.();decoders.delete(id);});
    stream.once('error',()=>fail('receive_error'));
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
  const voice=await import('@discordjs/voice');const {default:Opus}=await import('opusscript');await import('@snazzah/davey');
  const makeDecoder=()=>new Opus(48000,2,Opus.Application.AUDIO);
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
    catch{receiver?.destroy();process.exitCode=1;process.stdin.destroy();}
  });
  process.stdin.on('end',()=>receiver?.destroy());
  process.on('SIGTERM',()=>{receiver?.destroy();process.exit(0);});
}
if(import.meta.url===pathToFileURL(process.argv[1]||'').href)main().catch(()=>{process.stderr.write('voice_preflight_failed\n');process.exitCode=1;});
