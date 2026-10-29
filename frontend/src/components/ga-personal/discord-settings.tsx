"use client"

import * as React from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

type Settings = { enabled: boolean; configured: boolean; connected: boolean; version: number; guild_id: string; channel_id: string; user_ids: Record<string, string>; delivery_counts?: Record<string, number> }
type Request = <T>(path: string, init?: RequestInit) => Promise<T>

export function DiscordSettingsPanel({ request, onSaved }: { request: Request; onSaved: () => Promise<void> }) {
  const [value, setValue] = React.useState<Settings | null>(null)
  const [error, setError] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  React.useEffect(() => {
    let active = true
    request<Settings>("/discord/settings").then((data) => { if (active && typeof data.enabled === "boolean") setValue(data) }).catch((e) => { if (active) setError(e.message) })
    return () => { active = false }
  }, [request])
  async function save(event: React.FormEvent) {
    event.preventDefault(); if (!value) return
    setBusy(true); setError("")
    try {
      const saved = await request<Settings>("/discord/settings", { method: "PUT", body: JSON.stringify({
        enabled: value.enabled, guild_id: value.guild_id.trim(), channel_id: value.channel_id.trim(),
        user_ids: Object.fromEntries(Object.entries(value.user_ids).map(([p, id]) => [p, id.trim()])), expected_version: value.version,
      }) })
      setValue(saved); await onSaved()
    } catch (e) { setError(e instanceof Error ? e.message : "Cilësimet nuk u ruajtën.") }
    finally { setBusy(false) }
  }
  return <section className="space-y-4 rounded-xl border p-5"><div><h2 className="font-semibold">Kujtesa · Discord</h2><p className="mt-1 text-sm text-muted-foreground">5 minuta para, në orar dhe 5 minuta pas nëse detyra ende është e hapur.</p></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {!value ? <p className="text-sm text-muted-foreground">Duke lexuar konfigurimin…</p> : <form className="space-y-4" onSubmit={save}>
      <p className="text-sm">Boti: {value.connected ? "I lidhur" : "Jashtë linje"} · Lidhja në server: {value.configured ? "E konfiguruar" : "Pret konfigurim"}</p>
      <label className="block space-y-1 text-sm"><span>Discord Server ID</span><Input value={value.guild_id} inputMode="numeric" onChange={(e) => setValue({ ...value, guild_id: e.target.value })} /></label>
      <label className="block space-y-1 text-sm"><span>Kanali privat i familjes · Channel ID</span><Input value={value.channel_id} inputMode="numeric" onChange={(e) => setValue({ ...value, channel_id: e.target.value })} /></label>
      {[["rrita", "Rrita"], ["mrika", "Mrika"], ["gane", "Gane"]].map(([person, name]) => <label key={person} className="block space-y-1 text-sm"><span>{name} · Discord User ID</span><Input value={value.user_ids[person] || ""} inputMode="numeric" placeholder="Mund të shtohet më vonë" onChange={(e) => setValue({ ...value, user_ids: { ...value.user_ids, [person]: e.target.value } })} /></label>)}
      <p className="text-xs text-muted-foreground">Kujtesat personale të Lirzës i shkojnë Ganës. Pa ID, mesazhi personal pret konfigurimin dhe nuk kalon në kanal.</p>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={value.enabled} disabled={!value.configured} onChange={(e) => setValue({ ...value, enabled: e.target.checked })} /><span>Lejo Kujtesën të lexojë detyrat për njoftim dhe të ruajë konfirmimet nga Discord.</span></label>
      {!!value.delivery_counts && <p className="text-xs text-muted-foreground">Të dërguara: {value.delivery_counts.sent || 0} · Të pasigurta: {value.delivery_counts.uncertain || 0} · Dështime: {value.delivery_counts.failed || 0}</p>}
      <p className="text-xs text-muted-foreground">Dërgimi kërkon edhe aktivizimin te boti. Detyrat pa orë nuk dërgojnë kujtesa.</p>
      <Button type="submit" disabled={busy}>{busy ? "Duke ruajtur…" : "Ruaj lidhjen me Kujtesën"}</Button>
    </form>}
  </section>
}
