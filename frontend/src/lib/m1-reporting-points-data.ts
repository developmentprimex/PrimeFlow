type TaskMetadata = {
  assignees?: string
  department?: string
  am_pm?: string
  task_type?: string
  marker?: string
  planned_for?: string
}

type SavedReport = {
  report_date: string
  sent_at: string | null
  data: { tasks?: TaskMetadata[]; task_order_version?: number; ga_progress?: unknown[]; delivery?: unknown[] }
}

export function shouldRegenerateTaskData(report: SavedReport, currentDay: string): boolean {
  return report.report_date === currentDay && !report.sent_at &&
    (!Object.hasOwn(report.data, "ga_progress") || !Object.hasOwn(report.data, "delivery") || report.data.task_order_version !== 1 || (report.data.tasks || []).some((task) =>
      !Object.hasOwn(task, "assignees") || !Object.hasOwn(task, "department") ||
      !Object.hasOwn(task, "am_pm") || !Object.hasOwn(task, "task_type") ||
      !Object.hasOwn(task, "marker") || !Object.hasOwn(task, "planned_for")))
}
