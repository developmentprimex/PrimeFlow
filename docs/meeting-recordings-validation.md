# Screen & Audio Recorder implementation and verification

Branch: `feat/screen-audio-recorder`. Draft PR for review; no production deployment,
service restart, merge into main or customer database/data modification was made.
[Draft PR #183](https://github.com/elsaferati/Primex-TaskManager/pull/183).
Current main's Discord voice work was integrated into this feature branch, with
the recorder migration changed to `0153_meeting_recordings` after
`0152_discord_voice_meetings`. The migration graph has one head.

## Implemented

- Albanian authenticated recorder, meeting association/link, consent notice,
  native picker, actual audio-track availability, explicit no-system-audio choice,
  one mixed audio stream, codec selection, pause/resume/stop, independent audio
  toggles, timer, global indicator and navigation-safe capture ownership.
- Bounded synchronous staging and IndexedDB outbox, sequential SHA-256-verified
  fragments, exponential retries, backpressure pause, recovery, permanent partial
  labeling, server-confirmed completion and persisted authorized history.
- Owner-only mutation and existing management/meeting read permissions on every
  endpoint; private Range streaming/download, recording-scoped short-lived playback
  authorization via a same-origin HttpOnly cookie and existing audit logging.
- Configurable private local storage, PostgreSQL chunk receipts/row locking,
  cancellation-safe OS finalization lock, chunk rehashing, FFmpeg remux, ffprobe
  metadata, atomic publication and restart-safe persistence. No external storage.

## Verification results

| Check | Result |
| --- | --- |
| Frontend regression tests (`node --test tests/*.test.mjs test/*.test.mjs`) | **203 passed**, including 13 recorder/controller tests |
| Playwright recorder integration | **5 passed** on Windows Chromium with test capture device |
| Encoded mixed-audio verification | Decoded 440 Hz and 880 Hz sources both present, amplitude about 0.706 |
| Real PostgreSQL/API/FFmpeg integration | **5 passed** |
| Local storage/integrity/OS-lock tests | **5 passed** |
| Actual API process restart during upload and again after READY | **1 passed**; duplicate retry and subsequent Range playback verified |
| Alembic graph tests | **6 passed**, one migration head |
| Existing Discord assistant tests after integration | **38 passed** |
| New migration | Upgraded, downgraded and reapplied using Alembic on isolated PostgreSQL 16 prerequisites |
| Recorder lint (including test/config files) and scoped strict TypeScript | Passed |
| Next.js production build | Passed, including recording pages and streaming route |
| Full frontend TypeScript | Not globally clean: 100 errors remain outside recorder sources |
| Full frontend lint | Not globally clean: existing errors/warnings remain outside recorder code; feature files checked separately after fixing their test lint error |
| Full backend suite on feature branch | 1,094 tests; 18 failures, 10 errors, 63 skipped |
| Full backend suite on untouched current-main archive, same test environment/dependencies | 1,083 tests; **same 18 failures and 10 errors**, 57 skipped |

The full-suite comparison found no additional recorder-caused backend failure.
The existing failures involve report contracts/workflows, task mocks and
classification, plus Discord test import/environment issues. They were not
silently declared passing or fixed by changing unrelated business behavior.
The Next.js configuration already skips global type validation at build time;
the separate strict recorder check is therefore required and passed.

The browser suite exercises actual MediaRecorder/Web Audio/IndexedDB/HTTP/database/
encoder code. Unrelated app-shell data are stubbed. It verifies the native capture
API using a Chromium test device, pause/resume, server-confirmed save, reload,
video metadata, Range, download, cookie-origin restrictions, transient chunk
retry, durable outbox limits and cross-tab capture/recovery exclusion. Audio
sources in the two-input encoding test are synthetic, and independently decoded.

## Remaining acceptance and limitations

- **Real Teams/Discord/Meet/YouTube system audio, real Windows WASAPI loopback,
  and macOS capture have not been verified.** Native-device and OS/browser
  acceptance tests and a multi-hour soak test remain before production sign-off.
- Browser refresh cannot guarantee the final fragment. Available locally durable
  data may be explicitly recovered as a labeled partial recording. Cleared browser
  storage cannot recreate missing local chunks.
- Inline finalization can exceed a short proxy timeout; configure the documented
  limits and use idempotent retry. Chunks are retained; no automated retention or
  deletion policy is enabled. Provision temporary/remux/backup disk capacity.
- Phase B is a separate preparation commit only; no desktop application or local
  control port is shipped. Independent agent review was attempted but could not
  run because that tool's authentication failed. Author self-review and automated
  verification are recorded; the draft PR still needs human review.
- An existing embedded file-access credential was flagged for rotation without
  copying its value or changing that integration.

## Decisions made during implementation

- Preserve existing broad ADMIN/MANAGER meeting RBAC; restrict other reads to
  creator/linked-meeting authorization and all writes to the recorder's creator.
- Use a same-origin streaming proxy instead of media tokens in URLs or whole-file
  browser Blob downloads. Keep existing bearer authentication unchanged.
- Remux one continuous encoded stream; do not assume individual timeslices are
  independently playable. Require both FFmpeg and ffprobe at session creation.
- Keep finalization inline for this MVP, protected across API workers and thread
  cancellation. A supervised asynchronous finalizer can follow if load warrants it.
- Fix the shared date-input bound type, required by strict checking of the reused
  Input component. Preserve its string-date behavior; numeric date bounds remain
  ignored. Update the Discord migration test to permit later single-head revisions.

No minor review findings were deliberately deferred; the platform acceptance and
existing global-check failures above remain explicit release limitations.

## API, rollout and Phase B

Base API: `/api/meeting-recordings`. POST/GET base, GET `/{id}`, PUT
`/{id}/chunks/{index}`, POST `/{id}/complete`, POST `/{id}/fail`, POST
`/{id}/playback`, GET/HEAD `/{id}/stream`, GET `/{id}/download`.

After approval only: provision persistent private server-local storage and
FFmpeg/ffprobe, configure `MEETING_RECORDINGS_ROOT` and proxy/body/time limits,
back up DB/storage, run `python -m alembic upgrade head`, build the frontend,
restart the existing API/frontend PM2 processes, then perform consented native
capture and controlled restart acceptance checks. No FILES server configuration
is included. Exact settings, ACLs, migration/mount procedure, recovery, backups
and rollout details: [implementation guide](meeting-recordings.md).

Next desktop work: evaluate/pin Electron, implement separate Windows WASAPI and
macOS ScreenCaptureKit/Core Audio adapters, protected device authentication,
durable local disk recovery and real OS acceptance. Review any native-messaging
or localhost pairing/control protocol separately. See
[Phase B preparation](px-desktop-recorder.md).

## Exact created or modified files relative to current main

- `.gitignore`
- `backend/.env.example`
- `backend/alembic/versions/0153_meeting_recordings.py`
- `backend/app/api/routers/__init__.py`
- `backend/app/api/routers/meeting_recordings.py`
- `backend/app/config.py`
- `backend/app/models/__init__.py`
- `backend/app/models/meeting_recording.py`
- `backend/app/schemas/meeting_recording.py`
- `backend/app/services/meeting_recording_storage.py`
- `backend/tests/recording_test_support.py`
- `backend/tests/serve_recordings_test.py`
- `backend/tests/test_discord_assistant.py`
- `backend/tests/test_meeting_recording_restart.py`
- `backend/tests/test_meeting_recording_storage.py`
- `backend/tests/test_meeting_recordings_api.py`
- `backend/tests/verify_recording_audio.py`
- `docs/meeting-recordings-validation.md`
- `docs/meeting-recordings.md`
- `docs/px-desktop-recorder.md`
- `docs/superpowers/plans/2026-10-20-screen-audio-recorder.md`
- `frontend/eslint.config.mjs`
- `frontend/package-lock.json`
- `frontend/package.json`
- `frontend/playwright.recordings.config.ts`
- `frontend/src/app/(app)/layout.tsx`
- `frontend/src/app/(app)/meeting-recordings/[id]/page.tsx`
- `frontend/src/app/(app)/meeting-recordings/page.tsx`
- `frontend/src/app/api/meeting-recordings/[id]/[action]/route.ts`
- `frontend/src/components/meeting-details-dialog.tsx`
- `frontend/src/components/meeting-recordings/recorder-panel.tsx`
- `frontend/src/components/meeting-recordings/recorder-provider.tsx`
- `frontend/src/components/sidebar.tsx`
- `frontend/src/components/ui/date-input.tsx`
- `frontend/src/lib/recording-capture.ts`
- `frontend/src/lib/recording-outbox.ts`
- `frontend/src/lib/recording-types.ts`
- `frontend/tests/browser/recordings.spec.ts`
- `frontend/tests/recording.test.mjs`
- `frontend/tsconfig.json`
- `frontend/tsconfig.recordings.check.json`
