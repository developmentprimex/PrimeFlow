# Albanian recording timing pilot

This is an isolated, read-only experiment. It does not enable timestamps in the
recording API, change task source references, or modify saved transcripts/tasks.
It uses the saved `gpt-transcribe` text and local audio to estimate word times.
`gpt-6-luna` remains unrelated to the timing computation.

## Method

- CPU acoustic model: `Alimzhan/wav2vec2-large-xls-r-300m-albanian-colab`.
- Model revision: `3f69142` (resolved commit is recorded in the HF cache).
- Load safetensors only, with remote code disabled and no Hugging Face token.
- Wav2Vec2 emissions plus CTC forced alignment (the same class of method used
  for WhisperX alignment), rather than retranscribing the recording.
- Evidence must match one unambiguous span of the saved transcript. Missing,
  repeated, or unaligned quotes receive no claimed timestamp.
- Punctuation is excluded from acoustic targets. Albanian diacritics remain.
  Digits are spelled out only in the acoustic target; original text is preserved.
- Prepending two seconds of silence provides an automatic consistency check.
  It is **not** a substitute for listening against the original speech.

The Albanian model card describes training on Common Voice Albanian, but has
limited documented evaluation. Names, abbreviations, mixed languages, overlapping
speech, and transcript errors require special review before production use.

## Isolated setup (Windows)

From the repository root:

```powershell
.\backend\.venv\Scripts\python.exe -m venv tmp/recording-alignment-pilot/.venv
.\tmp\recording-alignment-pilot\.venv\Scripts\python.exe -m pip install torch==2.8.0+cpu torchaudio==2.8.0+cpu --index-url https://download.pytorch.org/whl/cpu
.\tmp\recording-alignment-pilot\.venv\Scripts\python.exe -m pip install transformers==4.57.1 numpy==1.26.4 psutil
```

The application venv and requirements remain unchanged. TorchAudio 2.8 is
intentionally pinned for this experiment: its `forced_align` API is deprecated
and removed in 2.9. A production integration should use a maintained alignment
implementation rather than silently upgrading this pilot environment.

Export a saved recording of at most 60 seconds using the application environment
from `backend/`:

```powershell
.\.venv\Scripts\python.exe scripts/export_recording_alignment_pilot.py --recording-id <recording-uuid>
```

Run the experiment from the repository root:

```powershell
.\tmp\recording-alignment-pilot\.venv\Scripts\python.exe backend/scripts/recording_alignment_pilot.py --input backend/private-data/alignment-pilot/<recording-uuid>/input.json --threads 4
```

Add `--local-only` for subsequent offline runs using the downloaded model.
The first run downloads approximately 1.3 GB of model weights. No audio or text
is uploaded, and there are no OpenAI API requests from the pilot.

## Private outputs and review

All artifacts and model weights are under ignored `backend/private-data/`:

- `input.json`: saved transcript and proposal evidence; private.
- `audio.wav`: the extracted recording audio; private.
- `result.json`: word timings, evidence timings, acoustic scores, and metrics.
- `preview.html`: self-contained local audio player with clickable words and
  proposal time ranges. Contains the audio and transcript; do not publish it.

Metrics separate initial model load/download from alignment, include process
peak memory, and record the artificial two-second shift consistency test.
Acoustic scores are diagnostics, not calibrated probabilities of correctness.
Every pilot action is explicitly marked as requiring listening review.

Before integration, review timings in the HTML against actual speech, test longer
and mixed-language meetings, and benchmark the deployment server itself. A local
laptop benchmark cannot determine production capacity or monthly server cost.

For future recordings, the intended integration would extract audio automatically
after recording finalization, align the saved transcript in a bounded worker,
store word/citation ranges with model provenance, and seek the video when a
timestamp is clicked. Old recordings would require an explicit backfill that
preserves existing transcript/task data. None of that is enabled by this pilot.

References: [model](https://huggingface.co/Alimzhan/wav2vec2-large-xls-r-300m-albanian-colab),
[WhisperX](https://github.com/m-bain/whisperX),
[TorchAudio alignment API](https://docs.pytorch.org/audio/2.8/generated/torchaudio.functional.forced_align.html).

## First local result (2026-10-21)

Measured on an AMD Ryzen 7 7735HS laptop with about 14 GB usable RAM, using
four CPU threads. This is not a deployment-server benchmark.

| Measurement | Result |
| --- | ---: |
| Saved audio duration | 23.40 s |
| Initial model download/load | 138.75 s |
| Acoustic inference + alignment | 10.786 s |
| Additional artificial-shift consistency check | 8.565 s |
| Median shift error against the known +2 s offset | 0.001 s |
| Maximum shift error against the known +2 s offset | 0.141 s |
| Peak process working set | 2712.3 MiB |
| Evidence quotes given a measured range | 4 / 4 |
| OpenAI API calls | 0 |

These consistency numbers **do not measure error against human-annotated speech
boundaries**. Every result still requires listening review. The sample includes
names and abbreviations; acoustic scores were roughly 0.35–0.45 and must not be
presented as calibrated confidence probabilities. The private HTML preview
allows review by seeking to each word or quote. No production timing feature
or backfill was enabled.
