"use client"

import { meetingTranslator } from "@/lib/meeting-notes-language"

import * as React from "react"
import Link from "next/link"
import { Search } from "lucide-react"
import { useAuth } from "@/lib/auth"
import { dmy, isoDate, KIND_LABEL, readError, userInitials, userName, type MeetingKind, type MeetingOverviewRow } from "@/lib/meeting-notes"
import { isIncludedOverviewMeeting, isOptionalOverviewMeeting } from "@/lib/meeting-notes-overview"
import { meetingClientLabel } from "@/lib/meeting-client-label"
import { isRecurringOverviewMeeting, meetingOverviewDateTime } from "@/lib/meeting-overview-columns"
import { useUsersMap } from "@/components/meeting-notes/use-lookups"
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
  const users = useUsersMap()
  const [rows, setRows] = React.useState<MeetingOverviewRow[]>([])
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState("")
  const [tab, setTab] = React.useState<Tab>("ALL")
  const [query, setQuery] = React.useState("")
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
  const scopedRows = includedRows.filter((row) => !isOptionalOverviewMeeting(row.meeting))
  const clients = [...new Map(includedRows.filter((row) => row.meeting.client_id && row.meeting.client_name)
    .map((row) => [row.meeting.client_id!, row.meeting.client_name!] as const)).entries()]
    .sort((a, b) => meetingClientLabel(a[1]).localeCompare(meetingClientLabel(b[1]), "sq") || a[1].localeCompare(b[1], "sq"))
  const clientRows = clientFilter ? scopedRows.filter((row) => row.meeting.client_id === clientFilter) : scopedRows
  const visible = clientRows.filter((row) => {
    if (tab !== "ALL" && row.kind !== tab) return false
    if (!search) return true
    const client = row.meeting.client_name || ""
    return `${row.meeting.title} ${client} ${meetingClientLabel(client)}`.toLocaleLowerCase("sq").includes(search)
  })
  const count = (key: Tab) => clientRows.filter((row) => key === "ALL" || row.kind === key).length

  return <div className="w-full min-w-0 space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-2xl font-semibold">{t("Takimet")}</h1>
      <Button asChild><Link href="/meeting-scheduler">{t("+ Takim i ri")}</Link></Button>
    </div>

    <div className="flex flex-wrap items-center gap-3">
      <div role="tablist" aria-label={t("Lloji i takimit")} className="grid w-96 max-w-full shrink-0 grid-cols-4 gap-0.5 rounded-xl bg-muted p-[3px]">
        {TABS.map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
          className={`h-[30px] rounded-[9px] px-2 text-sm font-medium whitespace-nowrap ${tab === key ? "bg-white text-foreground shadow-sm" : "text-neutral-600"}`}>
          {t(label)} <span className="text-muted-foreground">{count(key)}</span>
        </button>)}
      </div>
      <label className="flex h-9 min-w-[240px] items-center gap-2 rounded-md border px-3">
        <Search className="size-4 text-muted-foreground" aria-hidden="true" />
        <input type="search" aria-label={t("Kërko takim ose klient")} placeholder={t("Kërko takim ose klient…")} value={query} onChange={(e) => setQuery(e.target.value)} className="min-w-0 flex-1 bg-transparent text-sm outline-none" />
      </label>
    </div>

    <div className="flex flex-wrap items-center gap-3">
    <label className="flex items-center gap-2 text-sm">
      {t("Klienti")}
      <select aria-label={t("Filtro sipas klientit")} title={clients.find(([id]) => id === clientFilter)?.[1] || t("Të gjithë klientët")} value={clientFilter} onChange={(event) => setClientFilter(event.target.value)} className="h-9 min-w-52 rounded-md border bg-background px-3">
        <option value="">{t("Të gjithë klientët")}</option>
        {clients.map(([id, name]) => <option key={id} value={id} title={name}>{meetingClientLabel(name)}</option>)}
      </select>
    </label>
    </div>

    {error && <p role="alert" className="text-sm text-destructive">{t(error)}</p>}
    {loading ? <p role="status" className="text-sm text-muted-foreground">{t("Duke ngarkuar…")}</p> : <div className="overflow-x-auto rounded-md border-2 border-slate-700 bg-white">
      <table className="w-full min-w-[1200px] border-collapse text-sm">
        <thead><tr>
          <th className={`${th} w-10`}>{t("NR")}</th><th className={th}>{t("TAKIMI")}</th>
          <th className={`${th} w-44`}>{t("DATA / ORA")}</th>
          <th className={`${th} w-40`}>{t("PJESËMARRËSIT")}</th>
          <th className={`${th} w-28`}>{t("SHËNIME TË HAPURA")}</th>
          <th className={`${th} w-20`}>{t("LLOJI")}</th>
          <th className={`${th} w-28`}>{t("KLIENTI")}</th><th className={`${th} w-32`}>{t("E RADHËS")}</th><th className={`${th} w-[210px]`}>{t("DETYRAT")}</th>
        </tr></thead>
        <tbody>{visible.map((row, index) => {
          const client = row.meeting.client_name
          const isToday = row.next_session === today
          const participants = [...new Set(row.meeting.participant_ids || [])]
          return <tr key={row.meeting.id} className={isToday ? "bg-slate-50" : undefined}>
            <td className={`${td} font-bold text-muted-foreground`}>{index + 1}</td>
            <td className={td}>
              <Link href={`/meetings/${row.meeting.id}`} className="font-semibold underline underline-offset-[3px]">{row.meeting.title}</Link>
              <div className="mt-0.5 text-xs text-muted-foreground">{frequency(row)}</div>
            </td>
            <td className={`${td} whitespace-nowrap tabular-nums`}>{meetingOverviewDateTime(row)}</td>
            <td className={td}>{participants.length ? <span title={participants.map((id) => userName(users, id)).join(", ")}>
              {participants.map((id) => userInitials(users, id)).join(", ")}
            </span> : <span className="text-neutral-400">—</span>}</td>
            <td className={`${td} text-center tabular-nums`}><Link href={`/meetings/${row.meeting.id}`} aria-label={`${t("SHËNIME TË HAPURA")}: ${row.counts.open_notes}`} className="underline underline-offset-2">{row.counts.open_notes}</Link></td>
            <td className={td}>{KIND_LABEL[row.kind]}</td>
            <td className={td}>{client && row.meeting.client_id
              ? <button type="button" onClick={() => setClientFilter(row.meeting.client_id!)} className="text-left underline underline-offset-2" aria-label={`${meetingClientLabel(client)} (${client})`} title={`${client} · ${t("Shfaq takimet e këtij klienti")}`}>{meetingClientLabel(client)}</button>
              : client ? <span title={client}>{meetingClientLabel(client)}</span> : <span className="text-neutral-400">—</span>}</td>
            <td className={`${td} font-semibold tabular-nums`}>{isRecurringOverviewMeeting(row) ? isToday ? row.kind === "EXTERNAL" ? "Today" : "Sot" : dmy(row.next_session) : <span className="font-normal text-neutral-400">—</span>}</td>
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
