import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {FRAME_BYTES,Mixer,Playback,createOpusEncoder,toDiscord,toRealtime,int16FromBase64,int16ToBase64} from '../host-audio.mjs';
import {createOpusDecoder} from '../opus.mjs';
import {BARGE_IN_MS,SAY_WAIT_MS,createHost,decodeCommand} from '../host-worker.mjs';

test('48 kHz stereo becomes 24 kHz mono and back without changing the level',()=>{
  const pcm=Buffer.alloc(960*4);
  for(let i=0;i<960;i++){pcm.writeInt16LE(1000,i*4);pcm.writeInt16LE(3000,i*4+2);}
  const mono=toRealtime(pcm);
  assert.equal(mono.length,480);
  assert.ok(mono.every(v=>v===2000));
  const {pcm:back}=toDiscord(mono,2000);
  assert.equal(back.length,960*4);
  assert.equal(back.readInt16LE(0),2000);assert.equal(back.readInt16LE(2),2000);
  assert.deepEqual(int16FromBase64(int16ToBase64(mono)),mono);
});

test('the mixer adds speakers, clips, keeps silence and names the loudest speaker',()=>{
  const mixer=new Mixer();
  mixer.push('a',Int16Array.from([100,30000,0]));
  mixer.push('b',Int16Array.from([50,30000]));
  assert.deepEqual([...mixer.pull(4)],[150,32767,0,0]);
  assert.deepEqual([...mixer.pull(2)],[0,0]);
  mixer.takeLoudest();
  mixer.push('quiet',Int16Array.from([1,1]));mixer.push('loud',Int16Array.from([900,900]));
  assert.equal(mixer.takeLoudest(),'loud');
  assert.equal(mixer.takeLoudest(),null);
});

test('a speaker far behind does not build up delay',()=>{
  const mixer=new Mixer({maxBufferedMs:100});
  for(let i=0;i<10;i++)mixer.push('a',new Int16Array(960));
  assert.ok(mixer.queues.get('a').reduce((n,s)=>n+s.length,0)<=2400+960);
});

test('the encoder produces Opus frames the existing decoder plays back at the same level',()=>{
  const encoder=createOpusEncoder(),decoder=createOpusDecoder();
  const pcm=Buffer.alloc(FRAME_BYTES);
  for(let i=0;i<960;i++){const v=Math.round(Math.sin(2*Math.PI*440*i/48000)*8000);pcm.writeInt16LE(v,i*4);pcm.writeInt16LE(v,i*4+2);}
  let out;
  for(let i=0;i<6;i++)out=decoder.decode(encoder.encode(pcm));
  let energy=0;for(let i=0;i<960;i++)energy+=out.readInt16LE(i*4)**2;
  const rms=Math.sqrt(energy/960);
  assert.ok(rms>4500&&rms<7000,`rms ${rms}`);
  encoder.delete();decoder.delete();
});

test('playback frames 20 ms of audio and an interruption drops the rest at once',()=>{
  const playback=new Playback(frame=>frame.subarray(0,4));
  playback.push('item1',new Int16Array(480*3+100));
  assert.equal(playback.frames.length,3);
  playback.flush();
  assert.equal(playback.frames.length,4);
  playback.next();playback.next();
  assert.deepEqual(playback.clear(),{item:'item1',playedMs:40,dropped:2});
  assert.equal(playback.playing,false);
});

test('commands are validated',()=>{
  assert.throws(()=>decodeCommand('{"type":"eval"}'));
  assert.throws(()=>decodeCommand('{"type":"start","guild_id":"x"}'));
  assert.equal(decodeCommand('{"type":"say","text":"hi"}').type,'say');
});

function fakes(){
  const sent=[],events=[];
  class FakeSocket{constructor(url,protocols){this.url=url;this.protocols=protocols;this.readyState=1;FakeSocket.last=this;}
    send(data){sent.push(JSON.parse(data));} close(){}}
  const connection=new EventEmitter();
  Object.assign(connection,{receiver:{speaking:new EventEmitter(),subscribe:()=>new EventEmitter()},
    prepareAudioPacket(){},dispatchAudio(){},setSpeaking(){},destroy(){},rejoin(){return true;}});
  const voice={joinVoiceChannel:()=>connection,entersState:()=>new Promise(()=>{}),VoiceConnectionStatus:{Ready:'ready'},
    EndBehaviorType:{AfterSilence:1}};
  let dispatch;
  const gatewayFactory=options=>{dispatch=options.onDispatch;return {userId:'9',raw(){},close(){}};};
  // A manual clock: advance(ms) moves time and runs the timers that are due.
  const clock={at:0,timers:new Map(),id:0};
  const setTimer=(fn,ms)=>{const id=++clock.id;clock.timers.set(id,{fn,at:clock.at+ms});return id;};
  const advance=ms=>{
    clock.at+=ms;
    for(const [id,timer] of [...clock.timers].sort((a,b)=>a[1].at-b[1].at))
      if(timer.at<=clock.at&&clock.timers.delete(id))timer.fn();
  };
  const host=createHost({emit:m=>events.push(m),voice,makeDecoder:()=>({decode:()=>Buffer.alloc(0)}),
    makeEncoder:()=>({encode:f=>f.subarray(0,3),delete(){}}),WebSocketImpl:FakeSocket,gatewayFactory,
    now:()=>clock.at,setTimer,clearTimer:id=>clock.timers.delete(id)});
  host.start({guild_id:'1',channel_id:'2',token:'t',client_secret:'ek_1',model:'gpt-realtime'});
  return {host,sent,events,advance,socket:FakeSocket.last,dispatch:(...a)=>dispatch(...a)};
}

const speech=()=>Int16Array.from({length:240},(_,i)=>i%2?2000:-2000);

function speaking(host){
  host._onRealtime({type:'response.created',response:{id:'r1'}});
  host._onRealtime({type:'response.output_audio.delta',response_id:'r1',item_id:'i1',delta:int16ToBase64(new Int16Array(480*30))});
  host._playback.next();host._playback.next();
}

test('the realtime key goes in the WebSocket subprotocol, never in the URL',()=>{
  const {socket}=fakes();
  assert.ok(!socket.url.includes('ek_1'));
  assert.deepEqual(socket.protocols,['realtime','openai-insecure-api-key.ek_1']);
});

test('someone who keeps talking stops Mira and the unheard audio is truncated',()=>{
  const {host,sent,advance}=fakes();
  speaking(host);
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'u1'});
  assert.equal(host._playback.playing,true);
  advance(300);host._heard(speech());advance(BARGE_IN_MS-300);
  assert.equal(host._playback.playing,false);
  assert.ok(sent.some(e=>e.type==='response.cancel'));
  assert.deepEqual(sent.at(-1),{type:'conversation.item.truncate',item_id:'i1',content_index:0,audio_end_ms:40});
  // Late audio from the interrupted answer is ignored.
  host._onRealtime({type:'response.output_audio.delta',response_id:'r1',item_id:'i1',delta:int16ToBase64(new Int16Array(4800))});
  assert.equal(host._playback.playing,false);
});

test('a short "aha" while Mira speaks does not cut her off',()=>{
  const {host,sent,advance}=fakes();
  speaking(host);
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'u1'});
  host._heard(speech());advance(BARGE_IN_MS);
  assert.equal(host._playback.playing,true);
  assert.ok(!sent.some(e=>e.type==='response.cancel'||e.type==='conversation.item.truncate'));
});

test('a system instruction waits until the speaker stops, and Realtime answers them first',()=>{
  const {host,sent,advance}=fakes();
  host.say('SISTEMI: Faza GA');
  host._onRealtime({type:'response.created',response:{id:'r1'}});
  host._onRealtime({type:'response.done',response:{id:'r1'}});
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'u1'});
  host.say('SISTEMI: RADHA EF');
  advance(3000);
  assert.ok(!sent.some(e=>e.item?.content?.[0]?.text==='SISTEMI: RADHA EF'));
  host._onRealtime({type:'input_audio_buffer.speech_stopped',item_id:'u1'});
  host._onRealtime({type:'response.created',response:{id:'r2'}});
  advance(2000);
  assert.ok(!sent.some(e=>e.item?.content?.[0]?.text==='SISTEMI: RADHA EF'));
  host._onRealtime({type:'response.done',response:{id:'r2'}});
  assert.equal(sent.at(-2).item.content[0].text,'SISTEMI: RADHA EF');
  assert.equal(sent.at(-1).type,'response.create');
});

test('a system instruction does not wait forever for someone who never stops',()=>{
  const {host,sent,advance}=fakes();
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'u1'});
  host.say('SISTEMI: Koha ka kaluar');
  advance(SAY_WAIT_MS-1);
  assert.ok(!sent.some(e=>e.type==='response.create'));
  advance(1);
  assert.equal(sent.at(-1).type,'response.create');
});

test('wait_for_user keeps Mira quiet and never reaches PrimeFlow',()=>{
  const {host,sent,events}=fakes();
  host._onRealtime({type:'response.created',response:{id:'r1'}});
  host._onRealtime({type:'response.output_item.done',item:{type:'function_call',call_id:'w1',name:'wait_for_user',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'r1'}});
  assert.ok(!events.some(e=>e.type==='tool_call'));
  assert.equal(sent.at(-1).item.type,'function_call_output');
  assert.ok(!sent.some(e=>e.type==='response.create'));
});

test('a response refused while Realtime is busy is asked for again when it finishes',()=>{
  const {host,sent}=fakes();
  host.say('SISTEMI: Faza GA');
  host._onRealtime({type:'error',error:{code:'conversation_already_has_active_response'}});
  const before=sent.filter(e=>e.type==='response.create').length;
  host._onRealtime({type:'response.done',response:{id:'auto'}});
  assert.equal(sent.filter(e=>e.type==='response.create').length,before+1);
});

test('tool calls go to PrimeFlow and the answer continues only when all results are back',()=>{
  const {host,sent,events}=fakes();
  host._onRealtime({type:'response.created',response:{id:'r1'}});
  host._onRealtime({type:'response.output_item.done',item:{type:'function_call',call_id:'c1',name:'list_new_px_notes',arguments:'{}'}});
  host._onRealtime({type:'response.output_item.done',item:{type:'function_call',call_id:'c2',name:'find_user',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'r1'}});
  assert.deepEqual(events.filter(e=>e.type==='tool_call').map(e=>e.call_id),['c1','c2']);
  host.toolResult('c1',{notes:[]});
  assert.ok(!sent.some(e=>e.type==='response.create'));
  host.toolResult('c2',{name:'Elsa'});
  assert.equal(sent.at(-1).type,'response.create');
  assert.equal(sent.filter(e=>e.type==='conversation.item.create').length,2);
});

test('system messages wait for the current answer to finish',()=>{
  const {host,sent}=fakes();
  host._onRealtime({type:'response.created',response:{id:'r1'}});
  host.say('SISTEMI: RADHA EF');
  assert.ok(!sent.some(e=>e.type==='conversation.item.create'));
  host._onRealtime({type:'response.done',response:{id:'r1'}});
  assert.equal(sent.at(-2).item.content[0].text,'SISTEMI: RADHA EF');
  assert.equal(sent.at(-1).type,'response.create');
});

test('transcripts carry the loudest speaker of the utterance',()=>{
  const {host,events}=fakes();
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'u1'});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',item_id:'u1'});
  host._onRealtime({type:'conversation.item.input_audio_transcription.completed',item_id:'u1',transcript:' Po, e kreva. '});
  assert.deepEqual(events.at(-1),{type:'transcript',role:'staff',speaker_id:null,text:'Po, e kreva.'});
});

test('Mira stays deaf while she waits in the channel and starts listening with her first instruction',()=>{
  const {host}=fakes();
  assert.equal(host._listening,false);
  host.say('SISTEMI: Faza GA');
  assert.equal(host._listening,true);
});
