# Screen & Audio Recorder Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task.

**Goal:** Authenticated browser recording, bounded durable chunk uploads, private persistent playback and download in PrimeFlow.

**Architecture:** A browser capture controller mixes only actual audio tracks into one MediaRecorder stream. IndexedDB stores a bounded upload queue; sequential hash-verified requests feed recording sessions. PostgreSQL locks serialize mutations; local storage assembles a continuous MediaRecorder byte stream and FFmpeg remuxes it before ffprobe validates server-derived metadata. Next.js streams authorized playback through a same-origin proxy using a short-lived recording-scoped HttpOnly cookie.

**Tech Stack:** Existing Next.js/React/TypeScript, FastAPI/SQLAlchemy/PostgreSQL/Alembic; FFmpeg and ffprobe; Playwright for browser verification.

**Spec:** User implementation prompt, 2026-10-20. Phase A is the implementation scope; Phase B is a separate preparation commit.

## Global Constraints

- Feature branch only; no merge, production deployment, restart or customer data mutation.
- Albanian interface, existing authentication/design/audit conventions.
- Local `backend/uploads/meeting-recordings` default, configurable `MEETING_RECORDINGS_ROOT`, logical keys only in DB.
- Require explicit consent and native picker. Never claim system audio exists without actual live tracks.
- Never mark READY before verified media and durable storage. No third-party meeting APIs.

## Review Focus

- Acknowledgement lost after persistence: retries verify the same index/hash and do not duplicate bytes.
- Browser refresh before stop: preserve queued data; distinguish interrupted partial capture from a clean stopped session.
- Native share stop during asynchronous setup: release all devices and do not create an orphan live recorder.
- Full local queue or disk: pause and require recovery; never silently discard chunks and claim success.
- Media playback auth: range requests remain private without tokens in URLs or loading whole videos into browser RAM.

### Task 1: Persistence and upload protocol

Files: `backend/app/models/meeting_recording.py`, `backend/app/schemas/meeting_recording.py`, `backend/app/services/meeting_recording_storage.py`, `backend/app/api/routers/meeting_recordings.py`, migration `0153_meeting_recordings`, configuration and router/model registration. The revision follows the Discord voice-meeting migration introduced on main during implementation.

- [x] Write and run failing storage/API tests for traversal, streaming size limits, sequential/idempotent receipts, missing chunks, authorization and range playback.
- [x] Implement local storage, two new tables, owner writes and scoped reads, audit, validated remux/finalization and restart-safe retries.
- [x] Apply/rollback/reapply migration in isolated PostgreSQL test database and run backend tests.

### Task 2: Browser capture and library

Files: `frontend/src/lib/recording-*`, `frontend/src/components/meeting-recordings/*`, authenticated recording pages, same-origin media routes, sidebar and meeting detail link.

- [x] Write and run controller/queue tests covering denied permissions, missing system audio, native stop, pause/resume, backpressure, retries and cleanup.
- [x] Implement capture controller, bounded IndexedDB outbox, explicit recovery, Albanian recorder/library/detail and private streaming proxy.
- [x] Verify actual Chromium MediaRecorder output end to end; separate synthetic audio verification from unverified Teams/OS capture claims.

### Task 3: Release verification and documentation

- [x] Run backend regression tests, frontend unit/browser tests, lint, typecheck and production build; fix feature regressions.
- [x] Document storage/migration/permissions/proxy/encoding/backup/recovery/platform limits and verified scenarios, plus exact changed files.
- [x] Commit Phase A, prepare Phase B in a separate commit, review branch, push and create reviewable PR without merging/deploying: [draft PR #183](https://github.com/elsaferati/Primex-TaskManager/pull/183).
