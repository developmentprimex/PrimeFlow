export type OneHStrikeSummary = {
  report_date: string
  captured_at: string
  active_slot: string | null
  active_interval?: { start: string; end: string } | null
  intervals: Record<string, { start: string; end: string }>
  tasks: Record<string, Record<string, number>>
}

export function taskStrikeBadge(summary: OneHStrikeSummary, taskId: string) {
  const selected = summary.active_slot
  if (!selected) return null
  const interval = summary.active_interval || summary.intervals[selected]
  const count = summary.tasks[taskId]?.[selected]
  if (!interval || count == null) return null
  return { count, label: `Strikes: ${count} · ${interval.start}–${interval.end}` }
}

export function taskHasStrikes(summary: OneHStrikeSummary | undefined, taskId: string): boolean {
  return Boolean(summary && (taskStrikeBadge(summary, taskId)?.count ?? 0) > 0)
}

export function reportStrikeTotal(summary: OneHStrikeSummary | undefined) {
  const selected = summary?.active_slot
  if (!summary || !selected) return null
  const interval = summary.active_interval || summary.intervals[selected]
  if (!interval) return null
  // The server keys tasks by UUID, so cards repeated across slots count once.
  const count = Object.values(summary.tasks).reduce((total, task) => total + (task[selected] ?? 0), 0)
  return { count, label: `Total strikes: ${count} · ${interval.start}–${interval.end}` }
}

export function applyTaskStrikeBadges(document: Document, summary?: OneHStrikeSummary) {
  if (!summary) return
  document.querySelectorAll<HTMLElement>("td[data-task-id]").forEach((cell) => {
    const value = taskStrikeBadge(summary, cell.dataset.taskId || "")
    let badge = cell.querySelector<HTMLElement>("[data-task-strike-count]")
    if (!value) { badge?.remove(); return }
    if (!badge) {
      badge = document.createElement("div")
      badge.dataset.taskStrikeCount = "true"
      cell.append(badge)
    }
    badge.textContent = value.label
    badge.title = "Pikat me strike në këtë interval, sipas llogaritjes së 1H Reports"
    badge.style.cssText = `clear:both;display:table;margin-top:5px;padding:2px 5px;border:1px solid ${value.count ? "#2563eb" : "#94a3b8"};border-radius:4px;background:${value.count ? "#dbeafe" : "#f8fafc"};color:${value.count ? "#1e40af" : "#475569"};font:700 10px/1.4 Arial,sans-serif;white-space:normal;print-color-adjust:exact`
  })
}
