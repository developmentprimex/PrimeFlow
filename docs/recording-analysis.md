# Transcription, summary and reviewed Tasks

Recording details now offer **Transkripto dhe përmblidh**. The recording owner
selects the conversation language (Albanian, English, German or automatic),
acknowledges external processing and starts a durable job. The original video
stays READY even if AI processing fails. Existing meeting participants and
authorized management roles can read results under the recording's existing
RBAC; only the owner starts processing or confirms tasks.

## Configuration and operation

Apply `alembic upgrade head` from `backend/` to add
`0154_recording_analysis` after `0153_meeting_recordings`. Back up PostgreSQL
and the persistent recording directory before deploying; this migration adds
tables and does not rewrite existing meetings or videos.

Set these in the backend environment, never in frontend environment variables:

```
OPENAI_API_KEY=<configure privately>
RECORDING_ANALYSIS_ENABLED=true
RECORDING_ANALYSIS_MODEL=gpt-6-luna
SPEECH_ALBANIAN_TRANSCRIBE_MODEL=gpt-4o-transcribe
SPEECH_TRANSCRIBE_MODEL=whisper-1
```

FFmpeg is required as already configured for the recorder. The worker must
have read permission on the same `MEETING_RECORDINGS_ROOT` as the API and
write permission to its OS temporary directory. Keep the root persistent.
No new Python/npm dependency is required.

Summary generation and task proposals use `gpt-6-luna` by default. The model
can be overridden with `RECORDING_ANALYSIS_MODEL`; transcription continues to
use the separate speech settings above. Luna supports the existing Responses
API and Structured Outputs contract:
[OpenAI GPT-6 Luna model documentation](https://developers.openai.com/api/docs/models/gpt-6-luna).

Luna follow-up verification on 2026-10-20: the configured local key successfully
completed real Responses API calls for schema-validated proposals and the
existing meeting summarizer using `gpt-6-luna`. The input was invented Albanian
test text; no saved recording audio or transcripts were read or sent. The five
recording provider tests and four existing Discord provider tests also passed.

Production uses existing Celery workers and beat: the new
`app.celery_tasks.process_recording_analyses` task is scheduled every five
seconds. Restart the API, workers and beat on approved deployment after the
migration. Do not run a second beat process. Existing PM2 apps need no changes.
The same queue can be processed locally without Redis:

```
cd backend
python -m app.jobs.recording_analysis
```

Run the worker with the same database, storage and provider settings as the
API. For PM2 installations without Celery, a separately supervised process
may run that command from `backend/`; never run it against a different root.
The API commits the job before returning 202, so a worker restart cannot lose
queued work. API restarts alone do not interrupt a separate worker.

## Processing and recovery

The worker claims one job with a PostgreSQL `FOR UPDATE SKIP LOCKED` lease.
It extracts at most 300 seconds of mono 16 kHz PCM WAV (under 10 MB) into an
OS temporary directory and sends only that audio to transcription. It never
sends the multi-hour video to a small-file transcription endpoint. Temporary
audio is deleted after each extraction; remove stale `primeflow-audio-*`
temporary directories after an OS crash when no worker owns them.

Transcripts and extracted notes checkpoint independently for each segment.
The next tick continues the next missing step. A terminated worker's lease
expires after ten minutes; a new worker resumes. A provider failure marks the
analysis FAILED with a safe message and retains completed text. **Riprovo
përpunimin** reuses those checkpoints and the original language. It does not
reprocess completed transcripts. Summary map/reduce and cache reuse the
existing Discord/Mira summarizer, with the recording model passed explicitly
so Discord's default behavior is unchanged. One final analysis is kept per
recording; there is no destructive regenerate endpoint.

Task proposals are structured, size-validated and require a verbatim quote
from the source transcript. They cannot execute tools or create Tasks.
The owner edits the title/description, chooses a department and optionally
an active assignee and date, then clicks **Konfirmo dhe krijo detyrën**.
This calls the existing Tasks creation flow, including its permissions,
business rules, assignment notifications and audit. An internal callback
stores the proposal/task link in the same commit. A repeated request or lost
response returns the same task ID. Deleting a confirmed task does not permit
the proposal to silently recreate it. Project association can be edited later
using existing Tasks controls.

The task receives only a generated source reference after the reviewed
description. Evidence quotes remain in the recording analysis. This prevents
an `@username` inside an automatically appended quote from notifying someone
the reviewer did not select. Mentions deliberately left in the reviewed title
or description retain existing Tasks behavior.

## API

- `GET /api/meeting-recordings/{id}/analysis`: configuration status, durable
  progress, timestamped transcript, summary and proposals under recording RBAC.
- `POST /api/meeting-recordings/{id}/analysis`: owner only; requires
  `consent_acknowledged: true` and `language: sq|en|de|auto`. Idempotent while
  queued/running/ready; resumes FAILED jobs.
- `POST /api/meeting-recordings/{id}/actions/{action_id}/task`: owner only;
  confirmed title, description, department, optional active assignee and aware
  ISO date. Returns `task_id` and `duplicate`.

No public static transcript endpoint. Do not log provider bodies or audio,
transcripts, keys, tokens or user storage paths. Backups must include the new
three PostgreSQL tables along with existing recording metadata. Disabling
AI processing does not remove existing results. Retention/deletion should
include those tables when a future approved policy is implemented.

## Limits and evidence

The summary is Albanian. Transcript language follows the selected source
language. Timestamps identify five-minute segments, not individual words.
Speaker diarization is not implemented; the mixed track cannot identify a
particular Teams/Discord participant reliably. Splits may cut sentences.
AI may omit or misinterpret speech, names and actions; review all results.
An empty transcript is reported as a failure, not as a fabricated summary.
An all-silent PCM segment skips the provider.

The provider accepts files up to 25 MB; our extracted parts are smaller:
[OpenAI transcription guide](https://developers.openai.com/api/docs/guides/speech-to-text).
Suggestions use validated JSON schema:
[OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
`store: false` is used for Responses calls; company policy must still account
for the provider's applicable data processing/retention terms.

Automated PostgreSQL tests exercise actual migration upgrade/downgrade,
FFmpeg extraction, recording permissions, consent/configuration rejection,
provider interruption/resume and real existing Tasks creation/idempotency.
Provider responses are mocked in automated tests. They establish application
behavior, not real Albanian transcription accuracy or external model access.
Real provider validation requires a privately configured key and an explicit
processing action. No real user audio is sent by the tests.

### Verification on 2026-10-20

- 5 provider/validation tests passed.
- 3 actual PostgreSQL/API/FFmpeg/Tasks tests passed, including migration
  upgrade/downgrade, consent/RBAC, persisted transcript retry, expired worker
  leases, empty-speech failure, idempotent creation and quote-mention isolation.
- 2 Chromium UI tests passed with mocked AI API responses: consent and
  configuration guards, progress, transcript/summary, reviewed creation,
  persistence across reload. These do not claim real provider accuracy.
- 47 existing frontend recorder/speech/voice tests passed; 5 existing recorder
  API tests, 4 existing Discord provider tests and 6 migration-graph tests passed.
- Scoped strict TypeScript and ESLint passed. Next.js production build passed
  (global type checking is disabled by the application's existing build config;
  the separate scoped type check was run explicitly).
- A broader Tasks run executed 63 tests with 4 failures/1 error. The same
  failures/error reproduce in the untouched current-main baseline: PCM title
  classification cases and a one-hour-marker mock missing an attribute.
- Real local login, previously saved video playback and the new panel passed
  with zero browser runtime errors. Both existing local recordings survived
  the additive migration and local API/frontend restart. The provider key was
  not yet configured, so no user audio was sent externally.
- Independent read-only code review found the quote-mention issue; its failing
  regression test reproduced the unintended notification before the fix.

Changed files for this follow-up are the new migration, model, provider,
worker, router, two backend test modules, analysis UI component, browser spec,
Playwright config and this guide; registration/configuration changes are in
backend model/router registries, `.env.example`, `config.py`, `celery_app.py`,
`celery_tasks.py`, the existing summarizer's optional model parameter, the
internal Tasks transaction hook, isolated recording test fixtures,
`frontend/package.json` and the recording detail page. The implementation
sequence is recorded in
`docs/superpowers/plans/2026-10-20-recording-analysis.md`.

Exact follow-up files:

```
backend/.env.example
backend/alembic/versions/0154_recording_analysis.py
backend/app/api/routers/__init__.py
backend/app/api/routers/recording_analysis.py
backend/app/api/routers/tasks.py
backend/app/celery_app.py
backend/app/celery_tasks.py
backend/app/config.py
backend/app/jobs/recording_analysis.py
backend/app/models/__init__.py
backend/app/models/recording_analysis.py
backend/app/services/discord_voice_openai.py
backend/app/services/recording_analysis_provider.py
backend/tests/recording_test_support.py
backend/tests/serve_recordings_test.py
backend/tests/test_recording_analysis_api.py
backend/tests/test_recording_analysis_provider.py
docs/recording-analysis.md
docs/superpowers/plans/2026-10-20-recording-analysis.md
frontend/package.json
frontend/playwright.analysis.config.ts
frontend/src/app/(app)/meeting-recordings/[id]/page.tsx
frontend/src/components/meeting-recordings/analysis-panel.tsx
frontend/tests/browser/recording-analysis.spec.ts
```

## Quality changes (2026-10-20)

- Transcription uses `RECORDING_TRANSCRIBE_MODEL` (default `gpt-transcribe`) for every
  language, sends the language code (`RECORDING_TRANSCRIBE_LANGUAGE_HINT`), and adds a
  vocabulary of active staff (meeting participants first), departments and
  `RECORDING_TRANSCRIPTION_VOCABULARY` plus the end of the previous segment to the prompt.
- Segments start 2 s early so boundary words are heard whole; audio is filtered
  (`highpass`, `lowpass`, `dynaudnorm`). Segments with less than 1 s of audible speech are
  not sent, and known noise hallucinations ("Faleminderit që shikuat", subtitle credits) are removed.
- Summary, decisions and task proposals come from one analysis of the whole meeting
  (reduced in parts for long meetings, checkpointed in `summary_progress`) with the
  meeting date and participants, in the GA notes structure. Tasks are no longer
  extracted per 5-minute segment.
- A proposal whose evidence cannot be found in the transcript (ignoring punctuation and
  diacritics) is dropped instead of failing the analysis; near-duplicates are merged.
- Spoken assignees are matched to a single active user and relative deadlines are
  resolved to a date; both prefill the review form.
- Provider calls retry in-process, and transient job failures back off and retry up to
  three times before `FAILED`. Migration `0155_recording_analysis_quality` adds the
  columns for decisions, attempts and suggestions.
