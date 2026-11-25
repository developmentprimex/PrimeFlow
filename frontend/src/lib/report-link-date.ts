import { useState, useSyncExternalStore } from "react"

function subscribe(callback: () => void) {
  window.addEventListener("popstate", callback)
  return () => window.removeEventListener("popstate", callback)
}

function getSnapshot() {
  const value = new URLSearchParams(window.location.search).get("date")
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return ""
  const day = new Date(`${value}T00:00:00Z`)
  return Number.isFinite(day.getTime()) && day.toISOString().slice(0, 10) === value ? value : ""
}

export function useReportLinkDate() {
  return useSyncExternalStore(subscribe, getSnapshot, () => "")
}

export function useReportDate(initialDate: () => string) {
  const linkedDate = useReportLinkDate()
  const [defaultDate] = useState(initialDate)
  const [selectedDate, selectDate] = useState<string | null>(null)
  return [selectedDate ?? (linkedDate || defaultDate), selectDate, linkedDate] as const
}
