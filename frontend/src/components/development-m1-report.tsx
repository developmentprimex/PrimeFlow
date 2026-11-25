"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { Minus, Plus } from "lucide-react"
import { toast } from "sonner"

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

type M1Report = {
  date: string
  item_sections: Record<string, string>
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

export function useDevelopmentM1Report(enabled: boolean) {
  const { apiFetch } = useAuth()
  const confirm = useConfirm()
  const [report, setReport] = useState<M1Report | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  const [savingNote, setSavingNote] = useState<string | null>(null)
  const [cancelingMeeting, setCancelingMeeting] = useState<string | null>(null)

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    async function load() {
      setLoading(true)
      setFailed(false)
      try {
        const response = await apiFetch("/departments/development/m1", { signal: controller.signal, cache: "no-store" })
        if (!response.ok) throw new Error("M1 report request failed")
        const data: M1Report = await response.json()
        if (!controller.signal.aborted) setReport(data)
      } catch {
        if (!controller.signal.aborted) setFailed(true)
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [apiFetch, enabled, refresh])

  async function markDiscussed(id: string) {
    setSavingNote(id)
    try {
      const response = await apiFetch(`/ga-notes/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_discussed: true }),
      })
      if (!response.ok) throw new Error("PX Note update failed")
      setRefresh((previous) => previous + 1)
    } catch {
      toast.error("Shënimi nuk u shënua si i diskutuar.")
    } finally {
      setSavingNote(null)
    }
  }

  async function cancelMeeting(meeting: M1Meeting, title: string) {
    if (cancelingMeeting) return
    setCancelingMeeting(meeting.id)
    try {
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

      const response = await apiFetch(`/meetings/${meeting.id}/occurrence-status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ occurrence_date: meeting.date, status: "canceled" }),
      })
      if (!response.ok) throw new Error("Meeting cancellation failed")
      setReport((previous) => previous && {
        ...previous,
        sections: previous.sections.map((section) => ({
          ...section,
          rows: section.rows
            .filter((row) => meeting.type !== "external" || (
              row.meeting?.preExternalMeetingId !== meeting.id && row.meeting?.pairedExternalMeetingId !== meeting.id
            ))
            .map((row) => row.meeting?.id === meeting.id && row.meeting.date === meeting.date
              ? { ...row, canceled: true, meeting: { ...row.meeting, occurrenceStatus: "canceled" } }
              : row),
        })),
      })
      setRefresh((previous) => previous + 1)
    } catch {
      toast.error("Takimi nuk u anulua. Rifresko raportin dhe provo përsëri.")
    } finally {
      setCancelingMeeting(null)
    }
  }

  return {
    report, loading, failed, savingNote, markDiscussed, cancelingMeeting, cancelMeeting,
    reload: () => setRefresh((previous) => previous + 1),
  }
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
    held: meeting.occurrenceStatus === "held",
  }
}

export function DevelopmentM1Answer({
  section, readOnly, pending, savingNote, markDiscussed, cancelingMeeting, cancelMeeting,
}: {
  section: M1Report["sections"][number]
  readOnly: boolean
  pending: boolean
  savingNote: string | null
  markDiscussed: (id: string) => void
  cancelingMeeting: string | null
  cancelMeeting: (meeting: M1Meeting, title: string) => void
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
        const labels = meeting ? undefined : row.labels?.filter((label) => !row.task_status_labels?.includes(label))
        return (
          <li key={row.id} className={`flex min-w-0 items-start gap-2 rounded-lg border px-3 py-2 text-sm ${horizontal ? "flex-col" : "flex-wrap"} ${meeting?.tone ?? ""}`}
            style={row.color ? { backgroundColor: meeting ? undefined : row.color, borderColor: row.border, color: "#0f172a" } : undefined}>
            <div className={horizontal ? "w-full flex-1 [overflow-wrap:anywhere]" : "min-w-0 flex-1 break-words"}>
              {meeting && (meeting.time || meeting.calendar || meeting.manual || meeting.held) ? (
                <div className="mb-1 flex flex-wrap items-center gap-1">
                  {meeting.time ? <span className="meeting-time-chip">{meeting.time}</span> : null}
                  {meeting.calendar ? <span className="calendar-meeting-badge">CAL</span> : null}
                  {meeting.manual ? <span className="manual-meeting-badge">MANUAL</span> : null}
                  {meeting.held ? <span className="rounded border border-green-300 bg-green-100 px-1.5 py-0.5 text-xs text-green-800">Mbajtur</span> : null}
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
                {row.canceled ? <span className="sr-only">Anuluar. </span> : null}
                {row.task_status_labels?.length ? (
                  <span className="sr-only">{row.task_status_labels.join(", ")}. </span>
                ) : null}
                {row.email_heading ? (
                  <span className="block max-w-[80ch] truncate" title={row.email_heading}>{row.email_heading}</span>
                ) : (
                  <span className={row.canceled ? "line-through decoration-red-600 decoration-2" : undefined}>
                    {row.href ? <Link href={row.href} className="font-medium underline-offset-4 hover:underline">{row.title}</Link> : row.title}
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
              {row.detail && !row.email_heading ? <p className="whitespace-pre-line text-xs">{row.detail}</p> : null}
              {row.meeting_url && !row.canceled ? (
                <a href={row.meeting_url} target="_blank" rel="noreferrer" className="text-xs font-medium underline">
                  Hap takimin
                </a>
              ) : null}
            </div>
            {section.key === "notes" && !readOnly ? (
              <Button type="button" size="sm" variant="outline" disabled={pending || savingNote !== null}
                onClick={() => markDiscussed(row.id)}>
                {savingNote === row.id ? "Po ruhet…" : "Shëno si të diskutuar"}
              </Button>
            ) : null}
            {occurrence?.id && !row.canceled && !readOnly ? (
              <Button type="button" size="sm" variant="outline"
                disabled={pending || cancelingMeeting !== null}
                aria-label={`Anulo takimin ${row.title}`}
                onClick={() => cancelMeeting(occurrence, row.title)}>
                {cancelingMeeting === occurrence.id ? "Po anulohet…" : "Anulo takimin"}
              </Button>
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
