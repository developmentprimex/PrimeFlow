"use client"

import { meetingTranslator } from "@/lib/meeting-notes-language"

import * as React from "react"
import Link from "next/link"
import { Mic, Pencil, PenLine, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import {
  clock, dmy, noteCellClass, noteColumns, parseMeetingNoteDueDate, PICKABLE_STATUSES, readError, shortDm, STATUS_STYLE, userInitials, userName,
  type LookupUser, type MeetingKind, type MeetingNote, type MeetingNoteTaskStatus,
} from "@/lib/meeting-notes"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { AttachmentThumb, PendingThumb } from "./attachment-thumb"

const th = "border border-slate-600 bg-white px-2 h-10 text-left align-bottom font-medium"
const td = "border border-slate-600 p-2 align-bottom"
const selectClass = "h-9 w-full rounded-md border border-input bg-background px-3 text-sm"

function AssignmentCell({ note, field, people, users, onChanged, english = false }: {
  note: MeetingNote
  english?: boolean
  field: "assignee_user_id" | "due_date"
  people: LookupUser[]
  users: Map<string, LookupUser>
  onChanged: (note: MeetingNote) => void
}) {
  const t = meetingTranslator(english)
  const { apiFetch } = useAuth()
  const isOwner = field === "assignee_user_id"
  const initialValue = isOwner ? note.assignee_user_id || "" : note.due_date ? dmy(note.due_date) : ""
  const [value, setValue] = React.useState(initialValue)
  const [saving, setSaving] = React.useState(false)
  const savingRef = React.useRef(false)
  const changed = value !== initialValue

  const save = async () => {
    if (!changed || savingRef.current) return
    const nextValue = isOwner ? value || null : parseMeetingNoteDueDate(value)
    if (nextValue === undefined) {
      toast.error(t("Shkruaj një datë të vlefshme, p.sh. 15122026 ose 15.12.2026."))
      return
    }
    savingRef.current = true
    setSaving(true)
    try {
      const response = await apiFetch(`/meeting-notes/${note.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: nextValue }),
      })
      if (!response.ok) throw new Error(await readError(response, t("Ndryshimi nuk u ruajt.")))
      onChanged((await response.json()) as MeetingNote)
      if (!isOwner) setValue(nextValue ? dmy(nextValue) : "")
      toast.success(isOwner ? t("Përgjegjësi u ruajt.") : t("Afati u ruajt."))
    } catch (error) { toast.error(error instanceof Error ? error.message : String(error)) }
    finally { savingRef.current = false; setSaving(false) }
  }

  return <div className="grid gap-2">
    {isOwner ? <select aria-label={t("Kush")} className={`${selectClass} min-w-0 px-1 text-xs`} value={value} disabled={saving} onChange={(event) => setValue(event.target.value)}>
      <option value="">—</option>
      {note.assignee_user_id && !users.has(note.assignee_user_id) && <option value={note.assignee_user_id}>{userName(users, note.assignee_user_id)}</option>}
      {people.map((person) => <option key={person.id} value={person.id}>{userName(users, person.id)}</option>)}
    </select> : <Input aria-label={t("Afati")} type="text" inputMode="numeric" placeholder={t("dd.mm.vvvv")} maxLength={10} className="min-w-0 px-1 text-xs" value={value} disabled={saving} onChange={(event) => setValue(event.target.value)} />}
    {(changed || saving) && <>
      {note.ga_note_id && <p className="text-xs text-muted-foreground">{t("Ndryshimi këtu nuk përditëson kopjen në PX Notes apo detyrat e saj.")}</p>}
      <div className="flex flex-wrap gap-1">
        <Button size="sm" className="h-7 px-2 text-xs" disabled={saving} onClick={() => void save()}>{saving ? t("Duke ruajtur…") : t("Ruaj")}</Button>
        <Button size="sm" variant="outline" className="h-7 px-2 text-xs" disabled={saving} onClick={() => setValue(initialValue)}>{t("Anulo")}</Button>
      </div>
    </>}
  </div>
}

function NoteTextCell({ note, field, onChanged, english = false }: { english?: boolean; note: MeetingNote; field: "content" | "answer"; onChanged: (note: MeetingNote) => void }) {
  const t = meetingTranslator(english)
  const { apiFetch } = useAuth()
  const original = note[field] || ""
  const [text, setText] = React.useState(original)
  const [saving, setSaving] = React.useState(false)
  const savingRef = React.useRef(false)
  const changed = text.trim() !== original.trim()
  const isContent = field === "content"
  const canSave = changed && (!isContent || Boolean(text.trim()))

  const save = async () => {
    if (!canSave || savingRef.current) return
    savingRef.current = true
    setSaving(true)
    try {
      const response = await apiFetch(`/meeting-notes/${note.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: text.trim() || null }),
      })
      if (!response.ok) throw new Error(await readError(response, isContent ? t("Shënimi nuk u ruajt.") : t("Përshkrimi / PËRGJIGJA nuk u ruajt.")))
      onChanged((await response.json()) as MeetingNote)
      toast.success(isContent ? t("Shënimi u ruajt.") : t("Përshkrimi / PËRGJIGJA u ruajt."))
    } catch (error) { toast.error(error instanceof Error ? error.message : String(error)) }
    finally { savingRef.current = false; setSaving(false) }
  }

  return <div className="grid gap-2">
    {isContent && note.kind === "QUESTION" && <span className="text-xs font-medium">{t("? Pyetje")}</span>}
    <Textarea aria-label={isContent ? t("Shënimi / pyetja") : t("Përshkrimi / PËRGJIGJA")} placeholder={isContent ? t("Shkruaj shënimin ose pyetjen…") : t("Shkruaj përshkrimin ose përgjigjen…")} rows={2}
      className={`min-h-14 resize-y ${isContent ? "bg-transparent" : ""}`} value={text} disabled={saving} maxLength={isContent ? 10000 : undefined}
      onChange={(event) => setText(event.target.value)}
      onKeyDown={(event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); void save() }
        if (event.key === "Escape" && !saving) { event.preventDefault(); setText(original) }
      }} />
    {(changed || saving) && <>
      {note.ga_note_id && <p className="text-xs text-muted-foreground">{t("Ndryshimi këtu nuk përditëson kopjen në PX Notes.")}</p>}
      <div className="flex gap-2">
        <Button size="sm" className="h-7 text-xs" disabled={saving || !canSave} onClick={() => void save()}>{saving ? t("Duke ruajtur…") : t("Ruaj")}</Button>
        <Button size="sm" variant="outline" className="h-7 text-xs" disabled={saving} onClick={() => setText(original)}>{t("Anulo")}</Button>
      </div>
    </>}
  </div>
}

export function SourceCell({ note, users }: { note: MeetingNote; users: Map<string, LookupUser> }) {
  if (note.source === "RECORDING") {
    const label = `${shortDm(note.occurrence_date)}${note.recording_seconds != null ? ` · ${clock(note.recording_seconds)}` : ""}`
    const content = <>
      <span className="inline-flex items-center gap-1 text-xs font-bold"><Mic className="size-3.5" aria-hidden="true" />Recording</span>
      <span className="text-xs underline">▶ {label}</span>
    </>
    return note.recording_id
      ? <Link href={`/meeting-recordings/${note.recording_id}${note.recording_seconds != null ? `?t=${Math.floor(note.recording_seconds)}` : ""}`} className="flex flex-col gap-0.5 text-violet-800">{content}</Link>
      : <span className="flex flex-col gap-0.5 text-violet-800">{content}</span>
  }
  return <span className="flex flex-col gap-0.5">
    <span className="inline-flex items-center gap-1 text-xs font-bold text-neutral-700"><PenLine className="size-3.5" aria-hidden="true" />Manual</span>
    <span className="text-xs text-neutral-600">{userInitials(users, note.created_by)}</span>
  </span>
}

export function NotesTable({
  notes, kind, users, selected, onToggleSelect, onChanged, onRemoved, onTasksChanged, showSessionDate = false,
}: {
  notes: MeetingNote[]
  kind: MeetingKind
  users: Map<string, LookupUser>
  selected?: Set<string>
  onToggleSelect?: (id: string) => void
  onChanged: (note: MeetingNote) => void
  onRemoved?: (id: string) => void
  onTasksChanged?: () => void
  showSessionDate?: boolean
}) {
  const english = kind === "EXTERNAL"
  const t = meetingTranslator(english)
  const { apiFetch } = useAuth()
  const [editing, setEditing] = React.useState<MeetingNote | null>(null)
  const [busyId, setBusyId] = React.useState<string | null>(null)
  const cols = noteColumns(kind)
  const people = React.useMemo(() => [...users.values()].sort((a, b) => userName(users, a.id).localeCompare(userName(users, b.id), "sq")), [users])

  const setTaskStatus = async (note: MeetingNote, status: MeetingNoteTaskStatus) => {
    const taskId = note.task_ids[0]
    if (!taskId) return
    setBusyId(note.id)
    try {
      const response = await apiFetch(`/tasks/${taskId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) })
      if (!response.ok) throw new Error(await readError(response, t("Statusi nuk u ndryshua.")))
      onChanged({ ...note, task_status: status })
      onTasksChanged?.()
    } catch (error) { toast.error(error instanceof Error ? error.message : String(error)) }
    finally { setBusyId(null) }
  }

  const sendToPx = async (note: MeetingNote) => {
    setBusyId(note.id)
    try {
      const response = await apiFetch("/meeting-notes/send-to-px", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ note_ids: [note.id], merge: false }) })
      if (!response.ok) throw new Error(await readError(response, t("Shënimi nuk u dërgua në PX Notes.")))
      const [updated] = (await response.json()) as MeetingNote[]
      if (updated) onChanged(updated)
      toast.success(t("U dërgua në PX Notes. Krijo detyrën atje."))
    } catch (error) { toast.error(error instanceof Error ? error.message : String(error)) }
    finally { setBusyId(null) }
  }

  const deleteNote = async (note: MeetingNote) => {
    if (!onRemoved || busyId) return
    const message = t("Fshi këtë shënim nga takimi?") + (note.ga_note_id ? `\n${t("Fshirja këtu nuk fshin kopjen në PX Notes ose detyrat e saj.")}` : "")
    if (!window.confirm(message)) return
    setBusyId(note.id)
    try {
      const response = await apiFetch(`/meeting-notes/${note.id}`, { method: "DELETE" })
      if (!response.ok) throw new Error(await readError(response, t("Shënimi nuk u fshi.")))
      onRemoved(note.id)
      toast.success(t("Shënimi u fshi."))
    } catch (error) { toast.error(error instanceof Error ? error.message : String(error)) }
    finally { setBusyId(null) }
  }

  return <>
    <div className="overflow-x-auto rounded-md border-2 border-slate-700 bg-white">
      <table className="w-full min-w-[1280px] table-fixed border-collapse text-sm">
        <thead>
          <tr>
            {onToggleSelect && <th className={`${th} w-9`}><span className="sr-only">{t("Zgjidh")}</span></th>}
            <th className={`${th} w-12`}>{cols.nr}</th>
            <th className={`${th} w-[118px]`}>{cols.source}</th>
            <th className={th}>{cols.note}</th>
            <th className={`${th} w-[24%]`}>{cols.answer}</th>
            <th className={`${th} w-[160px]`}>{cols.owner}</th>
            <th className={`${th} w-[150px]`}>{cols.due}</th>
            <th className={`${th} w-[150px]`}>{cols.status}</th>
            <th className={`${th} w-20`}><span className="sr-only">{english ? "Actions" : "Veprime"}</span></th>
          </tr>
        </thead>
        <tbody>
          {notes.map((note, index) => {
            const checked = selected?.has(note.id) ?? false
            return <tr key={note.id} className={checked ? "outline outline-2 -outline-offset-2 outline-blue-600" : "hover:bg-muted/40"}>
              {onToggleSelect && <td className={`${td} text-center`}>
                <input type="checkbox" aria-label={`${english ? "Select note" : "Zgjidh shënimin"} ${index + 1}`} checked={checked} disabled={Boolean(note.ga_note_id)}
                  title={note.ga_note_id ? t("Është dërguar tashmë në PX Notes") : undefined} onChange={() => onToggleSelect(note.id)} />
              </td>}
              <td className={`${td} font-bold tabular-nums text-muted-foreground`}>{index + 1}</td>
              <td className={`${td} ${note.source === "RECORDING" ? "bg-violet-50" : ""}`}><SourceCell note={note} users={users} /></td>
              <td className={`${td} whitespace-pre-wrap break-words ${noteCellClass(note)}`}>
                <NoteTextCell english={english} key={`${note.id}:content:${note.content}`} note={note} field="content" onChanged={onChanged} />
                <div className="mt-1 text-xs opacity-80">{[note.reference, showSessionDate || note.occurrence_date ? dmy(note.occurrence_date) : null].filter(Boolean).join(" · ")}{note.is_closed ? (english ? " · closed" : " · mbyllur") : ""}</div>
                {note.attachments.length > 0 && <div className="mt-1.5 flex flex-wrap gap-1.5">{note.attachments.map((attachment) => <AttachmentThumb english={english} key={attachment.id} attachment={attachment} />)}</div>}
              </td>
              <td className={`${td} whitespace-pre-wrap break-words`}><NoteTextCell english={english} key={`${note.id}:answer:${note.answer || ""}`} note={note} field="answer" onChanged={onChanged} /></td>
              <td className={td}><AssignmentCell english={english} key={`${note.id}:owner:${note.assignee_user_id || ""}`} note={note} field="assignee_user_id" people={people} users={users} onChanged={onChanged} /></td>
              <td className={`${td} tabular-nums`}><AssignmentCell english={english} key={`${note.id}:due:${note.due_date || ""}`} note={note} field="due_date" people={people} users={users} onChanged={onChanged} /></td>
              <td className={`${td} p-1.5`}>
                {note.task_status && note.task_ids.length === 1 ? <select aria-label={t("Statusi i detyrës")} disabled={busyId === note.id}
                    className={`h-8 w-full rounded-md border border-slate-600 px-1.5 text-xs font-bold ${STATUS_STYLE[note.task_status].cell}`}
                    value={note.task_status} onChange={(event) => void setTaskStatus(note, event.target.value as MeetingNoteTaskStatus)}>
                    {[...new Set([note.task_status, ...PICKABLE_STATUSES])].map((status) => <option key={status} value={status}>{STATUS_STYLE[status].label}</option>)}
                  </select>
                  : note.task_status ? <span className={`inline-block rounded-md border border-slate-600 px-2 py-1 text-xs font-bold ${STATUS_STYLE[note.task_status].cell}`}>{STATUS_STYLE[note.task_status].label} · {note.task_ids.length} {english ? "tasks" : "det."}</span>
                  : note.ga_note_id ? <Link href="/ga-ka-notes" className="text-xs underline">{t("Në PX Notes – krijo detyrën")}</Link>
                  : <Button size="sm" variant="outline" className="h-7 text-xs" disabled={busyId === note.id} onClick={() => void sendToPx(note)}>{t("Dërgo në PX")}</Button>}
              </td>
              <td className={`${td} p-1 text-center`}>
                <div className="flex items-center justify-center gap-0.5">
                  <Button type="button" size="icon-sm" variant="ghost" aria-label={t("Edito shënimin")} disabled={busyId === note.id} onClick={() => setEditing(note)}><Pencil aria-hidden="true" /></Button>
                  {onRemoved && <Button type="button" size="icon-sm" variant="ghost" className="text-destructive hover:text-destructive" aria-label={t("Fshi shënimin")} title={t("Fshi shënimin")} disabled={busyId !== null} onClick={() => void deleteNote(note)}><Trash2 aria-hidden="true" /></Button>}
                </div>
              </td>
            </tr>
          })}
        </tbody>
      </table>
    </div>
    {editing && <NoteEditDialog english={english} note={editing} users={users} onClose={() => setEditing(null)}
      onSaved={(note) => { onChanged(note); setEditing(null) }}
      onDeleted={(id) => { onRemoved?.(id); setEditing(null) }} />}
  </>
}

export function NoteEditDialog({ note, users, onClose, onSaved, onDeleted, english = false }: {
  english?: boolean
  note: MeetingNote; users: Map<string, LookupUser>; onClose: () => void; onSaved: (note: MeetingNote) => void; onDeleted: (id: string) => void
}) {
  const t = meetingTranslator(english)
  const { apiFetch } = useAuth()
  const [content, setContent] = React.useState(note.content)
  const [kind, setKind] = React.useState(note.kind)
  const [reference, setReference] = React.useState(note.reference || "")
  const [answer, setAnswer] = React.useState(note.answer || "")
  const [assignee, setAssignee] = React.useState(note.assignee_user_id || "")
  const [due, setDue] = React.useState(note.due_date || "")
  const [closed, setClosed] = React.useState(note.is_closed)
  const [attachments, setAttachments] = React.useState(note.attachments)
  const [files, setFiles] = React.useState<File[]>([])
  const [saving, setSaving] = React.useState(false)
  const people = React.useMemo(() => [...users.values()].sort((a, b) => userName(users, a.id).localeCompare(userName(users, b.id), "sq")), [users])

  const save = async () => {
    if (!content.trim()) return
    setSaving(true)
    try {
      const response = await apiFetch(`/meeting-notes/${note.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, kind, reference, answer, assignee_user_id: assignee || null, due_date: due || null, is_closed: closed }),
      })
      if (!response.ok) throw new Error(await readError(response, t("Shënimi nuk u ruajt.")))
      let updated = (await response.json()) as MeetingNote
      if (files.length) {
        const form = new FormData()
        files.forEach((file) => form.append("files", file))
        const upload = await apiFetch(`/meeting-notes/${note.id}/attachments`, { method: "POST", body: form })
        if (!upload.ok) throw new Error(await readError(upload, t("Screenshot-i nuk u ngarkua.")))
        updated = (await upload.json()) as MeetingNote
      }
      onSaved(updated)
    } catch (error) { toast.error(error instanceof Error ? error.message : String(error)) }
    finally { setSaving(false) }
  }
  const removeAttachment = async (id: string) => {
    const response = await apiFetch(`/meeting-notes/attachments/${id}`, { method: "DELETE" })
    if (!response.ok) { toast.error(t("Skedari nuk u fshi.")); return }
    const next = attachments.filter((item) => item.id !== id)
    setAttachments(next)
    onSaved({ ...note, attachments: next })
  }
  const remove = async () => {
    if (!window.confirm(t("Fshi këtë shënim nga takimi?"))) return
    const response = await apiFetch(`/meeting-notes/${note.id}`, { method: "DELETE" })
    if (!response.ok) { toast.error(await readError(response, t("Shënimi nuk u fshi."))); return }
    onDeleted(note.id)
  }
  const onPaste = (event: React.ClipboardEvent) => {
    const pasted = [...event.clipboardData.files].filter((file) => file.type.startsWith("image/"))
    if (pasted.length) { event.preventDefault(); setFiles((current) => [...current, ...pasted]) }
  }

  return <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
    <DialogContent className="max-w-2xl" onPaste={onPaste}>
      <DialogHeader><DialogTitle>{t("Edito shënimin")}</DialogTitle></DialogHeader>
      <div className="grid gap-3">
        <div className="grid gap-1.5"><Label htmlFor="mn-content">{t("Shënimi / pyetja")}</Label><Textarea id="mn-content" value={content} onChange={(e) => setContent(e.target.value)} rows={3} /></div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="grid gap-1.5"><Label htmlFor="mn-kind">{t("Lloji")}</Label>
            <select id="mn-kind" className={selectClass} value={kind} onChange={(e) => setKind(e.target.value as MeetingNote["kind"])}><option value="NOTE">{t("Shënim")}</option><option value="QUESTION">{t("Pyetje")}</option></select></div>
          <div className="grid gap-1.5"><Label htmlFor="mn-ref">{t("Rasti / referenca")}</Label><Input id="mn-ref" value={reference} onChange={(e) => setReference(e.target.value)} placeholder={t("p.sh. Ticket #4821")} /></div>
        </div>
        <div className="grid gap-1.5"><Label htmlFor="mn-answer">{t("Përshkrimi / PËRGJIGJA")}</Label><Textarea id="mn-answer" value={answer} onChange={(e) => setAnswer(e.target.value)} rows={2} /></div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="grid gap-1.5"><Label htmlFor="mn-who">{t("Kush")}</Label>
            <select id="mn-who" className={selectClass} value={assignee} onChange={(e) => setAssignee(e.target.value)}>
              <option value="">—</option>{people.map((person) => <option key={person.id} value={person.id}>{userName(users, person.id)}</option>)}
            </select></div>
          <div className="grid gap-1.5"><Label htmlFor="mn-due">{t("Afati")}</Label><Input id="mn-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} /></div>
        </div>
        <div className="grid gap-1.5">
          <Label>Screenshots</Label>
          <div className="flex flex-wrap items-center gap-2">
            {attachments.map((attachment) => <AttachmentThumb english={english} key={attachment.id} attachment={attachment} onDelete={() => void removeAttachment(attachment.id)} />)}
            {files.map((file, index) => <PendingThumb english={english} key={`${file.name}-${index}`} file={file} onRemove={() => setFiles((current) => current.filter((_, i) => i !== index))} />)}
            <label className="inline-flex h-9 cursor-pointer items-center rounded-md border px-3 text-sm hover:bg-muted">
              {t("Shto foto")}<input type="file" accept="image/*" multiple className="sr-only" onChange={(e) => { setFiles((current) => [...current, ...(e.target.files ? [...e.target.files] : [])]); e.target.value = "" }} />
            </label>
            <span className="text-xs text-muted-foreground">{t("ose ngjit me Ctrl+V")}</span>
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={closed} onChange={(e) => setClosed(e.target.checked)} />{t("Mbyll shënimin (nuk kalon më te seanca e radhës)")}</label>
        {note.ga_note_id && <p className="text-xs text-muted-foreground">{t("Ky shënim është dërguar në PX Notes. Ndryshimet këtu nuk e ndryshojnë shënimin PX.")}</p>}
      </div>
      <DialogFooter className="gap-2 sm:justify-between">
        <Button variant="ghost" className="text-destructive" onClick={() => void remove()}>{t("Fshi")}</Button>
        <div className="flex gap-2"><Button variant="outline" onClick={onClose}>{t("Anulo")}</Button><Button disabled={saving || !content.trim()} onClick={() => void save()}>{saving ? t("Duke ruajtur…") : t("Ruaj")}</Button></div>
      </DialogFooter>
    </DialogContent>
  </Dialog>
}
