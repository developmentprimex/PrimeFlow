"use client"

import { ProjectActivityControl } from "@/components/project-activity"

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
import { TaskSkillField } from "@/components/task-skill-field"
import { TaskOneHMarker } from "@/components/task-one-h-marker"
import { TaskMarkerComment } from "@/components/task-marker-comment"
import { ChevronDown, Eye, Pencil } from "lucide-react"
import { BoldOnlyEditor } from "@/components/bold-only-editor"
import { useAuth } from "@/lib/auth"
import { formatDateDMY, formatDateTimeDMY, normalizeDueDateInput, toDateInputValue } from "@/lib/dates"
import { getConfirmerCandidates, isWaitingConfirmation, validateWaitingConfirmation } from "@/lib/task-confirmation"
import { SKILL_CATEGORIES } from "@/lib/skills"
import type {
  ChecklistItem,
  Department,
  GaNote,
  Meeting,
  Project,
  ProjectPhaseChecklistItem,
  ProjectPrompt,
  SkillCategory,
  Task,
  TaskFinishPeriod,
  User,
} from "@/lib/types"

const GENERAL_PHASES = ["MEETINGS", "PLANNING", "DEVELOPMENT", "TESTING", "DOCUMENTATION"] as const
const MST_PHASES = ["PLANNING", "PRODUCT", "CONTROL", "FINAL"] as const

const PHASE_LABELS: Record<string, string> = {
  MEETINGS: "Meetings",
  PLANNING: "Planning",
  DEVELOPMENT: "Development",
  TESTING: "Testing",
  DOCUMENTATION: "Documentation",
  PRODUCT: "Product",
  CONTROL: "Control",
  FINAL: "Final",
  CLOSED: "Closed",
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
  { id: "testing", label: "Testing" },
  { id: "tasks", label: "Tasks" },
  { id: "development-checklist", label: "Checklist" },
  { id: "checklists", label: "Checklists" },
  { id: "mst-acceptance", label: "Project Acceptance" },
  { id: "mst-ga-meeting", label: "GA Meeting" },
  { id: "members", label: "Members" },
  { id: "ga", label: "GA/KA Notes" },
  { id: "prompts", label: "Prompts" },
] as const

const MEETING_TABS = [
  { id: "meeting-focus", label: "Meeting Focus" },
  { id: "meeting-checklist", label: "Checklist" },
] as const

type TabId = (typeof TABS)[number]["id"] | (typeof MEETING_TABS)[number]["id"]

type TaskChecklist = {
  id: string
  title?: string | null
  task_id?: string | null
  items: ChecklistItem[]
}

const TASK_STATUSES = ["TODO", "IN_PROGRESS", "WAITING_CLIENT", "WAITING_CONFIRMATION", "DONE"] as const
const TASK_PRIORITIES = ["NORMAL", "HIGH"] as const
const PROJECT_TASK_TYPES = ["NORMAL", "HIGH", "1H", "R1", "PERSONAL", "BLLOK"] as const
const FINISH_PERIOD_OPTIONS: TaskFinishPeriod[] = ["AM", "PM"]
const FINISH_PERIOD_NONE_VALUE = "__none__"
const FINISH_PERIOD_NONE_LABEL = "None (all day)"
const ALL_USERS_FILTER = "__all__"
const ME_FILTER = "__me__"
const TASK_STATUS_LABELS: Record<(typeof TASK_STATUSES)[number], string> = {
  TODO: "To Do",
  IN_PROGRESS: "In Progress",
  WAITING_CLIENT: "WFE",
  WAITING_CONFIRMATION: "Waiting Confirmation",
  DONE: "Done",
}

function getProjectTaskType(task: Task | null): (typeof PROJECT_TASK_TYPES)[number] {
  if (!task) return "NORMAL"
  if (task.is_1h_report) return "1H"
  if (task.is_r1) return "R1"
  if (task.is_personal) return "PERSONAL"
  if (task.is_bllok) return "BLLOK"
  return task.priority === "HIGH" ? "HIGH" : "NORMAL"
}

const MEETING_FOCUS_POINTS = [
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
const TESTING_CHECKLIST_QUESTIONS = [
  "What should we test and why?",
  "Who owns each test area?",
  "What environments or data are required?",
  "How will issues be tracked and fixed?",
  "What is the acceptance checklist to approve?",
]

const MST_PLANNING_ACCEPTANCE_GROUP_KEY = "MST_PLANNING_ACCEPTANCE"
const MST_PLANNING_GA_MEETING_GROUP_KEY = "MST_PLANNING_GA_MEETING"

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

function matchesAssignee(task: Task, filterId: string, currentUserId?: string | null) {
  if (filterId === ALL_USERS_FILTER) return true
  const resolvedId = filterId === ME_FILTER ? currentUserId : filterId
  if (!resolvedId) return true
  if (task.assigned_to === resolvedId || task.assigned_to_user_id === resolvedId) return true
  if (task.assignees?.some((assignee) => assignee.id === resolvedId)) return true
  return false
}

function statusLabel(status?: string) {
  if (!status) return "-"
  if (status === "WAITING_CLIENT") return "WFE"
  return status
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/(^\w|\s\w)/g, (m) => m.toUpperCase())
}

function formatErrorDetail(detail: unknown) {
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        item && typeof item === "object" && "msg" in item
          ? (item as { msg?: string }).msg
          : String(item)
      )
      .filter(Boolean)
      .join(", ")
  }
  if (detail && typeof detail === "object" && "msg" in detail) {
    return String((detail as { msg?: string }).msg || "An error occurred")
  }
  return "An error occurred"
}

function formatDateTime(value?: string | null) {
  return formatDateTimeDMY(value)
}

function getTaskSortDate(task: Task): number | null {
  const start = task.start_date ? new Date(task.start_date) : null
  if (start && !Number.isNaN(start.getTime())) return start.getTime()
  const created = task.created_at ? new Date(task.created_at) : null
  if (created && !Number.isNaN(created.getTime())) return created.getTime()
  return null
}

async function initializeMeetingChecklistItems(
  projectId: string,
  existingItems: ChecklistItem[],
  apiFetch: (url: string, options?: RequestInit) => Promise<Response>
) {
  const existingTitles = new Set(
    existingItems
      .filter((item) => item.path === "MEETINGS" && item.item_type === "CHECKBOX")
      .map((item) => (item.title || "").trim().toLowerCase())
      .filter(Boolean)
  )
  const missing = MEETING_CHECKLIST_ITEMS.filter(
    (title) => !existingTitles.has(title.trim().toLowerCase())
  )
  if (!missing.length) return
  for (const title of missing) {
    const position = MEETING_CHECKLIST_ITEMS.indexOf(title)
    const res = await apiFetch("/checklist-items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: projectId,
        item_type: "CHECKBOX",
        path: "MEETINGS",
        title,
        is_checked: false,
        position: position >= 0 ? position + 1 : null,
      }),
    })
    if (!res.ok) {
      console.error("Failed to create meeting checklist item", title)
    }
  }
}

async function initializeMeetingFocusItems(
  projectId: string,
  existingItems: ChecklistItem[],
  apiFetch: (url: string, options?: RequestInit) => Promise<Response>
) {
  const existingComments = new Set(
    existingItems
      .filter((item) => item.path === "MEETING_FOCUS" && item.item_type === "COMMENT")
      .map((item) => (item.comment || "").trim().toLowerCase())
      .filter(Boolean)
  )
  const missing = MEETING_FOCUS_POINTS.filter(
    (text) => !existingComments.has(text.trim().toLowerCase())
  )
  if (!missing.length) return
  for (const text of missing) {
    const position = MEETING_FOCUS_POINTS.indexOf(text)
    const res = await apiFetch("/checklist-items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: projectId,
        item_type: "COMMENT",
        path: "MEETING_FOCUS",
        comment: text,
        position: position >= 0 ? position + 1 : null,
      }),
    })
    if (!res.ok) {
      console.error("Failed to create meeting focus item", text)
    }
  }
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

async function initializeTestingChecklistItems(
  projectId: string,
  existingItems: ChecklistItem[],
  apiFetch: (url: string, options?: RequestInit) => Promise<Response>
) {
  const existingTitles = new Set(
    existingItems
      .filter((item) => item.path === "TESTING" && item.item_type === "CHECKBOX")
      .map((item) => (item.title || "").trim().toLowerCase())
      .filter(Boolean)
  )
  const missing = TESTING_CHECKLIST_QUESTIONS.filter(
    (title) => !existingTitles.has(title.trim().toLowerCase())
  )
  if (!missing.length) return
  for (const title of missing) {
    const position = TESTING_CHECKLIST_QUESTIONS.indexOf(title)
    const res = await apiFetch("/checklist-items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: projectId,
        item_type: "CHECKBOX",
        path: "TESTING",
        title,
        is_checked: false,
        position: position >= 0 ? position + 1 : null,
      }),
    })
    if (!res.ok) {
      console.error("Failed to create testing checklist item", title)
    }
  }
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

export default function ProjectPage() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const projectId = String(params.id)
  const { apiFetch, user } = useAuth()
  const confirm = useConfirm()

  const [project, setProject] = React.useState<Project | null>(null)
  const [tasks, setTasks] = React.useState<Task[]>([])
  const [taskAssigneeFilter, setTaskAssigneeFilter] = React.useState<string>(ALL_USERS_FILTER)
  const [departmentUsers, setDepartmentUsers] = React.useState<User[]>([])
  const [allUsers, setAllUsers] = React.useState<User[]>([])
  const [projectDepartmentName, setProjectDepartmentName] = React.useState<string | null>(null)
  const [members, setMembers] = React.useState<User[]>([])
  const [checklistItems, setChecklistItems] = React.useState<ChecklistItem[]>([])
  const [gaNotes, setGaNotes] = React.useState<GaNote[]>([])
  const [prompts, setPrompts] = React.useState<ProjectPrompt[]>([])
  const [meetings, setMeetings] = React.useState<Meeting[]>([])
  const [activeTab, setActiveTab] = React.useState<TabId>("description")
  const [taskChecklistOpen, setTaskChecklistOpen] = React.useState<Record<string, boolean>>({})
  const [taskChecklistLoading, setTaskChecklistLoading] = React.useState<Record<string, boolean>>({})
  const [taskChecklists, setTaskChecklists] = React.useState<Record<string, TaskChecklist | null>>({})
  const [taskChecklistInputs, setTaskChecklistInputs] = React.useState<Record<string, string>>({})
  const [taskChecklistSaving, setTaskChecklistSaving] = React.useState<Record<string, boolean>>({})
  const [taskChecklistItemBusy, setTaskChecklistItemBusy] = React.useState<Record<string, boolean>>({})
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
  const [newSkillCategory, setNewSkillCategory] = React.useState<SkillCategory | null>(null)
  const [newTaskPhase, setNewTaskPhase] = React.useState<string>("")
  const [newStartDate, setNewStartDate] = React.useState("")
  const [newDueDate, setNewDueDate] = React.useState("")
  const [newDeadlineImportant, setNewDeadlineImportant] = React.useState(false)
  const [newFinishPeriod, setNewFinishPeriod] = React.useState<TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE>(
    FINISH_PERIOD_NONE_VALUE
  )
  const [creating, setCreating] = React.useState(false)
  const [editOpen, setEditOpen] = React.useState(false)
  const [editingTaskId, setEditingTaskId] = React.useState<string | null>(null)
  const [editTitle, setEditTitle] = React.useState("")
  const [editDescription, setEditDescription] = React.useState("")
  const [viewDescriptionOpen, setViewDescriptionOpen] = React.useState(false)
  const [viewingTaskTitle, setViewingTaskTitle] = React.useState("")
  const [viewingTaskDescription, setViewingTaskDescription] = React.useState("")
  const [editStatus, setEditStatus] = React.useState<(typeof TASK_STATUSES)[number]>("TODO")
  const [editTaskType, setEditTaskType] = React.useState<(typeof PROJECT_TASK_TYPES)[number]>("NORMAL")
  const [editAssignees, setEditAssignees] = React.useState<string[]>([])
  const [editSkillCategory, setEditSkillCategory] = React.useState<SkillCategory | null>(null)
  const [editPhase, setEditPhase] = React.useState<string>("")
  const [editStartDate, setEditStartDate] = React.useState("")
  const [editDueDate, setEditDueDate] = React.useState("")
  const [editFinishPeriod, setEditFinishPeriod] = React.useState<TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE>(
    FINISH_PERIOD_NONE_VALUE
  )
  const [editDeadlineImportant, setEditDeadlineImportant] = React.useState(false)
  const [savingEdit, setSavingEdit] = React.useState(false)
  const [updatingTaskId, setUpdatingTaskId] = React.useState<string | null>(null)
  const [pendingStatusTaskId, setPendingStatusTaskId] = React.useState<string | null>(null)
  const [pendingStatusValue, setPendingStatusValue] = React.useState<Task["status"]>("TODO")
  const [pendingConfirmationAssigneeId, setPendingConfirmationAssigneeId] = React.useState("")
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
  const [meetingChecklist, setMeetingChecklist] = React.useState<
    { id: string; content: string; answer: string; isChecked: boolean; position: number }[]
  >([])
  const [meetingChecklistNewNumber, setMeetingChecklistNewNumber] = React.useState("")
  const [newMeetingItemContent, setNewMeetingItemContent] = React.useState("")
  const [newMeetingItemAnswer, setNewMeetingItemAnswer] = React.useState("")
  const [addingMeetingItem, setAddingMeetingItem] = React.useState(false)
  const [editingMeetingItemId, setEditingMeetingItemId] = React.useState<string | null>(null)
  const [editingMeetingItemContent, setEditingMeetingItemContent] = React.useState("")
  const [editingMeetingItemAnswer, setEditingMeetingItemAnswer] = React.useState("")
  const [editingMeetingItemNumber, setEditingMeetingItemNumber] = React.useState("")
  const [meetingFocusItems, setMeetingFocusItems] = React.useState<
    { id: string; text: string; position: number }[]
  >([])
  const [newMeetingFocusText, setNewMeetingFocusText] = React.useState("")
  const [meetingFocusNewNumber, setMeetingFocusNewNumber] = React.useState("")
  const [meetingFocusEditingId, setMeetingFocusEditingId] = React.useState<string | null>(null)
  const [meetingFocusEditingText, setMeetingFocusEditingText] = React.useState("")
  const [meetingFocusEditingNumber, setMeetingFocusEditingNumber] = React.useState("")
  const [savingMeetingFocusItem, setSavingMeetingFocusItem] = React.useState(false)
  const [mstAcceptanceChecklist, setMstAcceptanceChecklist] = React.useState<ChecklistItem[]>([])
  const [mstGaMeetingChecklist, setMstGaMeetingChecklist] = React.useState<ChecklistItem[]>([])
  const [mstAcceptanceNewText, setMstAcceptanceNewText] = React.useState("")
  const [mstAcceptanceNewNumber, setMstAcceptanceNewNumber] = React.useState("")
  const [mstAcceptanceEditingId, setMstAcceptanceEditingId] = React.useState<string | null>(null)
  const [mstAcceptanceEditingText, setMstAcceptanceEditingText] = React.useState("")
  const [mstAcceptanceSaving, setMstAcceptanceSaving] = React.useState(false)
  const [mstGaMeetingNewText, setMstGaMeetingNewText] = React.useState("")
  const [mstGaMeetingNewNumber, setMstGaMeetingNewNumber] = React.useState("")
  const [mstGaMeetingEditingId, setMstGaMeetingEditingId] = React.useState<string | null>(null)
  const [mstGaMeetingEditingText, setMstGaMeetingEditingText] = React.useState("")
  const [mstGaMeetingSaving, setMstGaMeetingSaving] = React.useState(false)
  const [mstAcceptanceCommentEditingId, setMstAcceptanceCommentEditingId] = React.useState<string | null>(null)
  const [mstAcceptanceCommentText, setMstAcceptanceCommentText] = React.useState("")
  const [mstGaMeetingCommentEditingId, setMstGaMeetingCommentEditingId] = React.useState<string | null>(null)
  const [mstGaMeetingCommentText, setMstGaMeetingCommentText] = React.useState("")
  const [testingChecklist, setTestingChecklist] = React.useState<
    { id: string; question: string; isChecked: boolean; position?: number }[]
  >([])
  const [testingEditingId, setTestingEditingId] = React.useState<string | null>(null)
  const [testingEditingText, setTestingEditingText] = React.useState("")
  const [testingEditingNumber, setTestingEditingNumber] = React.useState("")
  const [newTestingNumber, setNewTestingNumber] = React.useState("")
  const [newTestingText, setNewTestingText] = React.useState("")
  const [savingTestingItem, setSavingTestingItem] = React.useState(false)
  const [documentationChecklist, setDocumentationChecklist] = React.useState<
    { id: string; question: string; isChecked: boolean; position?: number }[]
  >(
    DOCUMENTATION_CHECKLIST_QUESTIONS.map((question, index) => ({
      id: `doc-${index}`,
      question,
      isChecked: false,
      position: index + 1,
    }))
  )
  const [documentationEditingId, setDocumentationEditingId] = React.useState<string | null>(null)
  const [documentationEditingText, setDocumentationEditingText] = React.useState("")
  const [documentationEditingNumber, setDocumentationEditingNumber] = React.useState("")
  const [newDocumentationNumber, setNewDocumentationNumber] = React.useState("")
  const [newDocumentationText, setNewDocumentationText] = React.useState("")
  const [savingDocumentationItem, setSavingDocumentationItem] = React.useState(false)
  const [documentationFilePath, setDocumentationFilePath] = React.useState("")
  const [documentationFilePaths, setDocumentationFilePaths] = React.useState<
    { id: string; path: string }[]
  >([])
  const [documentationFilePathEditingId, setDocumentationFilePathEditingId] = React.useState<
    string | null
  >(null)
  const [documentationFilePathEditingText, setDocumentationFilePathEditingText] = React.useState("")

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
  const [documentationFilePathSaving, setDocumentationFilePathSaving] = React.useState(false)
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

      const [tRes, mRes, cRes, gRes, prRes, usersRes, meetingsRes, depsRes] = await Promise.all([
        apiFetch(`/tasks?project_id=${p.id}&include_done=true`),
        apiFetch(`/project-members?project_id=${p.id}`),
        apiFetch(`/checklist-items?project_id=${p.id}`),
        apiFetch(`/ga-notes?project_id=${p.id}`),
        apiFetch(`/project-prompts?project_id=${p.id}`),
        apiFetch("/users?include_all_departments=true"),
        apiFetch(`/meetings?project_id=${p.id}`),
        apiFetch("/departments"),
      ])

      if (tRes.ok) setTasks((await tRes.json()) as Task[])
      if (mRes.ok) setMembers((await mRes.json()) as User[])
      if (cRes.ok) {
        const items = (await cRes.json()) as ChecklistItem[]
        setChecklistItems(items)
        try {
          await initializeMeetingChecklistItems(p.id, items, apiFetch)
          await initializeMeetingFocusItems(p.id, items, apiFetch)
          await initializeDocumentationChecklistItems(p.id, items, apiFetch)
          await initializeTestingChecklistItems(p.id, items, apiFetch)
          const reloadRes = await apiFetch(`/checklist-items?project_id=${p.id}`)
          if (reloadRes.ok) {
            setChecklistItems((await reloadRes.json()) as ChecklistItem[])
          }
        } catch (error) {
          console.error("Failed to initialize meeting checklist items:", error)
        }
      }
      if (gRes.ok) setGaNotes((await gRes.json()) as GaNote[])
      if (prRes.ok) setPrompts((await prRes.json()) as ProjectPrompt[])
      if (meetingsRes.ok) setMeetings((await meetingsRes.json()) as Meeting[])
      if (depsRes.ok) {
        const deps = (await depsRes.json()) as Department[]
        const dep = deps.find((d) => d.id === p.department_id) || null
        setProjectDepartmentName(dep?.name ?? null)
      }
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
      const titleUpper = (project.title || project.name || "").toUpperCase()
      const isMst = project.project_type === "MST" || titleUpper.includes("MST")
      setViewedPhase(isMst ? "FINAL" : "DOCUMENTATION")
      return
    }
    setViewedPhase(project.current_phase)
  }, [project?.current_phase, project?.name, project?.project_type, project?.title])

  React.useEffect(() => {
    if (!prompts.length) return
  }, [prompts])

  React.useEffect(() => {
    const meetingItems = checklistItems.filter(
      (item) => item.path === "MEETINGS" && item.item_type === "CHECKBOX"
    )
    if (!meetingItems.length) {
      setMeetingChecklist([])
      return
    }
    const sorted = meetingItems
      .slice()
      .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
    const seenTitles = new Set<string>()
    const deduped = sorted.filter((item) => {
      const key = (item.title || "").trim().toLowerCase()
      if (!key) return true
      if (seenTitles.has(key)) return false
      seenTitles.add(key)
      return true
    })
    setMeetingChecklist(
      deduped.map((item, index) => ({
        id: item.id,
        content: item.title || "",
        answer: item.comment || "",
        isChecked: Boolean(item.is_checked),
        position: item.position ?? index + 1,
      }))
    )
  }, [checklistItems])

  React.useEffect(() => {
    const focusItems = checklistItems
      .filter((item) => item.path === "MEETING_FOCUS" && item.item_type === "COMMENT")
      .slice()
      .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
    if (!focusItems.length) {
      setMeetingFocusItems([])
      return
    }
    setMeetingFocusItems(
      focusItems.map((item, index) => ({
        id: item.id,
        text: item.comment || "",
        position: item.position ?? index + 1,
      }))
    )
  }, [checklistItems])

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

  React.useEffect(() => {
    const filePathItems = checklistItems
      .filter(
        (item) =>
          item.path === "DOCUMENTATION" &&
          item.item_type === "COMMENT" &&
          item.category === "FILE_PATH"
      )
      .slice()
      .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
    setDocumentationFilePaths(
      filePathItems
        .map((item) => ({ id: item.id, path: item.comment || "" }))
        .filter((item) => item.path)
    )
  }, [checklistItems])

  React.useEffect(() => {
    const items = checklistItems
      .filter((item) => item.path === "TESTING" && item.item_type === "CHECKBOX")
      .slice()
      .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
    if (!items.length) return
    setTestingChecklist(
      items.map((item, index) => ({
        id: item.id,
        question: item.title || "",
        isChecked: Boolean(item.is_checked),
        position: item.position ?? index + 1,
      }))
    )
  }, [checklistItems])

  React.useEffect(() => {
    if (!membersOpen) return
    setSelectedMemberIds(members.map((m) => m.id))
  }, [membersOpen, members])

  React.useEffect(() => {
    if (!createOpen) return
    if (newTaskPhase) return
    const phaseValue = viewedPhase || project?.current_phase || "MEETINGS"
    setNewTaskPhase(phaseValue)
  }, [createOpen, newTaskPhase, project?.current_phase, viewedPhase])

  const canEditTaskChecklist = React.useMemo(() => {
    if (!user || !project?.department_id) return false
    if (user.role === "ADMIN" || user.role === "MANAGER") return true
    return user.department_id === project.department_id
  }, [user, project?.department_id])

  const canUncheckTaskChecklist = React.useMemo(() => {
    return user?.role === "ADMIN" || user?.role === "MANAGER"
  }, [user?.role])

  const loadTaskChecklist = React.useCallback(
    async (taskId: string) => {
      setTaskChecklistLoading((prev) => ({ ...prev, [taskId]: true }))
      try {
        const res = await apiFetch(`/checklists?task_id=${taskId}&include_items=true`)
        if (!res.ok) {
          let detail = "Failed to load checklist"
          try {
            const data = (await res.json()) as { detail?: string }
            if (data?.detail) detail = data.detail
          } catch {
            // ignore
          }
          toast.error(typeof detail === "string" ? detail : "Failed to load checklist")
          return
        }
        const data = (await res.json()) as TaskChecklist[]
        const checklist = data.length ? data[0] : null
        setTaskChecklists((prev) => ({ ...prev, [taskId]: checklist }))
      } catch (error) {
        console.error("Failed to load task checklist", error)
        toast.error("Failed to load checklist")
      } finally {
        setTaskChecklistLoading((prev) => ({ ...prev, [taskId]: false }))
      }
    },
    [apiFetch]
  )

  const isChecklistComplete = React.useCallback(
    (taskId: string) => {
      const checklist = taskChecklists[taskId]
      if (!checklist?.items?.length) return true
      const checkboxItems = checklist.items.filter((item) => item.item_type === "CHECKBOX")
      if (checkboxItems.length === 0) return true
      return checkboxItems.every((item) => Boolean(item.is_checked))
    },
    [taskChecklists]
  )

  const toggleTaskChecklist = async (taskId: string) => {
    const next = !taskChecklistOpen[taskId]
    setTaskChecklistOpen((prev) => ({ ...prev, [taskId]: next }))
    if (next && taskChecklists[taskId] === undefined) {
      await loadTaskChecklist(taskId)
    }
  }

  const addTaskChecklistItem = async (taskId: string) => {
    const content = (taskChecklistInputs[taskId] || "").trim()
    if (!content || !canEditTaskChecklist) return
    setTaskChecklistSaving((prev) => ({ ...prev, [taskId]: true }))
    try {
      let checklist = taskChecklists[taskId] || null
      if (!checklist) {
        const createRes = await apiFetch("/checklists", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            task_id: taskId,
            title: "Task Checklist",
          }),
        })
        if (!createRes.ok) {
          let detail = "Failed to create checklist"
          try {
            const data = (await createRes.json()) as { detail?: string }
            if (data?.detail) detail = data.detail
          } catch {
            // ignore
          }
          toast.error(typeof detail === "string" ? detail : "Failed to create checklist")
          return
        }
        const created = (await createRes.json()) as { id: string; title?: string | null; task_id?: string | null }
        checklist = { id: created.id, title: created.title, task_id: created.task_id, items: [] }
      }

      const position = checklist.items.length
      const itemRes = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          checklist_id: checklist.id,
          item_type: "CHECKBOX",
          title: content,
          is_checked: false,
          position,
        }),
      })
      if (!itemRes.ok) {
        let detail = "Failed to add checklist item"
        try {
          const data = (await itemRes.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(typeof detail === "string" ? detail : "Failed to add checklist item")
        return
      }
      const createdItem = (await itemRes.json()) as ChecklistItem
      const updatedChecklist: TaskChecklist = {
        ...(checklist || { id: createdItem.checklist_id || "", items: [] }),
        items: [...(checklist?.items || []), createdItem],
      }
      setTaskChecklists((prev) => ({ ...prev, [taskId]: updatedChecklist }))
      setTaskChecklistInputs((prev) => ({ ...prev, [taskId]: "" }))
    } finally {
      setTaskChecklistSaving((prev) => ({ ...prev, [taskId]: false }))
    }
  }

  const toggleTaskChecklistItem = async (taskId: string, item: ChecklistItem, checked: boolean) => {
    if (!canEditTaskChecklist) return
    const previousChecked = Boolean(item.is_checked)
    if (previousChecked && !checked && !canUncheckTaskChecklist) return
    if (previousChecked === checked) return
    setTaskChecklists((prev) => {
      const checklist = prev[taskId]
      if (!checklist) return prev
      const items = checklist.items.map((i) => (i.id === item.id ? { ...i, is_checked: checked } : i))
      return { ...prev, [taskId]: { ...checklist, items } }
    })
    setTaskChecklistItemBusy((prev) => ({ ...prev, [item.id]: true }))
    try {
      const res = await apiFetch(`/checklist-items/${item.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_checked: checked }),
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
        setTaskChecklists((prev) => {
          const checklist = prev[taskId]
          if (!checklist) return prev
          const items = checklist.items.map((i) => (i.id === item.id ? { ...i, is_checked: previousChecked } : i))
          return { ...prev, [taskId]: { ...checklist, items } }
        })
        return
      }
      setTaskChecklists((prev) => {
        const checklist = prev[taskId]
        if (!checklist) return prev
        const items = checklist.items.map((i) => (i.id === item.id ? { ...i, is_checked: checked } : i))
        return { ...prev, [taskId]: { ...checklist, items } }
      })
    } catch (error) {
      console.error("Failed to update checklist item", error)
      toast.error("Failed to update checklist item")
      setTaskChecklists((prev) => {
        const checklist = prev[taskId]
        if (!checklist) return prev
        const items = checklist.items.map((i) => (i.id === item.id ? { ...i, is_checked: previousChecked } : i))
        return { ...prev, [taskId]: { ...checklist, items } }
      })
    } finally {
      setTaskChecklistItemBusy((prev) => ({ ...prev, [item.id]: false }))
    }
  }

  const deleteTaskChecklistItem = async (taskId: string, item: ChecklistItem) => {
    if (!canEditTaskChecklist) return
    setTaskChecklistItemBusy((prev) => ({ ...prev, [item.id]: true }))
    try {
      const res = await apiFetch(`/checklist-items/${item.id}`, { method: "DELETE" })
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
      setTaskChecklists((prev) => {
        const checklist = prev[taskId]
        if (!checklist) return prev
        const items = checklist.items.filter((i) => i.id !== item.id)
        return { ...prev, [taskId]: { ...checklist, items } }
      })
    } finally {
      setTaskChecklistItemBusy((prev) => ({ ...prev, [item.id]: false }))
    }
  }

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
        skill_category: newSkillCategory,
        status: newStatus,
        priority: newTaskType === "HIGH" ? "HIGH" : "NORMAL",
        is_1h_report: newTaskType === "1H",
        is_r1: newTaskType === "R1",
        is_personal: newTaskType === "PERSONAL",
        is_bllok: newTaskType === "BLLOK",
        phase: newTaskPhase || activePhase,
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
        toast.error(detail)
        return
      }
      const created = (await res.json()) as Task
      setTasks((prev) => [created, ...prev])
      setCreateOpen(false)
      setNewTitle("")
      setNewDescription("")
      setNewStatus("TODO")
      setNewTaskType("NORMAL")
      setNewAssignees([])
      setNewSkillCategory(null)
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
        toast.error(detail)
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
          path: activePhase,
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
        toast.error(formatErrorDetail(detail))
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

  const updateTaskStatus = async (taskId: string, nextStatus: Task["status"]) => {
    const task = tasks.find((t) => t.id === taskId)
    const previousStatus = task?.status
    
    // Only admins can change tasks from DONE to any other status
    if (previousStatus === "DONE" && nextStatus !== "DONE" && user?.role !== "ADMIN") {
      toast.error("Only admins can change tasks from DONE to another status")
      return
    }
    
    if (nextStatus === "DONE" || nextStatus === "WAITING_CONFIRMATION") {
      if (taskChecklists[taskId] === undefined) {
        await loadTaskChecklist(taskId)
      }
      if (!isChecklistComplete(taskId)) {
        toast.error("Complete all subtasks before marking this task as done.")
        return
      }
    }
    if (isWaitingConfirmation(nextStatus) && !task?.confirmation_assignee_id) {
      setPendingStatusTaskId(taskId)
      setPendingStatusValue(nextStatus)
      setPendingConfirmationAssigneeId("")
      return
    }

    setUpdatingTaskId(taskId)
    setTasks((prev) => prev.map((task) => (task.id === taskId ? { ...task, status: nextStatus } : task)))
    try {
      const payload: Record<string, unknown> = { status: nextStatus }
      if (isWaitingConfirmation(nextStatus) && task?.confirmation_assignee_id) {
        payload.confirmation_assignee_id = task.confirmation_assignee_id
      }
      const res = await apiFetch(`/tasks/${taskId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
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

  const submitPendingStatusUpdate = async () => {
    if (!pendingStatusTaskId) return
    const validation = validateWaitingConfirmation(pendingStatusValue, pendingConfirmationAssigneeId)
    if (validation) {
      toast.error(validation)
      return
    }
    setUpdatingTaskId(pendingStatusTaskId)
    try {
      const res = await apiFetch(`/tasks/${pendingStatusTaskId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status: pendingStatusValue,
          confirmation_assignee_id: pendingConfirmationAssigneeId,
        }),
      })
      if (!res.ok) {
        let detail = "Failed to update task status"
        try {
          const data = (await res.json()) as { detail?: string }
          if (typeof data?.detail === "string" && data.detail.trim()) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      const updated = (await res.json()) as Task
      setTasks((prev) => prev.map((task) => (task.id === updated.id ? updated : task)))
      setPendingStatusTaskId(null)
      setPendingStatusValue("TODO")
      setPendingConfirmationAssigneeId("")
    } finally {
      setUpdatingTaskId(null)
    }
  }

  const patchMeetingChecklistItem = async (
    itemId: string,
    payload: Partial<{ title: string; comment: string | null; is_checked: boolean; position: number }>
  ) => {
    const res = await apiFetch(`/checklist-items/${itemId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      toast.error("Failed to save meeting checklist")
      return null
    }
    const updated = (await res.json()) as ChecklistItem
    setChecklistItems((prev) => prev.map((entry) => (entry.id === updated.id ? updated : entry)))
    return updated
  }

  const toggleMeetingChecklistItem = async (itemId: string, next: boolean) => {
    const previous = meetingChecklist.find((item) => item.id === itemId)?.isChecked ?? false
    const source = checklistItems.find((item) => item.id === itemId)
    const normalizedTitle = (source?.title || "").trim().toLowerCase()
    const targetIds = checklistItems
      .filter(
        (item) =>
          item.item_type === "CHECKBOX" &&
          item.path === "MEETINGS" &&
          (item.title || "").trim().toLowerCase() === normalizedTitle
      )
      .map((item) => item.id)
    const idsToUpdate = targetIds.length ? targetIds : [itemId]
    const previousStates = new Map(
      checklistItems
        .filter((item) => idsToUpdate.includes(item.id))
        .map((item) => [item.id, item.is_checked ?? false])
    )
    setMeetingChecklist((prev) =>
      prev.map((item) => (item.id === itemId ? { ...item, isChecked: next } : item))
    )
    setChecklistItems((prev) =>
      prev.map((item) => (idsToUpdate.includes(item.id) ? { ...item, is_checked: next } : item))
    )
    const results = await Promise.all(
      idsToUpdate.map(async (id) => {
        const res = await apiFetch(`/checklist-items/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_checked: next }),
        })
        return res.ok
      })
    )
    if (results.some((ok) => !ok)) {
      setMeetingChecklist((prev) =>
        prev.map((item) => (item.id === itemId ? { ...item, isChecked: previous } : item))
      )
      setChecklistItems((prev) =>
        prev.map((item) =>
          idsToUpdate.includes(item.id)
            ? { ...item, is_checked: previousStates.get(item.id) ?? false }
            : item
        )
      )
      toast.error("Failed to update meeting checklist")
    }
  }

  const startEditTask = (task: Task) => {
    setEditingTaskId(task.id)
    setEditTitle(task.title || "")
    setEditDescription(task.description || "")
    setEditStatus(TASK_STATUSES.find((status) => status === task.status) || "TODO")
    setEditTaskType(getProjectTaskType(task))
    // Get assignees from assignees array, fallback to assigned_to for backward compatibility
    const assigneeIds = task.assignees && task.assignees.length > 0
      ? task.assignees.map(a => a.id)
      : (task.assigned_to || task.assigned_to_user_id ? [task.assigned_to || task.assigned_to_user_id!] : [])
    setEditAssignees(assigneeIds)
    setEditSkillCategory(task.skill_category || null)
    setEditPhase(task.phase || activePhase)
    setEditStartDate(toDateInput(task.start_date))
    setEditDueDate(toDateInput(task.due_date))
    setEditFinishPeriod(task.finish_period || FINISH_PERIOD_NONE_VALUE)
    setEditDeadlineImportant(Boolean(task.is_deadline_important))
    if (taskChecklists[task.id] === undefined) {
      void loadTaskChecklist(task.id)
    }
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
    if (editStatus === "DONE" || editStatus === "WAITING_CONFIRMATION") {
      if (taskChecklists[editingTaskId] === undefined) {
        await loadTaskChecklist(editingTaskId)
      }
      if (!isChecklistComplete(editingTaskId)) {
        toast.error("Complete all subtasks before marking this task as done.")
        return
      }
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
        skill_category: editSkillCategory,
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
        toast.error(formatErrorDetail(detail))
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
        toast.error(formatErrorDetail(detail))
        return
      }
      setTasks((prev) => prev.filter((task) => task.id !== taskId))
      toast.success("Task deleted")
    } finally {
      setDeletingTaskId(null)
    }
  }

  const startEditMeetingChecklistItem = (itemId: string) => {
    const item = meetingChecklist.find((entry) => entry.id === itemId)
    if (!item) return
    setEditingMeetingItemId(itemId)
    setEditingMeetingItemContent(item.content)
    setEditingMeetingItemAnswer(item.answer)
    setEditingMeetingItemNumber(item.position ? String(item.position) : "")
  }

  const cancelEditMeetingChecklistItem = () => {
    setEditingMeetingItemId(null)
    setEditingMeetingItemContent("")
    setEditingMeetingItemAnswer("")
    setEditingMeetingItemNumber("")
  }

  const startEditMeetingFocusItem = (itemId: string) => {
    const item = meetingFocusItems.find((entry) => entry.id === itemId)
    if (!item) return
    setMeetingFocusEditingId(itemId)
    setMeetingFocusEditingText(item.text)
    setMeetingFocusEditingNumber(item.position ? String(item.position) : "")
  }

  const cancelEditMeetingFocusItem = () => {
    setMeetingFocusEditingId(null)
    setMeetingFocusEditingText("")
    setMeetingFocusEditingNumber("")
  }

  const reloadChecklistItems = React.useCallback(async () => {
    const res = await apiFetch(`/checklist-items?project_id=${projectId}`)
    if (!res.ok) return false
    const items = (await res.json()) as ChecklistItem[]
    setChecklistItems(items)
    return true
  }, [apiFetch, projectId])

  const saveMeetingFocusItem = async () => {
    if (!meetingFocusEditingId) return
    const text = meetingFocusEditingText.trim()
    if (!text) return
    const rawNumber = meetingFocusEditingNumber.trim()
    let position: number | undefined
    if (rawNumber) {
      const parsed = Number.parseInt(rawNumber, 10)
      if (Number.isNaN(parsed) || parsed < 1) {
        toast.error("Invalid order number")
        return
      }
      position = parsed
    }
    setSavingMeetingFocusItem(true)
    try {
      const res = await apiFetch(`/checklist-items/${meetingFocusEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comment: text, position }),
      })
      if (!res.ok) {
        toast.error("Failed to update meeting focus item")
        return
      }
      const updated = (await res.json()) as ChecklistItem
      const refreshed = await reloadChecklistItems()
      if (!refreshed) {
        setChecklistItems((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
      }
      cancelEditMeetingFocusItem()
    } finally {
      setSavingMeetingFocusItem(false)
    }
  }

  const deleteMeetingFocusItem = async (itemId: string) => {
    const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
    if (!res.ok) {
      toast.error("Failed to delete meeting focus item")
      return
    }
    const refreshed = await reloadChecklistItems()
    if (!refreshed) {
      setChecklistItems((prev) => prev.filter((item) => item.id !== itemId))
    }
    toast.success("Meeting focus item deleted")
  }

  const addMeetingFocusItem = async () => {
    if (!project) return
    const text = newMeetingFocusText.trim()
    if (!text) return
    const rawNumber = meetingFocusNewNumber.trim()
    let position = meetingFocusItems.reduce((max, item) => Math.max(max, item.position ?? 0), 0) + 1
    if (rawNumber) {
      const parsed = Number.parseInt(rawNumber, 10)
      if (Number.isNaN(parsed) || parsed < 1) {
        toast.error("Invalid order number")
        return
      }
      position = parsed
    }
    setSavingMeetingFocusItem(true)
    try {
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          item_type: "COMMENT",
          path: "MEETING_FOCUS",
          comment: text,
          position,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to add meeting focus item")
        return
      }
      const created = (await res.json()) as ChecklistItem
      const refreshed = await reloadChecklistItems()
      if (!refreshed) {
        setChecklistItems((prev) => [...prev, created])
      }
      setNewMeetingFocusText("")
      setMeetingFocusNewNumber("")
      toast.success("Meeting focus item added")
    } finally {
      setSavingMeetingFocusItem(false)
    }
  }

  const saveMeetingChecklistItem = async () => {
    if (!editingMeetingItemId) return
    const title = editingMeetingItemContent.trim()
    if (!title) return
    const comment = editingMeetingItemAnswer.trim()
    const rawNumber = editingMeetingItemNumber.trim()
    let position: number | undefined
    if (rawNumber) {
      const parsed = Number.parseInt(rawNumber, 10)
      if (Number.isNaN(parsed) || parsed < 1) {
        toast.error("Invalid order number")
        return
      }
      position = parsed
    }
    const saved = await patchMeetingChecklistItem(editingMeetingItemId, {
      title,
      comment: comment || null,
      position,
    })
    if (saved) {
      await reloadChecklistItems()
      cancelEditMeetingChecklistItem()
    }
  }

  const deleteMeetingChecklistItem = async (itemId: string) => {
    const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
    if (!res.ok) {
      toast.error("Failed to delete meeting checklist item")
      return
    }
    const refreshed = await reloadChecklistItems()
    if (!refreshed) {
      setChecklistItems((prev) => prev.filter((entry) => entry.id !== itemId))
    }
    toast.success("Checklist item deleted")
  }

  const addMeetingChecklistItem = async () => {
    if (!project) return
    const title = newMeetingItemContent.trim()
    if (!title) return
    const rawNumber = meetingChecklistNewNumber.trim()
    let nextPosition =
      meetingChecklist.reduce((max, item) => Math.max(max, item.position ?? 0), 0) + 1
    if (rawNumber) {
      const parsed = Number.parseInt(rawNumber, 10)
      if (Number.isNaN(parsed) || parsed < 1) {
        toast.error("Invalid order number")
        return
      }
      nextPosition = parsed
    }
    setAddingMeetingItem(true)
    try {
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          item_type: "CHECKBOX",
          path: "MEETINGS",
          title,
          comment: newMeetingItemAnswer.trim() || null,
          is_checked: false,
          position: nextPosition,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to add meeting checklist item")
        return
      }
      const created = (await res.json()) as ChecklistItem
      const refreshed = await reloadChecklistItems()
      if (!refreshed) {
        setChecklistItems((prev) => [...prev, created])
      }
      setNewMeetingItemContent("")
      setNewMeetingItemAnswer("")
      setMeetingChecklistNewNumber("")
      toast.success("Checklist item added")
    } finally {
      setAddingMeetingItem(false)
    }
  }

  const toggleChecklistDbItem = async (item: ChecklistItem, next: boolean) => {
    const res = await apiFetch(`/checklist-items/${item.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_checked: next }),
    })
    if (!res.ok) {
      toast.error("Failed to update checklist")
      return
    }
    const updated = (await res.json()) as ChecklistItem
    setMstAcceptanceChecklist((prev) => prev.map((it) => (it.id === updated.id ? updated : it)))
    setMstGaMeetingChecklist((prev) => prev.map((it) => (it.id === updated.id ? updated : it)))
  }

  const toggleTestingChecklistItemDb = async (itemId: string, next: boolean) => {
    const previous = checklistItems.find((item) => item.id === itemId)?.is_checked ?? false
    setChecklistItems((prev) =>
      prev.map((item) => (item.id === itemId ? { ...item, is_checked: next } : item))
    )
    setTestingChecklist((prev) =>
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
      setTestingChecklist((prev) =>
        prev.map((item) => (item.id === itemId ? { ...item, isChecked: previous } : item))
      )
      toast.error("Failed to update testing checklist")
    }
  }

  const startEditTestingItem = (itemId: string) => {
    const item = testingChecklist.find((entry) => entry.id === itemId)
    if (!item) return
    setTestingEditingId(itemId)
    setTestingEditingText(item.question)
    setTestingEditingNumber(item.position ? String(item.position) : "")
  }

  const cancelEditTestingItem = () => {
    setTestingEditingId(null)
    setTestingEditingText("")
    setTestingEditingNumber("")
  }

  const saveTestingItem = async () => {
    if (!testingEditingId) return
    const text = testingEditingText.trim()
    if (!text) return
    const rawNumber = testingEditingNumber.trim()
    let position: number | undefined
    if (rawNumber) {
      const parsed = Number.parseInt(rawNumber, 10)
      if (Number.isNaN(parsed) || parsed < 1) {
        toast.error("Invalid order number")
        return
      }
      position = parsed
    }
    setSavingTestingItem(true)
    try {
      const res = await apiFetch(`/checklist-items/${testingEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: text, position }),
      })
      if (!res.ok) {
        toast.error("Failed to update testing checklist item")
        return
      }
      const updated = (await res.json()) as ChecklistItem
      const refreshed = await reloadChecklistItems()
      if (!refreshed) {
        setChecklistItems((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
      }
      cancelEditTestingItem()
    } finally {
      setSavingTestingItem(false)
    }
  }

  const deleteTestingItem = async (itemId: string) => {
    const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
    if (!res.ok) {
      toast.error("Failed to delete testing checklist item")
      return
    }
    const refreshed = await reloadChecklistItems()
    if (!refreshed) {
      setChecklistItems((prev) => prev.filter((item) => item.id !== itemId))
      setTestingChecklist((prev) => prev.filter((item) => item.id !== itemId))
    }
    toast.success("Testing checklist item deleted")
  }

  const addTestingChecklistItem = async () => {
    if (!project) return
    const text = newTestingText.trim()
    if (!text) return
    setSavingTestingItem(true)
    try {
      const rawNumber = newTestingNumber.trim()
      let position = testingChecklist.reduce((max, item) => Math.max(max, item.position ?? 0), 0) + 1
      if (rawNumber) {
        const parsed = Number.parseInt(rawNumber, 10)
        if (Number.isNaN(parsed) || parsed < 1) {
          toast.error("Invalid order number")
          return
        }
        position = parsed
      }
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          item_type: "CHECKBOX",
          path: "TESTING",
          title: text,
          is_checked: false,
          position,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to add testing checklist item")
        return
      }
      const created = (await res.json()) as ChecklistItem
      const refreshed = await reloadChecklistItems()
      if (!refreshed) {
        setChecklistItems((prev) => [...prev, created])
      }
      setNewTestingText("")
      setNewTestingNumber("")
      toast.success("Testing checklist item added")
    } finally {
      setSavingTestingItem(false)
    }
  }

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
    setDocumentationEditingNumber(item.position ? String(item.position) : "")
  }

  const cancelEditDocumentationItem = () => {
    setDocumentationEditingId(null)
    setDocumentationEditingText("")
    setDocumentationEditingNumber("")
  }

  const saveDocumentationItem = async () => {
    if (!documentationEditingId) return
    const text = documentationEditingText.trim()
    if (!text) return
    const rawNumber = documentationEditingNumber.trim()
    let position: number | undefined
    if (rawNumber) {
      const parsed = Number.parseInt(rawNumber, 10)
      if (Number.isNaN(parsed) || parsed < 1) {
        toast.error("Invalid order number")
        return
      }
      position = parsed
    }
    setSavingDocumentationItem(true)
    try {
      const res = await apiFetch(`/checklist-items/${documentationEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: text, position }),
      })
      if (!res.ok) {
        toast.error("Failed to update documentation checklist item")
        return
      }
      const updated = (await res.json()) as ChecklistItem
      const refreshed = await reloadChecklistItems()
      if (!refreshed) {
        setChecklistItems((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
      }
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
    const refreshed = await reloadChecklistItems()
    if (!refreshed) {
      setChecklistItems((prev) => prev.filter((item) => item.id !== itemId))
      setDocumentationChecklist((prev) => prev.filter((item) => item.id !== itemId))
    }
    toast.success("Documentation checklist item deleted")
  }

  const addDocumentationChecklistItem = async () => {
    if (!project) return
    const text = newDocumentationText.trim()
    if (!text) return
    setSavingDocumentationItem(true)
    try {
      const rawNumber = newDocumentationNumber.trim()
      let position =
        documentationChecklist.reduce((max, item) => Math.max(max, item.position ?? 0), 0) + 1
      if (rawNumber) {
        const parsed = Number.parseInt(rawNumber, 10)
        if (Number.isNaN(parsed) || parsed < 1) {
          toast.error("Invalid order number")
          return
        }
        position = parsed
      }
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
      const refreshed = await reloadChecklistItems()
      if (!refreshed) {
        setChecklistItems((prev) => [...prev, created])
      }
      setNewDocumentationText("")
      setNewDocumentationNumber("")
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
      const existingFilePaths = checklistItems.filter(
        (item) =>
          item.path === "DOCUMENTATION" &&
          item.item_type === "COMMENT" &&
          item.category === "FILE_PATH"
      )
      const position =
        existingFilePaths.length > 0
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
        toast.error("Failed to add file path")
        return
      }
      const created = (await res.json()) as ChecklistItem
      setChecklistItems((prev) => [...prev, created])
      setDocumentationFilePath("")
      toast.success("File path added")
    } catch (error) {
      console.error("Failed to add file path:", error)
      toast.error("Failed to add file path")
    }
  }

  const startEditDocumentationFilePath = (itemId: string) => {
    const item = documentationFilePaths.find((entry) => entry.id === itemId)
    if (!item) return
    setDocumentationFilePathEditingId(itemId)
    setDocumentationFilePathEditingText(item.path)
  }

  const cancelEditDocumentationFilePath = () => {
    setDocumentationFilePathEditingId(null)
    setDocumentationFilePathEditingText("")
  }

  const saveDocumentationFilePath = async () => {
    if (!documentationFilePathEditingId) return
    const value = documentationFilePathEditingText.trim()
    if (!value) return
    setDocumentationFilePathSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${documentationFilePathEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comment: value }),
      })
      if (!res.ok) {
        toast.error("Failed to update file path")
        return
      }
      const updated = (await res.json()) as ChecklistItem
      setChecklistItems((prev) => prev.map((item) => (item.id === updated.id ? updated : item)))
      cancelEditDocumentationFilePath()
      toast.success("File path updated")
    } finally {
      setDocumentationFilePathSaving(false)
    }
  }

  const deleteDocumentationFilePath = async (itemId: string) => {
    if (documentationFilePathEditingId === itemId) {
      cancelEditDocumentationFilePath()
    }
    try {
      const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
      if (!res.ok) {
        toast.error("Failed to delete file path")
        return
      }
      setChecklistItems((prev) => prev.filter((item) => item.id !== itemId))
      toast.success("File path deleted")
    } catch (error) {
      console.error("Failed to delete file path:", error)
      toast.error("Failed to delete file path")
    }
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
        toast.error(detail)
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
    const projectTitle = (project.title || project.name || "").toUpperCase()
    const isMst = project.project_type === "MST" || projectTitle.includes("MST")
    const openTasks = tasks.filter(
      (task) =>
        task.status !== "DONE" &&
        task.status !== "DONE" &&
        (task.phase || currentPhase) === currentPhase
    )
    const phaseChecklistItems = checklistItems.filter(
      (item) =>
        item.item_type === "CHECKBOX" &&
        (item.path || "").toUpperCase() === currentPhase &&
        !item.is_checked
    )
    const uncheckedItems =
      isMeetingPhase || (isMst && currentPhase === "PLANNING") ? [] : phaseChecklistItems
    const uncheckedMeeting = isMeetingPhase ? meetingChecklist.filter((item) => !item.isChecked) : []
    const uncheckedMstPlanning =
      isMst && currentPhase === "PLANNING"
        ? [
            ...mstAcceptanceChecklist.filter((item) => item.item_type === "CHECKBOX" && !item.is_checked),
            ...mstGaMeetingChecklist.filter((item) => item.item_type === "CHECKBOX" && !item.is_checked),
          ]
        : []

    if (openTasks.length || uncheckedItems.length || uncheckedMeeting.length || uncheckedMstPlanning.length) {
      const blockers: string[] = []
      if (openTasks.length) blockers.push(`${openTasks.length} detyra te hapura`)
      if (uncheckedItems.length) blockers.push(`${uncheckedItems.length} checklist te pa kryera`)
      if (uncheckedMeeting.length) blockers.push(`${uncheckedMeeting.length} checklist te takimeve te pa kryera`)
      if (uncheckedMstPlanning.length) blockers.push(`${uncheckedMstPlanning.length} checklist te planifikimit te pa kryera`)
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
        toast.error(detail)
        return
      }
      const updated = (await res.json()) as Project
      const nextPhase = updated.current_phase || "MEETINGS"
      setProject(updated)
      if (nextPhase === "CLOSED") {
        // When closing the final phase, keep the user viewing the phase they just completed.
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
        toast.error(detail)
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
      toast.error(detail)
      return
    }
    const updated = (await res.json()) as GaNote
    setGaNotes((prev) => prev.map((note) => (note.id === updated.id ? updated : note)))
  }

  const phaseValue = viewedPhase || project?.current_phase || "MEETINGS"
  const titleUpper = (project?.title || project?.name || "").toUpperCase()
  const isMstProject = project?.project_type === "MST" || titleUpper.includes("MST")
  const isDevelopmentProject = (projectDepartmentName || "").toLowerCase() === "development"
  const visibleTabs = React.useMemo(() => {
    if (phaseValue === "MEETINGS") {
      return [
        ...MEETING_TABS.filter((tab) => tab.id === "meeting-focus"),
        ...TABS.filter((tab) => tab.id === "description"),
        ...MEETING_TABS.filter((tab) => tab.id === "meeting-checklist"),
        ...TABS.filter((tab) => tab.id === "members"),
        ...TABS.filter((tab) => tab.id === "ga"),
      ]
    }
    if (phaseValue === "PLANIFIKIMI" || phaseValue === "PLANNING") {
      if (isMstProject) {
        return TABS.filter((tab) =>
          tab.id === "description" ||
          tab.id === "tasks" ||
          tab.id === "mst-acceptance" ||
          tab.id === "mst-ga-meeting" ||
          tab.id === "members" ||
          tab.id === "checklists" ||
          tab.id === "ga"
        )
      }
      return TABS.filter(
        (tab) =>
          tab.id !== "checklists" &&
          tab.id !== "members" &&
          tab.id !== "prompts" &&
          tab.id !== "testing" &&
          tab.id !== "development-checklist" &&
          tab.id !== "mst-acceptance" &&
          tab.id !== "mst-ga-meeting"
      )
    }
    if (phaseValue === "ZHVILLIMI" || phaseValue === "DEVELOPMENT") {
      return [
        ...TABS.filter((tab) => tab.id === "tasks" || tab.id === "development-checklist" || tab.id === "prompts"),
        ...TABS.filter((tab) => tab.id === "ga"),
      ]
    }
    if (phaseValue === "TESTIMI" || phaseValue === "TESTING") {
      return TABS.filter((tab) => tab.id === "testing" || tab.id === "tasks" || tab.id === "ga")
    }
    if (phaseValue === "DOKUMENTIMI" || phaseValue === "DOCUMENTATION") {
      return TABS.filter((tab) => {
        if (
          tab.id === "description" ||
          tab.id === "tasks" ||
          tab.id === "members" ||
          tab.id === "prompts" ||
          tab.id === "development-checklist"
        ) {
          return false
        }
        if (
          isDevelopmentProject &&
          (tab.id === "testing" || tab.id === "mst-acceptance" || tab.id === "mst-ga-meeting")
        ) {
          return false
        }
        return true
      })
    }
    const baseTabs = TABS.filter((tab) => tab.id !== "testing" && tab.id !== "development-checklist")
    if (isMstProject) {
      // Outside PLANNING, hide the MST-only checklist tabs.
      return baseTabs.filter((tab) => tab.id !== "mst-acceptance" && tab.id !== "mst-ga-meeting")
    }
    return baseTabs
  }, [phaseValue, isDevelopmentProject])

  React.useEffect(() => {
    if (!visibleTabs.length) return
    if (!visibleTabs.some((tab) => tab.id === activeTab)) {
      setActiveTab(visibleTabs[0].id)
    }
  }, [activeTab, visibleTabs])

  React.useEffect(() => {
    if (!project) return
    if (!isMstProject) return
    if (phaseValue !== "PLANNING" && phaseValue !== "PLANIFIKIMI") return
    const loadMstChecklists = async () => {
      const [accRes, gaRes] = await Promise.all([
        apiFetch(`/checklists?project_id=${project.id}&group_key=${MST_PLANNING_ACCEPTANCE_GROUP_KEY}&include_items=true`),
        apiFetch(`/checklists?project_id=${project.id}&group_key=${MST_PLANNING_GA_MEETING_GROUP_KEY}&include_items=true`),
      ])
      if (accRes.ok) {
        const data = (await accRes.json()) as { items?: ChecklistItem[] }[]
        setMstAcceptanceChecklist(data?.[0]?.items || [])
      }
      if (gaRes.ok) {
        const data = (await gaRes.json()) as { items?: ChecklistItem[] }[]
        setMstGaMeetingChecklist(data?.[0]?.items || [])
      }
    }
    void loadMstChecklists()
  }, [apiFetch, project, isMstProject, phaseValue])

  const reloadMstPlanningChecklists = React.useCallback(async () => {
    if (!project) return
    const [accRes, gaRes] = await Promise.all([
      apiFetch(`/checklists?project_id=${project.id}&group_key=${MST_PLANNING_ACCEPTANCE_GROUP_KEY}&include_items=true`),
      apiFetch(`/checklists?project_id=${project.id}&group_key=${MST_PLANNING_GA_MEETING_GROUP_KEY}&include_items=true`),
    ])
    if (accRes.ok) {
      const data = (await accRes.json()) as { items?: ChecklistItem[] }[]
      setMstAcceptanceChecklist(data?.[0]?.items || [])
    }
    if (gaRes.ok) {
      const data = (await gaRes.json()) as { items?: ChecklistItem[] }[]
      setMstGaMeetingChecklist(data?.[0]?.items || [])
    }
  }, [apiFetch, project])

  const isAdmin = user?.role === "ADMIN"
  const isManager = user?.role === "MANAGER"
  const canEditDueDate = isAdmin || isManager
  const canEditProjectTitle = Boolean(user)

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
      const res = await apiFetch(`/checklist-items/${developmentChecklistEditingId}`, {
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
      const res = await apiFetch(`/checklist-items/${item.id}`, {
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
      const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
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

  const addMstAcceptanceItem = async () => {
    if (!project) return
    const text = mstAcceptanceNewText.trim()
    if (!text) return
    const rawNumber = mstAcceptanceNewNumber.trim()
    const position =
      rawNumber ? Math.max(0, Number.parseInt(rawNumber, 10) - 1) : undefined
    setMstAcceptanceSaving(true)
    try {
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          group_key: MST_PLANNING_ACCEPTANCE_GROUP_KEY,
          checklist_title: "Project Acceptance",
          item_type: "CHECKBOX",
          title: text,
          position,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to add item")
        return
      }
      setMstAcceptanceNewText("")
      setMstAcceptanceNewNumber("")
      await reloadMstPlanningChecklists()
    } finally {
      setMstAcceptanceSaving(false)
    }
  }

  const startEditMstAcceptanceItem = (item: ChecklistItem) => {
    setMstAcceptanceEditingId(item.id)
    setMstAcceptanceEditingText(item.title || "")
  }

  const saveEditMstAcceptanceItem = async () => {
    if (!mstAcceptanceEditingId) return
    const text = mstAcceptanceEditingText.trim()
    if (!text) return
    setMstAcceptanceSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${mstAcceptanceEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: text }),
      })
      if (!res.ok) {
        toast.error("Failed to update item")
        return
      }
      setMstAcceptanceEditingId(null)
      setMstAcceptanceEditingText("")
      await reloadMstPlanningChecklists()
    } finally {
      setMstAcceptanceSaving(false)
    }
  }

  const deleteMstAcceptanceItem = async (itemId: string) => {
    setMstAcceptanceSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
      if (!res.ok) {
        toast.error("Failed to delete item")
        return
      }
      await reloadMstPlanningChecklists()
    } finally {
      setMstAcceptanceSaving(false)
    }
  }

  const addMstGaMeetingItem = async () => {
    if (!project || !mstGaMeetingNewText.trim()) return
    const text = mstGaMeetingNewText.trim()
    const position = mstGaMeetingNewNumber.trim() ? parseInt(mstGaMeetingNewNumber.trim(), 10) - 1 : mstGaMeetingChecklist.length
    if (isNaN(position) || position < 0) {
      toast.error("Invalid position number")
      return
    }
    setMstGaMeetingSaving(true)
    try {
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          group_key: MST_PLANNING_GA_MEETING_GROUP_KEY,
          checklist_title: "GA Meeting",
          item_type: "CHECKBOX",
          title: text,
          position,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to add item")
        return
      }
      setMstGaMeetingNewText("")
      setMstGaMeetingNewNumber("")
      await reloadMstPlanningChecklists()
    } finally {
      setMstGaMeetingSaving(false)
    }
  }

  const startEditMstGaMeetingItem = (item: ChecklistItem) => {
    setMstGaMeetingEditingId(item.id)
    setMstGaMeetingEditingText(item.title || "")
  }

  const saveEditMstGaMeetingItem = async () => {
    if (!mstGaMeetingEditingId) return
    const text = mstGaMeetingEditingText.trim()
    if (!text) return
    setMstGaMeetingSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${mstGaMeetingEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: text }),
      })
      if (!res.ok) {
        toast.error("Failed to update item")
        return
      }
      setMstGaMeetingEditingId(null)
      setMstGaMeetingEditingText("")
      await reloadMstPlanningChecklists()
    } finally {
      setMstGaMeetingSaving(false)
    }
  }

  const deleteMstGaMeetingItem = async (itemId: string) => {
    setMstGaMeetingSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
      if (!res.ok) {
        toast.error("Failed to delete item")
        return
      }
      await reloadMstPlanningChecklists()
    } finally {
      setMstGaMeetingSaving(false)
    }
  }

  const startEditMstAcceptanceComment = (item: ChecklistItem) => {
    setMstAcceptanceCommentEditingId(item.id)
    setMstAcceptanceCommentText(item.comment || "")
  }

  const saveMstAcceptanceComment = async (itemId: string) => {
    setMstAcceptanceSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${itemId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comment: mstAcceptanceCommentText.trim() || null }),
      })
      if (!res.ok) {
        toast.error("Failed to save comment")
        return
      }
      setMstAcceptanceCommentEditingId(null)
      setMstAcceptanceCommentText("")
      await reloadMstPlanningChecklists()
    } finally {
      setMstAcceptanceSaving(false)
    }
  }

  const startEditMstGaMeetingComment = (item: ChecklistItem) => {
    setMstGaMeetingCommentEditingId(item.id)
    setMstGaMeetingCommentText(item.comment || "")
  }

  const saveMstGaMeetingComment = async (itemId: string) => {
    setMstGaMeetingSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${itemId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comment: mstGaMeetingCommentText.trim() || null }),
      })
      if (!res.ok) {
        toast.error("Failed to save comment")
        return
      }
      setMstGaMeetingCommentEditingId(null)
      setMstGaMeetingCommentText("")
      await reloadMstPlanningChecklists()
    } finally {
      setMstGaMeetingSaving(false)
    }
  }

  const activePhase = phaseValue
  const visibleTasks = React.useMemo(
    () =>
      tasks.filter((task) => {
        const taskPhase = task.phase || project?.current_phase || "MEETINGS"
        return taskPhase === activePhase
      }),
    [activePhase, project?.current_phase, tasks]
  )
  const visibleChecklistItems = React.useMemo(
    () => checklistItems.filter((item) => item.path === activePhase),
    [activePhase, checklistItems]
  )
  const userMap = new Map(
    [...allUsers, ...members, ...(user ? [user] : [])].map((m) => [m.id, m])
  )
  const confirmerCandidates = React.useMemo(
    () => getConfirmerCandidates([...allUsers, ...members, ...(user ? [user] : [])]),
    [allUsers, members, user]
  )
  const taskAssigneeOptions = React.useMemo(() => {
    const map = new Map<string, string>()
    const add = (id?: string | null, label?: string | null) => {
      if (!id) return
      if (!map.has(id)) map.set(id, label || id)
    }

    visibleTasks.forEach((task) => {
      if (task.assigned_to) {
        const label = userMap.get(task.assigned_to)?.full_name ||
          userMap.get(task.assigned_to)?.username ||
          userMap.get(task.assigned_to)?.email ||
          task.assigned_to
        add(task.assigned_to, label)
      }
      if (task.assigned_to_user_id) {
        const label = userMap.get(task.assigned_to_user_id)?.full_name ||
          userMap.get(task.assigned_to_user_id)?.username ||
          userMap.get(task.assigned_to_user_id)?.email ||
          task.assigned_to_user_id
        add(task.assigned_to_user_id, label)
      }
      task.assignees?.forEach((assignee) => {
        add(assignee.id, assignee.full_name || assignee.username || assignee.email || assignee.id)
      })
    })

    let list = Array.from(map.entries()).map(([id, label]) => ({ id, label }))
    list.sort((a, b) => a.label.localeCompare(b.label))

    return list
  }, [userMap, visibleTasks])
  const filteredVisibleTasks = React.useMemo(() => {
    const currentUserId = user?.id ?? null
    return visibleTasks.filter((task) => matchesAssignee(task, taskAssigneeFilter, currentUserId))
  }, [taskAssigneeFilter, user?.id, visibleTasks])
  const tasksByStatus = React.useMemo(() => {
    const buckets: Record<(typeof TASK_STATUSES)[number], Task[]> = {
      TODO: [],
      IN_PROGRESS: [],
      WAITING_CLIENT: [],
      WAITING_CONFIRMATION: [],
      DONE: [],
    }
    for (const task of filteredVisibleTasks) {
      const statusValue = (task.status || "TODO") as (typeof TASK_STATUSES)[number]
      if (statusValue === "IN_PROGRESS") {
        buckets.IN_PROGRESS.push(task)
      } else if (statusValue === "WAITING_CLIENT") {
        buckets.WAITING_CLIENT.push(task)
      } else if (statusValue === "WAITING_CONFIRMATION") {
        buckets.WAITING_CONFIRMATION.push(task)
      } else if (statusValue === "DONE") {
        buckets.DONE.push(task)
      } else {
        buckets.TODO.push(task)
      }
    }
    const sortNewestFirst = (a: Task, b: Task) => {
      const aTime = getTaskSortDate(a)
      const bTime = getTaskSortDate(b)
      if (aTime == null && bTime == null) return 0
      if (aTime == null) return 1
      if (bTime == null) return -1
      return bTime - aTime
    }
    buckets.TODO.sort(sortNewestFirst)
    buckets.IN_PROGRESS.sort(sortNewestFirst)
    buckets.WAITING_CLIENT.sort(sortNewestFirst)
    buckets.WAITING_CONFIRMATION.sort(sortNewestFirst)
    buckets.DONE.sort(sortNewestFirst)
    return buckets
  }, [filteredVisibleTasks])

  if (!project) return <div className="text-sm text-muted-foreground">Loading...</div>

  const baseTitle = project.title || project.name || "Project"
  const title = project.project_type === "MST" && project.total_products != null && project.total_products > 0
    ? `${baseTitle} - ${project.total_products}`
    : baseTitle

  const renderProjectTitle = (titleClassName: string, inputClassName: string) => {
    if (!canEditProjectTitle) {
      return <div className={titleClassName}>{title}</div>
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
        <div className={titleClassName}>{title}</div>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 px-2"
          onClick={startEditProjectTitle}
          aria-label="Edit project title"
        >
          <Pencil className="h-4 w-4" />
        </Button>
      </div>
    )
  }

  if (project.current_phase === "CLOSED" && !showClosedDetails) {
    const totalTasks = tasks.length
    const doneTasks = tasks.filter((t) => t.status === "DONE").length
    const openTasks = totalTasks - doneTasks
    return (
      <div className="space-y-6">
        <div className="sticky top-0 z-10 bg-white/95 backdrop-blur print:static pt-6 pb-4 border-b border-slate-200">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <button
                type="button"
                onClick={() => router.back()}
                className="text-sm text-muted-foreground hover:text-foreground"
              >
                &larr; Back to Projects
              </button>
              <div className="mt-3 flex items-center gap-3">
                {renderProjectTitle("text-3xl font-semibold", "h-10 text-3xl font-semibold")}
                <ProjectActivityControl project={project} onChange={setProject} />
                <Badge variant="secondary">Closed</Badge>
              </div>
            </div>
          </div>
        </div>

        <Card className="p-6">
          <div className="text-lg font-semibold text-slate-900">Project closed</div>
          <div className="mt-2 text-sm text-muted-foreground">
            This project has been completed and is now read-only.
          </div>
          <div className="mt-4 flex flex-wrap gap-3">
            <Button onClick={() => setShowClosedDetails(true)}>View details</Button>
            <Button variant="outline" onClick={() => router.back()}>
              Back to Projects
            </Button>
          </div>
          <div className="mt-6 grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="rounded-lg border p-4">
              <div className="text-xs text-muted-foreground">Tasks</div>
              <div className="mt-1 text-2xl font-semibold">{totalTasks}</div>
            </div>
            <div className="rounded-lg border p-4">
              <div className="text-xs text-muted-foreground">Done</div>
              <div className="mt-1 text-2xl font-semibold">{doneTasks}</div>
            </div>
            <div className="rounded-lg border p-4">
              <div className="text-xs text-muted-foreground">Open</div>
              <div className="mt-1 text-2xl font-semibold">{openTasks}</div>
            </div>
          </div>
        </Card>
      </div>
    )
  }
  const phase = project.current_phase || "MEETINGS"

  const basePhaseSteps: string[] = isMstProject ? [...MST_PHASES] : [...GENERAL_PHASES]
  // Always include CLOSED so navigation/locking works correctly after the final phase is closed.
  const phaseSteps: string[] = [...basePhaseSteps, "CLOSED"]
  const phaseIndex = phaseSteps.indexOf(phase)
  const canClosePhase = phaseIndex !== -1 && phaseIndex < phaseSteps.length - 1
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
        toast.error(detail)
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

  return (
    <div className="space-y-6">
      <div className="sticky top-0 z-10 bg-white/95 backdrop-blur print:static pt-6 pb-4 border-b border-slate-200">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <button
              type="button"
              onClick={() => router.back()}
              className="text-sm text-muted-foreground hover:text-foreground"
            >
              &larr; Back to Projects
            </button>
            <div className="mt-3 flex items-center gap-3">
              {renderProjectTitle("text-3xl font-semibold", "h-10 text-3xl font-semibold")}
              <ProjectActivityControl project={project} onChange={setProject} />
              {canEditDueDate && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    const currentDueDate = project.due_date ? toDateInput(project.due_date) : ""
                    console.log("Edit due date clicked", { project: project?.id, due_date: project?.due_date, formatted: currentDueDate })
                    setEditProjectDueDate(currentDueDate)
                    setEditProjectDueDateOpen(true)
                  }}
                  className="text-sm text-muted-foreground hover:text-foreground cursor-pointer"
                  title="Edit project due date"
                >
                  {project.due_date ? `Due: ${formatDateDisplay(project.due_date)}` : "Set due date"}
                </button>
              )}
              {!canEditDueDate && project.due_date && (
                <span className="text-sm text-muted-foreground">Due: {formatDateDisplay(project.due_date)}</span>
              )}
            </div>
            <div className="mt-3">
              <Badge variant="outline" className="text-blue-600 border-blue-200 bg-blue-50">
                {PHASE_LABELS[phase] || "Meetings"}
              </Badge>
            </div>
            <div className="mt-3 text-sm text-muted-foreground">
              {phaseSteps.map((p, idx) => {
                const isViewed = p === activePhase
                const isCurrent = p === phase
                const isLocked = phaseIndex !== -1 && idx > phaseIndex
                return (
                  <span key={p}>
                    <button
                      type="button"
                      onClick={() => {
                        if (isLocked) return
                        setViewedPhase(p)
                      }}
                      className={[
                        "transition-colors",
                        isLocked
                          ? "text-slate-300 cursor-not-allowed"
                          : isViewed
                            ? "text-blue-600 font-medium"
                            : isCurrent
                              ? "text-foreground"
                              : "text-muted-foreground",
                      ].join(" ")}
                      aria-pressed={isViewed}
                      disabled={isLocked}
                    >
                      {PHASE_LABELS[p] || p}
                    </button>
                    {idx < phaseSteps.length - 1 ? " -> " : ""}
                  </span>
                )
              })}
            </div>
            {activePhase !== phase ? (
              <div className="mt-2 text-xs text-muted-foreground">
                View: {PHASE_LABELS[activePhase] || "Meetings"}
              </div>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <Button className="rounded-xl">Settings</Button>
          </div>
        </div>

        <div className="flex justify-end mt-4">
          {canClosePhase ? (
            <Button
              variant="outline"
              disabled={advancingPhase}
              onClick={() => void advancePhase()}
            >
              {advancingPhase ? "Closing..." : "Close Phase"}
            </Button>
          ) : null}
        </div>

        <div className="mt-4 border-t border-slate-200 pt-4">
          <div className="flex flex-wrap gap-6">
            {visibleTabs.map((tab) => {
              const isActive = tab.id === activeTab
              const label = activePhase === "TESTING" && tab.id === "description" ? "Testing" : tab.label
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setActiveTab(tab.id)}
                  className={[
                    "relative pb-3 text-sm font-medium",
                    tab.id === "ga" ? "ml-auto" : "",
                    isActive ? "text-blue-600" : "text-muted-foreground",
                  ].join(" ")}
                >
                  {label}
                  {isActive ? <span className="absolute inset-x-0 bottom-0 h-0.5 bg-blue-600" /> : null}
                </button>
              )
            })}
          </div>
        </div>
      </div>

      {activeTab === "meeting-focus" ? (
        <Card className="p-6">
          <div className="text-lg font-semibold text-slate-900">Meeting focus</div>
          <div className="mt-2 text-sm text-slate-700">Main points to discuss in the meeting.</div>
          <div className="mt-4 space-y-3">
            {meetingFocusItems.length ? (
              meetingFocusItems.map((item, index) => {
                const isEditing = meetingFocusEditingId === item.id
                const displayNumber = item.position != null && item.position > 0 ? item.position : index + 1
                return (
                  <div key={item.id} className="flex flex-wrap items-start gap-3 rounded-lg border px-4 py-3">
                    <div className="mt-0.5 w-16 shrink-0 text-right text-sm text-muted-foreground">
                      {isEditing ? (
                        <Input
                          type="number"
                          min={1}
                          inputMode="numeric"
                          value={meetingFocusEditingNumber}
                          onChange={(e) => setMeetingFocusEditingNumber(e.target.value)}
                          className="h-8 w-16 text-right"
                        />
                      ) : (
                        `${displayNumber}.`
                      )}
                    </div>
                    <div className="flex-1">
                      {isEditing ? (
                        <Input
                          value={meetingFocusEditingText}
                          onChange={(e) => setMeetingFocusEditingText(e.target.value)}
                        />
                      ) : (
                        <div className="text-sm font-semibold text-slate-900">{item.text}</div>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {isEditing ? (
                        <>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => void saveMeetingFocusItem()}
                            disabled={savingMeetingFocusItem}
                          >
                            Save
                          </Button>
                          <Button size="sm" variant="ghost" onClick={cancelEditMeetingFocusItem}>
                            Cancel
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button size="sm" variant="outline" onClick={() => startEditMeetingFocusItem(item.id)}>
                            Edit
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="text-red-600 border-red-200 hover:bg-red-50"
                            onClick={() => void deleteMeetingFocusItem(item.id)}
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
              <div className="text-sm text-muted-foreground">No meeting focus items yet.</div>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Input
                type="number"
                min={1}
                inputMode="numeric"
                value={meetingFocusNewNumber}
                onChange={(e) => setMeetingFocusNewNumber(e.target.value)}
                placeholder="No."
                className="w-24"
              />
              <Input
                value={newMeetingFocusText}
                onChange={(e) => setNewMeetingFocusText(e.target.value)}
                placeholder="Add meeting focus item..."
                className="flex-1 min-w-[220px]"
              />
              <Button
                variant="outline"
                disabled={!newMeetingFocusText.trim() || savingMeetingFocusItem}
                onClick={() => void addMeetingFocusItem()}
              >
                {savingMeetingFocusItem ? "Saving..." : "Add"}
              </Button>
            </div>
          </div>
        </Card>
      ) : null}

      {activeTab === "meeting-checklist" ? (
        <Card className="p-6">
          <div className="text-lg font-semibold">Meeting checklist</div>
          <div className="mt-4 space-y-3">
            {meetingChecklist.length ? (
              meetingChecklist.map((item, index) => {
                const isEditing = editingMeetingItemId === item.id
                const displayNumber = item.position != null && item.position > 0 ? item.position : index + 1
                return (
                  <div key={item.id} className="flex flex-wrap items-start gap-3 rounded-lg border px-4 py-3">
                    <div className="mt-0.5 w-16 shrink-0 text-right text-sm text-muted-foreground">
                      {isEditing ? (
                        <Input
                          type="number"
                          min={1}
                          inputMode="numeric"
                          value={editingMeetingItemNumber}
                          onChange={(e) => setEditingMeetingItemNumber(e.target.value)}
                          className="h-8 w-16 text-right"
                        />
                      ) : (
                        `${displayNumber}.`
                      )}
                    </div>
                    <Checkbox
                      checked={item.isChecked}
                      onCheckedChange={(checked) => toggleMeetingChecklistItem(item.id, Boolean(checked))}
                    />
                    <div className="flex-1 space-y-2">
                      {isEditing ? (
                        <Input
                          value={editingMeetingItemContent}
                          onChange={(e) => setEditingMeetingItemContent(e.target.value)}
                          placeholder="Checklist item"
                        />
                      ) : (
                        <div className="text-sm font-semibold text-slate-700">{item.content}</div>
                      )}
                      {isEditing ? (
                        <Input
                          value={editingMeetingItemAnswer}
                          onChange={(e) => setEditingMeetingItemAnswer(e.target.value)}
                          placeholder="Notes (optional)"
                        />
                      ) : item.answer ? (
                        <div className="text-sm text-muted-foreground">{item.answer}</div>
                      ) : (
                        <div className="text-sm text-muted-foreground">No notes</div>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {isEditing ? (
                        <>
                          <Button size="sm" variant="outline" onClick={() => void saveMeetingChecklistItem()}>
                            Save
                          </Button>
                          <Button size="sm" variant="ghost" onClick={cancelEditMeetingChecklistItem}>
                            Cancel
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button size="sm" variant="outline" onClick={() => startEditMeetingChecklistItem(item.id)}>
                            Edit
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="text-red-600 border-red-200 hover:bg-red-50"
                            onClick={() => void deleteMeetingChecklistItem(item.id)}
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
              <div className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">
                No meeting checklist items yet.
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Input
                type="number"
                min={1}
                inputMode="numeric"
                value={meetingChecklistNewNumber}
                onChange={(e) => setMeetingChecklistNewNumber(e.target.value)}
                placeholder="No."
                className="w-24"
              />
              <Input
                value={newMeetingItemContent}
                onChange={(e) => setNewMeetingItemContent(e.target.value)}
                placeholder="Add checklist item..."
                className="min-w-[220px] flex-1"
              />
              <Input
                value={newMeetingItemAnswer}
                onChange={(e) => setNewMeetingItemAnswer(e.target.value)}
                placeholder="Notes (optional)"
                className="min-w-[220px] flex-1"
              />
              <Button
                variant="outline"
                disabled={!newMeetingItemContent.trim() || addingMeetingItem}
                onClick={() => void addMeetingChecklistItem()}
              >
                {addingMeetingItem ? "Adding..." : "Add"}
              </Button>
            </div>
          </div>
        </Card>
      ) : null}

      {activeTab === "description" ? (
        <Card className="p-6">
          {activePhase === "MEETINGS" ? (
            <>
              <div className="text-lg font-semibold">Project Description</div>
              <Textarea
                value={editingDescription}
                onChange={(e) => setEditingDescription(e.target.value)}
                rows={4}
                className="mt-3"
              />
              <div className="mt-3 flex justify-end">
                <Button variant="outline" disabled={savingDescription} onClick={() => void saveDescription()}>
                  {savingDescription ? "Saving..." : "Save"}
                </Button>
              </div>
            </>
          ) : (
            <>
              <div className="text-lg font-semibold">Project Description</div>
              <Textarea
                value={editingDescription}
                onChange={(e) => setEditingDescription(e.target.value)}
                rows={4}
                className="mt-3"
              />
              <div className="mt-3 flex justify-end">
                <Button variant="outline" disabled={savingDescription} onClick={() => void saveDescription()}>
                  {savingDescription ? "Saving..." : "Save"}
                </Button>
              </div>
            </>
          )}
        </Card>
      ) : null}

      {activeTab === "testing" ? (
        <Card className="p-6">
          <div className="text-lg font-semibold">Testing Questions</div>
          <div className="mt-4 space-y-3">
            {testingChecklist.length ? (
              testingChecklist.map((item, index) => {
                const isEditing = testingEditingId === item.id
                const displayNumber = item.position != null && item.position > 0 ? item.position : index + 1
                return (
                  <div key={item.id} className="flex flex-wrap items-start gap-3 rounded-lg border px-4 py-3">
                    <div className="mt-0.5 w-16 shrink-0 text-right text-sm text-muted-foreground">
                      {isEditing ? (
                        <Input
                          type="number"
                          min={1}
                          inputMode="numeric"
                          value={testingEditingNumber}
                          onChange={(e) => setTestingEditingNumber(e.target.value)}
                          className="h-8 w-16 text-right"
                        />
                      ) : (
                        `${displayNumber}.`
                      )}
                    </div>
                    <Checkbox
                      checked={item.isChecked}
                      onCheckedChange={(checked) => toggleTestingChecklistItemDb(item.id, Boolean(checked))}
                    />
                    <div className="flex-1">
                      {isEditing ? (
                        <Input
                          value={testingEditingText}
                          onChange={(e) => setTestingEditingText(e.target.value)}
                        />
                      ) : (
                        <div className={item.isChecked ? "text-muted-foreground line-through" : ""}>
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
                            onClick={() => void saveTestingItem()}
                            disabled={savingTestingItem}
                          >
                            Save
                          </Button>
                          <Button size="sm" variant="ghost" onClick={cancelEditTestingItem}>
                            Cancel
                          </Button>
                        </>
                      ) : (
                        <>
                          <Button size="sm" variant="outline" onClick={() => startEditTestingItem(item.id)}>
                            Edit
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="text-red-600 border-red-200 hover:bg-red-50"
                            onClick={() => void deleteTestingItem(item.id)}
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
              <div className="text-sm text-muted-foreground">No testing checklist items yet.</div>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Input
                type="number"
                min={1}
                inputMode="numeric"
                value={newTestingNumber}
                onChange={(e) => setNewTestingNumber(e.target.value)}
                placeholder="No."
                className="w-24"
              />
              <Input
                value={newTestingText}
                onChange={(e) => setNewTestingText(e.target.value)}
                placeholder="Add testing checklist item..."
                className="flex-1 min-w-[220px]"
              />
              <Button
                variant="outline"
                disabled={!newTestingText.trim() || savingTestingItem}
                onClick={() => void addTestingChecklistItem()}
              >
                {savingTestingItem ? "Saving..." : "Add"}
              </Button>
            </div>
          </div>
        </Card>
      ) : null}

      {activeTab === "tasks" ? (
        <div className="space-y-4">
          <div className="flex items-center justify-end">
            <Dialog open={createOpen} onOpenChange={setCreateOpen}>
              <DialogTrigger asChild>
                <Button variant="outline">+ Add Task</Button>
              </DialogTrigger>
              <DialogContent className="sm:max-w-lg">
                <DialogHeader>
                  <DialogTitle>New Task</DialogTitle>
                </DialogHeader>
                <div className="space-y-3">
                  <div className="space-y-2">
                    <Label>Title <span className="text-red-500">*</span></Label>
                    <Input value={newTitle} onChange={(e) => setNewTitle(e.target.value.toUpperCase())} />
                  </div>
                  <div className="space-y-2">
                    <Label>Description</Label>
                    <BoldOnlyEditor value={newDescription} onChange={setNewDescription} />
                  </div>
                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="space-y-2">
                      <Label>Status</Label>
                      <Select value={newStatus} onValueChange={(v) => setNewStatus(v as typeof newStatus)}>
                        <SelectTrigger>
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
                      <Label>Type</Label>
                      <Select value={newTaskType} onValueChange={(v) => setNewTaskType(v as typeof newTaskType)}>
                        <SelectTrigger>
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
                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="space-y-2">
                      <Label>Assign to <span className="text-red-500">*</span></Label>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="outline" className="w-full justify-between">
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
                      <Label>Phase</Label>
                      <Select value={newTaskPhase} onValueChange={setNewTaskPhase}>
                        <SelectTrigger>
                          <SelectValue placeholder="Select phase" />
                        </SelectTrigger>
                        <SelectContent>
                          {(isMstProject ? MST_PHASES : GENERAL_PHASES).map((p) => (
                            <SelectItem key={p} value={p}>
                              {PHASE_LABELS[p] || p}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="md:col-span-2">
                      <TaskSkillField
                        value={newSkillCategory}
                        onChange={setNewSkillCategory}
                        selectedAssigneeIds={newAssignees}
                        onSelectCandidate={(candidateId) => setNewAssignees((previous) => previous.includes(candidateId) ? previous : [...previous, candidateId])}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Start date</Label>
                      <Input
                        type="date"
                        value={newStartDate}
                        onChange={(e) => setNewStartDate(normalizeDueDateInput(e.target.value))}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Due date <span className="text-red-500">*</span></Label>
                      <Input
                        type="date"
                        value={newDueDate}
                        onChange={(e) => setNewDueDate(normalizeDueDateInput(e.target.value))}
                        required
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Finish period</Label>
                      <Select
                        value={newFinishPeriod}
                        onValueChange={(value) =>
                          setNewFinishPeriod(value as TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE)
                        }
                      >
                        <SelectTrigger>
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
                  <label className="flex items-center gap-3 rounded-md border px-3 py-2">
                    <Checkbox
                      checked={newDeadlineImportant}
                      onCheckedChange={(checked) => setNewDeadlineImportant(checked === true)}
                    />
                    <span className="text-sm font-medium">Deadline important</span>
                  </label>
                  <div className="flex justify-end">
                    <Button 
                      disabled={!newTitle.trim() || !newAssignees || newAssignees.length === 0 || !newDueDate || !newDueDate.trim() || creating} 
                      onClick={() => void submitCreateTask()}
                    >
                      {creating ? "Creating..." : "Create"}
                    </Button>
                  </div>
                </div>
              </DialogContent>
            </Dialog>
            <Dialog open={editOpen} onOpenChange={setEditOpen}>
              <DialogContent className="sm:max-w-lg">
                <DialogHeader>
                  <DialogTitle>Edit Task</DialogTitle>
                </DialogHeader>
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label>Title <span className="text-red-500">*</span></Label>
                    <Input value={editTitle} onChange={(e) => setEditTitle(e.target.value.toUpperCase())} />
                  </div>
                  <div className="space-y-2">
                    <Label>Description</Label>
                    <BoldOnlyEditor value={editDescription} onChange={setEditDescription} />
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                      <Label>Status</Label>
                      <Select value={editStatus} onValueChange={(v) => setEditStatus(v as (typeof TASK_STATUSES)[number])}>
                        <SelectTrigger>
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
                      <Label>Type</Label>
                      <Select value={editTaskType} onValueChange={(v) => setEditTaskType(v as typeof editTaskType)}>
                        <SelectTrigger>
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
                      <Label>Assign to <span className="text-red-500">*</span></Label>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="outline" className="w-full justify-between">
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
                      <Label>Phase</Label>
                      <Select value={editPhase} onValueChange={setEditPhase}>
                        <SelectTrigger>
                          <SelectValue placeholder="Select phase" />
                        </SelectTrigger>
                        <SelectContent>
                          {(isMstProject ? MST_PHASES : GENERAL_PHASES).map((p) => (
                            <SelectItem key={p} value={p}>
                              {PHASE_LABELS[p] || p}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="md:col-span-2">
                      <TaskSkillField
                        value={editSkillCategory}
                        onChange={setEditSkillCategory}
                        selectedAssigneeIds={editAssignees}
                        onSelectCandidate={(candidateId) => setEditAssignees((previous) => previous.includes(candidateId) ? previous : [...previous, candidateId])}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Start date</Label>
                      <Input
                        type="date"
                        value={editStartDate}
                        onChange={(e) => setEditStartDate(normalizeDueDateInput(e.target.value))}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Due date <span className="text-red-500">*</span></Label>
                      <Input
                        type="date"
                        value={editDueDate}
                        onChange={(e) => setEditDueDate(normalizeDueDateInput(e.target.value))}
                        required
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Finish period</Label>
                      <Select
                        value={editFinishPeriod}
                        onValueChange={(value) =>
                          setEditFinishPeriod(value as TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE)
                        }
                      >
                        <SelectTrigger>
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
                  <label className="flex items-center gap-3 rounded-md border px-3 py-2">
                    <Checkbox
                      checked={editDeadlineImportant}
                      onCheckedChange={(checked) => setEditDeadlineImportant(checked === true)}
                    />
                    <span className="text-sm font-medium">Deadline important</span>
                  </label>
                  <div className="flex justify-end gap-2">
                    <Button variant="outline" onClick={() => setEditOpen(false)} disabled={savingEdit}>
                      Cancel
                    </Button>
                    <Button 
                      disabled={!editTitle.trim() || !editAssignees || editAssignees.length === 0 || !editDueDate || !editDueDate.trim() || savingEdit} 
                      onClick={() => void saveEditTask()}
                    >
                      {savingEdit ? "Saving..." : "Save"}
                    </Button>
                  </div>
                </div>
              </DialogContent>
            </Dialog>
            <Dialog open={viewDescriptionOpen} onOpenChange={setViewDescriptionOpen}>
              <DialogContent className="sm:max-w-2xl z-[120]">
                <DialogHeader>
                  <DialogTitle className="text-slate-800">{viewingTaskTitle || "Task Description"}</DialogTitle>
                </DialogHeader>
                <div className="space-y-4">
                  <div className="space-y-2">
                    <Label className="text-slate-700">Description</Label>
                    {viewingTaskDescription && viewingTaskDescription.trim().length > 0 ? (
                      <div className="border border-slate-200 rounded-lg p-4 bg-slate-50 min-h-[100px] max-h-[400px] overflow-y-auto whitespace-pre-wrap text-sm text-slate-700">
                        {viewingTaskDescription}
                      </div>
                    ) : (
                      <div className="border border-slate-200 rounded-lg p-4 bg-slate-50 min-h-[100px] text-sm text-slate-500 italic">
                        No description provided.
                      </div>
                    )}
                  </div>
                  <div className="flex justify-end gap-2">
                    <Button 
                      variant="outline" 
                      onClick={() => setViewDescriptionOpen(false)}
                      className="rounded-xl"
                    >
                      Close
                    </Button>
                  </div>
                </div>
              </DialogContent>
            </Dialog>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Label className="text-xs text-slate-500">Assignee</Label>
            <Select value={taskAssigneeFilter} onValueChange={setTaskAssigneeFilter}>
              <SelectTrigger className="h-8 w-48">
                <SelectValue placeholder="All users" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_USERS_FILTER}>All users</SelectItem>
                {taskAssigneeOptions.map((option) => (
                  <SelectItem key={option.id} value={option.id}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Card className="p-0">
            <div className="space-y-3 p-3">
              {TASK_STATUSES.map((statusKey) => {
                const sectionTasks = tasksByStatus[statusKey]
                const statusLabelText = TASK_STATUS_LABELS[statusKey]
                return (
                  <div key={statusKey} className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
                    <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
                      <div className="text-xs font-semibold uppercase text-slate-600">{statusLabelText}</div>
                      <Badge variant="secondary" className="text-xs">
                        {sectionTasks.length}
                      </Badge>
                    </div>
                    <div className="grid min-w-[1080px] grid-cols-[minmax(320px,1fr)_100px_140px_130px_110px_230px] gap-3 border-b border-slate-200 bg-slate-50 px-6 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                      <div>Task Note</div>
                      <div>Assignee</div>
                      <div>Status</div>
                      <div>Due Date</div>
                      <div>Subtasks</div>
                      <div>Actions</div>
                    </div>
                    <div className="min-w-[1080px] divide-y">
                      {sectionTasks.length ? (
                        sectionTasks.map((task) => {
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
                  const statusValue = (task.status || "TODO") as (typeof TASK_STATUSES)[number]
                  const statusRowClass = statusValue === "DONE"
                    ? "border-green-200 border-l-green-500 bg-green-50/30 opacity-80"
                    : statusValue === "WAITING_CLIENT"
                      ? "border-[#B8860B] border-l-[#B8860B] bg-[#E2C15B]/75"
                    : statusValue === "WAITING_CONFIRMATION"
                      ? "border-blue-200 border-l-blue-500 bg-blue-50/40"
                      : statusValue === "IN_PROGRESS"
                        ? "border-amber-200 border-l-amber-500"
                        : "border-slate-200 border-l-slate-400"
                  const checklist = taskChecklists[task.id]
                  const checklistItems = checklist?.items
                    ? [...checklist.items].sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
                    : []
                  const isChecklistOpen = Boolean(taskChecklistOpen[task.id])
                  const isChecklistLoading = Boolean(taskChecklistLoading[task.id])
                  const checklistInputValue = taskChecklistInputs[task.id] || ""
                  return (
                    <div
                      key={task.id}
                      className={`px-6 py-4 text-sm border-l-4 ${statusRowClass}`}
                    >
                      <div className="grid grid-cols-[minmax(320px,1fr)_100px_140px_130px_110px_230px] items-start gap-3">
                        <div className="font-medium flex items-center gap-2 flex-wrap">
                          <TaskOneHMarker marker={task.one_h_marker} markerByGa={task.one_h_marker_by_ga} comment={task.one_h_marker_comment} />
                          <span className="min-w-0"><TaskMarkerComment comment={task.one_h_marker_comment} taskId={task.id} />{task.title}</span>
                          {task.skill_category ? (
                            <Badge variant="outline" className="text-xs">
                              {SKILL_CATEGORIES.find((category) => category.id === task.skill_category)?.label || task.skill_category}
                            </Badge>
                          ) : null}
                          {isDevelopmentProject && (
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
                          )}
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
                            <span className="text-muted-foreground">-</span>
                          )}
                        </div>
                        <div>
                          <Select
                            value={task.status || "TODO"}
                            onValueChange={(value) => void updateTaskStatus(task.id, value as Task["status"])}
                            onOpenChange={(open) => {
                              if (open && taskChecklists[task.id] === undefined) {
                                void loadTaskChecklist(task.id)
                              }
                            }}
                            disabled={updatingTaskId === task.id}
                          >
                            <SelectTrigger className="h-8">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {TASK_STATUSES.map((status) => {
                                // Disable all non-DONE options if task is DONE and user is not admin
                                const isDisabled = task.status === "DONE" && status !== "DONE" && user?.role !== "ADMIN"
                                const isChecklistBlocking =
                                  (status === "DONE" || status === "WAITING_CONFIRMATION") &&
                                  !isChecklistComplete(task.id)
                                return (
                                  <SelectItem
                                    key={status}
                                    value={status}
                                    disabled={isDisabled || isChecklistBlocking}
                                    title={isChecklistBlocking ? "Complete all subtasks first." : undefined}
                                  >
                                    {statusLabel(status)}
                                  </SelectItem>
                                )
                              })}
                            </SelectContent>
                          </Select>
                        </div>
                        <div className="flex items-center gap-2 whitespace-nowrap text-muted-foreground">
                          <span className={overdue ? "text-red-600 font-semibold" : undefined}>
                            {formatDateDisplay(task.due_date)}
                          </span>
                          {overdue ? (
                            <Badge variant="outline" className="border-red-200 text-red-700 bg-red-50">
                              Late
                            </Badge>
                          ) : null}
                        </div>
                        <div>
                          <Button
                            size="sm"
                            variant="outline"
                            className="w-full"
                            onClick={() => void toggleTaskChecklist(task.id)}
                          >
                            {isChecklistOpen ? "Hide" : "Subtasks"}
                          </Button>
                        </div>
                        <div className="flex items-center gap-2 whitespace-nowrap">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => startViewDescription(task)}
                            disabled={!task.description || task.description.trim().length === 0}
                            className="hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed"
                            title={!task.description || task.description.trim().length === 0 ? "No description available" : "View description"}
                          >
                            <Eye className="h-4 w-4 mr-1" />
                            View
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => startEditTask(task)}>
                            Edit
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={deletingTaskId === task.id}
                            className="text-red-600 border-red-200 hover:bg-red-50"
                            onClick={() => void deleteTask(task.id, task.title)}
                          >
                            {deletingTaskId === task.id ? "Deleting..." : "Delete"}
                          </Button>
                        </div>
                      </div>
                      {isChecklistOpen ? (
                        <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                          {isChecklistLoading ? (
                            <div className="text-sm text-muted-foreground">Loading checklist...</div>
                          ) : checklistItems.length ? (
                            <div className="space-y-2">
                              {checklistItems.map((item) => (
                                <div key={item.id} className="flex items-center gap-3 text-sm">
                                  <Checkbox
                                    checked={Boolean(item.is_checked)}
                                    onCheckedChange={(checked) =>
                                      void toggleTaskChecklistItem(task.id, item, checked === true)
                                    }
                                    disabled={
                                      !canEditTaskChecklist ||
                                      taskChecklistItemBusy[item.id] ||
                                      (Boolean(item.is_checked) && !canUncheckTaskChecklist)
                                    }
                                  />
                                  <div className={item.is_checked ? "text-muted-foreground line-through flex-1" : "text-slate-700 flex-1"}>
                                    {item.title || "-"}
                                  </div>
                                  {canEditTaskChecklist ? (
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      onClick={() => void deleteTaskChecklistItem(task.id, item)}
                                      disabled={taskChecklistItemBusy[item.id]}
                                      className="h-7 w-7 p-0 text-slate-400 hover:text-red-600"
                                    >
                                      ×
                                    </Button>
                                  ) : null}
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div className="text-sm text-muted-foreground">No checklist items yet.</div>
                          )}
                          {canEditTaskChecklist ? (
                            <div className="mt-3 flex flex-wrap items-center gap-2">
                              <Input
                                value={checklistInputValue}
                                onChange={(e) =>
                                  setTaskChecklistInputs((prev) => ({ ...prev, [task.id]: e.target.value }))
                                }
                                placeholder="Add checklist item..."
                                className="flex-1 min-w-[220px]"
                              />
                              <Button
                                variant="outline"
                                disabled={!checklistInputValue.trim() || taskChecklistSaving[task.id]}
                                onClick={() => void addTaskChecklistItem(task.id)}
                              >
                                {taskChecklistSaving[task.id] ? "Saving..." : "Add"}
                              </Button>
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  )
                        })
                      ) : (
                        <div className="px-4 py-3 text-sm text-muted-foreground">No tasks.</div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </Card>
        </div>
      ) : null}

      {activeTab === "development-checklist" ? (
        <Card className="bg-white/90 backdrop-blur-sm border-slate-200 shadow-sm rounded-2xl overflow-hidden">
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
                <DialogContent className="sm:max-w-lg bg-white border-slate-200 rounded-2xl">
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
                        className="border-slate-200 focus:border-slate-400 rounded-xl"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-slate-700">Comment / Notes</Label>
                      <Textarea
                        value={developmentChecklistComment}
                        onChange={(e) => setDevelopmentChecklistComment(e.target.value)}
                        placeholder="Add notes (optional)..."
                        rows={4}
                        className="border-slate-200 focus:border-slate-400 rounded-xl"
                      />
                    </div>
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="outline"
                        onClick={() => setDevelopmentChecklistCreateOpen(false)}
                        className="rounded-xl border-slate-200"
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
                {developmentChecklistItems.map((item, index) => {
                  const isEditing = developmentChecklistEditingId === item.id
                  return (
                    <div key={item.id} className="flex flex-wrap items-start gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 hover:bg-slate-50/30 transition-colors">
                      <div className="mt-1 w-6 text-right text-xs font-bold text-slate-900">{index + 1}.</div>
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
                              className="border-slate-200 focus:border-slate-400 rounded-xl"
                            />
                            <Textarea
                              value={developmentChecklistEditingComment}
                              onChange={(e) => setDevelopmentChecklistEditingComment(e.target.value)}
                              rows={3}
                              className="border-slate-200 focus:border-slate-400 rounded-xl"
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
                              className="rounded-xl border-slate-200"
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
                              className="rounded-xl border-slate-200"
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
        <div className="space-y-3">
          {activePhase === "DOCUMENTATION" ? (
            <Card className="p-6">
              <div className="text-lg font-semibold">Documentation checklist</div>
              <div className="mt-4 space-y-3">
                {documentationChecklist.length ? (
                  documentationChecklist.map((item, index) => {
                    const isEditing = documentationEditingId === item.id
                    const displayNumber = item.position ? item.position : index + 1
                    return (
                      <div key={item.id} className="flex flex-wrap items-start gap-3 rounded-lg border px-4 py-3">
                        <div className="mt-0.5 w-16 shrink-0 text-right text-sm text-muted-foreground">
                          {isEditing ? (
                            <Input
                              type="number"
                              min={1}
                              inputMode="numeric"
                              value={documentationEditingNumber}
                              onChange={(e) => setDocumentationEditingNumber(e.target.value)}
                              className="h-8 w-16 text-right"
                            />
                          ) : (
                            `${displayNumber}.`
                          )}
                        </div>
                        <Checkbox
                          checked={item.isChecked}
                          onCheckedChange={(checked) =>
                            toggleDocumentationChecklistItemDb(item.id, Boolean(checked))
                          }
                        />
                        <div className="flex-1">
                          {isEditing ? (
                            <Input
                              value={documentationEditingText}
                              onChange={(e) => setDocumentationEditingText(e.target.value)}
                            />
                          ) : (
                            <div className={item.isChecked ? "text-muted-foreground line-through" : ""}>
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
                              >
                                Save
                              </Button>
                              <Button size="sm" variant="ghost" onClick={cancelEditDocumentationItem}>
                                Cancel
                              </Button>
                            </>
                          ) : (
                            <>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => startEditDocumentationItem(item.id)}
                              >
                                Edit
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                className="text-red-600 border-red-200 hover:bg-red-50"
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
                  <div className="text-sm text-muted-foreground">No documentation checklist items yet.</div>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <Input
                    type="number"
                    min={1}
                    inputMode="numeric"
                    value={newDocumentationNumber}
                    onChange={(e) => setNewDocumentationNumber(e.target.value)}
                    placeholder="No."
                    className="w-24"
                  />
                  <Input
                    value={newDocumentationText}
                    onChange={(e) => setNewDocumentationText(e.target.value)}
                    placeholder="Add documentation checklist item..."
                    className="flex-1 min-w-[220px]"
                  />
                  <Button
                    variant="outline"
                    disabled={!newDocumentationText.trim() || savingDocumentationItem}
                    onClick={() => void addDocumentationChecklistItem()}
                  >
                    {savingDocumentationItem ? "Saving..." : "Add"}
                  </Button>
                </div>
              </div>
              <div className="mt-6">
                <div className="text-sm font-semibold">Documentation file paths</div>
                <div className="mt-3 flex items-center gap-2">
                  <Input
                    placeholder="Add file path..."
                    value={documentationFilePath}
                    onChange={(e) => setDocumentationFilePath(e.target.value)}
                  />
                  <Button
                    variant="outline"
                    disabled={!documentationFilePath.trim()}
                    onClick={addDocumentationFilePath}
                  >
                    Add
                  </Button>
                </div>
                {documentationFilePaths.length ? (
                  <div className="mt-3 space-y-2 text-sm text-muted-foreground">
                    {documentationFilePaths.map((item) => {
                      const isEditing = documentationFilePathEditingId === item.id
                      return (
                        <div
                          key={item.id}
                          className="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
                        >
                          {isEditing ? (
                            <>
                              <Input
                                value={documentationFilePathEditingText}
                                onChange={(e) => setDocumentationFilePathEditingText(e.target.value)}
                              />
                              <div className="flex items-center gap-2">
                                <Button
                                  size="sm"
                                  variant="outline"
                                  disabled={
                                    documentationFilePathSaving ||
                                    !documentationFilePathEditingText.trim()
                                  }
                                  onClick={() => void saveDocumentationFilePath()}
                                >
                                  Save
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={cancelEditDocumentationFilePath}
                                >
                                  Cancel
                                </Button>
                              </div>
                            </>
                          ) : (
                            <>
                              <div className="flex-1">{item.path}</div>
                              <div className="flex items-center gap-2">
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => startEditDocumentationFilePath(item.id)}
                                >
                                  Edit
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="text-red-600 border-red-200 hover:bg-red-50"
                                  onClick={() => void deleteDocumentationFilePath(item.id)}
                                >
                                  Delete
                                </Button>
                              </div>
                            </>
                          )}
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <div className="mt-3 text-sm text-muted-foreground">No file paths added.</div>
                )}
              </div>
            </Card>
          ) : (
            <>
              {isMstProject && activePhase === "PLANNING" ? (
                <div className="text-sm text-muted-foreground">
                  Planning checklists are available under <span className="font-medium">Project Acceptance</span> and{" "}
                  <span className="font-medium">GA Meeting</span>.
                </div>
              ) : null}

              <div className="flex items-center gap-2">
                <Input
                  placeholder="Add item..."
                  value={newChecklistContent}
                  onChange={(e) => setNewChecklistContent(e.target.value)}
                />
                <Button
                  variant="outline"
                  disabled={!newChecklistContent.trim() || addingChecklist}
                  onClick={() => void submitChecklistItem()}
                >
                  {addingChecklist ? "Adding..." : "Add"}
                </Button>
              </div>
              {visibleChecklistItems.length ? (
                visibleChecklistItems.map((item) => (
                  <Card
                    key={item.id}
                    className="cursor-pointer px-6 py-5"
                    onClick={() => void toggleChecklistItem(item.id, !item.is_checked)}
                  >
                    <div className="flex items-center gap-3">
                      <Checkbox checked={item.is_checked ?? false} />
                      <div className={item.is_checked ? "text-muted-foreground line-through" : ""}>
                        {(item as any).content || item.title}
                      </div>
                    </div>
                  </Card>
                ))
              ) : (
                <div className="text-sm text-muted-foreground">No checklist items yet.</div>
              )}
            </>
          )}
        </div>
      ) : null}

      {activeTab === "mst-acceptance" ? (
        <Card className="p-6">
          <div className="text-lg font-semibold">Project Acceptance</div>
          {isAdmin ? (
            <div className="mt-4 grid gap-2 md:grid-cols-[120px_1fr_auto]">
              <div className="space-y-1">
                <Label>Number</Label>
                <Input
                  value={mstAcceptanceNewNumber}
                  onChange={(e) => setMstAcceptanceNewNumber(e.target.value)}
                  placeholder="e.g. 3"
                />
              </div>
              <div className="space-y-1">
                <Label>Item</Label>
                <Input
                  value={mstAcceptanceNewText}
                  onChange={(e) => setMstAcceptanceNewText(e.target.value)}
                  placeholder="Add new checklist item..."
                />
              </div>
              <div className="flex items-end">
                <Button
                  variant="outline"
                  disabled={!mstAcceptanceNewText.trim() || mstAcceptanceSaving}
                  onClick={() => void addMstAcceptanceItem()}
                >
                  {mstAcceptanceSaving ? "Saving..." : "Add"}
                </Button>
              </div>
            </div>
          ) : null}
          <div className="mt-4 space-y-3">
            {mstAcceptanceChecklist.length ? (
              mstAcceptanceChecklist
                .filter((item) => item.item_type === "CHECKBOX")
                .map((item) => (
                  <div key={item.id} className="flex items-start gap-3 rounded-lg border px-4 py-3">
                    <div className="mt-0.5 w-7 shrink-0 text-right text-sm text-muted-foreground">
                      {(item.position ?? 0) + 1}.
                    </div>
                    <Checkbox
                      checked={Boolean(item.is_checked)}
                      onCheckedChange={(checked) => void toggleChecklistDbItem(item, Boolean(checked))}
                    />
                    <div className="flex-1">
                      {isAdmin && mstAcceptanceEditingId === item.id ? (
                        <div className="flex items-center gap-2">
                          <Input
                            value={mstAcceptanceEditingText}
                            onChange={(e) => setMstAcceptanceEditingText(e.target.value)}
                          />
                          <Button
                            variant="outline"
                            disabled={!mstAcceptanceEditingText.trim() || mstAcceptanceSaving}
                            onClick={() => void saveEditMstAcceptanceItem()}
                          >
                            Save
                          </Button>
                          <Button
                            variant="ghost"
                            onClick={() => {
                              setMstAcceptanceEditingId(null)
                              setMstAcceptanceEditingText("")
                            }}
                          >
                            Cancel
                          </Button>
                        </div>
                      ) : (
                        <div className={item.is_checked ? "text-muted-foreground line-through" : ""}>{item.title}</div>
                      )}
                    </div>
                    {isAdmin && mstAcceptanceEditingId !== item.id ? (
                      <div className="flex items-center gap-2">
                        <Button variant="ghost" onClick={() => startEditMstAcceptanceItem(item)}>
                          Edit
                        </Button>
                        <Button
                          variant="ghost"
                          disabled={mstAcceptanceSaving}
                          onClick={() => void deleteMstAcceptanceItem(item.id)}
                        >
                          Delete
                        </Button>
                      </div>
                    ) : null}
                  </div>
                ))
            ) : (
              <div className="text-sm text-muted-foreground">No items yet.</div>
            )}
          </div>
        </Card>
      ) : null}

      {activeTab === "mst-ga-meeting" ? (
        <Card className="p-6">
          <div className="text-lg font-semibold">GA Meeting</div>
          <div className="mt-4 space-y-3">
            {mstGaMeetingChecklist.length ? (
              mstGaMeetingChecklist
                .filter((item) => item.item_type === "CHECKBOX")
                .map((item) => (
                  <div key={item.id} className="flex items-start gap-3 rounded-lg border px-4 py-3">
                    <div className="mt-0.5 w-7 shrink-0 text-right text-sm text-muted-foreground">
                      {(item.position ?? 0) + 1}.
                    </div>
                    <Checkbox
                      checked={Boolean(item.is_checked)}
                      onCheckedChange={(checked) => void toggleChecklistDbItem(item, Boolean(checked))}
                    />
                    <div className="flex-1">
                      {isAdmin && mstGaMeetingEditingId === item.id ? (
                        <div className="flex items-center gap-2">
                          <Input
                            value={mstGaMeetingEditingText}
                            onChange={(e) => setMstGaMeetingEditingText(e.target.value)}
                          />
                          <Button
                            variant="outline"
                            disabled={!mstGaMeetingEditingText.trim() || mstGaMeetingSaving}
                            onClick={() => void saveEditMstGaMeetingItem()}
                          >
                            Save
                          </Button>
                          <Button
                            variant="ghost"
                            onClick={() => {
                              setMstGaMeetingEditingId(null)
                              setMstGaMeetingEditingText("")
                            }}
                          >
                            Cancel
                          </Button>
                        </div>
                      ) : (
                        <div className={item.is_checked ? "text-muted-foreground line-through" : ""}>{item.title}</div>
                      )}
                    </div>
                    {isAdmin && mstGaMeetingEditingId !== item.id ? (
                      <div className="flex items-center gap-2">
                        <Button variant="ghost" onClick={() => startEditMstGaMeetingItem(item)}>
                          Edit
                        </Button>
                        <Button
                          variant="ghost"
                          disabled={mstGaMeetingSaving}
                          onClick={() => void deleteMstGaMeetingItem(item.id)}
                        >
                          Delete
                        </Button>
                      </div>
                    ) : null}
                  </div>
                ))
            ) : (
              <div className="text-sm text-muted-foreground">No items yet.</div>
            )}
          </div>
          {isAdmin ? (
            <div className="mt-4 grid gap-2 md:grid-cols-[120px_1fr_auto]">
              <div className="space-y-1">
                <Label>Number</Label>
                <Input
                  value={mstGaMeetingNewNumber}
                  onChange={(e) => setMstGaMeetingNewNumber(e.target.value)}
                  placeholder="e.g. 3"
                />
              </div>
              <div className="space-y-1">
                <Label>Item</Label>
                <Input
                  value={mstGaMeetingNewText}
                  onChange={(e) => setMstGaMeetingNewText(e.target.value)}
                  placeholder="Add new checklist item..."
                />
              </div>
              <div className="flex items-end">
                <Button
                  variant="outline"
                  disabled={!mstGaMeetingNewText.trim() || mstGaMeetingSaving}
                  onClick={() => void addMstGaMeetingItem()}
                >
                  {mstGaMeetingSaving ? "Saving..." : "Add"}
                </Button>
              </div>
            </div>
          ) : null}
        </Card>
      ) : null}

      {activeTab === "members" ? (
        <div className="space-y-4">
          <div className="flex items-center justify-end">
            <Dialog open={membersOpen} onOpenChange={setMembersOpen}>
              <DialogTrigger asChild>
                <Button variant="outline">+ Add members</Button>
              </DialogTrigger>
              <DialogContent className="sm:max-w-lg">
                <DialogHeader>
                  <DialogTitle>Select members</DialogTitle>
                </DialogHeader>
                <div className="space-y-3">
                  {departmentUsers.length ? (
                    departmentUsers.map((u) => (
                      <div
                        key={u.id}
                        className="flex items-center justify-between rounded-md border px-3 py-2"
                        onClick={() => toggleMemberSelect(u.id)}
                      >
                        <div className="flex items-center gap-2">
                          <Checkbox checked={selectedMemberIds.includes(u.id)} />
                          <span>{u.full_name || u.username || u.email}</span>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="text-sm text-muted-foreground">No department users found.</div>
                  )}
                  <div className="flex justify-end gap-2">
                    <Button variant="outline" onClick={() => setMembersOpen(false)}>
                      Cancel
                    </Button>
                    <Button disabled={savingMembers || selectedMemberIds.length === 0} onClick={() => void submitMembers()}>
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
                <div key={m.id} className="flex flex-col items-center gap-3 text-center">
                  <div className="h-20 w-20 rounded-full bg-blue-100 text-lg font-semibold text-blue-700 flex items-center justify-center">
                    {initials(m.full_name || m.username || m.email)}
                  </div>
                  <div className="text-sm font-semibold">{m.full_name || m.username || m.email}</div>
                </div>
              ))
            ) : (
              <div className="text-sm text-muted-foreground">No members yet.</div>
            )}
          </div>
        </div>
      ) : null}

      {activeTab === "ga" ? (
        <div className="space-y-3">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <Select value={newGaNoteType} onValueChange={setNewGaNoteType}>
                <SelectTrigger className="w-28">
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
                <SelectTrigger className="w-40">
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
              />
              <Button
                variant="outline"
                disabled={!newGaNote.trim() || addingGaNote}
                onClick={() => void submitGaNote()}
              >
                {addingGaNote ? "Adding..." : "Add"}
              </Button>
            </div>
          </div>
          {gaNotes.length ? (
            gaNotes.map((note) => (
              <Card key={note.id} className="border-orange-100 p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Badge variant="outline" className={note.note_type === "KA" ? "border-orange-200 text-orange-600" : "border-blue-200 text-blue-600"}>
                      {note.note_type || "GA"}
                    </Badge>
                    <span>
                      From {userMap.get(note.created_by || "")?.full_name || userMap.get(note.created_by || "")?.username || "-"}
                    </span>
                    <span>• {formatDateTime(note.created_at)}</span>
                    {note.priority ? (
                      <Badge variant="secondary">{statusLabel(note.priority)}</Badge>
                    ) : null}
                  </div>
                  {note.status !== "CLOSED" ? (
                    <Button variant="outline" size="sm" onClick={() => void closeGaNote(note.id)}>
                      Close
                    </Button>
                  ) : (
                    <Badge variant="secondary">Closed</Badge>
                  )}
                </div>
                <div className="mt-3 text-sm text-muted-foreground">{note.content}</div>
              </Card>
            ))
          ) : (
            <div className="text-sm text-muted-foreground">No GA/KA notes yet.</div>
          )}
        </div>
      ) : null}

      {activeTab === "prompts" ? (
        <div className="grid gap-4 md:grid-cols-2">
          <Card className="p-5 space-y-3">
            <div className="text-sm font-semibold">GA Prompt</div>
            <Input
              value={gaPromptTitle}
              onChange={(e) => setGaPromptTitle(e.target.value)}
              placeholder="Enter prompt title..."
            />
            <Textarea value={gaPromptContent} onChange={(e) => setGaPromptContent(e.target.value)} rows={8} placeholder="Enter prompt content..." />
            <div className="flex justify-end">
              <Button variant="outline" disabled={savingGaPrompt} onClick={() => void savePrompt("GA_PROMPT")}>
                {savingGaPrompt ? "Saving..." : "Save"}
              </Button>
            </div>
            <div className="text-xs text-muted-foreground">Used for GA guidelines and standards.</div>
            {prompts.filter((p) => p.type === "GA_PROMPT").length ? (
              <div className="space-y-3 pt-2">
                {prompts
                  .filter((p) => p.type === "GA_PROMPT")
                  .map((prompt) => {
                    const isExpanded = expandedPrompts.has(prompt.id)
                    return (
                      <Card
                        key={prompt.id}
                        className="border border-muted p-4 cursor-pointer hover:bg-muted/50 transition-colors"
                        onClick={() => togglePromptExpanded(prompt.id)}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1">
                            <div className="font-medium mb-1">{prompt.title || "Untitled"}</div>
                            <div className="text-xs text-muted-foreground">
                              {formatDateTimeDMY(prompt.created_at)}
                            </div>
                            {isExpanded ? (
                              <div className="mt-3 text-sm text-muted-foreground whitespace-pre-wrap">{prompt.content}</div>
                            ) : (
                              <div className="mt-2 text-xs text-muted-foreground">Click to view description</div>
                            )}
                          </div>
                        </div>
                      </Card>
                    )
                  })}
              </div>
            ) : null}
          </Card>
          <Card className="p-5 space-y-3">
            <div className="text-sm font-semibold">Development Prompt</div>
            <Input
              value={devPromptTitle}
              onChange={(e) => setDevPromptTitle(e.target.value)}
              placeholder="Enter prompt title..."
            />
            <Textarea value={devPromptContent} onChange={(e) => setDevPromptContent(e.target.value)} rows={8} placeholder="Enter prompt content..." />
            <div className="flex justify-end">
              <Button variant="outline" disabled={savingDevPrompt} onClick={() => void savePrompt("ZHVILLIM_PROMPT")}>
                {savingDevPrompt ? "Saving..." : "Save"}
              </Button>
            </div>
            <div className="text-xs text-muted-foreground">Used by the development team.</div>
            {prompts.filter((p) => p.type === "ZHVILLIM_PROMPT").length ? (
              <div className="space-y-3 pt-2">
                {prompts
                  .filter((p) => p.type === "ZHVILLIM_PROMPT")
                  .map((prompt) => {
                    const isExpanded = expandedPrompts.has(prompt.id)
                    return (
                      <Card
                        key={prompt.id}
                        className="border border-muted p-4 cursor-pointer hover:bg-muted/50 transition-colors"
                        onClick={() => togglePromptExpanded(prompt.id)}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1">
                            <div className="font-medium mb-1">{prompt.title || "Untitled"}</div>
                            <div className="text-xs text-muted-foreground">
                              {formatDateTimeDMY(prompt.created_at)}
                            </div>
                            {isExpanded ? (
                              <div className="mt-3 text-sm text-muted-foreground whitespace-pre-wrap">{prompt.content}</div>
                            ) : (
                              <div className="mt-2 text-xs text-muted-foreground">Click to view description</div>
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
      <Dialog open={editProjectDueDateOpen} onOpenChange={setEditProjectDueDateOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Edit Project Due Date</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Due Date</Label>
              <Input
                type="date"
                value={editProjectDueDate}
                onChange={(e) => setEditProjectDueDate(normalizeDueDateInput(e.target.value))}
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setEditProjectDueDateOpen(false)} disabled={savingProjectDueDate}>
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
              >
                {savingProjectDueDate ? "Saving..." : "Save"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog
        open={Boolean(pendingStatusTaskId)}
        onOpenChange={(open) => {
          if (!open) {
            setPendingStatusTaskId(null)
            setPendingStatusValue("TODO")
            setPendingConfirmationAssigneeId("")
          }
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Select Confirmer</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="text-sm text-muted-foreground">
              Select manager/admin confirmer before setting task to Waiting Confirmation.
            </div>
            <div className="space-y-2">
              <Label>Confirm by (Manager/Admin)</Label>
              <Select
                value={pendingConfirmationAssigneeId || "__none__"}
                onValueChange={(value) => setPendingConfirmationAssigneeId(value === "__none__" ? "" : value)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select confirmer" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">Select confirmer</SelectItem>
                  {confirmerCandidates.map((candidate) => (
                    <SelectItem key={candidate.id} value={candidate.id}>
                      {candidate.full_name || candidate.username || "-"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => {
                  setPendingStatusTaskId(null)
                  setPendingStatusValue("TODO")
                  setPendingConfirmationAssigneeId("")
                }}
              >
                Cancel
              </Button>
              <Button disabled={!pendingConfirmationAssigneeId} onClick={() => void submitPendingStatusUpdate()}>
                Confirm
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
