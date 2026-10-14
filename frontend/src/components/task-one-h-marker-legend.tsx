"use client"

import { useId, useState } from "react"
import { cn } from "@/lib/utils"

const LEGEND_ITEMS = [
  ["?", "PYETJE/PAQARTESI"],
  ["!", "DYSHIM/ NUK KUPTOHET DET"],
  ["!!!", "KLIENT/URGJENT"],
  ["SHARE", "DET QE DUHET SCREENSHARE ME GA"],
  ["👁", "KËRKON MONITORIM NGA DIKUSH TJETËR"],
  ["X", "MBYLL DETYREN"],
  ["M2", "DOREZIM DERI NE PAUZE"],
  ["M3", "DOREZIM DERI NE FUND TE DITES"],
  ["M2/3", "DOREZIM EDHE NE M2 EDHE M3"],
  ["GENT", "PYETJE/SQARIM ME GENTIN"],
  ["KA", "PYETJE/SQARIM ME KA"],
  ["GA", "PYETJE/SQARIM ME GA"],
  ["F", "DET FIZIKISHT"],
  ["BZ1N1", ""],
] as const

export function TaskOneHMarkerLegend({ className }: { className?: string }) {
  const [expanded, setExpanded] = useState(false)
  const contentId = useId()

  return (
    <div className={className}>
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={contentId}
        onClick={() => setExpanded((value) => !value)}
        className="inline-flex items-center gap-2 rounded-md border border-blue-300 bg-blue-50 px-3 py-1 text-xs font-bold text-[#0F2A5F] hover:bg-blue-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
      >
        <span aria-hidden="true" className="text-lg leading-none">{expanded ? "−" : "+"}</span>
        <span>Legjenda</span>
      </button>
      <div
        id={contentId}
        hidden={!expanded}
        className={cn("mt-2 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-blue-300 bg-blue-50 px-3 py-2 text-xs font-bold text-[#0F2A5F]", !expanded && "hidden")}
      >
        {LEGEND_ITEMS.map(([symbol, description], index) => (
          <span key={symbol} className="contents">
            {index > 0 ? <span className="text-lg font-black leading-none text-[#0F2A5F]" aria-hidden="true">/</span> : null}
            <span><b className={cn("font-black text-red-600", symbol.length > 1 ? "text-xs" : "text-base")}>{symbol}</b>{description ? ` - ${description}` : ""}</span>
          </span>
        ))}
      </div>
    </div>
  )
}
