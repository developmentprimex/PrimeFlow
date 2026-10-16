# Discord Task Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Delegate a task or one title/description point to GPT-6 Luna from Discord, persist research/drafts and let its owner review and accept the result.

**Architecture:** PostgreSQL stores durable runs; Celery submits background Responses requests and polls them every 30 seconds. The Discord worker delivers results through normal bot messages; authenticated bridge routes reuse existing identity, ownership, version and task-mutation checks.

**Tech Stack:** Existing Python/FastAPI, SQLAlchemy/asyncpg, Alembic, httpx, Celery/Redis, discord.py and unittest; no new production dependencies.

**Spec:** `docs/superpowers/specs/2026-10-16-discord-task-agents-design.md` (approved by the user's “vazhdo”).

## Global Constraints

- Model: `gpt-6-luna`; reasoning: `medium`; Responses `background=true`, `store=true`; no silent model fallback.
- No application spending budget, daily spending limit, token cap or search-count cap.
- Modes: `RESEARCH` with required `web_search`; `DRAFT` without web tools.
- Targets: entire task or exactly one title/description text point, using existing strike-point identity.
- Existing Discord user/guild/channel identity, active link/user and task ownership checks apply throughout.
- No automatic task mutations by the agent; accepted point strike uses existing task API/audit.
- Full-task completion, external email sending, publishing, purchases, code execution, company-document retrieval and day planning are outside this version.
- Results and interactions use Albanian labels; citations remain visible and clickable.
- Work on Windows with the existing Celery async-loop disposal convention; never apply migrations to a live database as a local check.
- Local tests mock OpenAI/Discord; no paid live API calls during automated verification.

## Review Focus

1. Network loss after OpenAI accepts a submission: no automatic duplicate paid submission; preserve an ambiguous-failure message (Task 3).
2. Cancellation/revocation racing with submission or completion: preserve a returned response ID and request cancellation without overwriting a completed result (Tasks 2–3).
3. Duplicate point text or reordered points: point identity and fingerprint must prevent accepting against a different point (Tasks 1–2).
4. Delivery after restart, expired interactions or lost ACK: use bot-authenticated messages with a stable nonce, durable lease and message receipt (Tasks 4–5).
5. Oversized text/citations and boundary pagination: preserve complete UTF-8 output and sources, with valid Discord component/message limits (Task 5).

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/app/models/discord_agent_run.py` | Durable run model and state/acceptance/delivery metadata |
| `backend/alembic/versions/0149_discord_agent_runs.py` | Schema, constraints and indexes after `0148_discord_assistant` |
| `backend/app/schemas/discord_agent.py` | Request validation and serialized run/result contracts |
| `backend/app/services/discord_agents.py` | Target selection, snapshots, ownership, lifecycle persistence and acceptance |
| `backend/app/services/discord_agent_openai.py` | Responses payloads, submit/retrieve/cancel and result extraction |
| `backend/app/jobs/discord_agents.py` | Claim/process/recover persisted work using short transactions |
| `backend/app/api/routers/discord_agents.py` | Bot-authenticated lifecycle and delivery routes |
| `backend/discord_agent_ui.py` | Target/mode selectors, instruction/revision modals and result rendering |
| `backend/discord_agent_client.py` | Interaction dispatch and durable result delivery using the existing bot |
| Existing model/router registries, settings, Celery files, bot/UI, deploy/configuration scripts | Small integration changes |
| `backend/tests/test_discord_agent_{model,api,openai,jobs,ui}.py` | Focused mocked unit tests |
| Existing Discord tests and migration graph test | Integration/regression checks |

### Task 1: Durable runs, target identity and configuration

**Files:** Create model, migration, schemas and initial `discord_agents.py`; modify `backend/app/models/__init__.py`, `backend/app/config.py`, `backend/scripts/configure_discord.py`; create `backend/tests/test_discord_agent_model.py`; extend `backend/tests/test_discord_deploy.py`.

**Interfaces:**
- `resolve_target(task: dict, field: str | None, number: int | None) -> dict` returns `{field, number, key, text}`; full task has all target values null.
- `snapshot_context(task: dict, target: dict) -> dict` includes only ID/title/description/target and the acting user's comment.
- Schemas: `AgentCreate(Actor)` with request ID, task ID, expected fingerprint, mode, instruction, optional field/number and parent run ID; `AgentActor(Actor)`; `AgentAccept(Actor)` with request ID and `mark_point_done`.
- `serialize_run(run: DiscordAgentRun) -> dict` produces the public representation, excluding leases, secrets and raw provider errors.
- Model columns follow the spec; add unique request ID, nullable response ID, nullable target identity, processing lease, delivery lease/token, message IDs, acceptance request ID/status and timestamps. Task deletion uses SET NULL for history; access is refused when the task no longer exists.
- `Settings.DISCORD_AGENT_MODEL` and deploy config default to `gpt-6-luna`; interpretation-model settings stay independent.

- [x] Write tests for full-task/title/description target resolution and invalid fields/numbers. Include this assertion for duplicate bullets:
  ```python
  task = {"title": "Task", "description": "• Same\n• Same"}
  self.assertNotEqual(resolve_target(task, "description", 1)["key"],
                      resolve_target(task, "description", 2)["key"])
  ```
- [x] Add tests asserting snapshots exclude other users' data, config defaults to `gpt-6-luna`, request IDs are unique and migration graph has a single head.
- [x] Run `python -m unittest tests.test_discord_agent_model tests.test_discord_deploy -v` from `backend`; confirm failures exercise missing behavior, then implement the interfaces/model/migration/config.
- [x] Repeat that command and `python -m unittest tests.test_migration_graph -v`; expect all applicable tests passing. Check migration SQL against model fields without connecting to production.
- [x] Commit this deliverable and its passing tests.

### Task 2: Authorized lifecycle routes and result acceptance

**Files:** Extend `discord_agents.py`; create the agent router and `backend/tests/test_discord_agent_api.py`; modify `backend/app/api/routers/__init__.py`.

**Interfaces:** Under `/api/discord/bot/agents` with existing `require_bot` dependency:
- `POST /runs`: `AgentCreate` -> serialized run. Atomically return the existing run for the same request ID/identity, or reject cross-identity replay.
- `POST /tasks/{task_id}/runs`: `AgentActor` -> `{runs: [...]}` with cursor pagination (25 per page, newest first).
- `POST /runs/{run_id}`: `AgentActor` -> serialized run.
- `POST /runs/{run_id}/cancel`: `AgentActor` -> serialized run.
- `POST /runs/{run_id}/accept`: `AgentAccept` -> `{run, task_detail?}`.
- Service `authorized_run(db, actor, run_id, *, lock=False)` checks the original run link/user and current identity/ownership; shared helper reuses `identity` and `owned_task` from the existing router.
- Creation snapshots the currently displayed version. A revision validates its parent run belongs to the same actor/task/target and adds the parent result to the new snapshot; parent data is immutable.
- Plain acceptance records acceptance without task mutation. Point acceptance calls the existing `discord_assistant.command` direct-action path with `set_points`, the saved fingerprint and request ID. Persist acceptance only after a successful reply. Reserve/reuse the mutation request ID across retries, so a lost successful reply cannot apply a second mutation; ambiguous reservations need explicit reconciliation, not blind replay.

- [x] Write API tests for wrong guild/channel/user, disabled/revoked link, reassignment, stale fingerprint, invalid parent, duplicate creation, and no mutation during creation/plain acceptance.
- [x] Add tests for duplicate/reordered point acceptance and normal-API rejection; assert failed strike never sets accepted, and repeated acceptance uses the reserved command request ID.
- [x] Run `python -m unittest tests.test_discord_agent_api -v`; confirm intended failures, implement the routes and service logic, then rerun to pass.
- [x] Add cancellation tests: queued -> cancelled without provider access, running -> cancel requested with response ID retained, ready result cannot be presented as stopped retroactively. Revocation blocks read/delivery/acceptance and schedules cancellation during worker processing.
- [x] Run `python -m unittest tests.test_discord_agent_api tests.test_discord_assistant -v`; expect passing tests and commit.

### Task 3: OpenAI execution and recoverable background processing

**Files:** Create OpenAI adapter, job module and `test_discord_agent_openai.py`/`test_discord_agent_jobs.py`; modify `backend/app/celery_app.py` and `backend/app/celery_tasks.py`.

**Interfaces:**
- `build_request(run: DiscordAgentRun) -> dict` returns the exact configured model, reasoning, background/store flags and system/input context. Research uses `tools=[{"type":"web_search"}]` with a specific web-search tool choice; drafts omit web tools.
- Adapter async functions `submit(payload: dict) -> dict`, `retrieve(response_id: str) -> dict`, `cancel(response_id: str) -> dict`; use existing `httpx` and backend-only API key.
- `extract_result(response: dict) -> dict` returns `{status, text, sources, usage}` from all output text segments and URL annotations. Completed research must include an actual search and sources; missing evidence becomes a clear incomplete-result error.
- Job `async process_agent_runs() -> dict[str, int]`, exposed through `app.celery_tasks.process_discord_agent_runs` using `_run_async`; beat schedule is `30.0` seconds.
- Claims use `FOR UPDATE SKIP LOCKED` and a 2-minute lease, stored before remote calls. Submission enters `SUBMITTING`; preserve any returned response ID before subsequent transitions. Provider requests have a 30-second network timeout and do not occupy an open DB transaction.
- Expired `SUBMITTING` without response ID -> `FAILED` with ambiguous-submission message, never auto-resubmit. Expired `RUNNING` resumes retrieval of the same ID. Transient retrieve failures retain resumable state; terminal provider/auth/model errors produce a redacted public error.
- Treat provider `queued`/`in_progress` as running; `completed` with valid content as ready; `failed`/`incomplete` as failed; confirmed `cancelled` as cancelled. Invalid/deleted/expired response IDs fail clearly without regeneration.
- Before submission and result delivery, recheck ownership/link. Lost ownership/revocation requests cancellation; provider cleanup may continue with the stored response ID while result access remains blocked.

- [x] Write payload tests with these assertions:
  ```python
  self.assertEqual(payload["model"], "gpt-6-luna")
  self.assertEqual(payload["reasoning"], {"effort": "medium"})
  self.assertIs(payload["background"], True)
  self.assertIs(payload["store"], True)
  self.assertNotIn("max_output_tokens", payload)
  self.assertNotIn("max_tool_calls", payload)
  ```
- [x] Add research/draft separation, multi-segment output, citations, prompt-injection-as-data, empty output and provider error-redaction tests.
- [x] Add job tests for competing workers, restart with ID, ambiguous submit, cancellation during submit and completion, revocation, transient polling failure and unsupported model. Assert no second submit for existing/ambiguous work.
- [x] Run `python -m unittest tests.test_discord_agent_openai tests.test_discord_agent_jobs -v`; confirm intended failures, implement the adapter/jobs/schedule and rerun to pass.
- [x] Verify settings and async-loop disposal via mocked Celery wrapper tests; commit.

### Task 4: Durable notification handoff

**Files:** Extend agent service/router and `backend/tests/test_discord_agent_api.py`.

**Interfaces:**
- `POST /deliveries/claim` (bridge-secret authenticated) -> `{jobs:[{run_id, lease_token, discord_user_id, guild_id, channel_id}]}`. Claim only terminal, undelivered runs for currently authorized active links/tasks.
- `POST /runs/{run_id}/delivery` with actor and lease token -> `{run}` after a fresh ownership check.
- `POST /runs/{run_id}/ack` with actor, lease token and message IDs -> `{ok:true}`. ACK must match the current delivery lease; store all IDs and delivery time. If lease expired after a valid send, retry can discover/deduplicate the existing Discord message before ACKing the renewed lease.
- Deliveries use a 2-minute lease. Stable message nonce derives from run ID and message part. Save no raw results in claim responses; retrieve only after private-channel validation.

- [x] Write tests for competing claims, stale lease tokens, repeat ACK, task deletion/reassignment and link revocation between claim/read/ACK.
- [x] Run `python -m unittest tests.test_discord_agent_api -v`; confirm intended failures, implement delivery operations and rerun to pass.
- [x] Verify lost ACK reclaims only undelivered jobs and preserves stable run identity; commit.

### Task 5: Discord delegation and result controls

**Files:** Create UI/client modules and `backend/tests/test_discord_agent_ui.py`; modify `backend/discord_bot.py`, `backend/discord_ui.py` and existing Discord bot/UI tests.

**Interfaces:**
- UI `target_view(detail: dict, page: int=0) -> discord.ui.View`, `mode_view(task_id, fingerprint, field=None, number=None) -> discord.ui.View`, `AgentInstructionModal`, `AgentRevisionModal`, `run_view(run: dict) -> discord.ui.View`, `result_message(run: dict) -> dict`.
- Client `async handle_agent_interaction(bot, interaction) -> bool` routes `pf:agent:*` components and returns whether handled; `async deliver_agent_results(bot) -> None` processes claimed notifications.
- Short custom IDs encode action, UUID and only needed target/version values; enforce <=100 characters. Back/forward/current controls have distinct action tags, including disabled controls. Each selection has <=25 options; buttons/selects respect row widths.
- Add the two task-card buttons to available row 3. Target chooser uses whole task plus title/description selectors on separate rows; paginate each field without losing original point numbers.
- Modals send exact task/version/target/mode/instruction to creation endpoint. Revisions copy the immutable parent target via the server, not editable client metadata.
- Results use normal `channel.send`/bot-authenticated HTTP, never cached interaction-webhook tokens. Display a short preview, model/time/status and source links; always include the complete result plus sources as a UTF-8 `.txt` attachment when the preview/citations would truncate. Split source-list text into valid message parts; preserve clickable citations.
- Add a 30-second notification loop started in `setup_hook`, waiting for readiness and cancelled in `close`. Each delivery reuses `private_channel`, then reads authorized result, sends stable-nonce parts and ACKs. No event-loop blocking while model runs.
- Status refresh/listing retrieves persisted runs after restart; newest-first history is paginated, not held solely in memory. Accept-with-strike refreshes the task card with returned detail. Revision creates a new run; cancellation shows actual returned state.

- [x] Write UI tests for whole task, both fields, duplicate points, pages 0/1/last with 90 points, unique IDs and row/label/custom-ID limits.
- [x] Add interaction tests for research/draft creation, revision parent, cancellation, result history and acceptance; assert private-channel validation precedes result reads/sends.
- [x] Add delivery tests for expired initial interaction, bot restart, lost ACK, source preservation, Unicode and oversized output; assert regular bot sends and stable run/part nonce.
- [x] Run `python -m unittest tests.test_discord_agent_ui -v`; confirm intended failures, implement modules/integration and rerun to pass.
- [x] Run `python -m unittest tests.test_discord_bot tests.test_discord_ui tests.test_discord_agent_ui -v`; expect passing tests and commit.

### Task 6: Deploy wiring, documentation and final verification

**Files:** Modify `.github/workflows/deploy.yml`, `docs/discord-assistant.md`, `backend/tests/test_discord_deploy.py`; update plan checkboxes as work passes.

**Interfaces:** Workflow passes `DISCORD_AGENT_MODEL` to `configure_discord.py`, defaulting to the requested model, and discovers all `test_discord*.py` tests instead of omitting new modules. Existing Celery worker/beat and single Discord worker remain the deployed process topology.

- [x] Add deploy tests asserting model propagation, 30-second job schedule, required new modules included in test discovery, and no extra worker process.
- [x] Run `python -m unittest tests.test_discord_deploy -v`; confirm failures, implement wiring and document commands, permissions, lifecycle, storage, model, no application budget, acceptance and ambiguous-submission recovery.
- [x] Install existing pinned requirements in an isolated local environment if needed; do not change the dependency pins just to accommodate a test host. Document any unavailable dependencies.
- [x] Run `python -m unittest discover -s tests -p "test_discord*.py" -v` and `python -m unittest tests.test_migration_graph -v` from `backend`; require all relevant tests executed, not skipped for missing Discord dependencies.
- [x] With test-only `DATABASE_URL`/`JWT_SECRET`, import the complete ASGI app and run `alembic heads`; require successful import and a single `0149_discord_agent_runs` head. Use a disposable PostgreSQL database for migration round-trip if available; otherwise explicitly report that limitation.
- [x] Run `git diff --check`; inspect all mutations, state transitions, acceptance and startup/close hooks against the five Review Focus items and every spec section. Fix issues and rerun only affected checks plus the final Discord suite.
- [x] Commit the completed deliverable. Report changed behavior, checks and the remaining live-server migration/OpenAI/Discord smoke test; do not claim deployment or live verification.

## Handoff

Plan self-review: spec requirements map to Tasks 1–6; all five Review Focus cases have explicit tests. No new product dependencies, external messaging, database changes or paid API calls have been executed during planning.

Recommended execution: **Native**, implementing tasks sequentially in this session; shared lifecycle, ownership and delivery contracts benefit from one implementation context. A final independent review can follow if selected/authorized. Native implementation was authorized by the user and is complete. See the validation record for checks, review fixes and live-server limitations.
