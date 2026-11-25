"use client"

import * as React from "react"
import { TaskPauseBadge } from "@/components/task-pause-field"
import { isTaskPausedOnDay } from "@/lib/task-pause"
import Link from "next/link"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { TaskOneHMarkerEditor } from "@/components/task-one-h-marker-editor"
import { updateTaskMarkersInTree, useTaskMarkerUpdates } from "@/lib/task-marker-updates"
import { TaskMarkerComment } from "@/components/task-marker-comment"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useAuth } from "@/lib/auth"
import type { Department, Task, User } from "@/lib/types"

type MonthlySummary = { month_completed: number; previous_month_completed: number }
type MonthlyResponse = {
  month_start: string
  month_end: string
  tasks: Task[]
  recurring: Task[]
  summary: MonthlySummary
}

function formatPlannerDay(value: string) {
  const parsed = new Date(`${value}T00:00:00`)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleDateString("en-GB", {
    weekday: "long",
    day: "2-digit",
    month: "short",
    year: "numeric",
  })
}

export default function MonthlyPlannerPage() {
  const { apiFetch, user } = useAuth()
  const now = new Date()
  const [year, setYear] = React.useState(String(now.getFullYear()))
  const [month, setMonth] = React.useState(String(now.getMonth() + 1))
  const ALL_USERS_VALUE = "__all__"
  const [departments, setDepartments] = React.useState<Department[]>([])
  const [users, setUsers] = React.useState<User[]>([])
  const [departmentId, setDepartmentId] = React.useState<string>("")
  const [userId, setUserId] = React.useState<string>(ALL_USERS_VALUE)
  const [data, setData] = React.useState<MonthlyResponse | null>(null)
  useTaskMarkerUpdates(update => setData(current => updateTaskMarkersInTree(current, update)))
  const [filtersReady, setFiltersReady] = React.useState(false)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (!user) return
    let cancelled = false

    const boot = async () => {
      const [depRes, userRes] = await Promise.all([
        apiFetch("/departments"),
        user.role !== "STAFF" ? apiFetch("/users") : Promise.resolve(null),
      ])
      if (cancelled) return

      const deps = depRes.ok ? ((await depRes.json()) as Department[]) : []
      const loadedUsers = userRes?.ok ? ((await userRes.json()) as User[]) : []
      if (cancelled) return

      setDepartments(deps)
      setDepartmentId(user.department_id || deps[0]?.id || "")
      setUsers(loadedUsers)
      setFiltersReady(true)
    }
    void boot()

    return () => {
      cancelled = true
    }
  }, [apiFetch, user])

  React.useEffect(() => {
    if (!user || !filtersReady) return
    let active = true

    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const qs = new URLSearchParams()
        qs.set("year", year)
        qs.set("month", month)
        if (departmentId) qs.set("department_id", departmentId)
        if (userId && userId !== ALL_USERS_VALUE) qs.set("user_id", userId)
        const res = await apiFetch(`/planners/monthly?${qs.toString()}`)
        if (!res.ok) {
          let detail = "Could not load the monthly planner."
          try {
            const payload = (await res.json()) as { detail?: string }
            if (payload.detail) detail = payload.detail
          } catch {
            // Keep the fallback message when the API does not return JSON.
          }
          throw new Error(`${detail} (${res.status})`)
        }
        const responseData = (await res.json()) as MonthlyResponse
        if (active) setData(responseData)
      } catch (loadError) {
        if (active) {
          setError(loadError instanceof Error ? loadError.message : "Could not load the monthly planner.")
        }
      } finally {
        if (active) setLoading(false)
      }
    }
    void load()

    return () => {
      active = false
    }
  }, [apiFetch, year, month, departmentId, filtersReady, user, userId])

  const tasksByDay = React.useMemo(() => {
    const map = new Map<string, Task[]>()
    if (!data) return map
    for (const t of data.tasks) {
      const d = (t.due_date || t.start_date || t.planned_for || "").slice(0, 10)
      if (!d) continue
      map.set(d, [...(map.get(d) || []), t])
    }
    return map
  }, [data])

  return (
    <div className="space-y-4">
      <div className="text-lg font-semibold">Monthly Planner</div>
      <div className="grid gap-3 md:grid-cols-4">
        <div className="space-y-2">
          <Label>Year</Label>
          <Input value={year} onChange={(e) => setYear(e.target.value)} />
        </div>
        <div className="space-y-2">
          <Label>Month</Label>
          <Select value={month} onValueChange={setMonth}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Array.from({ length: 12 }).map((_, i) => (
                <SelectItem key={i + 1} value={String(i + 1)}>
                  {i + 1}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {user?.role !== "STAFF" ? (
          <div className="space-y-2">
            <Label>Department</Label>
            <Select value={departmentId} onValueChange={setDepartmentId}>
              <SelectTrigger>
                <SelectValue placeholder="Department" />
              </SelectTrigger>
              <SelectContent>
                {departments.map((d) => (
                  <SelectItem key={d.id} value={d.id}>
                    {d.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}
        {user?.role !== "STAFF" ? (
          <div className="space-y-2">
            <Label>User</Label>
            <Select value={userId} onValueChange={setUserId}>
              <SelectTrigger>
                <SelectValue placeholder="All users" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_USERS_VALUE}>All users</SelectItem>
                {users
                  .filter((u) => !departmentId || u.department_id === departmentId)
                  .map((u) => (
                    <SelectItem key={u.id} value={u.id}>
                      {u.full_name || u.username}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}
      </div>

      {loading && data ? <div className="text-sm text-muted-foreground">Updating planner...</div> : null}

      {!data && error ? (
        <div className="text-sm text-red-600">{error}</div>
      ) : data ? (
        <div className="space-y-4">
          <div className="grid gap-4 md:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Completed (planned this month)</CardTitle>
              </CardHeader>
              <CardContent className="text-2xl font-semibold">{data.summary.month_completed}</CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Previous month</CardTitle>
              </CardHeader>
              <CardContent className="text-2xl font-semibold">{data.summary.previous_month_completed}</CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Recurring</CardTitle>
              </CardHeader>
              <CardContent className="text-2xl font-semibold">
                {data.recurring.length}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm">List view</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {Array.from(tasksByDay.entries())
                  .sort((a, b) => a[0].localeCompare(b[0]))
                  .map(([d, list]) => (
                    <section key={d} className="overflow-hidden rounded-lg border border-slate-200 bg-white">
                      <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-slate-50 px-3 py-2">
                        <div className="text-sm font-semibold text-slate-700">{formatPlannerDay(d)}</div>
                        <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs font-semibold text-slate-600">
                          {list.length}
                        </span>
                      </div>
                      <div className="divide-y divide-slate-100">
                        {list.map((t) => (
                          <Link
                            key={t.id}
                            href={`/tasks/${t.id}`}
                            className="block px-3 py-2.5 text-sm text-slate-700 transition-colors hover:bg-blue-50 hover:text-blue-700"
                          >
                            <span className="flex items-start gap-1.5">
                              <TaskOneHMarkerEditor taskId={t.id} marker={t.one_h_marker} markerByGa={t.one_h_marker_by_ga} markerComment={t.one_h_marker_comment} />
                              <span className="min-w-0"><TaskMarkerComment comment={t.one_h_marker_comment} taskId={t.id} />{t.title}</span>
                              {isTaskPausedOnDay(t, d) && <TaskPauseBadge />}
                            </span>
                          </Link>
                        ))}
                      </div>
                    </section>
                  ))}
              </div>
              {!tasksByDay.size ? <div className="text-sm text-muted-foreground">No tasks scheduled.</div> : null}
            </CardContent>
          </Card>
        </div>
      ) : (
        <div className="text-sm text-muted-foreground">Loading planner…</div>
      )}
    </div>
  )
}


