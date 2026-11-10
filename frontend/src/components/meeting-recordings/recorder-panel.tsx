"use client"

import * as React from "react"
import Link from "next/link"
import { ChevronDown, Mic, Monitor, Pause, Play, Square, Video } from "lucide-react"
import { useAuth } from "@/lib/auth"
import type { Department, Meeting, Project } from "@/lib/types"
import { recordingJson } from "@/lib/recording-outbox"
import { RecordingProjectOptions } from "./project-options"
import { RecordingMeetingOptions } from "./meeting-options"
import { recordingSize, recordingTime } from "@/lib/recording-types"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Command, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { useRecorder } from "./recorder-provider"

export function RecorderPanel() {
  const recorder = useRecorder()
  const { apiFetch } = useAuth()
  const [title, setTitle] = React.useState("Regjistrim i ri")
  const [description, setDescription] = React.useState("")
  const [projectId, setProjectId] = React.useState("")
  const [projects, setProjects] = React.useState<Project[]>([])
  const [departments, setDepartments] = React.useState<Department[]>([])
  const [projectError, setProjectError] = React.useState("")
  const [meetingId, setMeetingId] = React.useState("")
  const [meetings, setMeetings] = React.useState<Meeting[]>([])
  const [meetingError, setMeetingError] = React.useState("")
  const [meetingSearch, setMeetingSearch] = React.useState("")
  const [meetingOpen, setMeetingOpen] = React.useState(false)
  const meetingPickerRef = React.useRef<HTMLDivElement>(null)
  const meetingTriggerRef = React.useRef<HTMLButtonElement>(null)
  React.useEffect(() => {
    if (!meetingOpen) return
    const closeOutside = (event: PointerEvent) => {
      if (!meetingPickerRef.current?.contains(event.target as Node)) setMeetingOpen(false)
    }
    document.addEventListener("pointerdown", closeOutside)
    return () => document.removeEventListener("pointerdown", closeOutside)
  }, [meetingOpen])
  const [devices, setDevices] = React.useState<MediaDeviceInfo[]>([])
  const [device, setDevice] = React.useState("default")
  const [source, setSource] = React.useState("monitor")
  const [consent, setConsent] = React.useState(false)
  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const timer = window.setTimeout(() => {
      if (params.get("project_id")) setProjectId(params.get("project_id")!)
      if (params.get("meeting_id")) setMeetingId(params.get("meeting_id")!)
      if (params.get("title")) setTitle(params.get("title")!.slice(0, 200))
    }, 0)
    void navigator.mediaDevices?.enumerateDevices().then(all => setDevices(all.filter(d => d.kind === "audioinput"))).catch(() => {})
    return () => window.clearTimeout(timer)
  }, [])
  React.useEffect(() => {
    if (recorder.state === "prepared") void navigator.mediaDevices.enumerateDevices().then(all => setDevices(all.filter(d => d.kind === "audioinput"))).catch(() => {})
  }, [recorder.state])
  React.useEffect(() => {
    let active = true
    void apiFetch("/meetings?include_all_departments=true").then(recordingJson).then((all: Meeting[]) => {
      if (active) { setMeetings(all); setMeetingError("") }
    }).catch(() => { if (active) setMeetingError("Takimet nuk u ngarkuan. Rifreskoni faqen.") })
    return () => { active = false }
  }, [apiFetch])
  React.useEffect(() => {
    let active = true
    void Promise.all([
      apiFetch("/projects").then(recordingJson) as Promise<Project[]>,
      apiFetch("/departments").then(recordingJson) as Promise<Department[]>,
    ]).then(([items, departments]) => {
      if (active) { setProjects(items); setDepartments(departments); setProjectError("") }
    }).catch(() => { if (active) setProjectError("Projektet nuk u ngarkuan. Rifreskoni faqen.") })
    return () => { active = false }
  }, [apiFetch])
  const active = ["recording", "paused", "stopping"].includes(recorder.state)
  const locked = active || recorder.busy || recorder.saving || recorder.state === "selecting" || !!recorder.manifest
  const percent = recorder.manifest?.bytes ? Math.floor(recorder.manifest.uploadedBytes / recorder.manifest.bytes * 100) : 0
  const normalizeSearch = (value: string) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase().trim()
  const searchTerms = normalizeSearch(meetingSearch).split(/\s+/).filter(Boolean)
  const departmentNames = new Map(departments.map(department => [department.id, `${department.name} ${department.code}`]))
  const filteredMeetings = meetings.filter(meeting => {
    const date = meeting.starts_at ? new Date(meeting.starts_at) : null
    const validDate = date && Number.isFinite(date.getTime())
    const searchable = normalizeSearch([
      meeting.title, departmentNames.get(meeting.department_id) || "Pa departament",
      validDate ? date.toLocaleDateString("en-GB").replaceAll("/", ".") : "Pa datë",
      validDate ? date.toLocaleDateString("en-GB") : "",
      validDate ? date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }) : "",
    ].join(" "))
    return searchTerms.every(term => searchable.includes(term))
  })
  const prepare = () => { void recorder.prepare(device === "none" ? false : device === "default" ? "" : device, source, { title: title.trim(), meetingId, description, projectId }) }
  const selectMeeting = (id: string) => {
    setMeetingId(id)
    setMeetingOpen(false)
    meetingTriggerRef.current?.focus()
  }
  return <Card>
    <CardHeader><CardTitle className="flex items-center gap-2"><Video className="size-5" /> Regjistrim i ri</CardTitle></CardHeader>
    <CardContent className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2"><Label htmlFor="recording-title">Titulli</Label><Input id="recording-title" maxLength={200} value={title} disabled={locked} onChange={e => setTitle(e.target.value)} /></div>
        <div className="min-w-0 space-y-2"><Label htmlFor="recording-meeting">Takimi (opsional)</Label>
          <div ref={meetingPickerRef} className="relative" onBlur={event => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setMeetingOpen(false)
          }} onKeyDown={event => {
            if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); setMeetingOpen(false); meetingTriggerRef.current?.focus() }
          }}>
            <Button ref={meetingTriggerRef} id="recording-meeting" type="button" variant="outline" className="w-full min-w-0 justify-between font-normal" disabled={locked} aria-expanded={meetingOpen && !locked} aria-controls={meetingOpen ? "recording-meeting-picker" : undefined} onClick={() => { setMeetingSearch(""); setMeetingOpen(open => !open) }} onKeyDown={event => {
              if (event.key === "ArrowDown") { event.preventDefault(); setMeetingSearch(""); setMeetingOpen(true) }
            }}><span className="truncate">{meetings.find(meeting => meeting.id === meetingId)?.title || "Pa takim të lidhur"}</span><ChevronDown className="size-4 shrink-0 opacity-50" /></Button>
            {meetingOpen && !locked && <div id="recording-meeting-picker" className="absolute top-full right-0 left-0 z-[120] mt-1 overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md">
              <Command shouldFilter={false}>
                <CommandInput autoFocus aria-label="Kërko takime" placeholder="Kërko me titull, departament, datë ose orë…" value={meetingSearch} onValueChange={setMeetingSearch} />
                <div aria-hidden="true" className="grid grid-cols-[minmax(0,1fr)_6rem_3.5rem] gap-3 border-b px-3 py-2 text-xs font-semibold text-muted-foreground"><span>Takimi</span><span className="text-right">Data</span><span className="text-right">Ora</span></div>
                <CommandList className="max-h-72" aria-label="Takimet">
                  <CommandItem value="none" onSelect={() => selectMeeting("")}>Pa takim të lidhur</CommandItem>
                  <RecordingMeetingOptions meetings={filteredMeetings} departments={departments} onSelect={selectMeeting} />
                  {!filteredMeetings.length && <p role="status" className="px-2 py-4 text-center text-sm text-muted-foreground">Nuk u gjet asnjë takim.</p>}
                </CommandList>
              </Command>
            </div>}
          </div>
          {meetingError && <p role="alert" className="text-sm text-destructive">{meetingError}</p>}</div>
        <div className="space-y-2"><Label htmlFor="recording-project">Projekti (opsional)</Label><select id="recording-project" className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={projectId} disabled={locked} onChange={e => setProjectId(e.target.value)}>
          <option value="">Pa projekt të lidhur</option><RecordingProjectOptions projects={projects} departments={departments} />
        </select>{projectError && <p role="alert" className="text-sm text-destructive">{projectError}</p>}</div>
        <div className="space-y-2"><Label htmlFor="recording-source">Burimi</Label><select id="recording-source" className="h-9 w-full rounded-md border bg-background px-3 text-sm" disabled={locked || recorder.state === "prepared"} value={source} onChange={e => setSource(e.target.value)}>
          <option value="monitor">Ekrani i plotë — gjithçka në ekranin e zgjedhur, edhe kur ndërron programe</option>
          <option value="window">Dritare — vetëm dritarja e zgjedhur, p.sh. Teams ose Word</option>
          <option value="browser">Skedë e shfletuesit — vetëm tab-i i zgjedhur në Chrome/Edge</option>
        </select></div>
        <div className="space-y-2"><Label htmlFor="recording-microphone">Mikrofoni</Label><select id="recording-microphone" className="h-9 w-full rounded-md border bg-background px-3 text-sm" disabled={locked || recorder.state === "prepared"} value={device} onChange={e => setDevice(e.target.value)}>
          <option value="default">Mikrofoni i parazgjedhur — përdor mikrofonin e zgjedhur automatikisht</option>
          <option value="none">Pa mikrofon — nuk regjistron zërin nga mikrofoni</option>
          {devices.filter(d => d.deviceId && d.deviceId !== "default").map((d, i) => <option key={d.deviceId} value={d.deviceId}>{d.label || `Mikrofoni ${i + 1}`} — regjistron zërin nga kjo pajisje</option>)}
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
          <Button disabled={!consent || !title.trim() || recorder.busy} onClick={() => void recorder.start(title.trim(), meetingId, description, projectId)}><Play className="mr-2 size-4" />{recorder.info.system ? "Fillo regjistrimin" : "Vazhdo pa audio sistemi"}</Button>
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
