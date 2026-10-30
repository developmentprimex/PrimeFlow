"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { dayLabel, type GaOccurrence, type GaTemplate, localTime, type Workspace } from "@/lib/ga-personal"

export function WeekTimeDialog({ rows, templates, workspace, busy, error, onClose, onSave }: {
  rows: GaOccurrence[]; templates: GaTemplate[]; workspace: Workspace; busy: boolean; error: string
  onClose: () => void; onSave: (rows: GaOccurrence[], time: string | null, future: boolean) => void
}) {
  const times = Array.from(new Set(rows.map((r) => localTime(r.due_at))))
  const [time, setTime] = useState(times.length === 1 ? times[0] : "")
  const [selected, setSelected] = useState(rows.map((r) => r.id))
  const [future, setFuture] = useState(false)
  const chosen = rows.filter((r) => selected.includes(r.id))
  const canChangeFuture = chosen.length > 0 && chosen.every((row) => {
    const template = templates.find((t) => t.id === row.template_id)
    return template?.can_manage && !template.archived && template.definition.assignment === "fixed" && template.definition.frequency !== "once"
  })
  return <Dialog open onOpenChange={(open) => { if (!open && !busy) onClose() }}>
    <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg"><DialogHeader>
      <DialogTitle>Cakto orën</DialogTitle>
      <DialogDescription>Zgjidh personat dhe datat ku do të vlejë ora. Kryerjet e përfunduara ruhen.</DialogDescription>
    </DialogHeader>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); onSave(chosen, time || null, future && canChangeFuture) }}>
        {error && <p role="alert" className="rounded-md bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
        <label className="block space-y-2 text-sm"><span>Ora e detyrës</span><Input type="time" autoFocus value={time} disabled={busy} onChange={(e) => setTime(e.target.value)} /></label>
        <p className="text-xs text-muted-foreground">Europe/Belgrade. Lëre bosh për të hequr orën.</p>
        <fieldset disabled={busy} className="space-y-2"><legend className="mb-2 text-sm font-medium">Personat dhe datat</legend>
          <div className="max-h-60 space-y-2 overflow-y-auto rounded-lg border p-3">{[...rows].sort((a, b) => a.local_date.localeCompare(b.local_date)).map((row) => <label key={row.id} className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" checked={selected.includes(row.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, row.id] : selected.filter((id) => id !== row.id))} />
            <span className="min-w-0">{dayLabel(row.local_date, true)} · {row.snapshot.assignees.map((key) => workspace.members.find((m) => m.person_key === key)?.name || key).join(", ")}<span className="block text-xs text-muted-foreground">{row.snapshot.short_code || row.snapshot.title} · {localTime(row.due_at) || "Pa orar"}</span></span>
          </label>)}</div>
        </fieldset>
        {canChangeFuture && <label className="flex items-start gap-2 rounded-lg border p-3 text-sm"><input type="checkbox" className="mt-1" disabled={busy} checked={future} onChange={(e) => setFuture(e.target.checked)} /><span>Edhe përsëritjet e ardhshme<span className="mt-1 block text-xs text-muted-foreground">Ora e modelit vlen për të gjithë përgjegjësit e tij. Detyrat e tjera të krijuara më herët ruhen.</span></span></label>}
        <div className="flex flex-wrap justify-end gap-2 border-t pt-4"><Button type="button" variant="outline" disabled={busy} onClick={onClose}>Anulo</Button><Button type="submit" disabled={busy || !chosen.length}>{busy ? "Duke ruajtur…" : "Ruaj orën"}</Button></div>
      </form>
    </DialogContent>
  </Dialog>
}
