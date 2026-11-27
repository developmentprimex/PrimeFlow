"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { ChevronDown, Minus, Plus } from "lucide-react"
import { toast } from "sonner"

import { OriginalEmailLink } from "@/components/note-email-preview"
import { MorningReorganization, REORGANIZATION_SECTION } from "@/components/morning-reorganization"
import { useConfirm } from "@/components/providers/confirm-dialog-provider"
import { TaskMarkerComment } from "@/components/task-marker-comment"
import { TaskMarkerDisplay } from "@/components/task-marker-display"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/lib/auth"
import { formatTimeLabel } from "@/lib/calendar-meeting-time"
import { formatDateDMY } from "@/lib/dates"
import { personInitials } from "@/lib/person-initials"
import {
  internalMeetingLegendTone,
  internalMeetingRelation,
  isCalendarLinkedInternalMeeting,
  isManualInternalMeeting,
  meetingLegendTone,
  type InternalMeetingToneInput,
} from "@/lib/meeting-tone"

type M1Meeting = InternalMeetingToneInput & {
  id: string
  date: string
  type: "external" | "internal"
  time?: string
  calendarImported?: boolean
  calendarCategories?: string[]
  occurrenceStatus?: string
}

type MeetingStatus = "" | "held" | "canceled"
type NoteAction = "close" | "discuss"
type NoteUpdate = { id: string; action: NoteAction }

type DevelopmentMeetingReport = {
  date: string
  cutoff?: string
  item_sections: Record<string, string>
  item_titles?: Record<string, string>
  hidden_item_ids?: string[]
  sections: {
    key: string
    title: string
    message: string | null
    rows: {
      id: string
      title: string
      detail: string
      email_heading?: string
      email_body?: string
      heading?: boolean
      href?: string
      meeting_url?: string
      labels?: string[]
      task_status_labels?: string[]
      task_assignees?: string[]
      meeting?: M1Meeting
      color?: string
      border?: string
      canceled?: boolean
      marker?: string | null
      marker_by_ga?: boolean
      marker_comment?: string | null
    }[]
  }[]
}

export function useDevelopmentMeetingReport(slot: "M1" | "M2" | "M3", enabled: boolean) {
  const { apiFetch } = useAuth()
  const confirm = useConfirm()
  const [report, setReport] = useState<DevelopmentMeetingReport | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  const [savingNote, setSavingNote] = useState<NoteUpdate | null>(null)
  const [savingMeeting, setSavingMeeting] = useState<{ id: string; date: string } | null>(null)

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    async function load() {
      setLoading(true)
      setFailed(false)
      try {
        const response = await apiFetch(`/departments/development/${slot.toLowerCase()}`, {
          signal: controller.signal, cache: "no-store",
        })
        if (!response.ok) throw new Error(`${slot} report request failed`)
        const data: DevelopmentMeetingReport = await response.json()
        if (!controller.signal.aborted) setReport(data)
      } catch {
        if (!controller.signal.aborted) setFailed(true)
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [apiFetch, enabled, refresh, slot])

  async function updateNote(id: string, action: NoteAction) {
    if (savingNote) return
    setSavingNote({ id, action })
    try {
      const response = await apiFetch(`/ga-notes/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(action === "close" ? { status: "CLOSED" } : { is_discussed: true }),
      })
      if (!response.ok) throw new Error("PX Note update failed")
      setRefresh((previous) => previous + 1)
    } catch {
      toast.error(action === "close" ? "Shënimi nuk u mbyll." : "Shënimi nuk u shënua si i diskutuar.")
    } finally {
      setSavingNote(null)
    }
  }

  async function updateMeetingStatus(meeting: M1Meeting, title: string, status: MeetingStatus) {
    if (savingMeeting) return
    setSavingMeeting({ id: meeting.id, date: meeting.date })
    try {
      const canceled = status === "canceled"
      if (canceled) {
        const effects = meeting.type === "external"
          ? "Takimet interne të lidhura dhe detyrat e gjeneruara për këto takime fshihen, nëse ekzistojnë."
          : "Detyrat e gjeneruara nga ky takim fshihen, nëse ekzistojnë."
        const confirmed = await confirm({
          title: "Ta anulosh takimin?",
          description: `${title} · ${formatDateDMY(meeting.date)}\n\n${effects}`,
          confirmLabel: "Anulo takimin",
          cancelLabel: "Kthehu",
          variant: "destructive",
        })
        if (!confirmed) return
      }

      const response = await apiFetch(`/meetings/${meeting.id}/occurrence-status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ occurrence_date: meeting.date, status }),
      })
      if (!response.ok) throw new Error("Meeting status update failed")
      setReport((previous) => previous && {
        ...previous,
        sections: previous.sections.map((section) => ({
          ...section,
          rows: section.rows
            .filter((row) => !canceled || meeting.type !== "external" || (
              row.meeting?.preExternalMeetingId !== meeting.id && row.meeting?.pairedExternalMeetingId !== meeting.id
            ))
            .map((row) => row.meeting?.id === meeting.id && row.meeting.date === meeting.date
              ? { ...row, canceled, meeting: { ...row.meeting, occurrenceStatus: status } }
              : row),
        })),
      })
      setRefresh((previous) => previous + 1)
    } catch {
      toast.error("Statusi i takimit nuk u ruajt. Rifresko raportin dhe provo përsëri.")
    } finally {
      setSavingMeeting(null)
    }
  }

  return {
    report, loading, failed, savingNote, updateNote, savingMeeting, updateMeetingStatus, refresh,
    reload: () => setRefresh((previous) => previous + 1),
  }
}

type DevelopmentReorganization = { date: string; body: string; can_edit: boolean }

export function DevelopmentMeetingReorganization({ slot, refresh, reload }: {
  slot: "M1" | "M2"
  refresh: number
  reload: () => void
}) {
  const { apiFetch } = useAuth()
  const path = `/departments/development/${slot.toLowerCase()}/reorganization`
  const [report, setReport] = useState<DevelopmentReorganization | null>(null)
  const [draft, setDraft] = useState<{ date: string; body: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [saving, setSaving] = useState(false)
  const body = draft && draft.date === report?.date ? draft.body : report?.body ?? ""

  useEffect(() => {
    if (saving) return
    const controller = new AbortController()
    async function load() {
      setLoading(true)
      setFailed(false)
      try {
        const response = await apiFetch(path, { cache: "no-store", signal: controller.signal })
        if (!response.ok) throw new Error("Reorganization request failed")
        const data: DevelopmentReorganization = await response.json()
        if (!controller.signal.aborted) setReport(data)
      } catch {
        if (!controller.signal.aborted) setFailed(true)
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [apiFetch, path, refresh, saving])

  async function save() {
    if (!report?.can_edit || loading || failed || saving) return
    setSaving(true)
    try {
      const response = await apiFetch(path, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report_date: report.date, body }),
      })
      if (response.status === 409) throw new Error("Data e raportit ndryshoi. Rifresko dhe provo përsëri.")
      if (!response.ok) throw new Error("Përgjigjja e riorganizimit nuk u ruajt.")
      const saved: { body: string } = await response.json()
      setReport({ ...report, body: saved.body })
      setDraft(null)
      toast.success("Përgjigjja e riorganizimit u ruajt.")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Përgjigjja e riorganizimit nuk u ruajt.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <section aria-label={REORGANIZATION_SECTION}
      className="rounded-xl border border-slate-200 bg-background p-4">
      <h3 className="text-sm font-semibold">{REORGANIZATION_SECTION}</h3>
      {failed ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <p role="alert" className="text-sm text-destructive">Përgjigjja e riorganizimit nuk u ngarkua.</p>
          <Button type="button" variant="outline" size="sm" onClick={reload}>Rifresko riorganizimin</Button>
        </div>
      ) : !report ? (
        <p className="mt-2 text-sm text-muted-foreground">Po ngarkohet përgjigjja e ruajtur.</p>
      ) : null}
      <MorningReorganization body={body} showAllFollowUps
        readOnly={report?.can_edit !== true} saving={saving} saveDisabled={loading || failed}
        onChange={(next) => { if (report) setDraft({ date: report.date, body: next }) }}
        onSave={() => void save()} />
    </section>
  )
}

function meetingAppearance(meeting: M1Meeting) {
  const isInternal = meeting.type === "internal"
  return {
    tone: isInternal ? internalMeetingLegendTone(meeting) : meetingLegendTone({
      meetingType: "external",
      categories: meeting.calendarCategories,
      recurrenceType: meeting.recurrence_type,
      calendarImported: meeting.calendarImported,
    }),
    time: formatTimeLabel(meeting.time),
    calendar: isInternal ? isCalendarLinkedInternalMeeting(meeting) : meeting.calendarImported,
    manual: isInternal && isManualInternalMeeting(meeting),
    relation: isInternal ? internalMeetingRelation(meeting) : undefined,
  }
}

export function DevelopmentMeetingAnswer({
  section, canUpdateMeetingStatus, pending, savingNote, updateNote, savingMeeting, updateMeetingStatus,
}: {
  section: DevelopmentMeetingReport["sections"][number]
  canUpdateMeetingStatus: boolean
  pending: boolean
  savingNote: NoteUpdate | null
  updateNote: (id: string, action: NoteAction) => void
  savingMeeting: { id: string; date: string } | null
  updateMeetingStatus: (meeting: M1Meeting, title: string, status: MeetingStatus) => void
}) {
  const emailRows = section.rows.filter((row) => row.email_heading)
  const groups: { horizontal: boolean; rows: typeof section.rows }[] = []
  for (const row of section.rows) {
    if (row.email_heading) continue
    const horizontal = Boolean(row.meeting)
    const previous = groups.at(-1)
    if (previous?.horizontal === horizontal) previous.rows.push(row)
    else groups.push({ horizontal, rows: [row] })
  }
  const noteNumbers = section.key === "notes"
    ? new Map([...groups.flatMap((group) => group.rows), ...emailRows].map((row, index) => [row.id, index + 1]))
    : undefined

  const renderRows = (rows: typeof section.rows, horizontal = false) => (
    <ul key={rows[0].id}
      className={horizontal
        ? "grid min-w-0 grid-flow-col auto-cols-[min(100%,20rem)] gap-2 overflow-x-auto p-1 print:grid-flow-row print:auto-cols-auto print:overflow-visible"
        : "space-y-2"}
      tabIndex={horizontal && rows.length > 1 ? 0 : undefined}
      aria-label={horizontal ? section.title : undefined}>
      {(horizontal ? [...rows].sort((a, b) => Number(Boolean(a.canceled)) - Number(Boolean(b.canceled))) : rows).map((row) => {
        if (row.heading) return <li key={row.id} className="pt-1 text-sm font-semibold">{row.title}</li>
        const occurrence = row.meeting
        const meeting = occurrence ? meetingAppearance(occurrence) : undefined
        const meetingStatus: MeetingStatus = row.canceled ? "canceled" : occurrence?.occurrenceStatus === "held" ? "held" : ""
        const showStatusSelect = Boolean(occurrence?.id && canUpdateMeetingStatus)
        const savingStatus = Boolean(savingMeeting && savingMeeting.id === occurrence?.id && savingMeeting.date === occurrence.date)
        const savingNoteAction = savingNote?.id === row.id ? savingNote.action : undefined
        const noteNumber = noteNumbers?.get(row.id)
        const labels = meeting ? undefined : row.labels?.filter((label) => !row.task_status_labels?.includes(label))
        const isEmailMessage = section.key === "emails" && row.email_body !== undefined
        return (
          <li key={row.id} className={`flex min-w-0 items-start gap-2 rounded-lg border px-3 py-2 text-sm ${horizontal ? "flex-col" : "flex-wrap"} ${meeting?.tone ?? ""}`}
            style={row.color ? { backgroundColor: meeting ? undefined : row.color, borderColor: row.border, color: "#0f172a" } : undefined}>
            {noteNumber !== undefined ? (
              <span className="min-w-6 shrink-0 text-right text-xs font-semibold leading-5 tabular-nums text-slate-600">{noteNumber}.</span>
            ) : null}
            <div className={horizontal ? "w-full flex-1 [overflow-wrap:anywhere]" : "min-w-0 flex-1 break-words"}>
              {occurrence && meeting && (showStatusSelect || meeting.time || meeting.calendar || meeting.manual || meetingStatus) ? (
                <div className="mb-1 flex flex-wrap items-center gap-1">
                  {showStatusSelect ? (
                    <select
                      className="h-[22px] max-w-[92px] rounded-md border border-slate-300 bg-white px-1 py-px text-[11px] font-bold text-slate-700 data-[status=held]:border-green-300 data-[status=held]:bg-green-100 data-[status=held]:text-green-800 data-[status=canceled]:border-red-300 data-[status=canceled]:bg-red-100 data-[status=canceled]:text-red-800 print:hidden"
                      data-status={meetingStatus}
                      value={meetingStatus}
                      disabled={pending || savingMeeting !== null}
                      aria-label={`Statusi i takimit: ${row.title}`}
                      aria-busy={savingStatus}
                      onChange={(event) => updateMeetingStatus(occurrence, row.title, event.currentTarget.value as MeetingStatus)}
                    >
                      <option value="" aria-label="Pa status" />
                      <option value="held">Mbajtur</option>
                      <option value="canceled">Anuluar</option>
                    </select>
                  ) : null}
                  {meeting.time ? <span className="meeting-time-chip">{meeting.time}</span> : null}
                  {meeting.calendar ? <span className="calendar-meeting-badge">CAL</span> : null}
                  {meeting.manual ? <span className="manual-meeting-badge">MANUAL</span> : null}
                  {meetingStatus ? (
                    <span className={`rounded border px-1.5 py-0.5 text-xs ${showStatusSelect ? "hidden print:inline" : ""} ${
                      meetingStatus === "held" ? "border-green-300 bg-green-100 text-green-800" : "border-red-300 bg-red-100 text-red-800"
                    }`}>
                      {meetingStatus === "held" ? "Mbajtur" : "Anuluar"}
                    </span>
                  ) : null}
                </div>
              ) : null}
              {labels?.length || row.marker ? (
                <div className="mb-1 flex flex-wrap items-center gap-1">
                  {labels?.map((label, labelIndex) => (
                    <span key={labelIndex} className="rounded border border-current/20 px-1.5 py-0.5 text-xs font-medium">
                      {label}
                    </span>
                  ))}
                  {row.marker ? (
                    <span className="rounded border border-blue-300 bg-blue-50 px-1.5 py-0.5 text-xs font-bold text-red-700">
                      <TaskMarkerDisplay value={row.marker} byGa={row.marker_by_ga} />
                    </span>
                  ) : null}
                </div>
              ) : null}
              {row.marker_comment ? <TaskMarkerComment comment={row.marker_comment} taskId={row.id} /> : null}
              <div>
                {meeting?.relation ? (
                  <span className="meeting-relation-badge" title={`${meeting.relation === "PARA" ? "Para" : "Pas"} takimit extern`}>
                    {meeting.relation}
                  </span>
                ) : null}
                {row.task_status_labels?.length ? (
                  <span className="sr-only">{row.task_status_labels.join(", ")}. </span>
                ) : null}
                {row.email_heading ? (
                  <span className="block max-w-[80ch] truncate" title={row.email_heading}>{row.email_heading}</span>
                ) : isEmailMessage ? (
                  <details className="group/email-message">
                    <summary className="group/subject flex cursor-pointer list-none items-start justify-between gap-2 rounded [overflow-wrap:anywhere] focus-visible:outline-2 focus-visible:outline-offset-2 [&::-webkit-details-marker]:hidden">
                      <span>
                        <span className="font-medium group-hover/subject:underline">{row.title}</span>
                        {row.detail ? <span className="block text-xs">{row.detail}</span> : null}
                      </span>
                      <ChevronDown aria-hidden="true" className="size-4 shrink-0 group-open/email-message:rotate-180 print:hidden" />
                    </summary>
                    <OriginalEmailLink sourceUrl={row.href} />
                    <div className="mt-2 max-h-72 overflow-y-auto overscroll-contain whitespace-pre-wrap rounded border bg-background p-3 [overflow-wrap:anywhere] print:hidden"
                      tabIndex={0} aria-label="Emaili i plotë">
                      {row.email_body || "Ky email nuk ka tekst."}
                    </div>
                  </details>
                ) : (
                  <span className={row.canceled ? "line-through decoration-red-600 decoration-2" : undefined}>
                    {row.href?.startsWith("http") ? (
                      <a href={row.href} target="_blank" rel="noreferrer" className="font-medium underline-offset-4 hover:underline">{row.title}</a>
                    ) : row.href ? (
                      <Link href={row.href} className="font-medium underline-offset-4 hover:underline">{row.title}</Link>
                    ) : row.title}
                  </span>
                )}
              </div>
              {row.task_assignees?.length ? (
                <div className="mt-1 flex flex-wrap gap-1">
                  {row.task_assignees.map((name) => (
                    <span key={name} title={name} className="inline-flex h-6 min-w-6 items-center justify-center rounded-full border border-slate-300 bg-slate-200 px-1.5 text-[10px] font-bold leading-none text-slate-900">
                      {personInitials(name)}
                    </span>
                  ))}
                </div>
              ) : null}
              {row.detail && !row.email_heading && !isEmailMessage ? <p className="whitespace-pre-line text-xs">{row.detail}</p> : null}
              {row.meeting_url && !row.canceled ? (
                <a href={row.meeting_url} target="_blank" rel="noreferrer" className="text-xs font-medium underline">
                  Hap takimin
                </a>
              ) : null}
            </div>
            {section.key === "notes" ? (
              <div className="flex flex-wrap items-center gap-2 print:hidden" aria-busy={Boolean(savingNoteAction)}>
                <Button type="button" size="sm" variant="outline" disabled={pending || savingNote !== null}
                  className="h-6 px-2 text-[11px] border-dashed border-slate-300 bg-white text-slate-500 hover:border-emerald-300 hover:bg-emerald-50 hover:text-emerald-700"
                  title="Shëno si të diskutuar"
                  onClick={() => updateNote(row.id, "discuss")}>
                  YES
                </Button>
                <Button type="button" size="sm" variant="outline" disabled={pending || savingNote !== null}
                  className="h-7 text-xs border-emerald-200 text-emerald-700 hover:bg-emerald-50"
                  onClick={() => updateNote(row.id, "close")}>
                  Close
                </Button>
              </div>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
  return (
    <div className="mt-2 space-y-2">
      {groups.map(({ rows, horizontal }) => renderRows(rows, horizontal))}
      {emailRows.length ? (
        <details className="group/email rounded-lg border px-3 py-2">
          <summary className="flex cursor-pointer list-none items-center gap-2 text-sm font-medium [&::-webkit-details-marker]:hidden">
            <Plus className="size-4 group-open/email:hidden" aria-hidden="true" />
            <Minus className="hidden size-4 group-open/email:block" aria-hidden="true" />
            Email-et ({emailRows.length})
          </summary>
          <div className="mt-2">{renderRows(emailRows)}</div>
        </details>
      ) : null}
      {section.message || !section.rows.length ? (
        <p className="text-sm text-muted-foreground">{section.message || "Nuk ka për sot."}</p>
      ) : null}
    </div>
  )
}
