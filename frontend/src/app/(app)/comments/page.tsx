"use client"

import * as React from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { CheckCheck, MessageCircle, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { commentDate, useMarkerComments, type MarkerComment } from "@/components/marker-comments-context"
import { Button } from "@/components/ui/button"
import { getPlainMarkedText } from "@/lib/note-markup"
import { useAuth } from "@/lib/auth"

function CommentsInbox() {
  const comments = useMarkerComments()
  const { apiFetch } = useAuth()
  const router = useRouter()
  const params = useSearchParams()
  const scope = params.get("scope") === "all" ? "all" : "mine"
  const requestedRead = params.get("read")
  const readFilter = requestedRead === "all" || requestedRead === "read" || requestedRead === "unread" ? requestedRead : "all"
  const requestedId = params.get("comment")
  const handledId = React.useRef<string | null>(null)
  const [allItems, setAllItems] = React.useState<MarkerComment[]>([])
  const [allLoading, setAllLoading] = React.useState(true)
  const [allCount, setAllCount] = React.useState<number | null>(null)
  const [allError, setAllError] = React.useState<string | null>(null)
  const allRequest = React.useRef(0)
  const [search, setSearch] = React.useState("")
  const [reading, setReading] = React.useState<string | null>(null)
  const loadAll = React.useCallback(async () => {
    const request = ++allRequest.current
    setAllLoading(true)
    try {
      const response = await apiFetch("/marker-comments?scope=all")
      if (!response?.ok) throw new Error("Komentet e ekipit nuk u ngarkuan. Provo përsëri.")
      const data = await response.json() as { items: MarkerComment[] }
      if (request !== allRequest.current) return
      setAllItems(data.items)
      setAllCount(data.items.length)
      setAllError(null)
    } catch (failure) {
      if (request === allRequest.current) setAllError(failure instanceof Error ? failure.message : "Komentet nuk u ngarkuan.")
    } finally {
      if (request === allRequest.current) setAllLoading(false)
    }
  }, [apiFetch])
  React.useEffect(() => { void loadAll() }, [comments?.items, loadAll])
  const changeFilters = (nextScope: "mine" | "all", nextRead: string) => {
    const next = new URLSearchParams(params.toString())
    next.set("scope", nextScope)
    next.set("read", nextRead)
    next.delete("comment")
    router.replace(`/comments?${next.toString()}`, { scroll: false })
  }
  React.useEffect(() => {
    if (!comments || comments.loading || comments.error || (scope === "all" && allLoading && !allItems.length) || !requestedId || handledId.current === requestedId) return
    const item = comments.items.find((row) => row.id === requestedId) || allItems.find((row) => row.id === requestedId)
    handledId.current = requestedId
    if (item) comments.open(item)
    else toast.error("Ky koment nuk është më i disponueshëm.")
  }, [comments, requestedId, allItems, allLoading, scope])
  if (!comments) return null
  const ownById = new Map(comments.items.map((item) => [item.id, item]))
  const source = scope === "all" ? allItems.map((item) => {
    const own = ownById.get(item.id)
    // Personal acknowledgement must never mark the whole group as complete.
    return own?.revision === item.revision ? { ...item, read_at: own.read_at } : item
  }) : comments.items
  const isUnread = (item: MarkerComment) => scope === "all" ? item.recipient_count > 0 && !item.all_read : !item.read_at
  const isRead = (item: MarkerComment) => scope === "all" ? item.all_read : Boolean(item.read_at)
  const filtered = readFilter === "all" ? source : source.filter((item) => readFilter === "unread" ? isUnread(item) : isRead(item))
  const loading = scope === "all" ? allLoading && !allItems.length : comments.loading
  const error = scope === "all" ? allError : comments.error
  const query = search.trim().toLocaleLowerCase()
  const items = filtered.filter((item) => !query || `${getPlainMarkedText(item.title)} ${item.comment} ${item.author_name || ""} ${item.symbol} ${item.recipients.map((person) => `${person.name} ${person.initials}`).join(" ")}`.toLocaleLowerCase().includes(query))
  return (
    <div className="w-full space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div><h1 className="flex items-center gap-2 text-xl font-bold"><MessageCircle className="text-blue-600" />Simbolet dhe komentet</h1><p className="mt-1 text-sm text-muted-foreground">{scope === "all" ? "Simbolet dhe komentet e të gjithë përdoruesve, pavarësisht departamentit." : "Simbolet dhe komentet që të përkasin, pavarësisht datës së detyrës."} Vetëm detyrat To do dhe In progress. Leximin e konfirmojnë vetëm personat përgjegjës të detyrës.</p></div>
        <Button variant="outline" disabled={comments.loading || allLoading} onClick={() => { void comments.refresh(); void loadAll() }}><RefreshCw className="size-4" />Ringarko</Button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex gap-1 rounded-md border border-slate-300 bg-slate-50 p-1" role="group" aria-label="Komentet sipas personave">
          <Button size="sm" variant={scope === "mine" ? "default" : "ghost"} aria-pressed={scope === "mine"} onClick={() => changeFilters("mine", "all")}>Të miat ({comments.items.length})</Button>
          <Button size="sm" variant={scope === "all" ? "default" : "ghost"} aria-pressed={scope === "all"} onClick={() => changeFilters("all", "all")}>Të gjitha ({allCount ?? "…"})</Button>
        </div>
        <select aria-label="Gjendja e leximit" value={readFilter} onChange={(event) => changeFilters(scope, event.target.value)} className="h-9 rounded-md border bg-white px-3 text-sm">
          <option value="all">Çdo gjendje leximi</option>
          <option value="unread">Të palexuara ({source.filter(isUnread).length})</option>
          <option value="read">Të lexuara</option>
        </select>
        <input aria-label="Kërko komentet" placeholder="Kërko detyrën, simbolin, komentin ose personin…" value={search} onChange={(event) => setSearch(event.target.value)} className="h-9 min-w-60 flex-1 rounded-md border bg-background px-3 text-sm" />
      </div>
      {error && <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      <div className="relative max-h-[75vh] w-full overflow-auto rounded-md border-2 border-slate-700 bg-white">
        <table className="w-full min-w-[1200px] table-fixed border-collapse text-sm">
          <caption className="sr-only">Komentet e simboleve sipas detyrës, autorit dhe gjendjes së leximit</caption>
          <colgroup>
            <col className="w-12" /><col className="w-20" /><col className="w-[25%]" /><col />
            <col className="w-20" /><col className="w-28" /><col className="w-36" /><col className="w-40" /><col className="w-44" />
          </colgroup>
          <thead className="sticky top-0 z-10 bg-white">
            <tr>{["NR", "SIMBOLI", "DETYRA", "KOMENTI", "NGA", "PËR", "DATA, ORA", "LEXIMI", "VEPRIMET"].map((label) =>
              <th key={label} scope="col" className="h-10 border border-slate-600 bg-white px-2 text-left align-bottom text-xs font-medium text-slate-950">{label}</th>
            )}</tr>
          </thead>
          <tbody>
            {loading || !items.length ? <tr><td colSpan={9} className="border border-slate-600 p-6 text-center text-sm text-slate-600">
              {loading ? "Duke ngarkuar komentet…" : error ? "Komentet nuk u ngarkuan. Përdor Ringarko." : query ? "Nuk u gjet asnjë koment." : readFilter === "unread" ? "Nuk ke komente të palexuara." : "Nuk ka komente për filtrat e zgjedhur."}
            </td></tr> : items.map((item, index) => <tr key={item.id} className={isUnread(item) ? "group bg-blue-100 text-blue-950 hover:bg-blue-200" : "group bg-white hover:bg-slate-50"}>
              <td className="border border-slate-600 px-2 py-2 align-top text-xs">{index + 1}</td>
              <td className="border border-slate-600 px-2 py-2 align-top">
                <button type="button" onClick={() => comments.open(item)} aria-label={`${item.can_mark_read ? "Lexo" : "Shiko"} ${item.comment ? "komentin te simboli" : "simbolin"} ${item.symbol}`} className="inline-flex min-h-7 min-w-7 items-center justify-center rounded-md border border-blue-300 bg-blue-50 px-1.5 text-base font-black leading-none text-red-600 focus-visible:outline-2 focus-visible:outline-blue-700">{item.symbol}</button>
              </td>
              <td className="border border-slate-600 px-2 py-2 align-top">
                <button type="button" onClick={() => comments.open(item)} className="block w-full text-left text-[13px] font-medium leading-snug focus-visible:outline-2 focus-visible:outline-blue-700">
                  <span className="line-clamp-2 break-words">{getPlainMarkedText(item.title).split("\n")[0]}</span>
                </button>
              </td>
              <td className="border border-slate-600 px-2 py-2 align-top">
                <button type="button" onClick={() => comments.open(item)} title={item.comment} className="block w-full text-left text-[13px] leading-snug text-blue-950 focus-visible:outline-2 focus-visible:outline-blue-700">
                  <span className={`line-clamp-2 whitespace-pre-wrap break-words${item.comment ? "" : " italic text-slate-500"}`}>{item.comment || "Pa koment"}</span>
                </button>
              </td>
              <td className="border border-slate-600 px-2 py-2 align-top text-xs">
                {item.author_name?.trim() ? <span title={item.author_name} aria-label={item.author_name} className="inline-flex min-h-6 min-w-7 items-center justify-center rounded-full border border-slate-300 bg-slate-100 px-1.5 text-[11px] font-bold text-slate-800">{item.author_name.trim().split(/\s+/).map((part) => part[0]).join("").slice(0, 3).toLocaleUpperCase()}</span> : <span title="Autor i paregjistruar" className="text-slate-500">—</span>}
              </td>
              <td className="border border-slate-600 px-2 py-2 align-top text-xs"><div className="flex flex-wrap gap-1">
                {item.recipients.length ? item.recipients.map((person) => <span key={person.user_id} title={person.name} aria-label={person.name} className="inline-flex min-h-6 min-w-7 items-center justify-center rounded-full border border-slate-300 bg-slate-100 px-1.5 text-[11px] font-bold text-slate-800">{person.initials}</span>) : <span className="text-slate-500">—</span>}
              </div></td>
              <td className="border border-slate-600 px-2 py-2 align-top text-xs"><time dateTime={item.updated_at}>{commentDate(item.updated_at)}</time></td>
              <td className="border border-slate-600 px-2 py-2 align-top">{scope === "all"
                ? <span className={`inline-block rounded border px-2 py-0.5 text-[11px] ${item.all_read ? "border-emerald-200 bg-emerald-50 text-emerald-700" : item.recipient_count ? "border-blue-600 bg-[#0055FF] font-bold text-white" : "border-slate-200 bg-slate-50 text-slate-600"}`} title={item.recipients.map((person) => `${person.name}: ${person.read_at ? `Lexuar ${commentDate(person.read_at)}` : "Pa lexuar"}`).join("\n")}>
                  {!item.recipient_count ? "Pa përgjegjës" : item.recipient_count === 1 ? item.all_read ? `Lexuar nga ${item.recipients[0].initials}` : "Pa lexuar" : `Lexuar ${item.read_count}/${item.recipient_count}`}
                </span>
                : !item.read_at
                  ? <span className="inline-block rounded bg-[#0055FF] px-2 py-0.5 text-[11px] font-bold text-white">E RE</span>
                  : <span className="inline-block rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700" title={`Lexuar: ${commentDate(item.read_at)}`}>Lexuar</span>}
              </td>
              <td className="border border-slate-600 px-2 py-2 align-top">
                <div className="flex flex-col items-start gap-1">
                  <Button size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={() => comments.open(item)}>{item.can_mark_read ? item.comment ? "Lexo komentin" : "Lexo simbolin" : "Shiko"}</Button>
                  {item.can_mark_read && !item.read_at && <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" disabled={reading === item.id} onClick={async () => {
                    setReading(item.id)
                    try { await comments.markRead(item) } catch { toast.error("Komenti nuk u shënua si i lexuar. Ringarko dhe provo përsëri.") } finally { setReading(null) }
                  }}><CheckCheck className="size-3.5" />Shëno si të lexuar</Button>}
                </div>
              </td>
            </tr>)}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default function CommentsPage() {
  return <React.Suspense fallback={<p>Duke ngarkuar komentet…</p>}><CommentsInbox /></React.Suspense>
}
