"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { ChevronDown, MessageCircle, RefreshCw } from "lucide-react"
import { useAuth } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { CommentTaskEditDialog } from "@/components/comment-task-edit-dialog"
import { getPlainMarkedText, renderMarkedNoteContent } from "@/lib/note-markup"

export type MarkerComment = {
  id: string
  source_key?: string
  task_id: string
  task_ids: string[]
  revision: string
  title: string
  marker: string
  marker_by_ga?: boolean
  symbol: string
  comment: string
  author_name: string | null
  updated_at: string
  read_at: string | null
  is_mine?: boolean
  can_mark_read: boolean
  recipients: { user_id: string; name: string; initials: string; read_at: string | null }[]
  recipient_count: number
  read_count: number
  all_read: boolean
}

type CommentsContext = {
  items: MarkerComment[]
  unread: MarkerComment[]
  byTask: Map<string, MarkerComment>
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  open: (item: MarkerComment) => void
  openTask: (taskId?: string | null, text?: string) => void
  markTaskRead: (taskId: string, text: string) => void
  markRead: (item: MarkerComment) => Promise<void>
}

const Context = React.createContext<CommentsContext | null>(null)
export const useMarkerComments = () => React.useContext(Context)

export function commentDate(value: string) {
  return new Intl.DateTimeFormat("sq-AL", { dateStyle: "short", timeStyle: "short" }).format(new Date(value))
}

export function MarkerCommentsProvider({ children }: { children: React.ReactNode }) {
  const { apiFetch, user } = useAuth()
  const [items, setItems] = React.useState<MarkerComment[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [selected, setSelected] = React.useState<MarkerComment | null>(null)
  const [editingTaskId, setEditingTaskId] = React.useState<string | null>(null)
  const [readError, setReadError] = React.useState<string | null>(null)
  const requestVersion = React.useRef(0)
  const readVersions = React.useRef(new Map<string, string>())

  const refresh = React.useCallback(async () => {
    if (!user) return
    const version = ++requestVersion.current
    try {
      const response = await apiFetch("/marker-comments")
      if (!response?.ok) throw new Error("Komentet nuk u ngarkuan. Provo përsëri.")
      const data = await response.json() as { items: MarkerComment[] }
      if (version !== requestVersion.current) return
      setItems(data.items.map((item) => readVersions.current.get(item.id) === item.revision
        ? { ...item, read_at: item.read_at || new Date().toISOString() } : item))
      setError(null)
    } catch (failure) {
      if (version === requestVersion.current) setError(failure instanceof Error ? failure.message : "Komentet nuk u ngarkuan.")
    } finally {
      if (version === requestVersion.current) setLoading(false)
    }
  }, [apiFetch, user])

  React.useEffect(() => {
    void refresh()
    const update = () => { if (document.visibilityState === "visible") void refresh() }
    window.addEventListener("primex:notification", update)
    window.addEventListener("primeflow:task-marker-updated", update)
    window.addEventListener("focus", update)
    document.addEventListener("visibilitychange", update)
    const interval = window.setInterval(update, 30_000)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener("primex:notification", update)
      window.removeEventListener("primeflow:task-marker-updated", update)
      window.removeEventListener("focus", update)
      document.removeEventListener("visibilitychange", update)
    }
  }, [refresh])

  const markRead = React.useCallback(async (item: MarkerComment) => {
    if (!item.can_mark_read || item.read_at) return
    try {
      const response = await apiFetch(`/marker-comments/${item.id}/read`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ revision: item.revision }),
      })
      if (!response?.ok) {
        if (response?.status === 409) {
          void refresh()
          throw new Error("Komenti ka ndryshuar. Hape përsëri për të lexuar versionin e ri.")
        }
        throw new Error("Komenti nuk u shënua si i lexuar. Provo përsëri.")
      }
      const result = await response.json() as { source_key?: string; read_at?: string }
      const read_at = result.read_at || new Date().toISOString()
      readVersions.current.set(item.id, item.revision)
      setItems((current) => current.map((row) => row.id === item.id && row.revision === item.revision
        ? { ...row, read_at } : row))
      setReadError(null)
    } catch (failure) {
      const message = failure instanceof Error ? failure.message : "Komenti nuk u shënua si i lexuar."
      setReadError(message)
      throw failure
    }
  }, [apiFetch, refresh])

  const byTask = React.useMemo(() => {
    const map = new Map<string, MarkerComment>()
    for (const item of items) for (const id of item.task_ids) if (!map.has(id)) map.set(id, item)
    return map
  }, [items])
  const unread = React.useMemo(() => items.filter((item) => !item.read_at), [items])
  const open = React.useCallback((item: MarkerComment) => {
    setSelected(item)
    setReadError(null)
    void markRead(item).catch(() => undefined)
  }, [markRead])
  const openTask = React.useCallback((taskId?: string | null, text = "") => {
    const item = taskId ? byTask.get(taskId) : undefined
    if (item && (!text || item.comment.trim() === text.trim())) { open(item); return }
    if (text.trim()) {
      setReadError(null)
      setSelected({ id: "", task_id: taskId || "", task_ids: [], revision: "", title: "Koment te simboli", marker: "", symbol: "", comment: text, author_name: null, updated_at: "", read_at: "", can_mark_read: false, recipients: [], recipient_count: 0, read_count: 0, all_read: false })
    }
  }, [byTask, open])
  const markTaskRead = React.useCallback((taskId: string, text: string) => {
    const item = byTask.get(taskId)
    if (item && item.comment.trim() === text.trim()) void markRead(item).catch(() => undefined)
  }, [byTask, markRead])

  return (
    <Context.Provider value={{ items, unread, byTask, loading, error, refresh, open, openTask, markTaskRead, markRead }}>
      {children}
      <Dialog open={Boolean(selected || editingTaskId)} onOpenChange={(isOpen) => { if (!isOpen) { setSelected(null); setEditingTaskId(null) } }}>
        <DialogContent className={`flex max-h-[calc(100dvh-2rem)] flex-col overflow-hidden sm:max-w-3xl${editingTaskId ? " h-[calc(100dvh-2rem)]" : ""}`} onClick={(event) => event.stopPropagation()}>
          {editingTaskId ? <CommentTaskEditDialog key={editingTaskId} taskId={editingTaskId} onClose={() => { setEditingTaskId(null); setSelected(null) }} onSaved={() => {
            window.dispatchEvent(new Event("primeflow:task-marker-updated"))
          }} /> : <>
          <DialogHeader className="shrink-0 text-left">
            <DialogTitle className="pr-5">{selected?.symbol && <span className="mr-2 text-red-600">{selected.symbol}</span>}{selected?.comment ? "Koment te simboli" : "Simboli i detyrës"}</DialogTitle>
            <DialogDescription>{selected?.updated_at ? `${selected.author_name || "Autor i paregjistruar"} · ${commentDate(selected.updated_at)}` : "Komenti i plotë i simbolit"}</DialogDescription>
          </DialogHeader>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto overscroll-contain pr-1">
            <section aria-label="Komenti" className="space-y-1.5">
              <h2 className="text-xs font-semibold text-blue-700">Komenti</h2>
              <div className="whitespace-pre-wrap rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm leading-relaxed text-slate-950 [overflow-wrap:anywhere]">{selected?.comment || "Ky simbol nuk ka koment."}</div>
            </section>
            {selected?.id && selected.title && <section aria-label="Detyra" className="space-y-1.5">
              <h2 className="text-xs font-semibold text-slate-500">Detyra</h2>
              <div className="whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm font-normal leading-relaxed text-slate-950 [overflow-wrap:anywhere]">{renderMarkedNoteContent(selected.title)}</div>
            </section>}
          </div>
          {readError && <div role="alert" className="text-sm text-red-700">{readError}</div>}
          <div className="flex shrink-0 flex-wrap justify-end gap-2">
            {readError && selected?.id && <Button variant="outline" onClick={() => void markRead(selected).catch(() => undefined)}>Provo përsëri</Button>}
            {selected?.task_id && <Button variant="outline" onClick={() => { setEditingTaskId(selected.task_id); setSelected(null) }}>Hap detyrën</Button>}
            <Button onClick={() => setSelected(null)}>Mbyll</Button>
          </div>
          </>}
        </DialogContent>
      </Dialog>
    </Context.Provider>
  )
}

export function MarkerCommentsPanel() {
  const comments = useMarkerComments()
  const pathname = usePathname()
  const [expanded, setExpanded] = React.useState(false)
  const show = pathname === "/common" || pathname === "/dashboard" || pathname.startsWith("/departments/") || pathname.endsWith("print-report")
  if (!comments || !show || (!comments.unread.length && !comments.error)) return null
  return (
    <section className="mb-3 rounded-lg border-2 border-blue-600 bg-blue-50 text-slate-950 print:hidden" aria-label="Simbole dhe komente të palexuara">
      <div className="flex items-center gap-2 p-2.5">
        <button type="button" aria-expanded={expanded} aria-controls="unread-marker-comments" onClick={() => setExpanded((value) => !value)} className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm font-bold text-blue-950">
          <MessageCircle className="size-5 shrink-0 text-blue-700" />
          <span>Simbole dhe komente të palexuara</span>
          <span className="rounded-full bg-[#0055FF] px-2 py-0.5 text-xs text-white" aria-live="polite">{comments.unread.length}</span>
          <ChevronDown className={`size-4 shrink-0 transition-transform ${expanded ? "rotate-180" : ""}`} />
        </button>
        <Link href="/comments" className="shrink-0 text-xs font-semibold text-blue-700 underline">Shiko të gjitha</Link>
      </div>
      {comments.error && <div role="alert" className="flex items-center gap-2 px-3 pb-2 text-xs text-red-700">{comments.error}<button type="button" onClick={() => void comments.refresh()} aria-label="Ringarko komentet"><RefreshCw className="size-4" /></button></div>}
      {expanded && <div id="unread-marker-comments" className="space-y-1 border-t border-blue-200 p-2">
        {comments.unread.slice(0, 5).map((item) => <button key={item.id} type="button" onClick={() => comments.open(item)} className="block w-full rounded-md border border-blue-200 bg-white p-2 text-left hover:border-blue-600 focus-visible:outline-2 focus-visible:outline-blue-700">
          <div className="flex items-center gap-2 text-xs"><span className="font-black text-red-600">{item.symbol}</span><span className="truncate font-semibold">{getPlainMarkedText(item.title).split("\n")[0]}</span><span className="ml-auto shrink-0 rounded bg-blue-600 px-1 text-[10px] font-bold text-white">E RE</span></div>
          <p className="mt-1 line-clamp-1 text-sm text-blue-950">{item.comment || "Simbol i ri · Pa koment"}</p>
          <p className="mt-1 text-[11px] text-slate-500">{item.author_name || "Autor i paregjistruar"} · {commentDate(item.updated_at)}</p>
        </button>)}
      </div>}
    </section>
  )
}
