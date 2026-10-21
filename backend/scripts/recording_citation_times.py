"""Isolated CPU runner. Only reads explicitly supplied audio/text; no API or DB access.

Run in the pinned alignment environment, never import ML libraries in the API.
Model must already be cached. Audio inference is bounded to 20-second windows.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
import wave

os.environ.update(OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2',
                  HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', HF_HUB_DISABLE_XET='1')
# Allow execution by absolute path from the application's dedicated worker.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.recording_alignment_pilot import align, action_times, MODEL, REVISION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--cache', required=True, type=Path)
    parser.add_argument('--parent-pid', type=int, default=os.getppid())
    args = parser.parse_args()
    import psutil
    process = psutil.Process()
    parent = psutil.Process(args.parent_pid)
    if os.name == 'nt':
        process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    else:
        process.nice(10)
    if hasattr(process, 'cpu_affinity'):
        process.cpu_affinity(process.cpu_affinity()[:2])

    def guard():
        while True:
            # Do not leave an expensive orphan behind after a worker restart.
            if parent is None or not parent.is_running():
                os._exit(75)
            if psutil.virtual_memory().available < 4 * 1024**3 or process.memory_info().rss > 5 * 1024**3:
                os._exit(75)
            time.sleep(1)
    if psutil.virtual_memory().available < 6 * 1024**3:
        raise RuntimeError('insufficient_memory')
    threading.Thread(target=guard, daemon=True).start()
    import numpy as np
    import torch
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    data = json.loads(args.input.read_text(encoding='utf-8'))
    if not isinstance(data['text'], str) or len(data['text']) > 20000:
        raise ValueError('invalid_transcript')
    with wave.open(str(args.input.parent / 'audio.wav'), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise ValueError('invalid_audio')
        if not 0 < wav.getnframes() <= 302 * 16000:
            raise ValueError('invalid_duration')
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32) / 32768
    options = dict(revision=REVISION, cache_dir=str(args.cache.resolve()), token=False,
                   local_files_only=True, trust_remote_code=False)
    processor = Wav2Vec2Processor.from_pretrained(MODEL, **options)
    model = Wav2Vec2ForCTC.from_pretrained(MODEL, use_safetensors=True, **options).eval()
    emissions = []
    # Each window retains only compact vocabulary probabilities, not activations.
    for offset in range(0, len(samples), 20 * 16000):
        values = samples[offset:offset + 20 * 16000]
        if len(values) < 400:
            values = np.pad(values, (0, 400 - len(values)))
        with torch.inference_mode():
            emissions.append(model(**processor(values, sampling_rate=16000, return_tensors='pt')).logits.log_softmax(-1).cpu())
    probabilities = torch.cat(emissions, dim=1)
    words, unsupported = align(probabilities, data['text'], processor.tokenizer.get_vocab(),
                               model.config.pad_token_id, len(samples) / 16000)
    results = action_times(data['actions'], data['text'], words)
    # Scores are diagnostics, not probabilities. Weak matches remain unavailable.
    for item in results:
        if unsupported or item.get('acoustic_score', 0) < 0.3:
            item['start'] = item['end'] = None
    output = {'model': MODEL, 'revision': REVISION, 'actions': [
        {'id': a['id'], 'start': a['start'], 'end': a['end']} for a in results]}
    (args.input.parent / 'output.json').write_text(json.dumps(output), encoding='utf-8')


if __name__ == '__main__':
    main()
