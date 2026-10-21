"use client"

import * as React from "react"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { STATUS_LABELS, clock, json, type GaParticipant, type HostStatus } from "@/lib/mira"

export function SettingsTab({ canManage, status, onChange }: { canManage: boolean; status: HostStatus | null; onChange: (s: HostStatus) => void }) {
  const { apiFetch } = useAuth()
  const [form, setForm] = React.useState<HostStatus | null>(status)
  const [until, setUntil] = React.useState("")
  const [busy, setBusy] = React.useState(false)

  if (!form || !status) return <p className="py-10 text-sm text-muted-foreground">Duke u ngarkuar…</p>

  const call = async (path: string, init: RequestInit, done: string) => {
    setBusy(true)
    try {
      const next = await json<HostStatus>(await apiFetch(path, { ...init, headers: { "Content-Type": "application/json" } }))
      onChange({ ...status, ...next })
      toast.success(done)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const people = form.ga_participants.length ? form.ga_participants : [{ name: "" }]
  const setPerson = (index: number, patch: Partial<GaParticipant>) =>
    setForm({ ...form, ga_participants: people.map((p, i) => (i === index ? { ...p, ...patch } : p)) })

  const save = () => call("/mira/settings", {
    method: "PUT",
    body: JSON.stringify({
      ga_participants: people.filter((p) => p.name.trim()).map((p) => ({ name: p.name.trim(), fallback: p.fallback?.trim() || null })),
      protocol_text: form.protocol_text, target_minutes_per_person: form.target_minutes_per_person,
      knowledge_char_budget: form.knowledge_char_budget,
    }),
  }, "Cilësimet u ruajtën.")

  return (
    <div className="max-w-3xl py-5">
      <section className="rounded-lg border p-4">
        <h3 className="text-sm font-semibold">Mira si mbajtëse e 1H (test)</h3>
        {!status.configured && (
          <p className="mt-1 text-sm text-muted-foreground">
            Boti “Mira Host” nuk është konfiguruar në server (MIRA_HOST_ENABLED dhe MIRA_HOST_BOT_TOKEN).
          </p>
        )}
        <p className="mt-1 text-sm">
          {status.enabled ? <>Aktive deri në <strong>{clock(status.enabled_until)}</strong> · slotet {status.slots.join(", ")}</> : "Joaktive. Regjistrimi i heshtur vazhdon si më parë."}
        </p>
        {status.live && (
          <p className="mt-1 text-sm text-muted-foreground">
            Tani: 1H {status.live.slot} · {STATUS_LABELS[status.live.status]} · {status.live.people.map((p) => p.initials).join(" → ") || "faza GA"}
          </p>
        )}
        {canManage && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {status.enabled ? (
              <Button size="sm" variant="outline" disabled={busy} onClick={() => call("/mira/host", { method: "POST", body: JSON.stringify({ enabled: false }) }, "Mira u ndal.")}>
                Ndalo
              </Button>
            ) : (
              <>
                <Input aria-label="Deri në orë" placeholder="deri në orë, p.sh. 12:00" value={until} maxLength={5}
                  onChange={(e) => setUntil(e.target.value)} className="h-9 w-48" />
                <Button size="sm" disabled={busy || !status.configured}
                  onClick={() => call("/mira/host", { method: "POST", body: JSON.stringify({ enabled: true, until: until.trim() || null }) }, "Mira i mban takimet 1H.")}>
                  Nis
                </Button>
              </>
            )}
            <span className="text-xs text-muted-foreground">Njëlloj si <code>/mira mbaj-takimet</code> dhe <code>/mira ndalo</code> në Discord.</span>
          </div>
        )}
      </section>

      <fieldset disabled={!canManage || busy} className="mt-8 space-y-6">
        <div>
          <Label className="text-sm font-semibold">Ekipi GA në 1H</Label>
          <p className="mb-2 mt-0.5 text-xs text-muted-foreground">
            Thirren 2 minuta para çdo 1H. Zëvendësimi thirret kur personi mungon sot ose s’është kyçur në fillim të slotit.
          </p>
          <ul className="space-y-2">
            {people.map((person, index) => (
              <li key={index} className="flex flex-wrap items-center gap-2">
                <Input aria-label="Emri" placeholder="Emri i plotë" value={person.name} className="h-9 w-56"
                  onChange={(e) => setPerson(index, { name: e.target.value })} />
                <span className="text-xs text-muted-foreground">nëse mungon</span>
                <Input aria-label="Zëvendësimi" placeholder="(opsionale)" value={person.fallback ?? ""} className="h-9 w-56"
                  onChange={(e) => setPerson(index, { fallback: e.target.value })} />
                <Button size="sm" variant="ghost" className="text-muted-foreground"
                  onClick={() => setForm({ ...form, ga_participants: people.filter((_, i) => i !== index) })}>Hiq</Button>
              </li>
            ))}
          </ul>
          <Button size="sm" variant="ghost" className="mt-1" onClick={() => setForm({ ...form, ga_participants: [...people, { name: "" }] })}>
            + Shto person
          </Button>
        </div>

        <div>
          <Label htmlFor="protocol" className="text-sm font-semibold">Protokolli për stafin</Label>
          <p className="mb-2 mt-0.5 text-xs text-muted-foreground">Dërgohet 5 minuta para 1H (përveç 10:00) dhe Mira e ndjek me secilin.</p>
          <Textarea id="protocol" rows={5} value={form.protocol_text} onChange={(e) => setForm({ ...form, protocol_text: e.target.value })} />
        </div>

        <div className="flex flex-wrap gap-6">
          <div>
            <Label htmlFor="minutes" className="text-sm font-semibold">Minuta për person</Label>
            <Input id="minutes" type="number" min={1} max={30} className="mt-1 h-9 w-28" value={form.target_minutes_per_person}
              onChange={(e) => setForm({ ...form, target_minutes_per_person: Number(e.target.value) || 1 })} />
          </div>
          <div>
            <Label htmlFor="budget" className="text-sm font-semibold">Knowledge në kontekst (shenja)</Label>
            <Input id="budget" type="number" min={2000} max={120000} step={1000} className="mt-1 h-9 w-36" value={form.knowledge_char_budget}
              onChange={(e) => setForm({ ...form, knowledge_char_budget: Number(e.target.value) || 2000 })} />
          </div>
        </div>
        {canManage && <Button onClick={save}>Ruaj cilësimet</Button>}
      </fieldset>
    </div>
  )
}
