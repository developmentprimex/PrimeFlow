# GA weekly filters and recurring task visibility

> Use superpowers:executing-plans for inline implementation.

**Goal:** Keep weekly status controls available with empty results and show configured recurring tasks beyond the worker's rolling 14-day window.

**Architecture:** Place the weekly toolbar outside the conditional table. Load the selected calendar week through a bounded occurrence query; prepare only opted-in automatic occurrences for today/future days using the existing serialized, idempotent generator. Preserve conditional rules, history, snapshots and member isolation.

**Requirements:** User screenshots and report, 2026-11-02. No recurrence end date was intended.

## Task 1: Persistent status controls
- [x] Add a browser regression that filters the weekly table to zero results, switches filters, and clears the filter without losing the legend.
- [x] Observe failure, move the toolbar to the page, and verify the regression.

## Task 2: Selected-week loading and recurrence preparation
- [x] Add database regressions for a future week, repeat reads, member access, paused automation, conditional rules, invalid ranges and more than 500 weekly rows.
- [x] Observe failures, add a validated inclusive range of at most seven days and automatic preparation respecting the existing configuration.
- [x] Load the selected week when navigating; reject stale responses and preserve session/draft state. Add browser navigation and request-race regressions.
- [x] Run the household backend suites, browser suite and TypeScript check, then review the diff.

## Review focus
Paused automation and dates before today must not create occurrences. Repeated or concurrent reads must preserve occurrence identity. Conditional and school-day inputs must never be inferred. Date navigation must not clear drafts or allow old responses to replace the selected week. A bounded week must not be truncated by the unbounded history limit.

## Verification results

- New four database regressions failed before the implementation and passed afterward, including canonical compact date inputs.
- Combined backend command: `python -m unittest tests.test_ga_personal tests.test_ga_personal_dataset_v2 tests.test_ga_personal_week_interval tests.test_ga_personal_devices tests.test_ga_personal_week_window -q`: **79 passed**, using the existing disposable local PostgreSQL server and generated private test schemas.
- New browser checks: **4 passed** (empty status filter, distant-week navigation, stale responses, preserving the table during background access checks).
- Full browser command: `playwright test --config playwright.ga-personal.config.ts --timeout 15000`: **21 passed, 6 failed**. These existing checks refer to removed daily article cards or the old legend label; those selectors already disagree with the baseline source. The failing test names are:
  - `the task card edits time and assignee for only this occurrence`
  - `the task card can explicitly apply a schedule change to future recurrences`
  - `an existing task can route its reminders to the family channel`
  - `new tasks use the selected day and saving follows a changed date`
  - `completing one person's occurrence preserves the other and the mobile layout fits`
  - `personal duties share a row with independent people, full hover titles and source legend`
- TypeScript `tsc --noEmit` passed. `git diff HEAD --check` passed.
- Independent code review found two issues, both corrected: blocking loading during background polling, and string range comparisons using noncanonical input dates.
- No deployment or production data changes were performed.
