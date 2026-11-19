"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Summary } from "@/components/mira/meetings-tab"
import { useAuth } from "@/lib/auth"
import { json } from "@/lib/mira"

const sections = {
  discussion: "U diskutua",
  decisions: "U vendos",
  actions: "U kërkua të bëhet",
  open_points: "Mbeti e hapur",
  follow_up: "Për takimin tjetër",
} as const

type Meeting = { id: string; title: string; started_at: string; partial: boolean }
type MeetingDetail = Meeting & {
  quick_summary: Record<keyof typeof sections, string[]> | null
  full_notes: string | null
  error: string | null
  transcript: { id: string; speaker: string; start_ms: number; end_ms: number; text: string }[]
}

const base = "/mira?tab=notetaker"
const endpoint = "/mira/notetaker/meetings"
const pageSize = 30
const views = { quick: "Përmbledhja e shpejtë", full: "Shënimet e plota", transcript: "Transkripti" } as const
const dateTime = new Intl.DateTimeFormat("sq-AL", { dateStyle: "medium", timeStyle: "short" })

function timestamp(ms: number) {
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.floor(ms / 1_000) % 60
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
}

export function NotetakerTab({ meetingId, view }: { meetingId: string | null; view: string | null }) {
  const { apiFetch } = useAuth()
  const [offset, setOffset] = useState(0)
  const [items, setItems] = useState<Meeting[] | null>(null)
  const [detail, setDetail] = useState<MeetingDetail | null>(null)
  const [error, setError] = useState<{ key: string; message: string } | null>(null)
  const selected = view === "full" || view === "transcript" ? view : "quick"
  const requestKey = meetingId ?? `page-${offset}`

  useEffect(() => {
    let ignore = false
    async function load() {
      try {
        if (meetingId) {
          const record = await json<MeetingDetail>(await apiFetch(`${endpoint}/${encodeURIComponent(meetingId)}`))
          if (!ignore) {
            setDetail(record)
            setError(null)
          }
        } else {
          const result = await json<{ items: Meeting[] }>(await apiFetch(`${endpoint}?limit=${pageSize + 1}&offset=${offset}`))
          if (!ignore) {
            setItems(result.items)
            setError(null)
          }
        }
      } catch {
        if (!ignore) setError({ key: requestKey, message: meetingId ? "Takimi nuk mund të hapet." : "Takimet nuk u ngarkuan." })
      }
    }
    void load()
    return () => { ignore = true }
  }, [apiFetch, meetingId, offset, requestKey])

  if (error?.key === requestKey) return <p role="alert" className="mt-4 text-sm">{error.message} {meetingId && <Link className="underline" href={base}>Kthehu te takimet</Link>}</p>

  if (!meetingId) return (
    <section className="mt-5 space-y-3">
      {items === null ? <p role="status">Po ngarkohen takimet…</p> : items.length === 0 ? <p>Nuk ka takime për të shfaqur.</p> : (
        <ul className="divide-y rounded-md border text-sm">
          {items.slice(0, pageSize).map((item) => (
            <li key={item.id}>
              <Link href={`${base}&meeting=${item.id}`} className="flex flex-wrap justify-between gap-2 px-4 py-3 hover:bg-muted/40">
                <span className="font-medium">{item.title}</span>
                <span className="text-muted-foreground">{dateTime.format(new Date(item.started_at))}{item.partial ? " · Regjistrim i pjesshëm" : ""}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {(offset > 0 || (items?.length ?? 0) > pageSize) && <div className="flex gap-2">
        <Button variant="outline" disabled={offset === 0} onClick={() => { setItems(null); setOffset(offset - pageSize) }}>Para</Button>
        <Button variant="outline" disabled={(items?.length ?? 0) <= pageSize} onClick={() => { setItems(null); setOffset(offset + pageSize) }}>Tjetër</Button>
      </div>}
    </section>
  )

  if (!detail || detail.id !== meetingId) return <p className="mt-4 text-sm" role="status">Po ngarkohet takimi…</p>
  const quick = detail.quick_summary
  return (
    <section className="mt-5 space-y-4">
      <Link href={base} className="text-sm underline">Kthehu te takimet</Link>
      <header>
        <h2 className="text-lg font-semibold">{detail.title}</h2>
        <p className="text-sm text-muted-foreground">{dateTime.format(new Date(detail.started_at))}</p>
      </header>
      {detail.partial && <p className="rounded-md border border-amber-500/50 px-3 py-2 text-sm">Regjistrimi ose transkripti është i pjesshëm.</p>}
      <nav aria-label="Pamjet e takimit" className="flex flex-wrap gap-4 border-b pb-2 text-sm">
        {Object.entries(views).map(([key, label]) => (
          <Link key={key} href={`${base}&meeting=${detail.id}&view=${key}`} aria-current={selected === key ? "page" : undefined} className={selected === key ? "font-semibold underline" : "text-muted-foreground"}>{label}</Link>
        ))}
      </nav>
      {selected === "quick" && (quick ? Object.entries(sections).map(([key, label]) => {
        const points = quick[key as keyof typeof sections]
        return <div key={key} className="text-sm"><h3 className="font-semibold">{label}</h3>{points.length ? (
          <ul className="ml-5 mt-1 list-disc space-y-1">{points.map((point, index) => <li key={index}>{point}</li>)}</ul>
        ) : <p className="text-muted-foreground">—</p>}</div>
      }) : <p className="text-sm">Përmbledhja e shpejtë nuk është e disponueshme.</p>)}
      {selected === "full" && (detail.full_notes ? <Summary text={detail.full_notes} /> : <p className="text-sm">{detail.error || "Shënimet nuk janë të disponueshme."}</p>)}
      {selected === "transcript" && (detail.transcript.length ? <ul className="divide-y rounded-md border text-sm">
        {detail.transcript.map((segment) => <li id={`segment-${segment.id}`} key={segment.id} className="px-4 py-2">
          <p className="font-medium">{segment.speaker} <span className="font-normal text-muted-foreground">{timestamp(segment.start_ms)}–{timestamp(segment.end_ms)}</span></p>
          <p className="whitespace-pre-wrap">{segment.text}</p>
        </li>)}
      </ul> : <p className="text-sm">Nuk ka segmente të transkriptuara.</p>)}
    </section>
  )
}
