"use client"

import { meetingTranslator } from "@/lib/meeting-notes-language"

import * as React from "react"
import { useAuth } from "@/lib/auth"
import { meetingClientLabel } from "@/lib/meeting-client-label"

export type MeetingClientSelection = { id: string | null; name: string }

export function MeetingClientPicker({ id, value, onChange, onCommit, disabled = false, english = false }: {
  english?: boolean
  id: string
  value: MeetingClientSelection | null
  onChange: (value: MeetingClientSelection | null) => void
  onCommit?: (value: MeetingClientSelection) => void
  disabled?: boolean
}) {
  const t = meetingTranslator(english)
  const { apiFetch } = useAuth()
  const [clients, setClients] = React.useState<{ id: string; name: string }[]>([])
  const [error, setError] = React.useState("")
  const refresh = React.useCallback(async () => {
    try {
      const response = await apiFetch("/meeting-notes/clients", { cache: "no-store" })
      if (!response.ok) throw new Error(t("Lista e klientëve nuk u ngarkua."))
      setClients(await response.json())
      setError("")
    } catch { setError(t("Lista e klientëve nuk u ngarkua. Provo ta hapësh sërish zgjedhjen.")) }
  }, [apiFetch, t])
  React.useEffect(() => { void refresh() }, [refresh, value?.id])

  const options = value?.id && !clients.some((client) => client.id === value.id)
    ? [...clients, { id: value.id, name: value.name }]
    : clients
  return <div className="space-y-2">
    <select id={id} aria-label={t("Klienti")} title={value?.name || t("Klienti")} disabled={disabled} value={value ? value.id || "new" : "none"} onFocus={() => void refresh()}
      onChange={(event) => {
        const selected = event.target.value
        if (selected === "none") onChange(null)
        else if (selected === "new") onChange({ id: null, name: "" })
        else onChange(options.find((client) => client.id === selected) || null)
      }} className="h-9 w-full rounded-md border bg-background px-3 text-sm">
      <option value="none">{t("Pa klient")}</option>
      {[...options].sort((a, b) => meetingClientLabel(a.name).localeCompare(meetingClientLabel(b.name), "sq") || a.name.localeCompare(b.name, "sq"))
        .map((client) => <option key={client.id} value={client.id} title={client.name}>{meetingClientLabel(client.name)}</option>)}
      <option value="new">{t("+ Shto klient të ri")}</option>
    </select>
    {value && !value.id && <input aria-label={t("Emri i klientit të ri")} value={value.name} onChange={(event) => onChange({ id: null, name: event.target.value })}
      onBlur={() => { if (value.name.trim()) onCommit?.(value) }}
      onKeyDown={(event) => { if (onCommit && event.key === "Enter") { event.preventDefault(); event.currentTarget.blur() } }}
      maxLength={200} required placeholder={t("Emri i klientit, p.sh. Kettler")} disabled={disabled} className="h-9 w-full rounded-md border bg-background px-3 text-sm" />}
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
  </div>
}
