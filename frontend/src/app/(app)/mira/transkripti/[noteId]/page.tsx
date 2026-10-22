"use client"

import * as React from "react"
import { useParams } from "next/navigation"
import { useAuth } from "@/lib/auth"
import { clock, json, minutesBetween, type NoteTranscript } from "@/lib/mira"

// The silent recorder's transcript behind a Mira note, opened from PX Notes.
export default function MiraNoteTranscriptPage() {
  const { noteId } = useParams<{ noteId: string }>()
  const { apiFetch } = useAuth()
  const [transcript, setTranscript] = React.useState<NoteTranscript | null>(null)
  const [error, setError] = React.useState("")

  React.useEffect(() => {
    void (async () => {
      try {
        setTranscript(await json<NoteTranscript>(await apiFetch(`/mira/notes/${noteId}/transcript`)))
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      }
    })()
  }, [apiFetch, noteId])

  const minutes = transcript ? minutesBetween(transcript.started_at, transcript.stopped_at) : null
  const day = transcript?.started_at ? new Date(transcript.started_at).toLocaleDateString("sq-AL") : null
  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8 md:px-8">
      <header className="mb-6 flex items-center gap-3">
        <img src="/mira-avatar.png" alt="Mira" className="h-12 w-12 shrink-0 rounded-full border-2 border-violet-300" />
        <div className="min-w-0">
          <h1 className="text-[22px] font-semibold tracking-tight">Transkripti i takimit</h1>
          {transcript && (
            <p className="mt-1 text-sm text-muted-foreground">
              {transcript.title}
              {day && ` · ${day}`} · {clock(transcript.started_at)}–{clock(transcript.stopped_at)}
              {minutes !== null && ` · ${minutes} min`}
            </p>
          )}
        </div>
      </header>

      {error ? (
        <p className="py-16 text-center text-sm text-muted-foreground">{error}</p>
      ) : !transcript ? (
        <p className="py-16 text-center text-sm text-muted-foreground">Duke hapur transkriptin…</p>
      ) : transcript.passages.length === 0 ? (
        <p className="py-16 text-center text-sm text-muted-foreground">Në këtë takim nuk u dëgjua të folur i kuptueshëm.</p>
      ) : (
        <>
          {transcript.partial && (
            <p className="mb-4 text-xs text-muted-foreground">Regjistrimi nuk është i plotë: disa pjesë të takimit mungojnë.</p>
          )}
          <ol className="divide-y">
            {transcript.passages.map((passage, index) => (
              <li key={index} className="grid gap-1 py-3 text-sm sm:grid-cols-[6.5rem_9rem_1fr] sm:gap-3">
                <span className="text-xs tabular-nums text-muted-foreground">{passage.time}</span>
                <span className="truncate text-xs font-semibold">{passage.speaker}</span>
                <span className="leading-relaxed">{passage.text}</span>
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  )
}
