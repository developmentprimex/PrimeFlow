"use client"

import * as React from "react"
import Link from "next/link"
import { Gem, RefreshCw, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { DiamondAward, TaskReviewDialog } from "@/components/task-review-dialog"
import { useConfirm } from "@/components/providers/confirm-dialog-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useAuth } from "@/lib/auth"
import { formatDateDMY } from "@/lib/dates"
import { getPlainMarkedText } from "@/lib/note-markup"
import type {
  Department,
  TaskReview,
  TaskReviewOverview,
  TaskReviewOverviewRow,
  UserLookup,
} from "@/lib/types"


const ALL = "__all__"

function localDateValue(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, "0")
  const day = String(value.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}

function initialDates() {
  const today = new Date()
  const start = new Date(today.getFullYear(), today.getMonth(), 1)
  return { dateFrom: localDateValue(start), dateTo: localDateValue(today) }
}

const EMPTY_OVERVIEW: TaskReviewOverview = {
  completed_count: 0,
  reviewed_count: 0,
  unreviewed_count: 0,
  diamonds_total: 0,
  users: [],
  rows: [],
}


export default function ReviewsPage() {
  const { apiFetch, user } = useAuth()
  const confirm = useConfirm()
  const defaults = React.useMemo(initialDates, [])
  const [dateFrom, setDateFrom] = React.useState(defaults.dateFrom)
  const [dateTo, setDateTo] = React.useState(defaults.dateTo)
  const [departmentId, setDepartmentId] = React.useState(ALL)
  const [revieweeId, setRevieweeId] = React.useState(ALL)
  const [reviewStatus, setReviewStatus] = React.useState<"all" | "reviewed" | "unreviewed">("all")
  const [departments, setDepartments] = React.useState<Department[]>([])
  const [users, setUsers] = React.useState<UserLookup[]>([])
  const [overview, setOverview] = React.useState<TaskReviewOverview>(EMPTY_OVERVIEW)
  const [loading, setLoading] = React.useState(true)
  const [selectedRow, setSelectedRow] = React.useState<TaskReviewOverviewRow | null>(null)
  const canManage = user?.role === "ADMIN" || user?.role === "MANAGER"
  const sampleCount = React.useMemo(
    () => overview.rows.filter((row) => row.review?.is_sample).length,
    [overview.rows]
  )

  React.useEffect(() => {
    let cancelled = false
    const loadFilters = async () => {
      const [departmentRes, userRes] = await Promise.all([
        apiFetch("/departments"),
        apiFetch("/users/lookup?include_inactive=true"),
      ])
      if (cancelled) return
      if (departmentRes.ok) setDepartments((await departmentRes.json()) as Department[])
      if (userRes.ok) setUsers((await userRes.json()) as UserLookup[])
    }
    void loadFilters()
    return () => {
      cancelled = true
    }
  }, [apiFetch])

  const loadOverview = React.useCallback(async () => {
    if (!dateFrom || !dateTo) return
    setLoading(true)
    try {
      const query = new URLSearchParams({
        date_from: dateFrom,
        date_to: dateTo,
        review_status: reviewStatus,
      })
      if (departmentId !== ALL) query.set("department_id", departmentId)
      if (revieweeId !== ALL) query.set("reviewee_user_id", revieweeId)
      const res = await apiFetch(`/task-reviews/overview?${query.toString()}`)
      if (!res.ok) {
        let detail = "Failed to load reviews."
        try {
          const payload = (await res.json()) as { detail?: string }
          if (payload.detail) detail = payload.detail
        } catch {
          // Keep fallback.
        }
        throw new Error(detail)
      }
      setOverview((await res.json()) as TaskReviewOverview)
    } catch (error) {
      setOverview(EMPTY_OVERVIEW)
      toast.error(error instanceof Error ? error.message : "Failed to load reviews.")
    } finally {
      setLoading(false)
    }
  }, [apiFetch, dateFrom, dateTo, departmentId, reviewStatus, revieweeId])

  React.useEffect(() => {
    void loadOverview()
  }, [loadOverview])

  const visibleUsers = React.useMemo(
    () =>
      users.filter(
        (entry) => departmentId === ALL || !entry.department_id || entry.department_id === departmentId
      ),
    [departmentId, users]
  )

  const updateSavedReview = React.useCallback((saved: TaskReview) => {
    setOverview((current) => {
      const rows = current.rows.map((row) =>
        row.task_id === saved.task_id && row.reviewee_user_id === saved.reviewee_user_id
          ? { ...row, review: saved }
          : row
      )
      // Reload immediately after optimistic replacement so summaries and active
      // "unreviewed" filters are recalculated by the API.
      return { ...current, rows }
    })
    void loadOverview()
  }, [loadOverview])

  const deleteReview = React.useCallback(async (review: TaskReview) => {
    const approved = await confirm({
      title: "Delete review",
      description: `Delete the review for ${review.reviewee_name}?`,
      confirmLabel: "Delete",
      variant: "destructive",
    })
    if (!approved) return
    const res = await apiFetch(`/task-reviews/${review.id}`, { method: "DELETE" })
    if (!res.ok) {
      toast.error("Failed to delete review.")
      return
    }
    toast.success("Review deleted")
    await loadOverview()
  }, [apiFetch, confirm, loadOverview])

  const deleteSampleReviews = React.useCallback(async () => {
    const approved = await confirm({
      title: "Delete sample reviews",
      description: "This removes every review marked as Sample. Real reviews will not be touched.",
      confirmLabel: "Delete samples",
      variant: "destructive",
    })
    if (!approved) return
    const res = await apiFetch("/task-reviews/samples", { method: "DELETE" })
    if (!res.ok) {
      toast.error("Failed to delete sample reviews.")
      return
    }
    const payload = (await res.json()) as { deleted_count: number }
    toast.success(`${payload.deleted_count} sample review${payload.deleted_count === 1 ? "" : "s"} deleted`)
    await loadOverview()
  }, [apiFetch, confirm, loadOverview])

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <Gem className="h-6 w-6 fill-cyan-400 text-cyan-600" />
            Reviews
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Diamonds for completed work and improvement proposals recorded in Realization.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {canManage && sampleCount > 0 ? (
            <Button variant="destructive" onClick={() => void deleteSampleReviews()}>
              <Trash2 className="mr-2 h-4 w-4" />
              Delete sample reviews
            </Button>
          ) : null}
          <Button variant="outline" onClick={() => void loadOverview()} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="grid gap-4 pt-6 sm:grid-cols-2 lg:grid-cols-5">
          <div className="space-y-2">
            <Label htmlFor="review-date-from">From</Label>
            <Input id="review-date-from" type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="review-date-to">To</Label>
            <Input id="review-date-to" type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
          </div>
          <div className="space-y-2">
              <Label>Department</Label>
              <Select
                value={departmentId}
                onValueChange={(value) => {
                  setDepartmentId(value)
                  setRevieweeId(ALL)
                }}
              >
                <SelectTrigger><SelectValue placeholder="All departments" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All departments</SelectItem>
                  {departments.map((department) => (
                    <SelectItem key={department.id} value={department.id}>{department.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
          </div>
          <div className="space-y-2">
              <Label>User</Label>
              <Select value={revieweeId} onValueChange={setRevieweeId}>
                <SelectTrigger><SelectValue placeholder="All users" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All users</SelectItem>
                  {visibleUsers.map((entry) => (
                    <SelectItem key={entry.id} value={entry.id}>
                      {entry.full_name || entry.username || "User"}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
          </div>
          <div className="space-y-2">
            <Label>Review status</Label>
            <Select value={reviewStatus} onValueChange={(value) => setReviewStatus(value as typeof reviewStatus)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All tasks and proposals</SelectItem>
                <SelectItem value="unreviewed">Without review</SelectItem>
                <SelectItem value="reviewed">Reviewed</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ["Completed", overview.completed_count],
          ["Reviewed", overview.reviewed_count],
          ["Without review", overview.unreviewed_count],
          ["Diamonds awarded", overview.diamonds_total],
        ].map(([label, value]) => (
          <Card key={label}>
            <CardHeader className="pb-2"><CardTitle className="text-sm text-muted-foreground">{label}</CardTitle></CardHeader>
            <CardContent className="text-2xl font-bold">{value}</CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Completed tasks and improvement proposals</CardTitle>
          {overview.proposal_count ? <p className="text-xs text-cyan-800">{overview.proposal_count} propozime për përmirësim · 1 diamant për propozim</p> : null}
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="py-10 text-center text-sm text-muted-foreground">Loading completed tasks...</div>
          ) : overview.rows.length === 0 ? (
            <div className="py-10 text-center text-sm text-muted-foreground">
              No tasks or improvement proposals match these filters.
            </div>
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <Table className="w-full min-w-[900px] table-fixed">
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[5%]">Nr.</TableHead>
                    <TableHead className="w-[39%]">Task / Proposal</TableHead>
                    <TableHead className="w-[14%]">User</TableHead>
                    <TableHead className="w-[12%]">Date</TableHead>
                    <TableHead className="w-[18%]">Review</TableHead>
                    <TableHead className="w-[12%] text-right">Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {overview.rows.map((row, index) => (
                    <TableRow key={`${row.source || "TASK"}:${row.task_id || row.review?.id}:${row.reviewee_user_id}`}>
                      <TableCell className="align-top tabular-nums text-muted-foreground">{index + 1}</TableCell>
                      <TableCell className="max-w-0 align-top">
                        <Link
                          href={row.source === "REALIZATION_PROPOSAL" || !row.task_id ? "/realization" : `/tasks/${row.task_id}?returnTo=${encodeURIComponent("/reviews")}`}
                          className="line-clamp-2 whitespace-normal font-medium [overflow-wrap:anywhere] hover:underline"
                          title={getPlainMarkedText(row.task_title)}
                        >
                          {getPlainMarkedText(row.task_title)}
                        </Link>
                        {row.source === "REALIZATION_PROPOSAL" ? <Badge variant="outline" className="mt-1 border-cyan-300 bg-cyan-50 text-cyan-900">Propozim · Realizimi</Badge> : null}
                        {row.project_title ? (
                          <div className="truncate text-xs text-muted-foreground" title={row.project_title}>
                            {row.project_title}
                          </div>
                        ) : null}
                      </TableCell>
                      <TableCell className="truncate align-top" title={row.reviewee_name}>{row.reviewee_name}</TableCell>
                      <TableCell className="whitespace-nowrap">{formatDateDMY(row.completed_at)}</TableCell>
                      <TableCell>
                        {row.review ? (
                          <div>
                            <div className="flex items-center gap-2">
                              <DiamondAward compact />
                              <span className="text-xs font-semibold">Diamond</span>
                              {row.review.is_sample ? <Badge variant="outline">Sample</Badge> : null}
                            </div>
                            {row.review.comment ? (
                              <div className="mt-1 max-w-72 truncate text-xs text-muted-foreground" title={row.review.comment}>
                                {row.review.comment}
                              </div>
                            ) : null}
                          </div>
                        ) : (
                          <span className="text-sm text-muted-foreground">Not reviewed</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                          {row.source === "REALIZATION_PROPOSAL" ? (
                            <Link href="/realization" className="text-xs font-medium text-cyan-800 hover:underline">Shih te Realizimi</Link>
                          ) : row.reviewee_user_id === user?.id ? (
                            <span className="text-xs text-muted-foreground">Self-review disabled</span>
                          ) : (
                            <div className="flex justify-end gap-2">
                              {!row.review || canManage ? (
                                <Button variant={row.review ? "outline" : "default"} size="sm" onClick={() => setSelectedRow(row)}>
                                  {row.review ? "Edit" : "Review"}
                                </Button>
                              ) : null}
                              {row.review && canManage ? (
                                <Button
                                  variant="destructive"
                                  size="sm"
                                  aria-label="Delete review"
                                  onClick={() => void deleteReview(row.review!)}
                                >
                                  <Trash2 className="h-4 w-4" />
                                </Button>
                              ) : null}
                            </div>
                          )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <TaskReviewDialog
        row={selectedRow}
        open={Boolean(selectedRow)}
        onOpenChange={(open) => {
          if (!open) setSelectedRow(null)
        }}
        onSaved={updateSavedReview}
      />
    </div>
  )
}
