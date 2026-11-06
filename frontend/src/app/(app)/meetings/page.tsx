"use client"

import { meetingTranslator } from "@/lib/meeting-notes-language"

import * as React from "react"
import Link from "next/link"
import { Search } from "lucide-react"
import { useAuth } from "@/lib/auth"
import { dmy, isoDate, KIND_LABEL, readError, type MeetingKind, type MeetingOverviewRow } from "@/lib/meeting-notes"
import { isIncludedOverviewMeeting, isOptionalOverviewMeeting } from "@/lib/meeting-notes-overview"
import { StatusLegend } from "@/components/meeting-notes/status-legend"
import { Button } from "@/components/ui/button"

type Tab = "ALL" | MeetingKind
const TABS: [Tab, string][] = [["ALL", "Të gjitha"], ["EXTERNAL", "Eksterne"], ["INTERNAL", "Interne"], ["TRAINING", "Trajnime"]]
const th = "border border-slate-600 bg-white px-2 h-10 text-left align-bottom font-medium"
const td = "border border-slate-600 px-2 py-2.5 align-bottom"

function frequency(row: MeetingOverviewRow) {
  const type = (row.meeting.recurrence_type || "").toLowerCase()
  if (type === "weekly") return "Weekly"
  if (type === "monthly") return "Monthly"
  if (type === "yearly") return "Yearly"
  return row.kind === "EXTERNAL" ? "One-off" : "Njëherë"
}

function CountChip({ value, color }: { value: number; color: string }) {
  return <span className={`inline-flex h-[26px] min-w-[34px] items-center justify-center border border-slate-600 text-[13px] font-bold ${value > 0 ? color : "bg-white text-neutral-400"}`}>{value}</span>
}

export default function MeetingsPage() {
  const { apiFetch } = useAuth()
  const [rows, setRows] = React.useState<MeetingOverviewRow[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState("")
  const [tab, setTab] = React.useState<Tab>("ALL")
  const [query, setQuery] = React.useState("")
  const [showOptional, setShowOptional] = React.useState(false)
  const [clientFilter, setClientFilter] = React.useState("")
  const t = meetingTranslator(tab === "EXTERNAL")
  const today = isoDate(new Date())

  React.useEffect(() => {
    let active = true
    void apiFetch("/meeting-notes/overview", { cache: "no-store" }).then(async (response) => {
      if (!response.ok) throw new Error(await readError(response, "Takimet nuk u ngarkuan."))
      const data = (await response.json()) as MeetingOverviewRow[]
      if (active) { setRows(data); setError("") }
    }).catch((e) => { if (active) setError(e instanceof Error ? e.message : String(e)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [apiFetch])

  const search = query.trim().toLocaleLowerCase("sq")
  const includedRows = rows.filter((row) => isIncludedOverviewMeeting(row.meeting))
  const optionalCount = includedRows.filter((row) => isOptionalOverviewMeeting(row.meeting)).length
  const scopedRows = showOptional ? includedRows : includedRows.filter((row) => !isOptionalOverviewMeeting(row.meeting))
  const clients = [...new Map(includedRows.filter((row) => row.meeting.client_id && row.meeting.client_name)
    .map((row) => [row.meeting.client_id!, row.meeting.client_name!] as const)).entries()]
    .sort((a, b) => a[1].localeCompare(b[1], "sq"))
  const clientRows = clientFilter ? scopedRows.filter((row) => row.meeting.client_id === clientFilter) : scopedRows
  const visible = clientRows.filter((row) => {
    if (tab !== "ALL" && row.kind !== tab) return false
    if (!search) return true
    const client = row.meeting.client_name || ""
    return `${row.meeting.title} ${client}`.toLocaleLowerCase("sq").includes(search)
  })
  const count = (key: Tab) => clientRows.filter((row) => key === "ALL" || row.kind === key).length

  return <div className="w-full max-w-[1200px] space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-2xl font-semibold">{t("Takimet")}</h1>
      <Button asChild><Link href="/meeting-scheduler">{t("+ Takim i ri")}</Link></Button>
    </div>

    <div className="flex flex-wrap items-center justify-between gap-3">
      <div role="tablist" aria-label={t("Lloji i takimit")} className="inline-flex flex-wrap gap-0.5 rounded-xl bg-muted p-[3px]">
        {TABS.map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
          className={`h-[30px] rounded-[9px] px-3 text-sm font-medium ${tab === key ? "bg-white text-foreground shadow-sm" : "text-neutral-600"}`}>
          {t(label)} <span className="text-muted-foreground">{count(key)}</span>
        </button>)}
      </div>
      <label className="flex h-9 min-w-[240px] items-center gap-2 rounded-md border px-3">
        <Search className="size-4 text-muted-foreground" aria-hidden="true" />
        <input type="search" aria-label={t("Kërko takim ose klient")} placeholder={t("Kërko takim ose klient…")} value={query} onChange={(e) => setQuery(e.target.value)} className="flex-1 bg-transparent text-sm outline-none" />
      </label>
    </div>

    <div className="flex flex-wrap items-center justify-between gap-3">
    <label className="flex w-fit cursor-pointer items-center gap-2 text-sm">
      <input type="checkbox" checked={showOptional} onChange={(event) => setShowOptional(event.target.checked)} className="size-4 accent-slate-900" />
      <span>{t("Shfaq edhe eksterne fizike (të kaltra)")}{!loading && <span className="text-muted-foreground"> · {optionalCount}</span>}</span>
    </label>
    <label className="flex items-center gap-2 text-sm">
      {t("Klienti")}
      <select aria-label={t("Filtro sipas klientit")} value={clientFilter} onChange={(event) => setClientFilter(event.target.value)} className="h-9 min-w-52 rounded-md border bg-background px-3">
        <option value="">{t("Të gjithë klientët")}</option>
        {clients.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select>
    </label>
    </div>

    {error && <p role="alert" className="text-sm text-destructive">{t(error)}</p>}
    {loading ? <p role="status" className="text-sm text-muted-foreground">{t("Duke ngarkuar…")}</p> : <div className="overflow-x-auto rounded-md border-2 border-slate-700 bg-white">
      <table className="w-full min-w-[860px] border-collapse text-sm">
        <thead><tr>
          <th className={`${th} w-10`}>{t("NR")}</th><th className={th}>{t("TAKIMI")}</th><th className={`${th} w-20`}>{t("LLOJI")}</th>
          <th className={`${th} w-28`}>{t("KLIENTI")}</th><th className={`${th} w-32`}>{t("E RADHËS")}</th><th className={`${th} w-[210px]`}>{t("DETYRAT")}</th>
        </tr></thead>
        <tbody>{visible.map((row, index) => {
          const client = row.meeting.client_name
          const isToday = row.next_session === today
          return <tr key={row.meeting.id} className={isToday ? "bg-slate-50" : undefined}>
            <td className={`${td} font-bold text-muted-foreground`}>{index + 1}</td>
            <td className={td}>
              <Link href={`/meetings/${row.meeting.id}`} className="font-semibold underline underline-offset-[3px]">{row.meeting.title}</Link>
              <div className="mt-0.5 text-xs text-muted-foreground">{frequency(row)}{row.counts.open_notes ? ` · ${row.counts.open_notes} ${row.kind === "EXTERNAL" ? "open notes" : "shënime të hapura"}` : ""}</div>
            </td>
            <td className={td}>{KIND_LABEL[row.kind]}</td>
            <td className={td}>{client && row.meeting.client_id
              ? <button type="button" onClick={() => setClientFilter(row.meeting.client_id!)} className="text-left underline underline-offset-2" title={t("Shfaq takimet e këtij klienti")}>{client}</button>
              : client || <span className="text-neutral-400">—</span>}</td>
            <td className={`${td} font-semibold tabular-nums`}>{isToday ? row.kind === "EXTERNAL" ? "Today" : "Sot" : dmy(row.next_session)}</td>
            <td className="border border-slate-600 p-2 align-bottom"><div className="flex gap-1">
              <span title="TODO"><CountChip value={row.counts.TODO} color="bg-pink-200" /></span>
              <span title="IN PROGRESS"><CountChip value={row.counts.IN_PROGRESS} color="bg-yellow-200" /></span>
              <span title="WFE / WFC"><CountChip value={row.counts.WAITING} color="bg-[#E2C15B] text-[#4F3A00]" /></span>
              <span title="DONE"><CountChip value={row.counts.DONE} color="bg-emerald-200" /></span>
            </div></td>
          </tr>
        })}</tbody>
      </table>
      {!visible.length && <p className="p-4 text-center text-sm text-muted-foreground">{t("Nuk ka takime për këtë filtër.")}</p>}
    </div>}
    <StatusLegend withNotes={false} />
  </div>
}
