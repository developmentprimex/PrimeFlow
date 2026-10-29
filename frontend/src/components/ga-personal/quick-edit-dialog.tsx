"use client"

import * as React from "react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { GaOccurrence, GaTemplate, localTime, PersonKey, Workspace } from "@/lib/ga-personal"

export type QuickEditValues = { local_date: string; due_time: string | null; assignees: PersonKey[]; apply_to_future: boolean; discord_destination: "dm" | "channel" | "off" }

export function QuickEditDialog({ row, template, workspace, busy, error, onClose, onSave, onEditTemplate }: {
  row: GaOccurrence | null; template?: GaTemplate; workspace: Workspace | null; busy: boolean; error: string
  onClose: () => void; onSave: (values: QuickEditValues) => void; onEditTemplate: (row: GaTemplate) => void
}) {
  const [day, setDay] = React.useState("")
  const [time, setTime] = React.useState("")
  const [owners, setOwners] = React.useState<PersonKey[]>([])
  const [future, setFuture] = React.useState(false)
  const [destination, setDestination] = React.useState<QuickEditValues["discord_destination"]>("dm")
  React.useEffect(() => {
    if (row) { setDay(row.local_date); setTime(localTime(row.due_at)); setOwners(row.snapshot.assignees); setFuture(false); setDestination(row.snapshot.discord_destination || "dm") }
  }, [row])
  return <Dialog open={!!row && !!workspace} onOpenChange={(open) => { if (!open) onClose() }}>
    <DialogContent className="sm:max-w-lg"><DialogHeader><DialogTitle>Ndrysho detyrën</DialogTitle><DialogDescription>{row?.snapshot.title}</DialogDescription></DialogHeader>
      <form className="space-y-5" onSubmit={(event) => { event.preventDefault(); onSave({ local_date: day, due_time: time || null, assignees: owners, apply_to_future: future, discord_destination: destination }) }}>
        {error && <p role="alert" className="rounded-md bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
        <div className="grid grid-cols-2 gap-3">
          <label className="space-y-2 text-sm"><span>Data e detyrës</span><Input type="date" required value={day} onChange={(e) => setDay(e.target.value)} /></label>
          <label className="space-y-2 text-sm"><span>Ora e detyrës</span><Input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></label>
        </div>
        <p className="-mt-2 text-xs text-muted-foreground">Ora sipas Europe/Belgrade. Lëre bosh nëse detyra ende nuk ka orë.</p>
        <label className="block space-y-2 text-sm"><span>Kujtesat në Discord</span><select aria-label="Kujtesat në Discord" className="w-full rounded-md border bg-background px-3 py-2" value={destination} onChange={(e) => setDestination(e.target.value as QuickEditValues["discord_destination"])}><option value="dm">Mesazh privat</option><option value="channel">Kanali i familjes</option><option value="off">Pa njoftim</option></select></label>
        {row?.snapshot.completion_mode === "shared" ? <fieldset className="space-y-2"><legend className="text-sm font-medium">Përgjegjësit e kësaj detyre</legend><div className="space-y-2">{workspace?.members.map((m) => <label key={m.person_key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={owners.includes(m.person_key)} onChange={(e) => setOwners(e.target.checked ? [...owners, m.person_key] : owners.filter((p) => p !== m.person_key))} />{m.name}</label>)}</div></fieldset>
          : <label className="block space-y-2 text-sm"><span>Përgjegjësi i detyrës</span><select aria-label="Përgjegjësi i detyrës" required className="w-full rounded-md border bg-background px-3 py-2" value={owners[0] || ""} onChange={(e) => setOwners([e.target.value as PersonKey])}>{workspace?.members.map((m) => <option key={m.person_key} value={m.person_key}>{m.name}</option>)}</select></label>}
        {template?.can_manage && template.definition.assignment === "fixed" && !template.archived && <fieldset className="space-y-2 rounded-lg border p-3"><legend className="px-1 text-sm font-medium">Ku të vlejë ndryshimi?</legend>
          <label className="flex items-center gap-2 text-sm"><input type="radio" name="quick-scope" checked={!future} onChange={() => setFuture(false)} />Vetëm këtë detyrë</label>
          <label className="flex items-center gap-2 text-sm"><input type="radio" name="quick-scope" checked={future} onChange={() => setFuture(true)} />Këtë dhe përsëritjet e ardhshme</label>
          <p className="text-xs text-muted-foreground">Historiku dhe kryerjet e tjera të krijuara më herët ruhen.</p>
        </fieldset>}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          {template?.can_manage ? <Button type="button" variant="ghost" size="sm" onClick={() => onEditTemplate(template)}>Ndrysho përsëritjen</Button> : <span />}
          <div className="flex gap-2"><Button type="button" variant="outline" onClick={onClose} disabled={busy}>Anulo</Button><Button type="submit" disabled={busy || !owners.length}>{busy ? "Duke ruajtur…" : "Ruaj ndryshimet"}</Button></div>
        </div>
      </form>
    </DialogContent>
  </Dialog>
}
