"use client"

import * as React from "react"
import { CheckCircle2, ChevronLeft, ChevronRight, ClipboardList, LoaderCircle, LockKeyhole, Plus, Search, ShieldCheck } from "lucide-react"
import { toast } from "sonner"
import { useGaPersonalSession } from "@/lib/use-ga-personal-session"
import { TaskList } from "@/components/ga-personal/task-list"
import { QuickEditDialog, QuickEditValues } from "@/components/ga-personal/quick-edit-dialog"
import { DiscordSettingsPanel } from "@/components/ga-personal/discord-settings"
import { DeviceSettingsPanel } from "@/components/ga-personal/device-settings"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { dayLabel, Definition, emptyDefinition, frequencies, GaOccurrence, GaStatus, GaTemplate, groups, ImportPreview, localToday, moveDay, PersonKey, statuses } from "@/lib/ga-personal"

const fieldClass = "w-full rounded-md border bg-background px-3 py-2 text-sm"

export default function GaPersonalPage() {
  const [tab, setTab] = React.useState("today")
  const [person, setPerson] = React.useState<string>("all")
  const [day, setDay] = React.useState(localToday)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState("")
  const [editing, setEditing] = React.useState<GaTemplate | null>(null)
  const [draft, setDraft] = React.useState<Definition | null>(null)
  const [stepsText, setStepsText] = React.useState("")
  const [importData, setImportData] = React.useState<Record<string, unknown> | null>(null)
  const [preview, setPreview] = React.useState<ImportPreview | null>(null)
  const [deferred, setDeferred] = React.useState<GaOccurrence | null>(null)
  const [deferTime, setDeferTime] = React.useState("")
  const [quick, setQuick] = React.useState<GaOccurrence | null>(null)
  const [quickTemplateVersion, setQuickTemplateVersion] = React.useState<number | undefined>()
  const [search, setSearch] = React.useState("")
  const [statusFilter, setStatusFilter] = React.useState("all")
  const [groupFilter, setGroupFilter] = React.useState("all")
  const resetDrafts = React.useCallback(() => {
    setDraft(null); setEditing(null); setImportData(null); setPreview(null); setDeferred(null)
    setQuick(null); setStepsText("")
  }, [])
  const { access, workspace, templates, occurrences, history, request, load, check, obscured, connectionError } = useGaPersonalSession(resetDrafts)

  async function run(work: () => Promise<unknown>) {
    setBusy(true); setError("")
    try { await work() } catch (e) { setError(e instanceof Error ? e.message : "Veprimi nuk u krye.") }
    finally { setBusy(false) }
  }

  function edit(row?: GaTemplate) {
    setError(""); setQuick(null)
    setEditing(row || null)
    const d = row?.definition || emptyDefinition(workspace!.person_key)
    setDraft({ ...d }); setStepsText(d.steps.join("\n"))
  }

  function openQuick(row: GaOccurrence) {
    setError(""); setQuick(row)
    setQuickTemplateVersion(templates.find((t) => t.id === row.template_id)?.version)
  }

  async function saveQuick(values: QuickEditValues) {
    if (!quick) return
    await run(async () => {
      await request(`/occurrences/${quick.id}`, { method: "PATCH", body: JSON.stringify({ ...values,
        expected_version: quick.version, expected_template_version: quickTemplateVersion, request_id: crypto.randomUUID(),
      }) })
      setQuick(null); await load(); toast.success("Ora dhe përgjegjësi u ruajtën.")
    })
  }

  async function save(e: React.FormEvent) {
    e.preventDefault()
    await run(async () => {
      await request(editing ? `/templates/${editing.id}` : "/templates", { method: editing ? "PUT" : "POST", body: JSON.stringify({
        definition: { ...draft, steps: stepsText.split("\n").map((s) => s.trim()).filter(Boolean) }, expected_version: editing?.version,
      }) })
      setDraft(null); await load(); toast.success("Detyra u ruajt.")
    })
  }

  async function action(row: GaOccurrence, status: GaStatus, reschedule_at?: string) {
    await run(async () => {
      await request(`/occurrences/${row.id}/actions`, { method: "POST", body: JSON.stringify({
        status, expected_version: row.version, request_id: crypto.randomUUID(), reschedule_at,
      }) })
      setDeferred(null); await load()
    })
  }

  const names = (keys: PersonKey[]) => keys.map((key) => workspace?.members.find((m) => m.person_key === key)?.name || key).join(", ")
  const monday = new Date(`${day}T12:00:00Z`)
  monday.setUTCDate(monday.getUTCDate() - (monday.getUTCDay() + 6) % 7)
  const weekendKey = `weekend:${monday.toISOString().slice(0, 10)}`
  const datedRows = occurrences.filter((o) => tab === "week" ? o.period_key === weekendKey || (o.local_date >= monday.toISOString().slice(0, 10) && o.local_date <= new Date(monday.getTime() + 6 * 86400000).toISOString().slice(0, 10))
    : o.local_date === day || (o.period_key === weekendKey && new Date(`${day}T12:00:00Z`).getUTCDay() % 6 === 0))
  const personRows = datedRows.filter((o) => person === "all" || o.snapshot.assignees.includes(person as PersonKey))
  const visible = personRows.filter((o) => (groupFilter === "all" || o.snapshot.reminder_group === groupFilter)
    && (statusFilter === "all" || (statusFilter === "done" ? o.status === "done" : !["done", "cancelled"].includes(o.status)))
    && `${o.snapshot.short_code || ""} ${o.snapshot.title}`.toLowerCase().includes(search.toLowerCase()))
  const done = personRows.filter((row) => row.status === "done").length
  const modelRows = templates.filter((t) => (person === "all" || t.definition.assignees.includes(person as PersonKey)
    || (t.definition.assignment === "rotation" && ["rrita", "mrika", "lirza"].includes(person))) && `${t.definition.short_code || ""} ${t.definition.title}`.toLowerCase().includes(search.toLowerCase()))
  const dialogOpen = !!draft || !!quick || !!deferred

  return <div className="relative mx-auto max-w-5xl space-y-5 pb-8" data-testid="ga-personal">
    {obscured && <div className="fixed inset-0 z-[200] flex items-center justify-center bg-background" role="status"><div className="space-y-3 text-center"><LoaderCircle className="mx-auto h-6 w-6 animate-spin text-muted-foreground" /><p className="text-sm">Po verifikohet sesioni…</p>{connectionError && <><p className="max-w-sm text-sm text-muted-foreground">{connectionError}</p><Button variant="outline" onClick={() => void check()}>Provo përsëri</Button></>}</div></div>}
    <header className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border bg-card p-5">
      <div className="flex items-center gap-3"><div className="rounded-xl bg-primary/10 p-3"><ShieldCheck className="h-6 w-6 text-primary" /></div>
        <div><h1 className="text-xl font-semibold">GA PERSONAL</h1><p className="text-sm text-muted-foreground">Punët e shtëpisë, me kohë dhe pa nxitim.</p></div></div>
      {workspace && <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy} onClick={() => void run(async () => {
        const result = await request<{ first_home: PersonKey }>("/arrival", { method: "POST", body: JSON.stringify({ request_id: crypto.randomUUID() }) })
        await load(); toast.success(`Ardhja u regjistrua. Personi i parë: ${names([result.first_home])}.`)
      })}>Erdha në shpi</Button><Button onClick={() => edit()}><Plus className="mr-2 h-4 w-4" />Detyrë e re</Button></div>}
    </header>
    {error && !dialogOpen && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
    {connectionError && !obscured && <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-muted/40 p-3 text-sm"><p>{connectionError}</p><Button size="sm" variant="outline" onClick={() => void check()}>Provo përsëri</Button></div>}
    {(!access || (access.available && !workspace)) ? <div className="flex items-center justify-center gap-3 rounded-xl border p-12 text-sm text-muted-foreground" role="status"><LoaderCircle className="h-5 w-5 animate-spin" />Duke hapur hapësirën…</div>
      : !access.available ? <div className="rounded-xl border p-8 text-center"><LockKeyhole className="mx-auto mb-4 h-8 w-8 text-muted-foreground" /><p>Ky modul ende nuk është aktivizuar për llogarinë tënde.</p></div>
        : workspace && <>
          <nav className="flex flex-wrap gap-2" aria-label="Pamjet e GA PERSONAL">{[["today", "Detyrat e ditës"], ["week", "Këtë javë"], ["templates", "Përsëritjet"], ["history", "Historiku"], ["settings", "Cilësimet"]].map(([key, label]) =>
            <Button key={key} variant={tab === key ? "default" : "outline"} onClick={() => setTab(key)}>{label}</Button>)}</nav>
          {["today", "week", "templates"].includes(tab) && <div className="space-y-4 rounded-xl border bg-card p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              {tab !== "templates" ? <div className="flex flex-wrap items-center gap-2">
                <Button size="icon" variant="outline" aria-label="Dita e mëparshme" onClick={() => setDay(moveDay(day, tab === "week" ? -7 : -1))}><ChevronLeft className="h-4 w-4" /></Button>
                <label className="flex items-center rounded-md border px-2 text-sm"><Input aria-label="Data" type="date" className="w-[132px] border-0 px-0 shadow-none focus-visible:ring-0" value={day} onChange={(e) => { if (e.target.value) setDay(e.target.value) }} /></label>
                <Button size="icon" variant="outline" aria-label="Dita e ardhshme" onClick={() => setDay(moveDay(day, tab === "week" ? 7 : 1))}><ChevronRight className="h-4 w-4" /></Button>
                <Button variant="ghost" size="sm" onClick={() => setDay(localToday())}>Sot</Button>
              </div> : <div><h2 className="font-semibold">Detyrat që përsëriten</h2><p className="text-sm text-muted-foreground">Cakto orën, personin dhe ditët për të ardhmen.</p></div>}
              <label className="relative w-full min-w-0 flex-none sm:w-auto sm:flex-1 sm:max-w-xs"><Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><Input aria-label="Kërko detyrë" placeholder="Kërko një detyrë…" className="pl-9" value={search} onChange={(e) => setSearch(e.target.value)} /></label>
            </div>
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filtro sipas personit">
              <Button size="sm" variant={person === "all" ? "default" : "outline"} onClick={() => setPerson("all")}>Familja</Button>
              <Button size="sm" variant={person === workspace.person_key ? "default" : "outline"} onClick={() => setPerson(workspace.person_key)}>Të miat</Button>
              {workspace.members.filter((m) => m.person_key !== workspace.person_key).map((m) => <Button key={m.person_key} size="sm" variant={person === m.person_key ? "default" : "ghost"} onClick={() => setPerson(m.person_key)}>{m.name.split(" ")[0]}</Button>)}
            </div>
          </div>}
          {["today", "week"].includes(tab) && <>
            <div className="flex flex-wrap items-center justify-between gap-4 px-1">
              <div className="space-y-2"><h2 className="text-lg font-semibold">{tab === "week" ? "Plani i javës" : dayLabel(day)}</h2>
                <div className="flex items-center gap-3 text-sm text-muted-foreground"><span className="flex items-center gap-1.5"><CheckCircle2 className="h-4 w-4 text-emerald-600" />{done} nga {personRows.length} të kryera</span><div className="h-1.5 w-24 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="Progresi i detyrave" aria-valuenow={done} aria-valuemax={personRows.length}><div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${personRows.length ? done / personRows.length * 100 : 0}%` }} /></div></div>
              </div>
              <div className="flex flex-wrap gap-2">
                <select className={fieldClass.replace("w-full ", "")} aria-label="Filtro grupin" value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)}><option value="all">Të gjitha rutinat</option>{Object.entries(groups).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
                <select className={fieldClass.replace("w-full ", "")} aria-label="Filtro gjendjen" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}><option value="all">Të gjitha detyrat</option><option value="open">Të pakryera</option><option value="done">Të kryera</option></select>
              </div>
            </div>
            {!visible.length ? <div className="space-y-3 rounded-xl border bg-card p-8 text-center"><ClipboardList className="mx-auto h-8 w-8 text-muted-foreground" /><h3 className="font-medium">Nuk ka detyra në këtë pamje</h3><p className="mx-auto max-w-md text-sm text-muted-foreground">{personRows.length ? "Provo një filtër tjetër ose pastro kërkimin." : "Për këtë datë nuk janë krijuar ende detyra. Detyrat e aktivizuara shtohen automatikisht në ditën përkatëse."}</p></div>
              : <TaskList rows={visible} workspace={workspace} busy={busy} showDate={tab === "week"} onEdit={openQuick} onAction={(row, status) => void action(row, status)} onDefer={(row) => { setError(""); setDeferred(row); setDeferTime("") }} />}
            {workspace.is_admin && <details className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground"><summary className="cursor-pointer">Mundësi të tjera për datën</summary><div className="mt-3 flex flex-wrap items-center gap-3"><p>Krijo detyrat e aktivizuara për datën e zgjedhur.</p><Button size="sm" variant="outline" disabled={busy} onClick={() => void run(async () => {
              const result = await request<{ created: number }>("/generate", { method: "POST", body: JSON.stringify({ day }) }); await load(); toast.success(`${result.created} detyra të përgatitura.`)
            })}>Përgatit detyrat e datës</Button></div></details>}
          </>}
          {tab === "templates" && <div className="space-y-3">{!modelRows.length && <div className="rounded-xl border p-8 text-center text-muted-foreground">Nuk u gjet asnjë detyrë. Provo një kërkim tjetër ose shto një detyrë të re.</div>}{modelRows.map((t) => <article key={t.id} className="flex flex-wrap items-center justify-between gap-4 rounded-xl border bg-card p-4">
            <div className="min-w-0 space-y-1"><h2 className="font-medium">{t.definition.short_code && <span className="mr-2 text-xs text-muted-foreground">{t.definition.short_code}</span>}{t.definition.title}</h2><p className="text-sm text-muted-foreground">{names(t.definition.assignees) || (t.definition.assignment === "rotation" ? "Rotacioni Nala" : "Përgjegjësi ende nuk është caktuar")} · {frequencies[t.definition.frequency]}{t.definition.due_time ? ` · ${t.definition.due_time.slice(0, 5)}` : " · Pa orar"}</p><span className={`inline-block rounded-full px-2 py-0.5 text-xs ${t.definition.enabled && !t.archived ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200" : "bg-muted text-muted-foreground"}`}>{t.archived ? "Arkivuar" : t.definition.enabled ? "Aktive" : "Pret konfigurim"}</span></div>
            {t.can_manage && <div className="flex gap-2"><Button variant="outline" size="sm" onClick={() => edit(t)}>Ndrysho</Button><Button variant="ghost" size="sm" disabled={busy} onClick={() => void run(async () => {
              await request(`/templates/${t.id}/archive`, { method: "POST", body: JSON.stringify({ expected_version: t.version, archived: !t.archived }) }); await load()
            })}>{t.archived ? "Rikthe" : "Arkivo"}</Button></div>}
          </article>)}</div>}
          {tab === "history" && <section className="space-y-2 rounded-xl border p-4"><h2 className="mb-3 font-semibold">Veprimet e fundit</h2>{!history.length && <p className="text-sm text-muted-foreground">Ende pa veprime.</p>}{history.map((e) => <div key={e.id} className="flex flex-wrap justify-between gap-2 border-b py-3 text-sm"><span>{e.kind === "status_changed" ? `${statuses[e.payload.from as GaStatus] || e.payload.from} → ${statuses[e.payload.to as GaStatus] || e.payload.to}` : ({ occurrence_updated: "Ora ose përgjegjësi u ndryshua", template_created: "Model i krijuar", template_updated: "Model i ndryshuar", template_archived: "Model i arkivuar", template_restored: "Model i rikthyer", generated: "Detyrat e datës u përgatitën", auto_generated: "Detyrat u krijuan automatikisht", arrived: "Ardhja në shtëpi u regjistrua", automation_enabled: "Krijimi automatik u aktivizua", automation_disabled: "Krijimi automatik u ndal" }[e.kind] || "Veprim i ruajtur")}</span><time className="text-muted-foreground">{new Date(e.created_at).toLocaleString("sq")}</time></div>)}</section>}
          {tab === "settings" && <div className="grid gap-4 md:grid-cols-2">{workspace.is_admin && <DeviceSettingsPanel request={request} />}{workspace.is_admin && <DiscordSettingsPanel request={request} onSaved={load} />}<section className="space-y-3 rounded-xl border p-5"><h2 className="font-semibold">Hapësira private</h2><p className="text-sm">Zona kohore: Europe/Belgrade</p><p className="text-sm">Rotacioni Nala: {workspace.config.nala_rotation?.notes || workspace.config.rotation_anchor || "Ende pa datë fillestare"}</p><p className="text-sm">Krijimi automatik i detyrave: {workspace.config.automatic_generation?.enabled ? "Aktiv" : "Joaktiv"}</p>{workspace.is_admin && <Button variant="outline" disabled={busy} onClick={() => void run(async () => {
              await request("/automation", { method: "PUT", body: JSON.stringify({ enabled: !workspace.config.automatic_generation?.enabled }) }); await load()
            })}>{workspace.config.automatic_generation?.enabled ? "Ndalo krijimin automatik" : "Aktivizo krijimin automatik"}</Button>}<p className="text-sm text-muted-foreground">Kujtesa në Discord: {workspace.discord.connected ? "I lidhur" : "Jashtë linje"}. Njoftimet: {workspace.discord.messages_enabled ? "Të lejuara" : "Të ndaluara"}. Për Lirzën, kujtesat personale i shkojnë Ganës.</p></section>
            {workspace.is_admin && <section className="space-y-4 rounded-xl border p-5"><h2 className="font-semibold">Importo modelet</h2><Input aria-label="Dataset-i i modeleve" type="file" accept="application/json,.json" onChange={(e) => { const file = e.target.files?.[0]; if (!file) return; void run(async () => {
              if (file.size > 2 * 1024 * 1024) throw new Error("Skedari duhet të jetë deri në 2 MB.")
              const data = JSON.parse(await file.text()) as Record<string, unknown>; setImportData(data)
              setPreview(await request<ImportPreview>("/import/preview", { method: "POST", body: JSON.stringify({ dataset: data }) }))
            }) }} />{preview && <div className="space-y-2 text-sm"><p>{preview.templates} modele · {preview.steps} hapa ndihmës</p><p>{preview.create.length} shtohen · {preview.update?.length || 0} përditësohen · {preview.archive?.length || 0} arkivohen · {preview.unchanged.length} të pandryshuara · {preview.conflicts.length} konflikte</p>{preview.unresolved_members.length > 0 && <p>Pa lidhje: {preview.unresolved_members.join(", ")}</p>}<Button disabled={busy || !!preview.conflicts.length || !!preview.unresolved_members.length} onClick={() => void run(async () => {
              await request("/import/apply", { method: "POST", body: JSON.stringify({ dataset: importData, expected_hash: preview.dataset_hash }) }); await load(); toast.success("Modelet u importuan. Orët e sugjeruara nuk u aktivizuan."); setPreview(null); setImportData(null)
            })}>Importo pas kontrollit</Button></div>}</section>}
          </div>}
        </>}
    <Dialog open={!!draft && !!workspace} onOpenChange={(open) => { if (!open) setDraft(null) }}><DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl"><DialogHeader><DialogTitle>{editing ? "Ndrysho detyrën" : "Detyrë e re"}</DialogTitle></DialogHeader>
      {draft && workspace && <form onSubmit={save} className="space-y-4">
        {error && <p role="alert" className="rounded-md bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
        {editing && <p className="rounded-lg bg-muted/50 p-3 text-sm text-muted-foreground">Këtu ndryshon përsëritjen për detyrat e ardhshme. Për orën ose përgjegjësin e një detyre tashmë të krijuar, përdor “Ndrysho” te kartela e saj.</p>}
        <label className="block space-y-1 text-sm"><span>Titulli</span><Input required maxLength={200} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
        <label className="block space-y-1 text-sm"><span>Përshkrimi</span><Textarea value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></label>
        <label className="block space-y-1 text-sm"><span>Kujtesat në Discord</span><select aria-label="Kujtesat në Discord" className={fieldClass} value={draft.discord_destination || "dm"} onChange={(e) => setDraft({ ...draft, discord_destination: e.target.value as Definition["discord_destination"] })}><option value="dm">Mesazh privat</option><option value="channel">Kanali i familjes</option><option value="off">Pa njoftim</option></select></label>
        {workspace.is_admin && <label className="block space-y-1 text-sm"><span>Caktimi</span><select className={fieldClass} value={draft.assignment} onChange={(e) => { const assignment = e.target.value as Definition["assignment"]; setDraft({ ...draft, assignment, assignees: assignment === "fixed" ? [workspace.person_key] : [], rotation_id: assignment === "rotation" ? "nala" : null }) }}><option value="fixed">Persona të zgjedhur</option><option value="rotation">Rotacioni Nala</option><option value="first_home">Kush mbërrin i pari</option><option value="unassigned">Pa përgjegjës ende</option></select></label>}
        {draft.assignment === "fixed" && <fieldset className="space-y-2"><legend className="text-sm">Përgjegjësit</legend><div className="flex flex-wrap gap-4">{workspace.members.map((m) => <label key={m.person_key} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.assignees.includes(m.person_key)} disabled={!workspace.is_admin} onChange={(e) => setDraft({ ...draft, assignees: e.target.checked ? [...draft.assignees, m.person_key] : draft.assignees.filter((p) => p !== m.person_key) })} />{m.name}</label>)}</div></fieldset>}
        {draft.assignees.length > 1 && <label className="block space-y-1 text-sm"><span>Kryerja</span><select className={fieldClass} value={draft.completion_mode} onChange={(e) => setDraft({ ...draft, completion_mode: e.target.value as Definition["completion_mode"] })}><option value="individual">Secili e kryen veçmas</option><option value="shared">Një punë e përbashkët</option></select></label>}
        <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1 text-sm"><span>Përsëritja</span><select className={fieldClass} value={draft.frequency} onChange={(e) => setDraft({ ...draft, frequency: e.target.value as Definition["frequency"], enabled: false, weekdays: [] })}>{Object.entries(frequencies).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><label className="space-y-1 text-sm"><span>Grupi</span><select className={fieldClass} value={draft.reminder_group} onChange={(e) => setDraft({ ...draft, reminder_group: e.target.value as Definition["reminder_group"] })}>{Object.entries(groups).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
        <div className="grid gap-3 sm:grid-cols-2">{draft.frequency === "once" && <label className="space-y-1 text-sm"><span>Data</span><Input type="date" value={draft.on_date || ""} onChange={(e) => setDraft({ ...draft, on_date: e.target.value || null })} /></label>}<label className="space-y-1 text-sm"><span>Ora</span><Input type="time" value={draft.due_time?.slice(0, 5) || ""} onChange={(e) => setDraft({ ...draft, due_time: e.target.value || null })} /></label><label className="space-y-1 text-sm"><span>Kohëzgjatja (opsionale, minuta)</span><Input type="number" min={1} max={1440} value={draft.estimated_minutes || ""} onChange={(e) => setDraft({ ...draft, estimated_minutes: e.target.value ? Number(e.target.value) : null })} /></label></div>
        {["weekly", "near_daily", "school_day"].includes(draft.frequency) && <fieldset><legend className="mb-2 text-sm">Ditët</legend><div className="flex flex-wrap gap-3">{["Hën", "Mar", "Mër", "Enj", "Pre", "Sht", "Die"].map((label, i) => <label key={i} className="flex items-center gap-1 text-sm"><input type="checkbox" disabled={draft.frequency === "weekly" && i < 5} checked={draft.weekdays.includes(i)} onChange={(e) => setDraft({ ...draft, weekdays: e.target.checked ? [...draft.weekdays, i] : draft.weekdays.filter((v) => v !== i) })} />{label}</label>)}</div></fieldset>}
        <label className="block space-y-1 text-sm"><span>Hapat ndihmës (një për rresht)</span><Textarea rows={4} value={stepsText} onChange={(e) => setStepsText(e.target.value)} /></label>
        {!!draft.schedule_hints?.length && <div className="rounded-md bg-muted p-3 text-xs text-muted-foreground"><p className="mb-1 font-medium">Orari nga materiali burimor — për konfirmim</p>{draft.schedule_hints.map((hint, i) => <p key={i}>{(hint.suggested_start_time || hint.start_time)?.slice(0, 5)}{(hint.suggested_end_time || hint.end_time) ? `–${(hint.suggested_end_time || hint.end_time)!.slice(0, 5)}` : ""} {hint.notes}</p>)}</div>}
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.readiness === "ready_after_setup"} onChange={(e) => setDraft({ ...draft, readiness: e.target.checked ? "ready_after_setup" : "needs_confirmation", enabled: false })} />Udhëzimet janë të konfirmuara</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />Krijo detyrat sipas kësaj përsëritjeje</label>
        <p className="text-xs text-muted-foreground">Tiku vlen vetëm për ditën ose periudhën e detyrës. Hapat janë ndihmë; nuk duhen shënuar një nga një.</p>
        <Button type="submit" disabled={busy}>Ruaje detyrën</Button>
      </form>}
    </DialogContent></Dialog>
    <QuickEditDialog row={quick} template={templates.find((t) => t.id === quick?.template_id)} workspace={workspace} busy={busy} error={error} onClose={() => { setQuick(null); setError("") }} onSave={(values) => void saveQuick(values)} onEditTemplate={(row) => edit(row)} />
    <Dialog open={!!deferred && !!workspace} onOpenChange={(open) => { if (!open) setDeferred(null) }}><DialogContent><DialogHeader><DialogTitle>Kur të përshtatet?</DialogTitle></DialogHeader>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}<label className="space-y-2 text-sm"><span>Data dhe ora sipas pajisjes tënde</span><Input type="datetime-local" value={deferTime} onChange={(e) => setDeferTime(e.target.value)} /></label><Button disabled={busy || !deferTime} onClick={() => deferred && void action(deferred, "rescheduled", new Date(deferTime).toISOString())}>Shtyje detyrën</Button></DialogContent></Dialog>
  </div>
}
