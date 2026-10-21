"use client"

import * as React from "react"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { eventLabel, mentionText, type MemoryDetail, type MemoryList, type MemoryTab } from "@/lib/mira-memory"

// One accent marks what is still open; everything else stays neutral.
const ACCENT = "#2f5d8a"

const TABS: { id: MemoryTab; label: string }[] = [
  { id: "open", label: "Të hapura" },
  { id: "closed", label: "Të mbyllura" },
  { id: "all", label: "Të gjitha" },
]

async function json<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const error = new Error(typeof body?.detail === "string" ? body.detail : "Kërkesa dështoi. Provo përsëri.")
    ;(error as Error & { status?: number }).status = response.status
    throw error
  }
  return body as T
}

export function MiraMemoryPage() {
  const { apiFetch, user } = useAuth()
  const [tab, setTab] = React.useState<MemoryTab>("open")
  const [list, setList] = React.useState<MemoryList | null>(null)
  const [selected, setSelected] = React.useState<string | null>(null)
  const [detail, setDetail] = React.useState<MemoryDetail | null>(null)
  const [editing, setEditing] = React.useState(false)
  const [draft, setDraft] = React.useState({ title: "", description: "" })
  const [busy, setBusy] = React.useState(false)
  const canRetry = user?.role === "ADMIN" || user?.role === "MANAGER"

  const loadList = React.useCallback(async () => {
    try {
      setList(await json<MemoryList>(await apiFetch(`/mira-memory/items?status=${tab}`)))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }, [apiFetch, tab])

  const loadDetail = React.useCallback(async (id: string) => {
    try {
      setDetail(await json<MemoryDetail>(await apiFetch(`/mira-memory/items/${id}`)))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }, [apiFetch])

  React.useEffect(() => { void loadList() }, [loadList])
  React.useEffect(() => {
    setEditing(false)
    if (selected) void loadDetail(selected)
    else setDetail(null)
  }, [selected, loadDetail])

  const change = async (path: string, init: RequestInit, done: string) => {
    if (!detail || busy) return
    setBusy(true)
    try {
      const next = await json<MemoryDetail>(await apiFetch(path, {
        ...init, headers: { "Content-Type": "application/json" },
      }))
      setDetail(next)
      setEditing(false)
      toast.success(done)
      await loadList()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
      if ((e as { status?: number }).status === 409) await loadDetail(detail.id)
    } finally {
      setBusy(false)
    }
  }

  const save = () => change(`/mira-memory/items/${detail?.id}`, {
    method: "PATCH", body: JSON.stringify({ version: detail?.version, ...draft }),
  }, "Korrigjimi u ruajt.")

  const setStatus = (action: "close" | "reopen" | "wrong", done: string) => change(`/mira-memory/items/${detail?.id}/status`, {
    method: "POST", body: JSON.stringify({ version: detail?.version, action }),
  }, done)

  const retry = async () => {
    try {
      const result = await json<{ retried: number }>(await apiFetch("/mira-memory/retry-failed", { method: "POST" }))
      toast.success(`${result.retried} takime do të provohen sërish.`)
      await loadList()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }

  const counts = list?.counts
  const empty = list && list.items.length === 0

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-8 md:px-8">
      <header className="mb-6">
        <h1 className="text-[22px] font-semibold tracking-tight">Kujtesa e Mira-s</h1>
        <p className="mt-1 text-sm text-muted-foreground">Çka mban mend Mira nga takimet. Përditësohet pas çdo takimi.</p>
      </header>

      <div role="tablist" aria-label="Pikat e kujtesës" className="flex gap-6 border-b text-sm">
        {TABS.map((t) => {
          const count = t.id === "open" ? counts?.open : t.id === "closed" ? counts?.closed : undefined
          const active = tab === t.id
          return (
            <button key={t.id} role="tab" aria-selected={active} type="button"
              onClick={() => { setTab(t.id); setSelected(null) }}
              className={cn("-mb-px border-b-2 pb-2.5 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                active ? "border-foreground font-semibold text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
              {t.label}{count !== undefined && <span className="ml-1.5 font-normal text-muted-foreground">{count}</span>}
            </button>
          )
        })}
      </div>

      {empty ? (
        <p className="py-16 text-center text-sm text-muted-foreground">
          {tab === "open" && counts && counts.open + counts.closed === 0
            ? "Mira nuk ka mbajtur mend asgjë ende. Pikat shfaqen pas takimit të parë me shënime."
            : "Nuk ka pika këtu."}
        </p>
      ) : (
        <div className="grid md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <ul className={cn("py-3 md:border-r md:pr-4", selected && "hidden md:block")}>
            {list?.items.map((item) => (
              <li key={item.id}>
                <button type="button" onClick={() => setSelected(item.id)}
                  aria-current={selected === item.id}
                  className={cn("flex w-full items-baseline justify-between gap-3 rounded-md px-3 py-3 text-left text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                    selected === item.id ? "bg-muted" : "hover:bg-muted/60")}>
                  <span className={cn("min-w-0 flex-1 truncate", item.status !== "OPEN" && "text-muted-foreground",
                    item.status === "WRONG" && "line-through")}>
                    {item.status === "OPEN" && !item.quiet && (
                      <span aria-hidden className="mr-2 inline-block size-1.5 rounded-full align-middle" style={{ background: ACCENT }} />
                    )}
                    {item.title}
                  </span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {item.quiet && <span className="mr-2">e heshtur</span>}{mentionText(item.mention_count)}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          <section className={cn("min-w-0 py-5 md:pl-8", !selected && "hidden md:block")} aria-live="polite">
            {!detail ? (
              <p className="pt-10 text-sm text-muted-foreground">Zgjidh një pikë për të parë çka është thënë për të.</p>
            ) : (
              <article>
                <button type="button" onClick={() => setSelected(null)}
                  className="mb-4 text-sm text-muted-foreground underline-offset-4 hover:underline md:hidden">
                  Kthehu te lista
                </button>
                {editing ? (
                  <fieldset disabled={busy} className="space-y-3">
                    <Input aria-label="Titulli" value={draft.title} maxLength={200}
                      onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
                    <Textarea aria-label="Gjendja aktuale" value={draft.description} maxLength={4000} rows={4}
                      onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
                    <div className="flex gap-2">
                      <Button size="sm" onClick={save} disabled={!draft.title.trim()}>Ruaj</Button>
                      <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Anulo</Button>
                    </div>
                  </fieldset>
                ) : (
                  <>
                    <h2 className="text-lg font-semibold leading-snug">{detail.title}</h2>
                    {detail.description && <p className="mt-2 max-w-[62ch] text-sm leading-relaxed text-foreground/80">{detail.description}</p>}
                    {detail.people.length > 0 && <p className="mt-2 text-xs text-muted-foreground">{detail.people.join(", ")}</p>}
                    <div className="mt-4 flex flex-wrap gap-2">
                      <Button size="sm" variant="outline" disabled={busy}
                        onClick={() => { setDraft({ title: detail.title, description: detail.description }); setEditing(true) }}>
                        Korrigjo
                      </Button>
                      {detail.status === "OPEN" ? (
                        <>
                          <Button size="sm" variant="outline" disabled={busy} onClick={() => setStatus("close", "Pika u mbyll.")}>Shëno të mbyllur</Button>
                          <Button size="sm" variant="ghost" disabled={busy} className="text-muted-foreground"
                            onClick={() => setStatus("wrong", "Pika u shënua si e gabuar.")}>Shëno si të gabuar</Button>
                        </>
                      ) : (
                        <Button size="sm" variant="outline" disabled={busy} onClick={() => setStatus("reopen", "Pika u rihap.")}>Rihap</Button>
                      )}
                    </div>
                  </>
                )}

                <ol className="mt-8 border-l">
                  {detail.events.map((event, index) => (
                    <li key={index} className="relative pb-5 pl-5 last:pb-0">
                      <span aria-hidden className="absolute -left-[4px] top-1.5 size-[7px] rounded-full"
                        style={{ background: event.user_name ? "var(--muted-foreground)" : ACCENT }} />
                      <p className="text-xs font-medium">{eventLabel(event)}{event.partial && <span className="font-normal text-muted-foreground"> (takim i pjesshëm)</span>}</p>
                      {event.text && <p className="mt-1 max-w-[62ch] text-sm leading-relaxed text-muted-foreground">{event.text}</p>}
                    </li>
                  ))}
                </ol>
              </article>
            )}
          </section>
        </div>
      )}

      {list && list.failed_meetings > 0 && (
        <p className="mt-8 border-t pt-4 text-xs text-muted-foreground">
          {list.failed_meetings === 1 ? "1 takim nuk u përfshi" : `${list.failed_meetings} takime nuk u përfshinë`} në kujtesë.
          {canRetry && (
            <button type="button" onClick={retry} className="ml-2 text-foreground underline underline-offset-4">Provo përsëri</button>
          )}
        </p>
      )}
    </div>
  )
}
