# Mira meeting flow corrections

> **For agentic workers:** Use superpowers:executing-plans to implement these bug fixes in order.

**Goal:** Read existing Notes without a permission pause, pronounce codes in Albanian, and continue past absent staff.

**Architecture:** Keep the existing Python controller/service and Realtime worker. Supply speech-ready text separately from source data; enforce presence transitions in code. Keep gpt-realtime-2.1, confirmation requirements for writes, and test/real meeting isolation.

**Tech Stack:** Python asyncio, SQLAlchemy, Node Realtime voice worker.

**Spec:** User's four reported meeting problems in this conversation; existing meeting control and TEST MODE behavior.

## Tasks

- [x] Notes: reproduce the permission-pause contract with service/worker tests; return first-note reading and explicit next action; force the reading response without tools; update prompt/tool description.
- [x] Speech: add Albanian letter names for known codes and person initials; provide phonetic reading fields while preserving source titles and IDs; update prompt with pace and pronunciation examples; verify titles, Notes, progress and proposal reading.
- [x] Presence: reproduce absent waiting/current staff; atomically defer absent waiting turns and select present staff, retaining original order among those present. Distinguish unlinked identities from verified absence; bypass presence filtering in TEST MODE. Announce skipped names, retain deferred turns for later arrivals, and finish promptly when no one remains.
- [x] Verify related backend and full voice suites, inspect broader backend test discovery, request independent review, and document runtime activation and voice-listening limits.

## Review focus

- No staff presence check may skip simulated test participants.
- Missing staff remain DEFERRED, never DONE; unknown Discord identity is not proof of absence.
- A delayed handoff must reconcile server state without ending the next person twice.
- Speech formatting must not change source task titles, saved dictations, assignment IDs, or confirmation arguments.
- A forced note reading must not bypass a fresh, identified GA confirmation for task creation.


## Verification results

Related backend suite: 208 tests run, 194 passed and 14 skipped.
Full voice suite (`npm.cmd test`): 76 passed.
Independent review: no remaining Important findings after the lost-handoff-reply regression was fixed.

Full backend discovery, with the repository root on PYTHONPATH:

```text
Ran 1889 tests in 94.760s

FAILED (failures=20, errors=17, skipped=254)
```

The full backend is not green. These failures are outside the changed Mira Host modules; no claim is made that this run proves a clean baseline. The test import-path problem from the first discovery run was corrected for this final run. Failed tests and error cases are listed below.

- **ERROR** `test_daily_report_system_occurrence_filter (unittest.loader._FailedTest.test_daily_report_system_occurrence_filter)`
- **ERROR** `test_default_filters_inactive (test_list_tasks_inactive_filter.TestListTasksInactiveFilter.test_default_filters_inactive)`
- **ERROR** `test_include_inactive_true_skips_filter (test_list_tasks_inactive_filter.TestListTasksInactiveFilter.test_include_inactive_true_skips_filter)`
- **ERROR** `test_added_morning_table_preserves_original_and_accepts_comments_for_new_tasks (test_m2_reporting_points.ReportPersistenceTests.test_added_morning_table_preserves_original_and_accepts_comments_for_new_tasks)`
- **ERROR** `test_postponement_comments_save_and_export_without_affecting_delivery_answers (test_m2_reporting_points.ReportPersistenceTests.test_postponement_comments_save_and_export_without_affecting_delivery_answers)`
- **ERROR** `test_saving_answers_merges_and_rejects_task_from_another_report (test_m2_reporting_points.ReportPersistenceTests.test_saving_answers_merges_and_rejects_task_from_another_report)`
- **ERROR** `test_delivery_answers_save_only_for_report_tasks (test_m3_delivery.DeliveryAnswerTests.test_delivery_answers_save_only_for_report_tasks)`
- **ERROR** `test_scheduler_regenerates_sections_before_sending (test_morning_report_workflow.MorningReportWorkflowTests.test_scheduler_regenerates_sections_before_sending)`
- **ERROR** `test_department_and_note_editors_move_the_same_daily_row_to_pm (test_note_task_finish_period_sync.TestNoteTaskFinishPeriodSync.test_department_and_note_editors_move_the_same_daily_row_to_pm) (source='GA_KA', editor='note', status=<TaskStatus.TODO: 'TODO'>)`
- **ERROR** `test_department_and_note_editors_move_the_same_daily_row_to_pm (test_note_task_finish_period_sync.TestNoteTaskFinishPeriodSync.test_department_and_note_editors_move_the_same_daily_row_to_pm) (source='GA_KA', editor='note', status=<TaskStatus.IN_PROGRESS: 'IN_PROGRESS'>)`
- **ERROR** `test_department_and_note_editors_move_the_same_daily_row_to_pm (test_note_task_finish_period_sync.TestNoteTaskFinishPeriodSync.test_department_and_note_editors_move_the_same_daily_row_to_pm) (source='PX_JAV', editor='note', status=<TaskStatus.TODO: 'TODO'>)`
- **ERROR** `test_department_and_note_editors_move_the_same_daily_row_to_pm (test_note_task_finish_period_sync.TestNoteTaskFinishPeriodSync.test_department_and_note_editors_move_the_same_daily_row_to_pm) (source='PX_JAV', editor='note', status=<TaskStatus.IN_PROGRESS: 'IN_PROGRESS'>)`
- **ERROR** `test_creates_control_linked_by_product_id (test_pcm_control_auto_creation.TestPcmControlAutoCreation.test_creates_control_linked_by_product_id)`
- **ERROR** `test_new_control_gets_ko_prefix_and_existing_control_stays_unchanged (test_pcm_control_title_creation.TestPcmControlTitleCreation.test_new_control_gets_ko_prefix_and_existing_control_stays_unchanged)`
- **ERROR** `test_list_system_tasks_includes_templates_without_generated_rows (test_system_tasks_list_generated_only.TestSystemTasksListGeneratedOnly.test_list_system_tasks_includes_templates_without_generated_rows)`
- **ERROR** `test_list_system_tasks_with_occurrence_date_excludes_previous_occurrence_templates (test_system_tasks_list_generated_only.TestSystemTasksListGeneratedOnly.test_list_system_tasks_with_occurrence_date_excludes_previous_occurrence_templates)`
- **ERROR** `test_any_authenticated_staff_user_can_update_a_one_h_marker (test_task_update_permissions.TestTaskUpdatePermissions.test_any_authenticated_staff_user_can_update_a_one_h_marker)`
- **FAIL** `test_confirmation_table_includes_category_column (test_after_break_confirmation_category.AfterBreakConfirmationCategoryTests.test_confirmation_table_includes_category_column)`
- **FAIL** `test_new_system_tasks_include_department_and_finish_period (test_after_break_confirmation_category.NewSystemTaskRowsTests.test_new_system_tasks_include_department_and_finish_period)`
- **FAIL** `test_deployed_revision_is_recognized_and_is_the_single_head (test_deployed_ga_note_migration.DeployedNoteMigrationTests.test_deployed_revision_is_recognized_and_is_the_single_head)`
- **FAIL** `test_worker_selection_excludes_frontend_and_other_workspaces (test_discord_voice_dependency_install.VoiceDependencyInstallTests.test_worker_selection_excludes_frontend_and_other_workspaces)`
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

The full output is retained in `tmp/mira-flow-backend-tests.log`. No production meeting or paid Realtime session was started; pronunciation and pace still require a listening check after deployment. These changes are local and require backend/controller restart. No new migration is required.
