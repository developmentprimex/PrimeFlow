"use client"

import * as React from "react"
import { Button } from "@/components/ui/button"

type Preview = {
  hash: string; applied?: boolean; counts: Record<"create" | "update" | "existing", number>; rotation_will_change: boolean
  tasks: { source_id: string; title: string; action: "create" | "update" | "existing"; definition: { due_time: string | null; steps: string[]; frequency: string } }[]
}
type Request = <T>(path: string, init?: RequestInit) => Promise<T>

export function FamilyPack({ request, onSaved }: { request: Request; onSaved: () => Promise<void> }) {
  const [preview, setPreview] = React.useState<Preview | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState("")
  const [saved, setSaved] = React.useState(false)
  async function review() {
    setBusy(true); setError(""); setSaved(false)
    try { setPreview(await request<Preview>("/discord/family-pack")) }
    catch (e) { setError(e instanceof Error ? e.message : "Shtesat nuk u lexuan.") }
    finally { setBusy(false) }
  }
  async function apply() {
    if (!preview) return
    setBusy(true); setError("")
    try {
      await request<Preview>("/discord/family-pack", { method: "POST", body: JSON.stringify({ expected_hash: preview.hash }) })
      setSaved(true); setPreview(null); await onSaved()
    } catch (e) { setError(e instanceof Error ? e.message : "Shtesat nuk u ruajtën.") }
    finally { setBusy(false) }
  }
  const labels = { create: "Shtohet", update: "Përditësohet", existing: "Ruhet modeli ekzistues" }
  return <div className="space-y-3 border-t pt-4">
    <p className="font-medium">Rutinat shtesë të familjes</p>
    <p className="text-sm text-muted-foreground">Orari i Nalës, mëngjesi, dhomat, aktivitetet, ngrohja dhe kujdesi periodik. Detyrat ruhen dhe ndryshohen nga PrimeFlow. Ndryshimet tuaja dhe historiku ruhen.</p>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {saved && <p role="status" className="text-sm">Rutinat u ruajtën në PrimeFlow.</p>}
    <Button type="button" variant="outline" disabled={busy} onClick={review}>Shiko shtesat para importimit</Button>
    {preview && <div className="space-y-3">
      <p className="text-sm">Shtohen {preview.counts.create} · Përditësohen {preview.counts.update} · Ruhen {preview.counts.existing}</p>
      <p className="text-xs text-muted-foreground">{preview.rotation_will_change ? "Vendoset radha e Nalës nga rutina e re." : "Ruhet radha ekzistuese e Nalës."} Shënimi i Babit përfshihet në agjendë. Importi aktivizon krijimin e detyrave; dërgimi në Discord ndjek cilësimet e lidhjes.</p>
      <div className="max-h-80 space-y-2 overflow-y-auto rounded-md border p-3">
        {preview.tasks.map((task) => <details key={task.source_id} className="text-sm">
          <summary className="cursor-pointer">{task.title} · {task.definition.due_time?.slice(0, 5) || "Pa orë"} · {labels[task.action]}</summary>
          <ul className="mt-2 list-disc pl-5 text-muted-foreground">{task.definition.steps.map((step, index) => <li key={index}>{step}</li>)}</ul>
        </details>)}
      </div>
      <Button type="button" disabled={busy} onClick={apply}>{busy ? "Duke ruajtur…" : "Importo rutinat në PrimeFlow"}</Button>
    </div>}
  </div>
}
