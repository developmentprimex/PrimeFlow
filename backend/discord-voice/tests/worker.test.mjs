import {test} from 'node:test';import assert from 'node:assert/strict';import {EventEmitter} from 'node:events';
import {createReceiver} from '../worker.mjs';

function fixture(){
 const events=[];let options,adapter;const speaking=new EventEmitter();const conn=new EventEmitter();
 conn.receiver={speaking,subscribe:()=>new EventEmitter()};conn.destroy=()=>conn.emit('stateChange',{}, {status:'destroyed'});
 const voice={VoiceConnectionStatus:{Ready:'ready',Disconnected:'disconnected'},EndBehaviorType:{AfterSilence:1},
  joinVoiceChannel:o=>{options=o;adapter=o.adapterCreator({onVoiceServerUpdate:x=>events.push(x),onVoiceStateUpdate:x=>events.push(x),destroy:()=>{}});return conn;},entersState:async()=>{}};
 const r=createReceiver({sessionId:'s',instanceId:'i',guildId:'1',channelId:'2',userId:'3',emit:x=>events.push(x),voice,makeDecoder:()=>({decode:x=>x,delete(){}})});
 return {r,events,get options(){return options;},get adapter(){return adapter;},conn};
}
test('transport joins muted and undeafened with DAVE and emits ready only after handshake',async()=>{
 const f=fixture();await f.r.ready;assert.equal(f.options.selfMute,true);assert.equal(f.options.selfDeaf,false);assert.equal(f.options.daveEncryption,true);
 assert.equal(f.events[0].type,'ready');f.r.stop();assert.equal(f.events.at(-1).type,'stopped');f.r.stop();assert.equal(f.events.filter(x=>x.type==='stopped').length,1);
});
test('adapter forwards only matching voice events; unexpected disconnect interrupts',async()=>{
 const f=fixture();await f.r.ready;f.r.gateway({t:'VOICE_SERVER_UPDATE',d:{guild_id:'other'}});assert.equal(f.events.length,1);
 f.r.gateway({t:'VOICE_SERVER_UPDATE',d:{guild_id:'1',endpoint:'voice'}});assert.equal(f.events.length,2);
 f.conn.emit('stateChange',{}, {status:'disconnected'});assert.equal(f.events.find(x=>x.type==='interrupted').reason,'voice_disconnected');
});
