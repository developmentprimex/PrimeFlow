"use client"

import * as React from "react"
import { KnowledgeProvider, useKnowledge, type KnowledgeType } from "./knowledge-config"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import {
  BookOpen,
  ClipboardCopy,
  ListPlus,
  Loader2,
  Lock,
  NotebookPen,
  Plus,
  Search,
  Sparkles,
  Unlock,
  X,
} from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { PromptDetailDialog, PromptFormDialog, copyText } from "@/components/knowledge/prompt-dialogs"
import { Highlight, indexPrompts, normalizeText, searchPrompts } from "@/components/knowledge/prompt-search"
import {
  NOTE_STAGE_META,
  PROMPT_STATUS_META,
  TASK_STATUS_META,
  formatDate,
  promptMatchesFilter,
  promptNoteMatchesFilter,
  promptNoteStage,
  promptWaitsFor,
  type KnowledgePrompt,
  type KnowledgeUserRef,
  type PromptNote,
  type PromptNoteFilter,
  type PromptNoteStage,
  type PromptFilter,
} from "@/components/knowledge/prompt-types"
import { useAuth } from "@/lib/auth"
import type { Department } from "@/lib/types"
import { cn } from "@/lib/utils"

/* ========================================================================== */
/* Shared table primitives (same look as the PX Notes table)                  */
/* ========================================================================== */

const TH = "h-10 border border-slate-600 bg-white px-2 text-left align-bottom text-xs font-semibold uppercase tracking-wide text-foreground whitespace-nowrap"
const TD = "border border-slate-300 px-2 py-2 align-top text-sm"

function initials(name?: string | null) {
  if (!name) return "—"
  const parts = name.trim().split(/\s+/)
  return ((parts[0]?.[0] || "") + (parts.length > 1 ? parts[parts.length - 1][0] : parts[0]?.[1] || "")).toUpperCase()
}

function Person({ user }: { user?: KnowledgeUserRef | null }) {
  if (!user) return <span className="text-muted-foreground">—</span>
  return (
    <span
      title={user.full_name || ""}
      className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-slate-200 text-[11px] font-semibold text-slate-700"
    >
      {initials(user.full_name)}
    </span>
  )
}

function Pill({ label, className }: { label: string; className: string }) {
  return (
    <span className={cn("inline-flex whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium", className)}>
      {label}
    </span>
  )
}

function TableFrame({ children, minWidth }: { children: React.ReactNode; minWidth: number }) {
  return (
    <div className="max-h-[72vh] w-full overflow-auto rounded-md border-2 border-slate-700 bg-white">
      <table className="w-full table-fixed border-collapse text-sm" style={{ minWidth }}>
        {children}
      </table>
    </div>
  )
}

function EmptyRow({ colSpan, children }: { colSpan: number; children: React.ReactNode }) {
  return (
    <tr>
      <td colSpan={colSpan} className="border border-slate-300 px-4 py-12 text-center text-sm text-muted-foreground">
        {children}
      </td>
    </tr>
  )
}

function Toolbar({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-col gap-2 md:flex-row md:items-center">{children}</div>
}

function SearchBox({
  value,
  onChange,
  placeholder,
  inputRef,
}: {
  value: string
  onChange: (v: string) => void
  placeholder: string
  inputRef?: React.Ref<HTMLInputElement>
}) {
  return (
    <div className="relative flex-1">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        ref={inputRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Escape") onChange("") }}
        placeholder={placeholder}
        className="h-9 bg-white pl-8 pr-8"
        aria-label={placeholder}
      />
      {value ? (
        <button type="button" aria-label="Pastro" onClick={() => onChange("")} className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  )
}

/* ========================================================================== */
/* Prompt Library                                                             */
/* ========================================================================== */

type SortMode = "relevance" | "recent" | "az"

const LIBRARY_FILTERS: { id: PromptFilter; label: string }[] = [
  { id: "ALL", label: "Të gjitha" },
  { id: "APPROVED", label: "Libraria (aprovuar)" },
  { id: "PENDING_TEST", label: "Në testim" },
  { id: "PENDING_APPROVAL", label: "Në aprovim" },
  { id: "REJECTED", label: "Kthyer mbrapa" },
  { id: "WAITING_FOR_ME", label: "Presin veprimin tim" },
]

function PromptLibrary({
  prompts,
  loading,
  onOpen,
  onAdd,
  initialFilter = "APPROVED",
}: {
  prompts: KnowledgePrompt[]
  loading: boolean
  onOpen: (p: KnowledgePrompt) => void
  onAdd: () => void
  initialFilter?: PromptFilter
}) {
  const { kind, text: t } = useKnowledge()
  const { user } = useAuth()
  const [query, setQuery] = React.useState("")
  const [filter, setFilter] = React.useState<PromptFilter>(initialFilter)
  const [keywords, setKeywords] = React.useState<string[]>([])
  const [sort, setSort] = React.useState<SortMode>("relevance")
  const searchRef = React.useRef<HTMLInputElement | null>(null)
  const deferredQuery = React.useDeferredValue(query)

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)
      if (e.key === "/" && !typing) {
        e.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  const isManager = user?.role === "ADMIN" || user?.role === "MANAGER"
  const needsMe = React.useCallback(
    (p: KnowledgePrompt) => promptWaitsFor(p, user?.id, isManager),
    [isManager, user?.id]
  )
  const counts = React.useMemo(() => {
    const c: Record<PromptFilter, number> = { APPROVED: 0, PENDING_TEST: 0, PENDING_APPROVAL: 0, REJECTED: 0, ALL: prompts.length, WAITING_FOR_ME: prompts.filter(needsMe).length }
    for (const p of prompts) c[p.status] += 1
    return c
  }, [prompts, needsMe])
  const waitingForMe = counts.WAITING_FOR_ME

  const scoped = React.useMemo(() => prompts.filter((p) => promptMatchesFilter(p, filter, user?.id, isManager)), [prompts, filter, user?.id, isManager])
  const index = React.useMemo(() => indexPrompts(scoped), [scoped])
  const rows = React.useMemo(() => {
    const hits = searchPrompts(index, deferredQuery, keywords)
    const bySort: SortMode = sort === "relevance" && !deferredQuery.trim() ? "recent" : sort
    hits.sort((a, b) => {
      if (bySort === "relevance" && b.score !== a.score) return b.score - a.score
      if (bySort === "az") return a.prompt.title.localeCompare(b.prompt.title)
      if (filter === "ALL" && !deferredQuery.trim() && sort === "relevance") {
        const approvedDiff = Number(a.prompt.status === "APPROVED") - Number(b.prompt.status === "APPROVED")
        if (approvedDiff) return approvedDiff
      }
      return (b.prompt.approved_at || b.prompt.updated_at).localeCompare(a.prompt.approved_at || a.prompt.updated_at)
    })
    return hits.map((h) => h.prompt)
  }, [index, deferredQuery, keywords, sort, filter])

  const toggleKeyword = (kw: string) =>
    setKeywords((prev) =>
      prev.some((k) => normalizeText(k) === normalizeText(kw))
        ? prev.filter((k) => normalizeText(k) !== normalizeText(kw))
        : [...prev, kw]
    )

  return (
    <div className="space-y-3">
      <Toolbar>
        <SearchBox
          value={query}
          onChange={setQuery}
          inputRef={searchRef}
          placeholder="Kërko sipas titullit, keywords, tekstit ose path…  ( / )"
        />
        <Select value={filter} onValueChange={(v) => setFilter(v as PromptFilter)}>
          <SelectTrigger className="h-9 w-full bg-white md:w-56"><SelectValue /></SelectTrigger>
          <SelectContent>
            {LIBRARY_FILTERS.map((f) => (
              <SelectItem key={f.id} value={f.id}>{t(f.label)} ({counts[f.id]})</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={sort} onValueChange={(v) => setSort(v as SortMode)}>
          <SelectTrigger className="h-9 w-full bg-white md:w-40"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="relevance">Më relevantet</SelectItem>
            <SelectItem value="recent">Më të rejat</SelectItem>
            <SelectItem value="az">A – Z</SelectItem>
          </SelectContent>
        </Select>
        <Button className="h-9" onClick={onAdd}>
          <Plus className="h-4 w-4" /> {t(" Shto prompt ")}</Button>
      </Toolbar>

      {waitingForMe > 0 || keywords.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {waitingForMe > 0 ? (
            <button
              type="button"
              onClick={() => { setFilter("WAITING_FOR_ME"); setQuery(""); setKeywords([]) }}
              className="rounded-md border border-amber-300 bg-amber-50 px-2 py-1 font-medium text-amber-800 hover:bg-amber-100"
            >
              {waitingForMe} {waitingForMe === 1 ? t("prompt pret") : t("prompte presin")} veprimin tënd
            </button>
          ) : null}
          {keywords.map((kw) => (
            <button
              type="button"
              key={kw}
              onClick={() => toggleKeyword(kw)}
              className="inline-flex items-center gap-1 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 font-medium text-white"
            >
              #{kw} <X className="h-3 w-3" />
            </button>
          ))}
        </div>
      ) : null}

      <TableFrame minWidth={1180}>
        <thead className="sticky top-0 z-10 bg-white shadow-sm">
          <tr>
            <th className={cn(TH, "w-[48px] border-l-2 border-l-slate-800")}>NR</th>
            <th className={cn(TH, "w-[30%]")}>{t("Titulli / Prompti")}</th>
            <th className={cn(TH, "w-[18%]")}>Keywords</th>
            <th className={cn(TH, "w-[17%]")}>Path në Files PX</th>
            <th className={cn(TH, "w-[110px]")}>Statusi</th>
            <th className={cn(TH, "w-[56px]")}>Nga</th>
            <th className={cn(TH, kind === "PROMPT" ? "w-[64px]" : "w-[92px]")}>{t("Testoi")}</th>
            <th className={cn(TH, "w-[72px]")}>Aprovoi</th>
            <th className={cn(TH, "w-[92px]")}>Data</th>
            <th className={cn(TH, "w-[100px] border-r-2 border-r-slate-800")}>Kopjo</th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <EmptyRow colSpan={10}><Loader2 className="mx-auto h-4 w-4 animate-spin" /></EmptyRow>
          ) : rows.length === 0 ? (
            <EmptyRow colSpan={10}>
              {scoped.length === 0
                ? filter === "APPROVED"
                  ? t("Libraria është ende bosh. Promptet shfaqen këtu pasi testohen dhe aprovohen.")
                  : t("Asnjë prompt në këtë status.")
                : t("Asnjë prompt nuk përputhet me kërkimin.")}
            </EmptyRow>
          ) : (
            rows.map((p, i) => {
              const meta = PROMPT_STATUS_META[p.status]
              const mine = needsMe(p)
              return (
                <tr key={p.id} className={cn("cursor-pointer hover:bg-slate-50", mine && "bg-amber-50/60")} onClick={() => onOpen(p)}>
                  <td className={cn(TD, "text-center font-medium tabular-nums text-muted-foreground")}>{i + 1}</td>
                  <td className={TD}>
                    <div className="font-semibold leading-snug"><Highlight text={p.title} query={deferredQuery} /></div>
                    <div className="mt-0.5 line-clamp-2 font-mono text-[11px] leading-snug text-muted-foreground">
                      {p.content ? <Highlight text={p.content.replace(/\s+/g, " ").slice(0, 220)} query={deferredQuery} /> : p.file_original_name || ""}
                    </div>
                  </td>
                  <td className={TD}>
                    <div className="flex flex-wrap gap-1">
                      {p.keywords.map((kw) => (
                        <button
                          type="button"
                          key={kw}
                          onClick={(e) => { e.stopPropagation(); toggleKeyword(kw) }}
                          className="rounded border border-slate-300 bg-slate-50 px-1.5 py-0.5 text-[11px] hover:border-slate-500"
                          title="Filtro me këtë keyword"
                        >
                          <Highlight text={kw} query={deferredQuery} />
                        </button>
                      ))}
                    </div>
                  </td>
                  <td className={TD}>
                    {p.files_path ? (
                      <div className="flex items-start gap-1">
                        <code className="min-w-0 flex-1 break-all text-[11px] leading-snug" title={p.files_path}>
                          <Highlight text={p.files_path} query={deferredQuery} />
                        </code>
                        <button
                          type="button"
                          aria-label="Kopjo path"
                          onClick={(e) => { e.stopPropagation(); void copyText(p.files_path!, "Path u kopjua") }}
                          className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-slate-100 hover:text-foreground"
                        >
                          <ClipboardCopy className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ) : <span className="text-muted-foreground">—</span>}
                  </td>
                  <td className={TD}>
                    <Pill label={t(meta.label)} className={meta.className} />
                    {mine ? <div className="mt-1 text-[10px] font-semibold uppercase text-amber-700">Pret ty</div> : null}
                  </td>
                  <td className={cn(TD, "text-center")}><Person user={p.created_by} /></td>
                  <td className={cn(TD, "text-center")}>
                    {p.tested_by ? (
                      <Person user={p.tested_by} />
                    ) : p.tester ? (
                      <span title={(t("Testuesi: ") + (p.tester.full_name || "") + " (pret)")} className="inline-flex rounded-full opacity-70 outline-2 outline-offset-1 outline-dashed outline-amber-500">
                        <Person user={p.tester} />
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className={cn(TD, "text-center")}><Person user={p.approved_by} /></td>
                  <td className={cn(TD, "tabular-nums text-xs")}>{formatDate(p.approved_at || p.updated_at)}</td>
                  <td className={TD}>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 px-2"
                      disabled={!p.content}
                      onClick={(e) => { e.stopPropagation(); void copyText(p.content, t("Prompti u kopjua")) }}
                    >
                      <ClipboardCopy className="h-3.5 w-3.5" /> Kopjo
                    </Button>
                  </td>
                </tr>
              )
            })
          )}
        </tbody>
      </TableFrame>
      {!loading && rows.length ? (
        <p className="text-xs text-muted-foreground">{rows.length} {rows.length === 1 ? t("prompt") : t("prompte")} · kliko rreshtin për ta hapur</p>
      ) : null}
    </div>
  )
}

/* ========================================================================== */
/* Prompt Notes                                                               */
/* ========================================================================== */

const STAGE_FILTERS: { id: PromptNoteFilter; label: string }[] = [
  { id: "ACTIVE", label: "Aktive" },
  { id: "NO_TASK", label: "Pa detyrë" },
  { id: "TASK_OPEN", label: "Pending" },
  { id: "READY", label: "Gati për prompt" },
  { id: "IN_REVIEW", label: "Në shqyrtim" },
  { id: "PENDING_TEST", label: "Në pritje të testimit" },
  { id: "PENDING_APPROVAL", label: "Në pritje të konfirmimit" },
  { id: "REJECTED", label: "Kthyer mbrapa" },
  { id: "DONE", label: "Në librari" },
  { id: "CLOSED", label: "Mbyllur" },
  { id: "ALL", label: "Të gjitha" },
]

// Same colours as the SHENIMI cell in PX Notes.
function noteCellClass(note: PromptNote, stage: PromptNoteStage) {
  if (stage === "CLOSED" || stage === "DONE") return stage === "DONE" ? "bg-emerald-100" : "bg-slate-200 text-slate-500"
  if (!note.tasks.length) return "bg-sky-200"
  const statuses = note.tasks.map((t) => t.status)
  if (statuses.every((s) => s === "DONE")) return "bg-emerald-200"
  if (statuses.some((s) => s === "IN_PROGRESS")) return "bg-yellow-200"
  if (statuses.some((s) => s === "WAITING_CLIENT")) return "bg-[#E2C15B] text-[#4F3A00]"
  if (statuses.some((s) => s === "WAITING_CONFIRMATION")) return "bg-amber-50"
  return "bg-pink-200"
}

function PromptNotes({
  notes,
  loading,
  departments,
  prompts,
  reload,
  onAddPrompt,
  onOpenPrompt,
}: {
  notes: PromptNote[]
  loading: boolean
  departments: Department[]
  prompts: KnowledgePrompt[]
  reload: () => Promise<void>
  onAddPrompt: (note: PromptNote) => void
  onOpenPrompt: (p: KnowledgePrompt) => void
}) {
  const { kind, route, text: t } = useKnowledge()
  const { apiFetch, user } = useAuth()
  const router = useRouter()
  const isManager = user?.role === "ADMIN" || user?.role === "MANAGER"
  const [content, setContent] = React.useState("")
  const [priority, setPriority] = React.useState<"NORMAL" | "HIGH">("NORMAL")
  const [departmentId, setDepartmentId] = React.useState("")
  const [posting, setPosting] = React.useState(false)
  const [filter, setFilter] = React.useState<PromptNoteFilter>("ACTIVE")
  const [query, setQuery] = React.useState("")

  React.useEffect(() => {
    if (!departmentId && user?.department_id) setDepartmentId(user.department_id)
  }, [departmentId, user?.department_id])

  const deptCode = React.useCallback(
    (id?: string | null) => departments.find((d) => d.id === id)?.code || "",
    [departments]
  )

  // Same "Create Task from Note" dialog as PX Notes; PX Notes sends the user back here.
  const openPxNotesTaskDialog = (note: PromptNote) => {
    const params = new URLSearchParams({ taskFor: note.id, returnTo: `${route}?view=notes` })
    router.push(`/ga-ka-notes?${params.toString()}`)
  }

  const save = async () => {
    if (content.trim().length < 2) return toast.error(t("Shkruaj kërkesën për prompt"))
    setPosting(true)
    try {
      const res = await apiFetch("/knowledge/prompt-notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: content.trim(), knowledge_type: kind, priority, department_id: departmentId || null }),
      })
      if (!res.ok) {
        let msg = "Shënimi nuk u ruajt"
        try {
          const d = (await res.json()) as { detail?: string }
          if (typeof d.detail === "string") msg = d.detail
        } catch {
          // ignore
        }
        toast.error(msg)
        return
      }
      setContent("")
      setPriority("NORMAL")
      toast.success("Shënimi u ruajt · shfaqet edhe te PX Notes")
      await reload()
    } finally {
      setPosting(false)
    }
  }

  const setNoteStatus = async (note: PromptNote, status: "OPEN" | "CLOSED") => {
    const res = await apiFetch(`/knowledge/prompt-notes/${note.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    })
    if (!res.ok) return toast.error("Statusi nuk u ndryshua")
    await reload()
  }

  const staged = React.useMemo(() => notes.map((n) => ({ note: n, stage: promptNoteStage(n) })), [notes])
  const counts = React.useMemo(() => {
    return new Map(STAGE_FILTERS.map(({ id }) => [id, notes.filter((n) => promptNoteMatchesFilter(n, id)).length]))
  }, [notes])
  const rows = React.useMemo(() => {
    const q = normalizeText(query.trim())
    return staged.filter(({ note }) => {
      if (!promptNoteMatchesFilter(note, filter)) return false
      if (!q) return true
      const hay = normalizeText(
        [note.content, note.created_by?.full_name, ...note.tasks.map((t) => `${t.title} ${t.assignee?.full_name || ""}`), ...note.prompts.map((p) => p.title)].join(" ")
      )
      return q.split(/\s+/).every((t) => hay.includes(t))
    })
  }, [staged, filter, query])

  return (
    <div className="space-y-3">
      <div className="rounded-md border bg-white p-3">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
          <NotebookPen className="h-4 w-4 text-muted-foreground" /> {t(" Kërkesë e re për prompt ")}</div>
        <div className="flex flex-col gap-2 lg:flex-row lg:items-start">
          <Textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void save() }}
            placeholder={t("Çfarë prompti na duhet? p.sh. Prompt për krijimin e Amazon bullet points për programet e MST…")}
            className="max-h-40 min-h-9 flex-1 bg-white py-1.5"
            rows={1}
          />
          <div className="flex flex-wrap gap-2">
            <Select value={priority} onValueChange={(v) => setPriority(v as "NORMAL" | "HIGH")}>
              <SelectTrigger className="h-9 w-28 bg-white"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="NORMAL">Normal</SelectItem>
                <SelectItem value="HIGH">High</SelectItem>
              </SelectContent>
            </Select>
            {isManager || !user?.department_id ? (
              <Select value={departmentId || undefined} onValueChange={setDepartmentId}>
                <SelectTrigger className="h-9 w-44 bg-white"><SelectValue placeholder="Departamenti" /></SelectTrigger>
                <SelectContent>
                  {departments.map((d) => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
                </SelectContent>
              </Select>
            ) : null}
            <Button className="h-9" onClick={() => void save()} disabled={posting || content.trim().length < 2}>
              {posting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Ruaj
            </Button>
          </div>
        </div>
        <p className="mt-1.5 text-[11px] text-muted-foreground">Shfaqet automatikisht edhe te PX Notes. Ctrl+Enter për ta ruajtur.</p>
      </div>

      <Toolbar>
        <SearchBox value={query} onChange={setQuery} placeholder="Kërko te kërkesat, detyrat, personat…" />
        <Select value={filter} onValueChange={(v) => setFilter(v as PromptNoteFilter)}>
          <SelectTrigger className="h-9 w-full bg-white md:w-56"><SelectValue /></SelectTrigger>
          <SelectContent>
            {STAGE_FILTERS.map((f) => (
              <SelectItem key={f.id} value={f.id}>{t(f.label)} ({counts.get(f.id) || 0})</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Toolbar>

      <TableFrame minWidth={1180}>
        <thead className="sticky top-0 z-10 bg-white shadow-sm">
          <tr>
            <th className={cn(TH, "w-[48px] border-l-2 border-l-slate-800")}>NR</th>
            <th className={cn(TH, "w-[28%]")}>Kërkesa</th>
            <th className={cn(TH, "w-[20%]")}>Detyra</th>
            <th className={cn(TH, kind === "PROMPT" ? "w-[72px]" : "w-[100px]")} title={t("Kush e bën promptin / kush e teston")}>{kind === "PROMPT" ? "Për / Test" : "PER / KO"}</th>
            <th className={cn(TH, "w-[118px]")}>Statusi</th>
            <th className={cn(TH, "w-[16%]")}>{t("Prompti")}</th>
            <th className={cn(TH, "w-[56px]")}>Nga</th>
            <th className={cn(TH, "w-[56px]")}>Dep</th>
            <th className={cn(TH, "w-[92px]")}>Data</th>
            <th className={cn(TH, "w-[150px] border-r-2 border-r-slate-800")}>Veprimi</th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <EmptyRow colSpan={10}><Loader2 className="mx-auto h-4 w-4 animate-spin" /></EmptyRow>
          ) : rows.length === 0 ? (
            <EmptyRow colSpan={10}>
              {notes.length === 0 ? t("Ende nuk ka kërkesa për prompte. Shkruaj të parën më lart.") : "Asnjë kërkesë për këtë filtër."}
            </EmptyRow>
          ) : (
            rows.map(({ note, stage }, i) => {
              const stageMeta = NOTE_STAGE_META[stage]
              const canManage = isManager || note.created_by?.id === user?.id
              const canAddPrompt = note.tasks.length > 0 && note.prompts.length === 0 && (stage === "READY" || stage === "TASK_OPEN")
              return (
                <tr key={note.id} className="hover:bg-slate-50/60">
                  <td className={cn(TD, "text-center font-medium tabular-nums text-muted-foreground")}>{i + 1}</td>
                  <td className={cn(TD, noteCellClass(note, stage))}>
                    <p className="whitespace-pre-wrap break-words">{note.content}</p>
                    {note.priority === "HIGH" ? <span className="mt-1 inline-block rounded bg-red-600 px-1.5 text-[10px] font-bold text-white">HIGH</span> : null}
                  </td>
                  <td className={TD}>
                    {note.tasks.length || note.prompts.some((p) => p.test_task_status) ? (
                      <ul className="space-y-1">
                        {note.tasks.map((t) => (
                          <li key={t.id} className="leading-snug">
                            {t.title}
                            {t.due_date ? <span className="block text-[11px] text-muted-foreground">Afati {formatDate(t.due_date)}</span> : null}
                          </li>
                        ))}
                        {note.prompts.filter((p) => p.test_task_status).map((p) => {
                          const status = TASK_STATUS_META[p.test_task_status!] ?? { label: p.test_task_status!, className: "" }
                          return (
                            <li key={(t("test-") + (p.id) + "")} className="leading-snug">
                              {t(" PROMPT: TESTO: ")}{p.title}
                              <span className="mt-0.5 block"><Pill label={status.label} className={status.className} /></span>
                            </li>
                          )
                        })}
                      </ul>
                    ) : <span className="text-muted-foreground">—</span>}
                  </td>
                  <td className={cn(TD, "text-center")}>
                    <div className="flex flex-col items-center gap-1">
                      {note.tasks.length ? note.tasks.map((t) => <Person key={t.id} user={t.assignee} />) : <span className="text-muted-foreground">—</span>}
                      {note.tester ? (
                        <span title={(t("Testuesi: ") + (note.tester.full_name || "") + "")} className="mt-0.5 flex flex-col items-center">
                          <span className="text-[9px] font-bold uppercase tracking-wide text-violet-700">{t("Test")}</span>
                          <span className="rounded-full ring-2 ring-violet-400">
                            <Person user={note.tester} />
                          </span>
                        </span>
                      ) : null}
                    </div>
                  </td>
                  <td className={TD}>
                    <div className="flex flex-col items-start gap-1">
                      {note.tasks.map((t) => {
                        const m = TASK_STATUS_META[t.status] ?? { label: t.status, className: "" }
                        return <Pill key={t.id} label={m.label} className={m.className} />
                      })}
                      <Pill label={t(stageMeta.label)} className={stageMeta.className} />
                    </div>
                  </td>
                  <td className={TD}>
                    {note.prompts.length ? (
                      <div className="flex flex-col gap-1">
                        {note.prompts.map((p) => {
                          const full = prompts.find((x) => x.id === p.id)
                          const m = PROMPT_STATUS_META[p.status]
                          return (
                            <button
                              type="button"
                              key={p.id}
                              onClick={() => full && onOpenPrompt(full)}
                              className="text-left leading-snug hover:underline"
                            >
                              <span className="font-medium">{p.title}</span>
                              <span className="mt-0.5 block"><Pill label={t(m.label)} className={m.className} /></span>
                              <span className="mt-1 block space-y-0.5 text-[11px] leading-snug text-muted-foreground">
                                {p.created_by ? (
                                  <span className="block">Krijoi: <b className="font-medium text-foreground">{p.created_by.full_name || "—"}</b></span>
                                ) : null}
                                {p.tested_by ? (
                                  <span className="block">
                                    {t(" Testoi: ")}<b className="font-medium text-foreground">{p.tested_by.full_name || "—"}</b>
                                    {p.tested_at ? ` · ${formatDate(p.tested_at)}` : ""}
                                  </span>
                                ) : p.tester ? (
                                  <span className="block">
                                    {t(" Testuesi: ")}{p.tester.full_name || "—"} {t(" · pret testimin ")}</span>
                                ) : null}
                                {p.status === "PENDING_APPROVAL" ? (
                                  <span className="block font-medium text-sky-700">{t("Pret konfirmimin e menaxherit te Prompt Library")}</span>
                                ) : null}
                              </span>
                            </button>
                          )
                        })}
                      </div>
                    ) : <span className="text-muted-foreground">—</span>}
                  </td>
                  <td className={cn(TD, "text-center")}><Person user={note.created_by} /></td>
                  <td className={cn(TD, "text-center")}>
                    {deptCode(note.department_id) ? (
                      <span className="rounded-full border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800">{deptCode(note.department_id)}</span>
                    ) : "—"}
                  </td>
                  <td className={cn(TD, "tabular-nums text-xs")}>{formatDate(note.created_at)}</td>
                  <td className={TD}>
                    <div className="flex flex-col items-stretch gap-1">
                      {stage === "NO_TASK" ? (
                        <Button size="sm" className="h-7 px-2" onClick={() => openPxNotesTaskDialog(note)}>
                          <ListPlus className="h-3.5 w-3.5" /> Krijo detyrë
                        </Button>
                      ) : null}
                      {canAddPrompt ? (
                        <Button
                          size="sm"
                          variant={stage === "READY" ? "default" : "outline"}
                          className={cn("h-7 px-2", stage === "READY" && "bg-violet-600 hover:bg-violet-700")}
                          onClick={() => onAddPrompt(note)}
                        >
                          <Sparkles className="h-3.5 w-3.5" /> {t(" Shto promptin ")}</Button>
                      ) : null}
                      {canManage && note.status === "OPEN" && stage !== "DONE" ? (
                        <Button size="sm" variant="ghost" className="h-7 px-2 text-muted-foreground" onClick={() => void setNoteStatus(note, "CLOSED")}>
                          <Lock className="h-3.5 w-3.5" /> Mbyll
                        </Button>
                      ) : null}
                      {canManage && stage === "CLOSED" ? (
                        <Button size="sm" variant="ghost" className="h-7 px-2" onClick={() => void setNoteStatus(note, "OPEN")}>
                          <Unlock className="h-3.5 w-3.5" /> Rihap
                        </Button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              )
            })
          )}
        </tbody>
      </TableFrame>
    </div>
  )
}

/* ========================================================================== */
/* Page                                                                       */
/* ========================================================================== */

type PromptsView = "library" | "notes"

function ViewSwitch({
  view,
  onChange,
  libraryCount,
  notesCount,
  readyCount,
}: {
  view: PromptsView
  onChange: (v: PromptsView) => void
  libraryCount: number
  notesCount: number
  readyCount: number
}) {
  const { text: t } = useKnowledge()
  const item = (id: PromptsView, label: string, Icon: typeof BookOpen, count?: number, extra?: React.ReactNode) => {
    const active = view === id
    return (
      <button
        type="button"
        role="tab"
        aria-selected={active}
        onClick={() => onChange(id)}
        className={cn(
          "inline-flex h-9 items-center gap-2 rounded-md px-4 text-sm font-semibold transition-colors",
          active ? "bg-slate-900 text-white shadow-sm" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
        )}
      >
        <Icon className="h-4 w-4" />
        {label}
        {count !== undefined ? <span className={cn("rounded px-1.5 text-xs tabular-nums", active ? "bg-white/20" : "bg-slate-200 text-slate-700")}>{count}</span> : null}
        {extra}
      </button>
    )
  }
  return (
    <div role="tablist" className="inline-flex flex-wrap gap-1 rounded-lg border bg-white p-1">
      {item(
        "notes",
        "Notes",
        NotebookPen,
        notesCount,
        readyCount ? (
          <span className="rounded bg-violet-600 px-1.5 text-[10px] font-bold text-white" title={t("Gati për prompt")}>{readyCount}</span>
        ) : null
      )}
      {item("library", t("Prompt Library"), BookOpen, libraryCount)}
    </div>
  )
}

function PromptsPageInner() {
  const { kind, text: t } = useKnowledge()
  const { apiFetch } = useAuth()
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const requestedView = searchParams.get("view")
  const view: PromptsView = requestedView === "library" ? "library" : "notes"

  const [prompts, setPrompts] = React.useState<KnowledgePrompt[]>([])
  const [notes, setNotes] = React.useState<PromptNote[]>([])
  const [departments, setDepartments] = React.useState<Department[]>([])
  const [loadingPrompts, setLoadingPrompts] = React.useState(true)
  const [loadingNotes, setLoadingNotes] = React.useState(true)

  const [detail, setDetail] = React.useState<KnowledgePrompt | null>(null)
  const [formOpen, setFormOpen] = React.useState(false)
  const [editing, setEditing] = React.useState<KnowledgePrompt | null>(null)
  const [sourceNote, setSourceNote] = React.useState<PromptNote | null>(null)

  const loadPrompts = React.useCallback(async () => {
    const res = await apiFetch(`/knowledge/prompts?knowledge_type=${kind}`)
    if (res.ok) setPrompts((await res.json()) as KnowledgePrompt[])
    else toast.error(t("Promptet nuk u ngarkuan"))
    setLoadingPrompts(false)
  }, [apiFetch, kind, t])
  const loadNotes = React.useCallback(async () => {
    const res = await apiFetch(`/knowledge/prompt-notes?knowledge_type=${kind}`)
    if (res.ok) setNotes((await res.json()) as PromptNote[])
    else toast.error("Shënimet nuk u ngarkuan")
    setLoadingNotes(false)
  }, [apiFetch, kind])
  const reloadAll = React.useCallback(async () => {
    await Promise.all([loadPrompts(), loadNotes()])
  }, [loadPrompts, loadNotes])

  React.useEffect(() => {
    void reloadAll()
    void apiFetch("/departments").then(async (res) => { if (res.ok) setDepartments((await res.json()) as Department[]) })
  }, [apiFetch, reloadAll])

  // Deep link from a task description: /knowledge/prompts?prompt=<id> opens the full prompt.
  const linkedPromptId = searchParams.get("prompt")
  const openedLinkRef = React.useRef<string | null>(null)
  React.useEffect(() => {
    if (!linkedPromptId || loadingPrompts || openedLinkRef.current === linkedPromptId) return
    openedLinkRef.current = linkedPromptId
    const found = prompts.find((p) => p.id === linkedPromptId)
    if (found) {
      setDetail(found)
      return
    }
    void apiFetch(`/knowledge/prompts/${linkedPromptId}`).then(async (res) => {
      if (res.ok) {
        const entry = (await res.json()) as KnowledgePrompt
        if ((entry.knowledge_type || "PROMPT") === kind) setDetail(entry)
        else toast.error(t("Prompti nuk u gjet"))
      }
      else toast.error(t("Prompti nuk u gjet"))
    })
  }, [apiFetch, linkedPromptId, loadingPrompts, prompts, kind, t])

  const closeDetail = () => {
    setDetail(null)
    if (linkedPromptId) {
      const params = new URLSearchParams(searchParams.toString())
      params.delete("prompt")
      const qs = params.toString()
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
    }
  }

  const setView = (next: PromptsView) => {
    const params = new URLSearchParams(searchParams.toString())
    if (next === "notes") params.delete("view")
    else params.set("view", "library")
    const qs = params.toString()
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false })
  }

  const onSaved = (saved: KnowledgePrompt) => {
    setPrompts((prev) => [saved, ...prev.filter((p) => p.id !== saved.id)])
    if (detail?.id === saved.id) setDetail(saved)
    void loadNotes()
  }

  const readyCount = notes.filter((n) => promptNoteStage(n) === "READY").length
  const activeNotes = notes.filter((n) => promptNoteMatchesFilter(n, "ACTIVE")).length
  const approvedCount = prompts.filter((p) => p.status === "APPROVED").length
  // Prompts created without a request still need to be visible in the work queue.
  const notesById = new Set(notes.map((n) => n.id))
  const unlinkedPendingPrompts = prompts.filter((p) => p.status !== "APPROVED" && (!p.source_note_id || !notesById.has(p.source_note_id)))

  return (
    <div className="mx-auto max-w-[1600px] space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Knowledge PX</p>
          <h1 className="text-2xl font-bold tracking-tight">{t("Prompts")}</h1>
        </div>
        <ViewSwitch
          view={view}
          onChange={setView}
          libraryCount={approvedCount}
          notesCount={activeNotes + unlinkedPendingPrompts.length}
          readyCount={readyCount}
        />
      </div>

      {view === "notes" ? (
        <section className="space-y-3" aria-label={t("Kërkesat dhe detyrat për prompte")}>
          <PromptNotes
            key={`notes-${view}`}
            notes={notes}
            loading={loadingNotes}
            departments={departments}
            prompts={prompts}
            reload={reloadAll}
            onAddPrompt={(note) => { setEditing(null); setSourceNote(note); setFormOpen(true) }}
            onOpenPrompt={setDetail}
          />
          {unlinkedPendingPrompts.length > 0 ? (
            <div className="space-y-3">
              <h2 className="text-base font-semibold">{t("Promptet pa kërkesë · testim dhe konfirmim")}</h2>
              <PromptLibrary
                key="unlinked-prompts"
                prompts={unlinkedPendingPrompts}
                loading={loadingPrompts}
                onOpen={setDetail}
                onAdd={() => { setEditing(null); setSourceNote(null); setFormOpen(true) }}
                initialFilter="ALL"
              />
            </div>
          ) : null}
        </section>
      ) : null}

      {view === "library" ? (
        <section className="space-y-3" aria-label={t("Promptet")}>
          <PromptLibrary
            key={`prompts-${view}`}
            prompts={prompts}
            loading={loadingPrompts}
            onOpen={setDetail}
            onAdd={() => { setEditing(null); setSourceNote(null); setFormOpen(true) }}
            initialFilter="APPROVED"
          />
        </section>
      ) : null}

      <PromptFormDialog open={formOpen} onOpenChange={setFormOpen} prompt={editing} sourceNote={sourceNote} onSaved={onSaved} />
      <PromptDetailDialog
        prompt={detail}
        onClose={closeDetail}
        onChanged={(p) => { onSaved(p); setDetail(p) }}
        onDeleted={(id) => { setPrompts((prev) => prev.filter((p) => p.id !== id)); closeDetail(); void loadNotes() }}
        onEdit={(p) => { closeDetail(); setEditing(p); setSourceNote(null); setFormOpen(true) }}
      />
    </div>
  )
}

export default function KnowledgePage({ kind = "PROMPT" }: { kind?: KnowledgeType }) {
  return (
    <KnowledgeProvider key={kind} kind={kind}><React.Suspense fallback={<div className="py-12 text-center text-sm text-muted-foreground">Duke ngarkuar…</div>}>
      <PromptsPageInner />
    </React.Suspense></KnowledgeProvider>
  )
}
