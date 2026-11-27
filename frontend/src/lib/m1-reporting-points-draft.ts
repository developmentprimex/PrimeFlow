import type { ManualAnswers, ManualKey } from "@/components/m1-reporting-points-view"

type DraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">
const storageKey = (userId: string) => `primeflow:m1-reporting-points:answers:${userId}`
const manualKeys = ["plan_changes", "reorganization", "reorganization_form"] as const

export function changedManualAnswers(saved: ManualAnswers, edited: ManualAnswers): ManualAnswers {
  const changes: ManualAnswers = {}
  for (const key of manualKeys) {
    if ((saved[key] || "") !== (edited[key] || "")) changes[key] = edited[key] || ""
  }
  return changes
}

export function readManualDraft(storage: DraftStorage | null, userId: string, day: string): ManualAnswers | null {
  try {
    const draft = JSON.parse(storage?.getItem(storageKey(userId)) || "null")
    if (!draft || draft.day !== day || !draft.answers || typeof draft.answers !== "object") return null
    const answers: ManualAnswers = {}
    for (const key of manualKeys) {
      const value = draft.answers[key]
      if (typeof value === "string" && value.length <= (key === "reorganization_form" ? 61000 : 10000)) answers[key] = value
    }
    return answers
  } catch { return null }
}

export function shouldAdvanceReportDay(selectedDay: string, previousToday: string, currentToday: string, hasPendingWork: boolean) {
  return selectedDay === previousToday && currentToday !== previousToday && !hasPendingWork
}

export function writeManualDraft(storage: DraftStorage | null, userId: string, day: string, answers: ManualAnswers) {
  try { storage?.setItem(storageKey(userId), JSON.stringify({ day, answers })) } catch { /* Server saving still works if storage is blocked. */ }
}

export function clearSavedManualDraft(storage: DraftStorage | null, userId: string, day: string, saved: ManualAnswers) {
  const draft = readManualDraft(storage, userId, day)
  // A slower save must never remove newer text typed while it was in flight.
  if (draft && (Object.keys(draft) as ManualKey[]).every((key) => (draft[key] || "") === (saved[key] || ""))) {
    try { storage?.removeItem(storageKey(userId)) } catch { /* The saved server copy remains available. */ }
  }
}

