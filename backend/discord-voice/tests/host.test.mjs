import test from 'node:test';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {FRAME_BYTES,Mixer,SpeakerTimeline,Playback,createOpusEncoder,toDiscord,toRealtime,int16FromBase64,int16ToBase64} from '../host-audio.mjs';
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

function fakes({realtimeReady=true,voiceReady=false,toolsets={}}={}){
  const sent=[],events=[];
  const streams=new Map();
  class FakeSocket{constructor(url,protocols){this.url=url;this.protocols=protocols;this.readyState=1;FakeSocket.last=this;}
    send(data){sent.push(JSON.parse(data));} close(){}}
  const connection=new EventEmitter();
  Object.assign(connection,{receiver:{speaking:new EventEmitter(),subscribe:id=>{const stream=new EventEmitter();streams.set(id,stream);return stream;}},
    prepareAudioPacket(){},dispatchAudio(){},setSpeaking(){},destroy(){},rejoin(){return true;}});
  const voice={joinVoiceChannel:()=>connection,entersState:()=>voiceReady?Promise.resolve():new Promise(()=>{}),VoiceConnectionStatus:{Ready:'ready'},
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
  const host=createHost({emit:m=>events.push(m),voice,makeDecoder:()=>({decode:packet=>packet}),
    makeEncoder:()=>({encode:f=>f.subarray(0,3),delete(){}}),WebSocketImpl:FakeSocket,gatewayFactory,
    now:()=>clock.at,setTimer,clearTimer:id=>clock.timers.delete(id)});
  host.start({guild_id:'1',channel_id:'2',token:'t',client_secret:'ek_1',model:'gpt-realtime',toolsets});
  if(realtimeReady)host._onRealtime({type:'session.created'});
  return {host,sent,events,advance,connection,streams,socket:FakeSocket.last,dispatch:(...a)=>dispatch(...a)};
}

const speech=()=>Int16Array.from({length:240},(_,i)=>i%2?2000:-2000);

test('phase-specific tools wait for Realtime readiness and change at handoff',()=>{
  const tools=[{type:'function',name:'record_task_discussion',parameters:{type:'object'}}];
  const {host,sent}=fakes({realtimeReady:false,toolsets:{STAFF_PHASE:tools,ENDING:[]}});
  host.configure('STAFF_PHASE');
  assert.equal(sent.length,0);
  host._onRealtime({type:'session.created'});
  assert.deepEqual(sent.find(e=>e.type==='session.update').session.tools,tools);
  host.configure('ENDING');
  assert.deepEqual(sent.at(-1).session.tools,[]);
});

test('latency is recorded once per staff utterance across tool continuations',()=>{
  const {host,events,advance}=fakes();
  host._onRealtime({type:'input_audio_buffer.speech_started',audio_start_ms:0});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',audio_end_ms:100,item_id:'speech1'});
  for(const responseId of ['answer','continuation']){
    host._onRealtime({type:'response.created',response:{id:responseId}});
    advance(250);
    host._onRealtime({type:'response.output_audio.delta',response_id:responseId,item_id:responseId,delta:int16ToBase64(speech())});
    host._onRealtime({type:'response.done',response:{id:responseId,status:'completed'}});
  }
  const metrics=events.filter(e=>e.type==='metric');
  assert.equal(metrics.length,1);
  assert.equal(metrics[0].duration_ms,250);
  assert.equal(metrics[0].kind,'generated_audio');
});

test('speaker provenance follows uploaded audio time despite delayed VAD events',()=>{
  const timeline=new SpeakerTimeline();
  timeline.add(100,new Map([['11',480000]]));
  timeline.add(100,new Map([['22',480000]]));
  assert.equal(timeline.speaker(0,100),'11');
  assert.equal(timeline.speaker(100,200),'22');
  assert.equal(timeline.speaker(0,200),null);
});

test('quiet background hiss cannot become a trusted voice confirmation',()=>{
  const timeline=new SpeakerTimeline();
  timeline.add(100,new Map([['11',240000]]));
  assert.equal(timeline.speaker(0,100),null);
  timeline.add(100,new Map([['11',480000]]));
  assert.equal(timeline.speaker(100,200),'11');
});

test('slow responses remain in latency metrics even after voice authorization expires',()=>{
  const {host,events,advance}=fakes();
  host._onRealtime({type:'input_audio_buffer.speech_stopped',audio_end_ms:100,item_id:'slow-speech'});
  advance(16000);
  host._onRealtime({type:'response.created',response:{id:'slow-answer'}});
  advance(250);
  host._onRealtime({type:'response.output_audio.delta',response_id:'slow-answer',item_id:'slow-item',delta:int16ToBase64(speech())});
  assert.equal(events.find(e=>e.type==='metric').duration_ms,16250);
});

test('confirmation tool waits for the exact attributed utterance transcript',async()=>{
  const {host,events,dispatch,advance,connection,streams}=fakes({voiceReady:true});
  dispatch('GUILD_CREATE',{id:'1'});await Promise.resolve();
  host.say('SISTEMI: Faza GA');
  host._onRealtime({type:'response.done',response:{id:'opening',status:'completed'}});
  connection.receiver.speaking.emit('start','11');
  streams.get('11').emit('data',toDiscord(new Int16Array(2400).fill(2000)).pcm);
  advance(100);
  host._onRealtime({type:'input_audio_buffer.speech_started',audio_start_ms:0,item_id:'yes'});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',audio_end_ms:100,item_id:'yes'});
  host._onRealtime({type:'response.created',response:{id:'r-confirm'}});
  host._onRealtime({type:'response.output_item.done',response_id:'r-confirm',item:{type:'function_call',name:'create_task_from_note',call_id:'confirm',arguments:'{}'}});
  assert.equal(events.filter(e=>e.type==='tool_call').length,0);
  host._onRealtime({type:'conversation.item.input_audio_transcription.completed',item_id:'yes',transcript:'Po, krijoje.'});
  const tool=events.find(e=>e.type==='tool_call');
  assert.equal(tool.speaker_id,'11');assert.equal(tool.speech_id,'yes');assert.equal(tool.speech_text,'Po, krijoje.');
  assert.ok(tool.speech_started_at);
  host.stop();
});

test('a slow Realtime handshake retains the opening instruction',()=>{
  const {host,sent,socket}=fakes({realtimeReady:false});
  socket.readyState=0;
  host.say('SISTEMI: fillo takimin');
  assert.equal(sent.length,0);
  socket.readyState=1;
  host._onRealtime({type:'session.created'});
  assert.equal(sent.filter(m=>m.type==='conversation.item.create').length,1);
  assert.equal(sent.filter(m=>m.type==='response.create').length,1);
});

test('mixed voices cannot be attributed as a trusted confirmation',()=>{
  const mixer=new Mixer(),timeline=new SpeakerTimeline();
  mixer.push('11',new Int16Array(240).fill(2000));
  mixer.push('22',new Int16Array(240).fill(1900));
  mixer.pull(240);timeline.add(10,mixer.lastEnergy);
  assert.equal(timeline.speaker(0,10),null);
  mixer.push('11',new Int16Array(240).fill(2000));
  mixer.pull(240);timeline.add(10,mixer.lastEnergy);
  assert.equal(timeline.speaker(10,20),'11');
});

for(const status of ['completed','cancelled','wrong_text','dispatch_failed'])test(`progress is acknowledged only after ${status} audio drains`,async()=>{
  const {host,events,dispatch,advance,connection}=fakes({voiceReady:true});
  dispatch('GUILD_CREATE',{id:'1'});
  await Promise.resolve();
  host._onRealtime({type:'response.created',response:{id:'lookup'}});
  host._onRealtime({type:'response.output_item.done',response_id:'lookup',item:{type:'function_call',name:'list_new_done_and_strikes',call_id:'progress',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'lookup',status:'completed'}});
  host.toolResult('progress',{progress_token:'batch-1',read_aloud:'EF: e kreu ofertën.',sipas_personave:[{person:'EF',done:['Oferta']} ]});
  host._onRealtime({type:'response.created',response:{id:'spoken'}});
  host._onRealtime({type:'response.output_audio.delta',response_id:'spoken',item_id:'audio',delta:int16ToBase64(new Int16Array(480))});
  host._onRealtime({type:'response.output_audio_transcript.done',response_id:'spoken',transcript:status==='wrong_text'?'Fillojmë me stafin.':'EF: e kreu ofertën.'});
  host._onRealtime({type:'response.done',response:{id:'spoken',status:status==='cancelled'?'cancelled':'completed'}});
  assert.equal(events.filter(e=>e.type==='progress_played').length,0);
  if(status==='dispatch_failed')connection.dispatchAudio=()=>false;
  advance(40);
  assert.equal(events.filter(e=>e.type==='progress_played').length,status==='completed'?1:0);
  advance(40);
  assert.equal(events.filter(e=>e.type==='progress_played').length,status==='completed'?1:0);
  host.stop();
});

test('ready requires both the Discord voice and Realtime handshakes',async()=>{
  const {host,events,dispatch}=fakes({realtimeReady:false,voiceReady:true});
  dispatch('GUILD_CREATE',{id:'1'});
  await Promise.resolve();
  assert.equal(events.some(e=>e.type==='ready'),false);
  host._onRealtime({type:'session.created'});
  assert.equal(events.filter(e=>e.type==='ready').length,1);
  host.stop();
});

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

test('a fast tool result resumes exactly once after its originating response ends',()=>{
  const {host,sent}=fakes();
  host._onRealtime({type:'response.created',response:{id:'r1'}});
  host._onRealtime({type:'response.output_item.done',item:{type:'function_call',call_id:'c1',name:'end_person_turn',arguments:'{}'}});
  host.toolResult('c1',{RADHA:{person:'Elsa'}});
  assert.equal(sent.filter(e=>e.type==='response.create').length,0);
  host._onRealtime({type:'response.done',response:{id:'r1'}});
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
  host.toolResult('c1',{RADHA:{person:'Elsa'}});
  host._onRealtime({type:'response.created',response:{id:'r2'}});
  host._onRealtime({type:'response.done',response:{id:'r2'}});
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
});

test('mixed result arrival waits for every tool and continues once',()=>{
  const {host,sent}=fakes();
  host._onRealtime({type:'response.created',response:{id:'r1'}});
  for(const call_id of ['c1','c2'])
    host._onRealtime({type:'response.output_item.done',item:{type:'function_call',call_id,name:'list_ga_tasks',arguments:'{}'}});
  host.toolResult('c1',{});
  host._onRealtime({type:'response.done',response:{id:'r1'}});
  assert.equal(sent.filter(e=>e.type==='response.create').length,0);
  host.toolResult('c2',{});
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
  host.toolResult('c2',{});
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
});

test('a queued handoff and a tool result share one response without a second answer',()=>{
  const {host,sent}=fakes();
  host._onRealtime({type:'response.created',response:{id:'r1'}});
  host._onRealtime({type:'response.output_item.done',item:{type:'function_call',call_id:'c1',name:'list_ga_tasks',arguments:'{}'}});
  host.say('SISTEMI: RADHA EF');
  host._onRealtime({type:'response.done',response:{id:'r1'}});
  host.toolResult('c1',{});
  assert.equal(sent.filter(e=>e.item?.content?.[0]?.text==='SISTEMI: RADHA EF').length,1);
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
  host._onRealtime({type:'response.created',response:{id:'r2'}});
  host._onRealtime({type:'response.done',response:{id:'r2'}});
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
});

test('a fast real tool still resumes when a silence tool is in the same response',()=>{
  const {host,sent,events}=fakes();
  host._onRealtime({type:'response.created',response:{id:'r1'}});
  host._onRealtime({type:'response.output_item.done',item:{type:'function_call',call_id:'c1',name:'save_px_note',arguments:'{}'}});
  host._onRealtime({type:'response.output_item.done',item:{type:'function_call',call_id:'w1',name:'wait_for_user',arguments:'{}'}});
  host.toolResult('c1',{success:true});
  host._onRealtime({type:'response.done',response:{id:'r1'}});
  assert.deepEqual(events.filter(e=>e.type==='tool_call').map(e=>e.call_id),['c1']);
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
});

test('tool continuation waits for a speaking person before responding',()=>{
  const {host,sent,advance}=fakes();
  host._onRealtime({type:'response.created',response:{id:'r1'}});
  host._onRealtime({type:'response.output_item.done',item:{type:'function_call',call_id:'c1',name:'list_ga_tasks',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'r1'}});
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'u1'});
  host.toolResult('c1',{});
  assert.equal(sent.filter(e=>e.type==='response.create').length,0);
  host._onRealtime({type:'input_audio_buffer.speech_stopped',item_id:'u1'});
  advance(1200);
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
});

for(const silent of [false,true])
  test(`an automatic ${silent?'silent':'spoken'} reply consumes tool results without a duplicate answer`,()=>{
    const {host,sent,advance}=fakes();
    host._onRealtime({type:'response.created',response:{id:'r1'}});
    host._onRealtime({type:'response.output_item.done',item:{type:'function_call',call_id:'c1',name:'save_px_note',arguments:'{}'}});
    host._onRealtime({type:'response.done',response:{id:'r1'}});
    host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'u1'});
    host.toolResult('c1',{success:true});
    host._onRealtime({type:'input_audio_buffer.speech_stopped',item_id:'u1'});
    // Realtime's create_response=true responds to the speaker with the result already in context.
    host._onRealtime({type:'response.created',response:{id:'auto'}});
    if(silent)host._onRealtime({type:'response.output_item.done',item:{type:'function_call',call_id:'w1',name:'wait_for_user',arguments:'{}'}});
    host._onRealtime({type:'response.done',response:{id:'auto'}});
    advance(1200);
    assert.equal(sent.filter(e=>e.type==='response.create').length,0);
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
