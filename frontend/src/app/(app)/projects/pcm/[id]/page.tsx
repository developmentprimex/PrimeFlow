"use client"

import { ProjectActivityControl } from "@/components/project-activity"

import * as React from "react"
import { useParams, useRouter } from "next/navigation"

import { toast } from "sonner"
import { Check, Pencil, Trash2, Calendar, Users, FileText, Link2, MessageSquare, ListChecks, Lock, ChevronRight, Plus, Download } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useConfirm } from "@/components/providers/confirm-dialog-provider"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { BoldOnlyEditor } from "@/components/bold-only-editor"
import { ChecklistInlineStyleEditor } from "@/components/checklist-inline-style-editor"
import { useAuth } from "@/lib/auth"
import { formatDateDMY, formatDateTimeDMY, normalizeDueDateInput, toDateInputValue } from "@/lib/dates"
import { renderChecklistInlineStyle, stripChecklistInlineStyleTokens } from "@/lib/checklist-inline-style"
import { renderMarkedNoteContent } from "@/lib/note-markup"
import { getConfirmerCandidates, isWaitingConfirmation, validateWaitingConfirmation } from "@/lib/task-confirmation"
import type { ChecklistItem, ChecklistWithItems, GaNote, Meeting, Project, ProjectPrompt, Task, TaskFinishPeriod, TaskPriority, User } from "@/lib/types"
import { VsWorkflow } from "@/components/projects/vs-workflow"
import { isMstOrTtProject, isTtProjectTitle } from "@/lib/pcm-project-classification"


// PCM phases (English labels)
const PHASES = ["MEETINGS", "PLANNING", "DEVELOPMENT", "TESTING", "DOCUMENTATION", "CLOSED"] as const
const PHASE_LABELS: Record<string, string> = {
  MEETINGS: "Meetings",
  PLANNING: "Planning",
  DEVELOPMENT: "Development",
  TESTING: "Testing",
  DOCUMENTATION: "Documentation",
  CLOSED: "Closed",
}

// MST-specific phases
const MST_PHASES = ["PLANNING", "PRODUCT", "CONTROL", "FINAL"] as const
const MST_PHASE_LABELS: Record<(typeof MST_PHASES)[number], string> = {
  PLANNING: "Planning",
  PRODUCT: "Product",
  CONTROL: "Control",
  FINAL: "Final",
}

const FINISH_PERIOD_OPTIONS: TaskFinishPeriod[] = ["AM", "PM"]
const FINISH_PERIOD_NONE_VALUE = "__none__"
const FINISH_PERIOD_NONE_LABEL = "All day"
const PROJECT_TASK_TYPES = ["NORMAL", "HIGH", "1H", "R1", "PERSONAL", "BLLOK"] as const

const VS_VL_PHASES = ["PLANNING", "AMAZON", "CHECK", "DREAMROBOT"] as const
const VS_VL_PHASE_LABELS: Record<(typeof VS_VL_PHASES)[number], string> = {
  PLANNING: "Planning",
  AMAZON: "Amazon",
  CHECK: "Check",
  DREAMROBOT: "Dreamrobot",
}
const VS_VL_ACCEPTANCE_QUESTIONS = [
  "IS TEAMS GROUP OPENED?",
  "ARE TRELLO POINTS ADDED?",
  "IS CHATGPT PROJECT OPENED?",
]
const VS_VL_META_PREFIX = "VS_VL_META:"

const MST_PLANNING_QUESTIONS = [
  "Is the group opened in Teams?",
  "Is the project opened in Chat GPT?",
  "Have all necessary documents been received (PDF, Stammdaten, Artikelliste)?",
  "Has the category and PDF been analyzed?",
  "Have the program characteristics been identified?",
  "Is there a plan for when the project is expected to be completed?",
]
const MST_PROGRAM_QUESTION_LEGACY = "A eshte hapur projekti ne chat GPT?"
const MST_PLANNING_ORDER = new Map(
  MST_PLANNING_QUESTIONS.map((question, index) => [question.trim().toLowerCase(), index])
)
MST_PLANNING_ORDER.set(MST_PROGRAM_QUESTION_LEGACY.trim().toLowerCase(), 1)
const MST_PRODUCT_TEMPLATE_GROUP_KEY = "MST_PRODUCT_CHECKLIST_TEMPLATE"
const TT_PRODUCT_TEMPLATE_GROUP_KEY = "TT_PRODUCT_CHECKLIST_TEMPLATE"

function getMstPlanningOrder(item: ChecklistItem) {
  const key = (item.description || item.title || "").trim().toLowerCase()
  const order = key ? MST_PLANNING_ORDER.get(key) : undefined
  return order ?? Number.MAX_SAFE_INTEGER
}
const FINALIZATION_PATH = "FINALIZATION"
const MST_EXCLUDED_PATHS = new Set(["PLANNING", FINALIZATION_PATH, "MEETINGS", "VS_VL_PLANNING"])
const FINALIZATION_CHECKLIST = [
  { id: "kontrollat", question: "A jane kryer kontrollat?" },
  { id: "files", question: "A eshte ruajtur projekti tek files?" },
]

// Helper function to initialize MST checklist items in database
async function initializeMstChecklistItems(
  projectId: string,
  existingItems: ChecklistItem[],
  templateRows: MstChecklistRow[],
  apiFetch: (url: string, options?: RequestInit) => Promise<Response>,
  allowDelete = false,
  includeOriginal = true
) {
  // Create a map of existing items by path + title for quick lookup
  // Also detect and remove duplicates
  const existingMap = new Map<string, ChecklistItem>()
  const duplicates: string[] = []

  existingItems.forEach((item) => {
    let key: string
    if (item.path && item.title) {
      key = `${item.path}|${item.title}`
    } else if (item.title && !item.path) {
      // For planning questions, use just title as key
      key = `PLANNING|${item.title}`
    } else {
      return // Skip items without title
    }

    if (existingMap.has(key)) {
      // Found a duplicate - mark for deletion
      if (item.id) duplicates.push(item.id)
    } else {
      existingMap.set(key, item)
    }
  })

  // Delete duplicates (admin/manager only)
  if (allowDelete) {
    for (const dupId of duplicates) {
      await apiFetch(`/checklist-items/${dupId}`, { method: "DELETE" }).catch(() => {
        // Ignore errors - item might already be deleted
      })
    }
  }

  // Find user IDs for "DV, LM" initials (we'll need to parse this)
  // For now, we'll create items without assignees and they can be added later

  // Create missing items from final checklist
  const finalItemsToCreate = templateRows.filter((row) => {
    const key = `${row.path}|${row.detyrat}`
    return !existingMap.has(key)
  })

  const finalizationItemsToCreate = FINALIZATION_CHECKLIST.filter((entry) => {
    const key = `${FINALIZATION_PATH}|${entry.question}`
    return !existingMap.has(key)
  })

  const existingPlanningItems = existingItems.filter(
    (item) => item.item_type === "CHECKBOX" && item.path === "PLANNING"
  )
  const shouldSeedPlanning = existingPlanningItems.length === 0

  // Create missing planning questions only when none exist yet (admin-managed afterwards).
  const planningItemsToCreate = shouldSeedPlanning
    ? MST_PLANNING_QUESTIONS.filter((question) => {
      const key = `PLANNING|${question}`
      return !existingMap.has(key)
    })
    : []

  // Combine all items to create
  const itemsToCreate = [
    ...finalItemsToCreate.map((row, index) => ({
      type: "final" as const,
      path: row.path,
      title: row.detyrat,
      keyword: row.keywords,
      description: row.pershkrimi,
      category: row.kategoria,
      original: row.original,
      owner: row.incl,
      position: index + 1,
    })),
    ...finalizationItemsToCreate.map((entry) => ({
      type: "finalization" as const,
      path: FINALIZATION_PATH,
      title: entry.question,
      keyword: FINALIZATION_PATH,
      description: entry.question,
      category: FINALIZATION_PATH,
      original: "",
    })),
    ...planningItemsToCreate.map((question) => ({
      type: "planning" as const,
      path: "PLANNING",
      title: question,
      keyword: "PLANNING",
      description: question,
      category: "PLANNING",
      original: "",
    })),
  ]

  // Create items in batches - ensure all are created
  const createPromises = itemsToCreate.map(async (item) => {
    try {
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          item_type: "CHECKBOX",
          path: item.path,
          title: item.title,
          keyword: item.keyword,
          description: item.description,
          category: item.category,
          ...(includeOriginal ? { original: item.original || null } : {}),
          owner: "owner" in item ? item.owner : undefined,
          is_checked: false,
          position: "position" in item ? item.position : undefined,
        }),
      })
      if (!res.ok) {
        const errorText = await res.text().catch(() => "Unknown error")
        console.error(`Failed to create checklist item "${item.title}":`, errorText)
        return false
      }
      return true
    } catch (error) {
      console.error(`Failed to create checklist item "${item.title}":`, error)
      return false
    }
  })

  // Wait for all items to be created
  const results = await Promise.all(createPromises)
  const successCount = results.filter(Boolean).length
  const totalCount = itemsToCreate.length

  if (successCount < totalCount) {
    console.warn(`Only created ${successCount} out of ${totalCount} checklist items`)
  } else if (totalCount > 0) {
    console.log(`Successfully initialized ${successCount} checklist items`)
  }
}

async function initializeVsVlPlanningItems(
  projectId: string,
  existingItems: ChecklistItem[],
  apiFetch: (url: string, options?: RequestInit) => Promise<Response>,
  allowDelete = false
) {
  // Get all existing VS/VL planning items (including duplicates)
  const vsVlItems = existingItems.filter(
    (item) => item.item_type === "CHECKBOX" && item.path === "VS_VL_PLANNING"
  )

  // Track unique titles and duplicates
  const seenTitles = new Map<string, ChecklistItem>()
  const duplicates: string[] = []

  for (const item of vsVlItems) {
    if (!item.title) continue
    if (seenTitles.has(item.title)) {
      // Found a duplicate - mark for deletion
      if (item.id) duplicates.push(item.id)
    } else {
      seenTitles.set(item.title, item)
    }
  }

  // Delete duplicates (admin/manager only)
  if (allowDelete) {
    for (const dupId of duplicates) {
      await apiFetch(`/checklist-items/${dupId}`, { method: "DELETE" }).catch(() => {
        // Ignore errors - item might already be deleted
      })
    }
  }

  // Create missing items
  const itemsToCreate = VS_VL_ACCEPTANCE_QUESTIONS.filter((title) => !seenTitles.has(title))
  for (const [index, title] of itemsToCreate.entries()) {
    await apiFetch("/checklist-items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: projectId,
        item_type: "CHECKBOX",
        position: seenTitles.size + index + 1,
        path: "VS_VL_PLANNING",
        keyword: "VS_VL_PLANNING",
        description: title,
        category: "VS_VL_PLANNING",
        title,
        is_checked: false,
      }),
    })
  }
}

type MstChecklistRow = {
  path: string
  detyrat: string
  keywords: string
  pershkrimi: string
  shembull?: string
  kategoria: string
  original?: string
  incl: string
}

function normalizeMstChecklistRows(rows: MstChecklistRow[]): MstChecklistRow[] {
  return rows.map((row) => ({
    path: row.path || "",
    detyrat: row.detyrat || "",
    keywords: row.keywords || "",
    pershkrimi: row.pershkrimi || "",
    shembull: row.shembull || "",
    kategoria: row.kategoria || "",
    original: row.original || "",
    incl: row.incl || "DV, DM",
  }))
}

function checklistItemsToMstTemplateRows(items: ChecklistItem[]): MstChecklistRow[] {
  return normalizeMstChecklistRows(
    items
      .filter((item) => item.item_type === "CHECKBOX")
      .sort((a, b) => {
        if ((a.position ?? 0) !== (b.position ?? 0)) return (a.position ?? 0) - (b.position ?? 0)
        return String(a.title || "").localeCompare(String(b.title || ""))
      })
      .map((item) => ({
        path: item.path || "",
        detyrat: item.title || "",
        keywords: item.keyword || "",
        pershkrimi: item.description || "",
        kategoria: item.category || "",
        original: item.original || "",
        incl: item.owner || "DV, DM",
      }))
  )
}
type VsVlTaskMeta = {
  vs_vl_phase?: (typeof VS_VL_PHASES)[number]
  dependency_text?: string
  checklist?: string
  dependency_task_id?: string
  comment?: string
  unlock_after_days?: number  // Days after dependency task's creation before this task is editable
  manual_due_date?: boolean
}

const MST_FINAL_CHECKLIST: MstChecklistRow[] = [
  {
    path: "Z:\\\\03_MUS\\\\01_CHECKLISTA",
    detyrat: "Hapja e projektit",
    keywords: "GRUPI",
    pershkrimi:
      "Hapet grupi ne Teams per program, dhe dergohen te gjitha dokumentet duke perfshire: AI/PDF PRICELIST/ EXCEL-ARTIKLE DATEN & FOTOT",
    kategoria: "GJENERALE",
    incl: "DV, DM",
  },
  {
    path: "CHECKLISTA",
    detyrat: "Shtypet Checklista per klient",
    keywords: "CHECKLISTA",
    pershkrimi: "Shtypet Checklista per klient, nese nuk kemi duke e punuar rastin e pare krijohet checklista",
    kategoria: "GJENERALE",
    incl: "DV, DM",
  },
  {
    path: "TEMPLATE",
    detyrat: "Hapet template paraprak",
    keywords: "TEMPLATE",
    pershkrimi: "Hapet template paraprak - nese kemi kategori te njejte qe e kemi punuar me heret",
    kategoria: "GJENERALE",
    incl: "DV, DM",
  },
  {
    path: "TRELLO",
    detyrat: "Hapet projekti ne Trello",
    keywords: "TRELLO",
    pershkrimi: "Hapet projekti ne Trello, dhe krijohet checklista me te gjithe hapat, ndahen detyrat",
    kategoria: "GJENERALE",
    incl: "DV, DM",
  },
  {
    path: "REGJISTRATOR",
    detyrat: "Regjistratori",
    keywords: "DOKUMENTET",
    pershkrimi:
      "Dokumentet e shtypura dhe Checklistat ruhen ne regj. Nese nuk kemi, duhet te krijohet regjistratori per klient",
    kategoria: "GJENERALE",
    incl: "DV, DM",
  },
  {
    path: "Rast 1",
    detyrat: "R1",
    keywords: "R1",
    pershkrimi:
      "Kur kemi rast te ri per kategori/subkategori qe nuk e kemi punuar me heret, hulumtojme funksione te reja dhe top seller ne portale.",
    kategoria: "GJENERALE",
    incl: "DV, DM",
  },
  {
    path: "Krahasimi i dimensioneve/kg-ve dhe atributeve tjera",
    detyrat: "DOKUMENTET",
    keywords: "DOKUMENTET",
    pershkrimi:
      "Krahaso te dhenat kg/dim dhe atributet tjera ne: 1. PDF (pricelist) 2. Excel databaza 3. Assembly Instructions 4. Portale (OTTO).",
    kategoria: "GJENERALE",
    incl: "DV, DM",
  },
  {
    path: "BESONDERE MERKMALE",
    detyrat: "BESONDERE",
    keywords: "BESONDERE",
    pershkrimi: "Besondere Merkmale max. 70 karaktere. T'i cekim me te vecantat e produktit.",
    kategoria: "GJENERALE",
    incl: "DV, DM",
  },
  {
    path: "SELLING POINT GENERAL",
    detyrat: "SELLING POINT",
    keywords: "PRODUKTE TE NJEJTA",
    pershkrimi:
      "Kur kemi nje produkt te njejte, por vetem ne dimensione te ndryshme, duhet te vendosen te gjitha dimensionet sepse 5 selling points duhet te jene identike. Mund te ndryshoje vetem Besondere Merkmale. Formati: Maße (B/H/T in cm): 220/240/280 x 46 x 45 cm.",
    kategoria: "GJENERALE",
    incl: "DV, DM",
  },
  {
    path: "SELLING POINTS",
    detyrat: "SELLING POINTS",
    keywords: "SELLING POINTS",
    pershkrimi:
      "Selling points te shkurta. Produkte identike me ngjyra ndryshe nuk duhet te kene pershkrime te ndryshme.",
    kategoria: "GJENERALE",
    incl: "DV, DM",
  },
  { path: "SELLING POINT 1", detyrat: "5 JAHRE GARANTIE", keywords: "GARANTIE", pershkrimi: "", kategoria: "GJENERALE", incl: "DV, DM" },
  {
    path: "SELLING POINT 2",
    detyrat: "MATERIALI & DIZAJNI",
    keywords: "MATERIALI",
    pershkrimi: "",
    kategoria: "GJENERALE",
    incl: "DV, DM",
  },
  {
    path: "SELLING POINT 3",
    detyrat: "180°/Funksionet",
    keywords: "FUNKSIONET",
    pershkrimi: "",
    kategoria: "GJENERALE",
    incl: "DV, DM",
  },
  {
    path: "SELLING POINT 4",
    detyrat: "GESTELL/NGJYRA/DIMENSIONI",
    keywords: "DIMENSIONI",
    pershkrimi: "",
    kategoria: "GJENERALE",
    incl: "DV, DM",
  },
  {
    path: "SELLING POINT 5",
    detyrat: "MADE IN GERMANY",
    keywords: "MADE IN DE",
    pershkrimi: "",
    kategoria: "GJENERALE",
    incl: "DV, DM",
  },
  {
    path: "MARKENINFORMATIONEN",
    detyrat: "MARKENINFORMATIONEN",
    keywords: "MARKEN",
    pershkrimi:
      "Tekstet copy/paste: 1) Set One by MST ... 2) MST ... (shiko checkliste per tekstin e plote).",
    kategoria: "GJENERALE",
    incl: "DV, DM",
  },
  {
    path: "SPECIFIKA PER KARRIGE, SET APO TYPE",
    detyrat: "SET/TYPE",
    keywords: "CHAIRS",
    pershkrimi: "Pyet klientin nese shitet si set apo type (2,4,6,8). Konfirmo per kategori karrigesh.",
    kategoria: "CHAIRS",
    incl: "DV, DM",
  },
  {
    path: "SPECIFIKA PER SOFA, SET APO TYPE",
    detyrat: "SET/TYPE",
    keywords: "SOFA",
    pershkrimi:
      "Kontrollo mekanizmat e perfshire apo extra cmim. Kerkohen foto per konfirmim ngjyrash. BZ1N1 me PDF duhet te perputhen me LDB/bullet points.",
    kategoria: "SOFA",
    incl: "DV, DM",
  },
]
const DEFAULT_MST_PRODUCT_TEMPLATE_ROWS = normalizeMstChecklistRows(MST_FINAL_CHECKLIST)
const DEFAULT_TT_PRODUCT_TEMPLATE_ROWS = DEFAULT_MST_PRODUCT_TEMPLATE_ROWS

function buildMstTemplateOrderMap(rows: MstChecklistRow[]) {
  return new Map(rows.map((row, index) => [`${row.path}|${row.detyrat}`, index]))
}

const TABS = [
  { id: "description", label: "Description" },
  { id: "tasks", label: "Tasks" },
  { id: "checklists", label: "Checklists" },
  { id: "members", label: "Members" },
  { id: "ga", label: "GA/KA Notes" },
  { id: "financials", label: "Financials" },
] as const

const MEETING_TABS = [
  { id: "meeting-focus", label: "Meeting Focus" },
  { id: "meeting-checklist", label: "Checklist" },
] as const

type TabId = (typeof TABS)[number]["id"] | (typeof MEETING_TABS)[number]["id"]

const PCM_SELECTABLE_STATUSES = ["TODO", "IN_PROGRESS", "DONE"] as const
const LEGACY_WAITING_STATUS = "WAITING_CONFIRMATION"
const TASK_PRIORITIES = ["NORMAL", "HIGH"] as const

const MEETING_POINTS = [
  "Confirm scope and stakeholder alignment.",
  "Review budget and milestones.",
  "Define success criteria and reporting cadence.",
  "Identify risks and mitigation plans.",
]

// PCM-specific checklists
const MEETING_CHECKLIST_ITEMS = [
  "Contract signed",
  "Stakeholders introduced",
  "Roles clarified",
  "Budget reviewed",
  "Next meeting scheduled",
]
const DOCUMENTATION_CHECKLIST_QUESTIONS = [
  "Is the contract filed?",
  "Has the budget been approved?",
  "Has the client been invoiced?",
]

function initials(src: string) {
  return src
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("")
}

function initialsWithDots(src: string) {
  const raw = initials(src)
  if (!raw) return ""
  return raw.length === 1 ? raw : raw.split("").join(".")
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

function toDateInput(value?: string | null) {
  return toDateInputValue(value)
}

function formatDateDisplay(value?: string | null) {
  const formatted = formatDateDMY(value, "")
  return formatted || null
}

function mstBadgeLabel(project?: Project | null) {
  if (!project) return "MST"
  const title = (project.title || project.name || "").toUpperCase().trim()
  if (isTtProjectTitle(title)) {
    return "TT"
  }
  return "MST"
}
function isVsVlProject(project?: Project | null) {
  if (!project) return false
  const title = (project.title || project.name || "").toUpperCase()
  return title.includes("VS/VL") || isVsAmazonProject(project)
}
function isVsAmazonProject(project?: Project | null) {
  if (!project) return false
  const title = (project.title || project.name || "").toUpperCase()
  return title.includes("VS AMAZON") || title.includes("VS/VL AMAZON")
}


function parseVsVlMeta(notes?: string | null): VsVlTaskMeta | null {
  if (!notes || !notes.startsWith(VS_VL_META_PREFIX)) return null
  try {
    return JSON.parse(notes.slice(VS_VL_META_PREFIX.length)) as VsVlTaskMeta
  } catch {
    return null
  }
}

function serializeVsVlMeta(meta: VsVlTaskMeta): string {
  return `${VS_VL_META_PREFIX}${JSON.stringify(meta)}`
}

function vsVlPriorityLabel(priority?: string | null) {
  return priority === "HIGH" ? "I LARTE" : "NORMAL"
}

function getProjectTaskType(task: Task | null): (typeof PROJECT_TASK_TYPES)[number] {
  if (!task) return "NORMAL"
  if (task.is_1h_report) return "1H"
  if (task.is_r1) return "R1"
  if (task.is_personal) return "PERSONAL"
  if (task.is_bllok) return "BLLOK"
  return task.priority === "HIGH" ? "HIGH" : "NORMAL"
}

function normalizeTaskTitle(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, " ")
    .trim()
}

function parseTaskTotals(notes?: string | null) {
  if (!notes) return { total: 0, completed: 0 }
  const totalMatch = notes.match(/total_products[:=]\s*(\d+)/i)
  const completedMatch = notes.match(/completed_products[:=]\s*(\d+)/i)
  return {
    total: totalMatch ? parseInt(totalMatch[1], 10) : 0,
    completed: completedMatch ? parseInt(completedMatch[1], 10) : 0,
  }
}

function toNonNegativeInt(value: string | number | null | undefined): number {
  if (typeof value === "number") {
    return Number.isFinite(value) ? Math.max(0, Math.trunc(value)) : 0
  }
  const n = parseInt((value ?? "").toString(), 10)
  if (Number.isNaN(n) || n < 0) return 0
  return n
}

function computeStatusFromCompleted(total: number, completed: number): Task["status"] {
  if (total <= 0) return "TODO"
  if (completed <= 0) return "TODO"
  if (completed < total) return "IN_PROGRESS"
  return "DONE"
}

function getOriginTaskId(notes?: string | null) {
  if (!notes) return null
  const match = notes.match(/origin_task_id[:=]\s*([a-f0-9-]+)/i)
  return match ? match[1] : null
}

function parseKoUserId(notes?: string | null): string | null {
  if (!notes) return null
  const match = notes.match(/ko_user_id[:=]\s*([a-f0-9-]+)/i)
  return match ? match[1] : null
}

function parseProductionDate(notes?: string | null): string | null {
  if (!notes) return null
  const match = notes.match(/production_date[:=]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})/i)
  return match ? match[1] : null
}

function serializeInternalNotes(params: {
  total?: string | number
  completed?: string | number
  originTaskId?: string
  koUserId?: string | null
  productionDate?: string | null
}): string {
  const parts: string[] = []
  if (params.originTaskId) {
    parts.push(`origin_task_id=${params.originTaskId}`)
  }
  if (params.total !== undefined) {
    parts.push(`total_products=${params.total}`)
  }
  if (params.completed !== undefined) {
    parts.push(`completed_products=${params.completed}`)
  }
  if (params.koUserId) {
    parts.push(`ko_user_id=${params.koUserId}`)
  }
  if (params.productionDate) {
    parts.push(`production_date=${params.productionDate}`)
  }
  return parts.join("; ")
}

function addBusinessDaysToIso(baseIso: string, days: number) {
  const base = new Date(baseIso)
  if (Number.isNaN(base.getTime())) return null
  if (days === 0) return base.toISOString()
  let remaining = Math.max(0, days)
  const direction = remaining >= 0 ? 1 : -1
  while (remaining > 0) {
    base.setUTCDate(base.getUTCDate() + direction)
    const day = base.getUTCDay()
    if (day !== 0 && day !== 6) {
      remaining -= 1
    }
  }
  return base.toISOString()
}

function sameDate(value?: string | null, other?: string | null) {
  return toDateInput(value) === toDateInput(other)
}

const VS_VL_TASK_TITLES = {
  base: normalizeTaskTitle("ANALIZIMI DHE IDENTIFIKIMI I KOLONAVE"),
  template: normalizeTaskTitle("PLOTESIMI I TEMPLATE-IT TE AMAZONIT"),
  prices: normalizeTaskTitle("KALKULIMI I CMIMEVE"),
  photos: normalizeTaskTitle("GJENERIMI I FOTOVE"),
  control: normalizeTaskTitle("KONTROLLIMI I PROD. EGZSISTUESE DHE POSTIMI NE AMAZON"),
  ko1: normalizeTaskTitle("KO1 E PROJEKTIT VS"),
  ko2: normalizeTaskTitle("KO2 E PROJEKTIT VS"),
  dreamVs: normalizeTaskTitle("DREAM ROBOT VS"),
  dreamVl: normalizeTaskTitle("DREAM ROBOT VL"),
  dreamWeights: normalizeTaskTitle("KALKULIMI I PESHAVE"),
}

const VS_VL_AMAZON_CHECKLIST_PATH = "VS_VL_AMAZON_CHECKLIST"
const VS_VL_IMAGES_CHECKLIST_PATH = "VS_VL_IMAGES_CHECKLIST"

const VS_VL_AMAZON_CHECKLIST_NOTES = [
  "WHEN SOMETHING CHANGES FOR PARENTS, CHANGE IT FOR CHILDREN TOO",
  "FIRST ADJUST THE NAME THEN KEYWORDS",
  "WE CAN'T USE NEVER WORD PROSECCO. WE SHOULD ALWAYS UPDATE WITH SCHAUMWEIN or FRIZZANTE",
  "Do not add volume (e.g. 0.75 l) to child product names. Only add volume to the parent if there are duplicates.",
  "Do not mention \"Holzkiste\" (or \"HK\") in the product name, and don't put photo with wooden cask (Holzkisten).",
  "Check Dropdowns on \"Gültige Werte\" Sheet on Amazon Template",
  "Always use VLOOKUP to connect, not copy-paste, because the order of article numbers can change, and using copy-paste may lead to errors",
  "The term '1er Grand Cru Classé' is used for first-class wines, so it is not related to the quantity of the wine. Do not delete 03, 06, 12 in this case",
  "Food should not appear anywhere. In no title. Even if it is food like olives or anything like that",
]

interface VsVlChecklistRow {
  task: string
  comment: string
  time: string
}

const VS_VL_AMAZON_CHECKLIST_ITEMS: VsVlChecklistRow[] = [
  { task: "Fill data for missing Attributes in Produktdaten file (Ausbau, Beurteilung, Servierempfehlung, Temperature, Story, Geschmack)", comment: "Search for information on different websites: Wein Wolf, Vinello, and also on ChatGPT. Search by product name and producent (marke).", time: "1 H" },
  { task: "Transfer the missing data into the automated Excel file (with vlookup) and add for 4 child products.", comment: "", time: "2.5 H" },
  { task: "Check the Geschmack", comment: "If there is a Geschmack that isn't available in the dropdown, use ChatGPT to find the closest match.", time: "30 min" },
  { task: "Check how many characters the STORY has.", comment: "By adding an empty column after the Story column and using the LEN formula, it must not have more than 500 characters.", time: "2 min" },
  { task: "Check if there are any repeated words in Ausbau.", comment: "Delete if you find duplicate words", time: "15 min" },
  { task: "Price Calculation (normal price / feinkost price)", comment: "Create an excel file with two columns, in column A put Artikel Nr. only for parents and in column B put the price you find in Produktdaten. When we have same article numbers, we should use the highest price.", time: "10 min" },
  { task: "Price for 01- products, should always be -3 Euro for products with price under 50 Euro", comment: "Filter 01- products, and to price column, check for products with price under 50 Euro, and minus them (-3 Euro)", time: "10 min" },
  { task: "Fill in column K by looking at the category in column (AV). For Wein Wolf projekt ONLY BLANKS", comment: "IDs can be found in the Browse Nodes Amazon Excel file. Path: Y:\\20_VS\\99_TEMPLATE\\General", time: "1.5 H" },
  { task: "If the product is beer, write \"beer\" in column A. If the product is sirup, write \"grocery\" in column A.", comment: "", time: "" },
  { task: "Check column A for wine and spirits", comment: "If column AV mentions 'wein', put 'wine' in column A; otherwise, put 'spirits'.", time: "20 min" },
  { task: "Check the product name: [name of the vinery] [name of the wine] [Weisswein (Rotwein ...)] [colour] [süss (trocken ...)] [BIO (vegan ...)] [country] [inkl. FeinWert E-Book]", comment: "Replace Weißwein with Weisswein in product name. All product names should include the manufacturer. No (- / \" ) etc in the title/product name.", time: "2 H" },
  { task: "Create keywords, fill column (BK)", comment: "Add the product name + 2015-2025. Add for 4 child products. Do not write 01,03,16,12, liters (ex. (1 x 0.75l) and inkl. FeinWert E-Book", time: "40 min" },
  { task: "Remove \"brand\" from Keywords", comment: "If you have \"ST. Laurent\" and \"Gavi\" written in the keywords, delete it.", time: "2 min" },
  { task: "Products that are alcohol-free need to have separate columns filled out.", comment: "Amazon Template - Produktdaten (BY)- (AZ); (BZ) - (BA); (CA) - (BB); (CC) - (BC); (CD) - (BE); (CE) - (BF); (GF) - (AX)", time: "1H" },
  { task: "Alcohol free product & expiration date", comment: "For alcohol-free products, fill: Column NB with JA, Column NI with Expiration on Package, Column ND with 720 (2 years).", time: "3-5 min" },
  { task: "For alcohol-free products (alkoholfrei): Add ingredients in column IB", comment: "All alcohol-free wines and spirits must include the \"Ingredients (Zutaten)\" information in the Amazon file.", time: "" },
  { task: "Country", comment: "Mexico should be german Spelling = Mexiko, USA = Vereinigte Staaten, Schottland = Vereinigtes Königreich", time: "2 min" },
  { task: "For products from Israel: Ask Juliane to confirm", comment: "Amazon does not allow products from Israel.", time: "" },
  { task: "Check for the versluss (cap/closure) of wein (FC column)", comment: "If it's missing, search for it on the website.", time: "10 min" },
  { task: "Change Beschreibung with Story", comment: "Copy the text from the Story section (BC) into the Description field (I), but do not remove the 'Inverkehrbringer/Hersteller:' part at the end.", time: "1 H" },
  { task: "Verkaufsvolumen and Flüssigkeitsvolumen Should be displayed at 0.357 l with 0.38 l", comment: "(Column HE)= 0,38 (Column HL)= 0,38", time: "5 min" },
  { task: "If it is Magnum (1.5 liters) only create 01. This is only for MAGNUM!", comment: "Leave only parent and 01", time: "1 H" },
  { task: "Where there is 'Bio' in column IH, add 'bio' at the end after the article number", comment: "Filter bio in Article Number, then filter country, and in product name replace country with BIO+Country. EXAMPLE: \"Italien\" with \"BIO Italien\"", time: "2 H" },
  { task: "Check if a product includes 2 or more bottles.", comment: "If it does, keep only the parent and 01 children", time: "30 min" },
  { task: "If the product is in a can (dose), delete the whole product", comment: "They don't sell cans (dose).", time: "10 min" },
  { task: "Holzkiste Products", comment: "For products with wooden box, check their photos. If the photo shows the wooden box, replace it with a photo with a white background.", time: "2.5 H" },
  { task: "For \"Bag in Box\" products: Delete the entire product", comment: "These are not sold on Amazon.", time: "" },
  { task: "Delete the products - the entire item - when a product has no photo.", comment: "", time: "5 min" },
  { task: "Delete products that have the same article number and more than 1.5 liters on column (CK)", comment: "", time: "2 H" },
  { task: "Check if have duplicate on product name", comment: "Check for name in wein wolf website and in excel file produkt daten ohne filter", time: "1.5 H" },
  { task: "No more than one space", comment: "", time: "" },
  { task: "For alcohol free product fill column (IS) (Alkoholgehalt) 0.01%", comment: "", time: "2-3 min" },
  { task: "Marke/ Hersteller", comment: "Marke and Hersteller name is always FeinWert (column C and column H)", time: "1 min" },
  { task: "Check if there are any products on Amazon (Inventory) that are identical to any product in our list.", comment: "Delete the product on Amazon if it does not include the Inkl. Feinwert Ebook and 4 variations.", time: "2.5 H" },
  { task: "Delete the first 5 rows that are examples and created sheets.", comment: "", time: "1 min" },
  { task: "Upload Spreadsheet on Amazon", comment: "If there are no duplicates, upload our final list to Amazon.", time: "5 min" },
  { task: "Fix errors after 24 hours, after the list uploaded", comment: "", time: "2.5-3 H" },
]

const VS_VL_IMAGES_CHECKLIST_ITEMS: VsVlChecklistRow[] = [
  { task: "Save Photos in Separate Folders", comment: "Path: V:\\20_VS\\99_TEMPLATE\\PICTURE. Use python download_photo_vs.py to open the Excel Product Folder Automator app.", time: "20 min" },
  { task: "Special Case – When the photos are saved as JPG or PNG files and not in Excel", comment: "Path: V:\\20_VS\\99_TEMPLATE\\PICTURE. Use python photo_organizer.py to open the Excel Organizer Pro.", time: "10 min" },
  { task: "Generate Photos for Quantities 1, 3, 6, 12", comment: "Path: V:\\20_VS\\99_TEMPLATE\\PICTURE. Use python VS_IMAGE_GENERATOR_BIG_BOTTLE.py to open the Chic Bottle Grid Generator.", time: "20 min" },
  { task: "Generate URLs for Each Quantity", comment: "Path: V:\\20_VS\\99_TEMPLATE\\PICTURE. Use python url_generator.py to open LinkGen Pro. Create folder on Remote Desktop 65.", time: "30 min - 1H" },
  { task: "Connect URLs with Article Numbers", comment: "VBA për kodet nga URL - GJENERAL", time: "10-15 min" },
]

// Dreamrobot Phase Checklists
const VS_VL_DREAMROBOT_VS_CHECKLIST_PATH = "VS_VL_DREAMROBOT_VS_CHECKLIST"
const VS_VL_DREAMROBOT_VL_CHECKLIST_PATH = "VS_VL_DREAMROBOT_VL_CHECKLIST"

const VS_VL_DREAMROBOT_VS_CHECKLIST_ITEMS: VsVlChecklistRow[] = [
  { task: "DREAMROBOT", comment: "Filter the Amazon Template product list to include only child products with quantities 01, 03, 06, and 12. Move these filtered products into the DreamRobot template. After that, get the ASINs from SellerCentralAmazon (Reports). Once the Excel file is ready, import it into DreamRobot using LAGER IMPORT NEU MIT GEWICHT.", time: "2.5 H" },
  { task: "Weight", comment: "Take the weight from Produktdaten (the Gewicht column) and paste it into the weight_calculation file: V:\\20_VS\\0_TEMPLATE\\GENERAL", time: "30 min - 1 H" },
  { task: "Checking for duplicates on DreamRobot Manually", comment: "After posting the list in DreamRobot, export the report and use filters to find the duplicates marked in red. Then, manually delete only the duplicate products that begin with 01-, 03-, 06-, or 12-. Keep the products that end with -01, -03, -06, or -12 and connect them with our products.", time: "2-3 H" },
  { task: "Export Product List", comment: "Export all articles using \"Export Stücklisten-Sets\" in DreamRobot. Select 5000 items per file, and open the latest file.", time: "2 min" },
  { task: "Fill the DreamRobot Template\nPath: Y:\\20_VS\\99_TEMPLATE\\DREAMROBOT\n\nImport DR Stückliste VS_Template_18.08.2025", comment: "Fill the template like this:\n- Column A: lager_nr\n- Column B: set_article (values: :3, :6, :12)\n- Columns C and D: Always the same values (1, 24765)\n- Column E: Always 12 4 4 4 (So the pattern is always 12 for 1, and 4 for 3/6/12)\n\nUse the example in the template and replace it with your actual data.\n\nMake sure the article number is shown in column H (as a reference). Then separate the quantity in column G.\n\nIn column A you have the codes, while in column G you have the values, and the logic is this: whenever G shows 1, the corresponding cell in column B remains empty but the code from column A of that row is taken as the base for the following rows, and when G shows 3 or 6 or 12, column B is filled with the base code taken from column A plus \":3\" or \":6\" or \":12\" depending on the value in G, while if G is blank then B also stays blank.\n\nAlso, make sure to adjust the set_article values in column B to match only the quantities that are available for that product (e.g. :3, :6 if only 03 and 06 exist)", time: "2.5 H" },
  { task: "Delete column G and H", comment: "After checking, delete columns G and H, because they are only used as a reference.", time: "1 min" },
  { task: "Import into DreamRobot", comment: "Import the finished Excel file into DreamRobot using Import Stücklisten Sets.", time: "1-2 min" },
  { task: "Export Stücklisten-Sets", comment: "Make sure that the connections of parent and children is done", time: "5-10 min" },
]

const VS_VL_DREAMROBOT_VL_CHECKLIST_ITEMS: VsVlChecklistRow[] = [
  { task: "Fill Amazon Listing Loader Template", comment: "Template path: V:\\26_VL\\4_TEMPLATES\\AMAZON\n\"Listing loader Riegel spirit_VL\"\n\nFill with:\nSKU = Artikel Nr. from Visando\nPrice = same as Visando\nQuantity = 12, 4, 4, 4\nASIN = from Visando report\nColumn E: (\"asin\")= always default\nColumn F (\"neu\") = always default\nLeave all other columns empty\n!!!Parents not included - only children", time: "30 min" },
  { task: "Dream Robot (DR)", comment: "Take the existing file from Visando and rename it to VS.\n-Remove \"inkl. FeinWert E-Book\" from product names.\n-Adapt prices in column H (vk_preis):\n01 → minus 0.5\n03 → minus 1\n06 → minus 1\n12 → minus 2\n-Change ID and Nr of the Deliverer (find correct values in Lieferanten on DreamRobot)\n-links for photos must be filled in (columns AC, AD) - Use VLOOKUP to connect columns AC and AD with the Amazon list created for Visando. At the end, check for N/A → delete those rows.\n-link ASINs via VLOOKUP - In column P, connect with VLOOKUP to fetch ASINs from Visando report: V:\\26_VL\\4_TEMPLATES\\AMAZON\\All+Listings+Report+09-10-2025. Filter results → delete all rows with N/A.\n-Check Product Names (HK / Holzkiste) - If the name contains HK or Holzkiste, delete that part from the name.\n-Check Product Names (Magnum) - If the name contains (12 x 1.5l) → delete these products completely (they are magnum bottles - only 12 quantity, 01,03,06 do not delete!!!)\n-If strange characters appear - Import via Data - From Text/CSV - Code 10000 (check carefully if changes apply)", time: "1.2 H" },
  { task: "Import list into DreamRobot", comment: "Import it into DreamRobot using LAGER IMPORT NEU MIT GEWICHT", time: "1-2 min" },
  { task: "Checking for duplicates on DreamRobot Manually", comment: "After posting the list in DreamRobot, export the report and use filters to find the duplicates marked in red. Then, delete the duplicate products manually from DreamRobot.", time: "2-3 H" },
  { task: "Export Product List", comment: "Export all articles using \"Export Stücklisten-Sets\" in DreamRobot. Select 5000 items per file, and open the latest file.", time: "1 min" },
  { task: "Fill the DreamRobot Template\nPath: Y:\\20_VS\\99_TEMPLATE\\DREAMROBOT\n\nImport DR Stückliste Visando_Template_18.08.2025", comment: "Fill the template like this:\n- Column A: lager_nr\n- Column B: set_article (values: :3, :6, :12)\n- Columns C and D: Always the same values (1, 8942)\n- Column E: Always 12 4 4 4 (So the pattern is always 12 for 1, and 4 for 3/6/12)\n\nUse the example in the template and replace it with your actual data.\n\nMake sure the article number is shown in column H (as a reference). Then separate the quantity in column G.\n\nIn column A you have the codes, while in column G you have the values, and the logic is this: whenever G shows 1, the corresponding cell in column B remains empty but the code from column A of that row is taken as the base for the following rows, and when G shows 3 or 6 or 12, column B is filled with the base code taken from column A plus \":3\" or \":6\" or \":12\" depending on the value in G, while if G is blank then B also stays blank.\n\nAlso, make sure to adjust the set_article values in column B to match only the quantities that are available for that product (e.g. :3, :6 if only 03 and 06 exist)", time: "2.5 H" },
  { task: "Delete column G and H", comment: "After checking, delete columns G and H, because they are only used as a reference.", time: "1 min" },
  { task: "Import into DreamRobot", comment: "Import the finished Excel file into DreamRobot using Import Stücklisten Sets.", time: "1 min" },
  { task: "Export Stücklisten-Sets", comment: "Make sure that the connections of parent and children is done", time: "5-10 min" },
]

function findVsVlTask(tasks: Task[], titleKey: string) {
  return tasks.find((task) => normalizeTaskTitle(task.title) === titleKey)
}

export default function PcmProjectPage() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const projectId = String(params.id)
  const { apiFetch, user } = useAuth()
  const confirm = useConfirm()
  const confirmDeleteTask = React.useCallback(
    () =>
      confirm({
        title: "Delete task",
        description: "Are you sure you want to delete this task?",
        confirmLabel: "Delete",
        variant: "destructive",
      }),
    [confirm]
  )

  const [project, setProject] = React.useState<Project | null>(null)
  const [tasks, setTasks] = React.useState<Task[]>([])
  const [departmentUsers, setDepartmentUsers] = React.useState<User[]>([])
  const [allUsers, setAllUsers] = React.useState<User[]>([])
  const [members, setMembers] = React.useState<User[]>([])
  const [checklistItems, setChecklistItems] = React.useState<ChecklistItem[]>([])
  const hasIncompleteChecklist = React.useMemo(
    () => checklistItems.some((item) => item.item_type === "CHECKBOX" && !item.is_checked),
    [checklistItems]
  )
  const [initialDataLoaded, setInitialDataLoaded] = React.useState(false)
  const [gaNotes, setGaNotes] = React.useState<GaNote[]>([])
  const [prompts, setPrompts] = React.useState<ProjectPrompt[]>([])
  const [meetings, setMeetings] = React.useState<Meeting[]>([])
  const [activeTab, setActiveTab] = React.useState<TabId>("description")
  const [newChecklistContent, setNewChecklistContent] = React.useState("")
  const [addingChecklist, setAddingChecklist] = React.useState(false)
  const [createOpen, setCreateOpen] = React.useState(false)
  const [newTitle, setNewTitle] = React.useState("")
  const [newDescription, setNewDescription] = React.useState("")
  const [newStatus, setNewStatus] = React.useState<Task["status"]>("TODO")
  const [pendingStatusTaskId, setPendingStatusTaskId] = React.useState<string | null>(null)
  const [pendingStatusValue, setPendingStatusValue] = React.useState<Task["status"]>("TODO")
  const [pendingConfirmationAssigneeId, setPendingConfirmationAssigneeId] = React.useState("")
  const [newTaskType, setNewTaskType] = React.useState<(typeof PROJECT_TASK_TYPES)[number]>("NORMAL")
  const [newAssignedTo, setNewAssignedTo] = React.useState<string>("__unassigned__")
  const [newTaskPhase, setNewTaskPhase] = React.useState<string>("")
  const [newDueDate, setNewDueDate] = React.useState("")
  const [creating, setCreating] = React.useState(false)
  const [editingDescription, setEditingDescription] = React.useState("")
  const [savingDescription, setSavingDescription] = React.useState(false)
  const [membersOpen, setMembersOpen] = React.useState(false)
  const [selectedMemberIds, setSelectedMemberIds] = React.useState<string[]>([])
  const [savingMembers, setSavingMembers] = React.useState(false)
  const [advancingPhase, setAdvancingPhase] = React.useState(false)
  const [viewedPhase, setViewedPhase] = React.useState<string | null>(null)
  const canCloseProject = user?.role === "ADMIN" || user?.role === "MANAGER"
  const [closeConfirmOpen, setCloseConfirmOpen] = React.useState(false)
  const [pendingCloseSource, setPendingCloseSource] = React.useState<"mst" | "vsvl" | null>(null)
  const mstCommentTimersRef = React.useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  const vsVlDescriptionTimersRef = React.useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  const vsVlMetaTimersRef = React.useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  const [newGaNote, setNewGaNote] = React.useState("")
  const [newGaNoteType, setNewGaNoteType] = React.useState("GA")
  const [newGaNotePriority, setNewGaNotePriority] = React.useState<"__none__" | "NORMAL" | "HIGH">("__none__")
  const [addingGaNote, setAddingGaNote] = React.useState(false)
  const [meetingChecklist, setMeetingChecklist] = React.useState<
    { id: string; content: string; answer: string; isChecked: boolean; position: number }[]
  >([])
  const [newMeetingItemContent, setNewMeetingItemContent] = React.useState("")
  const [newMeetingItemAnswer, setNewMeetingItemAnswer] = React.useState("")
  const [addingMeetingItem, setAddingMeetingItem] = React.useState(false)
  const [editingMeetingItemId, setEditingMeetingItemId] = React.useState<string | null>(null)
  const [editingMeetingItemContent, setEditingMeetingItemContent] = React.useState("")
  const [editingMeetingItemAnswer, setEditingMeetingItemAnswer] = React.useState("")
  const [documentationChecklist, setDocumentationChecklist] = React.useState(() =>
    DOCUMENTATION_CHECKLIST_QUESTIONS.map((question, index) => ({
      id: `doc-${index}`,
      question,
      isChecked: false,
    }))
  )
  const [documentationFilePath, setDocumentationFilePath] = React.useState("")
  const [documentationFilePaths, setDocumentationFilePaths] = React.useState<string[]>([])
  const [gaPromptContent, setGaPromptContent] = React.useState("")
  const [devPromptContent, setDevPromptContent] = React.useState("")
  const [savingGaPrompt, setSavingGaPrompt] = React.useState(false)
  const [savingDevPrompt, setSavingDevPrompt] = React.useState(false)
  const [editProjectDueDateOpen, setEditProjectDueDateOpen] = React.useState(false)
  const [editProjectDueDate, setEditProjectDueDate] = React.useState("")
  const [savingProjectDueDate, setSavingProjectDueDate] = React.useState(false)
  const [isEditingProjectTitle, setIsEditingProjectTitle] = React.useState(false)
  const [projectTitleDraft, setProjectTitleDraft] = React.useState("")
  const [savingProjectTitle, setSavingProjectTitle] = React.useState(false)
  const [startDateDialogOpen, setStartDateDialogOpen] = React.useState(false)
  const [editStartDateDialogOpen, setEditStartDateDialogOpen] = React.useState(false)
  const [selectedStartDate, setSelectedStartDate] = React.useState("")
  const [savingStartDate, setSavingStartDate] = React.useState(false)
  const isAdmin = user?.role === "ADMIN"
  const isManager = user?.role === "MANAGER"
  const canEditDueDate = isAdmin || isManager
  const canEditProjectTitle = Boolean(user)

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

  // Sync the start date when dialog opens
  React.useEffect(() => {
    if (startDateDialogOpen) {
      // Default to today's date if no start date is set
      const defaultDate = project?.start_date ? toDateInput(project.start_date) : toDateInput(new Date().toISOString())
      setSelectedStartDate(defaultDate)
    }
  }, [startDateDialogOpen, project?.start_date])

  // Sync the start date when edit dialog opens
  React.useEffect(() => {
    if (editStartDateDialogOpen && project?.start_date) {
      setSelectedStartDate(toDateInput(project.start_date))
    }
  }, [editStartDateDialogOpen, project?.start_date])

  // Dialog component for editing project due date
  const renderEditDueDateDialog = () => (
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
  )

  // Dialog component for setting project start date
  const renderStartDateDialog = () => (
    <Dialog open={startDateDialogOpen} onOpenChange={setStartDateDialogOpen}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Set Project Start Date</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Start Date</Label>
            <Input
              type="date"
              value={selectedStartDate}
              onChange={(e) => setSelectedStartDate(normalizeDueDateInput(e.target.value))}
            />
            <p className="text-xs text-muted-foreground">
              All task dates will be calculated automatically based on this start date.
            </p>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setStartDateDialogOpen(false)} disabled={savingStartDate}>
              Cancel
            </Button>
            <Button
              disabled={savingStartDate || !selectedStartDate.trim()}
              onClick={async () => {
                if (!project || !selectedStartDate.trim()) return
                setSavingStartDate(true)
                try {
                  const startDateValue = new Date(selectedStartDate).toISOString()
                  const res = await apiFetch(`/projects/${project.id}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ start_date: startDateValue }),
                  })
                  if (!res.ok) {
                    toast.error("Failed to set project start date")
                    return
                  }
                  const updated = (await res.json()) as Project
                  setProject(updated)
                  setStartDateDialogOpen(false)
                  toast.success("Project start date set! Task dates will be calculated automatically.")
                } catch (err) {
                  console.error("Failed to set project start date", err)
                  toast.error("Failed to set project start date")
                } finally {
                  setSavingStartDate(false)
                }
              }}
            >
              {savingStartDate ? "Saving..." : "Set Start Date"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )

  // Dialog component for editing project start date (admin only)
  const renderEditStartDateDialog = () => (
    <Dialog open={editStartDateDialogOpen} onOpenChange={setEditStartDateDialogOpen}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Edit Project Start Date</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Start Date</Label>
            <Input
              type="date"
              value={selectedStartDate}
              onChange={(e) => setSelectedStartDate(normalizeDueDateInput(e.target.value))}
            />
            <p className="text-xs text-muted-foreground">
              All task dates will be recalculated automatically based on this start date.
            </p>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setEditStartDateDialogOpen(false)} disabled={savingStartDate}>
              Cancel
            </Button>
            <Button
              disabled={savingStartDate || !selectedStartDate.trim()}
              onClick={async () => {
                if (!project || !selectedStartDate.trim()) return
                setSavingStartDate(true)
                try {
                  const startDateValue = new Date(selectedStartDate).toISOString()
                  const res = await apiFetch(`/projects/${project.id}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ start_date: startDateValue }),
                  })
                  if (!res.ok) {
                    toast.error("Failed to update project start date")
                    return
                  }
                  const updated = (await res.json()) as Project
                  setProject(updated)
                  setEditStartDateDialogOpen(false)
                  toast.success("Project start date updated! Task dates will be recalculated automatically.")
                } catch (err) {
                  console.error("Failed to update project start date", err)
                  toast.error("Failed to update project start date")
                } finally {
                  setSavingStartDate(false)
                }
              }}
            >
              {savingStartDate ? "Saving..." : "Save"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )

  const renderCloseConfirmDialog = () => (
    <Dialog open={closeConfirmOpen} onOpenChange={setCloseConfirmOpen}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Close Project?</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            This will close the {pendingCloseSource === "vsvl" ? "VS/VL project" : "project"} and return you to the
            Project Content Manager list.
          </p>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setCloseConfirmOpen(false)}
              disabled={advancingPhase}
            >
              Cancel
            </Button>
            <Button type="button" onClick={() => void confirmCloseProject()} disabled={advancingPhase}>
              {advancingPhase ? "Closing..." : "Close Project"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
  const [mstPhase, setMstPhase] = React.useState<(typeof MST_PHASES)[number]>("PLANNING")
  const [vsVlPhase, setVsVlPhase] = React.useState<(typeof VS_VL_PHASES)[number]>("PLANNING")
  const [vsVlTab, setVsVlTab] = React.useState<"description" | "tasks" | "checklists" | "workflow" | "ga">("description")
  const [vsVlChecklistTab, setVsVlChecklistTab] = React.useState<"amazon" | "images">("amazon")
  const [exportingVsVlChecklist, setExportingVsVlChecklist] = React.useState(false)
  const [exportingMstChecklist, setExportingMstChecklist] = React.useState(false)
  const [vsVlDreamrobotChecklistTab, setVsVlDreamrobotChecklistTab] = React.useState<"vs" | "vl">("vs")
  const [mstChecklistChecked, setMstChecklistChecked] = React.useState<Record<string, boolean>>({})
  const [mstChecklistComments, setMstChecklistComments] = React.useState<Record<string, string>>({})
  const [mstTemplateChecklist, setMstTemplateChecklist] = React.useState<ChecklistWithItems | null>(null)
  const [loadingMstTemplate, setLoadingMstTemplate] = React.useState(false)
  const [initializingMstTemplate, setInitializingMstTemplate] = React.useState(false)
  const [editingMstChecklistKey, setEditingMstChecklistKey] = React.useState<string | null>(null)
  const [editingMstChecklistRow, setEditingMstChecklistRow] = React.useState({
    number: "",
    path: "",
    detyrat: "",
    keywords: "",
    pershkrimi: "",
    kategoria: "",
    original: "",
    incl: "DV, DM",
  })
  const [newMstChecklistRow, setNewMstChecklistRow] = React.useState({
    number: "",
    path: "",
    detyrat: "",
    keywords: "",
    pershkrimi: "",
    kategoria: "",
    original: "",
    incl: "DV, DM",
  })
  const [savingMstChecklistRow, setSavingMstChecklistRow] = React.useState(false)
  const [viewingChecklistField, setViewingChecklistField] = React.useState<{ key: string; field: string; value: string; label: string } | null>(null)
  const [mstPlanningChecks, setMstPlanningChecks] = React.useState<Record<string, boolean>>({})
  const [descriptionChecks, setDescriptionChecks] = React.useState<Record<string, boolean>>({})
  const [planningComments, setPlanningComments] = React.useState<Record<string, string>>({})
  const [editingPlanningItemId, setEditingPlanningItemId] = React.useState<string | null>(null)
  const [editingPlanningItemText, setEditingPlanningItemText] = React.useState("")
  const [editingPlanningItemNumber, setEditingPlanningItemNumber] = React.useState("")
  const [savingPlanningItem, setSavingPlanningItem] = React.useState(false)
  const [newPlanningItemNumber, setNewPlanningItemNumber] = React.useState("")
  const [newPlanningItemText, setNewPlanningItemText] = React.useState("")
  const [addingPlanningItem, setAddingPlanningItem] = React.useState(false)
  const [vsVlAcceptanceChecks, setVsVlAcceptanceChecks] = React.useState<Record<string, boolean>>({})
  const [vsVlPlanningItems, setVsVlPlanningItems] = React.useState<ChecklistItem[]>([])
  const [editingVsVlPlanningId, setEditingVsVlPlanningId] = React.useState<string | null>(null)
  const [editingVsVlPlanningText, setEditingVsVlPlanningText] = React.useState("")
  const [newVsVlPlanningText, setNewVsVlPlanningText] = React.useState("")
  const [savingVsVlPlanning, setSavingVsVlPlanning] = React.useState(false)
  const [vsVlTaskTitle, setVsVlTaskTitle] = React.useState("")
  const [vsVlTaskDetail, setVsVlTaskDetail] = React.useState("")
  const [vsVlTaskDate, setVsVlTaskDate] = React.useState("")
  const [vsVlTaskDeadlineImportant, setVsVlTaskDeadlineImportant] = React.useState(false)
  const [vsVlTaskPriority, setVsVlTaskPriority] = React.useState<TaskPriority>("NORMAL")
  const [vsVlTaskStatus, setVsVlTaskStatus] = React.useState<Task["status"]>("TODO")
  const [vsVlTaskAssignees, setVsVlTaskAssignees] = React.useState<string[]>([])
  const [vsVlTaskDependencyId, setVsVlTaskDependencyId] = React.useState("__none__")
  const [vsVlTaskChecklist, setVsVlTaskChecklist] = React.useState("")
  const [vsVlTaskComment, setVsVlTaskComment] = React.useState("")
  const [vsVlCommentEdits, setVsVlCommentEdits] = React.useState<Record<string, string>>({})
  const [vsVlChecklistEdits, setVsVlChecklistEdits] = React.useState<Record<string, string>>({})
  const [vsVlDescriptionEdits, setVsVlDescriptionEdits] = React.useState<Record<string, string>>({})
  const [vsVlAssigneeOpen, setVsVlAssigneeOpen] = React.useState<Record<string, boolean>>({})
  const [vsVlEditMode, setVsVlEditMode] = React.useState<Record<string, boolean>>({})
  const [vsVlAmazonCommentEdits, setVsVlAmazonCommentEdits] = React.useState<Record<string, string>>({})
  const [showVsVlAddTask, setShowVsVlAddTask] = React.useState(false)
  const [newVsVlDreamrobotRow, setNewVsVlDreamrobotRow] = React.useState({
    task: "",
    comment: "",
    time: "",
  })
  // VS/VL Checklist CRUD state
  const [newVsVlAmazonRow, setNewVsVlAmazonRow] = React.useState({
    task: "",
    comment: "",
    time: "",
    ko2: false,
  })
  const [newVsVlImagesRow, setNewVsVlImagesRow] = React.useState({ task: "", comment: "", time: "" })
  const [savingVsVlChecklist, setSavingVsVlChecklist] = React.useState(false)
  const [editingVsVlChecklistId, setEditingVsVlChecklistId] = React.useState<string | null>(null)
  const [editingVsVlChecklistRow, setEditingVsVlChecklistRow] = React.useState({ task: "", comment: "", time: "" })
  const [creatingVsVlTask, setCreatingVsVlTask] = React.useState(false)
  const [mstTab, setMstTab] = React.useState<"description" | "tasks" | "checklists" | "members" | "ga" | "final">(
    "description"
  )
  const [newMemberId, setNewMemberId] = React.useState<string>("")
  // Inline task form state for Produkte phase
  const [newInlineTaskTitle, setNewInlineTaskTitle] = React.useState("")
  const [newInlineTaskAssignee, setNewInlineTaskAssignee] = React.useState<string>("__unassigned__")
  const [newInlineTaskStartDate, setNewInlineTaskStartDate] = React.useState("")
  const [newInlineTaskDueDate, setNewInlineTaskDueDate] = React.useState("")
  const [newInlineTaskDeadlineImportant, setNewInlineTaskDeadlineImportant] = React.useState(false)
  const [newInlineTaskFinishPeriod, setNewInlineTaskFinishPeriod] = React.useState<
    TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE
  >(FINISH_PERIOD_NONE_VALUE)
  const [newInlineTaskTotal, setNewInlineTaskTotal] = React.useState("")
  const [newInlineTaskCompleted, setNewInlineTaskCompleted] = React.useState("")
  const [creatingInlineTask, setCreatingInlineTask] = React.useState(false)
  // Finalizimi checklist state
  const [finalizationChecks, setFinalizationChecks] = React.useState<Record<string, boolean>>({})
  const [finalizationItems, setFinalizationItems] = React.useState<ChecklistItem[]>([])
  const [editingFinalizationId, setEditingFinalizationId] = React.useState<string | null>(null)
  const [editingFinalizationText, setEditingFinalizationText] = React.useState("")
  const [editingFinalizationNumber, setEditingFinalizationNumber] = React.useState("")
  const [newFinalizationNumber, setNewFinalizationNumber] = React.useState("")
  const [newFinalizationText, setNewFinalizationText] = React.useState("")
  const [savingFinalization, setSavingFinalization] = React.useState(false)
  const [controlEdits, setControlEdits] = React.useState<
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
  const [editingTaskId, setEditingTaskId] = React.useState<string | null>(null)
  const [editingTaskTitle, setEditingTaskTitle] = React.useState("")
  const [editingTaskAssignee, setEditingTaskAssignee] = React.useState<string>("__unassigned__")
  const [editingTaskKoUserId, setEditingTaskKoUserId] = React.useState<string>("__unassigned__")
  const [editingTaskStartDate, setEditingTaskStartDate] = React.useState("")
  const [editingTaskDueDate, setEditingTaskDueDate] = React.useState("")
  const [editingTaskFinishPeriod, setEditingTaskFinishPeriod] = React.useState<
    TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE
  >(FINISH_PERIOD_NONE_VALUE)
  const [editingTaskTotal, setEditingTaskTotal] = React.useState("")
  const [editingTaskCompleted, setEditingTaskCompleted] = React.useState("")
  const [editingTaskProductionDate, setEditingTaskProductionDate] = React.useState("")
  const [savingTaskEdit, setSavingTaskEdit] = React.useState(false)
  const mstChecklistScrollRef = React.useRef<HTMLDivElement | null>(null)
  const mstChecklistDragRef = React.useRef({
    active: false,
    startX: 0,
    startScrollLeft: 0,
  })

  React.useEffect(() => {
    const load = async () => {
      const pRes = await apiFetch(`/projects/${projectId}`)
      if (!pRes.ok) return
      const p = (await pRes.json()) as Project
      setProject(p)
      setEditingDescription(p.description || "")
      const pTitleUpper = (p.title || p.name || "").toUpperCase()
      const isTtProject = isTtProjectTitle(pTitleUpper)
      const productTemplateGroupKey = isTtProject ? TT_PRODUCT_TEMPLATE_GROUP_KEY : MST_PRODUCT_TEMPLATE_GROUP_KEY
      const fallbackProductTemplateGroupKey = isTtProject ? MST_PRODUCT_TEMPLATE_GROUP_KEY : null
      const shouldLoadMstTemplate = isMstOrTtProject(p)

      const [tRes, mRes, cRes, gRes, prRes, usersRes, meetingsRes, mstTemplateRes, fallbackMstTemplateRes] = await Promise.all([
        apiFetch(`/tasks?project_id=${p.id}&include_done=true`),
        apiFetch(`/project-members?project_id=${p.id}`),
        apiFetch(`/checklist-items?project_id=${p.id}`),
        apiFetch(`/ga-notes?project_id=${p.id}`),
        apiFetch(`/project-prompts?project_id=${p.id}`),
        apiFetch("/users?include_all_departments=true"),
        apiFetch(`/meetings?project_id=${p.id}`),
        shouldLoadMstTemplate
          ? apiFetch(`/checklists?template_only=true&group_key=${encodeURIComponent(productTemplateGroupKey)}`)
          : Promise.resolve(null),
        fallbackProductTemplateGroupKey
          ? apiFetch(`/checklists?template_only=true&group_key=${encodeURIComponent(fallbackProductTemplateGroupKey)}`)
          : Promise.resolve(null),
      ])
      let loadedMstTemplate: ChecklistWithItems | null = null

      if (mstTemplateRes && "ok" in mstTemplateRes && mstTemplateRes.ok) {
        const templates = (await mstTemplateRes.json()) as ChecklistWithItems[]
        loadedMstTemplate = templates[0] || null
      }
      if (!loadedMstTemplate && fallbackMstTemplateRes && "ok" in fallbackMstTemplateRes && fallbackMstTemplateRes.ok) {
        const templates = (await fallbackMstTemplateRes.json()) as ChecklistWithItems[]
        loadedMstTemplate = templates[0] || null
      }
      if (loadedMstTemplate || shouldLoadMstTemplate) {
        setMstTemplateChecklist(loadedMstTemplate)
      }

      if (tRes.ok) setTasks((await tRes.json()) as Task[])
      if (mRes.ok) setMembers((await mRes.json()) as User[])
      if (cRes.ok) {
        const items = (await cRes.json()) as ChecklistItem[]
        setChecklistItems(items)

        try {
          if (isVsVlProject(p)) {
            const hasVsVlItems = items.some(
              (item) => item.item_type === "CHECKBOX" && item.path === "VS_VL_PLANNING"
            )
            if (!hasVsVlItems) {
              await initializeVsVlPlanningItems(p.id, items, apiFetch)
              const reloadRes = await apiFetch(`/checklist-items?project_id=${p.id}`)
              if (reloadRes.ok) {
                setChecklistItems((await reloadRes.json()) as ChecklistItem[])
              }
            }
          }

          // Initialize MST checklist items only if none exist yet
          if (isMstOrTtProject(p)) {
            const hasMstItems = items.some((item) => {
              if (item.item_type !== "CHECKBOX") return false
              if (!item.path || !item.title) return false
              return !MST_EXCLUDED_PATHS.has(item.path)
            })
            if (!hasMstItems) {
              const templateRows = loadedMstTemplate
                ? checklistItemsToMstTemplateRows(loadedMstTemplate.items || [])
                : isTtProject
                  ? DEFAULT_TT_PRODUCT_TEMPLATE_ROWS
                  : DEFAULT_MST_PRODUCT_TEMPLATE_ROWS
              await initializeMstChecklistItems(p.id, items, templateRows, apiFetch, false, !isTtProject)
              const reloadRes = await apiFetch(`/checklist-items?project_id=${p.id}`)
              if (reloadRes.ok) {
                setChecklistItems((await reloadRes.json()) as ChecklistItem[])
              }
            }
          }

          await initializeMeetingChecklistItems(p.id, items, apiFetch)
          const meetingReloadRes = await apiFetch(`/checklist-items?project_id=${p.id}`)
          if (meetingReloadRes.ok) {
            setChecklistItems((await meetingReloadRes.json()) as ChecklistItem[])
          }
        } catch (error) {
          console.error("Failed to initialize meeting checklist items:", error)
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
      if (isMstOrTtProject(p)) {
        setMstPhase(MST_PHASES[0])
      }
      if (isVsVlProject(p)) {
        setVsVlPhase(VS_VL_PHASES[0])
      }
      setInitialDataLoaded(true)
    }
    void load()
  }, [apiFetch, projectId])

  const reloadProjectTasks = React.useCallback(
    async (targetProjectId?: string) => {
      const id = targetProjectId || project?.id
      if (!id) return false
      const res = await apiFetch(`/tasks?project_id=${id}&include_done=true`)
      if (!res.ok) return false
      setTasks((await res.json()) as Task[])
      return true
    },
    [apiFetch, project?.id]
  )

  React.useEffect(() => {
    if (project?.current_phase) setViewedPhase(project.current_phase)
  }, [project?.current_phase])

  const isMst = React.useMemo(() => isMstOrTtProject(project), [project])
  const titleUpper = (project?.title || project?.name || "").toUpperCase()
  const isTtProject = isTtProjectTitle(titleUpper)
  const isMstLike = isMst || isTtProject
  const productChecklistLabel = isTtProject ? "TT" : "MST"
  const productTemplateGroupKey = isTtProject ? TT_PRODUCT_TEMPLATE_GROUP_KEY : MST_PRODUCT_TEMPLATE_GROUP_KEY
  const defaultProductTemplateRows = isTtProject ? DEFAULT_TT_PRODUCT_TEMPLATE_ROWS : DEFAULT_MST_PRODUCT_TEMPLATE_ROWS
  const showMstOriginalColumn = !isTtProject
  const mstChecklistGridClass = showMstOriginalColumn
    ? "grid-cols-[42px_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.8fr)_minmax(0,0.8fr)_minmax(0,1.35fr)_minmax(0,1.35fr)_minmax(0,1.25fr)_minmax(0,1.25fr)_minmax(0,0.65fr)_minmax(0,0.75fr)_minmax(0,1fr)_minmax(0,1fr)_72px]"
    : "grid-cols-[42px_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.8fr)_minmax(0,0.8fr)_minmax(0,1.4fr)_minmax(0,1.4fr)_minmax(0,1.25fr)_minmax(0,0.65fr)_minmax(0,0.75fr)_minmax(0,1fr)_minmax(0,1fr)_72px]"
  const isMstTemplateEditor = React.useMemo(
    () => Boolean(project?.is_template && isMstLike && (user?.role === "ADMIN" || user?.role === "MANAGER")),
    [isMstLike, project?.is_template, user?.role]
  )
  const mstTemplateRows = React.useMemo(
    () => (mstTemplateChecklist ? checklistItemsToMstTemplateRows(mstTemplateChecklist.items || []) : defaultProductTemplateRows),
    [defaultProductTemplateRows, mstTemplateChecklist]
  )
  const templateOrderMap = React.useMemo(() => buildMstTemplateOrderMap(mstTemplateRows), [mstTemplateRows])
  const planningItems = React.useMemo(
    () => checklistItems.filter((item) => item.item_type === "CHECKBOX" && item.path === "PLANNING"),
    [checklistItems]
  )
  const planningItemsOrdered = React.useMemo(() => {
    if (!planningItems.length) return []
    return planningItems
      .slice()
      .sort((a, b) => {
        const posA = a.position ?? Number.MAX_SAFE_INTEGER
        const posB = b.position ?? Number.MAX_SAFE_INTEGER
        if (posA !== posB) return posA - posB
        const orderA = getMstPlanningOrder(a)
        const orderB = getMstPlanningOrder(b)
        if (orderA !== orderB) return orderA - orderB
        return (a.title || "").localeCompare(b.title || "")
      })
  }, [planningItems])
  const mstChecklistItems = React.useMemo(() => {
    return checklistItems.filter((item) => {
      if (item.item_type !== "CHECKBOX") return false
      if (!item.path || !item.title) return false
      return !MST_EXCLUDED_PATHS.has(item.path)
    })
  }, [checklistItems])
  const loadMstTemplateChecklist = React.useCallback(async () => {
    setLoadingMstTemplate(true)
    try {
      const res = await apiFetch(
        `/checklists?template_only=true&group_key=${encodeURIComponent(productTemplateGroupKey)}`
      )
      if (!res.ok) {
        setMstTemplateChecklist(null)
        return null
      }
      const templates = (await res.json()) as ChecklistWithItems[]
      const checklist = templates[0] || null
      setMstTemplateChecklist(checklist)
      return checklist
    } catch (error) {
      console.error("Failed to load MST template checklist:", error)
      setMstTemplateChecklist(null)
      return null
    } finally {
      setLoadingMstTemplate(false)
    }
  }, [apiFetch, productTemplateGroupKey])

  const createMstTemplateFromDefaults = React.useCallback(async () => {
    if (user?.role !== "ADMIN" && user?.role !== "MANAGER") return null
    setInitializingMstTemplate(true)
    try {
      const createChecklistRes = await apiFetch("/checklists", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: `${productChecklistLabel} Product Checklist Template`,
          group_key: productTemplateGroupKey,
        }),
      })
      if (!createChecklistRes.ok) {
        toast.error(`Failed to create ${productChecklistLabel} template checklist`)
        return null
      }
      const checklist = (await createChecklistRes.json()) as ChecklistWithItems
      const existingTemplate = await loadMstTemplateChecklist()
      const templateChecklistId = existingTemplate?.id || checklist.id
      const rowsToCreate = defaultProductTemplateRows

      for (const [index, row] of rowsToCreate.entries()) {
        const itemRes = await apiFetch("/checklist-items", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            checklist_id: templateChecklistId,
            item_type: "CHECKBOX",
            path: row.path,
            title: row.detyrat,
            keyword: row.keywords,
            description: row.pershkrimi,
            category: row.kategoria,
            ...(showMstOriginalColumn ? { original: row.original || null } : {}),
            owner: row.incl,
            is_checked: false,
            position: index + 1,
          }),
        })
        if (!itemRes.ok) {
          toast.error(`Failed to add template row "${row.detyrat}"`)
          break
        }
      }

      const reloaded = await loadMstTemplateChecklist()
      if (reloaded) toast.success(`${productChecklistLabel} template initialized`)
      return reloaded
    } finally {
      setInitializingMstTemplate(false)
    }
  }, [apiFetch, defaultProductTemplateRows, loadMstTemplateChecklist, productChecklistLabel, productTemplateGroupKey, showMstOriginalColumn, user?.role])

  // Initialize MST checklist checked state and comments from database
  React.useEffect(() => {
    if (!isMst || !project) return

    const checked: Record<string, boolean> = {}
    const comments: Record<string, string> = {}
    mstChecklistItems.forEach((item) => {
      if (item.path && item.title) {
        const key = `${item.path}|${item.title}`
        checked[key] = item.is_checked || false
        if (item.comment) comments[key] = item.comment
      }
    })
    setMstChecklistChecked(checked)
    setMstChecklistComments(comments)

    const planningChecked: Record<string, boolean> = {}
    const descriptionChecked: Record<string, boolean> = {}
    const planningCommentsData: Record<string, string> = {}
    planningItems.forEach((item) => {
      planningChecked[item.id] = item.is_checked || false
      descriptionChecked[item.id] = item.is_checked || false
      if (item.comment) {
        planningCommentsData[item.id] = item.comment
      }
    })
    setMstPlanningChecks(planningChecked)
    setDescriptionChecks(descriptionChecked)
    setPlanningComments(planningCommentsData)

    const finalizationItemsFromDb = checklistItems.filter((item) => {
      return item.item_type === "CHECKBOX" && item.path === FINALIZATION_PATH
    })
    setFinalizationItems(finalizationItemsFromDb)

    if (finalizationItemsFromDb.length) {
      const finalizationData: Record<string, boolean> = {}
      finalizationItemsFromDb.forEach((item) => {
        // Use item ID as key for dynamic items
        finalizationData[item.id] = item.is_checked || false
      })
      setFinalizationChecks(finalizationData)
    }
  }, [checklistItems, isMst, planningItems, planningItemsOrdered, project])

  // Load VS/VL acceptance questions from database (separate from MST)
  const isVsVlForEffect = React.useMemo(() => isVsVlProject(project), [project])
  const vsVlAmazonChecklistItems = React.useMemo(
    () => {
      const filtered = checklistItems.filter(
        (item) => item.item_type === "CHECKBOX" && item.path === VS_VL_AMAZON_CHECKLIST_PATH
      )
      // Deduplicate by ID
      const seen = new Set<string>()
      return filtered.filter((item) => {
        if (seen.has(item.id)) return false
        seen.add(item.id)
        return true
      })
    },
    [checklistItems]
  )
  const vsVlImagesChecklistItems = React.useMemo(
    () => {
      const filtered = checklistItems.filter(
        (item) => item.item_type === "CHECKBOX" && item.path === VS_VL_IMAGES_CHECKLIST_PATH
      )
      // Deduplicate by ID
      const seen = new Set<string>()
      return filtered.filter((item) => {
        if (seen.has(item.id)) return false
        seen.add(item.id)
        return true
      })
    },
    [checklistItems]
  )
  const vsVlDreamrobotVsChecklistItems = React.useMemo(
    () => {
      const filtered = checklistItems.filter(
        (item) => item.item_type === "CHECKBOX" && item.path === VS_VL_DREAMROBOT_VS_CHECKLIST_PATH
      )
      const seen = new Set<string>()
      return filtered.filter((item) => {
        if (seen.has(item.id)) return false
        seen.add(item.id)
        return true
      })
    },
    [checklistItems]
  )
  const vsVlDreamrobotVlChecklistItems = React.useMemo(
    () => {
      const filtered = checklistItems.filter(
        (item) => item.item_type === "CHECKBOX" && item.path === VS_VL_DREAMROBOT_VL_CHECKLIST_PATH
      )
      const seen = new Set<string>()
      return filtered.filter((item) => {
        if (seen.has(item.id)) return false
        seen.add(item.id)
        return true
      })
    },
    [checklistItems]
  )
  React.useEffect(() => {
    if (!isVsVlForEffect || !project) return

    const vsVlAcceptanceItems = checklistItems.filter((item) => {
      return item.item_type === "CHECKBOX" && item.path === "VS_VL_PLANNING"
    })
    setVsVlPlanningItems(vsVlAcceptanceItems)
    const vsVlChecked: Record<string, boolean> = {}
    vsVlAcceptanceItems.forEach((item) => {
      if (item.title) {
        vsVlChecked[item.title] = item.is_checked || false
      }
    })
    setVsVlAcceptanceChecks(vsVlChecked)
  }, [checklistItems, isVsVlForEffect, project])

  // Initialize VS/VL Amazon checklist items
  React.useEffect(() => {
    if (!isVsVlForEffect || !project?.id || !initialDataLoaded) return
    const existingTitles = new Set(
      vsVlAmazonChecklistItems.map((item) => (item.title || "").trim())
    )
    const missing = VS_VL_AMAZON_CHECKLIST_ITEMS.filter(
      (row) => !existingTitles.has(row.task)
    )
    if (!missing.length) return
    void (async () => {
      let position = Math.max(0, ...vsVlAmazonChecklistItems.map((item) => item.position ?? 0))
      for (const row of missing) {
        position += 1
        const res = await apiFetch("/checklist-items", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: project.id,
            item_type: "CHECKBOX",
            path: VS_VL_AMAZON_CHECKLIST_PATH,
            title: row.task,
            keyword: row.time || null,
            description: row.comment || null,
            category: "AMAZON",
            position,
            is_checked: false,
          }),
        })
        if (!res.ok) {
          console.error("Failed to create VS/VL Amazon checklist item:", row.task)
          continue
        }
        const created = (await res.json()) as ChecklistItem
        setChecklistItems((prev) => {
          // Avoid duplicates by checking if ID already exists
          if (prev.some((p) => p.id === created.id)) return prev
          return [...prev, created]
        })
      }
    })()
  }, [apiFetch, isVsVlForEffect, project?.id, vsVlAmazonChecklistItems, initialDataLoaded])

  // Initialize VS/VL Images checklist items
  React.useEffect(() => {
    if (!isVsVlForEffect || !project?.id || !initialDataLoaded) return
    const existingTitles = new Set(
      vsVlImagesChecklistItems.map((item) => (item.title || "").trim())
    )
    const missing = VS_VL_IMAGES_CHECKLIST_ITEMS.filter(
      (row) => !existingTitles.has(row.task)
    )
    if (!missing.length) return
    void (async () => {
      let position = Math.max(0, ...vsVlImagesChecklistItems.map((item) => item.position ?? 0))
      for (const row of missing) {
        position += 1
        const res = await apiFetch("/checklist-items", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: project.id,
            item_type: "CHECKBOX",
            path: VS_VL_IMAGES_CHECKLIST_PATH,
            title: row.task,
            keyword: row.time || null,
            description: row.comment || null,
            category: "IMAGES",
            position,
            is_checked: false,
          }),
        })
        if (!res.ok) {
          console.error("Failed to create VS/VL Images checklist item:", row.task)
          continue
        }
        const created = (await res.json()) as ChecklistItem
        setChecklistItems((prev) => {
          // Avoid duplicates by checking if ID already exists
          if (prev.some((p) => p.id === created.id)) return prev
          return [...prev, created]
        })
      }
    })()
  }, [apiFetch, isVsVlForEffect, project?.id, vsVlImagesChecklistItems, initialDataLoaded])

  // Initialize VS/VL Dreamrobot VS checklist items
  React.useEffect(() => {
    if (!isVsVlForEffect || !project?.id || !initialDataLoaded) return
    const existingTitles = new Set(
      vsVlDreamrobotVsChecklistItems.map((item) => (item.title || "").trim())
    )
    const missing = VS_VL_DREAMROBOT_VS_CHECKLIST_ITEMS.filter(
      (row) => !existingTitles.has(row.task)
    )
    if (!missing.length) return
    void (async () => {
      let position = Math.max(0, ...vsVlDreamrobotVsChecklistItems.map((item) => item.position ?? 0))
      for (const row of missing) {
        position += 1
        const res = await apiFetch("/checklist-items", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: project.id,
            item_type: "CHECKBOX",
            path: VS_VL_DREAMROBOT_VS_CHECKLIST_PATH,
            title: row.task,
            keyword: row.time || null,
            description: row.comment || null,
            category: "DREAMROBOT_VS",
            position,
            is_checked: false,
          }),
        })
        if (!res.ok) {
          console.error("Failed to create VS/VL Dreamrobot VS checklist item:", row.task)
          continue
        }
        const created = (await res.json()) as ChecklistItem
        setChecklistItems((prev) => {
          if (prev.some((p) => p.id === created.id)) return prev
          return [...prev, created]
        })
      }
    })()
  }, [apiFetch, isVsVlForEffect, project?.id, vsVlDreamrobotVsChecklistItems, initialDataLoaded])

  // Initialize VS/VL Dreamrobot VL checklist items
  React.useEffect(() => {
    if (!isVsVlForEffect || !project?.id || !initialDataLoaded) return
    const existingTitles = new Set(
      vsVlDreamrobotVlChecklistItems.map((item) => (item.title || "").trim())
    )
    const missing = VS_VL_DREAMROBOT_VL_CHECKLIST_ITEMS.filter(
      (row) => !existingTitles.has(row.task)
    )
    if (!missing.length) return
    void (async () => {
      let position = Math.max(0, ...vsVlDreamrobotVlChecklistItems.map((item) => item.position ?? 0))
      for (const row of missing) {
        position += 1
        const res = await apiFetch("/checklist-items", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: project.id,
            item_type: "CHECKBOX",
            path: VS_VL_DREAMROBOT_VL_CHECKLIST_PATH,
            title: row.task,
            keyword: row.time || null,
            description: row.comment || null,
            category: "DREAMROBOT_VL",
            position,
            is_checked: false,
          }),
        })
        if (!res.ok) {
          console.error("Failed to create VS/VL Dreamrobot VL checklist item:", row.task)
          continue
        }
        const created = (await res.json()) as ChecklistItem
        setChecklistItems((prev) => {
          if (prev.some((p) => p.id === created.id)) return prev
          return [...prev, created]
        })
      }
    })()
  }, [apiFetch, isVsVlForEffect, project?.id, vsVlDreamrobotVlChecklistItems, initialDataLoaded])

  React.useEffect(() => {
    if (!vsVlAmazonChecklistItems.length) return
    setVsVlAmazonCommentEdits((prev) => {
      const next = { ...prev }
      vsVlAmazonChecklistItems.forEach((item) => {
        if (next[item.id] === undefined) {
          next[item.id] = item.comment ?? ""
        }
      })
      return next
    })
  }, [vsVlAmazonChecklistItems])

  React.useEffect(() => {
    if (!vsVlImagesChecklistItems.length) return
    setVsVlAmazonCommentEdits((prev) => {
      const next = { ...prev }
      vsVlImagesChecklistItems.forEach((item) => {
        if (next[item.id] === undefined) {
          next[item.id] = item.comment ?? ""
        }
      })
      return next
    })
  }, [vsVlImagesChecklistItems])

  React.useEffect(() => {
    if (!vsVlDreamrobotVsChecklistItems.length) return
    setVsVlAmazonCommentEdits((prev) => {
      const next = { ...prev }
      vsVlDreamrobotVsChecklistItems.forEach((item) => {
        if (next[item.id] === undefined) {
          next[item.id] = item.comment ?? ""
        }
      })
      return next
    })
  }, [vsVlDreamrobotVsChecklistItems])

  React.useEffect(() => {
    if (!vsVlDreamrobotVlChecklistItems.length) return
    setVsVlAmazonCommentEdits((prev) => {
      const next = { ...prev }
      vsVlDreamrobotVlChecklistItems.forEach((item) => {
        if (next[item.id] === undefined) {
          next[item.id] = item.comment ?? ""
        }
      })
      return next
    })
  }, [vsVlDreamrobotVlChecklistItems])

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
    setMeetingChecklist(
      sorted.map((item, index) => ({
        id: item.id,
        content: item.title || "",
        answer: item.comment || "",
        isChecked: Boolean(item.is_checked),
        position: item.position ?? index + 1,
      }))
    )
  }, [checklistItems])
  const isVsVl = React.useMemo(() => isVsVlProject(project), [project])

  const vsVlTabs = React.useMemo(() => {
    const tabs =
      vsVlPhase === "PLANNING" ? [{ id: "description", label: "Description" }] : [{ id: "tasks", label: "Tasks (Detyrat)" }]

    if (vsVlPhase === "AMAZON" || vsVlPhase === "CHECK" || vsVlPhase === "DREAMROBOT") {
      tabs.push({ id: "checklists", label: "Checklists" })
    }

    if (isVsAmazonProject(project) && vsVlPhase !== "PLANNING") {
      tabs.push({ id: "workflow", label: "Workflow" })
    }

    tabs.push({ id: "ga", label: "GA/KA Notes" })
    return tabs
  }, [vsVlPhase, project])
  const mstPhaseRef = React.useRef(mstPhase)
  const vsVlPhaseRef = React.useRef(vsVlPhase)

  React.useEffect(() => {
    if (!isMstLike) return
    if (mstPhaseRef.current === mstPhase) return
    mstPhaseRef.current = mstPhase
    if (mstPhase === "PLANNING") {
      setMstTab("description")
      return
    }
    if (mstPhase === "FINAL") {
      setMstTab("final")
      return
    }
    setMstTab("tasks")
  }, [isMstLike, mstPhase])

  React.useEffect(() => {
    if (!isVsVl) return
    if (vsVlPhaseRef.current === vsVlPhase) return
    vsVlPhaseRef.current = vsVlPhase
    setVsVlTab(vsVlPhase === "PLANNING" ? "description" : "tasks")
  }, [isVsVl, vsVlPhase])

  React.useEffect(() => {
    if (!isVsVl || !project?.id) return

    // Use project.start_date as the base date for calculating all task dates
    const baseDate = project.start_date
    if (!baseDate) return

    const baseTask = findVsVlTask(tasks, VS_VL_TASK_TITLES.base)
    if (baseTask?.dependency_task_id) {
      void (async () => {
        const res = await apiFetch(`/tasks/${baseTask.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dependency_task_id: null }),
        })
        if (!res.ok) return
        const updated = (await res.json()) as Task
        setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))
      })()
    }

    const templateTask = findVsVlTask(tasks, VS_VL_TASK_TITLES.template)
    const pricesTask = findVsVlTask(tasks, VS_VL_TASK_TITLES.prices)
    const photosTask = findVsVlTask(tasks, VS_VL_TASK_TITLES.photos)
    const kontrolTask = findVsVlTask(tasks, VS_VL_TASK_TITLES.control)
    const ko1Task = findVsVlTask(tasks, VS_VL_TASK_TITLES.ko1)
    const ko2Task = findVsVlTask(tasks, VS_VL_TASK_TITLES.ko2)
    const dreamVsTask = findVsVlTask(tasks, VS_VL_TASK_TITLES.dreamVs)
    const dreamVlTask = findVsVlTask(tasks, VS_VL_TASK_TITLES.dreamVl)
    const dreamWeightsTask = findVsVlTask(tasks, VS_VL_TASK_TITLES.dreamWeights)

    const updates: Array<{ task: Task; patch: Record<string, unknown> }> = []

    if (baseTask?.dependency_task_id) {
      updates.push({ task: baseTask, patch: { dependency_task_id: null } })
    }

    const applyRule = (
      task: Task | undefined,
      offsetDays: number,
      dependencyId?: string | null
    ) => {
      if (!task) return
      const expectedDate = addBusinessDaysToIso(baseDate, offsetDays)
      if (!expectedDate) return
      const patch: Record<string, unknown> = {}
      const meta = parseVsVlMeta(task.internal_notes)
      const isManualDueDate = Boolean(meta?.manual_due_date)
      if (!isManualDueDate && !sameDate(task.due_date, expectedDate)) {
        patch.due_date = expectedDate
      }
      if (dependencyId !== undefined && (task.dependency_task_id || null) !== dependencyId) {
        patch.dependency_task_id = dependencyId
      }
      if (Object.keys(patch).length) {
        updates.push({ task, patch })
      }
    }

    // Base task (ANALIZIMI) should be on day 0 (project start date)
    if (baseTask) {
      applyRule(baseTask, 0, null)
    }
    applyRule(templateTask, 1, baseTask?.id)
    applyRule(pricesTask, 3, null)
    applyRule(photosTask, 3, null)
    applyRule(ko1Task, 4, baseTask?.id)
    if (ko2Task && ko1Task) {
      applyRule(ko2Task, 4, ko1Task.id)
    } else {
      applyRule(ko2Task, 4, undefined)
    }
    if (kontrolTask) {
      const dependencyId = ko2Task?.id
      applyRule(kontrolTask, 4, dependencyId ?? undefined)
    }
    if (dreamVsTask || dreamVlTask || dreamWeightsTask) {
      const dependencyId = kontrolTask?.id
      applyRule(dreamVsTask, 4, dependencyId ?? undefined)
      applyRule(dreamVlTask, 4, dependencyId ?? undefined)
      applyRule(dreamWeightsTask, 4, null)
    }

    if (!updates.length) return
    let cancelled = false
    const run = async () => {
      for (const { task, patch } of updates) {
        const res = await apiFetch(`/tasks/${task.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch),
        })
        if (!res.ok) continue
        const updated = (await res.json()) as Task
        if (cancelled) return
        setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [apiFetch, isVsVl, project?.id, project?.start_date, tasks])

  React.useEffect(() => {
    if (!prompts.length) return
  }, [prompts])

  React.useEffect(() => {
    if (!isVsVl) return
    setVsVlCommentEdits((prev) => {
      const next = { ...prev }
      let changed = false
      for (const task of tasks) {
        if (next[task.id] !== undefined) continue
        const meta = parseVsVlMeta(task.internal_notes)
        next[task.id] = meta?.comment || ""
        changed = true
      }
      return changed ? next : prev
    })
  }, [isVsVl, tasks])

  React.useEffect(() => {
    if (!isVsVl) return
    setVsVlDescriptionEdits((prev) => {
      const next = { ...prev }
      let changed = false
      for (const task of tasks) {
        if (next[task.id] !== undefined) continue
        next[task.id] = task.description || ""
        changed = true
      }
      return changed ? next : prev
    })
  }, [isVsVl, tasks])

  React.useEffect(() => {
    if (!membersOpen) return
    setSelectedMemberIds(members.map((m) => m.id))
  }, [membersOpen, members])

  React.useEffect(() => {
    if (!createOpen) return
    if (newTaskPhase) return
    const phaseValue = viewedPhase || project?.current_phase || "INICIMI"
    setNewTaskPhase(phaseValue)
  }, [createOpen, newTaskPhase, project?.current_phase, viewedPhase])

  React.useEffect(() => {
    return () => {
      // Cleanup timers on unmount
      Object.values(vsVlDescriptionTimersRef.current).forEach(clearTimeout)
      Object.values(vsVlMetaTimersRef.current).forEach(clearTimeout)
      Object.values(mstCommentTimersRef.current).forEach(clearTimeout)
    }
  }, [])

  const submitCreateTask = async () => {
    if (!project) return
    if (!newTitle.trim()) {
      toast.error("Title is required")
      return
    }
    if (newAssignedTo === "__unassigned__" || !newAssignedTo) {
      toast.error("Please assign the task to a user")
      return
    }
    if (!newDueDate || !newDueDate.trim()) {
      toast.error("Due date is required")
      return
    }
    if (newStatus === "DONE" && hasIncompleteChecklist) {
      toast.error("Complete all checklist items before marking this task as done.")
      return
    }
    setCreating(true)
    try {
      const payload = {
        title: newTitle.trim(),
        description: newDescription.trim() || null,
        project_id: project.id,
        department_id: project.department_id,
        assigned_to: newAssignedTo === "__unassigned__" ? null : newAssignedTo,
        status: newStatus,
        priority: newTaskType === "HIGH" ? "HIGH" : "NORMAL",
        is_1h_report: newTaskType === "1H",
        is_r1: newTaskType === "R1",
        is_personal: newTaskType === "PERSONAL",
        is_bllok: newTaskType === "BLLOK",
        phase: newTaskPhase || activePhase,
        due_date: newDueDate || null,
        is_deadline_important: false,
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
      const reloaded = await reloadProjectTasks(project.id)
      if (!reloaded) setTasks((prev) => [created, ...prev])
      setCreateOpen(false)
      setNewTitle("")
      setNewDescription("")
      setNewStatus("TODO")
      setNewTaskType("NORMAL")
      setNewAssignedTo("__unassigned__")
      setNewTaskPhase("")
      setNewDueDate("")
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

  const toggleTemplate = async () => {
    if (!project) return
    const newValue = !project.is_template
    try {
      const res = await apiFetch(`/projects/${project.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_template: newValue }),
      })
      if (!res.ok) {
        toast.error("Failed to update template status")
        return
      }
      const updated = (await res.json()) as Project
      setProject(updated)
      toast.success(newValue ? "Marked as template" : "Unmarked as template")
    } catch {
      toast.error("Failed to update template status")
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
          content: newChecklistContent.trim(),
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

  const saveVsVlAmazonComment = async (item: ChecklistItem, nextValue: string) => {
    if (!item.id) return
    const trimmed = nextValue.trim()
    const previous = item.comment ?? ""
    if (trimmed === previous) return
    setChecklistItems((prev) =>
      prev.map((entry) => (entry.id === item.id ? { ...entry, comment: trimmed || null } : entry))
    )
    setVsVlAmazonCommentEdits((prev) => ({ ...prev, [item.id]: trimmed }))
    const res = await apiFetch(`/checklist-items/${item.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ comment: trimmed || null }),
    })
    if (!res.ok) {
      toast.error("Failed to save checklist comment")
      setChecklistItems((prev) =>
        prev.map((entry) => (entry.id === item.id ? { ...entry, comment: previous || null } : entry))
      )
      setVsVlAmazonCommentEdits((prev) => ({ ...prev, [item.id]: previous }))
    }
  }

  const toggleVsVlAmazonKo2 = async (item: ChecklistItem, next: boolean) => {
    if (!item.id) return
    const previous = item.time ?? null
    const nextValue = next ? "1" : ""
    setChecklistItems((prev) =>
      prev.map((entry) => (entry.id === item.id ? { ...entry, time: nextValue } : entry))
    )
    const res = await apiFetch(`/checklist-items/${item.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ time: nextValue }),
    })
    if (!res.ok) {
      toast.error("Failed to save KO2")
      setChecklistItems((prev) =>
        prev.map((entry) => (entry.id === item.id ? { ...entry, time: previous } : entry))
      )
      return
    }
    const updated = (await res.json()) as ChecklistItem
    setChecklistItems((prev) => prev.map((entry) => (entry.id === updated.id ? updated : entry)))
  }

  const exportVsVlChecklist = async (
    items: ChecklistItem[],
    path: string,
    filenameSuffix: string,
    title: string
  ) => {
    const checklistId = items[0]?.checklist_id
    if (!checklistId) {
      toast.error("No checklist items to export.")
      return
    }
    setExportingVsVlChecklist(true)
    try {
      const params = new URLSearchParams()
      params.set("checklist_id", checklistId)
      params.set("path", path)
      if (path === VS_VL_AMAZON_CHECKLIST_PATH && vsVlPhase === "CHECK") {
        params.set("include_ko2", "1")
      }
      params.set("title", title)
      const res = await apiFetch(`/exports/checklists.xlsx?${params.toString()}`)
      if (!res.ok) {
        let detail = "Failed to export checklist."
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      const projectTitle = (project?.title || project?.name || "vs-vl").replace(/\s+/g, "_")
      link.href = url
      link.download = `${projectTitle}_${filenameSuffix}_checklist.xlsx`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } finally {
      setExportingVsVlChecklist(false)
    }
  }

  const exportMstChecklist = async () => {
    const checklistId = isMstTemplateEditor ? mstTemplateChecklist?.id : mstChecklistItems[0]?.checklist_id
    if (!checklistId) {
      toast.error("No checklist items to export.")
      return
    }
    setExportingMstChecklist(true)
    try {
      const params = new URLSearchParams()
      params.set("checklist_id", checklistId)
      params.set("format", "mst")
      if (!showMstOriginalColumn) {
        params.set("include_original", "false")
      }
      Array.from(MST_EXCLUDED_PATHS).forEach((value) => {
        params.append("exclude_path", value)
      })
      const res = await apiFetch(`/exports/checklists.xlsx?${params.toString()}`)
      if (!res.ok) {
        let detail = "Failed to export checklist."
        try {
          const data = (await res.json()) as { detail?: string }
          if (data?.detail) detail = data.detail
        } catch {
          // ignore
        }
        toast.error(detail)
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = isMstTemplateEditor
        ? `${productChecklistLabel}_PRODUCT_TEMPLATE_CHECKLIST.xlsx`
        : `${productChecklistLabel}_PRODUCT_CHECKLIST.xlsx`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } finally {
      setExportingMstChecklist(false)
    }
  }

  // VS/VL Checklist CRUD functions
  const addVsVlAmazonChecklistRow = async () => {
    if (!project) return
    const task = newVsVlAmazonRow.task.trim()
    if (!task) {
      toast.error("Task is required.")
      return
    }
    setSavingVsVlChecklist(true)
    try {
      const maxPosition = vsVlAmazonChecklistItems.reduce((max, item) => Math.max(max, item.position ?? 0), 0)
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          item_type: "CHECKBOX",
          path: VS_VL_AMAZON_CHECKLIST_PATH,
          title: task,
          keyword: newVsVlAmazonRow.time.trim() || null,
          description: newVsVlAmazonRow.comment.trim() || null,
          time: newVsVlAmazonRow.ko2 ? "1" : "",
          is_checked: false,
          position: maxPosition + 1,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to add checklist row")
        return
      }
      const created = (await res.json()) as ChecklistItem
      setChecklistItems((prev) => {
        if (prev.some((p) => p.id === created.id)) return prev
        return [...prev, created]
      })
      setNewVsVlAmazonRow({ task: "", comment: "", time: "", ko2: false })
      toast.success("Checklist row added")
    } finally {
      setSavingVsVlChecklist(false)
    }
  }

  const addVsVlImagesChecklistRow = async () => {
    if (!project) return
    const task = newVsVlImagesRow.task.trim()
    if (!task) {
      toast.error("Task is required.")
      return
    }
    setSavingVsVlChecklist(true)
    try {
      const maxPosition = vsVlImagesChecklistItems.reduce((max, item) => Math.max(max, item.position ?? 0), 0)
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          item_type: "CHECKBOX",
          path: VS_VL_IMAGES_CHECKLIST_PATH,
          title: task,
          keyword: newVsVlImagesRow.time.trim() || null,
          description: newVsVlImagesRow.comment.trim() || null,
          category: "IMAGES",
          is_checked: false,
          position: maxPosition + 1,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to add checklist row")
        return
      }
      const created = (await res.json()) as ChecklistItem
      setChecklistItems((prev) => {
        if (prev.some((p) => p.id === created.id)) return prev
        return [...prev, created]
      })
      setNewVsVlImagesRow({ task: "", comment: "", time: "" })
      toast.success("Checklist row added")
    } finally {
      setSavingVsVlChecklist(false)
    }
  }

  const startEditVsVlChecklistRow = (item: ChecklistItem) => {
    setEditingVsVlChecklistId(item.id)
    setEditingVsVlChecklistRow({
      task: item.title || "",
      comment: item.description || "",
      time: item.keyword || "",
    })
  }

  const cancelEditVsVlChecklistRow = () => {
    setEditingVsVlChecklistId(null)
    setEditingVsVlChecklistRow({ task: "", comment: "", time: "" })
  }

  const saveEditVsVlChecklistRow = async (item: ChecklistItem) => {
    const itemId = item.id
    if (!itemId) return
    const nextTitle = editingVsVlChecklistRow.task.trim() || item.title || ""
    if (!nextTitle.trim()) {
      toast.error("Task is required.")
      return
    }
    setSavingVsVlChecklist(true)
    try {
      const res = await apiFetch(`/checklist-items/${itemId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: nextTitle.trim(),
          description: editingVsVlChecklistRow.comment.trim() || null,
          keyword: editingVsVlChecklistRow.time.trim() || null,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to update checklist row")
        return
      }
      const updated = (await res.json()) as ChecklistItem
      setChecklistItems((prev) => prev.map((item) => (item.id === itemId ? updated : item)))
      setEditingVsVlChecklistId(null)
      setEditingVsVlChecklistRow({ task: "", comment: "", time: "" })
      toast.success("Checklist row updated")
    } finally {
      setSavingVsVlChecklist(false)
    }
  }

  const deleteVsVlChecklistRow = async (itemId: string) => {
    const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
    if (!res.ok) {
      toast.error("Failed to delete checklist row")
      return
    }
    setChecklistItems((prev) => prev.filter((item) => item.id !== itemId))
    toast.success("Checklist row deleted")
  }

  const addVsVlDreamrobotChecklistRow = async (path: string) => {
    if (!project) return
    const task = newVsVlDreamrobotRow.task.trim()
    if (!task) {
      toast.error("Task is required.")
      return
    }
    setSavingVsVlChecklist(true)
    try {
      const existing = checklistItems.filter(
        (item) => item.item_type === "CHECKBOX" && item.path === path
      )
      const maxPosition = existing.reduce((max, item) => Math.max(max, item.position ?? 0), 0)
      const res = await apiFetch("/checklist-items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.id,
          item_type: "CHECKBOX",
          path,
          title: task,
          keyword: newVsVlDreamrobotRow.time.trim() || null,
          description: newVsVlDreamrobotRow.comment.trim() || null,
          category: path === VS_VL_DREAMROBOT_VS_CHECKLIST_PATH ? "DREAMROBOT_VS" : "DREAMROBOT_VL",
          is_checked: false,
          position: maxPosition + 1,
        }),
      })
      if (!res.ok) {
        toast.error("Failed to add checklist row")
        return
      }
      const created = (await res.json()) as ChecklistItem
      setChecklistItems((prev) => {
        if (prev.some((p) => p.id === created.id)) return prev
        return [...prev, created]
      })
      setNewVsVlDreamrobotRow({ task: "", comment: "", time: "" })
      toast.success("Checklist row added")
    } finally {
      setSavingVsVlChecklist(false)
    }
  }

  const patchMeetingChecklistItem = async (
    itemId: string,
    payload: Partial<{ title: string; comment: string | null; is_checked: boolean }>
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

  const toggleMeetingChecklistItem = (itemId: string, next: boolean) => {
    const previous = meetingChecklist.find((item) => item.id === itemId)?.isChecked ?? false
    setMeetingChecklist((prev) =>
      prev.map((item) => (item.id === itemId ? { ...item, isChecked: next } : item))
    )
    void patchMeetingChecklistItem(itemId, { is_checked: next }).then((saved) => {
      if (!saved) {
        setMeetingChecklist((prev) =>
          prev.map((item) => (item.id === itemId ? { ...item, isChecked: previous } : item))
        )
      }
    })
  }

  const startEditMeetingChecklistItem = (itemId: string) => {
    const item = meetingChecklist.find((entry) => entry.id === itemId)
    if (!item) return
    setEditingMeetingItemId(itemId)
    setEditingMeetingItemContent(item.content)
    setEditingMeetingItemAnswer(item.answer)
  }

  const cancelEditMeetingChecklistItem = () => {
    setEditingMeetingItemId(null)
    setEditingMeetingItemContent("")
    setEditingMeetingItemAnswer("")
  }

  const saveMeetingChecklistItem = async () => {
    if (!editingMeetingItemId) return
    const title = editingMeetingItemContent.trim()
    if (!title) return
    const comment = editingMeetingItemAnswer.trim()
    const saved = await patchMeetingChecklistItem(editingMeetingItemId, {
      title,
      comment: comment || null,
    })
    if (saved) {
      cancelEditMeetingChecklistItem()
    }
  }

  const deleteMeetingChecklistItem = async (itemId: string) => {
    const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
    if (!res.ok) {
      toast.error("Failed to delete meeting checklist item")
      return
    }
    setChecklistItems((prev) => prev.filter((entry) => entry.id !== itemId))
    toast.success("Checklist item deleted")
  }

  const addMeetingChecklistItem = async () => {
    if (!project) return
    const title = newMeetingItemContent.trim()
    if (!title) return
    setAddingMeetingItem(true)
    try {
      const nextPosition =
        meetingChecklist.reduce((max, item) => Math.max(max, item.position), 0) + 1
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
      setChecklistItems((prev) => [...prev, created])
      setNewMeetingItemContent("")
      setNewMeetingItemAnswer("")
      toast.success("Checklist item added")
    } finally {
      setAddingMeetingItem(false)
    }
  }

  const toggleDocumentationChecklistItem = (itemId: string, next: boolean) => {
    setDocumentationChecklist((prev) =>
      prev.map((item) => (item.id === itemId ? { ...item, isChecked: next } : item))
    )
  }

  const addDocumentationFilePath = () => {
    const value = documentationFilePath.trim()
    if (!value) return
    setDocumentationFilePaths((prev) => [value, ...prev])
    setDocumentationFilePath("")
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
    const currentPhase = project.current_phase || "INICIMI"
    const isMeetingPhase = currentPhase === "INICIMI"
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
      if (openTasks.length) blockers.push(`${openTasks.length} open tasks`)
      if (uncheckedItems.length) blockers.push(`${uncheckedItems.length} checklist items`)
      if (uncheckedMeeting.length) blockers.push(`${uncheckedMeeting.length} meeting checklist items`)
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
        toast.error(typeof detail === "string" ? detail : "An error occurred")
        return
      }
      const updated = (await res.json()) as Project
      setProject(updated)
      setViewedPhase(updated.current_phase || "MEETINGS")
      toast.success("Phase advanced")
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
      toast.error(typeof detail === "string" ? detail : Array.isArray(detail) ? (detail as any[]).map((e: any) => e.msg || String(e)).join(", ") : "An error occurred")
      return
    }
    const updated = (await res.json()) as GaNote
    setGaNotes((prev) => prev.map((note) => (note.id === updated.id ? updated : note)))
  }

  const closeProjectFromFinal = async () => {
    if (!project) return
    setAdvancingPhase(true)
    try {
      const res = await apiFetch(`/projects/${project.id}/close`, { method: "POST" })
      if (!res.ok) {
        let detail = "Failed to close project"
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
      toast.success("Project closed")
      router.push("/departments/project-content-manager?tab=projects")
    } finally {
      setAdvancingPhase(false)
    }
  }

  const requestCloseProject = (source: "mst" | "vsvl") => {
    setPendingCloseSource(source)
    setCloseConfirmOpen(true)
  }

  const confirmCloseProject = async () => {
    setCloseConfirmOpen(false)
    setPendingCloseSource(null)
    await closeProjectFromFinal()
  }

  const phaseValue = viewedPhase || project?.current_phase || "MEETINGS"
  const visibleTabs = React.useMemo(() => {
    // PCM: meetings phase shows meeting tabs + GA
    if (phaseValue === "MEETINGS") {
      return [...MEETING_TABS, ...TABS.filter((tab) => tab.id === "ga")]
    }
    // planning: show description/tasks/financials
    if (phaseValue === "PLANNING") {
      return TABS.filter((tab) => tab.id !== "checklists" && tab.id !== "members")
    }
    // execution: tasks, members, ga, financials
    if (phaseValue === "DEVELOPMENT") {
      return TABS.filter((tab) => tab.id === "tasks" || tab.id === "members" || tab.id === "ga" || tab.id === "financials")
    }
    // monitoring: show most tabs
    if (phaseValue === "TESTING") {
      return TABS
    }
    return TABS
  }, [phaseValue])

  React.useEffect(() => {
    if (!visibleTabs.length) return
    if (!visibleTabs.some((tab) => tab.id === activeTab)) {
      setActiveTab(visibleTabs[0].id)
    }
  }, [activeTab, visibleTabs])

  React.useEffect(() => {
    // Initialize control edits from tasks (parse totals from internal_notes if present)
    const next: Record<string, { total: string; completed: string; assigned_to: string | null; status: Task["status"] }> =
      {}
    for (const t of tasks) {
      let total = ""
      let completed = ""
      let hasProductCounts = false

      // For CONTROL phase tasks, try to get TOTAL from origin task's daily_products
      if (t.phase === "CONTROL") {
        const originTaskId = getOriginTaskId(t.internal_notes)
        if (originTaskId) {
          const originTask = tasks.find((ot) => ot.id === originTaskId)
          if (originTask && originTask.daily_products !== null && originTask.daily_products !== undefined) {
            total = originTask.daily_products.toString()
            hasProductCounts = true
          }
        }
      }

      if (t.internal_notes) {
        const totalMatch = t.internal_notes.match(/total_products[:=]\s*(\d+)/i)
        const completedMatch = t.internal_notes.match(/completed_products[:=]\s*(\d+)/i)
        // Only use internal_notes total if we didn't find it from origin task
        if (!total && totalMatch) total = totalMatch[1]
        if (completedMatch) completed = completedMatch[1]
        if (totalMatch || completedMatch) hasProductCounts = true
      }
      if (t.daily_products !== null && t.daily_products !== undefined) {
        // For PRODUCT phase, use daily_products directly
        if (t.phase === "PRODUCT") {
          total = t.daily_products.toString()
          hasProductCounts = true
        }
      }

      const totalNum = t.daily_products ?? toNonNegativeInt(total)
      const completedNum = toNonNegativeInt(completed)
      next[t.id] = {
        total,
        completed,
        assigned_to: t.assigned_to || null,
        status: hasProductCounts ? computeStatusFromCompleted(totalNum, completedNum) : t.status,
      }
    }
    setControlEdits(next)
  }, [tasks])

  const activePhase = phaseValue
  const visibleTasks = React.useMemo(
    () =>
      tasks.filter((task) => {
        const taskPhase = task.phase || project?.current_phase || "MEETINGS"
        return taskPhase === activePhase
      }),
    [activePhase, project?.current_phase, tasks]
  )
  const assignableUsers = React.useMemo(() => allUsers, [allUsers])
  const confirmationUserPool = React.useMemo(
    () => [...allUsers, ...members, ...(user ? [user] : [])],
    [allUsers, members, user]
  )
  const confirmerCandidates = React.useMemo(
    () => getConfirmerCandidates(confirmationUserPool),
    [confirmationUserPool]
  )

  if (!project) return <div className="text-sm text-muted-foreground">Loading...</div>

  const backendDisplayTitle = project.display_title?.trim()
  const baseTitle = project.title || project.name || "Project"
  const isTtOrMst = isMstOrTtProject(project)
  const controlTasks = tasks.filter((task) => task.phase === "CONTROL")
  const hasControlTasks = controlTasks.length > 0
  const fallbackControlTotals = controlTasks
    .map((task) => {
      const originTaskId = getOriginTaskId(task.internal_notes)
      const originTask = originTaskId ? tasks.find((t) => t.id === originTaskId) : null
      if (originTask?.daily_products != null && originTask.daily_products > 0) return originTask.daily_products
      const totals = parseTaskTotals(task.internal_notes)
      return totals.total > 0 ? totals.total : 0
    })
    .filter((value) => value > 0)
  const totalForTitle =
    project.total_products != null && project.total_products > 0
      ? project.total_products
      : fallbackControlTotals.length
        ? Math.max(...fallbackControlTotals)
        : null

  const completedSum = controlTasks.reduce((acc, task) => {
    const editCompleted = controlEdits[task.id]?.completed
    if (editCompleted != null && editCompleted !== "") {
      return acc + toNonNegativeInt(editCompleted)
    }
    const totals = parseTaskTotals(task.internal_notes)
    return acc + toNonNegativeInt(totals.completed)
  }, 0)

  const title = (() => {
    if (backendDisplayTitle) return backendDisplayTitle

    if (!(isTtOrMst && hasControlTasks && totalForTitle != null && totalForTitle > 0)) {
      if (project.project_type === "MST" && project.total_products != null && project.total_products > 0) {
        return `${baseTitle} - ${project.total_products}`
      }
      return baseTitle
    }
    const completed = Math.min(completedSum, totalForTitle)
    let normalizedBase = baseTitle.trim()
    const trailingTotalMatch = normalizedBase.match(/\((\d+)\)\s*$/)
    if (trailingTotalMatch && Number.parseInt(trailingTotalMatch[1], 10) === totalForTitle) {
      normalizedBase = normalizedBase.replace(/\s*\(\d+\)\s*$/, "").trim()
    }
    return `${normalizedBase} (${totalForTitle}/${completed})`
  })()

  const patchTask = async (taskId: string, payload: Record<string, unknown>, errorMessage: string) => {
    const nextStatus = typeof payload.status === "string" ? payload.status : null
    const currentTask = tasks.find((t) => t.id === taskId)
    if (
      isWaitingConfirmation(nextStatus) &&
      !currentTask?.confirmation_assignee_id &&
      !payload.confirmation_assignee_id
    ) {
      setPendingStatusTaskId(taskId)
      setPendingStatusValue((nextStatus || "TODO") as Task["status"])
      setPendingConfirmationAssigneeId("")
      return null
    }
    const res = await apiFetch(`/tasks/${taskId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      try {
        const data = (await res.json()) as { detail?: string }
        if (typeof data?.detail === "string" && data.detail.trim()) {
          toast.error(data.detail)
          return null
        }
      } catch {
        // ignore
      }
      toast.error(errorMessage)
      return null
    }
    const updated = (await res.json()) as Task
    setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))
    return updated
  }

  const submitPendingStatusUpdate = async () => {
    if (!pendingStatusTaskId) return
    const validation = validateWaitingConfirmation(pendingStatusValue, pendingConfirmationAssigneeId)
    if (validation) {
      toast.error(validation)
      return
    }
    const updated = await patchTask(
      pendingStatusTaskId,
      {
        status: pendingStatusValue,
        confirmation_assignee_id: pendingConfirmationAssigneeId,
      },
      "Failed to update status"
    )
    if (updated) {
      setPendingStatusTaskId(null)
      setPendingStatusValue("TODO")
      setPendingConfirmationAssigneeId("")
    }
  }

  const renderProjectTitle = () => {
    if (!canEditProjectTitle) {
      return <span className="text-3xl font-semibold">{title}</span>
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
        <span className="text-3xl font-semibold">{title}</span>
        <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={startEditProjectTitle}>
          Edit
        </Button>
      </div>
    )
  }
  const phase = project.current_phase || "MEETINGS"
  const phaseIndex = PHASES.indexOf(phase as (typeof PHASES)[number])
  const canClosePhase = phase !== "CLOSED"
  const userMap = new Map(confirmationUserPool.map((m) => [m.id, m]))

  const renderGaNotes = () => (
    <div className="space-y-4">
      <Card className="bg-white/90 backdrop-blur-sm border-slate-100 shadow-sm rounded-2xl overflow-hidden">
        <div className="p-6 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Select value={newGaNoteType} onValueChange={(value) => setNewGaNoteType(value as "GA" | "KA")}>
              <SelectTrigger className="w-28 border-slate-200 focus:border-slate-400 rounded-xl">
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
              <SelectTrigger className="w-40 border-slate-200 focus:border-slate-400 rounded-xl">
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
              className="border-slate-200 focus:border-slate-400 rounded-xl"
            />
            <Button
              variant="outline"
              disabled={!newGaNote.trim() || addingGaNote}
              onClick={() => void submitGaNote()}
              className="bg-slate-900 hover:bg-slate-800 text-white border-0 rounded-xl"
            >
              {addingGaNote ? "Adding..." : "Add"}
            </Button>
          </div>
        </div>
      </Card>
      {gaNotes.length ? (
        gaNotes.map((note) => (
          <Card key={note.id} className="bg-white/90 backdrop-blur-sm border-slate-100 shadow-sm rounded-2xl overflow-hidden p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex items-center gap-2 text-sm text-slate-600">
                <Badge className={note.note_type === "KA" ? "bg-amber-100 text-amber-700 border-amber-200" : "bg-sky-100 text-sky-700 border-sky-200"}>
                  {note.note_type || "GA"}
                </Badge>
                <span>
                  From {userMap.get(note.created_by || "")?.full_name || userMap.get(note.created_by || "")?.username || "-"}
                </span>
                <span>- {formatDateTime(note.created_at)}</span>
                {note.priority ? (
                  <Badge className="bg-slate-100 text-slate-700 border-slate-200">{statusLabel(note.priority)}</Badge>
                ) : null}
              </div>
              {note.status !== "CLOSED" ? (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void closeGaNote(note.id)}
                  className="rounded-xl border-slate-200 hover:bg-slate-50"
                >
                  Close
                </Button>
              ) : (
                <Badge className="bg-slate-100 text-slate-600 border-slate-200">Closed</Badge>
              )}
            </div>
            <div className="mt-3 text-sm text-slate-700 whitespace-pre-wrap">{note.content}</div>
          </Card>
        ))
      ) : (
        <div className="text-sm text-slate-500 text-center py-6">No GA/KA notes yet.</div>
      )}
    </div>
  )

  if (isVsVl) {
    const memberLabel = (id?: string | null) => {
      if (!id) return "-"
      const u = userMap.get(id)
      const label = u?.full_name || u?.username || u?.email || "-"
      return label === "-" ? "-" : initialsWithDots(label)
    }
    const taskAssigneeIds = (task: Task) => {
      const ids = task.assignees?.map((a) => a.id) || []
      if (ids.length) return ids
      if (task.assigned_to) return [task.assigned_to]
      return []
    }
    const vsVlTasks = tasks.filter((task) => {
      const meta = parseVsVlMeta(task.internal_notes)
      if (!meta?.vs_vl_phase) {
        return vsVlPhase === "AMAZON"
      }
      return meta.vs_vl_phase === vsVlPhase
    })
    const phaseOrder =
      vsVlPhase === "AMAZON"
        ? [
          VS_VL_TASK_TITLES.base,
          VS_VL_TASK_TITLES.template,
          VS_VL_TASK_TITLES.prices,
          VS_VL_TASK_TITLES.photos,
          VS_VL_TASK_TITLES.control,
        ]
        : vsVlPhase === "CHECK"
          ? [VS_VL_TASK_TITLES.ko1, VS_VL_TASK_TITLES.ko2]
          : vsVlPhase === "DREAMROBOT"
            ? [VS_VL_TASK_TITLES.dreamVs, VS_VL_TASK_TITLES.dreamVl, VS_VL_TASK_TITLES.dreamWeights]
            : []
    const orderMap = new Map(phaseOrder.map((key, idx) => [key, idx]))
    const orderedVsVlTasks = [...vsVlTasks].sort((a, b) => {
      const aKey = normalizeTaskTitle(a.title)
      const bKey = normalizeTaskTitle(b.title)
      const aIndex = orderMap.get(aKey) ?? 999
      const bIndex = orderMap.get(bKey) ?? 999
      if (aIndex !== bIndex) return aIndex - bIndex
      const aTime = a.created_at ? new Date(a.created_at).getTime() : 0
      const bTime = b.created_at ? new Date(b.created_at).getTime() : 0
      return aTime - bTime
    })
    const vsVlAmazonChecklistMap = new Map(
      vsVlAmazonChecklistItems.map((item) => [item.title || "", item])
    )
    const vsVlImagesChecklistMap = new Map(
      vsVlImagesChecklistItems.map((item) => [item.title || "", item])
    )
    const taskStatusById = new Map(tasks.map((task) => [task.id, task.status]))
    const dependencyOptions = tasks
    const showVsVlKo2 = vsVlPhase === "CHECK"
    const vsVlChecklistGridCols = showVsVlKo2
      ? "grid-cols-[40px_1fr_1fr_60px_70px_1fr_60px_80px]"
      : "grid-cols-[40px_1fr_1fr_60px_70px_1fr_80px]"

    const queueDescriptionSave = (taskId: string, description: string) => {
      const timers = vsVlDescriptionTimersRef.current
      if (timers[taskId]) {
        clearTimeout(timers[taskId])
      }
      timers[taskId] = setTimeout(() => {
        void patchTask(taskId, { description: description.trim() || null }, "Failed to update description")
      }, 800)
    }
    const buildVsVlMeta = (task: Task, updates: Partial<VsVlTaskMeta>) => {
      const current = parseVsVlMeta(task.internal_notes) || {}
      const nextMeta: VsVlTaskMeta = {
        ...current,
        ...updates,
        vs_vl_phase: current.vs_vl_phase || vsVlPhase,
      }
      if (!nextMeta.comment) delete nextMeta.comment
      if (!nextMeta.checklist) delete nextMeta.checklist
      if (!nextMeta.manual_due_date) delete nextMeta.manual_due_date
      if (nextMeta.unlock_after_days == null) delete nextMeta.unlock_after_days
      return serializeVsVlMeta(nextMeta)
    }
    const updateVsVlMeta = async (task: Task, updates: Partial<VsVlTaskMeta>) => {
      const meta = buildVsVlMeta(task, updates)
      const res = await apiFetch(`/tasks/${task.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ internal_notes: meta }),
      })
      if (!res.ok) {
        toast.error("Failed to update task")
        return null
      }
      const updated = (await res.json()) as Task
      setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))
      return updated
    }
    const queueVsVlMetaSave = (task: Task, updates: Partial<VsVlTaskMeta>) => {
      const timers = vsVlMetaTimersRef.current
      if (timers[task.id]) {
        clearTimeout(timers[task.id])
      }
      timers[task.id] = setTimeout(() => {
        void updateVsVlMeta(task, updates)
      }, 700)
    }

    // VS/VL acceptance checklist items map
    const vsVlAcceptanceItemMap = new Map<string, ChecklistItem>()
    checklistItems
      .filter((item) => item.item_type === "CHECKBOX" && item.path === "VS_VL_PLANNING")
      .forEach((item) => {
        if (item.title) vsVlAcceptanceItemMap.set(item.title, item)
      })

    const toggleVsVlAcceptance = async (q: string) => {
      const newChecked = !vsVlAcceptanceChecks[q]
      // Optimistically update UI
      setVsVlAcceptanceChecks((prev) => ({ ...prev, [q]: newChecked }))

      let item = vsVlAcceptanceItemMap.get(q)

      // Create item if it doesn't exist
      if (!item && project) {
        try {
          const createRes = await apiFetch("/checklist-items", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              project_id: project.id,
              item_type: "CHECKBOX",
              path: "VS_VL_PLANNING",
              title: q,
              keyword: "VS_VL_PLANNING",
              description: q,
              category: "VS_VL_PLANNING",
              is_checked: newChecked,
            }),
          })

          if (createRes.ok) {
            const created = (await createRes.json()) as ChecklistItem
            item = created
            setChecklistItems((prev) => [...prev, created])
            vsVlAcceptanceItemMap.set(q, created)
          }
        } catch (error) {
          console.error("Failed to create VS/VL acceptance item:", error)
        }
      }

      if (item) {
        // Update in background
        try {
          await apiFetch(`/checklist-items/${item.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ is_checked: newChecked }),
          })
        } catch (error) {
          // Silently handle errors
        }
      }
    }

    const toggleVsVlAcceptanceById = async (itemId: string, nextChecked: boolean) => {
      const item = vsVlPlanningItems.find((i) => i.id === itemId)
      if (!item) return

      const previousValue = item.is_checked || false
      setVsVlAcceptanceChecks((prev) => ({ ...prev, [item.title || ""]: nextChecked }))
      setVsVlPlanningItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, is_checked: nextChecked } : i)))
      setChecklistItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, is_checked: nextChecked } : i)))

      try {
        const res = await apiFetch(`/checklist-items/${itemId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_checked: nextChecked }),
        })
        if (!res.ok) {
          toast.error("Failed to save checklist")
          setVsVlAcceptanceChecks((prev) => ({ ...prev, [item.title || ""]: previousValue }))
          setVsVlPlanningItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, is_checked: previousValue } : i)))
          setChecklistItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, is_checked: previousValue } : i)))
        } else {
          const updated = (await res.json()) as ChecklistItem
          setChecklistItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)))
          setVsVlPlanningItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)))
        }
      } catch {
        toast.error("Failed to save checklist")
        setVsVlAcceptanceChecks((prev) => ({ ...prev, [item.title || ""]: previousValue }))
        setVsVlPlanningItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, is_checked: previousValue } : i)))
        setChecklistItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, is_checked: previousValue } : i)))
      }
    }

    const addVsVlPlanningItem = async () => {
      if (!project || !newVsVlPlanningText.trim()) return
      setSavingVsVlPlanning(true)
      try {
        const position = vsVlPlanningItems.length > 0
          ? Math.max(...vsVlPlanningItems.map((item) => item.position ?? 0)) + 1
          : 1

        const res = await apiFetch("/checklist-items", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: project.id,
            item_type: "CHECKBOX",
            path: "VS_VL_PLANNING",
            title: newVsVlPlanningText.trim(),
            keyword: "VS_VL_PLANNING",
            description: newVsVlPlanningText.trim(),
            category: "VS_VL_PLANNING",
            is_checked: false,
            position,
          }),
        })
        if (!res.ok) {
          toast.error("Failed to add checklist item")
          return
        }
        const created = (await res.json()) as ChecklistItem
        setChecklistItems((prev) => [...prev, created])
        setVsVlPlanningItems((prev) => [...prev, created])
        setVsVlAcceptanceChecks((prev) => ({ ...prev, [created.title || ""]: false }))
        setNewVsVlPlanningText("")
        toast.success("Checklist item added")
      } catch {
        toast.error("Failed to add checklist item")
      } finally {
        setSavingVsVlPlanning(false)
      }
    }

    const startEditVsVlPlanningItem = (itemId: string) => {
      const item = vsVlPlanningItems.find((i) => i.id === itemId)
      if (!item) return
      setEditingVsVlPlanningId(itemId)
      setEditingVsVlPlanningText(item.title || "")
    }

    const cancelEditVsVlPlanningItem = () => {
      setEditingVsVlPlanningId(null)
      setEditingVsVlPlanningText("")
    }

    const saveVsVlPlanningItem = async () => {
      if (!editingVsVlPlanningId || !editingVsVlPlanningText.trim()) return
      setSavingVsVlPlanning(true)
      try {
        const res = await apiFetch(`/checklist-items/${editingVsVlPlanningId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: editingVsVlPlanningText.trim() }),
        })
        if (!res.ok) {
          toast.error("Failed to update checklist item")
          return
        }
        const updated = (await res.json()) as ChecklistItem
        setChecklistItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)))
        setVsVlPlanningItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)))
        const oldTitle = vsVlPlanningItems.find((i) => i.id === editingVsVlPlanningId)?.title || ""
        if (oldTitle && oldTitle !== updated.title) {
          setVsVlAcceptanceChecks((prev) => {
            const next = { ...prev }
            delete next[oldTitle]
            if (updated.title) next[updated.title] = updated.is_checked || false
            return next
          })
        }
        cancelEditVsVlPlanningItem()
        toast.success("Checklist item updated")
      } catch {
        toast.error("Failed to update checklist item")
      } finally {
        setSavingVsVlPlanning(false)
      }
    }

    const deleteVsVlPlanningItem = async (itemId: string) => {
      const item = vsVlPlanningItems.find((i) => i.id === itemId)
      if (!item) return

      const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
      if (!res.ok) {
        toast.error("Failed to delete checklist item")
        return
      }
      setChecklistItems((prev) => prev.filter((i) => i.id !== itemId))
      setVsVlPlanningItems((prev) => prev.filter((i) => i.id !== itemId))
      if (item.title) {
        setVsVlAcceptanceChecks((prev) => {
          const next = { ...prev }
          delete next[item.title!]
          return next
        })
      }
      toast.success("Checklist item deleted")
    }

    return (
      <>
        <div className="space-y-5  mx-auto px-4">
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <button type="button" onClick={() => router.back()} className="text-sm text-muted-foreground hover:text-foreground">
                &larr; Back to Projects
              </button>
              <div className="flex items-center gap-3">
                {!project?.is_template ? (
                  project?.start_date ? (
                    <div className="flex items-center gap-2">
                      <div className="text-xs text-slate-500">
                        Started: {formatDateDMY(project.start_date)}
                      </div>
                      {isAdmin && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-xs h-6 w-6 p-0"
                          onClick={() => setEditStartDateDialogOpen(true)}
                          title="Edit start date (Admin only)"
                        >
                          <Pencil className="h-3 w-3" />
                        </Button>
                      )}
                    </div>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      className="text-xs h-7"
                      onClick={() => setStartDateDialogOpen(true)}
                    >
                      Start Project
                    </Button>
                  )
                ) : null}
                {isVsVl && vsVlPhase === "DREAMROBOT" && canCloseProject && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-xs h-7"
                    disabled={advancingPhase}
                    onClick={() => requestCloseProject("vsvl")}
                  >
                    {advancingPhase ? "Closing..." : "Close Project"}
                  </Button>
                )}
                {user?.role === "ADMIN" && (
                  <label className="flex items-center gap-2 text-sm cursor-pointer">
                    <Checkbox
                      checked={project?.is_template ?? false}
                      onCheckedChange={() => void toggleTemplate()}
                    />
                    <span className="text-muted-foreground">Template</span>
                  </label>
                )}
                <Badge variant="outline" className="text-blue-600 border-blue-200 bg-blue-50">
                  VS/VL
                </Badge>
              </div>
            </div>
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                {renderProjectTitle()}
                <ProjectActivityControl project={project} onChange={setProject} />
                {canEditDueDate && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      console.log("Set due date clicked", { project: project?.id, due_date: project?.due_date, isAdmin })
                      const currentDueDate = project.due_date ? toDateInput(project.due_date) : ""
                      console.log("Setting due date to:", currentDueDate)
                      setEditProjectDueDate(currentDueDate)
                      console.log("Opening dialog, setting editProjectDueDateOpen to true")
                      setEditProjectDueDateOpen(true)
                      setTimeout(() => {
                        console.log("Dialog state after set:", editProjectDueDateOpen)
                      }, 0)
                    }}
                    className="text-sm text-muted-foreground hover:text-foreground cursor-pointer underline"
                    title="Edit project due date"
                  >
                    {project.due_date ? `Due: ${formatDateDisplay(project.due_date)}` : "Set due date"}
                  </button>
                )}
                {!canEditDueDate && project.due_date && (
                  <span className="text-sm text-muted-foreground">Due: {formatDateDisplay(project.due_date)}</span>
                )}
                {project?.is_template && (
                  <Badge variant="secondary" className="text-amber-700 border-amber-300 bg-amber-50">Template</Badge>
                )}
              </div>
              <div className="text-sm text-muted-foreground">
                {VS_VL_PHASES.map((p, idx) => (
                  <span key={p}>
                    <button
                      type="button"
                      onClick={() => setVsVlPhase(p)}
                      className={p === vsVlPhase ? "text-blue-700 font-semibold" : "hover:text-foreground"}
                    >
                      {VS_VL_PHASE_LABELS[p]}
                    </button>
                    {idx < VS_VL_PHASES.length - 1 ? " -> " : ""}
                  </span>
                ))}
              </div>
            </div>
          </div>

          <div className="border-b flex gap-6">
            {vsVlTabs.map((tab) => {
              const isActive = vsVlTab === tab.id
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setVsVlTab(tab.id as typeof vsVlTab)}
                  className={[
                    "relative pb-3 text-sm font-medium",
                    tab.id === "ga" ? "ml-auto" : "",
                    isActive ? "text-blue-600" : "text-muted-foreground",
                  ].join(" ")}
                >
                  {tab.label}
                  {isActive ? <span className="absolute inset-x-0 bottom-0 h-0.5 bg-blue-600" /> : null}
                </button>
              )
            })}
          </div>

          {vsVlTab === "ga" ? (
            renderGaNotes()
          ) : vsVlTab === "workflow" ? (
            <VsWorkflow projectId={projectId} apiFetch={apiFetch} phase={vsVlPhase} />
          ) : vsVlTab === "checklists" ? (
            <Card>
              <div className="p-4 space-y-4">
                {/* Sub-tabs for Amazon and Images checklists (Images only in AMAZON phase) */}
                {vsVlPhase === "AMAZON" && (
                  <div className="border-b flex items-center justify-between gap-4">
                    <div className="flex gap-4">
                      <button
                        type="button"
                        onClick={() => setVsVlChecklistTab("amazon")}
                        className={[
                          "relative pb-2 text-sm font-medium",
                          vsVlChecklistTab === "amazon" ? "text-blue-600" : "text-muted-foreground hover:text-foreground",
                        ].join(" ")}
                      >
                        Amazon Checklist
                        {vsVlChecklistTab === "amazon" && <span className="absolute inset-x-0 bottom-0 h-0.5 bg-blue-600" />}
                      </button>
                      <button
                        type="button"
                        onClick={() => setVsVlChecklistTab("images")}
                        className={[
                          "relative pb-2 text-sm font-medium",
                          vsVlChecklistTab === "images" ? "text-blue-600" : "text-muted-foreground hover:text-foreground",
                        ].join(" ")}
                      >
                        Images Checklist
                        {vsVlChecklistTab === "images" && <span className="absolute inset-x-0 bottom-0 h-0.5 bg-blue-600" />}
                      </button>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        void exportVsVlChecklist(
                          vsVlChecklistTab === "amazon" ? vsVlAmazonChecklistItems : vsVlImagesChecklistItems,
                          vsVlChecklistTab === "amazon" ? VS_VL_AMAZON_CHECKLIST_PATH : VS_VL_IMAGES_CHECKLIST_PATH,
                          vsVlChecklistTab === "amazon" ? "amazon" : "images",
                          vsVlChecklistTab === "amazon" ? "Amazon Checklist" : "Images Checklist"
                        )
                      }
                      disabled={
                        exportingVsVlChecklist ||
                        (vsVlChecklistTab === "amazon"
                          ? vsVlAmazonChecklistItems.length === 0
                          : vsVlImagesChecklistItems.length === 0)
                      }
                      className="h-8 rounded-xl border-slate-200 text-xs"
                    >
                      <Download className="mr-2 h-4 w-4" />
                      {exportingVsVlChecklist ? "Exporting..." : "Export Excel"}
                    </Button>
                  </div>
                )}

                {/* Sub-tabs for Dreamrobot phase checklists */}
                {vsVlPhase === "DREAMROBOT" && (
                  <div className="border-b flex items-end justify-between gap-4">
                    <div className="flex gap-4">
                      <button
                        type="button"
                        onClick={() => setVsVlDreamrobotChecklistTab("vs")}
                        className={[
                          "relative pb-2 text-sm font-medium",
                          vsVlDreamrobotChecklistTab === "vs" ? "text-blue-600" : "text-muted-foreground hover:text-foreground",
                        ].join(" ")}
                      >
                        VS Dreamrobot Checklist
                        {vsVlDreamrobotChecklistTab === "vs" && <span className="absolute inset-x-0 bottom-0 h-0.5 bg-blue-600" />}
                      </button>
                      <button
                        type="button"
                        onClick={() => setVsVlDreamrobotChecklistTab("vl")}
                        className={[
                          "relative pb-2 text-sm font-medium",
                          vsVlDreamrobotChecklistTab === "vl" ? "text-blue-600" : "text-muted-foreground hover:text-foreground",
                        ].join(" ")}
                      >
                        VL Dreamrobot Checklist
                        {vsVlDreamrobotChecklistTab === "vl" && <span className="absolute inset-x-0 bottom-0 h-0.5 bg-blue-600" />}
                      </button>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        void exportVsVlChecklist(
                          vsVlDreamrobotChecklistTab === "vs"
                            ? vsVlDreamrobotVsChecklistItems
                            : vsVlDreamrobotVlChecklistItems,
                          vsVlDreamrobotChecklistTab === "vs"
                            ? VS_VL_DREAMROBOT_VS_CHECKLIST_PATH
                            : VS_VL_DREAMROBOT_VL_CHECKLIST_PATH,
                          vsVlDreamrobotChecklistTab === "vs" ? "dreamrobot_vs" : "dreamrobot_vl",
                          vsVlDreamrobotChecklistTab === "vs"
                            ? "VS Dreamrobot Checklist"
                            : "VL Dreamrobot Checklist"
                        )
                      }
                      disabled={
                        exportingVsVlChecklist ||
                        (vsVlDreamrobotChecklistTab === "vs"
                          ? vsVlDreamrobotVsChecklistItems.length === 0
                          : vsVlDreamrobotVlChecklistItems.length === 0)
                      }
                      className="h-8 rounded-xl border-slate-200 text-xs"
                    >
                      <Download className="mr-2 h-4 w-4" />
                      {exportingVsVlChecklist ? "Exporting..." : "Export Excel"}
                    </Button>
                  </div>
                )}

                {vsVlPhase === "DREAMROBOT" ? (
                  vsVlDreamrobotChecklistTab === "vs" ? (
                    <div className="space-y-4">
                      {/* VS Dreamrobot Checklist Table */}
                      <div className="border border-slate-200 rounded-lg overflow-hidden">
                        <div className="grid grid-cols-[40px_1fr_1fr_60px_70px_1fr_80px] gap-2 px-3 py-2 text-[11px] font-semibold text-slate-500 border-b bg-slate-50/60">
                          <div>NO</div>
                          <div>TASK</div>
                          <div>COMMENT</div>
                          <div>CHECK</div>
                          <div>TIME</div>
                          <div>KOMENT</div>
                          <div className="text-right">ACTIONS</div>
                        </div>
                        <div className="grid grid-cols-[40px_1fr_1fr_60px_70px_1fr_80px] gap-2 px-3 py-2 text-xs items-center border-b bg-slate-50/30">
                          <div className="text-slate-400">+</div>
                          <div>
                            <Input
                              value={newVsVlDreamrobotRow.task}
                              onChange={(e) => setNewVsVlDreamrobotRow((prev) => ({ ...prev, task: e.target.value }))}
                              placeholder="Task"
                              className="h-7 text-xs"
                            />
                          </div>
                          <div>
                            <Input
                              value={newVsVlDreamrobotRow.comment}
                              onChange={(e) => setNewVsVlDreamrobotRow((prev) => ({ ...prev, comment: e.target.value }))}
                              placeholder="Comment"
                              className="h-7 text-xs"
                            />
                          </div>
                          <div className="flex items-center justify-center" />
                          <div>
                            <Input
                              value={newVsVlDreamrobotRow.time}
                              onChange={(e) => setNewVsVlDreamrobotRow((prev) => ({ ...prev, time: e.target.value }))}
                              placeholder="Time"
                              className="h-7 text-xs"
                            />
                          </div>
                          <div />
                          <div className="flex justify-end">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => void addVsVlDreamrobotChecklistRow(VS_VL_DREAMROBOT_VS_CHECKLIST_PATH)}
                              disabled={savingVsVlChecklist || !newVsVlDreamrobotRow.task.trim()}
                              className="h-7 text-xs"
                            >
                              {savingVsVlChecklist ? "..." : "Add"}
                            </Button>
                          </div>
                        </div>
                        <div className="divide-y max-h-[500px] overflow-y-auto">
                          {vsVlDreamrobotVsChecklistItems
                            .slice()
                            .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
                            .map((item, index) => {
                              const isEditing = editingVsVlChecklistId === item.id
                              const checked = item.is_checked ?? false
                              const commentValue =
                                vsVlAmazonCommentEdits[item.id] !== undefined
                                  ? vsVlAmazonCommentEdits[item.id]
                                  : item.comment ?? ""
                              return (
                                <div key={item.id} className="grid grid-cols-[40px_1fr_1fr_60px_70px_1fr_80px] gap-2 px-3 py-2 text-xs items-start hover:bg-slate-50/50">
                                  <div className="text-slate-500 pt-1">{index + 1}</div>
                                  <div className="font-medium whitespace-pre-wrap">
                                    {isEditing ? (
                                      <Textarea
                                        value={editingVsVlChecklistRow.task}
                                        onChange={(e) => setEditingVsVlChecklistRow((prev) => ({ ...prev, task: e.target.value }))}
                                        className="text-xs min-h-[60px]"
                                      />
                                    ) : (
                                      item.title || "-"
                                    )}
                                  </div>
                                  <div className="text-slate-600 text-[11px] whitespace-pre-wrap">
                                    {isEditing ? (
                                      <Textarea
                                        value={editingVsVlChecklistRow.comment}
                                        onChange={(e) => setEditingVsVlChecklistRow((prev) => ({ ...prev, comment: e.target.value }))}
                                        className="text-xs min-h-[60px]"
                                      />
                                    ) : (
                                      item.description || "-"
                                    )}
                                  </div>
                                  <div className="flex items-center justify-center">
                                    <Checkbox
                                      checked={checked}
                                      onCheckedChange={(next) => void toggleChecklistItem(item.id, Boolean(next))}
                                    />
                                  </div>
                                  <div className="text-slate-500">
                                    {isEditing ? (
                                      <Input
                                        value={editingVsVlChecklistRow.time}
                                        onChange={(e) => setEditingVsVlChecklistRow((prev) => ({ ...prev, time: e.target.value }))}
                                        className="h-7 text-xs"
                                      />
                                    ) : (
                                      item.keyword || "-"
                                    )}
                                  </div>
                                  <div>
                                    <Input
                                      value={commentValue}
                                      onChange={(e) => setVsVlAmazonCommentEdits((prev) => ({ ...prev, [item.id]: e.target.value }))}
                                      onBlur={(e) => void saveVsVlAmazonComment(item, e.target.value)}
                                      placeholder="Koment"
                                      className="h-7 text-xs"
                                    />
                                  </div>
                                  <div className="flex gap-1 justify-end">
                                    {isEditing ? (
                                      <>
                                        <Button
                                          size="sm"
                                          variant="outline"
                                          onClick={() => void saveEditVsVlChecklistRow(item)}
                                          disabled={savingVsVlChecklist}
                                          className="h-6 px-2 text-[10px]"
                                        >
                                          Save
                                        </Button>
                                        <Button
                                          size="sm"
                                          variant="ghost"
                                          onClick={cancelEditVsVlChecklistRow}
                                          className="h-6 px-2 text-[10px]"
                                        >
                                          Cancel
                                        </Button>
                                      </>
                                    ) : (
                                      <>
                                        <Button
                                          size="sm"
                                          variant="ghost"
                                          onClick={() => startEditVsVlChecklistRow(item)}
                                          className="h-6 px-2 text-[10px]"
                                        >
                                          <Pencil className="h-3 w-3" />
                                        </Button>
                                        <Button
                                          size="sm"
                                          variant="ghost"
                                          onClick={() => void deleteVsVlChecklistRow(item.id)}
                                          className="h-6 px-2 text-[10px] text-red-600 hover:text-red-700"
                                        >
                                          <Trash2 className="h-3 w-3" />
                                        </Button>
                                      </>
                                    )}
                                  </div>
                                </div>
                              )
                            })}
                          {vsVlDreamrobotVsChecklistItems.length === 0 && (
                            <div className="px-3 py-6 text-center text-sm text-slate-400">
                              No checklist items yet.
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {/* VL Dreamrobot Checklist Table */}
                      <div className="border border-slate-200 rounded-lg overflow-hidden">
                        <div className="grid grid-cols-[40px_1fr_1fr_60px_70px_1fr_80px] gap-2 px-3 py-2 text-[11px] font-semibold text-slate-500 border-b bg-slate-50/60">
                          <div>NO</div>
                          <div>TASK</div>
                          <div>COMMENT</div>
                          <div>CHECK</div>
                          <div>TIME</div>
                          <div>KOMENT</div>
                          <div className="text-right">ACTIONS</div>
                        </div>
                        <div className="grid grid-cols-[40px_1fr_1fr_60px_70px_1fr_80px] gap-2 px-3 py-2 text-xs items-center border-b bg-slate-50/30">
                          <div className="text-slate-400">+</div>
                          <div>
                            <Input
                              value={newVsVlDreamrobotRow.task}
                              onChange={(e) => setNewVsVlDreamrobotRow((prev) => ({ ...prev, task: e.target.value }))}
                              placeholder="Task"
                              className="h-7 text-xs"
                            />
                          </div>
                          <div>
                            <Input
                              value={newVsVlDreamrobotRow.comment}
                              onChange={(e) => setNewVsVlDreamrobotRow((prev) => ({ ...prev, comment: e.target.value }))}
                              placeholder="Comment"
                              className="h-7 text-xs"
                            />
                          </div>
                          <div className="flex items-center justify-center" />
                          <div>
                            <Input
                              value={newVsVlDreamrobotRow.time}
                              onChange={(e) => setNewVsVlDreamrobotRow((prev) => ({ ...prev, time: e.target.value }))}
                              placeholder="Time"
                              className="h-7 text-xs"
                            />
                          </div>
                          <div />
                          <div className="flex justify-end">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => void addVsVlDreamrobotChecklistRow(VS_VL_DREAMROBOT_VL_CHECKLIST_PATH)}
                              disabled={savingVsVlChecklist || !newVsVlDreamrobotRow.task.trim()}
                              className="h-7 text-xs"
                            >
                              {savingVsVlChecklist ? "..." : "Add"}
                            </Button>
                          </div>
                        </div>
                        <div className="divide-y max-h-[500px] overflow-y-auto">
                          {vsVlDreamrobotVlChecklistItems
                            .slice()
                            .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
                            .map((item, index) => {
                              const isEditing = editingVsVlChecklistId === item.id
                              const checked = item.is_checked ?? false
                              const commentValue =
                                vsVlAmazonCommentEdits[item.id] !== undefined
                                  ? vsVlAmazonCommentEdits[item.id]
                                  : item.comment ?? ""
                              return (
                                <div key={item.id} className="grid grid-cols-[40px_1fr_1fr_60px_70px_1fr_80px] gap-2 px-3 py-2 text-xs items-start hover:bg-slate-50/50">
                                  <div className="text-slate-500 pt-1">{index + 1}</div>
                                  <div className="font-medium whitespace-pre-wrap">
                                    {isEditing ? (
                                      <Textarea
                                        value={editingVsVlChecklistRow.task}
                                        onChange={(e) => setEditingVsVlChecklistRow((prev) => ({ ...prev, task: e.target.value }))}
                                        className="text-xs min-h-[60px]"
                                      />
                                    ) : (
                                      item.title || "-"
                                    )}
                                  </div>
                                  <div className="text-slate-600 text-[11px] whitespace-pre-wrap">
                                    {isEditing ? (
                                      <Textarea
                                        value={editingVsVlChecklistRow.comment}
                                        onChange={(e) => setEditingVsVlChecklistRow((prev) => ({ ...prev, comment: e.target.value }))}
                                        className="text-xs min-h-[60px]"
                                      />
                                    ) : (
                                      item.description || "-"
                                    )}
                                  </div>
                                  <div className="flex items-center justify-center">
                                    <Checkbox
                                      checked={checked}
                                      onCheckedChange={(next) => void toggleChecklistItem(item.id, Boolean(next))}
                                    />
                                  </div>
                                  <div className="text-slate-500">
                                    {isEditing ? (
                                      <Input
                                        value={editingVsVlChecklistRow.time}
                                        onChange={(e) => setEditingVsVlChecklistRow((prev) => ({ ...prev, time: e.target.value }))}
                                        className="h-7 text-xs"
                                      />
                                    ) : (
                                      item.keyword || "-"
                                    )}
                                  </div>
                                  <div>
                                    <Input
                                      value={commentValue}
                                      onChange={(e) => setVsVlAmazonCommentEdits((prev) => ({ ...prev, [item.id]: e.target.value }))}
                                      onBlur={(e) => void saveVsVlAmazonComment(item, e.target.value)}
                                      placeholder="Koment"
                                      className="h-7 text-xs"
                                    />
                                  </div>
                                  <div className="flex gap-1 justify-end">
                                    {isEditing ? (
                                      <>
                                        <Button
                                          size="sm"
                                          variant="outline"
                                          onClick={() => void saveEditVsVlChecklistRow(item)}
                                          disabled={savingVsVlChecklist}
                                          className="h-6 px-2 text-[10px]"
                                        >
                                          Save
                                        </Button>
                                        <Button
                                          size="sm"
                                          variant="ghost"
                                          onClick={cancelEditVsVlChecklistRow}
                                          className="h-6 px-2 text-[10px]"
                                        >
                                          Cancel
                                        </Button>
                                      </>
                                    ) : (
                                      <>
                                        <Button
                                          size="sm"
                                          variant="ghost"
                                          onClick={() => startEditVsVlChecklistRow(item)}
                                          className="h-6 px-2 text-[10px]"
                                        >
                                          <Pencil className="h-3 w-3" />
                                        </Button>
                                        <Button
                                          size="sm"
                                          variant="ghost"
                                          onClick={() => void deleteVsVlChecklistRow(item.id)}
                                          className="h-6 px-2 text-[10px] text-red-600 hover:text-red-700"
                                        >
                                          <Trash2 className="h-3 w-3" />
                                        </Button>
                                      </>
                                    )}
                                  </div>
                                </div>
                              )
                            })}
                          {vsVlDreamrobotVlChecklistItems.length === 0 && (
                            <div className="px-3 py-6 text-center text-sm text-slate-400">
                              No checklist items yet.
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                ) : (vsVlChecklistTab === "amazon" || vsVlPhase === "CHECK") ? (
                  <div className="space-y-4">
                    {vsVlPhase === "CHECK" && (
                      <div className="flex justify-end">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            void exportVsVlChecklist(
                              vsVlAmazonChecklistItems,
                              VS_VL_AMAZON_CHECKLIST_PATH,
                              "amazon",
                              "Amazon Checklist"
                            )
                          }
                          disabled={exportingVsVlChecklist || vsVlAmazonChecklistItems.length === 0}
                          className="h-8 rounded-xl border-slate-200 text-xs"
                        >
                          <Download className="mr-2 h-4 w-4" />
                          {exportingVsVlChecklist ? "Exporting..." : "Export Excel"}
                        </Button>
                      </div>
                    )}
                    {/* Warning notes */}
                    <div className="text-sm text-red-600 space-y-1">
                      {VS_VL_AMAZON_CHECKLIST_NOTES.map((note, idx) => (
                        <div key={idx}>!!! {note}</div>
                      ))}
                    </div>

                    {/* Amazon Checklist Table */}
                    <div className="border border-slate-200 rounded-lg overflow-hidden">
                      <div className={`grid ${vsVlChecklistGridCols} gap-2 px-3 py-2 text-[11px] font-semibold text-slate-500 border-b bg-slate-50/60`}>
                        <div>NO</div>
                        <div>TASK</div>
                        <div>COMMENT</div>
                        <div>CHECK</div>
                        <div>TIME</div>
                        <div>KOMENT</div>
                        {showVsVlKo2 ? <div>KO2</div> : null}
                        <div className="text-right">ACTIONS</div>
                      </div>
                      {/* Add new row */}
                      <div className={`grid ${vsVlChecklistGridCols} gap-2 px-3 py-2 text-xs items-center border-b bg-slate-50/30`}>
                        <div className="text-slate-400">+</div>
                        <div>
                          <Input
                            value={newVsVlAmazonRow.task}
                            onChange={(e) => setNewVsVlAmazonRow((prev) => ({ ...prev, task: e.target.value }))}
                            placeholder="Task"
                            className="h-7 text-xs"
                          />
                        </div>
                        <div>
                          <Input
                            value={newVsVlAmazonRow.comment}
                            onChange={(e) => setNewVsVlAmazonRow((prev) => ({ ...prev, comment: e.target.value }))}
                            placeholder="Comment"
                            className="h-7 text-xs"
                          />
                        </div>
                        <div />
                        <div>
                          <Input
                            value={newVsVlAmazonRow.time}
                            onChange={(e) => setNewVsVlAmazonRow((prev) => ({ ...prev, time: e.target.value }))}
                            placeholder="Time"
                            className="h-7 text-xs"
                          />
                        </div>
                        <div className="flex items-center justify-center" />
                        {showVsVlKo2 ? (
                          <div>
                            <Checkbox
                              checked={newVsVlAmazonRow.ko2}
                              onCheckedChange={(next) =>
                                setNewVsVlAmazonRow((prev) => ({ ...prev, ko2: Boolean(next) }))
                              }
                            />
                          </div>
                        ) : null}
                        <div className="flex justify-end">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => void addVsVlAmazonChecklistRow()}
                            disabled={savingVsVlChecklist || !newVsVlAmazonRow.task.trim()}
                            className="h-7 text-xs"
                          >
                            {savingVsVlChecklist ? "..." : "Add"}
                          </Button>
                        </div>
                      </div>
                      <div className="divide-y max-h-[500px] overflow-y-auto">
                        {vsVlAmazonChecklistItems
                          .slice()
                          .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
                          .map((item, index) => {
                            const isEditing = editingVsVlChecklistId === item.id
                            const checked = item.is_checked ?? false
                            const ko2Checked = item.time === "1" || item.time === "true"
                            const commentValue =
                              vsVlAmazonCommentEdits[item.id] !== undefined
                                ? vsVlAmazonCommentEdits[item.id]
                                : item.comment ?? ""
                            return (
                              <div key={item.id} className={`grid ${vsVlChecklistGridCols} gap-2 px-3 py-2 text-xs items-start hover:bg-slate-50/50`}>
                                <div className="text-slate-500 pt-1">{index + 1}</div>
                                <div className="font-medium">
                                  {isEditing ? (
                                    <Input
                                      value={editingVsVlChecklistRow.task}
                                      onChange={(e) => setEditingVsVlChecklistRow((prev) => ({ ...prev, task: e.target.value }))}
                                      className="h-7 text-xs"
                                    />
                                  ) : (
                                    item.title || "-"
                                  )}
                                </div>
                                <div className="text-slate-600 text-[11px]">
                                  {isEditing ? (
                                    <Input
                                      value={editingVsVlChecklistRow.comment}
                                      onChange={(e) => setEditingVsVlChecklistRow((prev) => ({ ...prev, comment: e.target.value }))}
                                      className="h-7 text-xs"
                                    />
                                  ) : (
                                    item.description || "-"
                                  )}
                                </div>
                                <div className="flex items-center justify-center">
                                  <Checkbox
                                    checked={checked}
                                    onCheckedChange={(next) => void toggleChecklistItem(item.id, Boolean(next))}
                                  />
                                </div>
                                <div className="text-slate-500">
                                  {isEditing ? (
                                    <Input
                                      value={editingVsVlChecklistRow.time}
                                      onChange={(e) => setEditingVsVlChecklistRow((prev) => ({ ...prev, time: e.target.value }))}
                                      className="h-7 text-xs"
                                    />
                                  ) : (
                                    item.keyword || "-"
                                  )}
                                </div>
                                <div>
                                  <Input
                                    value={commentValue}
                                    onChange={(e) => setVsVlAmazonCommentEdits((prev) => ({ ...prev, [item.id]: e.target.value }))}
                                    onBlur={(e) => void saveVsVlAmazonComment(item, e.target.value)}
                                    placeholder="Koment"
                                    className="h-7 text-xs"
                                  />
                                </div>
                                {showVsVlKo2 ? (
                                  <div className="flex items-center justify-center">
                                    <Checkbox
                                      checked={ko2Checked}
                                      onCheckedChange={(next) =>
                                        void toggleVsVlAmazonKo2(item, Boolean(next))
                                      }
                                    />
                                  </div>
                                ) : null}
                                <div className="flex gap-1 justify-end">
                                  {isEditing ? (
                                    <>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() => void saveEditVsVlChecklistRow(item)}
                                        disabled={savingVsVlChecklist}
                                        className="h-6 px-2 text-[10px]"
                                      >
                                        Save
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="ghost"
                                        onClick={cancelEditVsVlChecklistRow}
                                        className="h-6 px-2 text-[10px]"
                                      >
                                        Cancel
                                      </Button>
                                    </>
                                  ) : (
                                    <>
                                      <Button
                                        size="sm"
                                        variant="ghost"
                                        onClick={() => startEditVsVlChecklistRow(item)}
                                        className="h-6 px-2 text-[10px]"
                                      >
                                        <Pencil className="h-3 w-3" />
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="ghost"
                                        onClick={() => void deleteVsVlChecklistRow(item.id)}
                                        className="h-6 px-2 text-[10px] text-red-600 hover:text-red-700"
                                      >
                                        <Trash2 className="h-3 w-3" />
                                      </Button>
                                    </>
                                  )}
                                </div>
                              </div>
                            )
                          })}
                        {vsVlAmazonChecklistItems.length === 0 && (
                          <div className="px-3 py-6 text-center text-sm text-slate-400">
                            No checklist items yet. Add one above.
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {/* Images Checklist Table */}
                    <div className="border border-slate-200 rounded-lg overflow-hidden">
                      <div className="grid grid-cols-[40px_1fr_1fr_60px_70px_1fr_80px] gap-2 px-3 py-2 text-[11px] font-semibold text-slate-500 border-b bg-slate-50/60">
                        <div>NO</div>
                        <div>TASK</div>
                        <div>COMMENT</div>
                        <div>CHECK</div>
                        <div>TIME</div>
                        <div>KOMENT</div>
                        <div className="text-right">ACTIONS</div>
                      </div>
                      {/* Add new row */}
                      <div className="grid grid-cols-[40px_1fr_1fr_60px_70px_1fr_80px] gap-2 px-3 py-2 text-xs items-center border-b bg-slate-50/30">
                        <div className="text-slate-400">+</div>
                        <div>
                          <Input
                            value={newVsVlImagesRow.task}
                            onChange={(e) => setNewVsVlImagesRow((prev) => ({ ...prev, task: e.target.value }))}
                            placeholder="Task"
                            className="h-7 text-xs"
                          />
                        </div>
                        <div>
                          <Input
                            value={newVsVlImagesRow.comment}
                            onChange={(e) => setNewVsVlImagesRow((prev) => ({ ...prev, comment: e.target.value }))}
                            placeholder="Comment"
                            className="h-7 text-xs"
                          />
                        </div>
                        <div className="flex items-center justify-center" />
                        <div>
                          <Input
                            value={newVsVlImagesRow.time}
                            onChange={(e) => setNewVsVlImagesRow((prev) => ({ ...prev, time: e.target.value }))}
                            placeholder="Time"
                            className="h-7 text-xs"
                          />
                        </div>
                        <div />
                        <div className="flex justify-end">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => void addVsVlImagesChecklistRow()}
                            disabled={savingVsVlChecklist || !newVsVlImagesRow.task.trim()}
                            className="h-7 text-xs"
                          >
                            {savingVsVlChecklist ? "..." : "Add"}
                          </Button>
                        </div>
                      </div>
                      <div className="divide-y max-h-[500px] overflow-y-auto">
                        {vsVlImagesChecklistItems
                          .slice()
                          .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
                          .map((item, index) => {
                            const isEditing = editingVsVlChecklistId === item.id
                            const checked = item.is_checked ?? false
                            const commentValue =
                              vsVlAmazonCommentEdits[item.id] !== undefined
                                ? vsVlAmazonCommentEdits[item.id]
                                : item.comment ?? ""
                            return (
                              <div key={item.id} className="grid grid-cols-[40px_1fr_1fr_60px_70px_1fr_80px] gap-2 px-3 py-2 text-xs items-start hover:bg-slate-50/50">
                                <div className="text-slate-500 pt-1">{index + 1}</div>
                                <div className="font-medium">
                                  {isEditing ? (
                                    <Input
                                      value={editingVsVlChecklistRow.task}
                                      onChange={(e) => setEditingVsVlChecklistRow((prev) => ({ ...prev, task: e.target.value }))}
                                      className="h-7 text-xs"
                                    />
                                  ) : (
                                    item.title || "-"
                                  )}
                                </div>
                                <div className="text-slate-600 text-[11px]">
                                  {isEditing ? (
                                    <Input
                                      value={editingVsVlChecklistRow.comment}
                                      onChange={(e) => setEditingVsVlChecklistRow((prev) => ({ ...prev, comment: e.target.value }))}
                                      className="h-7 text-xs"
                                    />
                                  ) : (
                                    item.description || "-"
                                  )}
                                </div>
                                <div className="flex items-center justify-center">
                                  <Checkbox
                                    checked={checked}
                                    onCheckedChange={(next) => void toggleChecklistItem(item.id, Boolean(next))}
                                  />
                                </div>
                                <div className="text-slate-500">
                                  {isEditing ? (
                                    <Input
                                      value={editingVsVlChecklistRow.time}
                                      onChange={(e) => setEditingVsVlChecklistRow((prev) => ({ ...prev, time: e.target.value }))}
                                      className="h-7 text-xs"
                                    />
                                  ) : (
                                    item.keyword || "-"
                                  )}
                                </div>
                                <div>
                                  <Input
                                    value={commentValue}
                                    onChange={(e) => setVsVlAmazonCommentEdits((prev) => ({ ...prev, [item.id]: e.target.value }))}
                                    onBlur={(e) => void saveVsVlAmazonComment(item, e.target.value)}
                                    placeholder="Koment"
                                    className="h-7 text-xs"
                                  />
                                </div>
                                <div className="flex gap-1 justify-end">
                                  {isEditing ? (
                                    <>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        onClick={() => void saveEditVsVlChecklistRow(item)}
                                        disabled={savingVsVlChecklist}
                                        className="h-6 px-2 text-[10px]"
                                      >
                                        Save
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="ghost"
                                        onClick={cancelEditVsVlChecklistRow}
                                        className="h-6 px-2 text-[10px]"
                                      >
                                        Cancel
                                      </Button>
                                    </>
                                  ) : (
                                    <>
                                      <Button
                                        size="sm"
                                        variant="ghost"
                                        onClick={() => startEditVsVlChecklistRow(item)}
                                        className="h-6 px-2 text-[10px]"
                                      >
                                        <Pencil className="h-3 w-3" />
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="ghost"
                                        onClick={() => void deleteVsVlChecklistRow(item.id)}
                                        className="h-6 px-2 text-[10px] text-red-600 hover:text-red-700"
                                      >
                                        <Trash2 className="h-3 w-3" />
                                      </Button>
                                    </>
                                  )}
                                </div>
                              </div>
                            )
                          })}
                        {vsVlImagesChecklistItems.length === 0 && (
                          <div className="px-3 py-6 text-center text-sm text-slate-400">
                            No checklist items yet. Add one above.
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </Card>
          ) : vsVlPhase === "PLANNING" ? (

            <Card>
              <div className="p-4 space-y-4">
                <div className="text-lg font-semibold">Planning</div>

                {/* Add new item */}
                <div className="flex items-center gap-2 mb-4">
                  <Input
                    placeholder="Add checklist item..."
                    value={newVsVlPlanningText}
                    onChange={(e) => setNewVsVlPlanningText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !savingVsVlPlanning) {
                        void addVsVlPlanningItem()
                      }
                    }}
                    className="flex-1"
                  />
                  <Button
                    onClick={() => void addVsVlPlanningItem()}
                    disabled={!newVsVlPlanningText.trim() || savingVsVlPlanning}
                    size="sm"
                  >
                    {savingVsVlPlanning ? "Adding..." : "Add"}
                  </Button>
                </div>

                <div className="grid gap-3">
                  {vsVlPlanningItems
                    .slice()
                    .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
                    .map((item, index) => {
                      const isEditing = editingVsVlPlanningId === item.id
                      return (
                        <div key={item.id} className="flex items-center gap-3 group">
                          <span className="text-xs font-semibold text-slate-400">{index + 1}.</span>
                          <Checkbox
                            checked={Boolean(vsVlAcceptanceChecks[item.title || ""])}
                            onCheckedChange={(checked) =>
                              void toggleVsVlAcceptanceById(item.id, Boolean(checked))
                            }
                            className="h-5 w-5 border-2 border-slate-400 data-[state=checked]:bg-blue-600 data-[state=checked]:border-blue-600"
                          />
                          <div className="flex-1">
                            {isEditing ? (
                              <Input
                                value={editingVsVlPlanningText}
                                onChange={(e) => setEditingVsVlPlanningText(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === "Enter" && !savingVsVlPlanning) {
                                    void saveVsVlPlanningItem()
                                  } else if (e.key === "Escape") {
                                    cancelEditVsVlPlanningItem()
                                  }
                                }}
                                className="border-blue-500"
                                autoFocus
                              />
                            ) : (
                              <span className="text-sm font-semibold uppercase tracking-wide">{item.title}</span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                            {isEditing ? (
                              <>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => void saveVsVlPlanningItem()}
                                  disabled={savingVsVlPlanning}
                                >
                                  Save
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={cancelEditVsVlPlanningItem}
                                >
                                  Cancel
                                </Button>
                              </>
                            ) : (
                              <>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => startEditVsVlPlanningItem(item.id)}
                                >
                                  Edit
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => void deleteVsVlPlanningItem(item.id)}
                                  className="text-red-600 hover:text-red-700"
                                >
                                  Delete
                                </Button>
                              </>
                            )}
                          </div>
                        </div>
                      )
                    })}
                  {vsVlPlanningItems.length === 0 && (
                    <div className="text-sm text-muted-foreground text-center py-8">
                      No checklist items yet. Add one above.
                    </div>
                  )}
                </div>
              </div>
            </Card>
          ) : (
            <Card className="border-0 shadow-sm">
              <div className="p-4 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-base font-semibold">{VS_VL_PHASE_LABELS[vsVlPhase]} Tasks</div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-xs text-slate-600 border-slate-200 bg-white">
                      {VS_VL_PHASE_LABELS[vsVlPhase]}
                    </Badge>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 px-2 text-xs"
                      onClick={() => setShowVsVlAddTask((prev) => !prev)}
                    >
                      <Plus className="h-3 w-3 mr-1" />
                      Add task
                    </Button>
                  </div>
                </div>

                {/* Compact Add Task Form */}
                {showVsVlAddTask && (
                  <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-3 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Input
                        value={vsVlTaskTitle}
                        onChange={(e) => setVsVlTaskTitle(e.target.value)}
                        placeholder="Task title..."
                        className="h-8 text-sm flex-1 min-w-[200px]"
                      />
                      <Select value={vsVlTaskPriority} onValueChange={(v) => setVsVlTaskPriority(v as TaskPriority)}>
                        <SelectTrigger className="h-8 w-[100px] text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="NORMAL">NORMAL</SelectItem>
                          <SelectItem value="HIGH">I LARTE</SelectItem>
                        </SelectContent>
                      </Select>
                      <Select value={vsVlTaskStatus || "TODO"} onValueChange={(v) => setVsVlTaskStatus(v as Task["status"])}>
                        <SelectTrigger className="h-8 w-[100px] text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {PCM_SELECTABLE_STATUSES.map((status) => (
                            <SelectItem key={status} value={status}>
                              {statusLabel(status)}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button
                        size="sm"
                        className="h-8 px-3 text-xs"
                        disabled={creatingVsVlTask || !vsVlTaskTitle.trim()}
                        onClick={async () => {
                          if (!project || !vsVlTaskTitle.trim()) return
                          if (
                            vsVlTaskStatus === "DONE" &&
                            hasIncompleteChecklist
                          ) {
                            toast.error("Complete all checklist items before marking this task as done.")
                            return
                          }
                          setCreatingVsVlTask(true)
                          try {
                            const meta: VsVlTaskMeta = {
                              vs_vl_phase: vsVlPhase,
                              checklist: vsVlTaskChecklist.trim() || undefined,
                              comment: vsVlTaskComment.trim() || undefined,
                            }
                            const res = await apiFetch("/tasks", {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({
                                title: vsVlTaskTitle.trim(),
                                description: vsVlTaskDetail.trim() || null,
                                project_id: project.id,
                                department_id: project.department_id,
                                assignees: vsVlTaskAssignees,
                                dependency_task_id:
                                  vsVlTaskDependencyId === "__none__" ? null : vsVlTaskDependencyId,
                                status: vsVlTaskStatus || "TODO",
                                priority: vsVlTaskPriority,
                                phase: vsVlPhase,
                                due_date: vsVlTaskDate ? new Date(vsVlTaskDate).toISOString() : null,
                                is_deadline_important: vsVlTaskDeadlineImportant,
                                internal_notes: serializeVsVlMeta(meta),
                              }),
                            })
                            if (!res?.ok) {
                              toast.error("Failed to add task")
                              return
                            }
                            const created = (await res.json()) as Task
                            const reloaded = await reloadProjectTasks(project.id)
                            if (!reloaded) setTasks((prev) => [...prev, created])
                            setVsVlTaskTitle("")
                            setVsVlTaskDetail("")
                            setVsVlTaskDate("")
                            setVsVlTaskDeadlineImportant(false)
                            setVsVlTaskPriority("NORMAL")
                            setVsVlTaskStatus("TODO")
                            setVsVlTaskAssignees([])
                            setVsVlTaskDependencyId("__none__")
                            setVsVlTaskChecklist("")
                            setVsVlTaskComment("")
                            setShowVsVlAddTask(false)
                            toast.success("Task added")
                          } finally {
                            setCreatingVsVlTask(false)
                          }
                        }}
                      >
                        {creatingVsVlTask ? "..." : "Add"}
                      </Button>
                    </div>
                    <Textarea
                      value={vsVlTaskDetail}
                      onChange={(e) => setVsVlTaskDetail(e.target.value)}
                      placeholder="Description..."
                      rows={2}
                      className="text-xs border-slate-300 bg-white resize-none"
                    />
                    <label className="flex items-center gap-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm">
                      <Checkbox
                        checked={vsVlTaskDeadlineImportant}
                        onCheckedChange={(checked) => setVsVlTaskDeadlineImportant(checked === true)}
                      />
                      <span className="font-medium text-slate-700">Deadline important</span>
                    </label>
                  </div>
                )}

                <div className="space-y-2">
                  {orderedVsVlTasks.length ? (
                    orderedVsVlTasks.map((task, index) => {
                      const meta = parseVsVlMeta(task.internal_notes)
                      const titleKey = normalizeTaskTitle(task.title)
                      const isBaseTask = titleKey === VS_VL_TASK_TITLES.base
                      const dependencyId = isBaseTask
                        ? null
                        : task.dependency_task_id || meta?.dependency_task_id || null
                      const dependencyStatus = dependencyId ? taskStatusById.get(dependencyId) : null
                      const dependencyTask = dependencyId ? tasks.find((t) => t.id === dependencyId) : null

                      // Calculate lock status based on unlock_after_days from PROJECT start date
                      let isTimeLocked = false
                      let daysRemaining = 0
                      let unlockDateDisplay: Date | null = null

                      // Helper to add business days (skip weekends)
                      const addBusinessDays = (start: Date, days: number): Date => {
                        const result = new Date(start)
                        let addedDays = 0
                        while (addedDays < days) {
                          result.setDate(result.getDate() + 1)
                          const dayOfWeek = result.getDay()
                          // Skip Saturday (6) and Sunday (0)
                          if (dayOfWeek !== 0 && dayOfWeek !== 6) {
                            addedDays++
                          }
                        }
                        // If result lands on weekend, move to Monday
                        while (result.getDay() === 0 || result.getDay() === 6) {
                          result.setDate(result.getDate() + 1)
                        }
                        return result
                      }

                      // Time-based lock: task unlocks X business days after project start
                      if (meta?.unlock_after_days !== undefined && meta.unlock_after_days > 0 && project) {
                        const projectStart = new Date(project.start_date || project.created_at || Date.now())
                        const unlockDate = addBusinessDays(projectStart, meta.unlock_after_days)
                        unlockDateDisplay = unlockDate
                        const now = new Date()
                        // Reset time to start of day for comparison
                        now.setHours(0, 0, 0, 0)
                        unlockDate.setHours(0, 0, 0, 0)
                        isTimeLocked = now < unlockDate
                        if (isTimeLocked) {
                          // Calculate business days remaining
                          let remaining = 0
                          const temp = new Date(now)
                          while (temp < unlockDate) {
                            temp.setDate(temp.getDate() + 1)
                            if (temp.getDay() !== 0 && temp.getDay() !== 6) {
                              remaining++
                            }
                          }
                          daysRemaining = remaining
                        }
                      }

                      // Dependency-based lock: locked until dependency is DONE
                      const isDependencyNotDone = Boolean(dependencyId && dependencyStatus !== "DONE")

                      // Combined lock: if has unlock_after_days, must ALSO have dependency done (if exists)
                      // If no unlock_after_days, just check dependency
                      const isLocked = isTimeLocked || isDependencyNotDone
                      const selectedAssignees = taskAssigneeIds(task)
                      const commentValue = vsVlCommentEdits[task.id] ?? meta?.comment ?? ""
                      const checklistValue = vsVlChecklistEdits[task.id] ?? meta?.checklist ?? ""
                      const descriptionValue = vsVlDescriptionEdits[task.id] ?? task.description ?? ""
                      const isEditing = Boolean(vsVlEditMode[task.id])
                      return (
                        <div
                          key={task.id}
                          className={`rounded-lg border bg-white transition-shadow hover:shadow-sm ${isLocked
                              ? "border-amber-200 bg-amber-50/20"
                              : "border-slate-300 shadow-[0_0_0_1px_#cbd5e1]"
                            }`}
                        >
                          {/* Main Row - Compact */}
                          <div className="p-2.5 flex items-center gap-2">
                            {isLocked && (
                              <div
                                className="flex items-center gap-1 flex-shrink-0"
                                title={
                                  isTimeLocked && isDependencyNotDone
                                    ? `Locked: ${daysRemaining}d remaining + waiting for "${dependencyTask?.title || 'dependency'}"`
                                    : isTimeLocked
                                      ? `Unlocks in ${daysRemaining} business day(s)`
                                      : `Waiting for "${dependencyTask?.title || 'dependency'}" to complete`
                                }
                              >
                                <Lock className="h-3.5 w-3.5 text-amber-600" />
                                {daysRemaining > 0 && (
                                  <span className="text-xs text-amber-600 font-medium">{daysRemaining}d</span>
                                )}
                                {!isTimeLocked && isDependencyNotDone && (
                                  <span className="text-xs text-amber-600">dep</span>
                                )}
                              </div>
                            )}
                            <span className="text-xs font-semibold text-slate-400 flex-shrink-0">{index + 1}.</span>
                            <div className="flex-1 min-w-0">
                              <Input
                                key={`title-${task.id}-${task.updated_at}`}
                                defaultValue={task.title}
                                onBlur={(e) => {
                                  const nextValue = e.target.value.trim()
                                  if (!nextValue || nextValue === task.title) return
                                  void patchTask(task.id, { title: nextValue }, "Failed to update title")
                                }}
                                className={`h-auto text-sm font-semibold px-0 border-0 bg-transparent focus-visible:ring-1 focus-visible:ring-slate-300 ${!isEditing ? (isLocked ? "text-slate-600" : "text-slate-900 font-bold") : "text-slate-900"
                                  }`}
                                readOnly={!isEditing}
                                disabled={isLocked || !isEditing}
                              />
                            </div>
                            <Select
                              value={getProjectTaskType(task)}
                              onValueChange={(value) => {
                                if (isLocked || !isEditing) return
                                const nextTaskType = (value || "NORMAL").toUpperCase() as (typeof PROJECT_TASK_TYPES)[number]
                                if (nextTaskType === getProjectTaskType(task)) return
                                void patchTask(
                                  task.id,
                                  {
                                    priority: nextTaskType === "HIGH" ? "HIGH" : "NORMAL",
                                    is_1h_report: nextTaskType === "1H",
                                    is_r1: nextTaskType === "R1",
                                    is_personal: nextTaskType === "PERSONAL",
                                    is_bllok: nextTaskType === "BLLOK",
                                  },
                                  "Failed to update priority"
                                )
                              }}
                              disabled={isLocked || !isEditing}
                            >
                              <SelectTrigger
                                className={`h-7 min-w-[90px] text-xs px-2 flex-shrink-0 ${
                                  task.priority === "HIGH"
                                    ? "bg-rose-50 text-rose-700 border-rose-200"
                                    : task.is_1h_report
                                      ? "bg-amber-50 text-amber-700 border-amber-200"
                                      : task.is_r1
                                        ? "bg-sky-50 text-sky-700 border-sky-200"
                                        : task.is_personal
                                          ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                          : task.is_bllok
                                            ? "bg-slate-200 text-slate-700 border-slate-300"
                                            : "bg-slate-50 text-slate-700 border-slate-200"
                                }`}
                              >
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {PROJECT_TASK_TYPES.map((type) => (
                                  <SelectItem key={type} value={type}>
                                    {type === "HIGH" ? "I LARTE" : type === "PERSONAL" ? "P" : type}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                            <Select
                              value={task.status || "TODO"}
                              onValueChange={(value) => {
                                if (isLocked || !isEditing) return
                                if (
                                  value === "DONE" &&
                                  hasIncompleteChecklist
                                ) {
                                  toast.error("Complete all checklist items before marking this task as done.")
                                  return
                                }
                                void patchTask(task.id, { status: value }, "Failed to update status")
                              }}
                              disabled={isLocked || !isEditing}
                            >
                              <SelectTrigger
                                className={`h-7 min-w-[90px] text-xs px-2 flex-shrink-0 ${task.status === "DONE"
                                    ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                    : task.status === "WAITING_CONFIRMATION"
                                      ? "bg-blue-50 text-blue-700 border-blue-200"
                                    : task.status === "IN_PROGRESS"
                                      ? "bg-amber-50 text-amber-700 border-amber-200"
                                      : "bg-slate-50 text-slate-700 border-slate-200"
                                  }`}
                              >
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {task.status === LEGACY_WAITING_STATUS ? (
                                  <SelectItem value={LEGACY_WAITING_STATUS} disabled>
                                    {statusLabel(LEGACY_WAITING_STATUS)}
                                  </SelectItem>
                                ) : null}
                                {PCM_SELECTABLE_STATUSES.map((status) => (
                                  <SelectItem key={status} value={status}>
                                    {statusLabel(status)}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                            {task.due_date && (
                              <div className="flex items-center gap-0.5 text-[10px] text-slate-500 flex-shrink-0" title="Due date">
                                <Calendar className="h-3 w-3" />
                                <span>{formatDateDisplay(task.due_date)}</span>
                              </div>
                            )}
                            <div className="flex items-center gap-1 flex-shrink-0">
                              {selectedAssignees.slice(0, 3).map((id, idx) => {
                                const user = userMap.get(id)
                                const label = user?.full_name || user?.username || user?.email || "-"
                                const colorClass = [
                                  "bg-blue-500 text-white",
                                  "bg-emerald-500 text-white",
                                  "bg-amber-500 text-white",
                                  "bg-rose-500 text-white",
                                  "bg-purple-500 text-white",
                                ][idx % 5]
                                return (
                                  <div
                                    key={id}
                                    className={`h-6 w-6 rounded-full flex items-center justify-center text-[9px] font-semibold ring-1 ring-slate-200 ${colorClass}`}
                                    title={label}
                                  >
                                    {initials(label)}
                                  </div>
                                )
                              })}
                              {selectedAssignees.length > 3 && (
                                <span className="text-[10px] text-slate-500">+{selectedAssignees.length - 3}</span>
                              )}
                              {selectedAssignees.length === 0 && (
                                <div className="h-6 w-6 rounded-full bg-slate-200 flex items-center justify-center" title="Unassigned">
                                  <Users className="h-3 w-3 text-slate-400" />
                                </div>
                              )}
                            </div>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-6 w-6 flex-shrink-0"
                              onClick={() =>
                                setVsVlEditMode((prev) => ({ ...prev, [task.id]: !prev[task.id] }))
                              }
                              aria-label={isEditing ? "Done editing" : "Edit task"}
                              title={isEditing ? "Done" : "Edit"}
                            >
                              {isEditing ? (
                                <Check className="h-3 w-3 text-emerald-600" />
                              ) : (
                                <Pencil className="h-3 w-3 text-slate-600" />
                              )}
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-6 w-6 text-red-600 hover:bg-red-50 flex-shrink-0"
                              onClick={async () => {
                                if (!(await confirmDeleteTask())) return
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
                              aria-label="Delete task"
                              title="Delete"
                            >
                              <Trash2 className="h-3 w-3" />
                            </Button>
                          </div>

                          {/* Expandable Details - Only when editing */}
                          {isEditing && (
                            <div className="border-t border-slate-100 p-2.5 space-y-2 bg-slate-50/30">
                              <div className="grid gap-2 md:grid-cols-[2fr_1fr]">
                                <div>
                                  <Label className="text-[10px] font-medium text-slate-600 mb-1 block">Description</Label>
                                  <Textarea
                                    value={descriptionValue}
                                    onChange={(e) => {
                                      const newValue = e.target.value
                                      setVsVlDescriptionEdits((prev) => ({ ...prev, [task.id]: newValue }))
                                      queueDescriptionSave(task.id, newValue)
                                    }}
                                    rows={2}
                                    className="text-xs border-slate-300 bg-white resize-none h-auto"
                                    placeholder="Description..."
                                  />
                                </div>
                                <div className="space-y-2">
                                  <div>
                                    <Label className="text-[10px] font-medium text-slate-600 mb-1 block">Due date</Label>
                                    <Input
                                      value={toDateInput(task.due_date)}
                                      onChange={(e) => {
                                        const nextValue = normalizeDueDateInput(e.target.value)
                                        const dueDate = nextValue ? new Date(nextValue).toISOString() : null
                                        const meta = buildVsVlMeta(task, { manual_due_date: Boolean(nextValue) })
                                        void patchTask(
                                          task.id,
                                          { due_date: dueDate, internal_notes: meta },
                                          "Failed to update date"
                                        )
                                      }}
                                      type="date"
                                      className="h-7 text-xs border-slate-300 bg-white"
                                    />
                                  </div>
                                  <div>
                                    <Label className="text-[10px] font-medium text-slate-600 mb-1 block">Dependency</Label>
                                    <Select
                                      value={
                                        isBaseTask ? "__none__" : task.dependency_task_id || meta?.dependency_task_id || "__none__"
                                      }
                                      onValueChange={(value) => {
                                        void patchTask(
                                          task.id,
                                          { dependency_task_id: value === "__none__" ? null : value },
                                          "Failed to update dependency"
                                        )
                                      }}
                                      disabled={isBaseTask}
                                    >
                                      <SelectTrigger className="h-7 text-xs border-slate-300 bg-white">
                                        <SelectValue placeholder="-" />
                                      </SelectTrigger>
                                      <SelectContent>
                                        <SelectItem value="__none__">-</SelectItem>
                                        {dependencyOptions
                                          .filter((opt) => opt.id !== task.id)
                                          .map((opt) => (
                                            <SelectItem key={opt.id} value={opt.id}>
                                              {opt.title}
                                            </SelectItem>
                                          ))}
                                      </SelectContent>
                                    </Select>
                                  </div>
                                  <div>
                                    <Label className="text-[10px] font-medium text-slate-600 mb-1 block">Unlock on day</Label>
                                    <Input
                                      type="number"
                                      min={0}
                                      placeholder="0"
                                      defaultValue={meta?.unlock_after_days || ""}
                                      className="h-7 text-xs border-slate-300 bg-white w-20"
                                      disabled={isBaseTask}
                                      onBlur={(e) => {
                                        const value = parseInt(e.target.value, 10)
                                        const newValue = isNaN(value) || value <= 0 ? undefined : value
                                        if (newValue === meta?.unlock_after_days) return
                                        void updateVsVlMeta(task, { unlock_after_days: newValue })
                                      }}
                                    />
                                  </div>
                                </div>
                              </div>
                              <div className="flex items-center justify-between">
                                <Label className="text-[10px] font-medium text-slate-700">Assignees</Label>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="text-[10px] h-5 px-2"
                                  onClick={() =>
                                    setVsVlAssigneeOpen((prev) => ({ ...prev, [task.id]: !prev[task.id] }))
                                  }
                                >
                                  {vsVlAssigneeOpen[task.id] ? "Hide" : "Manage"}
                                </Button>
                              </div>
                              {vsVlAssigneeOpen[task.id] && (
                                <div className="rounded border border-slate-200 bg-white p-1.5 space-y-1 max-h-32 overflow-y-auto">
                                  {assignableUsers.length ? (
                                    assignableUsers.map((u) => {
                                      const checked = selectedAssignees.includes(u.id)
                                      return (
                                        <label
                                          key={u.id}
                                          className="flex items-center gap-1.5 p-1 rounded hover:bg-slate-50 transition-colors cursor-pointer"
                                        >
                                          <Checkbox
                                            checked={checked}
                                            onCheckedChange={() => {
                                              const nextIds = checked
                                                ? selectedAssignees.filter((id) => id !== u.id)
                                                : [...selectedAssignees, u.id]
                                              void patchTask(task.id, { assignees: nextIds }, "Failed to update assignees")
                                            }}
                                            className="h-3.5 w-3.5"
                                          />
                                          <span className="text-[10px] text-slate-700 flex-1">
                                            {u.full_name || u.username || u.email}
                                          </span>
                                        </label>
                                      )
                                    })
                                  ) : (
                                    <div className="text-[10px] text-slate-400 text-center py-1">No users available</div>
                                  )}
                                </div>
                              )}
                              <div className="grid gap-2 md:grid-cols-2">
                                <div>
                                  <Label className="text-[10px] font-medium text-slate-600 mb-1 block">Comment</Label>
                                  <Textarea
                                    value={commentValue}
                                    onChange={(e) => {
                                      const nextValue = e.target.value
                                      setVsVlCommentEdits((prev) => ({ ...prev, [task.id]: nextValue }))
                                      if (isLocked) return
                                      const checklist = (vsVlChecklistEdits[task.id] ?? meta?.checklist ?? "").trim()
                                      queueVsVlMetaSave(task, {
                                        comment: nextValue.trim() || undefined,
                                        checklist: checklist || undefined,
                                      })
                                    }}
                                    onBlur={async (e) => {
                                      if (isLocked) return
                                      const nextValue = e.target.value.trim()
                                      const currentValue = meta?.comment || ""
                                      if (nextValue === currentValue) return
                                      const checklist = (vsVlChecklistEdits[task.id] ?? meta?.checklist ?? "").trim()
                                      const updated = await updateVsVlMeta(task, {
                                        comment: nextValue || undefined,
                                        checklist: checklist || undefined,
                                      })
                                      if (updated) {
                                        setVsVlCommentEdits((prev) => ({ ...prev, [task.id]: nextValue }))
                                      }
                                    }}
                                    placeholder="Koment..."
                                    rows={2}
                                    className="text-xs border-slate-300 bg-white resize-none"
                                  />
                                </div>
                                <div>
                                  <Label className="text-[10px] font-medium text-slate-600 mb-1 block">Checklist</Label>
                                  <Textarea
                                    value={checklistValue}
                                    onChange={(e) => {
                                      const nextValue = e.target.value
                                      setVsVlChecklistEdits((prev) => ({ ...prev, [task.id]: nextValue }))
                                      if (isLocked) return
                                      const comment = (vsVlCommentEdits[task.id] ?? meta?.comment ?? "").trim()
                                      queueVsVlMetaSave(task, {
                                        checklist: nextValue.trim() || undefined,
                                        comment: comment || undefined,
                                      })
                                    }}
                                    onBlur={async (e) => {
                                      if (isLocked) return
                                      const nextValue = e.target.value.trim()
                                      const currentValue = meta?.checklist || ""
                                      if (nextValue === currentValue) return
                                      const comment = (vsVlCommentEdits[task.id] ?? meta?.comment ?? "").trim()
                                      const updated = await updateVsVlMeta(task, {
                                        checklist: nextValue || undefined,
                                        comment: comment || undefined,
                                      })
                                      if (updated) {
                                        setVsVlChecklistEdits((prev) => ({ ...prev, [task.id]: nextValue }))
                                      }
                                    }}
                                    placeholder="Checklist..."
                                    rows={2}
                                    className="text-xs border-slate-300 bg-white resize-none"
                                  />
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      )
                    })
                  ) : (
                    <div className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">
                      No tasks yet.
                    </div>
                  )}
                </div>
              </div>
            </Card>
          )}
        </div>
        {renderEditDueDateDialog()}
        {renderStartDateDialog()}
        {renderEditStartDateDialog()}
        {renderCloseConfirmDialog()}
      </>
    )
  }

  if (isMstLike) {
    const planningTopItems = planningItemsOrdered.slice(0, 2)
    const planningOtherItems = planningItemsOrdered.slice(2)
    const planningIndexMap = new Map(
      planningItemsOrdered.map((item, index) => [item.id, index + 1])
    )
    const isFinalizationComplete =
      finalizationItems.length > 0 &&
      Object.values(finalizationChecks).filter(Boolean).length === finalizationItems.length
    const canCloseFromFinal = mstPhase === "FINAL" && isMstLike
    const togglePlanning = async (item: ChecklistItem) => {
      const newChecked = !mstPlanningChecks[item.id]
      setMstPlanningChecks((prev) => ({ ...prev, [item.id]: newChecked }))
      setDescriptionChecks((prev) => ({ ...prev, [item.id]: newChecked }))
      setChecklistItems((prev) =>
        prev.map((entry) => (entry.id === item.id ? { ...entry, is_checked: newChecked } : entry))
      )

      try {
        await apiFetch(`/checklist-items/${item.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_checked: newChecked }),
        })
      } catch {
        // Silently handle errors - update might still succeed
      }
    }

    const startEditPlanningItem = (item: ChecklistItem) => {
      setEditingPlanningItemId(item.id)
      setEditingPlanningItemText(item.title || "")
      setEditingPlanningItemNumber(item.position ? String(item.position) : "")
    }

    const cancelEditPlanningItem = () => {
      setEditingPlanningItemId(null)
      setEditingPlanningItemText("")
      setEditingPlanningItemNumber("")
    }

    const savePlanningItem = async () => {
      if (!editingPlanningItemId) return
      const title = editingPlanningItemText.trim()
      if (!title) return
      const rawNumber = editingPlanningItemNumber.trim()
      let position: number | undefined
      if (rawNumber) {
        const parsed = Number.parseInt(rawNumber, 10)
        if (Number.isNaN(parsed) || parsed < 1) {
          toast.error("Invalid order number")
          return
        }
        position = parsed
      }
      setSavingPlanningItem(true)
      try {
        const res = await apiFetch(`/checklist-items/${editingPlanningItemId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title, position }),
        })
        if (!res.ok) {
          toast.error("Failed to update checklist item")
          return
        }
        const updated = (await res.json()) as ChecklistItem
        setChecklistItems((prev) => prev.map((entry) => (entry.id === updated.id ? updated : entry)))
        cancelEditPlanningItem()
        toast.success("Checklist item updated")
      } finally {
        setSavingPlanningItem(false)
      }
    }

    const deletePlanningItem = async (item: ChecklistItem) => {
      const res = await apiFetch(`/checklist-items/${item.id}`, { method: "DELETE" })
      if (!res.ok) {
        toast.error("Failed to delete checklist item")
        return
      }
      setChecklistItems((prev) => prev.filter((entry) => entry.id !== item.id))
      if (editingPlanningItemId === item.id) {
        cancelEditPlanningItem()
      }
      toast.success("Checklist item deleted")
    }

    const addPlanningItem = async () => {
      if (!project) return
      const text = newPlanningItemText.trim()
      if (!text) return
      const rawNumber = newPlanningItemNumber.trim()
      setAddingPlanningItem(true)
      try {
        const maxPosition = planningItems.reduce(
          (max, item) => Math.max(max, item.position ?? 0),
          0
        )
        let position = maxPosition + 1
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
            path: "PLANNING",
            title: text,
            keyword: "PLANNING",
            description: text,
            category: "PLANNING",
            is_checked: false,
            position,
          }),
        })
        if (!res.ok) {
          toast.error("Failed to add checklist item")
          return
        }
        const created = (await res.json()) as ChecklistItem
        setChecklistItems((prev) => [...prev, created])
        setNewPlanningItemNumber("")
        setNewPlanningItemText("")
        toast.success("Checklist item added")
      } finally {
        setAddingPlanningItem(false)
      }
    }
    const activeMstChecklistItems = isMstTemplateEditor
      ? (mstTemplateChecklist?.items || []).filter((item) => item.item_type === "CHECKBOX" && item.path && item.title)
      : mstChecklistItems

    const mstChecklistRows = activeMstChecklistItems
      .map((item, index) => {
        const key = `${item.path}|${item.title}`
        const templateRow = templateOrderMap.has(key)
          ? mstTemplateRows[templateOrderMap.get(key) as number]
          : null
        const order = templateOrderMap.has(key)
          ? (templateOrderMap.get(key) as number)
          : templateOrderMap.size + (item.position ?? 0)
        return {
          key,
          order,
          item,
          number: String(index + 1),
          path: item.path || "",
          detyrat: item.title || "",
          keywords: item.keyword || "",
          pershkrimi: item.description || "",
          kategoria: item.category || "",
          original: item.original || "",
          incl: item.owner || templateRow?.incl || "",
        }
      })
      .sort((a, b) => {
        if (a.order !== b.order) return a.order - b.order
        return a.detyrat.localeCompare(b.detyrat)
      })

    // Initialize checked state from database (moved outside to avoid hook issues)

    const toggleFinalChecklist = async (item: ChecklistItem) => {
      if (!item.id || !item.path || !item.title) return
      const key = `${item.path}|${item.title}`
      const newChecked = !mstChecklistChecked[key]
      setMstChecklistChecked((prev) => ({ ...prev, [key]: newChecked }))
      setChecklistItems((prev) =>
        prev.map((i) => (i.id === item.id ? { ...i, is_checked: newChecked } : i))
      )
      try {
        const res = await apiFetch(`/checklist-items/${item.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_checked: newChecked }),
        })
        if (!res.ok && res.status !== 503) {
          let errorMessage = "Failed to update checklist"
          try {
            const errorData = await res.json()
            if (errorData.detail) {
              if (typeof errorData.detail === "string") {
                errorMessage = errorData.detail
              } else if (Array.isArray(errorData.detail)) {
                errorMessage = errorData.detail.map((e: any) => e.msg || String(e)).join(", ")
              } else {
                errorMessage = String(errorData.detail)
              }
            }
          } catch {
            errorMessage = `${errorMessage} (${res.status})`
          }
          toast.error(errorMessage)
        } else if (res.ok) {
          const updated = (await res.json()) as ChecklistItem
          setChecklistItems((prev) => prev.map((i) => (i.id === item.id ? updated : i)))
        }
      } catch (error) {
        console.error("Error updating checklist (may still succeed):", error)
      }
    }

    const updateMstChecklistComment = async (item: ChecklistItem, comment: string) => {
      if (!item.id || !item.path || !item.title) return
      const key = `${item.path}|${item.title}`
      const previousComment = item.comment || ""
      setMstChecklistComments((prev) => ({ ...prev, [key]: comment }))
      setChecklistItems((prev) =>
        prev.map((i) => (i.id === item.id ? { ...i, comment } : i))
      )

      try {
        const res = await apiFetch(`/checklist-items/${item.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ comment: comment || null }),
        })
        if (!res.ok) {
          const errorData = await res.json().catch(() => ({}))
          const detail = errorData.detail
          const errorMsg = typeof detail === "string"
            ? detail
            : Array.isArray(detail)
              ? detail.map((e: any) => e.msg || String(e)).join(", ")
              : "Failed to save comment"
          toast.error(errorMsg)
          setMstChecklistComments((prev) => ({ ...prev, [key]: previousComment }))
          setChecklistItems((prev) =>
            prev.map((i) => (i.id === item.id ? { ...i, comment: previousComment || null } : i))
          )
        }
      } catch (error) {
        toast.error("Failed to save comment")
        setMstChecklistComments((prev) => ({ ...prev, [key]: previousComment }))
        setChecklistItems((prev) =>
          prev.map((i) => (i.id === item.id ? { ...i, comment: previousComment || null } : i))
        )
      }
    }

    const queueMstCommentSave = (item: ChecklistItem, comment: string) => {
      if (!item.path || !item.title) return
      const key = `${item.path}|${item.title}`
      const timers = mstCommentTimersRef.current
      if (timers[key]) {
        clearTimeout(timers[key])
      }
      timers[key] = setTimeout(() => {
        void updateMstChecklistComment(item, comment)
      }, 600)
    }

    const startEditMstChecklistRow = (row: {
      key: string
      number: string
      path: string
      detyrat: string
      keywords: string
      pershkrimi: string
      kategoria: string
      original: string
      incl: string
    }) => {
      setEditingMstChecklistKey(row.key)
      setEditingMstChecklistRow({
        number: row.number,
        path: row.path,
        detyrat: row.detyrat,
        keywords: row.keywords,
        pershkrimi: row.pershkrimi,
        kategoria: row.kategoria,
        original: row.original,
        incl: row.incl || "DV, DM",
      })
    }

    const cancelEditMstChecklistRow = () => {
      setEditingMstChecklistKey(null)
      setEditingMstChecklistRow({
        number: "",
        path: "",
        detyrat: "",
        keywords: "",
        pershkrimi: "",
        kategoria: "",
        original: "",
        incl: "DV, DM",
      })
    }

    const saveMstChecklistRow = async (row: { key: string; item: ChecklistItem }) => {
      const path = editingMstChecklistRow.path.trim()
      const title = editingMstChecklistRow.detyrat.trim()
      if (!path || !stripChecklistInlineStyleTokens(title).trim()) {
        toast.error("Path and detyrat are required.")
        return
      }
      const rawNumber = editingMstChecklistRow.number.trim()
      let position: number | undefined
      if (rawNumber) {
        const parsed = Number.parseInt(rawNumber, 10)
        if (Number.isNaN(parsed) || parsed < 1) {
          toast.error("Invalid position number")
          return
        }
        position = parsed
      }
      setSavingMstChecklistRow(true)
      try {
        const payload = {
          path,
          title,
          keyword: editingMstChecklistRow.keywords.trim() || null,
          description: editingMstChecklistRow.pershkrimi.trim() || null,
          category: editingMstChecklistRow.kategoria.trim() || null,
          ...(showMstOriginalColumn ? { original: editingMstChecklistRow.original.trim() } : {}),
          owner: editingMstChecklistRow.incl.trim() || "DV, DM",
          position,
        }
        if (row.item?.id) {
          const res = await apiFetch(`/checklist-items/${row.item.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          })
          if (!res.ok) {
            toast.error("Failed to update checklist row")
            return
          }
          if (isMstTemplateEditor) {
            await loadMstTemplateChecklist()
          } else if (project?.id) {
            const reloadRes = await apiFetch(`/checklist-items?project_id=${project.id}`)
            if (reloadRes.ok) {
              setChecklistItems((await reloadRes.json()) as ChecklistItem[])
            }
          }
          const updated = (await res.json()) as ChecklistItem
          const oldKey = row.key
          const newKey = `${updated.path}|${updated.title}`
          if (oldKey !== newKey) {
            setMstChecklistChecked((prev) => {
              if (!(oldKey in prev)) return prev
              const next = { ...prev }
              next[newKey] = next[oldKey]
              delete next[oldKey]
              return next
            })
            setMstChecklistComments((prev) => {
              if (!(oldKey in prev)) return prev
              const next = { ...prev }
              next[newKey] = next[oldKey]
              delete next[oldKey]
              return next
            })
          }
        }
        cancelEditMstChecklistRow()
        toast.success("Checklist row saved")
      } finally {
        setSavingMstChecklistRow(false)
      }
    }

    const deleteMstChecklistRow = async (row: { key: string; item: ChecklistItem }) => {
      if (!row.item?.id) return
      const res = await apiFetch(`/checklist-items/${row.item.id}`, { method: "DELETE" })
      if (!res.ok) {
        toast.error("Failed to delete checklist row")
        return
      }
      if (isMstTemplateEditor) {
        setMstTemplateChecklist((prev) => {
          if (!prev) return prev
          return {
            ...prev,
            items: prev.items.filter((i) => i.id !== row.item.id),
          }
        })
      } else {
        setChecklistItems((prev) => prev.filter((i) => i.id !== row.item.id))
      }
      setMstChecklistChecked((prev) => {
        if (!(row.key in prev)) return prev
        const next = { ...prev }
        delete next[row.key]
        return next
      })
      setMstChecklistComments((prev) => {
        if (!(row.key in prev)) return prev
        const next = { ...prev }
        delete next[row.key]
        return next
      })
      toast.success("Checklist row deleted")
    }

    const addMstChecklistRow = async () => {
      const path = newMstChecklistRow.path.trim()
      const title = newMstChecklistRow.detyrat.trim()
      if (!path || !stripChecklistInlineStyleTokens(title).trim()) {
        toast.error("Path and detyrat are required.")
        return
      }
      const rawNumber = newMstChecklistRow.number.trim()
      let position: number | undefined
      if (rawNumber) {
        const parsed = Number.parseInt(rawNumber, 10)
        if (Number.isNaN(parsed) || parsed < 1) {
          toast.error("Invalid position number")
          return
        }
        position = parsed
      }
      const targetChecklistId = isMstTemplateEditor ? mstTemplateChecklist?.id : null
      if (!project && !targetChecklistId) return
      setSavingMstChecklistRow(true)
      try {
        const maxPosition = activeMstChecklistItems.reduce(
          (max, item) => Math.max(max, item.position ?? 0),
          templateOrderMap.size
        )
        const res = await apiFetch("/checklist-items", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: isMstTemplateEditor ? undefined : project?.id,
            checklist_id: targetChecklistId || undefined,
            item_type: "CHECKBOX",
            path,
            title,
            keyword: newMstChecklistRow.keywords.trim() || null,
            description: newMstChecklistRow.pershkrimi.trim() || null,
            category: newMstChecklistRow.kategoria.trim() || null,
            ...(showMstOriginalColumn ? { original: newMstChecklistRow.original.trim() } : {}),
            owner: newMstChecklistRow.incl.trim() || "DV, DM",
            is_checked: false,
            position: position ?? (maxPosition + 1),
          }),
        })
        if (!res.ok) {
          toast.error("Failed to add checklist row")
          return
        }
        if (isMstTemplateEditor) {
          await loadMstTemplateChecklist()
        } else if (project?.id) {
          const reloadRes = await apiFetch(`/checklist-items?project_id=${project.id}`)
          if (reloadRes.ok) {
            setChecklistItems((await reloadRes.json()) as ChecklistItem[])
          }
        }
        setNewMstChecklistRow({
          number: "",
          path: "",
          detyrat: "",
          keywords: "",
          pershkrimi: "",
          kategoria: "",
          original: "",
          incl: "DV, DM",
        })
        toast.success("Checklist row added")
      } finally {
        setSavingMstChecklistRow(false)
      }
    }
    const toggleFinalizationChecklist = async (itemId: string, nextChecked: boolean) => {
      if (!project) return
      const item = finalizationItems.find((i) => i.id === itemId)
      if (!item) return

      const previousValue = item.is_checked || false
      setFinalizationChecks((prev) => ({ ...prev, [itemId]: nextChecked }))
      setFinalizationItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, is_checked: nextChecked } : i)))
      setChecklistItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, is_checked: nextChecked } : i)))

      try {
        const res = await apiFetch(`/checklist-items/${itemId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_checked: nextChecked }),
        })
        if (!res.ok) {
          toast.error("Failed to save checklist")
          setFinalizationChecks((prev) => ({ ...prev, [itemId]: previousValue }))
          setFinalizationItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, is_checked: previousValue } : i)))
          setChecklistItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, is_checked: previousValue } : i)))
        } else {
          const updated = (await res.json()) as ChecklistItem
          setChecklistItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)))
          setFinalizationItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)))
        }
      } catch {
        toast.error("Failed to save checklist")
        setFinalizationChecks((prev) => ({ ...prev, [itemId]: previousValue }))
        setFinalizationItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, is_checked: previousValue } : i)))
        setChecklistItems((prev) => prev.map((i) => (i.id === itemId ? { ...i, is_checked: previousValue } : i)))
      }
    }

    const addFinalizationItem = async () => {
      if (!project || !newFinalizationText.trim()) return
      setSavingFinalization(true)
      try {
        const rawNumber = newFinalizationNumber.trim()
        const position = finalizationItems.length > 0
          ? Math.max(...finalizationItems.map((item) => item.position ?? 0)) + 1
          : 1
        let nextPosition = position
        if (rawNumber) {
          const parsed = Number.parseInt(rawNumber, 10)
          if (Number.isNaN(parsed) || parsed < 1) {
            toast.error("Invalid order number")
            return
          }
          nextPosition = parsed
        }

        const res = await apiFetch("/checklist-items", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: project.id,
            item_type: "CHECKBOX",
            path: FINALIZATION_PATH,
            title: newFinalizationText.trim(),
            keyword: FINALIZATION_PATH,
            description: newFinalizationText.trim(),
            category: FINALIZATION_PATH,
            is_checked: false,
            position: nextPosition,
          }),
        })
        if (!res.ok) {
          toast.error("Failed to add checklist item")
          return
        }
        const created = (await res.json()) as ChecklistItem
        setChecklistItems((prev) => [...prev, created])
        setFinalizationItems((prev) => [...prev, created])
        setFinalizationChecks((prev) => ({ ...prev, [created.id]: false }))
        setNewFinalizationNumber("")
        setNewFinalizationText("")
        toast.success("Checklist item added")
      } catch {
        toast.error("Failed to add checklist item")
      } finally {
        setSavingFinalization(false)
      }
    }

    const startEditFinalizationItem = (itemId: string) => {
      const item = finalizationItems.find((i) => i.id === itemId)
      if (!item) return
      setEditingFinalizationId(itemId)
      setEditingFinalizationText(item.title || "")
      setEditingFinalizationNumber(item.position ? String(item.position) : "")
    }

    const cancelEditFinalizationItem = () => {
      setEditingFinalizationId(null)
      setEditingFinalizationText("")
      setEditingFinalizationNumber("")
    }

    const saveFinalizationItem = async () => {
      if (!editingFinalizationId || !editingFinalizationText.trim()) return
      const rawNumber = editingFinalizationNumber.trim()
      let position: number | undefined
      if (rawNumber) {
        const parsed = Number.parseInt(rawNumber, 10)
        if (Number.isNaN(parsed) || parsed < 1) {
          toast.error("Invalid order number")
          return
        }
        position = parsed
      }
      setSavingFinalization(true)
      try {
        const res = await apiFetch(`/checklist-items/${editingFinalizationId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: editingFinalizationText.trim(), position }),
        })
        if (!res.ok) {
          toast.error("Failed to update checklist item")
          return
        }
        const updated = (await res.json()) as ChecklistItem
        setChecklistItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)))
        setFinalizationItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)))
        cancelEditFinalizationItem()
        toast.success("Checklist item updated")
      } catch {
        toast.error("Failed to update checklist item")
      } finally {
        setSavingFinalization(false)
      }
    }

    const deleteFinalizationItem = async (itemId: string) => {
      const res = await apiFetch(`/checklist-items/${itemId}`, { method: "DELETE" })
      if (!res.ok) {
        toast.error("Failed to delete checklist item")
        return
      }
      setChecklistItems((prev) => prev.filter((i) => i.id !== itemId))
      setFinalizationItems((prev) => prev.filter((i) => i.id !== itemId))
      setFinalizationChecks((prev) => {
        const next = { ...prev }
        delete next[itemId]
        return next
      })
      toast.success("Checklist item deleted")
    }

    const startEditTask = (task: Task) => {
      // Find the latest task from state to ensure we have the most recent data
      const latestTask = tasks.find((t) => t.id === task.id) || task
      setEditingTaskId(latestTask.id)
      setEditingTaskTitle(latestTask.title || "")
      setEditingTaskAssignee(latestTask.assigned_to || "__unassigned__")
      // Set start date for editing (format: YYYY-MM-DD for input[type=date])
      setEditingTaskStartDate(latestTask.start_date ? latestTask.start_date.split("T")[0] : "")
      // Set due date for editing (format: YYYY-MM-DD for input[type=date])
      setEditingTaskDueDate(latestTask.due_date ? latestTask.due_date.split("T")[0] : "")
      setEditingTaskFinishPeriod(latestTask.finish_period || FINISH_PERIOD_NONE_VALUE)
      const notes = latestTask.internal_notes || ""
      const totalMatch = notes.match(/total_products=(\d+)/)
      const completedMatch = notes.match(/completed_products=(\d+)/)

      // Get TOTAL from origin task if CONTROL phase
      let totalValue = latestTask.daily_products?.toString() || totalMatch?.[1] || controlEdits[latestTask.id]?.total || "0"
      if (latestTask.phase === "CONTROL") {
        const originTaskId = getOriginTaskId(notes)
        if (originTaskId) {
          const originTask = tasks.find((t) => t.id === originTaskId)
          if (originTask?.daily_products != null) {
            totalValue = originTask.daily_products.toString()
          }
        }
      }

      setEditingTaskTotal(totalValue)
      setEditingTaskCompleted(
        controlEdits[latestTask.id]?.completed || completedMatch?.[1] || "0"
      )
      // Initialize KO user ID from internal_notes
      const koUserId = parseKoUserId(notes)
      setEditingTaskKoUserId(koUserId || "__unassigned__")
      // Initialize production date from internal_notes
      const productionDate = parseProductionDate(notes)
      setEditingTaskProductionDate(productionDate || "")
    }

    const cancelEditTask = () => {
      setEditingTaskId(null)
      setEditingTaskTitle("")
      setEditingTaskAssignee("__unassigned__")
      setEditingTaskKoUserId("__unassigned__")
      setEditingTaskStartDate("")
      setEditingTaskDueDate("")
      setEditingTaskFinishPeriod(FINISH_PERIOD_NONE_VALUE)
      setEditingTaskTotal("")
      setEditingTaskCompleted("")
      setEditingTaskProductionDate("")
    }

    const saveTaskEdit = async () => {
      if (!editingTaskId || !editingTaskTitle.trim() || !project) return
      setSavingTaskEdit(true)
      try {
        const task = tasks.find((t) => t.id === editingTaskId)
        if (!task) return

        const currentNotes = task.internal_notes || ""
        const completedMatch = currentNotes.match(/completed_products=(\d+)/)
        const completed =
          editingTaskCompleted || controlEdits[task.id]?.completed || completedMatch?.[1] || "0"

        // Get TOTAL from origin task if CONTROL phase
        let totalValue = editingTaskTotal || controlEdits[task.id]?.total || "0"
        if (task.phase === "CONTROL") {
          const originTaskId = getOriginTaskId(currentNotes)
          if (originTaskId) {
            const originTask = tasks.find((t) => t.id === originTaskId)
            if (originTask?.daily_products != null) {
              totalValue = originTask.daily_products.toString()
            }
          }
        }
        const totalNum = toNonNegativeInt(totalValue)
        const completedNum = toNonNegativeInt(completed)
        const nextStatus = computeStatusFromCompleted(totalNum, completedNum)

        // Preserve origin_task_id if it exists
        const originTaskId = getOriginTaskId(currentNotes)
        const productionDate = editingTaskProductionDate || parseProductionDate(currentNotes) || null
        const internalNotes = serializeInternalNotes({
          originTaskId: originTaskId || undefined,
          total: totalValue,
          completed,
          koUserId: editingTaskKoUserId === "__unassigned__" ? null : editingTaskKoUserId,
          productionDate,
        })

        const res = await apiFetch(`/tasks/${editingTaskId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: editingTaskTitle.trim(),
            assigned_to: task.phase === "CONTROL"
              ? (editingTaskKoUserId === "__unassigned__" ? null : editingTaskKoUserId)
              : (editingTaskAssignee === "__unassigned__" ? null : editingTaskAssignee),
            start_date: editingTaskStartDate ? new Date(editingTaskStartDate).toISOString() : null,
            due_date: task.phase === "CONTROL" && productionDate
              ? new Date(productionDate).toISOString()
              : (editingTaskDueDate ? new Date(editingTaskDueDate).toISOString() : null),
            finish_period:
              editingTaskFinishPeriod === FINISH_PERIOD_NONE_VALUE ? null : editingTaskFinishPeriod,
            daily_products: totalNum,
            internal_notes: internalNotes,
          }),
        })
        if (!res.ok) {
          let detail = "Failed to update task"
          try {
            const data = (await res.json()) as { detail?: unknown }
            if (typeof data?.detail === "string" && data.detail.trim()) {
              detail = data.detail
            } else if (Array.isArray(data?.detail)) {
              detail = data.detail.map((e: any) => e.msg || String(e)).join(", ")
            }
          } catch {
            // ignore parse errors
          }
          toast.error(detail)
          return
        }
        const updated = (await res.json()) as Task
        setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))
        setControlEdits((prev) => ({
          ...prev,
          [updated.id]: {
            ...prev[updated.id],
            total: editingTaskTotal || "0",
            completed,
            assigned_to: task.phase === "CONTROL"
              ? (editingTaskKoUserId === "__unassigned__" ? null : editingTaskKoUserId)
              : (editingTaskAssignee === "__unassigned__" ? null : editingTaskAssignee),
            status: nextStatus,
          },
        }))
        cancelEditTask()
        toast.success("Task updated")
      } catch (error) {
        const message = error instanceof Error && error.message ? error.message : "Failed to update task"
        toast.error(message)
      } finally {
        setSavingTaskEdit(false)
      }
    }

    const memberLabel = (id?: string | null) => {
      if (!id) return "-"
      const u = userMap.get(id)
      const label = u?.full_name || u?.username || u?.email || "-"
      return label === "-" ? "-" : initialsWithDots(label)
    }
    return (
      <>
        <div className="space-y-5 mx-auto px-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-3">
              <button type="button" onClick={() => router.back()} className="text-sm text-muted-foreground hover:text-foreground">
                &larr; Back to Projects
              </button>
              <div className="flex items-center gap-3">
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
                    className="text-sm text-muted-foreground hover:text-foreground cursor-pointer underline"
                    title="Edit project due date"
                  >
                    {project.due_date ? `Due: ${formatDateDisplay(project.due_date)}` : "Set due date"}
                  </button>
                )}
                {!canEditDueDate && project.due_date && (
                  <span className="text-sm text-muted-foreground">Due: {formatDateDisplay(project.due_date)}</span>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                {MST_PHASES.map((p) => {
                  const isActive = p === mstPhase
                  return (
                    <button
                      key={p}
                      type="button"
                      onClick={() => setMstPhase(p)}
                      className={[
                        "rounded-full border px-3 py-1 transition-colors",
                        isActive ? "border-blue-500 bg-blue-50 text-blue-700" : "border-slate-200 text-muted-foreground",
                      ].join(" ")}
                    >
                      {MST_PHASE_LABELS[p]}
                    </button>
                  )
                })}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="text-blue-600 border-blue-200 bg-blue-50">
                {mstBadgeLabel(project)}
              </Badge>
            </div>
          </div>

          {mstPhase === "PLANNING" ? (
            <>
              <div className="border-b flex gap-6">
                {[
                  { id: "description", label: "Description" },
                  { id: "ga", label: "Shenime GA/KA" },
                ].map((tab) => {
                  const isActive = mstTab === tab.id
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setMstTab(tab.id as typeof mstTab)}
                      className={[
                        "relative pb-3 text-sm font-medium",
                        tab.id === "ga" ? "ml-auto" : "",
                        isActive ? "text-blue-600" : "text-muted-foreground",
                      ].join(" ")}
                    >
                      {tab.label}
                      {isActive ? <span className="absolute inset-x-0 bottom-0 h-0.5 bg-blue-600" /> : null}
                    </button>
                  )
                })}
              </div>
              {mstTab === "ga" ? (
                renderGaNotes()
              ) : (
                <Card>
                  <div className="p-4 space-y-4">
                    <div className="text-lg font-semibold">Planifikimi</div>
                    <div className="grid gap-3">
                      {planningTopItems.map((item, idx) => {
                        const isEditing = editingPlanningItemId === item.id
                        const itemNumber = planningIndexMap.get(item.id) ?? idx + 1
                        return (
                          <div key={item.id} className="grid grid-cols-12 gap-3 items-center px-3">
                            <div className="col-span-1 text-right text-xs text-muted-foreground">
                              {isEditing ? (
                                <Input
                                  type="number"
                                  min={1}
                                  inputMode="numeric"
                                  value={editingPlanningItemNumber}
                                  onChange={(e) => setEditingPlanningItemNumber(e.target.value)}
                                  className="h-8 w-14 text-right"
                                />
                              ) : (
                                `${itemNumber}.`
                              )}
                            </div>
                            <div className="col-span-1 flex justify-center">
                              <Checkbox
                                checked={Boolean(descriptionChecks[item.id])}
                                onCheckedChange={() => togglePlanning(item)}
                              />
                            </div>
                            <div className="col-span-6">
                              {isEditing ? (
                                <Input
                                  value={editingPlanningItemText}
                                  onChange={(e) => setEditingPlanningItemText(e.target.value)}
                                  className="w-full"
                                />
                              ) : (
                                <span className="text-sm font-semibold uppercase tracking-wide">
                                  {item.title || "-"}
                                </span>
                              )}
                            </div>
                            <div className="col-span-2">
                              {isAdmin ? (
                                isEditing ? (
                                  <div className="flex flex-col items-start gap-2">
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      disabled={!editingPlanningItemText.trim() || savingPlanningItem}
                                      onClick={() => void savePlanningItem()}
                                    >
                                      Save
                                    </Button>
                                    <Button size="sm" variant="ghost" onClick={cancelEditPlanningItem}>
                                      Cancel
                                    </Button>
                                  </div>
                                ) : (
                                  <div className="flex flex-col items-start gap-2">
                                    <Button size="sm" variant="outline" onClick={() => startEditPlanningItem(item)}>
                                      Edit
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      className="text-red-600 border-red-200 hover:bg-red-50"
                                      onClick={() => void deletePlanningItem(item)}
                                    >
                                      Delete
                                    </Button>
                                  </div>
                                )
                              ) : null}
                            </div>
                            <div className="col-span-2" />
                          </div>
                        )
                      })}
                    </div>

                    <div className="grid grid-cols-12 items-center bg-slate-50 px-3 py-2 font-semibold text-xs uppercase text-slate-600 border">
                      <div className="col-span-1" />
                      <div className="col-span-1" />
                      <div className="col-span-6">Description/General Points</div>
                      <div className="col-span-2 text-center">Actions</div>
                      <div className="col-span-2 text-right">COMENT</div>
                    </div>

                    <div className="divide-y border rounded-lg">
                      {planningOtherItems.map((item, idx) => {
                        const comment = planningComments[item.id] || item.comment || ""
                        const itemNumber = planningIndexMap.get(item.id) ?? (idx + 3)

                        return (
                          <div key={item.id} className="grid grid-cols-12 gap-3 items-center px-3 py-3">
                            <div className="col-span-1 text-right text-xs text-muted-foreground">
                              {editingPlanningItemId === item.id ? (
                                <Input
                                  type="number"
                                  min={1}
                                  inputMode="numeric"
                                  value={editingPlanningItemNumber}
                                  onChange={(e) => setEditingPlanningItemNumber(e.target.value)}
                                  className="h-8 w-14 text-right"
                                />
                              ) : (
                                `${itemNumber}.`
                              )}
                            </div>
                            <div className="col-span-1 flex justify-center">
                              <Checkbox
                                checked={Boolean(descriptionChecks[item.id])}
                                onCheckedChange={() => togglePlanning(item)}
                              />
                            </div>
                            <div className="col-span-6">
                              {editingPlanningItemId === item.id ? (
                                <Input
                                  value={editingPlanningItemText}
                                  onChange={(e) => setEditingPlanningItemText(e.target.value)}
                                  className="w-full"
                                />
                              ) : (
                                <span className="text-sm">{item.title || "-"}</span>
                              )}
                            </div>
                            <div className="col-span-2">
                              {isAdmin ? (
                                editingPlanningItemId === item.id ? (
                                  <div className="flex flex-col items-start gap-2">
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      disabled={!editingPlanningItemText.trim() || savingPlanningItem}
                                      onClick={() => void savePlanningItem()}
                                    >
                                      Save
                                    </Button>
                                    <Button size="sm" variant="ghost" onClick={cancelEditPlanningItem}>
                                      Cancel
                                    </Button>
                                  </div>
                                ) : (
                                  <div className="flex flex-col items-start gap-2">
                                    <Button size="sm" variant="outline" onClick={() => startEditPlanningItem(item)}>
                                      Edit
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      className="text-red-600 border-red-200 hover:bg-red-50"
                                      onClick={() => void deletePlanningItem(item)}
                                    >
                                      Delete
                                    </Button>
                                  </div>
                                )
                              ) : null}
                            </div>
                            <div className="col-span-2">
                              <Input
                                placeholder="Comment"
                                value={comment}
                                onChange={(e) => {
                                  const newComment = e.target.value
                                  setPlanningComments((prev) => ({ ...prev, [item.id]: newComment }))
                                  setChecklistItems((prev) =>
                                    prev.map((entry) =>
                                      entry.id === item.id ? { ...entry, comment: newComment } : entry
                                    )
                                  )
                                  apiFetch(`/checklist-items/${item.id}`, {
                                    method: "PATCH",
                                    headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ comment: newComment || null }),
                                  }).catch(() => {
                                    // Silently handle errors - update might still succeed
                                  })
                                }}
                                onBlur={async (e) => {
                                  const newComment = e.target.value
                                  try {
                                    await apiFetch(`/checklist-items/${item.id}`, {
                                      method: "PATCH",
                                      headers: { "Content-Type": "application/json" },
                                      body: JSON.stringify({ comment: newComment || null }),
                                    })
                                  } catch {
                                    // Silently handle network errors - update might still succeed
                                  }
                                }}
                              />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                    {isAdmin ? (
                      <div className="flex flex-wrap items-center gap-2">
                        <Input
                          type="number"
                          min={1}
                          inputMode="numeric"
                          value={newPlanningItemNumber}
                          onChange={(e) => setNewPlanningItemNumber(e.target.value)}
                          placeholder="No."
                          className="w-24"
                        />
                        <Input
                          value={newPlanningItemText}
                          onChange={(e) => setNewPlanningItemText(e.target.value)}
                          placeholder="Add planning checklist item..."
                          className="flex-1 min-w-[220px]"
                        />
                        <Button
                          variant="outline"
                          disabled={!newPlanningItemText.trim() || addingPlanningItem}
                          onClick={() => void addPlanningItem()}
                        >
                          {addingPlanningItem ? "Adding..." : "Add"}
                        </Button>
                      </div>
                    ) : null}
                  </div>
                </Card>
              )}
            </>
          ) : mstPhase === "PRODUCT" ? (
            <>
              <div className="border-b flex gap-6">
                {[
                  { id: "tasks", label: "Tasks (Detyrat)" },
                  { id: "checklists", label: "Checklists" },
                  { id: "members", label: "Members" },
                  { id: "ga", label: "Shenime GA/KA" },
                ].map((tab) => {
                  const isActive = mstTab === tab.id
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setMstTab(tab.id as typeof mstTab)}
                      className={[
                        "relative pb-3 text-sm font-medium",
                        isActive ? "text-blue-600" : "text-muted-foreground",
                      ].join(" ")}
                    >
                      {tab.label}
                      {isActive ? <span className="absolute inset-x-0 bottom-0 h-0.5 bg-blue-600" /> : null}
                    </button>
                  )
                })}
              </div>

              {mstTab === "tasks" ? (
                <Card className="border-0 shadow-sm">
                  <div className="p-6 space-y-4">
                    <div className="text-lg font-semibold tracking-tight">Tasks</div>
                    {/* Table header */}
                    <div className="sticky top-0 z-40 -mx-6 px-6 py-3 grid grid-cols-12 gap-4 text-[11px] font-medium text-slate-400 uppercase tracking-wider bg-white border-b border-slate-100 shadow-sm">
                      <div className="col-span-3">Task</div>
                      <div className="col-span-1">Product Owner</div>
                      <div className="col-span-1">Start Date</div>
                      <div className="col-span-1">Due Date</div>
                      <div className="col-span-1">Finish</div>
                      <div className="col-span-1">Daily Products</div>
                      <div className="col-span-2">Completed</div>
                      <div className="col-span-1">Status</div>
                      <div className="col-span-1"></div>
                    </div>
                    {/* Inline form row */}
                    <div className="grid grid-cols-12 gap-4 py-4 text-sm items-center bg-slate-50/60 -mx-6 px-6 border-y border-slate-100">
                      <div className="col-span-3">
                        <input
                          type="text"
                          placeholder="Enter task name..."
                          className="w-full bg-transparent border-0 border-b-2 border-slate-200 focus:border-blue-500 outline-none py-2 text-sm placeholder:text-slate-400 transition-colors"
                          value={newInlineTaskTitle}
                          onChange={(e) => setNewInlineTaskTitle(e.target.value)}
                        />
                      </div>
                      <div className="col-span-1">
                        <Select value={newInlineTaskAssignee} onValueChange={setNewInlineTaskAssignee}>
                          <SelectTrigger className="h-9 border-0 border-b-2 border-slate-200 rounded-none bg-transparent focus:border-blue-500 shadow-none">
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
                      <div className="col-span-1">
                        <input
                          type="date"
                          className="w-full bg-transparent border-0 border-b-2 border-slate-200 focus:border-blue-500 outline-none py-2 text-sm placeholder:text-slate-400 transition-colors"
                          value={newInlineTaskStartDate}
                          onChange={(e) => setNewInlineTaskStartDate(e.target.value)}
                        />
                      </div>
                      <div className="col-span-1">
                        <input
                          type="date"
                          className="w-full bg-transparent border-0 border-b-2 border-slate-200 focus:border-blue-500 outline-none py-2 text-sm placeholder:text-slate-400 transition-colors"
                          value={newInlineTaskDueDate}
                          onChange={(e) => setNewInlineTaskDueDate(e.target.value)}
                        />
                      </div>
                      <div className="col-span-1 flex items-center gap-2 text-xs text-slate-600">
                        <Checkbox
                          checked={newInlineTaskDeadlineImportant}
                          onCheckedChange={(checked) => setNewInlineTaskDeadlineImportant(checked === true)}
                        />
                        <span>Important</span>
                      </div>
                      <div className="col-span-1">
                        <Select
                          value={newInlineTaskFinishPeriod}
                          onValueChange={(value) =>
                            setNewInlineTaskFinishPeriod(value as TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE)
                          }
                        >
                          <SelectTrigger className="h-9 border-0 border-b-2 border-slate-200 rounded-none bg-transparent focus:border-blue-500 shadow-none">
                            <SelectValue placeholder="All day" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={FINISH_PERIOD_NONE_VALUE}>{FINISH_PERIOD_NONE_LABEL}</SelectItem>
                            {FINISH_PERIOD_OPTIONS.map((value) => (
                              <SelectItem key={value} value={value}>
                                {value}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="col-span-1">
                        <input
                          type="number"
                          placeholder="0"
                          className="w-full bg-transparent border-0 border-b-2 border-slate-200 focus:border-blue-500 outline-none py-2 text-sm placeholder:text-slate-400 transition-colors"
                          value={newInlineTaskTotal}
                          onChange={(e) => setNewInlineTaskTotal(e.target.value)}
                        />
                      </div>
                      <div className="col-span-2">
                        <input
                          type="number"
                          placeholder="0"
                          className="w-full bg-transparent border-0 border-b-2 border-slate-200 focus:border-blue-500 outline-none py-2 text-sm placeholder:text-slate-400 transition-colors"
                          value={newInlineTaskCompleted}
                          onChange={(e) => setNewInlineTaskCompleted(e.target.value)}
                        />
                      </div>
                      <div className="col-span-1">
                        <Button
                          size="sm"
                          className="rounded-full px-5 shadow-sm"
                          onClick={async () => {
                            if (!project || !newInlineTaskTitle.trim()) return
                            setCreatingInlineTask(true)
                            try {
                              const res = await apiFetch("/tasks", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({
                                  title: newInlineTaskTitle.trim(),
                                  project_id: project.id,
                                  department_id: project.department_id,
                                  assigned_to: newInlineTaskAssignee === "__unassigned__" ? null : newInlineTaskAssignee,
                                  priority: "NORMAL",
                                  phase: "PRODUCT",
                                  start_date: newInlineTaskStartDate ? new Date(newInlineTaskStartDate).toISOString() : null,
                                  due_date: newInlineTaskDueDate ? new Date(newInlineTaskDueDate).toISOString() : null,
                                  is_deadline_important: newInlineTaskDeadlineImportant,
                                  finish_period:
                                    newInlineTaskFinishPeriod === FINISH_PERIOD_NONE_VALUE
                                      ? null
                                      : newInlineTaskFinishPeriod,
                                  daily_products: newInlineTaskTotal ? parseInt(newInlineTaskTotal, 10) : null,
                                  internal_notes: `completed_products=${newInlineTaskCompleted || 0}`,
                                }),
                              })
                              if (!res?.ok) {
                                toast.error("Failed to add task")
                                return
                              }
                              const created = (await res.json()) as Task
                              const reloaded = await reloadProjectTasks(project.id)
                              if (!reloaded) setTasks((prev) => [...prev, created])
                              setNewInlineTaskTitle("")
                              setNewInlineTaskAssignee("__unassigned__")
                              setNewInlineTaskStartDate("")
                              setNewInlineTaskDueDate("")
                              setNewInlineTaskDeadlineImportant(false)
                              setNewInlineTaskFinishPeriod(FINISH_PERIOD_NONE_VALUE)
                              setNewInlineTaskTotal("")
                              setNewInlineTaskCompleted("")
                              toast.success("Task added")
                            } finally {
                              setCreatingInlineTask(false)
                            }
                          }}
                          disabled={creatingInlineTask || !newInlineTaskTitle.trim()}
                        >
                          {creatingInlineTask ? "..." : "Save"}
                        </Button>
                      </div>
                      <div className="col-span-1"></div>
                    </div>
                    {/* Task rows */}
                    <div className="divide-y divide-slate-100">
                      {tasks.filter((task) => (task.phase ?? "PRODUCT") === "PRODUCT").map((task, index) => {
                        const isEditing = editingTaskId === task.id
                        const baseTotalVal =
                          task.daily_products ?? (parseInt(controlEdits[task.id]?.total || "0", 10) || 0)
                        const totalVal = isEditing ? toNonNegativeInt(editingTaskTotal || baseTotalVal) : baseTotalVal
                        const completedValue = isEditing
                          ? editingTaskCompleted || controlEdits[task.id]?.completed || "0"
                          : controlEdits[task.id]?.completed || "0"
                        const completedNum = toNonNegativeInt(completedValue)
                        const autoStatus = computeStatusFromCompleted(totalVal, completedNum)
                        return (
                          <div key={task.id} className="grid grid-cols-12 gap-4 py-4 -mx-6 px-6 text-sm items-center hover:bg-slate-50/70 transition-colors group">
                            <div className="col-span-3 pr-2">
                              {isEditing ? (
                                <input
                                  type="text"
                                  value={editingTaskTitle}
                                  onChange={(e) => setEditingTaskTitle(e.target.value)}
                                  className="w-full bg-transparent border-0 border-b-2 border-blue-500 outline-none py-1 text-sm"
                                  autoFocus
                                />
                              ) : (
                                <span className="font-medium text-slate-700">
                                  {index + 1}. {task.ga_note_origin_id ? renderMarkedNoteContent(task.title, task.title) : task.title}
                                </span>
                              )}
                            </div>
                            <div className="col-span-1 px-2 min-w-0">
                              {isEditing ? (
                                <Select value={editingTaskAssignee} onValueChange={setEditingTaskAssignee}>
                                  <SelectTrigger className="h-8 w-full min-w-0 border-0 border-b-2 border-blue-500 rounded-none bg-transparent shadow-none px-1">
                                    <SelectValue />
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
                                <span className="block truncate text-slate-500">{memberLabel(task.assigned_to)}</span>
                              )}
                            </div>
                            <div className="col-span-1 px-2">
                              {isEditing ? (
                                <input
                                  type="date"
                                  value={editingTaskStartDate}
                                  onChange={(e) => setEditingTaskStartDate(e.target.value)}
                                  className="w-full bg-transparent border-0 border-b-2 border-blue-500 outline-none py-1 text-sm"
                                />
                              ) : (
                                <span className="text-slate-500">{formatDateDMY(task.start_date) || "-"}</span>
                              )}
                            </div>
                            <div className="col-span-1 px-2">
                              {isEditing ? (
                                <input
                                  type="date"
                                  value={editingTaskDueDate}
                                  onChange={(e) => setEditingTaskDueDate(e.target.value)}
                                  className="w-full bg-transparent border-0 border-b-2 border-blue-500 outline-none py-1 text-sm"
                                />
                              ) : (
                                <span className="text-slate-500">{formatDateDMY(task.due_date)}</span>
                              )}
                            </div>
                            <div className="col-span-1 px-2">
                              {isEditing ? (
                                <Select
                                  value={editingTaskFinishPeriod}
                                  onValueChange={(value) =>
                                    setEditingTaskFinishPeriod(
                                      value as TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE
                                    )
                                  }
                                >
                                  <SelectTrigger className="h-8 w-full border-0 border-b-2 border-blue-500 rounded-none bg-transparent shadow-none px-1">
                                    <SelectValue placeholder="All day" />
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value={FINISH_PERIOD_NONE_VALUE}>{FINISH_PERIOD_NONE_LABEL}</SelectItem>
                                    {FINISH_PERIOD_OPTIONS.map((value) => (
                                      <SelectItem key={value} value={value}>
                                        {value}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              ) : (
                                <span className="text-slate-500">{task.finish_period || "-"}</span>
                              )}
                            </div>
                            <div className="col-span-1 px-2">
                              {isEditing ? (
                                <input
                                  type="number"
                                  value={editingTaskTotal}
                                  onChange={(e) => setEditingTaskTotal(e.target.value)}
                                  placeholder="0"
                                  className="w-full bg-transparent border-0 border-b-2 border-blue-500 outline-none py-1 text-sm"
                                />
                              ) : (
                                <span className="text-slate-500">
                                  {task.daily_products ?? controlEdits[task.id]?.total ?? "-"}
                                </span>
                              )}
                            </div>
                            <div className="col-span-2 px-2">
                              {isEditing ? (
                                <input
                                  type="number"
                                  min="0"
                                  value={editingTaskCompleted}
                                  onChange={(e) => {
                                    const rawValue = e.target.value
                                    const completedNum = toNonNegativeInt(rawValue)
                                    const totalValue = editingTaskTotal || controlEdits[task.id]?.total || "0"
                                    const totalNum = toNonNegativeInt(totalValue)
                                    const newCompleted = completedNum.toString()
                                    const newStatus = computeStatusFromCompleted(totalNum, completedNum)
                                    setEditingTaskCompleted(newCompleted)
                                    setControlEdits((prev) => ({
                                      ...prev,
                                      [task.id]: { ...prev[task.id], completed: newCompleted, status: newStatus },
                                    }))
                                  }}
                                  className="w-full bg-transparent border-0 border-b-2 border-blue-500 outline-none py-1 text-sm text-left"
                                />
                              ) : (
                                <div className="flex items-center justify-start gap-2">
                                  <button
                                    type="button"
                                    className="h-6 w-6 rounded-full border border-slate-300 text-slate-500 hover:text-slate-700"
                                    onClick={async () => {
                                      const prevCompleted = controlEdits[task.id]?.completed || "0"
                                      const completedNum = Math.max(0, toNonNegativeInt(prevCompleted) - 1)
                                      const newCompleted = completedNum.toString()
                                      const newStatus = computeStatusFromCompleted(totalVal, completedNum)
                                      setControlEdits((prev) => ({
                                        ...prev,
                                        [task.id]: { ...prev[task.id], completed: newCompleted, status: newStatus },
                                      }))
                                      const currentNotes = task.internal_notes || ""
                                      const originTaskId = getOriginTaskId(currentNotes)
                                      const koUserId = parseKoUserId(currentNotes)
                                      const internalNotes = serializeInternalNotes({
                                        originTaskId: originTaskId || undefined,
                                        total: totalVal.toString(),
                                        completed: newCompleted,
                                        koUserId: koUserId || null,
                                      })
                                      const res = await apiFetch(`/tasks/${task.id}`, {
                                        method: "PATCH",
                                        headers: { "Content-Type": "application/json" },
                                        body: JSON.stringify({
                                          internal_notes: internalNotes,
                                        }),
                                      })
                                      if (!res?.ok) {
                                        toast.error("Failed to update completed count")
                                        const prevStatus = computeStatusFromCompleted(totalVal, toNonNegativeInt(prevCompleted))
                                        setControlEdits((prev) => ({
                                          ...prev,
                                          [task.id]: { ...prev[task.id], completed: prevCompleted, status: prevStatus },
                                        }))
                                        return
                                      }
                                      try {
                                        const updated = (await res.json()) as Task
                                        setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))
                                      } catch {
                                        // ignore JSON parse errors
                                      }
                                    }}
                                  >
                                    -
                                  </button>
                                  <div className="min-w-[32px] text-center text-sm text-slate-700">
                                    {controlEdits[task.id]?.completed || "0"}
                                  </div>
                                  <button
                                    type="button"
                                    className="h-6 w-6 rounded-full border border-slate-300 text-slate-500 hover:text-slate-700"
                                    onClick={async () => {
                                      const prevCompleted = controlEdits[task.id]?.completed || "0"
                                      const prevCompletedNum = toNonNegativeInt(prevCompleted)
                                      const completedNum = prevCompletedNum + 1
                                      const newCompleted = completedNum.toString()
                                      const newStatus = computeStatusFromCompleted(totalVal, completedNum)
                                      setControlEdits((prev) => ({
                                        ...prev,
                                        [task.id]: { ...prev[task.id], completed: newCompleted, status: newStatus },
                                      }))
                                      const currentNotes = task.internal_notes || ""
                                      const originTaskId = getOriginTaskId(currentNotes)
                                      const koUserId = parseKoUserId(currentNotes)
                                      const internalNotes = serializeInternalNotes({
                                        originTaskId: originTaskId || undefined,
                                        total: totalVal.toString(),
                                        completed: newCompleted,
                                        koUserId: koUserId || null,
                                      })
                                      const res = await apiFetch(`/tasks/${task.id}`, {
                                        method: "PATCH",
                                        headers: { "Content-Type": "application/json" },
                                        body: JSON.stringify({
                                          internal_notes: internalNotes,
                                        }),
                                      })
                                      if (!res?.ok) {
                                        toast.error("Failed to update completed count")
                                        const prevStatus = computeStatusFromCompleted(totalVal, toNonNegativeInt(prevCompleted))
                                        setControlEdits((prev) => ({
                                          ...prev,
                                          [task.id]: { ...prev[task.id], completed: prevCompleted, status: prevStatus },
                                        }))
                                        return
                                      }
                                      try {
                                        const updated = (await res.json()) as Task
                                        setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))
                                      } catch {
                                        // ignore JSON parse errors
                                      }
                                    }}
                                  >
                                    +
                                  </button>
                                </div>
                              )}
                            </div>
                            <div className="col-span-1 px-2">
                              <Badge
                                variant={autoStatus === "DONE" ? "default" : "outline"}
                                className={autoStatus === "DONE" ? "bg-emerald-500 hover:bg-emerald-600" : "text-slate-600 border-slate-300"}
                              >
                                {statusLabel(autoStatus)}
                              </Badge>
                            </div>
                            <div className="col-span-1 text-right opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-end gap-1">
                              {isEditing ? (
                                <>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-8 px-2 text-slate-400 hover:text-blue-600"
                                    onClick={() => void saveTaskEdit()}
                                    disabled={savingTaskEdit}
                                  >
                                    {savingTaskEdit ? "Saving..." : "Save"}
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-8 px-2 text-slate-400 hover:text-slate-600"
                                    onClick={cancelEditTask}
                                  >
                                    Cancel
                                  </Button>
                                </>
                              ) : (
                                <>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-8 w-8 p-0 text-slate-400 hover:text-blue-600 hover:bg-blue-50"
                                    onClick={() => startEditTask(task)}
                                  >
                                    <Pencil className="h-4 w-4" />
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-8 w-8 p-0 text-slate-400 hover:text-red-500 hover:bg-red-50"
                                    onClick={async () => {
                                      if (!(await confirmDeleteTask())) return
                                      const res = await apiFetch(`/tasks/${task.id}`, { method: "DELETE" })
                                      if (!res?.ok) {
                                        if (res?.status == 405) {
                                          toast.error("Delete endpoint not active. Restart backend.")
                                        } else {
                                          let message = "Failed to delete task"
                                          try {
                                            const data = (await res.json()) as { detail?: string }
                                            if (data.detail) message = data.detail
                                          } catch {
                                            // Keep the fallback message.
                                          }
                                          toast.error(message)
                                        }
                                        return
                                      }
                                      setTasks((prev) => {
                                        const next: Task[] = []
                                        for (const t of prev) {
                                          if (t.id === task.id) continue
                                          if (t.phase === "CONTROL") {
                                            const originTaskId = getOriginTaskId(t.internal_notes)
                                            if (originTaskId && originTaskId === task.id) {
                                              const totals = parseTaskTotals(t.internal_notes)
                                              const koUserId = parseKoUserId(t.internal_notes)
                                              const productionDate = parseProductionDate(t.internal_notes)
                                              const internalNotes = serializeInternalNotes({
                                                total: totals.total,
                                                completed: totals.completed,
                                                koUserId,
                                                productionDate,
                                              })
                                              next.push({ ...t, internal_notes: internalNotes })
                                              continue
                                            }
                                          }
                                          next.push(t)
                                        }
                                        return next
                                      })
                                      toast.success("Task deleted")
                                    }}
                                  >
                                    <Trash2 className="h-4 w-4" />
                                  </Button>
                                </>
                              )}
                            </div>
                          </div>
                        )
                      })}
                      {tasks.length === 0 ? (
                        <div className="py-8 text-center text-sm text-slate-400">
                          No tasks yet. Add one above to get started.
                        </div>
                      ) : null}
                    </div>
                  </div>
                </Card>
              ) : null}

              {mstTab === "checklists" ? (
                <Card>
                  <div className="p-4 space-y-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="text-lg font-semibold">Checklists</div>
                        {isMstTemplateEditor ? (
                          <div className="text-xs text-slate-500">Admin template editor for future {productChecklistLabel} projects</div>
                        ) : null}
                      </div>
                      <div className="flex items-center gap-2">
                        {isMstTemplateEditor && !mstTemplateChecklist ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => void createMstTemplateFromDefaults()}
                            disabled={initializingMstTemplate || loadingMstTemplate}
                            className="h-8 rounded-xl border-slate-200 text-xs"
                          >
                            {initializingMstTemplate ? "Initializing..." : "Create Template"}
                          </Button>
                        ) : null}
                        {isMstTemplateEditor && mstTemplateChecklist ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => void loadMstTemplateChecklist()}
                            disabled={loadingMstTemplate}
                            className="h-8 rounded-xl border-slate-200 text-xs"
                          >
                            {loadingMstTemplate ? "Refreshing..." : "Refresh Template"}
                          </Button>
                        ) : null}
                        {!isMstTemplateEditor || mstTemplateChecklist ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => void exportMstChecklist()}
                            disabled={exportingMstChecklist || activeMstChecklistItems.length === 0}
                            className="h-8 rounded-xl border-slate-200 text-xs"
                          >
                            <Download className="mr-2 h-4 w-4" />
                            {exportingMstChecklist ? "Exporting..." : "Export Excel"}
                          </Button>
                        ) : null}
                      </div>
                    </div>
                    {isMstTemplateEditor && !mstTemplateChecklist ? (
                      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                        No saved {productChecklistLabel} template exists yet. Create it, then edit the rows here.
                        New {productChecklistLabel} projects will seed from this saved template.
                      </div>
                    ) : null}
                    <div className="text-sm text-red-600 space-y-1">
                      <div>!!! EMRI I PLOTE I KLIENTIT NUK GUXON TE SHKRUHET I PLOTE NE ASNJE EMERTIM TE FILE AS ASKUND TJETER</div>
                      <div>!!! CDO KATEGORI E RE PARAQITET SI RAST I PARE, DHE GJITHMONE DUHET TE KONFIRMOHET R1 ME GA</div>
                      <div>!!! KRAHASO TE DHENAT QE DERGOHEN TE PLOTESUARA, A JANE NE PERPUTHSHMERI ME DROPDOWN DHE ME TE DHENAT QE NA I KANE DERGUAR NE PDF/EXCEL</div>
                      <div>!!! BESONDERE MERKMALE - MAX 70 CHARACTERS</div>
                      <div>!!! PER PRODUKTE TE NJEJTA ME DIMENSIONE TE NDRYSHME, TE VENDOSEN TE GJITHA DIMENSIONET TEK SELLING POINT GENERAL: Maße (B/H/T in cm): 220/240/280 x 46 x 45 cm.</div>
                      <div>!!! SELLING POINT 1: 5 JAHRE GARANTIE (FIKSE)</div>
                      <div>!!! TO SELLING POINTS & BESONDERE MERKMALE - WE SHOULD CREATE SAME DESCRIPTIONS FOR PRODUCTS THAT ARE IDENTICAL EXCEPT FOR COLOR.</div>
                    </div>
                    <div
                      ref={mstChecklistScrollRef}
                      className="overflow-x-auto scrollbar-hide cursor-grab active:cursor-grabbing"
                      style={{ WebkitOverflowScrolling: "touch" }}
                      onMouseDown={(event) => {
                        if (event.button !== 0) return
                        const target = event.target as HTMLElement
                        if (target.closest("input, textarea, button, select, [role=\"checkbox\"]")) {
                          return
                        }
                        const container = mstChecklistScrollRef.current
                        if (!container) return
                        mstChecklistDragRef.current.active = true
                        mstChecklistDragRef.current.startX = event.pageX - container.offsetLeft
                        mstChecklistDragRef.current.startScrollLeft = container.scrollLeft
                      }}
                      onMouseUp={() => {
                        mstChecklistDragRef.current.active = false
                      }}
                      onMouseLeave={() => {
                        mstChecklistDragRef.current.active = false
                      }}
                      onMouseMove={(event) => {
                        if (!mstChecklistDragRef.current.active) return
                        event.preventDefault()
                        const container = mstChecklistScrollRef.current
                        if (!container) return
                        const x = event.pageX - container.offsetLeft
                        const walk = (x - mstChecklistDragRef.current.startX) * 1.2
                        container.scrollLeft = mstChecklistDragRef.current.startScrollLeft - walk
                      }}
                    >
                      <div className={showMstOriginalColumn ? "min-w-[1280px]" : "min-w-[1200px]"}>
                        <div className={`grid ${mstChecklistGridClass} gap-3 text-xs font-semibold text-muted-foreground border-b pb-2`}>
                          <div className="col-span-1">NO</div>
                          <div className="col-span-2">PATH</div>
                          <div className="col-span-2">DETYRAT</div>
                          <div className="col-span-2">KEYWORDS</div>
                          <div className="col-span-2">PERSHKRIMI</div>
                          <div className="col-span-1">KATEGORIA</div>
                          {showMstOriginalColumn ? <div className="col-span-1">ORIGJINAL</div> : null}
                          <div className="col-span-1">CHECK</div>
                          <div className="col-span-1">INCL</div>
                          <div className="col-span-2">KOMENT</div>
                          <div className="col-span-1 text-right">ACTIONS</div>
                        </div>
                        <div className={`grid ${mstChecklistGridClass} gap-3 py-3 text-sm items-center border-b`}>
                          <div className="col-span-1">
                            <Input
                              value={newMstChecklistRow.number}
                              onChange={(e) => setNewMstChecklistRow((prev) => ({ ...prev, number: e.target.value }))}
                              placeholder="No"
                              className="h-8 text-xs"
                            />
                          </div>
                          <div className="col-span-2">
                            <Input
                              value={newMstChecklistRow.path}
                              onChange={(e) => setNewMstChecklistRow((prev) => ({ ...prev, path: e.target.value }))}
                              placeholder="Path"
                              className="h-8 text-xs"
                            />
                          </div>
                          <div className="col-span-2">
                            <ChecklistInlineStyleEditor
                              value={newMstChecklistRow.detyrat}
                              onChange={(value) => setNewMstChecklistRow((prev) => ({ ...prev, detyrat: value }))}
                              placeholder="Detyrat"
                            />
                          </div>
                          <div className="col-span-2">
                            <ChecklistInlineStyleEditor
                              value={newMstChecklistRow.keywords}
                              onChange={(value) => setNewMstChecklistRow((prev) => ({ ...prev, keywords: value }))}
                              placeholder="Keywords"
                            />
                          </div>
                          <div className="col-span-2">
                            <ChecklistInlineStyleEditor
                              value={newMstChecklistRow.pershkrimi}
                              onChange={(value) => setNewMstChecklistRow((prev) => ({ ...prev, pershkrimi: value }))}
                              placeholder="Pershkrimi"
                            />
                          </div>
                          <div className="col-span-1">
                            <ChecklistInlineStyleEditor
                              value={newMstChecklistRow.kategoria}
                              onChange={(value) => setNewMstChecklistRow((prev) => ({ ...prev, kategoria: value }))}
                              placeholder="Kategoria"
                            />
                          </div>
                          {showMstOriginalColumn ? (
                            <div className="col-span-1">
                              <ChecklistInlineStyleEditor
                                value={newMstChecklistRow.original}
                                onChange={(value) => setNewMstChecklistRow((prev) => ({ ...prev, original: value }))}
                                placeholder="Origjinal"
                              />
                            </div>
                          ) : null}
                          <div className="col-span-1" />
                          <div className="col-span-1">
                            <ChecklistInlineStyleEditor
                              value={newMstChecklistRow.incl}
                              onChange={(value) => setNewMstChecklistRow((prev) => ({ ...prev, incl: value }))}
                              placeholder="Incl"
                            />
                          </div>
                          <div className="col-span-2" />
                          <div className="col-span-1 flex justify-end">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => void addMstChecklistRow()}
                              disabled={
                                savingMstChecklistRow ||
                                !newMstChecklistRow.path.trim() ||
                                !stripChecklistInlineStyleTokens(newMstChecklistRow.detyrat).trim() ||
                                (isMstTemplateEditor && !mstTemplateChecklist)
                              }
                            >
                              {savingMstChecklistRow ? "Saving..." : "Add"}
                            </Button>
                          </div>
                        </div>
                        <div className="divide-y">
                          {mstChecklistRows.map((row, index) => {
                            const key = row.key
                            const rowKey = row.item?.id ? String(row.item.id) : `${key}-${index}`
                            const isChecked = mstChecklistChecked[key] || false
                            const comment = mstChecklistComments[key] ?? row.item.comment ?? ""
                            const assignees = row.item.assignees || []
                            const assigneeInitials = assignees
                              .map((a) => {
                                const user = allUsers.find((u) => u.id === a.user_id)
                                if (user?.full_name) {
                                  const names = user.full_name.split(" ")
                                  return names.map((n) => n[0]).join("").toUpperCase()
                                }
                                return user?.username?.substring(0, 2).toUpperCase() || ""
                              })
                              .filter(Boolean)
                              .join(", ") || row.incl || "-"
                            const isEditing = editingMstChecklistKey === key

                            return (
                              <div key={rowKey} className={`grid ${mstChecklistGridClass} gap-3 py-3 text-sm items-center`}>
                                <div className="col-span-1 text-xs text-slate-500">
                                  {isEditing ? (
                                    <Input
                                      value={editingMstChecklistRow.number}
                                      onChange={(e) => setEditingMstChecklistRow((prev) => ({ ...prev, number: e.target.value }))}
                                      className="h-8 text-xs"
                                      placeholder="No"
                                    />
                                  ) : (
                                    index + 1
                                  )}
                                </div>
                                <div className="col-span-2" title={stripChecklistInlineStyleTokens(row.path)}>
                                  {isEditing ? (
                                    <Input
                                      value={editingMstChecklistRow.path}
                                      onChange={(e) => setEditingMstChecklistRow((prev) => ({ ...prev, path: e.target.value }))}
                                      className="h-8 text-xs"
                                    />
                                  ) : (
                                    <div
                                      className="flex items-start gap-1"
                                      role="button"
                                      tabIndex={0}
                                      onClick={() => {
                                        if (row.path) {
                                          setViewingChecklistField({ key, field: "path", value: row.path, label: "Path" })
                                        }
                                      }}
                                      onKeyDown={(event) => {
                                        if ((event.key === "Enter" || event.key === " ") && row.path) {
                                          setViewingChecklistField({ key, field: "path", value: row.path, label: "Path" })
                                        }
                                      }}
                                    >
                                      <span className="flex-1 break-words max-h-10 overflow-hidden text-ellipsis">
                                        {renderChecklistInlineStyle(row.path, "")}
                                      </span>
                                      {row.path && row.path.length > 20 && (
                                        <Button
                                          size="icon"
                                          variant="ghost"
                                          className="h-5 w-5 shrink-0"
                                          onClick={() => setViewingChecklistField({ key, field: "path", value: row.path, label: "Path" })}
                                          title="View full text"
                                        >
                                          <FileText className="h-3 w-3" />
                                        </Button>
                                      )}
                                    </div>
                                  )}
                                </div>
                                <div className="col-span-2 min-w-0 font-semibold" title={stripChecklistInlineStyleTokens(row.detyrat)}>
                                  {isEditing ? (
                                    <ChecklistInlineStyleEditor
                                      value={editingMstChecklistRow.detyrat}
                                      onChange={(value) => setEditingMstChecklistRow((prev) => ({ ...prev, detyrat: value }))}
                                    />
                                  ) : (
                                    <div className="flex items-center gap-1 min-w-0">
                                      <span className="flex-1 whitespace-normal break-words max-h-10 overflow-hidden text-ellipsis">
                                        {renderChecklistInlineStyle(row.detyrat, "")}
                                      </span>
                                      {row.detyrat && row.detyrat.length > 20 && (
                                        <Button
                                          size="icon"
                                          variant="ghost"
                                          className="h-5 w-5 shrink-0"
                                          onClick={() => setViewingChecklistField({ key, field: "detyrat", value: row.detyrat, label: "Task" })}
                                          title="View full text"
                                        >
                                          <FileText className="h-3 w-3" />
                                        </Button>
                                      )}
                                    </div>
                                  )}
                                </div>
                                <div className="col-span-2 min-w-0" title={stripChecklistInlineStyleTokens(row.keywords)}>
                                  {isEditing ? (
                                    <ChecklistInlineStyleEditor
                                      value={editingMstChecklistRow.keywords}
                                      onChange={(value) => setEditingMstChecklistRow((prev) => ({ ...prev, keywords: value }))}
                                    />
                                  ) : (
                                    <div
                                      className="flex items-start gap-1 min-w-0"
                                      role="button"
                                      tabIndex={0}
                                      onClick={() => {
                                        if (row.keywords) {
                                          setViewingChecklistField({ key, field: "keywords", value: row.keywords, label: "Keywords" })
                                        }
                                      }}
                                      onKeyDown={(event) => {
                                        if ((event.key === "Enter" || event.key === " ") && row.keywords) {
                                          setViewingChecklistField({ key, field: "keywords", value: row.keywords, label: "Keywords" })
                                        }
                                      }}
                                    >
                                      <span className="flex-1 break-words max-h-10 overflow-hidden text-ellipsis">
                                        {renderChecklistInlineStyle(row.keywords, "")}
                                      </span>
                                      {row.keywords && row.keywords.length > 20 && (
                                        <Button
                                          size="icon"
                                          variant="ghost"
                                          className="h-5 w-5 shrink-0"
                                          onClick={() => setViewingChecklistField({ key, field: "keywords", value: row.keywords, label: "Keywords" })}
                                          title="View full text"
                                        >
                                          <FileText className="h-3 w-3" />
                                        </Button>
                                      )}
                                    </div>
                                  )}
                                </div>
                                <div className="col-span-2" title={stripChecklistInlineStyleTokens(row.pershkrimi)}>
                                  {isEditing ? (
                                    <ChecklistInlineStyleEditor
                                      value={editingMstChecklistRow.pershkrimi}
                                      onChange={(value) => setEditingMstChecklistRow((prev) => ({ ...prev, pershkrimi: value }))}
                                    />
                                  ) : (
                                    <div
                                      className="flex items-start gap-1"
                                      role="button"
                                      tabIndex={0}
                                      onClick={() => {
                                        if (row.pershkrimi) {
                                          setViewingChecklistField({ key, field: "pershkrimi", value: row.pershkrimi, label: "Description" })
                                        }
                                      }}
                                      onKeyDown={(event) => {
                                        if ((event.key === "Enter" || event.key === " ") && row.pershkrimi) {
                                          setViewingChecklistField({ key, field: "pershkrimi", value: row.pershkrimi, label: "Description" })
                                        }
                                      }}
                                    >
                                      <span className="flex-1 break-words max-h-10 overflow-hidden text-ellipsis">
                                        {renderChecklistInlineStyle(row.pershkrimi, "")}
                                      </span>
                                      {row.pershkrimi && row.pershkrimi.length > 20 && (
                                        <Button
                                          size="icon"
                                          variant="ghost"
                                          className="h-5 w-5 shrink-0"
                                          onClick={() => setViewingChecklistField({ key, field: "pershkrimi", value: row.pershkrimi, label: "Description" })}
                                          title="View full text"
                                        >
                                          <FileText className="h-3 w-3" />
                                        </Button>
                                      )}
                                    </div>
                                  )}
                                </div>
                                <div className="col-span-1" title={stripChecklistInlineStyleTokens(row.kategoria)}>
                                  {isEditing ? (
                                    <ChecklistInlineStyleEditor
                                      value={editingMstChecklistRow.kategoria}
                                      onChange={(value) => setEditingMstChecklistRow((prev) => ({ ...prev, kategoria: value }))}
                                    />
                                  ) : (
                                    <div className="flex items-start gap-1">
                                      <span className="flex-1 whitespace-normal break-words">{renderChecklistInlineStyle(row.kategoria, "")}</span>
                                    </div>
                                  )}
                                </div>
                                {showMstOriginalColumn ? (
                                  <div className="col-span-1" title={stripChecklistInlineStyleTokens(row.original)}>
                                    {isEditing ? (
                                      <ChecklistInlineStyleEditor
                                        value={editingMstChecklistRow.original}
                                        onChange={(value) => setEditingMstChecklistRow((prev) => ({ ...prev, original: value }))}
                                      />
                                    ) : (
                                      <div className="flex items-start gap-1">
                                        <span className="flex-1 whitespace-normal break-words">{renderChecklistInlineStyle(row.original, "")}</span>
                                      </div>
                                    )}
                                  </div>
                                ) : null}
                                <div className="col-span-1 flex justify-center">
                                  {isMstTemplateEditor ? (
                                    <span className="text-xs text-slate-400">-</span>
                                  ) : (
                                    <Checkbox
                                      checked={isChecked}
                                      onCheckedChange={() => toggleFinalChecklist(row.item)}
                                    />
                                  )}
                                </div>
                                <div className="col-span-1 truncate" title={stripChecklistInlineStyleTokens(assigneeInitials)}>
                                  {isEditing ? (
                                    <ChecklistInlineStyleEditor
                                      value={editingMstChecklistRow.incl}
                                      onChange={(value) => setEditingMstChecklistRow((prev) => ({ ...prev, incl: value }))}
                                    />
                                  ) : (
                                    renderChecklistInlineStyle(assigneeInitials, "-")
                                  )}
                                </div>
                                <div className="col-span-2 pr-3">
                                  {isMstTemplateEditor ? (
                                    <div className="text-xs text-slate-400">Template rows do not store comments</div>
                                  ) : (
                                    <Input
                                      placeholder="Koment"
                                      className="h-8 text-xs w-full"
                                      value={comment}
                                      onChange={(e) => {
                                        const newComment = e.target.value
                                        setMstChecklistComments((prev) => ({ ...prev, [key]: newComment }))
                                        queueMstCommentSave(row.item, newComment)
                                      }}
                                      onBlur={(e) => updateMstChecklistComment(row.item, e.target.value)}
                                    />
                                  )}
                                </div>
                                <div className="col-span-1 flex items-center justify-end gap-2">
                                  {isEditing ? (
                                    <>
                                      <Button
                                        size="icon"
                                        variant="outline"
                                        onClick={() => void saveMstChecklistRow(row)}
                                        aria-label="Save checklist row"
                                        title="Save"
                                        disabled={savingMstChecklistRow}
                                      >
                                        <Check className="h-4 w-4" />
                                      </Button>
                                      <Button
                                        size="icon"
                                        variant="ghost"
                                        onClick={cancelEditMstChecklistRow}
                                        aria-label="Cancel editing"
                                        title="Cancel"
                                      >
                                        <span className="text-xs">X</span>
                                      </Button>
                                    </>
                                  ) : (
                                    <>
                                      <Button
                                        size="icon"
                                        variant="outline"
                                        onClick={() => startEditMstChecklistRow(row)}
                                        aria-label="Edit checklist row"
                                        title="Edit"
                                      >
                                        <Pencil className="h-4 w-4" />
                                      </Button>
                                      <Button
                                        size="icon"
                                        variant="outline"
                                        className="text-red-600 border-red-200 hover:bg-red-50"
                                        onClick={() => void deleteMstChecklistRow(row)}
                                        aria-label="Delete checklist row"
                                        title="Delete"
                                      >
                                        <Trash2 className="h-4 w-4" />
                                      </Button>
                                    </>
                                  )}
                                </div>
                              </div>
                            )
                          })}
                          {!mstChecklistRows.length ? (
                            <div className="py-8 text-center text-sm text-muted-foreground">
                              No checklist rows yet. Add one above to get started.
                            </div>
                          ) : null}
                        </div>

                        {/* View Full Text Modal */}
                        <Dialog open={viewingChecklistField !== null} onOpenChange={(open) => !open && setViewingChecklistField(null)}>
                          <DialogContent className="sm:max-w-2xl">
                            <DialogHeader>
                              <DialogTitle>{viewingChecklistField?.label || "Full Text"}</DialogTitle>
                            </DialogHeader>
                            <div className="mt-4">
                              <div className="rounded-lg border bg-slate-50 p-4">
                                <p className="whitespace-pre-wrap text-sm">
                                  {renderChecklistInlineStyle(viewingChecklistField?.value || "", "")}
                                </p>
                              </div>
                              <div className="mt-4 flex justify-end">
                                <Button
                                  variant="outline"
                                  onClick={() => {
                                    const value = stripChecklistInlineStyleTokens(viewingChecklistField?.value || "")
                                    if (!value) return
                                    void navigator.clipboard.writeText(value)
                                    toast.success("Copied to clipboard")
                                  }}
                                >
                                  Copy
                                </Button>
                              </div>
                            </div>
                          </DialogContent>
                        </Dialog>
                      </div>
                    </div>
                  </div>
                </Card>
              ) : null}

              {mstTab === "members" ? (
                <Card>
                  <div className="p-4 space-y-4">
                    <div className="flex items-center justify-between">
                      <div className="text-lg font-semibold">Members</div>
                      <div className="flex items-center gap-2">
                        <Select value={newMemberId} onValueChange={setNewMemberId}>
                          <SelectTrigger className="w-56">
                            <SelectValue placeholder="Select member" />
                          </SelectTrigger>
                          <SelectContent>
                            {departmentUsers
                              .filter((u) => !members.some((m) => m.id === u.id))
                              .map((u) => (
                                <SelectItem key={u.id} value={u.id}>
                                  {u.full_name || u.username || u.email}
                                </SelectItem>
                              ))}
                          </SelectContent>
                        </Select>
                        <Button
                          onClick={async () => {
                            if (!project || !newMemberId) return
                            setSavingMembers(true)
                            try {
                              const res = await apiFetch("/project-members", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ project_id: project.id, user_ids: [newMemberId] }),
                              })
                              if (!res?.ok) {
                                toast.error("Failed to add member")
                                return
                              }
                              const added = (await res.json()) as User[]
                              const map = new Map(members.map((m) => [m.id, m]))
                              added.forEach((u) => map.set(u.id, u))
                              setMembers(Array.from(map.values()))
                              setNewMemberId("")
                              toast.success("Member added")
                            } finally {
                              setSavingMembers(false)
                            }
                          }}
                          disabled={savingMembers || !newMemberId}
                        >
                          {savingMembers ? "Adding..." : "Add"}
                        </Button>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-6">
                      {members.length ? (
                        members.map((m, idx) => {
                          const initialsText = initials(m.full_name || m.username || m.email || "-")
                          const colors = ["bg-blue-100 text-blue-800", "bg-green-100 text-green-800", "bg-purple-100 text-purple-800", "bg-rose-100 text-rose-800", "bg-amber-100 text-amber-800"]
                          const colorClass = colors[idx % colors.length]
                          return (
                            <div key={m.id} className="flex flex-col items-center gap-2">
                              <div className={`h-16 w-16 rounded-full flex items-center justify-center text-lg font-semibold ${colorClass}`}>
                                {initialsText}
                              </div>
                              <div className="text-sm font-semibold">{m.full_name || m.username || m.email}</div>
                            </div>
                          )
                        })
                      ) : (
                        <div className="text-sm text-muted-foreground">No members added.</div>
                      )}
                    </div>
                  </div>
                </Card>
              ) : null}

              {mstTab === "ga" ? renderGaNotes() : null}
            </>
          ) : mstPhase === "CONTROL" ? (
            <>
              <div className="border-b flex gap-6">
                {[
                  { id: "tasks", label: "Tasks (Detyrat)" },
                  { id: "ga", label: "Shenime GA/KA" },
                ].map((tab) => {
                  const isActive = mstTab === tab.id
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setMstTab(tab.id as typeof mstTab)}
                      className={[
                        "relative pb-3 text-sm font-medium",
                        tab.id === "ga" ? "ml-auto" : "",
                        isActive ? "text-blue-600" : "text-muted-foreground",
                      ].join(" ")}
                    >
                      {tab.label}
                      {isActive ? <span className="absolute inset-x-0 bottom-0 h-0.5 bg-blue-600" /> : null}
                    </button>
                  )
                })}
              </div>
              {mstTab === "ga" ? (
                renderGaNotes()
              ) : (
                <Card className="border-0 shadow-sm">
                  <div className="p-6 space-y-4">
                    <div className="text-lg font-semibold tracking-tight">Kontrolli</div>
                    {/* Table header */}
                    <div className="sticky top-0 z-40 -mx-6 px-6 py-3 grid grid-cols-12 gap-4 text-[11px] font-medium text-slate-400 uppercase tracking-wider bg-white border-b border-slate-100 shadow-sm">
                      <div className="col-span-2">Task</div>
                      <div className="col-span-1">Assigned</div>
                      <div className="col-span-1">Start Date</div>
                      <div className="col-span-1">Date</div>
                      <div className="col-span-1">Finish</div>
                      <div className="col-span-1">Total</div>
                      <div className="col-span-2">Completed</div>
                      <div className="col-span-1">KO</div>
                      <div className="col-span-1">Status</div>
                      <div className="col-span-1"></div>
                    </div>
                    <div className="-mx-6 border-y border-slate-100 bg-slate-50/60 px-6 py-3 text-xs text-slate-500">
                      CONTROL tasks are created automatically from PRODUCT tasks. The PRODUCT owner remains on the
                      source task; KO is the only assignee of the CONTROL task.
                    </div>
                    {/* Task rows */}
                    <div className="divide-y divide-slate-100">
                      {tasks.filter((task) => task.phase === "CONTROL").map((task, index) => {
                        const koUserId = parseKoUserId(task.internal_notes)
                        const productionDate = parseProductionDate(task.internal_notes)
                        const isEditing = editingTaskId === task.id

                        // Get TOTAL from origin task's daily_products
                        const originTaskId = getOriginTaskId(task.internal_notes)
                        const originTask = originTaskId ? tasks.find((t) => t.id === originTaskId) : null
                        const totalFromOrigin = originTask?.daily_products ?? null
                        const baseTotalVal = totalFromOrigin !== null
                          ? totalFromOrigin
                          : toNonNegativeInt(controlEdits[task.id]?.total || "0")
                        const totalVal = isEditing ? toNonNegativeInt(editingTaskTotal || baseTotalVal) : baseTotalVal
                        const completedValue = isEditing
                          ? editingTaskCompleted || controlEdits[task.id]?.completed || "0"
                          : controlEdits[task.id]?.completed || "0"
                        const completedNum = toNonNegativeInt(completedValue)
                        const autoStatus = computeStatusFromCompleted(totalVal, completedNum)
                        return (
                          <div key={task.id} className="grid grid-cols-12 gap-4 py-4 -mx-6 px-6 text-sm items-center hover:bg-slate-50/70 transition-colors group">
                            <div className="col-span-2 pr-2">
                              {isEditing ? (
                                <input
                                  type="text"
                                  value={editingTaskTitle}
                                  onChange={(e) => setEditingTaskTitle(e.target.value)}
                                  className="w-full bg-transparent border-0 border-b-2 border-blue-500 outline-none py-1 text-sm font-medium"
                                  autoFocus
                                />
                              ) : (
                                <span className="font-medium text-slate-700">
                                  {index + 1}. {task.ga_note_origin_id ? renderMarkedNoteContent(task.title, task.title) : task.title}
                                </span>
                              )}
                            </div>
                            <div className="col-span-1 px-2 min-w-0">
                              <span className="block truncate text-slate-500">
                                {memberLabel(originTask?.assigned_to)}
                              </span>
                            </div>
                            <div className="col-span-1 px-2">
                              {isEditing ? (
                                <input
                                  type="date"
                                  value={editingTaskStartDate}
                                  onChange={(e) => setEditingTaskStartDate(e.target.value)}
                                  className="w-full bg-transparent border-0 border-b-2 border-blue-500 outline-none py-1 text-sm"
                                />
                              ) : (
                                <span className="text-slate-500">{formatDateDMY(task.start_date) || "-"}</span>
                              )}
                            </div>
                            <div className="col-span-1 px-2">
                              {isEditing ? (
                                <input
                                  type="date"
                                  value={editingTaskProductionDate}
                                  onChange={(e) => setEditingTaskProductionDate(e.target.value)}
                                  className="w-full bg-transparent border-0 border-b-2 border-blue-500 outline-none py-1 text-sm"
                                />
                              ) : (
                                <span className="text-slate-500">{formatDateDMY(productionDate)}</span>
                              )}
                            </div>
                            <div className="col-span-1 px-2">
                              {isEditing ? (
                                <Select
                                  value={editingTaskFinishPeriod}
                                  onValueChange={(value) =>
                                    setEditingTaskFinishPeriod(
                                      value as TaskFinishPeriod | typeof FINISH_PERIOD_NONE_VALUE
                                    )
                                  }
                                >
                                  <SelectTrigger className="h-8 w-full border-0 border-b-2 border-blue-500 rounded-none bg-transparent shadow-none px-1">
                                    <SelectValue placeholder="All day" />
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value={FINISH_PERIOD_NONE_VALUE}>{FINISH_PERIOD_NONE_LABEL}</SelectItem>
                                    {FINISH_PERIOD_OPTIONS.map((value) => (
                                      <SelectItem key={value} value={value}>
                                        {value}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              ) : (
                                <span className="text-slate-500">{task.finish_period || "-"}</span>
                              )}
                            </div>
                            <div className="col-span-1 px-2">
                              {isEditing ? (
                                <input
                                  type="number"
                                  value={totalFromOrigin !== null ? totalFromOrigin.toString() : editingTaskTotal}
                                  onChange={(e) => setEditingTaskTotal(e.target.value)}
                                  placeholder="0"
                                  className="w-full bg-transparent border-0 border-b-2 border-blue-500 outline-none py-1 text-sm"
                                  readOnly={totalFromOrigin !== null}
                                  title={totalFromOrigin !== null ? "TOTAL from PRODUCT phase (read-only)" : ""}
                                />
                              ) : (
                                <span className="text-slate-500">{totalFromOrigin !== null ? totalFromOrigin.toString() : (controlEdits[task.id]?.total || "-")}</span>
                              )}
                            </div>
                            <div className="col-span-2 px-2">
                              {isEditing ? (
                                <input
                                  type="number"
                                  min="0"
                                  value={editingTaskCompleted}
                                  onChange={(e) => {
                                    const rawValue = e.target.value
                                    const completedNum = toNonNegativeInt(rawValue)
                                    const totalValue = editingTaskTotal || controlEdits[task.id]?.total || "0"
                                    const totalNum = toNonNegativeInt(totalValue)
                                    const newCompleted = completedNum.toString()
                                    const newStatus = computeStatusFromCompleted(totalNum, completedNum)
                                    setEditingTaskCompleted(newCompleted)
                                    setControlEdits((prev) => ({
                                      ...prev,
                                      [task.id]: { ...prev[task.id], completed: newCompleted, status: newStatus },
                                    }))
                                  }}
                                  className="w-full bg-transparent border-0 border-b-2 border-blue-500 outline-none py-1 text-sm text-left"
                                />
                              ) : (
                                <div className="flex items-center justify-start gap-2">
                                  <button
                                    type="button"
                                    className="h-6 w-6 rounded-full border border-slate-300 text-slate-500 hover:text-slate-700"
                                    onClick={async () => {
                                      const prevCompleted = controlEdits[task.id]?.completed || "0"
                                      const completedNum = Math.max(0, toNonNegativeInt(prevCompleted) - 1)
                                      const newCompleted = completedNum.toString()
                                      const newStatus = computeStatusFromCompleted(totalVal, completedNum)
                                      setControlEdits((prev) => ({
                                        ...prev,
                                        [task.id]: { ...prev[task.id], completed: newCompleted, status: newStatus },
                                      }))
                                      const currentNotes = task.internal_notes || ""
                                      const originTaskId = getOriginTaskId(currentNotes)
                                      const koUserId = parseKoUserId(currentNotes)
                                      const productionDate = parseProductionDate(currentNotes)
                                      const internalNotes = serializeInternalNotes({
                                        originTaskId: originTaskId || undefined,
                                        total: controlEdits[task.id]?.total || totalVal.toString(),
                                        completed: newCompleted,
                                        koUserId: koUserId || null,
                                        productionDate: productionDate || null,
                                      })
                                      const res = await apiFetch(`/tasks/${task.id}`, {
                                        method: "PATCH",
                                        headers: { "Content-Type": "application/json" },
                                        body: JSON.stringify({
                                          internal_notes: internalNotes,
                                          due_date: productionDate ? new Date(productionDate).toISOString() : null,
                                        }),
                                      })
                                      if (!res?.ok) {
                                        toast.error("Failed to update completed count")
                                        const prevStatus = computeStatusFromCompleted(totalVal, toNonNegativeInt(prevCompleted))
                                        setControlEdits((prev) => ({
                                          ...prev,
                                          [task.id]: { ...prev[task.id], completed: prevCompleted, status: prevStatus },
                                        }))
                                        return
                                      }
                                      try {
                                        const updated = (await res.json()) as Task
                                        setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))
                                      } catch {
                                        // ignore JSON parse errors
                                      }
                                    }}
                                  >
                                    -
                                  </button>
                                  <div className="min-w-[32px] text-center text-sm text-slate-700">
                                    {controlEdits[task.id]?.completed || "0"}
                                  </div>
                                  <button
                                    type="button"
                                    className="h-6 w-6 rounded-full border border-slate-300 text-slate-500 hover:text-slate-700"
                                    onClick={async () => {
                                      const prevCompleted = controlEdits[task.id]?.completed || "0"
                                      const prevCompletedNum = toNonNegativeInt(prevCompleted)
                                      const completedNum = prevCompletedNum + 1
                                      const newCompleted = completedNum.toString()
                                      const newStatus = computeStatusFromCompleted(totalVal, completedNum)
                                      setControlEdits((prev) => ({
                                        ...prev,
                                        [task.id]: { ...prev[task.id], completed: newCompleted, status: newStatus },
                                      }))
                                      const currentNotes = task.internal_notes || ""
                                      const originTaskId = getOriginTaskId(currentNotes)
                                      const koUserId = parseKoUserId(currentNotes)
                                      const productionDate = parseProductionDate(currentNotes)
                                      const internalNotes = serializeInternalNotes({
                                        originTaskId: originTaskId || undefined,
                                        total: controlEdits[task.id]?.total || totalVal.toString(),
                                        completed: newCompleted,
                                        koUserId: koUserId || null,
                                        productionDate: productionDate || null,
                                      })
                                      const res = await apiFetch(`/tasks/${task.id}`, {
                                        method: "PATCH",
                                        headers: { "Content-Type": "application/json" },
                                        body: JSON.stringify({
                                          internal_notes: internalNotes,
                                          due_date: productionDate ? new Date(productionDate).toISOString() : null,
                                        }),
                                      })
                                      if (!res?.ok) {
                                        toast.error("Failed to update completed count")
                                        const prevStatus = computeStatusFromCompleted(totalVal, toNonNegativeInt(prevCompleted))
                                        setControlEdits((prev) => ({
                                          ...prev,
                                          [task.id]: { ...prev[task.id], completed: prevCompleted, status: prevStatus },
                                        }))
                                        return
                                      }
                                      try {
                                        const updated = (await res.json()) as Task
                                        setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))
                                      } catch {
                                        // ignore JSON parse errors
                                      }
                                    }}
                                  >
                                    +
                                  </button>
                                </div>
                              )}
                            </div>
                            <div className="col-span-1 px-2">
                              {isEditing ? (
                                <Select value={editingTaskKoUserId} onValueChange={setEditingTaskKoUserId}>
                                  <SelectTrigger className="h-8 w-full border-0 border-b-2 border-blue-500 rounded-none bg-transparent shadow-none px-1">
                                    <SelectValue placeholder="-" />
                                  </SelectTrigger>
                                  <SelectContent>
                                    <SelectItem value="__unassigned__">-</SelectItem>
                                    {members.map((u) => (
                                      <SelectItem key={u.id} value={u.id}>
                                        {u.full_name || u.username || u.email}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              ) : (
                                <span className="block truncate text-slate-500">{memberLabel(koUserId)}</span>
                              )}
                            </div>
                            <div className="col-span-1 px-2">
                              <Badge
                                variant={autoStatus === "DONE" ? "default" : "outline"}
                                className={autoStatus === "DONE" ? "bg-emerald-500 hover:bg-emerald-600" : "text-slate-600 border-slate-300"}
                              >
                                {statusLabel(autoStatus)}
                              </Badge>
                            </div>
                            <div className="col-span-1 text-right opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-end gap-1 px-2">
                              {isEditing ? (
                                <>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-8 px-2 text-slate-400 hover:text-blue-600"
                                    onClick={() => void saveTaskEdit()}
                                    disabled={savingTaskEdit}
                                  >
                                    {savingTaskEdit ? "Saving..." : "Save"}
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-8 px-2 text-slate-400 hover:text-slate-600"
                                    onClick={cancelEditTask}
                                  >
                                    Cancel
                                  </Button>
                                </>
                              ) : (
                                <>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-8 w-8 p-0 text-slate-400 hover:text-blue-600 hover:bg-blue-50"
                                    onClick={() => startEditTask(task)}
                                  >
                                    <Pencil className="h-4 w-4" />
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-8 w-8 p-0 text-slate-400 hover:text-red-500 hover:bg-red-50"
                                    onClick={async () => {
                                      if (!(await confirmDeleteTask())) return
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
                                    <Trash2 className="h-4 w-4" />
                                  </Button>
                                </>
                              )}
                            </div>
                          </div>
                        )
                      })}
                      {tasks.length === 0 ? (
                        <div className="py-8 text-center text-sm text-slate-400">
                          No tasks yet. Add one above to get started.
                        </div>
                      ) : null}
                    </div>
                  </div>
                </Card>
              )}
            </>
          ) : mstPhase === "FINAL" ? (
            <>
              <div className="border-b flex gap-6">
                {[
                  { id: "final", label: "Finalizimi" },
                  { id: "ga", label: "Shenime GA/KA" },
                ].map((tab) => {
                  const isActive = mstTab === tab.id
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setMstTab(tab.id as typeof mstTab)}
                      className={[
                        "relative pb-3 text-sm font-medium",
                        tab.id === "ga" ? "ml-auto" : "",
                        isActive ? "text-blue-600" : "text-muted-foreground",
                      ].join(" ")}
                    >
                      {tab.label}
                      {isActive ? <span className="absolute inset-x-0 bottom-0 h-0.5 bg-blue-600" /> : null}
                    </button>
                  )
                })}
              </div>
              {mstTab === "ga" ? (
                renderGaNotes()
              ) : (
                <Card className="border-0 shadow-sm">
                  <div className="p-6 space-y-6">
                    <div className="text-lg font-semibold tracking-tight">Finalizimi - Checklist</div>

                    <div className="space-y-4">
                      {finalizationItems
                        .slice()
                        .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))
                        .map((item, index) => {
                          const isEditing = editingFinalizationId === item.id
                          const itemNumber = item.position ?? index + 1
                          return (
                            <div
                              key={item.id}
                              className="flex items-center gap-4 p-4 rounded-lg border border-slate-100 hover:bg-slate-50/70 transition-colors"
                            >
                              <div className="w-10 text-right text-xs text-muted-foreground">
                                {isEditing ? (
                                  <Input
                                    type="number"
                                    min={1}
                                    inputMode="numeric"
                                    value={editingFinalizationNumber}
                                    onChange={(e) => setEditingFinalizationNumber(e.target.value)}
                                    className="h-8 w-14 text-right"
                                  />
                                ) : (
                                  itemNumber ? `${itemNumber}.` : "-"
                                )}
                              </div>
                              <Checkbox
                                id={item.id}
                                checked={Boolean(finalizationChecks[item.id])}
                                onCheckedChange={(checked) =>
                                  void toggleFinalizationChecklist(item.id, Boolean(checked))
                                }
                              />
                              <div className="flex-1">
                                {isEditing ? (
                                  <Input
                                    value={editingFinalizationText}
                                    onChange={(e) => setEditingFinalizationText(e.target.value)}
                                    onKeyDown={(e) => {
                                      if (e.key === "Enter" && !savingFinalization) {
                                        void saveFinalizationItem()
                                      } else if (e.key === "Escape") {
                                        cancelEditFinalizationItem()
                                      }
                                    }}
                                    className="border-slate-200"
                                    autoFocus
                                  />
                                ) : (
                                  <label
                                    htmlFor={item.id}
                                    className={`text-sm font-medium cursor-pointer ${finalizationChecks[item.id] ? "text-slate-400 line-through" : "text-slate-700"}`}
                                  >
                                    {item.title}
                                  </label>
                                )}
                              </div>
                              <div className="flex items-center gap-2">
                                {isEditing ? (
                                  <>
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={() => void saveFinalizationItem()}
                                      disabled={savingFinalization}
                                    >
                                      Save
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      onClick={cancelEditFinalizationItem}
                                    >
                                      Cancel
                                    </Button>
                                  </>
                                ) : (
                                  <>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      onClick={() => startEditFinalizationItem(item.id)}
                                    >
                                      Edit
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      onClick={() => void deleteFinalizationItem(item.id)}
                                      className="text-red-600 hover:text-red-700"
                                    >
                                      Delete
                                    </Button>
                                  </>
                                )}
                              </div>
                            </div>
                          )
                        })}
                      {finalizationItems.length === 0 && (
                        <div className="text-sm text-muted-foreground text-center py-8">
                          No checklist items yet. Add one above.
                        </div>
                      )}
                    </div>
                    {/* Add new item */}
                    <div className="flex items-center gap-2 pt-2">
                      <Input
                        type="number"
                        min={1}
                        inputMode="numeric"
                        placeholder="No."
                        value={newFinalizationNumber}
                        onChange={(e) => setNewFinalizationNumber(e.target.value)}
                        className="w-24"
                      />
                      <Input
                        placeholder="Add checklist item..."
                        value={newFinalizationText}
                        onChange={(e) => setNewFinalizationText(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !savingFinalization) {
                            void addFinalizationItem()
                          }
                        }}
                        className="flex-1"
                      />
                      <Button
                        onClick={() => void addFinalizationItem()}
                        disabled={!newFinalizationText.trim() || savingFinalization}
                        size="sm"
                      >
                        {savingFinalization ? "Adding..." : "Add"}
                      </Button>
                    </div>
                    {isFinalizationComplete && (
                      <div className="p-4 rounded-lg bg-emerald-50 border border-emerald-200">
                        <div className="flex items-center gap-2 text-emerald-700 font-medium">
                          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>
                          Projekti eshte gati per mbyllje!
                        </div>
                      </div>
                    )}
                    {isFinalizationComplete && canCloseFromFinal && canCloseProject ? (
                      <div className="flex justify-end">
                        <Button
                          variant="outline"
                          disabled={advancingPhase}
                          onClick={() => requestCloseProject("mst")}
                        >
                          {advancingPhase ? "Closing..." : "Close Project"}
                        </Button>
                      </div>
                  ) : null}
                  </div>
                </Card>
              )}
            </>
          ) : (
            <Card>
              <div className="p-4 space-y-3">
                <div className="text-lg font-semibold">{MST_PHASE_LABELS[mstPhase]}</div>
                <div className="text-sm text-muted-foreground">{project.description || "No description."}</div>
              </div>
            </Card>
          )}
        </div>
        {renderEditDueDateDialog()}
        {renderStartDateDialog()}
        {renderEditStartDateDialog()}
        {renderCloseConfirmDialog()}
      </>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <button type="button" onClick={() => router.back()} className="text-sm text-muted-foreground hover:text-foreground">&larr; Back to Projects</button>
          <div className="mt-3 flex items-center gap-3">
            {renderProjectTitle()}
            <ProjectActivityControl project={project} onChange={setProject} />
            {isAdmin && (
              <>
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
                    className="text-sm text-muted-foreground hover:text-foreground cursor-pointer underline"
                    title="Edit project due date"
                  >
                    {project.due_date ? `Due: ${formatDateDisplay(project.due_date)}` : "Set due date"}
                  </button>
                )}
                {!canEditDueDate && project.due_date && (
                  <span className="text-sm text-muted-foreground">Due: {formatDateDisplay(project.due_date)}</span>
                )}
              </>
            )}
            {project?.is_template && (
              <Badge variant="secondary" className="text-amber-700 border-amber-300 bg-amber-50">Template</Badge>
            )}
          </div>
          <div className="mt-3">
            <Badge variant="outline" className="text-blue-600 border-blue-200 bg-blue-50">{PHASE_LABELS[phase] || "PCM"}</Badge>
          </div>
          <div className="mt-3 text-sm text-muted-foreground">
            {PHASES.map((p, idx) => {
              const isViewed = p === activePhase
              const isCurrent = p === phase
              const isLocked = idx > phaseIndex
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
                    {PHASE_LABELS[p]}
                  </button>
                  {idx < PHASES.length - 1 ? " -> " : ""}
                </span>
              )
            })}
          </div>
          {activePhase !== phase ? <div className="mt-2 text-xs text-muted-foreground">View: {PHASE_LABELS[activePhase] || "PCM"}</div> : null}
        </div>
        <div className="flex items-center gap-3">
          {user?.role === "ADMIN" && (
            <label className="flex items-center gap-2 text-sm cursor-pointer">
              <Checkbox
                checked={project?.is_template ?? false}
                onCheckedChange={() => void toggleTemplate()}
              />
              <span className="text-muted-foreground">Template</span>
            </label>
          )}
          <Button className="rounded-xl">Settings</Button>
        </div>
      </div>

      <div className="flex justify-end">
        <Button variant="outline" disabled={!canClosePhase || advancingPhase} onClick={() => void advancePhase()}>{advancingPhase ? "Closing..." : "Close Phase"}</Button>
      </div>

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
                  tab.id === "ga" ? "ml-auto" : "",
                  isActive ? "text-blue-600" : "text-muted-foreground",
                ].join(" ")}
              >
                {tab.label}
                {isActive ? <span className="absolute inset-x-0 bottom-0 h-0.5 bg-blue-600" /> : null}
              </button>
            )
          })}
        </div>
      </div>

      {activeTab === "meeting-focus" ? (
        <Card className="p-6 mt-6">
          <div className="text-lg font-semibold">Meeting focus</div>
          <div className="mt-2 text-sm text-muted-foreground">Main points to discuss in the meeting.</div>
          <div className="mt-4 space-y-2">
            {MEETING_POINTS.map((point) => (
              <div key={point} className="flex items-start gap-2 text-sm text-muted-foreground">
                <span className="mt-1 h-2 w-2 rounded-full bg-blue-500" aria-hidden />
                <span>{point}</span>
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {activeTab === "meeting-checklist" ? (
        <Card className="p-6 mt-6">
          <div className="text-lg font-semibold">Meeting checklist</div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
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
          <div className="mt-3 space-y-3">
            {meetingChecklist.length ? (
              meetingChecklist.map((item, index) => {
                const isEditing = editingMeetingItemId === item.id
                return (
                  <div key={item.id} className="flex flex-wrap items-start gap-3 rounded-lg border px-4 py-3">
                    <div className="mt-1 text-xs font-semibold text-slate-400">{index + 1}.</div>
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
          </div>
        </Card>
      ) : null}

      {/* Keep the rest of rendering logic similar to the source component; tabs will include Financials placeholder when active */}
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
      {renderEditDueDateDialog()}
    </div>
  )
}
