"use client"

import * as React from "react"
import Link from "next/link"
import { RecorderPanel } from "@/components/meeting-recordings/recorder-panel"
import { useRecorder } from "@/components/meeting-recordings/recorder-provider"
import { Button } from "@/components/ui/button"
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
  const load = React.useCallback(async () => {
    setLoading(true)
    try { setRows(await recordingJson(await apiFetch(`/meeting-recordings?offset=${offset}&limit=50`, { cache: "no-store" }))); setError("") }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setLoading(false) }
  }, [apiFetch, offset])
  React.useEffect(() => { void load() }, [load, savedId, saving])
  return <div className="mx-auto max-w-6xl space-y-6">
    <div><h1 className="text-2xl font-semibold">Regjistrimet e takimeve</h1><p className="text-sm text-muted-foreground">Regjistroni ekranin dhe audion, pastaj hapni bibliotekën tuaj private.</p></div>
    <RecorderPanel />
    <Card><CardHeader className="flex flex-row items-center justify-between"><CardTitle>Historiku i regjistrimeve</CardTitle><Button variant="outline" disabled={loading} onClick={() => void load()}>Rifresko</Button></CardHeader>
      <CardContent className="space-y-4">
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr className="border-b"><th className="p-2">Titulli / takimi</th><th className="p-2">Data / autori</th><th className="p-2">Kohëzgjatja</th><th className="p-2">Madhësia</th><th className="p-2">Statusi</th><th className="p-2">Veprimet</th></tr></thead>
          <tbody>{rows.map(row => <tr key={row.id} className="border-b align-top">
            <td className="p-2"><Link className="font-medium underline" href={`/meeting-recordings/${row.id}`}>{row.title}</Link>{row.meeting_title && <p className="text-muted-foreground">{row.meeting_title}</p>}</td>
            <td className="p-2">{new Date(row.created_at).toLocaleString("sq-AL")}<p className="text-muted-foreground">{row.recorded_by_name}</p></td>
            <td className="p-2 tabular-nums">{row.duration_seconds == null ? "—" : recordingTime(row.duration_seconds)}</td><td className="p-2">{recordingSize(row.size_bytes)}</td>
            <td className="p-2">{RECORDING_STATUS[row.status]}{row.is_partial && <p className="text-amber-700">Pjesë e rikuperuar</p>}{row.error_message && <p className="max-w-64 text-destructive">{row.error_message}</p>}</td>
            <td className="space-y-2 p-2"><Link className="underline" href={`/meeting-recordings/${row.id}`}>{row.status === "READY" ? "Luaj / shkarko" : "Detajet"}</Link>
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
