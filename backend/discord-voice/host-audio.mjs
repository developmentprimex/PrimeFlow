import {createRequire} from 'node:module';

// Audio helpers for Mira Host (the speaking 1H bot). The silent recorder in
// worker.mjs/audio.mjs is separate and does not use any of this.
// Discord: 48 kHz stereo 16-bit, 20 ms frames. OpenAI Realtime: 24 kHz mono 16-bit.
export const FRAME_SAMPLES=960; // 20 ms at 48 kHz
export const FRAME_BYTES=FRAME_SAMPLES*4;
const require=createRequire(import.meta.url);

// 48 kHz stereo -> 24 kHz mono: average both channels and each pair of samples.
export function toRealtime(pcm){
  const frames=Math.floor(pcm.length/8),out=new Int16Array(frames);
  for(let i=0;i<frames;i++){
    const o=i*8;
    out[i]=(pcm.readInt16LE(o)+pcm.readInt16LE(o+2)+pcm.readInt16LE(o+4)+pcm.readInt16LE(o+6))>>2;
  }
  return out;
}

// 24 kHz mono -> 48 kHz stereo with linear interpolation; `last` carries the
// previous chunk's final sample so chunk joins stay smooth.
export function toDiscord(samples,last=0){
  const out=Buffer.alloc(samples.length*8);
  let previous=last;
  for(let i=0;i<samples.length;i++){
    const current=samples[i],middle=(previous+current)>>1;
    out.writeInt16LE(middle,i*8);out.writeInt16LE(middle,i*8+2);
    out.writeInt16LE(current,i*8+4);out.writeInt16LE(current,i*8+6);
    previous=current;
  }
  return {pcm:out,last:previous};
}

export function int16FromBase64(value){
  const bytes=Buffer.from(value,'base64');
  return new Int16Array(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.length-(bytes.length%2)));
}

export function int16ToBase64(samples){
  return Buffer.from(samples.buffer,samples.byteOffset,samples.byteLength).toString('base64');
}

// Mixes every speaker into one 24 kHz stream. Realtime's VAD needs a
// continuous stream, so silence is sent while nobody talks.
export class Mixer{
  constructor({maxBufferedMs=2000}={}){this.queues=new Map();this.energy=new Map();this.max=maxBufferedMs*24;}
  push(id,samples){
    let queue=this.queues.get(id);
    if(!queue){queue=[];this.queues.set(id,queue);}
    queue.push(samples);
    let size=queue.reduce((n,s)=>n+s.length,0);
    while(size>this.max&&queue.length>1)size-=queue.shift().length; // a late speaker never builds up delay
    let sum=0;for(let i=0;i<samples.length;i++)sum+=Math.abs(samples[i]);
    this.energy.set(id,(this.energy.get(id)||0)+sum);
  }
  pull(count){
    const out=new Int32Array(count);
    for(const [id,queue] of this.queues){
      let written=0;
      while(written<count&&queue.length){
        const chunk=queue[0],take=Math.min(chunk.length,count-written);
        for(let i=0;i<take;i++)out[written+i]+=chunk[i];
        written+=take;
        if(take===chunk.length)queue.shift();else queue[0]=chunk.subarray(take);
      }
      if(!queue.length)this.queues.delete(id);
    }
    const mixed=new Int16Array(count);
    for(let i=0;i<count;i++)mixed[i]=Math.max(-32768,Math.min(32767,out[i]));
    return mixed;
  }
  // Who spoke most since the last call; used to name the speaker of a transcript.
  takeLoudest(){
    let best=null,max=0;
    for(const [id,value] of this.energy)if(value>max){max=value;best=id;}
    this.energy.clear();
    return best;
  }
  clear(){this.queues.clear();this.energy.clear();}
}

// opusscript's JS wrapper writes outside its buffers (see opus.mjs); the native
// encoder reads one PCM byte per 16-bit slot, so the input is laid out that way.
export function createOpusEncoder({loader=()=>require('opusscript/build/opusscript_native_wasm.js')()}={}){
  const module=loader();
  const handler=new module.OpusScriptHandler(48000,2,2048); // VOIP: tuned for speech
  const input=module._malloc(FRAME_BYTES*2),output=module._malloc(4000);
  let freed=false;
  return {
    encode(pcm){
      if(freed)throw Error('encoder_freed');
      if(pcm.length!==FRAME_BYTES)throw Error('frame_size');
      const slots=module.HEAPU16,base=input>>1;
      for(let i=0;i<pcm.length;i++)slots[base+i]=pcm[i];
      const length=handler._encode(input,pcm.length,output,FRAME_SAMPLES);
      if(length<0)throw Error('encode_error');
      return Buffer.from(module.HEAPU8.subarray(output,output+length));
    },
    delete(){
      if(freed)return;freed=true;
      try{module.OpusScriptHandler.destroy_handler(handler);module._free(input);module._free(output);}catch{}
    },
  };
}

// Mira's voice waits here as 20 ms Opus frames. clear() is the interruption:
// everything not yet sent is dropped at once and the played time is reported.
export class Playback{
  constructor(encode){this.encode=encode;this.frames=[];this.carry=Buffer.alloc(0);this.last=0;this.item=null;this.playedMs=0;}
  push(itemId,samples){
    if(this.item!==itemId){this.item=itemId;this.playedMs=0;}
    const {pcm,last}=toDiscord(samples,this.last);this.last=last;
    let data=this.carry.length?Buffer.concat([this.carry,pcm]):pcm,offset=0;
    while(data.length-offset>=FRAME_BYTES){this.frames.push(this.encode(data.subarray(offset,offset+FRAME_BYTES)));offset+=FRAME_BYTES;}
    this.carry=Buffer.from(data.subarray(offset));
  }
  // The tail of an answer is padded to a whole frame so the last word is heard.
  flush(){
    if(!this.carry.length)return;
    const frame=Buffer.alloc(FRAME_BYTES);this.carry.copy(frame);this.carry=Buffer.alloc(0);
    this.frames.push(this.encode(frame));
  }
  next(){
    const frame=this.frames.shift();
    if(frame)this.playedMs+=20;
    return frame;
  }
  get playing(){return this.frames.length>0;}
  clear(){
    const result={item:this.item,playedMs:this.playedMs,dropped:this.frames.length};
    this.frames=[];this.carry=Buffer.alloc(0);this.last=0;
    return result;
  }
}
