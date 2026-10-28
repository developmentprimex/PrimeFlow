"use client"

import * as React from "react"
import Image from "next/image"
import Link from "next/link"
import { Check, ChevronDown, RefreshCw, Search } from "lucide-react"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import { clock, json, type MiraNote } from "@/lib/mira"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Summary } from "@/components/mira/meetings-tab"

const PAGE_SIZE = 100
const SOURCE_LABELS = { "1H": "Takimi 1H", DISCORD: "Discord", DESKTOP: "Mira Desktop" }
const STATUS_LABELS: Record<string, string> = { OPEN: "E hapur", CLOSED: "E mbyllur", DONE: "Përfundoi", ABORTED: "U ndërpre" }
const noteKey = (note: MiraNote) => `${note.kind}:${note.id}`

function dateLabel(value: string | null) {
  if (!value) return "–"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "–" : `${String(date.getDate()).padStart(2, "0")}.${String(date.getMonth() + 1).padStart(2, "0")}.${date.getFullYear()}`
}

export function NotesTab() {
  const { apiFetch } = useAuth()
  const [notes, setNotes] = React.useState<MiraNote[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [reload, setReload] = React.useState(0)
  const [query, setQuery] = React.useState("")
  const [expanded, setExpanded] = React.useState<Set<string>>(() => new Set())
  const [sharing, setSharing] = React.useState<Set<string>>(() => new Set())

  React.useEffect(() => {
    let active = true
    void (async () => {
      setLoading(true)
      setError(null)
      try {
        // Read every page, including older closed notes, rather than silently stopping at 100.
        const all: MiraNote[] = []
        for (let offset = 0; active; offset += PAGE_SIZE) {
          const page = await json<MiraNote[]>(await apiFetch(`/mira/notes?limit=${PAGE_SIZE}&offset=${offset}`))
          all.push(...page)
          if (page.length < PAGE_SIZE) break
        }
        if (active) setNotes(all)
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : String(e))
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => { active = false }
  }, [apiFetch, reload])

  const visibleNotes = notes.filter(note =>
    `${note.title} ${note.content} ${SOURCE_LABELS[note.source]} ${STATUS_LABELS[note.status] ?? note.status}`
      .toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()))

  const toggle = (key: string) => setExpanded(current => {
    const next = new Set(current)
    if (!next.delete(key)) next.add(key)
    return next
  })

  const share = async (note: MiraNote) => {
    const key = noteKey(note)
    setSharing(current => new Set(current).add(key))
    try {
      const result = await json<{ note_id: string; shared_to_px: boolean }>(await apiFetch(
        `/mira/notes/${note.kind}/${note.id}/show-in-px-notes`, { method: "POST" }))
      setNotes(current => current.map(item => noteKey(item) === key
        ? { ...item, note_id: result.note_id, shared_to_px: result.shared_to_px } : item))
      toast.success("Shënimi tani shfaqet te All Tasks/Notes në PX Notes.")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setSharing(current => { const next = new Set(current); next.delete(key); return next })
    }
  }

  return (
    <section className="mt-6 rounded-xl border bg-background p-4 shadow-sm md:p-6" aria-label="Shënimet e Mira-s">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">Shënimet e Mira-s <span className="ml-1 text-sm font-normal text-muted-foreground">({notes.length})</span></h2>
          <p className="mt-1 text-sm text-muted-foreground">Të gjitha shënimet e takimeve dhe Mira Desktop. Zgjidh cilat të shfaqen edhe në PX Notes.</p>
        </div>
        <Button type="button" variant="outline" size="sm" disabled={loading || sharing.size > 0} onClick={() => setReload(value => value + 1)}>
          <RefreshCw className={cn("size-4", loading && "animate-spin")} /> Rifresko
        </Button>
      </div>
      <div className="relative mb-3 max-w-sm">
        <Search className="pointer-events-none absolute top-2.5 left-3 size-4 text-muted-foreground" />
        <Input className="pl-9" aria-label="Kërko shënime" placeholder="Kërko shënime..." value={query} onChange={event => setQuery(event.target.value)} />
      </div>
      {error && <div role="alert" className="mb-3 flex flex-wrap items-center gap-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
        {error}<Button type="button" variant="outline" size="sm" onClick={() => setReload(value => value + 1)}>Provo përsëri</Button>
      </div>}
      <div className="overflow-hidden rounded-md border-2 border-slate-600">
        <Table className="min-w-[850px] [&_th]:border-r [&_th]:border-slate-600 [&_th]:last:border-r-0 [&_td]:border-r [&_td]:border-slate-600 [&_td]:last:border-r-0 [&_tr]:border-slate-600">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="w-12">NR</TableHead>
              <TableHead>SHËNIMI</TableHead>
              <TableHead className="w-32">BURIMI</TableHead>
              <TableHead className="w-32">DATA, ORA</TableHead>
              <TableHead className="w-28">STATUSI</TableHead>
              <TableHead className="w-48">PX NOTES</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? <TableRow><TableCell colSpan={6} className="h-28 text-center text-muted-foreground">Duke ngarkuar shënimet...</TableCell></TableRow>
              : visibleNotes.length === 0 ? <TableRow><TableCell colSpan={6} className="h-28 text-center text-muted-foreground">
                {error ? "Shënimet nuk u ngarkuan." : query ? "Nuk u gjet asnjë shënim." : "Mira nuk ka ende shënime."}
              </TableCell></TableRow> : visibleNotes.map((note, index) => {
                const key = noteKey(note), open = expanded.has(key), busy = sharing.has(key)
                return <TableRow key={key} className="hover:bg-transparent">
                  <TableCell className="align-top text-muted-foreground">{index + 1}</TableCell>
                  <TableCell className="max-w-[750px] bg-violet-100/80 align-top whitespace-normal">
                    <button type="button" aria-expanded={open} onClick={() => toggle(key)} className="flex w-full items-start gap-2 rounded-sm text-left outline-none focus-visible:ring-2 focus-visible:ring-ring">
                      <Image src="/mira-avatar.png" alt="" width={34} height={34} className="shrink-0 rounded-full border border-violet-300" />
                      <span className="min-w-0 flex-1 break-words pt-1 font-medium">{note.title}</span>
                      <ChevronDown className={cn("mt-2 size-4 shrink-0 text-violet-700 transition-transform", open && "rotate-180")} />
                    </button>
                    {open && <div className="mt-3 max-h-[520px] overflow-y-auto break-words border-t border-violet-200 pt-3"><Summary text={note.content} /></div>}
                  </TableCell>
                  <TableCell className="align-top whitespace-normal text-xs">{SOURCE_LABELS[note.source]}</TableCell>
                  <TableCell className="align-top text-xs tabular-nums"><div>{dateLabel(note.created_at)}</div><div className="mt-1">{clock(note.created_at)}</div></TableCell>
                  <TableCell className="align-top"><span className={cn("inline-flex rounded-full border px-2 py-1 text-xs", note.status === "CLOSED" ? "border-slate-200 bg-slate-100 text-slate-600" : "border-emerald-200 bg-emerald-50 text-emerald-700")}>{STATUS_LABELS[note.status] ?? note.status}</span></TableCell>
                  <TableCell className="align-top">
                    {note.shared_to_px ? <div className="space-y-2">
                      <span className="flex items-center gap-1 text-xs text-emerald-700"><Check className="size-4" />Shfaqet në PX Notes</span>
                      <Link href="/ga-ka-notes" className="text-xs text-blue-700 underline underline-offset-4">Hap PX Notes</Link>
                    </div> : <Button type="button" variant="outline" size="sm" disabled={busy || loading} className="border-blue-200 text-xs text-blue-700" onClick={() => void share(note)}>
                      {busy ? "Duke shfaqur..." : "Shfaq në PX Notes"}
                    </Button>}
                  </TableCell>
                </TableRow>
              })}
          </TableBody>
        </Table>
      </div>
    </section>
  )
}
