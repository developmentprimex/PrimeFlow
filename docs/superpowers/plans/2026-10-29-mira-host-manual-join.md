# Mira Host: enter 1H on command

User request: Mira Host enters the team's Discord 1H channel when commanded.

Implement `/mira hyr sloti:<1H slot>` for linked admins/managers. It starts the selected slot immediately in the configured 1H voice channel, without enabling the day's scheduler. `/mira ndalo` stops it. Keep existing daily scheduling, meeting history and one-held-meeting-per-day/slot rules. Report success only after the Discord voice connection is ready; show permission/configuration/startup errors to the caller. Do not send live commands or deploy during development.

- [x] Add failing controller/API tests for immediate entry, single-session concurrency, role checks, manual start while daily hosting is disabled, and unchanged scheduled authorization.
- [x] Extend the existing start bridge with an authenticated manual caller; prepare its session before launching the worker.
- [x] Add manual joining and the slash command, reusing channel resolution, connection retries and meeting lifecycle. Set manual start time to now, not the scheduled hour.
- [x] Verify the command waits for connection readiness and surfaces startup failure; prevent the scheduler from racing manual startup.
- [x] Document command usage and run focused backend tests, voice regressions and diff checks.

No database migration, provider change, task permission change, or modification of unrelated staged work.

Verification: 86 focused backend tests and 2 subtests passed; entire voice package 50 tests passed; `git diff --check` passed. Independent read-only review found a cancellation race during connection retry/API wait. Two subcases reproduced it before the fix; cancellation checks now prevent another worker from starting after stop. No remaining review findings. No live Discord commands, notifications or deployment were performed. Existing full-backend collection blockers remain documented in the fast-conversation plan.
