"use client"

import * as React from "react"
import { AudioLines, Loader2, Mic, MicOff, Send, Square } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { useVoiceAssistant } from "@/lib/useVoiceAssistant"

export function VoiceAssistant() {
  const [open, setOpen] = React.useState(false)
  const [text, setText] = React.useState("")
  const [viewport, setViewport] = React.useState<{ height: number; top: number } | null>(null)
  const { phase, messages, error, muted, audioBlocked, audioRef, start, stop, sendText, toggleMute, resumeAudio } = useVoiceAssistant()
  const chat = React.useRef<HTMLDivElement>(null)
  const followBottom = React.useRef(true)
  const lastUser = React.useRef<string | undefined>(undefined)
  const connected = phase !== "idle" && phase !== "connecting"

  React.useEffect(() => {
    const latestUser = [...messages].reverse().find(message => message.role === "user")?.id
    if (latestUser !== lastUser.current) {
      lastUser.current = latestUser
      followBottom.current = true
    }
    const frame = window.requestAnimationFrame(() => {
      if (chat.current && followBottom.current) chat.current.scrollTop = chat.current.scrollHeight
    })
    return () => window.cancelAnimationFrame(frame)
  }, [messages, open, viewport?.height])

  React.useEffect(() => {
    const screen = window.visualViewport
    if (!open || !screen) return
    const update = () => setViewport({ height: screen.height, top: screen.offsetTop })
    const frame = window.requestAnimationFrame(update)
    screen.addEventListener("resize", update)
    screen.addEventListener("scroll", update)
    return () => {
      window.cancelAnimationFrame(frame)
      screen.removeEventListener("resize", update)
      screen.removeEventListener("scroll", update)
    }
  }, [open])

  function submit(event: React.FormEvent) {
    event.preventDefault()
    followBottom.current = true
    if (sendText(text)) setText("")
  }

  return (
    <Sheet open={open} onOpenChange={next => { setOpen(next); if (!next) { stop(); setViewport(null) } }}>
      <SheetTrigger asChild>
        <Button variant="outline" size="sm" title="Mira" aria-label="Hap asistenten zanore Mira">
          <AudioLines className="size-4" /><span className="hidden sm:inline">Mira</span>
        </Button>
      </SheetTrigger>
      <SheetContent style={viewport ? { height: viewport.height, top: viewport.top, bottom: "auto" } : undefined} className="h-dvh max-h-dvh w-full overflow-hidden sm:max-w-lg gap-0 p-0 [&>button]:size-11 [&>button]:flex [&>button]:items-center [&>button]:justify-center [&>button]:top-1 [&>button]:right-1">
        <SheetHeader className="shrink-0 border-b px-4 py-4">
          <SheetTitle className="text-base">Mira</SheetTitle>
          <SheetDescription className="sr-only">Chat me asistenten zanore.</SheetDescription>
        </SheetHeader>

        <div ref={chat} onScroll={() => {
          const element = chat.current
          if (element) followBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 60
        }} className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 [overflow-anchor:none]" role="log" aria-label="Biseda me Mirën" aria-live="polite">
          <div className="space-y-3">
            {messages.map(message => (
              <div key={message.id} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[90%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${message.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted"}`}>
                  <span className="sr-only">{message.role === "user" ? "Ti: " : "Mira: "}</span>
                  <p className="whitespace-pre-wrap break-words" aria-busy={message.pending}>{message.pending ? "…" : message.text}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="shrink-0 space-y-3 border-t bg-background p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
          {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
          <div className="flex gap-2">
            <Button className="h-11 flex-1" variant={phase === "idle" || audioBlocked ? "default" : "outline"} onClick={() => {
              if (audioBlocked) void resumeAudio()
              else if (phase === "idle") void start()
              else stop()
            }}>
              {phase === "connecting" ? <Loader2 className="size-4 animate-spin" /> : phase === "idle" || audioBlocked ? <Mic className="size-4" /> : <Square className="size-4" />}
              {phase === "idle" || audioBlocked ? "Start" : "Stop"}
            </Button>
            <Button className="h-11 flex-1" variant="outline" disabled={!connected} onClick={toggleMute} aria-pressed={muted}>
              {muted ? <MicOff className="size-4" /> : <Mic className="size-4" />}{muted ? "Unmute" : "Mute"}
            </Button>
          </div>
          <form onSubmit={submit} className="flex items-center gap-2">
            <Input className="h-11" value={text} onChange={event => setText(event.target.value)} maxLength={2000} placeholder="Shkruaj…" aria-label="Kërkesa për Mirën" />
            <Button type="submit" size="icon" className="size-11 shrink-0" disabled={!connected || !text.trim()} aria-label="Dërgo kërkesën"><Send className="size-4" /></Button>
          </form>
        </div>
        <audio ref={audioRef} autoPlay className="hidden" aria-label="Zëri i Mirës" />
      </SheetContent>
    </Sheet>
  )
}
