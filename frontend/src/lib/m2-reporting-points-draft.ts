import type { ManualAnswers, ManualKey } from "@/components/m2-reporting-points-view"

type DraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">
const storageKey = (userId: string) => `primeflow:m2-reporting-points:answers:${userId}`

export function readManualDraft(storage: DraftStorage | null, userId: string, day: string): ManualAnswers | null {
  try {
    const draft = JSON.parse(storage?.getItem(storageKey(userId)) || "null")
    if (!draft || draft.day !== day || !draft.answers || typeof draft.answers !== "object") return null
    const answers: ManualAnswers = {}
    for (const key of Object.keys(draft.answers) as ManualKey[]) {
      if (key !== "reorganization" && !/^(?:delivery(?:_choice)?|postponed_comment):[a-f0-9-]{36}$/.test(key)) continue
      const value = draft.answers[key]
      if (key.startsWith("delivery_choice:") && !["", "PO", "JO"].includes(value)) continue
      if (typeof value === "string" && value.length <= 10000) answers[key] = value
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
