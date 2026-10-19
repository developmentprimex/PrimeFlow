"use client"

import * as React from "react"
import { createPortal } from "react-dom"
import { ChevronDown, Minus, Plus, RefreshCw, Save, Send, Settings } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useAuth } from "@/lib/auth"
import { useMarkerComments } from "@/components/marker-comments-context"
import { reportTaskUsers, reportSummaryUser, reportUserOptions, isReportSummaryTask, collapseEmptyReportTaskRows } from "@/lib/one-h-report-users"
import { applyTaskStrikeBadges, taskHasStrikes, reportStrikeTotal, type OneHStrikeSummary } from "@/lib/one-h-strikes"

type Recipients = { to: string[]; cc: string[]; bcc: string[] }
type SettingsState = {
  is_active: boolean
  send_time: string
  timezone: string
  weekdays: number[]
  recipients: Recipients
  last_run_date?: string | null
}
type Delivery = {
  id: string
  delivery_date: string
  target_date: string
  subject: string
  recipients: Recipients
  status: string
  sent_at: string | null
  last_error?: string | null
}
type Preview = {
  one_h_strikes?: OneHStrikeSummary
  subject: string
  target_date: string
  html: string
  snapshot_id: string
  report_date: string
  generated_at: string | null
  generated_by: string | null
  is_frozen?: boolean
  frozen_at?: string
  source_captured_at?: string
}
type FrozenHistory = { report_date: string; frozen_at: string; source_captured_at: string }
type TaskMarker = "EXCLAMATION" | "QUESTION" | "KA" | "GENT" | "FLAG" | "F" | "BZ1N1" | "M2" | "M3" | "M2_M3" | "MONITOR" | "CLOSE" | "CLIENT_URGENT" | "SHARE"
type TaskMarkerSelection = TaskMarker | "none"
type TaskDueDateFilter = "all" | "today" | "deadline" | "starts_today"

const taskMarkerOptions: Array<{ value: TaskMarker; label: string }> = [
  { value: "QUESTION", label: "?" },
  { value: "EXCLAMATION", label: "!" },
  { value: "CLIENT_URGENT", label: "!!!" },
  { value: "SHARE", label: "SHARE" },
  { value: "MONITOR", label: "👁" },
  { value: "CLOSE", label: "X" },
  { value: "M2", label: "M2" },
  { value: "M3", label: "M3" },
  { value: "M2_M3", label: "M2/3" },
  { value: "GENT", label: "GENT" },
  { value: "KA", label: "KA" },
  { value: "FLAG", label: "GA" },
  { value: "F", label: "F" },
  { value: "BZ1N1", label: "BZ1N1" },
]

function MarkerFilterControl({
  selected,
  onChange,
}: {
  selected: ReadonlySet<TaskMarkerSelection>
  onChange: (next: Set<TaskMarkerSelection>) => void
}) {
  const detailsRef = React.useRef<HTMLDetailsElement | null>(null)
  const allSymbolsSelected = taskMarkerOptions.every(({ value }) => selected.has(value))
  const selectedLabels = [
    ...(selected.has("none") ? ["No symbol"] : []),
    ...taskMarkerOptions.filter(({ value }) => selected.has(value)).map(({ label }) => label),
  ]
  const label = selected.size === 0 || (allSymbolsSelected && selected.has("none")) ? "All"
    : allSymbolsSelected ? "All with symbols"
    : selectedLabels.length <= 2 ? selectedLabels.join(", ")
    : `${selectedLabels.slice(0, 2).join(", ")} +${selectedLabels.length - 2}`

  const update = (next: Set<TaskMarkerSelection>) => {
    onChange(next.has("none") && taskMarkerOptions.every(({ value }) => next.has(value)) ? new Set() : next)
  }

  const toggle = (value: TaskMarkerSelection) => {
    const next = new Set(selected)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    update(next)
  }

  const toggleAllSymbols = () => {
    const next = new Set(selected)
    for (const { value } of taskMarkerOptions) {
      if (allSymbolsSelected) next.delete(value)
      else next.add(value)
    }
    update(next)
  }

  const optionStyle: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 8, padding: "6px 8px", cursor: "pointer",
  }

  return (
    <details
      ref={detailsRef}
      data-symbol-filter-control="true"
      className="relative rounded-md border border-blue-300 bg-blue-50 text-sm text-[#0F2A5F]"
      style={{ position: "relative", border: "1px solid #93C5FD", borderRadius: 6, background: "#EFF6FF", color: "#0F2A5F", fontSize: 14 }}
    >
      <summary
        className="flex h-8 min-w-44 cursor-pointer list-none items-center gap-2 px-3 [&::-webkit-details-marker]:hidden"
        aria-label="Filter tasks by symbol"
        style={{ display: "flex", height: 32, minWidth: 176, alignItems: "center", gap: 8, padding: "0 12px", cursor: "pointer", listStyle: "none" }}
      >
        <span>Symbol</span>
        <strong className="min-w-0 flex-1 truncate" style={{ minWidth: 0, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</strong>
        <ChevronDown className="h-4 w-4 shrink-0" aria-hidden="true" style={{ width: 16, height: 16, flexShrink: 0 }} />
      </summary>
      <div
        className="absolute right-0 top-full z-[100] mt-1 max-h-80 w-56 overflow-y-auto rounded-md border border-blue-200 bg-white p-1 shadow-lg"
        role="group"
        aria-label="Symbols"
        style={{ position: "absolute", right: 0, top: "100%", zIndex: 100, marginTop: 4, maxHeight: 320, width: 224, overflowY: "auto", border: "1px solid #BFDBFE", borderRadius: 6, background: "white", padding: 4, boxShadow: "0 8px 24px rgba(15, 23, 42, .15)" }}
      >
        <button type="button" className="w-full rounded px-2 py-1.5 text-left hover:bg-blue-50" style={{ display: "block", width: "100%", border: 0, background: "transparent", padding: "6px 8px", textAlign: "left", color: "inherit", cursor: "pointer" }} onClick={() => onChange(new Set())}>All</button>
        <label className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-blue-50" style={optionStyle}>
          <input type="checkbox" checked={allSymbolsSelected} onChange={toggleAllSymbols} />
          <span>All with symbols</span>
        </label>
        <label className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-blue-50" style={optionStyle}>
          <input type="checkbox" checked={selected.has("none")} onChange={() => toggle("none")} />
          <span>No symbol</span>
        </label>
        <div className="my-1 border-t border-blue-100" style={{ margin: "4px 0", borderTop: "1px solid #DBEAFE" }} />
        {taskMarkerOptions.map(({ value, label: optionLabel }) => (
          <label key={value} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-blue-50" style={optionStyle}>
            <input type="checkbox" checked={selected.has(value)} onChange={() => toggle(value)} />
            <span className="font-semibold" style={{ fontWeight: 600 }}>{optionLabel}</span>
          </label>
        ))}
        <div className="sticky bottom-0 border-t border-blue-100 bg-white p-1 text-right" style={{ position: "sticky", bottom: 0, borderTop: "1px solid #DBEAFE", background: "white", padding: 4, textAlign: "right" }}>
          <button type="button" className="rounded px-2 py-1 font-semibold hover:bg-blue-50" style={{ border: 0, background: "transparent", padding: "4px 8px", fontWeight: 600, color: "inherit", cursor: "pointer" }} onClick={() => { if (detailsRef.current) detailsRef.current.open = false }}>Done</button>
        </div>
      </div>
    </details>
  )
}

const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

function secondSendTime(first: string) {
  const [hours, minutes] = first.split(":").map(Number)
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return "—"
  const total = (hours * 60 + minutes + 20) % (24 * 60)
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`
}

function toRecipientText(values?: string[]) {
  return (values || []).join(", ")
}

function parseRecipients(value: string) {
  const seen = new Set<string>()
  return value.split(/[,;\n]/).map((email) => email.trim()).filter((email) => {
    const key = email.toLowerCase()
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function formatDateTime(value?: string | null) {
  return value ? new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "-"
}

export function PrintReportPage({
  today = false,
  embedded = false,
  modeControl,
}: {
  today?: boolean
  embedded?: boolean
  modeControl?: React.ReactNode
}) {
  const API = today ? "/today-print-report" : "/tomorrow-print-report"
  const reportName = today ? "1H SHTYPI SOT (Shiko simbolet)" : "1H SHTYPI NESER (Shiko simbolet)"
  const { apiFetch, user, loading: authLoading } = useAuth()
  const markerComments = useMarkerComments()
  const markerCommentsRef = React.useRef(markerComments)
  React.useEffect(() => { markerCommentsRef.current = markerComments }, [markerComments])
  const [settings, setSettings] = React.useState<SettingsState | null>(null)
  const [recipientInputs, setRecipientInputs] = React.useState({ to: "", cc: "", bcc: "" })
  const [preview, setPreview] = React.useState<Preview | null>(null)
  const [automaticEmailExpanded, setAutomaticEmailExpanded] = React.useState(false)
  const [reportIntroExpanded, setReportIntroExpanded] = React.useState(false)
  const [markerFilters, setMarkerFilters] = React.useState<Set<TaskMarkerSelection>>(() => new Set())
  const [dueDateFilter, setDueDateFilter] = React.useState<TaskDueDateFilter>("all")
  const [strikesOnly, setStrikesOnly] = React.useState(false)
  const [userFilter, setUserFilter] = React.useState("")
  const [summaryOnly, setSummaryOnly] = React.useState(false)
  const [reportUsers, setReportUsers] = React.useState<string[]>([])
  const [history, setHistory] = React.useState<Delivery[]>([])
  const [loading, setLoading] = React.useState(true)
  const [snapshotLoading, setSnapshotLoading] = React.useState(true)
  const [snapshotError, setSnapshotError] = React.useState("")
  const [frozenHistory, setFrozenHistory] = React.useState<FrozenHistory[]>([])
  const [selectedReportDate, setSelectedReportDate] = React.useState("")
  const [saving, setSaving] = React.useState(false)
  const [sending, setSending] = React.useState(false)
  const [generatingAction, setGeneratingAction] = React.useState<"generate" | null>(null)
  const previewFrameRef = React.useRef<HTMLIFrameElement | null>(null)
  const syncPreviewCommentAttention = React.useCallback(() => {
    const frameDocument = previewFrameRef.current?.contentDocument
    if (!frameDocument) return
    frameDocument.querySelectorAll<HTMLElement>('[data-task-marker-comment="true"]').forEach((block) => {
      const cell = block.closest<HTMLElement>("td[data-task-id]")
      const taskId = cell?.dataset.taskId
      const item = taskId ? markerComments?.byTask.get(taskId) : undefined
      const unread = Boolean(item && !item.read_at && item.comment.trim() === block.title.trim())
      block.querySelector('[data-marker-comment-new="true"]')?.remove()
      if (unread) {
        const label = frameDocument.createElement("strong")
        label.dataset.markerCommentNew = "true"
        label.textContent = "E RE · "
        label.style.color = "#FEF08A"
        block.prepend(label)
      }
      block.style.boxShadow = unread ? "0 0 0 2px #93C5FD" : "none"
      block.style.cursor = "pointer"
      block.setAttribute("role", "button")
      block.tabIndex = 0
      block.setAttribute("aria-label", `${unread ? "Koment i palexuar. " : ""}${block.title}`)
      block.onclick = (event) => { event.preventDefault(); event.stopPropagation(); markerComments?.openTask(taskId, block.title) }
      block.onkeydown = (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); event.stopPropagation(); markerComments?.openTask(taskId, block.title) } }
    })
  }, [markerComments])
  React.useEffect(() => { syncPreviewCommentAttention() }, [syncPreviewCommentAttention])
  const [previewFilterContainer, setPreviewFilterContainer] = React.useState<HTMLElement | null>(null)
  const markerModalCleanupRef = React.useRef<(() => void) | null>(null)
  const observedTodayDateRef = React.useRef("")
  const canManage = user?.role === "ADMIN" || user?.role === "MANAGER"

  React.useEffect(() => {
    if (!preview) return
    const documents = [window.document, previewFrameRef.current?.contentDocument].filter(
      (document): document is Document => Boolean(document)
    )
    const closeOutside = (event: PointerEvent) => {
      const target = event.target as Node | null
      if (!target) return
      for (const document of documents) {
        document.querySelectorAll<HTMLDetailsElement>('details[data-symbol-filter-control="true"]').forEach((details) => {
          if (!details.contains(target)) details.open = false
        })
      }
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return
      for (const document of documents) {
        document.querySelectorAll<HTMLDetailsElement>('details[data-symbol-filter-control="true"]').forEach((details) => {
          details.open = false
        })
      }
    }
    documents.forEach((document) => {
      document.addEventListener("pointerdown", closeOutside)
      document.addEventListener("keydown", closeOnEscape)
    })
    return () => documents.forEach((document) => {
      document.removeEventListener("pointerdown", closeOutside)
      document.removeEventListener("keydown", closeOnEscape)
    })
  }, [preview, previewFilterContainer])

  const applyReportIntroVisibility = React.useCallback(() => {
    const intro = previewFrameRef.current?.contentDocument?.querySelector<HTMLElement>('[data-report-intro="true"]')
    if (intro) intro.hidden = !reportIntroExpanded
  }, [reportIntroExpanded])

  React.useEffect(() => {
    applyReportIntroVisibility()
  }, [applyReportIntroVisibility, preview])

  React.useEffect(() => {
    const frame = previewFrameRef.current
    if (!preview || !frame) return

    let resizeObserver: ResizeObserver | undefined
    let animationFrame = 0
    const resizePreview = () => {
      window.cancelAnimationFrame(animationFrame)
      animationFrame = window.requestAnimationFrame(() => {
        const document = frame.contentDocument
        if (!document?.body) return
        // Measure the content without collapsing the frame and shifting the page.
        const height = Math.ceil(document.body.getBoundingClientRect().height)
        frame.style.height = `${height + 2}px`
      })
    }
    const observePreview = () => {
      resizeObserver?.disconnect()
      const body = frame.contentDocument?.body
      if (!body) return
      // Include the report's outer margins in the observed content height.
      body.style.display = "flow-root"
      resizeObserver = new ResizeObserver(resizePreview)
      resizeObserver.observe(body)
      resizePreview()
    }

    frame.addEventListener("load", observePreview)
    if (frame.contentDocument?.readyState === "complete") observePreview()
    return () => {
      frame.removeEventListener("load", observePreview)
      resizeObserver?.disconnect()
      window.cancelAnimationFrame(animationFrame)
    }
  }, [preview])

  const applySettings = React.useCallback((next: SettingsState) => {
    setSettings(next)
    setRecipientInputs({
      to: toRecipientText(next.recipients.to),
      cc: toRecipientText(next.recipients.cc),
      bcc: toRecipientText(next.recipients.bcc),
    })
  }, [])

  const load = React.useCallback(async () => {
    if (embedded) {
      setLoading(false)
      return
    }
    if (!canManage) {
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const [settingsResponse, historyResponse] = await Promise.all([apiFetch(`${API}/settings`), apiFetch(`${API}/history`)])
      if (!settingsResponse?.ok || !historyResponse?.ok) throw new Error(`Could not load ${reportName} settings`)
      applySettings(await settingsResponse.json())
      setHistory(await historyResponse.json())
    } catch (error) {
      toast.error(`Could not load ${reportName}`, { description: String(error) })
    } finally {
      setLoading(false)
    }
  }, [API, apiFetch, applySettings, canManage, embedded, reportName])

  React.useEffect(() => { void load() }, [load])

  const loadSnapshot = React.useCallback(async () => {
    if (authLoading || !user?.id) return
    setSnapshotLoading(true)
    setSnapshotError("")
    try {
      const response = selectedReportDate && today
        ? await apiFetch(`${API}/snapshot?report_date=${selectedReportDate}`, { cache: "no-store" })
        : await apiFetch(`${API}/snapshot`, { cache: "no-store" })
      if (response.status === 404) {
        setPreview(null)
        return
      }
      if (!response.ok) {
        const error = await response.json().catch(() => null)
        throw new Error(error?.detail || "Saved report could not be loaded")
      }
      setPreview(await response.json())
    } catch (error) {
      setPreview(null)
      setSnapshotError(error instanceof Error ? error.message : String(error))
    } finally {
      setSnapshotLoading(false)
    }
  }, [API, apiFetch, authLoading, selectedReportDate, today, user?.id])

  React.useEffect(() => { void loadSnapshot() }, [loadSnapshot])

  React.useEffect(() => {
    if (!today || !preview || preview.is_frozen || selectedReportDate || !user?.id) return
    let cancelled = false
    let pending = false
    const reportDate = preview.report_date
    const refreshCounts = async () => {
      if (pending || document.visibilityState !== "visible") return
      pending = true
      try {
        const response = await apiFetch(`${API}/snapshot`, { cache: "no-store" })
        if (!response.ok || cancelled) return
        const latest = await response.json() as Preview
        if (latest.is_frozen || latest.report_date !== reportDate) { await loadSnapshot(); return }
        // Keep the generated layout, filters, and iframe scroll position.
        setPreview((current) => current?.report_date === reportDate
          ? { ...current, one_h_strikes: latest.one_h_strikes } : current)
      } catch { /* Retry after a temporary network failure. */ }
      finally { pending = false }
    }
    const timer = window.setInterval(() => { void refreshCounts() }, 30000)
    const onVisibility = () => { void refreshCounts() }
    document.addEventListener("visibilitychange", onVisibility)
    return () => {
      cancelled = true
      window.clearInterval(timer)
      document.removeEventListener("visibilitychange", onVisibility)
    }
  }, [API, apiFetch, today, preview?.snapshot_id, preview?.report_date, preview?.is_frozen, selectedReportDate, user?.id, loadSnapshot])

  React.useEffect(() => {
    const document = previewFrameRef.current?.contentDocument
    if (today && document) applyTaskStrikeBadges(document, preview?.one_h_strikes)
  }, [today, preview?.one_h_strikes])

  React.useEffect(() => {
    if (!today || authLoading || !user?.id) return
    let cancelled = false
    const loadFrozenHistory = async () => {
      try {
        const response = await apiFetch(`${API}/frozen-history`, { cache: "no-store" })
        if (response.ok && !cancelled) setFrozenHistory(await response.json())
      } catch { /* Keep the report usable if history is temporarily unavailable. */ }
    }
    void loadFrozenHistory()
    return () => { cancelled = true }
  }, [API, apiFetch, authLoading, today, user?.id, preview?.frozen_at])

  React.useEffect(() => {
    if (!today || selectedReportDate || authLoading || !user?.id) return
    let cancelled = false
    let pending = false
    const checkBoundary = async () => {
      if (pending) return
      pending = true
      try {
        const response = await apiFetch(`${API}/freeze-status`, { cache: "no-store" })
        if (!response.ok || cancelled) return
        const state = await response.json() as { report_date: string; is_frozen: boolean; freeze_ready: boolean }
        const dayChanged = Boolean(observedTodayDateRef.current && observedTodayDateRef.current !== state.report_date)
        observedTodayDateRef.current = state.report_date
        if (dayChanged || (preview && preview.report_date !== state.report_date) || (state.is_frozen && !preview?.is_frozen)) {
          // Remove yesterday/live data immediately, including its marker editors.
          setPreview(null)
          if (!state.is_frozen || state.freeze_ready) await loadSnapshot()
          else setSnapshotError("Raporti po ngrihet në 16:00. Kopja e ngrirë do të hapet sapo të jetë gati.")
        }
      } catch { /* Retry on the next tick after temporary network failures. */ }
      finally { pending = false }
    }
    const timer = window.setInterval(() => { void checkBoundary() }, 5000)
    const onVisibility = () => { if (document.visibilityState === "visible") void checkBoundary() }
    document.addEventListener("visibilitychange", onVisibility)
    void checkBoundary()
    return () => {
      cancelled = true
      window.clearInterval(timer)
      document.removeEventListener("visibilitychange", onVisibility)
    }
  }, [API, apiFetch, authLoading, loadSnapshot, preview, selectedReportDate, today, user?.id])

  React.useEffect(() => () => markerModalCleanupRef.current?.(), [])

  const updateRecipients = (kind: keyof Recipients, value: string) => {
    setRecipientInputs((current) => ({ ...current, [kind]: value }))
    setSettings((current) => current ? { ...current, recipients: { ...current.recipients, [kind]: parseRecipients(value) } } : current)
  }

  const toggleDay = (day: number) => {
    setSettings((current) => {
      if (!current) return current
      const weekdays = current.weekdays.includes(day)
        ? current.weekdays.filter((value) => value !== day)
        : [...current.weekdays, day].sort()
      return { ...current, weekdays }
    })
  }

  const saveSettings = async () => {
    if (!settings) return
    setSaving(true)
    try {
      const response = await apiFetch(`${API}/settings`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings),
      })
      if (!response?.ok) throw new Error(await response?.text())
      applySettings(await response.json())
      toast.success(`${reportName} settings saved`)
    } catch (error) {
      toast.error("Settings save failed", { description: String(error) })
    } finally {
      setSaving(false)
    }
  }

  const generateReport = async () => {
    if (today && (preview?.is_frozen || selectedReportDate)) return
    if (preview && !window.confirm("Regenerate this saved report with the latest data?")) return
    setGeneratingAction("generate")
    try {
      const response = await apiFetch(`${API}/generate`, { method: "POST" })
      if (!response?.ok) throw new Error(await response?.text())
      setPreview(await response.json())
      toast.success(preview ? `${reportName} regenerated` : `${reportName} generated`)
    } catch (error) {
      toast.error("Report could not be generated", { description: String(error) })
    } finally {
      setGeneratingAction(null)
    }
  }

  const applyPreviewMarkerFilter = React.useCallback(() => {
    const document = previewFrameRef.current?.contentDocument
    if (!document) return
    const reportDateLabel = preview?.target_date
      ? preview.target_date.slice(0, 10).split("-").reverse().join(".")
      : ""
    document.querySelectorAll<HTMLTableRowElement>('tr[data-task-card-row="content"]').forEach((contentRow) => {
      const dateRow = contentRow.nextElementSibling as HTMLTableRowElement | null
      const dateCells = dateRow?.matches('tr[data-task-card-row="dates"]')
        ? Array.from(dateRow.cells).filter((cell): cell is HTMLTableCellElement => cell.tagName === "TD")
        : []
      const taskCells = Array.from(contentRow.cells).filter(
        (cell): cell is HTMLTableCellElement => cell.tagName === "TD"
      )

      taskCells.forEach((cell, index) => {
        const marker = cell.dataset.taskMarker || ""
        const isTaskCard = Boolean(cell.dataset.taskId)
        const matchesMarker = markerFilters.size === 0 || (
          isTaskCard && (marker ? markerFilters.has(marker as TaskMarker) : markerFilters.has("none"))
        )
        const legacyRedDeadline = cell.getAttribute("bgcolor")?.toUpperCase() === "#DC2626"
        const matchesDeadline = cell.dataset.taskDeadlineImportant === "true" || legacyRedDeadline
        const dueToday = Boolean(dateCells[index]?.querySelector('[data-task-badge="due-date"][data-due-today="true"]'))
        const startDateLabel = dateCells[index]?.querySelector('[data-task-badge="start-date"]')?.textContent?.trim()
        const startsToday = cell.dataset.taskStartsToday === "true" || Boolean(reportDateLabel && startDateLabel === reportDateLabel)
        const matchesDueDate = dueDateFilter === "all" || (isTaskCard && (
          dueDateFilter === "today" ? dueToday :
          dueDateFilter === "deadline" ? matchesDeadline : startsToday
        ))
        const matchesUser = !userFilter || reportTaskUsers(cell).includes(userFilter)
        const matchesStrikes = !today || !strikesOnly || taskHasStrikes(preview?.one_h_strikes, cell.dataset.taskId || "")
        const matches = matchesMarker && matchesDueDate && matchesUser && matchesStrikes && (!summaryOnly || isReportSummaryTask(cell))
        cell.style.display = matches ? "" : "none"
        cell.dataset.taskMarkerFilterHidden = matches ? "false" : "true"
        if (dateCells[index]) dateCells[index].style.display = matches ? "" : "none"

        // Clear the old content-only filtering style from previews generated
        // before full-card filtering was introduced.
        const content = cell.querySelector<HTMLElement>("[data-task-marker-filter-content]")
        if (content) content.style.visibility = ""
      })
    })
    collapseEmptyReportTaskRows(document, Boolean(userFilter || summaryOnly || markerFilters.size || dueDateFilter !== "all" || (today && strikesOnly)))
    document.querySelectorAll<HTMLElement>('[data-ga-task-summary="true"] td').forEach((cell) => {
      cell.style.display = ""
      const active = summaryOnly && reportSummaryUser(cell) === userFilter
      cell.setAttribute("aria-pressed", String(active))
      cell.title = active ? "Show all tasks" : `Show ${reportSummaryUser(cell)}'s tasks in this summary`
      cell.style.outline = active ? "2px solid #2563EB" : ""
      cell.style.outlineOffset = "-2px"
    })
    document.querySelectorAll<HTMLElement>('[data-ga-task-summary="true"]').forEach((summary) => {
      summary.style.display = ""
    })
  }, [dueDateFilter, markerFilters, userFilter, summaryOnly, preview?.target_date, preview?.one_h_strikes, today, strikesOnly])

  const setupPreviewMarkerControls = React.useCallback(() => {
    const document = previewFrameRef.current?.contentDocument
    if (!document || (today && (preview?.is_frozen || selectedReportDate))) return

    const openMarkerCommentModal = (initialValue: string) => new Promise<string | null>((resolve) => {
      markerModalCleanupRef.current?.()
      // The report lives in an auto-height iframe. A fixed modal inside that
      // iframe is centered against the entire report, often several screens
      // away. Mount it in the host document so it always stays in the user's
      // current viewport and cannot affect the iframe resize observer.
      const hostDocument = window.document
      const overlay = hostDocument.createElement("div")
      overlay.style.cssText = "position:fixed;inset:0;z-index:2147483647;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(15,23,42,.18);font-family:Arial,sans-serif"
      const panel = hostDocument.createElement("div")
      panel.style.cssText = "box-sizing:border-box;width:min(460px,calc(100vw - 40px));max-height:calc(100vh - 40px);overflow:auto;border:1px solid #94A3B8;border-radius:14px;background:#FFF;padding:20px;box-shadow:0 18px 50px rgba(15,23,42,.28);color:#0F172A"
      const title = hostDocument.createElement("div")
      title.textContent = "Symbol comment"
      title.style.cssText = "margin-bottom:5px;font-size:18px;font-weight:800"
      const description = hostDocument.createElement("div")
      description.textContent = "Add an optional comment for this symbol."
      description.style.cssText = "margin-bottom:14px;color:#64748B;font-size:13px"
      const textarea = hostDocument.createElement("textarea")
      textarea.value = initialValue
      textarea.maxLength = 1000
      textarea.placeholder = "Write an optional comment..."
      textarea.style.cssText = "box-sizing:border-box;width:100%;min-height:110px;resize:vertical;border:1px solid #CBD5E1;border-radius:8px;padding:10px 12px;font:14px/1.45 Arial,sans-serif;color:#0F172A;outline:none"
      const actions = hostDocument.createElement("div")
      actions.style.cssText = "display:flex;justify-content:flex-end;gap:8px;margin-top:16px"
      const makeButton = (label: string, primary = false) => {
        const button = hostDocument.createElement("button")
        button.type = "button"
        button.textContent = label
        button.style.cssText = `height:36px;border-radius:8px;padding:0 16px;border:1px solid ${primary ? "#2563EB" : "#CBD5E1"};background:${primary ? "#2563EB" : "#FFF"};color:${primary ? "#FFF" : "#334155"};font-size:13px;font-weight:700;cursor:pointer`
        return button
      }
      const copyButton = makeButton("Copy")
      copyButton.style.display = initialValue ? "inline-block" : "none"
      const cancelButton = makeButton("Cancel")
      const saveButton = makeButton("Save", true)
      const previousBodyOverflow = hostDocument.body.style.overflow
      let finished = false
      const handleKeyDown = (event: KeyboardEvent) => {
        if (event.key === "Escape") finish(null)
      }
      const finish = (value: string | null) => {
        if (finished) return
        finished = true
        hostDocument.removeEventListener("keydown", handleKeyDown)
        hostDocument.body.style.overflow = previousBodyOverflow
        overlay.remove()
        markerModalCleanupRef.current = null
        resolve(value)
      }
      copyButton.addEventListener("click", () => void window.navigator.clipboard.writeText(textarea.value))
      cancelButton.addEventListener("click", () => finish(null))
      saveButton.addEventListener("click", () => finish(textarea.value))
      overlay.addEventListener("click", (event) => { if (event.target === overlay) finish(null) })
      panel.addEventListener("click", (event) => event.stopPropagation())
      actions.append(copyButton, cancelButton, saveButton)
      panel.append(title, description, textarea, actions)
      overlay.appendChild(panel)
      hostDocument.body.appendChild(overlay)
      hostDocument.body.style.overflow = "hidden"
      hostDocument.addEventListener("keydown", handleKeyDown)
      markerModalCleanupRef.current = () => finish(null)
      window.requestAnimationFrame(() => textarea.focus())
    })

    document.querySelectorAll<HTMLElement>("td[data-task-id]").forEach((cell) => {
      if (cell.querySelector("select[data-task-marker-control]")) return
      const taskId = cell.dataset.taskId
      if (!taskId) return

      const content = document.createElement("div")
      content.dataset.taskMarkerFilterContent = "true"
      content.style.display = "contents"
      while (cell.firstChild) content.appendChild(cell.firstChild)
      cell.appendChild(content)

      const existingBadge = cell.querySelector<HTMLElement>('[data-task-badge="one-h-marker"]')
      existingBadge?.remove()

      const markerControl = document.createElement("span")
      markerControl.dataset.taskMarkerControlWrapper = "true"
      markerControl.style.cssText = "position:relative;display:inline-flex;align-items:center;height:22px;float:right;margin:0 0 3px 4px;vertical-align:top"

      const select = document.createElement("select")
      // Render the visible label independently of the native select's baseline.
      // The select still handles focus, keyboard input, and the option menu.
      const selectedSymbol = document.createElement("span")
      selectedSymbol.setAttribute("aria-hidden", "true")
      selectedSymbol.style.cssText = "position:absolute;left:3px;right:14px;top:0;bottom:2px;display:flex;align-items:center;justify-content:center;pointer-events:none;white-space:nowrap;font:900 16px/1 Arial,sans-serif"
      const resizeMarkerSelect = (marker: string, byGa: boolean) => {
        const label = taskMarkerOptions.find((option) => option.value === marker)?.label || "—"
        const visibleLength = label.length + (byGa && marker ? 2 : 0)
        select.style.width = visibleLength <= 1 ? "46px" : visibleLength <= 2 ? "52px" : "64px"
        selectedSymbol.textContent = byGa && marker ? `(${label})` : label
        selectedSymbol.style.color = marker ? "#DC2626" : "#0F2A5F"
      }
      select.dataset.taskMarkerControl = "true"
      select.setAttribute("aria-label", "Task marker")
      select.title = cell.dataset.taskMarkerComment || "Task marker"
      select.style.cssText = [
        "display:inline-block",
        "box-sizing:border-box",
        "appearance:none",
        "height:22px",
        "min-width:46px",
        "max-width:64px",
        "margin:0",
        "padding:0 14px 0 3px",
        "border:1px solid #93C5FD",
        "border-radius:999px",
        "background:#EFF6FF",
        "background-image:url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12'%3E%3Cpath d='m3 4.5 3 3 3-3' fill='none' stroke='%230F2A5F' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E\")",
        "background-repeat:no-repeat",
        "background-position:right 3px center",
        "background-size:10px 10px",
        "color:transparent",
        "font:900 16px/18px Arial,sans-serif",
        "text-align:center",
        "text-align-last:center",
        "vertical-align:middle",
        "cursor:pointer",
      ].join(";")
      // Keep only the native control's interaction surface; the visible frame
      // and symbol use flex alignment so Windows cannot shift the text down.
      selectedSymbol.style.cssText = select.style.cssText + ";position:absolute;inset:0;width:100%;min-width:0;max-width:none;display:flex;align-items:center;justify-content:center;padding:0 14px 2px 3px;pointer-events:none;white-space:nowrap;font:900 16px/1 Arial,sans-serif"
      select.style.opacity = "0"
      select.addEventListener("focus", () => { markerControl.style.outline = "2px solid #2563EB"; markerControl.style.outlineOffset = "2px" })
      select.addEventListener("blur", () => { markerControl.style.outline = ""; markerControl.style.outlineOffset = "" })

      const emptyOption = document.createElement("option")
      emptyOption.value = ""
      emptyOption.textContent = "—"
      emptyOption.style.cssText = "color:#0F2A5F;font-size:16px;font-weight:900"
      select.appendChild(emptyOption)
      taskMarkerOptions.forEach((option) => {
        const element = document.createElement("option")
        element.value = option.value
        element.textContent = cell.dataset.taskMarkerByGa === "true" && option.value === cell.dataset.taskMarker
          ? `(${option.label})`
          : option.label
        element.style.cssText = "color:#DC2626;font-size:16px;font-weight:900"
        select.appendChild(element)
      })
      select.value = cell.dataset.taskMarker || ""
      resizeMarkerSelect(select.value, cell.dataset.taskMarkerByGa === "true")

      const commentBlock = cell.querySelector<HTMLElement>('[data-task-marker-comment="true"]')
      const updateCommentBlock = (comment: string) => {
        if (!commentBlock) return
        commentBlock.replaceChildren()
        if (comment) {
          const label = document.createElement("strong")
          label.textContent = "COM:"
          commentBlock.append(label, document.createTextNode(` ${comment}`))
        }
        commentBlock.title = comment
        commentBlock.style.display = comment ? "block" : "none"
      }

      const commentButton = document.createElement("button")
      commentButton.type = "button"
      commentButton.dataset.taskMarkerCommentControl = "true"
      const commentIcon = document.createElementNS("http://www.w3.org/2000/svg", "svg")
      commentIcon.setAttribute("viewBox", "0 0 24 24")
      commentIcon.setAttribute("width", "12")
      commentIcon.setAttribute("height", "12")
      commentIcon.setAttribute("fill", "none")
      commentIcon.setAttribute("stroke", "currentColor")
      commentIcon.setAttribute("stroke-width", "2.5")
      commentIcon.setAttribute("stroke-linecap", "round")
      commentIcon.setAttribute("stroke-linejoin", "round")
      commentIcon.setAttribute("aria-hidden", "true")
      const commentIconPath = document.createElementNS("http://www.w3.org/2000/svg", "path")
      commentIconPath.setAttribute("d", "M7.9 20A9 9 0 1 0 4 16.1L2 22Z")
      commentIcon.appendChild(commentIconPath)
      commentButton.appendChild(commentIcon)
      commentButton.style.cssText = [
        "position:absolute",
        "right:-4px",
        "top:-5px",
        "z-index:2",
        "display:flex",
        "height:14px",
        "width:14px",
        "align-items:center",
        "justify-content:center",
        "padding:0",
        "border:1px solid #93C5FD",
        "border-radius:999px",
        "background:#FFF",
        "font:9px/1 Arial,sans-serif",
        "cursor:pointer",
        "box-shadow:0 1px 2px rgba(15,23,42,.16)",
      ].join(";")
      const updateCommentButton = (marker: string, comment: string) => {
        const hasComment = Boolean(comment.trim())
        commentButton.style.display = marker ? "flex" : "none"
        commentButton.style.right = hasComment ? "-8px" : "-4px"
        commentButton.style.top = hasComment ? "-8px" : "-5px"
        commentButton.style.width = hasComment ? "24px" : "16px"
        commentButton.style.height = hasComment ? "24px" : "16px"
        commentButton.style.backgroundColor = hasComment ? "#0055FF" : "#FFF"
        commentButton.style.borderColor = hasComment ? "#172554" : "#93C5FD"
        commentButton.style.borderWidth = hasComment ? "2px" : "1px"
        commentButton.style.color = hasComment ? "#FFF" : "#60A5FA"
        commentButton.style.boxShadow = hasComment ? "0 0 0 2px #FFF, 0 3px 6px rgba(15,23,42,.3)" : "0 1px 2px rgba(15,23,42,.16)"
        commentIcon.setAttribute("width", hasComment ? "16" : "12")
        commentIcon.setAttribute("height", hasComment ? "16" : "12")
        commentIcon.setAttribute("stroke-width", hasComment ? "3" : "2.5")
        commentButton.title = hasComment ? comment : "Add symbol comment"
        commentButton.setAttribute("aria-label", hasComment ? "View symbol comment" : "Add symbol comment")
      }
      updateCommentButton(select.value, cell.dataset.taskMarkerComment || "")

      select.addEventListener("change", async () => {
        if (select.disabled) return
        const previousValue = cell.dataset.taskMarker || ""
        const nextValue = select.value
        const previousComment = cell.dataset.taskMarkerComment || ""
        select.disabled = true
        try {
          const nextComment = nextValue
            ? await openMarkerCommentModal(nextValue === previousValue ? previousComment : "")
            : ""
          if (nextValue && nextComment === null) {
            select.value = previousValue
            resizeMarkerSelect(previousValue, cell.dataset.taskMarkerByGa === "true")
            return
          }
          const response = await apiFetch(`/tasks/${taskId}/one-h-marker`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ one_h_marker: nextValue || null, one_h_marker_comment: nextValue ? nextComment?.trim() || null : null }),
          })
          if (!response?.ok) {
            const detail = await response?.json().catch(() => null)
            throw new Error(typeof detail?.detail === "string" ? detail.detail : "Could not update task marker")
          }
          const updated = await response.json() as { one_h_marker_by_ga?: boolean; one_h_marker_comment?: string | null }
          cell.dataset.taskMarker = nextValue
          cell.dataset.taskMarkerByGa = updated.one_h_marker_by_ga ? "true" : "false"
          cell.dataset.taskMarkerComment = updated.one_h_marker_comment || ""
          select.title = updated.one_h_marker_comment || "Task marker"
          resizeMarkerSelect(nextValue, Boolean(updated.one_h_marker_by_ga))
          updateCommentButton(nextValue, updated.one_h_marker_comment || "")
          updateCommentBlock(updated.one_h_marker_comment || "")
          window.dispatchEvent(new Event("primeflow:task-marker-updated"))
          taskMarkerOptions.forEach((option, index) => {
            const element = select.options[index + 1]
            if (element) {
              element.textContent = updated.one_h_marker_by_ga && option.value === nextValue
                ? `(${option.label})`
                : option.label
            }
          })
          applyPreviewMarkerFilter()
          toast.success("Task marker updated")
        } catch (error) {
          select.value = previousValue
          resizeMarkerSelect(previousValue, cell.dataset.taskMarkerByGa === "true")
          toast.error("Task marker update failed", { description: String(error) })
        } finally {
          select.disabled = false
        }
      })

      commentButton.addEventListener("click", async (event) => {
        event.preventDefault()
        event.stopPropagation()
        const marker = cell.dataset.taskMarker || ""
        if (!marker || select.disabled) return
        const value = cell.dataset.taskMarkerComment || ""
        markerCommentsRef.current?.markTaskRead(taskId, value)
        const nextComment = await openMarkerCommentModal(value)
        if (nextComment === null || nextComment.trim() === value.trim()) return
        select.disabled = true
        commentButton.disabled = true
        try {
          const response = await apiFetch(`/tasks/${taskId}/one-h-marker`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ one_h_marker: marker, one_h_marker_comment: nextComment.trim() || null }),
          })
          if (!response?.ok) throw new Error("Could not update symbol comment")
          const updated = await response.json() as { one_h_marker_comment?: string | null }
          const savedComment = updated.one_h_marker_comment || ""
          cell.dataset.taskMarkerComment = savedComment
          select.title = savedComment || "Task marker"
          updateCommentButton(marker, savedComment)
          updateCommentBlock(savedComment)
          window.dispatchEvent(new Event("primeflow:task-marker-updated"))
          toast.success("Symbol comment updated")
        } catch (error) {
          toast.error("Symbol comment update failed", { description: String(error) })
        } finally {
          select.disabled = false
          commentButton.disabled = false
        }
      })

      markerControl.append(select, selectedSymbol, commentButton)
      const periodBadge = cell.querySelector('[data-task-badge="finish-period"]')
      if (periodBadge) periodBadge.insertAdjacentElement("afterend", markerControl)
      else content.prepend(markerControl)
    })
    applyPreviewMarkerFilter()
  }, [apiFetch, applyPreviewMarkerFilter, preview?.is_frozen, selectedReportDate, today])

  React.useEffect(() => {
    applyPreviewMarkerFilter()
  }, [applyPreviewMarkerFilter, preview])

  const setupPreviewFilters = () => {
    const document = previewFrameRef.current?.contentDocument
    if (!document) return
    const users = reportUserOptions(document)
    setReportUsers(users)
    if (userFilter && !users.includes(userFilter)) setUserFilter("")
    document.querySelectorAll<HTMLElement>('[data-ga-task-summary="true"] td').forEach((cell) => {
      const person = reportSummaryUser(cell)
      if (!person) return
      const select = () => {
        const active = cell.getAttribute("aria-pressed") === "true"
        cell.setAttribute("aria-pressed", String(!active))
        setUserFilter(active ? "" : person)
        setSummaryOnly(!active)
        setMarkerFilters(new Set())
        setDueDateFilter("all")
      }
      cell.setAttribute("role", "button")
      cell.tabIndex = 0
      cell.title = `Show ${person}'s tasks in this summary`
      cell.style.cursor = "pointer"
      cell.onclick = select
      cell.onkeydown = (event) => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select() }
      }
    })
    applyPreviewMarkerFilter()
    // Saved reports also need the controls, including tables with no tasks.
    const taskTable = Array.from(document.querySelectorAll("table")).find((table) =>
      Array.from(table.querySelectorAll("thead th")).some((heading) => heading.textContent?.trim() === "TASKS")
    )
    if (!taskTable) {
      setPreviewFilterContainer(null)
      return
    }
    let container = document.querySelector<HTMLElement>("[data-task-filter-toolbar]")
    if (!container) {
      container = document.createElement("div")
      container.dataset.taskFilterToolbar = "true"
      container.style.cssText = "display:flex;flex-wrap:wrap;align-items:center;justify-content:flex-end;gap:8px;margin:8px 0 6px;font-family:Arial,sans-serif"
      taskTable.before(container)
    }
    const summary = document.querySelector<HTMLElement>('[data-ga-task-summary="true"]')
    if (summary) {
      summary.style.margin = "0 auto 0 0"
      container.prepend(summary)
    }
    setPreviewFilterContainer(container)
  }

  const sendNow = async () => {
    setSending(true)
    try {
      const response = await apiFetch(`${API}/send`, { method: "POST" })
      if (!response?.ok) throw new Error(await response?.text())
      toast.success(`${reportName} email sent`)
      await load()
    } catch (error) {
      toast.error("Email could not be sent", { description: String(error) })
    } finally {
      setSending(false)
    }
  }

  if (!authLoading && !user) return <div className="rounded-lg border bg-white p-8">Sign in to access {reportName}.</div>

  const markerFilterControl = () => <MarkerFilterControl selected={markerFilters} onChange={setMarkerFilters} />
  const strikeTotal = today ? reportStrikeTotal(preview?.one_h_strikes) : null
  const strikeTotalControl = strikeTotal ? <span role="status" aria-label="Totali i strikes në intervalin e fundit të përfunduar"
    title="Totali për të gjitha detyrat e raportit, pavarësisht filtrave. Çdo detyrë numërohet vetëm një herë."
    style={{ display: "inline-flex", alignItems: "center", minHeight: 34, padding: "0 10px", border: "1px solid #93C5FD", borderRadius: 6,
      background: "#EFF6FF", color: "#1E40AF", fontSize: 13, fontWeight: 700, whiteSpace: "nowrap" }}>
    {strikeTotal.label}
  </span> : null
  const strikesFilterControl = today ? <button type="button" aria-pressed={strikesOnly}
    aria-label="Vetëm detyrat me strikes > 0"
    onClick={() => setStrikesOnly((selected) => !selected)}
    style={{ minHeight: 34, padding: "0 12px", border: `1px solid ${strikesOnly ? "#2563EB" : "#CBD5E1"}`, borderRadius: 6,
      background: strikesOnly ? "#DBEAFE" : "#F8FAFC", color: strikesOnly ? "#1E40AF" : "#0F172A", fontSize: 13, fontWeight: 700, whiteSpace: "nowrap" }}>
    Vetëm me strikes &gt; 0
  </button> : null
  const userFilterControl = <>
    <label className="flex items-center gap-2 rounded-md border border-slate-300 bg-slate-50 px-3 text-sm font-medium"
      style={{ display: "flex", alignItems: "center", gap: 8, border: "1px solid #CBD5E1", borderRadius: 6, background: "#F8FAFC", padding: "0 12px", fontSize: 14, color: "#0F172A" }}>
      User
      <select aria-label="Filter report by user" value={userFilter} onChange={(event) => { setUserFilter(event.target.value); setSummaryOnly(false) }}
        className="h-8 bg-transparent text-sm font-bold outline-none" style={{ height: 32, border: 0, background: "transparent", fontWeight: 700 }}>
        <option value="">All</option>
        {reportUsers.map((initials) => <option key={initials} value={initials}>{initials}</option>)}
      </select>
    </label>
    {summaryOnly ? <button type="button" onClick={() => { setSummaryOnly(false); setUserFilter(""); setMarkerFilters(new Set()); setDueDateFilter("all"); setStrikesOnly(false) }}
      style={{ border: "1px solid #93C5FD", borderRadius: 6, background: "#EFF6FF", padding: "0 10px", fontSize: 13, color: "#1D4ED8" }}>Show all tasks</button> : null}
  </>

  const dueDateFilterControl = (
    <label
      className="flex items-center gap-2 rounded-md border border-red-300 bg-red-50 px-3 text-sm font-medium text-red-900"
      style={{ display: "flex", alignItems: "center", gap: 8, border: "1px solid #FCA5A5", borderRadius: 6, background: "#FEF2F2", padding: "0 12px", fontSize: 14, fontWeight: 500, color: "#7F1D1D" }}
    >
      Due date
      <select
        className={`h-8 bg-transparent text-sm font-black outline-none ${dueDateFilter === "deadline" ? "text-red-600" : "text-red-900"}`}
        style={{ height: 32, border: 0, background: "transparent", fontSize: 14, fontWeight: 900, color: dueDateFilter === "deadline" ? "#DC2626" : "#7F1D1D", outline: "none" }}
        value={dueDateFilter}
        onChange={(event) => setDueDateFilter(event.target.value as TaskDueDateFilter)}
        aria-label="Filter tasks by due date"
      >
        <option value="all">All</option>
        <option value="today">SOT</option>
        <option value="deadline" style={{ color: "#DC2626", fontWeight: 800 }}>Deadline</option>
        <option value="starts_today">Starts SOT</option>
      </select>
    </label>
  )

  const generatedPreview = preview ? (
    <div className="space-y-3 rounded-lg border bg-white p-4">
      {today ? <p className={`rounded-md px-3 py-2 text-sm font-semibold ${preview.is_frozen ? "bg-blue-50 text-blue-900" : "bg-amber-50 text-amber-900"}`}>
        {preview.is_frozen ? `Raport i ngrirë në 16:00 — ${preview.report_date}. Ndryshimet e mëvonshme nuk përfshihen.` : "Në 16:00 ruhet gjendja deri në 15:59. Nesër hapet raporti i ditës së re."}
      </p> : null}
      <div className="flex items-center gap-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-8 w-8 shrink-0 p-0"
          aria-expanded={reportIntroExpanded}
          aria-label={reportIntroExpanded ? "Hide report questions and legend" : "Show report questions and legend"}
          title={reportIntroExpanded ? "Hide questions and legend" : "Show questions and legend"}
          onClick={() => setReportIntroExpanded((expanded) => !expanded)}
        >
          {reportIntroExpanded ? "−" : "+"}
        </Button>
        <div>
          <h2 className="font-semibold">Saved generated report</h2>
          <p className="text-sm text-muted-foreground">{preview.subject}</p>
          <p className="text-xs text-muted-foreground">
            Generated {formatDateTime(preview.generated_at)}{preview.generated_by ? ` by ${preview.generated_by}` : ""}
          </p>
        </div>
      </div>
      <iframe
        ref={previewFrameRef}
        onLoad={() => {
          // Apply the compact layout to previously saved report HTML as well.
          previewFrameRef.current?.contentDocument?.querySelectorAll<HTMLElement>('[data-task-marker-comment="true"]').forEach((comment) => {
            comment.style.maxWidth = "min(100%, 150px)"
            comment.style.whiteSpace = "nowrap"
            comment.style.overflow = "hidden"
            comment.style.textOverflow = "ellipsis"
          })
          applyReportIntroVisibility()
          setupPreviewMarkerControls()
          syncPreviewCommentAttention()
          setupPreviewFilters()
          const document = previewFrameRef.current?.contentDocument
          if (today && document) applyTaskStrikeBadges(document, preview.one_h_strikes)
        }}
        title={`${reportName} generated email`}
        srcDoc={preview.html.replace('<div data-report-intro="true">', '<div data-report-intro="true" hidden>')}
        className={`w-full rounded border bg-white ${embedded ? "h-[620px]" : "h-dvh min-h-dvh"}`}
      />
      {previewFilterContainer ? createPortal(
        <>
          <style>{`
            [data-report-filters-group] > label,
            [data-report-filters-group] > details { font-size:13px !important; }
            [data-report-filters-group] > label { padding:0 10px !important;gap:6px !important; }
            [data-report-filters-group] > label > select { height:30px !important;font-size:13px !important; }
            [data-report-filters-group] > details > summary { height:30px !important;min-width:140px !important;padding:0 10px !important;gap:6px !important; }
            [data-report-filters-group] > button { min-height:32px;padding:0 10px !important;white-space:nowrap; }
          `}</style>
          <div data-report-filters-group="true" style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 4 }}>
            {userFilterControl}
            {dueDateFilterControl}
            {markerFilterControl()}
            {strikesFilterControl}
            {strikeTotalControl}
          </div>
        </>,
        previewFilterContainer,
      ) : null}
    </div>
  ) : null

  if (embedded) {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-center gap-2">
          {modeControl}
          {preview ? <>{userFilterControl}{dueDateFilterControl}{markerFilterControl()}{strikesFilterControl}{strikeTotalControl}</> : null}
          <Button
            variant="outline"
            onClick={() => void generateReport()}
            disabled={!user || generatingAction !== null || snapshotLoading || (today && (Boolean(preview?.is_frozen) || Boolean(selectedReportDate)))}
          >
            <RefreshCw className={generatingAction === "generate" ? "animate-spin" : ""} />
            {today && preview?.is_frozen ? "Raport i ngrirë" : generatingAction === "generate" ? "Generating..." : preview ? "Regenerate" : "Generate"}
          </Button>
        </div>
        {generatedPreview}
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1400px] space-y-5">
      <div className="sticky top-0 z-40 -mx-4 flex flex-wrap items-start justify-between gap-4 border-b bg-background/95 px-4 py-2 shadow-sm backdrop-blur supports-[backdrop-filter]:bg-background/90 print:static print:mx-0 print:border-0 print:bg-transparent print:p-0 print:shadow-none">
        <div>
          <h1 className="text-2xl font-semibold">{reportName}</h1>
          <p className="text-sm text-muted-foreground">{today ? "Today's Common View tasks and meetings, sent at 09:00 Monday-Friday." : "Next-working-day tasks and meetings, sent as an HTML email."}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {preview ? <>{userFilterControl}{dueDateFilterControl}{markerFilterControl()}{strikesFilterControl}{strikeTotalControl}</> : null}
          <Button variant="outline" onClick={() => void generateReport()} disabled={!user || generatingAction !== null || snapshotLoading || (today && (Boolean(preview?.is_frozen) || Boolean(selectedReportDate)))}><RefreshCw className={generatingAction === "generate" ? "animate-spin" : ""} /> {today && preview?.is_frozen ? "Raport i ngrirë" : generatingAction === "generate" ? "Generating..." : preview ? "Regenerate" : "Generate"}</Button>
          {canManage ? <Button onClick={() => void sendNow()} disabled={sending || (today && Boolean(selectedReportDate))}><Send /> {sending ? "Sending..." : "Send now"}</Button> : null}
        </div>
      </div>

      {canManage && settings ? (
        <div className="space-y-4 rounded-lg border bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 w-8 shrink-0 p-0"
                aria-expanded={automaticEmailExpanded}
                aria-label={automaticEmailExpanded ? "Close automatic email settings" : "Open automatic email settings"}
                title={automaticEmailExpanded ? "Close settings" : "Open settings"}
                onClick={() => setAutomaticEmailExpanded((expanded) => !expanded)}
              >
                {automaticEmailExpanded ? <Minus /> : <Plus />}
              </Button>
              <div>
                <div className="flex items-center gap-2 font-semibold"><Settings size={16} /> Automatic email</div>
                <div className="text-sm text-muted-foreground">{today ? "Each delivery contains that day's task rows, TAK INT, and TAK EXT meetings." : "Friday’s delivery contains Monday’s report."}</div>
              </div>
            </div>
            <button
              type="button"
              aria-pressed={settings.is_active}
              onClick={() => setSettings({ ...settings, is_active: !settings.is_active })}
              className={settings.is_active ? "relative h-8 w-14 rounded-full bg-emerald-500 p-1" : "relative h-8 w-14 rounded-full bg-red-500 p-1"}
            ><span className={settings.is_active ? "absolute right-1 top-1 size-6 rounded-full bg-white shadow" : "absolute left-1 top-1 size-6 rounded-full bg-white shadow"} /></button>
          </div>
          {automaticEmailExpanded ? <>
            <div className="grid gap-3 md:grid-cols-[180px_220px_1fr]">
              <div><Label>Send times</Label><Input type="time" value={settings.send_time} onChange={(event) => setSettings({ ...settings, send_time: event.target.value })} /><p className="mt-1 text-xs text-muted-foreground">{settings.send_time} and {secondSendTime(settings.send_time)}</p></div>
              <div><Label>Timezone</Label><Input value={settings.timezone} onChange={(event) => setSettings({ ...settings, timezone: event.target.value })} /></div>
              <div><Label>Days</Label><div className="flex flex-wrap gap-2">{days.map((label, day) => <Button key={label} type="button" variant={settings.weekdays.includes(day) ? "default" : "outline"} onClick={() => toggleDay(day)}>{label}</Button>)}</div></div>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <div><Label>To</Label><Input value={recipientInputs.to} onChange={(event) => updateRecipients("to", event.target.value)} placeholder="email@example.com" /></div>
              <div><Label>Cc</Label><Input value={recipientInputs.cc} onChange={(event) => updateRecipients("cc", event.target.value)} placeholder="Optional" /></div>
              <div><Label>Bcc</Label><Input value={recipientInputs.bcc} onChange={(event) => updateRecipients("bcc", event.target.value)} placeholder="Optional" /></div>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-3"><span className="text-sm text-muted-foreground">Last run: {formatDateTime(settings.last_run_date)}</span><Button variant="outline" onClick={() => void saveSettings()} disabled={saving}><Save /> Save settings</Button></div>
          </> : null}
        </div>
      ) : canManage ? <div className="rounded-lg border bg-white p-8 text-sm text-muted-foreground">{loading ? "Loading settings..." : "No settings available."}</div> : null}

      {generatedPreview}

      {today ? <div className="flex items-center gap-3 rounded-lg border bg-white p-4">
        <Label htmlFor="today-frozen-history">Historiku i raporteve të ngrira</Label>
        <select id="today-frozen-history" className="h-9 rounded-md border px-3 text-sm" value={selectedReportDate} onChange={(event) => { setPreview(null); setSelectedReportDate(event.target.value) }}>
          <option value="">Raporti i sotëm</option>
          {frozenHistory.map((row) => <option key={row.report_date} value={row.report_date}>{row.report_date} — 16:00</option>)}
        </select>
      </div> : null}

      {!snapshotLoading && !preview ? (
        <div className="rounded-lg border bg-white p-8 text-center text-sm text-muted-foreground">
          {snapshotError || "No saved report for this date. Select Generate to create it."}
        </div>
      ) : null}

      {canManage ? <div className="rounded-lg border bg-white p-4">
        <div className="mb-3 flex items-center justify-between"><div><h2 className="font-semibold">Delivery history</h2><p className="text-sm text-muted-foreground">Last 50 attempts</p></div><Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}><RefreshCw className={loading ? "animate-spin" : ""} /> Refresh</Button></div>
        <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="border-b text-left text-muted-foreground"><tr><th className="p-2">Delivery</th><th className="p-2">Report for</th><th className="p-2">Status</th><th className="p-2">Sent</th><th className="p-2">To</th></tr></thead><tbody>{history.map((row) => <tr key={row.id} className="border-b"><td className="p-2">{row.delivery_date}</td><td className="p-2">{row.target_date}</td><td className="p-2">{row.status}</td><td className="p-2">{formatDateTime(row.sent_at)}</td><td className="p-2">{row.recipients.to.join(", ") || "-"}{row.last_error ? <div className="text-xs text-red-600">{row.last_error}</div> : null}</td></tr>)}{!history.length ? <tr><td className="p-4 text-muted-foreground" colSpan={5}>No deliveries yet.</td></tr> : null}</tbody></table></div>
      </div> : null}
    </div>
  )
}

export default function TomorrowPrintReportPage() {
  return <PrintReportPage />
}

export function EmbeddedPrintReportGenerator() {
  const [mode, setMode] = React.useState<"today" | "tomorrow">("today")

  const modeControl = (
    <div className="flex items-center gap-2" role="group" aria-label="Select 1H SHTYPI report day">
      <Button
        type="button"
        size="sm"
        variant={mode === "today" ? "default" : "outline"}
        aria-pressed={mode === "today"}
        onClick={() => setMode("today")}
      >
        Today
      </Button>
      <Button
        type="button"
        size="sm"
        variant={mode === "tomorrow" ? "default" : "outline"}
        aria-pressed={mode === "tomorrow"}
        onClick={() => setMode("tomorrow")}
      >
        Tomorrow
      </Button>
    </div>
  )

  return (
    <PrintReportPage
      key={mode}
      today={mode === "today"}
      embedded
      modeControl={modeControl}
    />
  )
}
