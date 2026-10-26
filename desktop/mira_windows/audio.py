"""Bounded WASAPI input capture. Never opens a playback stream."""
import io
import math
import queue
import threading
import time
import wave

import numpy as np
from scipy.signal import resample_poly

RATE = 48000
CHUNK_FRAMES = RATE*10
MAX_SECONDS = 4*60*60


def wav_bytes(pcm):
    target = io.BytesIO()
    with wave.open(target,'wb') as stream:
        stream.setnchannels(2);stream.setsampwidth(2);stream.setframerate(RATE)
        stream.writeframes(pcm.astype('<i2').tobytes())
    return target.getvalue()


class TimelineMixer:
    def __init__(self):
        self.blocks = {};self.cursor = 0

    @property
    def buffered_frames(self):return len(self.blocks)*CHUNK_FRAMES

    def push(self, source, samples, sample_rate, start_seconds):
        if source not in ('system','mic'):raise ValueError('invalid_source')
        mono = np.asarray(samples,dtype=np.float32).reshape(len(samples),-1).mean(axis=1)
        divisor = math.gcd(int(sample_rate),RATE)
        if sample_rate != RATE:mono = resample_poly(mono,RATE//divisor,int(sample_rate)//divisor)
        start = round(max(0,start_seconds)*RATE)
        if start < self.cursor:raise ValueError('Audio erdhi me vonesë. Takimi është i pjesshëm.')
        if start + len(mono) > self.cursor + CHUNK_FRAMES*3:raise ValueError('audio_buffer_full')
        offset = 0
        while offset < len(mono):
            index,inside = divmod(start+offset,CHUNK_FRAMES)
            block = self.blocks.setdefault(index,np.zeros(CHUNK_FRAMES,dtype=np.float32))
            count = min(len(mono)-offset,CHUNK_FRAMES-inside)
            block[inside:inside+count] += mono[offset:offset+count]*.5
            offset += count

    def flush(self, elapsed, final=False):
        target = max(self.cursor,min(round(elapsed*RATE),MAX_SECONDS*RATE))
        if not final:target = target//CHUNK_FRAMES*CHUNK_FRAMES
        while self.cursor < target:
            count = min(CHUNK_FRAMES,target-self.cursor)
            mono = self.blocks.pop(self.cursor//CHUNK_FRAMES,np.zeros(CHUNK_FRAMES,dtype=np.float32))[:count]
            pcm = (np.clip(mono,-1,1)*32767).astype('<i2')
            chunk=(round(self.cursor*1000/RATE),round((self.cursor+count)*1000/RATE),np.repeat(pcm[:,None],2,axis=1))
            self.cursor += count
            yield chunk


class Capture:
    def __init__(self, on_chunk, on_level=lambda *args:None):
        import pyaudiowpatch as pa
        self.pa = pa;self.audio = pa.PyAudio();self.on_chunk = on_chunk;self.on_level = on_level
        self.streams = [];self.events = queue.Queue(maxsize=256);self.stop_event = threading.Event()
        self.fault = None;self.mixer = TimelineMixer();self.thread = None;self.started = None
        self.last_checked = 0

    def devices(self):
        loopbacks = list(self.audio.get_loopback_device_info_generator())
        microphones = [d for d in self.audio.get_device_info_generator()
            if d['maxInputChannels']>0 and not d.get('isLoopbackDevice')
            and self.audio.get_host_api_info_by_index(d['hostApi'])['type']==self.pa.paWASAPI]
        return loopbacks,microphones

    def defaults(self):
        return self.audio.get_default_wasapi_loopback()['index'],self.audio.get_default_wasapi_device(d_in=True)['index']

    def start(self, output_index, microphone_index):
        if self.thread:raise ValueError('capture_already_started')
        self.started = time.monotonic()
        try:
            for name,index in [('system',output_index),('mic',microphone_index)]:
                device = self.audio.get_device_info_by_index(index)
                channels = min(2,int(device['maxInputChannels']));rate = int(device['defaultSampleRate'])
                if channels < 1:raise ValueError('Pajisja e zgjedhur nuk ka hyrje audio.')
                def callback(raw,frames,timing,status,source=name,frequency=rate,channel_count=channels):
                    if status:self.fault = 'Pajisja raportoi humbje audio. Dëgjimi u ndal.'
                    if not self.stop_event.is_set():
                        # Map each device's ADC clock onto a shared monotonic clock.
                        delay = timing.get('current_time',0)-timing.get('input_buffer_adc_time',0)
                        if not 0 <= delay <= 2:delay = frames/frequency
                        at = max(0,time.monotonic()-self.started-delay)
                        try:self.events.put_nowait((source,raw,frequency,channel_count,at))
                        except queue.Full:self.fault = 'Përpunimi i audios mbeti prapa. Dëgjimi u ndal.'
                    return (None,self.pa.paContinue)
                self.streams.append(self.audio.open(format=self.pa.paFloat32,channels=channels,rate=rate,
                    input=True,input_device_index=index,frames_per_buffer=max(1,rate//50),stream_callback=callback))
            self.thread = threading.Thread(target=self._run,name='Mira capture',daemon=True);self.thread.start()
        except Exception:
            self.close();raise

    def _consume(self, event):
        source,raw,rate,channels,at = event
        samples = np.frombuffer(raw,dtype='<f4').reshape(-1,channels)
        self.on_level(source,min(1,float(np.sqrt(np.mean(samples*samples)))*5))
        self.mixer.push(source,samples,rate,at)

    def _emit(self,elapsed,final=False):
        for start,end,pcm in self.mixer.flush(elapsed,final):self.on_chunk(wav_bytes(pcm),start,end)

    def _run(self):
        try:
            while not self.stop_event.is_set():
                elapsed = time.monotonic()-self.started
                if elapsed-self.last_checked>2:
                    raise OSError('Kapja u ndërpre nga pritja ose gjumi i kompjuterit. Nise një takim të ri.')
                if self.fault:raise OSError(self.fault)
                if not all(s.is_active() for s in self.streams):raise OSError('Pajisja audio u shkëput.')
                try:self._consume(self.events.get(timeout=.1))
                except queue.Empty:pass
                elapsed = time.monotonic()-self.started
                if elapsed-self.last_checked>2:
                    raise OSError('Kapja u ndërpre nga pritja ose gjumi i kompjuterit. Nise një takim të ri.')
                self.last_checked = elapsed
                self._emit(max(0,elapsed-.5))
                if elapsed>=MAX_SECONDS:raise OSError('U arrit kufiri 4-orësh. Dëgjimi u ndal.')
        except Exception as exc:self.fault = str(exc)
        finally:
            self.stop_event.set()
            for stream in self.streams:
                try:stream.stop_stream()
                except OSError:pass
            while not self.events.empty():
                try:self._consume(self.events.get_nowait())
                except Exception as exc:self.fault = self.fault or str(exc)
            elapsed=time.monotonic()-self.started
            if elapsed-self.last_checked>2:
                self.fault=self.fault or 'Kapja u ndërpre nga gjumi i kompjuterit.'
                elapsed=self.last_checked
            try:self._emit(elapsed,final=True)
            except Exception as exc:self.fault = self.fault or str(exc)

    def stop(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=10)
        if self.thread and self.thread.is_alive():raise OSError('Ndalesa e audios nuk u konfirmua.')

    def close(self):
        self.stop()
        for stream in self.streams:
            try:stream.close()
            except OSError:pass
        self.streams = [];self.audio.terminate()
