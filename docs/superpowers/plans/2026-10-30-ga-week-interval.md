# Household week interval implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this single task with a failing test, minimal implementation, and final review.

**Goal:** Persist and execute selected-weekday recurrences every N calendar weeks without changing ordinary schedules.

**Architecture:** Extend the existing private template JSON and the shared scheduling predicate. Export interval schedules as dated tablet occurrences. Expose the interval and anchor in the existing editor.

**Tech Stack:** Python, Pydantic, SQLAlchemy, React/TypeScript.

**Spec:** `docs/superpowers/specs/2026-10-30-ga-week-interval-design.md`

## Global constraints

Europe/Belgrade calendar dates; optional clocks remain off; preserve existing definitions and occurrence identity; no private household source text in Git.

## Review focus

- Legacy imported definitions lack new fields: normal generation/import must remain valid.
- Never generate before the anchor or in an intervening week.
- A late-week anchor must not move the whole calendar-week phase.
- Tablet clients must not invent a weekly repeat from a multi-week rule.
- Changing the frequency in the editor must clear incompatible interval settings.

## Task 1: Anchored interval support

Files: `backend/app/schemas/ga_personal.py`, `backend/app/services/ga_personal.py`, `backend/app/services/ga_personal_device_sync.py`, `backend/tests/test_ga_personal_week_interval.py`, `frontend/src/lib/ga-personal.ts`, `frontend/src/app/(app)/ga-personal/page.tsx`.

- [x] Write tests of schema validation, schedule dates across week/year/DST boundaries, legacy definitions, and dated untimed tablet export; observe failures.
- [x] Add default interval 1 and optional anchor fields, validation, and a calendar-week gate before normal frequency checks.
- [x] Force concrete tablet export for interval schedules and expose/preserve both fields in the template editor; reset on frequency changes.
- [x] Run the new tests and existing GA PERSONAL suites against a disposable local test database, plus frontend type checking.
- [ ] Review, commit, deploy, then activate the separately stored private recurrence and verify actual generated dates/owners/no alarms/idempotence.

Validation: 89 checks passed in the combined household/device/migration run; its new database fixture lacked the reused authentication helper, which was corrected. The complete 9-test interval suite, including actual database generation, then passed. Frontend TypeScript check and git diff whitespace check passed.

Final read-only review found no Critical/Important issue. Its minor API documentation omission is documented above. Existing occurrence snapshots are intentionally retained; actual tablet rendering is outside this server change, while the exported dated-card contract is verified. Deployment and private activation are the remaining release steps.

Browser validation: 2 task-creation/persistence checks passed. The existing persistence assertion expected article cards after reload, but the current default view is a weekly table; the assertion now checks the visible task text across both views. No application behavior was changed for that test correction.
