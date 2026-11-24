"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"
import { MiraMemoryPage } from "@/components/mira-memory/mira-memory-page"
import { KnowledgeTab } from "@/components/mira/knowledge-tab"
import { MeetingNotes, UnlinkedNotes, type MeetingNote } from "@/components/mira/notes-tab"
import { miraMeetingUrl, NotetakerTab, type MeetingSource } from "@/components/mira/notetaker-tab"
import { SettingsTab } from "@/components/mira/settings-tab"
import { clock, json, type HostStatus, type MiraTab } from "@/lib/mira"

const ACCENT = "#2f5d8a"
const TABS: { id: MiraTab; label: string }[] = [
  { id: "takimet", label: "Takimet" },
  { id: "knowledge", label: "Knowledge" },
  { id: "kujtesa", label: "Kujtesa" },
  { id: "cilesimet", label: "Cilësimet" },
]

function NoteMeeting({ id }: { id: string }) {
  const { apiFetch } = useAuth()
  const router = useRouter()
  const [error, setError] = React.useState("")
  const [archivedNote, setArchivedNote] = React.useState<MeetingNote | null>(null)
  React.useEffect(() => {
    let ignore = false
    async function openMeeting() {
      try {
        const meeting = await json<{ id: string; source: MeetingSource } | { archived_note: MeetingNote }>(
          await apiFetch(`/mira/notes/${encodeURIComponent(id)}/meeting`))
        if (ignore) return
        if ("archived_note" in meeting) setArchivedNote(meeting.archived_note)
        else router.replace(miraMeetingUrl(meeting.id, meeting.source, "full", `note-${id}`))
      } catch (error) {
        if (!ignore) setError(error instanceof Error ? error.message : "Takimi burim nuk u hap.")
      }
    }
    void openMeeting()
    return () => { ignore = true }
  }, [apiFetch, id, router])
  if (archivedNote) return <section className="mt-5 space-y-4">
    <Link href="/mira?tab=takimet&archive=1" className="text-sm underline">Shënime pa takim të lidhur</Link>
    <MeetingNotes notes={[archivedNote]} />
  </section>
  return error
    ? <p role="alert" className="mt-4 text-sm">{error} <Link className="underline" href="/mira">Hap takimet</Link></p>
    : <p role="status" className="mt-4 text-sm">Po hapet takimi burim…</p>
}

export function MiraPage() {
  const { apiFetch, user } = useAuth()
  const router = useRouter()
  const params = useSearchParams()
  const requested = params.get("tab")
  const tab: MiraTab = TABS.some((t) => t.id === requested) ? (requested as MiraTab) : "takimet"
  const requestedSource = params.get("source")
  const source = requestedSource === "host" || requestedSource === "desktop" ? requestedSource : "discord"
  const noteId = params.get("note")
  const view = params.get("view") ?? (requested === "shenimet" ? "full" : null)
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
    <div className="mx-auto w-full px-4 py-8 md:px-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight">Mira</h1>
          <p className="mt-1 text-sm text-muted-foreground">Asistentja e takimeve interne: takimet 1H, shënimet, knowledge dhe kujtesa.</p>
        </div>
        {status && (
          <p className="text-sm text-muted-foreground">
            {status.stop_requested ? "Mira po ndalet…" : status.live ? (
              <Link className="hover:underline" style={{ color: ACCENT }} href={miraMeetingUrl(status.live.id, "host", "report")}>
                {status.live.is_test ? "● TEST · Mira po provon 1H " : "● Mira po e mban 1H "}{status.live.slot}
              </Link>
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

      {tab === "takimet" && (noteId ? <NoteMeeting key={noteId} id={noteId} /> :
        params.get("archive") === "1" ? <UnlinkedNotes /> :
          <NotetakerTab meetingId={params.get("meeting")} source={source} view={view} filter={params.get("filter")} />)}
      {tab === "knowledge" && <KnowledgeTab canManage={canManage} />}
      {tab === "kujtesa" && <div className="-mx-4 md:-mx-8"><MiraMemoryPage itemId={params.get("item")} /></div>}
      {/* The form starts from the loaded settings; it remounts once they arrive. */}
      {tab === "cilesimet" && <SettingsTab key={status ? "ready" : "loading"} canManage={canManage} status={status}
        onChange={(next) => setStatus({ ...next, live: status?.live ?? null })} />}
    </div>
  )
}
