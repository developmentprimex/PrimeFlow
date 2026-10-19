"use client"

import { Loader2, Mic, MicOff, Square } from "lucide-react"
import { Button } from "@/components/ui/button"

type Props = {
  phase: string; muted: boolean; error: string; audioBlocked: boolean
  onStart: () => void; onStop: () => void; onMute: () => void; onResume: () => void
}

export function PxNotesMiraControls({ phase, muted, error, audioBlocked, onStart, onStop, onMute, onResume }: Props) {
  const active = phase !== "idle"
  return <div className="flex max-w-full flex-wrap items-center gap-2" aria-label="Mira për PX Notes">
    <Button type="button" size="sm" className="h-11 gap-2" variant={active ? "default" : "outline"}
      onMouseDown={event => event.preventDefault()} onClick={audioBlocked ? onResume : active ? onStop : onStart}>
      {phase === "connecting" || phase === "working" ? <Loader2 className="size-4 animate-spin" /> : active ? <Square className="size-4" /> : <Mic className="size-4" />}
      {active && !audioBlocked ? "Stop" : "Mira · Start"}
    </Button>
    {active && <Button type="button" size="sm" className="h-11 gap-2" variant="outline" onMouseDown={event => event.preventDefault()}
      disabled={phase === "connecting"} onClick={onMute} aria-pressed={muted}>
      {muted ? <MicOff className="size-4" /> : <Mic className="size-4" />}{muted ? "Unmute" : "Mute"}
    </Button>}
    {active && phase !== "connecting" && <span className="text-xs text-muted-foreground" role="status">{muted ? "Në heshtje" : phase === "working" ? "Po shkruaj…" : "Po dëgjoj…"}</span>}
    {error && <p className="w-full text-xs text-destructive" role="alert">{error}</p>}
  </div>
}
