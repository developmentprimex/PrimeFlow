"use client"

import * as React from "react"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"
import { CATEGORY_LABELS, json, type KnowledgeCategory, type KnowledgeItem } from "@/lib/mira"

const CATEGORIES = Object.keys(CATEGORY_LABELS) as KnowledgeCategory[]
type Draft = { id?: string; title: string; category: KnowledgeCategory; content_text: string; is_active: boolean }
const EMPTY: Draft = { title: "", category: "STRUKTURA", content_text: "", is_active: true }

function CategorySelect({ value, onChange }: { value: KnowledgeCategory; onChange: (v: KnowledgeCategory) => void }) {
  return (
    <select aria-label="Kategoria" value={value} onChange={(e) => onChange(e.target.value as KnowledgeCategory)}
      className="h-9 rounded-md border bg-background px-2 text-sm">
      {CATEGORIES.map((c) => <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>)}
    </select>
  )
}

export function KnowledgeTab({ canManage }: { canManage: boolean }) {
  const { apiFetch } = useAuth()
  const [data, setData] = React.useState<{ items: KnowledgeItem[]; budget: number; active_chars: number } | null>(null)
  const [draft, setDraft] = React.useState<Draft | null>(null)
  const [open, setOpen] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [uploadCategory, setUploadCategory] = React.useState<KnowledgeCategory>("RREGULLORE")
  const fileInput = React.useRef<HTMLInputElement>(null)

  const load = React.useCallback(async () => {
    try {
      setData(await json(await apiFetch("/mira/knowledge")))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    }
  }, [apiFetch])
  React.useEffect(() => { void load() }, [load])

  const run = async (work: () => Promise<unknown>, done: string) => {
    setBusy(true)
    try {
      await work()
      toast.success(done)
      await load()
      return true
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
      return false
    } finally {
      setBusy(false)
    }
  }

  const save = async () => {
    if (!draft) return
    const body = JSON.stringify({ title: draft.title.trim(), category: draft.category, content_text: draft.content_text, is_active: draft.is_active })
    const ok = await run(async () => json(await apiFetch(draft.id ? `/mira/knowledge/${draft.id}` : "/mira/knowledge", {
      method: draft.id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body,
    })), "U ruajt në Knowledge.")
    if (ok) setDraft(null)
  }

  const upload = async (file: File) => {
    const form = new FormData()
    form.append("file", file)
    form.append("category", uploadCategory)
    await run(async () => json(await apiFetch("/mira/knowledge/upload", { method: "POST", body: form })), `${file.name} u shtua.`)
    if (fileInput.current) fileInput.current.value = ""
  }

  const toggle = (item: KnowledgeItem) => run(async () => json(await apiFetch(`/mira/knowledge/${item.id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ is_active: !item.is_active }),
  })), item.is_active ? "Mira nuk e lexon më." : "Mira e lexon tani.")

  const remove = (item: KnowledgeItem) => {
    if (!window.confirm(`Ta fshij "${item.title}"?`)) return
    void run(async () => json(await apiFetch(`/mira/knowledge/${item.id}`, { method: "DELETE" })), "U fshi.")
  }

  const over = data && data.active_chars > data.budget
  return (
    <div className="py-5">
      <p className="max-w-[70ch] text-sm text-muted-foreground">
        Çka di Mira për Primex: struktura, rregulloret, definimet. Dokumentet aktive i lexon para çdo takimi
        {data && <> ({data.active_chars.toLocaleString("sq-AL")} nga {data.budget.toLocaleString("sq-AL")} shenja)</>}.
        {over && " Pjesa që kalon kufirin kërkohet vetëm kur dikush pyet për të."}
      </p>

      {canManage && !draft && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => setDraft({ ...EMPTY })}>Shto tekst</Button>
          <span className="mx-1 text-sm text-muted-foreground">ose ngarko skedar</span>
          <CategorySelect value={uploadCategory} onChange={setUploadCategory} />
          <input ref={fileInput} type="file" accept=".txt,.md,.csv,.json,.docx" disabled={busy}
            onChange={(e) => { const file = e.target.files?.[0]; if (file) void upload(file) }}
            className="text-sm file:mr-2 file:rounded-md file:border file:bg-background file:px-3 file:py-1.5 file:text-sm" />
        </div>
      )}

      {draft && (
        <fieldset disabled={busy} className="mt-4 max-w-3xl space-y-3 rounded-lg border p-4">
          <div className="flex flex-wrap gap-2">
            <Input aria-label="Titulli" placeholder="Titulli, p.sh. Rregullorja e 1H" value={draft.title} maxLength={200}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })} className="min-w-[240px] flex-1" />
            <CategorySelect value={draft.category} onChange={(category) => setDraft({ ...draft, category })} />
          </div>
          <Textarea aria-label="Përmbajtja" rows={14} value={draft.content_text} placeholder="Teksti që Mira duhet ta dijë…"
            onChange={(e) => setDraft({ ...draft, content_text: e.target.value })} />
          <div className="flex gap-2">
            <Button size="sm" onClick={save} disabled={!draft.title.trim() || !draft.content_text.trim()}>Ruaj</Button>
            <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>Anulo</Button>
          </div>
        </fieldset>
      )}

      {data && data.items.length === 0 && !draft && (
        <p className="py-14 text-center text-sm text-muted-foreground">Knowledge është bosh. Shto strukturën e Primex, rregulloret dhe definimet.</p>
      )}

      {CATEGORIES.map((category) => {
        const items = data?.items.filter((i) => i.category === category) ?? []
        if (!items.length) return null
        return (
          <section key={category} className="mt-8">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{CATEGORY_LABELS[category]}</h3>
            <ul className="divide-y rounded-lg border">
              {items.map((item) => (
                <li key={item.id} className="px-4 py-3">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <button type="button" onClick={() => setOpen(open === item.id ? null : item.id)}
                      className={cn("min-w-0 flex-1 truncate text-left text-sm font-medium hover:underline", !item.is_active && "text-muted-foreground")}>
                      {item.title}
                    </button>
                    <span className="text-xs text-muted-foreground">
                      {item.file_name ?? "tekst"} · {item.chars.toLocaleString("sq-AL")} shenja{!item.is_active && " · joaktiv"}
                    </span>
                    {canManage && (
                      <span className="flex gap-1">
                        <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" disabled={busy}
                          onClick={() => setDraft({ id: item.id, title: item.title, category: item.category, content_text: item.content_text, is_active: item.is_active })}>
                          Ndrysho
                        </Button>
                        <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" disabled={busy} onClick={() => void toggle(item)}>
                          {item.is_active ? "Çaktivizo" : "Aktivizo"}
                        </Button>
                        <Button size="sm" variant="ghost" className="h-7 px-2 text-xs text-muted-foreground" disabled={busy} onClick={() => remove(item)}>
                          Fshij
                        </Button>
                      </span>
                    )}
                  </div>
                  {open === item.id && (
                    <pre className="mt-3 max-h-[360px] overflow-y-auto whitespace-pre-wrap font-sans text-sm leading-relaxed text-foreground/80">{item.content_text}</pre>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}
