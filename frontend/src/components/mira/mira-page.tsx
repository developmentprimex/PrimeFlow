"use client"

import * as React from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"
import { MiraMemoryPage } from "@/components/mira-memory/mira-memory-page"
import { KnowledgeTab } from "@/components/mira/knowledge-tab"
import { MeetingsTab } from "@/components/mira/meetings-tab"
import { SettingsTab } from "@/components/mira/settings-tab"
import { clock, json, type HostStatus, type MiraNote, type MiraTab } from "@/lib/mira"

const ACCENT = "#2f5d8a"
const TABS: { id: MiraTab; label: string }[] = [
  { id: "takimet", label: "Takimet 1H" },
  { id: "shenimet", label: "Shënimet e Mira-s" },
  { id: "knowledge", label: "Knowledge" },
  { id: "kujtesa", label: "Kujtesa" },
  { id: "cilesimet", label: "Cilësimet" },
]

function NotesTab() {
  const { apiFetch } = useAuth()
  const [notes, setNotes] = React.useState<MiraNote[] | null>(null)
  const [open, setOpen] = React.useState<string | null>(null)
  React.useEffect(() => {
    void (async () => {
      try {
        setNotes(await json<MiraNote[]>(await apiFetch("/mira/notes?limit=100")))
      } catch (e) {
        toast.error(e instanceof Error ? e.message : String(e))
      }
    })()
  }, [apiFetch])
  if (notes && notes.length === 0) return <p className="py-16 text-center text-sm text-muted-foreground">Mira nuk ka ruajtur ende shënime në PX Notes.</p>
  return (
    <ul className="divide-y py-3">
      {notes?.map((note) => (
        <li key={note.id} className="py-3">
          <button type="button" onClick={() => setOpen(open === note.id ? null : note.id)}
            className="flex w-full items-baseline gap-3 text-left text-sm hover:underline">
            <span className="min-w-0 flex-1 truncate font-medium">{note.title}</span>
            <span className="shrink-0 text-xs text-muted-foreground">{note.status === "OPEN" ? "e hapur" : "e mbyllur"}</span>
          </button>
          {open === note.id && (
            <div className="mt-2">
              <pre className="max-h-[420px] overflow-y-auto whitespace-pre-wrap font-sans text-sm leading-relaxed text-foreground/80">{note.content}</pre>
              <a href={note.url} className="mt-2 inline-block text-xs underline underline-offset-4">Hap te PX Notes</a>
            </div>
          )}
        </li>
      ))}
    </ul>
  )
}

export function MiraPage() {
  const { apiFetch, user } = useAuth()
  const router = useRouter()
  const params = useSearchParams()
  const requested = params.get("tab") as MiraTab | null
  const tab: MiraTab = TABS.some((t) => t.id === requested) ? (requested as MiraTab) : "takimet"
  const canManage = user?.role === "ADMIN" || user?.role === "MANAGER"
  const [status, setStatus] = React.useState<HostStatus | null>(null)

  const loadStatus = React.useCallback(async () => {
    try {
      setStatus(await json<HostStatus>(await apiFetch("/mira/status")))
    } catch {
      // The status line is informative only; the tabs still work without it.
    }
  }, [apiFetch])
  React.useEffect(() => {
    void loadStatus()
    const timer = window.setInterval(() => void loadStatus(), 30000)
    return () => window.clearInterval(timer)
  }, [loadStatus])

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-8 md:px-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight">Mira</h1>
          <p className="mt-1 text-sm text-muted-foreground">Asistentja e takimeve interne: takimet 1H, shënimet, knowledge dhe kujtesa.</p>
        </div>
        {status && (
          <p className="text-sm text-muted-foreground">
            {status.live ? (
              <span style={{ color: ACCENT }}>● Mira po e mban 1H {status.live.slot}</span>
            ) : status.enabled ? `Mira i mban takimet deri në ${clock(status.enabled_until)}` : "Mira vetëm dëgjon (nuk i mban takimet)"}
          </p>
        )}
      </header>

      <div role="tablist" aria-label="Mira" className="flex gap-6 overflow-x-auto border-b text-sm">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} type="button"
            onClick={() => router.replace(t.id === "takimet" ? "/mira" : `/mira?tab=${t.id}`)}
            className={cn("-mb-px whitespace-nowrap border-b-2 pb-2.5 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
              tab === t.id ? "border-foreground font-semibold text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "takimet" && <MeetingsTab canManage={canManage} />}
      {tab === "shenimet" && <NotesTab />}
      {tab === "knowledge" && <KnowledgeTab canManage={canManage} />}
      {tab === "kujtesa" && <div className="-mx-4 md:-mx-8"><MiraMemoryPage /></div>}
      {/* The form starts from the loaded settings; it remounts once they arrive. */}
      {tab === "cilesimet" && <SettingsTab key={status ? "ready" : "loading"} canManage={canManage} status={status}
        onChange={(next) => setStatus({ ...next, live: status?.live ?? null })} />}
    </div>
  )
}
