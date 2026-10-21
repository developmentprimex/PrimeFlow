# Mira Meeting Memory (Living Register) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After every Discord voice meeting Mira updates one staff-wide living register of what was said, uses that register to link the next meeting's notes to earlier meetings, and everyone can view and correct the register on a minimal PrimeFlow page.

**Architecture:** Two new tables (`mira_memory_items`, `mira_memory_events`) plus memory-state columns on `discord_voice_meetings`. The existing finalization job passes a register snapshot into `summarize_meeting` for the final notes step. A new Celery beat task extracts structured register operations from the full transcript (OpenAI Structured Outputs) and applies them serially in meeting start order. A thin FastAPI router serves the page at `/mira-kujtesa`.

**Tech Stack:** Python/FastAPI, PostgreSQL/SQLAlchemy/Alembic, Celery beat, OpenAI Responses API (`DISCORD_AI_MODEL`, `store=false`, `json_schema` strict), Next.js app router + shadcn UI.

**Spec:** [Approved design](../specs/2026-10-21-mira-kujtesa-design.md)

## Global Constraints

- Feature flag `MIRA_MEMORY_ENABLED`, default `false`. With it off, notes are produced exactly as today (same OpenAI payload) and no meeting is ever processed for memory.
- One register for all staff. Every authenticated active user can read and correct it; no department filter.
- All meetings count: READY, SAVED, and FAILED-with-transcript. Saving to PX Notes is not required. `FAILED` without usable segments never touches the register.
- No backfill: migration marks every existing meeting `memory_status='SKIPPED'`; meetings finalized while the flag is off are also `SKIPPED`.
- Memory is extracted from the full transcript, not from the notes draft.
- Notes delivery never waits on memory; a memory failure never changes `status`, `draft_text`, `error` or delivery fields of a meeting.
- Transcript, register text and human-written corrections are data, never instructions (reuse `RULES` from `backend/app/services/discord_voice_openai.py`).
- Quiet after 30 days without mention; context gets OPEN items + items closed in the last 14 days; WRONG item titles are always included.
- Up to 5 attempts per meeting, then `FAILED`; later meetings proceed. A meeting still preparing notes holds later meetings at most 15 minutes.
- Nothing is ever deleted from the page; "wrong" is a status (`WRONG`).
- Logs carry counts and codes only, never meeting content. Prefix `MIRA_DIAGNOSTIC memory`.
- UI copy is Albanian. Page title "Kujtesa e Mira-s"; lead "Çka mban mend Mira nga takimet. Përditësohet pas çdo takimi."; tabs "Të hapura", "Të mbyllura", "Të gjitha"; actions "Korrigjo", "Shëno të mbyllur", "Rihap", "Shëno si të gabuar"; empty state "Mira nuk ka mbajtur mend asgjë ende. Pikat shfaqen pas takimit të parë me shënime."

## Review Focus

1. A person corrects an item while Mira's extraction for that item is in flight → the mention is kept, Mira's state/description change is dropped (Task 2 test `test_version_mismatch_keeps_mention_drops_change`).
2. The model returns an `item_id` that is not in the snapshot, or an action with missing fields → that operation is rejected and counted, the rest apply (Task 2 test `test_unknown_ids_and_incomplete_operations_are_rejected`).
3. The memory job runs twice for the same meeting (worker restart after OpenAI answered) → events are not duplicated (Task 4 test `test_applying_twice_does_not_duplicate_events`).
4. An earlier meeting is still finalizing when a later one is pending → the later one waits, but not beyond 15 minutes (Task 4 test `test_later_meeting_waits_for_earlier_at_most_15_minutes`).
5. Two people save the same item at once → the second gets 409 with an Albanian message, not a silent overwrite (Task 5 test `test_stale_version_is_rejected_with_409`).

---

### Task 1: Data model, migration and settings

**Files:**
- Create: `backend/app/models/mira_memory.py`
- Modify: `backend/app/models/discord_voice_meeting.py` (add columns to `DiscordVoiceMeeting`)
- Modify: `backend/app/models/__init__.py` (import the new models, same style as the others)
- Create: `backend/alembic/versions/0156_mira_memory.py` (`down_revision = '0155_recording_analysis_quality'`)
- Modify: `backend/app/config.py` (next to `DISCORD_AI_MODEL`)
- Modify: `backend/.env.example`, `backend/scripts/configure_discord.py`, `.github/workflows/deploy.yml` (Configure Discord Assistant env: `MIRA_MEMORY_ENABLED: ${{ vars.MIRA_MEMORY_ENABLED }}`)
- Test: `backend/tests/test_mira_memory_model.py`

**Interfaces:**
- Produces:
  - `MiraMemoryItem` (`mira_memory_items`): `id UUID pk`, `title String(200)`, `description Text`, `kind String(20)` ∈ `TASK|TOPIC|DECISION|INFO`, `status String(20)` ∈ `OPEN|CLOSED|WRONG` default `OPEN`, `people JSONB` (list[str], default `[]`), `version Integer` default 1, `mention_count Integer` default 0, `last_mentioned_at timestamptz`, `human_edited Boolean` default false, `updated_by_user_id FK users SET NULL`, `created_at`, `updated_at` (server_default now, onupdate now). Index on `(status, last_mentioned_at)`.
  - `MiraMemoryEvent` (`mira_memory_events`): `id UUID pk`, `item_id FK mira_memory_items CASCADE` indexed, `kind String(20)` ∈ `MENTION|CHANGE|CLOSE|REOPEN|EDIT|WRONG`, `text Text`, `meeting_id FK discord_voice_meetings SET NULL`, `user_id FK users SET NULL`, `partial Boolean` default false, `refs JSONB` (list[int] segment sequences, default `[]`), `created_at`.
  - On `DiscordVoiceMeeting`: `memory_status String(20) nullable` ∈ `PENDING|RUNNING|APPLIED|FAILED|SKIPPED`, `memory_attempts Integer` default 0, `memory_error String(100) nullable`, `memory_lease_until timestamptz nullable`.
  - Settings: `MIRA_MEMORY_ENABLED: bool = False`, `MIRA_MEMORY_QUIET_DAYS: int = 30`, `MIRA_MEMORY_RECENT_CLOSED_DAYS: int = 14`, `MIRA_MEMORY_MAX_ATTEMPTS: int = 5`, `MIRA_MEMORY_WAIT_MINUTES: int = 15`, `MIRA_MEMORY_CONTEXT_CHARS: int = 40000`.

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_mira_memory_model.py`, subclassing `PostgresMeetingTests` from `tests/test_discord_voice_model.py` (extend its table set to include the two new tables, e.g. by overriding `asyncSetUp` to also `create_all` them):
  - `test_frozen_migration_creates_matching_columns`: same technique as `test_frozen_migration_creates_matching_columns_in_postgresql` (load `0156_mira_memory.py`, drop the new tables and the four meeting columns, run `upgrade()`), then assert column sets of both new tables equal the model's `__table__.c.keys()` and the four meeting columns exist.
  - `test_migration_marks_existing_meetings_skipped`: insert a meeting before running `upgrade()` on a schema without the columns; afterwards its `memory_status == 'SKIPPED'`.
  - `test_flag_defaults_off`: `Settings().MIRA_MEMORY_ENABLED is False`.
- [ ] **Step 2: Run** `cd backend && VOICE_TEST_DATABASE_URL=... python -m unittest tests.test_mira_memory_model -v` — Expected: FAIL (module/columns missing).
- [ ] **Step 3: Implement** models, migration (`upgrade` creates tables, adds columns, then `UPDATE discord_voice_meetings SET memory_status='SKIPPED'`; `downgrade` reverses), settings, `.env.example` line `MIRA_MEMORY_ENABLED=false`, `configure_discord.py` key + `boolean(...)` normalization like `DISCORD_MEETING_NOTES_ENABLED`, and the deploy env line.
- [ ] **Step 4: Run** the new tests plus `python -m unittest tests.test_migration_graph tests.test_discord_voice_model -v` — Expected: PASS, one Alembic head.
- [ ] **Step 5: Commit** `feat: add Mira memory register tables and flag`

---

### Task 2: Register snapshot and operation application

**Files:**
- Create: `backend/app/services/mira_memory.py`
- Test: `backend/tests/test_mira_memory_service.py` (Postgres, same base as Task 1)

**Interfaces:**
- Consumes: Task 1 models and settings.
- Produces:
  - `async def snapshot(db) -> dict` → `{'items': [ {'id': str, 'title', 'description', 'kind', 'status', 'people': list[str], 'human_edited': bool, 'quiet': bool, 'version': int, 'mentions': [{'date': 'dd.mm HH:MM', 'meeting': str, 'text': str}]} ], 'wrong_titles': list[str], 'omitted': int}`. Includes OPEN items and CLOSED items with `updated_at` within `MIRA_MEMORY_RECENT_CLOSED_DAYS`; ordered by `last_mentioned_at desc nulls last, mention_count desc`; `mentions` = last 3 `MENTION|CHANGE|CLOSE` events, local time `APP_TIMEZONE`; items are dropped from the end until `len(json.dumps(result, ensure_ascii=False)) <= MIRA_MEMORY_CONTEXT_CHARS`, the dropped count goes in `omitted`. `quiet` = OPEN and `last_mentioned_at` older than `MIRA_MEMORY_QUIET_DAYS`. `wrong_titles` = all WRONG item titles (no age limit).
  - `async def apply_operations(db, meeting, operations: list[dict], versions: dict[str, int]) -> dict` → `{'applied': int, 'rejected': int, 'dropped': int}`. Caller owns the transaction; this function only adds/flushes.
  - Operation shape (same as Task 3 schema): `{'action': 'add'|'mention'|'change'|'close', 'item_id': str|None, 'title': str|None, 'description': str|None, 'kind': str|None, 'people': list[str], 'said': str, 'segments': list[int]}`.

Rules for `apply_operations` (every event gets `meeting_id=meeting.id`, `partial=meeting.partial`, `refs=segments`, timestamp = meeting start (`started_at or created_at`)):
- `add`: needs `title`, `description`, `kind`; creates item (`mention_count=1`, `last_mentioned_at` = meeting start) + `MENTION` event with `said`. A title equal (case-insensitive, trimmed) to a WRONG item's title is rejected.
- `mention`: needs a known `item_id` (from `versions`); adds `MENTION` event, bumps `mention_count`, `last_mentioned_at`, `people` union.
- `change`: as `mention`, plus sets `description` and writes a `CHANGE` event instead of `MENTION`; a CLOSED item is reopened (status OPEN).
- `close`: as `mention`, plus status CLOSED with a `CLOSE` event (`text=said`).
- Unknown/absent `item_id` for non-`add`, missing required fields, `kind` outside the enum, `title` > 200 chars, or `said` empty → rejected.
- If the item's current `version` ≠ `versions[item_id]`, or the item is WRONG: write only the `MENTION` event and counters; drop the description/status change (`dropped += 1`).
- Every applied change/close bumps `version`; `updated_by_user_id = None`.

- [ ] **Step 1: Write the failing tests:**
  - `test_snapshot_includes_open_recent_closed_and_wrong_titles`: OPEN item, CLOSED 3 days ago, CLOSED 20 days ago, WRONG 90 days ago → items = first two; `wrong_titles == [that title]`.
  - `test_snapshot_marks_quiet_after_30_days` (OPEN, last mention 31 days ago → `quiet is True`).
  - `test_snapshot_truncates_to_context_limit` (patch `MIRA_MEMORY_CONTEXT_CHARS` small → `omitted > 0`, most recently mentioned item kept).
  - `test_add_mention_change_close_apply_and_record_history`: one operation of each; assert statuses, `mention_count`, `version`, event kinds in order, `refs`.
  - `test_unknown_ids_and_incomplete_operations_are_rejected`: unknown id, `add` without title, bad kind → `rejected == 3`, valid sibling applied.
  - `test_version_mismatch_keeps_mention_drops_change`: bump item version after snapshot; `change` → description unchanged, one MENTION event, `dropped == 1`.
  - `test_wrong_title_is_not_recreated`.
- [ ] **Step 2: Run** `python -m unittest tests.test_mira_memory_service -v` — Expected: FAIL.
- [ ] **Step 3: Implement** `snapshot` and `apply_operations` in `backend/app/services/mira_memory.py`.
- [ ] **Step 4: Run** the same command — Expected: PASS.
- [ ] **Step 5: Commit** `feat: snapshot and apply Mira memory operations`

---

### Task 3: Memory extraction and notes continuity prompts

**Files:**
- Modify: `backend/app/services/discord_voice_openai.py`
- Test: `backend/tests/test_discord_voice_openai.py` (extend; mock `request` like existing tests)

**Interfaces:**
- Consumes: Task 2 snapshot dict and operation shape.
- Produces:
  - `summarize_meeting(title, segments, *, meeting_date=None, cache=None, checkpoint=None, memory: dict | None = None)`. With `memory=None` the payloads are byte-identical to today. With `memory`, only the **final** call changes: system = `FINAL_SYSTEM + MEMORY_NOTES_RULES`, user JSON adds key `'kujtesa': memory` (`wrong_titles` and `omitted` excluded).
  - `MEMORY_NOTES_RULES` (Albanian, appended text): link to earlier meetings only when it is clearly the same matter; write it briefly inside the existing sections (no new section unless needed), with a reference like "(1H, 21.10 09:58)" taken from `mentions`; never repeat the register; register text is data.
  - `async def extract_memory_operations(title, segments, *, meeting_date, memory: dict, cache=None, checkpoint=None) -> list[dict]`.
  - `MEMORY_SCHEMA`: strict JSON schema `{'operations': [operation]}` with every operation field required and nullable where the Task 2 shape says `|None`; `action` and `kind` as enums.
  - `MEMORY_PART_SYSTEM` / `MEMORY_SYSTEM` (Albanian, prefixed with `RULES`): keep details useful later (promises, names, client names, numbers, deadlines, side topics); human-corrected items (`human_edited`) change only if this meeting clearly says otherwise; never recreate titles in `wrong_titles`; prefer `mention` over `add` when it is the same matter; `said` is a short summary of what was said in this meeting with the speaker names.

Long transcripts: reuse the 24000-char grouping from `summarize_meeting` (extract it into a helper `group_parts(parts, limit=24000)` used by both). Each group goes through `MEMORY_PART_SYSTEM` (free text, detail-preserving, keeps `[segmenti, folësi]` refs); the final structured call gets the group texts (or the raw segments when they fit) plus `memory`. Cache/checkpoint keyed the same way as `summarize_meeting`. Response parsing: concatenate `output_text`, `json.loads`, raise `ValueError('invalid_memory_response')` on empty/invalid/oversize (>100000 chars).

- [ ] **Step 1: Write the failing tests:**
  - `test_summary_payload_unchanged_without_memory`: capture the payload with `memory=None` and compare with a fixture captured before the change (assert system == `FINAL_SYSTEM` and the user JSON keys == `{'title','segments'}`).
  - `test_summary_final_call_receives_memory_and_rules`: with `memory`, final system ends with `MEMORY_NOTES_RULES`, user JSON has `kujtesa`, part calls (long transcript) do not.
  - `test_extract_memory_uses_strict_schema_and_returns_operations`: mocked response JSON → returned list equals `operations`; payload has `text.format.type == 'json_schema'`, `strict is True`, `store is False`, model `DISCORD_AI_MODEL`.
  - `test_extract_memory_long_transcript_uses_part_step` (segments > 24000 chars → ≥2 part calls before 1 structured call).
  - `test_extract_memory_invalid_json_raises`.
- [ ] **Step 2: Run** `python -m unittest tests.test_discord_voice_openai -v` — Expected: new tests FAIL, existing PASS.
- [ ] **Step 3: Implement** in `discord_voice_openai.py`.
- [ ] **Step 4: Run** the same command — Expected: all PASS.
- [ ] **Step 5: Commit** `feat: Mira memory extraction and continuity-aware notes`

---

### Task 4: Finalization wiring and the memory job

**Files:**
- Modify: `backend/app/jobs/discord_voice_meetings.py`
- Create: `backend/app/jobs/mira_memory.py`
- Modify: `backend/app/celery_tasks.py`, `backend/app/celery_app.py` (beat entry `"process-mira-memory": {"task": "app.celery_tasks.process_mira_memory", "schedule": 30.0}`)
- Modify: `.github/workflows/mira-diagnostics.yml` (also tail `C:\pm2-system\logs\celery_worker*` for `MIRA_DIAGNOSTIC memory`; add `memory_status, memory_attempts, memory_error` to the `MIRA_SESSION` query)
- Test: `backend/tests/test_mira_memory_jobs.py` (Postgres, patch `SessionLocal` like `test_discord_voice_jobs.py`)

**Interfaces:**
- Consumes: Task 2 `snapshot`, `apply_operations`; Task 3 `summarize_meeting(memory=...)`, `extract_memory_operations`.
- Produces: `async def process_mira_memory() -> dict` (`{'applied': n, 'failed': n, 'waiting': bool}`), Celery task `app.celery_tasks.process_mira_memory`.

Finalization changes (`process_voice_meetings`): when `settings.MIRA_MEMORY_ENABLED`, take `await mira_memory.snapshot(db)` in the claim session and pass `memory=` to `summarize_meeting`; a snapshot exception is logged as `MIRA_DIAGNOSTIC memory stage=snapshot` and notes proceed with `memory=None`. In the final commit set `memory_status = 'PENDING'` when the flag is on and the meeting had parts (READY, or FAILED because the summary failed), else `'SKIPPED'`; the no-parts FAILED branch sets `'SKIPPED'`.

`process_mira_memory` (returns immediately when the flag is off):
1. Claim, in one transaction under `pg_advisory_xact_lock` (key derived like `start_session`, string `'mira-memory'`): if any meeting is `RUNNING` with `memory_lease_until > now()`, return. Candidate = oldest by `coalesce(started_at, created_at)` with `memory_status='PENDING'` or (`RUNNING` and lease expired). If an earlier meeting (by the same key) has `status in ('FINALIZING','INTERRUPTED')` and `stopped_at` (or `created_at`) is newer than `MIRA_MEMORY_WAIT_MINUTES`, return `waiting=True`. Set `RUNNING`, `memory_attempts += 1`, lease = now + 5 min; remember the attempt number as the fence. Commit.
2. Outside any DB lock: load DONE segments (same dict shape as finalization), `memory = await snapshot(db)`, `ops = await extract_memory_operations(...)`.
3. Apply in a new transaction: lock the meeting; if `memory_status != 'RUNNING'` or attempts changed, discard. Else `apply_operations(db, meeting, ops, {i['id']: i['version'] for i in memory['items']})`, set `APPLIED`, clear lease/error, commit. Log `MIRA_DIAGNOSTIC memory meeting=<id> applied=.. rejected=.. dropped=.. omitted=..`.
4. On any exception from 2–3: in a new transaction, if still the same fence, set `memory_error` to the exception class/code (≤100 chars, no content), `memory_status = 'FAILED'` if `memory_attempts >= MIRA_MEMORY_MAX_ATTEMPTS` else `'PENDING'`; log `MIRA_DIAGNOSTIC memory meeting=<id> stage=extract error=<code> attempt=<n>`. Never touch notes fields.

- [ ] **Step 1: Write the failing tests:**
  - `test_flag_off_finalization_marks_skipped_and_job_does_nothing`.
  - `test_flag_on_notes_get_snapshot_and_meeting_becomes_pending` (assert `summarize_meeting` awaited with `memory=` the snapshot; status READY; `memory_status == 'PENDING'`).
  - `test_failed_summary_with_transcript_is_pending_no_speech_is_skipped`.
  - `test_pending_meeting_is_applied_in_start_order` (two meetings, later created first → first run applies the earlier one).
  - `test_later_meeting_waits_for_earlier_at_most_15_minutes` (earlier FINALIZING stopped 5 min ago → waiting; 16 min ago → later applied).
  - `test_failure_retries_then_fails_after_5_attempts_and_notes_untouched` (extract raises; after 5 runs `memory_status == 'FAILED'`, `draft_text`/`status`/`delivered_at` unchanged; next meeting then applies).
  - `test_applying_twice_does_not_duplicate_events` (simulate lease expiry after a successful apply: second run finds `APPLIED` and does nothing; and a stale fence result is discarded).
  - `test_unsaved_takimi_fillo_meeting_is_included` (READY, `saved_note_id` None → applied).
- [ ] **Step 2: Run** `python -m unittest tests.test_mira_memory_jobs tests.test_discord_voice_jobs -v` — Expected: new FAIL, existing PASS.
- [ ] **Step 3: Implement** the finalization changes, `backend/app/jobs/mira_memory.py`, the Celery task + beat entry, and the diagnostics workflow lines.
- [ ] **Step 4: Run** the same command plus `python -m unittest discover -s tests -p "test_discord*.py"` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: apply Mira memory after each meeting`

---

### Task 5: Register API for the page

**Files:**
- Modify: `backend/app/services/mira_memory.py` (user actions)
- Create: `backend/app/schemas/mira_memory.py`
- Create: `backend/app/api/routers/mira_memory.py`
- Modify: `backend/app/api/routers/__init__.py` (`api_router.include_router(mira_memory_router, prefix="/mira-memory", tags=["mira-memory"])`)
- Test: `backend/tests/test_mira_memory_api.py` (Postgres service tests + one `dependency_overrides` router smoke test)

**Interfaces:**
- Consumes: Task 1 models.
- Produces (all require `get_current_user`; no department check):
  - `GET /api/mira-memory/items?status=open|closed|all` → `{'items': [{'id','title','kind','status','quiet','mention_count','last_mentioned_at'}], 'counts': {'open': int, 'closed': int}, 'failed_meetings': int}`; `closed` = CLOSED + WRONG; ordering as `snapshot`. Service: `list_items(db, status) -> dict`.
  - `GET /api/mira-memory/items/{id}` → item fields + `description`, `people`, `version`, `human_edited`, `events: [{'kind','text','created_at','meeting_title','user_name','partial'}]` newest first. Service: `get_item(db, item_id) -> dict` (404 "Pika nuk u gjet.").
  - `PATCH /api/mira-memory/items/{id}` body `{'version': int, 'title': str (1–200), 'description': str (≤4000)}` → item detail; writes `EDIT` event (`text` = new description), `human_edited=True`, `updated_by_user_id`, `version += 1`. Service: `edit_item(db, user, item_id, payload)`.
  - `POST /api/mira-memory/items/{id}/status` body `{'version': int, 'action': 'close'|'reopen'|'wrong'}` → item detail; events `CLOSE|REOPEN|WRONG` with `user_id`; sets `human_edited=True`. Service: `set_status(db, user, item_id, payload)`.
  - `POST /api/mira-memory/retry-failed` (ADMIN/MANAGER only, else 403) → `{'retried': int}`; FAILED → PENDING, attempts 0, error null. Service: `retry_failed(db, user)`.
  - Version mismatch → 409 `"Pika është ndryshuar ndërkohë. U rifreskua."`. Row lock with `with_for_update()` on writes.

- [ ] **Step 1: Write the failing tests:** `test_list_filters_and_counts`, `test_detail_returns_events_with_sources`, `test_edit_marks_human_and_records_event`, `test_close_reopen_wrong_record_events`, `test_stale_version_is_rejected_with_409`, `test_retry_failed_requires_admin_or_manager`, `test_router_requires_authentication` (no override → 401).
- [ ] **Step 2: Run** `python -m unittest tests.test_mira_memory_api -v` — Expected: FAIL.
- [ ] **Step 3: Implement** schemas, service functions, router, registration.
- [ ] **Step 4: Run** the same command and `python -c "from app.main import app"` from `backend/` — Expected: PASS, import OK.
- [ ] **Step 5: Commit** `feat: Mira memory register API`

---

### Task 6: "Kujtesa e Mira-s" page

**REQUIRED SUB-SKILL:** `frontend-design:frontend-design` (the user asked for it). Direction is fixed by the spec: very minimal, simple, beautiful; layout B (list left, detail right with history timeline); PrimeFlow look (shadcn, Segoe UI, white, neutrals) with one accent colour for open items; the history timeline is the one memorable element. Accepted mockup: `.superpowers/brainstorm/1141-1792566447/content/register-layout.html` (option B, local only).

**Files:**
- Create: `frontend/src/lib/mira-memory.ts` (types + pure helpers)
- Create: `frontend/src/components/mira-memory/mira-memory-page.tsx`
- Create: `frontend/src/app/(app)/mira-kujtesa/page.tsx`
- Modify: `frontend/src/components/sidebar.tsx` (entry `{ href: "/mira-kujtesa", label: "Kujtesa e Mira-s", icon: Brain }` in the top-level list next to "PX Notes")
- Create: `frontend/tests/mira-memory.test.mjs`; Modify: `frontend/package.json` (`"test:mira": "node --test tests/mira-memory.test.mjs"`)
- Modify: `docs/discord-assistant.md` (new section "Kujtesa e Mira-s": what it does, `MIRA_MEMORY_ENABLED` Actions variable, all staff see it, no backfill, diagnostics)

**Interfaces:**
- Consumes: Task 5 endpoints via `useAuth().apiFetch` (paths without `/api`, like `/discord/me`).
- Produces in `mira-memory.ts`: types `MemoryListItem`, `MemoryDetail`, `MemoryEvent`; `eventLabel(event: MemoryEvent): string` ("1H · 21.10, 09:58" for meeting events using `meeting_title` and local date; "Korrigjuar nga <user_name> · 21.10, 10:20" for EDIT; "Mbyllur nga …", "Rihapur nga …", "Shënuar si e gabuar nga …" for human CLOSE/REOPEN/WRONG; meeting CLOSE "Mbyllur në takim"); `mentionText(count: number): string` ("1 takim" / "n takime").

Behaviour: tabs with counts; list sorted as returned; selecting an item loads detail; "Korrigjo" toggles inline title/description editing with "Ruaj" / "Anulo"; status buttons depend on status (OPEN → "Shëno të mbyllur", "Shëno si të gabuar"; CLOSED/WRONG → "Rihap"); on 409 show the message via `toast` and reload the item; quiet items show a quiet "e heshtur" marker; when `failed_meetings > 0` a footer line "N takime nuk u përfshinë në kujtesë", plus "Provo përsëri" for ADMIN/MANAGER calling retry; mobile: list only, detail replaces it with a back button; empty state copy from Global Constraints; keyboard focus visible.

- [ ] **Step 1: Write the failing tests** in `frontend/tests/mira-memory.test.mjs` (load the TS via `ts.transpileModule` + `vm`, as in `tests/px-notes-voice.test.mjs`): `eventLabel` for a meeting MENTION, a human EDIT and a human WRONG; `mentionText(1) === "1 takim"`, `mentionText(3) === "3 takime"`.
- [ ] **Step 2: Run** `cd frontend && npm run test:mira` — Expected: FAIL.
- [ ] **Step 3: Implement** helpers, then the page, route and sidebar entry following the frontend-design skill.
- [ ] **Step 4: Run** `npm run test:mira`, `npx tsc --noEmit`, `npm run lint` — Expected: PASS / no new errors. Then run the app (backend + frontend, seed a few items via the API) and screenshot the page at desktop and 390px width; check both against the mockup direction.
- [ ] **Step 5: Commit** `feat: Kujtesa e Mira-s page`

---

### Task 7: Real-meeting verification (manual, after deploy with the flag on)

- [ ] Set Actions variable `MIRA_MEMORY_ENABLED=true`, merge, wait for "Primex Auto Deploy".
- [ ] Two consecutive 1H meetings where the second returns to a topic from the first. Expected: the second meeting's notes mention the link with a reference; the page shows that item with two mentions; `gh workflow run mira-diagnostics.yml --ref main` shows `memory_status=APPLIED` for both and `MIRA_DIAGNOSTIC memory ... applied=` lines without content.
- [ ] Correct one item on the page, run another meeting that mentions it without contradicting it. Expected: the correction stands; a new MENTION event appears.
- [ ] Report the result as verified only if all three hold; otherwise report what was observed.
