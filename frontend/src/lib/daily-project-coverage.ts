import { isProjectCoverageDepartment } from "./one-h-project-coverage"

export type CoverageRow = { typeLabel?: string; subtype?: string; period?: string; status?: string; oneHReportSlot?: string | null }

export function dailyCoverageNotices(rows: CoverageRow[], department: string, slotDisplay: (row: CoverageRow) => string) {
  const projectPeriods = new Set(rows
    .filter((row) => row.typeLabel === "PRJK" && isProjectCoverageDepartment(department))
    .flatMap((row) => row.period === "AM/PM" ? ["AM", "PM"] : [row.period]))
  const personalPeriods = new Set(rows
    .filter((row) => ["P", "P:", "PERSONAL"].includes((row.subtype || "").trim().toUpperCase()))
    .flatMap((row) => !row.period || row.period === "AM/PM" ? ["AM", "PM"] : [row.period]))
  const notices: Array<{ key: string; covered: boolean; text: string }> = []
  if (!rows.some((row) => slotDisplay(row) === "10:00")) {
    const covered = projectPeriods.has("AM") || personalPeriods.has("AM")
    notices.push({ key: "am", covered, text: personalPeriods.has("AM")
      ? "AM mbulohet nga detyrë personale; mungesa e slotit 1H 10:00 është e arsyetuar."
      : covered
      ? "AM mbulohet nga detyrë projekti (PCM/Design); mungesa e slotit 1H 10:00 është e arsyetuar."
      : "Mungon sloti 1H 10:00; AM nuk mbulohet nga detyrë personale ose projekti PCM/Design." })
  }
  if (!rows.some((row) => ["BLL", "BLLOK"].includes(row.subtype || ""))) {
    const projectCovered = projectPeriods.has("PM")
    const personalCovered = personalPeriods.has("PM")
    const slotCovered = rows.some((row) => slotDisplay(row) === "16:00")
    notices.push({ key: "bll", covered: projectCovered || personalCovered || slotCovered, text: personalCovered
      ? "PM mbulohet nga detyrë personale; mungesa e detyrës BLL është e arsyetuar."
      : projectCovered
      ? "PM mbulohet nga detyrë projekti (PCM/Design); mungesa e detyrës BLL është e arsyetuar."
      : slotCovered ? "Mungesa e detyrës BLL është e arsyetuar nga detyra me slot 1H 16:00."
      : "Mungon detyra BLL; PM nuk mbulohet nga sloti 1H 16:00, detyrë personale ose projekti PCM/Design." })
  }
  if (!rows.some((row) => ["PM", "AM/PM"].includes(row.period || ""))) {
    notices.push({ key: "pm", covered: false, text: "Nuk ka detyrë të planifikuar në PM për këtë ditë." })
  }
  return notices
}
