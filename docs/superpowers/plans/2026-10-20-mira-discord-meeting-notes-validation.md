# Mira meeting notes: validation and rollout

Implementation follows the approved design and native execution plan. The
feature remains opt-in (`DISCORD_MEETING_NOTES_ENABLED=false` by default).
No real Discord voice channel was joined and no meeting audio was sent to
OpenAI during development.

## Verified locally

- `python -m unittest discover -s tests -p 'test_discord*.py'`: **199 passed**.
  `VOICE_TEST_DATABASE_URL` pointed only at a disposable PostgreSQL 17 instance
  on localhost:55439. These tests cover the existing bot and the new feature.
  The same **199 tests also passed with `DISCORD_MEETING_NOTES_ENABLED=true`**;
  the legacy command-registration fixture explicitly tests the feature-off
  command set, while the new fixture verifies the enabled `/takimi` group.
- `python -m unittest tests.test_ga_note_creation tests.test_speech_transcribe tests.test_migration_graph`:
  **17 passed**. Project-bound ordinary Note creation is covered as well as
  meeting Note creation.
- `node --test backend/discord-voice/tests/*.test.mjs`: **9 passed**.
- `python scripts/check_discord_voice.py --install` with the feature enabled:
  locked install, Node version check, DAVE/Opus imports and Node tests passed
  on Windows with Node 24.13.0. This command does not connect to Discord.
- Complete ASGI application imports successfully and includes all 11 meeting
  bridge routes. `git diff --check` passed.
- Real PostgreSQL tests verify concurrent start serialization, concurrent save
  creating exactly one Note, transcript deduplication/conflicting replay,
  chronological summaries, interrupted-session recovery, and the actual frozen
  Alembic migration matching model columns/indexes.
- Regression tests were observed failing before fixes for stop failure,
  startup/process-spawn cancellation, malformed Gateway messages, dead-child
  leave cleanup, long Opus frames and packet gaps exceeding wall-clock limits.
- A separate reviewer inspected the complete change. Reported project Note
  import, stop failure wedge and wall-span issues were fixed. The reviewer
  independently reran the 13 lifecycle and 9 Node tests and found no remaining
  immediately related Critical/Important issues.
- Activation verification also exercises the installed discord.py Gateway
  dispatch: `debug_log_receive` emits `socket_raw_receive`, not the obsolete
  `socket_response` event. The bot now consumes that real hook, parses only
  voice dispatches and ignores other/invalid packets. The regression failed
  before the hook correction and passed afterward. The enabled suite then ran
  201 tests successfully (eight PostgreSQL tests skipped after the disposable
  database was stopped; their earlier real-database run passed).

## Broader existing test state

The full backend `pytest -q` cannot collect
`tests/test_daily_report_system_occurrence_filter.py`: it imports the absent
`_acted_on_report_day_in_tirana` from the unchanged reports router.

Excluding that file, the initial broad run produced 1,894 passes, 37 failures,
one skip and 121 passing subtests. Three failures exposed a missing column in
the new migration snapshot; it was corrected and the PostgreSQL migration and
full Discord tests were rerun green. Two failures came from missing frontend
dependencies in the isolated worktree; those five tests passed when Node
resolved the existing frontend dependencies via `NODE_PATH`.

The remaining 32 failures were reproduced against the unchanged base checkout:
28 failures across report/status/frontend contract tests and four task
classification subtest failures. Their source files were not changed for this
feature. The project-wide suite is therefore **not claimed green**.

## Rollout / live acceptance still pending

1. Set repository variable `DISCORD_MEETING_NOTES_ENABLED=true` and run deploy.
   Node >=22.12 and the existing Discord/OpenAI credentials must be available.
2. Deliberately start a test meeting with `/takimi fillo` from the organizer's
   linked personal channel after joining an ordinary voice channel.
3. Verify the visible notice appears before capture, the bot stays muted and
   two people speaking Albanian (including overlap) are transcribed. One person
   should leave/rejoin to exercise real DAVE transitions.
4. `/takimi mbaro` must disconnect audio promptly. Check the private notes,
   source attribution, any partial warnings and decisions against what was said.
5. Save twice; confirm one Note in PX Notes and no shared-channel disclosure.

Live audio reception, production DAVE behavior and transcript quality are not
proven by mocked/local tests. The feature was not activated or used to record
staff automatically. Audio is temporary; only transcript/draft data persists.
