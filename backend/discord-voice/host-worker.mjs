import {pathToFileURL} from 'node:url';
import {Mixer,Playback,createOpusEncoder,int16FromBase64,int16ToBase64,toRealtime} from './host-audio.mjs';
import {createGateway} from './host-gateway.mjs';

// Mira Host: the second Discord bot that speaks in the 1H. It joins with its
// own token, streams everyone's voice to OpenAI Realtime and plays Mira's
// answers. The silent recorder (worker.mjs) keeps running untouched beside it.
export const MAX_LINE=2000000;
const INPUT_CHUNK_MS=100;
const SILENCE=Buffer.from([0xf8,0xff,0xfe]);
const COMMANDS=new Set(['start','say','tool_result','stop','shutdown']);

export function decodeCommand(line){
  if(Buffer.byteLength(line)>MAX_LINE)throw Error('ipc_size');
  const m=JSON.parse(line);
  if(!m||Array.isArray(m)||!COMMANDS.has(m.type))throw Error('ipc_type');
  if(m.type==='start'&&!(/^\d{1,32}$/.test(m.guild_id)&&/^\d{1,32}$/.test(m.channel_id)&&m.token&&m.client_secret&&m.model))throw Error('ipc_start');
  if(m.type==='say'&&typeof m.text!=='string')throw Error('ipc_say');
  if(m.type==='tool_result'&&typeof m.call_id!=='string')throw Error('ipc_tool');
  return m;
}

export function createHost({emit,voice,makeDecoder,makeEncoder=createOpusEncoder,WebSocketImpl=globalThis.WebSocket,
  gatewayFactory=createGateway,now=()=>performance.now(),setTimer=setTimeout,clearTimer=clearTimeout}){
  let gateway,connection,realtime,adapter,guildId,channelId,closed=false,joined=false;
  let responseActive=false,currentResponse=null,inputTimer,outputTimer,inputClock=0,nextFrameAt=0,silenceLeft=0;
  const mixer=new Mixer(),pendingCalls=new Set(),queuedSays=[],cancelled=new Set(),speakerOf=new Map();
  const streams=new Map();
  let encoder,playback;

  function rt(event){if(realtime?.readyState===1)realtime.send(JSON.stringify(event));}
  function fail(reason,extra={}){if(closed)return;emit({type:'interrupted',reason,...extra});stop();}

  // ---- Realtime
  function maybeContinue(){
    if(responseActive||pendingCalls.size)return;
    if(queuedSays.length){
      const text=queuedSays.shift();
      rt({type:'conversation.item.create',item:{type:'message',role:'system',content:[{type:'input_text',text}]}});
      rt({type:'response.create'});responseActive=true;
    }
  }
  function interrupt(){
    const state=playback.clear();
    silenceLeft=5;
    if(state.item&&state.dropped>0){
      rt({type:'conversation.item.truncate',item_id:state.item,content_index:0,audio_end_ms:state.playedMs});
      emit({type:'log',event:'interrupted_by_speaker',played_ms:state.playedMs});
    }
  }
  function onRealtime(message){
    switch(message.type){
      case 'session.created':emit({type:'realtime_ready'});break;
      case 'input_audio_buffer.speech_started':
        mixer.takeLoudest();
        if(playback.playing){if(currentResponse)cancelled.add(currentResponse);interrupt();}
        break;
      case 'input_audio_buffer.speech_stopped':speakerOf.set(message.item_id,mixer.takeLoudest());break;
      case 'conversation.item.input_audio_transcription.completed':
        if(message.transcript?.trim())emit({type:'transcript',role:'staff',speaker_id:speakerOf.get(message.item_id)??null,text:message.transcript.trim()});
        speakerOf.delete(message.item_id);break;
      case 'response.created':responseActive=true;currentResponse=message.response?.id;break;
      case 'response.output_audio.delta':case 'response.audio.delta':
        if(!cancelled.has(message.response_id))playback.push(message.item_id,int16FromBase64(message.delta));break;
      case 'response.output_audio.done':case 'response.audio.done':
        if(!cancelled.has(message.response_id))playback.flush();break;
      case 'response.output_audio_transcript.done':case 'response.audio_transcript.done':
        if(message.transcript?.trim())emit({type:'transcript',role:'mira',text:message.transcript.trim()});break;
      case 'response.output_item.done':
        if(message.item?.type==='function_call'){
          pendingCalls.add(message.item.call_id);
          emit({type:'tool_call',call_id:message.item.call_id,name:message.item.name,arguments:message.item.arguments||'{}'});
        }
        break;
      case 'response.done':responseActive=false;cancelled.delete(message.response?.id);maybeContinue();break;
      case 'error':
        emit({type:'log',event:'realtime_error',code:message.error?.code??null});
        if(message.error?.code==='conversation_already_has_active_response')responseActive=true;
        break;
    }
  }
  function connectRealtime(model,secret){
    realtime=new WebSocketImpl('wss://api.openai.com/v1/realtime?model='+encodeURIComponent(model),
      ['realtime','openai-insecure-api-key.'+secret]);
    realtime.onmessage=event=>{
      let message;try{message=JSON.parse(typeof event.data==='string'?event.data:Buffer.from(event.data).toString());}catch{return;}
      try{onRealtime(message);}catch{emit({type:'log',event:'realtime_event_failed',kind:message?.type??null});}
    };
    realtime.onclose=event=>fail('realtime_closed',{close_code:event?.code??null});
    realtime.onerror=()=>{};
  }

  // ---- Discord audio in/out
  function sendInput(){
    if(closed)return;
    const due=Math.floor((now()-inputClock)*24);
    if(due>=INPUT_CHUNK_MS*24){
      // After a stall (e.g. a long GC) send at most one second; Realtime needs fresh audio, not a backlog.
      const count=Math.min(due,24000);inputClock=now();
      rt({type:'input_audio_buffer.append',audio:int16ToBase64(mixer.pull(count))});
    }
    inputTimer=setTimer(sendInput,INPUT_CHUNK_MS/2);
  }
  function sendOutput(){
    if(closed)return;
    const at=now();let sent=0;
    while(nextFrameAt<=at&&sent<5){
      const frame=playback.next();
      if(frame){connection.prepareAudioPacket(frame);connection.dispatchAudio();silenceLeft=5;}
      else if(silenceLeft>0){connection.prepareAudioPacket(SILENCE);connection.dispatchAudio();if(--silenceLeft===0)connection.setSpeaking(false);}
      nextFrameAt+=20;sent++;
    }
    if(at-nextFrameAt>200)nextFrameAt=at;
    outputTimer=setTimer(sendOutput,Math.max(1,nextFrameAt-now()));
  }
  function listen(id){
    if(closed||streams.has(id))return;
    let decoder;
    try{decoder=makeDecoder();}catch{return;}
    const stream=connection.receiver.subscribe(id,{end:{behavior:voice.EndBehaviorType.AfterSilence,duration:600}});
    streams.set(id,stream);
    const release=()=>{if(streams.get(id)===stream)streams.delete(id);decoder?.delete?.();decoder=null;};
    stream.on('data',packet=>{
      if(closed||!decoder)return;
      try{const pcm=decoder.decode(packet);if(pcm.length)mixer.push(id,toRealtime(pcm));}catch{/* one bad packet is skipped */}
    });
    stream.once('end',release);stream.once('close',release);stream.on('error',release);
  }
  function join(){
    if(joined||closed)return;joined=true;
    connection=voice.joinVoiceChannel({guildId,channelId,selfMute:false,selfDeaf:false,daveEncryption:true,
      adapterCreator:methods=>{adapter=methods;return {sendPayload:payload=>{gateway.raw(payload);return true;},destroy:()=>{}};}});
    connection.on('stateChange',(_old,state)=>{
      if(closed)return;
      if(state.status==='destroyed')fail('voice_disconnected');
      else if(state.status==='disconnected'){
        voice.entersState(connection,voice.VoiceConnectionStatus.Ready,5000).catch(()=>{
          if(closed)return;
          if(!connection.rejoin())fail('voice_disconnected');
        });
      }
    });
    connection.on('error',()=>emit({type:'log',event:'voice_error'}));
    connection.receiver.speaking.on('start',listen);
    voice.entersState(connection,voice.VoiceConnectionStatus.Ready,20000).then(()=>{
      if(closed)return;
      inputClock=now();nextFrameAt=now();sendInput();sendOutput();
      emit({type:'ready',user_id:gateway.userId});
    }).catch(()=>fail('connect_timeout'));
  }

  function start(m){
    guildId=m.guild_id;channelId=m.channel_id;
    encoder=makeEncoder();playback=new Playback(frame=>encoder.encode(frame));
    connectRealtime(m.model,m.client_secret);
    gateway=gatewayFactory({token:m.token,WebSocketImpl,
      onDispatch:(type,data)=>{
        if(closed||!data)return;
        if(type==='GUILD_CREATE'&&data.id===guildId)join();
        else if(type==='VOICE_SERVER_UPDATE'&&data.guild_id===guildId)adapter?.onVoiceServerUpdate(data);
        else if(type==='VOICE_STATE_UPDATE'&&data.guild_id===guildId&&data.user_id===gateway.userId){
          if(joined&&data.channel_id&&data.channel_id!==channelId){fail('voice_moved');return;}
          adapter?.onVoiceStateUpdate(data);
        }
      },
      onClose:code=>fail('gateway_closed',{close_code:code})});
  }

  function stop(){
    if(closed)return;closed=true;
    clearTimer(inputTimer);clearTimer(outputTimer);
    for(const stream of streams.values())stream.destroy?.();
    try{connection?.destroy();}catch{}
    try{realtime?.close();}catch{}
    gateway?.close();encoder?.delete();mixer.clear();
    emit({type:'stopped'});
  }

  return {
    start,stop,
    say(text,{respond=true}={}){
      if(respond){queuedSays.push(text);maybeContinue();}
      else rt({type:'conversation.item.create',item:{type:'message',role:'system',content:[{type:'input_text',text}]}});
    },
    toolResult(callId,output){
      if(!pendingCalls.delete(callId))return;
      rt({type:'conversation.item.create',item:{type:'function_call_output',call_id:callId,output:JSON.stringify(output??{})}});
      if(!pendingCalls.size&&!responseActive){rt({type:'response.create'});responseActive=true;}
    },
    // Exposed for tests.
    _onRealtime:onRealtime,get _playback(){return playback;},
  };
}

async function main(){
  const voice=await import('@discordjs/voice');await import('@snazzah/davey');
  const {createOpusDecoder}=await import('./opus.mjs');
  createOpusDecoder().delete();createOpusEncoder().delete();
  if(typeof globalThis.WebSocket!=='function')throw Error('websocket_unavailable');
  if(process.argv.includes('--check')){process.stdout.write('{"host_ready":true}\n');return;}
  const emit=m=>{const line=JSON.stringify(m)+'\n';if(Buffer.byteLength(line)>MAX_LINE)return;process.stdout.write(line);};
  emit({type:'hello',version:1});
  const host=createHost({emit,voice,makeDecoder:createOpusDecoder});
  let carry='';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data',chunk=>{
    try{
      carry+=chunk;let end;
      while((end=carry.indexOf('\n'))>=0){
        const m=decodeCommand(carry.slice(0,end));carry=carry.slice(end+1);
        if(m.type==='start')host.start(m);
        else if(m.type==='say')host.say(m.text,{respond:m.respond!==false});
        else if(m.type==='tool_result')host.toolResult(m.call_id,m.output);
        else if(m.type==='stop')host.stop();
        else if(m.type==='shutdown'){host.stop();process.stdin.pause();setTimeout(()=>process.exit(0),200);}
      }
      if(Buffer.byteLength(carry)>MAX_LINE)throw Error('ipc_size');
    }catch{emit({type:'interrupted',reason:'worker_command_failed'});host.stop();process.exitCode=1;process.stdin.destroy();}
  });
  process.stdin.on('end',()=>host.stop());
  process.on('SIGTERM',()=>{host.stop();process.exit(0);});
}
if(import.meta.url===pathToFileURL(process.argv[1]||'').href)main().catch(()=>{process.stderr.write('host_preflight_failed\n');process.exitCode=1;});
