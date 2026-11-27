import { getPlainMarkedText } from "@/lib/note-markup"

export type PersonalTaskGroup = "GA" | "KA" | "GENT" | "PX"

export function getPersonalTaskGroup(entry: { title: string }): PersonalTaskGroup {
  const title = getPlainMarkedText(entry.title).split(/\r?\n/).map((line) => line.trim()).find(Boolean) ?? ""
  const match = title.toUpperCase().match(/^[A-Z]{1,5}(?:\s*[:/]\s*[A-Z]{1,5})*(?=\s|:|\/|$)/)
  const participants = (match?.[0] || "").split(/[:/]/).map((value) => value.trim())
  if (participants.some((value) => ["GENT", "GENTI", "GT"].includes(value))) return "GENT"
  if (participants.includes("KA")) return "KA"
  if (participants.includes("GA")) return "GA"
  return "PX"
}
