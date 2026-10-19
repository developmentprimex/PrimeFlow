import type { ManualAnswers, ManualKey } from "@/components/m3-reporting-points-view"

type DraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">
const keys = ["underload", "overload", "reorganization"] as const
const validKey = (key: string): key is ManualKey => keys.some((value) => value === key) ||
  /^(?:meeting_plan|untouched_comment):[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(key)
const storageKey = (userId: string) => `primeflow:m3-reporting-points:answers:${userId}`

export function readManualDraft(storage: DraftStorage | null, userId: string, day: string): ManualAnswers | null {
  try {
    const draft = JSON.parse(storage?.getItem(storageKey(userId)) || "null")
    if (!draft || draft.day !== day || !draft.answers || typeof draft.answers !== "object") return null
    const answers: ManualAnswers = {}
    for (const [key, value] of Object.entries(draft.answers)) {
      if (validKey(key) && typeof value === "string" && value.length <= 10000) answers[key] = value
    }
    return answers
  } catch { return null }
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
