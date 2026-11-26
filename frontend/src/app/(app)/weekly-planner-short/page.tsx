"use client"

import Link from "next/link"
import { useEffect, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/lib/auth"
import { internalMeetingDateOn } from "@/lib/internal-meeting-list"
import { taskDateKey } from "@/lib/task-calendar-date"
import type { Meeting, MeetingOccurrenceStatus, Task, User } from "@/lib/types"
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
type Finding = { id: string; label: string; href?: string }
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
type PlanNote = { id: string; content: string; status: string; is_discussed: boolean; planned_for_date: string | null; start_date: string }
type Project = { id: string; title: string; display_title: string | null; status: string; is_active: boolean; created_at: string }
type PlannedProject = { project_id: string; project_title: string; tasks: { status: string }[] }
type PlannerUserDay = { am_projects: PlannedProject[]; pm_projects: PlannedProject[] }
type PlannerTable = { departments: { days: { users: PlannerUserDay[] }[] }[] }
type CommonViewProjects = {
  items: { priority: { id: string; project: string; date: string; openAssignees?: string[] | null }[] }
  guardrails: { truncated: { priority?: boolean } }
}

const dateFormat = new Intl.DateTimeFormat("sq-AL", { dateStyle: "medium", timeZone: "UTC" })
const timestampFormat = new Intl.DateTimeFormat("sq-AL", { dateStyle: "medium", timeStyle: "short", timeZone: "Europe/Budapest" })
const fieldClass = "w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
const automaticPoints = [1, 2, 4, 6, 8, 9, 12]
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

async function noteFindings(apiFetch: ApiFetch, week: string): Promise<Finding[]> {
  const end = shiftDate(week, 6)
  const notes = await request<PlanNote[]>(apiFetch, "/plan-notes?include_attachments=false")
  return notes.filter((note) => {
    const day = note.planned_for_date ?? taskDateKey(note.start_date)
    return day && day >= week && day <= end && note.status.toUpperCase() !== "CLOSED" && !note.is_discussed
  }).map((note) => ({
    id: note.id,
    label: note.content.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim().slice(0, 180) || "Shënim PX JAV",
    href: `/next-week-plan#ga-note-content-${note.id}`,
  }))
}

function plannedProjects(table: PlannerTable) {
  return table.departments.flatMap((department) => department.days.flatMap((day) =>
    day.users.flatMap((user) => [...user.am_projects, ...user.pm_projects]),
  ))
}

async function currentProjectFindings(apiFetch: ApiFetch, week: string): Promise<Finding[]> {
  const data = await request<CommonViewProjects>(apiFetch, `/common-view?week_start=${week}&include=tasks&include_all_departments=true&max_items_per_bucket=5000`)
  if (data.guardrails.truncated.priority) throw new Error("Common View returned an incomplete PRJK list")

  const friday = shiftDate(week, 4)
  const projects = new Map<string, Finding>()
  for (const entry of data.items.priority) {
    if (entry.date < week || entry.date > friday || entry.openAssignees === null) continue
    // Common View identifies each PRJK occurrence as priority:<project_id>:<date>.
    const [, id] = entry.id.split(":")
    if (id) projects.set(id, { id, label: entry.project, href: `/projects/${id}` })
  }
  return [...projects.values()].sort((left, right) => left.label.localeCompare(right.label))
}

async function projectFindings(apiFetch: ApiFetch, week: string, role: User["role"], departmentId?: string | null): Promise<Findings> {
  const department = role === "STAFF" ? departmentId : undefined
  if (role === "STAFF" && !department) return { 4: "error", 12: "error" }
  const [current, next, projects] = await Promise.all([
    request<PlannerTable>(apiFetch, `/planners/weekly-table?week_start=${week}`),
    request<PlannerTable>(apiFetch, `/planners/weekly-table?week_start=${shiftDate(week, 7)}`),
    request<Project[]>(apiFetch, department ? `/projects?department_id=${encodeURIComponent(department)}` : "/projects"),
  ])
  const currentProjects = plannedProjects(current)
  const nextIds = new Set(plannedProjects(next).map((project) => project.project_id))
  const plannedIds = new Set([...currentProjects.map((project) => project.project_id), ...nextIds])
  const activeProjects = new Map(projects.filter((project) => project.is_active && project.status !== "DONE").map((project) => [project.id, project]))
  const weekEnd = shiftDate(week, 6)
  const newProjects = [...activeProjects.values()].filter((project) => {
    const created = taskDateKey(project.created_at)
    return created && created >= week && created <= weekEnd && !plannedIds.has(project.id)
  })
  const noContinuation = new Map<string, PlannedProject>()
  for (const project of currentProjects) {
    if (activeProjects.has(project.project_id) && !nextIds.has(project.project_id) && project.tasks.some((task) => task.status !== "DONE")) {
      noContinuation.set(project.project_id, project)
    }
  }
  return {
    4: newProjects.map((project) => ({ id: project.id, label: project.display_title || project.title, href: `/projects/${project.id}` })),
    12: [...noContinuation.values()].map((project) => ({ id: project.project_id, label: project.project_title, href: `/projects/${project.project_id}` })),
  }
}

async function waitingFindings(apiFetch: ApiFetch, week: string): Promise<Finding[]> {
  const tasks = await request<Task[]>(apiFetch, "/tasks?status=WAITING_CLIENT&include_done=false")
  const end = shiftDate(week, 13)
  return tasks.filter((task) => {
    const starts = taskDateKey(task.start_date || task.created_at)
    const due = taskDateKey(task.due_date)
    return (!starts || starts <= end) && (!due || due <= end)
  }).map((task) => ({
    id: task.id,
    label: `${task.title} · ${taskDateKey(task.due_date) || "pa afat"}`,
    href: `/tasks/${task.id}`,
  }))
}

async function externalMeetingFindings(apiFetch: ApiFetch, week: string): Promise<Finding[]> {
  const nextDays = Array.from({ length: 7 }, (_, index) => shiftDate(week, 7 + index))
  const [meetings, statuses] = await Promise.all([
    request<Meeting[]>(apiFetch, "/meetings?include_all_departments=true&meeting_type=external"),
    Promise.all(nextDays.map((day) => request<MeetingOccurrenceStatus[]>(apiFetch, `/meetings/occurrence-statuses?occurrence_date=${day}`))),
  ])
  const canceled = new Set(statuses.flat().filter((row) => row.status === "canceled").map((row) => `${row.meeting_id}:${row.occurrence_date}`))
  return nextDays.flatMap((day) => meetings
    .filter((meeting) => {
      if (canceled.has(`${meeting.id}:${day}`)) return false
      return meeting.recurrence_type && meeting.recurrence_type !== "none"
        ? Boolean(internalMeetingDateOn(meeting, day))
        : taskDateKey(meeting.starts_at || meeting.created_at) === day
    })
    .map((meeting) => {
      const missing = !meeting.starts_at ? " · pa orë të caktuar" :
        meeting.platform?.toLowerCase().includes("teams") && !meeting.meeting_url ? " · pa lidhje Teams" : ""
      return { id: `${meeting.id}:${day}`, label: `${day} · ${meeting.title}${missing}`, href: `/meetings/${meeting.id}?date=${day}` }
    }))
}

function PointRow({ point, question, comments, result, canDecide, path, apiFetch }: {
  point: Point
  question: string
  comments: Comment[]
  result?: FindingResult
  canDecide: boolean
  path: string
  apiFetch: ApiFetch
}) {
  const fallback = typeof result === "object" && !Array.isArray(result) ? result : undefined
  const findings = fallback?.items ?? (Array.isArray(result) || result === "error" ? result : undefined)
  const [draft, setDraft] = useState(point)
  const [saved, setSaved] = useState(point)
  const [added, setAdded] = useState<Comment[]>([])
  const [body, setBody] = useState("")
  const [posting, setPosting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [commentError, setCommentError] = useState(false)
  const [decisionError, setDecisionError] = useState(false)
  const attempt = useRef<{ id: string; body: string } | null>(null)
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
    <tr className="border-t align-top">
      <th scope="row" className="p-3 text-left font-medium"><span className="mr-2 text-muted-foreground">{point.point}.</span>{question}</th>
      <td className="p-3">
        {fallback && <p className="mb-1 text-xs text-muted-foreground" title="Kalendari Microsoft nuk u ngarkua">Burimi · {fallback.source}</p>}
        {findings === "error" ? <span role="status">{point.point === 1 ? "Kalendari nuk u ngarkua." : "Për kontroll · Burimi nuk u ngarkua."}</span> :
          point.point === 1 && findings?.length ? (
            findings.length === 1
              ? <p className="truncate" title={findings[0].label}>{findings[0].label}</p>
              : <details>
                <summary className="cursor-pointer" title={findings[0].label}>
                  <span className="inline-flex max-w-[calc(100%-1rem)] items-baseline gap-2 align-top">
                    <span className="truncate">{findings[0].label}</span>
                    <span className="shrink-0 text-muted-foreground">+{findings.length - 1}</span>
                  </span>
                </summary>
                <ul className="mt-1 list-disc space-y-1 pl-4">{findings.slice(1).map((item) => <li key={item.id}>{item.label}</li>)}</ul>
              </details>
          ) :
          findings?.length ? <ul className="space-y-1.5">
            {findings.slice(0, 3).map((item) => <li key={item.id}>{item.href ? <Link className="underline underline-offset-2" href={item.href}>{item.label}</Link> : item.label}</li>)}
            {findings.length > 3 && <li><details><summary className="cursor-pointer text-muted-foreground">Edhe {findings.length - 3} gjetje</summary><ul className="mt-2 space-y-1.5">{findings.slice(3).map((item) => <li key={item.id}>{item.href ? <Link className="underline underline-offset-2" href={item.href}>{item.label}</Link> : item.label}</li>)}</ul></details></li>}
          </ul> : <span className="text-muted-foreground">{
            findings ? point.point === 1 ? "S’ka festa/PV." : "S’ka gjetje në burimin e kontrolluar." :
              automaticPoints.includes(point.point) ? "Duke kontrolluar…" : "Kontroll manual"
          }</span>}
      </td>
      <td className="p-3">
        {canDecide ? (
          <form onSubmit={saveDecision}>
            <fieldset disabled={saving} className="space-y-2">
              <select aria-label={`Vendimi për pikën ${point.point}`} className={fieldClass} value={draft.decision ?? ""} onChange={(event) => setDraft({ ...draft, decision: (event.target.value || null) as Point["decision"] })}>
                <option value="">—</option><option value="check">✓</option><option value="o">O</option><option value="x">X</option>
              </select>
              <input aria-label={`Përgjegjësi për pikën ${point.point}`} className={fieldClass} placeholder="WHO" maxLength={120} value={draft.owner ?? ""} onChange={(event) => setDraft({ ...draft, owner: event.target.value || null })} />
              <input aria-label={`Afati për pikën ${point.point}`} className={fieldClass} type="date" value={draft.due_date ?? ""} onChange={(event) => setDraft({ ...draft, due_date: event.target.value || null })} />
              {(dirty || saving) && <Button size="sm" variant="outline" type="submit">Ruaj vendimin</Button>}
            </fieldset>
            {decisionError && <p role="alert" className="mt-1 text-destructive">Ruajtja e vendimit dështoi. Provo përsëri.</p>}
          </form>
        ) : (
          <div className="space-y-1"><p>{saved.decision === "check" ? "✓" : saved.decision?.toUpperCase() ?? "—"}</p>{saved.owner && <p>{saved.owner}</p>}{saved.due_date && <p>{dateFormat.format(dateObject(saved.due_date))}</p>}</div>
        )}
      </td>
      <td className="p-3">
        {[...comments, ...added].map((comment) => (
          <article key={comment.id} className="mb-2 rounded-md border bg-muted/30 p-2">
            <p className="text-xs text-muted-foreground"><strong>{comment.author_name}</strong> · <time dateTime={comment.created_at}>{timestampFormat.format(new Date(comment.created_at))}</time></p>
            <p className="mt-1 whitespace-pre-wrap break-words">{comment.body}</p>
          </article>
        ))}
        <form onSubmit={postComment}>
          <textarea aria-label={`Komenti për pikën ${point.point}`} className={fieldClass} placeholder="Shkruaj koment" rows={2} maxLength={4000} value={body} disabled={posting} onChange={(event) => setBody(event.target.value)} />
          <Button size="sm" type="submit" variant="outline" disabled={posting || !body.trim()}>{posting ? "Duke ruajtur…" : "Shto koment"}</Button>
          {commentError && <p role="alert" className="mt-1 text-destructive">Ruajtja e komentit dështoi. Provo përsëri.</p>}
        </form>
      </td>
    </tr>
  )
}

function WeekContent({ week, apiFetch, user }: { week: string; apiFetch: ApiFetch; user: User }) {
  const [data, setData] = useState<Week | null>(null)
  const [error, setError] = useState(false)
  const [revision, setRevision] = useState(0)
  const [findingsRevision, setFindingsRevision] = useState(0)
  const [findingBatch, setFindingBatch] = useState<{ revision: number; results: Findings }>({ revision: 0, results: {} })
  const path = `/weekly-planner-short/${week}`
  const { role, department_id: departmentId } = user
  const canDecide = role === "ADMIN" || role === "MANAGER"
  const findings = findingBatch.revision === findingsRevision ? findingBatch.results : {}
  const preparing = automaticPoints.some((point) => findings[point] === undefined)

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
    void currentProjectFindings(fetchForWeek, week).then((items) => publish({ 2: items }), () => publish({ 2: "error" }))
    void externalMeetingFindings(fetchForWeek, week).then((items) => publish({ 6: items }), () => publish({ 6: "error" }))
    void noteFindings(fetchForWeek, week).then((items) => publish({ 8: items }), () => publish({ 8: "error" }))
    void waitingFindings(fetchForWeek, week).then((items) => publish({ 9: items }), () => publish({ 9: "error" }))
    void projectFindings(fetchForWeek, week, role, departmentId).then(publish, () => publish({ 4: "error", 12: "error" }))
    return () => controller.abort()
  }, [apiFetch, week, role, departmentId, findingsRevision])

  if (!data) return error ? (
    <div role="alert" className="flex items-center gap-3"><p>Java nuk u ngarkua.</p><Button variant="outline" onClick={() => { setError(false); setRevision((value) => value + 1) }}>Provo përsëri</Button></div>
  ) : <p role="status" className="text-muted-foreground">Duke ngarkuar javën…</p>

  return (
    <>
      <Button onClick={() => setFindingsRevision((value) => value + 1)} disabled={preparing}>{preparing ? "Duke kontrolluar…" : "Rifresko gjetjet"}</Button>
      <div className="overflow-x-auto rounded-lg border bg-background">
        <table className="w-full min-w-[900px] table-fixed text-sm">
          <thead className="bg-muted/50 text-left">
            <tr><th className="w-[28%] p-3">Pyetja</th><th className="w-[24%] p-3">Gjetjet</th><th className="w-[17%] p-3">Vendimi · WHO · WHEN</th><th className="p-3">Komenti</th></tr>
          </thead>
          <tbody>
            {questions.map((question, index) => {
              const point = index + 1
              return <PointRow key={point} question={question} point={data.points.find((item) => item.point === point) ?? { point, decision: null, owner: null, due_date: null }} comments={data.comments.filter((item) => item.point === point)} result={findings[point]} canDecide={canDecide} path={`${path}/points/${point}`} apiFetch={apiFetch} />
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

export default function WeeklyPlannerShortPage() {
  const { apiFetch, user } = useAuth()
  const [week, setWeek] = useState(() => monday(taskDateKey(new Date().toISOString())!))

  if (!user) return null

  return (
    <section className="space-y-4">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Weekly Planner Short</h1>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setWeek(shiftDate(week, -7))}>Java e kaluar</Button>
          <input aria-label="Zgjidh javën" type="date" className="rounded-md border border-input bg-background px-2 py-1 text-sm" value={week} onChange={(event) => { if (event.target.value) setWeek(monday(event.target.value)) }} />
          <Button variant="outline" size="sm" onClick={() => setWeek(shiftDate(week, 7))}>Java tjetër</Button>
        </div>
      </header>
      <p className="text-sm text-muted-foreground">{dateFormat.format(dateObject(week))} – {dateFormat.format(dateObject(shiftDate(week, 4)))}</p>
      <WeekContent key={week} week={week} apiFetch={apiFetch} user={user} />
    </section>
  )
}
