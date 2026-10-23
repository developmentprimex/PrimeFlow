export function applyOneHReportFilter(document: Document, strikesOnly: boolean): number {
  // Also handle a preview fetched from the previous API version during a deploy.
  document.getElementById("one-h-strikes-filter")?.parentElement?.remove()
  let visible = 0
  document.querySelectorAll<HTMLElement>('[data-report-task="true"]').forEach((task) => {
    task.hidden = strikesOnly && !(Number(task.dataset.strikeCount) > 0)
    if (!task.hidden) visible += 1
  })
  document.querySelectorAll<HTMLElement>("[data-report-task-employee], [data-report-task-section]").forEach((group) => {
    group.hidden = strikesOnly && !group.querySelector('[data-report-task="true"]:not([hidden])')
  })
  document.querySelectorAll<HTMLElement>("[data-report-supplement]").forEach((group) => { group.hidden = strikesOnly })
  return visible
}
