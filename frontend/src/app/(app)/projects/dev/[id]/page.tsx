"use client"

import * as React from "react"
import { useParams, useRouter } from "next/navigation"

import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useConfirm } from "@/components/providers/confirm-dialog-provider"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { BoldOnlyEditor } from "@/components/bold-only-editor"
import { ChevronDown, Eye } from "lucide-react"
import { useAuth } from "@/lib/auth"
import { formatDateDMY, formatDateTimeDMY, normalizeDueDateInput, toDateInputValue } from "@/lib/dates"
import { renderMarkedNoteContent } from "@/lib/note-markup"
import type {
  ChecklistItem,
  GaNote,
  Meeting,
  Project,
  ProjectPhaseChecklistItem,
  ProjectPrompt,
  Task,
  TaskFinishPeriod,
  User,
} from "@/lib/types"

const PHASES = ["MEETINGS", "PLANNING", "DEVELOPMENT", "TESTING", "DOCUMENTATION", "CLOSED"] as const
const TASK_PHASES = ["PLANNING", "DEVELOPMENT", "TESTING", "DOCUMENTATION"] as const
const PHASE_LABELS: Record<string, string> = {
  MEETINGS: "Meetings",
  PLANNING: "Planning",
  DEVELOPMENT: "Development",
  TESTING: "Testing",
  DOCUMENTATION: "Documentation",
  CLOSED: "Closed",
  MBYLLUR: "Closed", // legacy
}

function getInitials(name: string | null | undefined): string {
  if (!name) return "?"
  const parts = name.trim().split(/\s+/)
  if (parts.length === 0) return "?"
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase()
}

const TABS = [
  { id: "description", label: "Description" },
  { id: "tasks", label: "Tasks" },
  { id: "development-checklist", label: "Checklist" },
  { id: "checklists", label: "Checklists" },
  { id: "members", label: "Members" },
  { id: "ga", label: "GA/KA Notes" },
  { id: "prompts", label: "Prompts" },
] as const

const MEETING_TABS = [
  { id: "meeting-focus", label: "Meeting Focus" },
  { id: "meeting-checklist", label: "Checklist" },
] as const

type TabId = (typeof TABS)[number]["id"] | (typeof MEETING_TABS)[number]["id"]

const TASK_STATUSES = ["TODO", "IN_PROGRESS", "WAITING_CLIENT", "DONE"] as const
const TASK_PRIORITIES = ["NORMAL", "HIGH"] as const
const PROJECT_TASK_TYPES = ["NORMAL", "HIGH", "1H", "R1", "PERSONAL", "BLLOK"] as const
const FINISH_PERIOD_OPTIONS: TaskFinishPeriod[] = ["AM", "PM"]
const FINISH_PERIOD_NONE_VALUE = "__none__"
const FINISH_PERIOD_NONE_LABEL = "None (all day)"

const MEETING_POINTS = [
  "Confirm scope and goals with the client.",
  "Align on timeline, milestones, and communication.",
  "Define roles, owners, and next steps.",
  "Capture risks, dependencies, and open questions.",
]

const MEETING_CHECKLIST_ITEMS = [
  "Project Type",
  "Requester/Supporter",
  "Project Lead",
  "Other Participants",
  "Role of Other Participants",
  "Concept/Planning",
  "Anticipated Problems",
]
const DOCUMENTATION_CHECKLIST_QUESTIONS = [
  "Does the documentation have a clear ending?",
  "Did you follow the documentation template?",
  "Did you save it as files?",
]

function initials(src: string) {
  return src
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("")
}

function toDateInput(value?: string | null) {
  return toDateInputValue(value)
}

function normalizeTaskPhase(phase?: string | null) {
  if (!phase || phase === "MEETINGS") return "PLANNING"
  if (phase === "CLOSED" || phase === "MBYLLUR") return "DOCUMENTATION"
  return phase
}

function getProjectTaskType(task: Task | null): (typeof PROJECT_TASK_TYPES)[number] {
  if (!task) return "NORMAL"
  if (task.is_1h_report) return "1H"
  if (task.is_r1) return "R1"
  if (task.is_personal) return "PERSONAL"
  if (task.is_bllok) return "BLLOK"
  return task.priority === "HIGH" ? "HIGH" : "NORMAL"
}

function formatDateDisplay(value?: string | null) {
  return formatDateDMY(value)
}

function isOverdue(task: Task) {
  if (!task.due_date || task.status === "DONE") return false
  const due = new Date(task.due_date)
  if (Number.isNaN(due.getTime())) return false
  due.setHours(23, 59, 59, 999)
  return Date.now() > due.getTime()
}

function statusLabel(status?: string) {
  if (!status) return "-"
  if (status === "WAITING_CLIENT") return "WFE"
  return status
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/(^\w|\s\w)/g, (m) => m.toUpperCase())
}

function formatDateTime(value?: string | null) {
  return formatDateTimeDMY(value)
}

function formatMeetingLabel(meeting: Meeting) {
  const platformLabel = meeting.platform ? ` (${meeting.platform})` : ""
  if (!meeting.starts_at) return `${meeting.title}${platformLabel}`
  const date = new Date(meeting.starts_at)
  if (Number.isNaN(date.getTime())) return `${meeting.title}${platformLabel}`
  const today = new Date()
  const sameDay =
    date.getFullYear() === today.getFullYear() &&
    date.getMonth() === today.getMonth() &&
    date.getDate() === today.getDate()
  const timeLabel = date.toLocaleTimeString("sq-AL", { hour: "2-digit", minute: "2-digit" })
  const weekdayLabel = date.toLocaleDateString("sq-AL", { weekday: "long" })
  const prefix = sameDay ? timeLabel : weekdayLabel
  return `${prefix} - ${meeting.title}${platformLabel}`
}

async function initializeDocumentationChecklistItems(
  projectId: string,
  existingItems: ChecklistItem[],
  apiFetch: (url: string, options?: RequestInit) => Promise<Response>
) {
  const existingTitles = new Set(
    existingItems
      .filter((item) => item.path === "DOCUMENTATION" && item.item_type === "CHECKBOX")
      .map((item) => (item.title || "").trim().toLowerCase())
      .filter(Boolean)
  )
  const missing = DOCUMENTATION_CHECKLIST_QUESTIONS.filter(
    (title) => !existingTitles.has(title.trim().toLowerCase())
  )
  if (!missing.length) return
  for (const title of missing) {
    const position = DOCUMENTATION_CHECKLIST_QUESTIONS.indexOf(title)
    const res = await apiFetch("/checklist-items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: projectId,
        item_type: "CHECKBOX",
        path: "DOCUMENTATION",
        title,
        is_checked: false,
        position: position >= 0 ? position + 1 : null,
      }),
    })
    if (!res.ok) {
      console.error("Failed to create documentation checklist item", title)
    }
  }
}

export default function DevelopmentProjectPage() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const projectId = String(params.id)
  const { apiFetch, user } = useAuth()
  const confirm = useConfirm()

  const [project, setProject] = React.useState<Project | null>(null)
  const [tasks, setTasks] = React.useState<Task[]>([])
  const [departmentUsers, setDepartmentUsers] = React.useState<User[]>([])
  const [allUsers, setAllUsers] = React.useState<User[]>([])
  const [members, setMembers] = React.useState<User[]>([])
  const [checklistItems, setChecklistItems] = React.useState<ChecklistItem[]>([])
  const [gaNotes, setGaNotes] = React.useState<GaNote[]>([])
  const [prompts, setPrompts] = React.useState<ProjectPrompt[]>([])
  const [meetings, setMeetings] = React.useState<Meeting[]>([])
  const [activeTab, setActiveTab] = React.useState<TabId>("description")
  const [developmentChecklistItems, setDevelopmentChecklistItems] = React.useState<ProjectPhaseChecklistItem[]>([])
  const [developmentChecklistLoading, setDevelopmentChecklistLoading] = React.useState(false)
  const [developmentChecklistError, setDevelopmentChecklistError] = React.useState<string | null>(null)
  const [developmentChecklistCreateOpen, setDevelopmentChecklistCreateOpen] = React.useState(false)
  const [developmentChecklistTitle, setDevelopmentChecklistTitle] = React.useState("")
  const [developmentChecklistComment, setDevelopmentChecklistComment] = React.useState("")
  const [developmentChecklistCreating, setDevelopmentChecklistCreating] = React.useState(false)
  const [developmentChecklistEditingId, setDevelopmentChecklistEditingId] = React.useState<string | null>(null)
  const [developmentChecklistEditingTitle, setDevelopmentChecklistEditingTitle] = React.useState("")
  const [developmentChecklistEditingComment, setDevelopmentChecklistEditingComment] = React.useState("")
  const [developmentChecklistSavingId, setDevelopmentChecklistSavingId] = React.useState<string | null>(null)
  const [developmentChecklistDeletingId, setDevelopmentChecklistDeletingId] = React.useState<string | null>(null)
  const [newChecklistContent, setNewChecklistContent] = React.useState("")
  const [addingChecklist, setAddingChecklist] = React.useState(false)
  const [createOpen, setCreateOpen] = React.useState(false)
  const [newTitle, setNewTitle] = React.useState("")
  const [newDescription, setNewDescription] = React.useState("")
  const [newStatus, setNewStatus] = React.useState<(typeof TASK_STATUSES)[number]>("TODO")
  const [newTaskType, setNewTaskType] = React.useState<(typeof PROJECT_TASK_TYPES)[number]>("NORMAL")
  const [newAssignees, setNewAssignees] = React.useState<string[]>([])
  const [newTaskPhase, setNewTaskPhase] = React.useState<string>("")
  const [newStartDate, setNewStartDate] = React.useState("")
  const [newDueDate, setNewDueDate] = React.useState("")
  const [newDeadlineImportant, setNewDeadlineImportant] = React.useState(false)
  const [newFinishPeriod, setNewFinishPeriod] = React.useState<TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE>(
    FINISH_PERIOD_NONE_VALUE
  )
  const [editOpen, setEditOpen] = React.useState(false)
  const [editingTaskId, setEditingTaskId] = React.useState<string | null>(null)
  const [editTitle, setEditTitle] = React.useState("")
  const [editDescription, setEditDescription] = React.useState("")
  const [viewDescriptionOpen, setViewDescriptionOpen] = React.useState(false)
  const [viewingTaskTitle, setViewingTaskTitle] = React.useState("")
  const [viewingTaskDescription, setViewingTaskDescription] = React.useState("")
  const [editStatus, setEditStatus] = React.useState<Task["status"]>("TODO")
  const [editTaskType, setEditTaskType] = React.useState<(typeof PROJECT_TASK_TYPES)[number]>("NORMAL")
  const [editAssignees, setEditAssignees] = React.useState<string[]>([])
  const [editPhase, setEditPhase] = React.useState<string>("")
  const [editStartDate, setEditStartDate] = React.useState("")
  const [editDueDate, setEditDueDate] = React.useState("")
  const [editFinishPeriod, setEditFinishPeriod] = React.useState<TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE>(
    FINISH_PERIOD_NONE_VALUE
  )
  const [editDeadlineImportant, setEditDeadlineImportant] = React.useState(false)
  const [savingEdit, setSavingEdit] = React.useState(false)
  const [creating, setCreating] = React.useState(false)
  const [updatingTaskId, setUpdatingTaskId] = React.useState<string | null>(null)
  const [deletingTaskId, setDeletingTaskId] = React.useState<string | null>(null)
  const [editingDescription, setEditingDescription] = React.useState("")
  const [savingDescription, setSavingDescription] = React.useState(false)
  const [membersOpen, setMembersOpen] = React.useState(false)
  const [selectedMemberIds, setSelectedMemberIds] = React.useState<string[]>([])
  const [savingMembers, setSavingMembers] = React.useState(false)
  const [advancingPhase, setAdvancingPhase] = React.useState(false)
  const [viewedPhase, setViewedPhase] = React.useState<string | null>(null)
  const [showClosedDetails, setShowClosedDetails] = React.useState(false)
  const [newGaNote, setNewGaNote] = React.useState("")
  const [newGaNoteType, setNewGaNoteType] = React.useState("GA")
  const [newGaNotePriority, setNewGaNotePriority] = React.useState<"__none__" | "NORMAL" | "HIGH">("__none__")
  const [addingGaNote, setAddingGaNote] = React.useState(false)
  const [meetingChecklist, setMeetingChecklist] = React.useState(() =>
    MEETING_CHECKLIST_ITEMS.map((content, index) => ({
      id: `meeting-${index}`,
      content,
      isChecked: false,
    }))
  )
  const [documentationChecklist, setDocumentationChecklist] = React.useState(() =>
    DOCUMENTATION_CHECKLIST_QUESTIONS.map((question, index) => ({
      id: `doc-${index}`,
      question,
      position: index + 1,
      isChecked: false,
    }))
  )
  const [documentationEditingId, setDocumentationEditingId] = React.useState<string | null>(null)
  const [documentationEditingText, setDocumentationEditingText] = React.useState("")
  const [newDocumentationText, setNewDocumentationText] = React.useState("")
  const [savingDocumentationItem, setSavingDocumentationItem] = React.useState(false)
  const [documentationFilePath, setDocumentationFilePath] = React.useState("")
  const [documentationFilePaths, setDocumentationFilePaths] = React.useState<string[]>([])
  const [gaPromptTitle, setGaPromptTitle] = React.useState("")
  const [gaPromptContent, setGaPromptContent] = React.useState("")
  const [devPromptTitle, setDevPromptTitle] = React.useState("")
  const [devPromptContent, setDevPromptContent] = React.useState("")
  const [savingGaPrompt, setSavingGaPrompt] = React.useState(false)
  const [savingDevPrompt, setSavingDevPrompt] = React.useState(false)
  const [expandedPrompts, setExpandedPrompts] = React.useState<Set<string>>(new Set())
  const [editProjectDueDateOpen, setEditProjectDueDateOpen] = React.useState(false)
  const [editProjectDueDate, setEditProjectDueDate] = React.useState("")
  const [savingProjectDueDate, setSavingProjectDueDate] = React.useState(false)
  const [isEditingProjectTitle, setIsEditingProjectTitle] = React.useState(false)
  const [projectTitleDraft, setProjectTitleDraft] = React.useState("")
  const [savingProjectTitle, setSavingProjectTitle] = React.useState(false)
  const isAdmin = user?.role === "ADMIN"
  const isManager = user?.role === "MANAGER"
  const canEditDueDate = isAdmin || isManager
  const canEditProjectTitle = Boolean(user)

  const loadDevelopmentChecklist = React.useCallback(
    async (targetProjectId?: string) => {
      if (!targetProjectId) return
      setDevelopmentChecklistLoading(true)
      setDevelopmentChecklistError(null)
      try {
        const res = await apiFetch(`/projects/${targetProjectId}/phases/development/checklist`)
        if (!res.ok) {
          let detail = "Failed to load checklist"
          try {
            const data = (await res.json()) as { detail?: string }
            if (data?.detail) detail = data.detail
          } catch {
            // ignore
          }
          setDevelopmentChecklistError(typeof detail === "string" ? detail : "Failed to load checklist")
          return
        }
        const items = (await res.json()) as ProjectPhaseChecklistItem[]
        setDevelopmentChecklistItems(items)
      } catch (error) {
        console.error("Failed to load development checklist", error)
        setDevelopmentChecklistError("Failed to load checklist")
      } finally {
        setDevelopmentChecklistLoading(false)
      }
    },
    [apiFetch]
  )

  const submitDevelopmentChecklistItem = async () => {
    if (!project) return
    const title = developmentChecklistTitle.trim()
    if (!title) {
      toast.error("Title is required")
      return
    }
    setDevelopmentChecklistCreating(true)
    try {
      const res = await apiFetch(`/projects/${project.id}/phases/development/checklist`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          comment: developmentChecklistComment.trim() || null,
        }),
      })
      if (!res.ok) {
        let detail = "Failed to add checklist item"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "Failed to add checklist item")
        return
      }
      const created = (await res.json()) as ProjectPhaseChecklistItem
      setDevelopmentChecklistItems((prev) => [...prev, created])
      setDevelopmentChecklistTitle("")
      setDevelopmentChecklistComment("")
      setDevelopmentChecklistCreateOpen(false)
      toast.success("Checklist item added")
    } finally {
      setDevelopmentChecklistCreating(false)
    }
  }

  const startEditDevelopmentChecklistItem = (item: ProjectPhaseChecklistItem) => {
    setDevelopmentChecklistEditingId(item.id)
    setDevelopmentChecklistEditingTitle(item.title || "")
    setDevelopmentChecklistEditingComment(item.comment || "")
  }

  const cancelEditDevelopmentChecklistItem = () => {
    setDevelopmentChecklistEditingId(null)
    setDevelopmentChecklistEditingTitle("")
    setDevelopmentChecklistEditingComment("")
  }

  const saveDevelopmentChecklistItem = async () => {
    if (!developmentChecklistEditingId) return
    const title = developmentChecklistEditingTitle.trim()
    if (!title) {
      toast.error("Title is required")
      return
    }
    setDevelopmentChecklistSavingId(developmentChecklistEditingId)
    try {
      const res = await apiFetch(`/phase-checklist-items/${developmentChecklistEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          comment: developmentChecklistEditingComment.trim() || null,
        }),
      })
      if (!res.ok) {
        let detail = "Failed to update checklist item"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "Failed to update checklist item")
        return
      }
      const updated = (await res.json()) as ProjectPhaseChecklistItem
      setDevelopmentChecklistItems((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
      cancelEditDevelopmentChecklistItem()
      toast.success("Checklist item updated")
    } finally {
      setDevelopmentChecklistSavingId(null)
    }
  }

  const toggleDevelopmentChecklistItem = async (item: ProjectPhaseChecklistItem, next: boolean) => {
    const previous = item.is_checked
    setDevelopmentChecklistItems((prev) =>
      prev.map((entry) => (entry.id === item.id ? { ...entry, is_checked: next } : entry))
    )
    try {
      const res = await apiFetch(`/phase-checklist-items/${item.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_checked: next }),
      })
      if (!res.ok) throw new Error("Failed to update checklist item")
      const updated = (await res.json()) as ProjectPhaseChecklistItem
      setDevelopmentChecklistItems((prev) =>
        prev.map((entry) => (entry.id === updated.id ? updated : entry))
      )
    } catch (error) {
      console.error("Failed to update checklist item", error)
      setDevelopmentChecklistItems((prev) =>
        prev.map((entry) => (entry.id === item.id ? { ...entry, is_checked: previous } : entry))
      )
      toast.error("Failed to update checklist item")
    }
  }

  const deleteDevelopmentChecklistItem = async (itemId: string) => {
    const confirmed = await confirm({
      title: "Delete checklist item",
      description: "Delete this checklist item?",
      confirmLabel: "Delete",
      variant: "destructive",
    })
    if (!confirmed) return
    setDevelopmentChecklistDeletingId(itemId)
    try {
      const res = await apiFetch(`/phase-checklist-items/${itemId}`, { method: "DELETE" })
      if (!res.ok) {
        let detail = "Failed to delete checklist item"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "Failed to delete checklist item")
        return
      }
      setDevelopmentChecklistItems((prev) => prev.filter((item) => item.id !== itemId))
      toast.success("Checklist item deleted")
    } finally {
      setDevelopmentChecklistDeletingId(null)
    }
  }

  // Sync the edit date when dialog opens or project changes
  React.useEffect(() => {
    if (editProjectDueDateOpen && project) {
      setEditProjectDueDate(toDateInput(project.due_date))
    }
  }, [editProjectDueDateOpen, project?.due_date])

  React.useEffect(() => {
    if (!project || isEditingProjectTitle) return
    setProjectTitleDraft(project.title || project.name || "")
  }, [project, isEditingProjectTitle])

  React.useEffect(() => {
    const load = async () => {
      const pRes = await apiFetch(`/projects/${projectId}`)
      if (!pRes.ok) return
      const p = (await pRes.json()) as Project
      setProject(p)
      setEditingDescription(p.description || "")

      const [tRes, mRes, cRes, gRes, prRes, usersRes, meetingsRes] = await Promise.all([
        apiFetch(`/tasks?project_id=${p.id}&include_done=true`),
        apiFetch(`/project-members?project_id=${p.id}`),
        apiFetch(`/checklist-items?project_id=${p.id}`),
        apiFetch(`/ga-notes?project_id=${p.id}`),
        apiFetch(`/project-prompts?project_id=${p.id}`),
        apiFetch("/users?include_all_departments=true"),
        apiFetch(`/meetings?project_id=${p.id}`),
      ])

      if (tRes.ok) setTasks((await tRes.json()) as Task[])
      if (mRes.ok) setMembers((await mRes.json()) as User[])
      if (cRes.ok) {
        const items = (await cRes.json()) as ChecklistItem[]
        console.log("Initial checklist items loaded:", items.length)
        const filePathItemsInitial = items.filter(
          (item) => item.path === "DOCUMENTATION" && item.item_type === "COMMENT" && item.category === "FILE_PATH"
        )
        console.log("File path items in initial load:", filePathItemsInitial)
        setChecklistItems(items)
        try {
          await initializeDocumentationChecklistItems(p.id, items, apiFetch)
          const reloadRes = await apiFetch(`/checklist-items?project_id=${p.id}`)
          if (reloadRes.ok) {
            const reloadedItems = (await reloadRes.json()) as ChecklistItem[]
            console.log("Reloaded checklist items after init:", reloadedItems.length)
            const filePathItemsAfterReload = reloadedItems.filter(
              (item) => item.path === "DOCUMENTATION" && item.item_type === "COMMENT" && item.category === "FILE_PATH"
            )
            console.log("File path items after reload:", filePathItemsAfterReload)
            setChecklistItems(reloadedItems)
          }
        } catch (error) {
          console.error("Failed to initialize documentation checklist items:", error)
        }
      }
      if (gRes.ok) setGaNotes((await gRes.json()) as GaNote[])
      if (prRes.ok) setPrompts((await prRes.json()) as ProjectPrompt[])
      if (meetingsRes.ok) setMeetings((await meetingsRes.json()) as Meeting[])
      if (usersRes.ok) {
        const users = (await usersRes.json()) as User[]
        setAllUsers(users)
        setDepartmentUsers(users.filter((u) => u.department_id === p.department_id))
      }
      await loadDevelopmentChecklist(p.id)
    }
    void load()
  }, [apiFetch, projectId])

  React.useEffect(() => {
    if (!project?.current_phase) return
    if (project.current_phase === "CLOSED") {
      setViewedPhase("DOCUMENTATION")
      return
    }
    setViewedPhase(project.current_phase)
  }, [project?.current_phase])

  React.useEffect(() => {
    if (!prompts.length) return
  }, [prompts])

  React.useEffect(() => {
    if (!membersOpen) return
    setSelectedMemberIds(members.map((m) => m.id))
  }, [membersOpen, members])

  React.useEffect(() => {
    if (!createOpen) return
    if (newTaskPhase) return
    const rawPhase = project?.current_phase || "MEETINGS"
    const phaseValue = normalizeTaskPhase(viewedPhase || rawPhase)
    setNewTaskPhase(phaseValue)
  }, [createOpen, newTaskPhase, project?.current_phase, viewedPhase])


  const submitCreateTask = async () => {
    if (!project) return
    if (!newTitle.trim()) {
      toast.error("Title is required")
      return
    }
    if (!newAssignees || newAssignees.length === 0) {
      toast.error("Please assign the task to at least one user")
      return
    }
    if (!newDueDate || !newDueDate.trim()) {
      toast.error("Due date is required")
      return
    }
    setCreating(true)
    try {
      const payload = {
        title: newTitle.trim(),
        description: newDescription.trim() || null,
        project_id: project.id,
        department_id: project.department_id,
        assignees: newAssignees,
        status: newStatus,
        priority: newTaskType === "HIGH" ? "HIGH" : "NORMAL",
        is_1h_report: newTaskType === "1H",
        is_r1: newTaskType === "R1",
        is_personal: newTaskType === "PERSONAL",
        is_bllok: newTaskType === "BLLOK",
        phase: normalizeTaskPhase(newTaskPhase || activePhase),
        start_date: newStartDate ? new Date(newStartDate).toISOString() : null,
        due_date: newDueDate || null,
        is_deadline_important: newDeadlineImportant,
        finish_period: newFinishPeriod === FINISH_PERIOD_NONE_VALUE ? null : newFinishPeriod,
      }
      const res = await apiFetch("/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to create task"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "An error occurred")
        return
      }
      const created = (await res.json()) as Task
      if (newAssignees.length > 1) {
        const refresh = await apiFetch(`/tasks?project_id=${project.id}&include_done=true`)
        if (refresh.ok) {
          setTasks((await refresh.json()) as Task[])
        } else {
          setTasks((prev) => [created, ...prev])
        }
      } else {
        setTasks((prev) => [created, ...prev])
      }
      setCreateOpen(false)
      setNewTitle("")
      setNewDescription("")
      setNewStatus("TODO")
      setNewTaskType("NORMAL")
      setNewAssignees([])
      setNewTaskPhase("")
      setNewStartDate("")
      setNewDueDate("")
      setNewDeadlineImportant(false)
      setNewFinishPeriod(FINISH_PERIOD_NONE_VALUE)
      toast.success("Task created")
    } finally {
      setCreating(false)
    }
  }

  const updateTaskStatus = async (taskId: string, nextStatus: Task["status"]) => {
    const task = tasks.find((t) => t.id === taskId)
    const previousStatus = task?.status
    
    // Only admins can change tasks from DONE to any other status
    if (previousStatus === "DONE" && nextStatus !== "DONE" && user?.role !== "ADMIN") {
      toast.error("Only admins can change tasks from DONE to another status")
      return
    }
    
    setUpdatingTaskId(taskId)
    setTasks((prev) => prev.map((task) => (task.id === taskId ? { ...task, status: nextStatus } : task)))
    try {
      const res = await apiFetch(`/tasks/${taskId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: nextStatus }),
      })
      if (!res.ok) {
        throw new Error("Failed to update status")
      }
      const updated = (await res.json()) as Task
      setTasks((prev) => prev.map((task) => (task.id === updated.id ? updated : task)))
    } catch {
      setTasks((prev) =>
        prev.map((task) => (task.id === taskId ? { ...task, status: previousStatus } : task))
      )
      toast.error("Failed to update task status")
    } finally {
      setUpdatingTaskId(null)
    }
  }

  const startEditTask = (task: Task) => {
    setEditingTaskId(task.id)
    setEditTitle(task.title || "")
    setEditDescription(task.description || "")
    setEditStatus(task.status || "TODO")
    setEditTaskType(getProjectTaskType(task))
    // Get assignees from assignees array, fallback to assigned_to for backward compatibility
    const assigneeIds = task.assignees && task.assignees.length > 0
      ? task.assignees.map(a => a.id)
      : (task.assigned_to || task.assigned_to_user_id ? [task.assigned_to || task.assigned_to_user_id!] : [])
    setEditAssignees(assigneeIds)
    setEditPhase(task.phase || activePhase)
    setEditStartDate(toDateInput(task.start_date))
    setEditDueDate(toDateInput(task.due_date))
    setEditFinishPeriod(task.finish_period || FINISH_PERIOD_NONE_VALUE)
    setEditDeadlineImportant(Boolean(task.is_deadline_important))
    setEditOpen(true)
  }

  const startViewDescription = (task: Task) => {
    setViewingTaskTitle(task.title || "")
    setViewingTaskDescription(task.description || "")
    setViewDescriptionOpen(true)
  }

  const saveEditTask = async () => {
    if (!editingTaskId) return
    if (!editTitle.trim()) {
      toast.error("Title is required")
      return
    }
    if (!editAssignees || editAssignees.length === 0) {
      toast.error("Please assign the task to at least one user")
      return
    }
    if (!editDueDate || !editDueDate.trim()) {
      toast.error("Due date is required")
      return
    }
    setSavingEdit(true)
    try {
      const payload = {
        title: editTitle.trim(),
        description: editDescription.trim() || null,
        status: editStatus,
        priority: editTaskType === "HIGH" ? "HIGH" : "NORMAL",
        is_1h_report: editTaskType === "1H",
        is_r1: editTaskType === "R1",
        is_personal: editTaskType === "PERSONAL",
        is_bllok: editTaskType === "BLLOK",
        assignees: editAssignees,
        phase: editPhase || activePhase,
        start_date: editStartDate ? new Date(editStartDate).toISOString() : null,
        due_date: editDueDate || null,
        finish_period: editFinishPeriod === FINISH_PERIOD_NONE_VALUE ? null : editFinishPeriod,
        is_deadline_important: editDeadlineImportant,
      }
      const res = await apiFetch(`/tasks/${editingTaskId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to update task"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "An error occurred")
        return
      }
      const updated = (await res.json()) as Task
      setTasks((prev) => prev.map((task) => (task.id === updated.id ? updated : task)))
      setEditOpen(false)
      setEditingTaskId(null)
      toast.success("Task updated")
    } finally {
      setSavingEdit(false)
    }
  }

  const deleteTask = async (taskId: string, taskTitle?: string) => {
    if (!taskId) return

    const confirmed = await confirm({
      title: "Delete task",
      description: taskTitle
        ? `Are you sure you want to delete the task "${taskTitle}"? This action cannot be undone.`
        : "Are you sure you want to delete this task? This action cannot be undone.",
      confirmLabel: "Delete",
      variant: "destructive",
    })

    if (!confirmed) return

    setDeletingTaskId(taskId)
    try {
      const res = await apiFetch(`/tasks/${taskId}`, { method: "DELETE" })
      if (!res.ok) {
        let detail = "Failed to delete task"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "An error occurred")
        return
      }
      setTasks((prev) => prev.filter((task) => task.id !== taskId))
      toast.success("Task deleted")
    } catch {
      toast.error("Failed to delete task")
    } finally {
      setDeletingTaskId(null)
    }
  }

  const saveDescription = async () => {
    if (!project) return
    setSavingDescription(true)
    try {
      const res = await apiFetch(`/projects/${project.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description: editingDescription.trim() || null }),
      })
      if (!res.ok) {
        let detail = "Failed to update description"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "An error occurred")
        return
      }
      const updated = (await res.json()) as Project
      setProject(updated)
      setEditingDescription(updated.description || "")
      toast.success("Description updated")
    } finally {
      setSavingDescription(false)
    }
  }

  const startEditProjectTitle = () => {
    if (!project) return
    setProjectTitleDraft(project.title || project.name || "")
    setIsEditingProjectTitle(true)
  }

  const cancelEditProjectTitle = () => {
    if (!project) return
    setProjectTitleDraft(project.title || project.name || "")
    setIsEditingProjectTitle(false)
  }

  const saveProjectTitle = async () => {
    if (!project) return
    const nextTitle = projectTitleDraft.trim()
    if (!nextTitle) {
      toast.error("Title is required")
      return
    }
    setSavingProjectTitle(true)
    try {
      const res = await apiFetch(`/projects/${project.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: nextTitle }),
      })
      if (!res.ok) {
        let detail = "Failed to update project title"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "An error occurred")
        return
      }
      const updated = (await res.json()) as Project
      setProject(updated)
      setProjectTitleDraft(updated.title || updated.name || nextTitle)
      setIsEditingProjectTitle(false)
      toast.success("Project title updated")
    } finally {
      setSavingProjectTitle(false)
    }
  }

  const submitChecklistItem = async () => {
    if (!project || !newChecklistContent.trim()) return
    setAddingChecklist(true)
    try {
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          item_type: "CHECKBOX",
          title: newChecklistContent.trim(),
          is_checked: false,
        }),
      })
      if (!res.ok) {
        let detail = "Failed to add checklist item"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "An error occurred")
        return
      }
      const created = (await res.json()) as ChecklistItem
      setChecklistItems((prev) => [...prev, created])
      setNewChecklistContent("")
      toast.success("Checklist item added")
    } finally {
      setAddingChecklist(false)
    }
  }

  const toggleChecklistItem = async (itemId: string, next: boolean) => {
    setChecklistItems((prev) =>
      prev.map((item) => (item.id === itemId ? { ...item, is_checked: next } : item))
    )
    const res = await apiFetch(`/checklist-items/${itemId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_checked: next }),
    })
    if (!res.ok) {
      setChecklistItems((prev) =>
        prev.map((item) => (item.id === itemId ? { ...item, is_checked: !next } : item))
      )
      toast.error("Failed to update checklist")
    }
  }

  const toggleMeetingChecklistItem = (itemId: string, next: boolean) => {
    setMeetingChecklist((prev) =>
      prev.map((item) => (item.id === itemId ? { ...item, isChecked: next } : item))
    )
  }

  const updateMeetingChecklistItem = (itemId: string, content: string) => {
    setMeetingChecklist((prev) =>
      prev.map((item) => (item.id === itemId ? { ...item, content } : item))
    )
  }

  const toggleDocumentationChecklistItem = (itemId: string, next: boolean) => {
    setDocumentationChecklist((prev) =>
      prev.map((item) => (item.id === itemId ? { ...item, isChecked: next } : item))
    )
  }

  React.useEffect(() => {
    const items = checklistItems
      .filter((item) => item.path === "DOCUMENTATION" && item.item_type === "CHECKBOX")
      .slice()
      .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
    if (!items.length) return
    setDocumentationChecklist(
      items.map((item, index) => ({
        id: item.id,
        question: item.title || "",
        isChecked: Boolean(item.is_checked),
        position: item.position ?? index + 1,
      }))
    )
  }, [checklistItems])

  // Load documentation file paths from checklist items
  React.useEffect(() => {
    const filePathItems = checklistItems
      .filter((item) => item.path === "DOCUMENTATION" && item.item_type === "COMMENT" && item.category === "FILE_PATH")
      .slice()
      .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
    const paths = filePathItems.map((item) => item.comment || "").filter(Boolean)
    console.log("Loading file paths:", { filePathItems, paths, checklistItemsCount: checklistItems.length })
    setDocumentationFilePaths(paths)
  }, [checklistItems])

  const toggleDocumentationChecklistItemDb = async (itemId: string, next: boolean) => {
    const previous = checklistItems.find((item) => item.id === itemId)?.is_checked ?? false
    setChecklistItems((prev) =>
      prev.map((item) => (item.id === itemId ? { ...item, is_checked: next } : item))
    )
    setDocumentationChecklist((prev) =>
      prev.map((item) => (item.id === itemId ? { ...item, isChecked: next } : item))
    )
    const res = await apiFetch(`/checklist-items/${itemId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_checked: next }),
    })
    if (!res.ok) {
      setChecklistItems((prev) =>
        prev.map((item) => (item.id === itemId ? { ...item, is_checked: previous } : item))
      )
      setDocumentationChecklist((prev) =>
        prev.map((item) => (item.id === itemId ? { ...item, isChecked: previous } : item))
      )
      toast.error("Failed to update documentation checklist")
    }
  }

  const startEditDocumentationItem = (itemId: string) => {
    const item = documentationChecklist.find((entry) => entry.id === itemId)
    if (!item) return
    setDocumentationEditingId(itemId)
    setDocumentationEditingText(item.question)
  }

  const cancelEditDocumentationItem = () => {
    setDocumentationEditingId(null)
    setDocumentationEditingText("")
  }

  const saveDocumentationItem = async () => {
    if (!documentationEditingId) return
    const text = documentationEditingText.trim()
    if (!text) return
    setSavingDocumentationItem(true)
    try {
      const res = await apiFetch(`/checklist-items/${documentationEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: text }),
      })
      if (!res.ok) {
        toast.error("Failed to update documentation checklist item")
        return
      }
      const updated = (await res.json()) as ChecklistItem
      setChecklistItems((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
      cancelEditDocumentationItem()
    } finally {
      setSavingDocumentationItem(false)
    }
  }

  const deleteDocumentationItem = async (itemId: string) => {
    const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
    if (!res.ok) {
      toast.error("Failed to delete documentation checklist item")
      return
    }
    setChecklistItems((prev) => prev.filter((item) => item.id !== itemId))
    setDocumentationChecklist((prev) => prev.filter((item) => item.id !== itemId))
    toast.success("Documentation checklist item deleted")
  }

  const addDocumentationChecklistItem = async () => {
    if (!project) return
    const text = newDocumentationText.trim()
    if (!text) return
    setSavingDocumentationItem(true)
    try {
      const position =
        documentationChecklist.reduce((max, item) => Math.max(max, item.position ?? 0), 0) + 1
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          item_type: "CHECKBOX",
          path: "DOCUMENTATION",
          title: text,
          is_checked: false,
          position,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to add documentation checklist item")
        return
      }
      const created = (await res.json()) as ChecklistItem
      setChecklistItems((prev) => [...prev, created])
      setNewDocumentationText("")
      toast.success("Documentation checklist item added")
    } finally {
      setSavingDocumentationItem(false)
    }
  }

  const addDocumentationFilePath = async () => {
    if (!project) return
    const value = documentationFilePath.trim()
    if (!value) return
    
    try {
      const existingFilePaths = checklistItems
        .filter((item) => item.path === "DOCUMENTATION" && item.item_type === "COMMENT" && item.category === "FILE_PATH")
      const position = existingFilePaths.length > 0
        ? Math.max(...existingFilePaths.map((item) => item.position ?? 0)) + 1
        : 1
      
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          item_type: "COMMENT",
          path: "DOCUMENTATION",
          category: "FILE_PATH",
          comment: value,
          position,
        }),
      })
      
      if (!res.ok) {
        const errorText = await res.text()
        console.error("Failed to add file path:", errorText)
        toast.error("Failed to add file path")
        return
      }
      
      // Read the created item first
      const created = (await res.json()) as ChecklistItem
      console.log("Created file path item:", created)
      
      // Reload checklist items to ensure we have the latest data from server
      const reloadRes = await apiFetch(`/checklist-items?project_id=${project.id}`)
      if (reloadRes.ok) {
        const updatedItems = (await reloadRes.json()) as ChecklistItem[]
        console.log("Reloaded checklist items:", updatedItems.length, "items")
        const filePathItems = updatedItems.filter(
          (item) => item.path === "DOCUMENTATION" && item.item_type === "COMMENT" && item.category === "FILE_PATH"
        )
        console.log("File path items found:", filePathItems)
        setChecklistItems(updatedItems)
      } else {
        // Fallback: add the created item to state
        console.log("Reload failed, using created item:", created)
        setChecklistItems((prev) => [...prev, created])
      }
      
      setDocumentationFilePath("")
      toast.success("File path added")
    } catch (err) {
      console.error("Error adding file path:", err)
      toast.error("Failed to add file path")
    }
  }

  const deleteDocumentationFilePath = async (filePath: string) => {
    if (!project) return
    const item = checklistItems.find(
      (item) => item.path === "DOCUMENTATION" && item.item_type === "COMMENT" && item.category === "FILE_PATH" && item.comment === filePath
    )
    if (!item) return
    
    const res = await apiFetch(`/checklist-items/${item.id}`, { method: "DELETE" })
    if (!res.ok) {
      toast.error("Failed to delete file path")
      return
    }
    
    // Reload checklist items to ensure we have the latest data
    const reloadRes = await apiFetch(`/checklist-items?project_id=${project.id}`)
    if (reloadRes.ok) {
      const updatedItems = (await reloadRes.json()) as ChecklistItem[]
      setChecklistItems(updatedItems)
    } else {
      // Fallback: remove from state
      setChecklistItems((prev) => prev.filter((i) => i.id !== item.id))
    }
    
    toast.success("File path deleted")
  }

  const toggleMemberSelect = (userId: string) => {
    setSelectedMemberIds((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId]
    )
  }

  const submitMembers = async () => {
    if (!project || selectedMemberIds.length === 0) return
    setSavingMembers(true)
    try {
      const res = await apiFetch("/project-members", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          user_ids: selectedMemberIds,
        }),
      })
      if (!res.ok) {
        let detail = "Failed to add members"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "An error occurred")
        return
      }
      const added = (await res.json()) as User[]
      const existing = new Map(members.map((m) => [m.id, m]))
      for (const u of added) {
        existing.set(u.id, u)
      }
      setMembers(Array.from(existing.values()))
      setMembersOpen(false)
      toast.success("Members updated")
    } finally {
      setSavingMembers(false)
    }
  }

  const advancePhase = async () => {
    if (!project) return
    const currentPhase = project.current_phase || "MEETINGS"
    const isMeetingPhase = currentPhase === "MEETINGS"
    const openTasks = tasks.filter(
      (task) =>
        task.status !== "DONE" &&
        task.status !== "DONE" &&
        (task.phase || currentPhase) === currentPhase
    )
    const uncheckedItems = checklistItems.filter((item) => !item.is_checked)
    const uncheckedMeeting = isMeetingPhase ? meetingChecklist.filter((item) => !item.isChecked) : []
    if (openTasks.length || uncheckedItems.length || uncheckedMeeting.length) {
      const blockers: string[] = []
      if (openTasks.length) blockers.push(`${openTasks.length} detyra te hapura`)
      if (uncheckedItems.length) blockers.push(`${uncheckedItems.length} checklist te pa kryera`)
      if (uncheckedMeeting.length) blockers.push(`${uncheckedMeeting.length} checklist te takimeve te pa kryera`)
      toast.error(`Ka ${blockers.join(" dhe ")}.`)
      return
    }
    setAdvancingPhase(true)
    try {
      const res = await apiFetch(`/projects/${project.id}/advance-phase`, { method: "POST" })
      if (!res.ok) {
        let detail = "Failed to advance phase"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "An error occurred")
        return
      }
      const updated = (await res.json()) as Project
      const nextPhase = updated.current_phase || "MEETINGS"
      setProject(updated)
      if (nextPhase === "CLOSED") {
        // Keep the user viewing the phase they just completed, even though the project is now closed.
        setViewedPhase(currentPhase)
        toast.success("Project closed")
      } else {
        setViewedPhase(nextPhase)
        toast.success("Phase advanced")
      }
    } finally {
      setAdvancingPhase(false)
    }
  }

  const submitGaNote = async () => {
    if (!project || !newGaNote.trim()) return
    setAddingGaNote(true)
    try {
      const priorityValue = newGaNotePriority === "__none__" ? null : newGaNotePriority
      const res = await apiFetch("/ga-notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          content: newGaNote.trim(),
          note_type: newGaNoteType,
          priority: priorityValue,
        }),
      })
      if (!res.ok) {
        let detail = "Failed to add GA/KA note"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "An error occurred")
        return
      }
      const created = (await res.json()) as GaNote
      setGaNotes((prev) => [...prev, created])
      setNewGaNote("")
      setNewGaNoteType("GA")
      setNewGaNotePriority("__none__")
      toast.success("GA/KA note added")
    } finally {
      setAddingGaNote(false)
    }
  }

  const closeGaNote = async (noteId: string) => {
    const res = await apiFetch(`/ga-notes/${noteId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "CLOSED" }),
    })
    if (!res.ok) {
      let detail = "Failed to close GA/KA note"
      try {
        const data = (await res.json()) as { detail?: string }
        if (data?.detail) detail = data.detail
      } catch {
        // ignore
      }
      toast.error(typeof detail === "string" ? detail : "An error occurred")
      return
    }
    const updated = (await res.json()) as GaNote
    setGaNotes((prev) => prev.map((note) => (note.id === updated.id ? updated : note)))
  }

  const rawPhaseValue = project?.current_phase || "MEETINGS"
  const phaseValue = viewedPhase || (rawPhaseValue === "CLOSED" ? "DOCUMENTATION" : rawPhaseValue)
  const visibleTabs = React.useMemo(() => {
    if (phaseValue === "MEETINGS") {
      return [
        ...TABS.filter((tab) => tab.id === "description"),
        ...MEETING_TABS,
        ...TABS.filter((tab) => tab.id === "ga"),
      ]
    }
    if (phaseValue === "PLANIFIKIMI") {
      return TABS.filter((tab) => tab.id !== "checklists" && tab.id !== "members" && tab.id !== "prompts" && tab.id !== "development-checklist")
    }
    if (phaseValue === "ZHVILLIMI" || phaseValue === "DEVELOPMENT") {
      return [
        ...TABS.filter((tab) => tab.id === "tasks" || tab.id === "prompts" || tab.id === "development-checklist"),
        ...TABS.filter((tab) => tab.id === "ga"),
      ]
    }
    if (phaseValue === "TESTIMI") {
      return TABS.filter((tab) => tab.id !== "checklists" && tab.id !== "members" && tab.id !== "prompts" && tab.id !== "development-checklist")
    }
    if (phaseValue === "DOKUMENTIMI") {
      return TABS.filter((tab) =>
        tab.id !== "description" && tab.id !== "tasks" && tab.id !== "members" && tab.id !== "prompts" && tab.id !== "development-checklist"
      )
    }
    return TABS
  }, [phaseValue])

  React.useEffect(() => {
    if (!visibleTabs.length) return
    if (!visibleTabs.some((tab) => tab.id === activeTab)) {
      setActiveTab(visibleTabs[0].id)
    }
  }, [activeTab, visibleTabs])

  const activePhase = phaseValue
  const visibleTasks = React.useMemo(
    () =>
      tasks.filter((task) => {
        const taskPhase = task.phase || project?.current_phase || "MEETINGS"
        return taskPhase === activePhase
      }),
    [activePhase, project?.current_phase, tasks]
  )

  if (!project)
    return (
      <div className="min-h-screen bg-gradient-to-br from-sky-50 via-blue-50/30 to-white flex items-center justify-center">
        <div className="text-center">
          <div className="inline-block h-8 w-8 animate-spin rounded-full border-4 border-solid border-sky-500 border-r-transparent"></div>
          <div className="mt-4 text-sm text-slate-600">Loading project...</div>
        </div>
      </div>
    )

  const baseTitle = project.title || project.name || "Project"
  const title = project.project_type === "MST" && project.total_products != null && project.total_products > 0
    ? `${baseTitle} - ${project.total_products}`
    : baseTitle

  const renderProjectTitle = (titleClassName: string, inputClassName: string) => {
    if (!canEditProjectTitle) {
      return <h1 className={titleClassName}>{title}</h1>
    }
    if (isEditingProjectTitle) {
      return (
        <div className="flex flex-wrap items-center gap-2">
          <Input
            value={projectTitleDraft}
            onChange={(event) => setProjectTitleDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault()
                void saveProjectTitle()
              }
              if (event.key === "Escape") {
                event.preventDefault()
                cancelEditProjectTitle()
              }
            }}
            className={inputClassName}
            autoFocus
            aria-label="Project title"
          />
          <Button
            size="sm"
            onClick={() => void saveProjectTitle()}
            disabled={savingProjectTitle || !projectTitleDraft.trim()}
          >
            Save
          </Button>
          <Button size="sm" variant="outline" onClick={cancelEditProjectTitle} disabled={savingProjectTitle}>
            Cancel
          </Button>
        </div>
      )
    }
    return (
      <div className="flex items-center gap-2">
        <h1 className={titleClassName}>{title}</h1>
        <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={startEditProjectTitle}>
          Edit
        </Button>
      </div>
    )
  }
  const phase = project.current_phase || "MEETINGS"
  const phaseIndex = PHASES.indexOf(phase as (typeof PHASES)[number])
  const canClosePhase = phaseIndex !== -1 && phaseIndex < PHASES.length - 1 && phase !== "MBYLLUR"
  const userMap = new Map([...allUsers, ...members, ...(user ? [user] : [])].map((m) => [m.id, m]))
  const savePrompt = async (type: "GA_PROMPT" | "ZHVILLIM_PROMPT") => {
    if (!project) return
    const isGa = type === "GA_PROMPT"
    const title = (isGa ? gaPromptTitle : devPromptTitle).trim()
    const content = (isGa ? gaPromptContent : devPromptContent).trim()
    if (!title) {
      toast.error("Prompt title is required")
      return
    }
    if (!content) {
      toast.error("Prompt content is required")
      return
    }
    if (isGa) setSavingGaPrompt(true)
    else setSavingDevPrompt(true)
    try {
      const res = await apiFetch("/project-prompts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: project.id, type, title, content }),
      })
      if (!res.ok) {
        let detail = "Failed to save prompt"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "An error occurred")
        return
      }
      const created = (await res.json()) as ProjectPrompt
      setPrompts((prev) => [created, ...prev])
      if (isGa) {
        setGaPromptTitle("")
        setGaPromptContent("")
      } else {
        setDevPromptTitle("")
        setDevPromptContent("")
      }
      toast.success("Prompt saved")
    } finally {
      if (isGa) setSavingGaPrompt(false)
      else setSavingDevPrompt(false)
    }
  }

  const togglePromptExpanded = (promptId: string) => {
    setExpandedPrompts((prev) => {
      const next = new Set(prev)
      if (next.has(promptId)) {
        next.delete(promptId)
      } else {
        next.add(promptId)
      }
      return next
    })
  }

  if (project.current_phase === "CLOSED" && !showClosedDetails) {
    const totalTasks = tasks.length
    const doneTasks = tasks.filter((t) => t.status === "DONE").length
    const openTasks = totalTasks - doneTasks
    return (
      <div className="min-h-screen bg-gradient-to-br from-sky-50 via-blue-50/30 to-white">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10 space-y-6">
          <Card className="bg-white/90 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl overflow-hidden">
            <div className="p-6">
              <button
                type="button"
                onClick={() => router.back()}
                className="text-sm text-sky-600/70 hover:text-sky-700 transition-colors mb-4 inline-flex items-center gap-1.5 font-medium"
              >
                <span className="text-sky-500">←</span> Back to Projects
              </button>
              <div className="flex items-center gap-3">
                {renderProjectTitle(
                  "text-3xl font-bold text-slate-800 tracking-tight",
                  "h-10 text-3xl font-bold text-slate-800 tracking-tight"
                )}
                <Badge className="bg-slate-100 text-slate-700 border-slate-200 px-3 py-1.5 text-sm font-medium rounded-lg">
                  Closed
                </Badge>
              </div>
              <div className="mt-2 text-sm text-slate-600">
                This project has been completed and is now read-only.
              </div>
              <div className="mt-5 flex flex-wrap gap-3">
                <Button
                  onClick={() => setShowClosedDetails(true)}
                  className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl px-6 py-2.5 font-medium transition-all"
                >
                  View details
                </Button>
                <Button variant="outline" onClick={() => router.back()} className="rounded-xl">
                  Back to Projects
                </Button>
              </div>
            </div>
          </Card>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <Card className="bg-white/90 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl overflow-hidden">
              <div className="p-5">
                <div className="text-xs text-slate-500">Tasks</div>
                <div className="mt-1 text-2xl font-semibold text-slate-800">{totalTasks}</div>
              </div>
            </Card>
            <Card className="bg-white/90 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl overflow-hidden">
              <div className="p-5">
                <div className="text-xs text-slate-500">Done</div>
                <div className="mt-1 text-2xl font-semibold text-slate-800">{doneTasks}</div>
              </div>
            </Card>
            <Card className="bg-white/90 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl overflow-hidden">
              <div className="p-5">
                <div className="text-xs text-slate-500">Open</div>
                <div className="mt-1 text-2xl font-semibold text-slate-800">{openTasks}</div>
              </div>
            </Card>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-sky-50 via-blue-50/30 to-white">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        <div className="sticky top-0 z-10 bg-gradient-to-br from-sky-50 via-blue-50/30 to-white print:static pt-8 pb-4 space-y-4">
          {/* Header Section with Soft Blue Background */}
          <Card className="bg-white/80 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl overflow-hidden">
            <div className="bg-gradient-to-r from-sky-100/50 via-blue-50/50 to-sky-100/50 px-6 py-5 border-b border-sky-100/50">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <button
                    type="button"
                    onClick={() => router.back()}
                    className="text-sm text-sky-600/70 hover:text-sky-700 transition-colors mb-4 inline-flex items-center gap-1.5 font-medium"
                  >
                    <span className="text-sky-500">←</span> Back to Projects
                  </button>
                  <div className="flex items-center gap-3 mb-4">
                    {renderProjectTitle(
                      "text-4xl font-bold text-slate-800 tracking-tight",
                      "h-11 text-4xl font-bold text-slate-800 tracking-tight"
                    )}
                    {canEditDueDate && (
                      <button
                        type="button"
                        onClick={() => {
                          setEditProjectDueDate(toDateInput(project.due_date))
                          setEditProjectDueDateOpen(true)
                        }}
                        className="text-sm text-sky-600/70 hover:text-sky-700 transition-colors"
                        title="Edit project due date"
                      >
                        {project.due_date ? `Due: ${formatDateDMY(project.due_date)}` : "Set due date"}
                      </button>
                    )}
                    {!canEditDueDate && project.due_date && (
                      <span className="text-sm text-slate-600">Due: {formatDateDMY(project.due_date)}</span>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-3 mb-4">
                    <Badge className="bg-sky-100 text-sky-700 border-sky-200 hover:bg-sky-200/80 px-3 py-1.5 text-sm font-medium rounded-lg shadow-sm">
                      {PHASE_LABELS[phase] || "Meetings"}
                    </Badge>
                    {activePhase !== phase && (
                      <Badge variant="outline" className="bg-blue-50/50 text-blue-600 border-blue-200 px-3 py-1.5 text-xs font-medium rounded-lg">
                        View: {PHASE_LABELS[activePhase] || "Meetings"}
                      </Badge>
                    )}
                  </div>
                  {/* Phase Navigation - Beautiful Soft Blue Pills */}
                  <div className="flex flex-wrap items-center gap-2">
                    {PHASES.map((p, idx) => {
                      const isViewed = p === activePhase
                      const isCurrent = p === phase
                      const isLocked = idx > phaseIndex
                      return (
                        <React.Fragment key={p}>
                          <button
                            type="button"
                            onClick={() => {
                              if (isLocked) return
                              setViewedPhase(p)
                            }}
                            className={[
                              "px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200",
                              isLocked
                                ? "bg-white/60 text-slate-300 border border-slate-200 cursor-not-allowed"
                                : isViewed
                                  ? "bg-sky-500 text-white shadow-md shadow-sky-200/50 scale-105"
                                  : isCurrent
                                    ? "bg-sky-100 text-sky-700 hover:bg-sky-200/80 border border-sky-200"
                                    : "bg-white/60 text-slate-500 hover:bg-sky-50/80 border border-slate-200 hover:border-sky-200",
                            ].join(" ")}
                            aria-pressed={isViewed}
                            disabled={isLocked}
                          >
                            {PHASE_LABELS[p]}
                          </button>
                          {idx < PHASES.length - 1 && (
                            <span className="text-sky-300 text-lg font-light">→</span>
                          )}
                        </React.Fragment>
                      )
                    })}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Button className="bg-white hover:bg-sky-50 text-slate-700 border border-slate-200 shadow-sm rounded-xl px-4 py-2 font-medium transition-all">
                    Settings
                  </Button>
                </div>
              </div>
            </div>

            {/* Close Phase Button */}
            {canClosePhase && (
              <div className="px-6 py-4 bg-white/50 flex justify-end">
                <Button
                  variant="outline"
                  disabled={advancingPhase}
                  onClick={() => void advancePhase()}
                  className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl px-6 py-2.5 font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {advancingPhase ? "Closing..." : "Close Phase"}
                </Button>
              </div>
            )}
          </Card>

          {/* Tabs Navigation - Soft Blue Design */}
          <Card className="bg-white/80 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl overflow-hidden">
            <div className="px-6 py-1">
              <div className="flex flex-wrap gap-1">
                {visibleTabs.map((tab) => {
                  const isActive = tab.id === activeTab
                  const label = activePhase === "TESTIMI" && tab.id === "description" ? "Testing" : tab.label
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setActiveTab(tab.id)}
                      className={[
                        "relative px-5 py-3 text-sm font-medium rounded-xl transition-all duration-200",
                        tab.id === "ga" ? "ml-auto" : "",
                        isActive
                          ? "bg-sky-100 text-sky-700 shadow-sm"
                          : "text-slate-500 hover:text-sky-600 hover:bg-sky-50/50",
                      ].join(" ")}
                    >
                      {label}
                      {isActive && <span className="absolute inset-x-2 bottom-1.5 h-0.5 bg-sky-500 rounded-full" />}
                    </button>
                  )
                })}
              </div>
            </div>
          </Card>
        </div>

        {/* Tab Content Area with Soft Blue Design */}
        <div className="min-h-[400px]">
          {activeTab === "meeting-focus" ? (
            <Card className="bg-white/90 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl overflow-hidden">
              <div className="p-6">
                <div className="text-xl font-semibold text-slate-800 mb-2">Meeting Focus</div>
                <div className="text-sm text-slate-500 mb-6">Main points to discuss in the meeting.</div>
                <div className="space-y-3">
                  {MEETING_POINTS.map((point, index) => (
                    <div key={point} className="flex items-start gap-3 p-4 rounded-xl bg-sky-50/50 border border-sky-100/50">
                      <span className="mt-1 text-xs font-semibold text-slate-400 flex-shrink-0">{index + 1}.</span>
                      <span className="text-sm text-slate-700">{point}</span>
                    </div>
                  ))}
                </div>
              </div>
            </Card>
          ) : null}

          {activeTab === "meeting-checklist" ? (
            <Card className="bg-white/90 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl overflow-hidden">
              <div className="p-6">
                <div className="text-xl font-semibold text-slate-800 mb-6">Meeting Checklist</div>
                <div className="space-y-3">
                  {meetingChecklist.map((item, index) => (
                    <div key={item.id} className="flex items-start gap-3 rounded-xl border border-sky-100 bg-white px-4 py-3 hover:bg-sky-50/30 transition-colors">
                      <div className="mt-1 text-xs font-semibold text-slate-400">{index + 1}.</div>
                      <Checkbox
                        checked={item.isChecked}
                        onCheckedChange={(checked) => toggleMeetingChecklistItem(item.id, Boolean(checked))}
                        className="mt-1"
                      />
                      <Input
                        value={item.content}
                        onChange={(e) => updateMeetingChecklistItem(item.id, e.target.value)}
                        className="flex-1 border-sky-200 focus:border-sky-400"
                      />
                    </div>
                  ))}
                </div>
              </div>
            </Card>
          ) : null}

          {activeTab === "description" ? (
            <Card className="bg-white/90 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl overflow-hidden">
              <div className="p-6">
                {activePhase === "MEETINGS" ? (
                  <>
                    <div className="text-xl font-semibold text-slate-800 mb-2">Project Description</div>
                    <Textarea
                      value={editingDescription}
                      onChange={(e) => setEditingDescription(e.target.value)}
                      rows={6}
                      className="mt-4 border-sky-200 focus:border-sky-400 rounded-xl"
                    />
                    <div className="mt-4 flex justify-end">
                      <Button
                        variant="outline"
                        disabled={savingDescription}
                        onClick={() => void saveDescription()}
                        className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl px-6"
                      >
                        {savingDescription ? "Saving..." : "Save"}
                      </Button>
                    </div>
                  </>
                ) : activePhase === "TESTIMI" ? (
                  <>
                    <div className="text-xl font-semibold text-slate-800 mb-2">Testing Questions</div>
                    <div className="mt-6 space-y-3">
                      {[
                        "What should we test and why?",
                        "Who owns each test area?",
                        "What environments or data are required?",
                        "How will issues be tracked and fixed?",
                        "What is the acceptance checklist to approve?",
                      ].map((question, idx) => (
                        <div key={idx} className="p-4 rounded-xl bg-sky-50/50 border border-sky-100/50 text-sm text-slate-700">
                          {question}
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="text-xl font-semibold text-slate-800 mb-2">Project Description</div>
                    <Textarea
                      value={editingDescription}
                      onChange={(e) => setEditingDescription(e.target.value)}
                      rows={6}
                      className="mt-4 border-sky-200 focus:border-sky-400 rounded-xl"
                    />
                    <div className="mt-4 flex justify-end">
                      <Button
                        variant="outline"
                        disabled={savingDescription}
                        onClick={() => void saveDescription()}
                        className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl px-6"
                      >
                        {savingDescription ? "Saving..." : "Save"}
                      </Button>
                    </div>
                  </>
                )}
              </div>
            </Card>
          ) : null}

          {activeTab === "tasks" ? (
            <div className="space-y-4">
              <div className="flex items-center justify-end">
                <Dialog open={createOpen} onOpenChange={setCreateOpen}>
                  <DialogTrigger asChild>
                    <Button className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl px-6">
                      + Add Task
                    </Button>
                  </DialogTrigger>
                  <DialogContent className="sm:max-w-lg bg-white border-sky-100 rounded-2xl">
                    <DialogHeader>
                      <DialogTitle className="text-slate-800">New Task</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-4">
                      <div className="space-y-2">
                        <Label className="text-slate-700">Title <span className="text-red-500">*</span></Label>
                        <Input value={newTitle} onChange={(e) => setNewTitle(e.target.value.toUpperCase())} className="border-sky-200 focus:border-sky-400 rounded-xl" />
                      </div>
                      <div className="space-y-2">
                        <Label className="text-slate-700">Description</Label>
                        <BoldOnlyEditor value={newDescription} onChange={setNewDescription} />
                      </div>
                      <div className="grid gap-4 md:grid-cols-2">
                        <div className="space-y-2">
                          <Label className="text-slate-700">Status</Label>
                          <Select value={newStatus} onValueChange={(v) => setNewStatus(v as typeof newStatus)}>
                            <SelectTrigger className="border-sky-200 focus:border-sky-400 rounded-xl">
                              <SelectValue placeholder="Status" />
                            </SelectTrigger>
                            <SelectContent>
                              {TASK_STATUSES.map((s) => (
                                <SelectItem key={s} value={s}>
                                  {statusLabel(s)}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Type</Label>
                          <Select value={newTaskType} onValueChange={(v) => setNewTaskType(v as typeof newTaskType)}>
                            <SelectTrigger className="border-sky-200 focus:border-sky-400 rounded-xl">
                              <SelectValue placeholder="Type" />
                            </SelectTrigger>
                            <SelectContent>
                              {PROJECT_TASK_TYPES.map((p) => (
                                <SelectItem key={p} value={p}>
                                  {p}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                      <div className="grid gap-4 md:grid-cols-2">
                        <div className="space-y-2">
                          <Label className="text-slate-700">Assign to <span className="text-red-500">*</span></Label>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="outline" className="w-full justify-between border-sky-200 focus:border-sky-400 rounded-xl">
                                <span className="truncate text-left flex-1">
                                  {newAssignees.length > 0 
                                    ? (() => {
                                        const selectedNames = newAssignees
                                          .map(id => {
                                            const user = allUsers.find(u => u.id === id)
                                            return user?.full_name || user?.username || user?.email || id
                                          })
                                          .join(", ")
                                        return selectedNames.length > 50 
                                          ? `${selectedNames.substring(0, 50)}... (${newAssignees.length})`
                                          : selectedNames
                                      })()
                                    : "Select users"}
                                </span>
                                <ChevronDown className="h-4 w-4 opacity-50 ml-2 flex-shrink-0" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent className="w-full max-h-64 overflow-y-auto">
                              <DropdownMenuLabel>Select Users</DropdownMenuLabel>
                              <DropdownMenuSeparator />
                              {allUsers.map((m) => (
                                <DropdownMenuCheckboxItem
                                  key={m.id}
                                  checked={newAssignees.includes(m.id)}
                                  onCheckedChange={(checked) => {
                                    if (checked) {
                                      setNewAssignees([...newAssignees, m.id])
                                    } else {
                                      setNewAssignees(newAssignees.filter(id => id !== m.id))
                                    }
                                  }}
                                >
                                  {m.full_name || m.username || m.email}
                                </DropdownMenuCheckboxItem>
                              ))}
                              {newAssignees.length > 0 && (
                                <>
                                  <DropdownMenuSeparator />
                                  <DropdownMenuItem
                                    onSelect={(event) => {
                                      event.preventDefault()
                                      setNewAssignees([])
                                    }}
                                  >
                                    Clear selection
                                  </DropdownMenuItem>
                                </>
                              )}
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Phase</Label>
                          <Select value={newTaskPhase} onValueChange={setNewTaskPhase}>
                            <SelectTrigger className="border-sky-200 focus:border-sky-400 rounded-xl">
                              <SelectValue placeholder="Select phase" />
                            </SelectTrigger>
                            <SelectContent>
                              {TASK_PHASES.map((p) => (
                                <SelectItem key={p} value={p}>
                                  {PHASE_LABELS[p]}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Start date</Label>
                          <Input
                            type="date"
                            value={newStartDate}
                            onChange={(e) => setNewStartDate(normalizeDueDateInput(e.target.value))}
                            className="border-sky-200 focus:border-sky-400 rounded-xl"
                          />
                        </div>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Due date <span className="text-red-500">*</span></Label>
                          <Input
                            type="date"
                            value={newDueDate}
                            onChange={(e) => setNewDueDate(normalizeDueDateInput(e.target.value))}
                            className="border-sky-200 focus:border-sky-400 rounded-xl"
                            required
                          />
                        </div>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Finish period</Label>
                          <Select
                            value={newFinishPeriod}
                            onValueChange={(value) =>
                              setNewFinishPeriod(value as TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE)
                            }
                          >
                            <SelectTrigger className="border-sky-200 focus:border-sky-400 rounded-xl">
                              <SelectValue placeholder="All day" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value={FINISH_PERIOD_NONE_VALUE}>{FINISH_PERIOD_NONE_LABEL}</SelectItem>
                              {FINISH_PERIOD_OPTIONS.map((o) => (
                                <SelectItem key={o} value={o}>
                                  {o}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                      <label className="flex items-center gap-3 rounded-xl border border-sky-200 px-3 py-2">
                        <Checkbox
                          checked={newDeadlineImportant}
                          onCheckedChange={(checked) => setNewDeadlineImportant(checked === true)}
                        />
                        <span className="text-sm font-medium text-slate-700">Deadline important</span>
                      </label>
                      <div className="flex justify-end">
                        <Button
                          disabled={!newTitle.trim() || !newAssignees || newAssignees.length === 0 || !newDueDate || !newDueDate.trim() || creating}
                          onClick={() => void submitCreateTask()}
                          className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl px-6"
                        >
                          {creating ? "Creating..." : "Create"}
                        </Button>
                      </div>
                    </div>
                  </DialogContent>
                </Dialog>
                <Dialog open={editOpen} onOpenChange={setEditOpen}>
                  <DialogContent className="sm:max-w-lg bg-white border-sky-100 rounded-2xl">
                    <DialogHeader>
                      <DialogTitle className="text-slate-800">Edit Task</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-4">
                      <div className="space-y-2">
                        <Label className="text-slate-700">Title <span className="text-red-500">*</span></Label>
                        <Input
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value.toUpperCase())}
                          className="border-sky-200 focus:border-sky-400 rounded-xl"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label className="text-slate-700">Description</Label>
                        <Textarea
                          value={editDescription}
                          onChange={(e) => setEditDescription(e.target.value)}
                          className="border-sky-200 focus:border-sky-400 rounded-xl"
                        />
                      </div>
                      <div className="grid gap-4 md:grid-cols-2">
                        <div className="space-y-2">
                          <Label className="text-slate-700">Status</Label>
                          <Select value={editStatus} onValueChange={(v) => setEditStatus(v as Task["status"])}>
                            <SelectTrigger className="border-sky-200 focus:border-sky-400 rounded-xl">
                              <SelectValue placeholder="Status" />
                            </SelectTrigger>
                            <SelectContent>
                              {TASK_STATUSES.map((s) => (
                                <SelectItem key={s} value={s}>
                                  {statusLabel(s)}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Type</Label>
                          <Select value={editTaskType} onValueChange={(v) => setEditTaskType(v as typeof editTaskType)}>
                            <SelectTrigger className="border-sky-200 focus:border-sky-400 rounded-xl">
                              <SelectValue placeholder="Type" />
                            </SelectTrigger>
                            <SelectContent>
                              {PROJECT_TASK_TYPES.map((p) => (
                                <SelectItem key={p} value={p}>
                                  {p}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                      <div className="grid gap-4 md:grid-cols-2">
                        <div className="space-y-2">
                          <Label className="text-slate-700">Assign to <span className="text-red-500">*</span></Label>
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <Button variant="outline" className="w-full justify-between border-sky-200 focus:border-sky-400 rounded-xl">
                                <span className="truncate text-left flex-1">
                                  {editAssignees.length > 0 
                                    ? (() => {
                                        const selectedNames = editAssignees
                                          .map(id => {
                                            const user = allUsers.find(u => u.id === id)
                                            return user?.full_name || user?.username || user?.email || id
                                          })
                                          .join(", ")
                                        return selectedNames.length > 50 
                                          ? `${selectedNames.substring(0, 50)}... (${editAssignees.length})`
                                          : selectedNames
                                      })()
                                    : "Select users"}
                                </span>
                                <ChevronDown className="h-4 w-4 opacity-50 ml-2 flex-shrink-0" />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent className="w-full max-h-64 overflow-y-auto">
                              <DropdownMenuLabel>Select Users</DropdownMenuLabel>
                              <DropdownMenuSeparator />
                              {allUsers.map((m) => (
                                <DropdownMenuCheckboxItem
                                  key={m.id}
                                  checked={editAssignees.includes(m.id)}
                                  onCheckedChange={(checked) => {
                                    if (checked) {
                                      setEditAssignees([...editAssignees, m.id])
                                    } else {
                                      setEditAssignees(editAssignees.filter(id => id !== m.id))
                                    }
                                  }}
                                >
                                  {m.full_name || m.username || m.email}
                                </DropdownMenuCheckboxItem>
                              ))}
                              {editAssignees.length > 0 && (
                                <>
                                  <DropdownMenuSeparator />
                                  <DropdownMenuItem
                                    onSelect={(event) => {
                                      event.preventDefault()
                                      setEditAssignees([])
                                    }}
                                  >
                                    Clear selection
                                  </DropdownMenuItem>
                                </>
                              )}
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Phase</Label>
                          <Select value={editPhase} onValueChange={setEditPhase}>
                            <SelectTrigger className="border-sky-200 focus:border-sky-400 rounded-xl">
                              <SelectValue placeholder="Select phase" />
                            </SelectTrigger>
                            <SelectContent>
                              {TASK_PHASES.map((p) => (
                                <SelectItem key={p} value={p}>
                                  {PHASE_LABELS[p]}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Start date</Label>
                          <Input
                            type="date"
                            value={editStartDate}
                            onChange={(e) => setEditStartDate(normalizeDueDateInput(e.target.value))}
                            className="border-sky-200 focus:border-sky-400 rounded-xl"
                          />
                        </div>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Due date <span className="text-red-500">*</span></Label>
                          <Input
                            type="date"
                            value={editDueDate}
                            onChange={(e) => setEditDueDate(normalizeDueDateInput(e.target.value))}
                            className="border-sky-200 focus:border-sky-400 rounded-xl"
                            required
                          />
                        </div>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Finish period</Label>
                          <Select
                            value={editFinishPeriod}
                            onValueChange={(value) =>
                              setEditFinishPeriod(value as TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE)
                            }
                          >
                            <SelectTrigger className="border-sky-200 focus:border-sky-400 rounded-xl">
                              <SelectValue placeholder="All day" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value={FINISH_PERIOD_NONE_VALUE}>{FINISH_PERIOD_NONE_LABEL}</SelectItem>
                              {FINISH_PERIOD_OPTIONS.map((o) => (
                                <SelectItem key={o} value={o}>
                                  {o}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                      <label className="flex items-center gap-3 rounded-md border border-sky-200 px-3 py-2">
                        <Checkbox
                          checked={editDeadlineImportant}
                          onCheckedChange={(checked) => setEditDeadlineImportant(checked === true)}
                        />
                        <span className="text-sm font-medium text-slate-700">Deadline important</span>
                      </label>
                      <div className="flex justify-end gap-2">
                        <Button variant="outline" onClick={() => setEditOpen(false)} disabled={savingEdit}>
                          Cancel
                        </Button>
                        <Button
                          disabled={!editTitle.trim() || !editAssignees || editAssignees.length === 0 || !editDueDate || !editDueDate.trim() || savingEdit}
                          onClick={() => void saveEditTask()}
                          className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl px-6"
                        >
                          {savingEdit ? "Saving..." : "Save"}
                        </Button>
                      </div>
                    </div>
                  </DialogContent>
                </Dialog>
                <Dialog open={viewDescriptionOpen} onOpenChange={setViewDescriptionOpen}>
                  <DialogContent className="sm:max-w-2xl bg-white border-sky-100 rounded-2xl">
                    <DialogHeader>
                      <DialogTitle className="text-slate-800">{viewingTaskTitle || "Task Description"}</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-4">
                      <div className="space-y-2">
                        <Label className="text-slate-700">Description</Label>
                        {viewingTaskDescription && viewingTaskDescription.trim().length > 0 ? (
                          <div className="border-sky-200 rounded-xl p-4 bg-slate-50 min-h-[100px] max-h-[400px] overflow-y-auto whitespace-pre-wrap text-sm text-slate-700">
                            {viewingTaskDescription}
                          </div>
                        ) : (
                          <div className="border-sky-200 rounded-xl p-4 bg-slate-50 min-h-[100px] text-sm text-slate-500 italic">
                            No description provided.
                          </div>
                        )}
                      </div>
                      <div className="flex justify-end gap-2">
                        <Button 
                          variant="outline" 
                          onClick={() => setViewDescriptionOpen(false)}
                          className="rounded-xl border-sky-200"
                        >
                          Close
                        </Button>
                      </div>
                    </div>
                  </DialogContent>
                </Dialog>
                {isAdmin && (
                  <Dialog open={editProjectDueDateOpen} onOpenChange={setEditProjectDueDateOpen}>
                    <DialogContent className="sm:max-w-md">
                      <DialogHeader>
                        <DialogTitle>Edit Project Due Date</DialogTitle>
                      </DialogHeader>
                      <div className="space-y-4">
                        <div className="space-y-2">
                          <Label className="text-slate-700">Due Date</Label>
                          <Input
                            type="date"
                            value={editProjectDueDate}
                            onChange={(e) => setEditProjectDueDate(normalizeDueDateInput(e.target.value))}
                            className="border-sky-200 focus:border-sky-400 rounded-xl"
                          />
                        </div>
                        <div className="flex justify-end gap-2">
                          <Button variant="outline" onClick={() => setEditProjectDueDateOpen(false)} disabled={savingProjectDueDate} className="rounded-xl border-slate-200">
                            Cancel
                          </Button>
                          <Button
                            disabled={savingProjectDueDate}
                            onClick={async () => {
                              if (!project) return
                              setSavingProjectDueDate(true)
                              try {
                                const dueDateValue = editProjectDueDate.trim()
                                  ? new Date(editProjectDueDate).toISOString()
                                  : null
                                const res = await apiFetch(`/projects/${project.id}`, {
                                  method: "PATCH",
                                  headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify({ due_date: dueDateValue }),
                                })
                                if (!res.ok) {
                                  toast.error("Failed to update project due date")
                                  return
                                }
                                const updated = (await res.json()) as Project
                                setProject(updated)
                                setEditProjectDueDateOpen(false)
                                toast.success("Project due date updated")
                              } catch (err) {
                                console.error("Failed to update project due date", err)
                                toast.error("Failed to update project due date")
                              } finally {
                                setSavingProjectDueDate(false)
                              }
                            }}
                            className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl px-6"
                          >
                            {savingProjectDueDate ? "Saving..." : "Save"}
                          </Button>
                        </div>
                      </div>
                    </DialogContent>
                  </Dialog>
                )}
              </div>
              <Card className="bg-white/90 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl overflow-hidden p-0">
                <div className="divide-y divide-sky-100">
                  {visibleTasks.length ? (
                    visibleTasks.map((task, index) => {
                      // Get all assignees from the assignees array, fallback to assigned_to for backward compatibility
                      const assignees = task.assignees && task.assignees.length > 0
                        ? task.assignees
                        : (() => {
                            const assignedId = task.assigned_to || task.assigned_to_user_id || null
                            if (!assignedId) return []
                            const assignedUser = userMap.get(assignedId)
                            return assignedUser ? [{ id: assignedId, full_name: assignedUser.full_name, username: assignedUser.username, email: assignedUser.email }] : []
                          })()
                      const overdue = isOverdue(task)
                      const taskPriority = (task.priority as "HIGH" | "NORMAL") || "NORMAL"
                      const isHighPriority = taskPriority === "HIGH"
                      if (index === 0) {
                        console.log("Task priority debug:", { title: task.title, priority: task.priority, taskPriority, isHighPriority })
                      }
                      return (
                        <div
                          key={task.id}
                          className="grid grid-cols-5 gap-4 px-6 py-4 text-sm hover:bg-sky-50/30 transition-colors"
                        >
                          <div className="font-medium text-slate-800 flex items-center gap-2 flex-wrap min-w-0">
                            <span className="mr-2 text-xs font-semibold text-slate-400 shrink-0">{index + 1}.</span>
                            <span className="min-w-0 flex-1">
                              {task.ga_note_origin_id ? renderMarkedNoteContent(task.title, task.title) : task.title}
                            </span>
                            <Badge
                              variant="secondary"
                              className={`text-xs ${
                                isHighPriority
                                  ? "bg-red-100 text-red-700 border-red-200"
                                  : "bg-slate-100 text-slate-700 border-slate-200"
                              }`}
                            >
                              {taskPriority}
                            </Badge>
                            {task.is_1h_report ? (
                              <Badge variant="secondary" className="text-xs bg-amber-100 text-amber-700 border-amber-200">
                                1H
                              </Badge>
                            ) : null}
                            {task.is_r1 ? (
                              <Badge variant="secondary" className="text-xs bg-sky-100 text-sky-700 border-sky-200">
                                R1
                              </Badge>
                            ) : null}
                            {task.is_personal ? (
                              <Badge variant="secondary" className="text-xs bg-emerald-100 text-emerald-700 border-emerald-200">
                                P
                              </Badge>
                            ) : null}
                            {task.is_bllok ? (
                              <Badge variant="secondary" className="text-xs bg-slate-200 text-slate-700 border-slate-300">
                                BLLOK
                              </Badge>
                            ) : null}
                          </div>
                          <div className="flex items-center gap-1 flex-wrap">
                            {assignees.length > 0 ? (
                              assignees.map((assignee, idx) => {
                                const displayName = assignee.full_name || assignee.username || assignee.email || "-"
                                const initials = getInitials(displayName)
                                return (
                                  <Badge key={assignee.id || idx} variant="secondary" className="bg-blue-100 text-blue-700 border-blue-200 text-xs" title={displayName}>
                                    {initials}
                                  </Badge>
                                )
                              })
                            ) : (
                              <span className="text-slate-600">-</span>
                            )}
                          </div>
                          <div>
                            <Select
                              value={task.status || "TODO"}
                              onValueChange={(value) => void updateTaskStatus(task.id, value as Task["status"])}
                              disabled={updatingTaskId === task.id}
                            >
                              <SelectTrigger className="h-8 border-sky-200 focus:border-sky-400 rounded-xl">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {TASK_STATUSES.map((status) => {
                                  // Disable all non-DONE options if task is DONE and user is not admin
                                  const isDisabled = task.status === "DONE" && status !== "DONE" && user?.role !== "ADMIN"
                                  return (
                                    <SelectItem key={status} value={status} disabled={isDisabled}>
                                      {statusLabel(status)}
                                    </SelectItem>
                                  )
                                })}
                              </SelectContent>
                            </Select>
                          </div>
                          <div className="flex items-center gap-2 text-slate-500">
                            <span className={overdue ? "text-red-600 font-semibold" : undefined}>
                              {formatDateDisplay(task.due_date)}
                            </span>
                            {overdue ? (
                              <Badge variant="outline" className="border-red-200 text-red-700 bg-red-50">
                                Late
                              </Badge>
                            ) : null}
                          </div>
                          <div className="flex justify-end gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => startViewDescription(task)}
                              disabled={!task.description || task.description.trim().length === 0}
                              className="rounded-xl border-sky-200 hover:bg-sky-50 disabled:opacity-50 disabled:cursor-not-allowed"
                              title={!task.description || task.description.trim().length === 0 ? "No description available" : "View description"}
                            >
                              <Eye className="h-4 w-4 mr-1" />
                              View
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => startEditTask(task)}
                              className="rounded-xl border-sky-200"
                            >
                              Edit
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => void deleteTask(task.id, task.title)}
                              disabled={deletingTaskId === task.id}
                              className="rounded-xl border-red-200 text-red-600 hover:bg-red-50 hover:text-red-700"
                            >
                              {deletingTaskId === task.id ? "Deleting..." : "Delete"}
                            </Button>
                          </div>
                        </div>
                      )
                    })
                  ) : (
                    <div className="px-6 py-8 text-sm text-slate-500 text-center">No tasks yet.</div>
                  )}
                </div>
              </Card>
            </div>
          ) : null}

          {activeTab === "development-checklist" ? (
            <Card className="bg-white/90 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl overflow-hidden">
              <div className="p-6 space-y-6">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-xl font-semibold text-slate-800">Development checklist</div>
                    <div className="text-sm text-slate-500">Track custom development items for this project.</div>
                  </div>
                  <Dialog open={developmentChecklistCreateOpen} onOpenChange={setDevelopmentChecklistCreateOpen}>
                    <DialogTrigger asChild>
                      <Button className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl px-5">
                        + Add Item
                      </Button>
                    </DialogTrigger>
                    <DialogContent className="sm:max-w-lg bg-white border-sky-100 rounded-2xl">
                      <DialogHeader>
                        <DialogTitle className="text-slate-800">Add checklist item</DialogTitle>
                      </DialogHeader>
                      <div className="space-y-4">
                        <div className="space-y-2">
                          <Label className="text-slate-700">
                            Title <span className="text-red-500">*</span>
                          </Label>
                          <Input
                            value={developmentChecklistTitle}
                            onChange={(e) => setDevelopmentChecklistTitle(e.target.value)}
                            placeholder="Enter title..."
                            className="border-sky-200 focus:border-sky-400 rounded-xl"
                          />
                        </div>
                        <div className="space-y-2">
                          <Label className="text-slate-700">Comment / Notes</Label>
                          <Textarea
                            value={developmentChecklistComment}
                            onChange={(e) => setDevelopmentChecklistComment(e.target.value)}
                            placeholder="Add notes (optional)..."
                            rows={4}
                            className="border-sky-200 focus:border-sky-400 rounded-xl"
                          />
                        </div>
                        <div className="flex justify-end gap-2">
                          <Button
                            variant="outline"
                            onClick={() => setDevelopmentChecklistCreateOpen(false)}
                            className="rounded-xl border-sky-200"
                          >
                            Cancel
                          </Button>
                          <Button
                            disabled={developmentChecklistCreating}
                            onClick={() => void submitDevelopmentChecklistItem()}
                            className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl"
                          >
                            {developmentChecklistCreating ? "Saving..." : "Save"}
                          </Button>
                        </div>
                      </div>
                    </DialogContent>
                  </Dialog>
                </div>

                {developmentChecklistLoading ? (
                  <div className="text-sm text-slate-500">Loading checklist...</div>
                ) : developmentChecklistError ? (
                  <div className="text-sm text-red-600">{developmentChecklistError}</div>
                ) : developmentChecklistItems.length ? (
                  <div className="space-y-3">
                    {developmentChecklistItems.map((item) => {
                      const isEditing = developmentChecklistEditingId === item.id
                      return (
                        <div key={item.id} className="flex flex-wrap items-start gap-3 rounded-xl border border-sky-100 bg-white px-4 py-3 hover:bg-sky-50/30 transition-colors">
                          <Checkbox
                            checked={item.is_checked}
                            onCheckedChange={(checked) => toggleDevelopmentChecklistItem(item, Boolean(checked))}
                            className="mt-1"
                          />
                          <div className="flex-1 min-w-[200px]">
                            {isEditing ? (
                              <div className="space-y-2">
                                <Input
                                  value={developmentChecklistEditingTitle}
                                  onChange={(e) => setDevelopmentChecklistEditingTitle(e.target.value)}
                                  className="border-sky-200 focus:border-sky-400 rounded-xl"
                                />
                                <Textarea
                                  value={developmentChecklistEditingComment}
                                  onChange={(e) => setDevelopmentChecklistEditingComment(e.target.value)}
                                  rows={3}
                                  className="border-sky-200 focus:border-sky-400 rounded-xl"
                                />
                              </div>
                            ) : (
                              <>
                                <div className="font-semibold text-slate-800">{item.title}</div>
                                <div className="text-sm text-slate-500">
                                  {item.comment?.trim() ? item.comment : "No notes"}
                                </div>
                              </>
                            )}
                          </div>
                          <div className="flex items-center gap-2">
                            {isEditing ? (
                              <>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => void saveDevelopmentChecklistItem()}
                                  disabled={developmentChecklistSavingId === item.id}
                                  className="rounded-xl border-sky-200"
                                >
                                  {developmentChecklistSavingId === item.id ? "Saving..." : "Save"}
                                </Button>
                                <Button size="sm" variant="ghost" onClick={cancelEditDevelopmentChecklistItem}>
                                  Cancel
                                </Button>
                              </>
                            ) : (
                              <>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => startEditDevelopmentChecklistItem(item)}
                                  className="rounded-xl border-sky-200"
                                >
                                  Edit
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => void deleteDevelopmentChecklistItem(item.id)}
                                  disabled={developmentChecklistDeletingId === item.id}
                                  className="rounded-xl border-red-200 text-red-600 hover:bg-red-50"
                                >
                                  {developmentChecklistDeletingId === item.id ? "Deleting..." : "Delete"}
                                </Button>
                              </>
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <div className="text-sm text-slate-500">No checklist items yet. Add one.</div>
                )}
              </div>
            </Card>
          ) : null}

          {activeTab === "checklists" ? (
            <div className="space-y-4">
              {activePhase === "DOKUMENTIMI" ? (
                <Card className="bg-white/90 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl overflow-hidden">
                  <div className="p-6">
                    <div className="text-xl font-semibold text-slate-800 mb-6">Documentation Checklist</div>
                    <div className="space-y-3">
                      {documentationChecklist.length ? (
                        documentationChecklist.map((item, index) => {
                          const isEditing = documentationEditingId === item.id
                          return (
                            <div key={item.id} className="flex flex-wrap items-start gap-3 rounded-xl border border-sky-100 bg-white px-4 py-3 hover:bg-sky-50/30 transition-colors">
                              <div className="mt-1 text-xs font-semibold text-slate-400">{index + 1}.</div>
                              <Checkbox
                                checked={item.isChecked}
                                onCheckedChange={(checked) =>
                                  toggleDocumentationChecklistItemDb(item.id, Boolean(checked))
                                }
                                className="mt-1"
                              />
                              <div className="flex-1">
                                {isEditing ? (
                                  <Input
                                    value={documentationEditingText}
                                    onChange={(e) => setDocumentationEditingText(e.target.value)}
                                    className="border-sky-200 focus:border-sky-400 rounded-xl"
                                  />
                                ) : (
                                  <div className={item.isChecked ? "text-slate-400 line-through" : "text-slate-700"}>
                                    {item.question}
                                  </div>
                                )}
                              </div>
                              <div className="flex items-center gap-2">
                                {isEditing ? (
                                  <>
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={() => void saveDocumentationItem()}
                                      disabled={savingDocumentationItem}
                                      className="rounded-xl border-sky-200"
                                    >
                                      Save
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      onClick={cancelEditDocumentationItem}
                                    >
                                      Cancel
                                    </Button>
                                  </>
                                ) : (
                                  <>
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={() => startEditDocumentationItem(item.id)}
                                      className="rounded-xl border-sky-200"
                                    >
                                      Edit
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      className="rounded-xl border-red-200 text-red-600 hover:bg-red-50"
                                      onClick={() => void deleteDocumentationItem(item.id)}
                                    >
                                      Delete
                                    </Button>
                                  </>
                                )}
                              </div>
                            </div>
                          )
                        })
                      ) : (
                        <div className="text-sm text-slate-500">No documentation checklist items yet.</div>
                      )}
                      <div className="flex flex-wrap items-center gap-2">
                        <Input
                          value={newDocumentationText}
                          onChange={(e) => setNewDocumentationText(e.target.value)}
                          placeholder="Add documentation checklist item..."
                          className="flex-1 min-w-[220px] border-sky-200 focus:border-sky-400 rounded-xl"
                        />
                        <Button
                          variant="outline"
                          disabled={!newDocumentationText.trim() || savingDocumentationItem}
                          onClick={() => void addDocumentationChecklistItem()}
                          className="rounded-xl border-sky-200"
                        >
                          {savingDocumentationItem ? "Saving..." : "Add"}
                        </Button>
                      </div>
                    </div>
                    <div className="mt-6">
                      <div className="text-sm font-semibold text-slate-800 mb-3">Documentation File Paths</div>
                      <div className="flex items-center gap-2">
                        <Input
                          placeholder="Add file path..."
                          value={documentationFilePath}
                          onChange={(e) => setDocumentationFilePath(e.target.value)}
                          className="border-sky-200 focus:border-sky-400 rounded-xl"
                        />
                        <Button
                          variant="outline"
                          disabled={!documentationFilePath.trim()}
                          onClick={addDocumentationFilePath}
                          className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl"
                        >
                          Add
                        </Button>
                      </div>
                      {documentationFilePaths.length ? (
                        <div className="mt-4 space-y-2">
                          {documentationFilePaths.map((path, idx) => (
                            <div key={`${path}-${idx}`} className="flex items-center justify-between rounded-xl border border-sky-100 bg-sky-50/50 px-4 py-2 text-sm text-slate-700">
                              <span className="flex-1">{path}</span>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => void deleteDocumentationFilePath(path)}
                                className="ml-2 h-6 w-6 p-0 text-slate-400 hover:text-red-600"
                              >
                                ×
                              </Button>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="mt-3 text-sm text-slate-500">No file paths added.</div>
                      )}
                    </div>
                  </div>
                </Card>
              ) : (
                <>
                  <div className="flex items-center gap-2">
                    <Input
                      placeholder="Add item..."
                      value={newChecklistContent}
                      onChange={(e) => setNewChecklistContent(e.target.value)}
                      className="border-sky-200 focus:border-sky-400 rounded-xl"
                    />
                    <Button
                      variant="outline"
                      disabled={!newChecklistContent.trim() || addingChecklist}
                      onClick={() => void submitChecklistItem()}
                      className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl"
                    >
                      {addingChecklist ? "Adding..." : "Add"}
                    </Button>
                  </div>
                  {checklistItems.length ? (
                    checklistItems.map((item, index) => (
                      <Card
                        key={item.id}
                        className="cursor-pointer px-6 py-5 bg-white/90 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl hover:bg-sky-50/30 transition-all"
                        onClick={() => void toggleChecklistItem(item.id, !item.is_checked)}
                      >
                        <div className="flex items-center gap-3">
                          <Checkbox checked={item.is_checked ?? false} />
                          <div className={item.is_checked ? "text-slate-400 line-through" : "text-slate-700"}>
                            <span className="mr-2 text-xs font-semibold text-slate-400">{index + 1}.</span>
                            {(item as any).content || item.title}
                          </div>
                        </div>
                      </Card>
                    ))
                  ) : (
                    <div className="text-sm text-slate-500 text-center py-8">No checklist items yet.</div>
                  )}
                </>
              )}
            </div>
          ) : null}

          {activeTab === "members" ? (
            <div className="space-y-4">
              <div className="flex items-center justify-end">
                <Dialog open={membersOpen} onOpenChange={setMembersOpen}>
                  <DialogTrigger asChild>
                    <Button className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl px-6">
                      + Add Members
                    </Button>
                  </DialogTrigger>
                  <DialogContent className="sm:max-w-lg bg-white border-sky-100 rounded-2xl">
                    <DialogHeader>
                      <DialogTitle className="text-slate-800">Select Members</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-3">
                      {departmentUsers.length ? (
                        departmentUsers.map((u) => (
                          <div
                            key={u.id}
                            className="flex items-center justify-between rounded-xl border border-sky-100 bg-white px-4 py-3 hover:bg-sky-50/30 transition-colors cursor-pointer"
                            onClick={() => toggleMemberSelect(u.id)}
                          >
                            <div className="flex items-center gap-3">
                              <Checkbox checked={selectedMemberIds.includes(u.id)} />
                              <span className="text-slate-700">{u.full_name || u.username || u.email}</span>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="text-sm text-slate-500">No department users found.</div>
                      )}
                      <div className="flex justify-end gap-2 pt-2">
                        <Button variant="outline" onClick={() => setMembersOpen(false)} className="rounded-xl border-sky-200">
                          Cancel
                        </Button>
                        <Button
                          disabled={savingMembers || selectedMemberIds.length === 0}
                          onClick={() => void submitMembers()}
                          className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl"
                        >
                          {savingMembers ? "Saving..." : "Save"}
                        </Button>
                      </div>
                    </div>
                  </DialogContent>
                </Dialog>
              </div>
              <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
                {members.length ? (
                  members.map((m) => (
                    <Card key={m.id} className="flex flex-col items-center gap-3 text-center p-6 bg-white/90 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl hover:shadow-md transition-shadow">
                      <div className="h-20 w-20 rounded-full bg-gradient-to-br from-sky-100 to-blue-100 text-lg font-semibold text-sky-700 flex items-center justify-center shadow-sm">
                        {initials(m.full_name || m.username || m.email)}
                      </div>
                      <div className="text-sm font-semibold text-slate-800">{m.full_name || m.username || m.email}</div>
                    </Card>
                  ))
                ) : (
                  <div className="text-sm text-slate-500 text-center py-8 col-span-full">No members yet.</div>
                )}
              </div>
            </div>
          ) : null}

          {activeTab === "ga" ? (
            <div className="space-y-4">
              <Card className="bg-white/90 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl overflow-hidden">
                <div className="p-6 space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Select value={newGaNoteType} onValueChange={(value) => setNewGaNoteType(value as "GA" | "KA")}>
                      <SelectTrigger className="w-28 border-sky-200 focus:border-sky-400 rounded-xl">
                        <SelectValue placeholder="GA/KA" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="GA">GA</SelectItem>
                        <SelectItem value="KA">KA</SelectItem>
                      </SelectContent>
                    </Select>
                    <Select
                      value={newGaNotePriority}
                      onValueChange={(value) => setNewGaNotePriority(value as "__none__" | "NORMAL" | "HIGH")}
                    >
                      <SelectTrigger className="w-40 border-sky-200 focus:border-sky-400 rounded-xl">
                        <SelectValue placeholder="Priority" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="__none__">No priority</SelectItem>
                        <SelectItem value="NORMAL">Normal</SelectItem>

                        <SelectItem value="HIGH">High</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex items-start gap-2">
                    <Textarea
                      placeholder="Add GA/KA note..."
                      value={newGaNote}
                      onChange={(e) => setNewGaNote(e.target.value)}
                      rows={3}
                      className="border-sky-200 focus:border-sky-400 rounded-xl"
                    />
                    <Button
                      variant="outline"
                      disabled={!newGaNote.trim() || addingGaNote}
                      onClick={() => void submitGaNote()}
                      className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl"
                    >
                      {addingGaNote ? "Adding..." : "Add"}
                    </Button>
                  </div>
                </div>
              </Card>
              {gaNotes.length ? (
                gaNotes.map((note) => (
                  <Card key={note.id} className="bg-white/90 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl overflow-hidden p-5 hover:shadow-md transition-shadow">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="flex items-center gap-2 text-sm text-slate-600">
                        <Badge className={note.note_type === "KA" ? "bg-orange-100 text-orange-700 border-orange-200" : "bg-sky-100 text-sky-700 border-sky-200"}>
                          {note.note_type || "GA"}
                        </Badge>
                        <span>
                          From {userMap.get(note.created_by || "")?.full_name || userMap.get(note.created_by || "")?.username || "-"}
                        </span>
                        <span>• {formatDateTime(note.created_at)}</span>
                        {note.priority ? (
                          <Badge className="bg-slate-100 text-slate-700 border-slate-200">{statusLabel(note.priority)}</Badge>
                        ) : null}
                      </div>
                      {note.status !== "CLOSED" ? (
                        <Button variant="outline" size="sm" onClick={() => void closeGaNote(note.id)} className="rounded-xl border-sky-200 hover:bg-sky-50">
                          Close
                        </Button>
                      ) : (
                        <Badge className="bg-slate-100 text-slate-600 border-slate-200">Closed</Badge>
                      )}
                    </div>
                    <div className="mt-3 text-sm text-slate-700">{note.content}</div>
                  </Card>
                ))
              ) : (
                <div className="text-sm text-slate-500 text-center py-8">No GA/KA notes yet.</div>
              )}
            </div>
          ) : null}

          {activeTab === "prompts" ? (
            <div className="grid gap-6 md:grid-cols-2">
              <Card className="bg-white/90 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl overflow-hidden p-6 space-y-4">
                <div className="text-lg font-semibold text-slate-800">GA Prompt</div>
                <Input
                  value={gaPromptTitle}
                  onChange={(e) => setGaPromptTitle(e.target.value)}
                  placeholder="Enter prompt title..."
                  className="border-sky-200 focus:border-sky-400 rounded-xl"
                />
                <Textarea value={gaPromptContent} onChange={(e) => setGaPromptContent(e.target.value)} rows={8} className="border-sky-200 focus:border-sky-400 rounded-xl" placeholder="Enter prompt content..." />
                <div className="flex justify-end">
                  <Button
                    variant="outline"
                    disabled={savingGaPrompt}
                    onClick={() => void savePrompt("GA_PROMPT")}
                    className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl px-6"
                  >
                    {savingGaPrompt ? "Saving..." : "Save"}
                  </Button>
                </div>
                <div className="text-xs text-slate-500">Used for GA guidelines and standards.</div>
                {prompts.filter((p) => p.type === "GA_PROMPT").length ? (
                  <div className="space-y-3 pt-2">
                    {prompts
                      .filter((p) => p.type === "GA_PROMPT")
                      .map((prompt) => {
                        const isExpanded = expandedPrompts.has(prompt.id)
                        return (
                          <Card
                            key={prompt.id}
                            className="border border-sky-100 bg-sky-50/30 p-4 rounded-xl cursor-pointer hover:bg-sky-50/50 transition-colors"
                            onClick={() => togglePromptExpanded(prompt.id)}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <div className="flex-1">
                                <div className="font-medium text-slate-800 mb-1">{prompt.title || "Untitled"}</div>
                                <div className="text-xs text-slate-500">
                                  {formatDateTimeDMY(prompt.created_at)}
                                </div>
                                {isExpanded ? (
                                  <div className="mt-3 text-sm text-slate-700 whitespace-pre-wrap">{prompt.content}</div>
                                ) : (
                                  <div className="mt-2 text-xs text-sky-600 hover:text-sky-700">Click to view description</div>
                                )}
                              </div>
                            </div>
                          </Card>
                        )
                      })}
                  </div>
                ) : null}
              </Card>
              <Card className="bg-white/90 backdrop-blur-sm border-sky-100 shadow-sm rounded-2xl overflow-hidden p-6 space-y-4">
                <div className="text-lg font-semibold text-slate-800">Development Prompt</div>
                <Input
                  value={devPromptTitle}
                  onChange={(e) => setDevPromptTitle(e.target.value)}
                  placeholder="Enter prompt title..."
                  className="border-sky-200 focus:border-sky-400 rounded-xl"
                />
                <Textarea value={devPromptContent} onChange={(e) => setDevPromptContent(e.target.value)} rows={8} className="border-sky-200 focus:border-sky-400 rounded-xl" placeholder="Enter prompt content..." />
                <div className="flex justify-end">
                  <Button
                    variant="outline"
                    disabled={savingDevPrompt}
                    onClick={() => void savePrompt("ZHVILLIM_PROMPT")}
                    className="bg-sky-500 hover:bg-sky-600 text-white border-0 shadow-md shadow-sky-200/50 rounded-xl px-6"
                  >
                    {savingDevPrompt ? "Saving..." : "Save"}
                  </Button>
                </div>
                <div className="text-xs text-slate-500">Used by the development team.</div>
                {prompts.filter((p) => p.type === "ZHVILLIM_PROMPT").length ? (
                  <div className="space-y-3 pt-2">
                    {prompts
                      .filter((p) => p.type === "ZHVILLIM_PROMPT")
                      .map((prompt) => {
                        const isExpanded = expandedPrompts.has(prompt.id)
                        return (
                          <Card
                            key={prompt.id}
                            className="border border-sky-100 bg-sky-50/30 p-4 rounded-xl cursor-pointer hover:bg-sky-50/50 transition-colors"
                            onClick={() => togglePromptExpanded(prompt.id)}
                          >
                            <div className="flex items-start justify-between gap-2">
                              <div className="flex-1">
                                <div className="font-medium text-slate-800 mb-1">{prompt.title || "Untitled"}</div>
                                <div className="text-xs text-slate-500">
                                  {formatDateTimeDMY(prompt.created_at)}
                                </div>
                                {isExpanded ? (
                                  <div className="mt-3 text-sm text-slate-700 whitespace-pre-wrap">{prompt.content}</div>
                                ) : (
                                  <div className="mt-2 text-xs text-sky-600 hover:text-sky-700">Click to view description</div>
                                )}
                              </div>
                            </div>
                          </Card>
                        )
                      })}
                  </div>
                ) : null}
              </Card>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
