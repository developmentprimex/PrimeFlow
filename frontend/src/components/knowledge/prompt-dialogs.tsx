"use client"

import * as React from "react"
import { useKnowledge } from "./knowledge-config"
import {
  Check,
  CheckCircle2,
  ChevronRight,
  ClipboardCopy,
  Download,
  FileText,
  FlaskConical,
  Folder,
  FolderOpen,
  Home,
  Loader2,
  Pencil,
  Search,
  ShieldCheck,
  Trash2,
  Undo2,
  Upload,
  X,
} from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useAuth } from "@/lib/auth"
import type { UserLookup } from "@/lib/types"
import { fetchUsersLookupCached } from "@/lib/users-cache"
import { cn } from "@/lib/utils"

import {
  PROMPT_STATUS_META,
  TASK_STATUS_META,
  formatDate,
  type KnowledgePrompt,
  type PromptNote,
  type PromptStatus,
} from "./prompt-types"

const TEXT_FILE_RE = /\.(txt|md|markdown|json|ya?ml|prompt|xml|csv)$/i

async function readError(res: Response, fallback: string) {
  try {
    const data = (await res.json()) as { detail?: unknown }
    if (typeof data?.detail === "string") return data.detail
  } catch {
    // ignore
  }
  return fallback
}

export async function copyText(text: string, label = "U kopjua") {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(label)
  } catch {
    toast.error("Kopjimi nuk funksionoi")
  }
}

export function PromptStatusBadge({ status }: { status: PromptStatus }) {
  const { text: t } = useKnowledge()
  const meta = PROMPT_STATUS_META[status]
  return (
    <Badge variant="outline" className={cn("font-medium", meta.className)}>
      {t(meta.label)}
    </Badge>
  )
}

export function TaskStatusBadge({ status }: { status: string }) {
  const meta = TASK_STATUS_META[status] ?? { label: status, className: "" }
  return (
    <Badge variant="outline" className={cn("font-medium", meta.className)}>
      {meta.label}
    </Badge>
  )
}

/* -------------------------------------------------------------------------- */
/* Keyword input                                                              */
/* -------------------------------------------------------------------------- */

function KeywordInput({ value, onChange }: { value: string[]; onChange: (next: string[]) => void }) {
  const [draft, setDraft] = React.useState("")
  const add = (raw: string) => {
    const parts = raw.split(/[,;\n#]+/).map((p) => p.trim()).filter(Boolean)
    if (!parts.length) return
    const seen = new Set(value.map((v) => v.toLowerCase()))
    const next = [...value]
    for (const p of parts) {
      if (!seen.has(p.toLowerCase())) {
        seen.add(p.toLowerCase())
        next.push(p)
      }
    }
    onChange(next)
    setDraft("")
  }
  return (
    <div className="flex min-h-10 flex-wrap items-center gap-1.5 rounded-md border px-2 py-1.5 focus-within:ring-[3px] focus-within:ring-ring/50">
      {value.map((kw) => (
        <span key={kw} className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-xs font-medium">
          {kw}
          <button
            type="button"
            aria-label={`Hiq ${kw}`}
            className="rounded-full text-muted-foreground hover:text-foreground"
            onClick={() => onChange(value.filter((v) => v !== kw))}
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(e) => {
          const v = e.target.value
          if (/[,;]/.test(v)) add(v)
          else setDraft(v)
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault()
            add(draft)
          } else if (e.key === "Backspace" && !draft && value.length) {
            onChange(value.slice(0, -1))
          }
        }}
        onBlur={() => add(draft)}
        onPaste={(e) => {
          const text = e.clipboardData.getData("text")
          if (/[,;\n]/.test(text)) {
            e.preventDefault()
            add(draft + text)
          }
        }}
        placeholder={value.length ? "" : "p.sh. Amazon, bulletpoints, listing"}
        className="min-w-[10rem] flex-1 bg-transparent py-0.5 text-sm outline-none placeholder:text-muted-foreground"
      />
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Create / edit prompt                                                       */
/* -------------------------------------------------------------------------- */

type FilesFolder = {
  id: number
  fullPath?: string | null
  relativePath?: string | null
  folderName: string
  hasChildren?: boolean | null
}

export function PromptFormDialog({
  open,
  onOpenChange,
  prompt,
  sourceNote,
  onSaved,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  prompt?: KnowledgePrompt | null
  sourceNote?: PromptNote | null
  onSaved: (prompt: KnowledgePrompt) => void
}) {
  const { kind, text: t } = useKnowledge()
  const { apiFetch, user } = useAuth()
  const [title, setTitle] = React.useState("")
  const [testerId, setTesterId] = React.useState("")
  const [users, setUsers] = React.useState<UserLookup[]>([])
  const [content, setContent] = React.useState("")
  const [keywords, setKeywords] = React.useState<string[]>([])
  const [filesPath, setFilesPath] = React.useState("")
  const [file, setFile] = React.useState<File | null>(null)
  const [removeFile, setRemoveFile] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const [folderPickerOpen, setFolderPickerOpen] = React.useState(false)
  const [folderItems, setFolderItems] = React.useState<FilesFolder[]>([])
  const [folderTrail, setFolderTrail] = React.useState<FilesFolder[]>([])
  const [selectedFolder, setSelectedFolder] = React.useState<FilesFolder | null>(null)
  const [folderSearch, setFolderSearch] = React.useState("")
  const [foldersLoading, setFoldersLoading] = React.useState(false)
  const fileRef = React.useRef<HTMLInputElement | null>(null)

  React.useEffect(() => {
    if (!open) return
    setTitle(prompt?.title ?? "")
    setContent(prompt?.content ?? "")
    setKeywords(prompt?.keywords ?? [])
    setFilesPath(prompt?.files_path ?? "")
    setTesterId(prompt?.tester?.id ?? sourceNote?.tester?.id ?? "")
    setFile(null)
    setRemoveFile(false)
  }, [open, prompt, sourceNote])

  React.useEffect(() => {
    if (!open || users.length) return
    void fetchUsersLookupCached(apiFetch).then((data) => { if (data) setUsers(data as UserLookup[]) })
  }, [apiFetch, open, users.length])

  const authorId = prompt?.created_by?.id ?? user?.id
  const testerOptions = React.useMemo(
    () =>
      users
        .filter((u) => u.is_active && u.id !== authorId)
        .sort((a, b) => (a.full_name || a.email).localeCompare(b.full_name || b.email)),
    [users, authorId]
  )
  const testerLocked = prompt?.status === "APPROVED"

  const pickFile = async (next: File | null) => {
    setFile(next)
    if (!next) return
    setRemoveFile(false)
    if (!title.trim()) setTitle(next.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "))
    if (TEXT_FILE_RE.test(next.name) && next.size < 2 * 1024 * 1024) {
      const text = await next.text()
      if (!content.trim() || window.confirm(t("Ta zëvendësoj tekstin e promptit me përmbajtjen e skedarit?"))) {
        setContent(text)
      }
    }
  }

  const hasExistingFile = Boolean(prompt?.file_original_name) && !removeFile
  const tasksDone = sourceNote ? sourceNote.tasks.every((t) => t.status === "DONE") : true

  const fetchFolders = async (url: string, trail: FilesFolder[] = []) => {
    setFoldersLoading(true)
    try {
      const res = await apiFetch(url)
      if (!res.ok) {
        toast.error(await readError(res, "Folderat e Files PX nuk u hapën"))
        return
      }
      setFolderItems((await res.json()) as FilesFolder[])
      setFolderTrail(trail)
    } finally {
      setFoldersLoading(false)
    }
  }

  const openFolderPicker = async () => {
    setFolderPickerOpen(true)
    setFolderSearch("")
    setSelectedFolder(null)
    await fetchFolders("/file-access/folders?limit=200", [])
  }

  const browseFolder = async (folder: FilesFolder) => {
    setSelectedFolder(folder)
    await fetchFolders(`/file-access/folders/${folder.id}/children`, [...folderTrail, folder])
  }

  const browseTrail = async (index: number) => {
    if (index < 0) {
      setSelectedFolder(null)
      await fetchFolders("/file-access/folders?limit=200", [])
      return
    }
    const folder = folderTrail[index]
    setSelectedFolder(folder)
    await fetchFolders(`/file-access/folders/${folder.id}/children`, folderTrail.slice(0, index + 1))
  }

  const searchFolders = async () => {
    const query = folderSearch.trim()
    setSelectedFolder(null)
    await fetchFolders(
      query ? `/file-access/folders?search=${encodeURIComponent(query)}&limit=200` : "/file-access/folders?limit=200",
      []
    )
  }

  const chooseFolder = () => {
    if (!selectedFolder) return
    const path = selectedFolder.fullPath || selectedFolder.relativePath || ""
    if (!path) return toast.error("Ky folder nuk ka path në Files PX")
    setFilesPath(path)
    setFolderPickerOpen(false)
  }

  const save = async () => {
    if (title.trim().length < 2) return toast.error(t("Shkruaj titullin e promptit"))
    if (!content.trim() && !file && !hasExistingFile) return toast.error(t("Shto tekstin e promptit ose ngarko një skedar"))
    if (!filesPath.trim()) return toast.error(t("Zgjidh folderin ku do të ruhet prompti në Files PX"))
    if (!testerLocked && !testerId) return toast.error(t("Zgjidh testuesin e promptit"))
    const form = new FormData()
    form.append("title", title.trim())
    if (!prompt) form.append("knowledge_type", kind)
    form.append("content", content)
    form.append("keywords", keywords.join(", "))
    form.append("files_path", filesPath.trim())
    if (testerId && !testerLocked) form.append("tester_id", testerId)
    if (file) form.append("file", file)
    if (!prompt && sourceNote) form.append("source_note_id", sourceNote.id)
    if (prompt && removeFile && !file) form.append("remove_file", "true")
    setSaving(true)
    try {
      const res = await apiFetch(prompt ? `/knowledge/prompts/${prompt.id}` : "/knowledge/prompts", {
        method: prompt ? "PATCH" : "POST",
        body: form,
      })
      if (!res.ok) {
        toast.error(await readError(res, t("Prompti nuk u ruajt")))
        return
      }
      const saved = (await res.json()) as KnowledgePrompt
      toast.success(
        saved.status === "PENDING_TEST"
          ? (t("Prompti u ruajt · ") + (saved.tester?.full_name || t("testuesi")) + t(" e ka detyrën \"PROMPT: TESTO\""))
          : t("Prompti u përditësua")
      )
      onSaved(saved)
      onOpenChange(false)
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{prompt ? t("Edito promptin") : t("Shto promptin")}</DialogTitle>
          <DialogDescription>
            {prompt && prompt.status === "APPROVED"
              ? "Ndryshimet ruhen direkt në librari."
              : t("Pas ruajtjes, prompti duhet të testohet nga një person tjetër dhe pastaj të aprovohet nga menaxheri.")}
          </DialogDescription>
        </DialogHeader>

        {sourceNote ? (
          <div className="rounded-lg border bg-muted/40 p-3 text-sm">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Kërkesa</p>
            <p className="mt-1 whitespace-pre-wrap">{sourceNote.content}</p>
            {!tasksDone ? (
              <p className="mt-2 text-xs text-violet-700">{t("Detyra jote mbyllet automatikisht sapo testuesi ta konfirmojë testimin.")}</p>
            ) : null}
          </div>
        ) : null}

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="kp-title">{t("Titulli i promptit")}</Label>
            <Input id="kp-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("p.sh. Amazon bulletpoints prompt")} maxLength={300} />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <Label htmlFor="kp-content">{t("Prompti")}</Label>
              <span className="text-xs text-muted-foreground">{content.length.toLocaleString()} karaktere</span>
            </div>
            <Textarea
              id="kp-content"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder={"Role: …\nContext: …\nTask: …\nOutput format: …"}
              className="max-h-[45vh] min-h-48 font-mono text-[13px] leading-relaxed"
            />
          </div>

          <div className="space-y-2">
            <Label>{t("Ose ngarko skedarin e promptit")}</Label>
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              accept=".txt,.md,.markdown,.json,.yaml,.yml,.prompt,.xml,.csv,.pdf,.doc,.docx"
              onChange={(e) => void pickFile(e.target.files?.[0] ?? null)}
            />
            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                <Upload className="h-4 w-4" />
                Zgjidh skedarin
              </Button>
              {file ? (
                <span className="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs">
                  <FileText className="h-3.5 w-3.5" />
                  {file.name}
                  <button type="button" aria-label="Hiq skedarin" onClick={() => { setFile(null); if (fileRef.current) fileRef.current.value = "" }}>
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ) : hasExistingFile ? (
                <span className="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs">
                  <FileText className="h-3.5 w-3.5" />
                  {prompt?.file_original_name}
                  <button type="button" aria-label="Hiq skedarin" onClick={() => setRemoveFile(true)}>
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ) : (
                <span className="text-xs text-muted-foreground">{t(".txt / .md lexohen automatikisht në fushën e promptit")}</span>
              )}
            </div>
          </div>

          <div className="space-y-2">
            <Label>Keywords</Label>
            <KeywordInput value={keywords} onChange={setKeywords} />
            <p className="text-xs text-muted-foreground">{t("Shtyp Enter ose presje pas çdo fjale. Këto fjalë e bëjnë promptin më të lehtë për t'u gjetur.")}</p>
          </div>

          <div className="space-y-2">
            <Label>{t("Testuesi i promptit")}</Label>
            <Select value={testerId || undefined} onValueChange={setTesterId} disabled={testerLocked}>
              <SelectTrigger className="w-full"><SelectValue placeholder={t("Zgjidh personin që do ta testojë")} /></SelectTrigger>
              <SelectContent>
                {testerOptions.map((u) => (
                  <SelectItem key={u.id} value={u.id}>{u.full_name || u.username || u.email}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {testerLocked
                ? t("Prompti është aprovuar; testuesi nuk ndryshohet më.")
                : t("Personit i krijohet automatikisht detyra “PROMPT: TESTO: Titulli”. Kur klikon “E testova”, detyra mbyllet vetë.")}
            </p>
          </div>

          <div className="space-y-2">
            <Label>Folderi në Files PX</Label>
            <div className="flex flex-col gap-2 rounded-md border bg-muted/20 p-3 sm:flex-row sm:items-center">
              <div className="flex min-w-0 flex-1 items-center gap-2">
                <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground" />
                <code className="min-w-0 break-all text-[12px]">
                  {filesPath || "Nuk është zgjedhur ende"}
                </code>
              </div>
              <Button type="button" variant="outline" size="sm" className="shrink-0" onClick={() => void openFolderPicker()}>
                <FolderOpen className="h-4 w-4" />
                {filesPath ? "Ndrysho folderin" : "Zgjidh folderin"}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              {t(" PrimeFlow krijon skedarin .txt në folderin e zgjedhur dhe e përditëson kur editohet prompti. ")}</p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Anulo
          </Button>
          <Button onClick={() => void save()} disabled={saving}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
            {prompt ? "Ruaj ndryshimet" : t("Ruaj për testim")}
          </Button>
        </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={folderPickerOpen} onOpenChange={setFolderPickerOpen}>
        <DialogContent className="max-h-[88vh] sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Zgjidh folderin në Files PX</DialogTitle>
            <DialogDescription>{t("Hap folderat e serverit dhe zgjidh ku do të ruhet prompti.")}</DialogDescription>
          </DialogHeader>

          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              void searchFolders()
            }}
          >
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={folderSearch}
                onChange={(event) => setFolderSearch(event.target.value)}
                placeholder="Kërko folderin..."
                className="pl-8"
              />
            </div>
            <Button type="submit" variant="outline" disabled={foldersLoading}>Kërko</Button>
          </form>

          <div className="flex min-h-8 flex-wrap items-center gap-1 rounded-md border bg-muted/30 px-2 py-1 text-xs">
            <button type="button" className="rounded p-1 hover:bg-background" onClick={() => void browseTrail(-1)} aria-label="Files PX">
              <Home className="h-4 w-4" />
            </button>
            {folderTrail.map((folder, index) => (
              <React.Fragment key={folder.id}>
                <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                <button type="button" className="max-w-48 truncate rounded px-1.5 py-1 hover:bg-background" onClick={() => void browseTrail(index)}>
                  {folder.folderName}
                </button>
              </React.Fragment>
            ))}
          </div>

          <div className="min-h-64 overflow-y-auto rounded-md border">
            {foldersLoading ? (
              <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
                <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Duke hapur folderat...
              </div>
            ) : folderItems.length ? (
              <div className="divide-y">
                {folderItems.map((folder) => {
                  const selected = selectedFolder?.id === folder.id
                  return (
                    <div key={folder.id} className={cn("flex items-center gap-2 p-2", selected && "bg-primary/10")}>
                      <button
                        type="button"
                        className="flex min-w-0 flex-1 items-center gap-2 rounded px-2 py-2 text-left hover:bg-muted"
                        onClick={() => setSelectedFolder(folder)}
                      >
                        <Folder className="h-4 w-4 shrink-0 text-amber-600" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">{folder.folderName}</span>
                          <span className="block truncate text-[11px] text-muted-foreground">{folder.fullPath || folder.relativePath}</span>
                        </span>
                        {selected ? <Check className="h-4 w-4 shrink-0 text-primary" /> : null}
                      </button>
                      <Button type="button" size="icon-sm" variant="ghost" aria-label={`Hap ${folder.folderName}`} onClick={() => void browseFolder(folder)}>
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="flex h-64 items-center justify-center px-6 text-center text-sm text-muted-foreground">
                Nuk u gjet asnjë nënfolder. Mund të zgjedhësh folderin aktual ose të kthehesh mbrapa.
              </div>
            )}
          </div>

          {selectedFolder ? (
            <div className="rounded-md bg-muted/40 px-3 py-2 text-xs">
              <span className="font-semibold">Folderi i zgjedhur: </span>
              <code className="break-all">{selectedFolder.fullPath || selectedFolder.relativePath}</code>
            </div>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setFolderPickerOpen(false)}>Anulo</Button>
            <Button type="button" onClick={chooseFolder} disabled={!selectedFolder}>
              <Check className="h-4 w-4" /> Zgjidh këtë folder
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

/* -------------------------------------------------------------------------- */
/* Prompt detail + review actions                                             */
/* -------------------------------------------------------------------------- */

type ReviewMode = "test" | "reject" | null

export function PromptDetailDialog({
  prompt,
  onClose,
  onChanged,
  onDeleted,
  onEdit,
}: {
  prompt: KnowledgePrompt | null
  onClose: () => void
  onChanged: (prompt: KnowledgePrompt) => void
  onDeleted: (id: string) => void
  onEdit: (prompt: KnowledgePrompt) => void
}) {
  const { kind, text: t } = useKnowledge()
  const { apiFetch, user } = useAuth()
  const [busy, setBusy] = React.useState(false)
  const [mode, setMode] = React.useState<ReviewMode>(null)
  const [comment, setComment] = React.useState("")

  React.useEffect(() => {
    setMode(null)
    setComment("")
  }, [prompt?.id])

  if (!prompt) return null
  const isManager = user?.role === "ADMIN" || user?.role === "MANAGER"
  const isAuthor = prompt.created_by?.id === user?.id
  const isTester = prompt.tester ? prompt.tester.id === user?.id : true
  const canTest = prompt.status === "PENDING_TEST" && !isAuthor && isTester
  const canApprove =
    prompt.status === "PENDING_APPROVAL" && isManager && !isAuthor && prompt.tested_by?.id !== user?.id
  const canReject =
    (prompt.status === "PENDING_TEST" && !isAuthor && (isTester || isManager)) ||
    ((prompt.status === "PENDING_APPROVAL" || prompt.status === "APPROVED") && isManager)
  const canEdit = isManager || (isAuthor && prompt.status !== "APPROVED")
  const canDelete = isManager || (isAuthor && prompt.status !== "APPROVED")

  const act = async (path: string, body?: object, success?: string) => {
    setBusy(true)
    try {
      const res = await apiFetch(`/knowledge/prompts/${prompt.id}/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body ?? {}),
      })
      if (!res.ok) {
        toast.error(await readError(res, "Veprimi dështoi"))
        return
      }
      onChanged((await res.json()) as KnowledgePrompt)
      setMode(null)
      setComment("")
      if (success) toast.success(success)
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!window.confirm((t("Ta fshij promptin \"") + (prompt.title) + "\"?"))) return
    setBusy(true)
    try {
      const res = await apiFetch(`/knowledge/prompts/${prompt.id}`, { method: "DELETE" })
      if (!res.ok) {
        toast.error(await readError(res, "Fshirja dështoi"))
        return
      }
      toast.success(t("Prompti u fshi"))
      onDeleted(prompt.id)
    } finally {
      setBusy(false)
    }
  }

  const download = async () => {
    const res = await apiFetch(`/knowledge/prompts/${prompt.id}/file`)
    if (!res.ok) return toast.error(await readError(res, "Skedari nuk u shkarkua"))
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = prompt.file_original_name || t("prompt")
    a.click()
    URL.revokeObjectURL(url)
  }

  const steps = [
    { label: "Krijuar", who: prompt.created_by?.full_name, when: prompt.created_at, done: true },
    {
      label: t("Testuar"),
      who: prompt.tested_by?.full_name,
      when: prompt.tested_at,
      done: Boolean(prompt.tested_at),
      pending: prompt.tester?.full_name ? (t("Testuesi: ") + (prompt.tester.full_name) + "") : undefined,
    },
    { label: "Aprovuar", who: prompt.approved_by?.full_name, when: prompt.approved_at, done: Boolean(prompt.approved_at) },
  ]

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-4xl">
        <DialogHeader>
          <div className="flex flex-wrap items-center gap-2 pr-8">
            <DialogTitle className="text-xl">{prompt.title}</DialogTitle>
            <PromptStatusBadge status={prompt.status} />
          </div>
          {prompt.keywords.length ? (
            <div className="flex flex-wrap gap-1.5 pt-1">
              {prompt.keywords.map((kw) => (
                <Badge key={kw} variant="secondary" className="font-normal">#{kw}</Badge>
              ))}
            </div>
          ) : null}
        </DialogHeader>

        {prompt.status === "REJECTED" && prompt.rejection_reason ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <p className="font-semibold">Kthyer mbrapa nga {prompt.rejected_by?.full_name || "—"} · {formatDate(prompt.rejected_at)}</p>
            <p className="mt-1 whitespace-pre-wrap">{prompt.rejection_reason}</p>
            {isAuthor ? <p className="mt-2 text-xs">{t("Edito promptin dhe ruaje përsëri për ta dërguar në testim.")}</p> : null}
          </div>
        ) : null}

        <div className="relative rounded-lg border bg-muted/30">
          <div className="flex items-center justify-between border-b px-3 py-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{t("Prompti")}</span>
            <Button size="sm" variant="ghost" onClick={() => void copyText(prompt.content, t("Prompti u kopjua"))} disabled={!prompt.content}>
              <ClipboardCopy className="h-4 w-4" />
              Kopjo
            </Button>
          </div>
          <pre className="max-h-[45vh] overflow-auto whitespace-pre-wrap break-words p-4 font-mono text-[13px] leading-relaxed">
            {prompt.content || <span className="text-muted-foreground">{t("Prompti është vetëm në skedarin e bashkëngjitur.")}</span>}
          </pre>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-lg border p-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Path në Files PX</p>
            {prompt.files_path ? (
              <div className="mt-1 flex items-center gap-2">
                <FolderOpen className="h-4 w-4 shrink-0 text-muted-foreground" />
                <code className="min-w-0 flex-1 truncate text-[13px]" title={prompt.files_path}>{prompt.files_path}</code>
                <Button size="icon-sm" variant="ghost" aria-label="Kopjo path" onClick={() => void copyText(prompt.files_path!, "Path u kopjua")}>
                  <ClipboardCopy className="h-4 w-4" />
                </Button>
              </div>
            ) : (
              <p className="mt-1 text-sm text-muted-foreground">—</p>
            )}
          </div>
          <div className="rounded-lg border p-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Skedari</p>
            {prompt.file_original_name ? (
              <button type="button" onClick={() => void download()} className="mt-1 inline-flex items-center gap-2 text-sm text-primary hover:underline">
                <Download className="h-4 w-4" />
                {prompt.file_original_name}
              </button>
            ) : (
              <p className="mt-1 text-sm text-muted-foreground">—</p>
            )}
          </div>
        </div>

        <ol className="grid gap-2 sm:grid-cols-3">
          {steps.map((step) => (
            <li key={step.label} className={cn("rounded-lg border p-3", step.done ? "border-emerald-200 bg-emerald-50/50" : "border-dashed")}>
              <div className="flex items-center gap-1.5 text-sm font-semibold">
                {step.done ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <span className="h-4 w-4 rounded-full border-2 border-muted-foreground/30" />}
                {step.label}
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{step.done ? `${step.who || "—"} · ${formatDate(step.when)}` : step.pending || "Në pritje"}</p>
            </li>
          ))}
        </ol>
        {prompt.test_comment ? (
          <p className="rounded-lg border bg-muted/30 p-3 text-sm"><span className="font-semibold">{t("Komenti i testimit: ")}</span>{prompt.test_comment}</p>
        ) : null}

        {mode ? (
          <div className="space-y-2 rounded-lg border p-3">
            <Label htmlFor="kp-review-comment">{mode === "test" ? t("Komenti i testimit (opsional)") : "Arsyeja e kthimit"}</Label>
            <Textarea
              id="kp-review-comment"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder={mode === "test" ? t("p.sh. E testova me 5 produkte, rezultati OK") : "Çfarë duhet rregulluar?"}
              className="min-h-20"
              autoFocus
            />
            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setMode(null)} disabled={busy}>Anulo</Button>
              {mode === "test" ? (
                <Button size="sm" disabled={busy} onClick={() => void act(kind === "PROMPT" ? "confirm-test" : "confirm-control", { comment }, t("Testimi u konfirmua · pret aprovimin e menaxherit"))}>
                  {kind === "PROMPT" ? <FlaskConical className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
                  {t(" Konfirmo testimin ")}</Button>
              ) : (
                <Button size="sm" variant="destructive" disabled={busy || !comment.trim()} onClick={() => void act("reject", { comment }, t("Prompti u kthye te autori"))}>
                  <Undo2 className="h-4 w-4" />
                  Kthe mbrapa
                </Button>
              )}
            </div>
          </div>
        ) : null}

        <DialogFooter className="flex-wrap gap-2 sm:justify-between">
          <div className="flex flex-wrap gap-2">
            {canEdit ? (
              <Button variant="outline" size="sm" onClick={() => onEdit(prompt)} disabled={busy}>
                <Pencil className="h-4 w-4" />
                Edito
              </Button>
            ) : null}
            {canDelete ? (
              <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive" onClick={() => void remove()} disabled={busy}>
                <Trash2 className="h-4 w-4" />
                Fshij
              </Button>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2">
            {canReject && !mode ? (
              <Button variant="outline" size="sm" onClick={() => setMode("reject")} disabled={busy}>
                <Undo2 className="h-4 w-4" />
                Kthe mbrapa
              </Button>
            ) : null}
            {canTest && !mode ? (
              <Button size="sm" onClick={() => setMode("test")} disabled={busy}>
                {kind === "PROMPT" ? <FlaskConical className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
                {t(" E testova ")}</Button>
            ) : null}
            {canApprove ? (
              <Button size="sm" className="bg-emerald-600 hover:bg-emerald-700" disabled={busy} onClick={() => void act("approve", undefined, t("Prompti u ruajt në Prompt Library"))}>
                <ShieldCheck className="h-4 w-4" />
                Aprovo në librari
              </Button>
            ) : null}
          </div>
        </DialogFooter>
        {prompt.status === "PENDING_TEST" && isAuthor ? (
          <p className="text-right text-xs text-muted-foreground">
            {prompt.tester?.full_name ? (t("Pret testimin nga ") + (prompt.tester.full_name) + ".") : t("Testimin duhet ta konfirmojë një koleg tjetër.")}
          </p>
        ) : null}
        {prompt.status === "PENDING_TEST" && !isAuthor && !isTester ? (
          <p className="text-right text-xs text-muted-foreground">{t("Testimin e konfirmon vetëm ")}{prompt.tester?.full_name}.</p>
        ) : null}
        {prompt.status === "PENDING_APPROVAL" && !canApprove ? (
          <p className="text-right text-xs text-muted-foreground">
            {isManager ? t("Aprovimin duhet ta bëjë një menaxher tjetër nga autori dhe testuesi.") : "Pret aprovimin e një menaxheri."}
          </p>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
