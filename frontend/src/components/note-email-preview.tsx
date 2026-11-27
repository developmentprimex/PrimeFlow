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

export function emailSubjectKind(subject: string): "Forward" | "Reply" | undefined {
  const prefix = /^\s*(fwd?|wg|re|aw)\s*:/i.exec(subject)?.[1].toLowerCase()
  if (!prefix) return
  return prefix === "re" || prefix === "aw" ? "Reply" : "Forward"
}

export function EmailKindBadge({ kind }: { kind?: ReturnType<typeof emailSubjectKind> }) {
  if (!kind) return null
  return <span className="mr-1.5 inline-block rounded border border-blue-700/30 bg-blue-50 px-1.5 text-[11px] font-semibold leading-4 text-blue-950 dark:bg-blue-950 dark:text-blue-100">{kind}</span>
}

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

export function EmailNoteDisclosure({ title, children, sourceUrl, kind, outlookUrl }: {
  title: string; children: React.ReactNode; sourceUrl?: string; kind?: ReturnType<typeof emailSubjectKind>
  outlookUrl?: string
}) {
  const [expanded, setExpanded] = React.useState(false)
  return (
    <details className="min-w-0 whitespace-normal" onToggle={event => setExpanded(event.currentTarget.open)}>
      <summary className="group flex cursor-pointer list-none items-start justify-between gap-2 rounded [overflow-wrap:anywhere] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700 [&::-webkit-details-marker]:hidden">
        <span className="min-w-0">
          <EmailKindBadge kind={kind} />
          <strong>{title}</strong>
        </span>
        <span
          className="inline-flex size-6 shrink-0 items-center justify-center rounded border border-blue-900 bg-blue-800 text-base font-bold leading-none text-white group-hover:bg-blue-950 print:hidden"
          aria-label={expanded ? "Mbyll detajet e shënimit" : "Hap detajet e shënimit"}
        >{expanded ? "−" : "+"}</span>
      </summary>
      <OriginalEmailLink sourceUrl={sourceUrl} />
      {outlookUrl && (
        <a href={outlookUrl} title="Kërkon komponentin PrimeFlow për Outlook Classic" className="ml-1 mt-2 inline-flex min-h-7 items-center rounded border border-blue-300 bg-background px-2 font-medium text-blue-700 underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 dark:text-blue-300 print:hidden">
          Hap në Outlook Classic
        </a>
      )}
      <div className="mt-2 max-h-72 overflow-y-auto overscroll-contain rounded border bg-background p-2 whitespace-pre-wrap [overflow-wrap:anywhere] print:hidden" tabIndex={0} aria-label="Detajet e shënimit">{children}</div>
    </details>
  )
}

export function NoteEmailPreview({ email, outlookClassic = false }: { email: NoteEmailPreview; outlookClassic?: boolean }) {
  const outlookUrl = outlookClassic && email.mailbox && email.internet_message_id
    ? `primeflow-outlook://message/${encodeURIComponent(email.mailbox)}/${encodeURIComponent(email.internet_message_id)}`
    : undefined
  return (
    <EmailNoteDisclosure title={email.title} sourceUrl={email.original_email_url} kind={emailSubjectKind(email.subject)} outlookUrl={outlookUrl}>
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
    kind: emailSubjectKind(match[2]),
  }
}

export function reportEmailNoteDetails(text: string, heading: NoteEmailHeading | undefined) {
  const note = text.trim().replace(/\s+/g, " ")
  if (!heading || (note !== heading.original && !note.startsWith(`${heading.original} `))) return null
  const body = emailNoteTextWithoutLink(note.slice(heading.original.length).trim(), heading.original_email_url)
  const kind = splitManualEmailNote(heading.original)?.kind ?? splitManualEmailNote(heading.title)?.kind
  return <EmailNoteDisclosure title={heading.title} sourceUrl={heading.original_email_url} kind={kind}>{body || "Ky shënim nuk ka detaje."}</EmailNoteDisclosure>
}
