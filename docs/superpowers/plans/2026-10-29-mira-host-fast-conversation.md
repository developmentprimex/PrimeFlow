# Mira Host Fast Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Mira Host ask direct, current-slot-first questions and remove avoidable response stalls.

**Architecture:** Keep the existing Python controller/API and Node Realtime worker. Improve the per-task context and instructions, then make tool-result continuation independent of event arrival order.

**Tech Stack:** Python, FastAPI, existing OpenAI Realtime integration, Node.js, unittest/pytest and node:test.

**Spec:** `docs/superpowers/specs/2026-10-29-mira-host-fast-conversation-design.md`

## Global Constraints

- Await design/plan approval before implementation; execute in this session unless the user requests delegation.
- Preserve unrelated staged work already present on `main`, including `backend/app/config.py`.
- No model/provider switch, new dependency, database migration, deployment, or live staff messages.
- Preserve GA announcement deduplication, 11:50 earlier-slot coverage, PM review, and 16:00 blocked tasks.
- Use medium semantic VAD eagerness with custom interruption handling preserved.

## Review Focus

- A tool result arrives before `response.done`: one continuation, without a stall.
- Several results arrive across `response.done`: wait for all and continue once.
- GA already announced a strike: staff context still knows progress occurred.
- A person gives reason, continuation time, and completion time in one answer: ask none of those again.
- The same task occurs in current and previous groups: discuss it once.

### Task 1: Current-first task context and direct dialogue

**Files:** `backend/app/services/mira_host.py`, `backend/mira_host.py`, `backend/tests/test_mira_host_service.py`, `backend/tests/test_mira_host_bot.py`.

**Interfaces:** Preserve `person_brief(...)`, `instructions(...)`, and `turn_brief(current)` consumers; add task-specific evidence to the existing handoff without removing compatibility fields. Distinguish report-window evidence from GA announcement deduplication.

- [x] Add failing backend tests for current-first handoff, previously announced strikes remaining visible as evidence, deduplicated task groups, and progress on one task not implying progress on another.
- [x] Run those tests and confirm failures reflect missing behavior.
- [x] Implement the handoff and progress evidence. Revise all contradictory previous-first instructions, including the controller handoff and the default protocol; preserve custom operational protocol text while explicitly setting conversation order.
- [x] Use short, varied Albanian examples and instructions to ask only missing questions. Keep completed-task and earlier-task handling consistent.
- [x] Verify backend host and notes regression tests.

### Task 2: Reliable tool continuation and quicker turn detection

**Files:** `backend/discord-voice/host-worker.mjs`, `backend/discord-voice/tests/host.test.mjs`, `backend/app/services/mira_host.py`, `backend/tests/test_mira_host_service.py`.

**Interfaces:** Preserve `createHost(...)`, `toolResult(callId, output)`, worker IPC, and the Realtime session schema.

- [x] Add failing worker tests for a tool result before response completion, results after completion, mixed arrival of several results, silence-only tools, and a queued system message competing with continuation.
- [x] Run the new tests and confirm the response stall reproduces.
- [x] Track a pending continuation and drain it once when the originating response has ended and all tools returned. Preserve interruption cancellation and silence semantics.
- [x] Change semantic VAD eagerness from low to medium and update its behavior/configuration test.
- [x] Run the full voice-worker test command and focused backend regressions. Record the known local missing-`opusscript` dependency separately if it remains unavailable.
- [x] Update `docs/discord-assistant.md` to describe the new current-first conversation and pacing.
- [x] Review the diff for contradictory instructions, unintended changes, and claims requiring a live voice check. Report test evidence and deployment status.

## Verification results

- Backend host, notes, Discord voice and 1H regression tests: **121 passed, 18 skipped, 7 subtests passed**. Skipped database integration tests were not exercised.
- Entire voice package (`npm test`): **50 passed**. Installed the existing npm lockfile; no dependency versions changed.
- `git diff --check`: passed.
- Independent read-only review found an automatic-response duplicate and missing blocked-only strike evidence. Both were reproduced with failing tests and corrected. The long-handoff truncation risk was also reproduced and corrected by preserving complete JSON within the worker's existing IPC size validation.
- Full backend `pytest` was attempted and stopped during collection in six unrelated modules:
  - `tests/serve_recordings_test.py`: missing `recording_test_support`.
  - `tests/test_daily_report_system_occurrence_filter.py`: missing `_acted_on_report_day_in_tirana` export.
  - `tests/test_meeting_recording_restart.py`: missing `recording_test_support`.
  - `tests/test_meeting_recordings_api.py`: missing `recording_test_support`.
  - `tests/test_mira_desktop_integration.py`: missing `backend` import path.
  - `tests/test_recording_analysis_api.py`: missing `recording_test_support`.
- No live calls, notifications, deployment, merge, or push. Changes remain reviewable on `codex/mira-fast-conversation`; unrelated staged work was preserved.
- A live Albanian Discord voice check is still needed after deployment to assess actual pacing, repetition, and model compliance. Automated tests do not prove human-like speech.
