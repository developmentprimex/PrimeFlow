"use client"

import { firstLineTitle } from "@/components/realization-deadline-tasks"
import type { RealizationItem } from "@/lib/types"

export function RealizationTaskList({ items, onSelect }: {
  items: RealizationItem[]
  onSelect: (item: RealizationItem) => void
}) {
  if (!items.length) return <span className="text-slate-400">—</span>
  return <ul className="divide-y divide-slate-200/80 whitespace-normal">
    {items.map((item, index) => {
      const confirmed = Boolean(item.confirmation?.confirmed)
      const waived = confirmed || item.approved
      const clickable = Boolean(item.task_id && (item.kind === "POSTPONED" || item.unconfirmed_penalty))
      return <li key={`${item.task_id}:${index}`} className="flex items-start gap-1 py-1">
        <div className="min-w-0 flex-1">
          {clickable ? <button type="button" onClick={() => onSelect(item)} className="block w-full break-words text-left text-[11px] leading-4 text-slate-800 underline decoration-dotted underline-offset-2 hover:text-blue-700" title="Shiko datat, arsyen dhe komentin">{firstLineTitle(item.title)}</button> : <p className="break-words text-[11px] leading-4 text-slate-800">{firstLineTitle(item.title)}</p>}
          <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-1 text-[10px]">
            {item.planned && item.share < 1 ? <span className="text-slate-500">1/{Math.round(1 / item.share)} në ditë</span> : null}
            {item.credit > 0 ? <span className="font-bold text-emerald-700">+{Math.round(item.credit * 100) / 100}</span> : null}
            {item.penalty > 0 ? <span className="font-bold text-rose-700">−{item.penalty} pikë{item.deadline ? item.critical ? " · deadline important" : " · deadline" : ""}</span> : null}
            {waived ? <span className="font-semibold text-emerald-700">Konfirmuar · pa penalizim</span> : null}
          </div>
        </div>
      </li>
    })}
  </ul>
}
