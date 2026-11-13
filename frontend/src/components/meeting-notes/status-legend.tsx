import { meetingTranslator } from "@/lib/meeting-notes-language"
const items: [string, string][] = [
  ["bg-sky-200", "Shënim manual"],
  ["bg-violet-100", "Shënim nga regjistrimi"],
  ["bg-pink-200", "TODO"],
  ["bg-yellow-200", "IN PROGRESS"],
  ["bg-[#E2C15B]", "WFE"],
  ["bg-green-200", "DONE"],
]

export function StatusLegend({ withNotes = true, withStatuses = true, english = false }: { withNotes?: boolean; withStatuses?: boolean; english?: boolean }) {
  const t = meetingTranslator(english)
  return <div className="flex flex-wrap items-center gap-3 text-xs text-neutral-600">
    {items.filter((_, index) => index < 2 ? withNotes : withStatuses).map(([color, label]) => <span key={label} className="inline-flex items-center gap-1.5">
      <span className={`size-3 border border-slate-600 ${color}`} aria-hidden="true" />{english && label === "WFE" ? "WAITING" : t(label)}
    </span>)}
  </div>
}
