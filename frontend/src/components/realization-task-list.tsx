"use client"

import { firstLineTitle } from "@/components/realization-deadline-tasks"
import type { RealizationDeadlineTask, RealizationItem } from "@/lib/types"
import { cn } from "@/lib/utils"

export function RealizationTaskList({ items, deadlines = [], onSelect }: {
  items: RealizationItem[]
  deadlines?: RealizationDeadlineTask[]
  onSelect: (item: RealizationItem) => void
}) {
  if (!items.length) return <span className="text-slate-400">—</span>
  return <ul className="divide-y divide-slate-200/80 whitespace-normal">
    {items.map((item, index) => {
      const deadline = deadlines.find(task => task.task_id && task.task_id === item.task_id)
      const hasDeadline = Boolean(deadline || item.deadline)
      const completed = deadline ? deadline.state === "COMPLETED" : item.kind === "COMPLETED" || item.kind === "EXTRA_COMPLETED"
      const alarm = hasDeadline && !completed
      const clickable = Boolean(item.task_id && (hasDeadline || item.kind === "POSTPONED" || item.unconfirmed_penalty))
      const titleClass = cn("block w-full break-words text-left text-[11px] leading-4", item.kind === "POSTPONED" && "flex items-start gap-1", alarm ? "font-bold text-red-700" : "text-slate-800")
      const title = item.kind === "POSTPONED"
        ? <><span className="shrink-0 whitespace-nowrap font-bold text-violet-800">Shtyrë:</span><span className="min-w-0 flex-1 break-words">{firstLineTitle(item.title)}</span></>
        : firstLineTitle(item.title)
      return <li key={`${item.task_id}:${index}`} className="py-1">
        {clickable ? <button type="button" onClick={() => onSelect(item)} className={cn(titleClass, "underline decoration-dotted underline-offset-2", alarm ? "hover:text-red-800" : "hover:text-blue-700")} title="Shiko datat, arsyen dhe komentin">{title}</button> : <p className={titleClass}>{title}</p>}
      </li>
    })}
  </ul>
}
