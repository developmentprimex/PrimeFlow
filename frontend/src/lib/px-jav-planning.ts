export const pxJavCommentOptions = [
  { id: "next-week", label: "J.T — Javën tjetër", text: "J.T" },
  { id: "info", label: "INFO — Vetëm për informim", text: "INFO" },
  { id: "waiting-client", label: "Presim nga klienti", text: "Presim nga klienti" },
  { id: "waiting-internal", label: "Presim konfirmim të brendshëm", text: "Presim konfirmim të brendshëm" },
  { id: "after-next-week", label: "PAS J.T — Pas javës tjetër", text: "PAS J.T" },
  { id: "year-end", label: "31.12", text: "" },
  { id: "custom-date", label: "Shtyje deri më…", text: "" },
] as const

export type PxJavCommentOption = typeof pxJavCommentOptions[number]["id"]

const monthNames = [
  "janar", "shkurt", "mars", "prill", "maj", "qershor", "korrik", "gusht", "shtator", "tetor", "nentor", "dhjetor",
]

function validDate(iso: string): string | null {
  const date = new Date(`${iso}T00:00:00Z`)
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === iso ? iso : null
}

export function parsePxJavDate(value: string | null | undefined, referenceDay: string): string | null {
  const input = value?.trim() ?? ""
  if (/^\d{4}-\d{2}-\d{2}$/.test(input)) return validDate(input)
  const match = /^(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?\.?$/.exec(input)
  if (!match) return null
  const [, day, month, year] = match
  const suffix = `${month.padStart(2, "0")}-${day.padStart(2, "0")}`
  if (year) return validDate(`${year}-${suffix}`)
  const referenceYear = Number(referenceDay.slice(0, 4))
  for (let nextYear = referenceYear; nextYear <= referenceYear + 4; nextYear++) {
    const date = validDate(`${nextYear}-${suffix}`)
    if (date && date >= referenceDay) return date
  }
  return null
}

export function formatPxJavDate(iso: string): string {
  return iso.split("-").reverse().join(".")
}

export function pxJavAfterNextWeek(today: string): string {
  const date = new Date(`${today}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + 14 - (date.getUTCDay() + 6) % 7)
  return date.toISOString().slice(0, 10)
}

export function pxJavCommentPlan(value: string | null | undefined, referenceDay: string): {
  option: PxJavCommentOption
  reviewDate: string | null
  waiting: boolean
  detail: string
} | null {
  const [firstLine, ...rest] = (value ?? "").trim().split(/\r?\n/)
  const detail = rest.join("\n").trim()
  const [label, ...dateParts] = firstLine.split(" · ")
  const option = pxJavCommentOptions.find((item) => item.text && item.text.toLowerCase() === label.trim().toLowerCase())
  if (option) {
    const waiting = option.id === "waiting-client" || option.id === "waiting-internal"
    const reviewDate = parsePxJavDate(dateParts.join(" · "), referenceDay)
    if (dateParts.length && (!reviewDate || (!waiting && option.id !== "after-next-week"))) return null
    return {
      option: option.id,
      reviewDate: reviewDate ?? (option.id === "after-next-week" ? pxJavAfterNextWeek(referenceDay) : null),
      waiting,
      detail,
    }
  }

  const notNextWeek = /^nuk [eë]sht[eë] (?:j\s*[.,]\s*t\.?|jav[eë]n tjet[eë]r)(?=$|\s|[,:;(])\s*[,;:]?\s*(.*)$/iu.exec(firstLine)
  if (notNextWeek) {
    return {
      option: "after-next-week",
      reviewDate: pxJavAfterNextWeek(referenceDay),
      waiting: false,
      detail: [notNextWeek[1], ...rest].join("\n").trim(),
    }
  }

  const normalized = firstLine.toLowerCase().normalize("NFD").replace(/\p{M}/gu, "")
  const month = /^([a-z]+)\s+(\d{4})$/.exec(normalized)
  const monthIndex = month ? monthNames.indexOf(month[1]) + 1 : 0
  const reviewDate = parsePxJavDate(firstLine, referenceDay) ??
    (month && monthIndex ? `${month[2]}-${String(monthIndex).padStart(2, "0")}-01` : null)
  if (!reviewDate) return null
  return { option: reviewDate.endsWith("-12-31") ? "year-end" : "custom-date", reviewDate, waiting: false, detail }
}

export function pxJavCommentWithPlan(
  previous: string,
  option: PxJavCommentOption | null,
  reviewDate: string | null,
  referenceDay: string,
): string {
  const detail = pxJavCommentPlan(previous, referenceDay)?.detail ?? previous.trim()
  const text = pxJavCommentOptions.find((item) => item.id === option)?.text
  const standard = [text, reviewDate && formatPxJavDate(reviewDate)].filter(Boolean).join(" · ")
  return [standard, detail].filter(Boolean).join("\n")
}

export function isPxJavCommentDeferred(comment: string | null | undefined, today: string, referenceDay: string): boolean {
  const plan = pxJavCommentPlan(comment, referenceDay)
  return plan?.reviewDate ? today < plan.reviewDate : plan?.waiting === true
}
