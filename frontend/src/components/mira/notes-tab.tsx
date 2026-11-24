"use client"

import { useEffect, useState, type ReactNode } from "react"
import Link from "next/link"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import { clock, json } from "@/lib/mira"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Summary } from "@/components/mira/meetings-tab"

export type MeetingNote = {
  id: string
  kind: "1H" | "PX_NOTE"
  title: string
  content: string
  status: string
  created_at: string | null
  note_id: string | null
  shared_to_px: boolean
  shareable?: boolean
  created_during_meeting?: boolean
}

const statusLabels: Record<string, string> = {
  OPEN: "E hapur", CLOSED: "E mbyllur", DONE: "Përfundoi", ABORTED: "U ndërpre",
}

const transcriptHeading = /^\*\*Transkripti fjalë për fjalë\*\*\s*$/im
const summaryHeading = /^\*\*Përmbledhje e shkurtër\*\*\s*$/im

function NoteContent({ text, transcript }: { text: string; transcript?: ReactNode }) {
  const marker = transcript && transcriptHeading.exec(text)
  if (!marker) return <Summary text={text} />
  const afterHeading = text.slice(marker.index + marker[0].length)
  const summary = summaryHeading.exec(afterHeading)
  const original = afterHeading.slice(0, summary?.index).trim()
  return <>
    {marker.index > 0 && <Summary text={text.slice(0, marker.index).trim()} />}
    {transcript}
    {original && <details className="text-sm">
      <summary className="cursor-pointer font-medium text-violet-800 dark:text-violet-200">Teksti origjinal i transkriptit në shënim</summary>
      <div className="mt-2"><Summary text={original} /></div>
    </details>}
    {summary && <Summary text={afterHeading.slice(summary.index)} />}
  </>
}

function Note({ note, transcript }: { note: MeetingNote; transcript?: ReactNode }) {
  const { apiFetch } = useAuth()
  const [shared, setShared] = useState(note.shared_to_px)
  const [busy, setBusy] = useState(false)

  async function share() {
    setBusy(true)
    try {
      const result = await json<{ shared_to_px: boolean }>(await apiFetch(
        `/mira/notes/${note.kind}/${note.id}/show-in-px-notes`, { method: "POST" }))
      setShared(result.shared_to_px)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Shënimi nuk u shfaq në PX Notes.")
    } finally {
      setBusy(false)
    }
  }

  return <article id={`note-${note.note_id ?? note.id}`} className="scroll-mt-24 space-y-3 rounded-lg border border-violet-200 bg-violet-50/60 p-4 target:ring-2 target:ring-violet-500 dark:border-violet-900 dark:bg-violet-950/30">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h3 className="text-sm font-semibold">{note.title}</h3>
        <p className="text-xs text-muted-foreground">
          {statusLabels[note.status] ?? note.status}
          {note.created_at && ` · ${new Date(note.created_at).toLocaleDateString("sq-AL")} · ${clock(note.created_at)}`}
        </p>
      </div>
      {shared
        ? <Link href="/ga-ka-notes" className="text-sm underline">Shfaqet në PX Notes</Link>
        : note.shareable !== false && <Button size="sm" variant="outline" disabled={busy} onClick={() => void share()}>
          {busy ? "Duke shfaqur…" : "Shfaq në PX Notes"}
        </Button>}
    </div>
    <NoteContent text={note.content} transcript={transcript} />
  </article>
}

export function MeetingNotes({ notes, draft, transcript, inlineTranscript }: {
  notes: MeetingNote[]; draft?: string | null; transcript?: ReactNode; inlineTranscript?: boolean
}) {
  const showDraft = draft && !notes.some((note) => note.content === draft)
  const inlineNote = inlineTranscript ? notes.find((note) => transcriptHeading.test(note.content)) : undefined
  const inlineDraft = inlineTranscript && !inlineNote && showDraft && transcriptHeading.test(draft)
  return <div className="space-y-3">
    {notes.map((note) => <Note key={`${note.kind}:${note.id}`} note={note} transcript={note === inlineNote ? transcript : undefined} />)}
    {showDraft && <article className="space-y-3 rounded-lg border border-violet-200 bg-violet-50/60 p-4 dark:border-violet-900 dark:bg-violet-950/30">
      <h3 className="text-sm font-semibold">Shënimet e plota</h3>
      <NoteContent text={draft} transcript={inlineDraft ? transcript : undefined} />
    </article>}
    {!notes.length && !showDraft && <p className="text-sm text-muted-foreground">Nuk ka shënime për këtë takim.</p>}
    {!inlineNote && !inlineDraft && transcript}
  </div>
}

export function UnlinkedNotes() {
  const { apiFetch } = useAuth()
  const [search, setSearch] = useState("")
  const [query, setQuery] = useState("")
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<{ notes: MeetingNote[]; has_more: boolean } | null>(null)
  const [error, setError] = useState("")
  const [retry, setRetry] = useState(0)
  const limit = 30

  useEffect(() => {
    let active = true
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset), query })
    async function load() {
      try {
        const result = await json<NonNullable<typeof page>>(await apiFetch(`/mira/unlinked-notes?${params}`))
        if (active) { setPage(result); setError("") }
      } catch (error) {
        if (active) setError(error instanceof Error ? error.message : "Shënimet nuk u ngarkuan.")
      }
    }
    void load()
    return () => { active = false }
  }, [apiFetch, offset, query, retry])

  return <section className="mt-5 space-y-4">
    <Link href="/mira?tab=takimet" className="text-sm underline">Kthehu te takimet</Link>
    <h2 className="text-lg font-semibold">Shënime pa takim të lidhur</h2>
    <form className="flex max-w-md gap-2" onSubmit={(event) => {
      event.preventDefault()
      setOffset(0)
      setQuery(search.trim())
    }}>
      <Input aria-label="Kërko shënime" value={search} maxLength={200} onChange={event => setSearch(event.target.value)} />
      <Button type="submit" variant="outline">Kërko</Button>
    </form>
    {error ? <p role="alert">{error}{" "}
      <button type="button" className="underline" onClick={() => { setError(""); setRetry(value => value + 1) }}>Provo përsëri</button>
    </p> : page ? (page.notes.length ? <MeetingNotes notes={page.notes} /> :
      <p className="text-sm text-muted-foreground">Nuk u gjetën shënime.</p>) : <p role="status">Po ngarkohen shënimet…</p>}
    {!error && (offset > 0 || page?.has_more) && <div className="flex gap-2">
      <Button variant="outline" disabled={offset === 0} onClick={() => { setPage(null); setOffset(offset - limit) }}>Para</Button>
      <Button variant="outline" disabled={!page?.has_more} onClick={() => { setPage(null); setOffset(offset + limit) }}>Tjetër</Button>
    </div>}
  </section>
}
