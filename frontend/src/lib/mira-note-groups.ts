import type { MiraNote } from "@/lib/mira"

export type MiraNoteGroup = "1H" | "AI_AGENT" | "OTHER"

export const MIRA_DEVELOPMENT_NAME = "Mira Zhvillim"

export const MIRA_NOTE_GROUPS: { value: MiraNoteGroup; label: string }[] = [
  { value: "1H", label: "1H" },
  { value: "AI_AGENT", label: MIRA_DEVELOPMENT_NAME },
  { value: "OTHER", label: "Të tjera" },
]

export function miraNoteGroup(note: MiraNote): MiraNoteGroup {
  if (note.meeting_group) return note.meeting_group
  if (note.kind === "1H" || note.source === "1H") return "1H"
  if (note.source === "DESKTOP") return "OTHER"
  if (/^(?:(?:(?:Mira[ \t]+)?AI[ \t_-]*Agent|Mira[ \t]+Zhvillim)\b|Zhvillim(?=\s+(?:\d|·)|$))/i.test(note.title.trim())) return "AI_AGENT"
  if (/^1H\b/i.test(note.title.trim())) return "1H"
  return "OTHER"
}
