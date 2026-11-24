"use client"

import * as React from "react"
import { useAuth } from "@/lib/auth"
import type { NoteEmailPreview } from "@/lib/types"

export function useNoteEmailLoader() {
  const { apiFetch } = useAuth()
  return React.useCallback(async (id: string) => {
    const response = await apiFetch(`/ga-notes/${encodeURIComponent(id)}/email`, { cache: "no-store" })
    if (!response.ok) throw new Error("Emaili origjinal nuk është i disponueshëm.")
    const email: { body: string } = await response.json()
    return email.body
  }, [apiFetch])
}

export function NoteEmailPreview({ email }: { email: NoteEmailPreview }) {
  const loadEmail = useNoteEmailLoader()
  const [expanded, setExpanded] = React.useState(false)
  const [body, setBody] = React.useState<string | null>(null)
  const [failed, setFailed] = React.useState(false)
  const [loading, setLoading] = React.useState(false)

  return (
    <details className="min-w-0 whitespace-normal" onToggle={event => {
      const open = event.currentTarget.open
      setExpanded(open)
      if (!open || body !== null || loading) return
      setFailed(false)
      setLoading(true)
      void loadEmail(email.id).then(setBody, () => setFailed(true)).finally(() => setLoading(false))
    }}>
      <summary className="flex cursor-pointer list-none items-start justify-between gap-2 [overflow-wrap:anywhere] [&::-webkit-details-marker]:hidden">
        <span><strong>{email.title}</strong>{[email.subject, email.sender].filter(Boolean).map((value, index) => <span key={index}> · {value}</span>)}</span>
        <span className="shrink-0 rounded border px-1.5 font-semibold print:hidden" aria-label={expanded ? "Mbyll emailin" : "Hap emailin"}>{expanded ? "−" : "+"}</span>
      </summary>
      <div className="mt-2 max-h-72 overflow-auto rounded border bg-background p-2 whitespace-pre-wrap [overflow-wrap:anywhere] print:hidden">
        {failed ? "Emaili origjinal nuk është i disponueshëm." : body === null ? "Duke hapur emailin…" : body || "Ky email nuk ka tekst."}
      </div>
    </details>
  )
}
