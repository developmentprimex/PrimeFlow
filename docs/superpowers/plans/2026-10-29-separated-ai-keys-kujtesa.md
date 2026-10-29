# Separate AI keys and manual Kujtesa meetings implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the independent credential routing and bot runtime tasks. The coordinator implements the private API and handles secrets and integration.

**Goal:** Isolate three user-supplied AI credentials and let Kujtesa lead a manually started private family conversation.

**Architecture:** Explicit server credential selection, private family bridge endpoints and a separate bot controller using the existing Node host worker. No family data enters work host services.

**Tech Stack:** Python/FastAPI, Pydantic/SQLAlchemy, discord.py/aiohttp, existing Node Discord Realtime worker, GitHub Actions encrypted secrets.

**Spec:** `docs/superpowers/specs/2026-10-29-separated-ai-keys-kujtesa.md`.

## Constraints and review focus

- Never commit or log credential values. Role keys have no cross-role fallback.
- Keep staged changes in the original checkout untouched; this worktree includes the migration prerequisite.
- Voice starts only by command, requires an active family administrator and private channel; unknown participants stop it.
- Recheck revocation and configuration changes; never automatically complete family tasks.
- Stop during startup must not leave a worker alive; duplicate commands cannot create two workers.

## Task 1: Credential routing and deployment

- [x] Add failing tests of real HTTP headers for notes, host Realtime/background summaries and general recording analysis; missing role keys fail closed.
- [x] Add settings, explicit request scopes, role-specific capability gates; update existing fixtures to use synthetic dedicated credentials.
- [x] Pass the three secrets through Actions and write dotenv via `scripts/configure_discord.py`; document names without values.
- [x] Run focused provider/host/desktop/recording/configuration tests and review.

## Task 2: Private family host API

- [x] Test `/ga-personal/bridge/host/context` and `/host/start` authorization, revoked grant, invalid guild/member, private task context, dedicated key and provider failures.
- [x] Implement `app/services/kujtesa_host.py` and `app/schemas/kujtesa_host.py`, register endpoints in `ga_personal_discord.py`.
- [x] Request payload: `actor_id`, `guild_id`, `channel_id`, `present_user_ids` (all snowflake strings). Context response: `guild_id`, `allowed_user_ids`, `participants` (`person`, `name`, `discord_user_id`, `tasks` with `title`, `status`, `due_at`), `instructions`, `model`. Start adds `client_secret` only, marked private/no-store by the existing PrivateRoute. The same authorization is run for context refresh.
- [x] Use `KUJTESA_OPENAI_API_KEY` only; no database mutations or work-table access. Allow administrator start only and mapped active participants. Reuse family occurrence selection without generating or changing tasks.
- [x] Realtime instructions: Albanian, kind brief rounds, review only today's supplied tasks, listen and ask for clarification; no invented facts or automatic task changes. Tools: `wait_for_user`, `finish_meeting` only.

## Task 3: Kujtesa manual bot host

- [x] Test manual command registration, authorization payload, private voice permissions, unknown join, startup cancellation, duplicate starts, shutdown and timeout with synthetic transports.
- [x] Create `integrations/kujtesa/voice_host.py`; wire optional `host_enabled` (default false), `host_worker` path, `node_binary` into `KujtesaBridge`. Main uses `KUJTESA_HOST_ENABLED=1`, `KUJTESA_HOST_WORKER`, `KUJTESA_VOICE_NODE_BINARY`. No automatic joins or dependency on reminder delivery flag.
- [x] Use bridge endpoints from Task 2; raw bot Discord token goes only into worker stdin and client_secret is ephemeral. Start data: `type=start`, `guild_id`, `channel_id`, `token`, `client_secret`, `model`; handle `ready`, `interrupted`, `process_exit`, `tool_call`. Say the context instructions after ready; handle `wait_for_user` and `finish_meeting`; do not log transcript or request secrets. Recheck `/host/context` every 30 seconds and stop on denied/changed config.
- [x] Document manual setup and test instructions. Reuse the existing `backend/discord-voice/host-worker.mjs` via a configured absolute path, no copied work bot code or token.

## Task 4: Secrets and integration

- [x] Encrypt and upload three dedicated GitHub Actions secrets; validate credentials without printing them or making paid generation requests.
- [x] Update ignored local backend dotenv and external bot installation using approved filesystem access; preserve reminders disabled.
- [x] Run combined relevant tests, migration/MCP tests, compile checks, secret scanning and independent review; resolve findings.
- [x] Commit/push feature branch and prepare a reviewable draft PR. Report precisely what is configured, locally installed, and still awaiting deployment.

## Execution ledger

- User supplied credentials, requested role isolation and specified manual Discord starts for Kujtesa. Implementation decisions follow existing server/bot boundaries; no main merge or unsolicited Discord messages.

- Credential routing, private API and manual bot host completed and independently reviewed. Final focused regression: 185 passed, 15 skipped, 40 subtests passed. Full backend comparison: base 1566 vs feature 1619, identical 18 failures and 16 errors with 184 skipped; all failing IDs recorded in ai-keys-kujtesa-validation.md.
- Three supplied API keys verified with read-only models requests and encrypted into Actions secrets. Existing matching family bridge secret provisioned; local adapter files and manual-host switches installed without starting a process, sending messages or changing delegation.
- Runtime choice: mapped family joins/leaves and task edits silently refresh the live conversation within 30 seconds. An initiating admin leaving still stops the meeting immediately.
- Code will be delivered in a draft PR; production merge and a live manual conversation remain separate.
