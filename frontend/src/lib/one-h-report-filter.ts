import { collapseEmptyReportTaskRows } from "./one-h-report-users"

export function applyOneHReportFilter(document: Document, strikesOnly: boolean): { visible: number; total: number; strikeTotal: number | null } {
  // Also handle a preview fetched from the previous API version during a deploy.
  document.getElementById("one-h-strikes-filter")?.parentElement?.remove()
  const tasks = document.querySelectorAll<HTMLElement>('[data-report-task="true"]')
  let visible = 0
  const strikesByTask = new Map<string, number>()
  tasks.forEach((task, index) => {
    task.hidden = strikesOnly && !(Number(task.dataset.strikeCount) > 0)
    if (!task.hidden) visible += 1
    const count = Number(task.dataset.strikeCount)
    if (task.dataset.strikeCount !== undefined && Number.isFinite(count) && count >= 0) {
      // The same task can appear in SHTYPI, a slot, and BLL. Count it once.
      const key = task.dataset.taskId || `card-${index}`
      strikesByTask.set(key, Math.max(strikesByTask.get(key) ?? 0, count))
    }
  })
  // SHTYPI uses paired content/date rows and slot labels spanning chunks.
  // Filter both halves of each card, then move labels out of hidden chunks.
  document.querySelectorAll<HTMLTableRowElement>('tr[data-task-card-row="content"]').forEach((row) => {
    const dates = row.nextElementSibling as HTMLTableRowElement | null
    const dateCells = dates?.matches('tr[data-task-card-row="dates"]') ? Array.from(dates.cells) : []
    Array.from(row.cells).filter(cell => cell.tagName === "TD").forEach((cell, index) => {
      const hide = strikesOnly && (!cell.matches('[data-report-task="true"]') || cell.hidden)
      cell.style.display = hide ? "none" : ""
      if (dateCells[index]) dateCells[index].style.display = hide ? "none" : ""
    })
  })
  collapseEmptyReportTaskRows(document, strikesOnly)
  document.querySelectorAll<HTMLElement>("[data-report-task-employee], [data-report-task-section]").forEach((group) => {
    group.hidden = strikesOnly && !group.querySelector('[data-report-task="true"]:not([hidden])')
  })
  document.querySelectorAll<HTMLElement>("[data-report-non-task-supplement], [data-ga-task-summary]").forEach((group) => { group.hidden = strikesOnly })
  document.querySelectorAll<HTMLElement>("[data-report-supplement], [data-report-print-section]").forEach((group) => {
    group.hidden = strikesOnly && !group.querySelector('[data-report-task="true"]:not([hidden])')
  })
  const strikeTotal = tasks.length && !strikesByTask.size ? null : [...strikesByTask.values()].reduce((sum, count) => sum + count, 0)
  return { visible, total: tasks.length, strikeTotal }
}
