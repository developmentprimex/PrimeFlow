"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname, useRouter, useSearchParams } from "next/navigation"

import { DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core"
import { arrayMove, SortableContext, useSortable, horizontalListSortingStrategy } from "@dnd-kit/sortable"
import { CSS } from "@dnd-kit/utilities"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { toast } from "sonner"
import { ChevronDown, Plus, X, Printer, GripVertical, Download } from "lucide-react"
import { useConfirm } from "@/components/providers/confirm-dialog-provider"
import { useAuth } from "@/lib/auth"
import { formatDateTimeDMY, normalizeDueDateInput, toDateInputValue } from "@/lib/dates"
import { fetchUsersLookupCached, invalidateUsersLookupCache } from "@/lib/users-cache"
import { formatDepartmentName } from "@/lib/department-name"
import { resolveProjectTitle } from "@/lib/project-display-title"
import { getPlainMarkedText, renderMarkedNoteContent } from "@/lib/note-markup"
import { buildRepeatedTaskFirstDateMap, isRepeatedTaskInstance } from "@/lib/repeated-task-visibility"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  WeeklyPlannerLegendTable,
  buildLegendSwatches,
  buildLegendDisplayEntries,
  getLegendQuestions,
  type LegendEntry,
} from "@/components/weekly-planner-legend-table"
import { WeeklyPlannerSnapshotsView } from "@/components/weekly-planner-snapshots-view"
import { TaskOneHMarker, taskOneHMarkerLabel } from "@/components/task-one-h-marker"
import { TaskMarkerComment } from "@/components/task-marker-comment"
import { WeeklyPlanPerformanceView, type WeeklyPlanPerformanceResponse } from "@/components/weekly-plan-performance-view"
import type { Department, GaNote, Project, Task, UserLookup } from "@/lib/types"

type WeeklyTableProjectTaskEntry = {
  task_id: string
  task_title: string
  phase?: string | null
  status?: string | null
  daily_status?: string | null
  created_at?: string | null
  completed_at?: string | null
  daily_products: number | null
  total_products?: number | null
  completed_products?: number | null
  weekly_planned_products?: number | null
  day_total_products?: number | null
  day_done_products?: number | null
  finish_period?: string | null
  is_bllok: boolean
  is_1h_report: boolean
  is_r1: boolean
  is_personal: boolean
  is_deadline_important?: boolean
  ga_note_origin_id: string | null
  plan_note_origin_id?: string | null
  one_h_marker?: Task["one_h_marker"]
  one_h_marker_by_ga?: boolean
  one_h_marker_comment?: string | null
}

type WeeklyTableProjectEntry = {
  project_id: string
  project_title: string
  project_total_products: number | null
  project_current_phase?: string | null
  project_type?: string | null
  task_count: number
  tasks: WeeklyTableProjectTaskEntry[]
  is_late?: boolean
}

type WeeklyTableTaskEntry = {
  task_id: string | null
  title: string
  status?: string | null
  daily_status?: string | null
  created_at?: string | null
  completed_at?: string | null
  daily_products: number | null
  finish_period?: string | null
  fast_task_type?: string | null
  is_bllok: boolean
  is_1h_report: boolean
  is_r1: boolean
  is_personal: boolean
  is_deadline_important?: boolean
  ga_note_origin_id: string | null
  plan_note_origin_id?: string | null
  one_h_marker?: Task["one_h_marker"]
  one_h_marker_by_ga?: boolean
  one_h_marker_comment?: string | null
}

type WeeklyTableUserDay = {
  user_id: string
  user_name: string
  am_projects: WeeklyTableProjectEntry[]
  pm_projects: WeeklyTableProjectEntry[]
  am_system_tasks: WeeklyTableTaskEntry[]
  pm_system_tasks: WeeklyTableTaskEntry[]
  am_fast_tasks: WeeklyTableTaskEntry[]
  pm_fast_tasks: WeeklyTableTaskEntry[]
}

type WeeklyTableDay = {
  date: string
  users: WeeklyTableUserDay[]
}

type WeeklyTableDepartment = {
  department_id: string
  department_name: string
  days: WeeklyTableDay[]
}

type WeeklyTableResponse = {
  week_start: string
  week_end: string
  departments: WeeklyTableDepartment[]
  saved_plan_id: string | null
}

const getWeeklyTableUserDayTasks = (userDay?: WeeklyTableUserDay) => {
  if (!userDay) return []

  return [
    ...(userDay.am_projects || []).flatMap((project) => project.tasks || []),
    ...(userDay.pm_projects || []).flatMap((project) => project.tasks || []),
    ...(userDay.am_system_tasks || []),
    ...(userDay.pm_system_tasks || []),
    ...(userDay.am_fast_tasks || []),
    ...(userDay.pm_fast_tasks || []),
  ]
}

const buildWeeklyPlannerRepeatedTaskFirstDateMap = (
  department: WeeklyTableDepartment,
  userId: string
) => buildRepeatedTaskFirstDateMap(
  department.days.map((day) => day.date),
  (dateIso) => {
    const day = department.days.find((entry) => entry.date === dateIso)
    const userDay = day?.users.find((entry) => entry.user_id === userId)
    return getWeeklyTableUserDayTasks(userDay)
  }
)

type WeeklySnapshotVersion = {
  id: string
  snapshot_type: "PLANNED" | "FINAL"
  created_at: string
  is_official: boolean
}

type WeeklySnapshotComparePayload = {
  planned_versions: WeeklySnapshotVersion[]
  final_versions: WeeklySnapshotVersion[]
}

type WeeklyPlannerBlock = {
  entry_id: string
  user_id: string
  start_date: string
  end_date: string
  full_day: boolean
  start_time?: string | null
  end_time?: string | null
  note?: string | null
}

type WeeklyPrintUser = {
  user_id: string
  user_name: string
}

type SelectedWeek = "last" | "this" | "next"
type PlanningInboxFilter = "all" | "unplanned" | "ga" | "project" | "fast" | "planned"
type PlannerTaskDialogMode = "plan" | "edit"

const ALL_DEPARTMENTS_VALUE = "__all__"
const DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

const normalizeDepartmentKey = (name?: string) => {
  const normalized = (name || "").trim().toLowerCase().replace(/\s+/g, "")
  if (normalized === "zhvillim") return "development"
  if (normalized === "grafikdizajn" || normalized === "dizajngrafik") return "graphicdesign"
  if (normalized === "productcontent" || normalized === "produktcontent") return "productcontent"
  if (normalized === "projectcontentmanager") return "productcontent"
  return normalized
}

const isMstOrTtProjectForWeeklyPlanner = (project?: WeeklyTableProjectEntry | null) => {
  if (!project) return false
  const title = (project.project_title || "").trim().toUpperCase()
  const projectType = (project.project_type || "").trim().toUpperCase()
  const isTt = title === "TT" || title.startsWith("TT ") || title.startsWith("TT-")
  const isMst = projectType === "MST" || title.includes("MST")
  return isTt || (isMst && !isTt)
}

const hasVisibleProjectTasks = (project?: WeeklyTableProjectEntry | null) => {
  return Boolean(project?.tasks?.length)
}

function mondayISO(today = new Date()) {
  const d = new Date(today)
  const day = (d.getDay() + 6) % 7
  d.setDate(d.getDate() - day)
  return d.toISOString().slice(0, 10)
}

const shiftIsoDateByDays = (iso: string, days: number) => {
  const shifted = fromISODate(iso)
  shifted.setDate(shifted.getDate() + days)
  return toISODate(shifted)
}

const pad2 = (n: number) => String(n).padStart(2, "0")
const toISODate = (d: Date) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
const fromISODate = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number)
  return new Date(y, m - 1, d)
}

const taskDateKey = (value?: string | null) => {
  if (!value) return null
  if (/^\d{4}-\d{2}-\d{2}/.test(value)) return value.slice(0, 10)
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return toISODate(date)
}

const isTaskPlannedForWeek = (task: Task, weekStart?: string | null, weekEnd?: string | null) => {
  if (!weekStart || !weekEnd) return false
  const due = taskDateKey(task.due_date)
  if (!due) return false
  const startCandidate = taskDateKey(task.start_date)
  const start = startCandidate && startCandidate <= due ? startCandidate : due
  return start <= weekEnd && due >= weekStart
}

const isFastPlannerTask = (task: Task) => {
  return !task.project_id && !task.system_template_origin_id
}

const nextWeekDefaultDay = (weekStart?: string | null) => weekStart || shiftIsoDateByDays(mondayISO(), 7)

const timeToMinutes = (value?: string | null) => {
  if (!value) return null
  const [h, m] = value.split(":").map(Number)
  if (!Number.isFinite(h) || !Number.isFinite(m)) return null
  return h * 60 + m
}

const buildDepartmentUsers = (dept: WeeklyTableDepartment): WeeklyPrintUser[] => {
  const userMap = new Map<string, WeeklyPrintUser>()
  dept.days.forEach((day) => {
    day.users.forEach((userDay) => {
      if (!userMap.has(userDay.user_id)) {
        userMap.set(userDay.user_id, {
          user_id: userDay.user_id,
          user_name: userDay.user_name,
        })
      }
    })
  })
  return Array.from(userMap.values())
}

type SortableUserHeaderProps = {
  user: WeeklyPrintUser
  isOrdering: boolean
}

const SortableUserHeader = ({ user, isOrdering }: SortableUserHeaderProps) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: user.user_id, disabled: !isOrdering })
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : undefined,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="flex items-center justify-center gap-2"
    >
      <div className="font-semibold">{user.user_name}</div>
      {isOrdering ? (
        <button
          type="button"
          className="text-slate-500 hover:text-slate-700"
          {...attributes}
          {...listeners}
          title="Drag to reorder"
        >
          <GripVertical className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  )
}

export default function WeeklyPlannerPage() {
  const { apiFetch, user } = useAuth()
  const confirm = useConfirm()
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const [departments, setDepartments] = React.useState<Department[]>([])
  const [projects, setProjects] = React.useState<Project[]>([])
  const [users, setUsers] = React.useState<UserLookup[]>([])
  const initialUrlWeek = searchParams.get("week")
  const initialUrlDepartmentId = searchParams.get("department_id")
  const [departmentId, setDepartmentId] = React.useState<string>(() => {
    if (user?.role === "STAFF" && user.department_id) return user.department_id
    return initialUrlDepartmentId || ALL_DEPARTMENTS_VALUE
  })
  const [viewMode, setViewMode] = React.useState<"current" | "snapshots">("current")
  const [selectedWeek, setSelectedWeek] = React.useState<SelectedWeek>(
    initialUrlWeek === "last" || initialUrlWeek === "next" ? initialUrlWeek : "this"
  )
  const [data, setData] = React.useState<WeeklyTableResponse | null>(null)
  const [pvFestBlocks, setPvFestBlocks] = React.useState<WeeklyPlannerBlock[]>([])
  const [orderedUsersByDept, setOrderedUsersByDept] = React.useState<Record<string, WeeklyPrintUser[]>>({})
  const [orderDirtyByDept, setOrderDirtyByDept] = React.useState<Record<string, boolean>>({})
  const [isOrderingUsers, setIsOrderingUsers] = React.useState(false)
  const [isSavingUserOrder, setIsSavingUserOrder] = React.useState(false)
  const [savingUserVisibilityId, setSavingUserVisibilityId] = React.useState<string | null>(null)

  const [isExporting, setIsExporting] = React.useState(false)
  const [savingSnapshotMode, setSavingSnapshotMode] = React.useState<"THIS_WEEK_FINAL" | "NEXT_WEEK_PLANNED" | null>(null)
  const [planVsActualOpen, setPlanVsActualOpen] = React.useState(false)
  const [isLoadingPlanVsActual, setIsLoadingPlanVsActual] = React.useState(false)
  const [planVsActualError, setPlanVsActualError] = React.useState<string | null>(null)
  const [planVsActual, setPlanVsActual] = React.useState<WeeklyPlanPerformanceResponse | null>(null)
  const [isExportingPlanVsActual, setIsExportingPlanVsActual] = React.useState(false)
  const [snapshotCompareOpen, setSnapshotCompareOpen] = React.useState(false)
  const [snapshotCompareLoading, setSnapshotCompareLoading] = React.useState(false)
  const [snapshotCompareListLoading, setSnapshotCompareListLoading] = React.useState(false)
  const [snapshotCompareError, setSnapshotCompareError] = React.useState<string | null>(null)
  const [snapshotCompareData, setSnapshotCompareData] = React.useState<WeeklyPlanPerformanceResponse | null>(null)
  const [isExportingSnapshotCompare, setIsExportingSnapshotCompare] = React.useState(false)
  const [snapshotCompareVersions, setSnapshotCompareVersions] = React.useState<WeeklySnapshotVersion[]>([])
  const [baselineSnapshotId, setBaselineSnapshotId] = React.useState("")
  const [compareSnapshotId, setCompareSnapshotId] = React.useState("")
  const [isLoading, setIsLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [manualTaskOpen, setManualTaskOpen] = React.useState(false)
  const [manualTaskType, setManualTaskType] = React.useState<"project" | "fast">("fast")
  const [manualTaskTitle, setManualTaskTitle] = React.useState("")
  const [manualTaskDays, setManualTaskDays] = React.useState<string[]>([])
  const [manualTaskUserIds, setManualTaskUserIds] = React.useState<string[]>([])
  const [manualTaskPeriod, setManualTaskPeriod] = React.useState<"AM" | "PM">("AM")
  const [manualTaskDeadlineImportant, setManualTaskDeadlineImportant] = React.useState(false)
  const [manualTaskDepartmentId, setManualTaskDepartmentId] = React.useState("")
  const [manualTaskFastType, setManualTaskFastType] = React.useState<string>("")
  const [manualTaskProjectId, setManualTaskProjectId] = React.useState("")
  const [isCreatingManualTask, setIsCreatingManualTask] = React.useState(false)
  const [planningTasks, setPlanningTasks] = React.useState<Task[]>([])
  const [planningNotes, setPlanningNotes] = React.useState<GaNote[]>([])
  const [planningInboxLoading, setPlanningInboxLoading] = React.useState(false)
  const [planningFilter, setPlanningFilter] = React.useState<PlanningInboxFilter>("all")
  const [planningUserId, setPlanningUserId] = React.useState(ALL_DEPARTMENTS_VALUE)
  const [planningSearch, setPlanningSearch] = React.useState("")
  const [plannerTaskDialogOpen, setPlannerTaskDialogOpen] = React.useState(false)
  const [plannerTaskDialogMode, setPlannerTaskDialogMode] = React.useState<PlannerTaskDialogMode>("plan")
  const [plannerTask, setPlannerTask] = React.useState<Task | null>(null)
  const [plannerTaskStartDate, setPlannerTaskStartDate] = React.useState("")
  const [plannerTaskDueDate, setPlannerTaskDueDate] = React.useState("")
  const [plannerTaskFinishPeriod, setPlannerTaskFinishPeriod] = React.useState<"AM" | "PM" | "__none__">("AM")
  const [plannerTaskAssigneeIds, setPlannerTaskAssigneeIds] = React.useState<string[]>([])
  const [plannerTaskSaving, setPlannerTaskSaving] = React.useState(false)
  const [plannerTaskClearingId, setPlannerTaskClearingId] = React.useState<string | null>(null)
  const [isSavingToday, setIsSavingToday] = React.useState(false)
  const canDeleteProjects = user?.role === "ADMIN"
  const canSaveSnapshots = user?.role === "ADMIN" || user?.role === "MANAGER"
  const canReorderUsers = user?.role === "ADMIN" || user?.role === "MANAGER"
  const canEditUserOrder = canReorderUsers && departmentId !== ALL_DEPARTMENTS_VALUE
  const canManageUserVisibility = canReorderUsers && departmentId !== ALL_DEPARTMENTS_VALUE
  const canSaveThisWeekFinal = selectedWeek === "this"
  const canSaveNextWeekPlanned = selectedWeek === "next"
  const canCompareLastFridayPlan = selectedWeek === "this"
  const canSaveToday = selectedWeek === "this" && departmentId !== ALL_DEPARTMENTS_VALUE
  const canSaveDepartmentToday = selectedWeek === "this"
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 8 },
    })
  )

  // Drag-to-scroll refs and state
  const scrollContainerRefs = React.useRef<Map<string, HTMLDivElement>>(new Map())
  const isDraggingRef = React.useRef(false)
  const startXRef = React.useRef(0)
  const startYRef = React.useRef(0)
  const scrollLeftRef = React.useRef(0)
  const activeContainerRef = React.useRef<HTMLDivElement | null>(null)
  const hasDraggedRef = React.useRef(false)

  const handlePointerDown = React.useCallback((e: React.PointerEvent<HTMLDivElement>, deptId: string) => {
    // Don't start drag if clicking on a button, link, or input
    const target = e.target as HTMLElement
    if (target.closest("button") || target.closest("a") || target.closest("input")) return
    if (e.pointerType === "mouse" && e.button !== 0) return

    const container = scrollContainerRefs.current.get(deptId)
    if (!container) return

    isDraggingRef.current = true
    hasDraggedRef.current = false
    activeContainerRef.current = container
    startXRef.current = e.clientX
    startYRef.current = e.clientY
    scrollLeftRef.current = container.scrollLeft

    container.setPointerCapture(e.pointerId)
  }, [])

  // Global mouse move and up handlers
  React.useEffect(() => {
    const handleGlobalPointerMove = (e: PointerEvent) => {
      if (!isDraggingRef.current || !activeContainerRef.current) return

      const deltaX = Math.abs(e.clientX - startXRef.current)
      const deltaY = Math.abs(e.clientY - startYRef.current)

      // Only start dragging if moved more than 5px horizontally
      if (!hasDraggedRef.current && deltaX < 5) return

      // If we're dragging more vertically than horizontally, don't scroll
      if (deltaY > deltaX) return

      hasDraggedRef.current = true
      e.preventDefault()

      activeContainerRef.current.style.cursor = "grabbing"
      document.body.style.userSelect = "none"

      const walk = (e.clientX - startXRef.current) * 2
      activeContainerRef.current.scrollLeft = scrollLeftRef.current - walk
    }

    const handleGlobalPointerUp = () => {
      if (activeContainerRef.current) {
        activeContainerRef.current.style.cursor = "grab"
      }
      document.body.style.userSelect = ""
      isDraggingRef.current = false
      hasDraggedRef.current = false
      activeContainerRef.current = null
    }

    document.addEventListener("pointermove", handleGlobalPointerMove, { passive: false })
    document.addEventListener("pointerup", handleGlobalPointerUp)
    document.addEventListener("pointercancel", handleGlobalPointerUp)

    return () => {
      document.removeEventListener("pointermove", handleGlobalPointerMove)
      document.removeEventListener("pointerup", handleGlobalPointerUp)
      document.removeEventListener("pointercancel", handleGlobalPointerUp)
    }
  }, [])

  // Horizontal wheel scroll handler
  const handleWheel = React.useCallback((e: React.WheelEvent<HTMLDivElement>, deptId: string) => {
    const container = scrollContainerRefs.current.get(deptId)
    if (!container) return

    // Allow horizontal scrolling with Shift+wheel or trackpad horizontal swipe
    if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
      e.preventDefault()
      // Use deltaX if available (trackpad), otherwise use deltaY with Shift key
      const scrollAmount = e.deltaX !== 0 ? e.deltaX : e.deltaY
      container.scrollLeft += scrollAmount
    }
  }, [])

  const setScrollRef = React.useCallback((deptId: string) => (el: HTMLDivElement | null) => {
    if (el) {
      scrollContainerRefs.current.set(deptId, el)
    } else {
      scrollContainerRefs.current.delete(deptId)
    }
  }, [])

  const [deletingTaskId, setDeletingTaskId] = React.useState<string | null>(null)
  const [deletingProjectId, setDeletingProjectId] = React.useState<string | null>(null)
  const [taskTitleDialogOpen, setTaskTitleDialogOpen] = React.useState(false)
  const [taskTitleDialogContent, setTaskTitleDialogContent] = React.useState<string | null>(null)

  const buildCurrentWeekParams = React.useCallback((deptId?: string) => {
    const qs = new URLSearchParams()
    const effectiveDepartmentId = deptId ?? departmentId
    if (effectiveDepartmentId && effectiveDepartmentId !== ALL_DEPARTMENTS_VALUE) {
      qs.set("department_id", effectiveDepartmentId)
    }

    if (selectedWeek === "this") {
      qs.set("is_this_week", "true")
      return qs
    }

    const currentMonday = mondayISO()
    const offsetDays = selectedWeek === "last" ? -7 : 7
    qs.set("week_start", shiftIsoDateByDays(currentMonday, offsetDays))
    return qs
  }, [departmentId, selectedWeek])

  const updatePlannerFilterUrl = React.useCallback((nextWeek: SelectedWeek, nextDepartmentId: string) => {
    const params = new URLSearchParams(searchParams.toString())
    if (nextWeek === "this") {
      params.delete("week")
    } else {
      params.set("week", nextWeek)
    }
    if (nextDepartmentId && nextDepartmentId !== ALL_DEPARTMENTS_VALUE && user?.role !== "STAFF") {
      params.set("department_id", nextDepartmentId)
    } else {
      params.delete("department_id")
    }
    const query = params.toString()
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false })
  }, [pathname, router, searchParams, user?.role])

  const handleSelectedWeekChange = React.useCallback((value: SelectedWeek) => {
    setSelectedWeek(value)
    updatePlannerFilterUrl(value, departmentId)
  }, [departmentId, updatePlannerFilterUrl])

  const handleDepartmentChange = React.useCallback((value: string) => {
    setDepartmentId(value)
    updatePlannerFilterUrl(selectedWeek, value)
  }, [selectedWeek, updatePlannerFilterUrl])

  const deleteTask = React.useCallback(async (
    taskId: string,
    taskTitle?: string,
    timeSlot?: "am" | "pm",
    dayDate?: string,
    userId?: string
  ) => {
    if (!taskId) return
    if (!dayDate || !userId) {
      toast.error("Missing planner context to remove this task.")
      return
    }

    const slotLabel = timeSlot ? timeSlot.toUpperCase() : "this slot"
    const confirmed = await confirm({
      title: "Remove task from planner",
      description: taskTitle
        ? `Remove task "${taskTitle}" from ${slotLabel} on ${dayDate} for this user?`
        : `Remove this task from ${slotLabel} on ${dayDate} for this user?`,
      confirmLabel: "Remove",
      variant: "destructive",
    })

    if (!confirmed) return

    setDeletingTaskId(taskId)
    try {
      const body: any = {
        day_date: dayDate,
        user_id: userId,
      }
      if (timeSlot) {
        body.time_slot = timeSlot.toUpperCase()
      }
      const res = await apiFetch(`/tasks/${taskId}/remove-from-day`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        toast.error("Failed to remove task")
        return
      }
      toast.success("Task removed from this slot")
      const refreshParams = buildCurrentWeekParams()
      const tableRes = await apiFetch(`/planners/weekly-table?${refreshParams.toString()}`)
      if (tableRes.ok) {
        setData(await tableRes.json())
      }
    } catch {
      toast.error("Failed to remove task")
    } finally {
      setDeletingTaskId(null)
    }
  }, [apiFetch, buildCurrentWeekParams, confirm, departmentId])

  const deleteProject = React.useCallback(async (
    projectId: string,
    projectTitle?: string,
    timeSlot?: "am" | "pm",
    dayDate?: string,
    userId?: string
  ) => {
    if (!projectId) return
    if (!dayDate || !userId) {
      toast.error("Missing planner context to remove this project.")
      return
    }

    const slotLabel = timeSlot ? timeSlot.toUpperCase() : "this slot"
    const confirmed = await confirm({
      title: "Remove project from planner",
      description: projectTitle
        ? `Remove project "${projectTitle}" from ${slotLabel} on ${dayDate} for this user?`
        : `Remove this project from ${slotLabel} on ${dayDate} for this user?`,
      confirmLabel: "Remove",
      variant: "destructive",
    })
    if (!confirmed) return

    setDeletingProjectId(projectId)
    try {
      const body: any = {
        day_date: dayDate,
        user_id: userId,
      }
      if (timeSlot) {
        body.time_slot = timeSlot.toUpperCase()
      }
      const res = await apiFetch(`/projects/${projectId}/remove-from-day`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        toast.error("Failed to remove project")
        return
      }
      toast.success("Project removed from this slot")
      const refreshParams = buildCurrentWeekParams()
      const tableRes = await apiFetch(`/planners/weekly-table?${refreshParams.toString()}`)
      if (tableRes.ok) {
        setData(await tableRes.json())
      }
    } catch {
      toast.error("Failed to remove project")
    } finally {
      setDeletingProjectId(null)
    }
  }, [apiFetch, buildCurrentWeekParams, confirm])

  const getOrderedUsersForDept = React.useCallback((dept: WeeklyTableDepartment) => {
    return orderedUsersByDept[dept.department_id] || buildDepartmentUsers(dept)
  }, [orderedUsersByDept])

  const selectedDepartmentUsers = React.useMemo(() => {
    if (departmentId === ALL_DEPARTMENTS_VALUE) return []
    return users
      .filter((entry) => entry.department_id === departmentId)
      .sort((a, b) => (a.full_name || a.username || "").localeCompare(b.full_name || b.username || ""))
  }, [departmentId, users])

  const visiblePlannerUsers = React.useMemo(
    () => selectedDepartmentUsers.filter((entry) => !entry.weekly_planner_hidden),
    [selectedDepartmentUsers]
  )

  const hiddenPlannerUsers = React.useMemo(
    () => selectedDepartmentUsers.filter((entry) => entry.weekly_planner_hidden),
    [selectedDepartmentUsers]
  )

  const handleUserOrderDragEnd = React.useCallback((deptId: string, event: DragEndEvent) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    setOrderedUsersByDept((prev) => {
      const current = prev[deptId]
      if (!current) return prev
      const oldIndex = current.findIndex((u) => u.user_id === active.id)
      const newIndex = current.findIndex((u) => u.user_id === over.id)
      if (oldIndex < 0 || newIndex < 0) return prev
      const nextOrder = arrayMove(current, oldIndex, newIndex)
      return { ...prev, [deptId]: nextOrder }
    })
    setOrderDirtyByDept((prev) => ({ ...prev, [deptId]: true }))
  }, [])

  const openTaskTitle = React.useCallback((taskTitle?: string | null) => {
    if (!taskTitle?.trim()) return
    setTaskTitleDialogContent(taskTitle)
    setTaskTitleDialogOpen(true)
  }, [])

  React.useEffect(() => {
    const boot = async () => {
      const [depRes, projRes, usersList] = await Promise.all([
        apiFetch("/departments"),
        apiFetch("/projects"),
        fetchUsersLookupCached(apiFetch),
      ])
      if (depRes.ok) {
        const deps = (await depRes.json()) as Department[]
        setDepartments(deps)
        if (user?.role === "STAFF" && user?.department_id) {
          setDepartmentId(user.department_id)
        }
      }
      if (projRes.ok) {
        const projs = (await projRes.json()) as Project[]
        setProjects(projs)
      }
      if (usersList) {
        setUsers((usersList as UserLookup[]).filter((u) => u.is_active))
      }
    }
    void boot()
  }, [apiFetch, user])

  const loadPlanningInbox = React.useCallback(async () => {
    setPlanningInboxLoading(true)
    try {
      const taskParams = new URLSearchParams()
      taskParams.set("include_done", "false")
      taskParams.set("include_all_departments", "true")
      if (departmentId && departmentId !== ALL_DEPARTMENTS_VALUE) {
        taskParams.set("department_id", departmentId)
      }

      const notesParams = new URLSearchParams()
      if (departmentId && departmentId !== ALL_DEPARTMENTS_VALUE) {
        notesParams.set("department_id", departmentId)
      }

      const [tasksRes, notesRes] = await Promise.all([
        apiFetch(`/tasks?${taskParams.toString()}`),
        apiFetch(`/ga-notes${notesParams.toString() ? `?${notesParams.toString()}` : ""}`),
      ])

      if (tasksRes.ok) {
        setPlanningTasks((await tasksRes.json()) as Task[])
      } else {
        setPlanningTasks([])
      }

      if (notesRes.ok) {
        setPlanningNotes((await notesRes.json()) as GaNote[])
      } else {
        setPlanningNotes([])
      }
    } catch (error) {
      console.error("Failed to load planning inbox", error)
      setPlanningTasks([])
      setPlanningNotes([])
    } finally {
      setPlanningInboxLoading(false)
    }
  }, [apiFetch, departmentId])

  const loadPlanner = React.useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const qs = buildCurrentWeekParams()
      const res = await apiFetch(`/planners/weekly-table?${qs.toString()}`)
      if (!res.ok) {
        const errorText = await res.text()
        console.error("Failed to load weekly planner:", res.status, res.statusText, errorText)
        setError(`Failed to load planner: ${res.status} ${res.statusText}`)
        setData(null)
        setPvFestBlocks([])
        return
      }
      const payload = (await res.json()) as WeeklyTableResponse
      setData(payload)
      void loadPlanningInbox()
      void (async () => {
        try {
          const blockParams = new URLSearchParams()
          blockParams.set("type", "PV_FEST")
          blockParams.set("start", payload.week_start)
          blockParams.set("end", payload.week_end)
          if (departmentId && departmentId !== ALL_DEPARTMENTS_VALUE) {
            blockParams.set("department_id", departmentId)
          }
          const blocksRes = await apiFetch(`/common-entries/blocks?${blockParams.toString()}`)
          if (blocksRes.ok) {
            const blocks = (await blocksRes.json()) as WeeklyPlannerBlock[]
            setPvFestBlocks(blocks)
          } else {
            setPvFestBlocks([])
          }
        } catch (err) {
          console.error("Failed to load PV/FEST blocks:", err)
          setPvFestBlocks([])
        }
      })()
    } catch (error) {
      console.error("Error loading weekly planner:", error)
      setError(error instanceof Error ? error.message : "Unknown error occurred")
      setData(null)
      setPvFestBlocks([])
    } finally {
      setIsLoading(false)
    }
  }, [apiFetch, buildCurrentWeekParams, departmentId, loadPlanningInbox])

  const toggleWeeklyPlannerUserVisibility = React.useCallback(
    async (targetUser: UserLookup, hidden: boolean) => {
      if (!canManageUserVisibility || departmentId === ALL_DEPARTMENTS_VALUE) return
      setSavingUserVisibilityId(targetUser.id)
      try {
        const res = await apiFetch("/planners/weekly-table/user-visibility", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            department_id: departmentId,
            user_id: targetUser.id,
            hidden,
          }),
        })
        if (!res.ok) {
          const message = await res.text().catch(() => "Failed to update user visibility")
          toast.error(message || "Failed to update user visibility")
          return
        }
        setUsers((prev) =>
          prev.map((entry) =>
            entry.id === targetUser.id ? { ...entry, weekly_planner_hidden: hidden } : entry
          )
        )
        invalidateUsersLookupCache()
        toast.success(hidden ? "User hidden from weekly plan." : "User shown in weekly plan.")
        void loadPlanner()
      } catch (err) {
        console.error("Failed to update weekly planner user visibility", err)
        toast.error("Failed to update user visibility")
      } finally {
        setSavingUserVisibilityId(null)
      }
    },
    [apiFetch, canManageUserVisibility, departmentId, loadPlanner]
  )

  const saveUserOrder = React.useCallback(async () => {
    if (!canEditUserOrder) return
    const deptId = departmentId
    const orderedUsers = orderedUsersByDept[deptId]
    if (!orderedUsers || orderedUsers.length === 0) {
      toast.error("No users available to save.")
      return
    }
    setIsSavingUserOrder(true)
    try {
      const res = await apiFetch("/planners/weekly-table/user-order", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          department_id: deptId,
          ordered_user_ids: orderedUsers.map((u) => u.user_id),
        }),
      })
      if (!res.ok) {
        const message = await res.text().catch(() => "Failed to save user order")
        toast.error(message || "Failed to save user order")
        return
      }
      toast.success("User order saved.")
      setOrderDirtyByDept((prev) => ({ ...prev, [deptId]: false }))
      setIsOrderingUsers(false)
      void loadPlanner()
    } catch (err) {
      console.error("Failed to save user order", err)
      toast.error("Failed to save user order")
    } finally {
      setIsSavingUserOrder(false)
    }
  }, [apiFetch, canEditUserOrder, departmentId, orderedUsersByDept, loadPlanner])

  React.useEffect(() => {
    if (viewMode !== "current") return
    void loadPlanner()
  }, [loadPlanner, viewMode])

  React.useEffect(() => {
    if (!data) {
      setOrderedUsersByDept({})
      setOrderDirtyByDept({})
      return
    }
    const nextOrder: Record<string, WeeklyPrintUser[]> = {}
    data.departments.forEach((dept) => {
      nextOrder[dept.department_id] = buildDepartmentUsers(dept)
    })
    setOrderedUsersByDept(nextOrder)
    setOrderDirtyByDept({})
    setIsOrderingUsers(false)
  }, [data])

  React.useEffect(() => {
    if (!manualTaskOpen) {
      // Reset all form state when dialog closes
      setManualTaskTitle("")
      setManualTaskDays([])
      setManualTaskUserIds([])
      setManualTaskPeriod("AM")
      setManualTaskDepartmentId("")
      setManualTaskFastType("")
      setManualTaskProjectId("")
      setManualTaskType("fast")
      return
    }
    if (departmentId !== ALL_DEPARTMENTS_VALUE) {
      setManualTaskDepartmentId(departmentId)
    }
  }, [manualTaskOpen, departmentId])

  React.useEffect(() => {
    if (!manualTaskDepartmentId) return
    setManualTaskUserIds([])
    setManualTaskProjectId("")
  }, [manualTaskDepartmentId])

  const availableDays = React.useMemo(() => {
    if (!data?.departments?.length) return []
    const firstDept = data.departments[0]
    return firstDept.days.map((day, index) => ({
      value: day.date,
      label: DAY_NAMES[index] || formatDate(day.date),
    }))
  }, [data])

  const availableUsers = React.useMemo(() => {
    const filtered = manualTaskDepartmentId
      ? users.filter((u) => u.department_id === manualTaskDepartmentId && !u.weekly_planner_hidden)
      : users.filter((u) => !u.weekly_planner_hidden)
    return filtered
      .map((u) => ({
        id: u.id,
        name: u.full_name || u.username || "",
      }))
      .filter((u) => u.name.trim().length > 0)
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [manualTaskDepartmentId, users])

  const plannerTaskUsers = React.useMemo(() => {
    const departmentFilter = plannerTask?.department_id ?? null
    const filtered = departmentFilter
      ? users.filter((u) => u.department_id === departmentFilter || plannerTaskAssigneeIds.includes(u.id))
      : users
    return filtered
      .map((u) => ({
        id: u.id,
        name: u.full_name || u.username || "",
      }))
      .filter((u) => u.name.trim().length > 0)
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [plannerTask?.department_id, plannerTaskAssigneeIds, users])

  const availableDepartments = React.useMemo(() => {
    return departments.slice().sort((a, b) => a.name.localeCompare(b.name))
  }, [departments])

  const pvFestByUserDate = React.useMemo(() => {
    const map = new Map<string, Map<string, WeeklyPlannerBlock[]>>()
    for (const block of pvFestBlocks) {
      if (!block.user_id || !block.start_date || !block.end_date) continue
      const current = fromISODate(block.start_date)
      const end = fromISODate(block.end_date)
      while (current <= end) {
        const iso = toISODate(current)
        const byDate = map.get(block.user_id) ?? new Map<string, WeeklyPlannerBlock[]>()
        const list = byDate.get(iso) ?? []
        list.push(block)
        byDate.set(iso, list)
        map.set(block.user_id, byDate)
        current.setDate(current.getDate() + 1)
      }
    }
    return map
  }, [pvFestBlocks])

  const getBlockForSlot = React.useCallback(
    (userId: string, dayIso: string, slot: "am" | "pm") => {
      const blocks = pvFestByUserDate.get(userId)?.get(dayIso) || []
      if (!blocks.length) return null
      const slotStart = slot === "am" ? 0 : 12 * 60
      const slotEnd = slot === "am" ? 12 * 60 : 24 * 60
      return (
        blocks.find((block) => {
          if (block.full_day) return true
          const start = timeToMinutes(block.start_time) ?? 0
          const end = timeToMinutes(block.end_time) ?? 24 * 60
          if (end <= start) return true
          return start < slotEnd && end > slotStart
        }) || null
      )
    },
    [pvFestByUserDate]
  )

  const isProjectClosed = React.useCallback((project: Project) => {
    const statusValue = (project.status || "").toUpperCase()
    const phaseValue = (project.current_phase || "").toUpperCase()
    if (project.completed_at) return true
    if (statusValue === "CLOSED" || statusValue === "MBYLLUR" || statusValue === "LOST" || statusValue === "CANCELLED") return true
    if (phaseValue === "CLOSED" || phaseValue === "MBYLLUR") return true
    return false
  }, [])

  const projectLabel = React.useCallback((project: Project) => {
    return resolveProjectTitle(project) || "Untitled project"
  }, [])

  const availableProjects = React.useMemo(() => {
    if (!manualTaskDepartmentId) return []
    return projects
      .filter((project) => project.department_id === manualTaskDepartmentId)
      .filter((project) => !project.is_template)
      .filter((project) => !isProjectClosed(project))
      .slice()
      .sort((a, b) => projectLabel(a).localeCompare(projectLabel(b)))
  }, [manualTaskDepartmentId, projects, isProjectClosed, projectLabel])

  const planningUserOptions = React.useMemo(() => {
    const scopedUsers =
      departmentId !== ALL_DEPARTMENTS_VALUE
        ? users.filter((u) => u.department_id === departmentId && !u.weekly_planner_hidden)
        : users.filter((u) => !u.weekly_planner_hidden)
    return scopedUsers
      .map((u) => ({ id: u.id, name: u.full_name || u.username || u.id }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [departmentId, users])

  const planningNoteById = React.useMemo(() => {
    const map = new Map<string, GaNote>()
    for (const note of planningNotes) map.set(note.id, note)
    return map
  }, [planningNotes])

  const planningUserById = React.useMemo(() => {
    const map = new Map<string, UserLookup>()
    for (const item of users) map.set(item.id, item)
    return map
  }, [users])

  const planningDepartmentById = React.useMemo(() => {
    const map = new Map<string, Department>()
    for (const item of departments) map.set(item.id, item)
    return map
  }, [departments])

  const planningProjectById = React.useMemo(() => {
    const map = new Map<string, Project>()
    for (const item of projects) map.set(item.id, item)
    return map
  }, [projects])

  const taskAssigneeIds = React.useCallback((task: Task) => {
    const ids = new Set<string>()
    if (task.assigned_to) ids.add(task.assigned_to)
    for (const assignee of task.assignees || []) {
      if (assignee.id) ids.add(assignee.id)
    }
    return Array.from(ids)
  }, [])

  const taskAssigneeLabel = React.useCallback(
    (task: Task) => {
      const ids = taskAssigneeIds(task)
      if (!ids.length) return "Unassigned"
      return ids
        .map((id) => {
          const found = planningUserById.get(id)
          return found?.full_name || found?.username || id
        })
        .join(", ")
    },
    [planningUserById, taskAssigneeIds]
  )

  const taskSourceLabel = React.useCallback(
    (task: Task) => {
      if (task.ga_note_origin_id || task.plan_note_origin_id) return "GA/KA"
      if (task.system_template_origin_id) return "System"
      if (task.project_id) return "Project"
      if (task.is_bllok) return "BLL"
      if (task.is_r1) return "R1"
      if (task.is_1h_report) return "1H"
      if (task.is_personal) return "P:"
      return "Fast"
    },
    []
  )

  const plannerWeekStart = data?.week_start || nextWeekDefaultDay(null)
  const plannerWeekEnd = data?.week_end || shiftIsoDateByDays(plannerWeekStart, 4)

  const filteredPlanningTasks = React.useMemo(() => {
    const query = planningSearch.trim().toLowerCase()
    return planningTasks.filter((task) => {
      const planned = isTaskPlannedForWeek(task, plannerWeekStart, plannerWeekEnd)
      const isGa = Boolean(task.ga_note_origin_id || task.plan_note_origin_id)
      const isFast = isFastPlannerTask(task)
      const ids = taskAssigneeIds(task)

      if (planningUserId !== ALL_DEPARTMENTS_VALUE && !ids.includes(planningUserId)) return false
      if (planningFilter === "unplanned" && planned) return false
      if (planningFilter === "ga" && !isGa) return false
      if (planningFilter === "project" && !task.project_id) return false
      if (planningFilter === "fast" && !isFast) return false
      if (planningFilter === "planned" && !planned) return false
      if (query) {
        const note = task.ga_note_origin_id ? planningNoteById.get(task.ga_note_origin_id) : null
        const project = task.project_id ? planningProjectById.get(task.project_id) : null
        const haystack = [
          task.title,
          task.description,
          task.status,
          taskSourceLabel(task),
          taskAssigneeLabel(task),
          note?.content,
          project ? projectLabel(project) : "",
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
        if (!haystack.includes(query)) return false
      }
      return true
    })
  }, [
    plannerWeekEnd,
    plannerWeekStart,
    planningFilter,
    planningNoteById,
    planningProjectById,
    planningSearch,
    planningTasks,
    planningUserId,
    projectLabel,
    taskAssigneeIds,
    taskAssigneeLabel,
    taskSourceLabel,
  ])

  const gaPlanningTasks = React.useMemo(
    () => filteredPlanningTasks.filter((task) => task.ga_note_origin_id || task.plan_note_origin_id),
    [filteredPlanningTasks]
  )
  const plannedNextWeekTasks = React.useMemo(
    () => filteredPlanningTasks.filter((task) => !(task.ga_note_origin_id || task.plan_note_origin_id) && isTaskPlannedForWeek(task, plannerWeekStart, plannerWeekEnd)),
    [filteredPlanningTasks, plannerWeekEnd, plannerWeekStart]
  )
  const openBacklogTasks = React.useMemo(
    () => filteredPlanningTasks.filter((task) => !(task.ga_note_origin_id || task.plan_note_origin_id) && !isTaskPlannedForWeek(task, plannerWeekStart, plannerWeekEnd)),
    [filteredPlanningTasks, plannerWeekEnd, plannerWeekStart]
  )

  const manualTaskDepartmentValue =
    departmentId !== ALL_DEPARTMENTS_VALUE ? departmentId : manualTaskDepartmentId

  const openPlannerTaskDialog = React.useCallback(
    (task: Task, mode: PlannerTaskDialogMode) => {
      const defaultDay = nextWeekDefaultDay(data?.week_start)
      setPlannerTask(task)
      setPlannerTaskDialogMode(mode)
      setPlannerTaskStartDate(toDateInputValue(task.start_date) || defaultDay)
      setPlannerTaskDueDate(toDateInputValue(task.due_date) || defaultDay)
      setPlannerTaskFinishPeriod((task.finish_period as "AM" | "PM" | null) || "AM")
      setPlannerTaskAssigneeIds(taskAssigneeIds(task))
      setPlannerTaskDialogOpen(true)
    },
    [data?.week_start, taskAssigneeIds]
  )

  const savePlannerTask = React.useCallback(async () => {
    if (!plannerTask) return
    if (!plannerTaskDueDate) {
      toast.error("Due date is required to place a task in the weekly planner.")
      return
    }
    if (plannerTaskStartDate && plannerTaskStartDate > plannerTaskDueDate) {
      toast.error("Start date cannot be after due date.")
      return
    }

    setPlannerTaskSaving(true)
    try {
      const res = await apiFetch(`/tasks/${plannerTask.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          start_date: plannerTaskStartDate ? new Date(plannerTaskStartDate).toISOString() : null,
          due_date: new Date(plannerTaskDueDate).toISOString(),
          finish_period: plannerTaskFinishPeriod === "__none__" ? null : plannerTaskFinishPeriod,
          ...(plannerTask.ga_note_origin_id || plannerTask.plan_note_origin_id
            ? {}
            : {
                assigned_to: plannerTaskAssigneeIds[0] ?? null,
                assignees: plannerTaskAssigneeIds,
              }),
        }),
      })

      if (!res.ok) {
        let detail = "Failed to update task planning."
        try {
          const payload = (await res.json()) as { detail?: string }
          if (payload?.detail) detail = payload.detail
        } catch {
          // Keep fallback.
        }
        toast.error(detail)
        return
      }

      const updated = (await res.json()) as Task
      setPlanningTasks((prev) => prev.map((task) => (task.id === updated.id ? updated : task)))
      setPlannerTaskDialogOpen(false)
      setPlannerTask(null)
      toast.success(plannerTaskDialogMode === "plan" ? "Task planned for the week." : "Task planning updated.")
      await Promise.all([loadPlanner(), loadPlanningInbox()])
    } catch (error) {
      console.error("Failed to save planner task", error)
      toast.error("Failed to update task planning.")
    } finally {
      setPlannerTaskSaving(false)
    }
  }, [
    apiFetch,
    loadPlanner,
    loadPlanningInbox,
    plannerTask,
    plannerTaskAssigneeIds,
    plannerTaskDialogMode,
    plannerTaskDueDate,
    plannerTaskFinishPeriod,
    plannerTaskStartDate,
  ])

  const clearTaskFromNextWeek = React.useCallback(
    async (task: Task) => {
      const isPlanned = isTaskPlannedForWeek(task, plannerWeekStart, plannerWeekEnd)
      if (!isPlanned) return

      const confirmed = await confirm({
        title: "Remove from next week plan",
        description: task.project_id
          ? "This clears the task start/due dates, which may also affect its project deadline display. Continue?"
          : "This clears the task start/due dates so it leaves the weekly planner.",
        confirmLabel: "Remove from plan",
        variant: "destructive",
      })
      if (!confirmed) return

      setPlannerTaskClearingId(task.id)
      try {
        const res = await apiFetch(`/tasks/${task.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            start_date: null,
            due_date: null,
            finish_period: null,
          }),
        })
        if (!res.ok) {
          toast.error("Failed to remove task from planner.")
          return
        }
        const updated = (await res.json()) as Task
        setPlanningTasks((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
        toast.success("Task removed from next week plan.")
        await Promise.all([loadPlanner(), loadPlanningInbox()])
      } catch (error) {
        console.error("Failed to remove task from next week", error)
        toast.error("Failed to remove task from planner.")
      } finally {
        setPlannerTaskClearingId(null)
      }
    },
    [apiFetch, confirm, loadPlanner, loadPlanningInbox, plannerWeekEnd, plannerWeekStart]
  )

  const handleCreateManualTask = async () => {
    if (!manualTaskTitle.trim()) {
      toast.error("Task title is required.")
      return
    }
    if (!manualTaskDepartmentValue) {
      toast.error("Select a department.")
      return
    }
    if (manualTaskType === "fast") {
      // Fast Task validation
      if (manualTaskDays.length === 0) {
        toast.error("Select at least one day.")
        return
      }
      if (manualTaskUserIds.length === 0) {
        toast.error("Select at least one member.")
        return
      }
      if (!manualTaskFastType) {
        toast.error("Select a task type.")
        return
      }
    } else {
      // Project validation
      if (manualTaskDays.length === 0) {
        toast.error("Select at least one day.")
        return
      }
      if (!manualTaskProjectId) {
        toast.error("Select a project.")
        return
      }
      if (manualTaskUserIds.length === 0) {
        toast.error("Select at least one member.")
        return
      }
    }

    const departmentValue = manualTaskDepartmentValue
    if (!departmentValue) {
      toast.error("Department is required for this task.")
      return
    }

    setIsCreatingManualTask(true)
    try {
      if (manualTaskType === "fast") {
        // Create fast tasks for multiple days and members
        const tasksToCreate: Promise<Response>[] = []

        for (const day of manualTaskDays) {
          for (const userId of manualTaskUserIds) {
            const dueDateIso = new Date(day).toISOString()
            const taskPayload: any = {
              title: manualTaskTitle.trim(),
              project_id: null,
              department_id: departmentValue,
              assigned_to: userId,
              status: "TODO",
              priority: "NORMAL",
              finish_period: manualTaskPeriod,
              due_date: dueDateIso,
              is_deadline_important: manualTaskDeadlineImportant,
            }

            // Set fast task type flags
            if (manualTaskFastType === "BLL") {
              taskPayload.is_bllok = true
            } else if (manualTaskFastType === "R1") {
              taskPayload.is_r1 = true
            } else if (manualTaskFastType === "1H") {
              taskPayload.is_1h_report = true
            } else if (manualTaskFastType === "P:") {
              taskPayload.is_personal = true
            }

            tasksToCreate.push(
              apiFetch("/tasks", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(taskPayload),
              })
            )
          }
        }

        const results = await Promise.all(tasksToCreate)
        const failed = results.filter(r => !r.ok)
        if (failed.length > 0) {
          toast.error(`Failed to create ${failed.length} task(s).`)
          return
        }
        toast.success(`Created ${tasksToCreate.length} fast task(s).`)
      } else {
        // Create project tasks for multiple days and members
        const tasksToCreate: Promise<Response>[] = []

        for (const day of manualTaskDays) {
          for (const userId of manualTaskUserIds) {
            const dueDateIso = new Date(day).toISOString()
            tasksToCreate.push(
              apiFetch("/tasks", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  title: manualTaskTitle.trim(),
                  project_id: manualTaskProjectId,
                  department_id: departmentValue,
                  assigned_to: userId,
                  status: "TODO",
                  priority: "NORMAL",
                  finish_period: manualTaskPeriod,
                  due_date: dueDateIso,
                  is_deadline_important: manualTaskDeadlineImportant,
                }),
              })
            )
          }
        }

        const results = await Promise.all(tasksToCreate)
        const failed = results.filter(r => !r.ok)
        if (failed.length > 0) {
          toast.error(`Failed to create ${failed.length} task(s).`)
          return
        }
        toast.success(`Created ${tasksToCreate.length} project task(s).`)
      }

      setManualTaskOpen(false)
      setManualTaskTitle("")
      setManualTaskDays([])
      setManualTaskUserIds([])
      setManualTaskDeadlineImportant(false)
      setManualTaskPeriod("AM")
      setManualTaskDepartmentId("")
      setManualTaskFastType("")
      setManualTaskProjectId("")
      setManualTaskType("fast")
      await loadPlanner()
    } catch (error) {
      console.error("Error creating task:", error)
      toast.error("Failed to create task")
    } finally {
      setIsCreatingManualTask(false)
    }
  }

  // Edit/delete handlers removed - now showing projects instead of individual tasks



  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" })
  }

  const fastTaskBadgeStyles: Record<string, string> = {
    BLL: "border-red-200 bg-red-50 text-red-700",
    R1: "border-indigo-200 bg-indigo-50 text-indigo-700",
    "1H": "border-amber-200 bg-amber-50 text-amber-700",
    "P:": "border-emerald-200 bg-emerald-50 text-emerald-700",
    N: "border-slate-200 bg-slate-50 text-slate-700",
  }

  const getStatusCardClasses = React.useCallback((status?: string | null) => {
    const normalized = (status || "TODO").toUpperCase()
    if (normalized === "IN_PROGRESS") {
      return "border-[#000000] bg-[#FFFF00] text-[#000000]"
    }
    if (normalized === "WAITING_CONFIRMATION") {
      return "border-[#C2410C] bg-[#FFEDD5] text-[#9A3412]"
    }
    if (normalized === "WAITING_CLIENT") {
      return "border-[#B8860B] bg-[#E2C15B] text-[#4F3A00]"
    }
    if (normalized === "DONE") {
      return "border-[#000000] bg-[#C4FDC4] text-[#000000]"
    }
    if (normalized === "TODO") {
      return "border-[#000000] bg-[#FFC4ED] text-[#000000]"
    }
    return "border-[#000000] bg-[#f1f5f9] text-[#000000]"
  }, [])

  const getStatusCardClassesForDay = React.useCallback(
    (
      status?: string | null,
      completedAt?: string | null,
      dayDate?: string | null,
      dailyStatus?: string | null
    ) => {
      const normalized = (status || "TODO").toUpperCase()
      const normalizedDaily = dailyStatus ? dailyStatus.toUpperCase() : null

      if (normalizedDaily === "DONE") {
        return getStatusCardClasses("DONE")
      }
      if (normalizedDaily === "IN_PROGRESS") {
        return getStatusCardClasses("IN_PROGRESS")
      }
      if (normalizedDaily === "WAITING_CONFIRMATION") {
        return getStatusCardClasses("WAITING_CONFIRMATION")
      }
      if (normalizedDaily === "WAITING_CLIENT") {
        return getStatusCardClasses("WAITING_CLIENT")
      }
      if (normalizedDaily) {
        return getStatusCardClasses("TODO")
      }

      if (completedAt && dayDate) {
        const completedDate = completedAt.slice(0, 10)
        const currentDate = dayDate.slice(0, 10)
        if (currentDate === completedDate) {
          return getStatusCardClasses("DONE")
        }
        if (normalized === "DONE") {
          return getStatusCardClasses(currentDate < completedDate ? "IN_PROGRESS" : "TODO")
        }
      }

      if (normalized === "DONE") {
        return getStatusCardClasses("DONE")
      }

      if (normalized === "WAITING_CONFIRMATION") {
        return getStatusCardClasses("TODO")
      }
      if (normalized === "WAITING_CLIENT") {
        return getStatusCardClasses("WAITING_CLIENT")
      }
      return getStatusCardClasses(normalized === "TODO" ? "TODO" : "IN_PROGRESS")
    },
    [getStatusCardClasses]
  )

  const isTaskNewForWeek = React.useCallback((createdAt?: string | null, weekStart?: string | null) => {
    if (!createdAt || !weekStart) return false
    const createdAtMs = Date.parse(createdAt)
    const weekStartMs = Date.parse(`${weekStart}T00:00:00`)
    if (!Number.isFinite(createdAtMs) || !Number.isFinite(weekStartMs)) return false
    return createdAtMs >= weekStartMs
  }, [])

  const getStatusValueForDay = React.useCallback(
    (
      status?: string | null,
      completedAt?: string | null,
      dayDate?: string | null,
      dailyStatus?: string | null
    ) => {
      const normalized = (status || "TODO").toUpperCase()
      const normalizedDaily = dailyStatus ? dailyStatus.toUpperCase() : null

      if (normalizedDaily === "DONE") {
        return "DONE"
      }
      if (normalizedDaily === "IN_PROGRESS") {
        return "IN_PROGRESS"
      }
      if (normalizedDaily === "WAITING_CONFIRMATION") {
        return "WAITING_CONFIRMATION"
      }
      if (normalizedDaily === "WAITING_CLIENT") {
        return "WAITING_CLIENT"
      }
      if (normalizedDaily) {
        return "TODO"
      }

      if (completedAt && dayDate) {
        const completedDate = completedAt.slice(0, 10)
        const currentDate = dayDate.slice(0, 10)
        if (currentDate === completedDate) {
          return "DONE"
        }
        if (normalized === "DONE") {
          return currentDate < completedDate ? "IN_PROGRESS" : "TODO"
        }
      }

      if (normalized === "DONE") {
        return "DONE"
      }

      if (normalized === "WAITING_CONFIRMATION") {
        return "TODO"
      }
      if (normalized === "WAITING_CLIENT") {
        return "WAITING_CLIENT"
      }
      return normalized === "TODO" ? "TODO" : "IN_PROGRESS"
    },
    []
  )

  const getTaskCardClassesForDay = React.useCallback(
    (
      status?: string | null,
      completedAt?: string | null,
      dayDate?: string | null,
      dailyStatus?: string | null,
      createdAt?: string | null,
      isDeadlineImportant?: boolean
    ) => {
      const statusValue = getStatusValueForDay(status, completedAt, dayDate, dailyStatus)
      if (isDeadlineImportant) {
        if (statusValue === "DONE") {
          return getStatusCardClasses("DONE")
        }
        return "border-red-800 bg-red-600 text-white"
      }
      const isNew = isTaskNewForWeek(createdAt, data?.week_start)
      if (isNew) {
        if (statusValue === "DONE") {
          return "border-[#059669] bg-[#02e6c7] text-[#064e3b]"
        }
        if (statusValue === "WAITING_CONFIRMATION") {
          return getStatusCardClasses("WAITING_CONFIRMATION")
        }
        if (statusValue === "WAITING_CLIENT") {
          return getStatusCardClasses("WAITING_CLIENT")
        }
        if (statusValue === "IN_PROGRESS") {
          return getStatusCardClasses("IN_PROGRESS")
        }
        return "border-[#1d4ed8] bg-[#dbeafe] text-[#0f172a]"
      }
      return getStatusCardClassesForDay(status, completedAt, dayDate, dailyStatus)
    },
    [data?.week_start, getStatusCardClasses, getStatusCardClassesForDay, getStatusValueForDay, isTaskNewForWeek]
  )

  const getTaskStatusBadge = React.useCallback((task: {
    is_bllok?: boolean
    is_1h_report?: boolean
    is_r1?: boolean
    is_personal?: boolean
    ga_note_origin_id?: string | null
    plan_note_origin_id?: string | null
    fast_task_type?: string | null
    is_deadline_important?: boolean
    status?: string | null
    completed_at?: string | null
    daily_status?: string | null
    day_date?: string | null
  }): { label: string; className: string } => {
    const statusValue = getStatusValueForDay(task.status, task.completed_at, task.day_date, task.daily_status)
    if (task.is_deadline_important && task.day_date && statusValue === "DONE") {
      return { label: "DL", className: "border-red-200 bg-red-50 text-red-700" }
    }
    if (task.is_bllok) {
      return { label: "BLL", className: "border-red-200 bg-red-50 text-red-700" }
    }
    if (task.is_r1) {
      return { label: "R1", className: "border-indigo-200 bg-indigo-50 text-indigo-700" }
    }
    if (task.is_1h_report) {
      return { label: "1H", className: "border-amber-200 bg-amber-50 text-amber-700" }
    }
    if (task.is_personal) {
      return { label: "P:", className: "border-emerald-200 bg-emerald-50 text-emerald-700" }
    }
    if (task.plan_note_origin_id) {
      return { label: "PX JAV", className: "border-indigo-200 bg-indigo-50 text-indigo-700" }
    }
    if (task.ga_note_origin_id) {
      return { label: "GA", className: "border-blue-200 bg-blue-50 text-blue-700" }
    }
    return { label: "N", className: "border-slate-200 bg-slate-50 text-slate-700" }
  }, [getStatusValueForDay])

  const formatTaskProducts = React.useCallback((
    task: WeeklyTableProjectTaskEntry,
    project?: WeeklyTableProjectEntry | null,
    departmentName?: string
  ) => {
    const isProductContentDepartment = normalizeDepartmentKey(departmentName) === "productcontent"
    const isScopedMstOrTt = isProductContentDepartment && isMstOrTtProjectForWeeklyPlanner(project)

    if (isScopedMstOrTt) {
      const weeklyPlanned = task.weekly_planned_products ?? null
      const dayTotal = task.day_total_products ?? null
      const dayDone = task.day_done_products ?? null
      if (weeklyPlanned == null && dayTotal == null && dayDone == null) return null
      const toLabel = (value: number | null) => (value == null ? "-" : String(value))
      const base = `${toLabel(weeklyPlanned)}/${toLabel(dayTotal)}/${toLabel(dayDone)} pcs`
      // A day nobody has touched yet is already pink; only annotate real over/under delivery.
      if (dayTotal == null || dayDone == null || dayTotal <= 0 || dayDone <= 0) return base
      const delta = dayDone - dayTotal
      if (delta === 0) return base
      return `${base} (${delta > 0 ? "+" : ""}${delta})`
    }

    const total = task.total_products ?? task.daily_products ?? null
    if (total == null) return null
    const completed = task.completed_products
    if (completed != null) return `${total}/${completed} pcs`
    return `${total} pcs`
  }, [])

  const getProjectDisplayTitle = React.useCallback((project: WeeklyTableProjectEntry) => {
    return project.project_title || "Untitled project"
  }, [])

  const getPlannerTaskFullTitle = React.useCallback(
    (task: { title?: string | null; task_title?: string | null }) => {
      const rawTitle = task.task_title ?? task.title ?? ""
      return rawTitle
        .replace(/<br\s*\/?>/gi, "\n")
        .replace(/<\/(div|p)>/gi, "\n")
        .replace(/<(div|p)[^>]*>/gi, "")
        .trim()
    },
    []
  )

  const getPlannerTaskDisplayTitle = React.useCallback(
    (task: { title?: string | null; task_title?: string | null }) => {
      const fullTitle = getPlannerTaskFullTitle(task)
      const plainTitle = getPlainMarkedText(fullTitle)
      const firstLine = plainTitle
        .split(/\r?\n/)
        .map((line) => line.trim())
        .find(Boolean)
      return firstLine || plainTitle.trim() || "Untitled task"
    },
    [getPlannerTaskFullTitle]
  )

  const getFastTaskBadge = React.useCallback((task: {
    is_bllok?: boolean
    is_1h_report?: boolean
    is_r1?: boolean
    is_personal?: boolean
    ga_note_origin_id?: string | null
    plan_note_origin_id?: string | null
    fast_task_type?: string | null
    is_deadline_important?: boolean
    status?: string | null
    completed_at?: string | null
    daily_status?: string | null
    day_date?: string | null
  }): { label: string; className: string } => {
    const badge = getTaskStatusBadge(task)
    if (badge) return badge
    if (task.fast_task_type) {
      if (task.fast_task_type === "GA") {
        return { label: "N", className: "border-slate-200 bg-slate-50 text-slate-700" }
      }
      return {
        label: task.fast_task_type,
        className: fastTaskBadgeStyles[task.fast_task_type] || "border-slate-200 bg-slate-50 text-slate-700",
      }
    }
    return { label: "N", className: "border-slate-200 bg-slate-50 text-slate-700" }
  }, [getTaskStatusBadge, fastTaskBadgeStyles])

  const fastTaskSortOrder = ["BLL", "1H", "P:", "R1", "N"] as const
  const fastTaskSortRank = new Map<string, number>(
    fastTaskSortOrder.map((label, index) => [label, index])
  )

  const getFastTaskSortLabel = React.useCallback((task: {
    is_bllok?: boolean
    is_1h_report?: boolean
    is_r1?: boolean
    is_personal?: boolean
    ga_note_origin_id?: string | null
    plan_note_origin_id?: string | null
    fast_task_type?: string | null
  }) => {
    const badge = getFastTaskBadge(task)
    return badge?.label || "N"
  }, [getFastTaskBadge])

  const sortFastTasks = React.useCallback((tasks: WeeklyTableTaskEntry[]) => (
    tasks
      .map((task, index) => ({ task, index }))
      .sort((a, b) => {
        const aLabel = getFastTaskSortLabel(a.task)
        const bLabel = getFastTaskSortLabel(b.task)
        const aRank = fastTaskSortRank.get(aLabel) ?? fastTaskSortOrder.length
        const bRank = fastTaskSortRank.get(bLabel) ?? fastTaskSortOrder.length
        if (aRank !== bRank) return aRank - bRank
        return a.index - b.index
      })
      .map((entry) => entry.task)
  ), [getFastTaskSortLabel, fastTaskSortOrder.length, fastTaskSortRank])

  const handlePrint = React.useCallback(async () => {
    if (!data) return

    const printWindow = window.open("", "_blank")
    if (!printWindow) return

    const weekRange = `${formatDate(data.week_start)} - ${formatDate(data.week_end)}`
    const selectedDept = departmentId !== ALL_DEPARTMENTS_VALUE
      ? formatDepartmentName(departments.find(d => d.id === departmentId)?.name || "All Departments")
      : "All Departments"
    const printTitle = selectedDept !== "All Departments"
      ? `WEEKLY PLANNER - ${selectedDept.toUpperCase()}`
      : "WEEKLY PLANNER"
    const printedAt = new Date()
    const printInitials = (user?.full_name || user?.username || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join("") || "?"
    const legendEntriesByDept = new Map<string, LegendEntry[]>()
    const escapeHtml = (value: string) => (
      value
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
    )

    await Promise.all(
      data.departments.map(async (dept) => {
        const legendConfig = getLegendQuestions(dept.department_name)
        if (!legendConfig) return

        let entries: LegendEntry[] = []
        try {
          const qs = new URLSearchParams()
          qs.set("department_id", dept.department_id)
          qs.set("week_start", data.week_start)
          const res = await apiFetch(`/planners/weekly-planner/legend?${qs.toString()}`)
          if (res.ok) {
            entries = (await res.json()) as LegendEntry[]
          }
        } catch (error) {
          console.error("Failed to load print legend entries:", error)
        }

        const displayEntries = buildLegendDisplayEntries({
          entries,
          departmentId: dept.department_id,
          weekStart: data.week_start,
          departmentName: dept.department_name,
        })
        legendEntriesByDept.set(dept.department_id, displayEntries)
      })
    )

    const printHtml = `
      <!DOCTYPE html>
      <html>
        <head>
          <title>Weekly Planner - ${weekRange}</title>
          <style>
            @media print {
              @page {
                size: letter portrait;
                margin-top: 0.35in;
                margin-bottom: 0.35in;
                margin-left: 0.4in;
                margin-right: 0.4in;
              }
              body { margin: 0; padding: 0; }
              .print-page { page-break-after: avoid; page-break-inside: avoid; }
              .print-page:last-child { page-break-after: avoid; }
              table { page-break-inside: avoid; }
              tr { page-break-inside: avoid; }
              tbody { page-break-inside: avoid; }
            }
            * {
              box-sizing: border-box;
              -webkit-print-color-adjust: exact;
              print-color-adjust: exact;
              line-height: 1.1;
            }
            body {
              font-family: Arial, sans-serif;
              font-size: 5.5pt;
              margin: 0;
              padding: 0;
              width: 100%;
              margin-left: auto;
              margin-right: auto;
              direction: ltr;
            }
            .print-page {
              position: relative;
              height: calc(11in - 0.7in);
              width: 100%;
              display: grid;
              grid-template-rows: auto auto 1fr auto;
            }
            .print-header {
              display: grid;
              grid-template-columns: 1fr auto 1fr;
              align-items: center;
              margin-bottom: 2px;
            }
            .print-header.compact {
              grid-template-columns: 1fr auto;
              margin-bottom: 2px;
            }
            .print-title {
              margin: 0;
              font-size: 8pt;
              font-weight: 700;
              text-transform: uppercase;
              text-align: center;
              color: #0f172a;
              line-height: 1.1;
            }
            .print-datetime {
              text-align: right;
              font-size: 6pt;
              color: #334155;
            }
            .print-meta {
              text-align: center;
              margin-bottom: 2px;
              font-size: 6pt;
              color: #334155;
            }
            .print-meta.compact {
              margin-bottom: 2px;
              font-size: 0;
              line-height: 0;
              height: 0;
              overflow: hidden;
            }
            .print-content {
              width: 100%;
              min-height: 0;
              overflow: visible;
              max-height: calc(11in - 0.7in - 70px);
              padding-left: 0.05in;
              padding-right: 0.05in;
            }
            .print-dept-title {
              margin-top: 2px;
              margin-bottom: 1px;
              font-size: 7pt;
              font-weight: 700;
            }
            .print-legend {
              margin-top: 2px;
              margin-bottom: 6px;
              break-inside: avoid;
              page-break-inside: avoid;
            }
            .print-legend-title {
              font-size: 6.5pt;
              font-weight: 700;
              margin-bottom: 2px;
              color: #0f172a;
            }
            .legend-panels {
              display: flex;
              gap: 6px;
              align-items: stretch;
            }
            .legend-panel {
              border: 0.5px solid #cbd5e1;
              border-radius: 3px;
              padding: 2px;
            }
            .legend-panel-colors {
              width: 35%;
              flex: 0 0 35%;
            }
            .legend-panel-qa {
              width: 65%;
              flex: 0 0 65%;
            }
            .legend-table {
              width: 100%;
              border-collapse: collapse;
              margin: 0;
            }
            .legend-table th,
            .legend-table td {
              font-size: 6pt;
              padding: 1px;
              vertical-align: middle;
            }
            .legend-table th {
              border-bottom: 0.5px solid #000;
            }
            .legend-color-box {
              width: 18px;
              height: 10px;
              border: 0.5px solid #000;
            }
            .legend-question {
              color: #991b1b;
              font-weight: 600;
            }
            .legend-answer-line {
              height: 9px;
              border-bottom: 0.5px solid #000;
            }
            .pv-fest-cell {
              position: relative;
              min-height: 18px;
              border: 0.5px solid #cbd5e1;
              background: #f1f5f9;
              color: #475569;
              border-radius: 3px;
              padding: 2px 4px 3px;
              display: flex;
              align-items: flex-start;
              justify-content: flex-start;
            }
            .pv-fest-badge {
              position: absolute;
              top: 1px;
              right: 1px;
              font-size: 4.5pt;
              font-weight: 700;
              text-transform: uppercase;
              background: #e2e8f0;
              color: #475569;
              padding: 1px 2px;
              border-radius: 2px;
              letter-spacing: 0.2px;
            }
            .pv-fest-note {
              font-size: 5pt;
              font-weight: 600;
              line-height: 1.15;
              margin-top: 6px;
              color: #475569;
            }
            .print-legend-spacer {
              height: 0.18in;
            }
            .notes-table {
              width: 100%;
              border-collapse: collapse;
              margin-top: 0.08in;
              font-size: 6pt;
            }
            .notes-table td {
              border: 1px solid #000;
              padding: 4px 6px;
              vertical-align: top;
              min-height: 56px;
            }
            .notes-label {
              font-weight: 700;
              text-transform: uppercase;
              white-space: nowrap;
            }
            .notes-columns {
              display: grid;
              width: 100%;
              min-height: 36px;
            }
            .notes-column {
              padding: 0 6px;
              min-height: 36px;
            }
            .notes-column + .notes-column {
              border-left: 0.5px solid #94a3b8;
            }
            .notes-line {
              height: 11px;
              border-bottom: 0.5px solid #94a3b8;
            }
            .notes-line:last-child {
              border-bottom: 0;
            }
            table {
              width: 100%;
              border-collapse: collapse;
              table-layout: fixed;
              margin-bottom: 0.01in;
              direction: ltr;
            }
            thead {
              display: table-header-group;
            }
            tbody.day-group {
              break-inside: avoid;
              page-break-inside: avoid;
            }
            tbody.day-group tr:first-child > td,
            tbody.day-group tr:first-child > th {
              border-top: 2px solid #000;
            }
            tbody.day-group tr:last-child > td,
            tbody.day-group tr:last-child > th {
              border-bottom: 1px solid #000;
            }
            tr {
              break-inside: avoid;
              page-break-inside: avoid;
            }
            .print-content {
              max-height: calc(11in - 0.7in - 70px);
              overflow: visible;
            }
            th {
              background-color: #e2e8f0;
              border: 2px solid #000;
              padding: 1px;
              text-align: left;
              font-weight: bold;
              font-size: 5.5pt;
              text-transform: uppercase;
              vertical-align: bottom;
              line-height: 1.1;
              overflow-wrap: anywhere;
              word-break: break-word;
            }
            th.user-header {
              white-space: normal;
              word-break: break-word;
              font-size: 5.5pt;
              line-height: 1.05;
            }
            td {
              border: 0.25px solid #000;
              padding: 0.5px;
              vertical-align: bottom;
              font-size: 5.5pt;
              line-height: 1.1;
              text-align: left;
              overflow-wrap: anywhere;
              word-break: break-word;
            }
            .day-cell {
              font-weight: bold;
              background-color: #f9f9f9;
              text-align: left;
              width: 70px;
              vertical-align: bottom;
              white-space: nowrap;
            }
            .ll-cell {
              font-weight: bold;
              background-color: #f9f9f9;
              text-align: left;
              width: 32px;
              vertical-align: bottom;
              font-size: 4.5pt;
              line-height: 1;
              letter-spacing: -0.2px;
              white-space: nowrap;
              padding-left: 0.5px;
              padding-right: 0.5px;
            }
            .time-cell {
              width: 22px;
              text-align: left;
              padding-left: 1px;
              padding-right: 1px;
              vertical-align: bottom;
            }
            .print-subhead {
              font-weight: bold;
              text-transform: uppercase;
              font-size: 6pt;
            }
            .project-card {
              margin: 1px 0;
              padding: 1px;
              background-color: #f5f5f5;
              border: 0.5px solid #ddd;
              border-radius: 2px;
              break-inside: avoid;
              page-break-inside: avoid;
            }
            .project-title {
              font-weight: bold;
              margin-bottom: 0.5px;
              line-height: 1.1;
              overflow-wrap: anywhere;
              word-break: break-word;
            }
            .task-item {
              font-size: 5pt;
              margin: 0.5px 0;
              padding: 0.5px 1px;
              border: 0.5px solid #000;
              border-radius: 2px;
              background-color: #fff;
              break-inside: avoid;
              page-break-inside: avoid;
              line-height: 1.1;
              overflow-wrap: anywhere;
              word-break: break-word;
            }
            .task-marker { color: #dc2626; font-weight: 900; margin-right: 2px; }
            .task-status-todo { background-color: #FFC4ED; }
            .task-status-in-progress { background-color: #FFFF00; }
            .task-status-waiting { background-color: #FFEDD5; border-color: #C2410C; color: #9A3412; }
            .task-status-waiting-client { background-color: #E2C15B; border-color: #B8860B; color: #4F3A00; }
            .task-status-done { background-color: #C4FDC4; }
            .task-status-new-open { background-color: #dbeafe; border-color: #1d4ed8; }
            .task-status-new-done { background-color: #6ee7b7; border-color: #059669; }
            .task-status-deadline { background-color: #dc2626; border-color: #991b1b; color: #ffffff; }
            .task-item.repeat-task-muted,
            .task-item.repeat-task-muted .badge,
            .task-item.repeat-task-muted .products {
              color: #9ca3af !important;
            }
            .badge {
              display: inline-block;
              padding: 0.5px 2px;
              border-radius: 2px;
              font-size: 5pt;
              font-weight: bold;
              margin-left: 1px;
              line-height: 1.1;
            }
            .badge-bll { background-color: #fee2e2; color: #991b1b; }
            .badge-r1 { background-color: #e0e7ff; color: #3730a3; }
            .badge-1h { background-color: #fef3c7; color: #92400e; }
            .badge-ga { background-color: #dbeafe; color: #1e40af; }
            .badge-p { background-color: #d1fae5; color: #065f46; }
            .badge-n { background-color: #f1f5f9; color: #475569; }
            .badge-dl { background-color: #fee2e2; color: #991b1b; }
            .badge-new {
              background-color: #dbeafe;
              color: #1e40af;
              border: 0.5px solid #93c5fd;
              font-size: 4pt;
              letter-spacing: -0.1px;
              padding: 0.25px 1.5px;
            }
            .products {
              color: #2563eb;
              font-weight: bold;
              font-size: 5pt;
            }
            .empty-cell {
              text-align: left;
              color: #999;
            }
            .am-end-row > td,
            .am-end-row > th {
              border-bottom: 0 !important;
            }
            .pm-row > td,
            .pm-row > th {
              border-top-width: 0.5px !important;
              border-top-style: dashed !important;
              border-top-color: #444 !important;
            }
            .table-narrow th,
            .table-narrow td {
              font-size: 5pt;
            }
            .table-narrow .task-item,
            .table-narrow .badge,
            .table-narrow .products {
              font-size: 4pt;
            }
            .table-compact th,
            .table-compact td {
              font-size: 5pt;
              padding: 0.5px;
            }
            .table-compact .task-item,
            .table-compact .badge,
            .table-compact .products {
              font-size: 4pt;
            }
            .table-compact th.user-header {
              font-size: 5pt;
              line-height: 1;
            }
            .table-ultra-compact th,
            .table-ultra-compact td {
              font-size: 4.5pt;
              padding: 0.25px;
            }
            .table-ultra-compact .task-item,
            .table-ultra-compact .badge,
            .table-ultra-compact .products {
              font-size: 3.5pt;
            }
            .table-ultra-compact th.user-header {
              font-size: 4.5pt;
              line-height: 1;
            }
            .print-footer {
              margin-top: auto;
              display: grid;
              grid-template-columns: 1fr auto 1fr;
              padding-left: 0.1in;
              padding-right: 0.04in;
              padding-bottom: 0.05in;
              font-size: 6pt;
              color: #334155;
              background: #fff;
            }
            .print-page-count {
              text-align: center;
            }
            .print-initials {
              text-align: right;
            }
            .print-measure {
              position: absolute;
              left: -9999px;
              top: 0;
              visibility: hidden;
              width: 7.7in;
            }
          </style>
        </head>
        <body>
          <div id="print-root"></div>
        </body>
      </html>
    `

    printWindow.document.write(printHtml)
    printWindow.document.close()
    printWindow.focus()

    const doc = printWindow.document
    const root = doc.getElementById("print-root")
    if (!root) return



    const formatPrintedAt = formatDateTimeDMY(printedAt)

    const createHeader = (showTitle: boolean) => {
      const header = doc.createElement("div")
      header.className = showTitle ? "print-header" : "print-header compact"
      header.innerHTML = showTitle
        ? `
        <div></div>
        <div class="print-title">${printTitle}</div>
        <div class="print-datetime">${formatPrintedAt}</div>
      `
        : `
        <div></div>
        <div class="print-datetime">${formatPrintedAt}</div>
      `
      return header
    }

    const createMeta = (showMeta: boolean) => {
      const meta = doc.createElement("div")
      meta.className = showMeta ? "print-meta" : "print-meta compact"
      meta.innerHTML = showMeta
        ? `<strong>Week:</strong> ${weekRange} | <strong>Department:</strong> ${selectedDept}`
        : ""
      return meta
    }

    const createFooter = () => {
      const footer = doc.createElement("div")
      footer.className = "print-footer"
      footer.innerHTML = `
        <div></div>
        <div class="print-page-count"></div>
        <div class="print-initials">PUNOI: ${printInitials}</div>
      `
      return footer
    }

    const createLegendSection = (entries: LegendEntry[]) => {
      const wrapper = doc.createElement("div")
      wrapper.className = "print-legend"

      const title = doc.createElement("div")
      title.className = "print-legend-title"
      title.textContent = "Legend / Questions"
      wrapper.appendChild(title)

      const panels = doc.createElement("div")
      panels.className = "legend-panels"

      const swatches = buildLegendSwatches(entries)
      const colorPanel = doc.createElement("div")
      colorPanel.className = "legend-panel legend-panel-colors"
      const colorTable = doc.createElement("table")
      colorTable.className = "legend-table"
      colorTable.innerHTML = `
        <thead>
          <tr>
            <th>Color</th>
            <th>Label</th>
          </tr>
        </thead>
      `
      const colorBody = doc.createElement("tbody")
      swatches.forEach((swatch) => {
        const row = doc.createElement("tr")
        const colorCell = doc.createElement("td")
        const colorBox = doc.createElement("div")
        colorBox.className = "legend-color-box"
        colorBox.style.backgroundColor = swatch.color
        colorCell.appendChild(colorBox)
        row.appendChild(colorCell)

        const labelCell = doc.createElement("td")
        labelCell.textContent = swatch.displayLabel
        row.appendChild(labelCell)
        colorBody.appendChild(row)
      })
      colorTable.appendChild(colorBody)
      colorPanel.appendChild(colorTable)
      panels.appendChild(colorPanel)

      const qaPanel = doc.createElement("div")
      qaPanel.className = "legend-panel legend-panel-qa"
      const qaTable = doc.createElement("table")
      qaTable.className = "legend-table"
      qaTable.innerHTML = `
        <thead>
          <tr>
            <th>Question</th>
            <th>Answer</th>
          </tr>
        </thead>
      `
      const qaBody = doc.createElement("tbody")
      entries.forEach((entry) => {
        const row = doc.createElement("tr")
        const questionCell = doc.createElement("td")
        if (entry.question_text) {
          const question = doc.createElement("span")
          question.className = "legend-question"
          question.textContent = entry.question_text
          questionCell.appendChild(question)
        } else {
          questionCell.textContent = "-"
        }
        row.appendChild(questionCell)

        const answerCell = doc.createElement("td")
        const answer = entry.answer_text?.trim() || ""
        const isPlaceholder = entry.id.startsWith("__placeholder__")
        if (isPlaceholder) {
          answerCell.textContent = "-"
        } else if (answer) {
          answerCell.textContent = answer
        } else {
          const answerLine = doc.createElement("div")
          answerLine.className = "legend-answer-line"
          answerCell.appendChild(answerLine)
        }
        row.appendChild(answerCell)
        qaBody.appendChild(row)
      })
      qaTable.appendChild(qaBody)
      qaPanel.appendChild(qaTable)
      panels.appendChild(qaPanel)

      wrapper.appendChild(panels)
      return wrapper
    }

    const createNotesSection = (userCount: number) => {
      const notesLabelWidth = dayColWidth + timeColWidth + llColWidth
      const columns = Math.max(1, userCount)
      const wrapper = doc.createElement("div")
      const table = doc.createElement("table")
      table.className = "notes-table"

      const colgroup = doc.createElement("colgroup")
      colgroup.innerHTML = `
        <col style="width: ${notesLabelWidth}px;" />
        <col />
      `
      table.appendChild(colgroup)

      const buildLinesHtml = () => `
        <div class="notes-columns" style="grid-template-columns: repeat(${columns}, minmax(0, 1fr));">
          ${Array.from({ length: columns })
            .map(
              () => `
            <div class="notes-column">
            </div>
          `
            )
            .join("")}
        </div>
      `

      const tbody = doc.createElement("tbody")
      tbody.innerHTML = `
        <tr>
          <td class="notes-label">KOMENT</td>
          <td>${buildLinesHtml()}</td>
        </tr>
        <tr>
          <td class="notes-label">ANKESA / KERKESA / PROPOZIME</td>
          <td>${buildLinesHtml()}</td>
        </tr>
      `
      table.appendChild(tbody)

      wrapper.appendChild(table)
      return wrapper
    }

    const createPage = (options?: { showTitle?: boolean; showMeta?: boolean }) => {
      const { showTitle = true, showMeta = true } = options || {}
      const page = doc.createElement("div")
      page.className = "print-page"
      page.appendChild(createHeader(showTitle))
      page.appendChild(createMeta(showMeta))
      const content = doc.createElement("div")
      content.className = "print-content"
      page.appendChild(content)
      page.appendChild(createFooter())
      return { page, content }
    }

    const dayColWidth = 70
    const llColWidth = 32
    const timeColWidth = 22
    const minUserColWidth = 48
    const targetUserColWidth = 72

    const getDepartmentUsersForPrint = (dept: WeeklyTableDepartment) => {
      const ordered = orderedUsersByDept[dept.department_id]
      if (ordered && ordered.length > 0) {
        return ordered
      }

      const fallbackUsers = buildDepartmentUsers(dept)
      return fallbackUsers.filter((user) => user.user_name.trim().length > 0)
    }

    const repeatedTaskFirstDateByDepartmentUser = new Map(
      data.departments.map((dept) => [
        dept.department_id,
        new Map(
          getDepartmentUsersForPrint(dept).map((entry) => [
            entry.user_id,
            buildWeeklyPlannerRepeatedTaskFirstDateMap(dept, entry.user_id),
          ])
        ),
      ])
    )

    const getPrintRepeatedTaskClassName = (
      departmentId: string,
      userId: string,
      task: { task_id?: string | null },
      dayIso: string
    ) => {
      const firstDateByTaskId = repeatedTaskFirstDateByDepartmentUser.get(departmentId)?.get(userId)
      return firstDateByTaskId && isRepeatedTaskInstance(task, dayIso, firstDateByTaskId)
        ? "repeat-task-muted"
        : ""
    }

    const getPrintableWidth = () => {
      if (measure.clientWidth) return measure.clientWidth
      return Math.max(0, Math.floor(printWindow.innerWidth * 0.9))
    }

    const getUserColumnWidth = (userCount: number) => {
      const measureWidth = getPrintableWidth() ? Math.floor(getPrintableWidth() * 0.98) : 0
      const fixedWidth = dayColWidth + llColWidth + timeColWidth
      const availableWidth = Math.max(0, measureWidth - fixedWidth)
      if (userCount <= 0) return minUserColWidth
      return Math.max(minUserColWidth, Math.floor(availableWidth / userCount))
    }

    const getMaxUsersPerPage = (totalUsers: number) => {
      if (totalUsers <= 0) return 1
      const printableWidth = getPrintableWidth()
      const fixedWidth = dayColWidth + llColWidth + timeColWidth
      const availableWidth = Math.max(0, printableWidth - fixedWidth)
      if (availableWidth <= 0) return 1
      const maxByTarget = Math.max(1, Math.floor(availableWidth / targetUserColWidth))
      return Math.min(totalUsers, maxByTarget)
    }

    const chunkUsers = (allUsers: WeeklyPrintUser[], chunkSize: number) => {
      if (chunkSize <= 0) return [allUsers]
      const chunks: WeeklyPrintUser[][] = []
      for (let i = 0; i < allUsers.length; i += chunkSize) {
        chunks.push(allUsers.slice(i, i + chunkSize))
      }
      return chunks
    }

    const createTable = (allUsers: WeeklyPrintUser[]) => {
      const userCount = allUsers.length
      const userColWidth = getUserColumnWidth(userCount)
      const table = doc.createElement("table")
      if (userColWidth <= 55) {
        table.classList.add("table-narrow")
      }
      if (userCount >= 8) {
        table.classList.add("table-compact")
      }
      if (userCount >= 12) {
        table.classList.add("table-ultra-compact")
      }
      const colgroup = doc.createElement("colgroup")
      colgroup.innerHTML = `
        <col style="width: ${dayColWidth}px;" />
        <col style="width: ${timeColWidth}px;" />
        <col style="width: ${llColWidth}px;" />
        ${allUsers.map(() => `<col style="width: ${userColWidth}px;" />`).join("")}
      `
      const thead = doc.createElement("thead")
      thead.innerHTML = `
        <tr>
          <th class="day-cell" rowspan="2">Day</th>
          <th class="time-cell" style="width: ${timeColWidth}px;">Time</th>
          <th style="width: ${llColWidth}px;">LL</th>
          ${allUsers.map(user => `<th class="user-header">${user.user_name}</th>`).join("")}
        </tr>
      `
      table.appendChild(colgroup)
      table.appendChild(thead)
      return table
    }

    const fitContentToWidth = (content: HTMLElement) => {
      const tables = Array.from(content.querySelectorAll("table")) as HTMLTableElement[]
      const maxTableWidth = tables.reduce((max, table) => Math.max(max, table.scrollWidth), 0)
      const availableWidth = Math.max(0, content.clientWidth - 2)
      if (maxTableWidth > 0 && availableWidth > 0) {
        const scale = Math.min(1, (availableWidth / maxTableWidth) * 0.98)
        if (scale < 1) {
          content.style.transform = `scale(${scale})`
          content.style.transformOrigin = "top left"
          content.style.width = `${Math.round((1 / scale) * 1000) / 10}%`
          return
        }
      }
      content.style.transform = ""
      content.style.transformOrigin = ""
      content.style.width = "100%"
    }

    const isContentOverflowing = (content: HTMLElement | null) => {
      if (!content) return false
      // Force layout so scrollHeight/clientHeight are accurate in the offscreen measure container.
      void content.offsetHeight
      return content.clientHeight > 0 && content.scrollHeight > content.clientHeight + 1
    }

    const buildBadgeClass = (label: string) => {
      if (label === "BLL") return "badge-bll"
      if (label === "R1") return "badge-r1"
      if (label === "1H") return "badge-1h"
      if (label === "GA") return "badge-ga"
      if (label === "PX JAV") return "badge-ga"
      if (label === "P:") return "badge-p"
      if (label === "N") return "badge-n"
      if (label === "DL") return "badge-dl"
      return ""
    }

    const getPrintTaskStatusClass = (
      task: Pick<WeeklyTableTaskEntry, "status" | "completed_at" | "daily_status" | "created_at" | "is_deadline_important">,
      dayIso: string
    ) => {
      const statusValue = getStatusValueForDay(task.status, task.completed_at, dayIso, task.daily_status)
      if (task.is_deadline_important) {
        if (statusValue === "DONE") return "task-status-done"
        return "task-status-deadline"
      }
      const isNew = isTaskNewForWeek(task.created_at, data.week_start)
      if (isNew) {
        if (statusValue === "DONE") return "task-status-new-done"
        if (statusValue === "WAITING_CONFIRMATION") return "task-status-waiting"
        if (statusValue === "WAITING_CLIENT") return "task-status-waiting-client"
        if (statusValue === "IN_PROGRESS") return "task-status-in-progress"
        return "task-status-new-open"
      }
      if (statusValue === "DONE") return "task-status-done"
      if (statusValue === "WAITING_CONFIRMATION") return "task-status-waiting"
      if (statusValue === "WAITING_CLIENT") return "task-status-waiting-client"
      if (statusValue === "IN_PROGRESS") return "task-status-in-progress"
      return "task-status-todo"
    }

    const buildPrintNewBadge = (createdAt?: string | null) => {
      if (!isTaskNewForWeek(createdAt, data.week_start)) return ""
      return ` <span class="badge badge-new">NEW</span>`
    }

    const buildPrintTaskMarker = (task: Pick<WeeklyTableTaskEntry, "one_h_marker" | "one_h_marker_by_ga">) => {
      const label = taskOneHMarkerLabel(task.one_h_marker, task.one_h_marker_by_ga)
      return label ? `<span class="task-marker">${escapeHtml(label)}</span>` : ""
    }

    const renderDayGroupHtml = (
      day: WeeklyTableDay,
      dayIndex: number,
      allUsers: WeeklyPrintUser[],
      departmentId: string,
      departmentName?: string
    ) => {
      const dayName = DAY_NAMES[dayIndex]
      const dayDate = formatDate(day.date)
      const dayIso = day.date
      const isGADepartment = departmentName === "GA"
      const rowSpan = isGADepartment ? 6 : 4

      let html = ""
      
      if (isGADepartment) {
        // GA Department: SYS, FT, PRJK order
        // AM SYS Row
        html += `
          <tr>
            <td class="day-cell" rowspan="${rowSpan}" style="text-align: left; padding: 1px;">
              <div style="display: flex; flex-direction: column;">
                <strong class="print-subhead">${dayName}</strong>
                <span class="print-subhead" style="margin-top: 0.5px;">${dayDate}</span>
              </div>
            </td>
            <td class="print-subhead time-cell" rowspan="3">AM</td>
            <td class="ll-cell print-subhead">SYS</td>
        `
        allUsers.forEach((user) => {
          const userDay = day.users.find(u => u.user_id === user.user_id)
          const systemTasks = userDay?.am_system_tasks || []
          const block = getBlockForSlot(user.user_id, dayIso, "am")
          const isBlocked = Boolean(block)

          html += `<td>`
          if (isBlocked) {
            html += `<div class="pv-fest-cell">`
            html += `<div class="pv-fest-badge">PV/FEST</div>`
            html += `<div class="pv-fest-note">${block?.note ? escapeHtml(block.note) : ""}</div>`
            html += `</div>`
          } else if (systemTasks.length > 0) {
            html += `<div style="font-size: 4pt; color: #1e40af;">`
            systemTasks.forEach((task, taskIndex) => {
              const statusClass = getPrintTaskStatusClass(task, dayIso)
              const repeatedTaskClass = getPrintRepeatedTaskClassName(departmentId, user.user_id, task, dayIso)
              html += `<div class="task-item ${statusClass} ${repeatedTaskClass}">${taskIndex + 1}. ${buildPrintTaskMarker(task)}${escapeHtml(getPlannerTaskDisplayTitle(task))}${buildPrintNewBadge(task.created_at)}</div>`
            })
            html += `</div>`
          } else {
            html += `<div class="empty-cell">-</div>`
          }
          html += `</td>`
        })
        html += `</tr>`

        // AM FT Row
        html += `<tr class="am-end-row">`
        html += `<td class="ll-cell print-subhead">FT</td>`
        allUsers.forEach((user) => {
          const userDay = day.users.find(u => u.user_id === user.user_id)
          const fastTasks = sortFastTasks(userDay?.am_fast_tasks || [])
          const block = getBlockForSlot(user.user_id, dayIso, "am")
          const isBlocked = Boolean(block)

          html += `<td>`
          if (isBlocked) {
            html += `<div class="pv-fest-cell">`
            html += `<div class="pv-fest-badge">PV/FEST</div>`
            html += `<div class="pv-fest-note">${block?.note ? escapeHtml(block.note) : ""}</div>`
            html += `</div>`
          } else if (fastTasks.length > 0) {
            html += `<div style="font-size: 4pt; color: #0f172a;">`
            fastTasks.forEach((task, taskIndex) => {
              const statusClass = getPrintTaskStatusClass(task, dayIso)
              const repeatedTaskClass = getPrintRepeatedTaskClassName(departmentId, user.user_id, task, dayIso)
              html += `<div class="task-item ${statusClass} ${repeatedTaskClass}">${taskIndex + 1}. ${buildPrintTaskMarker(task)}${escapeHtml(getPlannerTaskDisplayTitle(task))}`
              const badge = getFastTaskBadge({ ...task, day_date: dayIso })
              if (badge) {
                html += ` <span class="badge ${buildBadgeClass(badge.label)}">${badge.label}</span>`
              }
              html += buildPrintNewBadge(task.created_at)
              html += `</div>`
            })
            html += `</div>`
          } else {
            html += `<div class="empty-cell">-</div>`
          }
          html += `</td>`
        })
        html += `</tr>`

        // AM PRJK Row
        html += `<tr class="am-end-row">`
        html += `<td class="ll-cell print-subhead">PRJK</td>`
      } else {
        // Other Departments: PRJK, FT order (original)
        html += `
          <tr>
            <td class="day-cell" rowspan="${rowSpan}" style="text-align: left; padding: 1px;">
              <div style="display: flex; flex-direction: column;">
                <strong class="print-subhead">${dayName}</strong>
                <span class="print-subhead" style="margin-top: 0.5px;">${dayDate}</span>
              </div>
            </td>
            <td class="print-subhead time-cell" rowspan="2">AM</td>
            <td class="ll-cell print-subhead">PRJK</td>
        `
      }
      allUsers.forEach((user) => {
        const userDay = day.users.find(u => u.user_id === user.user_id)
        const projects = (userDay?.am_projects || []).filter(hasVisibleProjectTasks)
        const block = getBlockForSlot(user.user_id, dayIso, "am")
        const isBlocked = Boolean(block)

        html += `<td>`
        if (isBlocked) {
          html += `<div class="pv-fest-cell">`
          html += `<div class="pv-fest-badge">PV/FEST</div>`
          html += `<div class="pv-fest-note">${block?.note ? escapeHtml(block.note) : ""}</div>`
          html += `</div>`
        } else if (projects.length > 0) {
          projects.forEach((project, projectIndex) => {
            html += `<div class="project-card">
              <div class="project-title">${projectIndex + 1}. ${escapeHtml(getProjectDisplayTitle(project))}</div>`
            if (project.tasks && project.tasks.length > 0) {
              project.tasks.forEach((task, taskIndex) => {
                const statusClass = getPrintTaskStatusClass(task, dayIso)
                const repeatedTaskClass = getPrintRepeatedTaskClassName(departmentId, user.user_id, task, dayIso)
                const taskNumber = `${projectIndex + 1}.${taskIndex + 1}`
                html += `<div class="task-item ${statusClass} ${repeatedTaskClass}">${taskNumber}. ${buildPrintTaskMarker(task)}${escapeHtml(getPlannerTaskDisplayTitle(task))}`
                const productLabel = formatTaskProducts(task, project, departmentName)
                if (productLabel) {
                  html += ` <span class="products">${productLabel}</span>`
                }
                const badge = getTaskStatusBadge({ ...task, day_date: dayIso })
                if (badge) {
                  html += ` <span class="badge ${buildBadgeClass(badge.label)}">${badge.label}</span>`
                }
                html += buildPrintNewBadge(task.created_at)
                html += `</div>`
              })
            }
            html += `</div>`
          })
        } else {
          html += `<div class="empty-cell">-</div>`
        }
        html += `</td>`
      })
      html += `</tr>`

      if (!isGADepartment) {
        // FT Row for non-GA departments
        html += `<tr>`
        html += `<td class="ll-cell print-subhead">FT</td>`
      allUsers.forEach((user) => {
        const userDay = day.users.find(u => u.user_id === user.user_id)
        const fastTasks = sortFastTasks(userDay?.am_fast_tasks || [])
        const block = getBlockForSlot(user.user_id, dayIso, "am")
        const isBlocked = Boolean(block)

        html += `<td>`
        if (isBlocked) {
          html += `<div class="pv-fest-cell">`
          html += `<div class="pv-fest-badge">PV/FEST</div>`
          html += `<div class="pv-fest-note">${block?.note ? escapeHtml(block.note) : ""}</div>`
          html += `</div>`
        } else if (fastTasks.length > 0) {
          html += `<div style="font-size: 4pt; color: #0f172a;">`
          fastTasks.forEach((task, taskIndex) => {
            const statusClass = getPrintTaskStatusClass(task, dayIso)
            const repeatedTaskClass = getPrintRepeatedTaskClassName(departmentId, user.user_id, task, dayIso)
            html += `<div class="task-item ${statusClass} ${repeatedTaskClass}">${taskIndex + 1}. ${buildPrintTaskMarker(task)}${escapeHtml(getPlannerTaskDisplayTitle(task))}`
            const badge = getFastTaskBadge({ ...task, day_date: dayIso })
            if (badge) {
              html += ` <span class="badge ${buildBadgeClass(badge.label)}">${badge.label}</span>`
            }
            html += buildPrintNewBadge(task.created_at)
            html += `</div>`
          })
          html += `</div>`
        } else {
          html += `<div class="empty-cell">-</div>`
        }
        html += `</td>`
      })
        html += `</tr>`
      }

      // PM Section
      if (isGADepartment) {
        // PM SYS Row
        html += `<tr class="pm-row">`
        html += `<td class="print-subhead time-cell" rowspan="3">PM</td>`
        html += `<td class="ll-cell print-subhead">SYS</td>`
        allUsers.forEach((user) => {
          const userDay = day.users.find(u => u.user_id === user.user_id)
          const systemTasks = userDay?.pm_system_tasks || []
          const block = getBlockForSlot(user.user_id, dayIso, "pm")
          const isBlocked = Boolean(block)

          html += `<td>`
          if (isBlocked) {
            html += `<div class="pv-fest-cell">`
            html += `<div class="pv-fest-badge">PV/FEST</div>`
            html += `<div class="pv-fest-note">${block?.note ? escapeHtml(block.note) : ""}</div>`
            html += `</div>`
          } else if (systemTasks.length > 0) {
            html += `<div style="font-size: 4pt; color: #1e40af;">`
            systemTasks.forEach((task, taskIndex) => {
              const statusClass = getPrintTaskStatusClass(task, dayIso)
              const repeatedTaskClass = getPrintRepeatedTaskClassName(departmentId, user.user_id, task, dayIso)
              html += `<div class="task-item ${statusClass} ${repeatedTaskClass}">${taskIndex + 1}. ${buildPrintTaskMarker(task)}${escapeHtml(getPlannerTaskDisplayTitle(task))}${buildPrintNewBadge(task.created_at)}</div>`
            })
            html += `</div>`
          } else {
            html += `<div class="empty-cell">-</div>`
          }
          html += `</td>`
        })
        html += `</tr>`

        // PM FT Row
        html += `<tr>`
        html += `<td class="ll-cell print-subhead">FT</td>`
        allUsers.forEach((user) => {
          const userDay = day.users.find(u => u.user_id === user.user_id)
          const fastTasks = sortFastTasks(userDay?.pm_fast_tasks || [])
          const block = getBlockForSlot(user.user_id, dayIso, "pm")
          const isBlocked = Boolean(block)

          html += `<td>`
          if (isBlocked) {
            html += `<div class="pv-fest-cell">`
            html += `<div class="pv-fest-badge">PV/FEST</div>`
            html += `<div class="pv-fest-note">${block?.note ? escapeHtml(block.note) : ""}</div>`
            html += `</div>`
          } else if (fastTasks.length > 0) {
            html += `<div style="font-size: 4pt; color: #0f172a;">`
            fastTasks.forEach((task, taskIndex) => {
              const statusClass = getPrintTaskStatusClass(task, dayIso)
              const repeatedTaskClass = getPrintRepeatedTaskClassName(departmentId, user.user_id, task, dayIso)
              html += `<div class="task-item ${statusClass} ${repeatedTaskClass}">${taskIndex + 1}. ${buildPrintTaskMarker(task)}${escapeHtml(getPlannerTaskDisplayTitle(task))}`
              const badge = getFastTaskBadge({ ...task, day_date: dayIso })
              if (badge) {
                html += ` <span class="badge ${buildBadgeClass(badge.label)}">${badge.label}</span>`
              }
              html += buildPrintNewBadge(task.created_at)
              html += `</div>`
            })
            html += `</div>`
          } else {
            html += `<div class="empty-cell">-</div>`
          }
          html += `</td>`
        })
        html += `</tr>`

        // PM PRJK Row
        html += `<tr>`
        html += `<td class="ll-cell print-subhead">PRJK</td>`
      } else {
        // PM PRJK Row for non-GA departments
        html += `<tr class="pm-row">`
        html += `<td class="print-subhead time-cell" rowspan="2">PM</td>`
        html += `<td class="ll-cell print-subhead">PRJK</td>`
      }
      
      allUsers.forEach((user) => {
        const userDay = day.users.find(u => u.user_id === user.user_id)
        const projects = (userDay?.pm_projects || []).filter(hasVisibleProjectTasks)
        const block = getBlockForSlot(user.user_id, dayIso, "pm")
        const isBlocked = Boolean(block)

        html += `<td>`
        if (isBlocked) {
          html += `<div class="pv-fest-cell">`
          html += `<div class="pv-fest-badge">PV/FEST</div>`
          html += `<div class="pv-fest-note">${block?.note ? escapeHtml(block.note) : ""}</div>`
          html += `</div>`
        } else if (projects.length > 0) {
          projects.forEach((project, projectIndex) => {
            html += `<div class="project-card">
              <div class="project-title">${projectIndex + 1}. ${escapeHtml(getProjectDisplayTitle(project))}</div>`
            if (project.tasks && project.tasks.length > 0) {
              project.tasks.forEach((task, taskIndex) => {
                const statusClass = getPrintTaskStatusClass(task, dayIso)
                const repeatedTaskClass = getPrintRepeatedTaskClassName(departmentId, user.user_id, task, dayIso)
                const taskNumber = `${projectIndex + 1}.${taskIndex + 1}`
                html += `<div class="task-item ${statusClass} ${repeatedTaskClass}">${taskNumber}. ${buildPrintTaskMarker(task)}${escapeHtml(getPlannerTaskDisplayTitle(task))}`
                const productLabel = formatTaskProducts(task, project, departmentName)
                if (productLabel) {
                  html += ` <span class="products">${productLabel}</span>`
                }
                const badge = getTaskStatusBadge({ ...task, day_date: dayIso })
                if (badge) {
                  html += ` <span class="badge ${buildBadgeClass(badge.label)}">${badge.label}</span>`
                }
                html += buildPrintNewBadge(task.created_at)
                html += `</div>`
              })
            }
            html += `</div>`
          })
        } else {
          html += `<div class="empty-cell">-</div>`
        }
        html += `</td>`
      })
      html += `</tr>`

      if (!isGADepartment) {
        // PM FT Row for non-GA departments
        html += `<tr>`
        html += `<td class="ll-cell print-subhead">FT</td>`
      allUsers.forEach((user) => {
        const userDay = day.users.find(u => u.user_id === user.user_id)
        const fastTasks = sortFastTasks(userDay?.pm_fast_tasks || [])
        const block = getBlockForSlot(user.user_id, dayIso, "pm")
        const isBlocked = Boolean(block)

        html += `<td>`
        if (isBlocked) {
          html += `<div class="pv-fest-cell">`
          html += `<div class="pv-fest-badge">PV/FEST</div>`
          html += `<div class="pv-fest-note">${block?.note ? escapeHtml(block.note) : ""}</div>`
          html += `</div>`
        } else if (fastTasks.length > 0) {
          html += `<div style="font-size: 4pt; color: #0f172a;">`
          fastTasks.forEach((task, taskIndex) => {
            const statusClass = getPrintTaskStatusClass(task, dayIso)
            const repeatedTaskClass = getPrintRepeatedTaskClassName(departmentId, user.user_id, task, dayIso)
            html += `<div class="task-item ${statusClass} ${repeatedTaskClass}">${taskIndex + 1}. ${buildPrintTaskMarker(task)}${escapeHtml(getPlannerTaskDisplayTitle(task))}`
            const badge = getFastTaskBadge({ ...task, day_date: dayIso })
            if (badge) {
              html += ` <span class="badge ${buildBadgeClass(badge.label)}">${badge.label}</span>`
            }
            html += buildPrintNewBadge(task.created_at)
            html += `</div>`
          })
          html += `</div>`
        } else {
          html += `<div class="empty-cell">-</div>`
        }
        html += `</td>`
      })
      html += `</tr>`
      }

      return html
    }

    const measure = doc.createElement("div")
    measure.className = "print-measure"
    root.appendChild(measure)

    const pages: HTMLDivElement[] = []

    data.departments.forEach((dept) => {
      const allUsers = getDepartmentUsersForPrint(dept)
      const maxUsersPerPage = getMaxUsersPerPage(allUsers.length)
      const userChunks = chunkUsers(allUsers, maxUsersPerPage)

      userChunks.forEach((chunk, chunkIndex) => {
        const isFirstPage = pages.length === 0
        const { page, content } = createPage({ showTitle: isFirstPage, showMeta: isFirstPage })
        measure.appendChild(page)
        pages.push(page)

        const legendEntries = legendEntriesByDept.get(dept.department_id)
        if (legendEntries && legendEntries.length > 0 && chunkIndex === 0) {
          content.appendChild(createLegendSection(legendEntries))
          const legendSpacer = doc.createElement("div")
          legendSpacer.className = "print-legend-spacer"
          content.appendChild(legendSpacer)
        }

        const deptTitle = doc.createElement("div")
        deptTitle.className = "print-dept-title"
        let chunkLabel = ""
        if (allUsers.length > 0 && userChunks.length > 1) {
          const chunkStart = chunkIndex * maxUsersPerPage + 1
          const chunkEnd = Math.min(allUsers.length, chunkStart + chunk.length - 1)
          chunkLabel = ` (${chunkStart}-${chunkEnd} of ${allUsers.length})`
        }
        deptTitle.textContent = `${formatDepartmentName(dept.department_name)}${chunkLabel}`
        content.appendChild(deptTitle)

        const table = createTable(chunk)
        content.appendChild(table)

        dept.days.forEach((day, dayIndex) => {
          const tbody = doc.createElement("tbody")
          tbody.className = "day-group"
          tbody.innerHTML = renderDayGroupHtml(
            day,
            dayIndex,
            chunk,
            dept.department_id,
            dept.department_name
          )
          table.appendChild(tbody)
        })

        if (chunkIndex === userChunks.length - 1) {
          content.appendChild(createNotesSection(chunk.length))
        }

        fitContentToWidth(content)
      })
    })

    const renderPages = () => {
      root.innerHTML = ""
      pages.forEach((page, index) => {
        const countEl = page.querySelector(".print-page-count")
        if (countEl) {
          countEl.textContent = `Page ${index + 1} / ${pages.length}`
        }
        root.appendChild(page)
      })
    }

    setTimeout(() => {
      renderPages()
      requestAnimationFrame(() => {
        pages.forEach((page) => {
          const content = page.querySelector(".print-content") as HTMLElement | null
          if (content) {
            fitContentToWidth(content)
          }
        })
        printWindow.print()
      })
    }, 200)
  }, [
    apiFetch,
    data,
    departmentId,
    departments,
    getFastTaskBadge,
    getBlockForSlot,
    getProjectDisplayTitle,
    getPlannerTaskDisplayTitle,
    getStatusValueForDay,
    getTaskStatusBadge,
    isTaskNewForWeek,
    sortFastTasks,
    users,
  ])

  const parseFilenameFromDisposition = (headerValue: string | null) => {
    if (!headerValue) return null
    const match = headerValue.match(/filename=\"?([^\";]+)\"?/i)
    return match ? match[1] : null
  }

  const exportWeeklyPlannerExcel = async () => {
    if (isExporting) return
    setIsExporting(true)
    try {
      const targets =
        departmentId === ALL_DEPARTMENTS_VALUE
          ? departments.map((d) => d.id)
          : [departmentId]

      for (const deptId of targets) {
        const qs = buildCurrentWeekParams(deptId)
        const res = await apiFetch(`/exports/weekly-planner.xlsx?${qs.toString()}`)
        if (!res.ok) {
          toast.error("Failed to export weekly planner")
          return
        }
        const blob = await res.blob()
        const url = URL.createObjectURL(blob)
        const link = document.createElement("a")
        link.href = url
        const filename = parseFilenameFromDisposition(res.headers.get("content-disposition"))
        link.download = filename || "weekly_planner.xlsx"
        document.body.appendChild(link)
        link.click()
        link.remove()
        URL.revokeObjectURL(url)
      }
    } catch (error) {
      console.error("Failed to export weekly planner", error)
      toast.error("Failed to export weekly planner")
    } finally {
      setIsExporting(false)
    }
  }

  const saveWeeklySnapshot = async (mode: "THIS_WEEK_FINAL" | "NEXT_WEEK_PLANNED") => {
    if (!canSaveSnapshots) return
    if (!departmentId || departmentId === ALL_DEPARTMENTS_VALUE) {
      toast.error("Select a specific department before saving snapshots.")
      return
    }
    if (mode === "THIS_WEEK_FINAL" && !canSaveThisWeekFinal) return
    if (mode === "NEXT_WEEK_PLANNED" && !canSaveNextWeekPlanned) return
    if (savingSnapshotMode) return

    setSavingSnapshotMode(mode)
    try {
      const res = await apiFetch("/planners/weekly-snapshots/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          department_id: departmentId,
          mode,
        }),
      })
      if (!res.ok) {
        const message = await res.text().catch(() => "Failed to save snapshot")
        toast.error(message || "Failed to save snapshot")
        return
      }
      const payload = await res.json()
      const weekStart = payload?.snapshot?.week_start_date
      const weekEnd = payload?.snapshot?.week_end_date
      const versionCount = payload?.version_count
      const typeLabel = mode === "THIS_WEEK_FINAL" ? "This Week (Final)" : "Next Week (Planned)"
      if (weekStart && weekEnd) {
        toast.success(
          `Saved ${typeLabel}: ${formatDate(weekStart)} - ${formatDate(weekEnd)} (versions: ${versionCount ?? 1})`
        )
      } else {
        toast.success(`Saved ${typeLabel}`)
      }
    } catch (error) {
      console.error("Failed to save weekly snapshot", error)
      toast.error("Failed to save snapshot")
    } finally {
      setSavingSnapshotMode(null)
    }
  }

  const saveTodayProgress = async (targetDepartmentId = departmentId) => {
    const hasDepartment = Boolean(targetDepartmentId && targetDepartmentId !== ALL_DEPARTMENTS_VALUE)
    if (!data || selectedWeek !== "this" || !hasDepartment || isSavingToday) {
      if (!hasDepartment) {
        toast.error("Select a specific department before saving today.")
      } else if (selectedWeek !== "this") {
        toast.error('Switch Week to "This Week" before saving today.')
      }
      return
    }

    setIsSavingToday(true)
    try {
      const res = await apiFetch("/planners/weekly-table/save-day", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          department_id: targetDepartmentId,
          week_start: data.week_start,
        }),
      })
      if (!res.ok) {
        const message = await res.text().catch(() => "Failed to save today")
        toast.error(message || "Failed to save today")
        return
      }
      const payload = await res.json()
      toast.success(`Saved my week through today (${payload.saved_count ?? 0} task/day rows)`)
      await loadPlanner()
    } catch (error) {
      console.error("Failed to save today", error)
      toast.error("Failed to save today")
    } finally {
      setIsSavingToday(false)
    }
  }

  const openPlanVsActualCompare = async () => {
    if (!data) return
    if (!canCompareLastFridayPlan) {
      toast.error('Switch Week to "This Week" to compare against last Friday plan.')
      return
    }
    if (!departmentId || departmentId === ALL_DEPARTMENTS_VALUE) {
      toast.error("Select a specific department before comparing plan vs actual.")
      return
    }

    setPlanVsActualOpen(true)
    setIsLoadingPlanVsActual(true)
    setPlanVsActualError(null)
    setPlanVsActual(null)
    try {
      const qs = new URLSearchParams()
      qs.set("department_id", departmentId)
      qs.set("week_start", data.week_start)
      const res = await apiFetch(`/planners/weekly-snapshots/plan-vs-actual?${qs.toString()}`)
      if (!res.ok) {
        const message = await res.text().catch(() => "Failed to compare plan vs actual")
        throw new Error(message || "Failed to compare plan vs actual")
      }
      const payload = (await res.json()) as WeeklyPlanPerformanceResponse
      setPlanVsActual(payload)
    } catch (err) {
      setPlanVsActualError(err instanceof Error ? err.message : "Failed to compare plan vs actual")
      setPlanVsActual(null)
    } finally {
      setIsLoadingPlanVsActual(false)
    }
  }

  const exportPlanVsActualExcel = React.useCallback(async () => {
    if (!data || !departmentId || departmentId === ALL_DEPARTMENTS_VALUE) return
    if (isExportingPlanVsActual) return
    setIsExportingPlanVsActual(true)
    try {
      const qs = new URLSearchParams()
      qs.set("department_id", departmentId)
      qs.set("week_start", data.week_start)
      const res = await apiFetch(`/exports/weekly-plan-vs-actual.xlsx?${qs.toString()}`)
      if (!res.ok) {
        const message = await res.text().catch(() => "Failed to export plan vs actual report")
        toast.error(message || "Failed to export plan vs actual report")
        return
      }
      const blob = await res.blob()
      if (blob.size === 0) {
        toast.error("Export returned an empty file.")
        return
      }
      const filename = parseFilenameFromDisposition(res.headers.get("content-disposition"))
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = filename || "plan_vs_actual_report.xlsx"
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error("Failed to export plan vs actual report", err)
      toast.error("Failed to export plan vs actual report")
    } finally {
      setIsExportingPlanVsActual(false)
    }
  }, [apiFetch, data, departmentId, isExportingPlanVsActual])

  const handlePrintPlanVsActual = React.useCallback(() => {
    if (!planVsActual || !data) return

    const printWindow = window.open("", "_blank")
    if (!printWindow) return

    // Get the table from the modal content - find the dialog that contains "Plan vs Actual"
    const dialogs = Array.from(document.querySelectorAll('[role="dialog"]'))
    const planVsActualDialog = dialogs.find((dialog) => {
      const title = dialog.querySelector('h2, [class*="DialogTitle"]')
      return title?.textContent?.includes("Plan vs Actual")
    })
    const table = planVsActualDialog?.querySelector("table")
    const tableHtml = table?.outerHTML || ""

    if (!tableHtml) {
      toast.error("Nothing to print for plan vs actual report.")
      printWindow.close()
      return
    }

    const html = `
      <!DOCTYPE html>
      <html>
        <head>
          <title>Plan vs Actual Report</title>
          <style>
            @media print {
              @page { size: letter landscape; margin: 0.35in; }
            }

            body { font-family: Arial, sans-serif; font-size: 11px; color: #000; }

            table { width: 100%; border-collapse: collapse; table-layout: fixed; }
            th, td { border: 1px solid #000; padding: 6px; vertical-align: top; }
            th { font-weight: 700; }

            a { color: #000; text-decoration: none; }
            td div { margin-bottom: 4px; }
            tr { break-inside: avoid; page-break-inside: avoid; }
          </style>
        </head>
        <body>
          ${tableHtml}
        </body>
      </html>
    `

    printWindow.document.open()
    printWindow.document.write(html)
    printWindow.document.close()
    printWindow.focus()

    setTimeout(() => {
      printWindow.print()
    }, 200)
  }, [planVsActual, data])

  const plannedSnapshotOptions = React.useMemo(() => {
    const options = snapshotCompareVersions
      .filter((version) => version.snapshot_type === "PLANNED")
      .map((version) => {
      const typeLabel = version.snapshot_type === "PLANNED" ? "Planned" : "Final"
      const officialLabel = version.is_official ? " (Official)" : ""
      return {
        id: version.id,
        label: `${typeLabel}${officialLabel} - ${formatDateTimeDMY(version.created_at)}`,
      }
    })
    return options.sort((a, b) => a.label.localeCompare(b.label))
  }, [snapshotCompareVersions])

  const finalSnapshotOptions = React.useMemo(() => {
    const options = snapshotCompareVersions
      .filter((version) => version.snapshot_type === "FINAL")
      .map((version) => {
        const typeLabel = version.snapshot_type === "PLANNED" ? "Planned" : "Final"
        const officialLabel = version.is_official ? " (Official)" : ""
        return {
          id: version.id,
          label: `${typeLabel}${officialLabel} - ${formatDateTimeDMY(version.created_at)}`,
        }
      })
    return options.sort((a, b) => a.label.localeCompare(b.label))
  }, [snapshotCompareVersions])

  const loadSnapshotCompareVersions = React.useCallback(async () => {
    if (!data) return
    if (!departmentId || departmentId === ALL_DEPARTMENTS_VALUE) return

    setSnapshotCompareListLoading(true)
    setSnapshotCompareError(null)
    try {
      const qs = new URLSearchParams()
      qs.set("department_id", departmentId)
      qs.set("week_start", data.week_start)
      const res = await apiFetch(`/planners/weekly-snapshots/compare?${qs.toString()}`)
      if (!res.ok) {
        const message = await res.text().catch(() => "Failed to load snapshot versions")
        throw new Error(message || "Failed to load snapshot versions")
      }
      const payload = (await res.json()) as WeeklySnapshotComparePayload
      const plannedVersions = payload.planned_versions || []
      const finalVersions = payload.final_versions || []
      const versions = [...plannedVersions, ...finalVersions]
      setSnapshotCompareVersions(versions)

      const preferredBaseline =
        plannedVersions.find((v) => v.is_official) ??
        plannedVersions[0]

      const preferredCompare =
        finalVersions[finalVersions.length - 1] ?? null

      const nextBaseline = preferredBaseline?.id ?? ""
      let nextCompare = preferredCompare?.id ?? ""

      if (nextBaseline && nextCompare && nextBaseline === nextCompare) {
        const fallback = finalVersions.find((v) => v.id !== nextBaseline)
        nextCompare = fallback?.id ?? ""
      }

      setBaselineSnapshotId((prev) => (plannedVersions.some((v) => v.id === prev) ? prev : nextBaseline))
      setCompareSnapshotId((prev) => (finalVersions.some((v) => v.id === prev) ? prev : nextCompare))
    } catch (err) {
      setSnapshotCompareError(err instanceof Error ? err.message : "Failed to load snapshot versions")
      setSnapshotCompareVersions([])
      setBaselineSnapshotId("")
      setCompareSnapshotId("")
    } finally {
      setSnapshotCompareListLoading(false)
    }
  }, [apiFetch, data, departmentId])

  const openSnapshotCompare = () => {
    if (!data) return
    if (!departmentId || departmentId === ALL_DEPARTMENTS_VALUE) {
      toast.error("Select a specific department before comparing snapshots.")
      return
    }
    setSnapshotCompareOpen(true)
    setSnapshotCompareError(null)
    setSnapshotCompareData(null)
  }

  const runSnapshotCompare = async () => {
    if (!baselineSnapshotId || !compareSnapshotId) {
      toast.error("Select both snapshots to compare.")
      return
    }
    if (baselineSnapshotId === compareSnapshotId) {
      toast.error("Choose two different snapshots.")
      return
    }
    setSnapshotCompareLoading(true)
    setSnapshotCompareError(null)
    setSnapshotCompareData(null)
    try {
      const qs = new URLSearchParams()
      qs.set("baseline_snapshot_id", baselineSnapshotId)
      qs.set("compare_snapshot_id", compareSnapshotId)
      const path = `/planners/weekly-snapshots/compare/by-id?${qs.toString()}`
      const res = await apiFetch(path)
      if (!res.ok) {
        const message = await res.text().catch(() => "Failed to compare snapshots")
        throw new Error(message || "Failed to compare snapshots")
      }
      const payload = (await res.json()) as WeeklyPlanPerformanceResponse
      setSnapshotCompareData(payload)
    } catch (err) {
      setSnapshotCompareError(err instanceof Error ? err.message : "Failed to compare snapshots")
      setSnapshotCompareData(null)
    } finally {
      setSnapshotCompareLoading(false)
    }
  }

  React.useEffect(() => {
    if (!snapshotCompareOpen) return
    void loadSnapshotCompareVersions()
  }, [loadSnapshotCompareVersions, snapshotCompareOpen])

  const exportSnapshotCompareExcel = React.useCallback(async () => {
    if (!baselineSnapshotId || !compareSnapshotId) {
      toast.error("Select both snapshots to export.")
      return
    }
    if (isExportingSnapshotCompare) return
    setIsExportingSnapshotCompare(true)
    try {
      const qs = new URLSearchParams()
      qs.set("baseline_snapshot_id", baselineSnapshotId)
      qs.set("compare_snapshot_id", compareSnapshotId)
      const res = await apiFetch(`/exports/weekly-snapshot-compare.xlsx?${qs.toString()}`)
      if (!res.ok) {
        const message = await res.text().catch(() => "Failed to export snapshot comparison")
        toast.error(message || "Failed to export snapshot comparison")
        return
      }
      const blob = await res.blob()
      if (blob.size === 0) {
        toast.error("Export returned an empty file.")
        return
      }
      const filename = parseFilenameFromDisposition(res.headers.get("content-disposition"))
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = filename || "snapshot_comparison.xlsx"
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error("Failed to export snapshot comparison", err)
      toast.error("Failed to export snapshot comparison")
    } finally {
      setIsExportingSnapshotCompare(false)
    }
  }, [apiFetch, baselineSnapshotId, compareSnapshotId, isExportingSnapshotCompare])

  const handlePrintSnapshotCompare = React.useCallback(() => {
    if (!snapshotCompareData) return

    const printWindow = window.open("", "_blank")
    if (!printWindow) return

    // Get the table from the modal content - find the dialog that contains "Compare Weekly Snapshots"
    const dialogs = Array.from(document.querySelectorAll('[role="dialog"]'))
    const snapshotDialog = dialogs.find((dialog) => {
      const title = dialog.querySelector('h2, [class*="DialogTitle"]')
      return title?.textContent?.includes("Compare Weekly Snapshots")
    })
    const table = snapshotDialog?.querySelector("table")
    const tableHtml = table?.outerHTML || ""

    if (!tableHtml) {
      toast.error("Nothing to print for snapshot comparison.")
      printWindow.close()
      return
    }

    const html = `
      <!DOCTYPE html>
      <html>
        <head>
          <title>Snapshot Comparison</title>
          <style>
            @media print {
              @page { size: letter landscape; margin: 0.35in; }
            }

            body { font-family: Arial, sans-serif; font-size: 11px; color: #000; }

            table { width: 100%; border-collapse: collapse; table-layout: fixed; }
            th, td { border: 1px solid #000; padding: 6px; vertical-align: top; }
            th { font-weight: 700; }

            a { color: #000; text-decoration: none; }
            td div { margin-bottom: 4px; }
            tr { break-inside: avoid; page-break-inside: avoid; }
          </style>
        </head>
        <body>
          ${tableHtml}
        </body>
      </html>
    `

    printWindow.document.open()
    printWindow.document.write(html)
    printWindow.document.close()
    printWindow.focus()

    setTimeout(() => {
      printWindow.print()
    }, 200)
  }, [snapshotCompareData])

  const formatPlannerStatusLabel = (value?: string | null) => {
    const normalized = (value || "TODO")
      .trim()
      .toUpperCase()
      .replace(/\s+/g, "_")
    if (normalized === "IN_PROGRESS") return "In Progress"
    if (normalized === "WAITING_CLIENT") return "WFE"
    if (normalized === "WAITING_CONFIRMATION") return "Waiting Confirmation"
    if (normalized === "DONE") return "Done"
    return "To Do"
  }

  const renderPlanningTaskCard = (task: Task) => {
    const planned = isTaskPlannedForWeek(task, plannerWeekStart, plannerWeekEnd)
    const note = task.ga_note_origin_id ? planningNoteById.get(task.ga_note_origin_id) : null
    const project = task.project_id ? planningProjectById.get(task.project_id) : null
    const dept = task.department_id ? planningDepartmentById.get(task.department_id) : null
    const source = taskSourceLabel(task)
    const due = taskDateKey(task.due_date)

    return (
      <div key={task.id} className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold uppercase text-slate-700">
                {source}
              </span>
              {task.plan_note_origin_id ? (
                <span className="rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-[10px] font-semibold uppercase text-indigo-700">
                  PX JAV
                </span>
              ) : null}
              {planned ? (
                <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold uppercase text-emerald-700">
                  Planned
                </span>
              ) : (
                <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold uppercase text-amber-700">
                  Unplanned
                </span>
              )}
              <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold uppercase text-slate-600">
                {formatPlannerStatusLabel(task.status)}
              </span>
            </div>
            <div className="mt-1 flex items-start gap-1.5 text-sm font-semibold leading-snug text-slate-900" title={task.title}>
              <TaskOneHMarker marker={task.one_h_marker} markerByGa={task.one_h_marker_by_ga} comment={task.one_h_marker_comment} />
              <span className="min-w-0"><TaskMarkerComment comment={task.one_h_marker_comment} taskId={task.id} /><span className="line-clamp-2">{task.title}</span></span>
            </div>
          </div>
        </div>

        {note?.content ? (
          <div className="mt-2 line-clamp-2 rounded-md border border-blue-100 bg-blue-50 px-2 py-1 text-xs text-blue-900">
            Source note: {note.content}
          </div>
        ) : null}

        <div className="mt-2 grid gap-1 text-xs text-slate-600">
          <div>Assignee: {taskAssigneeLabel(task)}</div>
          <div>Due: {due ? formatDate(due) : "Not scheduled"} {task.finish_period ? `(${task.finish_period})` : ""}</div>
          {dept ? <div>Department: {formatDepartmentName(dept.name)}</div> : null}
          {project ? <div className="truncate">Project: {projectLabel(project)}</div> : null}
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" className="h-7 px-2 text-xs" onClick={() => openPlannerTaskDialog(task, planned ? "edit" : "plan")}>
            {planned ? "Edit" : "Plan next week"}
          </Button>
          {planned ? (
            <Button
              size="sm"
              variant="outline"
              className="h-7 px-2 text-xs"
              disabled={plannerTaskClearingId === task.id}
              onClick={() => void clearTaskFromNextWeek(task)}
            >
              {plannerTaskClearingId === task.id ? "Removing..." : "Remove from plan"}
            </Button>
          ) : null}
          {task.ga_note_origin_id || task.plan_note_origin_id ? (
            <Button asChild size="sm" variant="outline" className="h-7 px-2 text-xs">
              <Link href={task.plan_note_origin_id ? "/next-week-plan" : `/ga-ka-notes${task.department_id ? `?department_id=${task.department_id}` : ""}`}>
                Open source note
              </Link>
            </Button>
          ) : null}
        </div>
      </div>
    )
  }

  const renderPlanningSection = (title: string, subtitle: string, tasks: Task[]) => (
    <div className="space-y-2">
      <div>
        <div className="text-sm font-semibold text-slate-900">{title} ({tasks.length})</div>
        <div className="text-xs text-slate-500">{subtitle}</div>
      </div>
      {tasks.length ? (
        <div className="space-y-2">{tasks.map(renderPlanningTaskCard)}</div>
      ) : (
        <div className="rounded-md border border-dashed border-slate-200 px-3 py-4 text-xs text-slate-500">
          No tasks in this group.
        </div>
      )}
    </div>
  )

  return (
    <div className="space-y-4">
      <style dangerouslySetInnerHTML={{
        __html: `
        @media print {
          button[title="Delete task"] {
            display: none !important;
          }
        }
      `}} />
      <div className="flex items-center justify-between">
        <div className="text-lg font-semibold">Weekly Planner</div>
        {viewMode === "current" && data && (
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={() => setManualTaskOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Add Task
            </Button>
            <Button
              variant="outline"
              onClick={() => void saveTodayProgress()}
              disabled={isSavingToday || !canSaveToday}
            >
              {isSavingToday ? "Saving my week so far..." : "Save My Week So Far"}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" className="gap-2">
                  Actions
                  <ChevronDown className="h-4 w-4 opacity-60" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <DropdownMenuLabel>Daily Progress</DropdownMenuLabel>
                <DropdownMenuItem
                  onSelect={() => void saveTodayProgress()}
                  disabled={isSavingToday || !canSaveToday}
                >
                  {isSavingToday
                    ? "Saving my week so far..."
                    : canSaveToday
                      ? "Save My Week So Far"
                      : 'Save My Week So Far [This Week + Department]'}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                {canSaveSnapshots ? (
                  <>
                    <DropdownMenuLabel>Snapshots</DropdownMenuLabel>
                    <DropdownMenuItem
                      onSelect={() => void saveWeeklySnapshot("THIS_WEEK_FINAL")}
                      disabled={savingSnapshotMode !== null || !canSaveThisWeekFinal}
                    >
                      {savingSnapshotMode === "THIS_WEEK_FINAL"
                        ? "Saving..."
                        : canSaveThisWeekFinal
                          ? "Save This Week (Final)"
                          : 'Save This Week (Final) [Switch to This Week]'}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onSelect={() => void saveWeeklySnapshot("NEXT_WEEK_PLANNED")}
                      disabled={savingSnapshotMode !== null || !canSaveNextWeekPlanned}
                    >
                      {savingSnapshotMode === "NEXT_WEEK_PLANNED"
                        ? "Saving..."
                        : canSaveNextWeekPlanned
                          ? "Save Next Week (Planned)"
                          : 'Save Next Week (Planned) [Switch to Next Week]'}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                  </>
                ) : null}
                <>
                  <DropdownMenuLabel>Compare</DropdownMenuLabel>
                  <DropdownMenuItem onSelect={openSnapshotCompare}>
                    Compare Snapshots...
                  </DropdownMenuItem>
                  {canCompareLastFridayPlan ? (
                    <DropdownMenuItem
                      onSelect={() => void openPlanVsActualCompare()}
                      disabled={isLoadingPlanVsActual}
                    >
                      {isLoadingPlanVsActual ? "Comparing..." : "Compare with Last Friday Plan"}
                    </DropdownMenuItem>
                  ) : null}
                  <DropdownMenuSeparator />
                </>
                {canEditUserOrder ? (
                  <>
                    <DropdownMenuLabel>Ordering</DropdownMenuLabel>
                    <DropdownMenuItem onSelect={() => setIsOrderingUsers((prev) => !prev)}>
                      {isOrderingUsers ? "Finish Ordering" : "Edit User Order"}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onSelect={() => void saveUserOrder()}
                      disabled={!orderDirtyByDept[departmentId] || isSavingUserOrder}
                    >
                      {isSavingUserOrder ? "Saving..." : "Save Order"}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                  </>
                ) : null}
                {canManageUserVisibility ? (
                  <>
                    <DropdownMenuLabel>User Visibility</DropdownMenuLabel>
                    <DropdownMenuSub>
                      <DropdownMenuSubTrigger>Hide user</DropdownMenuSubTrigger>
                      <DropdownMenuSubContent className="max-h-80 min-w-56 overflow-y-auto">
                        {visiblePlannerUsers.length ? (
                          visiblePlannerUsers.map((entry) => (
                            <DropdownMenuItem
                              key={`hide-${entry.id}`}
                              onSelect={() => void toggleWeeklyPlannerUserVisibility(entry, true)}
                              disabled={savingUserVisibilityId === entry.id}
                            >
                              {savingUserVisibilityId === entry.id
                                ? "Saving..."
                                : entry.full_name || entry.username || "User"}
                            </DropdownMenuItem>
                          ))
                        ) : (
                          <DropdownMenuItem disabled>No visible users</DropdownMenuItem>
                        )}
                      </DropdownMenuSubContent>
                    </DropdownMenuSub>
                    <DropdownMenuSub>
                      <DropdownMenuSubTrigger>Unhide user</DropdownMenuSubTrigger>
                      <DropdownMenuSubContent className="max-h-80 min-w-56 overflow-y-auto">
                        {hiddenPlannerUsers.length ? (
                          hiddenPlannerUsers.map((entry) => (
                            <DropdownMenuItem
                              key={`show-${entry.id}`}
                              onSelect={() => void toggleWeeklyPlannerUserVisibility(entry, false)}
                              disabled={savingUserVisibilityId === entry.id}
                            >
                              {savingUserVisibilityId === entry.id
                                ? "Saving..."
                                : entry.full_name || entry.username || "User"}
                            </DropdownMenuItem>
                          ))
                        ) : (
                          <DropdownMenuItem disabled>No hidden users</DropdownMenuItem>
                        )}
                      </DropdownMenuSubContent>
                    </DropdownMenuSub>
                    <DropdownMenuSeparator />
                  </>
                ) : null}
                <DropdownMenuLabel>Export & Print</DropdownMenuLabel>
                <DropdownMenuItem onSelect={exportWeeklyPlannerExcel} disabled={isExporting}>
                  {isExporting ? "Exporting..." : "Export Excel"}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={handlePrint} disabled={!data}>
                  Print
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        <div className="space-y-2">
          <Label>View</Label>
          <Select value={viewMode} onValueChange={(value) => setViewMode(value as "current" | "snapshots")}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="current">Current Weekly Plan</SelectItem>
              <SelectItem value="snapshots">Saved Weekly Snapshots</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {viewMode === "current" ? (
        <div className="space-y-2">
          <Label>Week</Label>
          <Select value={selectedWeek} onValueChange={(value) => handleSelectedWeekChange(value as SelectedWeek)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="last">Last Week</SelectItem>
              <SelectItem value="this">This Week</SelectItem>
              <SelectItem value="next">Next Week</SelectItem>
            </SelectContent>
          </Select>
        </div>
        ) : null}
        {user?.role !== "STAFF" ? (
          <div className="space-y-2">
            <Label>Department</Label>
            <Select value={departmentId} onValueChange={handleDepartmentChange}>
              <SelectTrigger>
                <SelectValue placeholder="Department" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_DEPARTMENTS_VALUE}>All Departments</SelectItem>
                {departments.map((d) => (
                  <SelectItem key={d.id} value={d.id}>
                    {formatDepartmentName(d.name)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}
        {viewMode === "current" && data ? (
          <div className="space-y-2">
            <Label>Week Range</Label>
            <div className="text-sm text-muted-foreground pt-2">
              {formatDate(data.week_start)} - {formatDate(data.week_end)}
            </div>
          </div>
        ) : null}
      </div>

      <Dialog
        open={taskTitleDialogOpen}
        onOpenChange={(open) => {
          setTaskTitleDialogOpen(open)
          if (!open) {
            setTaskTitleDialogContent(null)
          }
        }}
      >
        <DialogContent className="sm:max-w-2xl z-[120]">
          <DialogHeader>
            <DialogTitle>Full task title</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="max-h-[60vh] overflow-y-auto whitespace-pre-wrap break-words rounded-lg border border-slate-200 bg-slate-50 p-4 text-base font-semibold leading-relaxed text-slate-800">
              {renderMarkedNoteContent(taskTitleDialogContent, "Untitled task")}
            </div>
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => setTaskTitleDialogOpen(false)}
                className="rounded-xl"
              >
                Close
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={manualTaskOpen} onOpenChange={setManualTaskOpen}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>Add Task to Weekly Planner</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {departmentId === ALL_DEPARTMENTS_VALUE ? (
              <div className="space-y-2">
                <Label>Department</Label>
                <Select value={manualTaskDepartmentId} onValueChange={setManualTaskDepartmentId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select department" />
                  </SelectTrigger>
                  <SelectContent>
                    {availableDepartments.map((dept) => (
                      <SelectItem key={dept.id} value={dept.id}>
                        {formatDepartmentName(dept.name)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : null}

            <div className="space-y-2">
              <Label>Task Type</Label>
              <Select value={manualTaskType} onValueChange={(v) => {
                setManualTaskType(v as "project" | "fast")
                // Reset fields when switching type
                setManualTaskDays([])
                setManualTaskUserIds([])
                setManualTaskFastType("")
                setManualTaskProjectId("")
              }}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="fast">Fast Task</SelectItem>
                  <SelectItem value="project">Project</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Task title</Label>
              <Input
                value={manualTaskTitle}
                onChange={(e) => setManualTaskTitle(e.target.value)}
                placeholder="Write the task..."
              />
            </div>

            {manualTaskType === "fast" ? (
              <>
                <div className="space-y-2">
                  <Label>Task Type</Label>
                  <Select value={manualTaskFastType} onValueChange={setManualTaskFastType}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select task type" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="BLL">BLL</SelectItem>
                      <SelectItem value="R1">R1</SelectItem>
                      <SelectItem value="1H">1H</SelectItem>
                      <SelectItem value="P:">P:</SelectItem>
                      <SelectItem value="N">N</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label>AM / PM</Label>
                    <Select value={manualTaskPeriod} onValueChange={(v) => setManualTaskPeriod(v as "AM" | "PM")}>
                      <SelectTrigger>
                        <SelectValue placeholder="AM/PM" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="AM">AM</SelectItem>
                        <SelectItem value="PM">PM</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <label className="flex items-center gap-3 rounded-md border px-3 py-2">
                  <Checkbox
                    checked={manualTaskDeadlineImportant}
                    onCheckedChange={(checked) => setManualTaskDeadlineImportant(checked === true)}
                  />
                  <span className="text-sm font-medium">Deadline important</span>
                </label>
                <div className="space-y-2">
                  <Label>Days (Select multiple)</Label>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="outline" className="w-full justify-between">
                        {manualTaskDays.length > 0 ? `Days (${manualTaskDays.length})` : "Select days"}
                        <ChevronDown className="h-4 w-4 opacity-50" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="w-56 max-h-64 z-[120]">
                      <DropdownMenuLabel>Days</DropdownMenuLabel>
                      <DropdownMenuSeparator />
                      {availableDays.map((day) => (
                        <DropdownMenuCheckboxItem
                          key={day.value}
                          checked={manualTaskDays.includes(day.value)}
                          onCheckedChange={(checked) => {
                            if (checked) {
                              setManualTaskDays([...manualTaskDays, day.value])
                            } else {
                              setManualTaskDays(manualTaskDays.filter(d => d !== day.value))
                            }
                          }}
                        >
                          {day.label}
                        </DropdownMenuCheckboxItem>
                      ))}
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        onSelect={(event) => {
                          event.preventDefault()
                          setManualTaskDays([])
                        }}
                      >
                        Clear days
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
                <div className="space-y-2">
                  <Label>Members (Select multiple)</Label>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="outline" className="w-full justify-between">
                        {manualTaskUserIds.length > 0 ? `Members (${manualTaskUserIds.length})` : "Select members"}
                        <ChevronDown className="h-4 w-4 opacity-50" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="w-64 max-h-64 z-[120]">
                      <DropdownMenuLabel>Members</DropdownMenuLabel>
                      <DropdownMenuSeparator />
                      {availableUsers.map((entry) => (
                        <DropdownMenuCheckboxItem
                          key={entry.id}
                          checked={manualTaskUserIds.includes(entry.id)}
                          onCheckedChange={(checked) => {
                            if (checked) {
                              setManualTaskUserIds([...manualTaskUserIds, entry.id])
                            } else {
                              setManualTaskUserIds(manualTaskUserIds.filter(id => id !== entry.id))
                            }
                          }}
                        >
                          {entry.name}
                        </DropdownMenuCheckboxItem>
                      ))}
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        onSelect={(event) => {
                          event.preventDefault()
                          setManualTaskUserIds([])
                        }}
                      >
                        Clear members
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </>
            ) : (
              <>
                <div className="space-y-2">
                  <Label>Project</Label>
                  <Select
                    value={manualTaskProjectId}
                    onValueChange={setManualTaskProjectId}
                    disabled={!manualTaskDepartmentValue}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder={manualTaskDepartmentValue ? "Select project" : "Select department first"} />
                    </SelectTrigger>
                    <SelectContent>
                      {availableProjects.length === 0 ? (
                        <SelectItem value="__none__" disabled>
                          No active projects
                        </SelectItem>
                      ) : (
                        availableProjects.map((project) => (
                          <SelectItem key={project.id} value={project.id}>
                            {projectLabel(project)}
                          </SelectItem>
                        ))
                      )}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Days (Select multiple)</Label>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="outline" className="w-full justify-between">
                        {manualTaskDays.length > 0 ? `Days (${manualTaskDays.length})` : "Select days"}
                        <ChevronDown className="h-4 w-4 opacity-50" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="w-56 max-h-64 z-[120]">
                      <DropdownMenuLabel>Days</DropdownMenuLabel>
                      <DropdownMenuSeparator />
                      {availableDays.map((day) => (
                        <DropdownMenuCheckboxItem
                          key={day.value}
                          checked={manualTaskDays.includes(day.value)}
                          onCheckedChange={(checked) => {
                            if (checked) {
                              setManualTaskDays([...manualTaskDays, day.value])
                            } else {
                              setManualTaskDays(manualTaskDays.filter(d => d !== day.value))
                            }
                          }}
                        >
                          {day.label}
                        </DropdownMenuCheckboxItem>
                      ))}
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        onSelect={(event) => {
                          event.preventDefault()
                          setManualTaskDays([])
                        }}
                      >
                        Clear days
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
                <div className="space-y-2">
                  <Label>AM / PM</Label>
                  <Select value={manualTaskPeriod} onValueChange={(v) => setManualTaskPeriod(v as "AM" | "PM")}>
                    <SelectTrigger>
                      <SelectValue placeholder="AM/PM" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="AM">AM</SelectItem>
                      <SelectItem value="PM">PM</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <label className="flex items-center gap-3 rounded-md border px-3 py-2">
                  <Checkbox
                    checked={manualTaskDeadlineImportant}
                    onCheckedChange={(checked) => setManualTaskDeadlineImportant(checked === true)}
                  />
                  <span className="text-sm font-medium">Deadline important</span>
                </label>
                <div className="space-y-2">
                  <Label>Members (Select multiple)</Label>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="outline" className="w-full justify-between">
                        {manualTaskUserIds.length > 0 ? `Members (${manualTaskUserIds.length})` : "Select members"}
                        <ChevronDown className="h-4 w-4 opacity-50" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="w-64 max-h-64 z-[120]">
                      <DropdownMenuLabel>Members</DropdownMenuLabel>
                      <DropdownMenuSeparator />
                      {availableUsers.map((entry) => (
                        <DropdownMenuCheckboxItem
                          key={entry.id}
                          checked={manualTaskUserIds.includes(entry.id)}
                          onCheckedChange={(checked) => {
                            if (checked) {
                              setManualTaskUserIds([...manualTaskUserIds, entry.id])
                            } else {
                              setManualTaskUserIds(manualTaskUserIds.filter(id => id !== entry.id))
                            }
                          }}
                        >
                          {entry.name}
                        </DropdownMenuCheckboxItem>
                      ))}
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        onSelect={(event) => {
                          event.preventDefault()
                          setManualTaskUserIds([])
                        }}
                      >
                        Clear members
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </>
            )}

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setManualTaskOpen(false)}>
                Cancel
              </Button>
              <Button onClick={handleCreateManualTask} disabled={isCreatingManualTask}>
                {isCreatingManualTask ? "Adding..." : "Add Task"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={plannerTaskDialogOpen}
        onOpenChange={(open) => {
          setPlannerTaskDialogOpen(open)
          if (!open) setPlannerTask(null)
        }}
      >
        <DialogContent className="sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle>{plannerTaskDialogMode === "plan" ? "Plan Task" : "Edit Task Plan"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            {plannerTask ? (
              <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
                <div className="line-clamp-2 text-sm font-semibold text-slate-900">{plannerTask.title}</div>
              </div>
            ) : null}
            {plannerTask?.ga_note_origin_id || plannerTask?.plan_note_origin_id ? (
              <div className="rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800">
                {plannerTask.plan_note_origin_id
                  ? "You are planning this person’s independent PX JAV task copy. Assignees are fixed from creation."
                  : "You are planning this person’s independent GA task copy. Membership is managed in GA Notes."}
              </div>
            ) : null}

            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Start date</Label>
                <Input
                  type="date"
                  value={plannerTaskStartDate}
                  onChange={(event) => setPlannerTaskStartDate(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label>Due date</Label>
                <Input
                  type="date"
                  value={plannerTaskDueDate}
                  onChange={(event) => setPlannerTaskDueDate(event.target.value)}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label>AM / PM</Label>
              <Select
                value={plannerTaskFinishPeriod}
                onValueChange={(value) => setPlannerTaskFinishPeriod(value as "AM" | "PM" | "__none__")}
              >
                <SelectTrigger>
                  <SelectValue placeholder="AM/PM" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="AM">AM</SelectItem>
                  <SelectItem value="PM">PM</SelectItem>
                  <SelectItem value="__none__">Both</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {!(plannerTask?.ga_note_origin_id || plannerTask?.plan_note_origin_id) ? <div className="space-y-2">
              <Label>Members</Label>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" className="w-full justify-between">
                    {plannerTaskAssigneeIds.length > 0 ? `Members (${plannerTaskAssigneeIds.length})` : "Select members"}
                    <ChevronDown className="h-4 w-4 opacity-50" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent className="w-64 max-h-64 z-[120]">
                  <DropdownMenuLabel>Members</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {plannerTaskUsers.map((entry) => (
                    <DropdownMenuCheckboxItem
                      key={entry.id}
                      checked={plannerTaskAssigneeIds.includes(entry.id)}
                      onCheckedChange={(checked) => {
                        if (checked) {
                          setPlannerTaskAssigneeIds([...plannerTaskAssigneeIds, entry.id])
                        } else {
                          setPlannerTaskAssigneeIds(plannerTaskAssigneeIds.filter((id) => id !== entry.id))
                        }
                      }}
                    >
                      {entry.name}
                    </DropdownMenuCheckboxItem>
                  ))}
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    onSelect={(event) => {
                      event.preventDefault()
                      setPlannerTaskAssigneeIds([])
                    }}
                  >
                    Clear members
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div> : null}

            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => {
                  setPlannerTaskDialogOpen(false)
                  setPlannerTask(null)
                }}
              >
                Cancel
              </Button>
              <Button onClick={() => void savePlannerTask()} disabled={plannerTaskSaving}>
                {plannerTaskSaving ? "Saving..." : "Save"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={planVsActualOpen} onOpenChange={setPlanVsActualOpen}>
        <DialogContent className="sm:max-w-[1000px] max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Plan vs Actual Weekly Comparison</DialogTitle>
          </DialogHeader>
          <div className="flex justify-end gap-2 mb-4 pb-2 border-b">
            <Button
              variant="outline"
              size="sm"
              onClick={() => void exportPlanVsActualExcel()}
              disabled={!planVsActual || isExportingPlanVsActual || !data || departmentId === ALL_DEPARTMENTS_VALUE}
            >
              <Download className="mr-2 h-4 w-4" />
              {isExportingPlanVsActual ? "Exporting..." : "Export Excel"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handlePrintPlanVsActual}
              disabled={!planVsActual}
            >
              <Printer className="mr-2 h-4 w-4" />
              Print
            </Button>
          </div>
          <div className="space-y-4">
            {isLoadingPlanVsActual ? (
              <div className="text-sm text-muted-foreground">Comparing plan vs actual...</div>
            ) : null}
            {planVsActualError ? (
              <div className="text-sm text-destructive">{planVsActualError}</div>
            ) : null}
            {(() => {
              if (!planVsActual) return null
              const dept = data?.departments?.find((d) => d.department_id === departmentId)
              const userMap = new Map<string, string>()
              dept?.days?.forEach((day) => {
                day.users?.forEach((u) => {
                  if (!userMap.has(u.user_id)) userMap.set(u.user_id, u.user_name)
                })
              })
              const columns = Array.from(userMap.entries()).map(([user_id, user_name]) => ({
                assignee_id: user_id,
                assignee_name: user_name,
              }))
              return <WeeklyPlanPerformanceView data={planVsActual} assigneeColumns={columns} />
            })()}
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={snapshotCompareOpen} onOpenChange={setSnapshotCompareOpen}>
        <DialogContent className="sm:max-w-[1000px] max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Compare Weekly Snapshots</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid gap-3 md:grid-cols-2">
              <div className="space-y-2">
                <Label>Planned snapshot</Label>
                <Select
                  value={baselineSnapshotId}
                  onValueChange={setBaselineSnapshotId}
                  disabled={snapshotCompareListLoading || plannedSnapshotOptions.length === 0}
                >
                  <SelectTrigger>
                    <SelectValue
                      placeholder={snapshotCompareListLoading ? "Loading snapshots..." : "Select planned snapshot"}
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {plannedSnapshotOptions.map((option) => (
                      <SelectItem key={option.id} value={option.id}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label>Final snapshot</Label>
                <Select
                  value={compareSnapshotId}
                  onValueChange={setCompareSnapshotId}
                  disabled={snapshotCompareListLoading || finalSnapshotOptions.length === 0}
                >
                  <SelectTrigger>
                    <SelectValue
                      placeholder={snapshotCompareListLoading ? "Loading snapshots..." : "Select final snapshot"}
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {finalSnapshotOptions.map((option) => (
                      <SelectItem key={option.id} value={option.id}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {snapshotCompareListLoading ? (
              <div className="text-sm text-muted-foreground">Loading snapshot versions...</div>
            ) : null}
            {!snapshotCompareListLoading && plannedSnapshotOptions.length === 0 ? (
              <div className="text-sm text-muted-foreground">No planned snapshots saved for this week.</div>
            ) : null}
            {!snapshotCompareListLoading && finalSnapshotOptions.length === 0 ? (
              <div className="text-sm text-muted-foreground">No final snapshots saved for this week.</div>
            ) : null}
            {snapshotCompareError ? (
              <div className="text-sm text-destructive">{snapshotCompareError}</div>
            ) : null}

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setSnapshotCompareOpen(false)}>
                Close
              </Button>
              <Button
                onClick={() => void runSnapshotCompare()}
                disabled={
                  snapshotCompareLoading ||
                  snapshotCompareListLoading ||
                  !baselineSnapshotId ||
                  !compareSnapshotId
                }
              >
                {snapshotCompareLoading ? "Comparing..." : "Compare"}
              </Button>
            </div>

            {snapshotCompareData ? (
              <>
                <div className="flex justify-end gap-2 mb-4 pb-2 border-b">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void exportSnapshotCompareExcel()}
                    disabled={!baselineSnapshotId || !compareSnapshotId || isExportingSnapshotCompare}
                  >
                    <Download className="mr-2 h-4 w-4" />
                    {isExportingSnapshotCompare ? "Exporting..." : "Export Excel"}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handlePrintSnapshotCompare}
                    disabled={!snapshotCompareData}
                  >
                    <Printer className="mr-2 h-4 w-4" />
                    Print
                  </Button>
                </div>
                <WeeklyPlanPerformanceView data={snapshotCompareData} />
              </>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>

      {viewMode === "snapshots" ? (
        <WeeklyPlannerSnapshotsView
          departmentId={departmentId}
          allDepartmentsValue={ALL_DEPARTMENTS_VALUE}
        />
      ) : error ? (
        <div className="text-center py-8 text-destructive">
          <p>{error}</p>
        </div>
      ) : isLoading ? (
        <div className="text-sm text-muted-foreground">Loading planner…</div>
      ) : data ? (
        data.departments.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            <p>No departments or tasks found for this week.</p>
            <p className="text-sm mt-2">Try selecting a different week or department.</p>
          </div>
        ) : (
          <div className="space-y-6">
            {/* Show Legend Table only for Development, Graphic Design, or Product Content */}
            {(() => {
              if (departmentId === ALL_DEPARTMENTS_VALUE) return null

              const selectedDept = departments.find((d) => d.id === departmentId)
              const selectedKey = normalizeDepartmentKey(selectedDept?.name)
              const isLegendDepartment =
                selectedKey === "development" ||
                selectedKey === "graphicdesign" ||
                selectedKey === "productcontent"
              if (!isLegendDepartment) return null

              const legendDept = data.departments.find(
                (d) => normalizeDepartmentKey(d.department_name) === selectedKey
              )

              if (legendDept && data.week_start) {
                return (
                  <WeeklyPlannerLegendTable
                    departmentId={departmentId}
                    weekStart={data.week_start}
                    departmentName={selectedDept?.name}
                  />
                )
              }
              return null
            })()}
            {data.departments.map((dept) => (
              <Card key={dept.department_id}>
                <CardHeader className="flex flex-row items-center justify-between gap-3">
                  <CardTitle>{formatDepartmentName(dept.department_name)}</CardTitle>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => void saveTodayProgress(dept.department_id)}
                    disabled={isSavingToday || !canSaveDepartmentToday}
                  >
                    {isSavingToday ? "Saving..." : "Save My Week So Far"}
                  </Button>
                </CardHeader>
                <CardContent>
                  {(() => {
                    const orderedUsers = getOrderedUsersForDept(dept)
                    const orderedUserIds = orderedUsers.map((u) => u.user_id)
                    const repeatedTaskFirstDateByUserId = new Map(
                      orderedUsers.map((entry) => [
                        entry.user_id,
                        buildWeeklyPlannerRepeatedTaskFirstDateMap(dept, entry.user_id),
                      ])
                    )
                    const isOrderingActive = canEditUserOrder && isOrderingUsers

                    return (
                      <DndContext
                        sensors={sensors}
                        onDragEnd={(event) => handleUserOrderDragEnd(dept.department_id, event)}
                      >
                        <Table
                          className="table-fixed w-full"
                          containerProps={{
                            ref: setScrollRef(dept.department_id),
                            className: "max-h-[75vh] overflow-x-auto overflow-y-auto cursor-grab",
                            onPointerDown: (e) => handlePointerDown(e, dept.department_id),
                            onWheel: (e) => handleWheel(e, dept.department_id),
                            style: {
                              scrollbarWidth: "thin",
                              scrollbarColor: "#94a3b8 #e2e8f0",
                              touchAction: "pan-y",
                            },
                          }}
                        >
                          <TableHeader>
                            <TableRow>
                              <TableHead className="w-24 min-w-24 sticky top-0 left-0 bg-background z-30 text-xs font-bold uppercase" rowSpan={2}>Day</TableHead>
                              <TableHead className="w-10 min-w-10 sticky top-0 left-24 bg-background z-30 text-center text-xs font-bold uppercase">Time</TableHead>
                              <TableHead className="w-10 min-w-10 sticky top-0 left-34 bg-background z-30 text-center text-xs font-bold uppercase">LL</TableHead>
                              <SortableContext items={orderedUserIds} strategy={horizontalListSortingStrategy}>
                                {orderedUsers.map((user) => (
                                  <TableHead key={user.user_id} className="w-56 min-w-56 sticky top-0 bg-background z-20 text-center text-xs font-bold uppercase">
                                    <SortableUserHeader user={user} isOrdering={isOrderingActive} />
                                  </TableHead>
                                ))}
                              </SortableContext>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                      {dept.days.map((day, dayIndex) => {
                        const allUsers = orderedUsers

                          const renderCellContent = (
                            projects: WeeklyTableProjectEntry[],
                            systemTasks: WeeklyTableTaskEntry[],
                            fastTasks: WeeklyTableTaskEntry[],
                            timeSlot: "am" | "pm",
                            dayDate: string,
                            userId: string
                          ) => {
                            // Ensure arrays are defined
                            const projectsList = (projects || []).filter(hasVisibleProjectTasks)
                            const systemTasksList = systemTasks || []
                            const fastTasksList = sortFastTasks(fastTasks || [])
                            const repeatedTaskFirstDateById = repeatedTaskFirstDateByUserId.get(userId)
                            const isRepeatedTaskForDay = (task: { task_id?: string | null }) => Boolean(
                              repeatedTaskFirstDateById &&
                              isRepeatedTaskInstance(task, dayDate, repeatedTaskFirstDateById)
                            )
                            const repeatedTaskCardClassName = (task: { task_id?: string | null }) =>
                              isRepeatedTaskForDay(task)
                                ? "[&_.weekly-task-title]:!text-[#9ca3af] [&_span]:!text-[#9ca3af]"
                                : ""

                            const hasContent = projectsList.length > 0 || systemTasksList.length > 0 || fastTasksList.length > 0
                            const block = getBlockForSlot(userId, dayDate, timeSlot)
                            const isBlocked = Boolean(block)
                            const blockTitle = isBlocked
                              ? `PV/FEST${block?.note ? `: ${block.note}` : ""}`
                              : undefined

                            if (!hasContent && !isBlocked) {
                              return <div className="min-h-20 text-xs text-muted-foreground/50">--</div>
                            }

                            if (isBlocked) {
                              return (
                                <div
                                  className="min-h-20 relative rounded-md border border-slate-300 bg-slate-100/70 text-slate-600 cursor-not-allowed"
                                  title={blockTitle}
                                >
                                  <div className="absolute inset-0 bg-slate-200/50 pointer-events-none" />
                                  <div className="absolute top-1 right-1 z-10 text-[10px] font-semibold uppercase tracking-wide text-slate-600 bg-slate-200/90 px-1.5 py-0.5 rounded">
                                    PV/FEST
                                  </div>
                                  <div className="relative z-0 px-2 py-1 text-xs font-semibold text-slate-600">
                                    {block?.note ?? null}
                                  </div>
                                </div>
                              )
                            }

                            return (
                              <div className="min-h-20">
                                {!hasContent ? (
                                  <div className="min-h-20 text-xs text-muted-foreground/50">--</div>
                                ) : (
                                  <div className="space-y-2 min-h-20">
                                      {/* Projects */}
                                {projectsList.map((project, projectIndex) => {
                                  // Debug: log if project should be late
                                  if (project.project_title.includes("LATE") || project.project_title.includes("PRJK")) {
                                    console.log("Project:", project.project_title, "is_late:", project.is_late, "project_id:", project.project_id)
                                  }
                                  return (
                                    <div
                                      key={project.project_id}
                                      className={[
                                        "group p-1.5 rounded-md transition-colors",
                                        project.is_late
                                          ? "bg-red-50 dark:bg-red-950/20 border-2 border-red-500 hover:bg-red-100 dark:hover:bg-red-950/30"
                                          : "bg-primary/5 border border-primary/20 hover:bg-primary/10",
                                      ].join(" ")}
                                    >
                                        <div className="font-semibold text-sm text-slate-900 flex items-start justify-between gap-2">
                                          <div className="flex items-center gap-2 min-w-0">
                                            <span className="truncate whitespace-nowrap">{projectIndex + 1}. {getProjectDisplayTitle(project)}</span>
                                          {project.is_late && (
                                            <span className="inline-flex h-5 items-center justify-center rounded-full bg-red-500 text-white px-2 text-[10px] font-semibold">
                                              LATE
                                            </span>
                                          )}
                                        </div>
                                        {canDeleteProjects && (
                                          <button
                                            type="button"
                                            onClick={(e) => {
                                              e.stopPropagation()
                                              void deleteProject(project.project_id, project.project_title, timeSlot, dayDate, userId)
                                            }}
                                            disabled={deletingProjectId === project.project_id}
                                            className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-red-100 dark:hover:bg-red-900/30 text-red-500 transition-opacity"
                                            title="Delete project"
                                          >
                                            <X className="h-3 w-3" />
                                          </button>
                                        )}
                                      </div>
                                        {project.tasks && project.tasks.length > 0 && (
                                          <div className="mt-1 space-y-0.5">
                                          {project.tasks.map((task, taskIndex) => {
                                              const statusBadge = getTaskStatusBadge({ ...task, day_date: dayDate })
                                              const isNewTask = isTaskNewForWeek(task.created_at, data?.week_start)
                                              const taskNumber = `${projectIndex + 1}.${taskIndex + 1}`
                                              const displayTitle = getPlannerTaskDisplayTitle(task)
                                              const fullTitle = getPlannerTaskFullTitle(task)
                                              const taskStatusValue = getStatusValueForDay(task.status, task.completed_at, dayDate, task.daily_status)
                                              const titleColorClass = task.is_deadline_important && taskStatusValue !== "DONE" ? "text-white" : "text-slate-900"
                                              return (
                                                <div
                                                  key={task.task_id}
                                                className={[
                                                  "text-[11px] flex items-center gap-1 rounded border pl-1.5 pr-0.5 py-0.5 group/task",
                                                  getTaskCardClassesForDay(task.status, task.completed_at, dayDate, task.daily_status, task.created_at, task.is_deadline_important),
                                                  repeatedTaskCardClassName(task),
                                                ].join(" ")}
                                              >
                                                  <TaskOneHMarker
                                                    marker={task.one_h_marker}
                                                    markerByGa={task.one_h_marker_by_ga}
                                                    comment={task.one_h_marker_comment}
                                                    className="h-4 min-h-4 min-w-4 rounded px-0.5 text-[10px] !text-red-600"
                                                  />
                                                  <span className="min-w-0 flex-1">
                                                    <TaskMarkerComment comment={task.one_h_marker_comment} />
                                                    <button
                                                    type="button"
                                                    onClick={() => openTaskTitle(fullTitle)}
                                                    className={[
                                                      "block w-full min-w-0 truncate whitespace-nowrap font-semibold text-left hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 rounded",
                                                      "weekly-task-title",
                                                      titleColorClass,
                                                    ].join(" ")}
                                                    title={`${taskNumber}. ${displayTitle}`}
                                                  >
                                                    {taskNumber}. {displayTitle}
                                                    </button>
                                                  </span>
                                                <div className="flex shrink-0 items-center gap-1">
                                                  {isNewTask && (
                                                    <span className="inline-flex h-4 items-center justify-center rounded-full border border-blue-300 bg-blue-100 px-1 text-[9px] font-semibold tracking-tight text-blue-700">
                                                      NEW
                                                    </span>
                                                  )}
                                                  {statusBadge && (
                                                    <span
                                                      className={[
                                                        "inline-flex h-5 min-w-[1.5rem] items-center justify-center rounded-full border px-1 text-[10px] font-semibold",
                                                        statusBadge.className,
                                                      ].join(" ")}
                                                      title={statusBadge.label}
                                                    >
                                                      {statusBadge.label}
                                                    </span>
                                                  )}
                                                  {(() => {
                                                    const productLabel = formatTaskProducts(task, project, dept.department_name)
                                                    if (!productLabel) return null
                                                    return (
                                                      <span className="font-medium bg-primary/10 text-primary px-1.5 py-0.5 rounded text-[10px]">
                                                        {productLabel}
                                                      </span>
                                                    )
                                                  })()}
                                                  <button
                                                    type="button"
                                                    onClick={(e) => {
                                                      e.stopPropagation()
                                                      void deleteTask(task.task_id, displayTitle, timeSlot, dayDate, userId)
                                                    }}
                                                    disabled={deletingTaskId === task.task_id}
                                                    className="opacity-0 group-hover/task:opacity-100 inline-flex h-3 w-3 items-center justify-center rounded text-red-500 transition-opacity hover:bg-red-100 dark:hover:bg-red-900/30"
                                                    title="Delete task"
                                                  >
                                                    <X className="h-2.5 w-2.5" />
                                                  </button>
                                                </div>
                                              </div>
                                            )
                                          })}
                                        </div>
                                      )}
                                      {(!project.tasks || project.tasks.length === 0) && project.task_count > 1 && (
                                        <div className="text-xs font-semibold text-slate-900 mt-0.5">
                                          {project.task_count} tasks
                                        </div>
                                      )}
                                    </div>
                                  )
                                })}

                                {/* System Tasks */}
                                {systemTasksList.length > 0 && (
                                  <div className="space-y-1">
                                      {systemTasksList.map((task, idx) => {
                                        const statusBadge = {
                                          label: "S",
                                          className: "border-sky-200 bg-sky-50 text-sky-700",
                                        }
                                        const isNewTask = isTaskNewForWeek(task.created_at, data?.week_start)
                                        const displayTitle = getPlannerTaskDisplayTitle(task)
                                        const fullTitle = getPlannerTaskFullTitle(task)
                                        const taskStatusValue = getStatusValueForDay(task.status, task.completed_at, dayDate, task.daily_status)
                                        const titleColorClass = task.is_deadline_important && taskStatusValue !== "DONE" ? "text-white" : "text-slate-900"
                                        return (
                                          <div
                                            key={task.task_id || idx}
                                          className={[
                                            "pl-1 pr-0.5 py-0.5 rounded border text-[11px] flex items-center gap-1 group/task",
                                            getTaskCardClassesForDay(task.status, task.completed_at, dayDate, task.daily_status, task.created_at, task.is_deadline_important),
                                            repeatedTaskCardClassName(task),
                                          ].join(" ")}
                                        >
                                            <TaskOneHMarker
                                              marker={task.one_h_marker}
                                              markerByGa={task.one_h_marker_by_ga}
                                              comment={task.one_h_marker_comment}
                                              className="h-4 min-h-4 min-w-4 rounded px-0.5 text-[10px] !text-red-600"
                                            />
                                            <span className="min-w-0 flex-1">
                                              <TaskMarkerComment comment={task.one_h_marker_comment} />
                                              <button
                                              type="button"
                                              onClick={() => openTaskTitle(fullTitle)}
                                              className={[
                                                "block w-full min-w-0 truncate whitespace-nowrap font-semibold text-left hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 rounded",
                                                "weekly-task-title",
                                                titleColorClass,
                                              ].join(" ")}
                                              title={`${idx + 1}. ${displayTitle}`}
                                            >
                                              {idx + 1}. {displayTitle}
                                              </button>
                                            </span>
                                          <div className="flex shrink-0 items-center gap-1">
                                            {isNewTask && (
                                              <span className="inline-flex h-4 items-center justify-center rounded-full border border-blue-300 bg-blue-100 px-1 text-[9px] font-semibold tracking-tight text-blue-700">
                                                NEW
                                              </span>
                                            )}
                                            {statusBadge && (
                                              <span
                                                className={[
                                                  "inline-flex h-5 min-w-[1.5rem] items-center justify-center rounded-full border px-1 text-[10px] font-semibold",
                                                  statusBadge.className,
                                                ].join(" ")}
                                                title={statusBadge.label}
                                              >
                                                {statusBadge.label}
                                              </span>
                                            )}
                                            {task.task_id && (
                                              <button
                                                type="button"
                                                onClick={(e) => {
                                                  e.stopPropagation()
                                                  void deleteTask(task.task_id!, displayTitle, timeSlot, dayDate, userId)
                                                }}
                                                disabled={deletingTaskId === task.task_id}
                                                className="opacity-0 group-hover/task:opacity-100 inline-flex h-3 w-3 items-center justify-center rounded text-red-500 transition-opacity hover:bg-red-100 dark:hover:bg-red-900/30"
                                                title="Delete task"
                                              >
                                                <X className="h-2.5 w-2.5" />
                                              </button>
                                            )}
                                          </div>
                                        </div>
                                      )
                                    })}
                                  </div>
                                )}

                                {/* Fast Tasks */}
                                {fastTasksList.length > 0 && (
                                  <div className="space-y-1">
                                  {fastTasksList.map((task, idx) => {
                                    const statusBadge = getFastTaskBadge({ ...task, day_date: dayDate })
                                    const isNewTask = isTaskNewForWeek(task.created_at, data?.week_start)
                                    const displayTitle = getPlannerTaskDisplayTitle(task)
                                    const fullTitle = getPlannerTaskFullTitle(task)
                                    const taskStatusValue = getStatusValueForDay(task.status, task.completed_at, dayDate, task.daily_status)
                                    const titleColorClass = task.is_deadline_important && taskStatusValue !== "DONE" ? "text-white" : "text-slate-900"
                                    return (
                                      <div
                                        key={task.task_id || idx}
                                          className={[
                                            "pl-1 pr-0.5 py-0.5 rounded border text-[11px] flex items-center gap-1 group/task",
                                            getTaskCardClassesForDay(task.status, task.completed_at, dayDate, task.daily_status, task.created_at, task.is_deadline_important),
                                            repeatedTaskCardClassName(task),
                                          ].join(" ")}
                                        >
                                        <TaskOneHMarker
                                          marker={task.one_h_marker}
                                          markerByGa={task.one_h_marker_by_ga}
                                          comment={task.one_h_marker_comment}
                                          className="h-4 min-h-4 min-w-4 rounded px-0.5 text-[10px] !text-red-600"
                                        />
                                        <span className="min-w-0 flex-1">
                                          <TaskMarkerComment comment={task.one_h_marker_comment} />
                                          <button
                                          type="button"
                                          onClick={() => openTaskTitle(fullTitle)}
                                          className={[
                                            "block w-full min-w-0 truncate whitespace-nowrap font-semibold text-left hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 rounded",
                                            "weekly-task-title",
                                            titleColorClass,
                                          ].join(" ")}
                                          title={`${idx + 1}. ${displayTitle}`}
                                        >
                                          {idx + 1}. {displayTitle}
                                          </button>
                                        </span>
                                          <div className="flex shrink-0 items-center gap-1">
                                            {isNewTask && (
                                              <span className="inline-flex h-4 items-center justify-center rounded-full border border-blue-300 bg-blue-100 px-1 text-[9px] font-semibold tracking-tight text-blue-700">
                                                NEW
                                              </span>
                                            )}
                                            {statusBadge && (
                                              <span
                                                className={[
                                                  "inline-flex h-5 min-w-[1.5rem] items-center justify-center rounded-full border px-1 text-[10px] font-semibold",
                                                  statusBadge.className,
                                                ].join(" ")}
                                                title={statusBadge.label}
                                              >
                                                {statusBadge.label}
                                              </span>
                                            )}
                                            {task.task_id && (
                                              <button
                                                type="button"
                                                onClick={(e) => {
                                                  e.stopPropagation()
                                                  void deleteTask(task.task_id!, displayTitle, timeSlot, dayDate, userId)
                                                }}
                                                disabled={deletingTaskId === task.task_id}
                                                className="opacity-0 group-hover/task:opacity-100 inline-flex h-3 w-3 items-center justify-center rounded text-red-500 transition-opacity hover:bg-red-100 dark:hover:bg-red-900/30"
                                                title="Delete task"
                                              >
                                                <X className="h-2.5 w-2.5" />
                                              </button>
                                            )}
                                          </div>
                                        </div>
                                      )
                                    })}
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                      )
                          }

                          const renderFastOnly = (
                            fastTasks: WeeklyTableTaskEntry[],
                            dayDate: string,
                            timeSlot: "am" | "pm",
                            userId: string
                          ) => (
                            renderCellContent([], [], fastTasks, timeSlot, dayDate, userId)
                          )

                          const renderSystemOnly = (
                            systemTasks: WeeklyTableTaskEntry[],
                            dayDate: string,
                            timeSlot: "am" | "pm",
                            userId: string
                          ) => (
                            renderCellContent([], systemTasks, [], timeSlot, dayDate, userId)
                          )

                          const isGADepartment = dept.department_name === "GA"
                          const hasAmSystemTasks = allUsers.some((visibleUser) => {
                            const userDay = day.users.find((entry) => entry.user_id === visibleUser.user_id)
                            return Boolean(userDay?.am_system_tasks?.length)
                          })
                          const hasPmSystemTasks = allUsers.some((visibleUser) => {
                            const userDay = day.users.find((entry) => entry.user_id === visibleUser.user_id)
                            return Boolean(userDay?.pm_system_tasks?.length)
                          })
                          const rowSpan = 4 + Number(hasAmSystemTasks) + Number(hasPmSystemTasks)
                          const renderDayCell = () => (
                            <TableCell
                              className="font-medium sticky left-0 bg-background z-10 align-top w-24 min-w-24"
                              rowSpan={rowSpan}
                            >
                              <div className="flex flex-col">
                                <div className="font-bold text-slate-900">{DAY_NAMES[dayIndex]}</div>
                                <div className="text-xs font-semibold text-slate-900 mt-1">{formatDate(day.date)}</div>
                              </div>
                            </TableCell>
                          )

                          return (
                            <React.Fragment key={day.date}>
                              {isGADepartment ? (
                                <>
                                  {/* GA Department: SYS, FT, PRJK order */}
                                  {/* AM SYS Row */}
                                  {hasAmSystemTasks ? <TableRow className={dayIndex > 0 ? "border-t-3 border-gray-500" : undefined}>
                                    {renderDayCell()}
                                    <TableCell className="w-10 min-w-10 align-top sticky left-24 bg-background z-10 text-center">
                                      <div className="text-xs font-medium text-primary">AM</div>
                                    </TableCell>
                                    <TableCell className="w-10 min-w-10 align-top sticky left-34 bg-background z-10 text-center text-xs font-bold uppercase">
                                      SYS
                                    </TableCell>
                                    {allUsers.map((user) => {
                                      const userDay = day.users.find((u) => u.user_id === user.user_id)
                                      return (
                                        <TableCell key={`${user.user_id}-am-sys`} className="align-top w-56 min-w-56">
                                          {userDay
                                            ? renderSystemOnly(
                                              userDay.am_system_tasks || [],
                                              day.date,
                                              "am",
                                              user.user_id
                                            )
                                            : <div className="min-h-20 text-xs text-muted-foreground/50">—</div>}
                                        </TableCell>
                                      )
                                    })}
                                  </TableRow> : null}

                                  {/* AM FT Row */}
                                  <TableRow className={hasAmSystemTasks ? "border-t border-border" : dayIndex > 0 ? "border-t-3 border-gray-500" : undefined}>
                                    {!hasAmSystemTasks ? renderDayCell() : null}
                                    <TableCell className="w-10 min-w-10 align-top sticky left-24 bg-background z-10 text-center">
                                      <div className="text-xs font-medium text-primary">AM</div>
                                    </TableCell>
                                    <TableCell className="w-10 min-w-10 align-top sticky left-34 bg-background z-10 text-center text-xs font-bold uppercase">
                                      FT
                                    </TableCell>
                                    {allUsers.map((user) => {
                                      const userDay = day.users.find((u) => u.user_id === user.user_id)
                                      return (
                                        <TableCell key={`${user.user_id}-am-ft`} className="align-top w-56 min-w-56">
                                          {userDay
                                            ? renderFastOnly(
                                              userDay.am_fast_tasks || [],
                                              day.date,
                                              "am",
                                              user.user_id
                                            )
                                            : <div className="min-h-20 text-xs text-muted-foreground/50">—</div>}
                                        </TableCell>
                                      )
                                    })}
                                  </TableRow>

                                  {/* AM PRJK Row */}
                                  <TableRow className="border-t border-border">
                                    <TableCell className="w-10 min-w-10 align-top sticky left-24 bg-background z-10 text-center">
                                      <div className="text-xs font-medium text-primary">AM</div>
                                    </TableCell>
                                    <TableCell className="w-10 min-w-10 align-top sticky left-34 bg-background z-10 text-center text-xs font-bold uppercase">
                                      PRJK
                                    </TableCell>
                                    {allUsers.map((user) => {
                                      const userDay = day.users.find((u) => u.user_id === user.user_id)
                                      return (
                                        <TableCell key={`${user.user_id}-am-prjk`} className="align-top w-56 min-w-56">
                                          {userDay
                                            ? renderCellContent(
                                              userDay.am_projects || [],
                                              [],
                                              [],
                                              "am",
                                              day.date,
                                              user.user_id
                                            )
                                            : <div className="min-h-20 text-xs text-muted-foreground/50">—</div>}
                                        </TableCell>
                                      )
                                    })}
                                  </TableRow>

                                  {/* PM SYS Row */}
                                  {hasPmSystemTasks ? <TableRow className="border-t-2 border-border">
                                    <TableCell className="w-10 min-w-10 align-top sticky left-24 bg-background z-10 text-center">
                                      <div className="text-xs font-medium text-primary">PM</div>
                                    </TableCell>
                                    <TableCell className="w-10 min-w-10 align-top sticky left-34 bg-background z-10 text-center text-xs font-bold uppercase">
                                      SYS
                                    </TableCell>
                                    {allUsers.map((user) => {
                                      const userDay = day.users.find((u) => u.user_id === user.user_id)
                                      return (
                                        <TableCell key={`${user.user_id}-pm-sys`} className="align-top w-56 min-w-56">
                                          {userDay
                                            ? renderSystemOnly(
                                              userDay.pm_system_tasks || [],
                                              day.date,
                                              "pm",
                                              user.user_id
                                            )
                                            : <div className="min-h-20 text-xs text-muted-foreground/50">—</div>}
                                        </TableCell>
                                      )
                                    })}
                                  </TableRow> : null}

                                  {/* PM FT Row */}
                                  <TableRow className={hasPmSystemTasks ? "border-t border-border" : "border-t-2 border-border"}>
                                    <TableCell className="w-10 min-w-10 align-top sticky left-24 bg-background z-10 text-center">
                                      <div className="text-xs font-medium text-primary">PM</div>
                                    </TableCell>
                                    <TableCell className="w-10 min-w-10 align-top sticky left-34 bg-background z-10 text-center text-xs font-bold uppercase">
                                      FT
                                    </TableCell>
                                    {allUsers.map((user) => {
                                      const userDay = day.users.find((u) => u.user_id === user.user_id)
                                      return (
                                        <TableCell key={`${user.user_id}-pm-ft`} className="align-top w-56 min-w-56">
                                          {userDay
                                            ? renderFastOnly(
                                              userDay.pm_fast_tasks || [],
                                              day.date,
                                              "pm",
                                              user.user_id
                                            )
                                            : <div className="min-h-20 text-xs text-muted-foreground/50">—</div>}
                                        </TableCell>
                                      )
                                    })}
                                  </TableRow>

                                  {/* PM PRJK Row */}
                                  <TableRow className="border-t border-border">
                                    <TableCell className="w-10 min-w-10 align-top sticky left-24 bg-background z-10 text-center">
                                      <div className="text-xs font-medium text-primary">PM</div>
                                    </TableCell>
                                    <TableCell className="w-10 min-w-10 align-top sticky left-34 bg-background z-10 text-center text-xs font-bold uppercase">
                                      PRJK
                                    </TableCell>
                                    {allUsers.map((user) => {
                                      const userDay = day.users.find((u) => u.user_id === user.user_id)
                                      return (
                                        <TableCell key={`${user.user_id}-pm-prjk`} className="align-top w-56 min-w-56">
                                          {userDay
                                            ? renderCellContent(
                                              userDay.pm_projects || [],
                                              [],
                                              [],
                                              "pm",
                                              day.date,
                                              user.user_id
                                            )
                                            : <div className="min-h-20 text-xs text-muted-foreground/50">—</div>}
                                        </TableCell>
                                      )
                                    })}
                                  </TableRow>
                                </>
                              ) : (
                                <>
                                  {/* Other Departments: keep system tasks in dedicated SYS rows. */}
                                  {/* AM SYS Row */}
                                  {hasAmSystemTasks ? <TableRow className={dayIndex > 0 ? "border-t-3 border-gray-500 border-b-0" : "border-b-0"}>
                                    {renderDayCell()}
                                    <TableCell className="w-10 min-w-10 align-top sticky left-24 bg-background z-10 text-center">
                                      <div className="text-xs font-medium text-primary">AM</div>
                                    </TableCell>
                                    <TableCell className="w-10 min-w-10 align-top sticky left-34 bg-background z-10 text-center text-xs font-bold uppercase">
                                      SYS
                                    </TableCell>
                                    {allUsers.map((user) => {
                                      const userDay = day.users.find((u) => u.user_id === user.user_id)
                                      return (
                                        <TableCell key={`${user.user_id}-am-sys`} className="align-top w-56 min-w-56">
                                          {userDay
                                            ? renderSystemOnly(
                                              userDay.am_system_tasks || [],
                                              day.date,
                                              "am",
                                              user.user_id
                                            )
                                            : <div className="min-h-20 text-xs text-muted-foreground/50">—</div>}
                                        </TableCell>
                                      )
                                    })}
                                  </TableRow> : null}

                                  {/* AM PRJK Row */}
                                  <TableRow className={hasAmSystemTasks ? "border-t border-t-slate-200/60 border-b-0" : dayIndex > 0 ? "border-t-3 border-gray-500 border-b-0" : "border-b-0"}>
                                    {!hasAmSystemTasks ? renderDayCell() : null}
                                    <TableCell className="w-10 min-w-10 align-top sticky left-24 bg-background z-10 text-center">
                                      <div className="text-xs font-medium text-primary">AM</div>
                                    </TableCell>
                                    <TableCell className="w-10 min-w-10 align-top sticky left-34 bg-background z-10 text-center text-xs font-bold uppercase">
                                      PRJK
                                    </TableCell>
                                    {allUsers.map((user) => {
                                      const userDay = day.users.find((u) => u.user_id === user.user_id)
                                      return (
                                        <TableCell key={`${user.user_id}-am-prjk`} className="align-top w-56 min-w-56">
                                          {userDay
                                            ? renderCellContent(
                                              userDay.am_projects || [],
                                              [],
                                              [],
                                              "am",
                                              day.date,
                                              user.user_id
                                            )
                                            : <div className="min-h-20 text-xs text-muted-foreground/50">—</div>}
                                        </TableCell>
                                      )
                                    })}
                                  </TableRow>

                                  {/* AM FT Row */}
                                  <TableRow className="border-t border-t-slate-200/60">
                                    <TableCell className="w-10 min-w-10 align-top sticky left-24 bg-background z-10 text-center">
                                      <div className="text-xs font-medium text-primary">AM</div>
                                    </TableCell>
                                    <TableCell className="w-10 min-w-10 align-top sticky left-34 bg-background z-10 text-center text-xs font-bold uppercase">
                                      FT
                                    </TableCell>
                                    {allUsers.map((user) => {
                                      const userDay = day.users.find((u) => u.user_id === user.user_id)
                                      return (
                                        <TableCell key={`${user.user_id}-am-ft`} className="align-top w-56 min-w-56">
                                          {userDay
                                            ? renderFastOnly(
                                              userDay.am_fast_tasks || [],
                                              day.date,
                                              "am",
                                              user.user_id
                                            )
                                            : <div className="min-h-20 text-xs text-muted-foreground/50">—</div>}
                                        </TableCell>
                                      )
                                    })}
                                  </TableRow>

                                  {/* PM SYS Row */}
                                  {hasPmSystemTasks ? <TableRow className="border-t-2 border-t-gray-500 border-b-0">
                                    <TableCell className="w-10 min-w-10 align-top sticky left-24 bg-background z-10 text-center">
                                      <div className="text-xs font-medium text-primary">PM</div>
                                    </TableCell>
                                    <TableCell className="w-10 min-w-10 align-top sticky left-34 bg-background z-10 text-center text-xs font-bold uppercase">
                                      SYS
                                    </TableCell>
                                    {allUsers.map((user) => {
                                      const userDay = day.users.find((u) => u.user_id === user.user_id)
                                      return (
                                        <TableCell key={`${user.user_id}-pm-sys`} className="align-top w-56 min-w-56">
                                          {userDay
                                            ? renderSystemOnly(
                                              userDay.pm_system_tasks || [],
                                              day.date,
                                              "pm",
                                              user.user_id
                                            )
                                            : <div className="min-h-20 text-xs text-muted-foreground/50">—</div>}
                                        </TableCell>
                                      )
                                    })}
                                  </TableRow> : null}

                                  {/* PM PRJK Row */}
                                  <TableRow className={hasPmSystemTasks ? "border-t border-t-slate-200/60 border-b-0" : "border-t-2 border-t-gray-500 border-b-0"}>
                                    <TableCell className="w-10 min-w-10 align-top sticky left-24 bg-background z-10 text-center">
                                      <div className="text-xs font-medium text-primary">PM</div>
                                    </TableCell>
                                    <TableCell className="w-10 min-w-10 align-top sticky left-34 bg-background z-10 text-center text-xs font-bold uppercase">
                                      PRJK
                                    </TableCell>
                                    {allUsers.map((user) => {
                                      const userDay = day.users.find((u) => u.user_id === user.user_id)
                                      return (
                                        <TableCell key={`${user.user_id}-pm-prjk`} className="align-top w-56 min-w-56">
                                          {userDay
                                            ? renderCellContent(
                                              userDay.pm_projects || [],
                                              [],
                                              [],
                                              "pm",
                                              day.date,
                                              user.user_id
                                            )
                                            : <div className="min-h-20 text-xs text-muted-foreground/50">—</div>}
                                        </TableCell>
                                      )
                                    })}
                                  </TableRow>

                                  {/* PM FT Row */}
                                  <TableRow className="border-t border-t-slate-200/60">
                                    <TableCell className="w-10 min-w-10 align-top sticky left-24 bg-background z-10 text-center">
                                      <div className="text-xs font-medium text-primary">PM</div>
                                    </TableCell>
                                    <TableCell className="w-10 min-w-10 align-top sticky left-34 bg-background z-10 text-center text-xs font-bold uppercase">
                                      FT
                                    </TableCell>
                                    {allUsers.map((user) => {
                                      const userDay = day.users.find((u) => u.user_id === user.user_id)
                                      return (
                                        <TableCell key={`${user.user_id}-pm-ft`} className="align-top w-56 min-w-56">
                                          {userDay
                                            ? renderFastOnly(
                                              userDay.pm_fast_tasks || [],
                                              day.date,
                                              "pm",
                                              user.user_id
                                            )
                                            : <div className="min-h-20 text-xs text-muted-foreground/50">—</div>}
                                        </TableCell>
                                      )
                                    })}
                                  </TableRow>
                                </>
                              )}
                            </React.Fragment>
                          )
                      })}
                          </TableBody>
                        </Table>
                      </DndContext>
                    )
                  })()}
                </CardContent>
              </Card>
            ))}
          </div>
        )
      ) : null}
    </div>
  )
}
