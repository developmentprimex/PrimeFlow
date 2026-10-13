"use client"

import * as React from "react"
import { ChevronRight, Loader2 } from "lucide-react"
import { RealizationWeeklyDays } from "@/components/realization-weekly-days"
import { RealizationWeeklyPostponements, weeklyPostponements } from "@/components/realization-weekly-postponements"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/lib/auth"
import { manualChecklistBooleanKeys, weeklyChecklistLabels } from "@/lib/realization-checklist"
import type { RealizationLevel, RealizationManagerReviewResponse, RealizationManagerReviewRating, RealizationPersonResult, RealizationQuestion } from "@/lib/types"
import { cn } from "@/lib/utils"

const RATINGS: Record<RealizationManagerReviewRating, string> = {
  GOOD: "Mirë", VERY_GOOD: "Shumë mirë", ACTION_REQUIRED: "Kërkon veprim", BAD: "Keq",
}
type QuestionDraft = { values: string[]; comment: string; touched: boolean }

const FACT_LABELS: Record<string, string> = {
  yes: "Përgjigjja", frequent: "Të shpeshta", threshold: "Pragu i vonesave",
  answer: "Përgjigjja", planned: "Planifikuar", completed: "Kryer", remaining: "Mbetur",
  count: "Numri", total: "Gjithsej", in_progress: "Në progres", no_progress: "Pa progres", todo: "To do", postponed: "Shtyrë",
  approved: "Aprovuar", unapproved: "Pa aprovim", closed: "Mbyllur",
  all_closed: "Të gjitha të mbyllura", attendance_tardiness: "Vonesa",
  missed_meeting_evidence: "Evidenca për takime të humbura",
}

function automaticValue(value: unknown): string {
  if (value == null) return "Pa të dhëna"
  if (typeof value === "boolean") return value ? "Po" : "Jo"
  if (typeof value !== "object") return String(value)
  if (Array.isArray(value)) return value.length ? value.map(automaticValue).join(", ") : "Asnjë"
  return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => `${FACT_LABELS[key] || key.replaceAll("_", " ")}: ${automaticValue(item)}`)
    .join(" · ")
}

function savedQuestionValues(question: RealizationQuestion): string[] {
  const value = question.final_value
  if (manualChecklistBooleanKeys.has(question.key)) {
    if (value === true) return ["YES"]
    if (value === false) return ["NO"]
    return ["NO"]
  }
  if (question.source_status !== "MANUAL_ANSWERED" || typeof value !== "string" || !value.trim()) return []
  return value.split(" • ").map((item) => item.trim()).filter(Boolean)
}

function automaticAnswer(question: RealizationQuestion, timeline?: RealizationPersonResult["facts_json"]["daily_timeline"]): { answer: string; detail: string } {
  const value = question.final_value ?? question.auto_value
  if (question.key === "unexpected_absences" && timeline) {
    const leaveDates = [...new Set(timeline.filter(day => day.on_leave || day.attendance?.some(entry => entry.type === "PUSHIM_VJETOR")).map(day => day.date))].sort()
    const leaveDetail = leaveDates.length
      ? `Pushim vjetor: ${leaveDates.length} ditë (${leaveDates.map(date => date.split("-").reverse().join(".")).join(", ")}).`
      : "Pushim vjetor: 0 ditë."
    const absenceDetail = typeof value === "number"
      ? `Mungesa të papritura: ${value}.`
      : "Mungesat e papritura: kërkojnë konfirmim."
    return {
      answer: leaveDates.length || (typeof value === "number" && value > 0) ? "Po" : typeof value === "number" ? "Jo" : "Për konfirmim",
      detail: `${leaveDetail}\n${absenceDetail}`,
    }
  }
  if (value == null) return { answer: "Pa të dhëna", detail: "" }
  const facts = typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}
  const number = (key: string) => typeof facts[key] === "number" ? facts[key] : "—"
  const yesNo = (answer: unknown) => answer === true ? "Po" : answer === false ? "Jo" : "Pa të dhëna"
  switch (question.key) {
    case "plan_completed":
      return { answer: yesNo(facts.answer), detail: `${number("completed")} nga ${number("planned")} detyra të kryera. Mbeten ${number("remaining")}.` }
    case "no_progress_tasks":
      return { answer: yesNo(facts.answer), detail: `${number("count")} detyra pa progres të regjistruar.` }
    case "in_progress_tasks":
      return { answer: yesNo(facts.answer), detail: `${number("count")} detyra janë ende në progres.` }
    case "new_tasks_added":
      return { answer: yesNo(facts.yes), detail: `${number("total")} detyra të reja: ${number("completed")} të kryera, ${number("in_progress")} në progres, ${number("todo")} pa filluar dhe ${number("postponed")} të shtyra.` }
    case "closed_tasks":
      return { answer: yesNo(facts.all_closed), detail: `${number("closed")} nga ${number("planned")} detyra të mbyllura. Mbeten ${number("remaining")}.` }
    case "frequent_delays":
      return { answer: yesNo(facts.answer ?? facts.frequent), detail: `${number("attendance_tardiness")} vonesa të regjistruara. Konsiderohen të shpeshta nga ${number("threshold")} vonesa.` }
    case "unexpected_absences":
      if (typeof value === "number") return { answer: value > 0 ? "Po" : "Jo", detail: `${value} mungesa të papritura të regjistruara.` }
  }
  return { answer: typeof value === "boolean" ? yesNo(value) : "Përmbledhje", detail: typeof value === "boolean" ? "" : automaticValue(value) }
}

function ManualQuestion({ number, label, draft, disabled, onChange, onSaveComment }: {
  number: number; label: string; draft: QuestionDraft; disabled: boolean; onChange: (next: QuestionDraft) => void; onSaveComment: () => void
}) {
  const commentRequired = draft.values.includes("YES")
  const commentMissing = commentRequired && !draft.comment.trim()
  return <tr className="border-b border-slate-200 align-top even:bg-slate-50/50 hover:bg-blue-50/40 focus-within:bg-blue-50/40">
    <td className="px-2 py-3 text-center text-xs tabular-nums text-slate-500">{number}</td>
    <th scope="row" className="border-l border-slate-200 px-3 py-3 text-left text-sm font-medium leading-5 text-slate-800">{label}</th>
    <td className="border-l border-slate-200 px-2 py-2">
      <select aria-label={label} disabled={disabled} value={draft.values[0] || ""} onChange={event => onChange({ ...draft, values: event.target.value ? [event.target.value] : [], touched: true })} className="h-9 w-full rounded-md border border-slate-300 bg-white px-2 text-xs focus-visible:outline-2 focus-visible:outline-blue-600 disabled:opacity-60">
        <option value="">E paplotësuar</option><option value="YES">Po</option><option value="NO">Jo</option>
      </select>
    </td>
    <td className="border-l border-slate-200 px-3 py-2">
      <div className="flex flex-col items-stretch gap-1.5">
        <Textarea aria-label={`Komenti për ${label}`} required={commentRequired} aria-required={commentRequired} className="min-h-9 resize-y bg-white px-2 py-2 text-xs" rows={1} maxLength={1000} value={draft.comment} disabled={disabled} onChange={(event) => onChange({ ...draft, comment: event.target.value, touched: true })} placeholder={commentRequired ? "Shto koment (i detyrueshëm)…" : "Shto koment (opsional)…"} />
        {commentMissing ? <p className="text-[11px] text-amber-700">Komenti është i detyrueshëm kur përgjigjja është Po.</p> : null}
        {draft.touched && !disabled ? <Button type="button" size="sm" variant="outline" className="h-7 self-end px-3 text-xs" disabled={commentMissing} onClick={onSaveComment}>Ruaj përgjigjen</Button> : null}
      </div>
    </td>
  </tr>
}

export function RealizationReviewCells({ periodId, userId, userName, result: initialResult, scope = "weekly", locked = false, compactTable = false, onSaved, onPrepareResult, refreshKey, commentCell }: {
  periodId: string; userId: string; userName: string; result?: RealizationPersonResult; scope?: "daily" | "weekly"; locked?: boolean; compactTable?: boolean; onSaved?: () => void; onPrepareResult?: () => Promise<void>; refreshKey?: unknown
  commentCell?: React.ReactNode
}) {
  const { apiFetch } = useAuth()
  const [updatedResult, setUpdatedResult] = React.useState<RealizationPersonResult | null>(null)
  const result = updatedResult || initialResult
  const fullWeekLeave = scope === "weekly" && result?.facts_json.availability_status === "PV"
  const [data, setData] = React.useState<RealizationManagerReviewResponse | null>(null)
  const [rating, setRating] = React.useState<RealizationManagerReviewRating | "">("")
  const [level, setLevel] = React.useState<RealizationLevel | "">("")
  const [comment, setComment] = React.useState("")
  const [drafts, setDrafts] = React.useState<Record<string, QuestionDraft>>({})
  const [savedAnswersFor, setSavedAnswersFor] = React.useState<RealizationPersonResult | null>(null)
  const proposalRef = React.useRef<HTMLElement | null>(null)
  const [open, setOpen] = React.useState(false)
  const [saving, setSaving] = React.useState(false)
  const [preparing, setPreparing] = React.useState(false)
  const [failed, setFailed] = React.useState(false)
  // The API answers for the week that contains periodId, so its period_id is
  // the weekly one and cannot be compared against periodId directly.
  const [loadedFor, setLoadedFor] = React.useState("")
  const draftsRef = React.useRef(drafts)
  const generatedQuestionLines = React.useRef<string[]>([])
  draftsRef.current = drafts
  const endpoint = `/realization/periods/${periodId}/users/${userId}/manager-review`
  const manualQuestions = React.useMemo(() => fullWeekLeave ? [] : (result?.facts_json.questions || []).filter((question) => question.source_status.startsWith("MANUAL")), [result, fullWeekLeave])
  const automaticQuestions = React.useMemo(() => (result?.facts_json.questions || []).filter((question) => question.source_status.startsWith("AUTO") && question.key !== "extra_engagement"), [result])
  const weeklySnapshotDays = scope === "weekly" ? Number(result?.facts_json.weekly_snapshot_days || 0) : 0
  const questionLabel = React.useCallback((question: RealizationQuestion) => {
    const label = weeklyChecklistLabels[question.key] || question.label
    return scope === "daily" ? label.replace("këtë javë", "këtë ditë") : label
  }, [scope])
  const initializeDrafts = React.useCallback((questions = manualQuestions) => {
    const nextDrafts = Object.fromEntries(questions.map((question) => [question.key, {
      values: savedQuestionValues(question), comment: question.source_status === "MANUAL_ANSWERED" ? question.manager_comment || "" : "", touched: manualChecklistBooleanKeys.has(question.key) && question.final_value !== true && question.final_value !== false,
    }]))
    generatedQuestionLines.current = questions.flatMap((question) => {
      const text = nextDrafts[question.key]?.comment.trim()
      return text ? [`- ${questionLabel(question)}: ${text}`] : []
    })
    setDrafts(nextDrafts)
  }, [manualQuestions, questionLabel])
  const load = React.useCallback(async () => {
    if (!periodId) return
    try {
      const response = await apiFetch(endpoint)
      if (!response.ok) throw new Error()
      const payload = await response.json() as RealizationManagerReviewResponse
      setData(payload)
      setLoadedFor(periodId)
      setRating(payload.realization?.rating ?? "")
      setLevel(payload.realization?.level ?? "")
      setComment(payload.realization?.comment ?? "")
      setFailed(false)
    } catch { setFailed(true) }
  }, [apiFetch, endpoint, periodId])
  React.useEffect(() => { queueMicrotask(() => void load()) }, [load, refreshKey])
  React.useEffect(() => {
    if (open && Object.keys(draftsRef.current).length > 0) return
    queueMicrotask(initializeDrafts)
  }, [initializeDrafts, open])
  const canEdit = Boolean(data?.can_edit && loadedFor === periodId && data.user_id === userId && !locked && periodId)
  const savedRating = data?.realization?.rating ?? ""
  const savedComment = data?.realization?.comment ?? ""
  const savedLevel = data?.realization?.level ?? ""
  const suggestion = result?.facts_json.weekly_evaluation
  const reviewDirty = rating !== savedRating || comment !== savedComment || level !== savedLevel
  const questionsDirty = !fullWeekLeave && Object.values(drafts).some((draft) => draft.touched)
  const answersComplete = fullWeekLeave || Boolean(result?.facts_json.manual_question_completeness?.complete)
  const proposalReady = answersComplete && !questionsDirty && savedAnswersFor !== result
  React.useEffect(() => {
    if (open && proposalReady) proposalRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })
  }, [open, proposalReady])
  const hasUnsavedChanges = reviewDirty || questionsDirty
  const ratingLabel = failed ? "Gabim ngarkimi" : !data ? "Duke ngarkuar…" : scope === "weekly" && !answersComplete ? "Plotëso përgjigjet" : scope === "weekly" && (savedLevel || suggestion?.level) ? `${savedLevel || suggestion?.level} · ${savedLevel ? "Konfirmuar" : "Propozim"}` : savedRating ? RATINGS[savedRating] : "Pa vlerësim"

  const syncQuestionComment = (nextDrafts: Record<string, QuestionDraft>) => {
    const previousLines = generatedQuestionLines.current
    const nextLines = manualQuestions.flatMap((question) => {
      const text = nextDrafts[question.key]?.comment.trim()
      return text ? [`- ${questionLabel(question)}: ${text}`] : []
    })
    setComment((current) => {
      const remaining = current.split("\n").filter((line) => !previousLines.includes(line.trim()))
      const base = remaining.join("\n").trim()
      return [...(base ? [base] : []), ...nextLines].join("\n")
    })
    generatedQuestionLines.current = nextLines
  }
  const updateQuestionDraft = (key: string, next: QuestionDraft) => {
    const nextDrafts = { ...drafts, [key]: next }
    setDrafts(nextDrafts)
    syncQuestionComment(nextDrafts)
  }

  const openReview = async () => {
    if (preparing || saving) return
    initializeDrafts()
    setOpen(true)
    if (scope === "weekly" && result) {
      setPreparing(true)
      try {
        const weekStart = result.facts_json.daily_timeline?.[0]?.date
        if (!weekStart || !result.department_id) throw new Error("Mungon java ose departamenti.")
        const response = await apiFetch(`/realization/weekly?department_id=${result.department_id}&week_start=${weekStart}`, { cache: "no-store" })
        if (!response.ok) throw new Error("Komentet dhe të dhënat e javës nuk u rifreskuan. Provo përsëri.")
        const report = await response.json() as { people: RealizationPersonResult[] }
        const next = report.people.find(person => person.user_id === userId)
        if (!next) throw new Error("Raporti javor i personit nuk u gjet.")
        setUpdatedResult(next)
        initializeDrafts(next.facts_json.availability_status === "PV" ? [] : (next.facts_json.questions || []).filter(question => question.source_status.startsWith("MANUAL")))
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Raporti javor nuk u rifreskua.")
      } finally { setPreparing(false) }
      return
    }
    if (result || !onPrepareResult) return
    setPreparing(true)
    try {
      await onPrepareResult()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Checklist-a nuk u ngarkua")
    } finally {
      setPreparing(false)
    }
  }

  const save = async ({ closeDialog = true, saveQuestions = true, confirmLevel }: { closeDialog?: boolean; saveQuestions?: boolean; confirmLevel?: RealizationLevel } = {}) => {
    if (!hasUnsavedChanges && !confirmLevel) return
    if (saveQuestions) {
      const missingComment = manualQuestions.find(question => {
        const draft = drafts[question.key]
        return draft?.touched && draft.values.includes("YES") && !draft.comment.trim()
      })
      if (missingComment) {
        toast.error(`Komenti është i detyrueshëm kur përgjigjja është Po: ${questionLabel(missingComment)}`)
        return
      }
    }
    setSaving(true)
    try {
      if (saveQuestions) {
        for (const question of manualQuestions) {
          const draft = drafts[question.key] || { values: [], comment: "", touched: false }
          if (!draft.touched) continue
          const value = draft.values.includes("YES")
          const response = await apiFetch(`/realization/periods/${periodId}/users/${userId}/questions/${question.key}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value, clear: draft.values.length === 0, comment: draft.comment.trim() || null, evidence_ids: [] }) })
          if (!response.ok) throw new Error(`Nuk u ruajt përgjigjja: ${question.label}`)
        }
      }
      if (scope === "weekly" && saveQuestions && questionsDirty) {
        setSavedAnswersFor(result || null)
        const weekStart = result?.facts_json.daily_timeline?.[0]?.date
        if (!weekStart || !result?.department_id) throw new Error("Mungon java ose departamenti për propozimin.")
        const refreshed = await apiFetch(`/realization/weekly?department_id=${result.department_id}&week_start=${weekStart}`)
        if (!refreshed.ok) throw new Error("Përgjigjet u ruajtën, por propozimi nuk u ngarkua. Provo përsëri.")
        const report = await refreshed.json() as { people: RealizationPersonResult[] }
        const next = report.people.find(person => person.user_id === userId)
        if (!next) throw new Error("Propozimi për këtë person nuk u gjet.")
        setUpdatedResult(next)
        setDrafts(current => Object.fromEntries(Object.entries(current).map(([key, draft]) => [key, { ...draft, touched: false }])))
        toast.success("Përgjigjet u ruajtën dhe propozimi u përditësua.")
        return
      }
      const marker = rating ? (["GOOD", "VERY_GOOD"].includes(rating) ? "POSITIVE" : "NEGATIVE") : data?.realization?.marker || "POSITIVE"
      const response = await apiFetch(`${endpoint}/REALIZATION`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rating: rating || null, marker, comment: comment.trim() || null, ...(scope === "weekly" && proposalReady ? { level: confirmLevel || level || null } : {}) }) })
      if (!response.ok) {
        const payload = await response.json().catch(() => ({})) as { detail?: string }
        throw new Error(typeof payload.detail === "string" ? payload.detail : "Vlerësimi nuk u ruajt")
      }
      const payload = await response.json() as RealizationManagerReviewResponse
      setData(payload)
      setLevel(payload.realization?.level ?? "")
      setComment(payload.realization?.comment ?? comment.trim())
      setDrafts((current) => Object.fromEntries(Object.entries(current).map(([key, draft]) => [key, { ...draft, touched: false }])))
      if (closeDialog) {
        setOpen(false)
      }
      onSaved?.()
      toast.success(saveQuestions ? "Vlerësimi dhe përgjigjet u ruajtën" : "Komenti i përgjegjësit u ruajt")
    } catch (error) { toast.error(error instanceof Error ? error.message : "Vlerësimi nuk u ruajt") }
    finally { setSaving(false) }
  }

  const approvePostponement = async (taskId: string, eventId: string, status: "APPROVED" | "REJECTED", comment: string) => {
    if (!canEdit || saving || !result) return false
    const weekStart = result.facts_json.daily_timeline?.[0]?.date
    if (!weekStart || !result.department_id) {
      toast.error("Mungon java ose departamenti.")
      return false
    }
    setSaving(true)
    try {
      const response = await apiFetch(`/realization/daily/tasks/${taskId}/adjustment`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ audit_event_id: eventId, user_id: userId, status, reason: status === "APPROVED" ? "Aprovuar nga vlerësimi javor." : "Jo aprovuar nga vlerësimi javor.", comment: comment || null }),
      })
      if (!response.ok) {
        const error = await response.json().catch(() => ({}))
        throw new Error(error.detail || "Vendimi nuk u ruajt.")
      }
      // Reflect the saved decision even if the subsequent report refresh fails.
      const decision = await response.json()
      const savedResult: RealizationPersonResult = {
        ...result,
        facts_json: { ...result.facts_json, daily_timeline: result.facts_json.daily_timeline?.map(day => ({
          ...day, tasks: day.tasks?.map(task => task.task_id === taskId && task.timeline?.some(event => event.id === eventId)
            ? { ...task, adjustment_status: status, manager_decision: decision } : task),
        })) },
      }
      setUpdatedResult(savedResult)
      setSavedAnswersFor(savedResult)
      const refreshed = await apiFetch(`/realization/weekly?department_id=${result.department_id}&week_start=${weekStart}`)
      if (!refreshed.ok) throw new Error("Vendimi u ruajt, por raporti nuk u rifreskua. Rifresko faqen.")
      const report = await refreshed.json() as { people: RealizationPersonResult[] }
      const next = report.people.find(person => person.user_id === userId)
      if (!next) throw new Error("Vendimi u ruajt, por raporti i personit nuk u gjet.")
      setUpdatedResult(next)
      toast.success("Vendimi u ruajt dhe propozimi u përditësua.")
      return true
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Vendimi nuk u ruajt.")
      return false
    } finally { setSaving(false) }
  }

  return <>
    {compactTable ? <td className="p-1" onClick={(event) => event.stopPropagation()}>
      <Button type="button" variant="outline" size="sm" className="h-8 w-full min-w-32 justify-between gap-2 px-2 text-[13px]" onClick={() => void openReview()} disabled={failed}>{ratingLabel}<ChevronRight className="h-3.5 w-3.5 shrink-0" /></Button>
      <p className={cn("mt-0.5 line-clamp-1 text-[11px]", savedComment ? "text-slate-500" : "text-slate-400")}>{savedComment || "Pa koment"}</p>
    </td> : <><td className="p-1" onClick={(event) => event.stopPropagation()}><Button type="button" variant="outline" size="sm" className="h-8 w-full min-w-32 justify-between gap-2 px-2 text-[13px]" onClick={() => void openReview()} disabled={failed}>{ratingLabel}<ChevronRight className="h-3.5 w-3.5 shrink-0" /></Button></td>
    {commentCell ?? <td className="p-1" onClick={(event) => event.stopPropagation()}>
      <div className="flex min-w-64 flex-col items-stretch gap-1">
        <Textarea aria-label={`Komenti i përgjegjësit për ${userName}`} className="min-h-20 w-full resize-y bg-white px-2 py-1.5 text-[13px] leading-5" rows={3} maxLength={4000} value={comment} disabled={!canEdit || saving} onChange={(event) => setComment(event.target.value)} placeholder="Shkruaj komentin e përgjegjësit…" />
        {canEdit && reviewDirty ? <Button type="button" size="sm" className="h-8 self-end px-3" disabled={saving} title="Ruaj komentin" onClick={() => void save({ closeDialog: false, saveQuestions: false })}>{saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Ruaj komentin"}</Button> : null}
      </div>
    </td>}</>}
    <Dialog open={open} onOpenChange={(next) => { if (!saving && !preparing) { setOpen(next); if (!next && updatedResult) onSaved?.() } }}><DialogContent className="max-h-[92vh] overflow-y-auto sm:max-w-4xl">
      <DialogHeader><DialogTitle>{scope === "weekly" ? "Vlerësimi javor" : "Përgjigjet ditore"} — {userName}</DialogTitle><DialogDescription className="sr-only">{scope === "weekly" ? "Përmbledhje nga ditët e javës. Shkronja propozohet nga sistemi; përgjegjësi mund ta konfirmojë ose ta ndryshojë." : "Përgjigjet ruhen për ditën e zgjedhur dhe përmblidhen në javor. Vlerësimi i përgjegjësit dhe përmbledhja e tij mbeten javore."}</DialogDescription></DialogHeader>
      {preparing ? <p role="status" className="flex items-center gap-2 py-6 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />Duke ngarkuar komentet dhe të dhënat…</p> : <>
      {scope === "weekly" && proposalReady ? <section ref={proposalRef} className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm">
        <p className="font-semibold">Propozimi: {suggestion?.level || "Pa të dhëna"}{suggestion?.reasons[0] ? ` — ${suggestion.reasons[0]}` : ""}{suggestion?.provisional ? " · Paraprak" : ""}</p>
        {suggestion?.reasons.slice(1).map(reason => <p key={reason} className="mt-1 text-xs text-slate-600">{reason}</p>)}
        {suggestion?.provisional ? <p className="mt-1 text-xs text-amber-800">Ka ditë ose përgjigje që duhen plotësuar. Propozimi përditësohet me të dhënat e javës.</p> : null}
        <label className="mt-3 block text-xs font-semibold">Shkronja e përgjegjësit
          <select aria-label="Shkronja e përgjegjësit" className="ml-2 rounded border bg-white p-2" value={level} disabled={!canEdit || saving} onChange={event => setLevel(event.target.value as RealizationLevel | "")}><option value="">Përdor propozimin</option>{(["A+", "A", "B", "C", "M", "D", "E"] as const).map(value => <option key={value}>{value}</option>)}</select>
        </label>
        {canEdit && suggestion?.level ? <Button className="mt-3" size="sm" disabled={saving} onClick={() => void save({ confirmLevel: level || suggestion.level! })}>{level ? `Konfirmo shkronjën ${level}` : `Prano propozimin ${suggestion.level}`}</Button> : null}
        {savedLevel ? <p className="mt-1 text-xs text-slate-500">Ruajtur nga {data?.realization?.created_by_name}. Ndryshimet e të dhënave nuk e mbishkruajnë këtë zgjedhje.</p> : null}
        {data?.history.some(item => item.level) ? <details className="mt-2 text-xs"><summary className="cursor-pointer">Historiku i shkronjës</summary>{data.history.filter(item => item.dimension === "REALIZATION" && item.level).map(item => <p key={item.id}>{new Date(item.created_at).toLocaleString("sq-AL")} · {item.created_by_name}: {item.level}{item.active ? " · Aktuale" : ""}</p>)}</details> : null}
      </section> : null}
      {scope === "weekly" && result ? <section><p className="mb-2 text-sm font-semibold">Ditët dhe komentet e javës</p><RealizationWeeklyDays result={result} /></section> : null}
      {result ? (
        <section aria-label="Pyetjet dhe përgjigjet">
          <div className="mb-3">
            <h3 className="text-sm font-semibold text-slate-800">Pyetjet dhe përgjigjet</h3>
          </div>
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white" role="region" aria-label="Tabela e përgjigjeve automatike dhe manuale" tabIndex={0}>
            <table className="w-full min-w-[640px] table-fixed border-collapse text-left">
              <caption className="sr-only">Përgjigjet automatike dhe manuale për {userName}</caption>
              <colgroup><col className="w-10" /><col className="w-[38%]" /><col className="w-32" /><col /></colgroup>
              <thead className="bg-slate-100 text-[10px] font-bold uppercase tracking-wide text-slate-600">
                <tr>
                  <th scope="col" className="px-2 py-3 text-center">Nr.</th>
                  <th scope="col" className="border-l border-slate-200 px-3 py-3">Pyetja</th>
                  <th scope="col" className="border-l border-slate-200 px-2 py-3 text-center">Përgjigjja</th>
                  <th scope="col" className="border-l border-slate-200 px-3 py-3">Shpjegimi / Komenti</th>
                </tr>
              </thead>
              {automaticQuestions.length ? <tbody>
                <tr className="border-y border-slate-200 bg-blue-50"><th scope="rowgroup" colSpan={4} className="px-3 py-2 text-xs font-semibold text-blue-900">Automatike · {automaticQuestions.length} pyetje{scope === "weekly" ? ` · Totali i ${weeklySnapshotDays} ditëve` : ""}</th></tr>
                {automaticQuestions.map((question, index) => {
                  const answer = automaticAnswer(question, scope === "weekly" ? result.facts_json.daily_timeline : undefined)
                  return <tr key={question.key} className="border-b border-slate-200 align-top even:bg-slate-50/50 hover:bg-blue-50/40">
                    <td className="px-2 py-3 text-center text-xs tabular-nums text-slate-500">{index + 1}</td>
                    <th scope="row" className="border-l border-slate-200 px-3 py-3 text-sm font-medium leading-5 text-slate-800">{scope === "weekly" && question.key === "unexpected_absences" ? "Mungesa të papritura ose pushim vjetor?" : question.label}</th>
                    <td className="border-l border-slate-200 px-2 py-2 text-center"><span className="inline-flex min-h-9 items-center justify-center rounded-md bg-blue-50 px-3 text-xs font-semibold text-blue-900">{answer.answer}</span></td>
                    <td className="whitespace-pre-line border-l border-slate-200 px-3 py-3 text-xs leading-5 text-slate-600">{answer.detail || "—"}</td>
                  </tr>
                })}
              </tbody> : null}
              {!fullWeekLeave ? <tbody>
                <tr className="border-y border-slate-200 bg-blue-50"><th scope="rowgroup" colSpan={4} className="px-3 py-2 text-xs font-semibold text-blue-900">Manuale · {manualQuestions.length} pyetje · Plotësohen nga përgjegjësi</th></tr>
                {manualQuestions.map((question, index) => (
                  <React.Fragment key={question.key}>
                  <ManualQuestion
                    number={automaticQuestions.length + index + 1}
                    label={questionLabel(question)}
                    draft={drafts[question.key] || { values: [], comment: "", touched: false }}
                    disabled={!canEdit || saving}
                    onChange={(next) => updateQuestionDraft(question.key, next)}
                    onSaveComment={() => void save({ closeDialog: false })}
                  />
                  {scope === "weekly" && question.key === "approved_postponement" && weeklyPostponements(result).length > 0 ? (
                    <tr className="border-b border-slate-200 bg-blue-50/30">
                      <td colSpan={4} className="p-3">
                        <RealizationWeeklyPostponements result={result} canEdit={canEdit} busy={saving || preparing} onDecide={approvePostponement} />
                      </td>
                    </tr>
                  ) : null}
                  </React.Fragment>
                ))}
              </tbody> : null}
            </table>
          </div>
          {scope === "weekly" && canEdit && (!proposalReady || questionsDirty) ? <div className="mt-3 flex justify-end"><Button disabled={saving || preparing || !questionsDirty} onClick={() => void save({ closeDialog: false })}>{saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}Ruaj përgjigjet dhe shfaq propozimin</Button></div> : null}
        </section>
      ) : (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-blue-100 bg-blue-50 p-3 text-xs text-blue-800">
          <span>{preparing ? "Duke përgatitur checklistën për këtë person…" : "Checklist-a nuk është përgatitur ende për këtë person."}</span>
          {preparing ? <Loader2 className="h-4 w-4 shrink-0 animate-spin" /> : onPrepareResult ? <Button type="button" size="sm" variant="outline" onClick={() => void openReview()}>Provo përsëri</Button> : null}
        </div>
      )}
      {scope !== "weekly" || proposalReady ? <section className="rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <p className="mr-auto text-[11px] font-bold uppercase tracking-wide text-slate-600">Vlerësimi i përgjegjësit</p>
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              disabled={!canEdit || saving}
              onClick={() => setRating("")}
              className={cn(
                "h-8 rounded-md border px-3 text-xs font-semibold",
                rating === "" ? "border-slate-400 bg-slate-100 text-slate-700" : "border-slate-200 bg-white text-slate-500"
              )}
            >
              Pa vlerësim
            </button>
            {(Object.entries(RATINGS) as Array<[RealizationManagerReviewRating, string]>).map(([value, label]) => (
              <button
                key={value}
                type="button"
                disabled={!canEdit || saving}
                onClick={() => setRating(value)}
                className={cn(
                  "h-8 rounded-md border px-3 text-xs font-semibold",
                  rating === value ? "border-blue-600 bg-blue-600 text-white" : "border-slate-200 bg-white text-slate-700"
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <Textarea
          className="mt-2 min-h-32 resize-y bg-white text-xs"
          rows={5}
          value={comment}
          disabled={!canEdit || saving}
          onChange={(event) => setComment(event.target.value)}
          placeholder="Përmbledhja e vlerësimit të përgjegjësit…"
          maxLength={4000}
        />
        {canEdit && hasUnsavedChanges ? <div className="mt-2 flex items-center justify-end gap-3"><Button type="button" size="sm" onClick={() => void save()} disabled={saving || preparing || Boolean(onPrepareResult && !result)}>{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Ruaj vlerësimin</Button></div> : null}
      </section> : null}
      </>}
      <DialogFooter><Button variant="outline" onClick={() => { setOpen(false); if (updatedResult) onSaved?.() }} disabled={saving || preparing}>Mbyll</Button></DialogFooter>
    </DialogContent></Dialog>
  </>
}
