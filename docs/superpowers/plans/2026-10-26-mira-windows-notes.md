# Mira Windows call notes implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Windows Start/Finish companion producing Mira-style notes for any locally audible call.
**Architecture:** Separate Windows capture client and owner-authenticated backend sessions.
Encrypted durable client queue, idempotent server segments and note finalization.
**Tech stack:** Python 3.12+, Tkinter, PyAudioWPatch, NumPy/SciPy, httpx, DPAPI;
existing FastAPI/PostgreSQL and Mira OpenAI helpers.
**Spec:** docs/superpowers/specs/2026-10-26-mira-windows-notes.md

## Global constraints

- Existing Discord Mira remains untouched by this feature.
- No speaker identification; manual visible recording only; Windows first.
- No tokens/passwords on disk. HTTPS except explicit localhost development.
- 10 s chunks, 512 MiB backlog, 4 h session; DPAPI protects local pending data.

## Review focus

- Callback faults, device removal, clock drift and changing devices must not silently lose audio.
- Wrong-account recovery and URL redirects must not expose data or credentials.
- Lost finish responses must not create duplicate PX Notes.
- Missing segments/offline storage failures must stay recoverable and visible.
- Silence and the final short chunk must not invent speech or disappear.

## Task 1: Dedicated backend (independent files)

- [x] Test session owner scope, duplicate segment/hash conflicts, bounded WAV,
  ordered finalization, missing chunks, note idempotency and no-speaker prompts.
- [x] Add dedicated models/migration, schemas, service and router under mira_desktop.
  API: POST /mira-desktop/sessions with client UUID/title/consent; POST
  /sessions/{id}/segments/{sequence}?start_ms=&end_ms= with WAV bytes; POST
  /sessions/{id}/finish with segment_count/partial; GET /sessions/{id}.
  GET /mira-desktop/capabilities supports preflight and account scope.
- [x] Use normal get_current_user and existing build_ga_note permissions.
  Validate all chunks before finalization. Persist lease and cached summaries;
  finished retries return same note; expose retryable status on busy finalization.
- [x] Run meaningful unit and disposable PostgreSQL integration tests.

## Task 2: Windows companion (main implementer)

- [x] Test PCM mixing/resampling, monotonic timestamps, bounded queues,
  encrypted persistence/recovery, credential/URL handling and upload replay.
- [x] Implement capture, storage, API client/coordinator and Tkinter UI in
  desktop/mira_windows; add requirements, launcher and packaging script.
- [x] Authenticate before start; source selection/levels, acknowledgement,
  visible Start/Finish; stop on faults; background uploads with retry;
  recover stopped sessions without recording again, view/copy final notes.
- [x] Install isolated dependencies, verify local tests and package Windows EXE.

## Task 3: Verify and hand over

- [x] Independent review, correct findings and rerun affected tests.
- [x] Document setup, API migration/deployment, source selection, headset usage,
  privacy, recovery, and the real-call acceptance steps still needing the user.
- [x] Deliver executable/source and test evidence; do not claim live-call or
  production verification without running it. Production activation remains
  subject to the existing remote administrative execution approval block.
