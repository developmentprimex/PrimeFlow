export function reportTaskUsers(cell: HTMLElement): string[] {
  const saved = cell.dataset.taskUsers
  if (saved) return saved.split("|").filter(Boolean)
  // Older saved reports predate the owner metadata.
  const title = cell.querySelector('[data-task-title-text="true"]')?.textContent || ""
  const match = title.match(/^\s*\d+\.\s*([A-Z]{1,4}(?:\/[A-Z]{1,4})*):/)
  return match ? match[1].split("/") : []
}

export function reportSummaryUser(cell: HTMLElement): string {
  return cell.dataset.gaSummaryUser || cell.querySelector("strong")?.textContent?.trim() || ""
}

export function isReportSummaryTask(cell: HTMLElement): boolean {
  const marker = cell.dataset.taskMarker || ""
  if (["FLAG", "GA", "F", "M2", "M2_M3"].includes(marker)) return true
  if (cell.dataset.taskGaPersonal !== undefined) return cell.dataset.taskGaPersonal === "true"
  // Saved reports can still be filtered before they are regenerated.
  const title = (cell.querySelector('[data-task-title-text="true"]')?.textContent || "").replace(/^\s*\d+\.\s*/, "")
  const prefix = title.match(/^[A-Z]{1,5}(?:\s*[:/]\s*[A-Z]{1,5})*(?=\s|:|\/|$)/i)?.[0] || ""
  const people = prefix.toUpperCase().split(/\s*[:/]\s*/)
  return people.includes("GA") && !people.some((person) => ["GENT", "GENTI", "GT", "KA"].includes(person))
}

export function reportUserOptions(document: Document): string[] {
  const users = new Set<string>()
  // Keep the report's person order, then append owners absent from the summary.
  document.querySelectorAll<HTMLElement>('[data-ga-task-summary="true"] td').forEach((cell) => {
    const user = reportSummaryUser(cell)
    if (user) users.add(user)
  })
  document.querySelectorAll<HTMLElement>('tr[data-task-card-row="content"] > td').forEach((cell) => {
    reportTaskUsers(cell).forEach((user) => users.add(user))
  })
  return [...users]
}

export function collapseEmptyReportTaskRows(document: Document, filtering: boolean): void {
  const rows = Array.from(document.querySelectorAll<HTMLTableRowElement>('tr[data-task-card-row="content"]'))
  const groups = new Map<string, HTMLTableRowElement[]>()
  let group = ""
  rows.forEach((row, index) => {
    if (row.dataset.taskFilterGroup === undefined) {
      if (Array.from(row.cells).some((cell) => cell.tagName === "TH")) group = String(index)
      row.dataset.taskFilterGroup = group
    } else group = row.dataset.taskFilterGroup
    const grouped = groups.get(group) || []
    grouped.push(row)
    groups.set(group, grouped)
  })
  groups.forEach((groupRows) => {
    const visible = groupRows.filter((row) => !filtering || Array.from(row.cells).some((cell) =>
      cell.tagName === "TD" && cell.style.display !== "none" &&
      Boolean(cell.dataset.taskId || cell.querySelector('[data-task-title-text="true"]'))))
    groupRows.forEach((row) => {
      row.style.display = visible.includes(row) ? "" : "none"
      const dates = row.nextElementSibling as HTMLElement | null
      if (dates?.matches('tr[data-task-card-row="dates"]')) dates.style.display = row.style.display
    })
    // Slot labels span every chunk. Move them when the first chunk is hidden.
    const headers = groupRows.flatMap((row) => Array.from(row.cells).filter((cell) => cell.tagName === "TH"))
    const first = visible[0] || groupRows[0]
    headers.reverse().forEach((header) => {
      header.rowSpan = Math.max(visible.length, 1) * 2
      first.insertBefore(header, first.firstChild)
    })
  })
}
