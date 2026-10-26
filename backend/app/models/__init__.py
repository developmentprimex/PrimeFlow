from app.models.attendance_log import AttendanceLog
from app.models.audit_log import AuditLog
from app.models.board import Board
from app.models.checklist import Checklist
from app.models.checklist_item import ChecklistItem, ChecklistItemAssignee
from app.models.common_entry import CommonEntry
from app.models.daily_report_ga_entry import DailyReportGaEntry
from app.models.daily_planner_snapshot import DailyPlannerSnapshot
from app.models.daily_plan_adjustment import DailyPlanAdjustment
from app.models.department import Department
from app.models.external_platform_link import ExternalPlatformLink
from app.models.file_access_request import FileAccessRequest
from app.models.feedback_log import FeedbackLog
from app.models.ga_note import GaNote
from app.models.ga_note_attachment import GaNoteAttachment
from app.models.knowledge_prompt import KnowledgePrompt
from app.models.ga_icloud_sync_connection import GaIcloudSyncConnection
from app.models.plan_note import PlanNote
from app.models.plan_note_attachment import PlanNoteAttachment
from app.models.ga_time_slot_entry import GaTimeSlotEntry
from app.models.ga_time_table_row import GaTimeTableRow
from app.models.ga_time_slot_template import GaTimeSlotTemplate
from app.models.holiday import Holiday
from app.models.internal_note import InternalNote
from app.models.internal_meeting_session import InternalMeetingSession
from app.models.meeting import Meeting, MeetingParticipant, MeetingReminderDelivery
from app.models.meeting_schedule_request import (
    MeetingScheduleApproval,
    MeetingScheduleRequest,
    MeetingScheduleRequestParticipant,
    MeetingSchedulingStandard,
)
from app.models.meetings_report_draft import MeetingsReportDraft
from app.models.meetings_report_settings import MeetingsReportSettings
from app.models.m3_reporting_points import M3ReportingPointsReport
from app.models.m2_reporting_points import M2ReportingPointsReport
from app.models.m1_reporting_points import M1ReportingPointsReport
from app.models.reporting_points_settings import ReportingPointsSettings
from app.models.after_break_report_draft import AfterBreakReportDraft
from app.models.after_break_report_settings import AfterBreakReportSettings
from app.models.end_week_bz_report_draft import EndWeekBzReportDraft
from app.models.end_week_bz_report_settings import EndWeekBzReportSettings
from app.models.tomorrow_print_report_delivery import TomorrowPrintReportDelivery
from app.models.tomorrow_print_report_settings import TomorrowPrintReportSettings
from app.models.today_print_report_delivery import TodayPrintReportDelivery
from app.models.today_print_report_settings import TodayPrintReportSettings
from app.models.morning_report_draft import MorningReportDraft
from app.models.morning_report_settings import MorningReportSettings
from app.models.meeting_occurrence_status import MeetingOccurrenceStatus
from app.models.microsoft_token import MicrosoftToken
from app.models.notification import Notification
from app.models.one_h_print_report_snapshot import OneHPrintReportSnapshot
from app.models.open_task_planning_baseline import OpenTaskPlanningBaseline
from app.models.project import Project
from app.models.primeflow_report_delivery_run import PrimeFlowReportDeliveryRun
from app.models.primeflow_report_recipient import PrimeFlowReportRecipient
from app.models.primeflow_report_schedule import PrimeFlowReportSchedule
from app.models.primeflow_report_snapshot import PrimeFlowReportSnapshot
from app.models.project_planner_exclusion import ProjectPlannerExclusion
from app.models.project_phase_checklist_item import ProjectPhaseChecklistItem
from app.models.project_member import ProjectMember
from app.models.project_prompt import ProjectPrompt
from app.models.std_feedback_ticket import StdFeedbackSyncState, StdFeedbackTicket
from app.models.question_library import (
    QuestionCategory,
    QuestionDefinition,
    QuestionStatusEvent,
    QuestionUserStatus,
)
from app.models.vs_workflow_item import VsWorkflowItem
from app.models.refresh_token import RefreshToken
from app.models.realization import (
    RealizationDailyApprovalEvent,
    RealizationDailyPersonComment,
    RealizationDailyCloseEvent,
    RealizationDepartmentResult,
    RealizationObservation,
    RealizationPeriod,
    RealizationPersonResult,
    RealizationPolicyVersion,
    RealizationQuestionAnswer,
)
from app.models.system_task_template import SystemTaskTemplate
from app.models.system_task_template_assignee_slot import SystemTaskTemplateAssigneeSlot
from app.models.system_task_occurrence import SystemTaskOccurrence
from app.models.system_task_occurrence_override import SystemTaskOccurrenceOverride
from app.models.system_task_template_alignment_role import SystemTaskTemplateAlignmentRole
from app.models.system_task_template_alignment_user import SystemTaskTemplateAlignmentUser
from app.models.task import Task
from app.models.task_marker_comment_inbox import TaskMarkerCommentInbox
from app.models.task_assignee import TaskAssignee
from app.models.task_alignment_user import TaskAlignmentUser
from app.models.task_planner_exclusion import TaskPlannerExclusion
from app.models.task_review import TaskReview
from app.models.task_daily_progress import TaskDailyProgress
from app.models.task_one_h_report_slot import TaskOneHReportSlot
from app.models.task_one_h_marker_history import TaskOneHMarkerHistory
from app.models.task_daily_rlz_state import TaskDailyRlzState
from app.models.task_status import TaskStatus
from app.models.task_strike_event import TaskStrikeEvent
from app.models.task_user_comment import TaskUserComment
from app.models.task_template import TaskTemplate
from app.models.task_template_run import TaskTemplateRun
from app.models.user import User
from app.models.user_task_preference import UserTaskPreference
from app.models.weekly_plan import WeeklyPlan
from app.models.weekly_planner_snapshot import WeeklyPlannerSnapshot
from app.models.weekly_planner_legend_entry import WeeklyPlannerLegendEntry
from app.models.weekly_planning_audit import (
    WeeklyPlanningAuditDelivery,
    WeeklyPlanningAuditRun,
    WeeklyPlanningAuditSettings,
)

__all__ = [
    "TaskMarkerCommentInbox",
    "ReportingPointsSettings",
    "AttendanceLog",
    "AuditLog",
    "Board",
    "Checklist",
    "ChecklistItem",
    "ChecklistItemAssignee",
    "CommonEntry",
    "DailyReportGaEntry",
    "DailyPlannerSnapshot",
    "DailyPlanAdjustment",
    "Department",
    "ExternalPlatformLink",
    "FileAccessRequest",
    "FeedbackLog",
    "GaNote",
    "GaNoteAttachment",
    "KnowledgePrompt",
    "GaIcloudSyncConnection",
    "PlanNote",
    "PlanNoteAttachment",
    "GaTimeSlotEntry",
    "GaTimeTableRow",
    "GaTimeSlotTemplate",
    "Holiday",
    "InternalNote",
    "InternalMeetingSession",
    "Meeting",
    "MeetingScheduleApproval",
    "MeetingScheduleRequest",
    "MeetingScheduleRequestParticipant",
    "MeetingSchedulingStandard",
    "MeetingsReportDraft",
    "MeetingsReportSettings",
    "M3ReportingPointsReport",
    "M2ReportingPointsReport",
    "M1ReportingPointsReport",
    "AfterBreakReportDraft",
    "AfterBreakReportSettings",
    "EndWeekBzReportDraft",
    "EndWeekBzReportSettings",
    "TomorrowPrintReportDelivery",
    "TomorrowPrintReportSettings",
    "TodayPrintReportDelivery",
    "TodayPrintReportSettings",
    "MorningReportDraft",
    "MorningReportSettings",
    "MeetingOccurrenceStatus",
    "MicrosoftToken",
    "Notification",
    "OneHPrintReportSnapshot",
    "OpenTaskPlanningBaseline",
    "Project",
    "PrimeFlowReportDeliveryRun",
    "PrimeFlowReportRecipient",
    "PrimeFlowReportSchedule",
    "PrimeFlowReportSnapshot",
    "ProjectPlannerExclusion",
    "ProjectPhaseChecklistItem",
    "ProjectMember",
    "ProjectPrompt",
    "StdFeedbackTicket",
    "StdFeedbackSyncState",
    "QuestionCategory",
    "QuestionDefinition",
    "QuestionStatusEvent",
    "QuestionUserStatus",
    "VsWorkflowItem",
    "RefreshToken",
    "RealizationDepartmentResult",
    "RealizationDailyApprovalEvent",
    "RealizationDailyPersonComment",
    "RealizationObservation",
    "RealizationPeriod",
    "RealizationPersonResult",
    "RealizationPolicyVersion",
    "RealizationQuestionAnswer",
    "SystemTaskTemplate",
    "SystemTaskTemplateAssigneeSlot",
    "SystemTaskOccurrence",
    "SystemTaskOccurrenceOverride",
    "SystemTaskTemplateAlignmentRole",
    "SystemTaskTemplateAlignmentUser",
    "Task",
    "TaskAssignee",
    "TaskAlignmentUser",
    "TaskPlannerExclusion",
    "TaskReview",
    "TaskDailyProgress",
    "TaskOneHReportSlot",
    "TaskOneHMarkerHistory",
    "TaskDailyRlzState",
    "TaskStatus",
    "TaskStrikeEvent",
    "TaskUserComment",
    "TaskTemplate",
    "TaskTemplateRun",
    "User",
    "UserTaskPreference",
    "WeeklyPlan",
    "WeeklyPlannerSnapshot",
    "WeeklyPlannerLegendEntry",
    "WeeklyPlanningAuditDelivery",
    "WeeklyPlanningAuditRun",
    "WeeklyPlanningAuditSettings",
]


# Knowledge PX: keep prompt-request tasks open until the prompt is tested.
from app.services import knowledge_task_guard as _knowledge_task_guard  # noqa: E402,F401
from app.models.discord_assistant import DiscordLink, DiscordLinkCode, DiscordReminder, DiscordAction, DiscordMeetingAlert
from app.models.discord_m2_question import DiscordM2Question
from app.models.discord_agent_run import DiscordAgentRun
from app.models.meeting_recording import MeetingRecording, MeetingRecordingChunk
from app.models.recording_analysis import RecordingAnalysis, RecordingTranscript, RecordingAction
from app.models.discord_voice_meeting import DiscordVoiceMeeting, DiscordVoiceSegment
from app.models.mira_memory import MiraMemoryItem, MiraMemoryEvent
from app.models.mira_host import MiraHostSettings, Mira1HMeeting, Mira1HTurn, Mira1HMention, Mira1HEvent, MiraKnowledgeItem
