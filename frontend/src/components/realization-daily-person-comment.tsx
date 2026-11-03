"use client"

import * as React from "react"
import { Loader2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/lib/auth"

type DailyComment = {
  period_id: string
  user_id: string
  day: string
  comment: string | null
  can_edit: boolean
}

type Props = { periodId: string; userId: string; userName: string; day: string; compact?: boolean }

export function RealizationDailyPersonComment(props: Props) {
  if (!props.periodId) return <span className="text-xs text-slate-400">Duke ngarkuar ditën…</span>
  return <DailyCommentEditor key={`${props.periodId}:${props.userId}`} {...props} />
}

function DailyCommentEditor({ periodId, userId, userName, day, compact = false }: Props) {
  const { apiFetch } = useAuth()
  const [data, setData] = React.useState<DailyComment | null>(null)
  const [comment, setComment] = React.useState("")
  const [loading, setLoading] = React.useState(true)
  const [failed, setFailed] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const [retry, setRetry] = React.useState(0)
  const endpoint = `/realization/periods/${periodId}/users/${userId}/daily-comment`
  const dateLabel = day.split("-").reverse().join(".")

  React.useEffect(() => {
    const controller = new AbortController()
    void (async () => {
      try {
        const response = await apiFetch(endpoint, { signal: controller.signal })
        if (!response.ok) throw new Error("Komenti nuk u ngarkua")
        const payload = await response.json() as DailyComment
        if (controller.signal.aborted) return
        if (payload.period_id !== periodId || payload.user_id !== userId || payload.day !== day) {
          throw new Error("Komenti nuk përputhet me ditën e zgjedhur")
        }
        setData(payload)
        setComment(payload.comment || "")
        setFailed(false)
      } catch {
        if (!controller.signal.aborted) setFailed(true)
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    })()
    return () => controller.abort()
  }, [apiFetch, endpoint, periodId, userId, day, retry])

  const save = async () => {
    if (!data?.can_edit || saving) return
    setSaving(true)
    try {
      const response = await apiFetch(endpoint, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ comment: comment.trim() || null }),
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => ({})) as { detail?: unknown }
        throw new Error(typeof payload.detail === "string" ? payload.detail : "Komenti nuk u ruajt")
      }
      const payload = await response.json() as DailyComment
      setData(payload)
      setComment(payload.comment || "")
      toast.success(`Komenti ditor për ${userName} u ruajt`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Komenti nuk u ruajt")
    } finally {
      setSaving(false)
    }
  }

  if (failed) return <div className="space-y-1 text-xs text-rose-700">
    <p>Komenti ditor nuk u ngarkua.</p>
    <Button type="button" size="sm" variant="outline" onClick={() => {
      setLoading(true)
      setFailed(false)
      setRetry(value => value + 1)
    }}>Provo përsëri</Button>
  </div>

  return <div className={`flex flex-col items-stretch gap-1 ${compact ? "min-w-0" : "min-w-64"}`} onClick={event => event.stopPropagation()}>
    <span className="text-[11px] text-slate-500">{dateLabel}</span>
    <Textarea
      aria-label={`Komenti ditor për ${userName}, ${dateLabel}`}
      className={compact ? "min-h-12 w-full min-w-0 resize-y bg-white px-1.5 py-1 text-[11px] leading-4" : "min-h-20 w-full resize-y bg-white px-2 py-1.5 text-[13px] leading-5"}
      rows={compact ? 2 : 3} maxLength={4000} value={comment}
      readOnly={!data?.can_edit} disabled={loading || saving}
      onChange={event => setComment(event.target.value)}
      placeholder={loading ? "Duke ngarkuar komentin…" : data?.can_edit ? "Shkruaj komentin për këtë ditë…" : "Pa koment ditor"}
    />
    {data?.can_edit ? <Button
      type="button" size="sm" className={compact ? "h-auto min-h-6 max-w-full self-end whitespace-normal px-1.5 py-1 text-[10px]" : "h-8 self-end px-3"}
      disabled={saving || comment.trim() === (data.comment || "")}
      onClick={() => void save()}
    >{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Ruaj komentin"}</Button> : null}
  </div>
}
