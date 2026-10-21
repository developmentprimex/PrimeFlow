"use client"

import * as React from "react"
import { useAuth } from "@/lib/auth"
import { recordingJson } from "@/lib/recording-outbox"
import { inferSkillCategory } from "@/lib/skills"
import type { Project, SkillCategory, SkillCategoryInference, Task } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { TaskSkillField } from "@/components/task-skill-field"
import { TaskTitleLimitHint } from "@/components/task-title-limit-hint"
import { recordingTaskTitle } from "@/lib/recording-transcript"
import { toDateInputValue } from "@/lib/dates"
import { getConfirmerCandidates, isWaitingConfirmation } from "@/lib/task-confirmation"
import type { RecordingAction, RecordingPerson, RecordingDepartment } from "./analysis-panel"

const selectClass = "h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
const markers: Array<[NonNullable<Task["one_h_marker"]>, string]> = [
  ["QUESTION", "?"], ["EXCLAMATION", "!"], ["CLIENT_URGENT", "!!!"], ["SHARE", "SHARE"],
  ["MONITOR", "👁"], ["CLOSE", "X"], ["M2", "M2"], ["M3", "M3"], ["M2_M3", "M2/3"],
  ["GENT", "GENT"], ["KA", "KA"], ["FLAG", "GA"], ["F", "F"], ["BZ1N1", "BZ1N1"],
]

function MultiPicker({ label, items, value, onChange }: { label: string; items: { id: string; name: string }[]; value: string[]; onChange: (ids: string[]) => void }) {
  const id = React.useId()
  return <div className="space-y-2"><Label htmlFor={id}>{label}</Label><div className="space-y-2 rounded-md border p-2">
    <div className="flex flex-wrap gap-2">{value.length ? value.map(key => <button type="button" key={key} className="rounded-full bg-muted px-2 py-1 text-xs" aria-label={`Hiq ${items.find(i => i.id === key)?.name || key}`} onClick={() => onChange(value.filter(v => v !== key))}>{items.find(i => i.id === key)?.name || key} ×</button>) : <span className="text-xs text-muted-foreground">Asnjë i zgjedhur.</span>}</div>
    <select id={id} className={selectClass} value="" onChange={e => { if (e.target.value) onChange([...value, e.target.value]) }}><option value="">Shto…</option>{items.filter(i => !value.includes(i.id)).map(i => <option key={i.id} value={i.id}>{i.name}</option>)}</select>
  </div></div>
}

export function RecordingTaskDialog({ action, recordingId, people, departments, onClose, onCreated, task }: {
  action: RecordingAction; recordingId: string; people: RecordingPerson[]; departments: RecordingDepartment[];
  onClose: () => void; onCreated: (id: string) => Promise<void>;
  task?: Task;
}) {
  const { apiFetch, user } = useAuth()
  const suggested = people.find(p => p.id === action.suggested_assignee_id)
  const [title, setTitle] = React.useState(recordingTaskTitle(task?.title ?? [action.title.trim(), action.description.trim()].filter(Boolean).join("\n")))
  const description = task?.description || ""
  const initialDepartment = task?.department_id || suggested?.department_id || user?.department_id
  const [departmentIds, setDepartmentIds] = React.useState<string[]>(initialDepartment ? [initialDepartment] : [])
  const [assignees, setAssignees] = React.useState<string[]>(task ? [...new Set([...(task.assigned_to ? [task.assigned_to] : []), ...(task.assignees || []).map(p => p.id)])] : suggested ? [suggested.id] : [])
  const [projects, setProjects] = React.useState<Project[]>([])
  const [projectId, setProjectId] = React.useState(task?.project_id || "")
  const [priority, setPriority] = React.useState(task ? task.is_bllok ? "BLLOK" : task.is_1h_report ? "1H" : task.is_r1 ? "R1" : task.is_personal ? "PERSONAL" : task.priority || "NORMAL" : "NORMAL")
  const [status, setStatus] = React.useState(task?.status || "TODO")
  const [confirmer, setConfirmer] = React.useState(task?.confirmation_assignee_id || "")
  const [finishPeriod, setFinishPeriod] = React.useState(task?.finish_period || "")
  const [slot, setSlot] = React.useState(task?.one_h_report_slot || "")
  const [marker, setMarker] = React.useState(task?.one_h_marker || "")
  const [markerComment, setMarkerComment] = React.useState(task?.one_h_marker_comment || "")
  const [startDate, setStartDate] = React.useState(toDateInputValue(task?.start_date))
  const [dueDate, setDueDate] = React.useState(task ? toDateInputValue(task.due_date) : action.suggested_due_date || "")
  const [important, setImportant] = React.useState(task?.is_deadline_important || false)
  const [skill, setSkill] = React.useState<SkillCategory | null>(() => task ? task.skill_category || null : inferSkillCategory(action.title, action.description, action.evidence))
  const [skillReason, setSkillReason] = React.useState("")
  const [skillBusy, setSkillBusy] = React.useState(false)
  const inferenceVersion = React.useRef(0)
  const mounted = React.useRef(true)
  const [busy, setBusy] = React.useState(false)
  const submitting = React.useRef(false)
  const [error, setError] = React.useState("")
  React.useEffect(() => {
    let active = true
    mounted.current = true
    void apiFetch("/projects").then(recordingJson).then((items: Project[]) => { if (active) setProjects(items) }).catch(() => { if (active) setError("Projektet nuk u ngarkuan. Mbyll dhe provo përsëri.") })
    return () => { active = false; mounted.current = false }
  }, [apiFetch])
  const projectOptions = projects.filter(p => !p.department_id || departmentIds.includes(p.department_id))
  const addAssignees = (ids: string[]) => {
    setAssignees(ids)
    setDepartmentIds(previous => [...new Set([...previous, ...people.filter(p => ids.includes(p.id)).flatMap(p => p.department_id ? [p.department_id] : [])])])
  }
  const infer = async () => {
    const version = ++inferenceVersion.current
    setSkillBusy(true)
    try {
      const result: SkillCategoryInference = await recordingJson(await apiFetch("/skills/infer-category", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title, description }) }))
      if (mounted.current && inferenceVersion.current === version) { setSkill(result.category); setSkillReason(result.reason) }
    } catch { if (mounted.current && inferenceVersion.current === version) setSkillReason("Analiza AI nuk u krye. Zgjidh llojin e punës manualisht.") }
    finally { if (mounted.current && inferenceVersion.current === version) setSkillBusy(false) }
  }
  const submit = async () => {
    if (submitting.current) return
    submitting.current = true; setBusy(true); setError("")
    try {
      const fields = {
          title: recordingTaskTitle(title.trim()), description, department_id: departmentIds[0],
          assigned_to: assignees[0] || null, assignees, project_id: projectId || null,
          priority: priority === "HIGH" ? "HIGH" : "NORMAL", finish_period: finishPeriod || null,
          start_date: startDate ? new Date(`${startDate}T00:00:00`).toISOString() : null,
          due_date: dueDate ? new Date(`${dueDate}T17:00:00`).toISOString() : null,
          is_deadline_important: important, is_bllok: priority === "BLLOK", is_1h_report: priority === "1H",
          is_r1: priority === "R1", is_personal: priority === "PERSONAL", one_h_report_slot: priority === "1H" || priority === "R1" ? slot || null : null,
          one_h_marker: marker || null, one_h_marker_comment: marker ? markerComment.trim() || null : null, skill_category: skill,
      }
      if (task) {
        // PATCH only edited fields so dates, markers and assignees keep their
        // existing scheduling and notification semantics when left untouched.
        const updates: Record<string, unknown> = {}
        for (const [key, value] of Object.entries(fields)) {
          const current = task[key as keyof Task]
          if (key === "assignees") {
            const ids = [...new Set([...(task.assignees || []).map(p => p.id), ...(task.assigned_to ? [task.assigned_to] : [])])]
            if (ids.length !== assignees.length || ids.some(id => !assignees.includes(id))) updates[key] = value
          } else if (key === "start_date" || key === "due_date") {
            if (toDateInputValue(current as string | null) !== (key === "start_date" ? startDate : dueDate)) updates[key] = value
          } else if (JSON.stringify(current ?? (typeof value === "boolean" ? false : null)) !== JSON.stringify(value)) updates[key] = value
        }
        if (status !== task.status) updates.status = status
        if (isWaitingConfirmation(status) && confirmer !== task.confirmation_assignee_id) updates.confirmation_assignee_id = confirmer
        if (Object.keys(updates).length) await recordingJson(await apiFetch(`/tasks/${task.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(updates) }))
        await onCreated(task.id)
      } else {
        const result: { task_id: string } = await recordingJson(await apiFetch(`/meeting-recordings/${recordingId}/actions/${action.id}/task`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(fields) }))
        await onCreated(result.task_id)
      }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { submitting.current = false; setBusy(false) }
  }
  return <Dialog open onOpenChange={open => { if (!open && !busy) onClose() }}><DialogContent className="flex max-h-[calc(100dvh-2rem)] w-[95vw] flex-col overflow-hidden sm:max-w-3xl" aria-describedby={undefined}>
    <DialogHeader><DialogTitle>{task ? "Edit task" : "Krijo detyrë nga regjistrimi"}</DialogTitle></DialogHeader>
    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pr-2"><fieldset disabled={busy} className="min-w-0 space-y-4">
      <div className="space-y-2"><Label htmlFor="recording-task-title">Titulli i detyrës</Label><Textarea id="recording-task-title" value={title} maxLength={6000} className="h-24 min-h-24 max-h-24 resize-none" onChange={e => setTitle(recordingTaskTitle(e.target.value))} /><TaskTitleLimitHint title={title} /></div>
      <div className="grid gap-3 md:grid-cols-2">
        {task && <div><Label htmlFor="recording-task-status">Status</Label><select id="recording-task-status" className={selectClass} value={status} onChange={e => setStatus(e.target.value)}><option value="TODO">To do</option><option value="IN_PROGRESS">In progress</option><option value="WAITING_CLIENT">WFE</option><option value="WAITING_CONFIRMATION">Waiting Confirmation</option><option value="DONE">Done</option></select></div>}
        {task && isWaitingConfirmation(status) && <div><Label htmlFor="recording-task-confirmer">Confirm by</Label><select id="recording-task-confirmer" className={selectClass} value={confirmer} onChange={e => setConfirmer(e.target.value)}><option value="">Select confirmer</option>{getConfirmerCandidates(people.map(p => ({ ...p, role: p.role || "STAFF" }))).map(p => <option key={p.id} value={p.id}>{p.full_name}</option>)}</select></div>}
        <div><Label htmlFor="recording-task-priority">Priority</Label><select id="recording-task-priority" className={selectClass} value={priority} onChange={e => { setPriority(e.target.value); setSlot("") }}>{["NORMAL", ...(projectId ? ["HIGH"] : []), "R1", "1H", "PERSONAL", "BLLOK"].map(p => <option key={p}>{p}</option>)}</select></div>
        <div><Label htmlFor="recording-task-finish">Finish by (optional)</Label><select id="recording-task-finish" className={selectClass} value={finishPeriod} onChange={e => { setFinishPeriod(e.target.value); setSlot("") }}><option value="">None (all day)</option><option>AM</option><option>PM</option></select></div>
        {(priority === "1H" || (task && priority === "R1")) && <div><Label htmlFor="recording-task-slot">1H slot (optional)</Label><select id="recording-task-slot" className={selectClass} value={slot} onChange={e => { setSlot(e.target.value); if (e.target.value) setFinishPeriod(["14:20", "16:00"].includes(e.target.value) ? "PM" : "AM") }}><option value="">Unassigned</option>{["10:00", "11:00", "11:50", "14:20", "16:00"].filter(s => !finishPeriod || (finishPeriod === "PM" ? s >= "14:20" : s < "14:20")).map(s => <option key={s}>{s}</option>)}</select></div>}
        <div><Label htmlFor="recording-task-marker">Symbol (optional)</Label><select id="recording-task-marker" className={selectClass} value={marker} onChange={e => { setMarker(e.target.value); setMarkerComment("") }}><option value="">No symbol</option>{markers.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
        {marker && <div><Label htmlFor="recording-task-marker-comment">Symbol comment (optional)</Label><Input id="recording-task-marker-comment" value={markerComment} maxLength={1000} onChange={e => setMarkerComment(e.target.value)} /></div>}
        <div><Label htmlFor="recording-task-start">Start date (optional)</Label><Input id="recording-task-start" type="date" value={startDate} onChange={e => setStartDate(e.target.value)} /></div>
        <div><Label htmlFor="recording-task-due">Due date (optional)</Label><Input id="recording-task-due" type="date" min={startDate || undefined} value={dueDate} onChange={e => setDueDate(e.target.value)} /></div>
      </div>
      <label className="flex items-center gap-3 rounded-md border p-3 text-sm"><input type="checkbox" checked={important} onChange={e => setImportant(e.target.checked)} />Deadline important</label>
      <div className="grid gap-3 md:grid-cols-2">
        <MultiPicker label="Departments" items={departments} value={departmentIds} onChange={ids => { setDepartmentIds(ids); setProjectId(""); if (priority === "HIGH") setPriority("NORMAL") }} />
        <div><Label htmlFor="recording-task-project">Project (optional)</Label><select id="recording-task-project" className={selectClass} value={projectId} onChange={e => { setProjectId(e.target.value); if (!e.target.value && priority === "HIGH") setPriority("NORMAL") }}><option value="">No project</option>{projectOptions.map(p => <option key={p.id} value={p.id}>{p.display_title || p.title || p.name || p.id}</option>)}</select></div>
      </div>
      <MultiPicker label="Assign to" items={people.map(p => ({ id: p.id, name: p.full_name }))} value={assignees} onChange={addAssignees} />
      <TaskSkillField value={skill} onChange={value => { inferenceVersion.current++; setSkillBusy(false); setSkill(value); setSkillReason("") }} disabled={busy} selectedAssigneeIds={assignees} onSelectCandidate={id => addAssignees([...new Set([...assignees, id])])} />
      {skillReason && <p className="text-xs text-muted-foreground">{skillReason}</p>}
      <Button type="button" variant="ghost" disabled={skillBusy || busy} onClick={() => void infer()}>{skillBusy ? "Duke analizuar…" : "Analizo me AI përsëri"}</Button>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </fieldset></div>
    <div className="flex shrink-0 justify-end gap-2 border-t pt-3"><Button variant="outline" disabled={busy} onClick={onClose}>Cancel</Button><Button disabled={busy || title.trim().length < 2 || !departmentIds.length || (!task && !assignees.length) || (isWaitingConfirmation(status) && !confirmer) || Boolean(startDate && dueDate && startDate > dueDate)} onClick={() => void submit()}>{busy ? "Duke ruajtur…" : task ? "Save changes" : "Konfirmo dhe krijo detyrën"}</Button></div>
  </DialogContent></Dialog>
}
