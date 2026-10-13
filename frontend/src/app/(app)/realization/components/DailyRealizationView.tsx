"use client"

import * as React from "react"
import { DailyStaffTable } from "./DailyStaffTable"
import { RealizationDailyPersonComment } from "@/components/realization-daily-person-comment"
import { RealizationProposalNotice } from "@/components/realization-proposal-notice"
import { compareRealizationDepartments } from "@/lib/department-name"
import { dailyExtraTaskState } from "@/lib/realization-extras"
import { AlertTriangle, ArrowLeft, CalendarDays, History, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { RealizationManagerReview } from "@/components/realization-manager-review"
import { useAuth } from "@/lib/auth"
import { combineDailyRealization } from "@/lib/daily-realization-summary"
import { dailyRlzReasonLabel } from "@/lib/daily-rlz-ui"
import { RealizationQuantitySummary, RealizationTaskQuantity } from "@/components/realization-quantity"
import { RealizationPlanSummary } from "@/components/realization-plan-summary"
import { MarkedTaskBlock } from "@/lib/note-markup"
import type { DailyRealizationLive, DailyRealizationMetrics, DailyRealizationPerson, DailyRealizationTask, Department, RealizationPersonResult, RealizationQuestion, UserLookup } from "@/lib/types"
import { cn } from "@/lib/utils"
import { compareWeeklyPlannerUsers } from "@/lib/weekly-planner-user-order"
import { manualChecklistBooleanKeys, weeklyChecklistLabels, checklistAnswerLabel } from "@/lib/realization-checklist"

const TZ = "Europe/Tirane"
const today = () => new Intl.DateTimeFormat("en-CA", { timeZone: TZ }).format(new Date())
const pct = (v: number | null) => v == null ? "—" : `${Math.min(100, v)}%`
const width = (v: number | null) => `${Math.max(0, Math.min(100, v ?? 0))}%`
const outcomeLabels: Record<string, string> = {
  DEADLINE_ALL: "Deadline gjithsej", DEADLINE_DONE: "Deadline të kryera", DEADLINE_NOT_DONE: "Deadline pa kryer",
  CRITICAL_ALL: "Deadline Important", CRITICAL_DONE: "Deadline Important të kryera", CRITICAL_NOT_DONE: "Deadline Important pa kryer",
  EXTRA_PROGRESS: "Ekstra në progres", EXTRA_NO_PROGRESS: "Ekstra pa progres", EXTRA_ALL: "Ekstra gjithsej", EXTRA_DONE: "Ekstra të kryera", REALIZED_AS_PLANNED: "Kryer sipas planit", IN_PROGRESS: "Në progres", NO_PROGRESS: "Pa progres",
  POSTPONED_APPROVED: "Shtyrë", POSTPONED_UNAPPROVED: "Shtyrë",
  WAITING_CONFIRMATION: "Në pritje konfirmimi", COMPLETED_LATE: "Kryer me vonesë",
  COMPLETED_EARLY: "Kryer para kohe", ADDITIONAL_COMPLETED: "Ekstra e kryer", ADDED_DURING_DAY: "Shtuar gjatë ditës",
  REOPENED: "Rihapur", REASSIGNED_OUT: "Transferuar jashtë", REASSIGNED_IN: "Transferuar brenda",
}
const outcomeStyles: Record<string, string> = {
  REALIZED_AS_PLANNED: "border-[#8BDD8B] bg-[#C4FDC4] text-slate-900", COMPLETED_LATE: "border-[#8BDD8B] bg-[#C4FDC4] text-slate-900", COMPLETED_EARLY: "border-[#8BDD8B] bg-[#C4FDC4] text-slate-900",
  IN_PROGRESS: "border-[#D6D600] bg-[#FFFF00] text-slate-900", NO_PROGRESS: "border-[#E69CCF] bg-[#FFC4ED] text-slate-900", WAITING_CONFIRMATION: "border-orange-200 bg-[#FFEDD5] text-orange-900",
  POSTPONED_APPROVED: "border-violet-200 bg-violet-50 text-violet-800", POSTPONED_UNAPPROVED: "border-violet-300 bg-violet-50 text-violet-900",
  ADDITIONAL_COMPLETED: "border-blue-200 bg-blue-50 text-[#2563EB]", ADDED_DURING_DAY: "border-blue-200 bg-blue-50 text-[#2563EB]",
}
const statuses: Record<string, string> = { DONE: "Kryer", IN_PROGRESS: "Në progres", TODO: "Pa progres", WAITING_CONFIRMATION: "Në pritje konfirmimi" }
const closeUi: Record<DailyRealizationPerson["close_state"], [string, string]> = {
  NOT_SAVED: ["Dita e hapur", "border-amber-200 bg-amber-50 text-amber-800"], SAVED: ["✓ Dita e mbyllur", "border-emerald-200 bg-emerald-50 text-emerald-800"],
  STALE: ["⚠ Ka ndryshime pas mbylljes", "border-orange-200 bg-orange-50 text-orange-800"], REOPENED: ["Dita është rihapur", "border-blue-200 bg-blue-50 text-blue-800"], CLOSED_EDIT_WINDOW: ["Afati i mbylljes ka përfunduar", "border-rose-200 bg-rose-50 text-rose-800"],
}
const events: Record<string, string> = { PLANNED_FOR_DAY: "Planifikuar për ditën", POSTPONED: "Afati u shty", POSTPONED_AGAIN: "Afati u shty përsëri", POSTPONEMENT_APPROVED: "Shtyrja u aprovua", POSTPONEMENT_REJECTED: "Shtyrja u refuzua", MOVED_BACK_TO_TODAY: "Afati u rikthye për sot", MOVED_EARLIER: "Afati u afrua", COMPLETED: "Detyra u krye", STARTED: "Puna filloi", DUE_DATE_CHANGED: "Afati ndryshoi", STATUS_CHANGED: "Statusi ndryshoi", ASSIGNEE_CHANGED: "Punonjësi ndryshoi", ASSIGNEES_CHANGED: "Punonjësit ndryshuan", CREATED: "Detyra u krijua", UPDATED: "Detyra u përditësua" }
const reasonIssues = new Set(["MISSING_REASON", "REASON_MISSING"])
const commentIssues = new Set(["MISSING_REQUIRED_COMMENT", "COMMENT_MISSING"])
const dailyManualBooleanKeys = manualChecklistBooleanKeys
const dailyQuestionSections = [
  ["1. Detyrat", ["plan_completed", "no_progress_tasks", "in_progress_tasks", "new_tasks_added", "approved_postponement"]],
  ["2. Angazhimi · input", ["requested_extra_tasks", "helped_colleague", "gave_proposal"]],
  ["3. Disiplina", ["respected_meetings", "closed_tasks", "frequent_delays", "unexpected_absences"]],
  ["4. Ndikimi · input", ["week_positive", "week_problems", "affected_other_plan", "repeated_after_clarification"]],
] as const
const dailyQuestionLabels: Record<string, string> = {
  plan_completed: "A janë përfunduar detyrat e planifikuara për këtë ditë?",
  no_progress_tasks: "A ka detyra pa progres këtë ditë?",
  in_progress_tasks: "A ka detyra që mbesin në proces pas kësaj dite?",
  new_tasks_added: "A iu shtuan punëtorit detyra të reja gjatë ditës?",
  approved_postponement: "A pati shtyrje me konfirmim gjatë ditës?",
  respected_meetings: "A janë respektuar takimet e ditës?",
  closed_tasks: "A janë mbyllur detyrat e ditës?",
  frequent_delays: "A ka vonesë në prezencë këtë ditë?",
  unexpected_absences: "A ka mungesë të papritur këtë ditë?",
}
const dailyValueLabels: Record<string, string> = { missed_meeting_evidence:"Evidenca për takime të humbura", answer:"Përgjigjja",planned:"Planifikuar",completed:"Kryer",remaining:"Mbetur",count:"Numri",total:"Gjithsej",in_progress:"Në progres",no_progress:"Pa progres",todo:"To do",postponed:"Shtyrë",yes:"Po",approved:"Aprovuar",unapproved:"Pa aprovim",needs_review:"Për konfirmim",all_closed:"Të gjitha të mbyllura",closed:"Mbyllur",attendance_tardiness:"Vonesa",frequent:"Të shpeshta",threshold:"Pragu",tasks_completed_late:"Kryer me vonesë",tasks_late_open:"Të vonuara të hapura",additional_tasks_candidate:"Detyra shtesë",verified_categories:"Kategori të verifikuara" }
const labelOutcome = (v: string) => outcomeLabels[v] || "Rezultat ditor"
const shortDate = (v?: string | null) => { const m = v?.match(/^(\d{4})-(\d{2})-(\d{2})/); return m ? `${m[3]}.${m[2]}` : v || "—" }
const dailyQuestionValue = (value: unknown): string => { if(value==null||value==="")return"—";if(typeof value==="boolean")return value?"Po":"Jo";if(typeof value==="string"||typeof value==="number")return String(value);if(Array.isArray(value))return value.length?value.map(dailyQuestionValue).join("; "):"—";if(typeof value==="object")return Object.entries(value as Record<string,unknown>).map(([key,item])=>`${dailyValueLabels[key]||key.replaceAll("_"," ")}: ${dailyQuestionValue(item)}`).join(" · ");return String(value) }

function CloseBadge({ person, timezone = TZ }: { person: DailyRealizationPerson; timezone?: string }) { const [label, style] = closeUi[person.close_state]; const closedAt=person.close_state_details?.closed_at; const time=closedAt?new Intl.DateTimeFormat("sq-AL",{timeZone:timezone,hour:"2-digit",minute:"2-digit"}).format(new Date(closedAt)):null; return <div><Badge variant="outline" className={cn("h-auto min-h-6 rounded-full px-2 py-1 text-[10px] font-semibold", style)}>{label}{person.close_state==="SAVED"&&time?` · ${time}`:""}</Badge>{person.close_state==="STALE"?<p className="mt-1 max-w-sm text-[10px] text-orange-700">{person.close_state_details?.stale_cause==="MANAGER_POSTPONEMENT_DECISION"?"Menaxheri vendosi për një shtyrje pas mbylljes së ditës.":"Realizimi ka ndryshuar pas mbylljes së ditës."}</p>:null}</div> }
function Bar({ m, compact = false }: { m: DailyRealizationMetrics; compact?: boolean }) { return <div className={compact ? "w-32" : "w-full"}><div className="flex items-end justify-between gap-2"><b className={compact ? "text-sm" : "text-2xl"}>{pct(m.raw_plan_realization)}</b>{!compact && <span className="text-xs text-slate-500">{m.total_completed_today_count} / {m.original_planned_count} të kryera</span>}</div><div className={cn("mt-1.5 overflow-hidden rounded-full bg-slate-100", compact ? "h-1.5" : "h-2")}><div className="h-full rounded-full bg-[#2563EB]" style={{ width: width(m.raw_plan_realization) }} /></div>{m.adjusted_plan_realization != null && <p className="mt-1 text-[10px] text-slate-500">E rregulluar: <span className={cn(m.adjusted_plan_realization !== m.raw_plan_realization && "font-medium text-[#2563EB]")}>{pct(m.adjusted_plan_realization)}</span></p>}</div> }



function issueState(t: DailyRealizationTask) { return { reason:t.reason_missing||t.issues.some(i=>reasonIssues.has(i)), comment:t.comment_missing||t.issues.some(i=>commentIssues.has(i)), due:t.issues.includes("DUE_DATE_NOT_MOVED"), slot:t.issues.includes("ONE_H_SLOT_MISSING") } }
function Explanation({ t }: { t: DailyRealizationTask }) { const i=issueState(t), missing=i.reason||i.comment, detail=i.reason&&i.comment?"Mungon arsyeja dhe komenti":i.reason?"Mungon arsyeja":"Mungon komenti", reason=dailyRlzReasonLabel(t.reason_code); return <div className="max-w-56 space-y-1.5">{missing&&<div title={detail}><Badge variant="outline" className="border-amber-300 bg-amber-50 text-[10px] text-amber-800"><AlertTriangle className="mr-1 h-3 w-3"/>Kërkon sqarim</Badge><p className="mt-1 text-[10px] text-amber-700">{detail}</p></div>}{!missing&&reason&&<p className="text-xs font-semibold">{reason}</p>}{t.comment&&<p className="line-clamp-2 text-xs text-slate-500" title={t.comment}>{t.comment}</p>}{i.slot&&<p className="text-[10px] font-medium text-amber-700">⚠ Mungon 1H sloti</p>}</div> }
function PlanDue({ t, day }: { t: DailyRealizationTask; day: string }) {
  const i=issueState(t), dueToday=t.current_due_date?.slice(0,10)===day
  const deadlineName=t.deadline_critical?"Deadline Important":"Deadline"
  const deadlineLabel=t.deadline_completed?`${deadlineName} · kryer`:t.postponed_today?`${deadlineName} · shtyrë`:`${deadlineName} · pa kryer`
  return <div className="space-y-2 text-xs">{t.in_original_plan?<div><p className="text-[10px] uppercase text-slate-400">Plan</p><b>{shortDate(t.original_daily_plan)}</b></div>:<Badge variant="outline" className="border-blue-200 bg-blue-50 text-[10px] text-[#2563EB]">EKSTRA</Badge>}<div><p className="text-[10px] uppercase text-slate-400">Afati</p><b className={cn(t.deadline_is_overdue?"text-[#DC2626]":dueToday?"text-amber-700":"text-slate-700")}>{shortDate(t.current_due_date)}{dueToday?" · sot":""}</b></div>{t.deadline_was_today&&<Badge variant="outline" className={cn("text-[10px]",t.deadline_completed?"border-emerald-200 bg-emerald-50 text-emerald-800":t.postponed_today?"border-violet-200 bg-violet-50 text-violet-800":"border-rose-200 bg-rose-50 text-rose-800",t.deadline_critical&&"ring-1 ring-red-300")}>{deadlineLabel}</Badge>}{t.deadline_is_overdue&&<p className="text-[10px] font-semibold text-[#DC2626]">Afat i kaluar</p>}{i.due&&<p className="text-[10px] font-medium text-amber-700">Afati duhet përditësuar</p>}</div>
}

function matchesClassificationFilter(task: DailyRealizationTask, filter: string) {
  if (filter === "ALL") return true
  if (filter === "DEADLINE_ALL") return task.deadline_was_today
  if (filter === "DEADLINE_DONE") return task.deadline_was_today && task.deadline_completed
  if (filter === "DEADLINE_NOT_DONE") return task.deadline_was_today && !task.deadline_completed
  if (filter === "CRITICAL_ALL") return task.deadline_was_today && task.deadline_critical
  if (filter === "CRITICAL_DONE") return task.deadline_was_today && task.deadline_critical && task.deadline_completed
  if (filter === "CRITICAL_NOT_DONE") return task.deadline_was_today && task.deadline_critical && !task.deadline_completed
  if (filter === "EXTRA_ALL") return dailyExtraTaskState(task) !== null
  if (filter === "EXTRA_DONE") return dailyExtraTaskState(task) === "completed"
  if (filter === "EXTRA_PROGRESS") return dailyExtraTaskState(task) === "progress"
  if (filter === "EXTRA_NO_PROGRESS") return dailyExtraTaskState(task) === "no-progress"
  return task.classification === filter
}

function DecisionEvidence({ task, timezone, canReview, onReview }: { task: DailyRealizationTask; timezone: string; canReview: boolean; onReview: () => void }) {
  const decision = task.manager_decision
  const decidedTime = decision?.decided_at ? new Intl.DateTimeFormat("sq-AL", { timeZone: timezone, hour: "2-digit", minute: "2-digit" }).format(new Date(decision.decided_at)) : null
  if (task.adjustment_status === "PENDING") return <div className="mt-2"><p className="text-[10px] font-semibold text-violet-700">Shtyrë · pret aprovim</p>{canReview?<Button size="sm" variant="outline" className="mt-1 h-7 text-xs font-semibold uppercase text-violet-700" onClick={onReview}>Shqyrto</Button>:null}</div>
  if (task.adjustment_status === "APPROVED" || task.adjustment_status === "REJECTED") return <div className="mt-2"><p className={cn("text-[10px] font-semibold",task.adjustment_status==="APPROVED"?"text-emerald-700":"text-rose-700")}>Shtyrë · {task.adjustment_status==="APPROVED"?"aprovuar":"refuzuar"}</p>{decision?.decided_by_name?<p className="text-[10px] text-slate-500">{task.adjustment_status==="APPROVED"?"Aprovuar":"Refuzuar"} nga {decision.decided_by_name}{decidedTime?` · ${decidedTime}`:""}</p>:null}{decision?.comment?<p className="mt-1 line-clamp-2 text-[10px] text-slate-500" title={decision.comment}>Koment: {decision.comment}</p>:null}</div>
  return null
}

function timelineValue(v: unknown) { if(v==null||v==="")return"—"; if(Array.isArray(v))return v.length?`${v.length} punonjës`:"Pa punonjës"; if(typeof v!=="string"&&typeof v!=="number")return"Vlerë e përditësuar"; const s=String(v); return statuses[s]||outcomeLabels[s]||dailyRlzReasonLabel(s)||(/^[A-Z][A-Z0-9_]+$/.test(s)?"Vlerë e përditësuar":shortDate(s)) }
function Timeline({task,open,onOpenChange,timezone}:{task:DailyRealizationTask|null;open:boolean;onOpenChange:(v:boolean)=>void;timezone:string}) { return <Dialog open={open} onOpenChange={onOpenChange}><DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto"><DialogHeader><DialogTitle>Historia e detyrës</DialogTitle></DialogHeader>{task?<div className="border-b pb-3"><MarkedTaskBlock content={task.title}/></div>:null}<div className="pt-2">{task?.timeline.map((e,index)=><div key={e.id} className="relative flex gap-3 pb-5">{index<task.timeline.length-1&&<span className="absolute left-[7px] top-4 h-full w-px bg-slate-200"/>}<span className={cn("mt-1 h-4 w-4 shrink-0 rounded-full border-2",e.type.includes("POSTPON")?"border-violet-500 bg-violet-100":e.type==="COMPLETED"?"border-emerald-500 bg-emerald-100":"border-[#2563EB] bg-white")}/><div className="min-w-0 flex-1"><div className="flex justify-between gap-2"><b className="text-sm">{events[e.type]||"Detyra u përditësua"}</b><span className="text-xs text-slate-500">{e.timestamp?new Intl.DateTimeFormat("sq-AL",{timeZone:timezone,day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}).format(new Date(e.timestamp)):"Plani fillestar"}</span></div>{(e.old_value!=null||e.new_value!=null)&&!e.type.startsWith("POSTPONEMENT_")?<p className="mt-2 rounded bg-slate-50 p-2 text-xs">{timelineValue(e.old_value)} <span className="text-slate-400">→</span> <b>{timelineValue(e.new_value)}</b></p>:null}{(e.actor_name||e.actor_user_id)&&<p className="mt-1 text-xs text-slate-500">Nga {e.actor_name||"përdoruesi"}</p>}{e.metadata?.reason&&<p className="text-xs text-slate-500">Arsyeja: {dailyRlzReasonLabel(e.metadata.reason)||e.metadata.reason}</p>}{e.metadata?.comment&&<p className="mt-1 rounded bg-slate-50 p-2 text-xs text-slate-600">Koment: {e.metadata.comment}</p>}</div></div>)}</div></DialogContent></Dialog> }

function DailyChecklist({ result, canEdit, onSaved }: { result: RealizationPersonResult; canEdit: boolean; onSaved: () => Promise<void> }) {
  const { apiFetch } = useAuth()
  const questions = React.useMemo(() => result.facts_json.questions || [], [result.facts_json.questions])
  const [drafts, setDrafts] = React.useState<Record<string, { value: string; comment: string }>>({})
  const [saving, setSaving] = React.useState<string | null>(null)
  const dirtyKeys = React.useRef(new Set<string>())

  React.useEffect(() => {
    const next: Record<string, { value: string; comment: string }> = {}
    for (const question of questions) {
      if (!question.source_status.startsWith("MANUAL")) continue
      const value = question.final_value
      next[question.key] = {
        value: dailyManualBooleanKeys.has(question.key)
          ? value === true ? "YES" : value === false ? "NO" : ""
          : typeof value === "string" ? value : "",
        comment: question.manager_comment || "",
      }
    }
    setDrafts(current => {
      for (const key of dirtyKeys.current) if (current[key]) next[key] = current[key]
      return next
    })
  }, [questions])

  const updateDraft = (key: string, patch: Partial<{ value: string; comment: string }>) => {
    dirtyKeys.current.add(key)
    setDrafts(current => ({ ...current, [key]: { ...(current[key] || { value: "", comment: "" }), ...patch } }))
  }
  const save = async (question: RealizationQuestion) => {
    const draft = drafts[question.key]
    if (!draft) return
    if (draft.value === "YES" && !draft.comment.trim()) {
      toast.error("Komenti është i detyrueshëm kur përgjigjja është Po")
      return
    }
    setSaving(question.key)
    try {
      const value = draft.value === "YES"
      const response = await apiFetch(`/realization/periods/${result.period_id}/results/${result.id}/questions/${question.key}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value, clear: false, comment: draft.comment.trim() || null, evidence_ids: [] }),
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}))
        throw new Error(typeof payload?.detail === "string" ? payload.detail : "Përgjigjja nuk u ruajt")
      }
      dirtyKeys.current.delete(question.key)
      toast.success("Përgjigjja u ruajt për të gjithë javën")
      await onSaved()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Përgjigjja nuk u ruajt")
    } finally {
      setSaving(null)
    }
  }
  const automaticCount = questions.filter(question => question.source_status.startsWith("AUTO") && dailyQuestionSections.some(([, keys]) => (keys as readonly string[]).includes(question.key))).length
  const completeness = result.facts_json.manual_question_completeness
  return (
    <Card className="rounded-xl shadow-sm">
      <CardHeader className="border-b p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle className="text-base">Checklist-a javore</CardTitle>
            <p className="mt-1 text-xs text-slate-500">Një përgjigje për të gjithë javën, që mund ta japësh ose ta ndryshosh nga cilado ditë.</p>
            <p className="mt-1 text-xs text-slate-500">Mbyllja e detyrave, vonesat dhe mungesat dalin nga sistemi. Takimet dhe gjykimi plotësohen nga përgjegjësi.</p>
          </div>
          <Badge variant="outline">{automaticCount} automatike · {completeness?.answered || 0}/{completeness?.required || manualChecklistBooleanKeys.size} inpute</Badge>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4 p-4 xl:grid-cols-2">
        {dailyQuestionSections.map(([title, keys]) => {
          const rows = keys.map(key => questions.find(question => question.key === key)).filter((question): question is RealizationQuestion => Boolean(question))
          return (
            <section key={title} className="overflow-hidden rounded-lg border">
              <h3 className="border-b bg-slate-50 px-3 py-2 text-xs font-semibold uppercase text-slate-700">{title}</h3>
              <div className="divide-y">
                {rows.map(question => {
                  const manual = question.source_status.startsWith("MANUAL")
                  const proposal = question.key === "gave_proposal"
                  const answered = question.source_status === "MANUAL_ANSWERED"
                  const draft = drafts[question.key] || { value: "", comment: "" }
                  const label = weeklyChecklistLabels[question.key] || dailyQuestionLabels[question.key] || question.label
                  return (
                    <div key={question.key} className={cn("space-y-2 p-3", proposal && "border-y-2 border-cyan-300 bg-cyan-50/70")}>
                      <div className="flex items-start justify-between gap-2">
                        <Label htmlFor={manual ? `daily-question-${question.key}` : undefined} className={cn("text-sm", proposal ? "font-bold text-cyan-950" : "font-medium")}>{label}</Label>
                        <Badge variant={manual && !answered ? "destructive" : "secondary"} className="shrink-0 text-[9px]">
                          {manual ? answered ? "INPUT · Ruajtur" : "INPUT" : question.source_status === "AUTO_NEEDS_CONFIRMATION" ? "AUTO · Konfirmo" : "AUTO"}
                        </Badge>
                      </div>
                      {proposal ? <RealizationProposalNotice yes={draft.value === "YES"} saved={answered && !dirtyKeys.current.has(question.key) && Boolean(draft.comment.trim())} /> : null}
                      {manual && canEdit ? (
                        <div className="space-y-2 rounded-md border bg-white px-3 py-2">
                          <div className="flex items-center justify-between gap-3">
                            <label className="flex items-center gap-2 text-xs font-semibold">
                              <Checkbox checked={draft.value === "YES"} disabled={saving !== null} onCheckedChange={checked => updateDraft(question.key, { value: checked ? "YES" : "NO" })} />
                              {draft.value === "YES" ? "Po" : "Jo"}
                            </label>
                            <Button size="sm" variant="outline" disabled={saving !== null || (draft.value === "YES" && !draft.comment.trim())} onClick={() => void save(question)}>
                              {saving === question.key ? "Duke ruajtur…" : "Ruaj përgjigjen ditore"}
                            </Button>
                          </div>
                          {draft.value === "YES" ? <div className="space-y-1"><Label htmlFor={`daily-question-comment-${question.key}`}>{proposal ? "Propozimi dhe përfitimi (i detyrueshëm)" : "Komenti (i detyrueshëm)"}</Label><Textarea id={`daily-question-comment-${question.key}`} rows={proposal ? 3 : 2} required value={draft.comment} disabled={saving !== null} onChange={event => updateDraft(question.key, { comment: event.target.value })} placeholder={proposal ? "Përshkruaj propozimin dhe përfitimin…" : "Shkruaj komentin e detyrueshëm për përgjigjen Po…"} /></div> : null}
                        </div>
                      ) : (
                        <p className="text-sm text-slate-700">
                          {manual ? answered ? checklistAnswerLabel(question.key, question.final_value) : "Pa përgjigje ditore" : dailyQuestionValue(question.final_value ?? question.auto_value)}
                        </p>
                      )}
                      {question.manager_comment && (!manual || !canEdit) ? <p className="text-xs text-slate-600">{question.manager_comment}</p> : null}
                      {question.explanation ? <p className="text-[11px] text-slate-500">{question.explanation}</p> : null}
                    </div>
                  )
                })}
                {!rows.length ? <p className="p-3 text-xs text-slate-500">Të dhënat do të shfaqen pas kalkulimit ditor.</p> : null}
              </div>
            </section>
          )
        })}
      </CardContent>
    </Card>
  )
}

export function DailyRealizationView() {
 const {apiFetch,user}=useAuth(); const [departments,setDepartments]=React.useState<Department[]>([]),[plannerUsers,setPlannerUsers]=React.useState<UserLookup[]>([]),[departmentId,setDepartmentId]=React.useState(user?.role==="STAFF"?user.department_id||"":"ALL"),[day,setDay]=React.useState(today),[data,setData]=React.useState<DailyRealizationLive|null>(null),[periodIds,setPeriodIds]=React.useState<Record<string,string>>({}),[failedDepartments,setFailedDepartments]=React.useState(0),[reviewVersion,setReviewVersion]=React.useState(0),[personId,setPersonId]=React.useState(""),[personFilter,setPersonFilter]=React.useState("ALL"),[classification,setClassification]=React.useState("ALL"),[sort,setSort]=React.useState("planner"),[loading,setLoading]=React.useState(false),[timelineTask,setTimelineTask]=React.useState<DailyRealizationTask|null>(null),[adjustmentTask,setAdjustmentTask]=React.useState<DailyRealizationTask|null>(null),[adjustmentDecision,setAdjustmentDecision]=React.useState<"APPROVED"|"REJECTED">("APPROVED"),[adjustmentReason,setAdjustmentReason]=React.useState(""),[adjustmentComment,setAdjustmentComment]=React.useState(""),[savingAdjustment,setSavingAdjustment]=React.useState(false); const request=React.useRef(0)
 const [dailyResults,setDailyResults]=React.useState<Record<string,RealizationPersonResult>>({})
 const reportScopeRef = React.useRef("")
 React.useEffect(()=>{void apiFetch("/departments").then(async r=>{if(!r.ok)return;const rows=await r.json() as Department[];const visibleRows=user?.role==="STAFF"?rows.filter(row=>row.id===user.department_id):rows;setDepartments(visibleRows);setDepartmentId(c=>user?.role==="STAFF"?user.department_id||"":c||"ALL")})},[apiFetch,user])
 React.useEffect(()=>{if(user?.role==="STAFF"){setPlannerUsers([]);return}void apiFetch("/users/lookup").then(async r=>{if(r.ok)setPlannerUsers(await r.json() as UserLookup[])})},[apiFetch,user?.role])
 const load = React.useCallback(async (silent = false) => {
   if (!user || (user.role === "STAFF" && departmentId === "ALL")) return
   const departmentIds = departmentId === "ALL" ? departments.map(item => item.id) : departmentId ? [departmentId] : []
   if (!departmentIds.length) return
   const id = ++request.current
   if (!silent) setLoading(true)
   const scope = `${user.id}:${departmentId}:${day}`
   const initialLoad = reportScopeRef.current !== scope
   if (initialLoad) {
     reportScopeRef.current = scope
     setData(null)
     setDailyResults({})
     setPeriodIds({})
   }
   try {
     const received: { departmentId: string; periodId: string; live: DailyRealizationLive; results: RealizationPersonResult[] }[] = []
     const results = await Promise.allSettled(departmentIds.map(async currentDepartmentId => {
       const params = new URLSearchParams({ department_id: currentDepartmentId, day })
       if (user?.role === "STAFF") params.set("user_id", user.id)
       const response = await apiFetch(`/realization/daily?${params}`)
       if (!response.ok) throw new Error("Raporti nuk u ngarkua")
       const payload = await response.json() as { period?: { id: string }; live?: DailyRealizationLive; people?: RealizationPersonResult[] }
       if (!payload.live) throw new Error("Raporti nuk u ngarkua")
       const report = { departmentId: currentDepartmentId, periodId: payload.period?.id || "", live: payload.live, results: payload.people || [] }
       received.push(report)
       if (initialLoad && id === request.current) {
         const ordered = [...received].sort((a, b) => departmentIds.indexOf(a.departmentId) - departmentIds.indexOf(b.departmentId))
         setData(combineDailyRealization(ordered.map(item => item.live)))
         setDailyResults(Object.fromEntries(ordered.flatMap(item => item.results.map(result => [`${item.departmentId}:${result.user_id}`, result]))))
         setPeriodIds(Object.fromEntries(ordered.map(item => [item.departmentId, item.periodId])))
       }
       return report
     }))
     if (id !== request.current) return
     const loaded = results.flatMap(result => result.status === "fulfilled" ? [result.value] : [])
     const failed = results.length - loaded.length
     setFailedDepartments(failed)
     const combined = combineDailyRealization(loaded.map(report => report.live))
     if (!combined) {
       if (!silent) toast.error("Raporti nuk u ngarkua. Provo përsëri.")
       return
     }
     setData(combined)
     setDailyResults(Object.fromEntries(loaded.flatMap(report=>report.results.map(result=>[`${report.departmentId}:${result.user_id}`,result]))))
     setPersonFilter(current => current === "ALL" || combined?.people.some(person => person.user_id === current) ? current : "ALL")
     setPeriodIds(Object.fromEntries(loaded.map(report => [report.departmentId, report.periodId])))
     setPersonId(current => user?.role === "STAFF" ? "" : combined?.people.some(person => person.user_id === current) ? current : "")
   } finally {
     if (id === request.current) setLoading(false)
   }
 }, [apiFetch, day, departmentId, departments, user])

 const prepareDailyResult = React.useCallback(async (currentDepartmentId: string, currentUserId: string) => {
   const params = new URLSearchParams({ department_id: currentDepartmentId, day, user_id: currentUserId })
   const response = await apiFetch(`/realization/daily/checklist/prepare?${params}`, { method: "POST" })
   if (!response.ok) {
     const payload = await response.json().catch(() => ({})) as { detail?: unknown }
     const detail = payload.detail
     const message = typeof detail === "string"
       ? detail
       : detail && typeof detail === "object" && "message" in detail
         ? String((detail as { message?: unknown }).message || "")
         : ""
     throw new Error(message || "Checklist-a ditore nuk mund të përgatitej")
   }
   const payload = await response.json() as { period?: { id: string }; people?: RealizationPersonResult[] }
   if (payload.people?.length) {
     setDailyResults(current => ({
       ...current,
       ...Object.fromEntries(payload.people!.map(result => [`${currentDepartmentId}:${result.user_id}`, result])),
     }))
   }
   if (payload.period?.id) {
     setPeriodIds(current => ({ ...current, [currentDepartmentId]: payload.period!.id }))
   }
   await load(true)
 }, [apiFetch, day, load])

 React.useEffect(()=>{queueMicrotask(()=>void load())},[load])
 const people = React.useMemo(() => {
   const departmentMap = new Map(departments.map(department => [department.id, department]))
   const plannerOrder = Object.fromEntries(plannerUsers.map(plannerUser => [plannerUser.id, plannerUser.weekly_planner_sort_order]))
   return [...(data?.people || [])].sort((a, b) => {
     const departmentOrder = compareRealizationDepartments(departmentMap.get(a.department_id), departmentMap.get(b.department_id))
     if (departmentOrder) return departmentOrder
     const withinDepartment = sort === "planner" ? compareWeeklyPlannerUsers(a, b, plannerOrder)
       : sort === "postponed" ? b.metrics.postponed_count - a.metrics.postponed_count
       : sort === "no-progress" ? b.metrics.no_progress_count - a.metrics.no_progress_count
       : sort === "name" ? 0
       : (a.metrics.raw_plan_realization ?? -1) - (b.metrics.raw_plan_realization ?? -1)
     return withinDepartment || a.user_name.localeCompare(b.user_name)
   })
 }, [data, departments, plannerUsers, sort]); const filteredPeople=people.filter(p=>personFilter==="ALL"||p.user_id===personFilter),selected=people.find(p=>p.user_id===personId),selectedResult=selected?dailyResults[`${selected.department_id}:${selected.user_id}`]:undefined,tasks=(selected?.tasks||[]).filter(t=>matchesClassificationFilter(t,classification)),classes=Array.from(new Set((data?.people||[]).flatMap(p=>p.tasks.map(t=>t.classification)))).sort(),metrics=selected?.metrics||(personFilter!=="ALL"?filteredPeople[0]?.metrics:data?.metrics),filters=classification!=="ALL",dept=departments.find(d=>d.id===(selected?.department_id||departmentId))?.name,periodId=selected?periodIds[selected.department_id]||"":""
 const clear=()=>setClassification("ALL")
 const decide=async()=>{if(!adjustmentTask||!selected||!adjustmentReason.trim())return;const e=[...adjustmentTask.timeline].reverse().find(x=>x.type==="POSTPONED"||x.type==="POSTPONED_AGAIN");if(!e)return;setSavingAdjustment(true);try{const r=await apiFetch(`/realization/daily/tasks/${adjustmentTask.task_id}/adjustment`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({audit_event_id:e.id,user_id:selected.user_id,status:adjustmentDecision,reason:adjustmentReason.trim(),comment:adjustmentComment.trim()||null})});if(!r.ok){const payload=await r.json().catch(()=>({}));throw new Error(payload?.detail||"Vendimi nuk u ruajt")}setAdjustmentTask(null);setAdjustmentReason("");setAdjustmentComment("");await load(true)}catch(error){toast.error(error instanceof Error?error.message:"Vendimi nuk u ruajt")}finally{setSavingAdjustment(false)}}
 const last=(v:string)=>new Intl.DateTimeFormat("sq-AL",{timeZone:data?.timezone||TZ,...(day===today()?{}:{day:"2-digit",month:"2-digit"}),hour:"2-digit",minute:"2-digit"}).format(new Date(v)).replace(","," ·")
 const postponementEvents=adjustmentTask?.timeline.filter(event=>event.type==="POSTPONED"||event.type==="POSTPONED_AGAIN")||[]
 const deadlineChain=postponementEvents.reduce<string[]>((values,event)=>{const old=String(event.old_value||"").slice(0,10),next=String(event.new_value||"").slice(0,10);if(old&&values.at(-1)!==old)values.push(old);if(next&&values.at(-1)!==next)values.push(next);return values},[])
 return <div className="space-y-3">
  <header className="flex flex-wrap items-center justify-between gap-2"><div><div className="flex items-center gap-2"><h1 className="text-lg font-semibold sm:text-xl">REALIZIMI DITOR</h1>{data?.live?<Badge className="h-5 bg-[#2563EB] px-1.5 text-[10px]">LIVE</Badge>:<Badge variant="secondary" className="h-5 px-1.5 text-[10px]">HISTORIK</Badge>}</div><div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs"><span className="capitalize text-slate-600">{new Intl.DateTimeFormat("sq-AL",{dateStyle:"full",timeZone:data?.timezone}).format(new Date(`${day}T12:00:00`))}</span><span className="hidden text-slate-300 sm:inline">•</span><span className="text-slate-400">Përditësuar {data?new Intl.DateTimeFormat("sq-AL",{timeZone:data.timezone,hour:"2-digit",minute:"2-digit",second:"2-digit"}).format(new Date(data.last_updated)):"—"}</span></div></div><Button variant="outline" size="sm" className="h-8" onClick={()=>void load()} disabled={loading}><RefreshCw className={cn("h-3.5 w-3.5",loading&&"animate-spin")}/>Rifresko</Button></header>
  {data&&!data.baseline_available&&<div className="flex gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"><AlertTriangle className="h-4 w-4 shrink-0"/>Nuk ka plan bazë të ruajtur për këtë ditë. Realizimi historik nuk mund të rindërtohet me saktësi.</div>}
   <section className="rounded-lg border bg-slate-50/60 p-2.5"><div className={cn("grid gap-2 sm:grid-cols-2 lg:items-end",user?.role==="STAFF"?"lg:grid-cols-4":"lg:grid-cols-[minmax(280px,520px)_minmax(180px,260px)]")}>{[...(user?.role==="STAFF"?[["Departamenti","department"],["Personi","person"]]:[]),["Data","date"],["Klasifikimi","class"]].map(([l,k])=><div key={k} className="min-w-0 space-y-1"><Label className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{l}</Label>{k==="date"?<Input className="h-8 bg-white text-xs" type="date" value={day} onChange={e=>setDay(e.target.value)}/>:<Select value={k==="department"?departmentId:k==="person"?personId||"ALL":classification} onValueChange={v=>k==="department"?(()=>{setDepartmentId(v);setPersonId("");setAdjustmentTask(null);setTimelineTask(null)})():k==="person"?setPersonId(v==="ALL"?"":v):setClassification(v)} disabled={k==="department"&&user?.role==="STAFF"}><SelectTrigger className="h-8 min-w-0 bg-white text-xs"><SelectValue/></SelectTrigger><SelectContent>{k==="department"?<>{user?.role!=="STAFF"&&<SelectItem value="ALL">Të gjitha departamentet</SelectItem>}{departments.map(d=><SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}</>:k==="person"?<><SelectItem value="ALL">Të gjithë</SelectItem>{people.map(p=><SelectItem key={p.user_id} value={p.user_id}>{p.user_name}</SelectItem>)}</>:<><SelectItem value="ALL">Të gjitha</SelectItem><SelectItem value="DEADLINE_ALL">Afat sot gjithsej</SelectItem><SelectItem value="DEADLINE_DONE">Afat sot të kryera</SelectItem><SelectItem value="DEADLINE_NOT_DONE">Afat sot pa kryer</SelectItem><SelectItem value="CRITICAL_ALL">Deadline Important gjithsej</SelectItem><SelectItem value="CRITICAL_DONE">Deadline Important të kryera</SelectItem><SelectItem value="CRITICAL_NOT_DONE">Deadline Important pa kryer</SelectItem><SelectItem value="EXTRA_ALL">Ekstra gjithsej</SelectItem><SelectItem value="EXTRA_DONE">Ekstra të kryera</SelectItem><SelectItem value="EXTRA_PROGRESS">Ekstra në progres</SelectItem><SelectItem value="EXTRA_NO_PROGRESS">Ekstra pa progres</SelectItem>{classes.map(c=><SelectItem key={c} value={c}>{labelOutcome(c)}</SelectItem>)}</>}</SelectContent></Select>}</div>)}</div></section>
  {loading&&<p role="status" className="py-3 text-center text-sm text-slate-500">{data ? "Duke përditësuar departamentet; përmbledhja mund të jetë ende e pjesshme…" : "Duke ngarkuar..."}</p>}
  {!loading&&failedDepartments>0&&<p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">{failedDepartments} departamente nuk u ngarkuan. Përmbledhja përfshin vetëm departamentet e ngarkuara. Rifresko për të provuar përsëri.</p>}
  {metrics&&<><RealizationPlanSummary metrics={metrics}/><RealizationQuantitySummary metrics={metrics}/></>}
  {selected&&<Card className="gap-3 rounded-md py-3"><CardHeader className="px-4 py-0"><CardTitle className="text-sm">Koment ditor · {selected.user_name}</CardTitle></CardHeader><CardContent className="px-4"><RealizationDailyPersonComment periodId={periodId} userId={selected.user_id} userName={selected.user_name} day={day}/></CardContent></Card>}
   {!personId&&<DailyStaffTable day={day} people={filteredPeople} filterPeople={people} departments={departments} departmentId={departmentId} personFilter={personFilter} onDepartmentFilter={id=>{setDepartmentId(id);setPersonFilter("ALL");setPersonId("");setAdjustmentTask(null);setTimelineTask(null);clear()}} onPersonFilter={id=>{setPersonFilter(id);setPersonId("");clear()}} periodIds={periodIds} results={dailyResults} sort={sort} onSort={setSort} onSelect={id=>{setPersonId(id);clear()}} onSelectExtra={(id,state)=>{setPersonId(id);setClassification(({completed:"EXTRA_DONE",progress:"EXTRA_PROGRESS","no-progress":"EXTRA_NO_PROGRESS",all:"EXTRA_ALL"})[state])}} onSelectDeadline={(id,state)=>{setPersonId(id);setClassification(({completed:"DEADLINE_DONE","not-completed":"DEADLINE_NOT_DONE",all:"DEADLINE_ALL","critical-all":"CRITICAL_ALL","critical-completed":"CRITICAL_DONE","critical-not-completed":"CRITICAL_NOT_DONE"})[state])}} reviewVersion={reviewVersion} onReviewSaved={()=>{setReviewVersion(value=>value+1);void load(true)}} onPrepareResult={prepareDailyResult}/>}

  {selected&&<Card className="rounded-xl shadow-sm"><CardHeader className="border-b p-4">{user?.role!=="STAFF"&&<Button variant="ghost" size="sm" className="mb-2 h-7 w-fit px-1 text-xs" onClick={()=>setPersonId("")}><ArrowLeft className="h-4 w-4"/>Kthehu te stafi</Button>}<div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between"><div><CardTitle className="text-lg">{selected.user_name}</CardTitle><p className="text-xs text-slate-500">{dept||"Departamenti"}</p><div className="mt-2 flex flex-wrap items-start gap-2"><CloseBadge person={selected} timezone={data?.timezone}/><Badge variant="outline" className={selected.metrics.daily_control_state==="ACTION_REQUIRED"?"border-amber-200 bg-amber-50 text-amber-800":"border-emerald-200 bg-emerald-50 text-emerald-800"}>{selected.metrics.daily_control_state==="ACTION_REQUIRED"?"Kërkon veprim":"Dita në rregull"}</Badge>{selected.metrics.unapproved_postponement_count>0?<Badge variant="outline" className="border-violet-200 bg-violet-50 text-violet-800">Pret aprovim: {selected.metrics.unapproved_postponement_count}</Badge>:null}</div></div><div className="flex flex-wrap gap-4 text-xs">{[["Plan",selected.metrics.original_planned_count],["Kryer",selected.metrics.total_completed_today_count],["Në progres",selected.metrics.in_progress_count],["Shtyrë",selected.metrics.postponed_count],["Pa progres",selected.metrics.no_progress_count],["Ekstra gjithsej",selected.metrics.additional_count],["Ekstra të kryera",selected.metrics.additional_completed_count],["Afat sot",selected.metrics.deadlines_today_count],["Afat kryer",selected.metrics.deadlines_completed_count],["Afat pa kryer",Math.max(0,selected.metrics.deadlines_today_count-selected.metrics.deadlines_completed_count)],["Important",selected.metrics.critical_deadlines_today_count],["Imp. kryer",selected.metrics.critical_deadlines_completed_count],["Imp. pa kryer",Math.max(0,selected.metrics.critical_deadlines_today_count-selected.metrics.critical_deadlines_completed_count)]].map(([l,v])=><span key={l}><b className="text-sm">{v}</b> {l}</span>)}</div><div><p className="text-[10px] uppercase">Plan RLZ</p><Bar m={selected.metrics} compact/><p className="text-[10px] text-slate-500">Total të kryera: {selected.metrics.total_completed_today_count}</p></div></div></CardHeader><CardContent className="overflow-x-auto p-0"><Table className="min-w-[1080px] table-fixed"><TableHeader className="sticky top-0 bg-white"><TableRow>{[["Detyra","w-[26%]"],["Plan / Afati","w-[12%]"],["Rezultati","w-[14%]"],["Progresi","w-[7%]"],["Sasi: plan / kryer / +−","w-[12%]"],["Sqarimi","w-[13%]"],["Ndryshimi","w-[10%]"],["Historia","w-[6%]"]].map(([l,w])=><TableHead key={l} className={cn("text-[10px] uppercase",w)}>{l}</TableHead>)}</TableRow></TableHeader><TableBody>{tasks.map((t,index)=><TableRow key={t.match_key} className="align-top"><TableCell className="whitespace-normal"><div className="flex gap-2"><div className="min-w-0 flex-1"><MarkedTaskBlock content={t.title} ordinal={index+1}/>{!t.in_original_plan&&<Badge variant="outline" className="ml-8 mt-1 border-blue-200 bg-blue-50 text-[10px] text-blue-800">Ekstra · jashtë planit fillestar</Badge>}<p className="ml-8 mt-1 line-clamp-1 text-xs text-slate-500">{t.project_title||"Pa projekt"} · {({project:"Projekt",fast:"Fast",system:"Sistem"} as Record<string,string>)[t.source_type]||"Burim tjetër"}</p>{t.postponement_count>1&&<p className="ml-8 text-[10px] text-violet-600">Shtyrë {t.postponement_count} herë</p>}</div>{t.is_bllok&&<Badge variant="outline" className="h-5 border-blue-200 bg-blue-50 text-[9px] text-[#2563EB]">BLL</Badge>}</div></TableCell><TableCell className="whitespace-normal"><PlanDue t={t} day={day}/></TableCell><TableCell className="whitespace-normal"><Badge variant="outline" className={cn("whitespace-normal rounded-md text-left text-[11px]",outcomeStyles[t.classification]||"bg-slate-50")}>{labelOutcome(t.classification)}</Badge><DecisionEvidence task={t} timezone={data?.timezone||TZ} canReview={user?.role!=="STAFF"} onReview={()=>setAdjustmentTask(t)}/>{!((t.classification==="IN_PROGRESS"&&t.current_status==="IN_PROGRESS")||(["REALIZED_AS_PLANNED","COMPLETED_LATE","COMPLETED_EARLY","ADDITIONAL_COMPLETED"].includes(t.classification)&&t.current_status==="DONE")||(t.classification==="NO_PROGRESS"&&t.current_status==="TODO"))&&<p className="mt-1 text-[10px] text-slate-500">Statusi aktual: {statuses[t.current_status]||"Status i përditësuar"}</p>}</TableCell><TableCell><b>{t.progress_today?`+${t.progress_today}%`:t.completed_delta?`+${t.completed_delta}`:"—"}</b></TableCell><TableCell><RealizationTaskQuantity quantity={t.quantity}/></TableCell><TableCell className="whitespace-normal"><Explanation t={t}/></TableCell><TableCell className="text-xs text-slate-500">{t.last_change?last(t.last_change):"—"}</TableCell><TableCell><Button size="icon" variant="ghost" title="Historia" aria-label="Historia" onClick={()=>setTimelineTask(t)}><History className="h-4 w-4"/></Button></TableCell></TableRow>)}</TableBody></Table>{!tasks.length&&<div className="p-10 text-center text-sm text-slate-500"><CalendarDays className="mx-auto mb-2 h-6 w-6"/><p>{filters?"Nuk ka rezultate për filtrat e zgjedhur.":"Nuk ka aktivitet për këtë ditë."}</p>{filters&&<Button variant="ghost" size="sm" onClick={clear}>Pastro filtrat</Button>}</div>}</CardContent></Card>}
  <Timeline task={timelineTask} open={Boolean(timelineTask)} onOpenChange={o=>{if(!o)setTimelineTask(null)}} timezone={data?.timezone||TZ}/><Dialog open={Boolean(adjustmentTask)} onOpenChange={o=>{if(!o&&!savingAdjustment){setAdjustmentTask(null);setAdjustmentReason("");setAdjustmentComment("")}}}><DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-xl"><DialogHeader><DialogTitle>SHQYRTO SHTYRJEN</DialogTitle><DialogDescription>Kontrollo ndryshimin dhe evidencën e stafit para vendimit.</DialogDescription></DialogHeader><div className="space-y-4">{selected?<div className="grid grid-cols-[90px_1fr] gap-2 text-sm"><span className="text-slate-500">Punonjësi</span><b>{selected.user_name}</b><span className="text-slate-500">Detyra</span><div>{adjustmentTask?<MarkedTaskBlock content={adjustmentTask.title} ordinal={1}/>:null}</div></div>:null}<div className="rounded-xl border border-violet-200 bg-violet-50 p-4"><p className="text-[10px] font-semibold uppercase tracking-wide text-violet-700">Ndryshimi i afatit</p><div className="mt-2 flex flex-wrap items-center gap-2 text-lg font-bold">{deadlineChain.map((value,index)=><React.Fragment key={`${value}-${index}`}><span>{value.split("-").reverse().join(".")}</span>{index<deadlineChain.length-1?<span className="text-violet-400">→</span>:null}</React.Fragment>)}</div>{postponementEvents.length>1?<p className="mt-1 text-xs text-violet-700">Shtyrë {postponementEvents.length} herë</p>:null}</div><div className="grid gap-3 sm:grid-cols-2"><div className="rounded-lg border p-3"><p className="text-[10px] font-semibold uppercase text-slate-500">Arsyeja e stafit</p><p className="mt-1 text-sm">{adjustmentTask?dailyRlzReasonLabel(adjustmentTask.reason_code)||"Kërkon sqarim":"—"}</p></div><div className="rounded-lg border p-3"><p className="text-[10px] font-semibold uppercase text-slate-500">Komenti i stafit</p><p className="mt-1 text-sm">{adjustmentTask?.comment?`“${adjustmentTask.comment}”`:"Kërkon sqarim"}</p></div></div><div><Label className="mb-2 block text-xs uppercase">Vendimi</Label><div className="grid grid-cols-2 gap-2"><Button type="button" variant="outline" className={cn("h-10",adjustmentDecision==="APPROVED"&&"border-emerald-400 bg-emerald-50 text-emerald-800 hover:bg-emerald-100")} onClick={()=>setAdjustmentDecision("APPROVED")}>APROVO</Button><Button type="button" variant="outline" className={cn("h-10",adjustmentDecision==="REJECTED"&&"border-rose-400 bg-rose-50 text-rose-800 hover:bg-rose-100")} onClick={()=>setAdjustmentDecision("REJECTED")}>REFUZO</Button></div></div><div className="space-y-1.5"><Label htmlFor="adjustment-reason">Arsyeja e vendimit *</Label><Textarea id="adjustment-reason" rows={2} value={adjustmentReason} onChange={e=>setAdjustmentReason(e.target.value)} placeholder="Shkruaj arsyen e vendimit"/></div><div className="space-y-1.5"><Label htmlFor="adjustment-comment">Koment i menaxherit (opsional)</Label><Textarea id="adjustment-comment" rows={2} value={adjustmentComment} onChange={e=>setAdjustmentComment(e.target.value)} placeholder="Shto një koment për stafin"/></div></div><DialogFooter><Button variant="outline" onClick={()=>setAdjustmentTask(null)} disabled={savingAdjustment}>Anulo</Button><Button className="bg-blue-600 hover:bg-blue-700" onClick={()=>void decide()} disabled={!adjustmentReason.trim()||savingAdjustment}>{savingAdjustment?"Duke ruajtur…":"Ruaj vendimin"}</Button></DialogFooter></DialogContent></Dialog>
  {selected&&selectedResult?<DailyChecklist key={selectedResult.id} result={selectedResult} canEdit={user?.role==="ADMIN"||user?.role==="MANAGER"} onSaved={()=>load(true)}/>:null}
  {selected&&periodId?<RealizationManagerReview key={`${periodId}:${selected.user_id}`} periodId={periodId} userId={selected.user_id} onSaved={()=>setReviewVersion(value=>value+1)}/>:null}
 </div>
}
