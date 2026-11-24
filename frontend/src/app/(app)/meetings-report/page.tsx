"use client"

import * as React from "react"
import { ReportTaskSymbolsPanel } from "@/components/report-task-symbols-panel"
import { M3TomorrowSymbolsTable } from "@/components/m3-tomorrow-symbols-table"
import { CalendarDays, CheckCircle2, Clock3, Eye, History, Mail, Pencil, RefreshCw, Save, Send, Settings, ShieldCheck } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  ReportSectionFieldEditor,
  ReportSectionPreview,
  reportSectionEditorLines,
  reportSectionPreviewText,
} from "@/components/report-section-editor"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useAuth } from "@/lib/auth"
import { addManualReportSection, isCustomManualReportSection, ManualReportQuestionAdd, ManualReportQuestionDelete, orderManualReportSections } from "@/components/manual-report-question-add"

type Section = { section_key?: string; title: string; body: string }
type Recipients = { to: string[]; cc: string[]; bcc: string[] }
type RecipientInputs = { to: string; cc: string; bcc: string }
type EditingSection = { index: number; title: string; lines: string[] }
const MANUAL_PLACEHOLDER = "(Ploteso manualisht)"
const TOMORROW_SYMBOLS_TITLE = "SHIKO DET ME SIMBOLE NE 1H SHTYPI NESER"
const HV_DONE_TITLE = "DET DONE TE HV"
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
  tomorrow_date: string
  subject: string
  recipients: Recipients
  sections: Section[]
  generated_snapshot?: { tomorrow_symbols_html?: string } | null
  status: string
  sent_at?: string | null
  gmail_message_id?: string | null
  last_error?: string | null
  updated_at?: string | null
}

function compactSectionTitle(value: string) {
  return value.toUpperCase().replace(/[^A-Z0-9]+/g, "")
}

function canonicalMeetingsSectionTitle(title: string) {
  const key = compactSectionTitle(title)
  if (key.replace(/^(?:MANUAL)?\d*/, "") === compactSectionTitle(TOMORROW_SYMBOLS_TITLE)) {
    return TOMORROW_SYMBOLS_TITLE
  }
  if (key.includes("TIKETATESTD")) {
    return "(GA) ZHV: TIKETAT E STD?"
  }
  if (key === compactSectionTitle("DET NE PROCES SISTEMIT - SYSTEM TASKS REPORT - LATE?")) {
    return "SYSTEM TASK LATE"
  }
  if (key === compactSectionTitle("DET. PA PROGRES (PINK)?")) {
    return "DET PA PROGRES PINK (FT DHE PRJK)"
  }
  if (key === compactSectionTitle("N- (GA) SHIKOHET COMMON VIEW NESER, VETEM DETYRAT E REJA ME TE KALTER, 08:00 DHE ME DEADLINE?")) {
    return "N- (GA) DET TE REJA LAST WEEK/THIS WEEK/08:00/ME DEADLINE?"
  }
  if (key === compactSectionTitle("N- (GA) DET TE REJA LAST WEEK DHE THIS WEEK, 08:00, ME DEADLINE?")) {
    return "N- (GA) DET TE REJA LAST WEEK/THIS WEEK/08:00/ME DEADLINE?"
  }
  if (key === compactSectionTitle("N- (GA) DET TE REJA LAST WEEK DHE THIS WEEK")) {
    return "N- (GA) DET TE REJA LAST WEEK/THIS WEEK/08:00/ME DEADLINE?"
  }
  if (key === compactSectionTitle("DET TE REJA LAST WEEK DHE THIS WEEK")) {
    return "N- (GA) DET TE REJA LAST WEEK/THIS WEEK/08:00/ME DEADLINE?"
  }
  if (key === compactSectionTitle("TAKIMET PA KRY (KONTROLLO PLATFORMEN)?")) {
    return "TAK STATUSI?"
  }
  if (key === compactSectionTitle("TAKIMET E PA KRYERA ?")) {
    return "TAK STATUSI?"
  }
  if (key === compactSectionTitle("TAK E PA KRYERA?")) {
    return "TAK STATUSI?"
  }
  if (key === compactSectionTitle("TAK STATUSI?")) {
    return "TAK STATUSI?"
  }
  if (key === compactSectionTitle("N- (GA) TAKIMET EXTERNE/ TAKIMET INTERNE/ BZ ME GA/BLLOK?")) {
    return "N- (GA) TAK EXT/TAK INT/BZ ME GA/BLLOK"
  }
  if (key === compactSectionTitle("N- A KA DETYRA 1H PA SLOT?")) {
    return "N- DETYRA 1H PA SLOT?"
  }
  if (key === compactSectionTitle("N- (GA/KA) KUSH KA DET PERSONALISHT?")) {
    return "N- (GA) DET PERSONALISHT?"
  }
  if (key === compactSectionTitle("N- (GA/KA/GENTI) DET PERSONALISHT?")) {
    return "N- DET PERSONALISHT ME KA/GENTIN?"
  }
  if (key === compactSectionTitle("WFC TASKS (KA/GENTI)")) {
    return "N- WFC ME KA/GENTIN?"
  }
  if (key === compactSectionTitle("TASKS PERSONALISHT ME KA/GENTIN?")) {
    return "N- DET PERSONALISHT ME KA/GENTIN?"
  }
  if (key === compactSectionTitle("N- TASKS PERSONALISHT ME KA/GENTIN?")) {
    return "N- DET PERSONALISHT ME KA/GENTIN?"
  }
  if (key === compactSectionTitle("WFC ME KA/GENTIN?")) {
    return "N- WFC ME KA/GENTIN?"
  }
  return title
}

function collapseMeetingsSections(sections: Section[]): Section[] {
  const displayOrder = [
    TOMORROW_SYMBOLS_TITLE,
    "(GA) ZHV: TIKETAT E STD?",
    "SYSTEM TASK LATE",
    "DET PA PROGRES PINK (FT DHE PRJK)",
    "DET TE SHTYERA",
    "DET E KRYERA SOT (AM/PM)",
    HV_DONE_TITLE,
    "PRODUKTE +/- SOT (PCM)",
    "TAK STATUSI?",
    "N- (GA) PV/FESTE?",
    "N- (GA) DET TE REJA LAST WEEK/THIS WEEK/08:00/ME DEADLINE?",
    "N- (GA) TAK EXT/TAK INT/BZ ME GA/BLLOK",
    "N- DETYRA 1H PA SLOT?",
    "N- (GA) DET PERSONALISHT?",
    "N- DET PERSONALISHT ME KA/GENTIN?",
    "N- WFC ME KA/GENTIN?",
  ]
  const placeholder = "(Ploteso manualisht)"
  const byTitle = new Map<string, Section>()
  const extras: Section[] = []
  const seenExtra = new Set<string>()

  const preferBody = (current: string, incoming: string) => {
    const cur = current.trim()
    const inc = incoming.trim()
    if (!cur || cur === placeholder) return incoming || current
    if (!inc || inc === placeholder) return current
    return current
  }

  for (const section of sections) {
    if ([section.title, section.section_key || ""].some((value) =>
      compactSectionTitle(value).replace(/^(?:MANUAL)?\d*/, "") === "AJEMIBRENDAMESATARESMEPROJEKTE"
    )) continue
    const title = canonicalMeetingsSectionTitle((section.section_key || section.title).trim())
    if (!title) continue
    if (displayOrder.includes(title)) {
      const existing = byTitle.get(title)
      byTitle.set(title, {
        section_key: title,
        title: section.section_key ? section.title : title,
        body: existing == null ? section.body : preferBody(existing.body, section.body),
      })
      continue
    }
    const key = compactSectionTitle(title)
    if (!key || seenExtra.has(key)) continue
    seenExtra.add(key)
    extras.push({ ...section, section_key: section.section_key || `manual:${key}`, title: section.title || title })
  }

  const ordered: Section[] = []
  for (const title of displayOrder) {
    const existing = byTitle.get(title)
    if (existing) ordered.push(existing)
  }
  return orderManualReportSections(
    [...extras, ...ordered],
    (section) => sectionGroupLabel(section) === "Manual questions",
  )
}

function sectionGroupLabel(section: Section) {
  const key = compactSectionTitle(section.section_key || section.title)
  if (key.includes("TIKETATESTD")) {
    return "Auto-filled from PrimeFlow"
  }
  const knownAuto = [
    TOMORROW_SYMBOLS_TITLE,
    "(GA) ZHV: TIKETAT E STD?",
    "SYSTEM TASK LATE",
    "DET PA PROGRES PINK (FT DHE PRJK)",
    "DET TE SHTYERA",
    "DET E KRYERA SOT (AM/PM)",
    HV_DONE_TITLE,
    "PRODUKTE +/- SOT (PCM)",
    "N- (GA) PV/FESTE?",
    "N- (GA) TAK EXT/TAK INT/BZ ME GA/BLLOK",
    "N- (GA) DET TE REJA LAST WEEK/THIS WEEK/08:00/ME DEADLINE?",
    "TAK STATUSI?",
    "N- DETYRA 1H PA SLOT?",
    "N- (GA) DET PERSONALISHT?",
    "N- DET PERSONALISHT ME KA/GENTIN?",
    "N- WFC ME KA/GENTIN?",
  ]
  if (knownAuto.some((auto) => compactSectionTitle(auto) === key)) return "Auto-filled from PrimeFlow"
  return "Manual questions"
}

function shouldShowSectionGroup(sections: Section[], index: number) {
  if (index === 0) return true
  return sectionGroupLabel(sections[index]) !== sectionGroupLabel(sections[index - 1])
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

const API = "/meetings-report"
const REPORT_LABEL = "Mbyllja e dites M3"

function sectionPreviewText(value: string) {
  return reportSectionPreviewText(value)
}

function recipientsSummary(recipients: Recipients) {
  const groups = [
    recipients.to.length ? `To: ${recipients.to.join(", ")}` : "",
    recipients.cc.length ? `Cc: ${recipients.cc.join(", ")}` : "",
    recipients.bcc.length ? `Bcc: ${recipients.bcc.join(", ")}` : "",
  ].filter(Boolean)
  return groups.join(" | ") || "-"
}

function todayIso() {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Europe/Tirane", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date())
  return ["year", "month", "day"].map((part) => parts.find(({ type }) => type === part)?.value).join("-")
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

export default function MeetingsReportPage() {
  const { apiFetch, loading: authLoading, user } = useAuth()
  const canAccess = !authLoading && Boolean(user)
  const canManageDelivery = user?.role === "ADMIN" || user?.role === "MANAGER"
  const [reportDate, setReportDate] = React.useState(todayIso())
  const [draft, setDraft] = React.useState<Draft | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const [sending, setSending] = React.useState(false)
  const [preview, setPreview] = React.useState<{ html: string; plain_text: string } | null>(null)
  const [settings, setSettings] = React.useState<ReportSettings | null>(null)
  const [settingsInputs, setSettingsInputs] = React.useState<RecipientInputs>({ to: "", cc: "", bcc: "" })
  const [savingSettings, setSavingSettings] = React.useState(false)
  const [editingSection, setEditingSection] = React.useState<EditingSection | null>(null)
  const [history, setHistory] = React.useState<DeliveryHistory[]>([])
  const [loadingHistory, setLoadingHistory] = React.useState(false)

  const applyDraft = React.useCallback((nextDraft: Draft | null) => {
    if (!nextDraft) {
      setDraft(null)
      return
    }
    setDraft({
      ...nextDraft,
      sections: collapseMeetingsSections(nextDraft.sections || []),
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

  const loadDraft = React.useCallback(async (signal?: AbortSignal) => {
    if (!canAccess) return
    setLoading(true)
    try {
      let res = await apiFetch(`${API}?report_date=${reportDate}`, { cache: "no-store", signal })
      if (res.status === 404 && reportDate === todayIso()) {
        res = await apiFetch(`${API}/generate?report_date=${reportDate}&create_if_missing=true`, { method: "POST", signal })
      }
      if (signal?.aborted) return
      if (res.status === 404) {
        applyDraft(null)
        return
      }
      if (!res.ok) throw new Error(await responseError(res))
      const value = await res.json()
      if (!signal?.aborted) applyDraft(value)
    } catch (error) {
      if (!signal?.aborted) toast.error(`Unable to load ${REPORT_LABEL}`, { description: String(error) })
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [apiFetch, applyDraft, canAccess, reportDate])

  const loadSettings = React.useCallback(async () => {
    if (!canAccess || !canManageDelivery) return
    try {
      const res = await apiFetch(`${API}/settings`)
      if (!res.ok) throw new Error(await responseError(res))
      applySettings(await res.json())
    } catch (error) {
      if (canAccess) toast.error(`Unable to load ${REPORT_LABEL} settings`, { description: String(error) })
    }
  }, [apiFetch, applySettings, canAccess, canManageDelivery])

  const loadHistory = React.useCallback(async () => {
    if (!canAccess) return
    setLoadingHistory(true)
    try {
      const res = await apiFetch(`${API}/history?limit=50`)
      if (!res.ok) throw new Error(await responseError(res))
      setHistory(await res.json())
    } catch (error) {
      toast.error("Unable to load delivery history", { description: String(error) })
    } finally {
      setLoadingHistory(false)
    }
  }, [apiFetch, canAccess])

  React.useEffect(() => {
    if (canAccess) {
      const controller = new AbortController()
      void loadDraft(controller.signal)
      void loadHistory()
      if (canManageDelivery) void loadSettings()
      return () => controller.abort()
    }
  }, [canAccess, canManageDelivery, loadDraft, loadHistory, loadSettings])

  const generate = async () => {
    if (!canAccess) return
    if (draft && !window.confirm("Refresh auto-filled sections for this date? Manual answers will be kept.")) return
    setLoading(true)
    try {
      if (draft) await save(draft)
      const res = await apiFetch(`${API}/generate?report_date=${reportDate}`, { method: "POST" })
      if (!res.ok) throw new Error(await responseError(res))
      applyDraft(await res.json())
      setEditingSection(null)
      toast.success(`${REPORT_LABEL} generated`)
    } catch (error) {
      toast.error("Generate failed", { description: String(error) })
    } finally {
      setLoading(false)
    }
  }

  const save = async (draftToSave: Draft | null = draft): Promise<Draft | null> => {
    if (!draftToSave) return draftToSave
    setSaving(true)
    try {
      const res = await apiFetch(`${API}/${draftToSave.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject: draftToSave.subject, sections: draftToSave.sections }),
      })
      if (!res.ok) throw new Error(await responseError(res))
      const data = await res.json()
      applyDraft(data)
      toast.success("Draft saved")
      return data
    } catch (error) {
      toast.error("Save failed", { description: String(error) })
      return null
    } finally {
      setSaving(false)
    }
  }

  const previewDraft = async () => {
    if (!draft) return
    await save()
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
    const nextDraft = { ...draft, sections }
    setDraft(nextDraft)
    setEditingSection(null)
    void save(nextDraft)
  }

  const addManualQuestion = async (title: string, position: number) => {
    if (!draft) return false
    const sections = addManualReportSection(draft.sections, title, position, (section) => sectionGroupLabel(section) === "Manual questions")
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

  if (!canAccess) return <div className="rounded-md border p-8">{REPORT_LABEL} access required.</div>

  return (
    <div className="mx-auto max-w-[1480px] space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b pb-5">
        <div className="flex items-center gap-3">
          <div className="flex size-11 items-center justify-center rounded-md bg-slate-900 text-white"><Mail className="size-5" /></div>
          <div>
            <h1 className="text-2xl font-semibold">{REPORT_LABEL}</h1>
            <p className="text-sm text-muted-foreground">Daily report workspace</p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => void Promise.all([loadDraft(), loadHistory()])} disabled={loading || loadingHistory}>
            <RefreshCw className={loading || loadingHistory ? "animate-spin" : ""} /> Refresh
          </Button>
          <Button onClick={() => void generate()} disabled={loading}>
            <RefreshCw className={loading ? "animate-spin" : ""} /> {loading ? "Generating..." : "Generate report"}
          </Button>
        </div>
      </div>

      <Tabs defaultValue="report" className="gap-5">
        <TabsList className="h-10 rounded-md">
          <TabsTrigger value="report"><Pencil /> Report</TabsTrigger>
          <TabsTrigger value="history"><History /> Send history</TabsTrigger>
          {canManageDelivery ? <TabsTrigger value="settings"><Settings /> Settings</TabsTrigger> : null}
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
              <div className="grid gap-4 border-y bg-slate-50/70 px-4 py-4 lg:grid-cols-[190px_minmax(320px,1fr)_auto]">
                <div>
                  <Label>Report date</Label>
                  <Input className="mt-1 bg-white" type="date" value={reportDate} onChange={(event) => setReportDate(event.target.value)} />
                </div>
                <div>
                  <Label>Email subject</Label>
                  <Input
                    className="mt-1 bg-white"
                    value={draft?.subject || ""}
                    onChange={(event) => draft && setDraft({ ...draft, subject: event.target.value })}
                    placeholder="Generate a draft first"
                  />
                </div>
                <div className="flex flex-wrap items-end gap-2">
                  <Button variant="outline" onClick={() => void save()} disabled={!draft || saving}><Save /> Save</Button>
                  <Button variant="outline" onClick={() => void previewDraft()} disabled={!draft || saving}><Eye /> Email preview</Button>
                  {canManageDelivery ? <Button onClick={() => void sendDraft()} disabled={!draft || sending}><Send /> Send now</Button> : null}
                </div>
              </div>
              {draft ? (
                <div className="grid border md:grid-cols-4">
                  {[
                    [CalendarDays, "Report date", draft.report_date],
                    [CalendarDays, "Tomorrow", draft.tomorrow_date],
                    [CheckCircle2, "Status", draft.status],
                    [Clock3, "Last update", formatDateTimeInTimezone(draft.updated_at, "Europe/Tirane")],
                  ].map(([Icon, label, value], index) => {
                    const MetaIcon = Icon as typeof CalendarDays
                    return (
                      <div key={String(label)} className={index < 3 ? "border-b p-4 md:border-b-0 md:border-r" : "p-4"}>
                        <div className="flex items-center gap-2 text-xs font-medium uppercase text-muted-foreground"><MetaIcon className="size-4" />{String(label)}</div>
                        <div className="mt-1.5 text-sm font-semibold">{String(value || "-")}</div>
                      </div>
                    )
                  })}
                </div>
              ) : null}
            </div>
          </details>

          {draft ? (
            <>
              <div className="space-y-4">
                {!draft.sections.some((section) => sectionGroupLabel(section) === "Manual questions") && (
                  <div className="flex justify-end">
                    <ManualReportQuestionAdd onAdd={addManualQuestion} disabled={saving} />
                  </div>
                )}
                {draft.sections.map((section, index) => {
                  const isSymbolsTable = canonicalMeetingsSectionTitle(section.section_key || section.title) === TOMORROW_SYMBOLS_TITLE
                  const symbolsHtml = isSymbolsTable && draft.generated_snapshot?.tomorrow_symbols_html
                  const isEditing = !isSymbolsTable && editingSection?.index === index
                  return (
                    <React.Fragment key={`${section.title}-${index}`}>
                      {shouldShowSectionGroup(draft.sections, index) ? (
                        <div className="flex items-center justify-between gap-2 rounded-md border bg-slate-100 px-3 py-2 text-xs font-bold uppercase tracking-wide text-slate-700">
                          {sectionGroupLabel(section)}
                          {sectionGroupLabel(section) === "Manual questions" ? <ManualReportQuestionAdd onAdd={addManualQuestion} disabled={saving} /> : null}
                        </div>
                      ) : null}
                      <section className="rounded-md border bg-white p-4 shadow-sm">
                        <div className="flex flex-wrap items-start gap-3">
                          <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-slate-100 text-sm font-semibold text-slate-700">{index + 1}</div>
                          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-3">
                            {isEditing ? (
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
                            ) : (
                              <h2 className="text-sm font-semibold leading-5">{section.title}</h2>
                            )}
                            {!isEditing && !isSymbolsTable ? (
                              <div className="flex items-center gap-2">
                                <Button variant="outline" size="sm" onClick={() => openSectionEditor(index)}><Pencil /> Edit</Button>
                                {user?.role === "ADMIN" && isCustomManualReportSection(section) ? (
                                  <ManualReportQuestionDelete title={section.title} disabled={saving} onDelete={() => deleteManualQuestion(section.section_key!)} />
                                ) : null}
                              </div>
                            ) : null}
                          </div>
                        </div>

                        {isEditing ? (
                          <ReportSectionFieldEditor
                            key={`edit-${index}`}
                            lines={editingSection.lines}
                            emptyPlaceholder={section.body.trim() === MANUAL_PLACEHOLDER ? MANUAL_PLACEHOLDER : undefined}
                            onCancel={() => setEditingSection(null)}
                            onSave={applySectionEditor}
                          />
                        ) : symbolsHtml ? (
                          <M3TomorrowSymbolsTable html={symbolsHtml} />
                        ) : (
                          <ReportSectionPreview
                            body={sectionPreviewText(section.body)}
                            projectColumnWidth={
                              canonicalMeetingsSectionTitle(section.section_key || section.title) ===
                              "DET PA PROGRES PINK (FT DHE PRJK)"
                                ? "140px"
                                : undefined
                            }
                            filterCreatedWeek={
                              canonicalMeetingsSectionTitle(section.title) ===
                              "N- (GA) DET TE REJA LAST WEEK/THIS WEEK/08:00/ME DEADLINE?"
                            }
                          />
                        )}
                      </section>
                    </React.Fragment>
                  )
                })}
              </div>
            </>
          ) : (
            <div className="border-y py-16 text-center text-sm text-muted-foreground">No draft for this date.</div>
          )}
        </TabsContent>

        <TabsContent value="history" className="space-y-3">
          <div className="flex items-center justify-between">
            <div><h2 className="font-semibold">Report delivery history</h2><p className="text-sm text-muted-foreground">Last 50 sent reports</p></div>
            <Button variant="outline" size="sm" onClick={() => void loadHistory()} disabled={loadingHistory}><RefreshCw className={loadingHistory ? "animate-spin" : ""} /> Refresh</Button>
          </div>
          <div className="rounded-md border bg-white">
            <Table>
              <TableHeader><TableRow><TableHead>Date</TableHead><TableHead>Sent at</TableHead><TableHead>Recipients</TableHead><TableHead>Subject</TableHead><TableHead>Status</TableHead></TableRow></TableHeader>
              <TableBody>
                {history.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="font-medium">{item.report_date}</TableCell>
                    <TableCell>{formatDateTimeInTimezone(item.sent_at, "Europe/Tirane")}</TableCell>
                    <TableCell className="max-w-[420px] whitespace-normal">{recipientsSummary(item.recipients)}</TableCell>
                    <TableCell className="max-w-[420px] truncate">{item.subject}</TableCell>
                    <TableCell><Badge variant={item.last_error ? "destructive" : "secondary"}>{item.last_error ? "ERROR" : item.status}</Badge></TableCell>
                  </TableRow>
                ))}
                {!loadingHistory && history.length === 0 ? <TableRow><TableCell colSpan={5} className="h-24 text-center text-muted-foreground">No sent reports yet.</TableCell></TableRow> : null}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        {canManageDelivery ? (
          <TabsContent value="settings">
            {settings ? (
              <div className="space-y-5 rounded-md border bg-white p-5">
                <div className="flex flex-wrap items-center justify-between gap-4 border-b pb-4">
                  <div className="flex items-center gap-3"><div className="flex size-9 items-center justify-center rounded-md bg-slate-100"><ShieldCheck className="size-5" /></div><div><h2 className="font-semibold">Automatic delivery</h2><p className="text-sm text-muted-foreground">Administrator access</p></div></div>
                  <button
                    type="button"
                    aria-pressed={settings.is_active}
                    aria-label={settings.is_active ? "Turn automatic send off" : "Turn automatic send on"}
                    onClick={() => setSettings({ ...settings, is_active: !settings.is_active })}
                    className={settings.is_active ? "relative h-8 w-14 rounded-full bg-emerald-500 p-1" : "relative h-8 w-14 rounded-full bg-slate-300 p-1"}
                  ><span className={settings.is_active ? "absolute right-1 top-1 size-6 rounded-full bg-white shadow" : "absolute left-1 top-1 size-6 rounded-full bg-white shadow"} /></button>
                </div>
                <div className="grid gap-4 lg:grid-cols-[180px_240px_1fr]">
                  <div><Label>Automatic send time</Label><div className="mt-1 flex h-10 items-center rounded-md border bg-muted/40 px-3 text-sm">16:30</div></div>
                  <div><Label>Timezone</Label><Input className="mt-1" value={settings.timezone} onChange={(event) => setSettings({ ...settings, timezone: event.target.value })} /></div>
                  <div><Label>Delivery days</Label><div className="mt-1 flex flex-wrap gap-2">{["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((label, day) => <Button key={label} type="button" size="sm" variant={settings.weekdays.includes(day) ? "default" : "outline"} onClick={() => toggleWeekday(day)}>{label}</Button>)}</div></div>
                </div>
                <div className="grid gap-4 md:grid-cols-3">
                  <div><Label>To</Label><Input className="mt-1" value={settingsInputs.to} onChange={(event) => updateSettingsRecipients("to", event.target.value)} /></div>
                  <div><Label>Cc</Label><Input className="mt-1" value={settingsInputs.cc} onChange={(event) => updateSettingsRecipients("cc", event.target.value)} /></div>
                  <div><Label>Bcc</Label><Input className="mt-1" value={settingsInputs.bcc} onChange={(event) => updateSettingsRecipients("bcc", event.target.value)} /></div>
                </div>
                <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
                  <div className="text-sm text-muted-foreground">Last automatic run: {formatDateTimeInTimezone(settings.last_run_date, settings.timezone)}</div>
                  <Button onClick={() => void saveSettings()} disabled={savingSettings}><Save /> Save settings</Button>
                </div>
              </div>
            ) : <div className="border-y py-12 text-center text-sm text-muted-foreground">Loading settings...</div>}
          </TabsContent>
        ) : null}
      </Tabs>

      <Dialog open={Boolean(preview)} onOpenChange={(open) => !open && setPreview(null)}>
        <DialogContent className="max-w-5xl">
          <DialogHeader>
            <DialogTitle>Email preview</DialogTitle>
          </DialogHeader>
          {preview ? <iframe title={`${REPORT_LABEL} preview`} srcDoc={preview.html} className="h-[650px] w-full rounded border bg-white" /> : null}
        </DialogContent>
      </Dialog>

    </div>
  )
}
