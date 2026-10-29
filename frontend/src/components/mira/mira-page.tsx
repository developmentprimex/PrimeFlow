"use client"

import * as React from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"
import { MiraMemoryPage } from "@/components/mira-memory/mira-memory-page"
import { KnowledgeTab } from "@/components/mira/knowledge-tab"
import { MeetingsTab } from "@/components/mira/meetings-tab"
import { NotesTab } from "@/components/mira/notes-tab"
import { SettingsTab } from "@/components/mira/settings-tab"
import { clock, json, type HostStatus, type MiraTab } from "@/lib/mira"

const ACCENT = "#2f5d8a"
const TABS: { id: MiraTab; label: string }[] = [
  { id: "takimet", label: "Takimet 1H" },
  { id: "shenimet", label: "Shënimet e Mira-s" },
  { id: "knowledge", label: "Knowledge" },
  { id: "kujtesa", label: "Kujtesa" },
  { id: "cilesimet", label: "Cilësimet" },
]

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
    <div className={cn("mx-auto w-full px-4 py-8 md:px-8", tab !== "takimet" && tab !== "shenimet" && "max-w-6xl")}>
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
