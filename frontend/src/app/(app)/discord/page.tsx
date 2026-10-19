"use client"

import * as React from "react"
import { AlarmClock, Bot, CalendarPlus, CheckCircle2, Copy, ExternalLink, ListChecks, MessageCircle, MessageSquare, ShieldCheck, Unplug } from "lucide-react"
import { toast } from "sonner"
import { useAuth } from "@/lib/auth"
import { Button } from "@/components/ui/button"

type Connection = {
  configured: boolean
  linked: boolean
  channel_id: string | null
  guild_id: string | null
  timezone: string
  schedule: { bucket: string; at: string }[]
}

const FEATURES = [
  {
    icon: ListChecks,
    title: "Detyrat e ditës",
    points: [
      "/detyrat shfaq detyrat e sotme me numra; kliko numrin për ta hapur.",
      "Karta hapet në të njëjtin mesazh: statusi, sloti, afati dhe të gjitha pikat, edhe ato të bëra strike.",
      "◀ ▶ lëvizin mes detyrave, ↩ Lista kthehet te lista.",
      "Më shumë: edito, koment, slot/AM–PM, konfirmim, To Do/WFE, teksti i plotë.",
    ],
  },
  {
    icon: CheckCircle2,
    title: "Mbyllja me një klik",
    points: [
      "Mbylle bën strike të gjitha pikat poshtë titullit dhe e mbyll detyrën.",
      "Nëse detyra nuk ka koment, shtohet vetë komenti “Kryer”.",
      "Pas mbylljes hapet vetë detyra tjetër.",
      "Për koment tjetër: Më shumë → Mbylle me koment.",
    ],
  },
  {
    icon: MessageCircle,
    title: "Shkruaj lirshëm",
    points: [
      "Shkruaj si në bisedë: mbylle, bëji strike pikat, ktheje në To Do, shto koment.",
      "“Këtë detyrë” = detyra në ekran; “detyra 2” = numri në listë; ose përmend titullin.",
      "Rezultati shfaqet si karta e përditësuar e detyrës.",
      "Kur nuk është e qartë, boti pyet dhe ti përgjigjesh shkurt.",
    ],
  },
  {
    icon: AlarmClock,
    title: "Raportimi i sloteve 1H",
    points: [
      "10 min para çdo sloti merr kujtesë vetëm për detyrat e atij sloti.",
      "Fillo raportimin: ✅ U krye / 🟡 Vazhdon / ⏸ WFE / ⏭ Kalo, një klik për detyrë.",
      "Shëno të kryerat mbyll disa detyra njëherësh.",
      "Butoni 🎧 Kyçu në takimin 1H të fut direkt në kanalin zanor 1H.",
    ],
  },
  {
    icon: CalendarPlus,
    title: "Takimet",
    points: [
      "Kujtesë në Discord para takimeve ku je pjesëmarrës, me linkun e takimit.",
      "Te TAK INT, kur fillon takimi, boti të thërret me 🎧 Hyr në kanalin zanor.",
      "Krijo takim nga chat-i: “krijo tak int për nesër ora 15 me unë, endi, rinesa”.",
      "Para ruajtjes kontrollon kartën dhe kliko ✅ Krijo takimin.",
    ],
  },
  {
    icon: Bot,
    title: "Agjenti AI",
    points: [
      "Më shumë → Delegoja agjentit: hulumtim në internet ose draft teksti për një detyrë ose pikë.",
      "Rezultatet AI ruajnë historikun; prano rezultatin ose kërko ndryshime.",
      "Prano dhe shëno pikën të kryer e bën strike pikën përkatëse.",
    ],
  },
]

const EXAMPLES = [
  "mbylle këtë detyrë",
  "detyra 2, bëji strike pikën 2 dhe 4",
  "hiq strike nga pika 3",
  "bëje WFE dhe shto komentin: presim përgjigjen e klientit",
  "ktheje REMPP në to do",
  "ndrysho slotin në 14:20",
  "dërgoje për konfirmim te Elsa",
  "krijo tak int për nesër ora 15 me unë, endi, rinesa, gane",
  "krijo tak ext të enjten 10:30 me klientin Bali, linku https://teams…",
]

const STATUS_LEGEND = [
  { label: "To Do", color: "#FFC4ED" },
  { label: "Në progres", color: "#FFFF00" },
  { label: "WFE", color: "#E2C15B" },
  { label: "Në konfirmim", color: "#FFEDD5" },
  { label: "E kryer", color: "#C4FDC4" },
]

export default function DiscordAssistantPage() {
  const { apiFetch } = useAuth()
  const [connection, setConnection] = React.useState<Connection | null>(null)
  const [code, setCode] = React.useState<{ command: string; expires_at: string } | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState("")
  const [expired, setExpired] = React.useState(false)

  const refresh = React.useCallback(async () => {
    try {
      const response = await apiFetch("/discord/me")
      if (!response.ok) throw new Error("Lidhja me Discord nuk mund të lexohet.")
      setConnection(await response.json())
      setError("")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Gabim gjatë leximit të lidhjes.")
    }
  }, [apiFetch])

  React.useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const response = await apiFetch("/discord/me")
        if (!response.ok) throw new Error("Lidhja me Discord nuk mund të lexohet.")
        const data: Connection = await response.json()
        if (!cancelled) { setConnection(data); setError("") }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Gabim gjatë leximit të lidhjes.")
      }
    }
    void load()
    return () => { cancelled = true }
  }, [apiFetch])
  React.useEffect(() => {
    if (!code) return
    const timer = window.setTimeout(() => setExpired(true), Math.max(0, new Date(code.expires_at).getTime() - Date.now()))
    return () => window.clearTimeout(timer)
  }, [code])

  async function generateCode() {
    setBusy(true)
    try {
      const response = await apiFetch("/discord/link-code", { method: "POST" })
      const data = await response.json()
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Kodi nuk u gjenerua.")
      setCode(data)
      setExpired(false)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Kodi nuk u gjenerua.")
    } finally {
      setBusy(false)
    }
  }

  async function disconnect() {
    setBusy(true)
    try {
      const response = await apiFetch("/discord/link", { method: "DELETE" })
      if (!response.ok) throw new Error("Shkëputja nuk u krye.")
      setCode(null)
      await refresh()
      toast.success("Discord u shkëput. Asistenti nuk mund të veprojë më për llogarinë tënde.")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Shkëputja nuk u krye.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-4 md:p-8">
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-indigo-50 p-3 text-indigo-600"><MessageSquare className="size-6" /></div>
        <div>
          <h1 className="text-2xl font-semibold">Asistenti në Discord</h1>
          <p className="mt-1 text-sm text-muted-foreground">Menaxho detyrat, raportimin 1H dhe takimet nga kanali yt privat në Discord.</p>
        </div>
      </div>

      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</p>}
      {!connection && !error && <p role="status">Duke lexuar lidhjen…</p>}
      {connection && (
        <>
          <section className="space-y-4 rounded-xl border bg-card p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="font-semibold">Llogaria jote</h2>
              <span className={`rounded-full px-3 py-1 text-xs font-medium ${connection.linked ? "bg-green-50 text-green-700" : "bg-slate-100 text-slate-600"}`}>
                {connection.linked ? "E lidhur" : "E palidhur"}
              </span>
            </div>
            {!connection.configured && <p className="text-sm text-muted-foreground">Asistenti ende nuk është aktivizuar. Administratori duhet të konfigurojë serverin dhe botin Discord.</p>}
            {connection.configured && <p className="text-sm text-muted-foreground">Gjenero një kod dhe përdor komandën <code>/lidh</code> në serverin Discord të ekipit. Boti të krijon kanalin personal. Kodi përdoret një herë dhe skadon pas 10 minutash.</p>}
            <div className="flex flex-wrap gap-2">
              <Button disabled={busy || !connection.configured} onClick={generateCode}>{busy ? "Duke përpunuar…" : "Gjenero kod lidhjeje"}</Button>
              <Button variant="outline" onClick={refresh} disabled={busy}>Rifresko lidhjen</Button>
              {connection.linked && <Button variant="outline" onClick={disconnect} disabled={busy}><Unplug className="mr-2 size-4" />Shkëput Discord</Button>}
              {connection.linked && connection.channel_id && <Button asChild variant="outline"><a href={`https://discord.com/channels/${connection.guild_id}/${connection.channel_id}`} target="_blank" rel="noreferrer"><ExternalLink className="mr-2 size-4" />Hap kanalin</a></Button>}
            </div>
            {code && <div className="space-y-2 rounded-lg bg-muted p-4">
              <p className="text-sm">{expired ? "Kodi ka skaduar. Gjenero një të ri." : "Kopjoje dhe përdore në Discord:"}</p>
              {!expired && <>
                <code className="block break-all text-sm">{code.command}</code>
                <Button variant="outline" size="sm" onClick={async () => {
                  try { await navigator.clipboard.writeText(code.command); toast.success("Komanda u kopjua.") }
                  catch { toast.error("Kopjoje komandën manualisht.") }
                }}><Copy className="mr-2 size-4" />Kopjo komandën</Button>
              </>}
            </div>}
          </section>

          <section className="rounded-xl border bg-card p-6">
            <h2 className="mb-4 font-semibold">Kur të pyet asistenti</h2>
            <p className="mb-4 text-sm text-muted-foreground">Nga e hëna në të premte, sipas zonës {connection.timezone}.</p>
            <table className="w-full text-left text-sm">
              <thead><tr className="border-b"><th className="py-2">Ora e pyetjes</th><th>Për detyrat</th></tr></thead>
              <tbody>{connection.schedule.map(row => <tr className="border-b last:border-0" key={row.bucket}><td className="py-2 tabular-nums">{row.at}</td><td>{["AM", "PM"].includes(row.bucket) ? row.bucket : `Sloti ${row.bucket}`}</td></tr>)}</tbody>
            </table>
          </section>

          <section className="space-y-4">
            <div>
              <h2 className="font-semibold">Çfarë mund të bësh me asistentin</h2>
              <p className="mt-1 text-sm text-muted-foreground">Përdor butonat ose shkruaj lirshëm në kanalin tënd. Të dyja ndryshojnë PrimeFlow me të njëjtat rregulla dhe leje.</p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {FEATURES.map(feature => (
                <div key={feature.title} className="space-y-2 rounded-xl border bg-card p-5 text-sm">
                  <div className="flex items-center gap-2 font-semibold"><feature.icon className="size-4 text-indigo-600" />{feature.title}</div>
                  <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
                    {feature.points.map(point => <li key={point}>{point}</li>)}
                  </ul>
                </div>
              ))}
            </div>
          </section>

          <section className="space-y-3 rounded-xl border bg-card p-6 text-sm">
            <h2 className="font-semibold">Shembuj për t’i shkruar në kanal</h2>
            <p className="text-muted-foreground">Asistenti e gjen detyrën nga mesazhi i fundit i botit (lista, kujtesa ose karta). Mund të bësh edhe <strong>Reply</strong> te mesazhi i detyrës. Kliko një shembull për ta kopjuar.</p>
            <div className="flex flex-wrap gap-2">
              {EXAMPLES.map(example => (
                <button key={example} type="button" className="rounded-full border bg-muted/50 px-3 py-1.5 text-left hover:bg-muted"
                  onClick={async () => {
                    try { await navigator.clipboard.writeText(example); toast.success("U kopjua.") }
                    catch { toast.error("Kopjoje manualisht.") }
                  }}>{example}</button>
              ))}
            </div>
          </section>

          <section className="space-y-3 rounded-xl border bg-card p-6 text-sm">
            <h2 className="font-semibold">Ngjyrat e statusit</h2>
            <div className="flex flex-wrap gap-4">
              {STATUS_LEGEND.map(status => (
                <span key={status.label} className="flex items-center gap-2">
                  <span className="size-3.5 rounded-full border border-black/10" style={{ backgroundColor: status.color }} />{status.label}
                </span>
              ))}
            </div>
          </section>

          <section className="space-y-2 rounded-xl border bg-card p-6 text-sm">
            <h2 className="flex items-center gap-2 font-semibold"><ShieldCheck className="size-4 text-indigo-600" />Siguria dhe kufijtë</h2>
            <p>Asistenti vepron vetëm mbi detyrat e tua, me lejet që ke në PrimeFlow. Kur kërkesa nuk është e qartë, të pyet para çdo ndryshimi. Çdo ndryshim regjistrohet në historik si në PrimeFlow.</p>
            <p>Fotot dhe skedarët në chat nuk lexohen. Takimet me përsëritje dhe TAK EXT me TAK INT të lidhur krijohen ende në PrimeFlow.</p>
            <p className="text-muted-foreground">Kanalet janë private për anëtarët e tjerë. Pronari dhe administratorët e serverit Discord mund t’i shohin ato.</p>
          </section>
        </>
      )}
    </div>
  )
}
