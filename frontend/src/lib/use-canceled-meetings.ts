"use client"

import { useCallback, useEffect, useState } from "react"
import { useAuth } from "@/lib/auth"
import type { MeetingOccurrenceStatus } from "@/lib/types"
import { useVisibleRefresh } from "@/lib/use-visible-refresh"

export function canceledMeetingIds(rows: MeetingOccurrenceStatus[], day: string): Set<string> {
  return new Set(rows
    .filter((row) => row.occurrence_date === day && row.status === "canceled")
    .map((row) => row.meeting_id))
}

export function useCanceledMeetings(day: string) {
  const { apiFetch } = useAuth()
  const [loaded, setLoaded] = useState<{ day: string; ids: Set<string> } | null>(null)
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const response = await apiFetch(`/meetings/occurrence-statuses?occurrence_date=${encodeURIComponent(day)}`, { signal })
      if (!response.ok) return
      const rows = await response.json() as MeetingOccurrenceStatus[]
      if (!signal?.aborted) return { day, ids: canceledMeetingIds(rows, day) }
    } catch { /* Keep the last successful status on network errors. */ }
  }, [apiFetch, day])

  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal).then((result) => {
      if (result && !controller.signal.aborted) setLoaded(result)
    })
    return () => controller.abort()
  }, [load])
  useVisibleRefresh(async () => {
    const result = await load()
    if (result) setLoaded(result)
  })

  return loaded?.day === day ? loaded.ids : new Set<string>()
}
