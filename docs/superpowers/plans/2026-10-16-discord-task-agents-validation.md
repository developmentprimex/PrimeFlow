# Discord task agents: validation record

Implemented on `feat/discord-task-agents`, based on `a84190c9`.

## Verification

- `python -m unittest discover -s tests -p "test_discord*.py" -v`: **110 passed**, no skips.
- `python -m unittest tests.test_migration_graph`: **6 passed**.
- Complete FastAPI application imports; 8 agent routes are registered.
- Alembic has one head: `0149_discord_agent_runs`; new migration DDL is exercised offline.
- Full backend unittest discovery: **976 tests**, **18 failures, 6 errors** outside this feature. Same suite from the base archive has the same 24 failing/error cases (plus one archive-only frontend-path error). **No new failing/error case** appears in the implementation.
- Existing dependency pins are unchanged; verification uses a temporary isolated Python environment with test-only database/JWT settings. OpenAI and Discord calls are mocked.
- No live OpenAI/Discord requests or production migrations/deployments were performed. A disposable PostgreSQL server was unavailable (Docker engine unavailable), so a real migration round-trip and real transaction/lock concurrency remain unverified.

## Independent review and fixes

A separate read-only reviewer inspected the entire branch. No Critical findings.

1. Important: late submission could lose its response ID after its lease expired. Fixed with lease-independent ID persistence, durable cleanup identity (including terminal rows), and an atomic local recovery spool before database persistence. Provider cancellation timeouts leave cleanup retryable; a database outage leaves ID-only recovery files for the next worker tick. Existing completed results are preserved. Four regression tests were observed failing before the implementation and passing after it.
2. Removed point acceptance returned HTTP 500. Regraded from Minor to Important because ordinary task edits must produce an actionable version conflict. Fixed to return HTTP 409 before any mutation; a regression test was observed failing before and passing after the fix.

Final focused and complete Discord suites were rerun after these fixes; no second reviewer dispatch was used.

## Decisions and review boundaries

- Used a dedicated feature branch in the existing checkout instead of another worktree, following the repeated request to implement in the shared workspace. Cost: concurrent edits are not isolated; the working tree was checked throughout.
- Used native Windows commands for the execution ledger because the skill helper scripts assume a POSIX shell. Cost: bookkeeping is maintained directly; test results and per-task commits remain the evidence.
- Added internal `cleanup_response_id` and ignored `backend/.discord-agent-recovery/` files to persist late provider IDs even during a database outage. These contain run/lease/response IDs only, with no API keys, prompts or results. Cost: Celery needs write access to that directory and recovery files must survive worker restarts/deploys.
- Normal cancellation races, ambiguous submissions without IDs, duplicate/reordered points, lost ACKs and long output were judged covered by the inspected implementation/tests; the review found no additional blocker there.
- Offset history pages may shift when new runs arrive; processing is oldest-first with bounded batches. Kept the planned approach: history remains persisted and can be refreshed; throughput tuning can follow measured demand. Cost: page boundaries may change and large queues may wait.
- Existing task API mutation concurrency and unrelated backend failures were left at baseline behavior. Cost: this branch does not repair those existing issues.
- Live model/account compatibility, Discord permissions and live migration execution remain deployment checks, not locally verified claims.
- Deferred minor code findings: none.

## Existing backend failures/errors, by test name

- **ERROR** `test_daily_report_system_occurrence_filter (unittest.loader._FailedTest.test_daily_report_system_occurrence_filter)`
- **ERROR** `test_default_filters_inactive (test_list_tasks_inactive_filter.TestListTasksInactiveFilter.test_default_filters_inactive)`
- **ERROR** `test_include_inactive_true_skips_filter (test_list_tasks_inactive_filter.TestListTasksInactiveFilter.test_include_inactive_true_skips_filter)`
- **ERROR** `test_scheduler_regenerates_sections_before_sending (test_morning_report_workflow.MorningReportWorkflowTests.test_scheduler_regenerates_sections_before_sending)`
- **ERROR** `test_list_system_tasks_includes_templates_without_generated_rows (test_system_tasks_list_generated_only.TestSystemTasksListGeneratedOnly.test_list_system_tasks_includes_templates_without_generated_rows)`
- **ERROR** `test_list_system_tasks_with_occurrence_date_excludes_previous_occurrence_templates (test_system_tasks_list_generated_only.TestSystemTasksListGeneratedOnly.test_list_system_tasks_with_occurrence_date_excludes_previous_occurrence_templates)`
- **FAIL** `test_confirmation_table_includes_category_column (test_after_break_confirmation_category.AfterBreakConfirmationCategoryTests.test_confirmation_table_includes_category_column)`
- **FAIL** `test_new_system_tasks_include_department_and_finish_period (test_after_break_confirmation_category.NewSystemTaskRowsTests.test_new_system_tasks_include_department_and_finish_period)`
- **FAIL** `test_settings_routes_require_admin (test_meetings_report_workflow.MeetingsReportWorkflowTests.test_settings_routes_require_admin)`
- **FAIL** `test_edited_auto_title_keeps_m1_identity_position_and_group (test_morning_report_workflow.MorningReportWorkflowTests.test_edited_auto_title_keeps_m1_identity_position_and_group)`
- **FAIL** `test_email_html_is_mobile_safe_and_contains_m1_heading (test_morning_report_workflow.MorningReportWorkflowTests.test_email_html_is_mobile_safe_and_contains_m1_heading)`
- **FAIL** `test_normalization_drops_duplicate_near_match_email_section (test_morning_report_workflow.MorningReportWorkflowTests.test_normalization_drops_duplicate_near_match_email_section)`
- **FAIL** `test_normalization_keeps_all_six_m1_questions_and_saved_edits (test_morning_report_workflow.MorningReportWorkflowTests.test_normalization_keeps_all_six_m1_questions_and_saved_edits)`
- **FAIL** `test_normalization_removes_retired_task_status_prompt (test_morning_report_workflow.MorningReportWorkflowTests.test_normalization_removes_retired_task_status_prompt)`
- **FAIL** `test_normalization_renames_the_previous_notes_section (test_morning_report_workflow.MorningReportWorkflowTests.test_normalization_renames_the_previous_notes_section)`
- **FAIL** `test_normalization_splits_legacy_notes_emails_into_manual_section (test_morning_report_workflow.MorningReportWorkflowTests.test_normalization_splits_legacy_notes_emails_into_manual_section)`
- **FAIL** `test_saved_m1_content_can_be_edited (test_morning_report_workflow.MorningReportWorkflowTests.test_saved_m1_content_can_be_edited)`
- **FAIL** `test_settings_routes_require_admin (test_morning_report_workflow.MorningReportWorkflowTests.test_settings_routes_require_admin)`
- **FAIL** `test_mst_title_known_total_no_progress (test_project_display_title.TestProjectDisplayTitle.test_mst_title_known_total_no_progress)`
- **FAIL** `test_trailing_total_is_normalized (test_project_display_title.TestProjectDisplayTitle.test_trailing_total_is_normalized)`
- **FAIL** `test_project_like_pcm_titles_are_not_fast (test_task_classification.TestTaskClassification.test_project_like_pcm_titles_are_not_fast) (title='MST OTTO - MR 370')`
- **FAIL** `test_project_like_pcm_titles_are_not_fast (test_task_classification.TestTaskClassification.test_project_like_pcm_titles_are_not_fast) (title='TT - Something')`
- **FAIL** `test_project_like_pcm_titles_are_not_fast (test_task_classification.TestTaskClassification.test_project_like_pcm_titles_are_not_fast) (title='VS/VL PROJEKT I MADH - X')`
- **FAIL** `test_project_like_pcm_titles_are_not_fast (test_task_classification.TestTaskClassification.test_project_like_pcm_titles_are_not_fast) (title='VS VL PROJEKT I MADH - X')`
