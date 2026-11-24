"use client"

import * as React from "react"
import { Minus, Plus, RefreshCw } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { useAuth } from "@/lib/auth"

type MailMessage = { id: string; subject: string; sender: string; received_at: string; body: string }
type MailResult = { configured: boolean; connected: boolean; messages: MailMessage[]; error?: string; notes_error?: string }

const mailboxes = {
  "info-px": { label: "INFO PX", provider: "Outlook" },
  it: { label: "EM IT", provider: "Outlook" },
  "px-eu": { label: "EM PX EU", provider: "Gmail" },
  hf: { label: "EM HF", provider: "Yandex" },
}

export function ReportMailbox({ reportDate, source }: { reportDate: string; source: keyof typeof mailboxes }) {
  const { label, provider } = mailboxes[source]
  const titlePrefix = source === "info-px" ? "EM INFO PX" : label
  const { apiFetch, user } = useAuth()
  const [result, setResult] = React.useState<MailResult | null>(null)
  const [expandedMessageId, setExpandedMessageId] = React.useState<string | null>(null)
  const [reload, setReload] = React.useState(0)
  const [loading, setLoading] = React.useState(false)
  const [connecting, setConnecting] = React.useState(false)

  React.useEffect(() => {
    const abort = new AbortController()
    setLoading(true)
    void apiFetch(`/microsoft-mail/sync?source=${source}&report_date=${encodeURIComponent(reportDate)}`, {
      method: "POST",
      signal: abort.signal,
      cache: "no-store",
    }).then(async (response) => {
      if (!response.ok || abort.signal.aborted) return
      const data: MailResult = await response.json()
      if (!abort.signal.aborted && typeof data.configured === "boolean") setResult(data)
    }).catch(() => {
      if (!abort.signal.aborted) toast.error(`Nuk u arrit lidhja me ${label}.`)
    }).finally(() => {
      if (!abort.signal.aborted) setLoading(false)
    })
    return () => abort.abort()
  }, [apiFetch, label, reload, reportDate, source])

  React.useEffect(() => {
    const url = new URL(window.location.href)
    const status = url.searchParams.get("outlook_mail")
    if (!status || (url.searchParams.get("outlook_source") || "info-px") !== source) return
    if (status === "connected") toast.success(`${label} u lidh me ${provider}.`)
    else toast.error(`Autorizimi për ${label} nuk u krye.`)
    url.searchParams.delete("outlook_mail")
    url.searchParams.delete("outlook_source")
    window.history.replaceState(window.history.state, "", url)
  }, [label, provider, source])

  const connect = async () => {
    setConnecting(true)
    try {
      const response = await apiFetch(`/microsoft-mail/authorize-url?source=${source}`, { method: "POST" })
      if (!response.ok) throw new Error()
      const { url } = await response.json()
      window.location.assign(url)
    } catch {
      toast.error(`Nuk u hap autorizimi për ${label}.`)
      setConnecting(false)
    }
  }

  if (!result?.configured) return null

  return (
    <div className="mt-3 overflow-hidden rounded-md border border-slate-200">
      <div className="flex items-center justify-between gap-2 bg-slate-50 px-3 py-2">
        <h3 className="text-sm font-semibold">{label} · {provider}</h3>
        <div className="flex gap-2">
          {(result.connected || source === "hf") && (
            <Button variant="outline" size="sm" disabled={loading} onClick={() => setReload(value => value + 1)}>
              <RefreshCw className={loading ? "animate-spin" : ""} /> Rifresko
            </Button>
          )}
          {source !== "hf" && user?.role === "ADMIN" && (!result.connected || result.error) && (
            <Button variant="outline" size="sm" disabled={connecting} onClick={() => void connect()}>
              {result.connected ? "Lidhe përsëri" : `Lidh ${provider}`}
            </Button>
          )}
        </div>
      </div>
      {result.notes_error && <p className="px-3 py-2 text-sm text-red-700" role="status">{result.notes_error}</p>}
      {result.error ? (
        <p className="px-3 py-2 text-sm text-red-700" role="status">{result.error}</p>
      ) : !result.connected || !result.messages.length ? (
        <p className="px-3 py-2 text-sm text-muted-foreground">
          {result.connected ? "Asnjë email për këtë datë." : `${label} ende nuk është lidhur me ${provider}.`}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full table-fixed text-left text-xs">
            <thead className="bg-slate-200">
              <tr>
                <th className="w-[26%] p-2 sm:w-40" scope="col">TITULLI</th>
                <th className="w-[28%] p-2 sm:w-48" scope="col">DËRGUESI</th>
                <th className="p-2" scope="col">PËRMBAJTJA</th>
                <th className="w-10" scope="col"><span className="sr-only">Emaili i plotë</span></th>
              </tr>
            </thead>
            <tbody>
              {result.messages.map(mail => {
                const expanded = expandedMessageId === mail.id
                return (
                  <React.Fragment key={mail.id}>
                    <tr className="border-t">
                      <td className="p-2 font-medium [overflow-wrap:anywhere]">{titlePrefix}: {mail.received_at}</td>
                      <td className="p-2 [overflow-wrap:anywhere]">{mail.sender}</td>
                      <td className="p-2 [overflow-wrap:anywhere]">{mail.subject}</td>
                      <td className="p-1">
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="size-8 focus-visible:ring-2 focus-visible:ring-ring"
                          aria-label={`${expanded ? "Mbyll" : "Hap"} emailin: ${mail.subject}`}
                          aria-expanded={expanded}
                          onClick={() => setExpandedMessageId(current => current === mail.id ? null : mail.id)}
                        >
                          {expanded ? <Minus aria-hidden="true" /> : <Plus aria-hidden="true" />}
                        </Button>
                      </td>
                    </tr>
                    {expanded && (
                      <tr className="border-t bg-slate-50">
                        <td colSpan={4} className="whitespace-pre-wrap p-3 [overflow-wrap:anywhere]">
                          {mail.body || "Ky email nuk ka tekst."}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
