# Mira Silent Discord Meeting Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mira joins the existing staff voice channel, listens without speaking, and produces reviewed meeting notes that can be saved once to PX Notes.

**Architecture:** The existing Python Discord bot owns the Gateway and commands. A local Node child receives/decrypts audio using a custom `@discordjs/voice` adapter. Authenticated FastAPI endpoints persist session/transcript state; a durable Celery job prepares notes and the existing bot delivers them privately.

**Tech Stack:** Python/FastAPI, discord.py, PostgreSQL/SQLAlchemy/Alembic, Celery, Node >=22.12, `@discordjs/voice@0.19.2`, Opus decoder, existing OpenAI transcription and text API configuration.

**Spec:** [Approved design](../specs/2026-10-20-mira-discord-meeting-notes-design.md).

## Global Constraints

- `selfMute=true`, `selfDeaf=false`; no generated speech, player, or outbound media path.
- Use the existing bot identity, `OPENAI_API_KEY`, account linking and bridge authentication. Do not start a second Discord Gateway client.
- `/takimi fillo` and `/takimi mbaro`; short Albanian responses; notify the voice-channel chat before capturing audio.
- One active capture per guild; ordinary voice channels only. Leaving/rejoining participants does not end the meeting.
- Session states: STARTING, LISTENING, FINALIZING, READY, SAVED, INTERRUPTED, FAILED.
- Audio is temporary; transcripts/drafts are durable. No audio archive and no transcript/key logging.
- Notes are reviewed privately before saving; existing role/department checks remain in force. Spoken content cannot execute tools or mutate tasks.
- Capture/decode/DAVE verification with actual human speakers is required before claiming production verification.
- Feature off must leave existing task commands functional. A feature-on preflight failure must be explicit and prevent listening.

## Review Focus

- Lost stop/ack replies: capture must stop once and repeated save must return the same Note (Tasks 1, 4, 5).
- Stale/revoked account or private-channel permissions: no transcript may be delivered to a newly public destination (Tasks 1, 5).
- Speech overlapping with a participant joining/leaving: retain speaker attribution and keep the DAVE transport alive or report interruption (Tasks 2, 3, 6).
- Slow transcription while stopping: capture stops immediately, bounded queues drain separately, and missing chunks are disclosed (Tasks 2, 4, 5).
- Restart during capture/finalization: no silent capture restart, no fabricated complete summary, no duplicate Note (Tasks 1, 4, 6).

## File Map

- `backend/app/models/discord_voice_meeting.py`: capture session and transcript segment persistence.
- `backend/app/schemas/discord_voice_meeting.py`: strict command, worker, segment and result schemas.
- `backend/app/services/discord_voice_meetings.py`: authorization, state transitions, leases, idempotency, save/delivery.
- `backend/app/api/routers/discord_voice_meetings.py`: bridge endpoints only; included under `/api/discord/bot/voice-meetings`.
- `backend/app/services/ga_note_creation.py`: shared uncommitted Note creation/validation extracted from the normal creation route.
- `backend/discord-voice/{package.json,package-lock.json,worker.mjs,audio.mjs,protocol.mjs}`: isolated transport dependencies, receive/decode, bounded IPC.
- `backend/discord_voice_client.py`: Python child-process and Gateway adapter; no Discord UI.
- `backend/discord_voice_meetings.py`: command orchestration, notices and capture lifecycle.
- `backend/discord_voice_ui.py`: private result/status controls.
- `backend/app/services/discord_voice_openai.py`: transcription, notes generation and safe provider errors.
- `backend/app/jobs/discord_voice_meetings.py`: durable finalization/recovery work.
- Existing bot/router/model registration, config, Celery registration, deploy workflow and Discord docs: narrow integration points.
- Tests: `backend/tests/test_discord_voice_{model,api,client,bot,openai,jobs}.py`, `backend/tests/test_ga_note_creation.py`, `backend/discord-voice/tests/*.test.mjs`, existing deploy/Discord tests.

## Task 1: Durable Sessions, Authorization and Atomic PX Notes Save

**Files:** Create model/schema/service/router files above, `backend/alembic/versions/0152_discord_voice_meetings.py`, `backend/app/services/ga_note_creation.py`, and model/API tests. Modify `backend/app/models/__init__.py`, `backend/app/api/routers/__init__.py`, `backend/app/api/routers/ga_notes.py`.

**Interfaces:**
- `start_session(db: AsyncSession, actor: VoiceStart) -> SessionView`.
- `authorize_session(db, actor: VoiceActor, session_id: UUID, *, operation: Literal['read','stop','save']) -> tuple[DiscordVoiceMeeting, User]`.
- `transition_session(db, session_id: UUID, capture_token: str, expected: set[str], target: str, **fields) -> SessionView`.
- `finish_session(db, actor: VoiceActor, session_id: UUID, *, segment_count: int, partial: bool) -> SessionView`.
- `save_notes(db, actor: VoiceActor, session_id: UUID) -> SessionView`.
- `build_ga_note(db: AsyncSession, user: User, payload: GaNoteCreate) -> GaNote`: validates and adds without committing; existing route retains its commit/output behavior.
- `VoiceActor`: existing Actor fields plus `voice_channel_id`; `VoiceStart` adds `request_id`, optional title/department_id. Backend checks both the bound personal channel and configured guild, never substitutes voice ID for personal-channel ID.
- `SessionView`: id, status, title, organizer_user_id, voice_channel_id, private_channel_id, partial, error, draft_text, saved_note_id, note_url. Capture token returned only by start/recovery worker operations, never by human result views.
- Model session fields: UUID, guild/channel IDs, organizer link/user IDs, destination department, request ID, worker instance UUID, capture-token hash, heartbeat/lease timestamps, state, partial/error, draft/version, saved_note_id, notification message/delivery lease fields, created/started/stopped timestamps.
- Segment fields: session UUID, globally monotonic sequence, speaker ID/name, relative start/end milliseconds, content hash, state/lease, transcript/error. Unique `(session_id, sequence)`.
- SQL partial unique index on guild for STARTING/LISTENING; FINALIZING can coexist with a subsequent capture. Verify Alembic heads before selecting migration down_revision; never add an independent head.
- All routes require existing `require_bot`. Worker mutations require matching unexpired capture token and instance. Start/save/stop additionally use authenticated linked-user authorization; manager stop checks current voice ID asserted by the trusted bot.
- Route contracts under the prefix above: `POST /start` (VoiceStart), `POST /{id}/detail` (VoiceActor), `POST /{id}/authorize-stop` (VoiceActor; authorizes before the bot disconnects), `POST /{id}/listening`, `POST /{id}/heartbeat`, `POST /{id}/interrupt` (worker token/instance), `POST /{id}/finish` (worker token/instance plus segment_count/partial after an authorized stop), `POST /{id}/save` (VoiceActor). Stale or mismatched workers cannot advance a session. Persist stop authorization against the session/instance so a capture token alone cannot impersonate a human stop request.

- [x] Write `test_discord_voice_model.py` assertions for unique sequence, active-guild index and migration chain; write API tests for start replay, wrong guild/link/channel, second active session, organizer/manager stop, unrelated staff denial, and revoked account.
- [x] Write `test_ga_note_creation.py`: ordinary POST and meeting save enforce the same department/project rules; `save_twice_returns_same_note` asserts one insert under concurrent transactions; losing the reply cannot create another Note. Use a disposable PostgreSQL test database for locking/index tests and mocks only for pure authorization cases.
- [x] Run from `backend`: `python -m unittest tests.test_discord_voice_model tests.test_discord_voice_api tests.test_ga_note_creation -v`; verify the new behavior fails before implementation.
- [x] Implement persistence, schemas, state transitions and shared Note creation. Save holds the session row lock, rechecks organizer/destination access, inserts Note and sets saved_note_id in one transaction. Empty drafts cannot be saved. Do not call an HTTP route that commits separately.
- [x] Run the tests green, plus `python -m unittest tests.test_discord_assistant tests.test_discord_agent_api -v`; confirm ordinary Note output remains unchanged.
- [x] Commit: `feat: persist and authorize Discord meeting note sessions`.

## Task 2: Silent Node Receive Transport with Bounded Buffers

**Files:** Create `backend/discord-voice/package.json`, lockfile, `worker.mjs`, `audio.mjs`, `protocol.mjs`, and `tests/{protocol,audio,worker}.test.mjs`.

**Interfaces:** JSON-lines IPC version 1; every session message includes session_id and capture instance UUID. Python sends `start`, `gateway`, `credit`, `stop`, `shutdown`. Child emits `hello`, `gateway_send`, `ready`, `segment`, `stopped`, `interrupted`. Messages are allowlisted and validated; stdout is exclusively protocol, stderr contains sanitized diagnostic codes.
- `createReceiver({sessionId, instanceId, guildId, channelId, userId, emit, now}) -> {gateway(event), credit(sequence), stop(), destroy()}`.
- `encodeWav(pcm: Buffer) -> Buffer`: 48 kHz, stereo, signed 16-bit little-endian PCM. Decoder is Opus receive-only.
- Segment payload: sequence, speaker_id, start_ms, end_ms, audio_base64; WAV <=2,000,000 bytes and IPC line <=3,000,000 bytes. Split at 10 seconds or 700 ms speech-stream silence. Sequence is global per session, independent of speaker.
- Maximum unacknowledged segments: 8. Maximum total buffered PCM: 16 MiB. If either limit prevents safe capture, emit interruption and stop, rather than silently dropping speech. A final `stopped` carries last sequence and partial flag.
- Use `@discordjs/voice@0.19.2` and its DAVE implementation; pin a compatible decoder after package metadata/native Windows checks and lock all resolved dependencies. Child env excludes API key, bot token, database credentials and bridge secret; voice credentials arrive only through the adapter pipe.

- [x] Write tests that assert `selfMute === true`, `selfDeaf === false`, DAVE enabled, and that the transport never creates a player or sends media. Simulate interleaved speaker Opus packets and assert distinct speaker segments/monotonic sequence.
- [x] Add tests for malformed/oversize IPC, credit exhaustion, stop with pending data, disconnect, DAVE/decode failure, silence, and repeated stop. WAV header size and PCM byte counts must match.
- [x] Run `node --test backend/discord-voice/tests/*.test.mjs` and observe red tests.
- [x] Implement pure protocol/audio functions and worker with injected adapter/clock dependencies for tests. Only receive APIs are allowed. `ready` is emitted after voice connection Ready, not after spawn. Emit a safe error if speaking is observed for 10 seconds without decodable audio.
- [x] Install locked dependencies in this isolated package; run `npm ci` and dependency/import preflight on Windows. Re-run Node tests green. Do not connect to a real Discord server during unit tests.
- [x] Commit: `feat: receive Discord meeting audio silently`.

## Task 3: Python Child Process and Existing Gateway Adapter

**Files:** Create `backend/discord_voice_client.py`, `backend/tests/test_discord_voice_client.py`; modify only needed Gateway lifecycle hooks in `backend/discord_bot.py`.

**Interfaces:**
- `VoiceCaptureClient(send_gateway: Callable[[dict], Awaitable[None]], on_segment: Callable[[dict], Awaitable[None]], on_interruption: Callable[[str], Awaitable[None]])`.
- `await client.start(*, session_id, instance_id, guild_id, channel_id, bot_user_id) -> None`: waits for `ready`, 20-second timeout.
- `await client.gateway(event: dict) -> None`, `await client.stop() -> CaptureEnd(last_sequence: int, partial: bool)`, `await client.close() -> None`.
- Only Op 4 outbound Gateway payloads for the exact active guild/channel (or channel_id=null for leave) are accepted; mute/deaf must retain silent-listening values. Pass raw VOICE_STATE_UPDATE/VOICE_SERVER_UPDATE only to the active adapter. Transport credentials must never reach logs.
- Child supervision uses `asyncio.create_subprocess_exec`, an absolute package path and configured Node binary; no shell invocation. Reader has the same 3 MB line limit. Child exit/Gateway disconnect interrupts the session, destroys voice transport and fails pending requests. Shutdown is bounded and reaps the child.

- [x] Write tests using a fake child process: startup success/timeout, invalid Op/guild/channel rejection, stderr redaction, only matching events forwarded, oversized JSON, unexpected exit, disconnect and close twice.
- [x] Add a race test: stop requested while the first chunk callback is blocked; assert the leave/stop command is sent before the callback finishes, no new capture starts, and final acknowledgement waits separately for queued work.
- [x] Run `python -m unittest tests.test_discord_voice_client -v` red.
- [x] Implement adapter using Task 2 IPC. Separate Gateway handling from HTTP uploads so slow transcription cannot block voice keepalives or stop. Enable only the minimal raw event hook required by discord.py; do not log raw Gateway frames.
- [x] Run green and existing bot tests. Verify shutdown with feature off creates no child process.
- [x] Commit: `feat: bridge Mira voice capture through the existing Discord bot`.

## Task 4: Transcription, Durable Finalization and Recovery

**Files:** Create `backend/app/services/discord_voice_openai.py`, `backend/app/jobs/discord_voice_meetings.py`, provider/job tests. Extend Task 1 schemas/router/service, `backend/app/celery_app.py`, `backend/app/celery_tasks.py`, `backend/app/config.py`.

**Interfaces:**
- `await transcribe_segment(wav: bytes) -> str`: existing Albanian transcription model/prompt and server-side API key; validates WAV and bounds before API call.
- `await summarize_meeting(title: str, segments: list[TranscriptPart], *, partial: bool) -> str`: text-only request, no tools; structured Albanian headings and evidence-derived actions, no invented names/deadlines.
- `await process_voice_meetings() -> dict[str,int]`: Celery tick every 30 seconds; leases finalization work, performs provider IO outside database locks, and commits results only under its current lease token/input digest.
- API `POST /{id}/segments`: multipart WAV + session token/instance/sequence/speaker/timing metadata; response is the durable receipt. Replays with the same digest return the original receipt; conflicting bytes are rejected. API never reads arbitrary audio URLs or persists raw audio.
- Python upload concurrency: 2, queue: 8. Retry transient failures at most 3 times with the same sequence/digest; report exhausted segments and partial capture. Child credit is returned only after a durable receipt or recorded failure.
- Finish seals the expected segment count after capture has stopped. READY requires all expected segments settled, or explicit partial status with missing IDs. `FINALIZING` cannot race a late segment into a completed summary.
- Summary inputs batch at 24,000 characters without splitting a segment; reduce batches recursively if necessary. Preserve speaker/timing references in intermediate summaries. Never silently slice the transcript to context length.
- Worker heartbeat every 10 seconds, stale capture after 60 seconds. Expired captures become INTERRUPTED and release the active-guild slot. Finalization can resume from persisted transcripts. Persist generation leases/progress and safe provider errors; do not persist raw audio.

- [x] Write provider tests for Albanian prompt/model, silence, malformed WAV, redacted errors, no tools, overlapping speakers, absent owner/deadline and long transcript reduction preserving last-batch decisions.
- [x] Write job/API tests for duplicate chunks, byte conflicts, out-of-order concurrent chunks, finish waiting for an outstanding receipt, expired lease/fenced result, crashed worker, interrupted partial output and empty transcript refusing Note creation.
- [x] Run `python -m unittest tests.test_discord_voice_openai tests.test_discord_voice_jobs tests.test_discord_voice_api -v` red.
- [x] Implement provider and job contracts with Tasks 1 and 3 interfaces. Reuse existing Albanian model config and normal text model config; do not alter agent-task model choices or switch providers silently. Use stable source identifiers in summaries, not guessed attribution.
- [x] Run tests green plus existing speech/agent job regressions. Confirm request cancellation does not leave raw audio on disk and logs contain neither keys nor meeting text.
- [x] Commit: `feat: transcribe and summarize Mira staff meetings durably`.

## Task 5: Commands, Private Review and PX Notes Save Controls

**Files:** Create `backend/discord_voice_meetings.py`, `backend/discord_voice_ui.py`, `backend/tests/test_discord_voice_bot.py`. Modify `backend/discord_bot.py` and existing bot registration tests.

**Interfaces:**
- `register_meeting_commands(bot: PrimeFlowBot, guild: discord.Object) -> None` registers group `takimi`, subcommands `fillo(titulli: str | None=None, departamenti: str | None=None)` and `mbaro()`.
- `MeetingCaptureCoordinator(bot)` implements `start(interaction, title, department_id)`, `stop(interaction, session_id=None)`, `gateway(event)`, `close()`. Resolve department names/IDs only against the caller's authorized choices; default to the caller's department, or unscoped Note for admin/manager without a department.
- Persistent component IDs: `pf:vm:stop:<uuid>`, `pf:vm:save:<uuid>`, `pf:vm:view:<uuid>`. Callbacks always reauthorize the actor; they do not trust the message owner or custom ID alone.
- Status view: **Përfundo takimin** during capture. READY view: **Shiko shënimet**, **Ruaj në PX Notes**. SAVED view: **Hap PX Notes**; no automatic task creation. Text >1,800 characters uses a UTF-8 file in the checked private channel.
- Public notice exactly communicates listening, e.g. `Mira po merr shënime për këtë takim. Nuk do të flasë.` Never post transcript/summary publicly.
- Result delivery uses claim/ack leases and persisted message IDs, stable Discord nonces with replay protection, following the existing reminder/result delivery pattern. Recheck private-channel overwrites and organizer link before every send or file upload.
- Delivery routes: `POST /delivery/claim` returns eligible session, organizer, private-channel ID and lease token; `POST /{id}/delivery/ack` takes that token and sent message IDs. Detail/view access remains user-authorized; worker delivery still checks the active organizer link and privacy before reading/sending the draft.

- [x] Write tests for missing voice channel, Stage channel, permission denial, failed public notice preventing capture, handshake failure, notice-before-capture ordering and no spoken output.
- [x] Test organizer/manager stop, outsider rejection, stale persistent buttons after restart, long private result, newly public personal channel, account unlink/deactivation, duplicate stop/save clicks and final note link.
- [x] Test `/takimi mbaro` while transcription is blocked: bot leaves immediately, shows processing, and later delivers the result without a live interaction token. Add capture-disabled command registration regression.
- [x] Run `python -m unittest tests.test_discord_voice_bot tests.test_discord_bot -v` red.
- [x] Implement commands/coordinator/UI using previous task interfaces. Reserve STARTING, verify notice and audio preflight, then enter LISTENING only on child readiness. Failed notice/connect cleans the reservation. Stop validates the actor before sending leave; queues drain/finalize after leave. Do not register a second Gateway client.
- [x] Run tests green plus `python -m unittest discover -s tests -p 'test_discord*.py'`; inspect every failure and separate pre-existing environment blockers from regressions.
- [x] Commit: `feat: add silent meeting commands and reviewed PX Notes delivery`.

## Task 6: Deployment, Full Verification and Live Acceptance

**Files:** Modify `backend/scripts/configure_discord.py`, `.github/workflows/deploy.yml`, `backend/app/config.py`, existing Discord deploy tests, `docs/discord-assistant.md`, `README.md`; create `backend/scripts/check_discord_voice.py` and `docs/superpowers/plans/2026-10-20-mira-discord-meeting-notes-validation.md`.

**Interfaces:** `DISCORD_MEETING_NOTES_ENABLED` defaults false; `DISCORD_VOICE_NODE_BINARY` defaults `node`. Existing bot token and API key remain server-only. Enabled deployment runs isolated `npm ci`, Node/version/DAVE/decoder preflight and both Python/Node regression tests before starting the bot. Disabled deployment does not require voice dependencies. No dependency install or test logs print environment values.

- [x] Write deploy tests asserting feature-off behavior, enabled Node/import checks, locked install path, missing dependency/unsupported runtime failures and secret-free configuration. Run them red.
- [x] Implement configuration and preflight. The bot reports capture availability separately from ordinary bot readiness. Mark expired prior captures interrupted; normal task commands remain available while voice capture is off.
- [x] Run `python -m unittest discover -s tests -p 'test_discord*.py'`, `python -m unittest tests.test_speech_transcribe tests.test_ga_note_creation`, `node --test backend/discord-voice/tests/*.test.mjs`, full backend suite, and `git diff --check`. Record commands, actual results/skips/blockers; mocked PostgreSQL tests do not count as locking verification.
- [x] Review the completed change, especially IPC bounds, fencing after restart, permissions, partial summaries, Note atomicity and absence of outbound audio. Fix review findings and rerun relevant regressions.
- [ ] Perform live acceptance only in a deliberately started test meeting with staff: two speakers in Albanian, overlap, join/leave/rejoin, stop, review, save twice. Verify audio reception survives DAVE transitions, bot never speaks, result attribution/decisions are accurate, only one Note exists and no private content is posted to shared chat.
- [x] Record live result or explicitly mark it pending. Do not join/record a real meeting automatically to complete this checkbox. Keep feature disabled until deployment preflight and live acceptance are deliberately exercised.
- [x] Update user docs with permissions (`View Channel`, `Connect`, `Send Messages` for the meeting notice), private command flow, recovery and known partial-result behavior. Document Node package requirements and how to verify readiness without recording.
- [x] Commit final verified code/docs; integrate remote changes safely and push when the authorized implementation is complete. Report commit, usage, verification and any remaining live acceptance requirement accurately.

## Plan Self-Review

- Every design section maps to Tasks 1–6; no new frontend app, bot identity or autonomous task execution is introduced.
- Session/token, Gateway, chunk and Note interfaces are shared across tasks with consistent field names.
- All five Review Focus conditions have named tests in their owning tasks.
- Commands and independent pieces can be developed/tested without recording a production meeting.
- The recommended execution method is native: implement these six dependent tasks in the current session and request one independent review of the whole change before completion.

Status: design and native execution approved; implementation and local verification complete. Live Discord acceptance remains pending as recorded in the validation report.
