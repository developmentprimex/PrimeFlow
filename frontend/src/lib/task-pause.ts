export type TaskPausePeriod = { from: string; until: string }

const pauseDayFormatter = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Europe/Tirane",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
})

export function currentTaskPauseDay(): string {
  return pauseDayFormatter.format(new Date())
}

export function isTaskPausedOnDay(task: { pause_periods?: TaskPausePeriod[] }, day: string): boolean {
  return task.pause_periods?.some((period) => period.from <= day && day <= period.until) ?? false
}
