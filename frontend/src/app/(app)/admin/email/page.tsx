"use client"

import * as React from "react"
import { Mail, RefreshCw, Unplug } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/lib/auth"

type Connection = {
  configured: boolean
  authorized: boolean
  connected: boolean
  encryption_ready: boolean
  mailbox_email: string
  redirect_uri: string
  has_read_permissions: boolean
  last_checked_at: string | null
}
type Preview = {
  checked_at: string
  categories: { id: string; name: string; color: string | null }[]
  messages: {
    id: string; subject: string; sender_name: string | null; sender_email: string | null
    received_at: string | null; preview: string; categories: string[]; is_read: boolean
  }[]
}

const callbackMessages: Record<string, string> = {
  authorized: "Autorizimi u ruajt. Leximi ende nuk është verifikuar. Shtyp ‘Provo leximin’ për kategoritë dhe Inbox-in.",
  encryption_not_ready: "Çelësi i enkriptimit nuk është gati në server. Administratori duhet ta përgatisë para lidhjes.",
  unsupported_mailbox_type: "Microsoft nuk e identifikoi këtë si user mailbox. Administratori duhet të kontrollojë llojin në Exchange; shared mailbox kërkon rrjedhë tjetër autorizimi.",
  denied: "Lidhja nuk u miratua në Microsoft. Mund ta provosh përsëri.",
  wrong_account: "Zgjidh llogarinë e email-it të kompanisë të treguar më poshtë.",
  missing_permissions: "Mungojnë lejet për leximin e email-eve ose kategorive. Kontrollo lejet në Microsoft 365 dhe lidhu sërish.",
  invalid_state: "Kërkesa e lidhjes ka skaduar ose u hap nga një shfletues tjetër. Fillo lidhjen përsëri këtu.",
  microsoft_error: "Microsoft nuk e përfundoi lidhjen. Provo përsëri ose kontrollo konfigurimin e aplikacionit në Microsoft 365.",
}

async function readResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === "string" ? data.detail : "Kërkesa nuk u përfundua. Provo përsëri.")
  }
  return response.json() as Promise<T>
}

function displayDate(value: string | null) {
  if (!value) return "—"
  return new Intl.DateTimeFormat("sq-AL", { dateStyle: "short", timeStyle: "short" }).format(new Date(value))
}

export default function EmailConnectionPage() {
  const { user, apiFetch } = useAuth()
  const [connection, setConnection] = React.useState<Connection | null>(null)
  const [preview, setPreview] = React.useState<Preview | null>(null)
  const [busy, setBusy] = React.useState<string | null>(null)
  const [error, setError] = React.useState("")
  const [notice, setNotice] = React.useState("")
  const isAdmin = user?.role === "ADMIN"

  const load = React.useCallback(async () => {
    setConnection(await readResponse<Connection>(await apiFetch("/mailbox/status", { cache: "no-store" })))
  }, [apiFetch])

  React.useEffect(() => {
    if (!isAdmin) return
    let active = true
    const controller = new AbortController()
    const callback = new URLSearchParams(window.location.search).get("mailbox")
    const timer = window.setTimeout(() => {
      if (callback) {
        setNotice(callbackMessages[callback] || "Kontrollo gjendjen e lidhjes më poshtë.")
        const url = new URL(window.location.href)
        url.searchParams.delete("mailbox")
        window.history.replaceState(null, "", url)
      }
      void apiFetch("/mailbox/status", { cache: "no-store", signal: controller.signal })
        .then(readResponse<Connection>)
        .then(data => { if (active) setConnection(data) })
        .catch(err => { if (active) setError(err.message) })
    }, 0)
    return () => { active = false; controller.abort(); window.clearTimeout(timer) }
  }, [apiFetch, isAdmin])

  async function connect() {
    setBusy("connect"); setError(""); setPreview(null); setNotice("")
    try {
      const data = await readResponse<{ url: string }>(await apiFetch("/mailbox/authorize-url", { method: "POST" }))
      window.location.assign(data.url)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lidhja nuk u nis.")
      setBusy(null)
    }
  }

  async function testReading() {
    setBusy("test"); setError(""); setPreview(null); setNotice("")
    try {
      const data = await readResponse<Preview>(await apiFetch("/mailbox/test", { method: "POST", cache: "no-store" }))
      setPreview(data)
      await load()
    } catch (err) { setError(err instanceof Error ? err.message : "Prova nuk u përfundua.") }
    finally { setBusy(null) }
  }

  async function disconnect() {
    setBusy("disconnect"); setError(""); setPreview(null); setNotice("")
    try {
      await readResponse(await apiFetch("/mailbox/connection", { method: "DELETE" }))
      await load()
      setNotice("Lidhja e email-it u shkëput nga PrimeFlow.")
    } catch (err) { setError(err instanceof Error ? err.message : "Shkëputja nuk u përfundua.") }
    finally { setBusy(null) }
  }

  if (!user) return <div className="p-6">Duke ngarkuar…</div>
  if (!isAdmin) return <div className="p-6">Kjo faqe është vetëm për administratorin.</div>

  return <main className="mx-auto w-full max-w-6xl space-y-6 p-4 md:p-6">
    <header>
      <h1 className="flex items-center gap-2 text-2xl font-semibold"><Mail className="size-6" />Lidhja e email-it</h1>
      <p className="mt-2 text-sm text-muted-foreground">Hapi 1 · Leximi i email-eve dhe kategorive nga Microsoft 365.</p>
    </header>
    {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</div>}
    {notice && <div role="status" className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">{notice}</div>}
    <section className="space-y-4 rounded-xl border bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">{connection?.mailbox_email || "Microsoft 365"}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {!connection ? "Duke kontrolluar lidhjen…" : connection.authorized ? connection.connected ? "Autorizimi është ruajtur · leximi është verifikuar" : "Autorizimi është ruajtur · leximi ende nuk është verifikuar" : "Email-i ende nuk është autorizuar"}
          </p>
          {connection?.last_checked_at && <p className="mt-1 text-xs text-muted-foreground">Leximi i fundit i suksesshëm: {displayDate(connection.last_checked_at)}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button disabled={!connection?.configured || !connection?.encryption_ready || !!busy} onClick={() => void connect()}>
            {busy === "connect" ? "Duke hapur Microsoft…" : connection?.authorized ? "Lidhe sërish" : "Lidh Microsoft 365"}
          </Button>
          <Button variant="outline" disabled={!connection?.authorized || !connection?.encryption_ready || !!busy} onClick={() => void testReading()}>
            <RefreshCw className={busy === "test" ? "size-4 animate-spin" : "size-4"} />{busy === "test" ? "Duke lexuar…" : "Provo leximin"}
          </Button>
          {connection?.authorized && <Button variant="outline" disabled={!!busy} onClick={() => void disconnect()}><Unplug className="size-4" />Shkëput</Button>}
        </div>
      </div>
      <p className="text-sm text-muted-foreground">Qasje vetëm për lexim. Ky hap nuk ndryshon email-et ose kategoritë dhe nuk krijon PX Notes apo detyra.</p>
      {connection && !connection.configured && <p className="text-sm text-amber-800">Konfigurimi Microsoft mungon në server. Administratori duhet ta plotësojë para lidhjes.</p>}
      {connection && !connection.encryption_ready && <p className="text-sm text-amber-800">Çelësi i enkriptimit të email-it nuk është gati në server. Administratori duhet ta përgatisë para autorizimit.</p>}
      {connection?.authorized && !connection.has_read_permissions && <p className="text-sm text-amber-800">Lidhe sërish për të miratuar lejet e leximit.</p>}
      {connection && <details className="rounded-lg border p-3 text-sm">
        <summary className="cursor-pointer font-medium">Konfigurimi në Microsoft 365</summary>
        <p className="mt-3">Te App registrations → aplikacioni PrimeFlow → Authentication, shto këtë Web Redirect URI:</p>
        <code className="mt-2 block break-all rounded bg-slate-50 p-2 text-xs">{connection.redirect_uri}</code>
        <p className="mt-3">API permissions → Microsoft Graph → Delegated permissions: <code>User.Read</code>, <code>Mail.Read</code> dhe <code>MailboxSettings.Read</code>. Nëse organizata kërkon miratim nga administratori, plotësoje atë në Microsoft.</p>
      </details>}
    </section>
    {preview && <>
      <section className="space-y-3 rounded-xl border bg-white p-5">
        <h2 className="font-semibold">Kategoritë ekzistuese në email ({preview.categories.length})</h2>
        <div className="flex flex-wrap gap-2">{preview.categories.map(category => <span key={category.id} className="rounded-md border bg-slate-50 px-3 py-1 text-sm">{category.name}</span>)}</div>
        {!preview.categories.length && <p className="text-sm text-muted-foreground">Microsoft nuk ktheu kategori të përcaktuara për këtë mailbox.</p>}
      </section>
      <section className="overflow-hidden rounded-xl border bg-white">
        <div className="border-b p-5">
          <h2 className="font-semibold">Email-et e fundit në Inbox ({preview.messages.length})</h2>
          <p className="mt-1 text-xs text-muted-foreground">Provë e kryer më {displayDate(preview.checked_at)} · Deri në 10 mesazhe · Hapja e provës nuk i shënon si të lexuara.</p>
        </div>
        <div className="divide-y">{preview.messages.map(message => <article key={message.id} className="space-y-2 p-5">
          <div className="flex flex-wrap justify-between gap-2">
            <h3 className={message.is_read ? "text-sm font-medium" : "text-sm font-bold"}>{message.subject}</h3>
            <time className="text-xs text-muted-foreground">{displayDate(message.received_at)}</time>
          </div>
          <p className="break-words text-xs text-muted-foreground">{[message.sender_name, message.sender_email].filter(Boolean).join(" · ")}</p>
          <p className="whitespace-pre-wrap break-words text-sm text-slate-700">{message.preview}</p>
          <div className="flex flex-wrap gap-1">{message.categories.map(category => <span key={category} className="rounded border px-2 py-0.5 text-xs">{category}</span>)}</div>
        </article>)}</div>
        {!preview.messages.length && <p className="p-5 text-sm text-muted-foreground">Inbox-i nuk ka mesazhe.</p>}
      </section>
    </>}
  </main>
}
