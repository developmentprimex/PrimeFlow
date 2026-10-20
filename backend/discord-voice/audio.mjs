const MAX_PCM=48000*4*10;
export function encodeWav(pcm) {
  if (!Buffer.isBuffer(pcm)||pcm.length%4||pcm.length+44>2000000) throw Error('audio_size');
  const h=Buffer.alloc(44);h.write('RIFF');h.writeUInt32LE(pcm.length+36,4);h.write('WAVEfmt ',8);
  h.writeUInt32LE(16,16);h.writeUInt16LE(1,20);h.writeUInt16LE(2,22);h.writeUInt32LE(48000,24);
  h.writeUInt32LE(192000,28);h.writeUInt16LE(4,32);h.writeUInt16LE(16,34);h.write('data',36);h.writeUInt32LE(pcm.length,40);
  return Buffer.concat([h,pcm]);
}
export class SegmentBuffer {
  constructor(emit){this.emit=emit;this.speakers=new Map();this.pending=new Set();this.sequence=0;this.bytes=0;this.closed=false;}
  push(id,pcm,time){
    if(this.closed)return;
    if(this.bytes+pcm.length>16*1024*1024)throw Error('audio_backpressure');
    if(!this.speakers.has(id))this.speakers.set(id,{parts:[],size:0,start:time,end:time});
    const s=this.speakers.get(id);s.parts.push(Buffer.from(pcm));s.size+=pcm.length;s.end=time+pcm.length/192;
    this.bytes+=pcm.length;
    if(s.size>=MAX_PCM)this.flush(id);
  }
  flush(id){
    const s=this.speakers.get(id);if(!s?.size)return;
    if(this.pending.size>=8)throw Error('audio_backpressure');
    const sequence=this.sequence++,wav=encodeWav(Buffer.concat(s.parts));
    this.pending.add(sequence);this.bytes-=s.size;this.speakers.delete(id);
    this.emit({type:'segment',sequence,speaker_id:id,start_ms:Math.floor(s.start),end_ms:Math.ceil(s.end),audio_base64:wav.toString('base64')});
  }
  credit(sequence){this.pending.delete(sequence);}
  stop(){if(this.closed)return;for(const id of this.speakers.keys())this.flush(id);this.closed=true;}
  clear(){this.closed=true;this.speakers.clear();this.bytes=0;}
}
