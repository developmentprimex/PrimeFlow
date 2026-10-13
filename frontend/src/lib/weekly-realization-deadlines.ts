import type { RealizationDeadlineOccurrence, RealizationDeadlineState, RealizationDeadlineTask } from "@/lib/types"

const stateRank: Record<RealizationDeadlineState, number> = { NO_PROGRESS: 0, IN_PROGRESS: 1, POSTPONED: 2, COMPLETED: 3 }

/** Pool shared tasks once while retaining every responsible person's name. */
export function mergeWeeklyDeadlineTasks(tasks: RealizationDeadlineTask[]): RealizationDeadlineTask[] {
  const groups = new Map<string, RealizationDeadlineTask[]>()
  tasks.forEach((task, index) => {
    const key = task.task_id ? `id:${task.task_id}` : task.match_key ? `match:${task.match_key}` : `anonymous:${index}`
    groups.set(key, [...(groups.get(key) || []), task])
  })
  return [...groups.values()].map(group => {
    const latest = [...group].sort((a, b) => (a.day || "").localeCompare(b.day || "") || stateRank[a.state] - stateRank[b.state]).at(-1)!
    const history = new Map<string | null, RealizationDeadlineOccurrence>()
    const names = [...new Set(group.flatMap(task => task.person ? [task.person] : []))]
    for (const task of group) {
      for (const occurrence of task.history || []) {
        const previous = history.get(occurrence.day)
        const preferred = !previous || stateRank[occurrence.state] >= stateRank[previous.state] ? occurrence : previous
        history.set(occurrence.day, { ...preferred, critical: Boolean(previous?.critical || occurrence.critical) })
      }
    }
    return {
      ...latest,
      state: group.some(task => task.state === "COMPLETED") ? "COMPLETED" : latest.state,
      critical: group.some(task => task.critical),
      person: names.join(", ") || undefined,
      history: [...history.values()].sort((a, b) => (a.day || "").localeCompare(b.day || "")),
    }
  })
}

export function weeklyDeadlineTotals(tasks: RealizationDeadlineTask[]) {
  return {
    deadlines: tasks.length,
    deadlinesCompleted: tasks.filter(task => task.state === "COMPLETED").length,
    deadlinesPostponed: tasks.filter(task => task.state === "POSTPONED").length,
    deadlinesInProgress: tasks.filter(task => task.state === "IN_PROGRESS").length,
    deadlinesNoProgress: tasks.filter(task => task.state === "NO_PROGRESS").length,
    criticalDeadlines: tasks.filter(task => task.critical).length,
    criticalDeadlinesCompleted: tasks.filter(task => task.critical && task.state === "COMPLETED").length,
  }
}
