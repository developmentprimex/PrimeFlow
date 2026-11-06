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
  assert.deepEqual(playback.clear(),{item:'item1',playedMs:40,dropped:2,items:[{item:'item1',playedMs:40}]});
  assert.equal(playback.playing,false);
});

test('commands are validated',()=>{
  assert.throws(()=>decodeCommand('{"type":"eval"}'));
  assert.throws(()=>decodeCommand('{"type":"start","guild_id":"x"}'));
  assert.equal(decodeCommand('{"type":"say","text":"hi"}').type,'say');
});

function fakes({realtimeReady=true,voiceReady=false,toolsets={},instructions_by_phase={},makeDecoder=()=>({decode:packet=>packet})}={}){
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
  const host=createHost({emit:m=>events.push(m),voice,makeDecoder,
    makeEncoder:()=>({encode:f=>f.subarray(0,3),delete(){}}),WebSocketImpl:FakeSocket,gatewayFactory,
    now:()=>clock.at,setTimer,clearTimer:id=>clock.timers.delete(id)});
  host.start({guild_id:'1',channel_id:'2',token:'t',client_secret:'ek_1',model:'gpt-realtime',toolsets,instructions_by_phase});
  if(realtimeReady)host._onRealtime({type:'session.created'});
  return {host,sent,events,advance,connection,streams,socket:FakeSocket.last,dispatch:(...a)=>dispatch(...a)};
}

const speech=()=>Int16Array.from({length:240},(_,i)=>i%2?2000:-2000);

function finishOpening(host){
  host._onRealtime({type:'response.created',response:{id:'opening-end'}});
  host._onRealtime({type:'response.output_item.done',response_id:'opening-end',item:{type:'function_call',name:'end_ga_phase',call_id:'end-opening',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'opening-end',status:'completed'}});
  host.toolResult('end-opening',{prit:true,silent:true,wait_for_staff:true});
}

test('the controller can hold an empty opening before its lookup result without another voice turn',()=>{
  const {host,sent,advance}=fakes();
  host.say('SISTEMI: Hyrja',{respond:false});
  host._onRealtime({type:'response.created',response:{id:'progress-lookup'}});
  host._onRealtime({type:'response.output_item.done',response_id:'progress-lookup',item:{type:'function_call',name:'list_new_done_and_strikes',call_id:'progress',arguments:'{}'}});
  host.configure('GA_PHASE',null,null,true);
  host.toolResult('progress',{read_aloud:'',announcements:[]});
  host._onRealtime({type:'response.done',response:{id:'progress-lookup',status:'cancelled'}});
  advance(20000);
  assert.equal(sent.filter(e=>e.type==='response.create').length,0);
  host.configure('STAFF_PHASE','11','first');host.say('SISTEMI: RADHA Elsa');
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
  host.stop();
});

test('completed opening waits silently and refuses automatic off-topic responses until staff starts',()=>{
  const {host,sent,events,advance}=fakes();
  host.say('SISTEMI: Hyrja',{respond:false});
  finishOpening(host);
  assert.equal(sent.filter(e=>e.type==='response.create').length,0);
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'side'});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',item_id:'side'});
  host._onRealtime({type:'conversation.item.input_audio_transcription.completed',item_id:'side',transcript:'Çfarë janë dividendët?'});
  host._onRealtime({type:'response.created',response:{id:'off-topic'}});
  host._onRealtime({type:'response.output_audio.delta',response_id:'off-topic',item_id:'stray',delta:int16ToBase64(new Int16Array(480))});
  host._onRealtime({type:'response.output_item.done',response_id:'off-topic',item:{type:'function_call',name:'search_knowledge',call_id:'stray-tool',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'off-topic',status:'completed'}});
  advance(10000);advance(10000);
  assert.equal(host._playback.playing,false);
  assert.ok(sent.some(e=>e.type==='response.cancel'&&e.response_id==='off-topic'));
  assert.equal(sent.filter(e=>e.type==='response.create').length,0);
  assert.equal(events.filter(e=>e.type==='tool_call'&&e.call_id==='stray-tool').length,0);
  assert.equal(events.filter(e=>e.type==='interrupted').length,0);
  host.configure('STAFF_PHASE','11','first');
  host.say('SISTEMI: RADHA Elsa');
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
  host.stop();
});

test('a late opening wait cannot silence the staff phase or replace its current turn',()=>{
  const {host,sent}=fakes();
  host._onRealtime({type:'response.created',response:{id:'opening-end'}});
  host._onRealtime({type:'response.output_item.done',response_id:'opening-end',item:{type:'function_call',name:'end_ga_phase',call_id:'end-opening',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'opening-end',status:'completed'}});
  host.configure('STAFF_PHASE','11','first');
  host.toolResult('end-opening',{prit:true,silent:true,wait_for_staff:true});
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
  const output=sent.filter(e=>e.type==='conversation.item.create'&&e.item.call_id==='end-opening').at(-1).item.output;
  assert.equal(JSON.parse(output).wait_for_staff,undefined);
  host.stop();
});

test('a fast opening completion drops queued waiting narration and cannot trigger recovery speech',()=>{
  const {host,sent,events,advance}=fakes();
  host.say('SISTEMI: Hyrja',{respond:false});
  host._onRealtime({type:'response.created',response:{id:'opening-end'}});
  host._onRealtime({type:'response.output_item.done',response_id:'opening-end',item:{type:'function_call',name:'end_ga_phase',call_id:'end-opening',arguments:'{}'}});
  host._onRealtime({type:'response.output_audio.delta',response_id:'opening-end',item_id:'waiting-audio',delta:int16ToBase64(new Int16Array(480))});
  assert.equal(host._playback.playing,true);
  host.toolResult('end-opening',{prit:true,silent:true,wait_for_staff:true});
  assert.equal(host._playback.playing,false);
  host._onRealtime({type:'response.done',response:{id:'opening-end',status:'cancelled'}});
  advance(20000);advance(20000);
  assert.equal(sent.filter(e=>e.type==='response.create').length,0);
  assert.equal(events.filter(e=>e.type==='interrupted').length,0);
  host.configure('ENDING');host.say('SISTEMI: Takimi u ndal');
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
  host.stop();
});

test('empty categories are read and acknowledged even without notes or person rows',async()=>{
  const {host,sent,events,dispatch,advance}=fakes({voiceReady:true});
  dispatch('GUILD_CREATE',{id:'1'});
  await Promise.resolve();
  const lookup=(id,name,output)=>{
    host._onRealtime({type:'response.created',response:{id}});
    host._onRealtime({type:'response.output_item.done',response_id:id,item:{type:'function_call',name,call_id:id,arguments:'{}'}});
    host._onRealtime({type:'response.done',response:{id,status:'completed'}});
    host.toolResult(id,output);
  };
  const play=(id,text)=>{
    host._onRealtime({type:'response.created',response:{id}});
    host._onRealtime({type:'response.output_audio.delta',response_id:id,item_id:id+'-audio',delta:int16ToBase64(new Int16Array(480))});
    host._onRealtime({type:'response.output_audio_transcript.done',response_id:id,transcript:text});
    host._onRealtime({type:'response.done',response:{id,status:'completed'}});
    advance(40);
  };
  const notes='Notes të reja nuk ka.';
  lookup('notes','list_new_px_notes',{notes:[],notes_token:'empty-notes',read_aloud:notes,next_step:'list_new_done_and_strikes'});
  assert.ok(sent.filter(e=>e.type==='response.create').at(-1).response.instructions?.includes(notes));
  assert.equal(events.filter(e=>e.type==='note_played').length,0);
  play('notes-audio',notes);
  assert.ok(events.some(e=>e.type==='note_played'&&e.token==='empty-notes'));
  // Complete the following model turn with the progress lookup.
  lookup('progress','list_new_done_and_strikes',{sipas_personave:[],announcements:[
    {token:'empty-done',read_aloud:'Done të reja nuk ka.'},
    {token:'empty-strikes',read_aloud:'Strikes të reja nuk ka.'},
  ]});
  const progress='Done të reja nuk ka. Strikes të reja nuk ka.';
  assert.ok(sent.filter(e=>e.type==='response.create').at(-1).response.instructions?.includes(progress));
  assert.equal(events.filter(e=>e.type==='progress_played').length,0);
  play('progress-audio',progress);
  assert.deepEqual(events.filter(e=>e.type==='progress_played').map(e=>e.token),['empty-done','empty-strikes']);
  host.configure('GA_PHASE',null,null,true);
  const replies=sent.filter(e=>e.type==='response.create').length;
  advance(20000);
  assert.equal(sent.filter(e=>e.type==='response.create').length,replies);
  host.stop();
});

test('existing Notes are read immediately without another tool or permission pause',()=>{
  const {host,sent}=fakes();
  host._onRealtime({type:'response.created',response:{id:'notes'}});
  host._onRealtime({type:'response.output_item.done',response_id:'notes',item:{type:'function_call',name:'list_new_px_notes',call_id:'notes-read',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'notes',status:'completed'}});
  const reading='Shënimi 1: fë gë, kontrollo ofertën. Shënimi 2: Dërgo raportin.';
  host.toolResult('notes-read',{notes:[{note_id:'n1'},{note_id:'n2'}],read_aloud:reading,next_step:'list_new_done_and_strikes'});
  const request=sent.filter(e=>e.type==='response.create').at(-1);
  assert.ok(request?.response.instructions?.includes(reading));
  assert.equal(request.response.tool_choice,'none');
  host.stop();
});

for(const status of ['completed','cancelled','wrong_text','dispatch_failed'])test(`notes ${status} playback continues or retries without silence`,async()=>{
  const {host,sent,events,dispatch,advance,connection}=fakes({voiceReady:true});
  dispatch('GUILD_CREATE',{id:'1'});
  await Promise.resolve();
  host._onRealtime({type:'response.created',response:{id:'lookup'}});
  host._onRealtime({type:'response.output_item.done',response_id:'lookup',item:{type:'function_call',name:'list_new_px_notes',call_id:'notes',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'lookup',status:'completed'}});
  const reading='Shënimi 1: Oferta. Shënimi 2: Raporti.';
  host.toolResult('notes',{notes:[{note_id:'n1'},{note_id:'n2'}],read_aloud:reading,next_step:'list_new_done_and_strikes'});
  const before=sent.filter(e=>e.type==='response.create').length;
  host._onRealtime({type:'response.created',response:{id:'spoken'}});
  host._onRealtime({type:'response.output_audio.delta',response_id:'spoken',item_id:'audio',delta:int16ToBase64(new Int16Array(480))});
  host._onRealtime({type:'response.output_audio_transcript.done',response_id:'spoken',transcript:status==='wrong_text'?'Fillojmë.':reading});
  host._onRealtime({type:'response.done',response:{id:'spoken',status:status==='cancelled'?'cancelled':'completed'}});
  assert.equal(sent.filter(e=>e.type==='response.create').length,before);
  if(status==='dispatch_failed')connection.dispatchAudio=()=>false;
  advance(40);
  assert.equal(sent.filter(e=>e.type==='response.create').length,before+1);
  assert.equal(sent.filter(e=>e.type==='response.create').at(-1).response.tool_choice,status==='completed'?undefined:'none');
  assert.equal(events.filter(e=>e.type==='note_played').length,status==='completed'?1:0);
  if(status==='completed'){
    advance(1000);
    assert.equal(sent.filter(e=>e.type==='response.create').length,before+1);
  }
  host.stop();
});

test('speech ending during an older response gets a reply when automatic VAD misses it',()=>{
  const {host,sent,advance}=fakes();
  host.say('SISTEMI: RADHA EF',{respond:false});
  host._onRealtime({type:'response.created',response:{id:'old'}});
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'answer'});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',item_id:'answer'});
  host._onRealtime({type:'response.done',response:{id:'old',status:'completed'}});
  advance(1000);
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
});

test('a rejected response request cannot leave the host permanently busy',()=>{
  const {host,sent,advance}=fakes();
  host.say('SISTEMI: RADHA EF');
  const request=sent.find(e=>e.type==='response.create');
  host._onRealtime({type:'error',error:{code:'server_error',event_id:request.event_id}});
  advance(1000);
  assert.equal(sent.filter(e=>e.type==='response.create').length,2);
});

test('a response which never starts is recovered before the person budget expires',()=>{
  const {host,sent,advance}=fakes();
  host.say('SISTEMI: RADHA EF');
  advance(8500);advance(1000);
  assert.equal(sent.filter(e=>e.type==='response.create').length,2);
  assert.ok(sent.some(e=>e.type==='response.cancel'));
});

test('late completion of a cancelled response cannot clear a newer active response',()=>{
  const {host,sent,advance}=fakes();
  host.say('SISTEMI: RADHA EF');
  host._onRealtime({type:'response.created',response:{id:'old'}});
  advance(8500);advance(1000);
  host._onRealtime({type:'response.created',response:{id:'new'}});
  const before=sent.filter(e=>e.type==='response.create').length;
  host.say('SISTEMI: follow-up');
  host._onRealtime({type:'response.done',response:{id:'old',status:'cancelled'}});
  assert.equal(sent.filter(e=>e.type==='response.create').length,before);
});

test('failed responses retry with a bound instead of staying silent or looping forever',()=>{
  const {host,sent,events,advance}=fakes();
  host.say('SISTEMI: RADHA EF');
  for(let i=0;i<4;i++){
    host._onRealtime({type:'response.created',response:{id:'failed-'+i}});
    host._onRealtime({type:'response.done',response:{id:'failed-'+i,status:'failed'}});
    advance(1000);
  }
  assert.ok(sent.filter(e=>e.type==='response.create').length<=3);
  assert.ok(events.some(e=>e.type==='interrupted'&&e.reason==='response_stalled'));
});

for(const phase of ['GA_PHASE','STAFF_PHASE','PM_REVIEW','ENDING'])
test(`response recovery preserves the active phase policy and concise transitions: ${phase}`,()=>{
  const policy=`Current ${phase} policy with slot-specific questions and tools`;
  const {host,sent,advance}=fakes({toolsets:{[phase]:[]},instructions_by_phase:{[phase]:policy}});
  host.configure(phase,'11','turn');
  host.say('SISTEMI: Vazhdo');
  host._onRealtime({type:'response.created',response:{id:'failed'}});
  host._onRealtime({type:'response.done',response:{id:'failed',status:'failed'}});
  advance(1000);
  const instructions=sent.filter(e=>e.type==='response.create').at(-1).response.instructions;
  assert.ok(instructions.includes(policy),'recovery must retain the slot question and phase rules');
  assert.ok(instructions.includes('po e mbaj shkurt'),'recovery must explicitly ban process commentary');
  assert.ok(instructions.includes('po vazhdoj'));
  host.stop();
});

test('watchdog never retries while speech, playback or an unresolved tool is active',()=>{
  const {host,sent,advance}=fakes();
  host.say('SISTEMI: RADHA EF');
  host._onRealtime({type:'response.created',response:{id:'working'}});
  host._onRealtime({type:'response.output_item.done',item:{type:'function_call',call_id:'c1',name:'save_px_note',arguments:'{}'}});
  advance(8500);advance(1000);
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
  assert.ok(!sent.some(e=>e.type==='response.cancel'));
});

test('explicit user pause preserves silence even when a tool continuation is owed',()=>{
  const {host,sent,advance}=fakes();
  host.say('SISTEMI: RADHA EF',{respond:false});
  host._onRealtime({type:'response.created',response:{id:'save'}});
  host._onRealtime({type:'response.output_item.done',item:{type:'function_call',call_id:'save',name:'save_px_note',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'save'}});
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'pause'});
  host.toolResult('save',{success:true});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',item_id:'pause'});
  host._onRealtime({type:'response.created',response:{id:'pause'}});
  host._onRealtime({type:'response.output_item.done',item:{type:'function_call',call_id:'wait',name:'wait_for_user',arguments:'{"reason":"user_pause"}'}});
  host._onRealtime({type:'response.done',response:{id:'pause',status:'completed'}});
  advance(10000);
  assert.equal(sent.filter(e=>e.type==='response.create').length,0);
});

test('a delayed response from an older request cannot execute tools or overwrite a retry',()=>{
  const {host,sent,events,advance}=fakes();
  host.say('SISTEMI: RADHA EF');
  const original=sent.find(e=>e.type==='response.create').event_id;
  advance(8500);advance(1000);
  const retry=sent.filter(e=>e.type==='response.create').at(-1).event_id;
  host._onRealtime({type:'response.created',response:{id:'late',metadata:{mira_request:original}}});
  host._onRealtime({type:'response.created',response:{id:'retry',metadata:{mira_request:retry}}});
  host._onRealtime({type:'response.output_item.done',response_id:'late',item:{type:'function_call',call_id:'unsafe',name:'save_px_note',arguments:'{}'}});
  host.say('SISTEMI: next');
  host._onRealtime({type:'response.done',response:{id:'late',status:'cancelled'}});
  assert.equal(events.filter(e=>e.type==='tool_call').length,0);
  assert.equal(sent.filter(e=>e.type==='response.create').length,2);
});

test('an empty response to a manual request is retried with a bound',()=>{
  const {host,sent,advance}=fakes();
  host.say('SISTEMI: RADHA EF');
  const request=sent.find(e=>e.type==='response.create');
  host._onRealtime({type:'response.created',response:{id:'empty',metadata:request.response.metadata}});
  host._onRealtime({type:'response.done',response:{id:'empty',status:'completed'}});
  advance(1000);
  assert.equal(sent.filter(e=>e.type==='response.create').length,2);
});

for(const answer of ['Duhet me prit furnitorin; e mbyll deri në njëmbëdhjetë.','Sot.','Nesër.','Po.','Jo.','Aha.'])
test(`an attributed answer is recovered if silently ignored, including short confirmations but excluding filler: ${answer}`,async()=>{
  const {host,events,sent,dispatch,advance,connection,streams}=fakes({voiceReady:true});
  dispatch('GUILD_CREATE',{id:'1'});await Promise.resolve();
  host.configure('STAFF_PHASE','11');
  host.say('SISTEMI: RADHA EF',{respond:false});
  connection.receiver.speaking.emit('start','11');
  streams.get('11').emit('data',toDiscord(new Int16Array(2400).fill(2000)).pcm);
  advance(100);
  host._onRealtime({type:'input_audio_buffer.speech_started',audio_start_ms:0,item_id:'answer'});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',audio_end_ms:100,item_id:'answer'});
  host._onRealtime({type:'response.created',response:{id:'ignored'}});
  host._onRealtime({type:'response.output_item.done',item:{type:'function_call',call_id:'wait',name:'wait_for_user',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'ignored',status:'completed'}});
  host._onRealtime({type:'conversation.item.input_audio_transcription.completed',item_id:'answer',transcript:answer});
  advance(1000);
  const shouldRecover=answer!=='Aha.';
  assert.equal(sent.filter(e=>e.type==='response.create').length,shouldRecover?1:0);
  assert.equal(events.some(e=>e.event==='response_recovery'&&e.reason==='ignored_staff_answer'),shouldRecover);
  host.stop();
});

test('partial audio from repeatedly failed responses does not reset the recovery limit',()=>{
  const {host,sent,events,advance}=fakes();
  host.say('SISTEMI: RADHA EF');
  for(let i=0;i<3;i++){
    host._onRealtime({type:'response.created',response:{id:'partial-'+i}});
    host._onRealtime({type:'response.output_audio.delta',response_id:'partial-'+i,item_id:'item-'+i,delta:int16ToBase64(speech())});
    host._playback.clear();
    host._onRealtime({type:'response.done',response:{id:'partial-'+i,status:'failed'}});
    advance(1000);
  }
  assert.equal(sent.filter(e=>e.type==='response.create').length,3);
  assert.ok(events.some(e=>e.type==='interrupted'&&e.reason==='response_stalled'));
});

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

test('a real interruption releases the cancelled response so the staff answer is handled promptly',()=>{
  const {host,sent,advance}=fakes();
  host.say('SISTEMI: RADHA EF',{respond:false});
  speaking(host);
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'answer'});
  advance(300);host._heard(speech());advance(BARGE_IN_MS-300);
  host._onRealtime({type:'input_audio_buffer.speech_stopped',item_id:'answer'});
  host._onRealtime({type:'response.done',response:{id:'r1',status:'cancelled'}});
  advance(1000);
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
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
  test(`an automatic ${silent?'silent reply preserves':'spoken reply consumes'} the owed tool continuation`,()=>{
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
    assert.equal(sent.filter(e=>e.type==='response.create').length,silent?1:0);
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
  assert.deepEqual(events.at(-1),{type:'transcript',role:'staff',speaker_id:null,speech_id:'u1',turn_id:null,started_at:null,ended_at:null,text:'Po, e kreva.'});
});

test('Mira stays deaf while she waits in the channel and starts listening with her first instruction',()=>{
  const {host}=fakes();
  assert.equal(host._listening,false);
  host.say('SISTEMI: Faza GA');
  assert.equal(host._listening,true);
});

test('playback truncation retains the actual item for every queued frame',()=>{
  const p=new Playback(frame=>frame.subarray(0,3));
  p.push('a',new Int16Array(960));p.push('b',new Int16Array(960));
  p.next();
  assert.deepEqual(p.clear().items,[{item:'a',playedMs:20},{item:'b',playedMs:0}]);
});

test('speech beginning before first generated audio still interrupts the response',()=>{
  const {host,sent,advance}=fakes();
  host._onRealtime({type:'response.created',response:{id:'thinking'}});
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'answer'});
  advance(300);host._heard(speech());advance(150);
  host._onRealtime({type:'response.output_audio.delta',response_id:'thinking',item_id:'audio',delta:int16ToBase64(new Int16Array(4800))});
  assert.ok(sent.some(e=>e.type==='response.cancel'));
  assert.equal(host._playback.playing,false);
  host.stop();
});

test('short explicit pause stops playback and holds queued continuation until resume',()=>{
  const {host,sent,advance}=fakes();
  host.say('SISTEMI: Fillimi',{respond:false});speaking(host);
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'pause'});
  host._heard(speech());advance(100);
  host._onRealtime({type:'input_audio_buffer.speech_stopped',item_id:'pause'});
  host._onRealtime({type:'conversation.item.input_audio_transcription.completed',item_id:'pause',transcript:'Mira prit'});
  assert.equal(host._playback.playing,false);
  host._onRealtime({type:'response.done',response:{id:'r1',status:'cancelled'}});
  host.say('SISTEMI: Vazhdo kur të jetë gati');advance(2000);
  assert.equal(sent.filter(e=>e.type==='response.create').length,0);
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'resume'});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',item_id:'resume'});
  host._onRealtime({type:'conversation.item.input_audio_transcription.completed',item_id:'resume',transcript:'Vazhdo'});
  advance(1000);
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
  host.stop();
});

test('a model-recognized user pause also holds later system instructions until resume',()=>{
  const {host,sent,advance}=fakes();
  host.say('SISTEMI: RADHA',{respond:false});
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'pause'});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',item_id:'pause'});
  host._onRealtime({type:'conversation.item.input_audio_transcription.completed',item_id:'pause',transcript:'Ma jep një minutë të lutem'});
  host._onRealtime({type:'response.created',response:{id:'pause-reply'}});
  host._onRealtime({type:'response.output_item.done',response_id:'pause-reply',item:{type:'function_call',call_id:'wait',name:'wait_for_user',arguments:'{"reason":"user_pause"}'}});
  host._onRealtime({type:'response.done',response:{id:'pause-reply',status:'completed'}});
  host.say('SISTEMI: Mbeten 15 sekonda');advance(2000);
  assert.equal(sent.filter(e=>e.type==='response.create').length,0);
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'resume'});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',item_id:'resume'});
  host._onRealtime({type:'conversation.item.input_audio_transcription.completed',item_id:'resume',transcript:'Vazhdo'});
  advance(1000);
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
  host.stop();
});

test('note ordinal wording is accepted and continues without retrying the reading',async()=>{
  const {host,sent,events,dispatch,advance}=fakes({voiceReady:true});
  dispatch('GUILD_CREATE',{id:'1'});await Promise.resolve();
  host._onRealtime({type:'response.created',response:{id:'lookup'}});
  host._onRealtime({type:'response.output_item.done',response_id:'lookup',item:{type:'function_call',name:'list_new_px_notes',call_id:'n',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'lookup',status:'completed'}});
  host.toolResult('n',{notes:[{note_id:'one'}],notes_token:'batch',read_aloud:'Shënimi 1: Dërgo raportin.',next_step:'list_new_done_and_strikes'});
  host._onRealtime({type:'response.created',response:{id:'read'}});
  host._onRealtime({type:'response.output_audio.delta',response_id:'read',item_id:'audio',delta:int16ToBase64(new Int16Array(480))});
  host._onRealtime({type:'response.output_audio_transcript.done',response_id:'read',transcript:'Shënimi i parë: Dërgo raportin.'});
  host._onRealtime({type:'response.done',response:{id:'read',status:'completed'}});advance(40);
  assert.equal(events.filter(e=>e.type==='note_played'&&e.token==='batch').length,1);
  assert.equal(sent.filter(e=>e.type==='response.create').at(-1).response.tool_choice,undefined);
  host.stop();
});

for(const [kind,transcript,accepted] of [
  ['note','Notes të reja: Progresi 12.5%.',true],
  ['progress','Elsa: Progresi 12,5%.',true],
  ['progress','Elsa: Progresi 12.6%.',false],
  ['note','Notes të reja: Progresi 12.5.',false],
])test(`percentage delivery accepts equivalent transcription but requires the same value and unit: ${kind} ${transcript}`,async()=>{
  const {host,sent,events,dispatch,advance}=fakes({voiceReady:true});
  dispatch('GUILD_CREATE',{id:'1'});await Promise.resolve();
  const name=kind==='note'?'list_new_px_notes':'list_new_done_and_strikes';
  const text=(kind==='note'?'Notes të reja: ':'Elsa: ')+'Progresi 12 presje 5 për qind.';
  host._onRealtime({type:'response.created',response:{id:'lookup'}});
  host._onRealtime({type:'response.output_item.done',response_id:'lookup',item:{type:'function_call',name,call_id:'lookup',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'lookup',status:'completed'}});
  host.toolResult('lookup',kind==='note'?{notes_token:'batch',read_aloud:text,next_step:'list_new_done_and_strikes'}:
    {announcements:[{token:'batch',read_aloud:text}]});
  const requests=sent.filter(e=>e.type==='response.create').length;
  host._onRealtime({type:'response.created',response:{id:'read'}});
  host._onRealtime({type:'response.output_audio.delta',response_id:'read',item_id:'audio',delta:int16ToBase64(new Int16Array(480))});
  host._onRealtime({type:'response.output_audio_transcript.done',response_id:'read',transcript});
  host._onRealtime({type:'response.done',response:{id:'read',status:'completed'}});advance(40);
  assert.equal(events.filter(e=>e.type===kind+'_played'&&e.token==='batch').length,accepted?1:0);
  assert.equal(sent.filter(e=>e.type==='response.create').length,requests+(kind==='note'||!accepted?1:0));
  if(kind==='note'||!accepted)
    assert.equal(sent.filter(e=>e.type==='response.create').at(-1).response.tool_choice,accepted?undefined:'none');
  host.stop();
});

test('short progress parts share a voice turn and only missing parts retry',async()=>{
  const {host,sent,events,dispatch,advance}=fakes({voiceReady:true});
  dispatch('GUILD_CREATE',{id:'1'});await Promise.resolve();
  host._onRealtime({type:'response.created',response:{id:'lookup'}});
  host._onRealtime({type:'response.output_item.done',response_id:'lookup',item:{type:'function_call',name:'list_new_done_and_strikes',call_id:'p',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'lookup',status:'completed'}});
  host.toolResult('p',{announcements:[{token:'a',read_aloud:'Elsa e kreu ofertën.'},{token:'b',read_aloud:'Rinesa e kreu raportin.'}]});
  assert.ok(sent.at(-1).response.instructions.includes('Elsa'));
  assert.ok(sent.at(-1).response.instructions.includes('Rinesa'));
  function played(id,text){
    host._onRealtime({type:'response.created',response:{id}});
    host._onRealtime({type:'response.output_audio.delta',response_id:id,item_id:id,delta:int16ToBase64(new Int16Array(480))});
    host._onRealtime({type:'response.output_audio_transcript.done',response_id:id,transcript:text});
    host._onRealtime({type:'response.done',response:{id,status:'completed'}});advance(40);
  }
  played('first','Elsa e kreu ofertën.');
  assert.deepEqual(events.filter(e=>e.type==='progress_played').map(e=>e.token),['a']);
  assert.ok(sent.at(-1).response.instructions.includes('Rinesa'));
  played('bad','Fillojmë.');
  assert.equal(events.filter(e=>e.type==='announcement_deferred'&&e.token==='b').length,1);
  assert.equal(events.filter(e=>e.type==='progress_played'&&e.token==='b').length,0);
  assert.equal(sent.at(-1).response.tool_choice,undefined);
  host.stop();
});

test('persistent decode errors recover once then signal health; valid audio clears the failure',async()=>{
  let creates=0,valid=false;
  const {host,events,dispatch,connection,streams,advance}=fakes({voiceReady:true,makeDecoder:()=>{
    creates++;return {decode(packet){if(!valid)throw Error('bad');return packet;},delete(){}};
  }});
  dispatch('GUILD_CREATE',{id:'1'});await Promise.resolve();
  connection.receiver.speaking.emit('start','11');
  for(let i=0;i<200;i++){streams.get('11').emit('data',Buffer.from([1]));advance(20);}
  assert.equal(creates,2);
  assert.equal(events.filter(e=>e.type==='audio_health'&&e.status==='failed').length,1);
  valid=true;streams.get('11').emit('data',toDiscord(new Int16Array(240).fill(2000)).pcm);
  assert.equal(events.filter(e=>e.type==='audio_health'&&e.status==='recovered').length,1);
  host.stop();
});

test('phase instructions update with tools and delayed speech retains its original turn',async()=>{
  const {host,sent,events,dispatch,connection,streams,advance}=fakes({voiceReady:true,
    toolsets:{STAFF_PHASE:[],PM_REVIEW:[]},instructions_by_phase:{STAFF_PHASE:'Stafi',PM_REVIEW:'PM'}});
  dispatch('GUILD_CREATE',{id:'1'});await Promise.resolve();
  host.configure('STAFF_PHASE','11','old-turn');host.say('SISTEMI: RADHA',{respond:false});
  connection.receiver.speaking.emit('start','11');
  streams.get('11').emit('data',toDiscord(new Int16Array(2400).fill(2000)).pcm);advance(100);
  host._onRealtime({type:'input_audio_buffer.speech_started',audio_start_ms:0,item_id:'late'});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',audio_end_ms:100,item_id:'late'});
  host.configure('PM_REVIEW','22','new-turn');
  host._onRealtime({type:'conversation.item.input_audio_transcription.completed',item_id:'late',transcript:'Oferta u dërgua'});
  assert.equal(sent.filter(e=>e.type==='session.update').at(-1).session.instructions,'PM');
  const line=events.find(e=>e.type==='transcript');
  assert.equal(line.turn_id,'old-turn');assert.equal(line.speaker_id,'11');assert.ok(line.started_at);assert.ok(line.ended_at);
  host.stop();
});

test('late VAD start is assigned to the turn active when its audio was uploaded',async()=>{
  const {host,events,dispatch,connection,streams,advance}=fakes({voiceReady:true});
  dispatch('GUILD_CREATE',{id:'1'});await Promise.resolve();
  host.configure('STAFF_PHASE','11','old-turn');host.say('SISTEMI: RADHA',{respond:false});
  connection.receiver.speaking.emit('start','11');
  streams.get('11').emit('data',toDiscord(new Int16Array(2400).fill(2000)).pcm);advance(100);
  host.configure('STAFF_PHASE','22','new-turn');
  host._onRealtime({type:'input_audio_buffer.speech_started',audio_start_ms:0,item_id:'late'});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',audio_end_ms:100,item_id:'late'});
  host._onRealtime({type:'conversation.item.input_audio_transcription.completed',item_id:'late',transcript:'Oferta u dërgua'});
  assert.equal(events.find(e=>e.type==='transcript').turn_id,'old-turn');
  host.stop();
});

test('interruption before response.created cancels the late response request',()=>{
  const {host,sent,advance}=fakes();
  host.say('SISTEMI: Pyetja');
  const request=sent.find(e=>e.type==='response.create');
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'staff'});
  advance(300);host._heard(speech());advance(150);
  host._onRealtime({type:'response.created',response:{id:'late',metadata:request.response.metadata}});
  host._onRealtime({type:'response.output_audio.delta',response_id:'late',item_id:'audio',delta:int16ToBase64(new Int16Array(4800))});
  assert.ok(sent.some(e=>e.type==='response.cancel'&&e.response_id==='late'));
  assert.equal(host._playback.playing,false);
  host.stop();
});

test('a slow GA lookup finishing after staff handoff is deferred without reading stale data',()=>{
  const {host,sent,events}=fakes();
  host._onRealtime({type:'response.created',response:{id:'lookup'}});
  host._onRealtime({type:'response.output_item.done',response_id:'lookup',item:{type:'function_call',name:'list_new_done_and_strikes',call_id:'p',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'lookup',status:'completed'}});
  host.configure('STAFF_PHASE','11','t1');
  host.say('SISTEMI: RADHA e stafit');
  assert.ok(sent.some(e=>e.type==='response.create'));
  const before=sent.filter(e=>e.type==='response.create').length;
  host.toolResult('p',{announcements:[{token:'stale',read_aloud:'Progresi i vjetër.'}]});
  assert.equal(events.filter(e=>e.type==='announcement_deferred'&&e.token==='stale').length,1);
  assert.equal(sent.filter(e=>e.type==='response.create').length,before);
  assert.equal(sent.filter(e=>e.type==='response.create').at(-1).response.tool_choice,undefined);
  host.stop();
});

test('official staff handoff stops opening audio even without an announcement token',()=>{
  const {host,sent,events}=fakes();
  host.say('SISTEMI: Hyrja e takimit');
  host._onRealtime({type:'response.created',response:{id:'opening'}});
  host._onRealtime({type:'response.output_audio.delta',response_id:'opening',item_id:'opening-audio',delta:int16ToBase64(new Int16Array(4800))});
  assert.equal(host._playback.playing,true);
  host.configure('STAFF_PHASE','11','first-turn');
  assert.equal(host._playback.playing,false);
  assert.ok(sent.some(e=>e.type==='response.cancel'));
  assert.equal(events.filter(e=>e.type==='announcement_deferred').length,0);
  host.stop();
});

test('changing staff person stops the previous persons audio and late frames',()=>{
  const {host,sent}=fakes();
  host.configure('STAFF_PHASE','11','first');
  host.say('SISTEMI: RADHA e parë');
  host._onRealtime({type:'response.created',response:{id:'first-answer'}});
  const frame={type:'response.output_audio.delta',response_id:'first-answer',item_id:'first-audio',delta:int16ToBase64(new Int16Array(4800))};
  host._onRealtime(frame);assert.equal(host._playback.playing,true);
  host.configure('STAFF_PHASE','22','second');
  assert.equal(host._playback.playing,false);
  host._onRealtime(frame);assert.equal(host._playback.playing,false);
  assert.ok(sent.some(e=>e.type==='response.cancel'));
  host.stop();
});

test('an old turns delayed pause transcript does not interrupt the new person',async()=>{
  const {host,events,dispatch,connection,streams,advance}=fakes({voiceReady:true});
  dispatch('GUILD_CREATE',{id:'1'});await Promise.resolve();
  host.configure('STAFF_PHASE','11','old');host.say('SISTEMI: RADHA',{respond:false});
  connection.receiver.speaking.emit('start','11');
  streams.get('11').emit('data',toDiscord(new Int16Array(2400).fill(2000)).pcm);advance(100);
  host._onRealtime({type:'input_audio_buffer.speech_started',audio_start_ms:0,item_id:'late'});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',audio_end_ms:100,item_id:'late'});
  host.configure('STAFF_PHASE','22','new');host.say('SISTEMI: RADHA e re');
  host._onRealtime({type:'response.created',response:{id:'new-answer'}});
  host._onRealtime({type:'conversation.item.input_audio_transcription.completed',item_id:'late',transcript:'prit'});
  host._onRealtime({type:'response.output_audio.delta',response_id:'new-answer',item_id:'new-audio',delta:int16ToBase64(new Int16Array(4800))});
  assert.equal(host._playback.playing,true);
  assert.equal(events.find(e=>e.type==='transcript'&&e.text==='prit').turn_id,'old');
  host.stop();
});

test('an old turns delayed resume does not override the current persons explicit pause',()=>{
  const {host,sent}=fakes();
  host.configure('STAFF_PHASE','11','old');
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'old-speech'});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',item_id:'old-speech'});
  host.configure('STAFF_PHASE','22','new');
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'current-speech'});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',item_id:'current-speech'});
  host._onRealtime({type:'conversation.item.input_audio_transcription.completed',item_id:'current-speech',transcript:'prit'});
  host._onRealtime({type:'conversation.item.input_audio_transcription.completed',item_id:'old-speech',transcript:'vazhdo'});
  host.say('SISTEMI: Pyetja e radhës');
  assert.equal(sent.filter(e=>e.type==='response.create').length,0);
  host.stop();
});

test('a delayed opening pause cannot silence the goodbye even though both phases have no turn id',()=>{
  const {host}=fakes();
  host._onRealtime({type:'input_audio_buffer.speech_started',item_id:'opening-speech'});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',item_id:'opening-speech'});
  host.configure('ENDING');host.say('SISTEMI: Mbyll shkurt');
  host._onRealtime({type:'response.created',response:{id:'goodbye'}});
  host._onRealtime({type:'conversation.item.input_audio_transcription.completed',item_id:'opening-speech',transcript:'prit'});
  host._onRealtime({type:'response.output_audio.delta',response_id:'goodbye',item_id:'goodbye-audio',delta:int16ToBase64(new Int16Array(4800))});
  assert.equal(host._playback.playing,true);
  host.stop();
});

test('the initial opening still honors a current pause with timestamped input audio',async()=>{
  const {host,sent,dispatch,connection,streams,advance}=fakes({voiceReady:true});
  dispatch('GUILD_CREATE',{id:'1'});await Promise.resolve();
  host.say('SISTEMI: Hyrja',{respond:false});
  connection.receiver.speaking.emit('start','11');
  streams.get('11').emit('data',toDiscord(new Int16Array(2400).fill(2000)).pcm);advance(100);
  host._onRealtime({type:'input_audio_buffer.speech_started',audio_start_ms:0,item_id:'pause'});
  host._onRealtime({type:'input_audio_buffer.speech_stopped',audio_end_ms:100,item_id:'pause'});
  host._onRealtime({type:'conversation.item.input_audio_transcription.completed',item_id:'pause',transcript:'prit'});
  host.say('SISTEMI: Notes e reja');
  assert.equal(sent.filter(e=>e.type==='response.create').length,0);
  host.stop();
});

test('a lookup for an old staff turn does not block the new staff prompt',()=>{
  const {host,sent}=fakes();
  host.configure('STAFF_PHASE','11','old');
  host._onRealtime({type:'response.created',response:{id:'lookup'}});
  host._onRealtime({type:'response.output_item.done',response_id:'lookup',item:{type:'function_call',name:'get_person_brief',call_id:'brief',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'lookup',status:'completed'}});
  host.configure('STAFF_PHASE','22','new');host.say('SISTEMI: RADHA e re');
  const count=sent.filter(e=>e.type==='response.create').length;
  assert.equal(count,1);
  host.toolResult('brief',{person:'Old person',current:[]});
  assert.equal(sent.filter(e=>e.type==='response.create').length,count);
  host.stop();
});

test('a write in flight keeps its actual result across a staff handoff',()=>{
  const {host,sent}=fakes();
  host.configure('STAFF_PHASE','11','old');
  host._onRealtime({type:'response.created',response:{id:'writing'}});
  host._onRealtime({type:'response.output_item.done',response_id:'writing',item:{type:'function_call',name:'record_task_discussion',call_id:'write',arguments:'{}'}});
  host._onRealtime({type:'response.done',response:{id:'writing',status:'completed'}});
  host.configure('STAFF_PHASE','22','new');host.say('SISTEMI: RADHA e re');
  assert.equal(sent.filter(e=>e.type==='response.create').length,0);
  host.toolResult('write',{success:true,discussion:{progress:'Oferta u dërgua'}});
  const result=sent.find(e=>e.item?.type==='function_call_output'&&e.item.call_id==='write');
  assert.equal(JSON.parse(result.item.output).success,true);
  assert.equal(sent.filter(e=>e.type==='response.create').length,1);
  host.stop();
});

test('decoder creation recovering on the next speech clears the previous health failure',async()=>{
  let attempts=0;
  const {host,events,dispatch,connection,streams}=fakes({voiceReady:true,makeDecoder:()=>{
    if(++attempts===1)throw Error('temporary decoder allocation failure');
    return {decode:packet=>packet,delete(){}};
  }});
  dispatch('GUILD_CREATE',{id:'1'});await Promise.resolve();
  connection.receiver.speaking.emit('start','11');
  assert.equal(events.filter(e=>e.type==='audio_health'&&e.status==='failed').length,1);
  connection.receiver.speaking.emit('start','11');
  streams.get('11').emit('data',toDiscord(new Int16Array(240).fill(2000)).pcm);
  assert.equal(events.filter(e=>e.type==='audio_health'&&e.status==='recovered').length,1);
  host.stop();
});
