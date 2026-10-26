// @refresh reset
"use client"

import * as React from "react"
import { CalendarDays, CheckCircle2, Clock3, Eye, History, Mail, Pencil, RefreshCw, Save, Send } from "lucide-react"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { changedManualAnswers, clearSavedManualDraft, readManualDraft, writeManualDraft } from "@/lib/m2-reporting-points-draft"
import { reportResponseJson as responseJson } from "@/lib/report-response"
import { ReportingPointsManagement } from "@/components/reporting-points-management"
import { M2ReportingPointsView, reportDate, reportTime, type ManualAnswers, type ManualKey, type ReportingPointsReport } from "@/components/m2-reporting-points-view"

const API = "/m2-reporting-points"
type Recipients = { to: string[]; cc: string[]; bcc: string[] }
type HistoryRow = Pick<ReportingPointsReport, "id" | "report_date" | "status" | "sent_at">

function today() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Tirane", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date())
}

function draftStorage() {
  try { return window.localStorage } catch { return null }
}

export default function M2ReportingPointsPage() {
  const { user, loading: authLoading, apiFetch } = useAuth()
  const [day, setDay] = React.useState(today)
  const [report, setReport] = React.useState<ReportingPointsReport | null>(null)
  const activeReportId = React.useRef<string | undefined>(undefined)
  React.useEffect(() => { activeReportId.current = report?.id }, [report?.id])
  const [answers, setAnswers] = React.useState<ManualAnswers>({})
  const [recipients, setRecipients] = React.useState<Recipients | null>(null)
  const [busy, setBusy] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [previewHtml, setPreviewHtml] = React.useState<string | null>(null)
  const [history, setHistory] = React.useState<HistoryRow[] | null>(null)
  const [sendOpen, setSendOpen] = React.useState(false)
  const [tab, setTab] = React.useState("report")
  const [savingAnswers, setSavingAnswers] = React.useState(false)
  const [saveError, setSaveError] = React.useState<string | null>(null)
  const canAccess = !!user
  const currentUserId = user?.id
  const canManage = !!user && (["ADMIN", "MANAGER"].includes(user.role) || (user.full_name || "").trim().toLowerCase() === "laurent hoxha")
  const dirty = !!report && (Array.from(new Set([...Object.keys(answers), ...Object.keys(report.manual_answers)])) as ManualKey[]).some((key) => (answers[key] || "") !== (report.manual_answers[key] || ""))

  const acceptReport = React.useCallback((value: ReportingPointsReport) => {
    setReport(value)
    const local = canManage && currentUserId ? readManualDraft(draftStorage(), currentUserId, value.report_date) : null
    setAnswers({ ...value.manual_answers, ...local })
    setError(null)
    setSaveError(null)
  }, [currentUserId, canManage])

  React.useEffect(() => {
    if (!canAccess) return
    let active = true
    Promise.resolve().then(() => {
      if (!active) return null
      setLoading(true)
      setReport(null)
      setAnswers({})
      setError(null)
      return apiFetch(`${API}?report_date=${day}`)
    }).then(async (response) => {
      if (!response) return
      if (response.status === 404) return
      const value = await responseJson<ReportingPointsReport>(response)
      if (active) acceptReport(value)
    }).catch((error: Error) => { if (active) setError(error.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [apiFetch, day, canAccess, acceptReport])

  React.useEffect(() => {
    if (!canAccess) return
    let active = true
    if (!canManage) return
    apiFetch(`${API}/recipients`).then(responseJson<{ recipients: Recipients }>).then((value) => {
      if (active) setRecipients(value.recipients)
    }).catch((error: Error) => { if (active) setError(error.message) })
    return () => { active = false }
  }, [apiFetch, canAccess, canManage])

  // Refresh automatic sections without replacing unsaved answers.
  React.useEffect(() => {
    if (!canAccess || day !== today() || dirty || busy || savingAnswers) return
    let active = true
    const timer = window.setInterval(() => {
      apiFetch(`${API}?report_date=${day}`, { cache: "no-store" }).then(async (response) => {
        if (response.ok) {
          const value = await responseJson<ReportingPointsReport>(response)
          if (active) acceptReport(value)
        }
      }).catch(() => {})
    }, 30000)
    return () => { active = false; window.clearInterval(timer) }
  }, [apiFetch, day, canAccess, dirty, busy, savingAnswers, acceptReport])

  React.useEffect(() => {
    if (!report || !dirty || !canManage || savingAnswers || busy || saveError) return
    const reportId = report.id
    const savedAnswers = { ...answers }
    const changedAnswers = changedManualAnswers(savedAnswers, report.manual_answers)
    const savedDay = report.report_date
    const timer = window.setTimeout(async () => {
      setSavingAnswers(true)
      try {
        const value = await responseJson<ReportingPointsReport>(await apiFetch(`${API}/${reportId}/answers`, {
          method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ manual_answers: changedAnswers }),
        }))
        // Preserve newer edits; the next save starts after this one finishes.
        setReport((previous) => previous?.id === reportId ? value : previous)
        if (activeReportId.current === reportId) {
          setAnswers((current) => ({ ...value.manual_answers, ...changedManualAnswers(current, savedAnswers) }))
        }
        if (user?.id) clearSavedManualDraft(draftStorage(), user.id, savedDay, savedAnswers)
      } catch (error) {
        setSaveError(error instanceof Error ? error.message : "Përgjigjet nuk u ruajtën.")
      } finally { setSavingAnswers(false) }
    }, 700)
    return () => window.clearTimeout(timer)
  }, [answers, apiFetch, report, dirty, canManage, savingAnswers, busy, saveError, user?.id])

  const action = async (name: string, work: () => Promise<void>) => {
    setBusy(name)
    try { await work() }
    catch (error) { toast.error(error instanceof Error ? error.message : "Veprimi dështoi.") }
    finally { setBusy(null) }
  }

  const generate = () => action("generate", async () => {
    const value = await responseJson<ReportingPointsReport>(await apiFetch(`${API}/generate?report_date=${day}`, { method: "POST" }))
    acceptReport(value)
    toast.success("Pikat automatike u përditësuan.")
  })

  const refresh = () => action("refresh", async () => {
    const response = await apiFetch(`${API}?report_date=${day}`, { cache: "no-store" })
    if (response.status === 404) { setReport(null); return }
    acceptReport(await responseJson<ReportingPointsReport>(response))
  })

  const save = () => action("save", async () => {
    if (!report) return
    const value = await responseJson<ReportingPointsReport>(await apiFetch(`${API}/${report.id}/answers`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ manual_answers: changedManualAnswers(answers, report.manual_answers) }),
    }))
    if (user?.id) clearSavedManualDraft(draftStorage(), user.id, day, answers)
    acceptReport(value)
    toast.success("Përgjigjet u ruajtën.")
  })

  const preview = () => action("preview", async () => {
    if (!report) return
    const value = await responseJson<{ html: string }>(await apiFetch(`${API}/${report.id}/preview`))
    setPreviewHtml(value.html)
  })

  const download = (format: "docx" | "png" | "txt") => action("download", async () => {
    if (!report) return
    const response = await apiFetch(`${API}/${report.id}/download/${format}`)
    if (!response.ok) { await responseJson(response); return }
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement("a")
    link.href = url; link.download = `pikat_m2_${report.report_date}.${format}`; link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  })

  const loadHistory = () => action("history", async () => {
    setHistory(await responseJson<HistoryRow[]>(await apiFetch(`${API}/history`)))
  })

  const changeAnswer = (key: ManualKey, value: string) => {
    const next = { ...answers, [key]: value }
    if (user?.id) writeManualDraft(draftStorage(), user.id, day, changedManualAnswers(next, report?.manual_answers || {}))
    setSaveError(null)
    setAnswers(next)
  }

  const send = () => action("send", async () => {
    if (!report) return
    const value = await responseJson<ReportingPointsReport>(await apiFetch(`${API}/${report.id}/send`, { method: "POST" }))
    acceptReport(value)
    setSendOpen(false)
    toast.success("Raporti u dërgua te marrësit aktualë të M2.")
  })

  if (authLoading) return <p className="p-8 text-sm text-muted-foreground">Duke ngarkuar…</p>
  if (!canAccess) return <p className="rounded-xl border p-8">Hyr në platformë për të parë raportin.</p>

  return <div className="mx-auto max-w-[1480px] space-y-6">
    <header className="flex flex-wrap items-center justify-between gap-4 border-b pb-5">
      <div className="flex items-center gap-3">
        <div className="flex size-11 items-center justify-center rounded-md bg-slate-900 text-white"><Mail className="size-5" /></div>
        <div><h1 className="text-2xl font-semibold">Pikat për raportim M2</h1><p className="text-sm text-muted-foreground">Hapësira e raportit ditor</p></div>
      </div>
      <div className="flex gap-2">
        <Button variant="outline" onClick={refresh} disabled={!!busy || loading || dirty || savingAnswers}><RefreshCw className={busy === "refresh" ? "animate-spin" : ""} />Rifresko</Button>
        <Button onClick={generate} disabled={!!busy || loading || dirty || savingAnswers || day !== today()}><RefreshCw className={busy === "generate" ? "animate-spin" : ""} />Gjenero raportin</Button>
      </div>
    </header>
    {error ? <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</p> : null}
    {report?.last_error ? <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">Dërgimi i fundit dështoi. Kontrollo konfigurimin e email-it dhe provo përsëri.</p> : null}
    <Tabs value={tab} onValueChange={(value) => { setTab(value); if (value === "history") void loadHistory() }} className="gap-5">
      <div className="flex flex-wrap items-center gap-2"><TabsList className="h-10 rounded-md"><TabsTrigger value="report"><Pencil />Raporti</TabsTrigger><TabsTrigger value="history"><History />Historiku</TabsTrigger></TabsList></div>
      <TabsContent value="report" className="space-y-5">
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button variant="outline" onClick={preview} disabled={!report || !!busy || savingAnswers || dirty}><Eye />Pamja e email-it</Button>
          {(["docx", "png", "txt"] as const).map((format) => <Button key={format} variant="outline" disabled={!report || !!busy || savingAnswers || dirty} onClick={() => download(format)}>{format === "docx" ? "Word" : format.toUpperCase()}</Button>)}
          {canManage ? <Button onClick={() => setSendOpen(true)} disabled={!report || !report.generated_at || !!busy || savingAnswers || dirty || !recipients?.to.length}><Send />{report?.sent_at ? "Dërgo sërish" : "Dërgo"}</Button> : null}
        </div>
        <ReportingPointsManagement api={API} reportType="M2" canManage={canManage} onRecipientsChange={setRecipients}>
        <div className="grid gap-4 border-y bg-slate-50/70 px-4 py-4 lg:grid-cols-[190px_minmax(320px,1fr)_auto]">
          <div><Label htmlFor="report-day">Data e raportit</Label><input className="mt-1 h-9 w-full rounded-md border border-input bg-white px-3 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50" id="report-day" type="date" value={day} max={today()} disabled={!!busy || savingAnswers}
            onChange={(event) => { if (dirty) toast.error("Prit ruajtjen e përgjigjeve përpara ndryshimit të datës."); else if (event.target.value) setDay(event.target.value) }} /></div>
          <div><Label htmlFor="report-subject">Titulli i email-it</Label><input id="report-subject" readOnly value={report?.subject || ""} placeholder="Gjenero raportin" className="mt-1 h-9 w-full rounded-md border border-input bg-white px-3 text-sm shadow-xs" /></div>
          <div className="flex flex-wrap items-end gap-2">
            {canManage ? <Button variant="outline" onClick={save} disabled={!report || !!busy || savingAnswers || !dirty}><Save />Ruaj përgjigjet</Button> : null}
          </div>
        </div>
        {report ? <div className="grid border md:grid-cols-3">
          {[
            [CalendarDays, "Data e raportit", reportDate(report.report_date)],
            [CheckCircle2, "Statusi", report.status],
            [Clock3, "Përditësimi i fundit", report.generated_at ? `${reportDate(report.generated_at)}, ${reportTime(report.generated_at)}` : "—"],
          ].map(([Icon, label, value], index) => {
            const MetaIcon = Icon as typeof CalendarDays
            return <div key={String(label)} className={index < 2 ? "border-b p-4 md:border-b-0 md:border-r" : "p-4"}>
              <div className="flex items-center gap-2 text-xs font-medium uppercase text-muted-foreground"><MetaIcon className="size-4" />{String(label)}</div>
              <div className="mt-1.5 text-sm font-semibold">{String(value)}</div>
            </div>
          })}
        </div> : null}
        </ReportingPointsManagement>
        {canManage && report ? <p role="status" className={`text-xs ${saveError ? "text-red-700" : "text-muted-foreground"}`}>
          {saveError ? `Ruajtja automatike dështoi: ${saveError} Provo Ruaj përgjigjet.` : savingAnswers || dirty ? "Duke ruajtur përgjigjet…" : "Përgjigjet ruhen automatikisht për datën e këtij raporti."}
        </p> : null}
    {loading ? <p className="py-10 text-center text-muted-foreground">Duke ngarkuar raportin…</p> : report ? <>
      <M2ReportingPointsView report={report} answers={answers} disabled={!canManage || !!busy} onAnswerChange={changeAnswer} />
    </> : <div className="rounded-xl border border-dashed p-12 text-center"><h2 className="font-semibold">Nuk ka raport të ruajtur për {reportDate(day)}.</h2><p className="mt-2 text-sm text-muted-foreground">{day === today() ? "Gjenero raportin për të plotësuar përgjigjet dhe për të parë pikat automatike." : "Zgjidh një datë nga historiku për të parë të dhënat e ruajtura."}</p></div>}
      </TabsContent>
      <TabsContent value="history" className="space-y-3">
        <h2 className="font-semibold">Historiku i raporteve</h2>
        {busy === "history" ? <p className="text-sm text-muted-foreground">Duke ngarkuar historikun…</p> : history?.length ? history.map((row) => <button key={row.id} type="button" className="flex w-full items-center justify-between rounded-md border p-3 text-left hover:bg-muted" onClick={() => {
          if (dirty || savingAnswers) { toast.error("Prit ruajtjen e përgjigjeve përpara hapjes së një date tjetër."); return }
          setDay(row.report_date); setTab("report")
        }}><span>{reportDate(row.report_date)}<span className="ml-3 text-xs text-muted-foreground">{row.sent_at ? reportTime(row.sent_at) : "Pa dërguar"}</span></span><Badge variant="secondary">{row.status}</Badge></button>) : <p className="text-sm text-muted-foreground">Nuk ka ende raporte në historik.</p>}
      </TabsContent>
    </Tabs>

    <Dialog open={previewHtml !== null} onOpenChange={(open) => { if (!open) setPreviewHtml(null) }}><DialogContent className="max-w-[95vw] sm:max-w-[95vw]"><DialogHeader><DialogTitle>Pamja e raportit në email</DialogTitle></DialogHeader><iframe title="Pikat për raportim M2" sandbox="" srcDoc={previewHtml || ""} className="h-[75vh] w-full rounded border bg-white" /></DialogContent></Dialog>
    <Dialog open={sendOpen} onOpenChange={(open) => { if (!busy) setSendOpen(open) }}><DialogContent><DialogHeader><DialogTitle>Dërgo raportin M2</DialogTitle></DialogHeader><p className="text-sm">Raporti i datës {reportDate(day)} dërgohet te marrësit aktualë të M2. Pikat automatike të raportit të sotëm përditësohen në momentin e dërgimit; përgjigjet ruhen. Çdo dërgim krijon një email të ri.</p><div className="space-y-2 rounded-lg bg-muted p-3 text-sm">{recipients ? (Object.entries(recipients) as [string, string[]][]).filter(([, values]) => values.length).map(([key, values]) => <p key={key}><strong>{key.toUpperCase()}:</strong> {values.join(", ")}</p>) : null}</div><Button onClick={send} disabled={!!busy}><Send className="mr-2 h-4 w-4" />{busy === "send" ? "Duke dërguar…" : "Dërgo raportin"}</Button></DialogContent></Dialog>
  </div>
}
