"use client"

import * as React from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useAuth } from "@/lib/auth"
import type { Department, Project, TaskStatus, User } from "@/lib/types"
import { weeklyPlanStatusBgClass } from "@/lib/weekly-plan-status"

type PreviewType = "fast" | "system" | "project"
type FastTaskKind = "fast" | "1h" | "p" | "r1" | "bllok"

const FAST_TASK_KIND_OPTIONS: Array<{ value: FastTaskKind; label: string }> = [
  { value: "fast", label: "Fast" },
  { value: "1h", label: "1H" },
  { value: "p", label: "P" },
  { value: "r1", label: "R1" },
  { value: "bllok", label: "BLL" },
]

const ALL_FAST_TASK_KINDS = FAST_TASK_KIND_OPTIONS.map((option) => option.value)
const REPORT_BUNDLE_FAST_TASK_KINDS: FastTaskKind[] = ["1h", "r1", "p", "bllok"]

type PreviewResponse = {
  headers: string[]
  rows: string[][]
  total?: number
  truncated?: boolean
}

export default function ReportsPage() {
  const { user, apiFetch } = useAuth()
  const canViewAllDepartments = user?.role === "ADMIN" || user?.role === "MANAGER"
  const [departments, setDepartments] = React.useState<Department[]>([])
  const [users, setUsers] = React.useState<User[]>([])
  const [projects, setProjects] = React.useState<Project[]>([])
  const [statuses, setStatuses] = React.useState<TaskStatus[]>([])

  const ALL_DEPARTMENTS_VALUE = "__all__"
  const ALL_USERS_VALUE = "__all_users__"
  const ALL_PROJECTS_VALUE = "__all_projects__"
  const ALL_STATUSES_VALUE = "__all_statuses__"
  const [departmentId, setDepartmentId] = React.useState(ALL_DEPARTMENTS_VALUE)
  const [userId, setUserId] = React.useState(ALL_USERS_VALUE)
  const [projectId, setProjectId] = React.useState(ALL_PROJECTS_VALUE)
  const [statusId, setStatusId] = React.useState(ALL_STATUSES_VALUE)
  const [selectedFastTaskKinds, setSelectedFastTaskKinds] = React.useState<FastTaskKind[]>(ALL_FAST_TASK_KINDS)
  const [plannedFrom, setPlannedFrom] = React.useState("")
  const [plannedTo, setPlannedTo] = React.useState("")
  const [previewType, setPreviewType] = React.useState<PreviewType>("fast")
  const [previewData, setPreviewData] = React.useState<PreviewResponse | null>(null)
  const [previewLoading, setPreviewLoading] = React.useState(false)
  const [previewError, setPreviewError] = React.useState<string | null>(null)
  const statusColumnIndex = React.useMemo(() => {
    if (!previewData?.headers?.length) return -1
    return previewData.headers.findIndex(
      (header) => header.trim().toLowerCase() === "status"
    )
  }, [previewData?.headers])

  const getStatusCellClass = (value: string) => {
    const normalized = value.trim().toLowerCase()
    if (!normalized) return ""
    if (normalized === "completed") return weeklyPlanStatusBgClass("DONE")
    if (normalized === "pending") return weeklyPlanStatusBgClass("TODO")
    if (normalized === "in progress") return weeklyPlanStatusBgClass("IN_PROGRESS")
    if (normalized === "paused" || normalized === "stopped") return weeklyPlanStatusBgClass("PAUSED")
    return weeklyPlanStatusBgClass(value)
  }

  const getFilenameFromDisposition = (disposition: string | null) => {
    if (!disposition) return null
    const filenameStarMatch = disposition.match(/filename\*\s*=\s*UTF-8''([^;]+)/i)
    if (filenameStarMatch?.[1]) return decodeURIComponent(filenameStarMatch[1])
    const filenameMatch = disposition.match(/filename\s*=\s*\"?([^\";]+)\"?/i)
    return filenameMatch?.[1] ?? null
  }

  React.useEffect(() => {
    const boot = async () => {
      const [dRes, uRes, pRes, sRes] = await Promise.all([
        apiFetch("/departments"),
        apiFetch("/users"),
        apiFetch("/projects"),
        apiFetch("/task-statuses"),
      ])
      if (dRes.ok) {
        const deps = (await dRes.json()) as Department[]
        setDepartments(deps)
        setDepartmentId(canViewAllDepartments ? ALL_DEPARTMENTS_VALUE : (user?.department_id || deps[0]?.id || ALL_DEPARTMENTS_VALUE))
      }
      if (uRes.ok) setUsers((await uRes.json()) as User[])
      if (pRes.ok) setProjects((await pRes.json()) as Project[])
      if (sRes.ok) setStatuses((await sRes.json()) as TaskStatus[])
    }
    if (user) void boot()
  }, [apiFetch, canViewAllDepartments, user])

  const allFastTaskKindsSelected = selectedFastTaskKinds.length === ALL_FAST_TASK_KINDS.length

  const toggleFastTaskKind = React.useCallback((kind: FastTaskKind, checked: boolean) => {
    setSelectedFastTaskKinds((current) => {
      if (checked) {
        if (current.includes(kind)) return current
        return [...current, kind]
      }
      return current.filter((value) => value !== kind)
    })
  }, [])

  const toggleAllFastTaskKinds = React.useCallback((checked: boolean) => {
    setSelectedFastTaskKinds(checked ? ALL_FAST_TASK_KINDS : [])
  }, [ALL_FAST_TASK_KINDS])

  const buildReportParams = React.useCallback(
    (options: { includeProject?: boolean; includeFastTaskKind?: boolean } = {}) => {
      const qs = new URLSearchParams()
      if (canViewAllDepartments) {
        if (departmentId && departmentId !== ALL_DEPARTMENTS_VALUE) qs.set("department_id", departmentId)
      } else if (user?.department_id) {
        qs.set("department_id", user.department_id)
      }
      if (userId && userId !== ALL_USERS_VALUE) qs.set("user_id", userId)
      if (statusId && statusId !== ALL_STATUSES_VALUE) qs.set("status_id", statusId)
      if (options.includeProject && projectId && projectId !== ALL_PROJECTS_VALUE) {
        qs.set("project_id", projectId)
      }
      if (options.includeFastTaskKind) {
        if (selectedFastTaskKinds.length === 0) {
          qs.set("fast_task_kind", "__none__")
        } else if (selectedFastTaskKinds.length !== ALL_FAST_TASK_KINDS.length) {
          selectedFastTaskKinds.forEach((kind) => qs.append("fast_task_kinds", kind))
        }
      }
      if (plannedFrom) qs.set("planned_from", plannedFrom)
      if (plannedTo) qs.set("planned_to", plannedTo)
      return qs
    },
    [
      departmentId,
      plannedFrom,
      plannedTo,
      projectId,
      selectedFastTaskKinds,
      statusId,
      user,
      canViewAllDepartments,
      userId,
      ALL_DEPARTMENTS_VALUE,
      ALL_FAST_TASK_KINDS.length,
      ALL_USERS_VALUE,
      ALL_PROJECTS_VALUE,
      ALL_STATUSES_VALUE,
    ]
  )

  const downloadFastTasks = async () => {
    const qs = buildReportParams({ includeFastTaskKind: true })
    const res = await apiFetch(`/exports/fast-tasks.xlsx?${qs.toString()}`)
    if (!res.ok) return
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    const downloadName =
      getFilenameFromDisposition(res.headers.get("content-disposition")) ?? "FAST_TASKS.xlsx"
    a.download = downloadName
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  const downloadBundleFastTasks = async () => {
    const qs = buildReportParams()
    REPORT_BUNDLE_FAST_TASK_KINDS.forEach((kind) => qs.append("fast_task_kinds", kind))
    const res = await apiFetch(`/exports/fast-tasks.xlsx?${qs.toString()}`)
    if (!res.ok) return
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    const downloadName =
      getFilenameFromDisposition(res.headers.get("content-disposition")) ?? "FAST_TASKS_1H_R1_P_BLL.xlsx"
    a.download = downloadName
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  const downloadSystemTasks = async () => {
    const qs = buildReportParams()
    const res = await apiFetch(`/exports/system-tasks.xlsx?${qs.toString()}`)
    if (!res.ok) return
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    const downloadName =
      getFilenameFromDisposition(res.headers.get("content-disposition")) ?? "SYSTEM_TASKS.xlsx"
    a.download = downloadName
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  const downloadProjectTasks = async () => {
    const selectedProject = projects.find((p) => p.id === projectId)
    const projectLabel = selectedProject ? selectedProject.name || selectedProject.title : null
    const reportTitle = projectLabel ? `${projectLabel} TASKS` : "PROJECT TASKS"
    const qs = buildReportParams({ includeProject: true })
    qs.set("standard", "true")
    qs.set("title", reportTitle)

    const res = await apiFetch(`/exports/tasks.xlsx?${qs.toString()}`)
    if (!res.ok) return
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    const downloadName =
      getFilenameFromDisposition(res.headers.get("content-disposition")) ?? "PROJECT_TASKS.xlsx"
    a.download = downloadName
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  React.useEffect(() => {
    if (!user) return
    let active = true
    const controller = new AbortController()
    const loadPreview = async () => {
      setPreviewLoading(true)
      setPreviewError(null)
      try {
        const qs = buildReportParams({
          includeProject: previewType === "project",
          includeFastTaskKind: previewType === "fast",
        })
        qs.set("limit", "200")
        const endpoint =
          previewType === "fast"
            ? "/exports/fast-tasks-preview"
            : previewType === "system"
              ? "/exports/system-tasks-preview"
              : "/exports/project-tasks-preview"
        const res = await apiFetch(`${endpoint}?${qs.toString()}`, { signal: controller.signal })
        if (!res.ok) {
          let detail = ""
          try {
            const payload = (await res.json()) as { detail?: string }
            if (payload?.detail) detail = payload.detail
          } catch {
            try {
              detail = await res.text()
            } catch {
              detail = ""
            }
          }
          const suffix = detail ? ` (${detail})` : ""
          if (active) setPreviewError(`Unable to load preview. [${res.status}]${suffix}`)
          return
        }
        const data = (await res.json()) as PreviewResponse
        if (active) setPreviewData(data)
      } catch (err) {
        if (active) setPreviewError("Unable to load preview.")
      } finally {
        if (active) setPreviewLoading(false)
      }
    }
    void loadPreview()
    return () => {
      active = false
      controller.abort()
    }
  }, [
    apiFetch,
    buildReportParams,
    plannedFrom,
    plannedTo,
    previewType,
    projectId,
    statusId,
    user,
    userId,
    departmentId,
  ])

  if (!user) {
    return <div className="text-sm text-muted-foreground">Forbidden.</div>
  }

  return (
    <div className="space-y-4">
      <div className="text-lg font-semibold">Reports & Exports</div>
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Export tasks</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            {canViewAllDepartments ? (
              <div className="space-y-2">
                <Label>Department</Label>
                <Select value={departmentId} onValueChange={setDepartmentId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Department" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ALL_DEPARTMENTS_VALUE}>All</SelectItem>
                    {departments.map((d) => (
                      <SelectItem key={d.id} value={d.id}>
                        {d.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : null}
            <div className="space-y-2">
              <Label>User</Label>
              <Select value={userId} onValueChange={setUserId}>
                <SelectTrigger>
                  <SelectValue placeholder="All users" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_USERS_VALUE}>All users</SelectItem>
                  {users
                    .filter((u) => (canViewAllDepartments ? true : u.department_id === user.department_id))
                    .map((u) => (
                      <SelectItem key={u.id} value={u.id}>
                        {u.full_name || u.username}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Project</Label>
              <Select value={projectId} onValueChange={setProjectId}>
                <SelectTrigger>
                  <SelectValue placeholder="All projects" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_PROJECTS_VALUE}>All projects</SelectItem>
                  {projects
                    .filter((p) => (canViewAllDepartments ? true : p.department_id === user.department_id))
                    .map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name || p.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Status</Label>
              <Select value={statusId} onValueChange={setStatusId}>
                <SelectTrigger>
                  <SelectValue placeholder="All statuses" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL_STATUSES_VALUE}>All statuses</SelectItem>
                  {statuses
                    .filter((s) =>
                      canViewAllDepartments
                        ? departmentId && departmentId !== ALL_DEPARTMENTS_VALUE
                          ? s.department_id === departmentId
                          : true
                        : s.department_id === user.department_id
                    )
                    .map((s) => (
                      <SelectItem key={s.id} value={s.id}>
                        {s.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Planned from</Label>
              <Input type="date" value={plannedFrom} onChange={(e) => setPlannedFrom(e.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>Planned to</Label>
              <Input type="date" value={plannedTo} onChange={(e) => setPlannedTo(e.target.value)} />
            </div>
            <div className="space-y-2 md:col-span-2">
              <Label>Fast task types for preview/export</Label>
              <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                <div className="flex flex-wrap gap-x-6 gap-y-3">
                  <label className="flex items-center gap-2 text-sm font-medium text-slate-700">
                    <Checkbox
                      checked={allFastTaskKindsSelected}
                      onCheckedChange={(value) => toggleAllFastTaskKinds(Boolean(value))}
                    />
                    <span>All fast task types</span>
                  </label>
                  {FAST_TASK_KIND_OPTIONS.map((option) => (
                    <label key={option.value} className="flex items-center gap-2 text-sm text-slate-700">
                      <Checkbox
                        checked={selectedFastTaskKinds.includes(option.value)}
                        onCheckedChange={(value) => toggleFastTaskKind(option.value, Boolean(value))}
                      />
                      <span>{option.label}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => void downloadFastTasks()}>
              Download Fast Tasks XLSX
            </Button>
            <Button variant="outline" onClick={() => void downloadBundleFastTasks()}>
              Download 1H + R1 + P + BLL XLSX
            </Button>
            <Button variant="outline" onClick={() => void downloadSystemTasks()}>
              Download System Tasks XLSX
            </Button>
            <Button variant="outline" onClick={() => void downloadProjectTasks()}>
              Download Project Tasks XLSX
            </Button>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Preview table</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-2">
              <Label>Preview type</Label>
              <Select value={previewType} onValueChange={(value) => setPreviewType(value as PreviewType)}>
                <SelectTrigger className="min-w-[180px]">
                  <SelectValue placeholder="Select preview" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="fast">Fast tasks</SelectItem>
                  <SelectItem value="system">System tasks</SelectItem>
                  <SelectItem value="project">Project tasks</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {previewData?.total ? (
              <div className="text-xs text-muted-foreground">
                Showing {previewData.rows.length} of {previewData.total}
                {previewData.truncated ? " (preview limit)" : ""}
              </div>
            ) : null}
          </div>
          {previewLoading ? (
            <div className="text-sm text-muted-foreground">Loading preview…</div>
          ) : previewError ? (
            <div className="text-sm text-destructive">{previewError}</div>
          ) : previewData?.rows?.length ? (
            <Table
              containerClassName="max-h-[420px] overflow-auto rounded-none border-2 border-slate-400 bg-white shadow-[inset_0_0_0_1px_rgba(148,163,184,0.35)]"
              className="border-collapse text-[11px]"
            >
              <TableHeader>
                <TableRow className="border-0">
                  {previewData.headers.map((header) => (
                    <TableHead
                      key={header}
                      className="sticky top-0 z-10 border border-slate-300 bg-slate-100 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-700"
                    >
                      {header}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {previewData.rows.map((row, rowIndex) => (
                  <TableRow key={`${rowIndex}-${row[0] || "row"}`} className="border-0">
                    {row.map((cell, cellIndex) => (
                      <TableCell
                        key={`${rowIndex}-${cellIndex}`}
                        className={`border border-slate-300 px-2 py-1 align-top text-[11px] text-slate-800 ${
                          cellIndex === statusColumnIndex ? getStatusCellClass(cell) : ""
                        }`}
                      >
                        {cell}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="text-sm text-muted-foreground">No rows match the current filters.</div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}


