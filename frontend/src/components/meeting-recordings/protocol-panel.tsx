"use client"

import * as React from "react"
import { useAuth } from "@/lib/auth"
import { recordingJson } from "@/lib/recording-outbox"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"

type Language = "en" | "de"
type Protocol = { language: Language; status: "QUEUED" | "GENERATING" | "READY" | "FAILED"; error: string | null }

export function RecordingProtocolPanel({ recordingId, canManage, configured }: {
  recordingId: string; canManage: boolean; configured: boolean
}) {
  const { apiFetch } = useAuth()
  const [language, setLanguage] = React.useState<Language>("en")
  const [protocols, setProtocols] = React.useState<Protocol[]>([])
  const [loaded, setLoaded] = React.useState(false)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState("")
  const autoDownload = React.useRef<Language | null>(null)
  const downloading = React.useRef(false)
  const base = `/meeting-recordings/${recordingId}/protocols`
  const current = protocols.find(p => p.language === language)
  const processing = current?.status === "QUEUED" || current?.status === "GENERATING"
  const anyProcessing = protocols.some(p => p.status === "QUEUED" || p.status === "GENERATING")

  const load = React.useCallback(async () => {
    const result = await recordingJson(await apiFetch(base, { cache: "no-store" })) as { protocols: Protocol[] }
    setProtocols(result.protocols)
    setLoaded(true)
  }, [apiFetch, base])

  React.useEffect(() => {
    let active = true
    const refresh = async () => {
      try { if (active) await load() }
      catch (e) { if (active) setError(e instanceof Error ? e.message : "Ngarkimi dështoi.") }
    }
    void refresh()
    return () => { active = false }
  }, [load])

  React.useEffect(() => {
    if (!anyProcessing) return
    const timer = window.setInterval(() => void load().catch(e => setError(e instanceof Error ? e.message : "Ngarkimi dështoi.")), 4000)
    return () => window.clearInterval(timer)
  }, [anyProcessing, load])

  const download = React.useCallback(async (selected: Language) => {
    const response = await apiFetch(`${base}/${selected}/download`, { cache: "no-store" })
    if (!response.ok) { await recordingJson(response); return }
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = `PRIMEX-Protocol-${recordingId}-${selected.toUpperCase()}.docx`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 60000)
  }, [apiFetch, base, recordingId])

  React.useEffect(() => {
    if (!autoDownload.current || downloading.current) return
    const requested = protocols.find(p => p.language === autoDownload.current)
    if (requested?.status === "FAILED") { autoDownload.current = null; return }
    if (requested?.status !== "READY") return
    downloading.current = true
    const selected = autoDownload.current
    autoDownload.current = null
    void download(selected).catch(e => setError(e instanceof Error ? e.message : "Shkarkimi dështoi."))
      .finally(() => { downloading.current = false })
  }, [protocols, download])

  const start = async () => {
    setBusy(true); setError("")
    try {
      if (current?.status === "READY") await download(language)
      else {
        const result = await recordingJson(await apiFetch(base, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ language }),
        })) as Protocol
        autoDownload.current = language
        setProtocols(previous => [...previous.filter(p => p.language !== language), result])
      }
    } catch (e) { setError(e instanceof Error ? e.message : "Gjenerimi dështoi.") }
    finally { setBusy(false) }
  }

  return <section aria-label="Protokolli i takimit" className="space-y-3 rounded-md border p-4">
    <h3 className="font-semibold">Protokolli i takimit</h3>
    <p className="text-sm text-muted-foreground">Shkarko protokollin sipas template-it PRIMEX. Ndryshimet i bën direkt në Word-in e shkarkuar.</p>
    <div className="flex flex-wrap items-end gap-3">
      <div className="space-y-1"><Label htmlFor="protocol-language">Gjuha e protokollit</Label>
        <select id="protocol-language" value={language} disabled={busy} onChange={e => { setLanguage(e.target.value as Language); setError("") }} className="h-9 w-44 rounded-md border border-input bg-background px-3 text-sm">
          <option value="en">English</option><option value="de">Deutsch</option>
        </select>
      </div>
      {(canManage || current?.status === "READY") && <Button variant="outline"
        disabled={!loaded || busy || processing || (current?.status !== "READY" && !configured)} onClick={() => void start()}>
        {busy ? "Duke përpunuar…" : processing ? "Duke gjeneruar…" : current?.status === "READY" ? "Shkarko Word" : current?.status === "FAILED" ? "Riprovo dhe shkarko Word" : "Gjenero dhe shkarko Word"}
      </Button>}
    </div>
    {processing && <p role="status" className="text-sm">Protokolli po përgatitet. Shkarkimi nis kur të jetë gati. Nëse mbyll faqen, mund ta shkarkosh kur të kthehesh.</p>}
    {current?.status === "READY" && <p role="status" className="text-sm text-muted-foreground">Protokolli është gati. Shkarkimet e përsëritura përdorin dokumentin e ruajtur.</p>}
    {!canManage && !current && <p className="text-sm text-muted-foreground">Autori i regjistrimit mund ta gjenerojë protokollin.</p>}
    {(error || current?.error) && <p role="alert" className="text-sm text-destructive">{error || current?.error}</p>}
  </section>
}
