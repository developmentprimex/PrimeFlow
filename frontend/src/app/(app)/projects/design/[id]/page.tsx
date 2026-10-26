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
import { BoldOnlyEditor } from "@/components/bold-only-editor"
import { ChevronDown } from "lucide-react"
import { useAuth } from "@/lib/auth"
import { formatDateDMY, formatDateTimeDMY, normalizeDueDateInput, toDateInputValue } from "@/lib/dates"
import { renderMarkedNoteContent } from "@/lib/note-markup"
import { getConfirmerCandidates, isWaitingConfirmation, validateWaitingConfirmation } from "@/lib/task-confirmation"
import type { ChecklistItem, GaNote, Meeting, Project, ProjectPrompt, Task, TaskPriority, User } from "@/lib/types"

function toDateInput(value?: string | null) {
  return toDateInputValue(value)
}

function todayInputValue() {
  const now = new Date()
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60 * 1000)
  return local.toISOString().slice(0, 10)
}

function formatDateDisplay(value?: string | null) {
  return formatDateDMY(value)
}

// MST phases for Graphic Design projects
const MST_PHASES = ["PLANNING", "PRODUCT", "CONTROL", "FINAL"] as const
const MST_PHASE_LABELS: Record<string, string> = {
  PLANNING: "Planning",
  PRODUCT: "Product",
  CONTROL: "Control",
  FINAL: "Final",
  CLOSED: "Closed",
}
const CONTROL_CHECKLIST_PATH = "control ko1/ko2"
const CONTROL_CHECKLIST_TITLE = "PËRGATITJA PËR DËRGIM KO1/KO2"
const FINALIZATION_PATH = "finalization"
const GD_MST_GJENERALE_PATH = "gd_mst_gjenerale"
const GD_MST_SOFA_NEW_PATH = "gd_mst_sofa_new"
const GD_MST_VITRINE_NEW_PATH = "gd_mst_vitrine_new"
const GD_MST_SIDEBOARD_NEW_PATH = "gd_mst_sideboard_new"
const GD_MST_LOWBOARD_PATH = "gd_mst_lowboard"
const LEGACY_GD_MST_PLANNING_PATH = "gd_mst_planning"
const FINALIZATION_TITLE = "Finalizimi"

// Tabs for Planning phase
const PLANNING_TABS = [
  { id: "description", label: "Description" },
  { id: "tasks", label: "Tasks" },
  { id: "checklist", label: "Checklist" },
  { id: "project-acceptance", label: "Pranimi i Projektit" },
  { id: "ga-meeting", label: "Takim me GA/DV" },
  { id: "members", label: "Members" },
  { id: "ga-notes", label: "GA Notes" },
] as const

// Tabs for Product phase
const PRODUCT_TABS = [
  { id: "tasks", label: "Tasks" },
  { id: "propozim-ko1-ko2", label: "PROPOZIM KO1/KO2" },
  { id: "punimi", label: "PUNIMI" },
  { id: "produkte-sa-jane-kryer", label: "PRODUKTE SA JANE KRYER" },
  { id: "members", label: "Members" },
  { id: "ga-notes", label: "GA Notes" },
] as const

// Tabs for Control phase
const CONTROL_TABS = [
  { id: "ko1-ko2", label: "KO1/KO2" },
  { id: "tasks", label: "Tasks" },
  { id: "checklist", label: "Checklist" },
  { id: "members", label: "Members" },
  { id: "ga-notes", label: "GA Notes" },
] as const

// Tabs for Final phase
const FINAL_TABS = [
  { id: "finalization", label: "Finalizimi" },
  { id: "ga-notes", label: "GA Notes" },
] as const

type TabId =
  | (typeof PLANNING_TABS)[number]["id"]
  | (typeof PRODUCT_TABS)[number]["id"]
  | (typeof CONTROL_TABS)[number]["id"]
  | (typeof FINAL_TABS)[number]["id"]

// Task statuses and priorities
const TASK_STATUSES = ["TODO", "IN_PROGRESS", "WAITING_CLIENT", "WAITING_CONFIRMATION", "DONE"] as const
const TASK_PRIORITIES = ["NORMAL", "HIGH"] as const
const PROJECT_TASK_TYPES = ["NORMAL", "HIGH", "1H"] as const


function initials(src: string) {
  return src
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("")
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

const sofaKey = (title?: string | null, keyword?: string | null) => `${title || ""}||${keyword || ""}`

const SOFA_NEW_SHEMBULL: Record<string, string[]> = {
  [sofaKey("PIKAT E SELLING IMAGE 1", "PIKAT GJENERALE - SELLING IMAGE_1")]: ["/sofa-new/selling-1.png"],
  [sofaKey("PIKAT E SELLING IMAGE 1", "VENDOSJA E FOTOVE NE KOCKA")]: [
    "/sofa-new/selling-2.1.png",
    "/sofa-new/selling-2.2.png",
    "/sofa-new/selling-2.3.png",
    "/sofa-new/selling-2.4.png",
  ],
  [sofaKey("PIKAT E SELLING IMAGE 1", "LOGO")]: ["/sofa-new/selling-3.png"],
  [sofaKey("PIKAT E SELLING IMAGE 2 - SKICA", "PIKAT GJENERALE")]: ["/sofa-new/skica-7.png"],
  [sofaKey("PIKAT E SELLING IMAGE 2 - SKICA", "LOGO")]: ["/sofa-new/skica-8.png"],
  [sofaKey("PIKAT E SELLING IMAGE 3 - NGJYRAT", "PIKAT GJENERALE")]: ["/sofa-new/ngjyrat-11.png"],
  [sofaKey("PIKAT E SELLING IMAGE 3 - NGJYRAT", "LOGOT")]: ["/sofa-new/ngjyrat-12.png"],
}
const SOFA_NEW_ROW_IMAGES: Record<number, string[]> = {
  1: ["/sofa-new/selling-1.png"],
  2: [
    "/sofa-new/selling-2.1.png",
    "/sofa-new/selling-2.2.png",
    "/sofa-new/selling-2.3.png",
    "/sofa-new/selling-2.4.png",
  ],
  3: ["/sofa-new/selling-3.png"],
  7: ["/sofa-new/skica-7.png"],
  8: ["/sofa-new/skica-8.png"],
  11: ["/sofa-new/ngjyrat-11.png"],
  12: ["/sofa-new/ngjyrat-12.png"],
}
const VITRINE_NEW_SHEMBULL: Record<string, string[]> = {}
const VITRINE_NEW_ROW_IMAGES: Record<number, string[]> = {
  1: ["/vitrine-new/selling-1.png"],
  2: ["/vitrine-new/selling-2.png"],
  3: ["/vitrine-new/selling-3.png"],
  4: ["/vitrine-new/selling-4.png"],
}
const VITRINE_NEW_ROW_SHEMBULL_TEXT: Record<number, string> = {
  7: "MST: Selling image 2 (Dimensionet / L/R ) duhet gjithmone te emertohet kodi i produktit SKU (KODI I MST) dhe _2",
  8: "MST: Selling image 3 (Variacioni) duhet gjithmone te emertohet kodi i produktit SKU (KODI I MST) dhe _3",
}
const SIDEBOARD_NEW_SHEMBULL: Record<string, string[]> = {}
const SIDEBOARD_NEW_ROW_IMAGES: Record<number, string[]> = {
  1: ["/sideboard_new/selling-1.png"],
  2: ["/sideboard_new/selling-2.png"],
  3: ["/sideboard_new/selling-3.png"],
  4: ["/sideboard_new/selling-4.png"],
}
const LOWBOARD_SHEMBULL: Record<string, string[]> = {}
const LOWBOARD_ROW_IMAGES: Record<number, string[]> = {
  4: ["/lowboard/image.png"],
}

function ShembullSlider({ urls }: { urls: string[] }) {
  const [index, setIndex] = React.useState(0)
  const [open, setOpen] = React.useState(false)
  React.useEffect(() => {
    setIndex(0)
  }, [urls.join("|")])

  if (!urls.length) {
    return <div className="text-xs text-muted-foreground italic">No photos</div>
  }

  const current = urls[Math.min(index, urls.length - 1)]
  const goPrev = () => setIndex((prev) => (prev - 1 + urls.length) % urls.length)
  const goNext = () => setIndex((prev) => (prev + 1) % urls.length)

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open image preview"
        className="group relative w-full max-w-[220px] h-[140px] bg-muted/40 rounded-md overflow-hidden border cursor-zoom-in"
      >
        <img src={current} alt="Shembull" className="w-full h-full object-cover" />
        <div className="absolute inset-0 bg-black/25 opacity-0 transition-opacity group-hover:opacity-100" />
      </button>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Button variant="outline" size="sm" onClick={goPrev}>
          Prev
        </Button>
        <span>
          {Math.min(index + 1, urls.length)} / {urls.length}
        </span>
        <Button variant="outline" size="sm" onClick={goNext}>
          Next
        </Button>
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="w-[90vw] max-w-[980px] h-[80vh] max-h-[80vh] p-0 overflow-hidden">
          <div className="flex h-full flex-col">
            <DialogHeader className="px-4 py-3 border-b">
              <DialogTitle>Image preview</DialogTitle>
            </DialogHeader>
            <div className="flex-1 px-4 py-3">
              <div className="h-full w-full flex items-center justify-center bg-muted/20 rounded-md">
                <img
                  src={current}
                  alt="Shembull full"
                  className="max-h-full max-w-full object-contain"
                />
              </div>
            </div>
            <div className="px-4 py-3 border-t">
              <div className="flex items-center justify-center gap-3 text-sm text-muted-foreground">
                <Button variant="outline" size="sm" onClick={goPrev}>
                  Prev
                </Button>
                <span>
                  {Math.min(index + 1, urls.length)} / {urls.length}
                </span>
                <Button variant="outline" size="sm" onClick={goNext}>
                  Next
                </Button>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function orderChecklistItems(items: ChecklistItem[]) {
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => {
      const aPos = a.item.position
      const bPos = b.item.position
      if (aPos == null && bPos == null) return a.index - b.index
      if (aPos == null) return 1
      if (bPos == null) return -1
      if (aPos !== bPos) return aPos - bPos
      return a.index - b.index
    })
    .map((entry) => entry.item)
}

function parseProductTotals(notes?: string | null) {
  if (!notes) return { total: "", completed: "" }
  const totalMatch = notes.match(/total_products[:=]\s*(\d+)/i)
  const completedMatch = notes.match(/completed_products[:=]\s*(\d+)/i)
  return {
    total: totalMatch ? totalMatch[1] : "",
    completed: completedMatch ? completedMatch[1] : "",
  }
}

function isKoTask(notes?: string | null) {
  return /ko_tab[:=]\s*KO1KO2/i.test(notes || "")
}

function hasProductTotals(notes?: string | null) {
  return /total_products[:=]\s*\d+/i.test(notes || "")
}

function checklistItemsForPhase(phase: string, items: ChecklistItem[]) {
  if (phase === "PLANNING") {
    return items.filter(
      (item) =>
        item.path === "project acceptance" ||
        item.path === "ga/dv meeting" ||
        item.path === GD_MST_GJENERALE_PATH ||
        item.path === GD_MST_SOFA_NEW_PATH ||
        item.path === GD_MST_VITRINE_NEW_PATH ||
        item.path === GD_MST_SIDEBOARD_NEW_PATH ||
        item.path === GD_MST_LOWBOARD_PATH
    )
  }
  if (phase === "PRODUCT") {
    return items.filter((item) => item.path === "propozim ko1/ko2" || item.path === "punimi")
  }
  if (phase === "CONTROL") {
    return items.filter((item) => item.path === CONTROL_CHECKLIST_PATH)
  }
  if (phase === "FINAL") {
    return items.filter((item) => item.path === FINALIZATION_PATH)
  }
  return []
}

export default function DesignProjectPage() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const projectId = String(params.id)
  const { apiFetch, user } = useAuth()
  const confirm = useConfirm()
  const stickyHeaderRef = React.useRef<HTMLDivElement | null>(null)
  const [stickyOffsetPx, setStickyOffsetPx] = React.useState(0)

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
  const [newChecklistContent, setNewChecklistContent] = React.useState("")
  const [newChecklistNumber, setNewChecklistNumber] = React.useState("")
  const [addingChecklist, setAddingChecklist] = React.useState(false)
  const [mstGjeneraleContent, setMstGjeneraleContent] = React.useState("")
  const [mstGjeneraleNumber, setMstGjeneraleNumber] = React.useState("")
  const [mstGjeneraleKeyword, setMstGjeneraleKeyword] = React.useState("")
  const [mstGjeneraleDescription, setMstGjeneraleDescription] = React.useState("")
  const [mstGjeneraleOwner, setMstGjeneraleOwner] = React.useState("")
  const [mstGjeneraleComment, setMstGjeneraleComment] = React.useState("")
  const [mstGjeneraleAdding, setMstGjeneraleAdding] = React.useState(false)
  const [mstGjeneraleCommentEditingId, setMstGjeneraleCommentEditingId] = React.useState<string | null>(null)
  const [mstGjeneraleCommentEditingText, setMstGjeneraleCommentEditingText] = React.useState("")
  const [mstGjeneraleCommentSaving, setMstGjeneraleCommentSaving] = React.useState(false)
  const [mstGjeneraleEditingId, setMstGjeneraleEditingId] = React.useState<string | null>(null)
  const [mstGjeneraleEditDraft, setMstGjeneraleEditDraft] = React.useState({
    number: "",
    title: "",
    keyword: "",
    description: "",
    owner: "",
    comment: "",
    is_checked: false,
  })
  const [mstGjeneraleEditingSaving, setMstGjeneraleEditingSaving] = React.useState(false)
  const [mstSofaNewContent, setMstSofaNewContent] = React.useState("")
  const [mstSofaNewNumber, setMstSofaNewNumber] = React.useState("")
  const [mstSofaNewKeyword, setMstSofaNewKeyword] = React.useState("")
  const [mstSofaNewDescription, setMstSofaNewDescription] = React.useState("")
  const [mstSofaNewAdding, setMstSofaNewAdding] = React.useState(false)
  const [mstSofaNewEditingId, setMstSofaNewEditingId] = React.useState<string | null>(null)
  const [mstSofaNewEditingSaving, setMstSofaNewEditingSaving] = React.useState(false)
  const [mstSofaNewEditDraft, setMstSofaNewEditDraft] = React.useState({
    number: "",
    title: "",
    keyword: "",
    description: "",
    is_checked: false,
  })
  const [mstVitrineNewContent, setMstVitrineNewContent] = React.useState("")
  const [mstVitrineNewNumber, setMstVitrineNewNumber] = React.useState("")
  const [mstVitrineNewKeyword, setMstVitrineNewKeyword] = React.useState("")
  const [mstVitrineNewDescription, setMstVitrineNewDescription] = React.useState("")
  const [mstVitrineNewAdding, setMstVitrineNewAdding] = React.useState(false)
  const [mstVitrineNewEditingId, setMstVitrineNewEditingId] = React.useState<string | null>(null)
  const [mstVitrineNewEditingSaving, setMstVitrineNewEditingSaving] = React.useState(false)
  const [mstVitrineNewEditDraft, setMstVitrineNewEditDraft] = React.useState({
    number: "",
    title: "",
    keyword: "",
    description: "",
    is_checked: false,
  })
  const [mstSideboardNewContent, setMstSideboardNewContent] = React.useState("")
  const [mstSideboardNewNumber, setMstSideboardNewNumber] = React.useState("")
  const [mstSideboardNewKeyword, setMstSideboardNewKeyword] = React.useState("")
  const [mstSideboardNewDescription, setMstSideboardNewDescription] = React.useState("")
  const [mstSideboardNewAdding, setMstSideboardNewAdding] = React.useState(false)
  const [mstSideboardNewEditingId, setMstSideboardNewEditingId] = React.useState<string | null>(null)
  const [mstSideboardNewEditingSaving, setMstSideboardNewEditingSaving] = React.useState(false)
  const [mstSideboardNewEditDraft, setMstSideboardNewEditDraft] = React.useState({
    number: "",
    title: "",
    keyword: "",
    description: "",
    is_checked: false,
  })
  const [mstLowboardContent, setMstLowboardContent] = React.useState("")
  const [mstLowboardNumber, setMstLowboardNumber] = React.useState("")
  const [mstLowboardKeyword, setMstLowboardKeyword] = React.useState("")
  const [mstLowboardDescription, setMstLowboardDescription] = React.useState("")
  const [mstLowboardAdding, setMstLowboardAdding] = React.useState(false)
  const [mstLowboardEditingId, setMstLowboardEditingId] = React.useState<string | null>(null)
  const [mstLowboardEditingSaving, setMstLowboardEditingSaving] = React.useState(false)
  const [mstLowboardEditDraft, setMstLowboardEditDraft] = React.useState({
    number: "",
    title: "",
    keyword: "",
    description: "",
    is_checked: false,
  })
  const [mstChecklistTab, setMstChecklistTab] = React.useState<
    "gjenerale" | "sofa_new" | "vitrine_new" | "sideboard_new" | "lowboard"
  >("gjenerale")
  const [createOpen, setCreateOpen] = React.useState(false)
  const [newTitle, setNewTitle] = React.useState("")
  const [newDescription, setNewDescription] = React.useState("")
  const [newStatus, setNewStatus] = React.useState<(typeof TASK_STATUSES)[number]>("TODO")
  const [newTaskType, setNewTaskType] = React.useState<(typeof PROJECT_TASK_TYPES)[number]>("NORMAL")
  const [newAssignees, setNewAssignees] = React.useState<string[]>([])
  const [newTaskPhase, setNewTaskPhase] = React.useState<string>("")
  const [newDueDate, setNewDueDate] = React.useState("")
  const [newStartDate, setNewStartDate] = React.useState("")
  const [newDeadlineImportant, setNewDeadlineImportant] = React.useState(false)
  const [creating, setCreating] = React.useState(false)
  const [editingDescription, setEditingDescription] = React.useState("")
  const [savingDescription, setSavingDescription] = React.useState(false)
  const [membersOpen, setMembersOpen] = React.useState(false)
  const [selectedMemberIds, setSelectedMemberIds] = React.useState<string[]>([])
  const [savingMembers, setSavingMembers] = React.useState(false)
  const [advancingPhase, setAdvancingPhase] = React.useState(false)
  const [resettingPhase, setResettingPhase] = React.useState(false)
  const [viewedPhase, setViewedPhase] = React.useState<string | null>(null)
  const [newGaNote, setNewGaNote] = React.useState("")
  const [newGaNoteType, setNewGaNoteType] = React.useState("GA")
  const [newGaNotePriority, setNewGaNotePriority] = React.useState<"__none__" | "NORMAL" | "HIGH">("__none__")
  const [addingGaNote, setAddingGaNote] = React.useState(false)
  
  // Admin controls for Project Acceptance checklist
  const [acceptanceEditingId, setAcceptanceEditingId] = React.useState<string | null>(null)
  const [acceptanceEditingText, setAcceptanceEditingText] = React.useState("")
  const [acceptanceNewText, setAcceptanceNewText] = React.useState("")
  const [acceptanceNewNumber, setAcceptanceNewNumber] = React.useState("")
  const [acceptanceSaving, setAcceptanceSaving] = React.useState(false)
  
  // Admin controls for GA/DV Meeting checklist
  const [gaMeetingEditingId, setGaMeetingEditingId] = React.useState<string | null>(null)
  const [gaMeetingEditingText, setGaMeetingEditingText] = React.useState("")
  const [gaMeetingNewText, setGaMeetingNewText] = React.useState("")
  const [gaMeetingNewNumber, setGaMeetingNewNumber] = React.useState("")
  const [gaMeetingSaving, setGaMeetingSaving] = React.useState(false)
  
  // Admin controls for PROPOZIM KO1/KO2 checklist
  const [propozimEditingId, setPropozimEditingId] = React.useState<string | null>(null)
  const [propozimEditingText, setPropozimEditingText] = React.useState("")
  const [propozimNewText, setPropozimNewText] = React.useState("")
  const [propozimNewNumber, setPropozimNewNumber] = React.useState("")
  const [propozimSaving, setPropozimSaving] = React.useState(false)
  
  // Admin controls for PUNIMI checklist
  const [punimiEditingId, setPunimiEditingId] = React.useState<string | null>(null)
  const [punimiEditingText, setPunimiEditingText] = React.useState("")
  const [punimiNewText, setPunimiNewText] = React.useState("")
  const [punimiNewNumber, setPunimiNewNumber] = React.useState("")
  const [punimiSaving, setPunimiSaving] = React.useState(false)

  // Admin controls for Finalization checklist
  const [finalizationNewText, setFinalizationNewText] = React.useState("")
  const [finalizationNewNumber, setFinalizationNewNumber] = React.useState("")
  const [finalizationSaving, setFinalizationSaving] = React.useState(false)
  
  // Comment editing state (for all checklist items)
  const [commentEditingId, setCommentEditingId] = React.useState<string | null>(null)
  const [commentEditingText, setCommentEditingText] = React.useState("")
  const [commentSaving, setCommentSaving] = React.useState(false)
  const [controlChecklistEditingId, setControlChecklistEditingId] = React.useState<string | null>(null)
  const [controlChecklistEditingText, setControlChecklistEditingText] = React.useState("")
  const [controlChecklistSaving, setControlChecklistSaving] = React.useState(false)
  const [taskStatusSaving, setTaskStatusSaving] = React.useState<Record<string, boolean>>({})
  const [pendingStatusTaskId, setPendingStatusTaskId] = React.useState<string | null>(null)
  const [pendingStatusValue, setPendingStatusValue] = React.useState<Task["status"]>("TODO")
  const [pendingConfirmationAssigneeId, setPendingConfirmationAssigneeId] = React.useState("")

  // Inline task form state for Produkte Sa Jane Kryer
  const [newProductTaskTitle, setNewProductTaskTitle] = React.useState("")
  const [newProductTaskAssignee, setNewProductTaskAssignee] = React.useState<string>("__unassigned__")
  const [newProductTaskTotal, setNewProductTaskTotal] = React.useState("")
  const [newProductTaskCompleted, setNewProductTaskCompleted] = React.useState("")
  const [creatingProductTask, setCreatingProductTask] = React.useState(false)
  const [newKoTaskTitle, setNewKoTaskTitle] = React.useState("")
  const [newKoTaskAssignee, setNewKoTaskAssignee] = React.useState<string>("__unassigned__")
  const [newKoTaskTotal, setNewKoTaskTotal] = React.useState("")
  const [newKoTaskCompleted, setNewKoTaskCompleted] = React.useState("")
  const [creatingKoTask, setCreatingKoTask] = React.useState(false)
  const [productTaskEdits, setProductTaskEdits] = React.useState<
    Record<
      string,
      {
        total: string
        completed: string
        assigned_to: string | null
        status: Task["status"]
      }
    >
  >({})
  const [editingTaskIds, setEditingTaskIds] = React.useState<Record<string, boolean>>({})
  const [editingTaskTitles, setEditingTaskTitles] = React.useState<Record<string, string>>({})
  const [editingTaskAssignees, setEditingTaskAssignees] = React.useState<Record<string, string>>({})
  const [editingTaskTotals, setEditingTaskTotals] = React.useState<Record<string, string>>({})
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
  const canEditGjenerale =
    Boolean(isAdmin || isManager) || Boolean(user && members.some((m) => m.id === user.id))

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

  // Load project data
  React.useEffect(() => {
    const load = async () => {
      const pRes = await apiFetch(`/projects/${projectId}`)
      if (!pRes.ok) return
      const p = (await pRes.json()) as Project
      if (p.project_type === "GD_DEVELOPMENT") {
        router.replace(`/projects/${p.id}`)
        return
      }
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
        setChecklistItems(items)
      }
      if (gRes.ok) setGaNotes((await gRes.json()) as GaNote[])
      if (prRes.ok) setPrompts((await prRes.json()) as ProjectPrompt[])
      if (meetingsRes.ok) setMeetings((await meetingsRes.json()) as Meeting[])
      if (usersRes.ok) {
        const users = (await usersRes.json()) as User[]
        setAllUsers(users)
        setDepartmentUsers(users.filter((u) => u.department_id === p.department_id))
      }
    }
    void load()
  }, [apiFetch, projectId, router])

  React.useEffect(() => {
    if (project?.current_phase) setViewedPhase(project.current_phase)
  }, [project?.current_phase])

  React.useEffect(() => {
    if (!membersOpen) return
    setSelectedMemberIds(members.map((m) => m.id))
  }, [membersOpen, members])

  React.useEffect(() => {
    if (!createOpen) return
    if (newTaskPhase) return
    const phaseValue = viewedPhase || project?.current_phase || "PLANNING"
    setNewTaskPhase(phaseValue)
  }, [createOpen, newTaskPhase, project?.current_phase, viewedPhase])

  React.useEffect(() => {
    const node = stickyHeaderRef.current
    if (!node) return
    const update = () => {
      const rect = node.getBoundingClientRect()
      setStickyOffsetPx(Math.round(rect.height))
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  // Task creation
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
        phase: newTaskPhase || activePhase,
        start_date: newStartDate || null,
        due_date: newDueDate || null,
        is_deadline_important: newDeadlineImportant,
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
      setNewDueDate("")
      setNewStartDate("")
      setNewDeadlineImportant(false)
      toast.success("Task created")
    } finally {
      setCreating(false)
    }
  }

  // Save description
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

  // Add checklist item
  const submitChecklistItem = async (options?: {
    path?: string
    content?: string
    number?: string
    onReset?: () => void
  }) => {
    if (!project) return
    const content = (options?.content ?? newChecklistContent).trim()
    if (!content) return
    const rawNumber = (options?.number ?? newChecklistNumber).trim()
    const parsedNumber = Number.parseInt(rawNumber, 10)
    const position =
      rawNumber && !Number.isNaN(parsedNumber) ? Math.max(0, parsedNumber - 1) : undefined
    setAddingChecklist(true)
    try {
      const payload: Record<string, unknown> = {
        project_id: project.id,
        item_type: "CHECKBOX",
        title: content,
        is_checked: false,
      }
      if (options?.path) {
        payload.path = options.path
      } else if (activePhase === "CONTROL") {
        payload.path = CONTROL_CHECKLIST_PATH
      }
      if (position != null) payload.position = position

      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to add checklist item"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      if (options?.onReset) {
        options.onReset()
      } else {
        setNewChecklistContent("")
        setNewChecklistNumber("")
      }
      await reloadChecklistItems()
      toast.success("Checklist item added")
    } finally {
      setAddingChecklist(false)
    }
  }

  const submitMstGjeneraleRow = async () => {
    if (!project) return
    const title = mstGjeneraleContent.trim()
    if (!title) return
    const rawNumber = mstGjeneraleNumber.trim()
    const parsedNumber = Number.parseInt(rawNumber, 10)
    const position =
      rawNumber && !Number.isNaN(parsedNumber) ? Math.max(0, parsedNumber - 1) : undefined
    setMstGjeneraleAdding(true)
    try {
      const payload: Record<string, unknown> = {
        project_id: project.id,
        item_type: "CHECKBOX",
        path: GD_MST_GJENERALE_PATH,
        title,
        keyword: mstGjeneraleKeyword.trim() || null,
        description: mstGjeneraleDescription.trim() || null,
        owner: mstGjeneraleOwner.trim() || null,
        comment: mstGjeneraleComment.trim() || null,
        is_checked: false,
      }
      if (position != null) payload.position = position

      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to add checklist item"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      setMstGjeneraleContent("")
      setMstGjeneraleNumber("")
      setMstGjeneraleKeyword("")
      setMstGjeneraleDescription("")
      setMstGjeneraleOwner("")
      setMstGjeneraleComment("")
      await reloadChecklistItems()
      toast.success("Checklist item added")
    } finally {
      setMstGjeneraleAdding(false)
    }
  }

  const submitMstSofaNewRow = async () => {
    if (!project) return
    const title = mstSofaNewContent.trim()
    if (!title) return
    const rawNumber = mstSofaNewNumber.trim()
    const parsedNumber = Number.parseInt(rawNumber, 10)
    const position =
      rawNumber && !Number.isNaN(parsedNumber) ? Math.max(0, parsedNumber - 1) : undefined
    setMstSofaNewAdding(true)
    try {
      const payload: Record<string, unknown> = {
        project_id: project.id,
        item_type: "CHECKBOX",
        path: GD_MST_SOFA_NEW_PATH,
        title,
        keyword: mstSofaNewKeyword.trim() || null,
        description: mstSofaNewDescription.trim() || null,
        is_checked: false,
      }
      if (position != null) payload.position = position

      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to add checklist item"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      setMstSofaNewContent("")
      setMstSofaNewNumber("")
      setMstSofaNewKeyword("")
      setMstSofaNewDescription("")
      await reloadChecklistItems()
      toast.success("Checklist item added")
    } finally {
      setMstSofaNewAdding(false)
    }
  }

  const submitMstVitrineNewRow = async () => {
    if (!project) return
    const title = mstVitrineNewContent.trim()
    if (!title) return
    const rawNumber = mstVitrineNewNumber.trim()
    const parsedNumber = Number.parseInt(rawNumber, 10)
    const position =
      rawNumber && !Number.isNaN(parsedNumber) ? Math.max(0, parsedNumber - 1) : undefined
    setMstVitrineNewAdding(true)
    try {
      const payload: Record<string, unknown> = {
        project_id: project.id,
        item_type: "CHECKBOX",
        path: GD_MST_VITRINE_NEW_PATH,
        title,
        keyword: mstVitrineNewKeyword.trim() || null,
        description: mstVitrineNewDescription.trim() || null,
        is_checked: false,
      }
      if (position != null) payload.position = position

      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to add checklist item"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      setMstVitrineNewContent("")
      setMstVitrineNewNumber("")
      setMstVitrineNewKeyword("")
      setMstVitrineNewDescription("")
      await reloadChecklistItems()
      toast.success("Checklist item added")
    } finally {
      setMstVitrineNewAdding(false)
    }
  }

  const submitMstSideboardNewRow = async () => {
    if (!project) return
    const title = mstSideboardNewContent.trim()
    if (!title) return
    const rawNumber = mstSideboardNewNumber.trim()
    const parsedNumber = Number.parseInt(rawNumber, 10)
    const position =
      rawNumber && !Number.isNaN(parsedNumber) ? Math.max(0, parsedNumber - 1) : undefined
    setMstSideboardNewAdding(true)
    try {
      const payload: Record<string, unknown> = {
        project_id: project.id,
        item_type: "CHECKBOX",
        path: GD_MST_SIDEBOARD_NEW_PATH,
        title,
        keyword: mstSideboardNewKeyword.trim() || null,
        description: mstSideboardNewDescription.trim() || null,
        is_checked: false,
      }
      if (position != null) payload.position = position

      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to add checklist item"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      setMstSideboardNewContent("")
      setMstSideboardNewNumber("")
      setMstSideboardNewKeyword("")
      setMstSideboardNewDescription("")
      await reloadChecklistItems()
      toast.success("Checklist item added")
    } finally {
      setMstSideboardNewAdding(false)
    }
  }

  const submitMstLowboardRow = async () => {
    if (!project) return
    const title = mstLowboardContent.trim()
    if (!title) return
    const rawNumber = mstLowboardNumber.trim()
    const parsedNumber = Number.parseInt(rawNumber, 10)
    const position =
      rawNumber && !Number.isNaN(parsedNumber) ? Math.max(0, parsedNumber - 1) : undefined
    setMstLowboardAdding(true)
    try {
      const payload: Record<string, unknown> = {
        project_id: project.id,
        item_type: "CHECKBOX",
        path: GD_MST_LOWBOARD_PATH,
        title,
        keyword: mstLowboardKeyword.trim() || null,
        description: mstLowboardDescription.trim() || null,
        is_checked: false,
      }
      if (position != null) payload.position = position

      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        let detail = "Failed to add checklist item"
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      setMstLowboardContent("")
      setMstLowboardNumber("")
      setMstLowboardKeyword("")
      setMstLowboardDescription("")
      await reloadChecklistItems()
      toast.success("Checklist item added")
    } finally {
      setMstLowboardAdding(false)
    }
  }

  // Toggle checklist item
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

  // Reload checklist items
  const reloadChecklistItems = async () => {
    if (!project) return
    const res = await apiFetch(`/checklist-items?project_id=${project.id}`)
    if (res.ok) {
      const items = (await res.json()) as ChecklistItem[]
      setChecklistItems(items)
    }
  }

  // Comment management functions
  const startEditComment = (item: ChecklistItem) => {
    setCommentEditingId(item.id)
    setCommentEditingText(item.comment || "")
  }

  const cancelEditComment = () => {
    setCommentEditingId(null)
    setCommentEditingText("")
  }

  const saveComment = async (itemId: string) => {
    setCommentSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${itemId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comment: commentEditingText.trim() || null }),
      })
      if (!res.ok) {
        toast.error("Failed to save comment")
        return
      }
      await reloadChecklistItems()
      setCommentEditingId(null)
      setCommentEditingText("")
      toast.success("Comment saved")
    } finally {
      setCommentSaving(false)
    }
  }

  const startEditMstGjeneraleComment = (item: ChecklistItem) => {
    setMstGjeneraleCommentEditingId(item.id)
    setMstGjeneraleCommentEditingText(item.comment || "")
  }

  const cancelEditMstGjeneraleComment = () => {
    setMstGjeneraleCommentEditingId(null)
    setMstGjeneraleCommentEditingText("")
  }

  const saveMstGjeneraleComment = async (itemId: string) => {
    setMstGjeneraleCommentSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${itemId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comment: mstGjeneraleCommentEditingText.trim() || null }),
      })
      if (!res.ok) {
        toast.error("Failed to save comment")
        return
      }
      await reloadChecklistItems()
      setMstGjeneraleCommentEditingId(null)
      setMstGjeneraleCommentEditingText("")
      toast.success("Comment saved")
    } finally {
      setMstGjeneraleCommentSaving(false)
    }
  }

  const startEditMstSofaNewRow = (item: ChecklistItem) => {
    setMstSofaNewEditingId(item.id)
    setMstSofaNewEditDraft({
      number: `${(item.position ?? 0) + 1}`,
      title: item.title || "",
      keyword: item.keyword || "",
      description: item.description || "",
      is_checked: item.is_checked || false,
    })
  }

  const cancelEditMstSofaNewRow = () => {
    setMstSofaNewEditingId(null)
    setMstSofaNewEditDraft({
      number: "",
      title: "",
      keyword: "",
      description: "",
      is_checked: false,
    })
  }

  const saveEditMstSofaNewRow = async () => {
    if (!mstSofaNewEditingId) return
    const title = mstSofaNewEditDraft.title.trim()
    if (!title) return
    const rawNumber = mstSofaNewEditDraft.number.trim()
    const parsedNumber = Number.parseInt(rawNumber, 10)
    const position =
      rawNumber && !Number.isNaN(parsedNumber) ? Math.max(0, parsedNumber - 1) : undefined
    setMstSofaNewEditingSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${mstSofaNewEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          position,
          title,
          keyword: mstSofaNewEditDraft.keyword.trim() || null,
          description: mstSofaNewEditDraft.description.trim() || null,
          is_checked: mstSofaNewEditDraft.is_checked,
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
        toast.error(detail)
        return
      }
      await reloadChecklistItems()
      cancelEditMstSofaNewRow()
      toast.success("Checklist item updated")
    } finally {
      setMstSofaNewEditingSaving(false)
    }
  }

  const deleteMstSofaNewRow = async (itemId: string) => {
    if (!(await confirm({ title: "Delete checklist item", description: "Delete this checklist item?", confirmLabel: "Delete", variant: "destructive" }))) return
    const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
    if (!res.ok) {
      toast.error("Failed to delete checklist item")
      return
    }
    await reloadChecklistItems()
    toast.success("Checklist item deleted")
  }

  const startEditMstVitrineNewRow = (item: ChecklistItem) => {
    setMstVitrineNewEditingId(item.id)
    setMstVitrineNewEditDraft({
      number: `${(item.position ?? 0) + 1}`,
      title: item.title || "",
      keyword: item.keyword || "",
      description: item.description || "",
      is_checked: item.is_checked || false,
    })
  }

  const cancelEditMstVitrineNewRow = () => {
    setMstVitrineNewEditingId(null)
    setMstVitrineNewEditDraft({
      number: "",
      title: "",
      keyword: "",
      description: "",
      is_checked: false,
    })
  }

  const saveEditMstVitrineNewRow = async () => {
    if (!mstVitrineNewEditingId) return
    const title = mstVitrineNewEditDraft.title.trim()
    if (!title) return
    const rawNumber = mstVitrineNewEditDraft.number.trim()
    const parsedNumber = Number.parseInt(rawNumber, 10)
    const position =
      rawNumber && !Number.isNaN(parsedNumber) ? Math.max(0, parsedNumber - 1) : undefined
    setMstVitrineNewEditingSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${mstVitrineNewEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          position,
          title,
          keyword: mstVitrineNewEditDraft.keyword.trim() || null,
          description: mstVitrineNewEditDraft.description.trim() || null,
          is_checked: mstVitrineNewEditDraft.is_checked,
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
        toast.error(detail)
        return
      }
      await reloadChecklistItems()
      cancelEditMstVitrineNewRow()
      toast.success("Checklist item updated")
    } finally {
      setMstVitrineNewEditingSaving(false)
    }
  }

  const deleteMstVitrineNewRow = async (itemId: string) => {
    if (!(await confirm({ title: "Delete checklist item", description: "Delete this checklist item?", confirmLabel: "Delete", variant: "destructive" }))) return
    const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
    if (!res.ok) {
      toast.error("Failed to delete checklist item")
      return
    }
    await reloadChecklistItems()
    toast.success("Checklist item deleted")
  }

  const startEditMstSideboardNewRow = (item: ChecklistItem) => {
    setMstSideboardNewEditingId(item.id)
    setMstSideboardNewEditDraft({
      number: `${(item.position ?? 0) + 1}`,
      title: item.title || "",
      keyword: item.keyword || "",
      description: item.description || "",
      is_checked: item.is_checked || false,
    })
  }

  const cancelEditMstSideboardNewRow = () => {
    setMstSideboardNewEditingId(null)
    setMstSideboardNewEditDraft({
      number: "",
      title: "",
      keyword: "",
      description: "",
      is_checked: false,
    })
  }

  const saveEditMstSideboardNewRow = async () => {
    if (!mstSideboardNewEditingId) return
    const title = mstSideboardNewEditDraft.title.trim()
    if (!title) return
    const rawNumber = mstSideboardNewEditDraft.number.trim()
    const parsedNumber = Number.parseInt(rawNumber, 10)
    const position =
      rawNumber && !Number.isNaN(parsedNumber) ? Math.max(0, parsedNumber - 1) : undefined
    setMstSideboardNewEditingSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${mstSideboardNewEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          position,
          title,
          keyword: mstSideboardNewEditDraft.keyword.trim() || null,
          description: mstSideboardNewEditDraft.description.trim() || null,
          is_checked: mstSideboardNewEditDraft.is_checked,
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
        toast.error(detail)
        return
      }
      await reloadChecklistItems()
      cancelEditMstSideboardNewRow()
      toast.success("Checklist item updated")
    } finally {
      setMstSideboardNewEditingSaving(false)
    }
  }

  const deleteMstSideboardNewRow = async (itemId: string) => {
    if (!(await confirm({ title: "Delete checklist item", description: "Delete this checklist item?", confirmLabel: "Delete", variant: "destructive" }))) return
    const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
    if (!res.ok) {
      toast.error("Failed to delete checklist item")
      return
    }
    await reloadChecklistItems()
    toast.success("Checklist item deleted")
  }

  const startEditMstLowboardRow = (item: ChecklistItem) => {
    setMstLowboardEditingId(item.id)
    setMstLowboardEditDraft({
      number: `${(item.position ?? 0) + 1}`,
      title: item.title || "",
      keyword: item.keyword || "",
      description: item.description || "",
      is_checked: item.is_checked || false,
    })
  }

  const cancelEditMstLowboardRow = () => {
    setMstLowboardEditingId(null)
    setMstLowboardEditDraft({
      number: "",
      title: "",
      keyword: "",
      description: "",
      is_checked: false,
    })
  }

  const saveEditMstLowboardRow = async () => {
    if (!mstLowboardEditingId) return
    const title = mstLowboardEditDraft.title.trim()
    if (!title) return
    const rawNumber = mstLowboardEditDraft.number.trim()
    const parsedNumber = Number.parseInt(rawNumber, 10)
    const position =
      rawNumber && !Number.isNaN(parsedNumber) ? Math.max(0, parsedNumber - 1) : undefined
    setMstLowboardEditingSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${mstLowboardEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          position,
          title,
          keyword: mstLowboardEditDraft.keyword.trim() || null,
          description: mstLowboardEditDraft.description.trim() || null,
          is_checked: mstLowboardEditDraft.is_checked,
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
        toast.error(detail)
        return
      }
      await reloadChecklistItems()
      cancelEditMstLowboardRow()
      toast.success("Checklist item updated")
    } finally {
      setMstLowboardEditingSaving(false)
    }
  }

  const deleteMstLowboardRow = async (itemId: string) => {
    if (!(await confirm({ title: "Delete checklist item", description: "Delete this checklist item?", confirmLabel: "Delete", variant: "destructive" }))) return
    const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
    if (!res.ok) {
      toast.error("Failed to delete checklist item")
      return
    }
    await reloadChecklistItems()
    toast.success("Checklist item deleted")
  }

  const startEditMstGjeneraleRow = (item: ChecklistItem) => {
    setMstGjeneraleEditingId(item.id)
    setMstGjeneraleEditDraft({
      number: `${(item.position ?? 0) + 1}`,
      title: item.title || "",
      keyword: item.keyword || "",
      description: item.description || "",
      owner: item.owner || "",
      comment: item.comment || "",
      is_checked: item.is_checked || false,
    })
  }

  const cancelEditMstGjeneraleRow = () => {
    setMstGjeneraleEditingId(null)
    setMstGjeneraleEditDraft({
      number: "",
      title: "",
      keyword: "",
      description: "",
      owner: "",
      comment: "",
      is_checked: false,
    })
  }

  const saveEditMstGjeneraleRow = async () => {
    if (!mstGjeneraleEditingId) return
    const title = mstGjeneraleEditDraft.title.trim()
    if (!title) return
    const rawNumber = mstGjeneraleEditDraft.number.trim()
    const parsedNumber = Number.parseInt(rawNumber, 10)
    const position =
      rawNumber && !Number.isNaN(parsedNumber) ? Math.max(0, parsedNumber - 1) : undefined
    setMstGjeneraleEditingSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${mstGjeneraleEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          position,
          title,
          keyword: mstGjeneraleEditDraft.keyword.trim() || null,
          description: mstGjeneraleEditDraft.description.trim() || null,
          owner: mstGjeneraleEditDraft.owner.trim() || null,
          comment: mstGjeneraleEditDraft.comment.trim() || null,
          is_checked: mstGjeneraleEditDraft.is_checked,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to update checklist item")
        return
      }
      await reloadChecklistItems()
      cancelEditMstGjeneraleRow()
      toast.success("Checklist item updated")
    } finally {
      setMstGjeneraleEditingSaving(false)
    }
  }

  const deleteMstGjeneraleRow = async (itemId: string) => {
    if (!(await confirm({ title: "Delete checklist item", description: "Delete this checklist item?", confirmLabel: "Delete", variant: "destructive" }))) return
    const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
    if (!res.ok) {
      toast.error("Failed to delete checklist item")
      return
    }
    await reloadChecklistItems()
    toast.success("Checklist item deleted")
  }

  // Project Acceptance admin functions
  const addAcceptanceItem = async () => {
    if (!project) return
    const text = acceptanceNewText.trim()
    if (!text) return
    const rawNumber = acceptanceNewNumber.trim()
    const position = rawNumber ? Math.max(0, Number.parseInt(rawNumber, 10) - 1) : undefined
    setAcceptanceSaving(true)
    try {
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          item_type: "CHECKBOX",
          path: "project acceptance",
          title: text,
          position,
          is_checked: false,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to add item")
        return
      }
      setAcceptanceNewText("")
      setAcceptanceNewNumber("")
      await reloadChecklistItems()
      toast.success("Item added")
    } finally {
      setAcceptanceSaving(false)
    }
  }

  const startEditAcceptanceItem = (item: ChecklistItem) => {
    setAcceptanceEditingId(item.id)
    setAcceptanceEditingText(item.title || "")
  }

  const saveEditAcceptanceItem = async () => {
    if (!acceptanceEditingId) return
    const text = acceptanceEditingText.trim()
    if (!text) return
    setAcceptanceSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${acceptanceEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: text }),
      })
      if (!res.ok) {
        toast.error("Failed to update item")
        return
      }
      setAcceptanceEditingId(null)
      setAcceptanceEditingText("")
      await reloadChecklistItems()
      toast.success("Item updated")
    } finally {
      setAcceptanceSaving(false)
    }
  }

  const deleteAcceptanceItem = async (itemId: string) => {
    setAcceptanceSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
      if (!res.ok) {
        toast.error("Failed to delete item")
        return
      }
      await reloadChecklistItems()
      toast.success("Item deleted")
    } finally {
      setAcceptanceSaving(false)
    }
  }

  // GA/DV Meeting admin functions
  const addGaMeetingItem = async () => {
    if (!project) return
    const text = gaMeetingNewText.trim()
    if (!text) return
    const rawNumber = gaMeetingNewNumber.trim()
    const position = rawNumber ? Math.max(0, Number.parseInt(rawNumber, 10) - 1) : undefined
    setGaMeetingSaving(true)
    try {
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          item_type: "CHECKBOX",
          path: "ga/dv meeting",
          title: text,
          position,
          is_checked: false,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to add item")
        return
      }
      setGaMeetingNewText("")
      setGaMeetingNewNumber("")
      await reloadChecklistItems()
      toast.success("Item added")
    } finally {
      setGaMeetingSaving(false)
    }
  }

  const startEditGaMeetingItem = (item: ChecklistItem) => {
    setGaMeetingEditingId(item.id)
    setGaMeetingEditingText(item.title || "")
  }

  const saveEditGaMeetingItem = async () => {
    if (!gaMeetingEditingId) return
    const text = gaMeetingEditingText.trim()
    if (!text) return
    setGaMeetingSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${gaMeetingEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: text }),
      })
      if (!res.ok) {
        toast.error("Failed to update item")
        return
      }
      setGaMeetingEditingId(null)
      setGaMeetingEditingText("")
      await reloadChecklistItems()
      toast.success("Item updated")
    } finally {
      setGaMeetingSaving(false)
    }
  }

  const deleteGaMeetingItem = async (itemId: string) => {
    setGaMeetingSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
      if (!res.ok) {
        toast.error("Failed to delete item")
        return
      }
      await reloadChecklistItems()
      toast.success("Item deleted")
    } finally {
      setGaMeetingSaving(false)
    }
  }

  // PROPOZIM KO1/KO2 admin functions
  const addPropozimItem = async () => {
    if (!project) return
    const text = propozimNewText.trim()
    if (!text) return
    const rawNumber = propozimNewNumber.trim()
    const position = rawNumber ? Math.max(0, Number.parseInt(rawNumber, 10) - 1) : undefined
    setPropozimSaving(true)
    try {
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          item_type: "CHECKBOX",
          path: "propozim ko1/ko2",
          title: text,
          position,
          is_checked: false,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to add item")
        return
      }
      setPropozimNewText("")
      setPropozimNewNumber("")
      await reloadChecklistItems()
      toast.success("Item added")
    } finally {
      setPropozimSaving(false)
    }
  }

  const startEditPropozimItem = (item: ChecklistItem) => {
    setPropozimEditingId(item.id)
    setPropozimEditingText(item.title || "")
  }

  const saveEditPropozimItem = async () => {
    if (!propozimEditingId) return
    const text = propozimEditingText.trim()
    if (!text) return
    setPropozimSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${propozimEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: text }),
      })
      if (!res.ok) {
        toast.error("Failed to update item")
        return
      }
      setPropozimEditingId(null)
      setPropozimEditingText("")
      await reloadChecklistItems()
      toast.success("Item updated")
    } finally {
      setPropozimSaving(false)
    }
  }

  const deletePropozimItem = async (itemId: string) => {
    setPropozimSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
      if (!res.ok) {
        toast.error("Failed to delete item")
        return
      }
      await reloadChecklistItems()
      toast.success("Item deleted")
    } finally {
      setPropozimSaving(false)
    }
  }

  // PUNIMI admin functions
  const addPunimiItem = async () => {
    if (!project) return
    const text = punimiNewText.trim()
    if (!text) return
    const rawNumber = punimiNewNumber.trim()
    const position = rawNumber ? Math.max(0, Number.parseInt(rawNumber, 10) - 1) : undefined
    setPunimiSaving(true)
    try {
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          item_type: "CHECKBOX",
          path: "punimi",
          title: text,
          position,
          is_checked: false,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to add item")
        return
      }
      setPunimiNewText("")
      setPunimiNewNumber("")
      await reloadChecklistItems()
      toast.success("Item added")
    } finally {
      setPunimiSaving(false)
    }
  }

  const startEditPunimiItem = (item: ChecklistItem) => {
    setPunimiEditingId(item.id)
    setPunimiEditingText(item.title || "")
  }

  const saveEditPunimiItem = async () => {
    if (!punimiEditingId) return
    const text = punimiEditingText.trim()
    if (!text) return
    setPunimiSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${punimiEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: text }),
      })
      if (!res.ok) {
        toast.error("Failed to update item")
        return
      }
      setPunimiEditingId(null)
      setPunimiEditingText("")
      await reloadChecklistItems()
      toast.success("Item updated")
    } finally {
      setPunimiSaving(false)
    }
  }

  const deletePunimiItem = async (itemId: string) => {
    setPunimiSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
      if (!res.ok) {
        toast.error("Failed to delete item")
        return
      }
      await reloadChecklistItems()
      toast.success("Item deleted")
    } finally {
      setPunimiSaving(false)
    }
  }

  const addFinalizationItem = async () => {
    if (!project) return
    const text = finalizationNewText.trim()
    if (!text) return
    const rawNumber = finalizationNewNumber.trim()
    const position = rawNumber ? Math.max(0, Number.parseInt(rawNumber, 10) - 1) : undefined
    setFinalizationSaving(true)
    try {
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          item_type: "CHECKBOX",
          path: FINALIZATION_PATH,
          title: text,
          position,
          is_checked: false,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to add item")
        return
      }
      setFinalizationNewText("")
      setFinalizationNewNumber("")
      await reloadChecklistItems()
      toast.success("Item added")
    } finally {
      setFinalizationSaving(false)
    }
  }

  // Member management
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

  // Advance phase
  const advancePhase = async () => {
    if (!project) return
    const currentPhase = project.current_phase || "PLANNING"
    const openTasks = tasks.filter(
      (task) =>
        task.status !== "DONE" &&
        (task.phase || currentPhase) === currentPhase
    )
    const phaseChecklistItems = checklistItemsForPhase(currentPhase, checklistItems)
    const uncheckedItems = phaseChecklistItems.filter((item) => !item.is_checked)
    const productTasksForPhase =
      currentPhase === "PRODUCT"
        ? tasks.filter((task) => (task.phase ?? "PRODUCT") === "PRODUCT")
        : []
    const productTotalsMissing =
      currentPhase === "PRODUCT"
        ? productTasksForPhase.filter((task) => {
            const totals = parseProductTotals(task.internal_notes)
            const total = parseInt(totals.total || "0", 10) || 0
            const completed = parseInt(totals.completed || "0", 10) || 0
            return total <= 0 || completed < total
          })
        : []
    
    if (openTasks.length || uncheckedItems.length || productTotalsMissing.length) {
      const blockers: string[] = []
      if (openTasks.length) blockers.push(`${openTasks.length} open tasks`)
      if (uncheckedItems.length) blockers.push(`${uncheckedItems.length} checklist items`)
      if (productTotalsMissing.length)
        blockers.push(`${productTotalsMissing.length} tasks missing total/completed`)
      toast.error(`There are ${blockers.join(" and ")} remaining.`)
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
      setProject(updated)
      setViewedPhase(updated.current_phase || "PLANNING")
      toast.success("Phase advanced")
    } finally {
      setAdvancingPhase(false)
    }
  }

  // GA Notes
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

  const startEditControlChecklistItem = (item: ChecklistItem) => {
    setControlChecklistEditingId(item.id)
    setControlChecklistEditingText(item.title || "")
  }

  const cancelEditControlChecklistItem = () => {
    setControlChecklistEditingId(null)
    setControlChecklistEditingText("")
  }

  const saveControlChecklistItem = async () => {
    if (!controlChecklistEditingId) return
    const text = controlChecklistEditingText.trim()
    if (!text) return
    setControlChecklistSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${controlChecklistEditingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: text }),
      })
      if (!res.ok) {
        toast.error("Failed to update item")
        return
      }
      setControlChecklistEditingId(null)
      setControlChecklistEditingText("")
      await reloadChecklistItems()
      toast.success("Item updated")
    } finally {
      setControlChecklistSaving(false)
    }
  }

  const deleteControlChecklistItem = async (itemId: string) => {
    setControlChecklistSaving(true)
    try {
      const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
      if (!res.ok) {
        toast.error("Failed to delete item")
        return
      }
      await reloadChecklistItems()
      toast.success("Item deleted")
    } finally {
      setControlChecklistSaving(false)
    }
  }

  const updateTaskStatus = async (taskId: string, status: Task["status"]) => {
    const task = tasks.find((t) => t.id === taskId)
    
    // Only admins can change tasks from DONE to any other status
    if (task?.status === "DONE" && status !== "DONE" && user?.role !== "ADMIN") {
      toast.error("Only admins can change tasks from DONE to another status")
      return
    }
    if (isWaitingConfirmation(status) && !task?.confirmation_assignee_id) {
      setPendingStatusTaskId(taskId)
      setPendingStatusValue(status)
      setPendingConfirmationAssigneeId("")
      return
    }
    
    setTaskStatusSaving((prev) => ({ ...prev, [taskId]: true }))
    try {
      const payload: Record<string, unknown> = { status }
      if (isWaitingConfirmation(status) && task?.confirmation_assignee_id) {
        payload.confirmation_assignee_id = task.confirmation_assignee_id
      }
      const res = await apiFetch(`/tasks/${taskId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) {
        toast.error("Failed to update task status")
        return
      }
      const updated = (await res.json()) as Task
      setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))
      toast.success("Task updated")
    } finally {
      setTaskStatusSaving((prev) => ({ ...prev, [taskId]: false }))
    }
  }

  const submitPendingStatusUpdate = async () => {
    if (!pendingStatusTaskId) return
    const validation = validateWaitingConfirmation(pendingStatusValue, pendingConfirmationAssigneeId)
    if (validation) {
      toast.error(validation)
      return
    }
    setTaskStatusSaving((prev) => ({ ...prev, [pendingStatusTaskId]: true }))
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
      setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))
      toast.success("Task updated")
      setPendingStatusTaskId(null)
      setPendingStatusValue("TODO")
      setPendingConfirmationAssigneeId("")
    } finally {
      setTaskStatusSaving((prev) => ({ ...prev, [pendingStatusTaskId]: false }))
    }
  }

  // Determine active phase and visible tabs
  const phaseValue = viewedPhase || project?.current_phase || "PLANNING"
  const visibleTabs = React.useMemo(() => {
    switch (phaseValue) {
      case "PLANNING":
        return PLANNING_TABS
      case "PRODUCT":
        return PRODUCT_TABS
      case "CONTROL":
        return CONTROL_TABS
      case "FINAL":
        return FINAL_TABS
      default:
        return PLANNING_TABS
    }
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
        const taskPhase = task.phase || project?.current_phase || "PLANNING"
        return taskPhase === activePhase
      }),
    [activePhase, project?.current_phase, tasks]
  )
  const taskList = React.useMemo(() => {
    if (activePhase !== "PRODUCT") return visibleTasks
    return visibleTasks.filter((task) => !hasProductTotals(task.internal_notes))
  }, [activePhase, visibleTasks])
  const productTasks = React.useMemo(
    () =>
      tasks.filter(
        (task) =>
          (task.phase ?? "PRODUCT") === "PRODUCT" &&
          hasProductTotals(task.internal_notes) &&
          !isKoTask(task.internal_notes)
      ),
    [tasks]
  )
  const koTasks = React.useMemo(
    () =>
      tasks.filter(
        (task) =>
          (task.phase ?? "PRODUCT") === "PRODUCT" &&
          hasProductTotals(task.internal_notes) &&
          isKoTask(task.internal_notes)
      ),
    [tasks]
  )

  React.useEffect(() => {
    const next: Record<string, { total: string; completed: string; assigned_to: string | null; status: Task["status"] }> =
      {}
    for (const t of tasks) {
      const totals = parseProductTotals(t.internal_notes)
      next[t.id] = {
        total: totals.total,
        completed: totals.completed,
        assigned_to: t.assigned_to || null,
        status: t.status,
      }
    }
    setProductTaskEdits(next)
  }, [tasks])

  const startEditTaskRow = (task: Task) => {
    setEditingTaskIds((prev) => ({ ...prev, [task.id]: true }))
    setEditingTaskTitles((prev) => ({ ...prev, [task.id]: task.title }))
    setEditingTaskAssignees((prev) => ({
      ...prev,
      [task.id]: task.assigned_to || "__unassigned__",
    }))
    setEditingTaskTotals((prev) => ({
      ...prev,
      [task.id]: productTaskEdits[task.id]?.total || "",
    }))
  }

  const resetToPlanning = async () => {
    if (!project) return
    setResettingPhase(true)
    try {
      const res = await apiFetch(`/projects/${project.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_phase: "PLANNING" }),
      })
      if (!res.ok) {
        let detail = "Failed to reset phase"
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
      setViewedPhase(updated.current_phase || "PLANNING")
      toast.success("Phase reset to Planning")
    } finally {
      setResettingPhase(false)
    }
  }

  const cancelEditTaskRow = (taskId: string) => {
    setEditingTaskIds((prev) => ({ ...prev, [taskId]: false }))
  }

  const saveTaskRowEdits = async (task: Task, isKo: boolean) => {
    if (!project) return
    const title = (editingTaskTitles[task.id] || "").trim()
    if (!title) return
    const assignedTo =
      editingTaskAssignees[task.id] === "__unassigned__"
        ? null
        : editingTaskAssignees[task.id] || null
    const totalValue = editingTaskTotals[task.id] || "0"
    const completedValue = productTaskEdits[task.id]?.completed || "0"
    const payload = {
      title,
      assigned_to: assignedTo,
      internal_notes: `${isKo ? "ko_tab=KO1KO2; " : ""}total_products=${totalValue || 0}; completed_products=${completedValue || 0}`,
    }
    const res = await apiFetch(`/tasks/${task.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      toast.error("Failed to update task")
      return
    }
    const updated = (await res.json()) as Task
    setTasks((prev) => prev.map((t) => (t.id === task.id ? updated : t)))
    setEditingTaskIds((prev) => ({ ...prev, [task.id]: false }))
    toast.success("Task updated")
  }

  // Filter acceptance checklist items (PRANIMI I PROJEKTIT)
  const acceptanceItems = React.useMemo(
    () => checklistItems.filter((item) => item.path === "project acceptance"),
    [checklistItems]
  )

  // Filter GA Meeting checklist items (TAKIM ME GA/DV)
  const gaMeetingItems = React.useMemo(
    () => checklistItems.filter((item) => item.path === "ga/dv meeting"),
    [checklistItems]
  )

  // Filter PROPOZIM KO1/KO2 checklist items
  const propozimItems = React.useMemo(
    () => checklistItems.filter((item) => item.path === "propozim ko1/ko2"),
    [checklistItems]
  )

  // Filter PUNIMI checklist items
  const punimiItems = React.useMemo(
    () => checklistItems.filter((item) => item.path === "punimi"),
    [checklistItems]
  )

  const mstGjeneraleItems = React.useMemo(
    () => orderChecklistItems(checklistItems.filter((item) => item.path === GD_MST_GJENERALE_PATH)),
    [checklistItems]
  )
  const mstSofaNewItems = React.useMemo(
    () => orderChecklistItems(checklistItems.filter((item) => item.path === GD_MST_SOFA_NEW_PATH)),
    [checklistItems]
  )
  const mstVitrineNewItems = React.useMemo(
    () => orderChecklistItems(checklistItems.filter((item) => item.path === GD_MST_VITRINE_NEW_PATH)),
    [checklistItems]
  )
  const mstSideboardNewItems = React.useMemo(
    () =>
      orderChecklistItems(checklistItems.filter((item) => item.path === GD_MST_SIDEBOARD_NEW_PATH)),
    [checklistItems]
  )
  const mstLowboardItems = React.useMemo(
    () => orderChecklistItems(checklistItems.filter((item) => item.path === GD_MST_LOWBOARD_PATH)),
    [checklistItems]
  )

  // Filter general checklist items (not project acceptance, GA meeting, propozim, or punimi)
  const generalChecklistItems = React.useMemo(
    () =>
      checklistItems.filter(
        (item) =>
          item.path !== "project acceptance" &&
          item.path !== "ga/dv meeting" &&
          item.path !== "propozim ko1/ko2" &&
          item.path !== "punimi" &&
          item.path !== FINALIZATION_PATH &&
          item.path !== CONTROL_CHECKLIST_PATH &&
          item.path !== GD_MST_GJENERALE_PATH &&
          item.path !== GD_MST_SOFA_NEW_PATH &&
          item.path !== GD_MST_VITRINE_NEW_PATH &&
          item.path !== GD_MST_SIDEBOARD_NEW_PATH &&
          item.path !== GD_MST_LOWBOARD_PATH &&
          item.path !== LEGACY_GD_MST_PLANNING_PATH
      ),
    [checklistItems]
  )
  const controlChecklistItems = React.useMemo(
    () => checklistItems.filter((item) => item.path === CONTROL_CHECKLIST_PATH),
    [checklistItems]
  )
  const finalizationItems = React.useMemo(
    () => checklistItems.filter((item) => item.path === FINALIZATION_PATH),
    [checklistItems]
  )
  const finalizationItemsOrdered = React.useMemo(
    () => orderChecklistItems(finalizationItems),
    [finalizationItems]
  )
  const checklistItemsForTab = React.useMemo(() => {
    const baseItems = activePhase === "CONTROL" ? controlChecklistItems : generalChecklistItems
    return orderChecklistItems(baseItems)
  }, [activePhase, controlChecklistItems, generalChecklistItems])
  const checklistTitle = activePhase === "CONTROL" ? CONTROL_CHECKLIST_TITLE : "Checklist"
  const isMstProject =
    (project?.project_type || "").toUpperCase() === "MST" ||
    (project?.title || "").toUpperCase().includes("MST")
  const showMstPlanningSections = isMstProject && activePhase === "PLANNING"

  const userMap = new Map([...allUsers, ...members, ...(user ? [user] : [])].map((m) => [m.id, m]))
  const confirmerCandidates = React.useMemo(
    () => getConfirmerCandidates([...allUsers, ...members, ...(user ? [user] : [])]),
    [allUsers, members, user]
  )
  const assignableUsers = React.useMemo(() => allUsers, [allUsers])
  const memberLabel = (id?: string | null) => {
    if (!id) return "-"
    const member = userMap.get(id)
    return member?.full_name || member?.username || member?.email || "-"
  }

  const renderChecklistItemsList = (items: ChecklistItem[]) => {
    if (items.length === 0) {
      return <p className="text-muted-foreground">No checklist items yet. Add items below.</p>
    }

    return (
      <div className="space-y-2">
        {items.map((item, idx) => (
          <div key={item.id} className="p-3 border rounded-lg space-y-2">
            <div className="flex items-center gap-3">
              <span className="text-purple-600 font-medium min-w-[24px] mt-0.5">{idx + 1}.</span>
              <Checkbox
                checked={item.is_checked || false}
                onCheckedChange={(checked) => void toggleChecklistItem(item.id, !!checked)}
              />
              <div className="flex-1">
                {activePhase === "CONTROL" && isAdmin ? (
                  controlChecklistEditingId === item.id ? (
                    <Input
                      value={controlChecklistEditingText}
                      onChange={(e) => setControlChecklistEditingText(e.target.value)}
                    />
                  ) : (
                    <span className={item.is_checked ? "line-through text-muted-foreground" : ""}>
                      {item.title || ""}
                    </span>
                  )
                ) : (
                  <span className={item.is_checked ? "line-through text-muted-foreground" : ""}>
                    {item.title || ""}
                  </span>
                )}
              </div>
              {activePhase === "CONTROL" && isAdmin ? (
                <div className="ml-auto flex items-center gap-2">
                  {controlChecklistEditingId === item.id ? (
                    <>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={controlChecklistSaving || !controlChecklistEditingText.trim()}
                        onClick={() => void saveControlChecklistItem()}
                      >
                        {controlChecklistSaving ? "Saving..." : "Save"}
                      </Button>
                      <Button variant="ghost" size="sm" onClick={cancelEditControlChecklistItem}>
                        Cancel
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button variant="ghost" size="sm" onClick={() => startEditControlChecklistItem(item)}>
                        Edit
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="text-red-500 hover:text-red-600"
                        disabled={controlChecklistSaving}
                        onClick={() => void deleteControlChecklistItem(item.id)}
                      >
                        Delete
                      </Button>
                    </>
                  )}
                </div>
              ) : null}
            </div>
            <div className="ml-9 space-y-2">
              {commentEditingId === item.id ? (
                <div className="space-y-2">
                  <Textarea
                    value={commentEditingText}
                    onChange={(e) => setCommentEditingText(e.target.value)}
                    placeholder="Add a comment..."
                    rows={2}
                  />
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={commentSaving}
                      onClick={() => void saveComment(item.id)}
                    >
                      {commentSaving ? "Saving..." : "Save Comment"}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={cancelEditComment}>
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-2">
                  {item.comment ? (
                    <div className="flex-1 text-sm text-muted-foreground bg-muted p-2 rounded">
                      {item.comment}
                    </div>
                  ) : (
                    <div className="flex-1 text-sm text-muted-foreground italic">No comment</div>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => startEditComment(item)}>
                    {item.comment ? "Edit" : "Add"} Comment
                  </Button>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    )
  }

  const renderMstGjeneraleTable = () => (
    <div className="space-y-4">
      <div className="relative overflow-x-auto rounded-lg border">
        <table className="w-full table-fixed border-collapse text-sm">
          <colgroup>
            <col className="w-[5%]" />
            <col className="w-[16%]" />
            <col className="w-[20%]" />
            <col className="w-[32%]" />
            <col className="w-[7%]" />
            <col className="w-[8%]" />
            <col className="w-[10%]" />
            <col className="w-[12%]" />
          </colgroup>
          <thead className="sticky top-[var(--design-sticky-offset)] z-30 bg-white/95 backdrop-blur text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">NR</th>
              <th className="px-3 py-2 text-left">KEYWORDS</th>
              <th className="px-3 py-2 text-left">DETYRAT</th>
              <th className="px-3 py-2 text-left">PERSHKRIMI</th>
              <th className="px-3 py-2 text-left">CHECK</th>
              <th className="px-3 py-2 text-left">INCL</th>
              <th className="px-3 py-2 text-left">COMMENT</th>
              <th className="px-3 py-2 text-left">ACTIONS</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {mstGjeneraleItems.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-3 py-4 text-sm text-muted-foreground">
                  No checklist items yet. Add items below.
                </td>
              </tr>
            ) : (
              mstGjeneraleItems.map((item, idx) => (
                <tr key={item.id}>
                  {mstGjeneraleEditingId === item.id ? (
                    <>
                      <td className="px-3 py-2 align-top">
                        <Input
                          value={mstGjeneraleEditDraft.number}
                          onChange={(e) =>
                            setMstGjeneraleEditDraft((prev) => ({ ...prev, number: e.target.value }))
                          }
                        />
                      </td>
                      <td className="px-3 py-2 align-top">
                        <Input
                          value={mstGjeneraleEditDraft.keyword}
                          onChange={(e) =>
                            setMstGjeneraleEditDraft((prev) => ({ ...prev, keyword: e.target.value }))
                          }
                        />
                      </td>
                      <td className="px-3 py-2 align-top">
                        <Input
                          value={mstGjeneraleEditDraft.title}
                          onChange={(e) =>
                            setMstGjeneraleEditDraft((prev) => ({ ...prev, title: e.target.value }))
                          }
                        />
                      </td>
                      <td className="px-3 py-2 align-top">
                        <Textarea
                          value={mstGjeneraleEditDraft.description}
                          onChange={(e) =>
                            setMstGjeneraleEditDraft((prev) => ({ ...prev, description: e.target.value }))
                          }
                          rows={2}
                        />
                      </td>
                      <td className="px-3 py-2 align-top">
                        <Checkbox
                          checked={mstGjeneraleEditDraft.is_checked}
                          onCheckedChange={(checked) =>
                            setMstGjeneraleEditDraft((prev) => ({ ...prev, is_checked: !!checked }))
                          }
                        />
                      </td>
                      <td className="px-3 py-2 align-top">
                        <Input
                          value={mstGjeneraleEditDraft.owner}
                          onChange={(e) =>
                            setMstGjeneraleEditDraft((prev) => ({ ...prev, owner: e.target.value }))
                          }
                        />
                      </td>
                      <td className="px-3 py-2 align-top">
                        <Textarea
                          value={mstGjeneraleEditDraft.comment}
                          onChange={(e) =>
                            setMstGjeneraleEditDraft((prev) => ({ ...prev, comment: e.target.value }))
                          }
                          rows={2}
                        />
                      </td>
                      <td className="px-3 py-2 align-top">
                        <div className="flex items-center gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={mstGjeneraleEditingSaving || !mstGjeneraleEditDraft.title.trim()}
                            onClick={() => void saveEditMstGjeneraleRow()}
                          >
                            {mstGjeneraleEditingSaving ? "Saving..." : "Save"}
                          </Button>
                          <Button variant="ghost" size="sm" onClick={cancelEditMstGjeneraleRow}>
                            Cancel
                          </Button>
                        </div>
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="px-3 py-2 align-top text-muted-foreground">{idx + 1}</td>
                      <td className="px-3 py-2 align-top font-semibold">{item.keyword || "-"}</td>
                      <td className="px-3 py-2 align-top">{item.title || "-"}</td>
                      <td className="px-3 py-2 align-top text-muted-foreground whitespace-pre-line">
                        {item.description || "-"}
                      </td>
                      <td className="px-3 py-2 align-top">
                        <Checkbox
                          checked={item.is_checked || false}
                          onCheckedChange={(checked) => void toggleChecklistItem(item.id, !!checked)}
                          disabled={!canEditGjenerale}
                        />
                      </td>
                      <td className="px-3 py-2 align-top">{item.owner || "-"}</td>
                      <td className="px-3 py-2 align-top text-sm text-muted-foreground whitespace-pre-line">
                        {item.comment || "—"}
                      </td>
                      <td className="px-3 py-2 align-top">
                        {canEditGjenerale ? (
                          <div className="flex items-center gap-2">
                            <Button variant="ghost" size="sm" onClick={() => startEditMstGjeneraleRow(item)}>
                              Edit
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-red-500 hover:text-red-600"
                              onClick={() => void deleteMstGjeneraleRow(item.id)}
                            >
                              Delete
                            </Button>
                          </div>
                        ) : null}
                      </td>
                    </>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="grid gap-2 md:grid-cols-[120px_1fr_1fr_1fr_140px_160px_auto]">
        <div className="space-y-1">
          <Label>Number</Label>
          <Input
            value={mstGjeneraleNumber}
            onChange={(e) => setMstGjeneraleNumber(e.target.value)}
            placeholder="e.g. 3"
          />
        </div>
        <div className="space-y-1">
          <Label>Detyrat</Label>
          <Input
            value={mstGjeneraleContent}
            onChange={(e) => setMstGjeneraleContent(e.target.value)}
            placeholder="Detyra"
          />
        </div>
        <div className="space-y-1">
          <Label>Keywords</Label>
          <Input
            value={mstGjeneraleKeyword}
            onChange={(e) => setMstGjeneraleKeyword(e.target.value)}
            placeholder="Keywords"
          />
        </div>
        <div className="space-y-1">
          <Label>Pershkrimi</Label>
          <Input
            value={mstGjeneraleDescription}
            onChange={(e) => setMstGjeneraleDescription(e.target.value)}
            placeholder="Pershkrimi"
          />
        </div>
        <div className="space-y-1">
          <Label>Incl</Label>
          <Input
            value={mstGjeneraleOwner}
            onChange={(e) => setMstGjeneraleOwner(e.target.value)}
            placeholder="Incl"
          />
        </div>
        <div className="space-y-1">
          <Label>Comment</Label>
          <Input
            value={mstGjeneraleComment}
            onChange={(e) => setMstGjeneraleComment(e.target.value)}
            placeholder="Comment"
          />
        </div>
        <div className="flex items-end">
          <Button onClick={() => void submitMstGjeneraleRow()} disabled={mstGjeneraleAdding || !mstGjeneraleContent.trim()}>
            {mstGjeneraleAdding ? "Adding..." : "Add"}
          </Button>
        </div>
      </div>
    </div>
  )

  const renderMstSofaNewTable = () => (
    <div className="space-y-4">
      <div className="relative overflow-x-auto rounded-lg border">
        <table className="w-full table-fixed border-collapse text-sm">
          <colgroup>
            <col className="w-[5%]" />
            <col className="w-[18%]" />
            <col className="w-[18%]" />
            <col className="w-[25%]" />
            <col className="w-[18%]" />
            <col className="w-[6%]" />
            <col className="w-[10%]" />
          </colgroup>
          <thead className="sticky top-[var(--design-sticky-offset)] z-30 bg-white/95 backdrop-blur text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">NR</th>
              <th className="px-3 py-2 text-left">PATH</th>
              <th className="px-3 py-2 text-left">KEYWORDS</th>
              <th className="px-3 py-2 text-left">PERSHKRIMI</th>
              <th className="px-3 py-2 text-left">SHEMBULL</th>
              <th className="px-3 py-2 text-left">CHECK</th>
              <th className="px-3 py-2 text-left">ACTIONS</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {mstSofaNewItems.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-4 text-sm text-muted-foreground">
                  No checklist items yet. Add items below.
                </td>
              </tr>
            ) : (
              mstSofaNewItems.map((item, idx) => {
                const rowNumber = (item.position ?? idx) + 1
                const urls =
                  SOFA_NEW_SHEMBULL[sofaKey(item.title, item.keyword)] ||
                  SOFA_NEW_ROW_IMAGES[rowNumber] ||
                  []
                return (
                  <tr key={item.id}>
                    {mstSofaNewEditingId === item.id ? (
                      <>
                        <td className="px-3 py-2 align-top">
                          <Input
                            value={mstSofaNewEditDraft.number}
                            onChange={(e) =>
                              setMstSofaNewEditDraft((prev) => ({ ...prev, number: e.target.value }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Input
                            value={mstSofaNewEditDraft.title}
                            onChange={(e) =>
                              setMstSofaNewEditDraft((prev) => ({ ...prev, title: e.target.value }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Input
                            value={mstSofaNewEditDraft.keyword}
                            onChange={(e) =>
                              setMstSofaNewEditDraft((prev) => ({ ...prev, keyword: e.target.value }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Textarea
                            value={mstSofaNewEditDraft.description}
                            onChange={(e) =>
                              setMstSofaNewEditDraft((prev) => ({ ...prev, description: e.target.value }))
                            }
                            rows={2}
                          />
                        </td>
                        <td className="px-3 py-2 align-top text-muted-foreground text-xs">
                          Photos are mapped in UI.
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Checkbox
                            checked={mstSofaNewEditDraft.is_checked}
                            onCheckedChange={(checked) =>
                              setMstSofaNewEditDraft((prev) => ({ ...prev, is_checked: !!checked }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <div className="flex items-center gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={mstSofaNewEditingSaving || !mstSofaNewEditDraft.title.trim()}
                              onClick={() => void saveEditMstSofaNewRow()}
                            >
                              {mstSofaNewEditingSaving ? "Saving..." : "Save"}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={cancelEditMstSofaNewRow}>
                              Cancel
                            </Button>
                          </div>
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="px-3 py-2 align-top text-muted-foreground">{idx + 1}</td>
                        <td className="px-3 py-2 align-top font-semibold">{item.title || "-"}</td>
                        <td className="px-3 py-2 align-top">{item.keyword || "-"}</td>
                        <td className="px-3 py-2 align-top text-muted-foreground whitespace-pre-line">
                          {item.description || "-"}
                        </td>
                        <td className="px-3 py-2 align-top">
                          <ShembullSlider urls={urls} />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Checkbox
                            checked={item.is_checked || false}
                            onCheckedChange={(checked) => void toggleChecklistItem(item.id, !!checked)}
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <div className="flex items-center gap-2">
                            <Button variant="ghost" size="sm" onClick={() => startEditMstSofaNewRow(item)}>
                              Edit
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-red-500 hover:text-red-600"
                              onClick={() => void deleteMstSofaNewRow(item.id)}
                            >
                              Delete
                            </Button>
                          </div>
                        </td>
                      </>
                    )}
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="grid gap-2 md:grid-cols-[120px_1fr_1fr_1fr_auto]">
        <div className="space-y-1">
          <Label>Number</Label>
          <Input
            value={mstSofaNewNumber}
            onChange={(e) => setMstSofaNewNumber(e.target.value)}
            placeholder="e.g. 3"
          />
        </div>
        <div className="space-y-1">
          <Label>Path</Label>
          <Input
            value={mstSofaNewContent}
            onChange={(e) => setMstSofaNewContent(e.target.value)}
            placeholder="PATH"
          />
        </div>
        <div className="space-y-1">
          <Label>Keywords</Label>
          <Input
            value={mstSofaNewKeyword}
            onChange={(e) => setMstSofaNewKeyword(e.target.value)}
            placeholder="Keywords"
          />
        </div>
        <div className="space-y-1">
          <Label>Pershkrimi</Label>
          <Input
            value={mstSofaNewDescription}
            onChange={(e) => setMstSofaNewDescription(e.target.value)}
            placeholder="Pershkrimi"
          />
        </div>
        <div className="flex items-end">
          <Button
            onClick={() => void submitMstSofaNewRow()}
            disabled={mstSofaNewAdding || !mstSofaNewContent.trim()}
          >
            {mstSofaNewAdding ? "Adding..." : "Add"}
          </Button>
        </div>
      </div>
    </div>
  )

  const renderMstVitrineNewTable = () => (
    <div className="space-y-4">
      <div className="relative overflow-x-auto rounded-lg border">
        <table className="w-full table-fixed border-collapse text-sm">
          <colgroup>
            <col className="w-[5%]" />
            <col className="w-[18%]" />
            <col className="w-[18%]" />
            <col className="w-[25%]" />
            <col className="w-[18%]" />
            <col className="w-[6%]" />
            <col className="w-[10%]" />
          </colgroup>
          <thead className="sticky top-[var(--design-sticky-offset)] z-30 bg-white/95 backdrop-blur text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">NR</th>
              <th className="px-3 py-2 text-left">PATH</th>
              <th className="px-3 py-2 text-left">KEYWORDS</th>
              <th className="px-3 py-2 text-left">PERSHKRIMI</th>
              <th className="px-3 py-2 text-left">SHEMBULL</th>
              <th className="px-3 py-2 text-left">CHECK</th>
              <th className="px-3 py-2 text-left">ACTIONS</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {mstVitrineNewItems.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-4 text-sm text-muted-foreground">
                  No checklist items yet. Add items below.
                </td>
              </tr>
            ) : (
              mstVitrineNewItems.map((item, idx) => {
                const rowNumber = (item.position ?? idx) + 1
                const urls =
                  VITRINE_NEW_SHEMBULL[sofaKey(item.title, item.keyword)] ||
                  VITRINE_NEW_ROW_IMAGES[rowNumber] ||
                  []
                const textShembull = VITRINE_NEW_ROW_SHEMBULL_TEXT[rowNumber]
                return (
                  <tr key={item.id}>
                    {mstVitrineNewEditingId === item.id ? (
                      <>
                        <td className="px-3 py-2 align-top">
                          <Input
                            value={mstVitrineNewEditDraft.number}
                            onChange={(e) =>
                              setMstVitrineNewEditDraft((prev) => ({ ...prev, number: e.target.value }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Input
                            value={mstVitrineNewEditDraft.title}
                            onChange={(e) =>
                              setMstVitrineNewEditDraft((prev) => ({ ...prev, title: e.target.value }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Input
                            value={mstVitrineNewEditDraft.keyword}
                            onChange={(e) =>
                              setMstVitrineNewEditDraft((prev) => ({ ...prev, keyword: e.target.value }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Textarea
                            value={mstVitrineNewEditDraft.description}
                            onChange={(e) =>
                              setMstVitrineNewEditDraft((prev) => ({ ...prev, description: e.target.value }))
                            }
                            rows={2}
                          />
                        </td>
                        <td className="px-3 py-2 align-top text-muted-foreground text-xs">
                          Photos are mapped in UI.
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Checkbox
                            checked={mstVitrineNewEditDraft.is_checked}
                            onCheckedChange={(checked) =>
                              setMstVitrineNewEditDraft((prev) => ({ ...prev, is_checked: !!checked }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <div className="flex items-center gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={mstVitrineNewEditingSaving || !mstVitrineNewEditDraft.title.trim()}
                              onClick={() => void saveEditMstVitrineNewRow()}
                            >
                              {mstVitrineNewEditingSaving ? "Saving..." : "Save"}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={cancelEditMstVitrineNewRow}>
                              Cancel
                            </Button>
                          </div>
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="px-3 py-2 align-top text-muted-foreground">{idx + 1}</td>
                        <td className="px-3 py-2 align-top font-semibold">{item.title || "-"}</td>
                        <td className="px-3 py-2 align-top">{item.keyword || "-"}</td>
                        <td className="px-3 py-2 align-top text-muted-foreground whitespace-pre-line">
                          {item.description || "-"}
                        </td>
                        <td className="px-3 py-2 align-top">
                          {urls.length ? (
                            <ShembullSlider urls={urls} />
                          ) : textShembull ? (
                            <div className="text-xs text-muted-foreground whitespace-pre-line">
                              {textShembull}
                            </div>
                          ) : (
                            <ShembullSlider urls={urls} />
                          )}
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Checkbox
                            checked={item.is_checked || false}
                            onCheckedChange={(checked) => void toggleChecklistItem(item.id, !!checked)}
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <div className="flex items-center gap-2">
                            <Button variant="ghost" size="sm" onClick={() => startEditMstVitrineNewRow(item)}>
                              Edit
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-red-500 hover:text-red-600"
                              onClick={() => void deleteMstVitrineNewRow(item.id)}
                            >
                              Delete
                            </Button>
                          </div>
                        </td>
                      </>
                    )}
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="grid gap-2 md:grid-cols-[120px_1fr_1fr_1fr_auto]">
        <div className="space-y-1">
          <Label>Number</Label>
          <Input
            value={mstVitrineNewNumber}
            onChange={(e) => setMstVitrineNewNumber(e.target.value)}
            placeholder="e.g. 3"
          />
        </div>
        <div className="space-y-1">
          <Label>Path</Label>
          <Input
            value={mstVitrineNewContent}
            onChange={(e) => setMstVitrineNewContent(e.target.value)}
            placeholder="PATH"
          />
        </div>
        <div className="space-y-1">
          <Label>Keywords</Label>
          <Input
            value={mstVitrineNewKeyword}
            onChange={(e) => setMstVitrineNewKeyword(e.target.value)}
            placeholder="Keywords"
          />
        </div>
        <div className="space-y-1">
          <Label>Pershkrimi</Label>
          <Input
            value={mstVitrineNewDescription}
            onChange={(e) => setMstVitrineNewDescription(e.target.value)}
            placeholder="Pershkrimi"
          />
        </div>
        <div className="flex items-end">
          <Button
            onClick={() => void submitMstVitrineNewRow()}
            disabled={mstVitrineNewAdding || !mstVitrineNewContent.trim()}
          >
            {mstVitrineNewAdding ? "Adding..." : "Add"}
          </Button>
        </div>
      </div>
    </div>
  )

  const renderMstSideboardNewTable = () => (
    <div className="space-y-4">
      <div className="relative overflow-x-auto rounded-lg border">
        <table className="w-full table-fixed border-collapse text-sm">
          <colgroup>
            <col className="w-[5%]" />
            <col className="w-[18%]" />
            <col className="w-[18%]" />
            <col className="w-[25%]" />
            <col className="w-[18%]" />
            <col className="w-[6%]" />
            <col className="w-[10%]" />
          </colgroup>
          <thead className="sticky top-[var(--design-sticky-offset)] z-30 bg-white/95 backdrop-blur text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">NR</th>
              <th className="px-3 py-2 text-left">PATH</th>
              <th className="px-3 py-2 text-left">KEYWORDS</th>
              <th className="px-3 py-2 text-left">PERSHKRIMI</th>
              <th className="px-3 py-2 text-left">SHEMBULL</th>
              <th className="px-3 py-2 text-left">CHECK</th>
              <th className="px-3 py-2 text-left">ACTIONS</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {mstSideboardNewItems.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-4 text-sm text-muted-foreground">
                  No checklist items yet. Add items below.
                </td>
              </tr>
            ) : (
              mstSideboardNewItems.map((item, idx) => {
                const rowNumber = (item.position ?? idx) + 1
                const urls =
                  SIDEBOARD_NEW_SHEMBULL[sofaKey(item.title, item.keyword)] ||
                  SIDEBOARD_NEW_ROW_IMAGES[rowNumber] ||
                  []
                return (
                  <tr key={item.id}>
                    {mstSideboardNewEditingId === item.id ? (
                      <>
                        <td className="px-3 py-2 align-top">
                          <Input
                            value={mstSideboardNewEditDraft.number}
                            onChange={(e) =>
                              setMstSideboardNewEditDraft((prev) => ({ ...prev, number: e.target.value }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Input
                            value={mstSideboardNewEditDraft.title}
                            onChange={(e) =>
                              setMstSideboardNewEditDraft((prev) => ({ ...prev, title: e.target.value }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Input
                            value={mstSideboardNewEditDraft.keyword}
                            onChange={(e) =>
                              setMstSideboardNewEditDraft((prev) => ({ ...prev, keyword: e.target.value }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Textarea
                            value={mstSideboardNewEditDraft.description}
                            onChange={(e) =>
                              setMstSideboardNewEditDraft((prev) => ({ ...prev, description: e.target.value }))
                            }
                            rows={2}
                          />
                        </td>
                        <td className="px-3 py-2 align-top text-muted-foreground text-xs">
                          Photos are mapped in UI.
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Checkbox
                            checked={mstSideboardNewEditDraft.is_checked}
                            onCheckedChange={(checked) =>
                              setMstSideboardNewEditDraft((prev) => ({ ...prev, is_checked: !!checked }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <div className="flex items-center gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={mstSideboardNewEditingSaving || !mstSideboardNewEditDraft.title.trim()}
                              onClick={() => void saveEditMstSideboardNewRow()}
                            >
                              {mstSideboardNewEditingSaving ? "Saving..." : "Save"}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={cancelEditMstSideboardNewRow}>
                              Cancel
                            </Button>
                          </div>
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="px-3 py-2 align-top text-muted-foreground">{idx + 1}</td>
                        <td className="px-3 py-2 align-top font-semibold">{item.title || "-"}</td>
                        <td className="px-3 py-2 align-top">{item.keyword || "-"}</td>
                        <td className="px-3 py-2 align-top text-muted-foreground whitespace-pre-line">
                          {item.description || "-"}
                        </td>
                        <td className="px-3 py-2 align-top">
                          <ShembullSlider urls={urls} />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Checkbox
                            checked={item.is_checked || false}
                            onCheckedChange={(checked) => void toggleChecklistItem(item.id, !!checked)}
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <div className="flex items-center gap-2">
                            <Button variant="ghost" size="sm" onClick={() => startEditMstSideboardNewRow(item)}>
                              Edit
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-red-500 hover:text-red-600"
                              onClick={() => void deleteMstSideboardNewRow(item.id)}
                            >
                              Delete
                            </Button>
                          </div>
                        </td>
                      </>
                    )}
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="grid gap-2 md:grid-cols-[120px_1fr_1fr_1fr_auto]">
        <div className="space-y-1">
          <Label>Number</Label>
          <Input
            value={mstSideboardNewNumber}
            onChange={(e) => setMstSideboardNewNumber(e.target.value)}
            placeholder="e.g. 3"
          />
        </div>
        <div className="space-y-1">
          <Label>Path</Label>
          <Input
            value={mstSideboardNewContent}
            onChange={(e) => setMstSideboardNewContent(e.target.value)}
            placeholder="PATH"
          />
        </div>
        <div className="space-y-1">
          <Label>Keywords</Label>
          <Input
            value={mstSideboardNewKeyword}
            onChange={(e) => setMstSideboardNewKeyword(e.target.value)}
            placeholder="Keywords"
          />
        </div>
        <div className="space-y-1">
          <Label>Pershkrimi</Label>
          <Input
            value={mstSideboardNewDescription}
            onChange={(e) => setMstSideboardNewDescription(e.target.value)}
            placeholder="Pershkrimi"
          />
        </div>
        <div className="flex items-end">
          <Button
            onClick={() => void submitMstSideboardNewRow()}
            disabled={mstSideboardNewAdding || !mstSideboardNewContent.trim()}
          >
            {mstSideboardNewAdding ? "Adding..." : "Add"}
          </Button>
        </div>
      </div>
    </div>
  )

  const renderMstLowboardTable = () => (
    <div className="space-y-4">
      <div className="relative overflow-x-auto rounded-lg border">
        <table className="w-full table-fixed border-collapse text-sm">
          <colgroup>
            <col className="w-[5%]" />
            <col className="w-[18%]" />
            <col className="w-[18%]" />
            <col className="w-[25%]" />
            <col className="w-[18%]" />
            <col className="w-[6%]" />
            <col className="w-[10%]" />
          </colgroup>
          <thead className="sticky top-[var(--design-sticky-offset)] z-30 bg-white/95 backdrop-blur text-xs uppercase text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">NR</th>
              <th className="px-3 py-2 text-left">PATH</th>
              <th className="px-3 py-2 text-left">KEYWORDS</th>
              <th className="px-3 py-2 text-left">PERSHKRIMI</th>
              <th className="px-3 py-2 text-left">SHEMBULL</th>
              <th className="px-3 py-2 text-left">CHECK</th>
              <th className="px-3 py-2 text-left">ACTIONS</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {mstLowboardItems.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-4 text-sm text-muted-foreground">
                  No checklist items yet. Add items below.
                </td>
              </tr>
            ) : (
              mstLowboardItems.map((item, idx) => {
                const rowNumber = (item.position ?? idx) + 1
                const urls =
                  LOWBOARD_SHEMBULL[sofaKey(item.title, item.keyword)] ||
                  LOWBOARD_ROW_IMAGES[rowNumber] ||
                  []
                return (
                  <tr key={item.id}>
                    {mstLowboardEditingId === item.id ? (
                      <>
                        <td className="px-3 py-2 align-top">
                          <Input
                            value={mstLowboardEditDraft.number}
                            onChange={(e) =>
                              setMstLowboardEditDraft((prev) => ({ ...prev, number: e.target.value }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Input
                            value={mstLowboardEditDraft.title}
                            onChange={(e) =>
                              setMstLowboardEditDraft((prev) => ({ ...prev, title: e.target.value }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Input
                            value={mstLowboardEditDraft.keyword}
                            onChange={(e) =>
                              setMstLowboardEditDraft((prev) => ({ ...prev, keyword: e.target.value }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Textarea
                            value={mstLowboardEditDraft.description}
                            onChange={(e) =>
                              setMstLowboardEditDraft((prev) => ({ ...prev, description: e.target.value }))
                            }
                            rows={2}
                          />
                        </td>
                        <td className="px-3 py-2 align-top text-muted-foreground text-xs">
                          Photos are mapped in UI.
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Checkbox
                            checked={mstLowboardEditDraft.is_checked}
                            onCheckedChange={(checked) =>
                              setMstLowboardEditDraft((prev) => ({ ...prev, is_checked: !!checked }))
                            }
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <div className="flex items-center gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={mstLowboardEditingSaving || !mstLowboardEditDraft.title.trim()}
                              onClick={() => void saveEditMstLowboardRow()}
                            >
                              {mstLowboardEditingSaving ? "Saving..." : "Save"}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={cancelEditMstLowboardRow}>
                              Cancel
                            </Button>
                          </div>
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="px-3 py-2 align-top text-muted-foreground">{idx + 1}</td>
                        <td className="px-3 py-2 align-top font-semibold">{item.title || "-"}</td>
                        <td className="px-3 py-2 align-top">{item.keyword || "-"}</td>
                        <td className="px-3 py-2 align-top text-muted-foreground whitespace-pre-line">
                          {item.description || "-"}
                        </td>
                        <td className="px-3 py-2 align-top">
                          <ShembullSlider urls={urls} />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Checkbox
                            checked={item.is_checked || false}
                            onCheckedChange={(checked) => void toggleChecklistItem(item.id, !!checked)}
                          />
                        </td>
                        <td className="px-3 py-2 align-top">
                          <div className="flex items-center gap-2">
                            <Button variant="ghost" size="sm" onClick={() => startEditMstLowboardRow(item)}>
                              Edit
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-red-500 hover:text-red-600"
                              onClick={() => void deleteMstLowboardRow(item.id)}
                            >
                              Delete
                            </Button>
                          </div>
                        </td>
                      </>
                    )}
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="grid gap-2 md:grid-cols-[120px_1fr_1fr_1fr_auto]">
        <div className="space-y-1">
          <Label>Number</Label>
          <Input
            value={mstLowboardNumber}
            onChange={(e) => setMstLowboardNumber(e.target.value)}
            placeholder="e.g. 3"
          />
        </div>
        <div className="space-y-1">
          <Label>Path</Label>
          <Input
            value={mstLowboardContent}
            onChange={(e) => setMstLowboardContent(e.target.value)}
            placeholder="PATH"
          />
        </div>
        <div className="space-y-1">
          <Label>Keywords</Label>
          <Input
            value={mstLowboardKeyword}
            onChange={(e) => setMstLowboardKeyword(e.target.value)}
            placeholder="Keywords"
          />
        </div>
        <div className="space-y-1">
          <Label>Pershkrimi</Label>
          <Input
            value={mstLowboardDescription}
            onChange={(e) => setMstLowboardDescription(e.target.value)}
            placeholder="Pershkrimi"
          />
        </div>
        <div className="flex items-end">
          <Button
            onClick={() => void submitMstLowboardRow()}
            disabled={mstLowboardAdding || !mstLowboardContent.trim()}
          >
            {mstLowboardAdding ? "Adding..." : "Add"}
          </Button>
        </div>
      </div>
    </div>
  )

  const renderMstChecklistSection = (options: {
    title: string
    items: ChecklistItem[]
    path: string
    number: string
    setNumber: (value: string) => void
    content: string
    setContent: (value: string) => void
  }) => (
    <div className="space-y-4">
      {renderChecklistItemsList(options.items)}
      <div className="grid gap-2 md:grid-cols-[120px_1fr_auto]">
        <div className="space-y-1">
          <Label>Number</Label>
          <Input
            value={options.number}
            onChange={(e) => options.setNumber(e.target.value)}
            placeholder="e.g. 3"
          />
        </div>
        <div className="space-y-1">
          <Label>Item</Label>
          <Input
            value={options.content}
            onChange={(e) => options.setContent(e.target.value)}
            placeholder="Add new checklist item..."
            onKeyDown={(e) => {
              if (e.key === "Enter")
                void submitChecklistItem({
                  path: options.path,
                  content: options.content,
                  number: options.number,
                  onReset: () => {
                    options.setContent("")
                    options.setNumber("")
                  },
                })
            }}
          />
        </div>
        <div className="flex items-end">
          <Button
            onClick={() =>
              void submitChecklistItem({
                path: options.path,
                content: options.content,
                number: options.number,
                onReset: () => {
                  options.setContent("")
                  options.setNumber("")
                },
              })
            }
            disabled={addingChecklist}
          >
            {addingChecklist ? "Adding..." : "Add"}
          </Button>
        </div>
      </div>
    </div>
  )

  if (!project) return <div className="text-sm text-muted-foreground">Loading...</div>

  const baseTitle = project.title || project.name || "Project"
  const title = project.project_type === "MST" && project.total_products != null && project.total_products > 0
    ? `${baseTitle} - ${project.total_products}`
    : baseTitle

  const renderProjectTitle = () => {
    if (!canEditProjectTitle) {
      return <div className="text-3xl font-semibold">{title}</div>
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
            className="h-10 text-3xl font-semibold"
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
        <div className="text-3xl font-semibold">{title}</div>
        <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={startEditProjectTitle}>
          Edit
        </Button>
      </div>
    )
  }
  const phase = project.current_phase || "PLANNING"
  const phaseSequence = MST_PHASES
  const phaseLabels = MST_PHASE_LABELS
  const phaseIndex = phaseSequence.indexOf(phase as (typeof phaseSequence)[number])
  const lockedAfterIndex = phaseIndex === -1 ? 0 : phaseIndex
  const canClosePhase = phase !== "CLOSED"

  return (
    <div className="space-y-6" style={{ ["--design-sticky-offset" as string]: `${stickyOffsetPx}px` }}>
      <div ref={stickyHeaderRef} className="sticky top-0 z-40 bg-white/95 backdrop-blur print:static">
        <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-3">
        <button type="button" onClick={() => router.back()} className="text-sm text-muted-foreground hover:text-foreground">&larr; Back to Projects</button>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-3">
            {renderProjectTitle()}
            <ProjectActivityControl project={project} onChange={setProject} />
            {canEditDueDate && (
              <button
                type="button"
                onClick={(e) => {
                  e.preventDefault()
                  e.stopPropagation()
                  const currentDueDate = project.due_date ? toDateInput(project.due_date) : ""
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
          <div className="flex items-center gap-2">
            {user?.role === "ADMIN" && phase !== "PLANNING" ? (
              <Button
                variant="outline"
                disabled={resettingPhase}
                onClick={() => void resetToPlanning()}
              >
                {resettingPhase ? "Resetting..." : "Reset to Planning"}
              </Button>
            ) : null}
            <Button className="rounded-xl" variant="outline">Settings</Button>
          </div>
        </div>
          <div className="mt-3">
            <Badge variant="outline" className="text-purple-600 border-purple-200 bg-purple-50">
              {phaseLabels[phase] || "Design"}
            </Badge>
            <Badge variant="outline" className="ml-2 text-blue-600 border-blue-200 bg-blue-50">
              Graphic Design
            </Badge>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            {phaseSequence.map((p, idx) => {
              const isViewed = p === activePhase
              const isCurrent = p === phase
              const isLocked = idx > lockedAfterIndex
              return (
                <span key={p} className="flex items-center gap-2">
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
                          ? "text-purple-600 font-medium"
                          : isCurrent
                            ? "text-foreground"
                            : "text-muted-foreground",
                    ].join(" ")}
                    aria-pressed={isViewed}
                    disabled={isLocked}
                  >
                    {phaseLabels[p] || p}
                  </button>
                  {idx < phaseSequence.length - 1 ? " → " : ""}
                </span>
              )
            })}
            <span className="ml-auto">
              <Button
                variant="outline"
                size="sm"
                disabled={!canClosePhase || advancingPhase}
                onClick={() => void advancePhase()}
              >
                {advancingPhase ? "Advancing..." : activePhase === "FINAL" ? "Finalize" : "Next Phase"}
              </Button>
            </span>
          </div>
          {activePhase !== phase ? <div className="mt-2 text-xs text-muted-foreground">Viewing: {phaseLabels[activePhase] || "Design"}</div> : null}
      </div>

      {/* Tabs */}
      <div className="border-b">
        <div className="flex flex-wrap gap-6">
          {visibleTabs.map((tab) => {
            const isActive = tab.id === activeTab
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={[
                  "relative pb-3 text-sm font-medium",
                  tab.id === "ga-notes" ? "ml-auto" : "",
                  isActive ? "text-purple-600" : "text-muted-foreground",
                ].join(" ")}
              >
                {tab.label}
                {isActive ? <span className="absolute inset-x-0 bottom-0 h-0.5 bg-purple-600" /> : null}
              </button>
            )
          })}
        </div>
      </div>

      {/* Checklist Sub-tabs (sticky with main tabs) */}
      {activeTab === "checklist" && showMstPlanningSections ? (
        <div className="border-b">
          <div className="flex flex-wrap gap-6">
            {[
              { id: "gjenerale", label: "GJENERALE" },
              { id: "sofa_new", label: "SOFA NEW" },
              { id: "vitrine_new", label: "VITRINE_NEW" },
              { id: "sideboard_new", label: "SIDEBOARD_NEW" },
              { id: "lowboard", label: "LOWBOARD" },
            ].map((tab) => {
              const isActive = tab.id === mstChecklistTab
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() =>
                    setMstChecklistTab(
                      tab.id as "gjenerale" | "sofa_new" | "vitrine_new" | "sideboard_new" | "lowboard"
                    )
                  }
                  className={[
                    "relative pb-3 text-sm font-medium",
                    isActive ? "text-purple-600" : "text-muted-foreground",
                  ].join(" ")}
                >
                  {tab.label}
                  {isActive ? <span className="absolute inset-x-0 bottom-0 h-0.5 bg-purple-600" /> : null}
                </button>
              )
            })}
          </div>
        </div>
      ) : null}
        </div>
      </div>

      {/* Tab Content */}
      <div className="mt-6">
        {/* Description Tab */}
        {activeTab === "description" && (
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-4">Project Description</h3>
            <Textarea
              value={editingDescription}
              onChange={(e) => setEditingDescription(e.target.value)}
              placeholder="Enter project description..."
              rows={6}
              className="mb-4"
            />
            <Button
              onClick={() => void saveDescription()}
              disabled={savingDescription}
            >
              {savingDescription ? "Saving..." : "Save Description"}
            </Button>
          </Card>
        )}

        {/* Tasks Tab */}
        {activeTab === "tasks" && (
          <Card className="p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">Tasks</h3>
              <Dialog open={createOpen} onOpenChange={setCreateOpen}>
                <DialogTrigger asChild>
                  <Button>+ New Task</Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Create Task</DialogTitle>
                  </DialogHeader>
                  <div className="space-y-4">
                    <div>
                      <Label>Title <span className="text-red-500">*</span></Label>
                      <Input
                        value={newTitle}
                        onChange={(e) => setNewTitle(e.target.value.toUpperCase())}
                        placeholder="Task title"
                      />
                    </div>
                    <div>
                      <Label>Description</Label>
                      <BoldOnlyEditor value={newDescription} onChange={setNewDescription} />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <Label>Status</Label>
                        <Select value={newStatus} onValueChange={(v) => setNewStatus(v as typeof newStatus)}>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {TASK_STATUSES.map((s) => (
                              <SelectItem key={s} value={s}>{statusLabel(s)}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div>
                        <Label>Type</Label>
                        <Select value={newTaskType} onValueChange={(v) => setNewTaskType(v as typeof newTaskType)}>
                          <SelectTrigger>
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {PROJECT_TASK_TYPES.map((p) => (
                              <SelectItem key={p} value={p}>{p}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                    <div>
                      <Label>Assignee <span className="text-red-500">*</span></Label>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="outline" className="w-full justify-between">
                            <span className="truncate text-left flex-1">
                              {newAssignees.length > 0 
                                ? (() => {
                                    const selectedNames = newAssignees
                                      .map(id => {
                                        const user = assignableUsers.find(u => u.id === id)
                                        return user?.full_name || user?.email || id
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
                          {assignableUsers.map((u) => (
                            <DropdownMenuCheckboxItem
                              key={u.id}
                              checked={newAssignees.includes(u.id)}
                              onCheckedChange={(checked) => {
                                if (checked) {
                                  setNewAssignees([...newAssignees, u.id])
                                } else {
                                  setNewAssignees(newAssignees.filter(id => id !== u.id))
                                }
                              }}
                            >
                              {u.full_name || u.email}
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
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <Label>Start Date</Label>
                        <Input
                          type="date"
                          value={newStartDate}
                          onChange={(e) => setNewStartDate(e.target.value)}
                        />
                      </div>
                      <div>
                        <Label>Due Date <span className="text-red-500">*</span></Label>
                        <Input
                          type="date"
                          value={newDueDate}
                          onChange={(e) => setNewDueDate(e.target.value)}
                          required
                        />
                      </div>
                    </div>
                    <label className="flex items-center gap-3 rounded-md border px-3 py-2">
                      <Checkbox
                        checked={newDeadlineImportant}
                        onCheckedChange={(checked) => setNewDeadlineImportant(checked === true)}
                      />
                      <span className="text-sm font-medium">Deadline important</span>
                    </label>
                    <Button 
                      onClick={() => void submitCreateTask()} 
                      disabled={creating || !newTitle.trim() || !newAssignees || newAssignees.length === 0 || !newDueDate || !newDueDate.trim()} 
                      className="w-full"
                    >
                      {creating ? "Creating..." : "Create Task"}
                    </Button>
                  </div>
                </DialogContent>
              </Dialog>
            </div>
            {taskList.length === 0 ? (
              <p className="text-muted-foreground">No tasks for this phase.</p>
            ) : (
              <div className="space-y-3">
                {taskList.map((task) => {
                  // Get all assignees from the assignees array, fallback to assigned_to for backward compatibility
                  const assignees = task.assignees && task.assignees.length > 0
                    ? task.assignees
                    : (() => {
                        const assignedId = task.assigned_to || task.assigned_to_user_id || null
                        if (!assignedId) return []
                        const assignedUser = userMap.get(assignedId)
                        return assignedUser ? [{ id: assignedId, full_name: assignedUser.full_name, username: assignedUser.username, email: assignedUser.email }] : []
                      })()
                  const savingStatus = taskStatusSaving[task.id]
                  const taskPhase = task.phase || project?.current_phase || "PLANNING"
                  const canMarkDone = taskPhase === activePhase
                  return (
                    <div key={task.id} className="flex items-center justify-between p-3 border rounded-lg">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">
                            {task.ga_note_origin_id ? renderMarkedNoteContent(task.title, task.title) : task.title}
                          </span>
                          {task.ga_note_origin_id ? (
                            <Badge variant="outline" className="bg-rose-100 text-rose-700 border-rose-200 text-[11px]">
                              GA
                            </Badge>
                          ) : null}
                        </div>
                        <div className="text-sm text-muted-foreground flex items-center gap-1 flex-wrap">
                          {assignees.length > 0 ? (
                            assignees.map((assignee, idx) => {
                              const displayName = assignee.full_name || assignee.username || assignee.email || "-"
                              const assigneeInitials = initials(displayName)
                              return (
                                <Badge key={assignee.id || idx} variant="secondary" className="bg-blue-100 text-blue-700 border-blue-200 text-xs" title={displayName}>
                                  {assigneeInitials}
                                </Badge>
                              )
                            })
                          ) : (
                            <span>Unassigned</span>
                          )}
                          {task.due_date ? ` • Due: ${formatDateTime(task.due_date)}` : ""}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant={task.priority === "HIGH" ? "destructive" : "secondary"}>
                          {task.priority}
                        </Badge>
                        <Select
                          value={task.status}
                          onValueChange={(value) => void updateTaskStatus(task.id, value as Task["status"])}
                          disabled={savingStatus}
                        >
                          <SelectTrigger className="w-[160px]">
                            <SelectValue placeholder="Status" />
                          </SelectTrigger>
                          <SelectContent>
                            {TASK_STATUSES.map((status) => {
                              // Disable DONE option if can't mark done, or disable all non-DONE options if task is DONE and user is not admin
                              const isDisabled =
                                ((status === "DONE" || status === "WAITING_CONFIRMATION") && !canMarkDone) ||
                                (task.status === "DONE" && status !== "DONE" && user?.role !== "ADMIN")
                              return (
                                <SelectItem key={status} value={status} disabled={isDisabled}>
                                  {statusLabel(status)}
                                </SelectItem>
                              )
                            })}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </Card>
        )}

        {/* Checklist Tab */}
        {activeTab === "checklist" && (
          <Card className="p-6">
            {showMstPlanningSections ? (
              <div className="space-y-4">

                {mstChecklistTab === "gjenerale" && renderMstGjeneraleTable()}
                {mstChecklistTab === "sofa_new" && renderMstSofaNewTable()}
                {mstChecklistTab === "vitrine_new" && renderMstVitrineNewTable()}
                {mstChecklistTab === "sideboard_new" && renderMstSideboardNewTable()}
                {mstChecklistTab === "lowboard" && renderMstLowboardTable()}
              </div>
            ) : (
              <>
                {renderChecklistItemsList(checklistItemsForTab)}
                <div className="mt-4 grid gap-2 md:grid-cols-[120px_1fr_auto]">
                  <div className="space-y-1">
                    <Label>Number</Label>
                    <Input
                      value={newChecklistNumber}
                      onChange={(e) => setNewChecklistNumber(e.target.value)}
                      placeholder="e.g. 3"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label>Item</Label>
                    <Input
                      value={newChecklistContent}
                      onChange={(e) => setNewChecklistContent(e.target.value)}
                      placeholder="Add new checklist item..."
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void submitChecklistItem()
                      }}
                    />
                  </div>
                  <div className="flex items-end">
                    <Button onClick={() => void submitChecklistItem()} disabled={addingChecklist}>
                      {addingChecklist ? "Adding..." : "Add"}
                    </Button>
                  </div>
                </div>
              </>
            )}
          </Card>
        )}

        {/* Project Acceptance Tab (PRANIMI I PROJEKTIT) - connected to database */}
        {activeTab === "project-acceptance" && (
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-4">Pranimi i Projektit</h3>
            <p className="text-sm text-muted-foreground mb-4">
              Plotësoni këto pika për të konfirmuar pranimin e projektit.
            </p>
            {acceptanceItems.length === 0 ? (
              <p className="text-muted-foreground">Duke ngarkuar checklistën...</p>
            ) : (
              <div className="space-y-3">
                {acceptanceItems.map((item, idx) => (
                  <div key={item.id} className="p-3 border rounded-lg space-y-2">
                    <div className="flex items-start gap-3">
                      <span className="text-purple-600 font-medium min-w-[24px] mt-0.5">{idx + 1}.</span>
                      <Checkbox
                        checked={item.is_checked || false}
                        onCheckedChange={(checked) => void toggleChecklistItem(item.id, !!checked)}
                        className="mt-0.5"
                      />
                      <div className="flex-1">
                        {isAdmin && acceptanceEditingId === item.id ? (
                          <div className="flex items-center gap-2">
                            <Input
                              value={acceptanceEditingText}
                              onChange={(e) => setAcceptanceEditingText(e.target.value)}
                            />
                            <Button
                              variant="outline"
                              disabled={!acceptanceEditingText.trim() || acceptanceSaving}
                              onClick={() => void saveEditAcceptanceItem()}
                            >
                              Save
                            </Button>
                            <Button
                              variant="ghost"
                              onClick={() => {
                                setAcceptanceEditingId(null)
                                setAcceptanceEditingText("")
                              }}
                            >
                              Cancel
                            </Button>
                          </div>
                        ) : (
                          <span className={item.is_checked ? "line-through text-muted-foreground" : ""}>
                            {item.title}
                          </span>
                        )}
                      </div>
                      {isAdmin && acceptanceEditingId !== item.id ? (
                        <div className="flex items-center gap-2">
                          <Button variant="ghost" onClick={() => startEditAcceptanceItem(item)}>
                            Edit
                          </Button>
                          <Button
                            variant="ghost"
                            disabled={acceptanceSaving}
                            onClick={() => void deleteAcceptanceItem(item.id)}
                          >
                            Delete
                          </Button>
                        </div>
                      ) : null}
                    </div>
                    {/* Comment section */}
                    <div className="ml-9 space-y-2">
                      {commentEditingId === item.id ? (
                        <div className="space-y-2">
                          <Textarea
                            value={commentEditingText}
                            onChange={(e) => setCommentEditingText(e.target.value)}
                            placeholder="Add a comment..."
                            rows={2}
                          />
                          <div className="flex items-center gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={commentSaving}
                              onClick={() => void saveComment(item.id)}
                            >
                              {commentSaving ? "Saving..." : "Save Comment"}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={cancelEditComment}>
                              Cancel
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-start gap-2">
                          {item.comment ? (
                            <div className="flex-1 text-sm text-muted-foreground bg-muted p-2 rounded">
                              {item.comment}
                            </div>
                          ) : (
                            <div className="flex-1 text-sm text-muted-foreground italic">
                              No comment
                            </div>
                          )}
                          <Button variant="ghost" size="sm" onClick={() => startEditComment(item)}>
                            {item.comment ? "Edit" : "Add"} Comment
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {isAdmin ? (
              <div className="mt-6 grid gap-2 md:grid-cols-[120px_1fr_auto]">
                <div className="space-y-1">
                  <Label>Number</Label>
                  <Input
                    value={acceptanceNewNumber}
                    onChange={(e) => setAcceptanceNewNumber(e.target.value)}
                    placeholder="e.g. 3"
                  />
                </div>
                <div className="space-y-1">
                  <Label>Item</Label>
                  <Input
                    value={acceptanceNewText}
                    onChange={(e) => setAcceptanceNewText(e.target.value)}
                    placeholder="Add new checklist item..."
                  />
                </div>
                <div className="flex items-end">
                  <Button
                    variant="outline"
                    disabled={!acceptanceNewText.trim() || acceptanceSaving}
                    onClick={() => void addAcceptanceItem()}
                  >
                    {acceptanceSaving ? "Saving..." : "Add"}
                  </Button>
                </div>
              </div>
            ) : null}
          </Card>
        )}

        {/* GA Meeting Tab (TAKIM ME GA/DV) */}
        {activeTab === "ga-meeting" && (
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-4">Takim me GA/DV</h3>
            
            {/* GA Meeting Questions */}
            <div className="space-y-3">
              {gaMeetingItems.length === 0 ? (
                <p className="text-muted-foreground">Duke ngarkuar checklistën e takimit...</p>
              ) : (
                gaMeetingItems.map((item, idx) => (
                  <div key={item.id} className="p-3 border rounded-lg space-y-2">
                    <div className="flex items-start gap-3">
                      <span className="text-purple-600 font-medium min-w-[24px] mt-0.5">{idx + 1}.</span>
                      <Checkbox
                        checked={item.is_checked || false}
                        onCheckedChange={(checked) => void toggleChecklistItem(item.id, !!checked)}
                        className="mt-0.5"
                      />
                      <div className="flex-1">
                        {isAdmin && gaMeetingEditingId === item.id ? (
                          <div className="flex items-center gap-2">
                            <Input
                              value={gaMeetingEditingText}
                              onChange={(e) => setGaMeetingEditingText(e.target.value)}
                            />
                            <Button
                              variant="outline"
                              disabled={!gaMeetingEditingText.trim() || gaMeetingSaving}
                              onClick={() => void saveEditGaMeetingItem()}
                            >
                              Save
                            </Button>
                            <Button
                              variant="ghost"
                              onClick={() => {
                                setGaMeetingEditingId(null)
                                setGaMeetingEditingText("")
                              }}
                            >
                              Cancel
                            </Button>
                          </div>
                        ) : (
                          <span className={item.is_checked ? "line-through text-muted-foreground" : ""}>
                            {item.title}
                          </span>
                        )}
                      </div>
                      {isAdmin && gaMeetingEditingId !== item.id ? (
                        <div className="flex items-center gap-2">
                          <Button variant="ghost" onClick={() => startEditGaMeetingItem(item)}>
                            Edit
                          </Button>
                          <Button
                            variant="ghost"
                            disabled={gaMeetingSaving}
                            onClick={() => void deleteGaMeetingItem(item.id)}
                          >
                            Delete
                          </Button>
                        </div>
                      ) : null}
                    </div>
                    {/* Comment section */}
                    <div className="ml-9 space-y-2">
                      {commentEditingId === item.id ? (
                        <div className="space-y-2">
                          <Textarea
                            value={commentEditingText}
                            onChange={(e) => setCommentEditingText(e.target.value)}
                            placeholder="Add a comment..."
                            rows={2}
                          />
                          <div className="flex items-center gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={commentSaving}
                              onClick={() => void saveComment(item.id)}
                            >
                              {commentSaving ? "Saving..." : "Save Comment"}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={cancelEditComment}>
                              Cancel
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-start gap-2">
                          {item.comment ? (
                            <div className="flex-1 text-sm text-muted-foreground bg-muted p-2 rounded">
                              {item.comment}
                            </div>
                          ) : (
                            <div className="flex-1 text-sm text-muted-foreground italic">
                              No comment
                            </div>
                          )}
                          <Button variant="ghost" size="sm" onClick={() => startEditComment(item)}>
                            {item.comment ? "Edit" : "Add"} Comment
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
            {isAdmin ? (
              <div className="mt-6 grid gap-2 md:grid-cols-[120px_1fr_auto]">
                <div className="space-y-1">
                  <Label>Number</Label>
                  <Input
                    value={gaMeetingNewNumber}
                    onChange={(e) => setGaMeetingNewNumber(e.target.value)}
                    placeholder="e.g. 3"
                  />
                </div>
                <div className="space-y-1">
                  <Label>Item</Label>
                  <Input
                    value={gaMeetingNewText}
                    onChange={(e) => setGaMeetingNewText(e.target.value)}
                    placeholder="Add new checklist item..."
                  />
                </div>
                <div className="flex items-end">
                  <Button
                    variant="outline"
                    disabled={!gaMeetingNewText.trim() || gaMeetingSaving}
                    onClick={() => void addGaMeetingItem()}
                  >
                    {gaMeetingSaving ? "Saving..." : "Add"}
                  </Button>
                </div>
              </div>
            ) : null}
          </Card>
        )}

        {/* PROPOZIM KO1/KO2 Tab */}
        {activeTab === "propozim-ko1-ko2" && (
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-4">PROPOZIM KO1/KO2</h3>

            {propozimItems.length === 0 ? (
              <p className="text-muted-foreground">Duke ngarkuar checklistën...</p>
            ) : (
              <div className="space-y-3">
                {propozimItems.map((item, idx) => (
                  <div key={item.id} className="p-3 border rounded-lg space-y-2">
                    <div className="flex items-start gap-3">
                      <span className="text-purple-600 font-medium min-w-[24px] mt-0.5">{idx + 1}.</span>
                      <Checkbox
                        checked={item.is_checked || false}
                        onCheckedChange={(checked) => void toggleChecklistItem(item.id, !!checked)}
                        className="mt-0.5"
                      />
                      <div className="flex-1">
                        {isAdmin && propozimEditingId === item.id ? (
                          <div className="flex items-center gap-2">
                            <Input
                              value={propozimEditingText}
                              onChange={(e) => setPropozimEditingText(e.target.value)}
                            />
                            <Button
                              variant="outline"
                              disabled={!propozimEditingText.trim() || propozimSaving}
                              onClick={() => void saveEditPropozimItem()}
                            >
                              Save
                            </Button>
                            <Button
                              variant="ghost"
                              onClick={() => {
                                setPropozimEditingId(null)
                                setPropozimEditingText("")
                              }}
                            >
                              Cancel
                            </Button>
                          </div>
                        ) : (
                          <span className={item.is_checked ? "line-through text-muted-foreground" : ""}>
                            {item.title}
                          </span>
                        )}
                      </div>
                      {isAdmin && propozimEditingId !== item.id ? (
                        <div className="flex items-center gap-2">
                          <Button variant="ghost" onClick={() => startEditPropozimItem(item)}>
                            Edit
                          </Button>
                          <Button
                            variant="ghost"
                            disabled={propozimSaving}
                            onClick={() => void deletePropozimItem(item.id)}
                          >
                            Delete
                          </Button>
                        </div>
                      ) : null}
                    </div>
                    {/* Comment section */}
                    <div className="ml-9 space-y-2">
                      {commentEditingId === item.id ? (
                        <div className="space-y-2">
                          <Textarea
                            value={commentEditingText}
                            onChange={(e) => setCommentEditingText(e.target.value)}
                            placeholder="Add a comment..."
                            rows={2}
                          />
                          <div className="flex items-center gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={commentSaving}
                              onClick={() => void saveComment(item.id)}
                            >
                              {commentSaving ? "Saving..." : "Save Comment"}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={cancelEditComment}>
                              Cancel
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-start gap-2">
                          {item.comment ? (
                            <div className="flex-1 text-sm text-muted-foreground bg-muted p-2 rounded">
                              {item.comment}
                            </div>
                          ) : (
                            <div className="flex-1 text-sm text-muted-foreground italic">
                              No comment
                            </div>
                          )}
                          <Button variant="ghost" size="sm" onClick={() => startEditComment(item)}>
                            {item.comment ? "Edit" : "Add"} Comment
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {isAdmin ? (
              <div className="mt-6 grid gap-2 md:grid-cols-[120px_1fr_auto]">
                <div className="space-y-1">
                  <Label>Number</Label>
                  <Input
                    value={propozimNewNumber}
                    onChange={(e) => setPropozimNewNumber(e.target.value)}
                    placeholder="e.g. 3"
                  />
                </div>
                <div className="space-y-1">
                  <Label>Item</Label>
                  <Input
                    value={propozimNewText}
                    onChange={(e) => setPropozimNewText(e.target.value)}
                    placeholder="Add new checklist item..."
                  />
                </div>
                <div className="flex items-end">
                  <Button
                    variant="outline"
                    disabled={!propozimNewText.trim() || propozimSaving}
                    onClick={() => void addPropozimItem()}
                  >
                    {propozimSaving ? "Saving..." : "Add"}
                  </Button>
                </div>
              </div>
            ) : null}
          </Card>
        )}

        {/* PUNIMI Tab */}
        {activeTab === "punimi" && (
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-4">PUNIMI</h3>

            {punimiItems.length === 0 ? (
              <p className="text-muted-foreground">Duke ngarkuar checklistën...</p>
            ) : (
              <div className="space-y-3">
                {punimiItems.map((item, idx) => (
                  <div key={item.id} className="p-3 border rounded-lg space-y-2">
                    <div className="flex items-start gap-3">
                      <span className="text-purple-600 font-medium min-w-[24px] mt-0.5">{idx + 1}.</span>
                      <Checkbox
                        checked={item.is_checked || false}
                        onCheckedChange={(checked) => void toggleChecklistItem(item.id, !!checked)}
                        className="mt-0.5"
                      />
                      <div className="flex-1">
                        {isAdmin && punimiEditingId === item.id ? (
                          <div className="flex items-center gap-2">
                            <Input
                              value={punimiEditingText}
                              onChange={(e) => setPunimiEditingText(e.target.value)}
                            />
                            <Button
                              variant="outline"
                              disabled={!punimiEditingText.trim() || punimiSaving}
                              onClick={() => void saveEditPunimiItem()}
                            >
                              Save
                            </Button>
                            <Button
                              variant="ghost"
                              onClick={() => {
                                setPunimiEditingId(null)
                                setPunimiEditingText("")
                              }}
                            >
                              Cancel
                            </Button>
                          </div>
                        ) : (
                          <span className={item.is_checked ? "line-through text-muted-foreground" : ""}>
                            {item.title}
                          </span>
                        )}
                      </div>
                      {isAdmin && punimiEditingId !== item.id ? (
                        <div className="flex items-center gap-2">
                          <Button variant="ghost" onClick={() => startEditPunimiItem(item)}>
                            Edit
                          </Button>
                          <Button
                            variant="ghost"
                            disabled={punimiSaving}
                            onClick={() => void deletePunimiItem(item.id)}
                          >
                            Delete
                          </Button>
                        </div>
                      ) : null}
                    </div>
                    {/* Comment section */}
                    <div className="ml-9 space-y-2">
                      {commentEditingId === item.id ? (
                        <div className="space-y-2">
                          <Textarea
                            value={commentEditingText}
                            onChange={(e) => setCommentEditingText(e.target.value)}
                            placeholder="Add a comment..."
                            rows={2}
                          />
                          <div className="flex items-center gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={commentSaving}
                              onClick={() => void saveComment(item.id)}
                            >
                              {commentSaving ? "Saving..." : "Save Comment"}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={cancelEditComment}>
                              Cancel
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-start gap-2">
                          {item.comment ? (
                            <div className="flex-1 text-sm text-muted-foreground bg-muted p-2 rounded">
                              {item.comment}
                            </div>
                          ) : (
                            <div className="flex-1 text-sm text-muted-foreground italic">
                              No comment
                            </div>
                          )}
                          <Button variant="ghost" size="sm" onClick={() => startEditComment(item)}>
                            {item.comment ? "Edit" : "Add"} Comment
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {isAdmin ? (
              <div className="mt-6 grid gap-2 md:grid-cols-[120px_1fr_auto]">
                <div className="space-y-1">
                  <Label>Number</Label>
                  <Input
                    value={punimiNewNumber}
                    onChange={(e) => setPunimiNewNumber(e.target.value)}
                    placeholder="e.g. 3"
                  />
                </div>
                <div className="space-y-1">
                  <Label>Item</Label>
                  <Input
                    value={punimiNewText}
                    onChange={(e) => setPunimiNewText(e.target.value)}
                    placeholder="Add new checklist item..."
                  />
                </div>
                <div className="flex items-end">
                  <Button
                    variant="outline"
                    disabled={!punimiNewText.trim() || punimiSaving}
                    onClick={() => void addPunimiItem()}
                  >
                    {punimiSaving ? "Saving..." : "Add"}
                  </Button>
                </div>
              </div>
            ) : null}
          </Card>
        )}

        {/* PRODUKTE SA JANE KRYER Tab */}
        {activeTab === "produkte-sa-jane-kryer" && (
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-4">PRODUKTE SA JANE KRYER</h3>
            <div className="space-y-4">
              <div className="grid grid-cols-12 gap-4 text-[11px] font-medium text-slate-400 uppercase tracking-wider pb-3">
                <div className="col-span-4">Task</div>
                <div className="col-span-1">Assigned</div>
                <div className="col-span-2">Total</div>
                <div className="col-span-2">Completed</div>
                <div className="col-span-2">Status</div>
                <div className="col-span-1"></div>
              </div>
              <div className="grid grid-cols-12 gap-4 py-4 text-sm items-center bg-slate-50/60 -mx-6 px-6 border-y border-slate-100">
                <div className="col-span-4">
                  <input
                    type="text"
                    placeholder="Enter task name..."
                    className="w-full bg-transparent border-0 border-b-2 border-slate-200 focus:border-purple-500 outline-none py-2 text-sm placeholder:text-slate-400 transition-colors"
                    value={newProductTaskTitle}
                    onChange={(e) => setNewProductTaskTitle(e.target.value)}
                  />
                </div>
                <div className="col-span-1">
                  <Select value={newProductTaskAssignee} onValueChange={setNewProductTaskAssignee}>
                    <SelectTrigger className="h-9 border-0 border-b-2 border-slate-200 rounded-none bg-transparent focus:border-purple-500 shadow-none">
                      <SelectValue placeholder="-" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__unassigned__">-</SelectItem>
                      {assignableUsers.map((u) => (
                        <SelectItem key={u.id} value={u.id}>
                          {u.full_name || u.username || u.email}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="col-span-2">
                  <input
                    type="number"
                    placeholder="0"
                    className="w-full bg-transparent border-0 border-b-2 border-slate-200 focus:border-purple-500 outline-none py-2 text-sm placeholder:text-slate-400 transition-colors"
                    value={newProductTaskTotal}
                    onChange={(e) => setNewProductTaskTotal(e.target.value)}
                  />
                </div>
                <div className="col-span-2">
                  <input
                    type="number"
                    placeholder="0"
                    className="w-full bg-transparent border-0 border-b-2 border-slate-200 focus:border-purple-500 outline-none py-2 text-sm placeholder:text-slate-400 transition-colors"
                    value={newProductTaskCompleted}
                    onChange={(e) => setNewProductTaskCompleted(e.target.value)}
                  />
                </div>
                <div className="col-span-2">
                  <Button
                    size="sm"
                    className="rounded-full px-5 shadow-sm"
                    onClick={async () => {
                      if (!project || !newProductTaskTitle.trim()) return
                      setCreatingProductTask(true)
                      try {
                        const res = await apiFetch("/tasks", {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({
                            title: newProductTaskTitle.trim(),
                            project_id: project.id,
                            department_id: project.department_id,
                            assigned_to: newProductTaskAssignee === "__unassigned__" ? null : newProductTaskAssignee,
                            status: "TODO",
                            priority: "NORMAL",
                            phase: "PRODUCT",
                            internal_notes: `total_products=${newProductTaskTotal || 0}; completed_products=${newProductTaskCompleted || 0}`,
                          }),
                        })
                        if (!res?.ok) {
                          toast.error("Failed to add task")
                          return
                        }
                        const created = (await res.json()) as Task
                        setTasks((prev) => [...prev, created])
                        setNewProductTaskTitle("")
                        setNewProductTaskAssignee("__unassigned__")
                        setNewProductTaskTotal("")
                        setNewProductTaskCompleted("")
                        toast.success("Task added")
                      } finally {
                        setCreatingProductTask(false)
                      }
                    }}
                    disabled={creatingProductTask || !newProductTaskTitle.trim()}
                  >
                    {creatingProductTask ? "Saving..." : "Save"}
                  </Button>
                </div>
                <div className="col-span-1"></div>
              </div>
              <div className="divide-y divide-slate-100">
                {productTasks.map((task, index) => {
                  const totalVal = parseInt(productTaskEdits[task.id]?.total || "0", 10) || 0
                  const isEditing = Boolean(editingTaskIds[task.id])
                  return (
                    <div key={task.id} className="grid grid-cols-12 gap-4 py-4 text-sm items-center hover:bg-slate-50/70 transition-colors group">
                      <div className="col-span-4 font-medium text-slate-700">
                        {isEditing ? (
                          <input
                            type="text"
                            className="w-full bg-transparent border-0 border-b-2 border-slate-200 focus:border-purple-500 outline-none py-1 text-sm"
                            value={editingTaskTitles[task.id] ?? task.title}
                            onChange={(e) =>
                              setEditingTaskTitles((prev) => ({ ...prev, [task.id]: e.target.value }))
                            }
                          />
                        ) : (
                          <span>
                            {index + 1}. {task.ga_note_origin_id ? renderMarkedNoteContent(task.title, task.title) : task.title}
                          </span>
                        )}
                      </div>
                      <div className="col-span-1 text-slate-500">
                        {isEditing ? (
                          <Select
                            value={editingTaskAssignees[task.id] ?? (task.assigned_to || "__unassigned__")}
                            onValueChange={(value) =>
                              setEditingTaskAssignees((prev) => ({ ...prev, [task.id]: value }))
                            }
                          >
                            <SelectTrigger className="h-9 border-0 border-b-2 border-slate-200 rounded-none bg-transparent focus:border-purple-500 shadow-none">
                              <SelectValue placeholder="-" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="__unassigned__">-</SelectItem>
                              {assignableUsers.map((u) => (
                                <SelectItem key={u.id} value={u.id}>
                                  {u.full_name || u.username || u.email}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        ) : (
                          memberLabel(task.assigned_to)
                        )}
                      </div>
                      <div className="col-span-2 text-slate-500">
                        {isEditing ? (
                          <input
                            type="number"
                            className="w-full bg-transparent border-0 border-b-2 border-slate-200 focus:border-purple-500 outline-none py-1 text-sm"
                            value={editingTaskTotals[task.id] ?? productTaskEdits[task.id]?.total ?? ""}
                            onChange={(e) =>
                              setEditingTaskTotals((prev) => ({ ...prev, [task.id]: e.target.value }))
                            }
                          />
                        ) : (
                          productTaskEdits[task.id]?.total || "-"
                        )}
                      </div>
                      <div className="col-span-2">
                        <div className="flex items-center justify-center gap-2">
                          <button
                            type="button"
                            className="h-6 w-6 rounded-full border border-slate-300 text-slate-500 hover:text-slate-700"
                            onClick={async () => {
                              const completedNum = Math.max(
                                0,
                                (parseInt(productTaskEdits[task.id]?.completed || "0", 10) || 0) - 1
                              )
                              const newCompleted = completedNum.toString()
                              const shouldMarkDone = totalVal > 0 && completedNum >= totalVal
                              const newStatus = shouldMarkDone ? "DONE" : "TODO"
                              setProductTaskEdits((prev) => ({
                                ...prev,
                                [task.id]: { ...prev[task.id], completed: newCompleted, status: newStatus },
                              }))
                              await apiFetch(`/tasks/${task.id}`, {
                                method: "PATCH",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({
                                  internal_notes: `total_products=${productTaskEdits[task.id]?.total || 0}; completed_products=${newCompleted}`,
                                  status: newStatus,
                                }),
                              })
                            }}
                          >
                            -
                          </button>
                          <div className="min-w-[32px] text-center text-sm text-slate-700">
                            {productTaskEdits[task.id]?.completed || "0"}
                          </div>
                          <button
                            type="button"
                            className="h-6 w-6 rounded-full border border-slate-300 text-slate-500 hover:text-slate-700"
                            onClick={async () => {
                              let completedNum = (parseInt(productTaskEdits[task.id]?.completed || "0", 10) || 0) + 1
                              if (totalVal > 0 && completedNum > totalVal) completedNum = totalVal
                              const newCompleted = completedNum.toString()
                              const shouldMarkDone = totalVal > 0 && completedNum >= totalVal
                              const newStatus = shouldMarkDone ? "DONE" : "TODO"
                              setProductTaskEdits((prev) => ({
                                ...prev,
                                [task.id]: { ...prev[task.id], completed: newCompleted, status: newStatus },
                              }))
                              await apiFetch(`/tasks/${task.id}`, {
                                method: "PATCH",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({
                                  internal_notes: `total_products=${productTaskEdits[task.id]?.total || 0}; completed_products=${newCompleted}`,
                                  status: newStatus,
                                }),
                              })
                            }}
                          >
                            +
                          </button>
                        </div>
                      </div>
                      <div className="col-span-2">
                        <Badge
                          variant={task.status === "DONE" ? "default" : "outline"}
                          className={task.status === "DONE" ? "bg-emerald-500 hover:bg-emerald-600" : "text-slate-600 border-slate-300"}
                        >
                          {statusLabel(productTaskEdits[task.id]?.status || task.status)}
                        </Badge>
                      </div>
                      <div className="col-span-1 text-right opacity-0 group-hover:opacity-100 transition-opacity">
                        <div className="flex items-center justify-end gap-2">
                          {isEditing ? (
                            <>
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => void saveTaskRowEdits(task, false)}
                              >
                                Save
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => cancelEditTaskRow(task.id)}
                              >
                                Cancel
                              </Button>
                            </>
                          ) : (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => startEditTaskRow(task)}
                            >
                              Edit
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-8 w-8 p-0 text-slate-400 hover:text-red-500 hover:bg-red-50"
                            onClick={async () => {
                              const res = await apiFetch(`/tasks/${task.id}`, { method: "DELETE" })
                              if (!res?.ok) {
                                if (res?.status == 405) {
                                  toast.error("Delete endpoint not active. Restart backend.")
                                } else {
                                  toast.error("Failed to delete task")
                                }
                                return
                              }
                              setTasks((prev) => prev.filter((t) => t.id !== task.id))
                              toast.success("Task deleted")
                            }}
                          >
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18" /><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" /><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" /><line x1="10" x2="10" y1="11" y2="17" /><line x1="14" x2="14" y1="11" y2="17" /></svg>
                          </Button>
                        </div>
                      </div>
                    </div>
                  )
                })}
                {productTasks.length === 0 ? (
                  <div className="py-8 text-center text-sm text-slate-400">
                    No tasks yet. Add one above to get started.
                  </div>
                ) : null}
              </div>
            </div>
          </Card>
        )}

        {/* KO1/KO2 Tab */}
        {activeTab === "ko1-ko2" && (
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-4">KO1/KO2</h3>
            <div className="space-y-4">
              <div className="grid grid-cols-12 gap-4 text-[11px] font-medium text-slate-400 uppercase tracking-wider pb-3">
                <div className="col-span-4">Task</div>
                <div className="col-span-1">Assigned</div>
                <div className="col-span-2">Total</div>
                <div className="col-span-2">Completed</div>
                <div className="col-span-2">Status</div>
                <div className="col-span-1"></div>
              </div>
              <div className="grid grid-cols-12 gap-4 py-4 text-sm items-center bg-slate-50/60 -mx-6 px-6 border-y border-slate-100">
                <div className="col-span-4">
                  <input
                    type="text"
                    placeholder="Enter task name..."
                    className="w-full bg-transparent border-0 border-b-2 border-slate-200 focus:border-purple-500 outline-none py-2 text-sm placeholder:text-slate-400 transition-colors"
                    value={newKoTaskTitle}
                    onChange={(e) => setNewKoTaskTitle(e.target.value)}
                  />
                </div>
                <div className="col-span-1">
                  <Select value={newKoTaskAssignee} onValueChange={setNewKoTaskAssignee}>
                    <SelectTrigger className="h-9 border-0 border-b-2 border-slate-200 rounded-none bg-transparent focus:border-purple-500 shadow-none">
                      <SelectValue placeholder="-" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__unassigned__">-</SelectItem>
                      {assignableUsers.map((u) => (
                        <SelectItem key={u.id} value={u.id}>
                          {u.full_name || u.username || u.email}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="col-span-2">
                  <input
                    type="number"
                    placeholder="0"
                    className="w-full bg-transparent border-0 border-b-2 border-slate-200 focus:border-purple-500 outline-none py-2 text-sm placeholder:text-slate-400 transition-colors"
                    value={newKoTaskTotal}
                    onChange={(e) => setNewKoTaskTotal(e.target.value)}
                  />
                </div>
                <div className="col-span-2">
                  <input
                    type="number"
                    placeholder="0"
                    className="w-full bg-transparent border-0 border-b-2 border-slate-200 focus:border-purple-500 outline-none py-2 text-sm placeholder:text-slate-400 transition-colors"
                    value={newKoTaskCompleted}
                    onChange={(e) => setNewKoTaskCompleted(e.target.value)}
                  />
                </div>
                <div className="col-span-2">
                  <Button
                    size="sm"
                    className="rounded-full px-5 shadow-sm"
                    onClick={async () => {
                      if (!project || !newKoTaskTitle.trim()) return
                      setCreatingKoTask(true)
                      try {
                        const res = await apiFetch("/tasks", {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({
                            title: newKoTaskTitle.trim(),
                            project_id: project.id,
                            department_id: project.department_id,
                            assigned_to: newKoTaskAssignee === "__unassigned__" ? null : newKoTaskAssignee,
                            status: "TODO",
                            priority: "NORMAL",
                            phase: "PRODUCT",
                            internal_notes: `ko_tab=KO1KO2; total_products=${newKoTaskTotal || 0}; completed_products=${newKoTaskCompleted || 0}`,
                          }),
                        })
                        if (!res?.ok) {
                          toast.error("Failed to add task")
                          return
                        }
                        const created = (await res.json()) as Task
                        setTasks((prev) => [...prev, created])
                        setNewKoTaskTitle("")
                        setNewKoTaskAssignee("__unassigned__")
                        setNewKoTaskTotal("")
                        setNewKoTaskCompleted("")
                        toast.success("Task added")
                      } finally {
                        setCreatingKoTask(false)
                      }
                    }}
                    disabled={creatingKoTask || !newKoTaskTitle.trim()}
                  >
                    {creatingKoTask ? "Saving..." : "Save"}
                  </Button>
                </div>
                <div className="col-span-1"></div>
              </div>
              <div className="divide-y divide-slate-100">
                {koTasks.map((task, index) => {
                  const totalVal = parseInt(productTaskEdits[task.id]?.total || "0", 10) || 0
                  const isEditing = Boolean(editingTaskIds[task.id])
                  return (
                    <div key={task.id} className="grid grid-cols-12 gap-4 py-4 text-sm items-center hover:bg-slate-50/70 transition-colors group">
                      <div className="col-span-4 font-medium text-slate-700">
                        {isEditing ? (
                          <input
                            type="text"
                            className="w-full bg-transparent border-0 border-b-2 border-slate-200 focus:border-purple-500 outline-none py-1 text-sm"
                            value={editingTaskTitles[task.id] ?? task.title}
                            onChange={(e) =>
                              setEditingTaskTitles((prev) => ({ ...prev, [task.id]: e.target.value }))
                            }
                          />
                        ) : (
                          <span>
                            {index + 1}. {task.ga_note_origin_id ? renderMarkedNoteContent(task.title, task.title) : task.title}
                          </span>
                        )}
                      </div>
                      <div className="col-span-1 text-slate-500">
                        {isEditing ? (
                          <Select
                            value={editingTaskAssignees[task.id] ?? (task.assigned_to || "__unassigned__")}
                            onValueChange={(value) =>
                              setEditingTaskAssignees((prev) => ({ ...prev, [task.id]: value }))
                            }
                          >
                            <SelectTrigger className="h-9 border-0 border-b-2 border-slate-200 rounded-none bg-transparent focus:border-purple-500 shadow-none">
                              <SelectValue placeholder="-" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="__unassigned__">-</SelectItem>
                              {assignableUsers.map((u) => (
                                <SelectItem key={u.id} value={u.id}>
                                  {u.full_name || u.username || u.email}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        ) : (
                          memberLabel(task.assigned_to)
                        )}
                      </div>
                      <div className="col-span-2 text-slate-500">
                        {isEditing ? (
                          <input
                            type="number"
                            className="w-full bg-transparent border-0 border-b-2 border-slate-200 focus:border-purple-500 outline-none py-1 text-sm"
                            value={editingTaskTotals[task.id] ?? productTaskEdits[task.id]?.total ?? ""}
                            onChange={(e) =>
                              setEditingTaskTotals((prev) => ({ ...prev, [task.id]: e.target.value }))
                            }
                          />
                        ) : (
                          productTaskEdits[task.id]?.total || "-"
                        )}
                      </div>
                      <div className="col-span-2">
                        <div className="flex items-center justify-center gap-2">
                          <button
                            type="button"
                            className="h-6 w-6 rounded-full border border-slate-300 text-slate-500 hover:text-slate-700"
                            onClick={async () => {
                              const completedNum = Math.max(
                                0,
                                (parseInt(productTaskEdits[task.id]?.completed || "0", 10) || 0) - 1
                              )
                              const newCompleted = completedNum.toString()
                              const shouldMarkDone = totalVal > 0 && completedNum >= totalVal
                              const newStatus = shouldMarkDone ? "DONE" : "TODO"
                              setProductTaskEdits((prev) => ({
                                ...prev,
                                [task.id]: { ...prev[task.id], completed: newCompleted, status: newStatus },
                              }))
                              await apiFetch(`/tasks/${task.id}`, {
                                method: "PATCH",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({
                                  internal_notes: `ko_tab=KO1KO2; total_products=${productTaskEdits[task.id]?.total || 0}; completed_products=${newCompleted}`,
                                  status: newStatus,
                                }),
                              })
                            }}
                          >
                            -
                          </button>
                          <div className="min-w-[32px] text-center text-sm text-slate-700">
                            {productTaskEdits[task.id]?.completed || "0"}
                          </div>
                          <button
                            type="button"
                            className="h-6 w-6 rounded-full border border-slate-300 text-slate-500 hover:text-slate-700"
                            onClick={async () => {
                              let completedNum = (parseInt(productTaskEdits[task.id]?.completed || "0", 10) || 0) + 1
                              if (totalVal > 0 && completedNum > totalVal) completedNum = totalVal
                              const newCompleted = completedNum.toString()
                              const shouldMarkDone = totalVal > 0 && completedNum >= totalVal
                              const newStatus = shouldMarkDone ? "DONE" : "TODO"
                              setProductTaskEdits((prev) => ({
                                ...prev,
                                [task.id]: { ...prev[task.id], completed: newCompleted, status: newStatus },
                              }))
                              await apiFetch(`/tasks/${task.id}`, {
                                method: "PATCH",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({
                                  internal_notes: `ko_tab=KO1KO2; total_products=${productTaskEdits[task.id]?.total || 0}; completed_products=${newCompleted}`,
                                  status: newStatus,
                                }),
                              })
                            }}
                          >
                            +
                          </button>
                        </div>
                      </div>
                      <div className="col-span-2">
                        <Badge
                          variant={task.status === "DONE" ? "default" : "outline"}
                          className={task.status === "DONE" ? "bg-emerald-500 hover:bg-emerald-600" : "text-slate-600 border-slate-300"}
                        >
                          {statusLabel(productTaskEdits[task.id]?.status || task.status)}
                        </Badge>
                      </div>
                      <div className="col-span-1 text-right opacity-0 group-hover:opacity-100 transition-opacity">
                        <div className="flex items-center justify-end gap-2">
                          {isEditing ? (
                            <>
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => void saveTaskRowEdits(task, true)}
                              >
                                Save
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => cancelEditTaskRow(task.id)}
                              >
                                Cancel
                              </Button>
                            </>
                          ) : (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => startEditTaskRow(task)}
                            >
                              Edit
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-8 w-8 p-0 text-slate-400 hover:text-red-500 hover:bg-red-50"
                            onClick={async () => {
                              const res = await apiFetch(`/tasks/${task.id}`, { method: "DELETE" })
                              if (!res?.ok) {
                                if (res?.status == 405) {
                                  toast.error("Delete endpoint not active. Restart backend.")
                                } else {
                                  toast.error("Failed to delete task")
                                }
                                return
                              }
                              setTasks((prev) => prev.filter((t) => t.id !== task.id))
                              toast.success("Task deleted")
                            }}
                          >
                            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18" /><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" /><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" /><line x1="10" x2="10" y1="11" y2="17" /><line x1="14" x2="14" y1="11" y2="17" /></svg>
                          </Button>
                        </div>
                      </div>
                    </div>
                  )
                })}
                {koTasks.length === 0 ? (
                  <div className="py-8 text-center text-sm text-slate-400">
                    No tasks yet. Add one above to get started.
                  </div>
                ) : null}
              </div>
            </div>
          </Card>
        )}

        {/* Members Tab */}
        {activeTab === "members" && (
          <Card className="p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold">Team Members</h3>
              <Dialog open={membersOpen} onOpenChange={setMembersOpen}>
                <DialogTrigger asChild>
                  <Button variant="outline">Manage Members</Button>
                </DialogTrigger>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Manage Team Members</DialogTitle>
                  </DialogHeader>
                  <div className="space-y-3 max-h-64 overflow-y-auto">
                    {departmentUsers.map((u) => (
                      <div key={u.id} className="flex items-center gap-3">
                        <Checkbox
                          checked={selectedMemberIds.includes(u.id)}
                          onCheckedChange={() => toggleMemberSelect(u.id)}
                        />
                        <div className="flex items-center gap-2">
                          <div className="w-8 h-8 rounded-full bg-purple-100 flex items-center justify-center text-xs font-medium text-purple-600">
                            {initials(u.full_name || u.email)}
                          </div>
                          <span>{u.full_name || u.email}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                  <Button onClick={() => void submitMembers()} disabled={savingMembers} className="w-full">
                    {savingMembers ? "Saving..." : "Save Members"}
                  </Button>
                </DialogContent>
              </Dialog>
            </div>
            {members.length === 0 ? (
              <p className="text-muted-foreground">No members assigned to this project.</p>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                {members.map((member) => (
                  <div key={member.id} className="flex items-center gap-3 p-3 border rounded-lg">
                    <div className="w-10 h-10 rounded-full bg-purple-100 flex items-center justify-center text-sm font-medium text-purple-600">
                      {initials(member.full_name || member.email)}
                    </div>
                    <div>
                      <div className="font-medium">{member.full_name || member.email}</div>
                      <div className="text-xs text-muted-foreground">{member.role || "Member"}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        )}

        {/* GA Notes Tab */}
        {activeTab === "ga-notes" && (
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-4">GA/KA Notes</h3>
            
            {/* Add new note */}
            <div className="space-y-3 mb-6 p-4 bg-muted/30 rounded-lg">
              <Textarea
                value={newGaNote}
                onChange={(e) => setNewGaNote(e.target.value)}
                placeholder="Add a new GA/KA note..."
                rows={3}
              />
              <div className="flex gap-4">
                <div className="flex-1">
                  <Label className="text-xs">Type</Label>
                  <Select value={newGaNoteType} onValueChange={setNewGaNoteType}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="GA">GA</SelectItem>
                      <SelectItem value="KA">KA</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex-1">
                  <Label className="text-xs">Priority</Label>
                  <Select value={newGaNotePriority} onValueChange={(v) => setNewGaNotePriority(v as typeof newGaNotePriority)}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__none__">None</SelectItem>
                      <SelectItem value="NORMAL">Normal</SelectItem>
                      <SelectItem value="HIGH">High</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <Button onClick={() => void submitGaNote()} disabled={addingGaNote}>
                {addingGaNote ? "Adding..." : "Add Note"}
              </Button>
            </div>

            {/* Notes list */}
            {gaNotes.length === 0 ? (
              <p className="text-muted-foreground">No GA/KA notes yet.</p>
            ) : (
              <div className="space-y-3">
                {gaNotes.map((note) => {
                  const creator = note.created_by ? userMap.get(note.created_by) : null
                  const linkedTask = tasks.find((task) => task.ga_note_origin_id === note.id)
                  return (
                    <div key={note.id} className={`p-4 border rounded-lg ${note.status === "CLOSED" ? "bg-muted/30" : ""}`}>
                      <div className="flex items-start justify-between">
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-2">
                            <Badge variant={note.note_type === "GA" ? "default" : "secondary"}>
                              {note.note_type}
                            </Badge>
                            {note.priority && (
                              <Badge variant={note.priority === "HIGH" ? "destructive" : "outline"}>
                                {note.priority}
                              </Badge>
                            )}
                            {note.status === "CLOSED" && (
                              <Badge variant="outline" className="text-green-600">Closed</Badge>
                            )}
                          </div>
                          <p className={note.status === "CLOSED" ? "text-muted-foreground" : ""}>
                            {note.content}
                          </p>
                          <div className="text-xs text-muted-foreground mt-2">
                            {creator ? creator.full_name || creator.email : "Unknown"} ??? {formatDateTime(note.created_at)}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          {linkedTask ? (
                            <Badge variant="outline" className="text-muted-foreground">Task Created</Badge>
                          ) : null}
                          {note.status !== "CLOSED" && (
                            <Button variant="ghost" size="sm" onClick={() => void closeGaNote(note.id)}>
                              Close
                            </Button>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </Card>
        )}

        {/* Finalization Tab */}
        {activeTab === "finalization" && (
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-4">{FINALIZATION_TITLE}</h3>
            {finalizationItemsOrdered.length === 0 ? (
              <p className="text-muted-foreground">No finalization items yet.</p>
            ) : (
              <div className="space-y-2">
                {finalizationItemsOrdered.map((item, idx) => (
                  <div key={item.id} className="p-3 border rounded-lg space-y-2">
                    <div className="flex items-center gap-3">
                      <span className="text-purple-600 font-medium min-w-[24px] mt-0.5">{idx + 1}.</span>
                      <Checkbox
                        checked={item.is_checked || false}
                        onCheckedChange={(checked) => void toggleChecklistItem(item.id, !!checked)}
                      />
                      <span className={item.is_checked ? "line-through text-muted-foreground" : ""}>
                        {item.title || ""}
                      </span>
                    </div>
                    <div className="ml-9 space-y-2">
                      {commentEditingId === item.id ? (
                        <div className="space-y-2">
                          <Textarea
                            value={commentEditingText}
                            onChange={(e) => setCommentEditingText(e.target.value)}
                            placeholder="Add a comment..."
                            rows={2}
                          />
                          <div className="flex items-center gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={commentSaving}
                              onClick={() => void saveComment(item.id)}
                            >
                              {commentSaving ? "Saving..." : "Save Comment"}
                            </Button>
                            <Button variant="ghost" size="sm" onClick={cancelEditComment}>
                              Cancel
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex items-start gap-2">
                          {item.comment ? (
                            <div className="flex-1 text-sm text-muted-foreground bg-muted p-2 rounded">
                              {item.comment}
                            </div>
                          ) : (
                            <div className="flex-1 text-sm text-muted-foreground italic">
                              No comment
                            </div>
                          )}
                          <Button variant="ghost" size="sm" onClick={() => startEditComment(item)}>
                            {item.comment ? "Edit" : "Add"} Comment
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {isAdmin ? (
              <div className="mt-4 grid gap-2 md:grid-cols-[120px_1fr_auto]">
                <div className="space-y-1">
                  <Label>Number</Label>
                  <Input
                    value={finalizationNewNumber}
                    onChange={(e) => setFinalizationNewNumber(e.target.value)}
                    placeholder="e.g. 3"
                  />
                </div>
                <div className="space-y-1">
                  <Label>Item</Label>
                  <Input
                    value={finalizationNewText}
                    onChange={(e) => setFinalizationNewText(e.target.value)}
                    placeholder="Add new checklist item..."
                  />
                </div>
                <div className="flex items-end">
                  <Button
                    variant="outline"
                    disabled={!finalizationNewText.trim() || finalizationSaving}
                    onClick={() => void addFinalizationItem()}
                  >
                    {finalizationSaving ? "Saving..." : "Add"}
                  </Button>
                </div>
              </div>
            ) : null}
          </Card>
        )}

      </div>
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
