"use client"

import * as React from "react"
import Link from "next/link"
import { AudioLines, Check, Loader2, Mic, MicOff, PhoneOff, Send, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { useVoiceAssistant } from "@/lib/useVoiceAssistant"

const phases = { idle: "Gati për të ndihmuar", connecting: "Po lidhem…", listening: "Po të dëgjoj", thinking: "Po mendoj…", speaking: "Mira po flet", working: "Po punoj…" }
const examples = ["Çfarë detyra kam në 1H të orës 10?", "Çfarë më ka mbetur për sot?", "Ma mbyll detyrën…", "Bëje strike pikën e dytë te…"]
const plain = (text: string) => text.replace(/\[\[\/?[^\]]+\]\]/g, "").replace(/<[^>]+>/g, " ")

export function VoiceAssistant() {
  const [open, setOpen] = React.useState(false)
  const [text, setText] = React.useState("")
  const [viewport, setViewport] = React.useState<{ height: number; top: number } | null>(null)
  const { phase, messages, tasks, error, muted, activity, audioBlocked, audioRef, start, stop, sendText, toggleMute } = useVoiceAssistant()
  const bottom = React.useRef<HTMLDivElement>(null)
  const connected = phase !== "idle" && phase !== "connecting"

  React.useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }) }, [messages, activity])

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
    if (sendText(text)) setText("")
  }

  return (
    <Sheet open={open} onOpenChange={next => { setOpen(next); if (!next) { stop(); setViewport(null) } }}>
      <SheetTrigger asChild>
        <Button variant="outline" size="sm" title="Fol me Mirën, asistenten e detyrave" aria-label="Hap asistenten zanore Mira">
          <AudioLines className="size-4" /><span className="hidden sm:inline">Mira</span>
        </Button>
      </SheetTrigger>
      <SheetContent style={viewport ? { height: viewport.height, top: viewport.top, bottom: "auto" } : undefined} className="h-dvh max-h-dvh w-full overflow-hidden sm:max-w-lg gap-0 p-0 [&>button]:size-11 [&>button]:flex [&>button]:items-center [&>button]:justify-center [&>button]:top-1 [&>button]:right-1">
        <SheetHeader className="border-b p-5">
          <SheetTitle className="flex items-center gap-2"><Sparkles className="size-5 text-primary" /> Mira <span className="rounded-full bg-muted px-2 py-1 text-[10px] font-normal tracking-wide">ASISTENTJA JOTE</span></SheetTitle>
          <SheetDescription>Bisedo në shqip. Gjej, mbyll dhe përditëso detyrat me zë.</SheetDescription>
        </SheetHeader>

        <div className="border-b bg-muted/25 px-5 py-5">
          <div className="flex items-center gap-4">
            <div className={`flex size-14 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary ${phase === "speaking" ? "motion-safe:animate-pulse" : ""}`}>
              {phase === "connecting" || phase === "working" ? <Loader2 className="size-6 animate-spin" /> : <AudioLines className="size-7" />}
            </div>
            <div className="min-w-0 flex-1">
              <p className="font-medium" role="status">{activity || (muted && connected ? "Mikrofoni është i heshtur" : phases[phase])}</p>
              <p className="mt-1 text-xs text-muted-foreground">{connected ? "Mund të më ndërpresësh kur të duash." : "Zë femëror · Bisedë e drejtpërdrejtë"}</p>
            </div>
          </div>
          <div className="mt-4 flex gap-2">
            {phase === "idle" ? <Button className="h-12 flex-1 text-base" onClick={() => void start()}><Mic className="size-5" /> Fillo bisedën</Button> : <>
              <Button variant="outline" className="h-12 flex-1" disabled={!connected} onClick={toggleMute} aria-pressed={muted}>
                {muted ? <MicOff className="size-4" /> : <Mic className="size-4" />}{muted ? "Aktivizo mikrofonin" : "Hesht mikrofonin"}
              </Button>
              <Button variant="destructive" className="h-12" onClick={stop}><PhoneOff className="size-4" /> Mbyll</Button>
            </>}
          </div>
          {error && <p className="mt-3 text-sm text-destructive" role="alert">{error}</p>}
          <audio ref={audioRef} autoPlay controls={audioBlocked} className={connected && audioBlocked ? "mt-3 h-8 w-full" : "hidden"} aria-label="Zëri i Mirës" />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {messages.length === 0 && <div className="space-y-3">
            <p className="text-sm text-muted-foreground">Provo të thuash…</p>
            {examples.map((example, index) => <button key={example} type="button" className={`${index > 1 ? "hidden sm:block" : "block"} w-full rounded-xl border px-4 py-3 text-left text-sm transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring`} onClick={() => setText(example)}>{example}</button>)}
            <p className="pt-2 text-xs leading-relaxed text-muted-foreground">Mira përdor lejet e llogarisë sate dhe të pyet kur detyra është e paqartë. Audioja përpunohet nga OpenAI. Përgjigjet gjenerohen nga AI.</p>
          </div>}
          <div className="space-y-4" role="log" aria-label="Biseda me Mirën">
            {messages.map(m => m.role === "activity"
              ? <div key={m.id} className="flex gap-2 rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground"><Check className="size-4 shrink-0" /><span>{m.text}</span></div>
              : <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}><div className={`max-w-[90%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${m.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted"}`}><p className="mb-1 text-[10px] font-semibold uppercase opacity-60">{m.role === "user" ? "Ti" : "Mira"}</p><p className="whitespace-pre-wrap">{m.text}</p></div></div>)}
          </div>
          {tasks.length > 0 && <div className="mt-5 space-y-2 rounded-xl border p-3">
            <p className="text-xs text-muted-foreground">Detyrat nga përgjigjja e fundit</p>
            {tasks.map((task, index) => <Link key={task.id} href={`/tasks/${task.id}`} onClick={() => { stop(); setOpen(false) }} className="block rounded-lg p-2 text-sm hover:bg-muted">
              <span className="text-muted-foreground">{index + 1}. </span>{plain(task.title)}<span className="mt-1 block text-[11px] text-muted-foreground">{task.one_h_report_slot ? `1H ${task.one_h_report_slot} · ` : ""}{task.status === "DONE" ? "E përfunduar" : "E hapur"}</span>
            </Link>)}
          </div>}
          <div ref={bottom} />
        </div>

        <form onSubmit={submit} className="flex shrink-0 gap-2 border-t bg-background p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
          <Input value={text} onChange={e => setText(e.target.value)} maxLength={2000} placeholder={connected ? "Ose shkruaje kërkesën…" : "Fillo bisedën për të vazhduar…"} aria-label="Kërkesa për Mirën" />
          <Button type="submit" size="icon" className="size-11 shrink-0" disabled={!connected || !text.trim()} aria-label="Dërgo kërkesën"><Send className="size-4" /></Button>
        </form>
      </SheetContent>
    </Sheet>
  )
}
