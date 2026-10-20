import {createRequire} from 'node:module';

// opusscript's JS wrapper indexes its 16-bit heap view with byte pointers, so
// decoded PCM is written to twice the allocated address, and it caches heap
// views that detach when the WASM heap grows. Both corrupt or break decoding
// once many speakers have decoders. This wrapper calls the same native Opus
// handler with correct byte pointers and reads the live heap on every call.
// Its WASM build also corrupts memory on packets longer than 60 ms; Discord
// sends 20 ms frames, so such a packet is undecryptable garbage and is rejected.
const require=createRequire(import.meta.url);
const CHANNELS=2,MAX_PACKET=1276*3,MAX_SAMPLES=5760; // 120 ms at 48 kHz, the Opus maximum
const MAX_DECODED_SAMPLES=2880; // 60 ms

// Samples per frame at 48 kHz from the TOC config (RFC 6716, section 3.1).
function frameSamples(config){
  if(config<12)return [480,960,1920,2880][config%4];
  if(config<16)return [480,960][config%2];
  return [120,240,480,960][config%4];
}
export function packetSamples(packet){
  const code=packet[0]&3;
  const frames=code===0?1:code<3?2:packet.length>1?packet[1]&0x3f:0;
  return frames*frameSamples(packet[0]>>3);
}
const ERRORS={'-1':'Bad argument','-2':'Buffer too small','-3':'Internal error','-4':'Invalid packet',
  '-5':'Unimplemented','-6':'Invalid state','-7':'Memory allocation fail'};
let native,load=()=>require('opusscript/build/opusscript_native_wasm.js')();
// Tests replace the WASM module loader to simulate a trapping heap.
export function setOpusLoader(loader){load=loader;native=undefined;}

function open(){
  native??=load();
  const module=native;
  try{
    const handler=new module.OpusScriptHandler(48000,CHANNELS,2049);
    return {module,handler,input:module._malloc(MAX_PACKET),output:module._malloc(MAX_SAMPLES*CHANNELS*2)};
  }catch(error){
    // A WASM trap means this heap is damaged; later speakers get a fresh instance.
    if(error instanceof WebAssembly.RuntimeError&&native===module)native=undefined;
    throw error;
  }
}

export function createOpusDecoder(){
  let state;
  try{state=open();}catch(error){if(!(error instanceof WebAssembly.RuntimeError))throw error;state=open();}
  const {module,handler,input,output}=state;
  let freed=false;
  return {
    decode(packet){
      if(freed)throw Error('Decode error: Invalid state');
      if(!packet?.length||packet.length>MAX_PACKET)throw Error('Decode error: Invalid packet');
      const samples=packetSamples(packet);
      if(!samples||samples>MAX_DECODED_SAMPLES)throw Error('Decode error: Invalid packet');
      let decoded;
      try{module.HEAPU8.set(packet,input);decoded=handler._decode(input,packet.length,output);}
      catch(error){
        if(error instanceof WebAssembly.RuntimeError&&native===module)native=undefined;
        throw Error('Decode error: Internal error');
      }
      if(decoded<0)throw Error('Decode error: '+(ERRORS[decoded]??'Internal error'));
      return Buffer.from(module.HEAPU8.slice(output,output+decoded*CHANNELS*2));
    },
    delete(){
      if(freed)return;freed=true;
      // Freeing into a damaged heap can trap; the instance is abandoned then.
      try{module.OpusScriptHandler.destroy_handler(handler);module._free(input);module._free(output);}
      catch(error){if(!(error instanceof WebAssembly.RuntimeError))throw error;if(native===module)native=undefined;}
    },
  };
}
