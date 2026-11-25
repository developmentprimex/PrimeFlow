"use client"

import * as React from "react"
import { TaskPauseBadge, TaskPauseField } from "@/components/task-pause-field"
import { currentTaskPauseDay, isTaskPausedOnDay } from "@/lib/task-pause"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Checkbox } from "@/components/ui/checkbox"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { TaskSkillField } from "@/components/task-skill-field"
import { TaskOneHMarkerEditor } from "@/components/task-one-h-marker-editor"
import { updateTaskMarkersInTree, useTaskMarkerUpdates } from "@/lib/task-marker-updates"
import { TaskMarkerComment } from "@/components/task-marker-comment"
import { useAuth } from "@/lib/auth"
import { departmentTableTag, formatDepartmentName } from "@/lib/department-name"
import { formatDateDMY, normalizeDueDateInput, toDateInputValue } from "@/lib/dates"
import { resolveProjectTitle } from "@/lib/project-display-title"
import { SKILL_CATEGORIES } from "@/lib/skills"
import { fetchUsersLookupCached } from "@/lib/users-cache"
import type { Department, GaNote, Project, SkillCategory, Task, UserLookup } from "@/lib/types"

type OpenTaskDateFilter = "all" | OpenTaskDateBucket
type OpenTaskStatusFilter = "all" | "todo" | "in_progress"
type OpenTaskTypeFilter = "project" | "system" | "personal" | "hourly" | "normal" | "high" | "r1" | "blocked" | "plan" | "fast"
type PlannerTaskDialogMode = "plan" | "edit"
type OpenTaskEditType = "normal" | "high" | "hourly" | "r1" | "personal" | "blocked"
type OpenTaskDateBucket = "overdue" | "this_week" | "next_week" | "future" | "no_date"

const ALL_VALUE = "__all__"
const NONE_VALUE = "__none__"
const PROJECT_NONE_VALUE = "__no_project__"

const pad2 = (value: number) => String(value).padStart(2, "0")
const toISODate = (value: Date) => `${value.getFullYear()}-${pad2(value.getMonth() + 1)}-${pad2(value.getDate())}`

function mondayISO(today = new Date()) {
  const d = new Date(today)
  const day = (d.getDay() + 6) % 7
  d.setDate(d.getDate() - day)
  return toISODate(d)
}

function shiftIsoDateByDays(iso: string, days: number) {
  const [year, month, day] = iso.split("-").map(Number)
  const date = new Date(year, month - 1, day)
  date.setDate(date.getDate() + days)
  return toISODate(date)
}

function taskDateKey(value?: string | null) {
  if (!value) return null
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) return value.slice(0, 10)
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return toISODate(date)
}

function taskDateBucket(
  task: Task,
  thisWeekStart: string,
  thisWeekEnd: string,
  nextWeekStart: string,
  nextWeekEnd: string
): OpenTaskDateBucket {
  const due = taskDateKey(task.due_date)
  if (!due) return "no_date"
  if (due < thisWeekStart) return "overdue"
  if (due >= thisWeekStart && due <= thisWeekEnd) return "this_week"
  if (due >= nextWeekStart && due <= nextWeekEnd) return "next_week"
  return "future"
}

function isFastPlannerTask(task: Task) {
  return !task.project_id && !task.system_template_origin_id
}

function formatDate(value: string) {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

function statusLabel(value?: string | null) {
  const normalized = (value || "TODO").toUpperCase()
  if (normalized === "IN_PROGRESS") return "In Progress"
  if (normalized === "PAUSED") return "Stopped"
  if (normalized === "WAITING_CLIENT") return "WFE"
  if (normalized === "WAITING_CONFIRMATION") return "WFC INT"
  if (normalized === "DONE") return "Done"
  return "To Do"
}

function bucketLabel(bucket: OpenTaskDateBucket) {
  if (bucket === "overdue") return "Overdue"
  if (bucket === "this_week") return "This Week"
  if (bucket === "next_week") return "Next Week"
  if (bucket === "future") return "Future"
  return "No Date"
}

function bucketBadgeClass(bucket: OpenTaskDateBucket) {
  if (bucket === "overdue") {
    return "inline-flex max-w-full whitespace-normal break-words rounded-full border border-red-200 bg-red-50 px-1.5 py-0.5 text-[11px] font-semibold uppercase leading-tight text-red-800"
  }
  if (bucket === "no_date") {
    return "inline-flex max-w-full whitespace-normal break-words rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[11px] font-semibold uppercase leading-tight text-amber-800"
  }
  if (bucket === "future") {
    return "inline-flex max-w-full whitespace-normal break-words rounded-full border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[11px] font-semibold uppercase leading-tight text-blue-800"
  }
  return "inline-flex max-w-full whitespace-normal break-words rounded-full border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[11px] font-semibold uppercase leading-tight text-emerald-800"
}

const TASK_STATUS_OPTIONS = [
  { value: "TODO", label: "To Do" },
  { value: "IN_PROGRESS", label: "In Progress" },
  { value: "WAITING_CLIENT", label: "WFE" },
  { value: "WAITING_CONFIRMATION", label: "WFC INT" },
  { value: "DONE", label: "Done" },
] as const

const TASK_TYPE_OPTIONS: Array<{ value: OpenTaskEditType; label: string }> = [
  { value: "normal", label: "Normal" },
  { value: "high", label: "High" },
  { value: "hourly", label: "1H" },
  { value: "r1", label: "R1" },
  { value: "personal", label: "Personal" },
  { value: "blocked", label: "BLLOK" },
]

const OPEN_TASK_DATE_FILTER_OPTIONS: Array<{ value: OpenTaskDateFilter; label: string }> = [
  { value: "all", label: "All open" },
  { value: "overdue", label: "Overdue" },
  { value: "this_week", label: "Due this week" },
  { value: "next_week", label: "Due next week" },
  { value: "future", label: "Future" },
  { value: "no_date", label: "No date" },
]

const OPEN_TASK_STATUS_FILTER_OPTIONS: Array<{ value: OpenTaskStatusFilter; label: string }> = [
  { value: "all", label: "All statuses" },
  { value: "todo", label: "To Do" },
  { value: "in_progress", label: "In Progress" },
]

const OPEN_TASK_TYPE_FILTER_OPTIONS: Array<{ value: OpenTaskTypeFilter; label: string }> = [
  { value: "project", label: "Project" },
  { value: "system", label: "System" },
  { value: "personal", label: "P" },
  { value: "hourly", label: "1H" },
  { value: "normal", label: "Normal" },
  { value: "high", label: "High" },
  { value: "r1", label: "R1" },
  { value: "blocked", label: "BLLOK" },
  { value: "plan", label: "Plan note" },
  { value: "fast", label: "Fast task" },
]

const FINISH_PERIOD_OPTIONS = ["AM", "PM"] as const

function taskEditType(task: Task): OpenTaskEditType {
  if (task.is_bllok) return "blocked"
  if (task.is_1h_report) return "hourly"
  if (task.is_r1) return "r1"
  if (task.is_personal) return "personal"
  if (task.priority === "HIGH") return "high"
  return "normal"
}

function taskMatchesTypeFilter(task: Task, value: OpenTaskTypeFilter) {
  if (value === "project") return Boolean(task.project_id)
  if (value === "system") return Boolean(task.system_template_origin_id)
  if (value === "plan") return Boolean(task.plan_note_origin_id)
  if (value === "fast") return isFastPlannerTask(task)
  if (value === "personal") return Boolean(task.is_personal)
  if (value === "hourly") return Boolean(task.is_1h_report)
  if (value === "high") return task.priority === "HIGH"
  if (value === "r1") return Boolean(task.is_r1)
  if (value === "blocked") return Boolean(task.is_bllok)
  return taskEditType(task) === "normal"
}

function renderHighlightedAddedText(value: string) {
  const parts: React.ReactNode[] = []
  const markerPattern = /\[\[added\]\]([\s\S]*?)\[\[\/added\]\]/gi
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = markerPattern.exec(value)) !== null) {
    if (match.index > lastIndex) parts.push(value.slice(lastIndex, match.index))
    parts.push(
      <span key={`${match.index}-${markerPattern.lastIndex}`} className="rounded-sm bg-blue-100 px-0.5 text-blue-900">
        {match[1]}
      </span>
    )
    lastIndex = markerPattern.lastIndex
  }

  if (lastIndex < value.length) parts.push(value.slice(lastIndex))
  return parts.length ? parts : value
}

function initialsFromDisplayName(name: string) {
  const t = name.trim()
  if (!t) return "?"
  const parts = t.split(/\s+/).filter(Boolean)
  if (parts.length === 1) {
    const w = parts[0]
    return (w.length >= 2 ? w[0] + w[1] : w[0]).toUpperCase()
  }
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

export default function OpenTasksPage() {
  const { apiFetch, user } = useAuth()
  const [departments, setDepartments] = React.useState<Department[]>([])
  const [projects, setProjects] = React.useState<Project[]>([])
  const [users, setUsers] = React.useState<UserLookup[]>([])
  const [tasks, setTasks] = React.useState<Task[]>([])
  useTaskMarkerUpdates(update => setTasks(current => updateTaskMarkersInTree(current, update)))
  const [notes, setNotes] = React.useState<GaNote[]>([])
  const [departmentId, setDepartmentId] = React.useState(ALL_VALUE)
  const [dateFilter, setDateFilter] = React.useState<OpenTaskDateFilter>("all")
  const [statusFilter, setStatusFilter] = React.useState<OpenTaskStatusFilter>("all")
  const [pausedOnly, setPausedOnly] = React.useState(false)
  const pauseDay = currentTaskPauseDay()
  const [skillFilter, setSkillFilter] = React.useState<SkillCategory | typeof ALL_VALUE>(ALL_VALUE)
  const [typeFilters, setTypeFilters] = React.useState<OpenTaskTypeFilter[]>([])
  const [userId, setUserId] = React.useState(ALL_VALUE)
  const [search, setSearch] = React.useState("")
  const [loading, setLoading] = React.useState(true)
  const [dialogOpen, setDialogOpen] = React.useState(false)
  const [dialogMode, setDialogMode] = React.useState<PlannerTaskDialogMode>("plan")
  const [selectedTask, setSelectedTask] = React.useState<Task | null>(null)
  const [taskTitle, setTaskTitle] = React.useState("")
  const [taskDescription, setTaskDescription] = React.useState("")
  const [taskType, setTaskType] = React.useState<OpenTaskEditType>("normal")
  const [taskStatus, setTaskStatus] = React.useState("TODO")
  const [pauseDays, setPauseDays] = React.useState<number | null>()
  const [taskDepartmentId, setTaskDepartmentId] = React.useState(ALL_VALUE)
  const [taskProjectId, setTaskProjectId] = React.useState(PROJECT_NONE_VALUE)
  const [deadlineImportant, setDeadlineImportant] = React.useState(false)
  const [startDate, setStartDate] = React.useState("")
  const [dueDate, setDueDate] = React.useState("")
  const [finishPeriod, setFinishPeriod] = React.useState<"AM" | "PM" | typeof NONE_VALUE>("AM")
  const [assigneeIds, setAssigneeIds] = React.useState<string[]>([])
  const [skillCategory, setSkillCategory] = React.useState<SkillCategory | null>(null)
  const [saving, setSaving] = React.useState(false)
  const [exportingExcel, setExportingExcel] = React.useState(false)
  const [importingBaseline, setImportingBaseline] = React.useState(false)
  const [resettingBaseline, setResettingBaseline] = React.useState(false)
  const baselineFileInputRef = React.useRef<HTMLInputElement>(null)

  const thisWeekStart = React.useMemo(() => mondayISO(), [])
  const thisWeekEnd = React.useMemo(() => shiftIsoDateByDays(thisWeekStart, 4), [thisWeekStart])
  const nextWeekStart = React.useMemo(() => shiftIsoDateByDays(thisWeekStart, 7), [thisWeekStart])
  const nextWeekEnd = React.useMemo(() => shiftIsoDateByDays(nextWeekStart, 4), [nextWeekStart])

  const loadLookups = React.useCallback(async () => {
    const [depRes, projectRes] = await Promise.all([apiFetch("/departments"), apiFetch("/projects?include_templates=true")])
    if (depRes.ok) setDepartments((await depRes.json()) as Department[])
    if (projectRes.ok) setProjects((await projectRes.json()) as Project[])
    const usersList = await fetchUsersLookupCached(apiFetch)
    if (usersList) setUsers((usersList as UserLookup[]).filter((item) => item.is_active))
  }, [apiFetch])

  const loadTasks = React.useCallback(async () => {
    setLoading(true)
    try {
      const taskParams = new URLSearchParams()
      taskParams.set("include_done", "false")
      taskParams.set("include_all_departments", "true")
      if (departmentId !== ALL_VALUE) taskParams.set("department_id", departmentId)

      const noteParams = new URLSearchParams()
      if (departmentId !== ALL_VALUE) noteParams.set("department_id", departmentId)

      const [tasksRes, notesRes] = await Promise.all([
        apiFetch(`/tasks?${taskParams.toString()}`),
        apiFetch(`/ga-notes${noteParams.toString() ? `?${noteParams.toString()}` : ""}`),
      ])

      setTasks(tasksRes.ok ? ((await tasksRes.json()) as Task[]) : [])
      setNotes(notesRes.ok ? ((await notesRes.json()) as GaNote[]) : [])
    } catch (error) {
      console.error("Failed to load open tasks", error)
      toast.error("Failed to load open tasks")
      setTasks([])
      setNotes([])
    } finally {
      setLoading(false)
    }
  }, [apiFetch, departmentId])

  React.useEffect(() => {
    void loadLookups()
  }, [loadLookups])

  React.useEffect(() => {
    if (user?.role === "STAFF" && user.department_id) {
      setDepartmentId(user.department_id)
    }
  }, [user?.department_id, user?.role])

  React.useEffect(() => {
    void loadTasks()
  }, [loadTasks])

  const userById = React.useMemo(() => new Map(users.map((item) => [item.id, item])), [users])
  const noteById = React.useMemo(() => new Map(notes.map((item) => [item.id, item])), [notes])
  const departmentById = React.useMemo(() => new Map(departments.map((item) => [item.id, item])), [departments])
  const projectById = React.useMemo(() => new Map(projects.map((item) => [item.id, item])), [projects])

  const taskAssigneeIds = React.useCallback((task: Task) => {
    const ids = new Set<string>()
    if (task.assigned_to) ids.add(task.assigned_to)
    for (const assignee of task.assignees || []) {
      if (assignee.id) ids.add(assignee.id)
    }
    return Array.from(ids)
  }, [])

  const assigneeLabel = React.useCallback(
    (task: Task) => {
      const ids = taskAssigneeIds(task)
      if (!ids.length) return "Unassigned"
      return ids.map((id) => userById.get(id)?.full_name || userById.get(id)?.username || id).join(", ")
    },
    [taskAssigneeIds, userById]
  )

  const assigneeInitialsLabel = React.useCallback(
    (task: Task) => {
      const ids = taskAssigneeIds(task)
      if (!ids.length) return "—"
      return ids
        .map((id) => {
          const u = userById.get(id)
          const name = u?.full_name || u?.username || id
          return initialsFromDisplayName(String(name))
        })
        .join(", ")
    },
    [taskAssigneeIds, userById]
  )

  const sourceLabel = React.useCallback((task: Task) => {
    if (task.ga_note_origin_id || task.plan_note_origin_id) return "GA/KA"
    if (task.system_template_origin_id) return "System"
    if (task.project_id) return "Project"
    if (task.is_bllok) return "BLL"
    if (task.is_r1) return "R1"
    if (task.is_1h_report) return "1H"
    if (task.is_personal) return "P:"
    return "Fast"
  }, [])

  const userOptions = React.useMemo(() => {
    const scoped = departmentId !== ALL_VALUE ? users.filter((item) => item.department_id === departmentId) : users
    return scoped
      .map((item) => ({ id: item.id, name: item.full_name || item.username || item.id }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [departmentId, users])

  const dialogProjectOptions = React.useMemo(() => {
    const scoped = taskDepartmentId !== ALL_VALUE
      ? projects.filter((project) => project.department_id === taskDepartmentId)
      : projects
    return scoped
      .filter((project) => !project.is_template)
      .map((project) => ({ id: project.id, name: resolveProjectTitle(project) || project.title || project.name || "Untitled project" }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [projects, taskDepartmentId])

  const dialogAssigneeOptions = React.useMemo(() => {
    const scoped = taskDepartmentId !== ALL_VALUE ? users.filter((item) => item.department_id === taskDepartmentId) : users
    return scoped
      .map((item) => ({ id: item.id, name: item.full_name || item.username || item.id }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [taskDepartmentId, users])

  const filteredTasks = React.useMemo(() => {
    const query = search.trim().toLowerCase()
    return tasks.filter((task) => {
      const project = task.project_id ? projectById.get(task.project_id) : null
      if (project?.is_template) return false

      const dateBucket = taskDateBucket(task, thisWeekStart, thisWeekEnd, nextWeekStart, nextWeekEnd)
      const ids = taskAssigneeIds(task)

      if (userId !== ALL_VALUE && !ids.includes(userId)) return false
      if (dateFilter !== "all" && dateBucket !== dateFilter) return false
      if (statusFilter === "todo" && (task.status || "TODO").toUpperCase() !== "TODO") return false
      if (statusFilter === "in_progress" && (task.status || "").toUpperCase() !== "IN_PROGRESS") return false
      if (pausedOnly && !isTaskPausedOnDay(task, pauseDay)) return false
      if (skillFilter !== ALL_VALUE && task.skill_category !== skillFilter) return false
      if (typeFilters.length && !typeFilters.some((value) => taskMatchesTypeFilter(task, value))) return false
      if (query) {
        const note = task.ga_note_origin_id ? noteById.get(task.ga_note_origin_id) : null
        const dept = task.department_id ? departmentById.get(task.department_id) : null
        const haystack = [
          statusLabel(task.status),
          task.title,
          task.description,
          task.status,
          sourceLabel(task),
          task.plan_note_origin_id ? "next week plan note px jav" : "",
          assigneeLabel(task),
          assigneeInitialsLabel(task),
          note?.content,
          project ? resolveProjectTitle(project) : "",
          dept ? departmentTableTag(dept) : "",
          dept ? formatDepartmentName(dept.name) : "",
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
        if (!haystack.includes(query)) return false
      }
      return true
    })
  }, [assigneeInitialsLabel, assigneeLabel, dateFilter, departmentById, nextWeekEnd, nextWeekStart, noteById, pauseDay, pausedOnly, projectById, search, skillFilter, sourceLabel, statusFilter, taskAssigneeIds, tasks, thisWeekEnd, thisWeekStart, typeFilters, userId])

  const bucketCounts = React.useMemo(() => {
    const counts: Record<OpenTaskDateBucket, number> = {
      overdue: 0,
      this_week: 0,
      next_week: 0,
      future: 0,
      no_date: 0,
    }
    for (const task of filteredTasks) {
      counts[taskDateBucket(task, thisWeekStart, thisWeekEnd, nextWeekStart, nextWeekEnd)] += 1
    }
    return counts
  }, [filteredTasks, nextWeekEnd, nextWeekStart, thisWeekEnd, thisWeekStart])

  const tableRows = React.useMemo(
    () =>
      filteredTasks.map((task) => {
        const dateBucket = taskDateBucket(task, thisWeekStart, thisWeekEnd, nextWeekStart, nextWeekEnd)

        return {
          task,
          dateBucket,
          planned: dateBucket !== "no_date",
        }
      }),
    [filteredTasks, nextWeekEnd, nextWeekStart, thisWeekEnd, thisWeekStart]
  )

  const openDialog = (task: Task, mode: PlannerTaskDialogMode) => {
    setSelectedTask(task)
    setDialogMode(mode)
    setTaskTitle(task.title || "")
    setTaskDescription(task.description || "")
    setTaskType(taskEditType(task))
    setTaskStatus(task.status || "TODO")
    setPauseDays(undefined)
    setTaskDepartmentId(task.department_id || ALL_VALUE)
    setTaskProjectId(task.project_id || PROJECT_NONE_VALUE)
    setDeadlineImportant(Boolean(task.is_deadline_important))
    setStartDate(toDateInputValue(task.start_date))
    setDueDate(toDateInputValue(task.due_date))
    setFinishPeriod((task.finish_period as "AM" | "PM" | null) || NONE_VALUE)
    setAssigneeIds(taskAssigneeIds(task))
    setSkillCategory(task.skill_category || null)
    setDialogOpen(true)
  }

  const parseFilenameFromDisposition = (headerValue: string | null) => {
    if (!headerValue) return null
    const match = headerValue.match(/filename=\"?([^\";]+)\"?/i)
    return match ? match[1] : null
  }

  const exportOpenTasksExcel = async () => {
    if (exportingExcel) return
    setExportingExcel(true)
    try {
      const qs = new URLSearchParams()
      qs.set("this_week_start", thisWeekStart)
      qs.set("filter", dateFilter)
      if (statusFilter !== "all") qs.set("status_filter", statusFilter)
      if (pausedOnly) qs.set("paused_only", "true")
      for (const value of typeFilters) qs.append("type_filter", value)
      if (departmentId !== ALL_VALUE) qs.set("department_id", departmentId)
      if (userId !== ALL_VALUE) qs.set("user_id", userId)
      if (search.trim()) qs.set("search", search.trim())

      const res = await apiFetch(`/exports/open-tasks.xlsx?${qs.toString()}`)
      if (!res.ok) {
        const detail = await res.text().catch(() => "")
        toast.error(detail || "Failed to export open tasks.")
        return
      }
      const blob = await res.blob()
      if (!blob.size) {
        toast.error("Export returned an empty file.")
        return
      }
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = parseFilenameFromDisposition(res.headers.get("content-disposition")) || "OPEN_TASKS.xlsx"
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (error) {
      console.error("Failed to export open tasks", error)
      toast.error("Failed to export open tasks.")
    } finally {
      setExportingExcel(false)
    }
  }

  const importOpenTasksBaseline = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ""
    if (!file || importingBaseline) return
    setImportingBaseline(true)
    try {
      const body = new FormData()
      body.append("file", file)
      const res = await apiFetch("/exports/open-tasks/baseline", { method: "POST", body })
      if (!res.ok) {
        const raw = await res.text().catch(() => "")
        let detail = raw
        try {
          detail = (JSON.parse(raw) as { detail?: string }).detail || raw
        } catch {
          // Keep the plain response when it is not JSON.
        }
        toast.error(detail || "Failed to import the pre-plan Excel.")
        return
      }
      const result = (await res.json()) as { imported: number; planning_week_start: string }
      toast.success(`Saved ${result.imported} pre-plan task values for the week of ${result.planning_week_start}.`)
    } catch (error) {
      console.error("Failed to import open task baseline", error)
      toast.error("Failed to import the pre-plan Excel.")
    } finally {
      setImportingBaseline(false)
    }
  }

  const resetOpenTasksBaseline = async () => {
    if (resettingBaseline) return
    const confirmed = window.confirm(
      `Reset your imported pre-plan for ${formatDate(nextWeekStart)} - ${formatDate(nextWeekEnd)}? This will not change any tasks. To restore the comparison, you must import the Excel again.`
    )
    if (!confirmed) return

    setResettingBaseline(true)
    try {
      const qs = new URLSearchParams({ planning_week_start: nextWeekStart })
      const res = await apiFetch(`/exports/open-tasks/baseline?${qs.toString()}`, { method: "DELETE" })
      if (!res.ok) {
        const raw = await res.text().catch(() => "")
        let detail = raw
        try {
          detail = (JSON.parse(raw) as { detail?: string }).detail || raw
        } catch {
          // Keep the plain response when it is not JSON.
        }
        toast.error(detail || "Failed to reset the pre-plan import.")
        return
      }
      const result = (await res.json()) as { deleted: number; planning_week_start: string }
      toast.success(
        result.deleted
          ? `Reset ${result.deleted} imported pre-plan task values.`
          : "No imported pre-plan values were found for this planning week."
      )
    } catch (error) {
      console.error("Failed to reset open task baseline", error)
      toast.error("Failed to reset the pre-plan import.")
    } finally {
      setResettingBaseline(false)
    }
  }

  const saveTask = async () => {
    if (!selectedTask) return
    const isNoteOriginTask = Boolean(selectedTask.ga_note_origin_id || selectedTask.plan_note_origin_id)
    const nextTitle = taskTitle.trim()
    if (!isNoteOriginTask && nextTitle.length < 2) {
      toast.error("Title must be at least 2 characters.")
      return
    }
    if (startDate && dueDate && startDate > dueDate) {
      toast.error("Start date cannot be after due date.")
      return
    }
    if (!isNoteOriginTask && taskStatus === "WAITING_CONFIRMATION" && !selectedTask.confirmation_assignee_id) {
      toast.error("This task needs a confirmation assignee before it can use WFC INT.")
      return
    }
    setSaving(true)
    try {
      const updatePayload = isNoteOriginTask
        ? {
            // Shared note definition and membership are controlled from GA Notes / PX JAV.
            // Execution status and scheduling belong to this person's copy.
            status: taskStatus !== selectedTask.status ? taskStatus : undefined,
            pause_days: taskStatus === "DONE" ? undefined : pauseDays,
            start_date: startDate ? new Date(startDate).toISOString() : null,
            due_date: dueDate ? new Date(dueDate).toISOString() : null,
            finish_period: finishPeriod === NONE_VALUE ? null : finishPeriod,
            is_deadline_important: deadlineImportant,
            priority: taskType === "high" ? "HIGH" : "NORMAL",
            is_bllok: taskType === "blocked",
            is_1h_report: taskType === "hourly",
            is_r1: taskType === "r1",
            is_personal: taskType === "personal",
          }
        : {
            title: nextTitle,
            description: taskDescription,
            status: taskStatus !== selectedTask.status ? taskStatus : undefined,
            pause_days: taskStatus === "DONE" ? undefined : pauseDays,
            priority: taskType === "high" ? "HIGH" : "NORMAL",
            is_bllok: taskType === "blocked",
            is_1h_report: taskType === "hourly",
            is_r1: taskType === "r1",
            is_personal: taskType === "personal",
            department_id: taskDepartmentId === ALL_VALUE ? null : taskDepartmentId,
            project_id: taskProjectId === PROJECT_NONE_VALUE ? null : taskProjectId,
            start_date: startDate ? new Date(startDate).toISOString() : null,
            due_date: dueDate ? new Date(dueDate).toISOString() : null,
            finish_period: finishPeriod === NONE_VALUE ? null : finishPeriod,
            is_deadline_important: deadlineImportant,
            assigned_to: assigneeIds[0] ?? null,
            assignees: assigneeIds,
            skill_category: skillCategory,
          }
      const res = await apiFetch(`/tasks/${selectedTask.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updatePayload),
      })
      if (!res.ok) {
        toast.error("Failed to update task planning.")
        return
      }
      const updated = (await res.json()) as Task
      setTasks((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
      setDialogOpen(false)
      setSelectedTask(null)
      toast.success(dialogMode === "plan" ? "Task planned." : "Task planning updated.")
      void loadTasks()
    } finally {
      setSaving(false)
    }
  }

  const toggleTypeFilter = (value: OpenTaskTypeFilter) => {
    setTypeFilters((prev) => (prev.includes(value) ? prev.filter((item) => item !== value) : [...prev, value]))
  }

  const selectedTypeFilterLabel = typeFilters.length
    ? OPEN_TASK_TYPE_FILTER_OPTIONS.filter((option) => typeFilters.includes(option.value)).map((option) => option.label).join(", ")
    : "All types"

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Open Tasks</h1>
          <p className="text-sm text-slate-500">
            Open tasks grouped by due date: this week {formatDate(thisWeekStart)} - {formatDate(thisWeekEnd)}, next week {formatDate(nextWeekStart)} - {formatDate(nextWeekEnd)}.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            ref={baselineFileInputRef}
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            className="hidden"
            onChange={(event) => void importOpenTasksBaseline(event)}
          />
          <Button variant="outline" disabled={loading || exportingExcel || resettingBaseline} onClick={() => void exportOpenTasksExcel()}>
            {exportingExcel ? "Exporting..." : "Export Excel"}
          </Button>
          <Button
            variant="outline"
            disabled={loading || exportingExcel || importingBaseline || resettingBaseline}
            onClick={() => baselineFileInputRef.current?.click()}
          >
            {importingBaseline ? "Importing..." : "Import Pre-Plan Excel"}
          </Button>
          <Button
            variant="destructive"
            disabled={loading || exportingExcel || importingBaseline || resettingBaseline}
            onClick={() => void resetOpenTasksBaseline()}
          >
            {resettingBaseline ? "Resetting..." : "Reset Pre-Plan Import"}
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="pt-6">
          <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search open tasks..." />
            <Select value={dateFilter} onValueChange={(value) => setDateFilter(value as OpenTaskDateFilter)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {OPEN_TASK_DATE_FILTER_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value as OpenTaskStatusFilter)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {OPEN_TASK_STATUS_FILTER_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button type="button" variant={pausedOnly ? "secondary" : "outline"} aria-pressed={pausedOnly} onClick={() => setPausedOnly(!pausedOnly)}>
              Vetëm në pauzë
            </Button>
            <Select value={skillFilter} onValueChange={(value) => setSkillFilter(value as SkillCategory | typeof ALL_VALUE)}>
              <SelectTrigger><SelectValue placeholder="Lloji i punës" /></SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_VALUE}>Të gjitha aftësitë</SelectItem>
                {SKILL_CATEGORIES.map((category) => (
                  <SelectItem key={category.id} value={category.id}>{category.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  className="min-w-0 justify-start overflow-hidden text-ellipsis whitespace-nowrap font-normal"
                  title={selectedTypeFilterLabel}
                >
                  {selectedTypeFilterLabel}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-56">
                <DropdownMenuItem onSelect={() => setTypeFilters([])}>All types</DropdownMenuItem>
                <DropdownMenuSeparator />
                {OPEN_TASK_TYPE_FILTER_OPTIONS.map((option) => (
                  <DropdownMenuCheckboxItem
                    key={option.value}
                    checked={typeFilters.includes(option.value)}
                    onCheckedChange={() => toggleTypeFilter(option.value)}
                    onSelect={(event) => event.preventDefault()}
                  >
                    {option.label}
                  </DropdownMenuCheckboxItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
            <Select value={departmentId} onValueChange={setDepartmentId} disabled={user?.role === "STAFF"}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_VALUE}>All departments</SelectItem>
                {departments.map((department) => (
                  <SelectItem key={department.id} value={department.id}>{formatDepartmentName(department.name)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={userId} onValueChange={setUserId}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_VALUE}>All users</SelectItem>
                {userOptions.map((option) => (
                  <SelectItem key={option.id} value={option.id}>{option.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {loading ? (
        <div className="text-sm text-slate-500">Loading open tasks...</div>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Card><CardContent className="pt-6 text-center"><div className="text-2xl font-semibold text-red-700">{bucketCounts.overdue}</div><div className="text-xs text-slate-500">Overdue</div></CardContent></Card>
            <Card><CardContent className="pt-6 text-center"><div className="text-2xl font-semibold text-emerald-800">{bucketCounts.this_week}</div><div className="text-xs text-slate-500">This Week</div></CardContent></Card>
            <Card><CardContent className="pt-6 text-center"><div className="text-2xl font-semibold text-emerald-800">{bucketCounts.next_week}</div><div className="text-xs text-slate-500">Next Week</div></CardContent></Card>
            <Card><CardContent className="pt-6 text-center"><div className="text-2xl font-semibold text-blue-800">{bucketCounts.future}</div><div className="text-xs text-slate-500">Future</div></CardContent></Card>
            <Card><CardContent className="pt-6 text-center"><div className="text-2xl font-semibold text-amber-700">{bucketCounts.no_date}</div><div className="text-xs text-slate-500">No Date</div></CardContent></Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Open Tasks ({tableRows.length})</CardTitle>
              <div className="text-xs text-slate-500">
                Table view of open tasks with planning, ownership, date details, and actions.
              </div>
            </CardHeader>
            <CardContent>
              <Table className="w-full min-w-[1180px] table-fixed border-collapse text-[15px] [&_td]:border-r [&_td]:border-slate-200 [&_td:last-child]:border-r-0 [&_th]:border-r [&_th]:border-slate-200 [&_th:last-child]:border-r-0">
                <colgroup>
                  <col style={{ width: "32px" }} />
                  <col style={{ width: "128px" }} />
                  <col />
                  <col style={{ width: "72px" }} />
                  <col style={{ width: "54px" }} />
                  <col style={{ width: "88px" }} />
                  <col style={{ width: "56px" }} />
                  <col style={{ width: "52px" }} />
                  <col style={{ width: "86px" }} />
                  <col style={{ width: "96px" }} />
                  <col style={{ width: "104px" }} />
                </colgroup>
                <TableHeader>
                  <TableRow>
                    <TableHead className="h-auto px-1.5 py-2 text-[13px] font-semibold">#</TableHead>
                    <TableHead className="h-auto px-1.5 py-2 text-[13px] font-semibold" title="Group / plan status">
                      Group
                    </TableHead>
                    <TableHead className="h-auto min-w-0 px-1.5 py-2 text-[13px] font-semibold">Task</TableHead>
                    <TableHead className="h-auto px-1.5 py-2 text-[13px] font-semibold">Source</TableHead>
                    <TableHead className="h-auto px-1 py-2 text-center text-[13px] font-semibold" title="PX JAV">
                      PX JAV
                    </TableHead>
                    <TableHead className="h-auto whitespace-normal px-1.5 py-2 text-[13px] font-semibold leading-tight">Status</TableHead>
                    <TableHead className="h-auto px-1.5 py-2 text-[13px] font-semibold">Who</TableHead>
                    <TableHead className="h-auto px-1.5 py-2 text-[13px] font-semibold" title="Department">
                      Dep
                    </TableHead>
                    <TableHead className="h-auto px-1.5 py-2 text-[13px] font-semibold leading-tight">Due date</TableHead>
                    <TableHead className="h-auto px-1.5 py-2 text-[13px] font-semibold leading-tight">Date created</TableHead>
                    <TableHead className="h-auto px-1.5 py-2 text-[13px] font-semibold">Act</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tableRows.length ? (
                    tableRows.map(({ task, dateBucket, planned }, index) => {
                      const department = task.department_id ? departmentById.get(task.department_id) : null
                      const dueLabel = task.due_date ? formatDateDMY(task.due_date) : "-"

                      return (
                        <TableRow key={task.id} className="align-middle">
                          <TableCell className="px-1.5 py-2 align-middle text-[13px] font-medium text-slate-600">{index + 1}</TableCell>
                          <TableCell className="min-w-0 whitespace-normal px-1.5 py-2 align-middle">
                            <span
                              className={bucketBadgeClass(dateBucket)}
                              title={bucketLabel(dateBucket)}
                            >
                              {bucketLabel(dateBucket)}
                            </span>
                          </TableCell>
                          <TableCell className="min-w-0 whitespace-normal px-1.5 py-2 align-middle">
                            <div className="flex items-start gap-1.5 break-words text-sm font-medium leading-snug text-slate-900">
                              <TaskOneHMarkerEditor taskId={task.id} marker={task.one_h_marker} markerByGa={task.one_h_marker_by_ga} markerComment={task.one_h_marker_comment} />
                              <span className="min-w-0"><TaskMarkerComment comment={task.one_h_marker_comment} taskId={task.id} />{renderHighlightedAddedText(task.title)}</span>
                            </div>
                          </TableCell>
                          <TableCell className="px-1.5 py-2 align-middle text-[13px] uppercase text-slate-700">{sourceLabel(task)}</TableCell>
                          <TableCell className="whitespace-normal px-1 py-2 text-center align-middle text-slate-700">
                            {task.plan_note_origin_id ? (
                              <span className="inline-flex rounded-full border border-indigo-200 bg-indigo-50 px-1.5 py-0 text-[11px] font-semibold uppercase text-indigo-700">
                                Y
                              </span>
                            ) : (
                              <span className="text-xs text-slate-400">—</span>
                            )}
                          </TableCell>
                          <TableCell className="min-w-0 whitespace-normal px-1.5 py-2 align-middle text-[13px] uppercase leading-snug text-slate-700">
                            {statusLabel(task.status)}
                            {isTaskPausedOnDay(task, pauseDay) && <TaskPauseBadge />}
                          </TableCell>
                          <TableCell className="px-1.5 py-2 align-middle text-[13px] text-slate-700" title={assigneeLabel(task)}>
                            {assigneeInitialsLabel(task)}
                          </TableCell>
                          <TableCell className="px-1.5 py-2 align-middle text-[13px] uppercase text-slate-700" title={department ? formatDepartmentName(department.name) : undefined}>
                            {departmentTableTag(department)}
                          </TableCell>
                          <TableCell className="whitespace-normal px-1.5 py-2 align-middle tabular-nums text-[13px] leading-tight text-slate-700">{dueLabel}</TableCell>
                          <TableCell className="whitespace-normal px-1.5 py-2 align-middle tabular-nums text-[13px] leading-tight text-slate-700">
                            {formatDateDMY(task.created_at)}
                          </TableCell>
                          <TableCell className="min-w-0 whitespace-normal px-1.5 py-2 align-middle">
                            <div className="flex max-w-[10.5rem] flex-row flex-wrap items-center gap-0.5">
                              <Button size="sm" className="h-6 min-h-0 shrink-0 px-1.5 py-0 text-[11px] leading-tight" onClick={() => openDialog(task, planned ? "edit" : "plan")}>
                                {planned ? "Edit" : "Plan"}
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      )
                    })
                  ) : (
                    <TableRow>
                      <TableCell colSpan={11} className="py-8 text-center text-sm text-slate-500">
                        No open tasks match the current filters.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}

      <Dialog open={dialogOpen} onOpenChange={(open) => (!saving ? setDialogOpen(open) : undefined)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
          <DialogHeader>
            <DialogTitle>{dialogMode === "plan" ? "Plan task" : "Edit task"}</DialogTitle>
          </DialogHeader>
          {selectedTask ? (
            <div className="space-y-4">
              {selectedTask.ga_note_origin_id || selectedTask.plan_note_origin_id ? (
                <div className="rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800">
                  {selectedTask.plan_note_origin_id
                    ? "This is your independent PX JAV task copy. Edit its status and scheduling here; source details come from PX JAV and assignees are fixed from creation."
                    : "This is your independent GA task copy. Edit its status and scheduling here; shared details and assignees are managed in GA Notes."}
                </div>
              ) : null}
              <div className="space-y-2">
                <Label>Title</Label>
                <Textarea
                  value={taskTitle}
                  disabled={saving || Boolean(selectedTask.ga_note_origin_id || selectedTask.plan_note_origin_id)}
                  onChange={(event) => setTaskTitle(event.target.value)}
                  className="min-h-[72px]"
                />
              </div>
              <div className="space-y-2">
                <Label>Description</Label>
                <Textarea
                  value={taskDescription}
                  disabled={saving || Boolean(selectedTask.ga_note_origin_id || selectedTask.plan_note_origin_id)}
                  onChange={(event) => setTaskDescription(event.target.value)}
                  className="min-h-[72px]"
                />
              </div>
              <div className="grid gap-3 md:grid-cols-3">
                <div className="space-y-2">
                  <Label>Type</Label>
                  <Select value={taskType} disabled={saving} onValueChange={(value) => setTaskType(value as OpenTaskEditType)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {TASK_TYPE_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Status</Label>
                  <Select value={taskStatus} disabled={saving} onValueChange={setTaskStatus}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {TASK_STATUS_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {!selectedTask?.question_origin_id && taskStatus !== "DONE" && <TaskPauseField value={pauseDays} onChange={setPauseDays} until={selectedTask?.pause_until} />}
                <div className="space-y-2">
                  <Label>Finish by</Label>
                  <Select value={finishPeriod} disabled={saving} onValueChange={(value) => setFinishPeriod(value as "AM" | "PM" | typeof NONE_VALUE)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NONE_VALUE}>None / all day</SelectItem>
                      {FINISH_PERIOD_OPTIONS.map((value) => (
                        <SelectItem key={value} value={value}>{value}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Start date</Label>
                  <Input type="date" value={startDate} disabled={saving} onChange={(event) => setStartDate(normalizeDueDateInput(event.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>Due date</Label>
                  <Input type="date" value={dueDate} disabled={saving} onChange={(event) => setDueDate(normalizeDueDateInput(event.target.value))} />
                </div>
              </div>
              <label className="flex items-center gap-3 rounded-md border px-3 py-2">
                <Checkbox
                  checked={deadlineImportant}
                  disabled={saving}
                  onCheckedChange={(checked) => setDeadlineImportant(checked === true)}
                />
                <span className="text-sm font-medium">Deadline important</span>
              </label>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Department</Label>
                  <Select
                    value={taskDepartmentId}
                    disabled={saving || Boolean(selectedTask.ga_note_origin_id || selectedTask.plan_note_origin_id)}
                    onValueChange={(value) => {
                      setTaskDepartmentId(value)
                      setTaskProjectId(PROJECT_NONE_VALUE)
                    }}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value={ALL_VALUE}>No department</SelectItem>
                      {departments.map((department) => (
                        <SelectItem key={department.id} value={department.id}>
                          {formatDepartmentName(department.name)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Project</Label>
                  <Select
                    value={taskProjectId}
                    disabled={saving || Boolean(selectedTask.ga_note_origin_id || selectedTask.plan_note_origin_id)}
                    onValueChange={(value) => {
                      setTaskProjectId(value)
                      const project = projects.find((item) => item.id === value)
                      if (project?.department_id) setTaskDepartmentId(project.department_id)
                    }}
                  >
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value={PROJECT_NONE_VALUE}>No project</SelectItem>
                      {dialogProjectOptions.map((project) => (
                        <SelectItem key={project.id} value={project.id}>{project.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="space-y-2">
                <Label>Assignees</Label>
                <div className="rounded-md border bg-white p-2">
                  <div className="mb-2 flex flex-wrap gap-2">
                    {assigneeIds.length ? assigneeIds.map((id) => {
                      const person = userById.get(id)
                      return (
                        <button key={id} type="button" disabled={saving || Boolean(selectedTask.ga_note_origin_id || selectedTask.plan_note_origin_id)} className="rounded-full bg-slate-100 px-2 py-0.5 text-xs" onClick={() => setAssigneeIds((prev) => prev.filter((item) => item !== id))}>
                          {person?.full_name || person?.username || id} <span className="text-slate-500">x</span>
                        </button>
                      )
                    }) : <span className="text-xs text-slate-500">No assignees selected.</span>}
                  </div>
                  <Select value="__picker__" disabled={saving || Boolean(selectedTask.ga_note_origin_id || selectedTask.plan_note_origin_id) || dialogAssigneeOptions.length === 0} onValueChange={(value) => {
                    if (value === "__picker__") return
                    setAssigneeIds((prev) => (prev.includes(value) ? prev : [...prev, value]))
                    const person = users.find((item) => item.id === value)
                    if (person?.department_id && taskDepartmentId === ALL_VALUE) setTaskDepartmentId(person.department_id)
                  }}>
                    <SelectTrigger><SelectValue placeholder="Add assignee" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__picker__" disabled>Add assignee</SelectItem>
                      {dialogAssigneeOptions.filter((option) => !assigneeIds.includes(option.id)).map((option) => (
                        <SelectItem key={option.id} value={option.id}>{option.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <TaskSkillField
                value={skillCategory}
                onChange={setSkillCategory}
                disabled={saving || Boolean(selectedTask.ga_note_origin_id || selectedTask.plan_note_origin_id)}
                selectedAssigneeIds={assigneeIds}
                onSelectCandidate={(candidateId) => setAssigneeIds((previous) => previous.includes(candidateId) ? previous : [...previous, candidateId])}
              />
              <div className="flex justify-end gap-2">
                <Button variant="outline" disabled={saving} onClick={() => setDialogOpen(false)}>Cancel</Button>
                <Button disabled={saving} onClick={() => void saveTask()}>{saving ? "Saving..." : "Save task"}</Button>
              </div>
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  )
}
