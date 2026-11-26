"use client"

import * as React from "react"
import { ReportTaskSymbolsPanel } from "@/components/report-task-symbols-panel"
import { ReportMailbox } from "@/components/report-mailbox"
import { installReportNoteControls, ReportNoteAttachmentDialog, ReportNoteCell, type ReportNoteAttachment, type ReportNoteAttachments } from "@/components/report-note-attachments"
import { NoteEmailPreview, reportEmailNoteDetails } from "@/components/note-email-preview"
import type { NoteEmailHeadings, NoteEmailPreviews } from "@/lib/types"
import { Eye, History, Pencil, RefreshCw, Save, Send, Settings } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import {
  ReportSectionFieldEditor,
  ReportSectionPreview,
  reportSectionEditorLines,
  reportSectionPreviewText,
} from "@/components/report-section-editor"
import { useAuth } from "@/lib/auth"
import { useReportDate } from "@/lib/report-link-date"
import { addManualReportSection, isCustomManualReportSection, ManualReportQuestionAdd, ManualReportQuestionDelete } from "@/components/manual-report-question-add"

type Section = { section_key?: string; title: string; body: string }
type Recipients = { to: string[]; cc: string[]; bcc: string[] }
type RecipientInputs = { to: string; cc: string; bcc: string }
type EditingSection = { index: number; title: string; lines: string[] }
type TaskFeedback = { continuation: "" | "PO" | "JO"; comment: string }
type TaskFeedbackRow = TaskFeedback & { key: string; title: string; owners: string }
type TaskFeedbackEdits = Record<string, Partial<TaskFeedback>>
const TASK_FEEDBACK_SECTION = "GA/HV/DV TASKS"
const MANUAL_PLACEHOLDER = "(Ploteso manualisht)"
const NOTES_SECTION = "(GA) NOTES TE REJA ( NOT DISSCUSED)?"
const MARKER_TASK_SECTIONS = new Set(["FIZIKISHT ME GA?", "A KA PYTJE/SQARIME ME KA/GENTIN"])
const GA_REPLIES_SECTION = "(GA) A KA REPLY NGA GA TEK DETYRAT NGA STAFI PER GA?"
const GA_REACTIONS_SECTION = "A KA REACTION TE GRUPI?"
const GA_PF_COMMENTS_SECTION = "(GA) A KA KOMENTE NE PF?"
type ReportSettings = {
  is_active: boolean
  send_time: string
  timezone: string
  weekdays: number[]
  recipients: Recipients
  last_run_date?: string | null
}
type Draft = {
  id: string
  report_date: string
  subject: string
  recipients: Recipients
  sections: Section[]
  note_attachments?: ReportNoteAttachments
  note_emails?: NoteEmailPreviews
  note_email_headings?: NoteEmailHeadings
  generated_snapshot?: { ga_replies_generated_at?: string }
  task_feedback_rows?: Record<string, TaskFeedbackRow[]>
  status: string
  sent_at?: string | null
  gmail_message_id?: string | null
  last_error?: string | null
  updated_at?: string | null
}
type DeliveryHistory = {
  id: string
  report_date: string
  subject: string
  recipients: Recipients
  status: string
  sent_at: string | null
  gmail_message_id?: string | null
  last_error?: string | null
}

function sectionGroupLabel(section: Section) {
  // Built-in manuals are first; Common View–synced extras sit after them and before autos.
  const knownAuto = [
    GA_REPLIES_SECTION,
    GA_REACTIONS_SECTION,
    GA_PF_COMMENTS_SECTION,
    TASK_FEEDBACK_SECTION,
    "DET 08:00/DL AM",
    "GA TASKS",
    "HV TASKS",
    "DV TASKS",
    "(GA) DET NGA EMAILS TE REJA",
    "(GA) VONESA/MUNGESA. A NDRYSHON PLANI PER SOT?",
    "(GA) NOTES TE REJA ( NOT DISSCUSED)?",
    "PV/FESTA EXT/TAK EXT/ TAK INT/ BZ ME GA/BLLOK:",
    "(GA/KA) KUSH KA DET PERSONALISHT?",
    "DET PERSONALISHT ME KA/GENTIN?",
    "TASKS PERSONALISHT ME KA/GENTIN?",
    "WFC INT ME KA/GENTIN?",
    "WFC ME KA/GENTIN?",
    ...MARKER_TASK_SECTIONS,
  ]
  const compact = (value: string) => value.toUpperCase().replace(/[^A-Z0-9]+/g, "")
  const key = compact(section.section_key || section.title)
  const isEmailTasksSection = key.startsWith("GAEMINFO") || key.includes("DETNGEMAILS")
  if (isEmailTasksSection || knownAuto.some((auto) => compact(auto) === key)) {
    return "Auto-filled from PrimeFlow"
  }
  return "Manual questions"
}

function shouldShowSectionGroup(sections: Section[], index: number) {
  if (index === 0) return true
  return sectionGroupLabel(sections[index]) !== sectionGroupLabel(sections[index - 1])
}

function InlineTaskComment({ row, onSave }: {
  row: TaskFeedbackRow
  onSave: (comment: string) => void
}) {
  const [comment, setComment] = React.useState<string | null>(null)
  React.useEffect(() => {
    setComment((current) => current === row.comment ? null : current)
  }, [row.comment])
  return (
    <Textarea
      aria-label={`Koment për ${row.title} (${row.owners})`}
      value={comment ?? row.comment}
      onChange={(event) => setComment(event.target.value)}
      onBlur={() => {
        if (comment !== null && comment !== row.comment) onSave(comment)
      }}
      rows={1}
      maxLength={4000}
      className="min-h-6 min-w-36 resize-y border-slate-400 bg-white/60 px-1 py-0.5 text-xs print:border-0"
    />
  )
}

const API = "/morning-report"
const REPORT_LABEL = "Hapja e dites M1"

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function recipientsText(values?: string[]) {
  return (values || []).join(", ")
}

function parseRecipients(value: string) {
  const seen = new Set<string>()
  const rows: string[] = []
  for (const part of value.split(/[,\n;]/)) {
    const email = part.trim()
    const normalized = email.toLowerCase()
    if (!email || seen.has(normalized)) continue
    seen.add(normalized)
    rows.push(email)
  }
  return rows
}

function recipientsSummary(recipients: Recipients) {
  const groups = [
    recipients.to.length ? `To: ${recipients.to.join(", ")}` : "",
    recipients.cc.length ? `Cc: ${recipients.cc.join(", ")}` : "",
    recipients.bcc.length ? `Bcc: ${recipients.bcc.join(", ")}` : "",
  ].filter(Boolean)
  return groups.join(" | ") || "-"
}

function formatDateTimeInTimezone(value: string | null | undefined, timezone: string) {
  if (!value) return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: timezone || "Europe/Tirane",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date)
  } catch {
    return new Intl.DateTimeFormat("en-GB", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date)
  }
}

async function responseError(res: Response) {
  const text = await res.text()
  if (!text) return `HTTP ${res.status}`
  try {
    const data = JSON.parse(text)
    return typeof data?.detail === "string" ? data.detail : text
  } catch {
    return text
  }
}

export default function MorningReportPage() {
  const { apiFetch, loading: authLoading, user } = useAuth()
  const canAccess = !authLoading && Boolean(user)
  const isManagerOrAdmin = ["ADMIN", "MANAGER"].includes(String(user?.role || "").toUpperCase())
  const canEdit = Boolean(user)
  const canManageDelivery = isManagerOrAdmin
  const [reportDate, setReportDate] = useReportDate(todayIso)
  const [draft, setDraft] = React.useState<Draft | null>(null)
  const [loading, setLoading] = React.useState(false)
  const feedbackQueue = React.useRef(Promise.resolve())
  const [saving, setSaving] = React.useState(false)
  const [sending, setSending] = React.useState(false)
  const [preview, setPreview] = React.useState<{ html: string; plain_text: string; note_attachments?: ReportNoteAttachments; note_emails?: NoteEmailPreviews; note_email_headings?: NoteEmailHeadings } | null>(null)
  const [noteFiles, setNoteFiles] = React.useState<ReportNoteAttachment[] | null>(null)
  const [recipientInputs, setRecipientInputs] = React.useState<RecipientInputs>({ to: "", cc: "", bcc: "" })
  const [settings, setSettings] = React.useState<ReportSettings | null>(null)
  const [settingsInputs, setSettingsInputs] = React.useState<RecipientInputs>({ to: "", cc: "", bcc: "" })
  const [savingSettings, setSavingSettings] = React.useState(false)
  const [editingSection, setEditingSection] = React.useState<EditingSection | null>(null)
  const [history, setHistory] = React.useState<DeliveryHistory[]>([])
  const [loadingHistory, setLoadingHistory] = React.useState(false)

  const applyDraft = React.useCallback((nextDraft: Draft | null) => {
    setDraft(nextDraft)
    setRecipientInputs({
      to: recipientsText(nextDraft?.recipients?.to),
      cc: recipientsText(nextDraft?.recipients?.cc),
      bcc: recipientsText(nextDraft?.recipients?.bcc),
    })
  }, [])

  const applySettings = React.useCallback((nextSettings: ReportSettings) => {
    setSettings(nextSettings)
    setSettingsInputs({
      to: recipientsText(nextSettings.recipients?.to),
      cc: recipientsText(nextSettings.recipients?.cc),
      bcc: recipientsText(nextSettings.recipients?.bcc),
    })
  }, [])

  const loadDraft = React.useCallback(async () => {
    if (!canAccess) return
    setLoading(true)
    try {
      const res = await apiFetch(`${API}?report_date=${reportDate}`, { cache: "no-store" })
      if (res.status === 404) {
        applyDraft(null)
        return
      }
      if (!res.ok) throw new Error(await responseError(res))
      applyDraft(await res.json())
    } catch (error) {
      if (canAccess) toast.error(`Unable to load ${REPORT_LABEL}`, { description: String(error) })
    } finally {
      setLoading(false)
    }
  }, [apiFetch, applyDraft, canAccess, reportDate])

  const loadSettings = React.useCallback(async () => {
    if (!canManageDelivery) return
    try {
      const res = await apiFetch(`${API}/settings`)
      if (!res.ok) throw new Error(await responseError(res))
      applySettings(await res.json())
    } catch (error) {
      if (canManageDelivery) toast.error(`Unable to load ${REPORT_LABEL} settings`, { description: String(error) })
    }
  }, [apiFetch, applySettings, canManageDelivery])

  const loadHistory = React.useCallback(async () => {
    if (!canManageDelivery) return
    setLoadingHistory(true)
    try {
      const res = await apiFetch(`${API}/history?limit=50`)
      if (!res.ok) throw new Error(await responseError(res))
      setHistory(await res.json())
    } catch (error) {
      toast.error("Unable to load send history", { description: String(error) })
    } finally {
      setLoadingHistory(false)
    }
  }, [apiFetch, canManageDelivery])

  React.useEffect(() => {
    if (!canAccess) return
    const frame = window.requestAnimationFrame(() => {
      void loadDraft()
      if (canManageDelivery) {
        void loadSettings()
        void loadHistory()
      }
    })
    return () => window.cancelAnimationFrame(frame)
  }, [canAccess, canManageDelivery, loadDraft, loadSettings, loadHistory])

  const generate = async () => {
    if (!canAccess) return
    setLoading(true)
    try {
      if (draft && canEdit) {
        await save(draft)
      }
      const res = await apiFetch(`${API}/generate?report_date=${reportDate}`, { method: "POST" })
      if (!res.ok) throw new Error(await responseError(res))
      applyDraft(await res.json())
      toast.success(`${REPORT_LABEL} generated`)
    } catch (error) {
      toast.error("Generate failed", { description: String(error) })
    } finally {
      setLoading(false)
    }
  }

  const save = async (draftToSave: Draft | null = draft, taskFeedback?: TaskFeedbackEdits): Promise<Draft | null> => {
    if (!draftToSave || !canEdit) return draftToSave
    if (!taskFeedback) await feedbackQueue.current
    setSaving(true)
    try {
      const res = await apiFetch(`${API}/${draftToSave.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(taskFeedback ? { task_feedback: taskFeedback } : {
          subject: draftToSave.subject,
          recipients: draftToSave.recipients,
          sections: draftToSave.sections,
        }),
      })
      if (!res.ok) throw new Error(await responseError(res))
      const data: Draft = await res.json()
      if (taskFeedback) {
        setDraft((current) => current?.id === data.id ? {
          ...current,
          task_feedback_rows: data.task_feedback_rows,
          sections: current.sections.map((section) =>
            (section.section_key || section.title) === TASK_FEEDBACK_SECTION
              ? data.sections.find((next) => (next.section_key || next.title) === TASK_FEEDBACK_SECTION) ?? section
              : section,
          ),
        } : current)
      } else {
        setDraft((current) => {
          if (current?.id !== data.id) return current
          // General saves return the stored sections, while loading M1 refreshes these tables.
          const liveTaskSections = new Map(current.sections.flatMap((section) => {
            const key = section.section_key || section.title
            return key === TASK_FEEDBACK_SECTION || MARKER_TASK_SECTIONS.has(key) ? [[key, section] as const] : []
          }))
          return {
            ...data,
            task_feedback_rows: current.task_feedback_rows ?? data.task_feedback_rows,
            sections: data.sections.map((section) =>
              liveTaskSections.get(section.section_key || section.title) ?? section,
            ),
          }
        })
      }
      toast.success("Draft saved")
      return data
    } catch (error) {
      toast.error("Save failed", { description: String(error) })
      return null
    } finally {
      setSaving(false)
    }
  }

  const saveTaskFeedback = (row: TaskFeedbackRow, edit: Partial<TaskFeedback>) => {
    feedbackQueue.current = feedbackQueue.current.then(async () => {
      await save(draft, { [row.key]: edit })
    })
  }

  const previewDraft = async () => {
    if (!draft) return
    if (canEdit) await save()
    try {
      const res = await apiFetch(`${API}/${draft.id}/preview`)
      if (!res.ok) throw new Error(await responseError(res))
      setPreview(await res.json())
    } catch (error) {
      toast.error("Preview failed", { description: String(error) })
    }
  }

  const sendDraft = async () => {
    if (!draft || !canManageDelivery) return
    setSending(true)
    try {
      const savedDraft = await save()
      if (!savedDraft) return
      const res = await apiFetch(`${API}/${savedDraft.id}/send`, { method: "POST" })
      if (!res.ok) throw new Error(await responseError(res))
      const data = await res.json()
      applyDraft(data)
      void loadHistory()
      toast.success(`${REPORT_LABEL} sent`, { description: data.gmail_message_id || undefined })
    } catch (error) {
      toast.error("Send failed", { description: String(error) })
    } finally {
      setSending(false)
    }
  }

  const updateSection = (index: number, body: string) => {
    setDraft((current) => {
      if (!current) return current
      const sections = current.sections.map((section, sectionIndex) =>
        sectionIndex === index ? { ...section, body } : section
      )
      return { ...current, sections }
    })
  }

  const openSectionEditor = (index: number) => {
    if (!draft) return
    const body = draft.sections[index]?.body || ""
    setEditingSection({
      index,
      title: draft.sections[index]?.title || "",
      lines: body.trim() === MANUAL_PLACEHOLDER ? [""] : reportSectionEditorLines(body),
    })
  }

  const applySectionEditor = (lines: string[]) => {
    if (!editingSection || !draft) return
    const sections = draft.sections.map((section, index) =>
      index === editingSection.index
        ? {
            ...section,
            title: editingSection.title.trim() || section.title,
            body: lines.join("\n"),
          }
        : section
    )
    const editedSection = draft.sections[editingSection.index]
    const notesEdited = (editedSection.section_key || editedSection.title) === NOTES_SECTION
    const nextDraft = {
      ...draft, sections,
      note_attachments: notesEdited ? undefined : draft.note_attachments,
      note_emails: notesEdited ? undefined : draft.note_emails,
      note_email_headings: notesEdited ? undefined : draft.note_email_headings,
    }
    setDraft(nextDraft)
    setEditingSection(null)
    void save(nextDraft)
  }

  const addManualQuestion = async (title: string, position: number) => {
    if (!draft) return false
    const sections = addManualReportSection(draft.sections, title, position, (section) =>
      sectionGroupLabel(section) === "Manual questions",
    )
    if (!sections) {
      toast.error("Kjo pikë ekziston tashmë")
      return false
    }
    const nextDraft = { ...draft, sections }
    const addedKey = sections.find((section) => !draft.sections.includes(section))?.section_key
    const saved = await save(nextDraft)
    if (!saved) return false
    if (saved.sections.some((section) => section.section_key === addedKey)) return true
    toast.error("Pika nuk u ruajt. Provo përsëri.")
    return false
  }

  const deleteManualQuestion = async (sectionKey: string) => {
    if (!draft || saving || user?.role !== "ADMIN") return
    const nextDraft = { ...draft, sections: draft.sections.filter((section) => section.section_key !== sectionKey) }
    setDraft(nextDraft)
    if (!await save(nextDraft)) setDraft(draft)
  }

  const updateRecipients = (kind: keyof Recipients, value: string) => {
    setRecipientInputs((current) => ({ ...current, [kind]: value }))
    setDraft((current) => current ? { ...current, recipients: { ...current.recipients, [kind]: parseRecipients(value) } } : current)
  }

  const updateSettingsRecipients = (kind: keyof Recipients, value: string) => {
    setSettingsInputs((current) => ({ ...current, [kind]: value }))
    setSettings((current) => current ? { ...current, recipients: { ...current.recipients, [kind]: parseRecipients(value) } } : current)
  }

  const toggleWeekday = (day: number) => {
    setSettings((current) => {
      if (!current) return current
      const exists = current.weekdays.includes(day)
      const weekdays = exists ? current.weekdays.filter((value) => value !== day) : [...current.weekdays, day].sort()
      return { ...current, weekdays }
    })
  }

  const saveSettings = async () => {
    if (!settings || !canManageDelivery) return
    setSavingSettings(true)
    try {
      const res = await apiFetch(`${API}/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      })
      if (!res.ok) throw new Error(await responseError(res))
      applySettings(await res.json())
      toast.success(`${REPORT_LABEL} settings saved`)
    } catch (error) {
      toast.error("Settings save failed", { description: String(error) })
    } finally {
      setSavingSettings(false)
    }
  }

  if (!canAccess) return <div className="rounded-lg border p-8">{REPORT_LABEL} access required.</div>

  return (
    <div className="mx-auto max-w-[1400px] space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{REPORT_LABEL}</h1>
          <p className="text-sm text-muted-foreground">Editable morning M1 summary for the start of the day.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {draft && canEdit && !draft.sections.some((section) => sectionGroupLabel(section) === "Manual questions") ? (
            <ManualReportQuestionAdd onAdd={addManualQuestion} disabled={saving} />
          ) : null}
          <Button variant="outline" onClick={() => void loadDraft()} disabled={loading}>
            <RefreshCw className={loading ? "animate-spin" : ""} /> Refresh
          </Button>
          <Button onClick={() => void generate()} disabled={loading}>
            <RefreshCw className={loading ? "animate-spin" : ""} /> {loading ? "Generating..." : "Generate"}
          </Button>
        </div>
      </div>

      <Tabs defaultValue="report" className="gap-5">
        <TabsList className="h-10 rounded-md">
          <TabsTrigger value="report"><Pencil /> Report</TabsTrigger>
          {canManageDelivery ? <TabsTrigger value="history"><History /> Send history</TabsTrigger> : null}
        </TabsList>

        <TabsContent value="report" className="space-y-5">
          <details className="group rounded-lg border bg-white">
            <summary className="flex cursor-pointer list-none items-center gap-3 rounded-lg bg-slate-50 px-4 py-3 text-sm font-semibold group-open:rounded-b-none [&::-webkit-details-marker]:hidden">
              <span aria-hidden="true" className="w-4 text-center text-xl leading-none group-open:hidden">+</span>
              <span aria-hidden="true" className="hidden w-4 text-center text-xl leading-none group-open:inline">−</span>
              Menaxhimi i raportit dhe email-it
            </summary>
            <div className="space-y-5 border-t p-4">
              <ReportTaskSymbolsPanel key={reportDate} reportDate={reportDate} />
              <div className="grid gap-3 rounded-lg border bg-white p-4 md:grid-cols-[220px_1fr_auto]">
                <div>
                  <Label>Date</Label>
                  <Input type="date" value={reportDate} onChange={(event) => setReportDate(event.target.value)} />
                </div>
                <div>
                  <Label>Subject</Label>
                  <Input
                    value={draft?.subject || ""}
                    onChange={(event) => draft && setDraft({ ...draft, subject: event.target.value })}
                    placeholder="Generate a draft first"
                    readOnly={!canEdit}
                  />
                </div>
                <div className="flex items-end gap-2">
                  {canEdit ? (
                    <Button variant="outline" onClick={() => void save()} disabled={!draft || saving}>
                      <Save /> Save
                    </Button>
                  ) : null}
                  <Button variant="outline" onClick={() => void previewDraft()} disabled={!draft || saving}>
                    <Eye /> Preview
                  </Button>
                  {canManageDelivery ? (
                    <Button onClick={() => void sendDraft()} disabled={!draft || sending}>
                      <Send /> Send
                    </Button>
                  ) : null}
                </div>
              </div>

              {canManageDelivery ? (
              <div className="grid gap-3 rounded-lg border bg-white p-4 md:grid-cols-3">
                <div>
                  <Label>To</Label>
                    <Input
                    value={recipientInputs.to}
                    onChange={(event) => draft && updateRecipients("to", event.target.value)}
                    placeholder="email@example.com"
                    readOnly={!canEdit}
                  />
                </div>
                <div>
                  <Label>Cc</Label>
                  <Input
                    value={recipientInputs.cc}
                    onChange={(event) => draft && updateRecipients("cc", event.target.value)}
                    placeholder="Optional"
                    readOnly={!canEdit}
                  />
                </div>
                <div>
                  <Label>Bcc</Label>
                  <Input
                    value={recipientInputs.bcc}
                    onChange={(event) => draft && updateRecipients("bcc", event.target.value)}
                    placeholder="Optional"
                    readOnly={!canEdit}
                  />
                </div>
              </div>
              ) : null}

              {canManageDelivery && settings ? (
                <div className="space-y-3 rounded-lg border bg-white p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2 font-semibold"><Settings size={16} /> Automatic Send</div>
                      <div className="text-sm text-muted-foreground">
                        {settings.is_active
                          ? "Automatic sending is ON. This report regenerates and sends at 07:00 and 09:00 on the selected days."
                          : "Automatic sending is OFF. This report will not send by itself."}
                      </div>
                    </div>
                    <button
                      type="button"
                      aria-pressed={settings.is_active}
                      aria-label={settings.is_active ? "Turn automatic send off" : "Turn automatic send on"}
                      onClick={() => setSettings({ ...settings, is_active: !settings.is_active })}
                      className={
                        settings.is_active
                          ? "relative h-8 w-14 rounded-full bg-emerald-500 p-1 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                          : "relative h-8 w-14 rounded-full bg-red-500 p-1 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                      }
                    >
                      <span
                        className={
                          settings.is_active
                            ? "absolute right-1 top-1 size-6 rounded-full bg-white shadow transition-all"
                            : "absolute left-1 top-1 size-6 rounded-full bg-white shadow transition-all"
                        }
                      />
                    </button>
                  </div>
                  <div className="grid gap-3 md:grid-cols-[180px_220px_1fr]">
                    <div>
                      <Label>Automatic times</Label>
                      <div className="mt-1 flex h-9 items-center rounded-md border bg-slate-50 px-3 text-sm font-medium">
                        07:00 and 09:00
                      </div>
                    </div>
                    <div>
                      <Label>Timezone</Label>
                      <Input value={settings.timezone} onChange={(event) => setSettings({ ...settings, timezone: event.target.value })} />
                    </div>
                    <div>
                      <Label>Days</Label>
                      <div className="flex flex-wrap gap-2">
                        {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((label, day) => (
                          <Button
                            key={label}
                            type="button"
                            variant={settings.weekdays.includes(day) ? "default" : "outline"}
                            onClick={() => toggleWeekday(day)}
                          >
                            {label}
                          </Button>
                        ))}
                      </div>
                    </div>
                  </div>
                  <div className="grid gap-3 md:grid-cols-3">
                    <div>
                      <Label>Default To</Label>
                      <Input value={settingsInputs.to} onChange={(event) => updateSettingsRecipients("to", event.target.value)} />
                    </div>
                    <div>
                      <Label>Default Cc</Label>
                      <Input value={settingsInputs.cc} onChange={(event) => updateSettingsRecipients("cc", event.target.value)} />
                    </div>
                    <div>
                      <Label>Default Bcc</Label>
                      <Input value={settingsInputs.bcc} onChange={(event) => updateSettingsRecipients("bcc", event.target.value)} />
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="text-sm text-muted-foreground">
                      Last automatic run: {formatDateTimeInTimezone(settings.last_run_date, settings.timezone)}
                    </div>
                      <Button variant="outline" onClick={() => void saveSettings()} disabled={savingSettings}>
                        <Save /> Save settings
                      </Button>
                  </div>
                </div>
              ) : null}

              {draft ? (
                <div className="grid gap-3 text-sm md:grid-cols-3">
                  <div className="rounded-lg border bg-white p-3">
                    <div className="text-muted-foreground">Report date</div>
                    <div className="font-medium">{draft.report_date}</div>
                  </div>
                  <div className="rounded-lg border bg-white p-3">
                    <div className="text-muted-foreground">Status</div>
                    <div className="font-medium">{draft.status}</div>
                  </div>
                  <div className="rounded-lg border bg-white p-3">
                    <div className="text-muted-foreground">Sent to</div>
                    <div className="truncate font-medium">{draft.recipients.to.join(", ") || "-"}</div>
                  </div>
                </div>
              ) : null}
            </div>
          </details>

      {draft ? (
        <>
          <div className="space-y-4">
            {draft.sections.map((section, index) => {
              const isEditing = editingSection?.index === index
              const sectionKey = section.section_key || section.title
              const isEmailSection = sectionKey === "(GA) DET NGA EMAILS TE REJA"
              const showSectionBody = !isEmailSection || Boolean(section.body.trim())
              const group = sectionGroupLabel(section)
              const showAddPoint = group === "Manual questions" && canEdit &&
                (index === 0 || sectionGroupLabel(draft.sections[0]) !== "Manual questions")
              const isMarkerTaskSection = MARKER_TASK_SECTIONS.has(sectionKey)
              const isTaskFeedbackSection = sectionKey === TASK_FEEDBACK_SECTION
              return (
                <React.Fragment key={`${section.title}-${index}`}>
                  {shouldShowSectionGroup(draft.sections, index) ? (
                    <div className="flex items-center justify-between gap-2 rounded-md border bg-slate-100 px-3 py-2 text-xs font-bold uppercase tracking-wide text-slate-700">
                      {group}
                      {showAddPoint ? <ManualReportQuestionAdd onAdd={addManualQuestion} disabled={saving} /> : null}
                    </div>
                  ) : null}
                  <div className="rounded-lg border bg-white p-4 shadow-sm">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        {isEditing ? (
                          <div className="flex items-start gap-2">
                            <span className="mt-2 text-sm font-semibold tabular-nums">{index + 1}.</span>
                            <Input
                              value={editingSection.title}
                              onChange={(event) =>
                                setEditingSection((current) =>
                                  current ? { ...current, title: event.target.value } : current
                                )
                              }
                              className="font-semibold"
                              placeholder="Shkruaj pyetjen..."
                            />
                          </div>
                        ) : (
                          <div className="text-sm font-semibold">{index + 1}. {section.title}</div>
                        )}
                        {!isEditing && showSectionBody ? (
                          <div className="mt-1 text-xs text-muted-foreground">
                            {section.body.trim().split(/\s+/).filter(Boolean).length} words
                          </div>
                        ) : null}
                      </div>
                      {canEdit && !isEditing && !isMarkerTaskSection && !isTaskFeedbackSection &&
                        sectionKey !== GA_REACTIONS_SECTION && sectionKey !== GA_PF_COMMENTS_SECTION ? (
                        <div className="flex items-center gap-2">
                          <Button variant="outline" size="sm" onClick={() => openSectionEditor(index)}>
                            <Pencil className="h-4 w-4" /> Edit
                          </Button>
                          {user?.role === "ADMIN" && isCustomManualReportSection(section) ? (
                            <ManualReportQuestionDelete title={section.title} disabled={saving} onDelete={() => deleteManualQuestion(section.section_key!)} />
                          ) : null}
                        </div>
                      ) : null}
                    </div>

                    {isEditing ? (
                      <ReportSectionFieldEditor
                        key={`edit-${index}`}
                        lines={editingSection.lines}
                        emptyPlaceholder={section.body.trim() === MANUAL_PLACEHOLDER ? MANUAL_PLACEHOLDER : undefined}
                        onCancel={() => setEditingSection(null)}
                        onSave={applySectionEditor}
                      />
                    ) : showSectionBody ? (
                      <ReportSectionPreview
                        body={reportSectionPreviewText(section.body)}
                        compactBzColumn={isTaskFeedbackSection || sectionKey === "GA TASKS"}
                        largerTableText={(section.section_key || section.title) === GA_REPLIES_SECTION}
                        discordReplyReport={sectionKey === GA_REPLIES_SECTION
                          ? { report: "M1", date: draft.report_date }
                          : sectionKey === GA_REACTIONS_SECTION
                            ? { report: "M1", date: draft.report_date, source: "reaction" } : undefined}
                        emphasizeOwnerSeparator={isMarkerTaskSection || sectionKey === GA_PF_COMMENTS_SECTION}
                        renderLine={isTaskFeedbackSection && canEdit ? (line) => {
                          const plans = draft.task_feedback_rows?.plan ?? []
                          const row = plans.find((plan) =>
                            line.startsWith(`${plan.title} (${plan.owners}):`),
                          )
                          if (!row) {
                            return plans.some((plan) =>
                              line.trim() === `${plan.owners} TASKS:` &&
                              section.body.includes(`${plan.title} (${plan.owners}):`),
                            ) ? false : null
                          }
                          return (
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b bg-slate-50 px-3 py-2">
                              <span className="shrink-0 font-semibold">{row.owners} TASKS:</span>
                              <label className="flex items-center gap-2 font-semibold">
                                {row.title} <span className="sr-only">({row.owners})</span>
                                <select
                                  className={`rounded border px-2 py-0.5 ${
                                    row.continuation === "PO"
                                      ? "border-red-300 bg-red-100 font-semibold text-red-800"
                                      : row.continuation === "JO"
                                        ? "border-green-300 bg-green-100 font-semibold text-green-800"
                                        : "border-slate-400 bg-background font-normal"
                                  }`}
                                  value={row.continuation}
                                  onChange={(event) => saveTaskFeedback(row, { continuation: event.target.value as TaskFeedback["continuation"] })}
                                >
                                  <option value="">–</option>
                                  <option value="PO">Po</option>
                                  <option value="JO">Jo</option>
                                </select>
                              </label>
                              <div className="min-w-44 flex-1">
                                <InlineTaskComment key={row.key} row={row} onSave={(comment) => saveTaskFeedback(row, { comment })} />
                              </div>
                            </div>
                          )
                        } : undefined}
                        renderCell={sectionKey === NOTES_SECTION ? (label, number, header, text) => {
                          if (label !== "NOTES:" || header !== "NOTE") return null
                          const files = draft.note_attachments?.[number]
                          const email = draft.note_emails?.[number]
                          if (email) {
                            const preview = <NoteEmailPreview key={email.id} email={email} />
                            return files?.length ? <ReportNoteCell text={preview} files={files} onOpen={setNoteFiles} /> : preview
                          }
                          const formatted = reportEmailNoteDetails(text, draft.note_email_headings?.[number])
                          return files?.length ? <ReportNoteCell text={formatted ?? text} files={files} onOpen={setNoteFiles} /> : formatted
                        } : isTaskFeedbackSection && canEdit ? (label, number, header) => {
                          if (!/^[1-9]\d*$/.test(number)) return null
                          const row = draft.task_feedback_rows?.[label.trim().replace(/:$/, "").toUpperCase()]?.[Number(number) - 1]
                          if (!row) return null
                          if (header === "KOMENT") {
                            return <InlineTaskComment key={row.key} row={row} onSave={(comment) => saveTaskFeedback(row, { comment })} />
                          }
                          if (header !== "VAZHDON?") return null
                          return (
                            <select
                              aria-label={`Vazhdon? ${row.title} (${row.owners})`}
                              className="w-full rounded border border-slate-400 bg-transparent px-1"
                              value={row.continuation}
                              onChange={(event) => saveTaskFeedback(row, { continuation: event.target.value as TaskFeedback["continuation"] })}
                            >
                              <option value="">–</option>
                              <option value="PO" aria-label="Po">✓</option>
                              <option value="JO" aria-label="Jo">X</option>
                            </select>
                          )
                        } : undefined}
                      />
                    ) : null}
                    {isEmailSection && !isEditing && (
                      <React.Fragment key={draft.generated_snapshot?.ga_replies_generated_at ?? draft.id}>
                        <ReportMailbox source="info-px" reportDate={draft.report_date} draftId={draft.id} />
                        <ReportMailbox source="it" reportDate={draft.report_date} draftId={draft.id} />
                        <ReportMailbox source="hf" reportDate={draft.report_date} draftId={draft.id} />
                        <ReportMailbox source="px-eu" reportDate={draft.report_date} draftId={draft.id} />
                      </React.Fragment>
                    )}
                  </div>
                </React.Fragment>
              )
            })}
          </div>
        </>
      ) : (
        <div className="rounded-lg border bg-white p-8 text-center text-sm text-muted-foreground">
          No draft for this date. Generate one to start editing.
        </div>
      )}
        </TabsContent>

        {canManageDelivery ? (
          <TabsContent value="history" className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="font-semibold">Report delivery history</h2>
                <p className="text-sm text-muted-foreground">Last 50 sent reports</p>
              </div>
              <Button variant="outline" size="sm" onClick={() => void loadHistory()} disabled={loadingHistory}>
                <RefreshCw className={loadingHistory ? "animate-spin" : ""} /> Refresh
              </Button>
            </div>
            <div className="rounded-md border bg-white">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead>Sent at</TableHead>
                    <TableHead>Recipients</TableHead>
                    <TableHead>Subject</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {history.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="font-medium">{item.report_date}</TableCell>
                      <TableCell>{formatDateTimeInTimezone(item.sent_at, settings?.timezone || "Europe/Tirane")}</TableCell>
                      <TableCell className="max-w-[420px] whitespace-normal">{recipientsSummary(item.recipients)}</TableCell>
                      <TableCell className="max-w-[420px] truncate">{item.subject}</TableCell>
                      <TableCell>{item.last_error ? "ERROR" : item.status}</TableCell>
                    </TableRow>
                  ))}
                  {loadingHistory ? (
                    <TableRow><TableCell colSpan={5} className="h-24 text-center text-muted-foreground">Loading history...</TableCell></TableRow>
                  ) : null}
                  {!loadingHistory && history.length === 0 ? (
                    <TableRow><TableCell colSpan={5} className="h-24 text-center text-muted-foreground">No sent reports yet.</TableCell></TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </div>
          </TabsContent>
        ) : null}
      </Tabs>

      <Dialog open={Boolean(preview)} onOpenChange={(open) => !open && setPreview(null)}>
        <DialogContent className="max-w-5xl">
          <DialogHeader>
            <DialogTitle>Email preview</DialogTitle>
          </DialogHeader>
          {preview ? <iframe
            title={`${REPORT_LABEL} preview`}
            srcDoc={preview.html}
            className="h-[650px] w-full rounded border bg-white"
            onLoad={(event) => installReportNoteControls(event.currentTarget.contentDocument, preview.note_attachments, setNoteFiles, preview.note_emails, preview.note_email_headings)}
          /> : null}
        </DialogContent>
      </Dialog>
      <ReportNoteAttachmentDialog files={noteFiles} onClose={() => setNoteFiles(null)} />

    </div>
  )
}
