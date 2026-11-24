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

export function EmailNoteDisclosure({ title, children, onOpen }: {
  title: string; children: React.ReactNode; onOpen?: () => void
}) {
  const [expanded, setExpanded] = React.useState(false)
  return (
    <details className="min-w-0 whitespace-normal" onToggle={event => {
      const open = event.currentTarget.open
      setExpanded(open)
      if (open) onOpen?.()
    }}>
      <summary className="group flex cursor-pointer list-none items-start justify-between gap-2 rounded [overflow-wrap:anywhere] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700 [&::-webkit-details-marker]:hidden">
        <strong>{title}</strong>
        <span
          className="inline-flex size-6 shrink-0 items-center justify-center rounded border border-blue-900 bg-blue-800 text-base font-bold leading-none text-white group-hover:bg-blue-950 print:hidden"
          aria-label={expanded ? "Mbyll emailin" : "Hap emailin"}
        >{expanded ? "−" : "+"}</span>
      </summary>
      <div className="mt-2 max-h-72 overflow-y-auto overscroll-contain rounded border bg-background p-2 whitespace-pre-wrap [overflow-wrap:anywhere] print:hidden" tabIndex={0} aria-label="Detajet e emailit">{children}</div>
    </details>
  )
}

export function NoteEmailPreview({ email }: { email: NoteEmailPreview }) {
  const loadEmail = useNoteEmailLoader()
  const [body, setBody] = React.useState<string | null>(null)
  const [failed, setFailed] = React.useState(false)
  const [loading, setLoading] = React.useState(false)

  return (
    <EmailNoteDisclosure title={email.title} onOpen={() => {
      if (body !== null || loading) return
      setFailed(false)
      setLoading(true)
      void loadEmail(email.id).then(setBody, () => setFailed(true)).finally(() => setLoading(false))
    }}>
      {email.subject && <div><strong>Subjekti</strong> · {email.subject}</div>}
      {email.sender && <div><strong>Dërguesi</strong> · {email.sender}</div>}
      <div className="mt-2">{failed ? "Emaili origjinal nuk është i disponueshëm." : body === null ? "Duke hapur emailin…" : body || "Ky email nuk ka tekst."}</div>
    </EmailNoteDisclosure>
  )
}

export function splitManualEmailNote(content: string) {
  const [heading, ...lines] = content.trimStart().split(/\r?\n/)
  const match = /^(EM (?:INFO PX|IT|HF|PX EU|GA|GMAIL)):\s*\d{1,2}:\d{2}\s+(.+)$/i.exec(heading.trim())
  return match ? { title: `${match[1].toUpperCase()}: 08:00 ${match[2].toUpperCase()}`, body: lines.join("\n").trim() } : null
}

export function reportEmailNoteDetails(text: string, heading: { title: string; original: string } | undefined) {
  const note = text.trim().replace(/\s+/g, " ")
  if (!heading || (note !== heading.original && !note.startsWith(`${heading.original} `))) return null
  const body = note.slice(heading.original.length).trim()
  return <EmailNoteDisclosure title={heading.title}>{body || "Ky shënim nuk ka detaje."}</EmailNoteDisclosure>
}
