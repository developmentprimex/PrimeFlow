import type { DailyRealizationMetrics, DailyRealizationTask, RealizationItem, RealizationItemKind } from "@/lib/types"

export function dailyRealizationColumnKind(kind: RealizationItemKind): RealizationItemKind {
  return kind === "POSTPONED" ? "NO_PROGRESS" : kind
}

/** Keep deadline tasks visible after removing their separate summary column. */
export function dailyRealizationTableItems(metrics: DailyRealizationMetrics, tasks: DailyRealizationTask[] = []): RealizationItem[] {
  const deadlines = metrics.deadline_tasks ?? []
  const items = (metrics.realization_items ?? []).map<RealizationItem>(item => {
    if (item.kind !== "EXTRA_OPEN") return item
    const state = deadlines.find(task => task.task_id && task.task_id === item.task_id)?.state
    const kind = state === "COMPLETED" ? "EXTRA_COMPLETED" : state === "POSTPONED" ? "POSTPONED" : state === "IN_PROGRESS" ? "IN_PROGRESS" : "NO_PROGRESS"
    return { ...item, kind }
  })
  for (const task of deadlines) {
    // Anonymous rows cannot safely be matched by their title alone.
    if (task.task_id && items.some(item => item.task_id === task.task_id)) continue
    const source = tasks.find(row => task.task_id && row.task_id === task.task_id)
    const planned = source?.in_original_plan ?? true
    items.push({
      task_id: task.task_id, title: task.title,
      kind: task.state === "COMPLETED" ? planned ? "COMPLETED" : "EXTRA_COMPLETED" : task.state,
      planned, share: 1, credit: 0, penalty: 0,
      approved: source?.classification === "POSTPONED_APPROVED", deadline: true, critical: task.critical,
    })
  }
  return items
}
