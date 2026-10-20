import {test} from 'node:test';import assert from 'node:assert/strict';import {EventEmitter} from 'node:events';
import {createReceiver} from '../worker.mjs';
import Opus from 'opusscript';

function fixture(makeDecoder=()=>({decode:x=>x,delete(){}})){
 const events=[];let options,adapter;const speaking=new EventEmitter();const conn=new EventEmitter();
 const streams=new Map();
 conn.receiver={speaking,subscribe:id=>{const s=new EventEmitter();streams.set(id,s);return s;}};conn.destroy=()=>conn.emit('stateChange',{}, {status:'destroyed'});
 const voice={VoiceConnectionStatus:{Ready:'ready',Disconnected:'disconnected'},EndBehaviorType:{AfterSilence:1},
  joinVoiceChannel:o=>{options=o;adapter=o.adapterCreator({onVoiceServerUpdate:x=>events.push(x),onVoiceStateUpdate:x=>events.push(x),destroy:()=>{}});return conn;},entersState:async()=>{}};
 const r=createReceiver({sessionId:'s',instanceId:'i',guildId:'1',channelId:'2',userId:'3',emit:x=>events.push(x),voice,makeDecoder});
 return {r,events,get options(){return options;},get adapter(){return adapter;},conn,streams};
}

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

test('persistent invalid audio still fails instead of pretending to listen',async()=>{
 const f=fixture(()=>({decode(){throw Error('Decode error: Invalid packet');},delete(){}}));await f.r.ready;
 try{f.conn.receiver.speaking.emit('start','10');for(let n=0;n<100;n++)f.streams.get('10').emit('data',Buffer.from([255]));
 assert.equal(f.events.find(x=>x.type==='interrupted')?.reason,'decode_error');}finally{f.r.stop();}
});

test('real Opus decoder recovers after a malformed packet between valid frames',async()=>{
 const f=fixture(()=>new Opus(48000,2,Opus.Application.AUDIO));await f.r.ready;
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
test('adapter forwards only matching voice events; unexpected disconnect interrupts',async()=>{
 const f=fixture();await f.r.ready;f.r.gateway({t:'VOICE_SERVER_UPDATE',d:{guild_id:'other'}});assert.equal(f.events.length,1);
 f.r.gateway({t:'VOICE_SERVER_UPDATE',d:{guild_id:'1',endpoint:'voice'}});assert.equal(f.events.length,2);
 f.conn.emit('stateChange',{}, {status:'disconnected'});assert.equal(f.events.find(x=>x.type==='interrupted').reason,'voice_disconnected');
});
test('moving the bot to an unannounced voice channel immediately stops capture',async()=>{
 const f=fixture();await f.r.ready;f.r.gateway({t:'VOICE_STATE_UPDATE',d:{guild_id:'1',user_id:'3',channel_id:'99'}});
 assert.equal(f.events.find(x=>x.type==='interrupted')?.reason,'voice_moved');
});
