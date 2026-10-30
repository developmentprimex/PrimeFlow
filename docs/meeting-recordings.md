# PrimeFlow Screen & Audio Recorder

Phase A implements browser capture, bounded durable uploads, PostgreSQL history,
private server storage, validated media finalization, playback and download.
Phase B preparation is in `docs/px-desktop-recorder.md`; there is no desktop binary.
No meeting-platform APIs are involved. Validated recordings are also copied to
the configured FILES meetings folder by a restart-safe background archiver.

## User flow and permissions

Open **Regjistrimet**, enter a title and optionally select a PrimeFlow meeting.
Acknowledging the company recording notice enables the native browser picker.
The source dropdown expresses a preference; the browser makes the actual choice.
The page checks the returned audio tracks and starts recording automatically when
system audio is available after sharing is confirmed. When system audio is absent, it offers
cancel, source change, or explicit continuation without system audio. Denied
microphone permission releases the screen; retry with permission or “Pa mikrofon”.

The recorder combines the chosen video track and one Web Audio mix of the actual
microphone/system tracks. It never connects captured audio to speakers. Use
headphones and browser echo cancellation to reduce acoustic duplication.
Pause/resume excludes paused time from the displayed timer. Actual file duration,
dimensions and size come from the server's validated output. Source-specific
audio flags are browser declarations: encoded mixed audio cannot prove which
speaker/input contributed sound.

Every authenticated active user may list, view, play and download all undeleted
recordings, including recordings without a linked meeting, and read their analysis.
Only the creator may upload, complete, abandon or start analysis for a recording.
The creator and ADMIN/MANAGER may rename a recording using **Edito titullin** in
the history table, then **Ruaj** or **Anulo**. Titles must contain 1–200 characters;
the authenticated PATCH endpoint validates permissions and audits title changes.
Only ADMIN/MANAGER may delete it. Anonymous and deactivated users have no access;
authentication is checked on media requests. Deleted recordings remain inaccessible
to every role. Meeting creation/linking permissions are unchanged.

Client-side PrimeFlow navigation preserves capture in the authenticated layout,
with a persistent red indicator and stop control. Refresh/closing warns while
capture or saving is active. Browser shutdown cannot guarantee delivery of the
last fragment. Starting another tab is prevented by Web Locks. A session UUID is
stable for future transcripts, summaries and task suggestions; `meeting_id` is
nullable and existing meetings/calendar/task workflows remain unchanged.

## Storage and encoding configuration

| Backend variable | Default | Meaning |
| --- | --- | --- |
| `MEETING_RECORDINGS_ROOT` | `uploads/meeting-recordings` | Private local persistent root, relative to `backend/` unless absolute |
| `MEETING_RECORDINGS_FILES_ENABLED` | `true` | Copy READY videos to FILES automatically; disable on isolated development/test servers |
| `MEETING_RECORDINGS_FILES_FROM` | `2026-10-23T09:55:36+00:00` | Fixed activation boundary: export only recordings started at or after this instant; old recordings are excluded |
| `MEETING_RECORDINGS_FILES_SUBDIR` | `10_ZHVILLIM/04_PROJECTS/26_PRIMEFLOW/08_TAKIMET` | Meetings destination relative to `FILES_SERVER_STORAGE_ROOT` |
| `MEETING_RECORDINGS_FFMPEG` | `ffmpeg` | Executable name or absolute binary path |
| `MEETING_RECORDINGS_FFPROBE` | `ffprobe` | Executable name or absolute binary path |
| `MEETING_RECORDINGS_MAX_CHUNK_BYTES` | `33554432` | 32 MiB streamed request limit |
| `MEETING_RECORDINGS_MAX_SESSION_BYTES` | `21474836480` | 20 GiB per session, verified upload bytes |
| `MEETING_RECORDINGS_MAX_DURATION_SECONDS` | `43200` | Maximum validated 12-hour media duration |
| `MEETING_RECORDINGS_MAX_OPEN_SESSIONS` | `3` | Concurrent unfinished sessions per account |

Optional **frontend server** variable `MEETING_RECORDINGS_API_URL` overrides the
server-to-server API base, **including `/api`**, for media streaming. Otherwise it
uses the existing `NEXT_PUBLIC_API_BASE_URL` plus `/api`. Never configure a
user-controlled destination. The frontend requires a Node.js Next server for this
streaming route, consistent with this repository's PM2 hosting.

Install a maintained FFmpeg/ffprobe build on the application server before enabling
recording. Session creation returns 503 if either executable is unavailable.
No Python runtime dependency was added. WebM is preferred; actual MP4 capture is
kept as MP4. WebM is never renamed MP4 and no MP4 transcode service is included.

Storage structure: `<root>/YYYY/MM/<server-uuid>/recording.webm` (or `.mp4`),
`metadata.json`, `chunks/00000000.chunk`, and a private finalization lock file.
Database rows store only `storage_backend=local` and the logical directory key.
The `LocalMeetingStorage` boundary owns path resolution, bounded receipt,
hash-verifying assembly, remux, probe and atomic publication. A future network
provider must preserve that interface's integrity, durability and lock guarantees;
it is deliberately not implemented now.

### FILES meetings copy

The API starts a background archive/deletion sweep on startup and every 60
seconds after each sweep. It copies READY recordings started at or after the
fixed `MEETING_RECORDINGS_FILES_FROM` activation timestamp to
`<FILES_SERVER_STORAGE_ROOT>/<MEETING_RECORDINGS_FILES_SUBDIR>/REGJISTRIM <title>_DD.MM.YYYY.webm`
(or `.mp4`), directly without subfolders. An ID suffix is added only when another
recording already uses the same filename. Metadata and SHA-256 receipts stay in
private local storage. This corresponds to the user's
`Z:\10_ZHVILLIM\04_PROJECTS\26_PRIMEFLOW\08_TAKIMET`
share; the API uses the same server-side `FILES_SERVER_STORAGE_ROOT` as prompts
(default `F:\FILES`), without depending on a user's mapped Z: drive.
On workstations without `F:\FILES`, set `FILES_SERVER_STORAGE_ROOT=\\192.168.10.8\files`
in `backend/.env` and restart the API (or let the development reloader reload it).

The database can contain recordings created by a different API host. Export
requires the actual finalized video under `MEETING_RECORDINGS_ROOT`; a shared
database alone does not provide its bytes. Missing sources are left pending,
without creating empty session folders or repeatedly logging tracebacks. A
summary warning is emitted only when the missing set changes. Run the archiver
on the host holding the originals or configure the same accessible media root.
Likewise, a host without the session folder never marks its deletion as purged.
Historical recordings before activation are excluded from archive sweeps entirely,
including after restarts or deployments. Their files and DB rows are unchanged.

The service account needs write access to this folder. An unavailable root is
never created as a replacement share. Copies use bounded reads, fsync, SHA-256
read-back validation and atomic rename. A local `files-archive.json` receipt is
published last; failed or interrupted copies retry on later sweeps, including
after API restart. A local OS lock prevents concurrent workers copying the same
recording. Local playback files and chunks remain intact. FILES availability does
not affect READY status or playback, and this receipt is not currently exposed
in the UI. The share's own permissions govern access to its exported videos.

Admins and managers can delete READY/FAILED recordings using the history's
**Fshi** button and confirmation dialog. `DELETE /api/meeting-recordings/{id}`
checks the role on the server, audits the action and marks `deleted_at`. Deleted
rows disappear from history and all metadata, media and analysis routes return
404, including previously issued playback grants. Active sessions must be stopped
or abandoned first. New analysis/timing jobs exclude deleted recordings.

The same background loop removes the archived video and local media/chunks,
then records `files_purged_at`. A FILES outage retains the durable deletion queue
for retry while the recording stays inaccessible in PrimeFlow. The cleanup
checks receipt ownership, destination containment and the archived SHA-256 before
removing a file; modified external files require investigation and are not
silently deleted. DB row locks serialize export and deletion. The loop processes
deletions even when new exports are disabled. Audit records and the deleted DB
row remain. Apply migration `0161_recording_deletion` before running this code.

After deploying this code, restart the API to start the archiver. Verify the
configured FILES root is accessible to its service account and check the meetings
folder and API logs after completing a recording. Disable the archive setting
on isolated browser/API test servers to prevent exporting test media.

The PM2 account needs read/write/create/rename permissions on the root and execute
permission for FFmpeg/ffprobe. Restrict the root to that service account and backup
operators. Do not serve it through a public static directory, IIS virtual folder,
Next `public/` directory, CDN bucket or unauthenticated file service. All API
workers must use the same PostgreSQL database and same persistent local root.

The production root is `C:\PrimeFlowData\MeetingRecordings`, outside the Actions
checkout. Deployment writes that absolute `MEETING_RECORDINGS_ROOT` explicitly.
The active `PrimeFlow` checkout's original `backend/uploads/meeting-recordings`
path is also a server-side junction to that persistent root, so already-running
API processes using the former relative default keep working. Local development
against the shared production DB must use the same media root through an
authorized share, or an isolated DB/storage pair.

On 2026-10-23 the `TAK NOLTE` 503 was traced to recordings left in the previous
`Primex-TaskManager` checkout after the active checkout changed to `PrimeFlow`.
419 finalized files/metadata/chunks were copied to the persistent root and
SHA-256 verified without removing the originals. The active path was repaired
without a process restart. Only the requested `TAK NOLTE` historical video was
also exported to FILES as `REGJISTRIM TAK NOLTE_22.10.2026.webm`; the automatic
archive activation cutoff remains unchanged.

Metadata/list responses include `media_available` for READY recordings, based on
the actual file and expected size under the API's root. The UI labels an
unavailable file explicitly instead of presenting it as playable. This check
does not rewrite READY history or destroy a recording during a transient storage
outage; restoring access makes it available again. Playback uses the same check.

Use a persistent server-local data directory outside disposable checkouts for
release-directory deployments, e.g. `D:\PrimeFlowData\MeetingRecordings`. The
default works with this repository's in-place deployment, which only cleans
untracked migration files and does not clean ignored uploads. PM2 restarts do not
remove data. Avoid cleanup commands that remove ignored uploads.

**Changing the root requires moving/mounting the existing tree.** With writes
stopped during an approved maintenance window: back up DB and storage together,
copy every year/month/UUID subtree to the new root preserving relative paths,
verify file hashes/counts/permissions, configure the new root for every API
worker, restart only after approval, and verify old recording playback. Merely
changing the variable will make old recordings unavailable. Keep the old copy
until the migration/restore is verified. Do not alter every logical DB key.

## Upload protocol and recovery

MediaRecorder requests a 4-second timeslice; actual browser timing can be much
longer. Fragments belong to **one continuous MediaRecorder instance**, not to a
series of independently playable videos. They are persisted to IndexedDB before
upload and uploaded sequentially with SHA-256, index and byte-count receipts.
Same-index/same-content retry is idempotent; a conflicting digest or missing index
is rejected. PostgreSQL row locks coordinate all API workers. Request streaming
does not load a full upload in server memory; temporary writes are fsynced and
atomically renamed before the DB acknowledges persistence.

The uploader retries transient errors 5 times with exponential delays, then
requires the visible retry action. It holds one bounded fragment while uploading.
IndexedDB pending data is limited to 96 MiB, individual fragments to 32 MiB, and
the synchronous staging queue to 64 MiB. Capture pauses at 32 MiB of durable
backlog, 12 pending fragments, or 16 MiB of pending local writes. Resume is
explicit after drainage. Oversized browser fragments or local-disk failures stop
capture and prohibit completion; nothing is silently discarded as “saved”. These
limits bound retained application data; a browser may itself allocate a large
Blob when a laptop sleeps. Keep laptops awake for long meetings.

Completion requires a persisted stop marker and acknowledgement of every expected
fragment. The server re-hashes every stored chunk, reconstructs the single encoded
stream using bounded reads, and **remuxes with FFmpeg**, then validates video,
codec/container, duration and dimensions using ffprobe. The final file and metadata
are fsynced and atomically published before committing READY. Finalization holds a
DB row lock and an OS file lock, preventing remux races even after request
cancellation. A process crash rolls back the DB transaction; retry is safe.
The client never treats uploaded bytes or a failed complete response as “saved”.

On reload, the same logged-in user can retry stopped sessions from IndexedDB.
An interrupted capture without a stop marker requires explicit partial recovery;
the library permanently labels that result `is_partial=true`. A fatal local-write
failure cannot be marked complete. Partial recovery may still fail if the browser
never emitted a complete header or ended in an invalid media fragment.

If server completion succeeded but its response was lost, repeating complete
returns the existing READY result and clears the local outbox. If browser storage
was cleared, the history still shows the server session but missing local chunks
cannot be reconstructed automatically. Abandon that session; retained server
chunks can be examined through an authorized maintenance procedure. This MVP
does not silently guess that an interrupted session was complete.

No automatic retention/deletion is enabled. READY recordings currently retain
their verified chunks for recovery, so provision roughly **3×** the maximum
recording bytes for chunks, assembly and remux temporary output, plus backups.
Monitor free disk, unfinished sessions and finalization failures. Retention can
later use UUID/status/created_at without changing playback/storage contracts.
Do not delete retained customer recordings or chunks without an approved policy.

## Authenticated media and proxy configuration

Bearer authentication remains unchanged. A bearer-authenticated playback request
mints a recording-scoped 15-minute token. The frontend stores it in an HttpOnly,
SameSite=Strict cookie on that recording's same-origin proxy path; it renews while
the detail page is open. Tokens never appear in media URLs or recording metadata.
The proxy streams bytes and forwards single HTTP Range requests; it does not
buffer the full video in JS RAM. Anonymous users, inactive users, wrong scopes
and unauthorized accounts are rejected. Sensitive creation/finalization/playback/
download/abandon operations use the existing audit log. No media/token bodies are
logged by this module. Existing unrelated WebSocket logging is outside its scope.

The trusted reverse proxy must preserve the public `Host` and set/overwrite
`X-Forwarded-Proto` from the actual connection. Never trust a client's forwarded
protocol header. This enables strict same-origin cookie setup behind TLS
termination. Deploy over HTTPS; only localhost development can use HTTP. Media
responses are `private, no-store` with `nosniff`; never cache them publicly.

For nginx, adapt the existing virtual host (do not add a public storage alias):

```nginx
client_max_body_size 34m;
proxy_request_buffering off;
proxy_buffering off;
proxy_read_timeout 720s;
proxy_send_timeout 120s;
proxy_set_header Host $host;
proxy_set_header X-Forwarded-Proto $scheme;
```

For IIS/ARR, allow binary requests slightly above 32 MiB using
`requestFiltering/requestLimits/maxAllowedContentLength`, configure ARR timeouts
for completion and long media responses, and preserve Range/Host/protocol headers.
Ensure any CDN/WAF body/time limits permit these chunk requests. Completion can
take up to the 600-second remux and 60-second probe timeouts. Finalization is
inline in this MVP; client retry handles a lost HTTP response. Configure trusted
reverse-proxy per-IP concurrency/rate limits and disk monitoring for capacity.

## API and migration

All paths below have `/api/meeting-recordings` as their base:

| Method | Suffix | Behavior |
| --- | --- | --- |
| POST | empty | Explicit consent; create session, optionally link meeting |
| GET | empty | Authorized history, `offset`/`limit` pagination |
| GET | `/{id}` | Authorized metadata and creator/meeting labels |
| PUT | `/{id}/chunks/{index}` | Owner-only binary fragment, `X-Chunk-SHA256` |
| POST | `/{id}/complete` | Owner-only `{chunks, partial?}`; validate then READY |
| POST | `/{id}/fail` | Owner-only abandonment; never modifies READY media |
| POST | `/{id}/playback` | Authorized scoped playback token |
| GET/HEAD | `/{id}/stream` | Authorized media, single byte ranges |
| GET | `/{id}/download` | Authorized attachment, server-controlled filename |

Migration `0153_meeting_recordings` follows `0152_discord_voice_meetings` and
creates `meeting_recordings` and `meeting_recording_chunks`. Existing meeting IDs,
participants, recurrence and calendar rows are not rewritten. After backing up the
target DB and obtaining deployment approval, run from `backend/`:

```text
python -m alembic heads
python -m alembic current
python -m alembic upgrade head
```

The new migration was upgraded, downgraded and reapplied on an isolated local
PostgreSQL 16 database with model prerequisites. The full historical migration
chain was not reapplied to an empty production-like DB. Downgrade drops recording
metadata/receipts, so back up first and never downgrade a populated feature as an
automatic rollback. Reverting frontend code leaves stored media intact.

## Verification and known platform limits

Automated browser coverage uses Windows Chromium through Playwright with a test
capture device. It invokes the actual getDisplayMedia API, MediaRecorder, mixer,
IndexedDB, frontend pages, real API, PostgreSQL and FFmpeg; app-shell data unrelated
to recording are stubbed. It verifies pause/resume, save confirmation, reload,
playback metadata, Range, download, cookie origin checks and upload retry.
Synthetic canvas + 440/880 Hz inputs verify both sources survive real encoding;
decoded output was checked for both tones. **This does not verify Teams, Discord,
YouTube, a real Windows WASAPI loopback device or macOS system audio.**

Controller tests cover screen/microphone denial, missing system audio, native
sharing stop (including during microphone setup), toggles, cleanup, duplicate
start/stop guards, failed uploads, 1,500 sequential fragments, and non-READY
completion. API tests cover idempotency/order/hash conflicts, incomplete media,
upload bounds, auth/read/write scopes, linked/unlinked sessions and persisted
playback. A separate opt-in test terminates/restarts actual API processes between
chunks and again after READY, then reads a byte range successfully.

Chrome/Edge with HTTPS and Web Locks are the initial target. Tab capture with a
share-audio option is generally the most practical browser audio path; actual
availability depends on browser, source, OS and user selection. Firefox/Safari
and real Windows/macOS source/audio combinations require acceptance testing;
codec detection alone is not evidence of universal capture. DRM/protected media,
OS privacy settings, sleeping machines, suspended tabs and denied permissions may
prevent recording. Multi-hour soak tests and native-device acceptance remain.
See [MDN getDisplayMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getDisplayMedia)
and [MediaRecorder dataavailable](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/dataavailable_event).

## Reproduce tests and approved deployment checklist

Use an isolated PostgreSQL instance bound to localhost, database named exactly
`primeflow_recorder_test`. Tests explicitly reject other hosts/database names and
never fall back to the configured customer DB. Set `RECORDINGS_TEST_DATABASE_URL`
to its sync PostgreSQL URL, and point the encoding variables at installed binaries.
Use the existing backend virtualenv. Run integration and process tests separately
because they recreate only the isolated fixture schema:

```text
cd backend
python -m unittest discover -s tests -p test_meeting_recording_storage.py
python -m unittest discover -s tests -p test_meeting_recordings_api.py
# Set RECORDINGS_TEST_PROCESS_RESTART=true for this test:
python -m unittest discover -s tests -p test_meeting_recording_restart.py
python tests/serve_recordings_test.py --prepare
cd ../frontend
npm ci
npx playwright install chromium
npm run test:recordings
npm run typecheck:recordings
npm run test:recordings:browser
cd ../backend
python tests/verify_recording_audio.py ../frontend/test-results/two-audio-inputs.webm
```

Browser tests use localhost ports 3100/8012. An optional
`RECORDINGS_CHROMIUM_EXECUTABLE` selects an installed compatible Chromium binary.
The process test starts/stops only its own test API. Capture-device tests do not
change OS permissions or install audio drivers.

For an approved rollout: provision private persistent local storage, install and
verify FFmpeg/ffprobe, set backend/frontend/proxy variables consistently, back up
DB+storage, apply migration, build frontend, restart the existing PM2 API/frontend
processes only with approval, then run a consented browser acceptance recording
and verify playback after a controlled restart. Existing in-place PM2 cwd supports
the default root; no extra worker or scheduler is required.

Inspection found an embedded default credential in `backend/app/config.py` for an
existing file-access integration. It was not copied into this feature or changed;
rotate it and move it exclusively to protected environment configuration through
the integration's authorized remediation process. Its value is intentionally
omitted here.
