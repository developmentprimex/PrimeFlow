import { type GaOccurrence, groups } from "./ga-personal"

// Existing volleyball entries were created before the Eventet group existed.
// Keep this explicit legacy classification; a one-time frequency alone never
// turns a regular task into an event.
export function isGaEvent(row: GaOccurrence) {
  return row.snapshot.reminder_group === "events"
    || row.snapshot.title.trim().toLocaleLowerCase("sq").startsWith("volejboll")
}

// Only the personal code families defined by the handoff share a row across
// people. Daily, deep-clean and school-morning duties remain distinct.
function personalCode(code: string) {
  return /^(DHGJ|BP)-([RML])-(D|TH|MS)$/.exec(code) || /^(SHK)-([RML])()$/.exec(code)
}

export function groupWeekTasks(rows: GaOccurrence[]) {
  const tasks = new Map<string, GaOccurrence[]>()
  for (const row of rows) {
    const d = row.snapshot, code = d.short_code || "", personal = personalCode(code)
    const identity = personal ? ["personal", personal[1], personal[3]]
      : code ? ["code", code, d.area_id] : ["title", d.title.trim().toLocaleLowerCase("sq"), d.area_id]
    const key = JSON.stringify([d.reminder_group, d.frequency, ...identity])
    tasks.set(key, [...(tasks.get(key) || []), row])
  }
  return Array.from(tasks, ([id, entries]) => {
    const codes = Array.from(new Set(entries.map((r) => r.snapshot.short_code).filter((code): code is string => !!code)))
    const personal = personalCode(codes[0] || "")
    const letters = ["R", "M", "L"].filter((letter) => codes.some((code) => personalCode(code)?.[2] === letter))
    const label = personal && codes.length > 1
      ? `${personal[1]}-${letters.join("/")}${personal[3] ? `-${personal[3]}` : ""}` : codes[0] || entries[0].snapshot.title
    const titles = Array.from(new Set(entries.map((r) => `${r.snapshot.short_code ? `${r.snapshot.short_code} — ` : ""}${r.snapshot.title}`)))
    return { id, entries, label, titles, group: entries[0].snapshot.reminder_group, isEvent: isGaEvent(entries[0]) }
  }).sort((a, b) => Number(b.isEvent) - Number(a.isEvent) || Object.keys(groups).indexOf(a.group) - Object.keys(groups).indexOf(b.group)
    || a.entries[0].snapshot.title.localeCompare(b.entries[0].snapshot.title, "sq"))
}

export function canEditTime(row: GaOccurrence) {
  return !!row.can_edit && !["done", "cancelled"].includes(row.status)
}
