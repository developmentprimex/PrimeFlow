"use client"

import * as React from "react"
import Link from "next/link"
import { Mic, Monitor, Pause, Play, Square, Video } from "lucide-react"
import { useAuth } from "@/lib/auth"
import type { Meeting } from "@/lib/types"
import { recordingSize, recordingTime } from "@/lib/recording-types"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useRecorder } from "./recorder-provider"

export function RecorderPanel() {
  const recorder = useRecorder()
  const { apiFetch, user } = useAuth()
  const [title, setTitle] = React.useState("Regjistrim i ri")
  const [description, setDescription] = React.useState("")
  const [meetingId, setMeetingId] = React.useState("")
  const [meetings, setMeetings] = React.useState<Meeting[]>([])
  const [devices, setDevices] = React.useState<MediaDeviceInfo[]>([])
  const [device, setDevice] = React.useState("default")
  const [source, setSource] = React.useState("monitor")
  const [consent, setConsent] = React.useState(false)
  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get("meeting_id")) setMeetingId(params.get("meeting_id")!)
    if (params.get("title")) setTitle(params.get("title")!.slice(0, 200))
    void navigator.mediaDevices?.enumerateDevices().then(all => setDevices(all.filter(d => d.kind === "audioinput"))).catch(() => {})
  }, [])
  React.useEffect(() => {
    if (recorder.state === "prepared") void navigator.mediaDevices.enumerateDevices().then(all => setDevices(all.filter(d => d.kind === "audioinput"))).catch(() => {})
  }, [recorder.state])
  React.useEffect(() => {
    let active = true
    void apiFetch("/meetings?include_all_departments=true").then(async response => {
      if (!response.ok) return
      const all: Meeting[] = await response.json()
      if (active) setMeetings(all.filter(m => ["ADMIN", "MANAGER"].includes(user?.role || "") || m.created_by === user?.id || m.participant_ids?.includes(user?.id || "")))
    }).catch(() => {})
    return () => { active = false }
  }, [apiFetch, user])
  const active = ["recording", "paused", "stopping"].includes(recorder.state)
  const locked = active || recorder.busy || recorder.saving || recorder.state === "selecting" || !!recorder.manifest
  const percent = recorder.manifest?.bytes ? Math.floor(recorder.manifest.uploadedBytes / recorder.manifest.bytes * 100) : 0
  const prepare = () => { void recorder.prepare(device === "none" ? false : device === "default" ? "" : device, source, { title: title.trim(), meetingId, description }) }
  return <Card>
    <CardHeader><CardTitle className="flex items-center gap-2"><Video className="size-5" /> Regjistrim i ri</CardTitle></CardHeader>
    <CardContent className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2"><Label htmlFor="recording-title">Titulli</Label><Input id="recording-title" maxLength={200} value={title} disabled={locked} onChange={e => setTitle(e.target.value)} /></div>
        <div className="space-y-2"><Label htmlFor="recording-meeting">Takimi (opsional)</Label><select id="recording-meeting" className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={meetingId} disabled={locked} onChange={e => setMeetingId(e.target.value)}>
          <option value="">Pa takim të lidhur</option>{meetings.map(m => <option key={m.id} value={m.id}>{m.title}</option>)}
        </select></div>
        <div className="space-y-2"><Label htmlFor="recording-source">Burimi</Label><select id="recording-source" className="h-9 w-full rounded-md border bg-background px-3 text-sm" disabled={locked || recorder.state === "prepared"} value={source} onChange={e => setSource(e.target.value)}>
          <option value="monitor">Ekrani i plotë</option><option value="window">Dritare</option><option value="browser">Skedë e shfletuesit</option>
        </select></div>
        <div className="space-y-2"><Label htmlFor="recording-microphone">Mikrofoni</Label><select id="recording-microphone" className="h-9 w-full rounded-md border bg-background px-3 text-sm" disabled={locked || recorder.state === "prepared"} value={device} onChange={e => setDevice(e.target.value)}>
          <option value="default">Mikrofoni i parazgjedhur</option><option value="none">Pa mikrofon</option>{devices.filter(d => d.deviceId && d.deviceId !== "default").map((d, i) => <option key={d.deviceId} value={d.deviceId}>{d.label || `Mikrofoni ${i + 1}`}</option>)}
        </select></div>
      </div>
      <details className="text-sm">
        <summary className="w-fit cursor-pointer text-muted-foreground">Përshkrimi (opsional)</summary>
        <div className="mt-2"><Label htmlFor="recording-description" className="sr-only">Përshkrimi (opsional)</Label><Input id="recording-description" maxLength={2000} value={description} disabled={locked} onChange={e => setDescription(e.target.value)} /></div>
      </details>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={consent} disabled={locked} onChange={e => setConsent(e.target.checked)} />
        <span>Konfirmoj se kam njoftuar pjesëmarrësit dhe kam autorizim për regjistrimin.</span>
      </label>
      {recorder.state === "prepared" && !recorder.info.system && <div role="alert" className="rounded-md border border-amber-400 bg-amber-50 p-4 text-sm text-amber-950 dark:bg-amber-950 dark:text-amber-100">
        <p className="font-semibold">Audio e sistemit nuk është e disponueshme për këtë burim. Zërat e pjesëmarrësve të tjerë mund të mos regjistrohen.</p>
        <p className="mt-1">Mund të anuloni, të ndryshoni burimin ose të vazhdoni shprehimisht me hyrjet e disponueshme.</p>
      </div>}
      {(active || recorder.state === "prepared" || recorder.state === "stopped") && <div className="flex flex-wrap items-center gap-4 rounded-md bg-muted p-3 text-sm">
        <span className="font-mono text-xl tabular-nums" aria-label="Koha e regjistrimit">{recordingTime(recorder.seconds)}</span>
        <span>Burimi: {recorder.info.source}</span>
        <span><Mic className="mr-1 inline size-4" /> Mikrofon: {recorder.inputs.microphone === "on" ? "aktiv" : recorder.inputs.microphone === "muted" ? "i heshtur" : "i padisponueshëm"}</span>
        <span><Monitor className="mr-1 inline size-4" /> Audio sistemi: {recorder.inputs.system === "on" ? "aktive" : recorder.inputs.system === "muted" ? "e heshtur" : "e padisponueshme"}</span>
      </div>}
      <div className="flex flex-wrap gap-2">
        {["recording", "paused"].includes(recorder.state) && !recorder.screenSharing && <Button variant="outline" disabled={recorder.selectingScreen} onClick={() => void recorder.shareScreen(source)}><Monitor className="mr-2 size-4" />Ndaj ekranin përsëri</Button>}
        {!active && recorder.state !== "prepared" && <Button disabled={!consent || !title.trim() || locked || !recorder.available} onClick={prepare}><Monitor className="mr-2 size-4" /> Zgjidh ekranin</Button>}
        {recorder.state === "prepared" && <>
          <Button disabled={!consent || !title.trim() || recorder.busy} onClick={() => void recorder.start(title.trim(), meetingId, description)}><Play className="mr-2 size-4" />{recorder.info.system ? "Fillo regjistrimin" : "Vazhdo pa audio sistemi"}</Button>
          <Button variant="outline" disabled={recorder.busy} onClick={() => { recorder.cancel(); prepare() }}>Ndrysho burimin</Button>
          <Button variant="outline" disabled={recorder.busy} onClick={recorder.cancel}>Anulo</Button>
        </>}
        {recorder.state === "recording" && <Button variant="outline" onClick={recorder.pause}><Pause className="mr-2 size-4" /> Pauzë</Button>}
        {recorder.state === "paused" && <Button variant="outline" disabled={!!recorder.error || (recorder.manifest ? recorder.manifest.bytes - recorder.manifest.uploadedBytes >= 32 * 1024 * 1024 : false)} onClick={recorder.resume}><Play className="mr-2 size-4" /> Vazhdo</Button>}
        {active && <>
          <Button variant="destructive" disabled={recorder.state === "stopping"} onClick={recorder.stop}><Square className="mr-2 size-4" /> Ndalo</Button>
          <Button variant="outline" disabled={!recorder.info.microphone} onClick={() => recorder.toggle("microphone")}>Mikrofoni On/Off</Button>
          <Button variant="outline" disabled={!recorder.info.system} onClick={() => recorder.toggle("system")}>Audio sistemi On/Off</Button>
        </>}
      </div>
      {recorder.backpressure && <p role="alert" className="text-sm text-amber-700 dark:text-amber-300">Regjistrimi u vendos në pauzë për shkak të ngarkimit. Prisni konfirmimin e fragmenteve, pastaj klikoni Vazhdo.</p>}
      {recorder.manifest && <div className="space-y-2 text-sm" role="status">
        <p>Ngarkuar: {recordingSize(recorder.manifest.uploadedBytes)} / {recordingSize(recorder.manifest.bytes)} ({percent}%) · {recorder.manifest.acknowledged}/{recorder.manifest.count} fragmente</p>
        <progress className="w-full" aria-label="Progresi i ngarkimit" max={100} value={percent} />
        <p>{recorder.saving ? "Duke përfunduar dhe verifikuar videon në server…" : active ? "Ngarkimi vazhdon gjatë regjistrimit." : "Nuk është konfirmuar ende si i ruajtur."}</p>
        {!recorder.saving && <Button variant="outline" onClick={() => void recorder.retry()}>Riprovo ngarkimin</Button>}
        {!active && !recorder.saving && <Button variant="ghost" onClick={() => { if (window.confirm("Mbyll sesionin dhe hiq fragmentet lokale të pangarkuara?")) void recorder.discard(recorder.manifest!.id) }}>Braktis sesionin</Button>}
      </div>}
      {recorder.error && <div role="alert" className="rounded-md border border-destructive p-3 text-sm text-destructive">{recorder.error}<p className="mt-1">Nëse leja e mikrofonit u refuzua, zgjidhni “Pa mikrofon” ose ndryshoni lejet e shfletuesit. Nëse ekrani u refuzua, klikoni sërish Zgjidh ekranin.</p></div>}
      {recorder.savedId && <p role="status" className="text-sm font-semibold text-green-700 dark:text-green-300">Serveri konfirmoi ruajtjen. <Link className="underline" href={`/meeting-recordings/${recorder.savedId}`}>Hap regjistrimin</Link></p>}
      {recorder.recoveries.map(m => <div key={m.id} className="space-y-2 rounded-md border p-3 text-sm">
        <p className="font-semibold">Rikuperim: {m.title}</p>
        <p>{m.fatal || (m.stopped ? "Regjistrimi u ndal; ngarkimi mbeti i papërfunduar." : "Shfletuesi u ndërpre. Mund të rikuperohet vetëm pjesa e ruajtur lokalisht; sekondat e fundit mund të mungojnë.")}</p>
        <p>{m.acknowledged}/{m.count} fragmente të konfirmuara</p>
        <Button size="sm" variant="outline" disabled={recorder.saving || active || !m.count || !!m.fatal} onClick={() => {
          if (m.stopped || window.confirm("Konfirmoni ruajtjen vetëm të pjesës së disponueshme të regjistrimit të ndërprerë?")) void recorder.retry(m.id, !m.stopped)
        }}>{m.stopped ? "Riprovo ngarkimin" : "Rikupero pjesën e disponueshme"}</Button>
        <Button size="sm" variant="ghost" disabled={recorder.saving || active} onClick={() => { if (window.confirm("Hiq fragmentet lokale dhe braktis sesionin?")) void recorder.discard(m.id) }}>Braktis</Button>
      </div>)}
      {(active || recorder.state === "prepared" || recorder.manifest) && <p className="text-xs text-muted-foreground">Mos e rifreskoni ose mbyllni këtë skedë deri në ruajtjen e regjistrimit.</p>}
    </CardContent>
  </Card>
}
