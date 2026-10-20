import {test,mock} from 'node:test';import assert from 'node:assert/strict';import {EventEmitter} from 'node:events';
import {createReceiver} from '../worker.mjs';
import {createOpusDecoder} from '../opus.mjs';

function fixture(makeDecoder=()=>({decode:x=>x,delete(){}}),{entersState=async()=>{}}={}){
 const events=[];let options,adapter;const speaking=new EventEmitter();const conn=new EventEmitter();
 const streams=new Map();const clock={t:0};
 conn.receiver={speaking,subscribe:id=>{const s=new EventEmitter();s.destroy=()=>s.emit('close');streams.set(id,s);return s;}};
 conn.state={status:'ready'};conn.rejoins=0;conn.rejoin=()=>{conn.rejoins++;return true;};
 conn.destroy=()=>{conn.state={status:'destroyed'};conn.emit('stateChange',{}, {status:'destroyed'});};
 const voice={VoiceConnectionStatus:{Ready:'ready',Disconnected:'disconnected'},EndBehaviorType:{AfterSilence:1},
  joinVoiceChannel:o=>{options=o;adapter=o.adapterCreator({onVoiceServerUpdate:x=>events.push(x),onVoiceStateUpdate:x=>events.push(x),destroy:()=>{}});return conn;},entersState};
 const r=createReceiver({sessionId:'s',instanceId:'i',guildId:'1',channelId:'2',userId:'3',emit:x=>events.push(x),voice,makeDecoder,now:()=>clock.t});
 return {r,events,get options(){return options;},get adapter(){return adapter;},conn,streams,clock};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('a transient Discord disconnect reconnects without ending the meeting',async()=>{
 const f=fixture();await f.r.ready;
 try{
  f.conn.state={status:'disconnected',closeCode:4014};f.conn.emit('stateChange',{}, {status:'disconnected',closeCode:4014});
  await tick();
  assert.equal(f.events.some(x=>x.type==='interrupted'),false);
  assert.equal(f.events.find(x=>x.type==='audio_gap')?.reason,'voice_reconnecting');
 }finally{f.r.stop();}
});

test('a disconnect that Discord does not repair is rejoined once, then reported',async()=>{
 let readyWaits=0;
 // The initial handshake succeeds; every recovery wait times out.
 const f=fixture(undefined,{entersState:async(_c,status)=>{if(status==='ready'&&readyWaits++>0)throw Error('timeout');}});
 await f.r.ready;
 f.conn.state={status:'disconnected',closeCode:4014};f.conn.emit('stateChange',{}, {status:'disconnected',closeCode:4014});
 await tick();await tick();
 assert.equal(f.conn.rejoins,1);
 const interrupted=f.events.find(x=>x.type==='interrupted');
 assert.equal(interrupted?.reason,'voice_disconnected');assert.equal(interrupted.close_code,4014);
});

test('a voice transport error event is diagnostic, not a meeting stop',async()=>{
 const f=fixture();await f.r.ready;
 try{f.conn.emit('error',Error('socket hiccup'));
  assert.equal(f.events.some(x=>x.type==='interrupted'),false);
  assert.equal(f.events.find(x=>x.type==='audio_gap')?.reason,'voice_error');
 }finally{f.r.stop();}
});

test('a receive stream error drops only that speaker, who is captured again on the next turn',async()=>{
 const f=fixture();await f.r.ready;
 try{
  for(const id of ['10','11']){f.conn.receiver.speaking.emit('start',id);f.streams.get(id).emit('data',Buffer.alloc(1920));}
  const broken=f.streams.get('11');broken.emit('error',Error('Failed to parse packet'));broken.emit('close');
  f.streams.get('10').emit('data',Buffer.alloc(1920));
  assert.equal(f.events.some(x=>x.type==='interrupted'),false);
  assert.equal(f.events.find(x=>x.type==='audio_gap')?.reason,'receive_error');
  f.conn.receiver.speaking.emit('start','11');
  assert.notEqual(f.streams.get('11'),broken);f.streams.get('11').emit('data',Buffer.alloc(1920));
 }finally{f.r.stop();}
 assert.deepEqual(f.events.filter(x=>x.type==='segment').map(x=>x.speaker_id).sort(),['10','11','11']);
});

test('one speaker whose audio never decodes does not stop the meeting',async()=>{
 mock.timers.enable({apis:['setTimeout']});
 const f=fixture();
 try{
  await f.r.ready;
  f.conn.receiver.speaking.emit('start','10');f.streams.get('10').emit('data',Buffer.alloc(1920));
  f.conn.receiver.speaking.emit('start','11');
  f.clock.t=10000;mock.timers.tick(10000);
  assert.equal(f.events.some(x=>x.type==='interrupted'),false);
  assert.equal(f.events.find(x=>x.type==='audio_gap')?.reason,'no_decoded_audio');
 }finally{f.r.stop();mock.timers.reset();}
});

test('a corrupt Opus packet from one participant does not stop other speakers',async()=>{
 const f=fixture(()=>({decode:p=>{if(p[0]===255)throw Error('Decode error: Invalid packet');return p;},delete(){}}));
 await f.r.ready;
 try{
  for(const id of ['10','11','12']){f.conn.receiver.speaking.emit('start',id);f.streams.get(id).emit('data',Buffer.alloc(1920));}
  f.streams.get('11').emit('data',Buffer.from([255]));
  f.streams.get('12').emit('data',Buffer.alloc(1920));
  f.streams.get('11').emit('data',Buffer.alloc(1920));
  assert.equal(f.events.some(x=>x.type==='interrupted'),false);
  assert.equal(f.events.find(x=>x.type==='audio_gap')?.reason,'decode_invalid_packet');
 }finally{f.r.stop();}
 assert.equal(f.events.at(-1).partial,true);
 assert.equal(f.events.filter(x=>x.type==='segment').length,3);
});

test('a short burst of undecodable audio (e.g. a DAVE key change) keeps listening',async()=>{
 const f=fixture(()=>({decode(){throw Error('Decode error: Invalid packet');},delete(){}}));await f.r.ready;
 try{f.conn.receiver.speaking.emit('start','10');for(let n=0;n<150;n++){f.clock.t=n*20;f.streams.get('10').emit('data',Buffer.from([255]));}
 assert.equal(f.events.some(x=>x.type==='interrupted'),false);}finally{f.r.stop();}
});

test('persistent invalid audio still fails instead of pretending to listen',async()=>{
 const f=fixture(()=>({decode(){throw Error('Decode error: Invalid packet');},delete(){}}));await f.r.ready;
 try{
  for(let n=0;n<=1600&&!f.events.some(x=>x.type==='interrupted');n++){
   // 32 s of undecodable packets; a dropped speaker is resubscribed on the next start.
   f.clock.t=n*20;f.conn.receiver.speaking.emit('start','10');
   f.streams.get('10').emit('data',Buffer.from([255]));
  }
  assert.equal(f.events.find(x=>x.type==='interrupted')?.reason,'decode_error');
 }finally{f.r.stop();}
});

test('real Opus decoder recovers after a malformed packet between valid frames',async()=>{
 const f=fixture(createOpusDecoder);await f.r.ready;
 try{
  f.conn.receiver.speaking.emit('start','10');const s=f.streams.get('10');
  s.emit('data',Buffer.from([0xf8,0xff,0xfe]));
  s.emit('data',Buffer.from([0xff]));
  s.emit('data',Buffer.from([0xf8,0xff,0xfe]));
  assert.equal(f.events.some(x=>x.type==='interrupted'),false);
  assert.equal(f.events.find(x=>x.type==='audio_gap')?.reason,'decode_invalid_packet');
 }finally{f.r.stop();}
 assert.equal(f.events.filter(x=>x.type==='segment').length,1);
});
test('transport joins muted and undeafened with DAVE and emits ready only after handshake',async()=>{
 const f=fixture();await f.r.ready;assert.equal(f.options.selfMute,true);assert.equal(f.options.selfDeaf,false);assert.equal(f.options.daveEncryption,true);
 assert.equal(f.events[0].type,'ready');f.r.stop();assert.equal(f.events.at(-1).type,'stopped');f.r.stop();assert.equal(f.events.filter(x=>x.type==='stopped').length,1);
});
test('adapter forwards only matching voice events; unexpected destroy interrupts',async()=>{
 const f=fixture();await f.r.ready;f.r.gateway({t:'VOICE_SERVER_UPDATE',d:{guild_id:'other'}});assert.equal(f.events.length,1);
 f.r.gateway({t:'VOICE_SERVER_UPDATE',d:{guild_id:'1',endpoint:'voice'}});assert.equal(f.events.length,2);
 f.conn.emit('stateChange',{}, {status:'destroyed'});assert.equal(f.events.find(x=>x.type==='interrupted').reason,'voice_disconnected');
});
test('moving the bot to an unannounced voice channel immediately stops capture',async()=>{
 const f=fixture();await f.r.ready;f.r.gateway({t:'VOICE_STATE_UPDATE',d:{guild_id:'1',user_id:'3',channel_id:'99'}});
 assert.equal(f.events.find(x=>x.type==='interrupted')?.reason,'voice_moved');
});
