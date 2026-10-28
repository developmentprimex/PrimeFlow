export type UserRole = "ADMIN" | "MANAGER" | "STAFF"

export type SkillRating = "A_PLUS" | "A" | "B" | "C"
export type SkillCategory =
  | "analysis"
  | "research"
  | "problem_solving"
  | "creativity"
  | "standards"
  | "qa"
  | "management"
  | "communication"
  | "fast_tasks"

export interface UserSkillsProfile {
  id?: string | null
  user_id: string
  exists: boolean
  analysis?: SkillRating | null
  research?: SkillRating | null
  problem_solving?: SkillRating | null
  creativity?: SkillRating | null
  standards?: SkillRating | null
  qa?: SkillRating | null
  management?: SkillRating | null
  communication?: SkillRating | null
  fast_tasks?: SkillRating | null
  above_average?: string | null
  experience?: string | null
  development?: string | null
  ideal_projects?: string | null
  motivation?: string | null
  completed_count: number
  is_complete: boolean
  completed_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface TeamSkillsMatrixItem extends UserSkillsProfile {
  name: string
  department_id?: string | null
  department?: string | null
}

export interface SkillRecommendation {
  rank: number
  user_id: string
  name: string
  department_id?: string | null
  department?: string | null
  category: SkillCategory
  rating: SkillRating
  score: number
}

export interface SkillCategoryInference {
  category: SkillCategory
  confidence: "high" | "medium" | "low"
  reason: string
  model: string
}

export type TaskType = "adhoc" | "system" | "reminder"

export type TaskPriority = "NORMAL" | "HIGH" | "BLLOK"

export type TaskFinishPeriod = "AM" | "PM"

export type TemplateRecurrence = "daily" | "weekly" | "monthly" | "yearly"

export type SystemTaskFrequency = "DAILY" | "WEEKLY" | "MONTHLY" | "YEARLY" | "3_MONTHS" | "6_MONTHS"
export type SystemTaskScope = "ALL" | "DEPARTMENT" | "GA"

export interface TaskAssignee {
  id: string
  email?: string | null
  username?: string | null
  full_name?: string | null
  department_id?: string | null
}

export interface SystemTaskTemplateAssigneeSlot {
  id: string
  primary_user_id: string
  is_active: boolean
}

export interface SystemTaskTemplateDefinition {
  id: string
  title: string
  description?: string | null
  internal_notes?: string | null
  department_id?: string | null
  department_ids?: string[] | null
  default_assignee_id?: string | null
  assignee_ids?: string[] | null
  zv1_user_id?: string | null
  zv2_user_id?: string | null
  assignees?: TaskAssignee[] | null
  assignee_slots?: SystemTaskTemplateAssigneeSlot[] | null
  scope: SystemTaskScope
  frequency: SystemTaskFrequency
  day_of_week?: number | null
  days_of_week?: number[] | null
  day_of_month?: number | null
  month_of_year?: number | null
  timezone?: string | null
  due_time?: string | null
  lookahead?: number | null
  interval?: number | null
  apply_from?: string | null
  duration_days?: number | null
  priority?: TaskPriority | null
  finish_period?: TaskFinishPeriod | null
  requires_alignment?: boolean | null
  alignment_time?: string | null
  show_in_weekly_planner?: boolean | null
  is_repetitive?: boolean | null
  alignment_roles?: string[] | null
  alignment_user_ids?: string[] | null
  status?: string | null
  is_active: boolean
  created_by_user_id?: string | null
  approval_status?: CommonApprovalStatus | null
  approved_by_user_id?: string | null
  approved_at?: string | null
  rejected_by_user_id?: string | null
  rejected_at?: string | null
  rejection_reason?: string | null
  created_at: string
}

export interface SystemTaskTemplate {
  id: string
  template_id?: string | null
  title: string
  description?: string | null
  internal_notes?: string | null
  department_id?: string | null
  department_ids?: string[] | null
  default_assignee_id?: string | null
  zv1_user_id?: string | null
  zv2_user_id?: string | null
  created_by?: string | null
  assignees?: TaskAssignee[] | null
  assignee_slots?: SystemTaskTemplateAssigneeSlot[] | null
  scope: SystemTaskScope
  frequency: SystemTaskFrequency
  day_of_week?: number | null
  days_of_week?: number[] | null
  day_of_month?: number | null
  month_of_year?: number | null
  occurrence_date?: string | null
  next_occurrence_date?: string | null
  effective_occurrence_date?: string | null
  priority?: TaskPriority | null
  finish_period?: TaskFinishPeriod | null
  start_date?: string | null
  due_date?: string | null
  requires_alignment?: boolean | null
  alignment_time?: string | null
  show_in_weekly_planner?: boolean | null
  is_repetitive?: boolean | null
  alignment_roles?: string[] | null
  alignment_user_ids?: string[] | null
  status?: string | null
  is_active: boolean
  user_comment?: string | null
  approval_status?: CommonApprovalStatus | null
  rejection_reason?: string | null
  created_at: string
}

export interface SystemTaskOut {
  id: string
  template_id: string
  title: string
  description?: string | null
  internal_notes?: string | null
  department_id?: string | null
  department_ids?: string[] | null
  default_assignee_id?: string | null
  assignees?: TaskAssignee[] | null
  scope: SystemTaskScope
  frequency: SystemTaskFrequency
  day_of_week?: number | null
  days_of_week?: number[] | null
  day_of_month?: number | null
  month_of_year?: number | null
  occurrence_date?: string | null
  next_occurrence_date?: string | null
  effective_occurrence_date?: string | null
  priority?: TaskPriority | null
  finish_period?: TaskFinishPeriod | null
  start_date?: string | null
  due_date?: string | null
  status?: string | null
  is_active: boolean
  user_comment?: string | null
  requires_alignment?: boolean | null
  alignment_time?: string | null
  show_in_weekly_planner?: boolean | null
  is_repetitive?: boolean | null
  alignment_roles?: string[] | null
  alignment_user_ids?: string[] | null
  created_by?: string | null
  approval_status?: CommonApprovalStatus | null
  created_at: string
}

export type CommonCategory =
  | "Delays"
  | "Absences"
  | "Annual Leave"
  | "Blocks"
  | "External Tasks"
  | "External Holiday"
  | "Problems"
  | "Complaints"
  | "Requests"
  | "Proposals"

export type CommonApprovalStatus = "pending" | "approved" | "rejected"

export type NotificationType =
  | "assignment"
  | "status_change"
  | "overdue"
  | "mention"
  | "reminder"

export interface User {
  id: string
  email: string
  username?: string | null
  full_name?: string | null
  role: UserRole
  department_id?: string | null
  is_active: boolean
  weekly_planner_sort_order?: number | null
  weekly_planner_hidden?: boolean
}

export interface UserLookup {
  id: string
  email: string
  username?: string | null
  full_name?: string | null
  role: UserRole
  department_id?: string | null
  is_active: boolean
  weekly_planner_sort_order?: number | null
  weekly_planner_hidden?: boolean
}

export interface Department {
  id: string
  code: string
  realization_mode?: "AUTO" | "SEMI_MANUAL" | "MANUAL"
  name: string
}

export interface Board {
  id: string
  department_id: string
  name: string
  description?: string | null
}

export interface Project {
  id: string
  title?: string
  display_title?: string | null
  name?: string
  description?: string | null
  department_id?: string | null
  manager_id?: string | null
  created_by?: string | null
  project_type?: string | null
  current_phase?: string
  status?: string
  progress_percentage?: number
  total_products?: number | null
  is_template?: boolean
  is_active?: boolean
  start_date?: string | null
  due_date?: string | null
  completed_at?: string | null
  created_at?: string
  updated_at?: string
  board_id?: string
}

export interface TaskStatus {
  id: string
  department_id: string
  name: string
  position: number
  is_done: boolean
}

export interface PxJavPlanningBrief {
  dl?: string | null
  lloji_det?: "1H" | "P" | "BLLOK" | "R1" | null
  dg?: boolean | null
  dg_kush?: string | null
  dg_kush_user_ids?: string[]
  hapat?: string | null
  kush?: string | null
  kush_user_ids?: string[]
  sq?: string | null
}

export interface Task {
  id: string
  is_active?: boolean
  skill_category?: SkillCategory | null
  department_id?: string
  board_id?: string
  project_id?: string | null
  dependency_task_id?: string | null
  title: string
  description?: string | null
  internal_notes?: string | null
  task_type?: TaskType
  status_id?: string
  position?: number
  assigned_to_user_id?: string | null
  planned_for?: string | null
  is_carried_over?: boolean
  carried_over_from?: string | null
  reminder_enabled?: boolean
  next_reminder_at?: string | null
  assigned_to?: string | null
  confirmation_assignee_id?: string | null
  assignees?: TaskAssignee[] | null
  created_by?: string | null
  ga_note_origin_id?: string | null
  plan_note_origin_id?: string | null
  planning_brief?: PxJavPlanningBrief | null
  system_template_origin_id?: string | null
  origin_run_at?: string | null
  system_task_slot_id?: string | null
  meeting_origin_id?: string | null
  meeting_occurrence_date?: string | null
  meeting_system_task_kind?: string | null
  status?: string
  priority?: string
  finish_period?: TaskFinishPeriod | null
  phase?: string
  progress_percentage?: number
  daily_products?: number | null
  start_date?: string | null
  due_date?: string | null
  original_due_date?: string | null
  planned_date?: string | null
  late_days?: number | null
  moved_days?: number | null
  completed_at?: string | null
  is_deadline_important?: boolean
  is_bllok?: boolean
  is_1h_report?: boolean
  one_h_report_slot?: string | null
  one_h_marker?: "EXCLAMATION" | "QUESTION" | "KA" | "GENT" | "FLAG" | "F" | "BZ1N1" | "M2" | "M3" | "M2_M3" | "MONITOR" | "CLOSE" | "CLIENT_URGENT" | "SHARE" | null
  one_h_marker_by_ga?: boolean
  one_h_marker_comment?: string | null
  is_r1?: boolean
  is_personal?: boolean
  fast_task_order?: number | null
  user_comment?: string | null
  alignment_user_ids?: string[] | null
  created_at: string
  updated_at: string
}

export interface TaskReview {
  id: string
  task_id?: string | null
  source?: "TASK" | "REALIZATION_PROPOSAL"
  realization_period_id?: string | null
  reviewee_user_id: string
  reviewee_name: string
  reviewer_user_id?: string | null
  reviewer_name: string
  diamond_score: number
  comment?: string | null
  is_sample?: boolean
  task_title: string
  project_title?: string | null
  created_at: string
  updated_at: string
}

export interface TaskReviewOverviewRow {
  task_id: string | null
  source?: "TASK" | "REALIZATION_PROPOSAL"
  realization_period_id?: string | null
  task_title: string
  project_id?: string | null
  project_title?: string | null
  department_id?: string | null
  reviewee_user_id: string
  reviewee_name: string
  completed_at: string
  due_date?: string | null
  is_late: boolean
  review?: TaskReview | null
}

export interface TaskReviewUserSummary {
  user_id: string
  user_name: string
  completed_count: number
  reviewed_count: number
  unreviewed_count: number
  late_count: number
  diamonds_total: number
  proposal_count?: number
}

export interface TaskReviewOverview {
  completed_count: number
  reviewed_count: number
  unreviewed_count: number
  diamonds_total: number
  proposal_count?: number
  users: TaskReviewUserSummary[]
  rows: TaskReviewOverviewRow[]
}

export type DailyReportSystemOccurrenceStatus = "OPEN" | "DONE" | "NOT_DONE" | "SKIPPED"

export interface DailyReportTaskItem {
  task: Task
  project_title?: string | null
  planned_start?: string | null
  planned_end?: string | null
  original_planned_end?: string | null
  is_overdue: boolean
  late_days?: number | null
  rlz_daily_state?: {
    reason_code?: string | null
    reason_label?: string | null
    comment?: string | null
    updated_at?: string | null
    is_editable: boolean
    editable_until: string | null
    requires_explanation?: boolean
    reason_required?: boolean
    comment_required?: boolean
    reason_missing?: boolean
    comment_missing?: boolean
    deadline_was_today?: boolean
    deadline_is_overdue?: boolean
    postponed_today?: boolean
  } | null
}

export interface DailyReportSystemOccurrence {
  task: Task
  template_id: string
  title: string
  frequency?: string | null
  department_id?: string | null
  scope?: SystemTaskScope | null
  occurrence_date: string
  status: DailyReportSystemOccurrenceStatus
  comment?: string | null
  acted_at?: string | null
  is_overdue: boolean
  late_days?: number | null
  rlz_daily_state?: {
    reason_code?: string | null
    reason_label?: string | null
    comment?: string | null
    updated_at?: string | null
    is_editable: boolean
    editable_until: string | null
    requires_explanation?: boolean
    reason_required?: boolean
    comment_required?: boolean
    reason_missing?: boolean
    comment_missing?: boolean
    deadline_was_today?: boolean
    deadline_is_overdue?: boolean
    postponed_today?: boolean
  } | null
}

export interface DailyReportResponse {
  day: string
  tasks_today: DailyReportTaskItem[]
  tasks_overdue: DailyReportTaskItem[]
  system_today: DailyReportSystemOccurrence[]
  system_overdue: DailyReportSystemOccurrence[]
  rlz_close_state?: {
    status: "NOT_SAVED" | "SAVED" | "STALE" | "REOPENED" | "CLOSED_EDIT_WINDOW"
    saved: boolean
    stale: boolean
    saved_at?: string | null
    is_editable: boolean
    closable_from?: string | null
    editable_until?: string | null
  } | null
}

export interface DailyReportGaEntry {
  id: string
  user_id: string
  department_id: string
  entry_date: string
  content: string
  created_at: string
  updated_at: string
}

export interface DailyReportGaNote {
  id: string
  content: string
  note_type?: "GA" | "KA"
  status?: "OPEN" | "CLOSED"
  priority?: "NORMAL" | "HIGH" | null
  created_at: string
  project_id?: string | null
  project_name?: string | null
}

export interface DailyReportGaTableResponse {
  entry?: DailyReportGaEntry | null
  notes: DailyReportGaNote[]
}

export type ChecklistItemType = "TITLE" | "COMMENT" | "CHECKBOX"

export interface ChecklistItemAssignee {
  user_id: string
  user_full_name?: string | null
  user_username?: string | null
}

export interface ChecklistItem {
  id: string
  checklist_id?: string | null
  item_type: ChecklistItemType
  position: number
  // Common fields
  path?: string | null
  keyword?: string | null
  description?: string | null
  category?: string | null
  original?: string | null
  day?: string | null
  owner?: string | null
  time?: string | null
  // Type-specific fields
  title?: string | null
  comment?: string | null
  is_checked?: boolean | null
  // Assignees
  assignees?: ChecklistItemAssignee[]
}

export interface Checklist {
  id: string
  title?: string | null
  task_id?: string | null
  project_id?: string | null
  note?: string | null
  default_owner?: string | null
  default_time?: string | null
  group_key?: string | null
  columns?: Array<{ key: string; label: string; width?: string | null }> | null
  position?: number | null
  created_at: string
}

export interface ChecklistWithItems extends Checklist {
  items: ChecklistItem[]
}

export interface ProjectPhaseChecklistItem {
  id: string
  project_id: string
  phase_key: string
  title: string
  comment?: string | null
  is_checked: boolean
  sort_order?: number | null
  created_by?: string | null
  created_at: string
  updated_at: string
}

export interface GaNote {
  id: string
  content: string
  created_by?: string | null
  note_type?: "GA" | "KA"
  status?: "OPEN" | "CLOSED"
  priority?: "NORMAL" | "HIGH" | null
  start_date: string
  due_date?: string | null
  completed_at?: string | null
  is_converted_to_task: boolean
  is_discussed?: boolean
  one_h_marker?: "EXCLAMATION" | "QUESTION" | "KA" | "GENT" | "FLAG" | "F" | "BZ1N1" | "M2" | "M3" | "M2_M3" | "MONITOR" | "CLOSE" | "CLIENT_URGENT" | "SHARE" | null
  one_h_marker_by_ga?: boolean
  one_h_marker_comment?: string | null
  next_week?: boolean
  project_id?: string | null
  department_id?: string | null
  knowledge_type?: "PROMPT" | "DEFINITION" | "REGULATION" | null
  knowledge_tester_id?: string | null
  created_at: string
  updated_at: string
  attachments?: GaNoteAttachment[]
  /** Saved by Mira from a meeting or desktop recording. */
  from_mira?: boolean
  mira_shared_to_px?: boolean
}

export interface PlanNote {
  id: string
  content: string
  comment?: string | null
  created_by?: string | null
  note_type?: "GA" | "KA"
  status?: "OPEN" | "CLOSED"
  priority?: "NORMAL" | "HIGH" | null
  start_date: string
  due_date?: string | null
  completed_at?: string | null
  is_converted_to_task: boolean
  is_discussed?: boolean
  one_h_marker?: "EXCLAMATION" | "QUESTION" | "KA" | "GENT" | "FLAG" | "F" | "BZ1N1" | "M2" | "M3" | "M2_M3" | "MONITOR" | "CLOSE" | "CLIENT_URGENT" | "SHARE" | null
  one_h_marker_by_ga?: boolean
  one_h_marker_comment?: string | null
  next_week?: boolean
  project_id?: string | null
  department_id?: string | null
  planned_for_date?: string | null
  planning_brief?: PxJavPlanningBrief | null
  created_at: string
  updated_at: string
  attachments?: PlanNoteAttachment[]
  attachment_count?: number
}

export interface PlanNoteAttachment {
  id: string
  note_id: string
  original_filename: string
  stored_filename: string
  content_type?: string | null
  size_bytes: number
  created_by?: string | null
  created_at: string
}

export interface GaNoteAttachment {
  id: string
  note_id: string
  original_filename: string
  stored_filename: string
  content_type?: string | null
  size_bytes: number
  created_by?: string | null
  created_at: string
}

export interface InternalNote {
  id: string
  title: string
  description?: string | null
  from_user_id: string
  to_user_id: string
  department_id?: string
  project_id?: string | null
  to_department_id: string
  is_done: boolean
  done_at?: string | null
  done_by_user_id?: string | null
  created_at: string
  updated_at: string
}

export interface ProjectPrompt {
  id: string
  project_id: string
  type: "GA_PROMPT" | "ZHVILLIM_PROMPT"
  title: string
  content: string
  created_at: string
}

export interface ExternalPlatformLink {
  id: string
  label: string
  href: string
  description?: string | null
  sort_order: number
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface TaskTemplate {
  id: string
  department_id: string
  board_id: string
  project_id?: string | null
  title: string
  description?: string | null
  recurrence: TemplateRecurrence
  default_status_id: string
  assigned_to_user_id?: string | null
  created_by_user_id?: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface CommonEntry {
  id: string
  category: CommonCategory
  title: string
  description?: string | null
  entry_date?: string | null
  created_by_user_id: string
  assigned_to_user_id?: string | null
  approval_status: CommonApprovalStatus
  approved_by_user_id?: string | null
  approved_at?: string | null
  rejected_by_user_id?: string | null
  rejected_at?: string | null
  rejection_reason?: string | null
  generated_task_id?: string | null
  created_at: string
  updated_at: string
}

export interface Notification {
  id: string
  user_id: string
  type: NotificationType
  title: string
  body?: string | null
  data?: Record<string, unknown> | null
  created_at: string
  read_at?: string | null
}

export interface Meeting {
  id: string
  title: string
  platform?: string | null
  starts_at?: string | null
  ends_at?: string | null
  meeting_url?: string | null
  microsoft_event_id?: string | null
  calendar_imported?: boolean
  calendar_sync_status?: string | null
  calendar_categories?: string[]
  calendar_last_synced_at?: string | null
  reminder_minutes_before?: number | null
  meeting_type?: string | null
  recurrence_type?: string | null // "none", "weekly", "monthly"
  recurrence_days_of_week?: number[] | null
  recurrence_days_of_month?: number[] | null
  external_agent_test_task_requested?: boolean
  external_pim_image_test_task_requested?: boolean
  department_id: string
  project_id?: string | null
  created_by?: string | null
  created_at: string
  updated_at: string
  participant_ids?: string[]
  paired_internal_meeting?: Meeting | null
  paired_external_meeting_id?: string | null
  pre_external_meeting_id?: string | null
}

export interface MeetingOccurrenceStatus {
  id: string
  meeting_id: string
  occurrence_date: string
  status: "planned" | "held" | "canceled"
  note?: string | null
  checked_by_user_id?: string | null
  checked_at?: string | null
  created_at: string
  updated_at: string
}

export type RealizationPeriodStatus =
  | "OPEN"
  | "CALCULATED"
  | "REVIEWED"
  | "APPROVED"
  | "LOCKED"

export type RealizationLevel = "A+" | "A" | "B" | "C" | "M" | "D" | "E"
export type RealizationSymbol = "+" | "+/-" | "-"
export type RealizationPulse = "+" | "++" | "DIAMOND" | "?" | "OK"
export type RealizationOperatingMode = "AUTO" | "SEMI_MANUAL" | "MANUAL"

export interface RealizationPulseDecision {
  pulse: RealizationPulse
  reason: string
  expected_count: number
  completed_count: number
  delta_to_plan: number
  justified_shortfall: number
  unresolved_pink_count: number
  missing_comment_count: number
  unresolved_negative_count: number
  unverified_extra_count: number
  verified_extra_count: number
  verified_diamond_count: number
}

export interface RealizationPeriod {
  id: string
  period_type: "DAILY" | "WEEKLY" | "MONTHLY"
  slot: "AM" | "PM" | "ALL"
  start_date: string
  end_date: string
  department_id: string
  policy_version_id: string
  planned_snapshot_id?: string | null
  final_snapshot_id?: string | null
  status: RealizationPeriodStatus
  calculated_at?: string | null
  approved_at?: string | null
  locked_at?: string | null
  created_by?: string | null
  approved_by?: string | null
  created_at: string
}

export interface RealizationTaskFact {
  adjustment_status?: string | null
  manager_decision?: DailyRealizationManagerDecision | null
  timeline?: DailyRealizationTimelineEvent[]
  match_key: string
  task_id?: string | null
  title: string
  project_title?: string | null
  source_type: string
  classification: string
  status?: string | null
  completed_at?: string | null
  planned_deadline?: string | null
  effective_deadline?: string | null
  positive_progress_delta?: number
  planned_occurrences?: Array<{
    day?: string | null
    time_slot?: string | null
    assignee_id?: string | null
  }>
  daily_progress?: Array<{
    id: string
    day: string
    completed_value: number
    total_value: number
    completed_delta: number
    daily_status: string
    finish_period?: string | null
  }>
  postponement?: string | null
  postponement_evidence_ids?: string[]
  reassignment?: boolean
  attribution?: "planned_owner" | "actual_worker" | "additional_owner" | "planned_today" | "added_after_weekly_plan" | "completed_from_weekly_plan" | "completed_outside_weekly_plan" | "system_schedule"
  completion_day?: string | null
  meeting_origin_id?: string | null
  status_progress_inconsistent?: boolean
  user_comment?: string | null
  daily_report_comment?: string | null
  reason_code?: string | null
  reason_label?: string | null
  comment_required_before_close?: boolean
  rlz_impact?: string
}

export type RealizationManagerReviewDimension = "PLANNING" | "REALIZATION"
export type RealizationManagerReviewRating = "GOOD" | "VERY_GOOD" | "ACTION_REQUIRED" | "BAD"
export type RealizationManagerReviewMarker = "POSITIVE" | "NEGATIVE"

export interface RealizationManagerReviewItem {
  level?: RealizationLevel | null
  rating?: RealizationManagerReviewRating | null
  id: string
  dimension: RealizationManagerReviewDimension
  marker: RealizationManagerReviewMarker
  label: string
  comment: string
  created_by_user_id?: string | null
  created_by_name: string
  created_at: string
  active: boolean
  voided_at?: string | null
}

export interface RealizationManagerReviewResponse {
  period_id: string
  user_id: string
  can_edit: boolean
  planning: RealizationManagerReviewItem | null
  realization: RealizationManagerReviewItem | null
  history: RealizationManagerReviewItem[]
}

export type RealizationDeadlineState = "COMPLETED" | "IN_PROGRESS" | "POSTPONED" | "NO_PROGRESS"

export interface RealizationDeadlineOccurrence {
  day: string | null
  state: RealizationDeadlineState
  critical: boolean
}

export interface RealizationDeadlineTask {
  task_id: string | null
  match_key?: string
  title: string
  day: string | null
  state: RealizationDeadlineState
  critical: boolean
  /** Filled in by the table when several people's deadlines are pooled. */
  person?: string
  /** Earlier deadline outcomes, separate from the task's weekly status. */
  history?: RealizationDeadlineOccurrence[]
}

export type RealizationItemKind = "COMPLETED" | "IN_PROGRESS" | "POSTPONED" | "NO_PROGRESS" | "REASSIGNED_OUT" | "EXTRA_COMPLETED" | "EXTRA_OPEN" | "WFE" | "EXTRA_WFE"

/** How one task moved a person's Plan RLZ for the day. */
export interface RealizationItem {
  task_id: string | null
  title: string
  kind: RealizationItemKind
  planned: boolean
  /** Plan task: 1, or 1/N for a task spread over N working days. Extra: the day's average plan task weight. */
  share: number
  credit: number
  penalty: number
  approved: boolean
  deadline: boolean
  critical: boolean
}

export interface DailyRealizationMetrics {
  quantity_task_count: number
  quantity_planned_count: number
  quantity_completed_count: number
  quantity_delta: number
  original_planned_count: number
  planned_completed_today_count: number
  in_progress_count: number
  no_progress_count: number
  postponed_count: number
  approved_postponement_count: number
  unapproved_postponement_count: number
  waiting_confirmation_count: number
  additional_count: number
  additional_completed_count: number
  additional_in_progress_count: number
  additional_no_progress_count: number
  completed_late_count: number
  completed_early_count: number
  reopened_count: number
  reassigned_out_count: number
  reassigned_in_count: number
  total_completed_today_count: number
  adjusted_exclusion_count: number
  adjusted_denominator: number
  raw_plan_realization: number | null
  adjusted_plan_realization: number | null
  realization_plan_weight: number
  realization_credit: number
  realization_penalty_points: number
  adjusted_realization_plan_weight: number
  adjusted_realization_penalty_points: number
  realization_items?: RealizationItem[]
  deadlines_today_count: number
  deadlines_completed_count: number
  deadlines_postponed_count: number
  deadlines_in_progress_count: number
  deadlines_no_progress_count: number
  deadline_tasks?: RealizationDeadlineTask[]
  deadlines_open_count: number
  overdue_open_count: number
  deadline_compliance_percentage: number | null
  critical_deadlines_today_count: number
  critical_deadlines_completed_count: number
  critical_deadlines_open_count: number
  daily_control_state: "CLEAN_DAY" | "ACTION_REQUIRED"
}

export interface DailyRealizationTimelineEvent {
  id: string
  type: string
  timestamp?: string | null
  actor_user_id?: string | null
  actor_name?: string | null
  old_value?: unknown
  new_value?: unknown
  metadata?: { reason?: string | null; comment?: string | null; time_slot?: string | null }
}

export interface DailyRealizationManagerDecision {
  status: "PENDING" | "APPROVED" | "REJECTED"
  reason?: string | null
  comment?: string | null
  decided_by_user_id?: string | null
  decided_by_name?: string | null
  decided_at?: string | null
}

export interface DailyRealizationTask {
  quantity?: { source: "title" | "products"; planned: number; completed: number; delta: number } | null
  task_id: string
  match_key: string
  title: string
  project_id?: string | null
  project_title?: string | null
  source_type: string
  original_daily_plan?: string | null
  baseline_due_date?: string | null
  current_due_date?: string | null
  current_status: string
  classification: string
  in_original_plan: boolean
  progress_today: number
  completed_delta: number
  reason_code?: string | null
  comment?: string | null
  is_bllok: boolean
  one_h_report_slot?: string | null
  last_change?: string | null
  postponement_count: number
  adjustment_status?: string | null
  manager_decision?: DailyRealizationManagerDecision | null
  issues: string[]
  timeline: DailyRealizationTimelineEvent[]
  requires_explanation: boolean
  reason_required: boolean
  comment_required: boolean
  reason_missing: boolean
  comment_missing: boolean
  deadline_was_today: boolean
  deadline_completed: boolean
  deadline_critical: boolean
  deadline_is_overdue: boolean
  postponed_today: boolean
  had_postponement_event: boolean
  action_required: boolean
}

export interface DailyRealizationPerson {
  user_id: string
  user_name: string
  department_id: string
  tasks: DailyRealizationTask[]
  metrics: DailyRealizationMetrics
  availability_status?: "PV" | "MUNGESE" | "PV_MUNGESE" | null
  close_state: "NOT_SAVED" | "CLOSED_EDIT_WINDOW" | "SAVED" | "STALE" | "REOPENED"
  close_state_details?: {
    status: DailyRealizationPerson["close_state"]
    closed_at?: string | null
    closed_by_user_id?: string | null
    closed_by_name?: string | null
    action?: string | null
    stale_cause?: "MANAGER_POSTPONEMENT_DECISION" | null
  }
}

export interface DailyRealizationLive {
  day: string
  department_id: string
  timezone: string
  baseline_id?: string | null
  baseline_captured_at?: string | null
  baseline_available: boolean
  historical_estimate: boolean
  live: boolean
  last_updated: string
  metrics: DailyRealizationMetrics
  people: DailyRealizationPerson[]
}

export interface RealizationObservationFact {
  id: string
  marker: "POSITIVE" | "NEUTRAL" | "NEGATIVE" | "DIAMOND"
  category: string
  comment?: string | null
  task_id?: string | null
  user_id?: string | null
  project_id?: string | null
  impact_minutes?: number | null
  repeat_count?: number | null
  source_type?: string | null
  relevant_date?: string | null
  created_at?: string | null
  evidence_json: Record<string, unknown>
  verified: boolean
  visibility: string
}

export interface RealizationQuestion {
  answer_source?: "DIRECT" | "DAILY_ROLLUP"
  daily_history?: Array<{ date: string; value: boolean; comment?: string | null; answered_by_name?: string | null }>
  key: string
  label: string
  answer_type: string
  auto_value: unknown
  final_value: unknown
  source_status: string
  evidence_ids: string[]
  explanation: string
  manager_comment?: string | null
  linked_evidence_ids?: string[]
}

export interface RealizationManualAnswer {
  diamond_score?: number
  id: string
  value: boolean | string | null
  comment?: string | null
  evidence_ids: string[]
  answered_by: string
  answered_by_name?: string | null
  answered_at: string
  updated_at: string
  supersedes_answer_id?: string | null
}

export interface RealizationPersonResult {
  id: string
  period_id: string
  user_id: string
  user_name: string
  department_id?: string | null
  facts_json: {
    weekly_evaluation?: { level: RealizationLevel | null; reasons: string[]; provisional: boolean; missing: string[]; rule_version: string }
    availability_status?: "PV" | "MUNGESE" | "PV_MUNGESE" | null
    tasks?: RealizationTaskFact[]
    observations?: RealizationObservationFact[]
    questions?: RealizationQuestion[]
    needs_review?: Array<Record<string, unknown>>
    counters?: Record<string, number>
    attendance?:
      | Record<string, { date: string; type: string; details?: string | null }>
      | Array<{ id?: string; date?: string; type: string; details?: string | null }>
    decision?: { triggered_rule?: string; reasons?: string[]; policy_suggested_level?: RealizationLevel; hard_cap_level?: RealizationLevel | null }
    manual_answers?: Record<string, RealizationManualAnswer>
    manual_question_completeness?: {
      answered: number
      required: number
      missing_keys: string[]
      complete: boolean
    }
    weekly_progress_percent?: number
    /** Awarded task and proposal diamonds for the report's selected week. */
    weekly_diamond_count?: number
    weekly_task_diamond_count?: number
    weekly_proposal_diamond_count?: number
    weekly_diamonds?: TaskReviewOverviewRow[]
    daily_progress_percent?: number
    daily_planned_count?: number
    daily_completed_count?: number
    weekly_planned_count?: number
    weekly_completed_count?: number
    weekly_all_completed_count?: number
    weekly_completed_outside_plan_count?: number
    weekly_completed_tasks?: RealizationTaskFact[]
    weekly_additional_count?: number
    weekly_additional_completed_count?: number
    weekly_additional_in_progress_count?: number
    /** Extras added, never started, then pushed past the week, so left out of it. */
    weekly_additional_deferred_count?: number
    weekly_additional_postponed_count?: number
    weekly_additional_todo_count?: number
    weekly_additional_no_progress_count?: number
    weekly_in_progress_task_count?: number
    weekly_postponed_task_count?: number
    /** Points deducted for plan tasks still unfinished at week end (25 postponed, 40/60 postponed with deadline, 50/70 missed deadline). */
    weekly_penalty_points?: number
    weekly_wfe_count?: number
    weekly_no_progress_task_count?: number
    weekly_quantity_task_count?: number
    weekly_quantity_planned_count?: number
    weekly_quantity_completed_count?: number
    weekly_quantity_delta?: number
    weekly_deadline_count?: number
    weekly_deadline_completed_count?: number
    weekly_deadline_postponed_count?: number
    weekly_deadline_in_progress_count?: number
    weekly_deadline_no_progress_count?: number
    weekly_deadline_tasks?: RealizationDeadlineTask[]
    weekly_critical_deadline_count?: number
    weekly_critical_deadline_completed_count?: number
    weekly_fast_task_count?: number
    weekly_in_progress_count?: number
    weekly_no_progress_count?: number
    weekly_pending_count?: number
    weekly_snapshot_days?: number
    question_scope?: "DAILY" | "WEEKLY"
    report_mode?: "LIVE_DAILY" | "FINAL_WEEKLY"
    pulse?: RealizationPulseDecision
    projected_weekly_pulse?: RealizationPulseDecision
    recovery?: {
      expected_cumulative: number
      actual_cumulative: number
      delta_to_plan: number
      remaining_planned_obligations: number
      remaining_working_days: number
      unresolved_pink: number
      justified_shortfall: number
      unverified_extra: number
      verified_extra: number
      required_for_plus: number
      messages: string[]
    }
    pulse_history?: Array<{
      date: string
      pulse?: RealizationPulse | null
      reason?: string | null
      has_snapshot: boolean
      close_state: "OPEN" | "CLOSED" | "REOPENED"
      close_event?: RealizationDailyCloseEvent | null
    }>
    daily_timeline?: Array<{
      on_leave?: boolean
      future?: boolean
      person_comment?: { comment: string; author?: string | null; updated_at?: string | null }
      manual_answers?: Record<string, RealizationManualAnswer>
      date: string
      period_id?: string
      result_id?: string
      has_snapshot?: boolean
      daily_progress_percent: number | null
      weekly_progress_percent: number
      planned_count: number
      completed_count: number
      weekly_planned_count?: number
      weekly_completed_count?: number
      additional_count: number
      weekly_additional_count?: number
      attendance: Array<{ id?: string; type: string; details?: string | null }>
      tasks?: RealizationTaskFact[]
      pulse?: RealizationPulseDecision
      recovery?: Record<string, unknown>
      close_state?: "OPEN" | "CLOSED" | "REOPENED"
      close_event?: RealizationDailyCloseEvent | null
      close_history?: RealizationDailyCloseEvent[]
      manager_approval?: RealizationDailyApprovalState
    }>
    project_progress?: Array<{
      project_id: string
      project_title: string
      task_count: number
      progress_percent: number
      method: string
      task_ids: string[]
    }>
    ai_analysis?: RealizationAIAnalysis
    ai_analysis_history?: RealizationAIAnalysis[]
  }
  planned_count: number
  completed_on_time_count: number
  completed_late_count: number
  in_progress_count: number
  pending_count: number
  no_progress_count: number
  additional_count: number
  approved_postponement_count: number
  unapproved_postponement_count: number
  tardiness_count: number
  approved_absence_days: number
  unexcused_absence_days: number
  suggested_symbol?: RealizationSymbol | null
  suggested_level?: RealizationLevel | null
  ai_suggested_level?: RealizationLevel | null
  ai_generated_at?: string | null
  ai_analysis_stale: boolean
  final_symbol?: RealizationSymbol | null
  final_level?: RealizationLevel | null
  auto_narrative?: string | null
  manager_comment?: string | null
  override_reason?: string | null
  reviewed_by?: string | null
  reviewed_at?: string | null
}

export interface RealizationDailyCloseEvent {
  id: string
  period_id: string
  result_id: string
  user_id: string
  department_id: string
  action: "CLOSE" | "REOPEN" | "CORRECT"
  mode: RealizationOperatingMode
  suggested_pulse: RealizationPulse
  confirmed_pulse?: RealizationPulse | null
  daily_comment?: string | null
  reason?: string | null
  facts_json?: {
    daily_report_state?: {
      day: string
      saved_at?: string
      tasks: Array<{
        task_id: string
        title: string
        status: string
        due_date?: string | null
        planned_due_date?: string | null
        reason_code?: string | null
        reason_label?: string | null
        comment?: string | null
      }>
    }
  }
  created_at: string
}

export interface RealizationDailyApprovalState {
  status: "PENDING" | "APPROVED" | "STALE" | "REVOKED"
  approval_id?: string | null
  action?: "APPROVE" | "REVOKE" | null
  approved_by?: string | null
  approved_at?: string | null
  approval_comment?: string | null
  reason?: string | null
  source_close_event_id?: string | null
}

export interface RealizationDepartmentResult {
  id: string
  period_id: string
  department_id: string
  facts_json: Record<string, unknown>
  a_plus_count: number
  a_count: number
  b_count: number
  c_count: number
  m_count: number
  d_count: number
  e_count: number
  a_rate?: number | null
}

export interface RealizationDailyResponse {
  period: RealizationPeriod
  department_name?: string | null
  has_planned_snapshot: boolean
  can_calculate: boolean
  message?: string | null
  people: RealizationPersonResult[]
  department_result?: RealizationDepartmentResult | null
}

export interface RealizationAIAnalysis {
  summary: string
  positives: string[]
  problems: string[]
  missing_evidence: string[]
  suggested_level: RealizationLevel
  grade_reason: string
  grade_drivers: Array<{
    type: "POSITIVE" | "NEGATIVE" | "JUSTIFICATION" | "FACT"
    description: string
    evidence_ids: string[]
  }>
  caps: Array<{ maximum_level: RealizationLevel; reason: string; evidence_ids: string[] }>
  question_keys_used: string[]
  confidence: number
  evidence_ids: string[]
  model: string
  advisory_only: true
  generated_at?: string
  generated_by?: string
}

export interface RealizationWeeklyResponse {
  period: RealizationPeriod
  department_name?: string | null
  has_planned_snapshot: boolean
  /** When the weekly plan was actually photographed, which is not always Monday. */
  planned_snapshot_captured_day?: string | null
  has_final_snapshot: boolean
  can_calculate: boolean
  message?: string | null
  people: RealizationPersonResult[]
  department_result?: RealizationDepartmentResult | null
  unassigned: RealizationTaskFact[]
}
