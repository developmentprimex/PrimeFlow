"""Offline Albanian CTC timing experiment, intentionally outside the API worker.

Run using tmp/recording-alignment-pilot/.venv. Downloads model weights only;
no audio/text is uploaded. Reads private input from export_recording_alignment_pilot.py.
Uses a CPU Albanian acoustic model and TorchAudio's CTC forced alignment,
the same family of alignment used by WhisperX, without its ASR/diarization stack.
"""
import argparse
import base64
import html
import json
import os
import re
import time
import unicodedata
import wave
from pathlib import Path

os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
MODEL = 'Alimzhan/wav2vec2-large-xls-r-300m-albanian-colab'
REVISION = '3f69142'


def normalized_word(word):
    # Keep transcript text untouched. Spell digits only in the acoustic target.
    digits = dict(zip('0123456789', ['zero', 'një', 'dy', 'tre', 'katër', 'pesë', 'gjashtë', 'shtatë', 'tetë', 'nëntë']))
    text = unicodedata.normalize('NFC', word).lower()
    return ''.join(digits.get(c, c) for c in text)


def align(log_probs, transcript, vocabulary, blank, duration):
    import torch
    from torchaudio.functional import forced_align, merge_tokens
    words = list(re.finditer(r'\S+', transcript))
    target, owners, unsupported = [], [], []
    separator = vocabulary.get('|')
    for index, match in enumerate(words):
        chars = [c for c in normalized_word(match.group()) if c in vocabulary and len(c) == 1 and c != '|']
        if not chars:
            unsupported.append(index)
            continue
        if target and separator is not None:
            target.append(separator)
            owners.append(None)
        target.extend(vocabulary[c] for c in chars)
        owners.extend([index] * len(chars))
    if not target:
        raise ValueError('No alignable transcript characters')
    path, scores = forced_align(log_probs, torch.tensor([target], dtype=torch.int64), blank=blank)
    tokens = merge_tokens(path[0], scores[0].exp(), blank=blank)
    if [t.token for t in tokens] != target:
        raise ValueError('CTC alignment did not preserve the target sequence')
    seconds_per_frame = duration / log_probs.shape[1]
    results = []
    for index, match in enumerate(words):
        spans = [span for span, owner in zip(tokens, owners) if owner == index]
        results.append({'text': match.group(), 'char_start': match.start(), 'char_end': match.end(),
            'start': round(spans[0].start * seconds_per_frame, 3) if spans else None,
            'end': round(spans[-1].end * seconds_per_frame, 3) if spans else None,
            'acoustic_score': round(sum(s.score for s in spans) / len(spans), 4) if spans else None})
    return results, unsupported


def action_times(actions, text, words):
    result = []
    # Ignore only punctuation/case when locating the saved evidence in the source.
    source = list(re.finditer(r'\w+', text.lower()))
    source_words = [m.group() for m in source]
    for action in actions:
        quote = re.findall(r'\w+', action['evidence'].lower())
        matches = [i for i in range(len(source_words) - len(quote) + 1) if quote and source_words[i:i + len(quote)] == quote]
        item = {**action, 'start': None, 'end': None, 'review_required': True}
        if len(matches) == 1:
            first, last = source[matches[0]].start(), source[matches[0] + len(quote) - 1].end()
            selected = [w for w in words if w['char_end'] > first and w['char_start'] < last]
            if selected and all(w['start'] is not None for w in selected):
                score = sum(w['acoustic_score'] for w in selected) / len(selected)
                item.update(start=selected[0]['start'], end=selected[-1]['end'], acoustic_score=round(score, 4),
                    review_required=True)  # Pilot results always require listening review.
        result.append(item)
    return result


def preview(folder, data, result):
    audio = base64.b64encode((folder / 'audio.wav').read_bytes()).decode('ascii')
    rows = []
    for action in result['actions']:
        jump = f'<button onclick="jump({action["start"]})">▶ {action["start"]:.2f}s – {action["end"]:.2f}s</button>' if action['start'] is not None else 'Koha nuk u përcaktua'
        rows.append(f'<tr><td>{html.escape(action["title"].upper())}<p>{html.escape(action["evidence"])}</p></td><td>{jump}</td></tr>')
    word_buttons = ' '.join(f'<button class="word" onclick="jump({w["start"]})" title="{w["start"]}s – {w["end"]}s">{html.escape(w["text"])}</button>' if w['start'] is not None else html.escape(w['text']) for w in result['words'])
    markup = f'''<!doctype html><html lang="sq"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prova e sekondave — regjistrim shqip</title><style>
body{{font:16px system-ui;background:#f5f7fa;color:#142033;margin:0;padding:30px}}main{{max-width:1100px;margin:auto;background:white;border:1px solid #dbe1e9;border-radius:12px;padding:28px}}
audio{{width:100%;margin:20px 0}}table{{width:100%;border-collapse:collapse}}td,th{{padding:16px;text-align:left;border:1px solid #dde3eb}}th{{background:#edf3fa}}td p{{font-size:14px;color:#596579;margin-bottom:0}}button{{cursor:pointer;border:1px solid #b8c8dc;border-radius:7px;background:#edf5ff;color:#123d71;padding:9px 12px;white-space:nowrap}}.word{{padding:3px 4px;margin:2px;border:0;background:transparent;color:#142033}}.word:hover{{background:#dcecff}}.notice{{padding:14px;background:#fff5da;border-radius:8px}}.stats{{color:#596579;font-size:14px}}</style>
<main><h1>Prova e sekondave</h1><p class="notice">Rezultat eksperimental. Kliko kohën dhe dëgjo nëse fjalia fillon aty. Saktësia ende duhet kontrolluar nga një dëgjues.</p>
<p class="stats">Audio: {data['duration_seconds']:.2f}s · Përpunimi pas ngarkimit të modelit: {result['metrics']['alignment_seconds']:.2f}s · CPU: {result['metrics']['threads']} threads · Kulmi i memories së procesit: {result['metrics']['peak_rss_mb']:.0f} MB</p>
<audio id="audio" controls src="data:audio/wav;base64,{audio}"></audio><table><thead><tr><th>Detyra / citimi</th><th>Koha e matur</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>Transkripti</h2><p>Kliko një fjalë për ta dëgjuar. Emrat dhe termat teknikë duhen kontrolluar.</p><div>{word_buttons}</div>
<p class="stats">Përpunim lokal. Nuk është dërguar audio ose tekst te një API. Regjistrimi, transkripti dhe detyrat në aplikacion nuk janë ndryshuar.</p></main>
<script>function jump(second){{const audio=document.getElementById('audio');audio.currentTime=Math.max(0,second-.25);audio.play();}}</script></html>'''
    (folder / 'preview.html').write_text(markup, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--threads', type=int, default=4, choices=range(1, 9))
    parser.add_argument('--local-only', action='store_true')
    args = parser.parse_args()
    folder = args.input.resolve().parent
    data = json.loads(args.input.read_text(encoding='utf-8'))
    if not 0 < data['duration_seconds'] <= 60 or len(data['segments']) != 1:
        raise ValueError('Pilot is limited to one transcript segment / 60s audio')
    started = time.perf_counter()
    import numpy as np
    import psutil
    import torch
    from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    cache = folder.parent / 'model-cache'
    model_args = dict(revision=REVISION, cache_dir=str(cache), token=False,
                      local_files_only=args.local_only, trust_remote_code=False)
    print('Loading CPU Albanian model; private audio remains local.', flush=True)
    load_started = time.perf_counter()
    processor = Wav2Vec2Processor.from_pretrained(MODEL, **model_args)
    model = Wav2Vec2ForCTC.from_pretrained(MODEL, use_safetensors=True, low_cpu_mem_usage=True, **model_args).eval()
    load_seconds = time.perf_counter() - load_started
    with wave.open(str(folder / 'audio.wav'), 'rb') as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float32) / 32768
    def emissions(values):
        inputs = processor(values, sampling_rate=16000, return_tensors='pt')
        with torch.inference_mode():
            return model(**inputs).logits.log_softmax(-1).cpu()
    print('Model loaded. Aligning saved transcript.', flush=True)
    alignment_started = time.perf_counter()
    probabilities = emissions(samples)
    transcript = data['segments'][0]['text']
    words, unsupported = align(probabilities, transcript, processor.tokenizer.get_vocab(), model.config.pad_token_id, len(samples) / 16000)
    alignment_seconds = time.perf_counter() - alignment_started
    # Known perturbation: prepend two seconds of silence. Real acoustic times
    # should move by approximately two seconds; this is not a human accuracy test.
    shift_started = time.perf_counter()
    shifted_samples = np.concatenate([np.zeros(32000, dtype=np.float32), samples])
    shifted, _ = align(emissions(shifted_samples), transcript, processor.tokenizer.get_vocab(), model.config.pad_token_id, len(shifted_samples) / 16000)
    shift_errors = [abs((s['start'] - w['start']) - 2) for w, s in zip(words, shifted) if w['start'] is not None and s['start'] is not None]
    memory = psutil.Process().memory_info()
    metrics = {'threads': args.threads, 'model_load_seconds': round(load_seconds, 3),
        'alignment_seconds': round(alignment_seconds, 3), 'shift_check_seconds': round(time.perf_counter() - shift_started, 3),
        'shift_check_median_error_seconds': round(float(np.median(shift_errors)), 3),
        'shift_check_max_error_seconds': round(max(shift_errors), 3),
        'peak_rss_mb': round(getattr(memory, 'peak_wset', memory.rss) / 1024 ** 2, 1),
        'total_seconds': round(time.perf_counter() - started, 3), 'unsupported_word_count': len(unsupported)}
    result = {'model': MODEL, 'model_revision': REVISION, 'device': 'cpu',
        'validation': 'Timing consistency only; listening review required before production.',
        'metrics': metrics, 'words': words, 'actions': action_times(data['actions'], transcript, words)}
    (folder / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    preview(folder, data, result)
    print(json.dumps({'metrics': metrics, 'action_times': [{'start': a['start'], 'end': a['end']} for a in result['actions']]}, indent=2), flush=True)
    print('Private result.json and preview.html created. No database writes.', flush=True)


if __name__ == '__main__':
    main()
