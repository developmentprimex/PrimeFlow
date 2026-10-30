"use client"

import * as React from "react"
import Link from "next/link"
import { RecorderPanel } from "@/components/meeting-recordings/recorder-panel"
import { useRecorder } from "@/components/meeting-recordings/recorder-provider"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuth } from "@/lib/auth"
import { recordingJson } from "@/lib/recording-outbox"
import { RECORDING_STATUS, recordingSize, recordingTime, type MeetingRecording } from "@/lib/recording-types"

export default function MeetingRecordingsPage() {
  const { apiFetch, user } = useAuth()
  const { savedId, saving, manifest, discard } = useRecorder()
  const [rows, setRows] = React.useState<MeetingRecording[]>([])
  const [error, setError] = React.useState("")
  const [offset, setOffset] = React.useState(0)
  const [loading, setLoading] = React.useState(true)
  const [deletingId, setDeletingId] = React.useState<string | null>(null)
  const [editingId, setEditingId] = React.useState<string | null>(null)
  const [editTitle, setEditTitle] = React.useState("")
  const [savingTitle, setSavingTitle] = React.useState(false)
  const [titleError, setTitleError] = React.useState("")
  const canDelete = user?.role === "ADMIN"
  const canManage = canDelete || user?.role === "MANAGER"
  const load = React.useCallback(async () => {
    setLoading(true)
    try { setRows(await recordingJson(await apiFetch(`/meeting-recordings?offset=${offset}&limit=50`, { cache: "no-store" }))); setError("") }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [apiFetch, offset])
  async function saveTitle(row: MeetingRecording) {
    const title = editTitle.trim()
    if (!title || savingTitle) return
    setSavingTitle(true)
    setTitleError("")
    try {
      const updated: MeetingRecording = await recordingJson(await apiFetch(`/meeting-recordings/${row.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }),
      }))
      setRows(current => current.map(item => item.id === row.id ? updated : item))
      setEditingId(null)
    } catch { setTitleError("Titulli nuk u ruajt. Provoni përsëri.") }
    finally { setSavingTitle(false) }
  }
  async function removeRecording(row: MeetingRecording) {
    if (!canDelete) return
    if (!window.confirm(`Fshi përgjithmonë regjistrimin “${row.title}”, përfshirë videon në FILES? Fshirja nuk mund të zhbëhet.`)) return
    setDeletingId(row.id)
    try {
      const response = await apiFetch(`/meeting-recordings/${row.id}`, { method: "DELETE" })
      if (!response.ok) await recordingJson(response)
      setRows(current => current.filter(item => item.id !== row.id))
      await load()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setDeletingId(null) }
  }
  React.useEffect(() => {
    const timer = window.setTimeout(() => { void load() }, 0)
    return () => window.clearTimeout(timer)
  }, [load, savedId, saving])
  return <div className="w-full space-y-6">
    <h1 className="text-2xl font-semibold">Regjistrimet e takimeve</h1>
    <RecorderPanel />
    <Card><CardHeader className="flex flex-row items-center justify-between"><CardTitle>Historiku i regjistrimeve</CardTitle><Button variant="outline" disabled={loading} onClick={() => void load()}>Rifresko</Button></CardHeader>
      <CardContent className="space-y-4">
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <div className="overflow-x-auto rounded-md border"><table aria-label="Historiku i regjistrimeve" className="w-full border-collapse text-left text-sm [&_th]:border-r [&_th]:px-3 [&_th]:py-3 [&_th:last-child]:border-r-0 [&_td]:border-r [&_td]:px-3 [&_td]:py-2 [&_td:last-child]:border-r-0"><thead className="bg-muted/70"><tr className="border-b"><th scope="col" className="w-14 text-center">Nr.</th><th scope="col">Titulli / takimi</th><th scope="col">Data / autori</th><th scope="col">Kohëzgjatja</th><th scope="col">Madhësia</th><th scope="col">Statusi</th><th scope="col">Veprimet</th></tr></thead>
          <tbody>{rows.map((row, index) => <tr key={row.id} className="border-b align-top last:border-b-0 even:bg-muted/20 hover:bg-muted/40">
            <td className="text-center tabular-nums text-muted-foreground">{offset + index + 1}</td>
            <td className="p-2">{editingId === row.id ? <form className="min-w-56 space-y-2" onSubmit={event => { event.preventDefault(); void saveTitle(row) }}>
              <Input aria-label="Titulli i regjistrimit" value={editTitle} onChange={event => setEditTitle(event.target.value)} maxLength={200} required autoFocus disabled={savingTitle} />
              <div className="flex gap-2"><Button size="sm" type="submit" disabled={savingTitle || !editTitle.trim()}>{savingTitle ? "Duke ruajtur…" : "Ruaj"}</Button><Button size="sm" type="button" variant="outline" disabled={savingTitle} onClick={() => setEditingId(null)}>Anulo</Button></div>
              {titleError && <p role="alert" className="text-sm text-destructive">{titleError}</p>}
            </form> : <Link className="font-medium underline" href={`/meeting-recordings/${row.id}`}>{row.title}</Link>}{row.meeting_title && <p className="text-muted-foreground">{row.meeting_title}</p>}</td>
            <td className="p-2">{new Date(row.created_at).toLocaleString("sq-AL")}<p className="text-muted-foreground">{row.recorded_by_name}</p></td>
            <td className="p-2 tabular-nums">{row.duration_seconds == null ? "—" : recordingTime(row.duration_seconds)}</td><td className="p-2">{recordingSize(row.size_bytes)}</td>
            <td className="p-2">{row.media_available === false ? <span className="text-destructive">Skedari nuk është i arritshëm</span> : RECORDING_STATUS[row.status]}{row.is_partial && <p className="text-amber-700">Pjesë e rikuperuar</p>}{row.error_message && <p className="max-w-64 text-destructive">{row.error_message}</p>}</td>
            <td className="space-y-2 p-2"><Button asChild size="sm" variant="outline"><Link href={`/meeting-recordings/${row.id}`}>Open</Link></Button>
              {(canManage || row.created_by === user?.id) && <Button size="sm" variant="outline" className="ml-2" disabled={savingTitle || deletingId !== null} onClick={() => { setEditingId(row.id); setEditTitle(row.title); setTitleError("") }}>Edit</Button>}
              {canDelete && ["READY", "FAILED"].includes(row.status) && <Button size="sm" variant="destructive" className="ml-2" disabled={deletingId !== null || row.id === manifest?.id} onClick={() => void removeRecording(row)}>{deletingId === row.id ? "Deleting…" : "Delete"}</Button>}
              {row.created_by === user?.id && row.id !== manifest?.id && !["READY", "FAILED"].includes(row.status) && <Button size="sm" variant="ghost" disabled={saving} onClick={async () => {
                if (!window.confirm("Braktis këtë sesion të papërfunduar? Mos e përdorni për një regjistrim aktiv në një pajisje tjetër.")) return
                await discard(row.id)
                await load()
              }}>Braktis</Button>}
            </td>
          </tr>)}</tbody>
        </table></div>
        {!rows.length && !loading && !error && <p className="py-4 text-center text-sm text-muted-foreground">Nuk ka regjistrime ende.</p>}
        {loading && <p role="status" className="text-sm">Duke ngarkuar…</p>}
        <div className="flex gap-2"><Button variant="outline" disabled={loading || offset === 0} onClick={() => setOffset(n => Math.max(0, n - 50))}>Mbrapa</Button><Button variant="outline" disabled={loading || rows.length < 50} onClick={() => setOffset(n => n + 50)}>Tjetër</Button></div>
      </CardContent>
    </Card>
  </div>
}
