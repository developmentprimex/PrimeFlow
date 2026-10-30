"use client"

import { BookOpen, ChevronDown, Info } from "lucide-react"

// Labels from GA-PERSONAL-DATASET-HANDOFF.md, section 2.
const sections = [
  ["Ditët", [["H", "Hënë"], ["M", "Martë"], ["MR", "Mërkurë"], ["E", "Enjte"], ["P", "Premte"], ["SH", "Shtunë"], ["D", "Diel"]]],
  ["Hapësirat", [["SHP", "Shtëpia"], ["KZH", "Kuzhina"], ["EN", "Zona e enëve"], ["KGJ", "Korridori i gjatë"], ["KM", "Korridori i madh"], ["KV", "Korridori i vogël"], ["KB", "Biblioteka"], ["KVB", "Korridori i bibliotekës"], ["DP", "Dhoma e pritjes"], ["TB", "Tavolina e bardhë"], ["BL", "Ballkoni"], ["DHGJ-R", "Dhoma e Rritës"], ["BP-R", "Banjoja e Rritës"], ["DHGJ-M", "Dhoma e Mrikës"], ["BP-M", "Banjoja e Mrikës"], ["DHGJ-L", "Dhoma e Lirzës"], ["BP-L", "Banjoja e Lirzës"]]],
  ["Prapashtesat e detyrave", [["-D", "Mirëmbajtje ditore"], ["-TH", "Deep clean / thellë"], ["-MS", "Para shkollës / mëngjes shkolle"]]],
  ["Shkurtesa speciale", [["NALA-M", "Nala mëngjes"], ["NALA-P", "Nala pasdite"], ["NALA-E", "Nala mbrëmje"], ["NALA-U", "Nala ushqim darke"], ["NALA-BL", "Nala ballkon"], ["NALA-RU", "Nala ujë Roki"], ["NALA-PG", "Nala përgatitje para gjumit"], ["NALA-5", "Nala 5 minuta personi i parë"], ["ROKI-1", "Roki programi 1"], ["ROKI-2", "Roki programi 2"], ["SHK-R", "Çelësa dhe ushqim shkolle — Rrita"], ["SHK-M", "Çelësa dhe ushqim shkolle — Mrika"], ["SHK-L", "Çelësa dhe ushqim shkolle — Lirza"]]],
] as const

export function AbbreviationLegend() {
  return <details className="group/legend relative shrink-0 text-xs">
    <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg border bg-card px-3 py-2 transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
      <BookOpen className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      <span className="font-medium">Legjenda</span>
      <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform group-open/legend:rotate-180" aria-hidden="true" />
    </summary>
    <div className="absolute right-0 top-full z-40 mt-2 max-h-[65vh] w-[min(480px,calc(100vw-24px))] overflow-y-auto rounded-xl border bg-card p-3 text-xs shadow-xl sm:p-4">
      <div className="space-y-4">{sections.map(([section, entries]) => <section key={section} aria-label={section} className="space-y-2">
        <h3 className="border-b pb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{section}</h3>
        <dl className="grid grid-cols-1">{entries.map(([code, meaning]) => <div key={code} className="flex min-w-0 items-baseline gap-2 border-b border-border/60 py-2"><dt className="w-[76px] shrink-0 rounded-md bg-muted px-1.5 py-1 text-center font-mono text-[11px] font-semibold">{code}</dt><dd className="min-w-0 leading-relaxed text-muted-foreground">{meaning}</dd></div>)}</dl>
      </section>)}</div>
      <div className="flex items-start gap-2 text-[11px] leading-relaxed text-muted-foreground"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" /><p><span className="font-medium text-foreground">R/M/L = Rrita / Mrika / Lirza.</span> BP-R/M/L-D bashkon BP-R-D, BP-M-D dhe BP-L-D. Kalo mbi kodin për titullin e plotë; mbi inicialet për emrin dhe statusin.</p></div>
    </div>
  </details>
}
