export const DAILY_RLZ_REASONS = [
  ["TOOK_LONGER", "Mori më shumë kohë"],
  ["OTHER_URGENCY", "Urgjencë tjetër"],
  ["WAITING_CLIENT", "Në pritje të klientit"],
  ["PRIORITY_CHANGE", "Ndryshim prioriteti"],
  ["TECHNICAL_PROBLEM", "Problem teknik"],
  ["MISSING_INFORMATION", "Mungesë informacioni"],
  ["REQUEST_CHANGE", "Ndryshim kërkese"],
  ["NEW_REQUESTS", "Kërkesa të reja"],
  ["ABSENCE", "Mungesë"],
  ["PV", "PV"],
  ["OTHER", "Tjetër"],
] as const

export const WEEKLY_PLANNING_REASON = "WEEKLY_PLANNING"
const WEEKLY_PLANNING_REASON_OPTION = [WEEKLY_PLANNING_REASON, "Planifikim javor"] as const
export const TASK_POSTPONEMENT_REASONS = [...DAILY_RLZ_REASONS, WEEKLY_PLANNING_REASON_OPTION] as const

const DAILY_RLZ_REASON_LABELS = Object.fromEntries(TASK_POSTPONEMENT_REASONS)

export function dailyRlzReasonRequiresComment(code?: string | null) {
  return code !== "PV" && code !== WEEKLY_PLANNING_REASON
}

export function dailyRlzReasonLabel(code?: string | null) {
  if (!code) return null
  return DAILY_RLZ_REASON_LABELS[code as keyof typeof DAILY_RLZ_REASON_LABELS] || "Arsye tjetër"
}
