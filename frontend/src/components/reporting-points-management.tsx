"use client"

import * as React from "react"
import { useAuth } from "@/lib/auth"
import { reportResponseJson } from "@/lib/report-response"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"

export type DeliveryRecipients = { to: string[]; cc: string[]; bcc: string[] }
export type DeliverySettings = {
  report_type: "M1" | "M2" | "M3"; is_active: boolean; send_time: string; weekdays: number[]
  timezone: string; recipients: DeliveryRecipients; manual_recipients: DeliveryRecipients
}
type EditableSettings = Omit<DeliverySettings, "recipients" | "manual_recipients"> & {
  recipients: Record<keyof DeliveryRecipients, string>
  manual_recipients: Record<keyof DeliveryRecipients, string>
}
const DAYS = ["E hënë", "E martë", "E mërkurë", "E enjte", "E premte", "E shtunë", "E diel"]
const ADDRESS_FIELDS = ["to", "cc", "bcc"] as const
const inputClass = "mt-1 h-9 w-full rounded-md border border-input bg-white px-3 text-sm disabled:opacity-50"

export function splitRecipientAddresses(value: string): string[] {
  return Array.from(new Set(value.split(/[,;\n]+/).map((address) => address.trim().toLowerCase()).filter(Boolean)))
}

function editSettings(settings: DeliverySettings): EditableSettings {
  const addresses = (value: DeliveryRecipients) => ({ to: value.to.join(", "), cc: value.cc.join(", "), bcc: value.bcc.join(", ") })
  return { ...settings, recipients: addresses(settings.recipients), manual_recipients: addresses(settings.manual_recipients) }
}

export function ReportingPointsManagement({ api, reportType, canManage, onRecipientsChange, children }: {
  api: string; reportType: "M1" | "M2" | "M3"; canManage: boolean
  onRecipientsChange: (value: DeliveryRecipients) => void; children: React.ReactNode
}) {
  const { apiFetch } = useAuth()
  const [saved, setSaved] = React.useState<DeliverySettings | null>(null)
  const [draft, setDraft] = React.useState<EditableSettings | null>(null)
  const [saving, setSaving] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [message, setMessage] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (!canManage) return
    let active = true
    apiFetch(`${api}/settings`, { cache: "no-store" }).then(reportResponseJson<DeliverySettings>).then((value) => {
      if (!active) return
      setSaved(value); setDraft(editSettings(value)); setError(null)
      onRecipientsChange(value.manual_recipients)
    }).catch((reason: Error) => { if (active) setError(reason.message) })
    return () => { active = false }
  }, [apiFetch, api, canManage, onRecipientsChange])

  const dirty = !!saved && !!draft && JSON.stringify(editSettings(saved)) !== JSON.stringify(draft)
  const change = (update: Partial<EditableSettings>) => {
    setDraft((previous) => previous ? { ...previous, ...update } : previous)
    setMessage(null)
  }
  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!draft || saving) return
    const addresses = (value: Record<keyof DeliveryRecipients, string>): DeliveryRecipients => ({
      to: splitRecipientAddresses(value.to), cc: splitRecipientAddresses(value.cc), bcc: splitRecipientAddresses(value.bcc),
    })
    const recipients = addresses(draft.recipients)
    const manual = addresses(draft.manual_recipients)
    if ([...Object.values(recipients).flat(), ...Object.values(manual).flat()].some((address) => !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address))) {
      setError("Kontrollo adresat e email-it. Ndaji marrësit me presje.")
      return
    }
    if (!draft.weekdays.length || !recipients.to.length || !manual.to.length) {
      setError("Zgjidh të paktën një ditë dhe një marrës To për secilin dërgim.")
      return
    }
    setSaving(true); setError(null); setMessage(null)
    try {
      const value = await reportResponseJson<DeliverySettings>(await apiFetch(`${api}/settings`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: draft.is_active, send_time: draft.send_time, weekdays: draft.weekdays,
          recipients, manual_recipients: manual }),
      }))
      setSaved(value); setDraft(editSettings(value)); onRecipientsChange(value.manual_recipients)
      setMessage("Konfigurimi u ruajt. Dërgimet e ardhshme përdorin këto të dhëna.")
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Konfigurimi nuk u ruajt.")
    } finally { setSaving(false) }
  }

  const recipientFields = (kind: "recipients" | "manual_recipients") => draft ? <div className="grid gap-3 md:grid-cols-3">
    {ADDRESS_FIELDS.map((field) => {
      const id = `${reportType}-${kind}-${field}`
      return <div key={field}><Label htmlFor={id}>{field.toUpperCase()}{field === "to" ? " — Marrësit" : ""}</Label>
        <input id={id} type="text" autoComplete="off" required={field === "to"} value={draft[kind][field]}
          placeholder={field === "to" ? "email@primexeu.com" : "Opsionale"} className={inputClass}
          onChange={(event) => change({ [kind]: { ...draft[kind], [field]: event.target.value } })} />
      </div>
    })}
  </div> : null

  return <details className="group rounded-md border" data-report-management={reportType}>
    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 bg-slate-50 px-4 py-3 text-sm font-semibold [&::-webkit-details-marker]:hidden">
      <span className="flex items-center gap-3"><span aria-hidden="true" className="text-xl leading-none group-open:hidden">+</span>
        <span aria-hidden="true" className="hidden text-xl leading-none group-open:inline">−</span>Menaxhimi i raportit dhe email-it</span>
      {saved ? <span className="text-xs font-normal text-muted-foreground">{saved.is_active ? `Automatik ${saved.send_time}` : "Automatik i çaktivizuar"}</span> : null}
    </summary>
    <div className="space-y-5 p-4">
      {children}
      {canManage ? <form onSubmit={save} className="space-y-5 border-t pt-5">
        <h2 className="font-semibold">Konfigurimi i email-it {reportType}</h2>
        {error ? <p role="alert" className="rounded bg-red-50 p-3 text-sm text-red-800">{error}</p> : null}
        {!draft && !error ? <p className="text-sm text-muted-foreground">Duke ngarkuar konfigurimin…</p> : null}
        {draft ? <fieldset disabled={saving} className="space-y-5">
          <div className="flex flex-wrap items-end gap-5">
            <label className="flex min-h-9 items-center gap-2 text-sm font-medium"><input type="checkbox" checked={draft.is_active}
              onChange={(event) => change({ is_active: event.target.checked })} />Dërgim automatik aktiv</label>
            <div><Label htmlFor={`${reportType}-send-time`}>Ora e dërgimit automatik</Label>
              <input id={`${reportType}-send-time`} type="time" required value={draft.send_time} min={reportType === "M3" ? "16:15" : reportType === "M1" ? "08:30" : undefined}
                onChange={(event) => change({ send_time: event.target.value })} className={inputClass} /></div>
            <p className="pb-2 text-xs text-muted-foreground">Ora lokale: {draft.timezone}</p>
          </div>
          {reportType === "M3" ? <p className="text-xs text-muted-foreground">M3 mund të dërgohet automatikisht nga ora 16:15, pasi merret realizimi.</p> : null}
          {reportType === "M1" ? <p className="text-xs text-muted-foreground">M1 mund të dërgohet automatikisht nga ora 08:30. Plotëso komentet manuale para dërgimit.</p> : null}
          <fieldset className="space-y-2"><legend className="text-sm font-medium">Ditët e dërgimit automatik</legend>
            <div className="flex flex-wrap gap-3">{DAYS.map((label, day) => <label key={day} className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={draft.weekdays.includes(day)} onChange={(event) => change({ weekdays: event.target.checked
                ? [...draft.weekdays, day].sort((a, b) => a - b) : draft.weekdays.filter((value) => value !== day) })} />{label}</label>)}</div>
          </fieldset>
          <section className="space-y-3"><h3 className="text-sm font-semibold">Marrësit e dërgimit automatik</h3>{recipientFields("recipients")}</section>
          <section className="space-y-3"><h3 className="text-sm font-semibold">Marrësit e dërgimit manual</h3>{recipientFields("manual_recipients")}
            <p className="text-xs text-muted-foreground">Dërgimi manual mbetet i mundshëm edhe kur automatiku është i çaktivizuar.</p></section>
          <p className="text-xs text-muted-foreground">Ndaji adresat me presje. Email-i përfshin edhe Excel-in e raportit. Ruajtja e konfigurimit nuk dërgon email.</p>
          <p className="text-xs text-muted-foreground">Nëse raporti është dërguar automatikisht sot, konfigurimi i ri përdoret në dërgimin automatik të ardhshëm. Për ta dërguar sot përsëri, përdor Dërgo sërish.</p>
          <div className="flex flex-wrap items-center gap-3"><Button type="submit" disabled={!dirty || saving}>{saving ? "Duke ruajtur…" : "Ruaj konfigurimin"}</Button>
            {message ? <p role="status" className="text-sm text-green-800">{message}</p> : null}</div>
        </fieldset> : null}
      </form> : null}
    </div>
  </details>
}
