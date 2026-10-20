import {test} from 'node:test';
import assert from 'node:assert/strict';
import {encodeWav, SegmentBuffer} from '../audio.mjs';
import {decodeMessage} from '../protocol.mjs';

test('WAV describes the exact stereo PCM and rejects oversized buffers',()=>{
  const pcm=Buffer.alloc(48000*4);const wav=encodeWav(pcm);
  assert.equal(wav.toString('ascii',0,4),'RIFF');assert.equal(wav.readUInt32LE(24),48000);
  assert.equal(wav.readUInt16LE(22),2);assert.equal(wav.readUInt32LE(40),pcm.length);
  assert.throws(()=>encodeWav(Buffer.alloc(2000000)));
});
test('overlapping speakers retain IDs and global sequence; stop flushes once',()=>{
  const chunks=[];const b=new SegmentBuffer(x=>chunks.push(x));
  b.push('12',Buffer.alloc(1920),100);b.push('13',Buffer.alloc(1920),110);b.flush('13');b.stop();b.stop();
  assert.deepEqual(chunks.map(x=>[x.sequence,x.speaker_id]),[[0,'13'],[1,'12']]);
  assert.equal(b.sequence,2);assert.equal(chunks[0].start_ms,110);
});
test('credit exhaustion interrupts rather than silently dropping speech',()=>{
  const b=new SegmentBuffer(()=>{});
  for(let i=0;i<8;i++){b.push('12',Buffer.alloc(1920),i*10);b.flush('12');}
  assert.throws(()=>{b.push('12',Buffer.alloc(1920),100);b.flush('12');},/backpressure/);
  b.credit(0);b.flush('12');assert.equal(b.sequence,9);
});
test('malformed, oversized, and unknown IPC messages are rejected',()=>{
  for(const value of ['[]','null','{"type":"eval"}','x'.repeat(3000001)])assert.throws(()=>decodeMessage(value));
  assert.equal(decodeMessage('{"type":"shutdown"}').type,'shutdown');
});
test('60ms Opus frames split exactly at the ten second WAV limit',()=>{
 const chunks=[];const b=new SegmentBuffer(x=>chunks.push(x));
 for(let i=0;i<167;i++)b.push('12',Buffer.alloc(11520),i*60);
 b.stop();assert.equal(chunks.length,2);
 for(const c of chunks)assert.ok(Buffer.from(c.audio_base64,'base64').length<=1920044);
});
test('packet gaps cannot make a chunk exceed the backend wall-time limit',()=>{
 const chunks=[];const b=new SegmentBuffer(x=>chunks.push(x));
 for(let i=0;i<500;i++)b.push('12',Buffer.alloc(3840),i*25);
 b.stop();assert.equal(chunks.length,2);
 for(const c of chunks)assert.ok(c.end_ms-c.start_ms<=10000);
});
