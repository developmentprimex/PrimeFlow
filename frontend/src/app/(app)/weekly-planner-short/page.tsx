"use client"

import Link from "next/link"
import { ChevronRight, RefreshCw } from "lucide-react"
import { useEffect, useId, useRef, useState } from "react"
import type { ReactNode } from "react"
import { toast } from "sonner"
import { InternalMeetingCreateDialog } from "@/components/internal-meeting-create-dialog"
import { useConfirm } from "@/components/providers/confirm-dialog-provider"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/lib/auth"
import { getPersonalTaskGroup } from "@/lib/common-personal-task"
import { internalMeetingDateOn } from "@/lib/internal-meeting-list"
import { getPlainMarkedText } from "@/lib/note-markup"
import { personInitials } from "@/lib/person-initials"
import { isPxJavCommentDeferred } from "@/lib/px-jav-planning"
import { taskDateKey } from "@/lib/task-calendar-date"
import type { Meeting, MeetingOccurrenceStatus, PlanNote, Task, TaskAssignee, User } from "@/lib/types"
import { fetchUsersLookupCached } from "@/lib/users-cache"

const questions = [
  "KA/GA: FESTA/PV PER DY JAVET E ARDHSHME?",
  "KA/GA: DISKUTOHEN PROJEKTET DHE TAKIMET KRYESORE PËR JAVËN AKTUALE DHE JAVËN E ARDHSHME (PX JAV)",
  "A KA DICKA ME KA, QE DUHET GJITHSESI ME U RIORGANIZU PER ME MBERRI DEADLINE? (DEADLINES NUK SHTYHEN POR RIORGANIZOHEN)",
  "KA/GA: KONTROLLOHET NËSE KA PROJEKTE TË REJA QË DUHET TË FUTEN NË PLAN",
  "KA/GA: A KA EVENTE QE MARRIM PJESE QE PRITEN GJATE JAVES?",
  "KA/GA: CAKTOHEN DHE KONTROLLOHEN TAKIMET E JAVES SE ARDHSHME NE TEAMS",
  "A KA TAKIME JAVORE QE BEHEN CANCEL J.T?",
  "KA/GA: KONTROLLO SHENIMET TEK PX JAV NE PRIMEFLOW",
  "A PRESIM DICKA NGA KLIENTI PER PLNF J.T? DERGO EMAIL NESE KA NEVOJE?",
  "GA/KA: KONTROLLO GRUPIN INT GA/KA A KA DICKA PER J.T?",
  "CILAT DETYRA JANE ME HAPA QE DUHET TE PLANIFIKOHEN PER JAVEN TJETER, SQARO NGA 08:00",
  "PRJK QE KANE QENE KETE JAVE DHE NUK JANE VAZHDUAR, CILAT JANE HAPAT TJERE PER JT",
  "A JEMI TE ANGAZHUM ME KREJT PROJEKTET, NESE JO PROPOZO (KONTROLLA NE PORTALE)?",
  "KA: A KA NDONJE IDE PER STAFIN QE ESHTE NENGARKESE?",
  "KA/GA: DISKUTONI SOCIAL MEDIA/WEBI DHE PLANET NEXT WEEK?",
  "A KA DET QE DUHET TAK INT",
  "GA: PIKAT TE GR. RLZ JAV.",
  "DISKUTO ME KA/GT DETYRAT PERSONALISHT",
]

type Point = { point: number; decision: "check" | "o" | "x" | null; owner: string | null; due_date: string | null }
type Comment = { id: string; point: number; author_name: string; body: string; created_at: string }
type Week = { points: Point[]; comments: Comment[] }
type Finding = { id: string; label: string; href?: string; body?: string; comment?: string; planning?: string; discussed?: boolean; waitingFor?: string; personalGroup?: "KA" | "GT" }
type NoteAction = "close" | "discuss" | "undiscuss"
type NoteActions = { pendingId: string | null; run: (id: string, action: NoteAction) => Promise<void> }
type MeetingFinding = {
  id: string
  date: string
  title: string
  startTime: string | null
  detail: string
  occurrence?: MeetingOccurrenceStatus
}
type MeetingFindings = MeetingFinding[] | "error"
type FindingResult = Finding[] | { items: Finding[]; source: "PrimeFlow" } | "error"
type Findings = Partial<Record<number, FindingResult>>
type ApiFetch = ReturnType<typeof useAuth>["apiFetch"]
type CalendarEvent = {
  id: string
  subject: string | null
  categories: string[]
  starts_at: string | null
  ends_at: string | null
  is_all_day: boolean
}
type CalendarHoliday = { id: string; category: string; title: string; entry_date: string | null; created_at: string }
type CalendarLeave = { entry_id: string; user_id: string; start_date: string; end_date: string }
type Project = { id: string; status: string; is_active: boolean }
type PlannedProject = { project_id: string; project_title: string; tasks: { status: string }[] }
type PlannerUserDay = { am_projects: PlannedProject[]; pm_projects: PlannedProject[] }
type PlannerTable = { departments: { days: { users: PlannerUserDay[] }[] }[] }
type CommonViewTasks = {
  items: {
    priority: { id: string; project: string; date: string; openAssignees?: string[] | null }[]
    personal: {
      task_id: string
      title: string
      date: string
      description?: string | null
      due_date?: string | null
      status?: string
      is_personal_task?: boolean
      confirmation_owner?: string | null
    }[]
  }
  guardrails: { truncated: { priority?: boolean; personal?: boolean } }
}

const dateFormat = new Intl.DateTimeFormat("sq-AL", { dateStyle: "medium", timeZone: "UTC" })
const timestampFormat = new Intl.DateTimeFormat("sq-AL", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Budapest" })
const meetingStartFormat = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Europe/Budapest",
})
const fieldClass = "w-full min-w-0 rounded-md border border-input bg-background px-2 py-1.5 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
const cellClass = "min-w-0 [overflow-wrap:anywhere] @min-[60rem]:table-cell @min-[60rem]:px-4 @min-[60rem]:py-3"
const mobileLabelClass = "mb-1.5 block text-xs font-semibold text-muted-foreground @min-[60rem]:hidden"
const automaticPoints = [1, 2, 8, 9, 12, 18]
const calendarTopic = /(?:^|[^\p{L}\p{N}])(?:pv|fest(?:ë|a|at)?|pushim(?:e|et)?|(?:public )?holidays?|annual leave)(?=$|[^\p{L}\p{N}])/iu

function dateObject(day: string) {
  return new Date(`${day}T00:00:00Z`)
}

function shiftDate(day: string, days: number) {
  const date = dateObject(day)
  date.setUTCDate(date.getUTCDate() + days)
  return date.toISOString().slice(0, 10)
}

function monday(day: string) {
  return shiftDate(day, -((dateObject(day).getUTCDay() + 6) % 7))
}

async function request<T>(apiFetch: ApiFetch, path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

function calendarTimestamp(value: string | null): string | null {
  if (!value) return null
  return /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`
}

function shortCalendarDate(day: string) {
  return `${day.slice(8, 10)}.${day.slice(5, 7)}`
}

function calendarFinding(id: string, title: string, startDate: string, lastDate: string, week: string, end: string) {
  if (lastDate < week || startDate > end) return []
  const first = startDate < week ? week : startDate
  const last = lastDate > end ? end : lastDate
  const range = first === last ? shortCalendarDate(first) : `${shortCalendarDate(first)}–${shortCalendarDate(last)}`
  return [{ id, label: `${range} · ${title}`, day: first }]
}

async function leaveFindings(apiFetch: ApiFetch, week: string): Promise<Finding[]> {
  const end = shiftDate(week, 13)
  // Allow for the UTC offset at both ends, then clip in the planning timezone.
  const params = new URLSearchParams({
    start: `${shiftDate(week, -1)}T00:00:00Z`,
    end: `${shiftDate(end, 2)}T00:00:00Z`,
  })
  const events = await request<CalendarEvent[]>(apiFetch, `/microsoft/events?${params}`)
  return events.flatMap((event) => {
    const subject = event.subject?.trim()
    const category = event.categories.find((item) => calendarTopic.test(item))
    if (!category && !calendarTopic.test(subject || "")) return []

    const starts = calendarTimestamp(event.starts_at)
    const finishes = calendarTimestamp(event.ends_at)
    const startDate = taskDateKey(starts)
    const endDate = taskDateKey(finishes)
    if (!startDate) return []
    let lastDate = startDate
    if (finishes && endDate && endDate > startDate) {
      lastDate = event.is_all_day ? shiftDate(endDate, -1) : taskDateKey(new Date(Date.parse(finishes) - 1).toISOString()) ?? startDate
    }
    return calendarFinding(event.id, subject || category || "PV/FEST", startDate, lastDate, week, end)
  }).sort((left, right) => left.day.localeCompare(right.day) || left.label.localeCompare(right.label))
}

async function primeFlowLeaveFindings(apiFetch: ApiFetch, week: string): Promise<Finding[]> {
  const end = shiftDate(week, 13)
  const [entries, leave, people] = await Promise.all([
    request<CalendarHoliday[]>(apiFetch, `/common-entries?from=${week}&to=${end}`),
    request<CalendarLeave[]>(apiFetch, `/common-entries/blocks?start=${week}&end=${end}`),
    fetchUsersLookupCached(apiFetch).catch(() => null),
  ])
  const names = new Map(((people ?? []) as Pick<User, "id" | "full_name">[]).map((person) => [person.id, person.full_name]))
  return [
    ...entries.flatMap((entry) => {
      const day = entry.entry_date ?? taskDateKey(entry.created_at)
      return day && entry.category === "External Holiday" ? calendarFinding(entry.id, entry.title, day, day, week, end) : []
    }),
    ...leave.flatMap((item) => calendarFinding(item.entry_id, `PV · ${names.get(item.user_id) || "Punonjës"}`, item.start_date, item.end_date, week, end)),
  ].sort((left, right) => left.day.localeCompare(right.day) || left.label.localeCompare(right.label))
}

function findingPlainText(value?: string | null): string {
  return getPlainMarkedText(value)
    .replace(/<br\s*\/?>|<\/(?:div|p|li|h[1-6])\s*>/gi, "\n")
    .replace(/<[^>]*>/g, "")
    .replace(/(?:&nbsp;|\u00a0)/gi, " ")
    .replace(/\r\n?/g, "\n")
    .trim()
}

function findingText(value: string, fallback: string) {
  const plainText = findingPlainText(value)
  const firstBreak = plainText.indexOf("\n")
  return {
    label: (firstBreak === -1 ? plainText : plainText.slice(0, firstBreak)).trim() || fallback,
    body: firstBreak === -1 ? "" : plainText.slice(firstBreak + 1).trim(),
  }
}

async function noteFindings(apiFetch: ApiFetch, week: string, today: string): Promise<Finding[]> {
  const end = shiftDate(week, 20)
  const notes = await request<PlanNote[]>(apiFetch, "/plan-notes?include_attachments=false")
  const candidates = notes.filter((note) =>
    note.status === "OPEN" && !note.is_converted_to_task &&
    (!note.planned_for_date || note.planned_for_date <= end) &&
    !isPxJavCommentDeferred(note.comment, today, taskDateKey(note.updated_at) ?? today)
  )
  if (!candidates.length) return []

  const linkedTasks = await request<Pick<Task, "plan_note_origin_id">[]>(apiFetch, "/tasks/by-ga-notes/summary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ga_note_origin_ids: [],
      plan_note_origin_ids: candidates.map((note) => note.id),
      include_done: true,
      include_all_done: false,
    }),
  })
  const linkedNoteIds = new Set(linkedTasks.map((task) => task.plan_note_origin_id))
  return candidates.filter((note) => !linkedNoteIds.has(note.id)).map((note) => ({
    id: note.id,
    ...findingText(note.content, "Shënim PX JAV"),
    href: `/next-week-plan#ga-note-content-${note.id}`,
    comment: findingPlainText(note.comment),
    discussed: Boolean(note.is_discussed),
    planning: [
      note.planned_for_date && `Planned for ${dateFormat.format(dateObject(note.planned_for_date))}`,
      note.planning_brief?.dl && `DL ${findingPlainText(note.planning_brief.dl)}`,
    ].filter(Boolean).join(" · "),
  }))
}

function plannedProjects(table: PlannerTable) {
  return table.departments.flatMap((department) => department.days.flatMap((day) =>
    day.users.flatMap((user) => [...user.am_projects, ...user.pm_projects]),
  ))
}

async function commonViewFindings(apiFetch: ApiFetch, week: string): Promise<Findings> {
  const data = await request<CommonViewTasks>(apiFetch, `/common-view?week_start=${week}&include=tasks&include_all_departments=true&max_items_per_bucket=5000`)
  const friday = shiftDate(week, 4)
  const projects = new Map<string, Finding>()
  for (const entry of data.items.priority) {
    if (entry.date < week || entry.date > friday || entry.openAssignees === null) continue
    // Common View identifies each PRJK occurrence as priority:<project_id>:<date>.
    const [, id] = entry.id.split(":")
    if (id) projects.set(id, { id, label: entry.project, href: `/projects/${id}` })
  }
  const personal = new Map<string, Finding>()
  for (const entry of data.items.personal) {
    if (entry.date < week || entry.date > friday || ["WAITING_CLIENT", "WFE", "WAITINGCLIENT", "WAITING_FOR_CLIENT"].includes(entry.status ?? "")) continue
    const group = entry.is_personal_task === false && entry.status === "WAITING_CONFIRMATION"
      ? entry.confirmation_owner
      : getPersonalTaskGroup(entry)
    if ((group !== "KA" && group !== "GENT") || personal.has(entry.task_id)) continue

    const { label, body } = findingText(entry.title, "Detyrë pa titull")
    const due = taskDateKey(entry.due_date)
    personal.set(entry.task_id, {
      id: entry.task_id,
      label,
      href: `/tasks/${entry.task_id}`,
      personalGroup: group === "KA" ? "KA" : "GT",
      body: [body, findingPlainText(entry.description)].filter(Boolean).join("\n\n"),
      planning: due ? `DL ${due}` : undefined,
    })
  }
  return {
    2: data.guardrails.truncated.priority ? "error" : [...projects.values()].sort((left, right) => left.label.localeCompare(right.label)),
    18: data.guardrails.truncated.personal ? "error" : [...personal.values()].sort(
      (left, right) => Number(left.personalGroup === "GT") - Number(right.personalGroup === "GT"),
    ),
  }
}

async function projectContinuationFindings(apiFetch: ApiFetch, week: string, role: User["role"], departmentId?: string | null): Promise<FindingResult> {
  const department = role === "STAFF" ? departmentId : undefined
  if (role === "STAFF" && !department) return "error"
  const [current, next, projects] = await Promise.all([
    request<PlannerTable>(apiFetch, `/planners/weekly-table?week_start=${week}`),
    request<PlannerTable>(apiFetch, `/planners/weekly-table?week_start=${shiftDate(week, 7)}`),
    request<Project[]>(apiFetch, department ? `/projects?department_id=${encodeURIComponent(department)}` : "/projects"),
  ])
  const currentProjects = plannedProjects(current)
  const nextIds = new Set(plannedProjects(next).map((project) => project.project_id))
  const activeProjectIds = new Set(projects.filter((project) => project.is_active && project.status !== "DONE").map((project) => project.id))
  const noContinuation = new Map<string, PlannedProject>()
  for (const project of currentProjects) {
    if (activeProjectIds.has(project.project_id) && !nextIds.has(project.project_id) && project.tasks.some((task) => task.status !== "DONE")) {
      noContinuation.set(project.project_id, project)
    }
  }
  return [...noContinuation.values()].map((project) => ({ id: project.project_id, label: project.project_title, href: `/projects/${project.project_id}` }))
}

async function waitingFindings(apiFetch: ApiFetch, week: string): Promise<Finding[]> {
  const tasks = await request<Task[]>(apiFetch, "/tasks?status=WAITING_CLIENT&include_done=false")
  const end = shiftDate(week, 13)
  const waitingTasks = tasks.filter((task) => {
    const starts = taskDateKey(task.start_date || task.created_at)
    const due = taskDateKey(task.due_date)
    return (!starts || starts <= end) && (!due || due <= end)
  })
  const ownersFor = (task: Task): TaskAssignee[] =>
    task.assignees?.length ? task.assignees : task.assigned_to ? [{ id: task.assigned_to }] : []
  const needsLookup = waitingTasks.some((task) => ownersFor(task).some((person) => !person.full_name?.trim() && !person.username?.trim()))
  const lookup = needsLookup ? (await fetchUsersLookupCached(apiFetch).catch(() => null)) as TaskAssignee[] | null : null
  const people = new Map((lookup ?? []).map((person) => [person.id, person]))

  return waitingTasks.map((task) => {
    const { label, body } = findingText(task.title, "Detyrë pa titull")
    const initials = [...new Set(ownersFor(task).flatMap((person) => {
      const known = people.get(person.id)
      const name = person.full_name?.trim() || known?.full_name?.trim() || person.username?.trim() || known?.username?.trim()
      return name ? [personInitials(name.replace(/[._-]+/g, " "))] : []
    }))]
    const prefix = /^([\p{Lu}]{2,4}(?:\s*\/\s*[\p{Lu}]{2,4})*)\s*:\s*(.+)$/u.exec(label)
    const hasOwnerPrefix = prefix && prefix[1].split("/").some((part) => initials.includes(part.trim()))
    const description = findingPlainText(task.description)
    const due = taskDateKey(task.due_date)
    return {
      id: task.id,
      label: hasOwnerPrefix ? prefix[2] : label,
      waitingFor: initials.join(" / "),
      body: [body, description].filter(Boolean).join("\n\n"),
      planning: due ? `DL ${due}` : "Pa afat",
      href: `/tasks/${task.id}`,
    }
  })
}

async function externalMeetingFindings(apiFetch: ApiFetch, week: string): Promise<MeetingFinding[]> {
  const nextDays = Array.from({ length: 7 }, (_, index) => shiftDate(week, 7 + index))
  const [meetings, statuses] = await Promise.all([
    request<Meeting[]>(apiFetch, "/meetings?include_all_departments=true&meeting_type=external"),
    Promise.all(nextDays.map((day) => request<MeetingOccurrenceStatus[]>(apiFetch, `/meetings/occurrence-statuses?occurrence_date=${day}`))),
  ])
  const occurrences = new Map(statuses.flat().map((row) => [`${row.meeting_id}:${row.occurrence_date}`, row]))
  return nextDays.flatMap((day) => meetings
    .filter((meeting) => meeting.recurrence_type && meeting.recurrence_type !== "none"
        ? Boolean(internalMeetingDateOn(meeting, day))
        : taskDateKey(meeting.starts_at || meeting.created_at) === day)
    .map((meeting) => {
      const start = Date.parse(calendarTimestamp(meeting.starts_at ?? null) ?? "")
      return {
        id: meeting.id,
        date: day,
        title: meeting.title.trim().replace(/^\.+$/, "") || "Takim pa titull",
        startTime: Number.isFinite(start) ? meetingStartFormat.format(start) : null,
        detail: meeting.platform?.toLowerCase().includes("teams") && !meeting.meeting_url ? "Pa lidhje Teams" : "",
        occurrence: occurrences.get(`${meeting.id}:${day}`),
      }
    }))
}

function ExpandableFinding({ item, noteActions }: { item: Finding; noteActions?: NoteActions }) {
  const [open, setOpen] = useState(false)
  const detailId = useId()
  const hasDetails = Boolean(item.body || item.planning || item.comment)
  const titleClass = "min-w-0 [overflow-wrap:anywhere]"
  return (
    <li className="py-1.5">
      <div className="flex min-w-0 flex-wrap items-start gap-x-2 gap-y-1">
        <div className="flex min-w-0 flex-[1_1_12rem] items-start gap-1.5">
          {hasDetails ? (
            <button
              type="button"
              className="flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground"
              aria-label={`${open ? "Mbyll" : "Shfaq"} detajet për ${item.label}`}
              aria-expanded={open}
              aria-controls={detailId}
              onClick={() => setOpen(!open)}
            >
              <ChevronRight aria-hidden="true" className={open ? "size-4 rotate-90" : "size-4"} />
            </button>
          ) : <span aria-hidden="true" className="size-5 shrink-0" />}
          {item.waitingFor && (
            <span className="shrink-0 rounded bg-muted px-1.5 text-xs font-semibold leading-5 text-foreground" title="Në pritje nga klienti"
              aria-label={`Në pritje nga klienti për ${item.waitingFor}`}>
              {item.waitingFor}
            </span>
          )}
          {item.personalGroup && (
            <span className="shrink-0 rounded bg-muted px-1.5 text-xs font-semibold leading-5">{item.personalGroup}</span>
          )}
          {item.href ? (
            <Link href={item.href} className={`${titleClass} underline decoration-muted-foreground/50 underline-offset-2 hover:decoration-current`}>
              {item.label}
            </Link>
          ) : <span className={titleClass}>{item.label}</span>}
        </div>
        {noteActions && (
          <div className="ml-auto flex shrink-0 items-center gap-1" aria-busy={noteActions.pendingId === item.id}>
            <Button
              type="button"
              size="sm"
              variant={item.discussed ? "secondary" : "outline"}
              className="h-6 px-2 text-xs"
              title={item.discussed ? "Hiq shenjën Diskutuar" : "Shëno si diskutuar"}
              aria-pressed={Boolean(item.discussed)}
              disabled={noteActions.pendingId !== null}
              onClick={() => void noteActions.run(item.id, item.discussed ? "undiscuss" : "discuss")}
            >
              DISK{item.discussed && <span aria-hidden="true">✓</span>}
            </Button>
            <Button type="button" size="sm" variant="outline" className="h-6 px-2 text-xs" title="Mbyll shënimin"
              disabled={noteActions.pendingId !== null} onClick={() => void noteActions.run(item.id, "close")}>
              Close
            </Button>
          </div>
        )}
      </div>
      {hasDetails && (
        <div id={detailId} hidden={!open} className="ml-6.5 mt-1.5 space-y-1.5 rounded-md border bg-background px-2.5 py-2">
          {open && (
            <>
              {item.body && <p className="whitespace-pre-wrap">{item.body}</p>}
              {item.planning && <p className="text-xs text-muted-foreground">{item.planning}</p>}
              {item.comment && <p className="whitespace-pre-wrap text-xs text-muted-foreground"><span className="font-semibold">Koment PX JAV</span> · {item.comment}</p>}
            </>
          )}
        </div>
      )}
    </li>
  )
}

function FindingList({ items, previewCount }: { items: Finding[]; previewCount: number }) {
  const preview = items.slice(0, previewCount)
  const remaining = items.slice(previewCount)
  const renderItem = (item: Finding) => (
    <li key={item.id} className="pl-0.5 marker:text-muted-foreground">
      {item.href ? <Link className="underline decoration-muted-foreground/50 underline-offset-2 hover:decoration-current" href={item.href}>{item.label}</Link> : item.label}
    </li>
  )

  return (
    <div className="space-y-2">
      <ul className="list-disc space-y-1 pl-4">{preview.map(renderItem)}</ul>
      {remaining.length > 0 && (
        <details className="group">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs font-medium text-foreground hover:bg-accent [&::-webkit-details-marker]:hidden">
            <ChevronRight aria-hidden="true" className="size-3.5 transition-transform group-open:rotate-90" />
            Edhe {remaining.length} gjetje
          </summary>
          <ul className="mt-2 list-disc space-y-1 pl-4">{remaining.map(renderItem)}</ul>
        </details>
      )}
    </div>
  )
}

function PointDecision({ point, canDecide, path, apiFetch }: {
  point: Point
  path: string
  apiFetch: ApiFetch
  canDecide: boolean
}) {
  const [draft, setDraft] = useState(point)
  const [saved, setSaved] = useState(point)
  const [saving, setSaving] = useState(false)
  const [decisionError, setDecisionError] = useState(false)
  const dirty = draft.decision !== saved.decision || draft.owner !== saved.owner || draft.due_date !== saved.due_date

  async function saveDecision(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    setDecisionError(false)
    try {
      const result = await request<Point>(apiFetch, path, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: draft.decision, owner: draft.owner, due_date: draft.due_date }),
      })
      setSaved(result)
      setDraft(result)
    } catch {
      setDecisionError(true)
    } finally {
      setSaving(false)
    }
  }

  return canDecide ? (
    <form onSubmit={saveDecision}>
      <fieldset disabled={saving} className="grid min-w-0 grid-cols-[3.5rem_minmax(0,1fr)] gap-1.5">
        <select aria-label={`Vendimi për pikën ${point.point}`} className={fieldClass} value={draft.decision ?? ""} onChange={(event) => setDraft({ ...draft, decision: (event.target.value || null) as Point["decision"] })}>
          <option value="">—</option><option value="check">✓</option><option value="o">O</option><option value="x">X</option>
        </select>
        <input aria-label={`Përgjegjësi për pikën ${point.point}`} className={fieldClass} placeholder="WHO" maxLength={120} value={draft.owner ?? ""} onChange={(event) => setDraft({ ...draft, owner: event.target.value || null })} />
        <input aria-label={`Afati për pikën ${point.point}`} className={`${fieldClass} col-span-2`} type="date" value={draft.due_date ?? ""} onChange={(event) => setDraft({ ...draft, due_date: event.target.value || null })} />
        {(dirty || saving) && <Button className="col-span-2 justify-self-start" size="sm" variant="outline" type="submit">Ruaj vendimin</Button>}
      </fieldset>
      {decisionError && <p role="alert" className="mt-1 text-destructive">Ruajtja e vendimit dështoi. Provo përsëri.</p>}
    </form>
  ) : (
    <div className="space-y-1"><p>{saved.decision === "check" ? "✓" : saved.decision?.toUpperCase() ?? "—"}</p>{saved.owner && <p>{saved.owner}</p>}{saved.due_date && <p>{dateFormat.format(dateObject(saved.due_date))}</p>}</div>
  )
}

function PointComments({ point, comments, path, apiFetch }: {
  point: Point
  path: string
  apiFetch: ApiFetch
  comments: Comment[]
}) {
  const [added, setAdded] = useState<Comment[]>([])
  const [body, setBody] = useState("")
  const [posting, setPosting] = useState(false)
  const [commentError, setCommentError] = useState(false)
  const attempt = useRef<{ id: string; body: string } | null>(null)

  async function postComment(event: React.FormEvent) {
    event.preventDefault()
    const content = body.trim()
    if (posting || !content) return
    if (attempt.current?.body !== content) attempt.current = { id: crypto.randomUUID(), body: content }
    setPosting(true)
    setCommentError(false)
    try {
      const comment = await request<Comment>(apiFetch, `${path}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(attempt.current),
      })
      setAdded((items) => [...items, comment])
      setBody("")
      attempt.current = null
    } catch {
      setCommentError(true)
    } finally {
      setPosting(false)
    }
  }

  return (
    <>
      {[...comments, ...added].map((comment) => (
        <article key={comment.id} className="mb-2 rounded-md border bg-muted/30 p-2">
          <p className="text-xs text-muted-foreground"><strong>{comment.author_name}</strong> · <time dateTime={comment.created_at}>{timestampFormat.format(new Date(comment.created_at))}</time></p>
          <p className="mt-1 whitespace-pre-wrap break-words">{comment.body}</p>
        </article>
      ))}
      <form className="space-y-1.5" onSubmit={postComment}>
        <textarea aria-label={`Komenti për pikën ${point.point}`} className={`${fieldClass} block field-sizing-content min-h-9 max-h-40 resize-y`} placeholder="Shkruaj koment" rows={1} maxLength={4000} value={body} disabled={posting} onChange={(event) => setBody(event.target.value)} />
        {(body.trim() || posting || commentError) && <Button size="sm" type="submit" variant="outline" disabled={posting || !body.trim()}>{posting ? "Duke ruajtur…" : "Shto koment"}</Button>}
        {commentError && <p role="alert" className="text-destructive">Ruajtja e komentit dështoi. Provo përsëri.</p>}
      </form>
    </>
  )
}

function MeetingList({ items, pending, onCancel }: {
  items?: MeetingFindings
  pending: MeetingFinding | null
  onCancel: (meeting: MeetingFinding) => void
}) {
  if (items === "error") return <p role="status" className="text-destructive">Takimet nuk u ngarkuan.</p>
  if (!items) return <p role="status" className="text-muted-foreground">Duke ngarkuar takimet…</p>
  if (!items.length) return <p className="text-muted-foreground">S’ka takime externe për javën e ardhshme.</p>

  return (
    <ul className="divide-y rounded-lg border bg-background">
      {items.map((meeting) => {
        const { id, date, title, startTime, detail, occurrence } = meeting
        const canceled = occurrence?.status === "canceled"
        const saving = pending?.id === id && pending.date === date
        const formattedDate = shortCalendarDate(date)
        return (
          <li key={`${id}:${date}`} className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 px-2.5 py-2">
            <div className="min-w-0 flex-1 basis-28">
              <p className="text-xs text-muted-foreground">
                <time dateTime={date}>{formattedDate}</time>
                {" · "}{startTime ? <time dateTime={startTime} className="font-medium text-foreground">{startTime}</time> : "Pa orë të caktuar"}
                {detail && <span> · {detail}</span>}
                {occurrence?.status === "held" && <span> · Mbajtur</span>}
              </p>
              <Link href={`/meetings/${id}?date=${date}`} className={canceled ? "font-medium text-muted-foreground line-through" : "font-medium hover:underline"}>
                {title}
              </Link>
            </div>
            {canceled ? (
              <span className="ml-auto rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground">Anuluar</span>
            ) : (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="ml-auto h-7 text-xs text-destructive"
                aria-label={`Anulo takimin ${title} · ${formattedDate}${startTime ? ` · ${startTime}` : ""}`}
                disabled={pending !== null}
                onClick={() => onCancel(meeting)}
              >
                {saving ? "Duke anuluar…" : "Anulo"}
              </Button>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function PointRow({ entries, result, canDecide, path, apiFetch, meetingList, noteActions }: {
  entries: { point: Point; question: string; comments: Comment[] }[]
  result?: FindingResult
  canDecide: boolean
  path: string
  apiFetch: ApiFetch
  meetingList?: ReactNode
  noteActions?: NoteActions
}) {
  const [{ point }] = entries
  const combined = entries.length > 1
  const fallback = typeof result === "object" && !Array.isArray(result) ? result : undefined
  const findings = fallback?.items ?? (Array.isArray(result) || result === "error" ? result : undefined)
  return (
    <tr role="row" className="grid gap-4 rounded-lg border bg-card p-4 @min-[36rem]:grid-cols-2 @min-[60rem]:table-row @min-[60rem]:rounded-none @min-[60rem]:border-0 @min-[60rem]:border-t @min-[60rem]:align-top @min-[60rem]:even:bg-muted/25">
      <th role="rowheader" scope="row" className={`${cellClass} space-y-3 border-b pb-3 text-left font-semibold @min-[36rem]:col-span-2 @min-[60rem]:border-b-0`}>
        {entries.map(({ point, question }) => (
          <div key={point.point} className="flex items-start gap-2.5">
            <span className="flex size-6 shrink-0 items-center justify-center rounded-md border bg-muted text-xs font-semibold tabular-nums text-muted-foreground">{point.point}</span>
            <span className="leading-5">{question}</span>
          </div>
        ))}
      </th>
      <td role="cell" className={`${cellClass} @min-[36rem]:col-span-2`}>
        <span aria-hidden="true" className={mobileLabelClass}>Gjetjet</span>
        {meetingList ?? (
          <>
            {fallback && <p className="mb-1.5 text-xs text-muted-foreground" title="Kalendari Microsoft nuk u ngarkua">Burimi · {fallback.source}</p>}
            {findings === "error" ? <span role="status" className="text-destructive">{point.point === 1 ? "Kalendari nuk u ngarkua." : "Për kontroll · Burimi nuk u ngarkua."}</span> :
              findings?.length ? [8, 9, 18].includes(point.point) ? (
                <ul className="divide-y">{findings.map((item) => <ExpandableFinding key={item.id} item={item} noteActions={noteActions} />)}</ul>
              ) : <FindingList items={findings} previewCount={point.point === 2 ? findings.length : point.point === 1 ? 1 : 3} /> :
              <span className="text-muted-foreground">{
                findings ? point.point === 1 ? "S’ka festa/PV." : "S’ka gjetje në burimin e kontrolluar." :
                  automaticPoints.includes(point.point) ? "Duke kontrolluar…" : "Kontroll manual"
              }</span>}
          </>
        )}
      </td>
      <td role="cell" className={cellClass}>
        <span aria-hidden="true" className={mobileLabelClass}>Komenti</span>
        <div className="space-y-3">
          {entries.map(({ point, comments }) => (
            <div key={point.point}>
              {combined && <p className="mb-1 text-xs font-medium text-muted-foreground">Pika {point.point}</p>}
              <PointComments point={point} comments={comments} path={`${path}/points/${point.point}`} apiFetch={apiFetch} />
            </div>
          ))}
        </div>
      </td>
      <td role="cell" className={cellClass}>
        <span aria-hidden="true" className={mobileLabelClass}>Vendimi · WHO · WHEN</span>
        <div className="space-y-3">
          {entries.map(({ point }) => (
            <div key={point.point}>
              {combined && <p className="mb-1 text-xs font-medium text-muted-foreground">Pika {point.point}</p>}
              <PointDecision point={point} canDecide={canDecide} path={`${path}/points/${point.point}`} apiFetch={apiFetch} />
            </div>
          ))}
        </div>
      </td>
    </tr>
  )
}

function WeekContent({ week, apiFetch, user }: { week: string; apiFetch: ApiFetch; user: User }) {
  const confirm = useConfirm()
  const [today, setToday] = useState(() => taskDateKey(new Date().toISOString())!)
  const [data, setData] = useState<Week | null>(null)
  const [error, setError] = useState(false)
  const [revision, setRevision] = useState(0)
  const [findingsRevision, setFindingsRevision] = useState(0)
  const [findingBatch, setFindingBatch] = useState<{ revision: number; results: Findings }>({ revision: 0, results: {} })
  const [meetingBatch, setMeetingBatch] = useState<{ revision: number; results: MeetingFindings }>()
  const [pendingMeeting, setPendingMeeting] = useState<MeetingFinding | null>(null)
  const [pendingNoteId, setPendingNoteId] = useState<string | null>(null)
  const [createdInternalMeetings, setCreatedInternalMeetings] = useState<Meeting[]>([])
  const path = `/weekly-planner-short/${week}`
  const { role, department_id: departmentId } = user
  const canDecide = role === "ADMIN" || role === "MANAGER"
  const findings = findingBatch.revision === findingsRevision ? findingBatch.results : {}
  const meetings = meetingBatch?.revision === findingsRevision ? meetingBatch.results : undefined
  const preparing = meetings === undefined || automaticPoints.some((point) => findings[point] === undefined)

  async function updateNote(id: string, action: NoteAction) {
    if (pendingNoteId) return
    const errorToastId = `weekly-planner-note:${id}`
    setPendingNoteId(id)
    try {
      toast.dismiss(errorToastId)
      const updated = await request<PlanNote>(apiFetch, `/plan-notes/${encodeURIComponent(id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(action === "close" ? { status: "CLOSED" } : { is_discussed: action === "discuss" }),
      })
      setFindingBatch((previous) => {
        const notes = previous.results[8]
        if (!Array.isArray(notes)) return previous
        const items = updated.status === "CLOSED"
          ? notes.filter((note) => note.id !== id)
          : notes.map((note) => note.id === id ? { ...note, discussed: Boolean(updated.is_discussed) } : note)
        return { ...previous, results: { ...previous.results, 8: items } }
      })
    } catch {
      toast.error(action === "close" ? "Shënimi nuk u mbyll. Provo përsëri." : "Statusi Diskutuar nuk u ruajt. Provo përsëri.", { id: errorToastId })
    } finally {
      setPendingNoteId(null)
    }
  }

  useEffect(() => {
    const refreshDay = () => setToday(taskDateKey(new Date().toISOString())!)
    const interval = window.setInterval(refreshDay, 60_000)
    document.addEventListener("visibilitychange", refreshDay)
    return () => {
      window.clearInterval(interval)
      document.removeEventListener("visibilitychange", refreshDay)
    }
  }, [])

  async function cancelMeeting(meeting: MeetingFinding) {
    if (pendingMeeting) return
    const errorToastId = `cancel-meeting:${meeting.id}:${meeting.date}`
    setPendingMeeting(meeting)
    try {
      const confirmed = await confirm({
        title: "Ta anulosh takimin?",
        description: `${meeting.title} · ${dateFormat.format(dateObject(meeting.date))}${meeting.startTime ? ` · ${meeting.startTime}` : ""}\n\nTakimet interne të lidhura dhe detyrat e gjeneruara për këto takime fshihen, nëse ekzistojnë.`,
        confirmLabel: "Anulo takimin",
        cancelLabel: "Kthehu",
        variant: "destructive",
      })
      if (!confirmed) return

      toast.dismiss(errorToastId)
      const occurrence = await request<MeetingOccurrenceStatus>(apiFetch, `/meetings/${meeting.id}/occurrence-status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ occurrence_date: meeting.date, status: "canceled", note: meeting.occurrence?.note ?? null }),
      })
      setMeetingBatch((previous) => previous && Array.isArray(previous.results) ? {
        ...previous,
        results: previous.results.map((item) => item.id === meeting.id && item.date === meeting.date ? { ...item, occurrence } : item),
      } : previous)
    } catch {
      toast.error("Takimi nuk u anulua. Provo përsëri.", { id: errorToastId })
    } finally {
      setPendingMeeting(null)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    request<Week>(apiFetch, path, { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setData(result) })
      .catch(() => { if (!controller.signal.aborted) setError(true) })
    return () => controller.abort()
  }, [apiFetch, path, revision])

  useEffect(() => {
    const controller = new AbortController()
    const fetchForWeek: ApiFetch = (url, init) => apiFetch(url, { ...init, signal: controller.signal })
    const publish = (results: Findings) => {
      if (controller.signal.aborted) return
      setFindingBatch((previous) => ({
        revision: findingsRevision,
        results: { ...(previous.revision === findingsRevision ? previous.results : {}), ...results },
      }))
    }

    void leaveFindings(fetchForWeek, week).then((items) => publish({ 1: items }), async () => {
      if (controller.signal.aborted) return
      try {
        publish({ 1: { items: await primeFlowLeaveFindings(fetchForWeek, week), source: "PrimeFlow" } })
      } catch {
        publish({ 1: "error" })
      }
    })
    void commonViewFindings(fetchForWeek, week).then(publish, () => publish({ 2: "error", 18: "error" }))
    const publishMeetings = (results: MeetingFindings) => {
      if (!controller.signal.aborted) setMeetingBatch({ revision: findingsRevision, results })
    }
    void externalMeetingFindings(fetchForWeek, week).then(publishMeetings, () => publishMeetings("error"))
    void noteFindings(fetchForWeek, week, today).then((items) => publish({ 8: items }), () => publish({ 8: "error" }))
    void waitingFindings(fetchForWeek, week).then((items) => publish({ 9: items }), () => publish({ 9: "error" }))
    void projectContinuationFindings(fetchForWeek, week, role, departmentId)
      .then((items) => publish({ 12: items }), () => publish({ 12: "error" }))
    return () => controller.abort()
  }, [apiFetch, week, today, role, departmentId, findingsRevision])

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">{dateFormat.format(dateObject(week))} – {dateFormat.format(dateObject(shiftDate(week, 4)))}</p>
        {data && (
          <Button size="sm" variant="outline" onClick={() => setFindingsRevision((value) => value + 1)} disabled={preparing || pendingMeeting !== null || pendingNoteId !== null}>
            <RefreshCw aria-hidden="true" className={preparing ? "motion-safe:animate-spin" : undefined} />
            {preparing ? "Duke kontrolluar…" : "Rifresko gjetjet"}
          </Button>
        )}
      </div>
      {!data && (error ? (
        <div role="alert" className="flex items-center gap-3"><p>Java nuk u ngarkua.</p><Button variant="outline" onClick={() => { setError(false); setRevision((value) => value + 1) }}>Provo përsëri</Button></div>
      ) : <p role="status" className="text-muted-foreground">Duke ngarkuar javën…</p>)}
      {data && (
        <div className="@min-[60rem]:overflow-hidden @min-[60rem]:rounded-lg @min-[60rem]:border">
          <table role="table" aria-label="Pikat e Weekly Planner Short" className="block w-full text-sm @min-[60rem]:table @min-[60rem]:table-fixed">
            <thead role="rowgroup" className="sr-only bg-muted text-left @min-[60rem]:not-sr-only">
              <tr role="row">
                <th role="columnheader" scope="col" className="w-[24%] px-4 py-2.5">Pyetja</th>
                <th role="columnheader" scope="col" className="w-[36%] px-4 py-2.5">Gjetjet</th>
                <th role="columnheader" scope="col" className="w-[21%] px-4 py-2.5">Komenti</th>
                <th role="columnheader" scope="col" className="px-4 py-2.5">Vendimi · WHO · WHEN</th>
              </tr>
            </thead>
            <tbody role="rowgroup" className="grid gap-3 @min-[60rem]:table-row-group">
              {questions.map((_, index) => {
                const number = index + 1
                if (number === 7) return null
                const entries = (number === 6 ? [6, 7] : [number]).map((point) => ({
                  point: data.points.find((item) => item.point === point) ?? { point, decision: null, owner: null, due_date: null },
                  question: questions[point - 1],
                  comments: data.comments.filter((item) => item.point === point),
                }))
                return (
                  <PointRow
                    key={number}
                    entries={entries}
                    result={findings[number]}
                    canDecide={canDecide}
                    path={path}
                    apiFetch={apiFetch}
                    meetingList={number === 6 ? <MeetingList items={meetings} pending={pendingMeeting} onCancel={cancelMeeting} /> :
                      number === 16 ? (
                        <div className="space-y-2">
                          <InternalMeetingCreateDialog onCreated={(meeting) => {
                            setCreatedInternalMeetings((current) => [...current, meeting])
                            toast.success("Takimi intern u krijua.")
                          }} />
                          {createdInternalMeetings.length > 0 && <ul className="space-y-1">
                            {createdInternalMeetings.map((meeting) => <li key={meeting.id}>
                              <Link className="underline underline-offset-2" href={`/meetings/${meeting.id}`}>{meeting.title}</Link>
                            </li>)}
                          </ul>}
                        </div>
                      ) : undefined}
                    noteActions={number === 8 ? { pendingId: pendingNoteId, run: updateNote } : undefined}
                  />
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}

export default function WeeklyPlannerShortPage() {
  const { apiFetch, user } = useAuth()
  const [week, setWeek] = useState(() => monday(taskDateKey(new Date().toISOString())!))

  if (!user) return null

  return (
    <section className="@container min-w-0 space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Weekly Planner Short</h1>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setWeek(shiftDate(week, -7))}>Java e kaluar</Button>
          <input aria-label="Zgjidh javën" type="date" className="rounded-md border border-input bg-background px-2 py-1 text-sm" value={week} onChange={(event) => { if (event.target.value) setWeek(monday(event.target.value)) }} />
          <Button variant="outline" size="sm" onClick={() => setWeek(shiftDate(week, 7))}>Java tjetër</Button>
        </div>
      </header>
      <WeekContent key={week} week={week} apiFetch={apiFetch} user={user} />
    </section>
  )
}
