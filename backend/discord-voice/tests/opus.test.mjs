import {test} from 'node:test';import assert from 'node:assert/strict';import {randomBytes} from 'node:crypto';
import {createRequire} from 'node:module';
import {createOpusDecoder,setOpusLoader} from '../opus.mjs';

const require=createRequire(import.meta.url);

const SILENCE=Buffer.from([0xf8,0xff,0xfe]);

test('a 20 ms Opus frame decodes to 960 stereo 16-bit samples',()=>{
 const d=createOpusDecoder();
 try{assert.equal(d.decode(SILENCE).length,960*2*2);}finally{d.delete();}
});

test('corrupt packets from many speakers never damage memory for new decoders',()=>{
 for(let round=0;round<3000;round++){
  const d=createOpusDecoder();
  for(let i=0;i<50;i++){
   const packet=randomBytes([1,3,60,200,1000,1275,3828][i%7]);
   try{d.decode(packet);}catch(error){assert.match(error.message,/^Decode error: /);}
  }
  d.delete();
 }
 const d=createOpusDecoder();try{assert.equal(d.decode(SILENCE).length,3840);}finally{d.delete();}
});

test('existing speakers keep decoding after the WASM heap grows for new speakers',()=>{
 const first=createOpusDecoder();const crowd=[];
 try{
  for(let n=0;n<1500;n++)crowd.push(createOpusDecoder());
  assert.equal(first.decode(SILENCE).length,3840);
  assert.equal(crowd.at(-1).decode(SILENCE).length,3840);
 }finally{first.delete();for(const d of crowd)d.delete();}
});

test('packets longer than 60 ms (which crash the WASM build) are rejected before decoding',()=>{
 const d=createOpusDecoder();
 try{
  // SILK 60 ms config, code 1 = two frames = 120 ms
  assert.throws(()=>d.decode(Buffer.from([(3<<3)|1,1,2,3,4])),/Decode error: Invalid packet/);
  // hybrid 20 ms config, code 3 with 6 frames = 120 ms
  assert.throws(()=>d.decode(Buffer.from([(13<<3)|3,6,1,2,3])),/Decode error: Invalid packet/);
  // code 3 without a frame count byte, or with zero frames
  assert.throws(()=>d.decode(Buffer.from([(31<<3)|3])),/Decode error: Invalid packet/);
  assert.throws(()=>d.decode(Buffer.from([(31<<3)|3,0])),/Decode error: Invalid packet/);
  assert.equal(d.decode(SILENCE).length,3840);
 }finally{d.delete();}
});

test('a WASM trap abandons that heap so the next speaker still gets a working decoder',()=>{
 const trap=()=>{throw new WebAssembly.RuntimeError('memory access out of bounds');};
 let loads=0;
 const damaged={HEAPU8:new Uint8Array(1<<16),_malloc:()=>16,_free:trap,
  OpusScriptHandler:class{_decode(){trap();}static destroy_handler(){trap();}}};
 setOpusLoader(()=>{loads++;return loads===1?damaged:require('opusscript/build/opusscript_native_wasm.js')();});
 try{
  const broken=createOpusDecoder();
  assert.throws(()=>broken.decode(SILENCE),/Decode error: Internal error/);
  broken.delete();
  const next=createOpusDecoder();
  try{assert.equal(next.decode(SILENCE).length,3840);assert.equal(loads,2);}finally{next.delete();}
 }finally{setOpusLoader(()=>require('opusscript/build/opusscript_native_wasm.js')());}
});

test('oversized and empty packets are rejected as invalid, and delete is idempotent',()=>{
 const d=createOpusDecoder();
 assert.throws(()=>d.decode(Buffer.alloc(0)),/Decode error: Invalid packet/);
 assert.throws(()=>d.decode(Buffer.alloc(5000)),/Decode error: Invalid packet/);
 d.delete();d.delete();
 assert.throws(()=>d.decode(SILENCE),/Decode error: Invalid state/);
});
