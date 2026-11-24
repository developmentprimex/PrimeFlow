"use client"

import * as React from "react"
import type { NoteEmailHeading, NoteEmailPreview } from "@/lib/types"

const MAIL_WEB_HOSTS = new Set([
  "outlook.office.com", "outlook.office365.com", "outlook.live.com", "outlook.cloud.microsoft",
  "mail.google.com", "mail.yandex.com", "mail.yandex.ru", "mail.ya.ru",
])
const MANUAL_EMAIL_LINK = /(?:^|\s)Email origjinal:\s*(\S+)\s*$/i
export const ORIGINAL_EMAIL_LABEL = "Hap emailin origjinal"
export const NO_EMAIL_SUMMARY = "Ky shënim nuk ka përmbledhje të ruajtur."

export function originalEmailUrl(value?: string) {
  if (!value || /[\s\\]/.test(value)) return undefined
  try {
    const url = new URL(value)
    if (url.protocol === "https:" && MAIL_WEB_HOSTS.has(url.host) && !url.username && !url.password) return url.href
  } catch {
    return undefined
  }
}

export function emailNoteTextWithoutLink(text: string, sourceUrl?: string) {
  const match = MANUAL_EMAIL_LINK.exec(text)
  return sourceUrl && match?.[1] === sourceUrl ? text.slice(0, match.index).trimEnd() : text
}

export function OriginalEmailLink({ sourceUrl }: { sourceUrl?: string }) {
  const href = originalEmailUrl(sourceUrl)
  if (!href) return null
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex min-h-7 items-center rounded border border-blue-300 bg-background px-2 font-medium text-blue-700 underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 dark:text-blue-300 print:hidden">
      {ORIGINAL_EMAIL_LABEL}
    </a>
  )
}

export function EmailNoteDisclosure({ title, children, sourceUrl }: {
  title: string; children: React.ReactNode; sourceUrl?: string
}) {
  const [expanded, setExpanded] = React.useState(false)
  return (
    <details className="min-w-0 whitespace-normal" onToggle={event => setExpanded(event.currentTarget.open)}>
      <summary className="group flex cursor-pointer list-none items-start justify-between gap-2 rounded [overflow-wrap:anywhere] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700 [&::-webkit-details-marker]:hidden">
        <strong>{title}</strong>
        <span
          className="inline-flex size-6 shrink-0 items-center justify-center rounded border border-blue-900 bg-blue-800 text-base font-bold leading-none text-white group-hover:bg-blue-950 print:hidden"
          aria-label={expanded ? "Mbyll detajet e shënimit" : "Hap detajet e shënimit"}
        >{expanded ? "−" : "+"}</span>
      </summary>
      <OriginalEmailLink sourceUrl={sourceUrl} />
      <div className="mt-2 max-h-72 overflow-y-auto overscroll-contain rounded border bg-background p-2 whitespace-pre-wrap [overflow-wrap:anywhere] print:hidden" tabIndex={0} aria-label="Detajet e shënimit">{children}</div>
    </details>
  )
}

export function NoteEmailPreview({ email }: { email: NoteEmailPreview }) {
  return (
    <EmailNoteDisclosure title={email.title} sourceUrl={email.original_email_url}>
      {email.summary || NO_EMAIL_SUMMARY}
    </EmailNoteDisclosure>
  )
}

export function splitManualEmailNote(content: string) {
  const [heading, ...lines] = content.trimStart().split(/\r?\n/)
  const match = /^(EM (?:INFO PX|IT|HF|PX EU|GA|GMAIL)):\s*\d{1,2}:\d{2}\s+(.+)$/i.exec(heading.trim())
  if (!match) return null
  const body = lines.join("\n").trim()
  const link = MANUAL_EMAIL_LINK.exec(body.split(/\r?\n/).at(-1)?.trim() || "")
  const sourceUrl = originalEmailUrl(link?.[1]) ? link?.[1] : undefined
  return {
    title: `${match[1].toUpperCase()}: 08:00 ${match[2].toUpperCase()}`,
    body: emailNoteTextWithoutLink(body, sourceUrl),
    sourceUrl,
  }
}

export function reportEmailNoteDetails(text: string, heading: NoteEmailHeading | undefined) {
  const note = text.trim().replace(/\s+/g, " ")
  if (!heading || (note !== heading.original && !note.startsWith(`${heading.original} `))) return null
  const body = emailNoteTextWithoutLink(note.slice(heading.original.length).trim(), heading.original_email_url)
  return <EmailNoteDisclosure title={heading.title} sourceUrl={heading.original_email_url}>{body || "Ky shënim nuk ka detaje."}</EmailNoteDisclosure>
}
