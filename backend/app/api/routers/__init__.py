from fastapi import APIRouter
from app.api.routers.private_profile_photo import router as private_profile_photo_router
from app.api.routers.discord_assistant import router as discord_assistant_router

from app.api.routers.auth import router as auth_router
from app.api.routers.checklist_items import router as checklist_items_router
from app.api.routers.checklists import router as checklists_router
from app.api.routers.departments import router as departments_router
from app.api.routers.ga_notes import router as ga_notes_router
from app.api.routers.plan_notes import router as plan_notes_router
from app.api.routers.ga_time_slots import router as ga_time_slots_router
from app.api.routers.internal_meeting_sessions import router as internal_meeting_sessions_router
from app.api.routers.internal_notes import router as internal_notes_router
from app.api.routers.microsoft import router as microsoft_router
from app.api.routers.meetings import router as meetings_router
from app.api.routers.meeting_recordings import router as meeting_recordings_router
from app.api.routers.meeting_scheduler import router as meeting_scheduler_router
from app.api.routers.notifications import router as notifications_router
from app.api.routers.marker_comments import router as marker_comments_router
from app.api.routers.planners import router as planners_router
from app.api.routers.reports import router as reports_router
from app.api.routers.project_members import router as project_members_router
from app.api.routers.project_prompts import router as project_prompts_router
from app.api.routers.project_phase_checklists import router as project_phase_checklists_router
from app.api.routers.projects import router as projects_router
from app.api.routers.system_tasks import router as system_tasks_router
from app.api.routers.tasks import router as tasks_router
from app.api.routers.task_reviews import router as task_reviews_router
from app.api.routers.users import router as users_router
from app.api.routers.boards import router as boards_router
from app.api.routers.common_entries import router as common_entries_router
from app.api.routers.common_view import router as common_view_router
from app.api.routers.task_statuses import router as task_statuses_router
from app.api.routers.exports import router as exports_router
from app.api.routers.external_platform_links import router as external_platform_links_router
from app.api.routers.file_access import router as file_access_router
from app.api.routers.speech import router as speech_router
from app.api.routers.voice_assistant import router as voice_assistant_router
from app.api.routers.public import router as public_router
from app.api.routers.question_library import router as question_library_router
from app.api.routers.report_delivery_runs import router as report_delivery_runs_router
from app.api.routers.primeflow_1h_reports import router as primeflow_1h_reports_router
from app.api.routers.meetings_report import router as meetings_report_router
from app.api.routers.m3_reporting_points import router as m3_reporting_points_router
from app.api.routers.m2_reporting_points import router as m2_reporting_points_router
from app.api.routers.m1_reporting_points import router as m1_reporting_points_router
from app.api.routers.after_break_report import router as after_break_report_router
from app.api.routers.end_week_bz_report import router as end_week_bz_report_router
from app.api.routers.morning_report import router as morning_report_router
from app.api.routers.tomorrow_print_report import router as tomorrow_print_report_router
from app.api.routers.today_print_report import router as today_print_report_router
from app.api.routers.realization import router as realization_router
from app.api.routers.weekly_planning_audit import router as weekly_planning_audit_router
from app.api.routers.px_jav_weekly_report import router as px_jav_weekly_report_router
from app.api.routers.standards import router as standards_router
from app.api.routers.external_tickets import router as external_tickets_router
from app.api.routers.skills import router as skills_router
from app.api.routers.knowledge import router as knowledge_router


from app.api.routers.discord_voice_meetings import router as discord_voice_meetings_router
api_router = APIRouter()
api_router.include_router(discord_voice_meetings_router, prefix="/discord/bot/voice-meetings", tags=["discord"])
api_router.include_router(private_profile_photo_router, prefix="/profile-photo", tags=["profile-photo"])
from app.api.routers.discord_agents import router as discord_agents_router
api_router.include_router(discord_agents_router, prefix="/discord/bot/agents", tags=["discord"])
api_router.include_router(discord_assistant_router, prefix="/discord", tags=["discord"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(checklist_items_router, prefix="/checklist-items", tags=["checklist-items"])
api_router.include_router(checklists_router, prefix="/checklists", tags=["checklists"])
api_router.include_router(departments_router, prefix="/departments", tags=["departments"])
api_router.include_router(ga_notes_router, prefix="/ga-notes", tags=["ga-notes"])
api_router.include_router(plan_notes_router, prefix="/plan-notes", tags=["plan-notes"])
api_router.include_router(ga_time_slots_router, prefix="/ga-time-slots", tags=["ga-time-slots"])
api_router.include_router(internal_meeting_sessions_router, prefix="/internal-meeting-sessions", tags=["internal-meeting-sessions"])
api_router.include_router(internal_notes_router, prefix="/internal-notes", tags=["internal-notes"])
api_router.include_router(microsoft_router, prefix="/microsoft", tags=["microsoft"])
api_router.include_router(meetings_router, prefix="/meetings", tags=["meetings"])
api_router.include_router(meeting_recordings_router, prefix="/meeting-recordings", tags=["meeting-recordings"])
api_router.include_router(meeting_scheduler_router, prefix="/meeting-scheduler", tags=["meeting-scheduler"])
api_router.include_router(notifications_router, prefix="/notifications", tags=["notifications"])
api_router.include_router(marker_comments_router, prefix="/marker-comments", tags=["marker-comments"])
api_router.include_router(planners_router, prefix="/planners", tags=["planners"])
api_router.include_router(reports_router, prefix="/reports", tags=["reports"])
api_router.include_router(projects_router, prefix="/projects", tags=["projects"])
api_router.include_router(project_members_router, prefix="/project-members", tags=["project-members"])
api_router.include_router(project_prompts_router, prefix="/project-prompts", tags=["project-prompts"])
api_router.include_router(project_phase_checklists_router, tags=["project-phase-checklists"])
api_router.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
api_router.include_router(task_reviews_router, prefix="/task-reviews", tags=["task-reviews"])
api_router.include_router(system_tasks_router, prefix="/system-tasks", tags=["system-tasks"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(boards_router, prefix="/boards", tags=["boards"])
api_router.include_router(task_statuses_router, prefix="/task-statuses", tags=["task-statuses"])
api_router.include_router(common_entries_router, prefix="/common-entries", tags=["common-entries"])
api_router.include_router(common_view_router, prefix="/common-view", tags=["common-view"])
api_router.include_router(exports_router, prefix="/exports", tags=["exports"])
api_router.include_router(external_platform_links_router, prefix="/external-platform-links", tags=["external-platform-links"])
api_router.include_router(file_access_router, prefix="/file-access", tags=["file-access"])
api_router.include_router(speech_router, prefix="/speech", tags=["speech"])
api_router.include_router(voice_assistant_router, prefix="/voice-assistant", tags=["voice-assistant"])
api_router.include_router(public_router, prefix="/public", tags=["public"])
api_router.include_router(question_library_router, prefix="/question-library", tags=["question-library"])
api_router.include_router(report_delivery_runs_router, prefix="/admin/report-delivery-runs", tags=["admin"])
api_router.include_router(primeflow_1h_reports_router, prefix="/admin/primeflow-1h-reports", tags=["admin", "primeflow-1h-reports"])
api_router.include_router(meetings_report_router, prefix="/meetings-report", tags=["meetings-report"])
api_router.include_router(m3_reporting_points_router, prefix="/m3-reporting-points", tags=["m3-reporting-points"])
api_router.include_router(m2_reporting_points_router, prefix="/m2-reporting-points", tags=["m2-reporting-points"])
api_router.include_router(m1_reporting_points_router, prefix="/m1-reporting-points", tags=["m1-reporting-points"])
api_router.include_router(after_break_report_router, prefix="/after-break-report", tags=["after-break-report"])
api_router.include_router(end_week_bz_report_router, prefix="/end-week-bz-report", tags=["end-week-bz-report"])
api_router.include_router(morning_report_router, prefix="/morning-report", tags=["morning-report"])
api_router.include_router(tomorrow_print_report_router, prefix="/tomorrow-print-report", tags=["tomorrow-print-report"])
api_router.include_router(today_print_report_router, prefix="/today-print-report", tags=["today-print-report"])
api_router.include_router(realization_router, prefix="/realization", tags=["realization"])
api_router.include_router(skills_router, prefix="/skills", tags=["skills"])
api_router.include_router(knowledge_router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(
    weekly_planning_audit_router,
    prefix="/reports/weekly-planning-audit",
    tags=["reports", "weekly-planning-audit"],
)
api_router.include_router(
    px_jav_weekly_report_router,
    prefix="/reports/px-jav-weekly",
    tags=["reports", "px-jav-weekly"],
)
api_router.include_router(standards_router, prefix="/standards", tags=["standards"])
api_router.include_router(external_tickets_router, prefix="/external-tickets", tags=["external-tickets"])

