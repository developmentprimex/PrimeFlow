"use client"

import * as React from "react"
import { Gem } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/lib/auth"
import { getPlainMarkedText } from "@/lib/note-markup"
import type { TaskReview, TaskReviewOverviewRow } from "@/lib/types"


export function DiamondAward({
  compact = false,
}: {
  compact?: boolean
}) {
  return (
    <span aria-label="Diamond awarded">
      <Gem
        className={`${compact ? "h-4 w-4" : "h-8 w-8"} fill-cyan-400 text-cyan-600`}
      />
    </span>
  )
}


export function TaskReviewDialog({
  row,
  open,
  onOpenChange,
  onSaved,
}: {
  row: TaskReviewOverviewRow | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved: (review: TaskReview) => void | Promise<void>
}) {
  const { apiFetch } = useAuth()
  const [comment, setComment] = React.useState("")
  const [saving, setSaving] = React.useState(false)

  React.useEffect(() => {
    if (!open || !row) return
    setComment(row.review?.comment ?? "")
  }, [open, row])

  const save = React.useCallback(async () => {
    if (!row || row.source === "REALIZATION_PROPOSAL" || !row.task_id) return
    setSaving(true)
    try {
      const existing = row.review
      const res = await apiFetch(existing ? `/task-reviews/${existing.id}` : "/task-reviews", {
        method: existing ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          existing
            ? { diamond_score: 1, comment: comment.trim() || null }
            : {
                task_id: row.task_id,
                reviewee_user_id: row.reviewee_user_id,
                diamond_score: 1,
                comment: comment.trim() || null,
              }
        ),
      })
      if (!res.ok) {
        let detail = "Failed to save review."
        try {
          const payload = (await res.json()) as { detail?: string }
          if (payload.detail) detail = payload.detail
        } catch {
          // Keep the fallback message for non-JSON responses.
        }
        throw new Error(detail)
      }
      const review = (await res.json()) as TaskReview
      await onSaved(review)
      toast.success(existing ? "Review updated" : "Review saved")
      onOpenChange(false)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to save review.")
    } finally {
      setSaving(false)
    }
  }, [apiFetch, comment, onOpenChange, onSaved, row])

  return (
    <Dialog open={open} onOpenChange={(next) => (!saving ? onOpenChange(next) : undefined)}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{row?.review ? "Edit review" : "Review task"}</DialogTitle>
          <DialogDescription>
            {row ? `${row.reviewee_name} - ${getPlainMarkedText(row.task_title)}` : "Review a completed task."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-2">
          <div className="space-y-2">
            <Label>Diamond</Label>
            <div className="flex items-center gap-3">
              <DiamondAward />
              <span className="text-sm font-semibold">This review awards one diamond</span>
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="task-review-comment">Comment</Label>
            <Textarea
              id="task-review-comment"
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              rows={4}
              maxLength={4000}
              placeholder="Optional feedback about the result..."
              disabled={saving}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={saving || !row}>
            {saving ? "Saving..." : "Save review"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
