"use client"

import * as React from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { cn } from "@/lib/utils"

type PcmTaskStatus = "Done" | "In Progress" | "Pending"

type PcmTask = {
  id: string
  label: string
  assignee: string
  reviewer: string
  total: number
  done: number
}

type PcmChecklistItem = {
  id: string
  keyword: string
  task: string
  description: string
  category: string
  checked: boolean
  owner: string
}

type PcmTeamMember = {
  id: string
  name: string
  role: string
  initials: string
  tone: string
}

type PcmMstDetailProps = {
  projectTitle?: string | null
  projectStatus?: string | null
  onBack: () => void
}

const PCM_PHASES = ["Planifikimi", "Produkte", "Kontrolli", "Finalizimi"] as const
const PCM_CURRENT_PHASE = "Produkte"

const PCM_TASKS: PcmTask[] = [
  {
    id: "schrank-ldb",
    label: "P.SH PUNIMI I KATEGORISE SCHRANK LDB",
    assignee: "DV",
    reviewer: "LM",
    total: 125,
    done: 60,
  },
  {
    id: "sideboard-ldb",
    label: "P.SH PUNIMI I KATEGORISE SIDEBOARD LDB",
    assignee: "LM",
    reviewer: "DV",
    total: 330,
    done: 330,
  },
  {
    id: "wall-unit",
    label: "PUNIMI I KATEGORISE WALL UNIT",
    assignee: "EP",
    reviewer: "DV",
    total: 50,
    done: 0,
  },
]

const PCM_CHECKLIST: PcmChecklistItem[] = [
  {
    id: "open-project",
    keyword: "HAPJA E PROJEKTIT",
    task: "Hapja e projektit",
    description: "Hapet grupi ne Teams, dergohen dokumentet (PDF, Excel, Foto).",
    category: "GJENERALE",
    checked: true,
    owner: "DV",
  },
  {
    id: "checklist",
    keyword: "CHECKLISTA",
    task: "Shtypet Checklista",
    description: "Nese nuk kemi duke punuar rastin e pare, krijohet checklista fizike.",
    category: "GJENERALE",
    checked: true,
    owner: "LM",
  },
  {
    id: "r1",
    keyword: "RAST 1 (R1)",
    task: "Hulumtimi i kategorise",
    description: "Kur kemi kategori te re, hulumtohen TOP SELLER ne Otto/Amazon.",
    category: "GJENERALE",
    checked: false,
    owner: "DM",
  },
  {
    id: "besondere",
    keyword: "BESONDERE",
    task: "Besondere Merkmale",
    description: "Max 70 Karaktere. Cek vecorite me unike te produktit.",
    category: "GJENERALE",
    checked: false,
    owner: "EP",
  },
  {
    id: "selling-point-1",
    keyword: "SELLING POINTS",
    task: "Selling Point 1",
    description: "5 JAHRE GARANTIE (FIKSE)",
    category: "GJENERALE",
    checked: false,
    owner: "All",
  },
  {
    id: "selling-point-5",
    keyword: "SELLING POINTS",
    task: "Selling Point 5",
    description: "MADE IN GERMANY (Nese eshte ne PDF), perndryshe Dimensionet.",
    category: "GJENERALE",
    checked: false,
    owner: "All",
  },
  {
    id: "markeninfo",
    keyword: "MARKENINFO",
    task: "Set One vs MST",
    description: "Kujdes te zgjidhet teksti i duhur (shih dok. referues).",
    category: "GJENERALE",
    checked: false,
    owner: "DV",
  },
  {
    id: "set-type",
    keyword: "SET / TYPE",
    task: "Specifika per Karrige",
    description: "A shiten si set (2,4,6) apo cope? Konfirmo me email.",
    category: "CHAIRS",
    checked: false,
    owner: "LM",
  },
]

const PCM_TEAM: PcmTeamMember[] = [
  { id: "dm", name: "Diellza Muja", role: "Manager", initials: "DM", tone: "bg-blue-100 text-blue-700" },
  { id: "dv", name: "Diellza Veliu", role: "Senior PCM", initials: "DV", tone: "bg-emerald-100 text-emerald-700" },
  { id: "lm", name: "Lea Murtiri", role: "PCM", initials: "LM", tone: "bg-purple-100 text-purple-700" },
  { id: "ep", name: "Elza Preniqi", role: "PCM", initials: "EP", tone: "bg-red-100 text-red-700" },
  { id: "es", name: "Enesa Sharku", role: "PCM", initials: "ES", tone: "bg-amber-100 text-amber-700" },
]

const STATUS_STYLES: Record<PcmTaskStatus, string> = {
  Done: "border-emerald-200 bg-emerald-50 text-emerald-700",
  "In Progress": "border-blue-200 bg-blue-50 text-blue-700",
  Pending: "border-slate-200 bg-slate-100 text-slate-700",
}

const CHECKLIST_WARNING = [
  "!!! EMRI I KLIENTIT NUK GUXON TE SHKRUHET I PLOTE",
  "!!! CDO KATEGORI E RE PARAQITET SI RAST I PARE (R1)",
  "!!! KRAHASO TE DHENAT: PDF vs EXCEL vs DROPDOWN",
  "!!! BESONDERE MERKMALE - MAX 70 CHARACTERS",
].join("\n")

const PROJECT_STATUS_BADGES: Record<string, { label: string; className: string }> = {
  TODO: {
    label: "To do",
    className: "border-slate-200 bg-slate-50 text-slate-700",
  },
  IN_PROGRESS: {
    label: "In progress",
    className: "border-amber-200 bg-amber-50 text-amber-700",
  },
  WAITING_CLIENT: {
    label: "WFE",
    className: "border-[#B8860B] bg-[#E2C15B] text-[#4F3A00]",
  },
  WAITING_CONFIRMATION: {
    label: "WFC INT",
    className: "border-teal-300 bg-teal-100 text-teal-900",
  },
  DONE: {
    label: "Done",
    className: "border-emerald-200 bg-emerald-50 text-emerald-700",
  },
}

function getProjectBadge(status?: string | null) {
  if (!status) return { label: "PCM", className: "border-blue-200 bg-blue-50 text-blue-700" }
  return PROJECT_STATUS_BADGES[status] || { label: "PCM", className: "border-blue-200 bg-blue-50 text-blue-700" }
}

function getTaskStatus(total: number, done: number): PcmTaskStatus {
  if (total > 0 && done >= total) return "Done"
  if (done > 0) return "In Progress"
  return "Pending"
}

export function PcmMstDetail({ projectTitle, projectStatus, onBack }: PcmMstDetailProps) {
  const [activeTab, setActiveTab] = React.useState<"general" | "tasks" | "checklist" | "team">("general")
  const [programName, setProgramName] = React.useState("V-Alpin 2025")
  const [tasks, setTasks] = React.useState<PcmTask[]>(PCM_TASKS)

  const baseTitle = (projectTitle || "MST").trim() || "MST"
  const detailTitle = programName.trim() ? `${baseTitle} - ${programName.trim()}` : baseTitle
  const detailBadge = getProjectBadge(projectStatus)
  const checklistTitle = `${baseTitle} MASTER CHECKLIST`

  const updateTask = (id: string, field: "total" | "done", value: string) => {
    const parsed = Number.parseInt(value, 10)
    const nextValue = Number.isNaN(parsed) ? 0 : Math.max(0, parsed)
    setTasks((prev) =>
      prev.map((task) => (task.id === id ? { ...task, [field]: nextValue } : task))
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b pb-4">
        <div className="space-y-3">
          <Button variant="ghost" className="px-0 text-muted-foreground" onClick={onBack}>
            &larr; Kthehu tek Projektet
          </Button>
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-3">
              <div className="text-2xl font-semibold">{detailTitle}</div>
              <Badge className={detailBadge.className}>{detailBadge.label}</Badge>
            </div>
            <div className="flex flex-wrap items-center text-xs text-muted-foreground">
              {PCM_PHASES.map((phase, index) => (
                <span key={phase} className="flex items-center">
                  <span className={phase === PCM_CURRENT_PHASE ? "font-semibold text-blue-600" : undefined}>
                    {phase}
                  </span>
                  {index < PCM_PHASES.length - 1 ? <span className="mx-2 text-slate-300">-&gt;</span> : null}
                </span>
              ))}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline">Export Report</Button>
          <Button>Settings</Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 border-b pb-2">
        {[
          { id: "general", label: "General Info" },
          { id: "tasks", label: "Tasks & Progress" },
          { id: "checklist", label: "Master Checklist" },
          { id: "team", label: "Team" },
        ].map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id as typeof activeTab)}
            className={cn(
              "border-b-2 px-3 pb-2 text-sm font-medium transition",
              activeTab === tab.id ? "border-primary text-primary" : "border-transparent text-muted-foreground"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "general" ? (
        <Card className="p-6 space-y-4">
          <div className="overflow-hidden rounded-lg border">
            <table className="w-full border-collapse text-sm">
              <thead className="bg-muted/40 text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 text-left" colSpan={2}>
                    PROJEKTI: {baseTitle}
                  </th>
                  <th className="px-4 py-3 text-left">EMRI I PROGRAMIT:</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                <tr>
                  <td className="px-4 py-3">
                    <Checkbox defaultChecked />
                  </td>
                  <td className="px-4 py-3">A ESHTE HAPUR GRUPI NE TEAMS</td>
                  <td className="px-4 py-3" rowSpan={2}>
                    <Textarea
                      value={programName}
                      onChange={(event) => setProgramName(event.target.value)}
                      placeholder="Shkruaj emrin e programit..."
                      className="min-h-[72px]"
                    />
                  </td>
                </tr>
                <tr>
                  <td className="px-4 py-3">
                    <Checkbox />
                  </td>
                  <td className="px-4 py-3">A ESHTE HAPUR PROJEKTI NE CHAT GPT?</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="overflow-hidden rounded-lg border">
            <table className="w-full border-collapse text-sm">
              <thead className="bg-muted/40 text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 text-left">DESCRIPTION/GENERAL POINTS</th>
                  <th className="px-4 py-3 text-left w-48">COMENT</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                <tr>
                  <td className="px-4 py-3">A JANE PRANUAR TE GJITHA DOKUMENTET E NEVOJSHME?</td>
                  <td className="px-4 py-3">
                    <Checkbox defaultChecked />
                  </td>
                </tr>
                <tr>
                  <td className="px-4 py-3">A ESHTE ANALIZUAR KATEGORIA DHE PDF?</td>
                  <td className="px-4 py-3">
                    <Checkbox />
                  </td>
                </tr>
                <tr>
                  <td className="px-4 py-3">A JANE IDENTIFIKUAR KARAKTERISTIKAT E PROGRAMIT?</td>
                  <td className="px-4 py-3">
                    <Input placeholder="Koment" />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      {activeTab === "tasks" ? (
        <Card className="p-6 space-y-4">
          <div>
            <div className="text-lg font-semibold">Product Entry Progress</div>
            <div className="text-sm text-muted-foreground">
              Sheno numrin total te produkteve dhe sa jane perfunduar per te kalkuluar statusin.
            </div>
          </div>
          <div className="overflow-hidden rounded-lg border">
            <table className="w-full border-collapse text-sm">
              <thead className="bg-muted/40 text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 text-left">Kategoria / Detyra</th>
                  <th className="px-4 py-3 text-left">Assigned To</th>
                  <th className="px-4 py-3 text-left">Total Nr i Produkteve</th>
                  <th className="px-4 py-3 text-left">Nr i Produkteve te Perfunduara</th>
                  <th className="px-4 py-3 text-left">KO (Review)</th>
                  <th className="px-4 py-3 text-left">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {tasks.map((task) => {
                  const status = getTaskStatus(task.total, task.done)
                  return (
                    <tr key={task.id}>
                      <td className="px-4 py-3">{task.label}</td>
                      <td className="px-4 py-3">{task.assignee}</td>
                      <td className="px-4 py-3">
                        <Input
                          type="number"
                          min={0}
                          value={task.total}
                          onChange={(event) => updateTask(task.id, "total", event.target.value)}
                          className="h-8 w-24 text-center"
                        />
                      </td>
                      <td className="px-4 py-3">
                        <Input
                          type="number"
                          min={0}
                          value={task.done}
                          onChange={(event) => updateTask(task.id, "done", event.target.value)}
                          className="h-8 w-24 text-center"
                        />
                      </td>
                      <td className="px-4 py-3">{task.reviewer}</td>
                      <td className="px-4 py-3">
                        <Badge variant="outline" className={cn("border px-2 py-0.5 text-xs", STATUS_STYLES[status])}>
                          {status}
                        </Badge>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      {activeTab === "checklist" ? (
        <Card className="p-6">
          <div className="max-h-[70vh] overflow-y-auto pr-2">
            <div className="sticky top-0 z-10 space-y-2 border-b bg-background pb-3">
              <div className="text-base font-semibold">{checklistTitle}</div>
              <div className="whitespace-pre-line rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-xs font-semibold text-red-700">
                {CHECKLIST_WARNING}
              </div>
            </div>
            <div className="mt-4 overflow-hidden rounded-lg border">
              <table className="w-full table-fixed border-collapse text-sm">
                <colgroup>
                  <col className="w-[15%]" />
                  <col className="w-[25%]" />
                  <col className="w-[30%]" />
                  <col className="w-[10%]" />
                  <col className="w-[10%]" />
                  <col className="w-[10%]" />
                </colgroup>
                <thead className="bg-muted/40 text-xs uppercase text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 text-left">KEYWORDS</th>
                    <th className="px-4 py-3 text-left">DETYRA</th>
                    <th className="px-4 py-3 text-left">PERSHKRIMI &amp; RREGULLAT</th>
                    <th className="px-4 py-3 text-left">KATEGORIA</th>
                    <th className="px-4 py-3 text-left">CHECK</th>
                    <th className="px-4 py-3 text-left">RESP</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {PCM_CHECKLIST.map((item) => (
                    <tr key={item.id}>
                      <td className="px-4 py-3 font-semibold">{item.keyword}</td>
                      <td className="px-4 py-3">{item.task}</td>
                      <td className="px-4 py-3 text-muted-foreground">{item.description}</td>
                      <td className="px-4 py-3">{item.category}</td>
                      <td className="px-4 py-3">
                        <Checkbox defaultChecked={item.checked} />
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant="secondary" className="text-xs">
                          {item.owner}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </Card>
      ) : null}

      {activeTab === "team" ? (
        <Card className="p-6">
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {PCM_TEAM.map((member) => (
              <div key={member.id} className="flex flex-col items-center text-center">
                <div
                  className={cn(
                    "mb-3 grid h-16 w-16 place-items-center rounded-full text-lg font-semibold",
                    member.tone
                  )}
                >
                  {member.initials}
                </div>
                <div className="text-sm font-semibold">{member.name}</div>
                <div className="text-xs text-muted-foreground">{member.role}</div>
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  )
}
