import type { MiraNote } from "@/lib/mira"

export type MiraNoteGroup = "1H" | "AI_AGENT" | "OTHER"

export const MIRA_NOTE_GROUPS: { value: MiraNoteGroup; label: string }[] = [
  { value: "1H", label: "1H" },
  { value: "AI_AGENT", label: "AI Agent" },
  { value: "OTHER", label: "Të tjera" },
]

export function miraNoteGroup(note: MiraNote): MiraNoteGroup {
  if (note.meeting_group) return note.meeting_group
  if (note.kind === "1H" || note.source === "1H") return "1H"
  if (note.source === "DESKTOP") return "OTHER"
  if (/^AI[\s_-]*AGENT\b/i.test(note.title.trim())) return "AI_AGENT"
  if (/^1H\b/i.test(note.title.trim())) return "1H"
  return "OTHER"
}
