# Kujtesa bridge implementation plan

> **For agentic workers:** Use superpowers:executing-plans for inline execution. The user selected the API bridge and requested implementation in this session.

**Goal:** Connect the existing separate Kujtesa bot to GA PERSONAL tasks, timings and confirmations.

**Architecture:** PrimeFlow owns occurrences, reminder scheduling, a private persistent outbox and authorization. The separate bot polls a narrowly scoped secret-authenticated bridge, sends channel/DM cards and returns verified interactions. Browser access still requires the existing login and extra password. An unlocked module administrator explicitly configures the delegation; no work Mira credentials or tables are reused.

**Tech stack:** FastAPI, SQLAlchemy/PostgreSQL, Pydantic, Next.js, discord.py/aiohttp.

**Spec:** User instructions in this conversation: dedicated existing bot; reminders at -5/0/+5 minutes, following changes to due time and owner; primary tasks in the configured channel, personal tasks in DMs; missing Discord IDs can be supplied later. Source bot: `C:/Users/01pri/OneDrive/Desktop/mira-project 1/mira-project/bot`.

## Global constraints

- Europe/Belgrade local dates; untimed tasks never send reminders.
- No outgoing messages in tests or automatic activation. Preserve REMINDERS_ENABLED=0.
- Existing live task history, passwords and work integrations are preserved.
- Keep bot tokens out of PrimeFlow; independent bridge secret stays server-side.
- Lirza's personal messages use Gane as the explicit adult contact.
- Interrupted/ambiguous Discord sends are visible and never blindly redelivered.

## Review focus

- Stale cards after reassignment cannot complete a different person's task.
- Acknowledgement changes do not regenerate reminder phases.
- Worker restart or API result retry cannot duplicate a claimed send.
- Missing/blocked DM recipients never cause fallback to a shared channel.
- Channel messages require the configured private guild channel; foreign actors/channels are rejected.

## Tasks

1. [x] Add backend tests for scoped bridge authentication/grant, -5/0/+5, rescheduling, deduplication, missing mappings and verified/idempotent button actions. Observe failures first.
2. [x] Add private outbox model and non-destructive migration; implement bridge settings, scheduler/claim/prepare/result/actions and message synchronization. Reuse the family-space transaction lock.
3. [x] Add settings UI and task destination selectors for recurring templates and current occurrences. Verify type/lint and browser flows.
4. [x] Add the distributable adapter in `backend/integrations/kujtesa`, test with synthetic API/Discord transports, install it into the provided external folder with filesystem approval, preserve the legacy code and disable its startup practice sends.
5. [x] Provision only the bridge configuration/secret locally with delivery disabled, apply only the isolated new table if needed, and run a read-only bot/API health handshake. Do not use the exposed token or send messages.
6. [x] Run migration/deploy and focused regression checks, review implementation, document activation and remaining external setup.

## Execution ledger

- Scope approved by user: API integration in both projects. Work in the existing requested workspace to preserve the running development environment; do not merge/push or restart Discord processes.
- Activation stays disabled until the operator has replaced the exposed Discord token and selected timings/destinations. The implementation is independently testable without Discord credentials.

- Completed 2026-10-29: 82 backend/adapter/migration/MCP tests passed, 14 synthetic browser tests passed, TypeScript and targeted ESLint passed. Initial failures were reproduced before their fixes.
- Independent review findings addressed with regression tests: unique schedule generations, usable snoozed cards, durable dirty-card acknowledgements, and retry backoff for unavailable messages.
- Installed the final adapter, dependency file, entry-point switch and instructions into the supplied bot folder, with a backup of its original entry point. Generated a separate private bridge key, configured the known IDs, and created only the private outbox. 31 existing live occurrences preserved; Alembic stamp untouched.
- Verified the installed adapter against the local API using --check: authenticated bridge OK, delegation disabled, no Discord connection or messages. Stopped the temporary API and test web server afterward.
- Operator activation remains separate: replace the exposed dedicated bot token locally, deploy API/frontend with the bridge key, grant access from unlocked GA PERSONAL settings, choose task times/destinations, and enable REMINDERS_ENABLED=1 in one bot process.
