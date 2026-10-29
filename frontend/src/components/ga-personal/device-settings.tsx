"use client"

import * as React from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

type Device = { id: string; name: string; device_id: string | null; created_at: string; last_seen_at: string | null; revoked_at: string | null }
type CreatedDevice = Device & { code: string }
type Props = { request: <T,>(path: string, init?: RequestInit) => Promise<T> }

export function DeviceSettingsPanel({ request }: Props) {
  const [devices, setDevices] = React.useState<Device[] | null>(null)
  const [name, setName] = React.useState("")
  const [created, setCreated] = React.useState<CreatedDevice | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState("")
  React.useEffect(() => {
    let active = true
    request<Device[]>("/devices").then((rows) => { if (active) setDevices(rows) })
      .catch((e) => { if (active) setError(e instanceof Error ? e.message : "Pajisjet nuk u lexuan.") })
    return () => { active = false }
  }, [request])

  async function create(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(""); setCreated(null)
    try {
      const result = await request<CreatedDevice>("/devices", { method: "POST", body: JSON.stringify({ name: name.trim() }) })
      setCreated(result); setName("")
      const { code: _code, ...device } = result
      setDevices((rows) => [device, ...(rows || [])])
    } catch (e) { setError(e instanceof Error ? e.message : "Kodi nuk u krijua.") }
    finally { setBusy(false) }
  }

  async function revoke(device: Device) {
    setBusy(true); setError("")
    try {
      const result = await request<Device>(`/devices/${device.id}/revoke`, { method: "POST" })
      setDevices((rows) => rows?.map((row) => row.id === result.id ? result : row) || [])
      if (created?.id === result.id) setCreated(null)
    } catch (e) { setError(e instanceof Error ? e.message : "Lidhja nuk u çaktivizua.") }
    finally { setBusy(false) }
  }

  return <section className="space-y-4 rounded-xl border p-5">
    <div><h2 className="font-semibold">Kujtesa · Aplikacioni lokal</h2><p className="mt-1 text-sm text-muted-foreground">Krijo kodin për tabletin dhe vendose te Kujtesa → Cilësimet → Lidhja me Primeflow.</p></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <label className="block space-y-1 text-sm"><span>Adresa e Primeflow</span><Input readOnly value="https://primeflow.primexeu.com" /></label>
    <p className="text-xs text-muted-foreground">Detyrat pa orar shfaqen pa alarm. Orarin caktoje te detyra në GA PERSONAL.</p>
    <form onSubmit={create} className="space-y-3">
      <label className="block space-y-1 text-sm"><span>Emri i pajisjes</span><Input required maxLength={100} placeholder="Tableti i familjes" value={name} onChange={(event) => setName(event.target.value)} /></label>
      <Button type="submit" disabled={busy || !name.trim() || devices === null}>Krijo kod pajisjeje</Button>
    </form>
    {created && <div className="space-y-3 rounded-lg border bg-muted/40 p-3">
      <label className="block space-y-1 text-sm"><span>Kodi i pajisjes</span><Input className="font-mono text-xs" readOnly autoComplete="off" value={created.code} onFocus={(event) => event.currentTarget.select()} /></label>
      <p className="text-xs text-muted-foreground">Kodi shfaqet vetëm tani. Kopjoje në tablet; në lidhjen e parë ai lidhet me ID-në e asaj pajisjeje.</p>
      <Button variant="outline" size="sm" onClick={() => setCreated(null)}>E ruajta kodin</Button>
    </div>}
    {!devices ? <p className="text-sm text-muted-foreground">Duke lexuar pajisjet…</p> : devices.length === 0 ? <p className="text-sm text-muted-foreground">Ende nuk ka pajisje të lidhura.</p> : <ul className="space-y-3">{devices.map((device) => <li key={device.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3">
      <div className="min-w-0 space-y-1"><p className="break-words text-sm font-medium">{device.name}</p><p className="break-all text-xs text-muted-foreground">{device.revoked_at ? "E çaktivizuar" : device.device_id ? `E lidhur · ${device.device_id}` : "Pret lidhjen e parë"}</p>{device.last_seen_at && <p className="text-xs text-muted-foreground">Lidhja e fundit: {new Date(device.last_seen_at).toLocaleString("sq")}</p>}</div>
      {!device.revoked_at && <Button variant="outline" size="sm" disabled={busy} onClick={() => void revoke(device)}>Çaktivizo lidhjen</Button>}
    </li>)}</ul>}
  </section>
}
