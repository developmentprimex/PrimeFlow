import { isProjectCoverageDepartment } from "./one-h-project-coverage"

export type CoverageRow = { typeLabel?: string; subtype?: string; period?: string; status?: string; oneHReportSlot?: string | null }

export function dailyCoverageNotices(rows: CoverageRow[], department: string, slotDisplay: (row: CoverageRow) => string) {
  const projectPeriods = new Set(rows
    .filter((row) => row.typeLabel === "PRJK" && isProjectCoverageDepartment(department))
    .flatMap((row) => row.period === "AM/PM" ? ["AM", "PM"] : [row.period]))
  const notices: Array<{ key: string; covered: boolean; text: string }> = []
  if (!rows.some((row) => slotDisplay(row) === "10:00")) {
    const covered = projectPeriods.has("AM")
    notices.push({ key: "am", covered, text: covered
      ? "AM mbulohet nga detyrë projekti (PCM/Design); mungesa e slotit 1H 10:00 është e arsyetuar."
      : "Mungon detyra me slot 1H 10:00 për këtë ditë; nuk ka detyrë projekti PCM/Design që mbulon AM." })
  }
  if (!rows.some((row) => ["BLL", "BLLOK"].includes(row.subtype || ""))) {
    const projectCovered = projectPeriods.has("PM")
    const slotCovered = rows.some((row) => slotDisplay(row) === "16:00")
    notices.push({ key: "bll", covered: projectCovered || slotCovered, text: projectCovered
      ? "PM mbulohet nga detyrë projekti (PCM/Design); mungesa e detyrës BLL është e arsyetuar."
      : slotCovered ? "Mungesa e detyrës BLL është e arsyetuar nga detyra me slot 1H 16:00."
      : "Mungon detyra BLL për këtë ditë; nuk ka slot 1H 16:00 ose detyrë projekti PCM/Design që mbulon PM." })
  }
  if (!rows.some((row) => ["PM", "AM/PM"].includes(row.period || ""))) {
    notices.push({ key: "pm", covered: false, text: "Nuk ka detyrë të planifikuar në PM për këtë ditë." })
  }
  return notices
}
