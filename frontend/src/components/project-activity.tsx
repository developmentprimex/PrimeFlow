"use client"

import * as React from "react"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import type { Project } from "@/lib/types"
import { clearDepartmentBootstrapCache } from "@/lib/department-bootstrap-cache"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

export type ProjectActivityFilter = "active" | "inactive" | "all"

export function matchesProjectActivity(project: Project, filter: ProjectActivityFilter) {
  return filter === "all" || (project.is_active !== false) === (filter === "active")
}

export function ProjectActivityFilterControl({ value, onChange, projects }: {
  value: ProjectActivityFilter
  onChange: (value: ProjectActivityFilter) => void
  projects: Project[]
}) {
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Project activity filter">
      {(["active", "inactive", "all"] as const).map((filter) => (
        <button key={filter} type="button" aria-pressed={value === filter} onClick={() => onChange(filter)}
          className={`rounded-full border px-3 py-1.5 text-sm ${value === filter ? "border-slate-900 bg-slate-900 text-white dark:bg-white dark:text-slate-900" : "border-slate-200 bg-white text-slate-600 dark:bg-slate-900 dark:text-slate-300"}`}>
          {{ active: "Active", inactive: "Inactive", all: "All" }[filter]} ({projects.filter((project) => matchesProjectActivity(project, filter)).length})
        </button>
      ))}
    </div>
  )
}

export function ProjectActivityControl({ project, onChange, readOnly = false }: {
  project: Project
  onChange: (project: Project) => void
  readOnly?: boolean
}) {
  const { apiFetch, user } = useAuth()
  const [saving, setSaving] = React.useState(false)
  const active = project.is_active !== false
  const canChange = !readOnly && (user?.role === "ADMIN" || user?.role === "MANAGER")
  const className = `relative z-10 inline-flex h-5 shrink-0 rounded-full border px-2 py-0 text-[10px] font-medium ${active ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-slate-300 bg-slate-100 text-slate-500"}`

  async function saveActivity(nextActive: boolean) {
    if (nextActive === active || saving) return
    setSaving(true)
    try {
      const response = await apiFetch(`/projects/${project.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: nextActive }),
      })
      if (!response.ok) throw new Error("Failed to update project activity")
      const updated = await response.json() as Project
      clearDepartmentBootstrapCache()
      onChange(updated)
      toast.success(updated.is_active ? "Project activated" : "Project deactivated")
    } catch {
      toast.error("Failed to update project activity")
    } finally {
      setSaving(false)
    }
  }

  if (!canChange) return <span className={`${className} items-center gap-1.5`}><span className={`size-1.5 rounded-full ${active ? "bg-emerald-500" : "bg-slate-400"}`} />{active ? "Active" : "Inactive"}</span>
  return (
    <Select value={active ? "active" : "inactive"} disabled={saving}
      onValueChange={(value) => void saveActivity(value === "active")}>
      <SelectTrigger size="sm"
        className={`${className} data-[size=sm]:h-5 cursor-pointer gap-1.5 py-0 text-[10px] shadow-none [&_svg]:size-3 focus-visible:ring-2 ${active ? "hover:bg-emerald-100" : "hover:bg-slate-200"}`}
        aria-label={`Activity for project ${project.title || project.name || ""}`}
        aria-busy={saving}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => event.stopPropagation()}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent position="popper" align="end" sideOffset={4}
        className="min-w-36 rounded-xl border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900"
        onClick={(event) => event.stopPropagation()}>
        <SelectItem value="active" className="cursor-pointer rounded-lg py-2 text-xs text-emerald-700 focus:bg-emerald-50 focus:text-emerald-800 dark:text-emerald-400 dark:focus:bg-emerald-950 dark:focus:text-emerald-300">
          <span className="size-1.5 rounded-full bg-emerald-500" />Active
        </SelectItem>
        <SelectItem value="inactive" className="cursor-pointer rounded-lg py-2 text-xs text-slate-600 focus:bg-slate-100 focus:text-slate-900 dark:text-slate-300 dark:focus:bg-slate-800 dark:focus:text-slate-100">
          <span className="size-1.5 rounded-full bg-slate-400" />Inactive
        </SelectItem>
      </SelectContent>
    </Select>
  )
}

export function ProjectListEmptyState({ projects, visibleCount, mine, membersLoaded }: {
  projects: Project[]
  visibleCount: number
  mine: boolean
  membersLoaded: boolean
}) {
  if (visibleCount > 0) return null
  return (
    <p role="status" className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
      {mine && projects.length === 0
        ? membersLoaded
          ? "My View shows only projects where you are listed as a member. Switch to Department to see all projects."
          : "Loading project memberships..."
        : "No projects match this filter."}
    </p>
  )
}
