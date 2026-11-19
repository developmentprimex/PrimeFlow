"use client"

import * as React from "react"
import { ChevronDown, Eye, EyeOff } from "lucide-react"
import { Button } from "@/components/ui/button"
import { collapseEmptyReportTaskRows } from "@/lib/one-h-report-users"
import { splitTaskMarkers, TASK_MARKER_OPTIONS, type SingleTaskMarker } from "@/lib/task-markers"

export function M3TomorrowSymbolsTable({ html }: { html: string }) {
  const tableId = React.useId()
  const tableRef = React.useRef<HTMLDivElement>(null)
  const emptyRef = React.useRef<HTMLParagraphElement>(null)
  const [expanded, setExpanded] = React.useState(true)
  const [selected, setSelected] = React.useState<ReadonlySet<SingleTaskMarker>>(() => new Set())
  const markup = React.useMemo(() => ({ __html: html }), [html])

  React.useEffect(() => {
    const table = tableRef.current
    if (!table) return
    const filtering = selected.size > 0
    let hasMatches = false
    for (const row of table.querySelectorAll<HTMLTableRowElement>('tr[data-task-card-row="content"]')) {
      const dateRow = row.nextElementSibling
      const dates = dateRow instanceof HTMLTableRowElement && dateRow.dataset.taskCardRow === "dates"
        ? Array.from(dateRow.cells) : []
      const tasks = Array.from(row.cells).filter((cell) => cell.tagName === "TD")
      tasks.forEach((cell, index) => {
        const matches = !filtering || splitTaskMarkers(cell.dataset.taskMarker).some((marker) => selected.has(marker))
        cell.style.display = matches ? "" : "none"
        const date = dates[index]
        if (date) date.style.display = cell.style.display
        hasMatches ||= matches && Boolean(cell.dataset.taskMarker)
      })
    }
    collapseEmptyReportTaskRows(table, filtering)
    table.hidden = filtering && !hasMatches
    if (emptyRef.current) emptyRef.current.hidden = !table.hidden
  }, [markup, selected])

  function toggleSymbol(symbol: SingleTaskMarker) {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(symbol)) next.delete(symbol)
      else next.add(symbol)
      return next
    })
  }

  return (
    <div className="mt-3 space-y-3">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {expanded && (
          <details className="relative">
            <summary className="flex min-h-8 cursor-pointer list-none items-center gap-2 rounded-md border px-3 text-sm [&::-webkit-details-marker]:hidden">
              Simbolet <strong>{selected.size ? `${selected.size} të zgjedhura` : "Të gjitha"}</strong>
              <ChevronDown className="size-4" aria-hidden="true" />
            </summary>
            <div className="absolute right-0 z-20 mt-1 w-52 rounded-md border bg-white p-2 shadow-md">
              <Button type="button" variant="ghost" size="sm" className="w-full justify-start" onClick={() => setSelected(new Set())}>
                Të gjitha simbolet
              </Button>
              <div className="grid grid-cols-2 gap-1 border-t pt-1" role="group" aria-label="Filtro sipas simboleve">
                {TASK_MARKER_OPTIONS.map(({ value, label }) => (
                  <label key={value} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-slate-100">
                    <input type="checkbox" checked={selected.has(value)} onChange={() => toggleSymbol(value)} />
                    {label}
                  </label>
                ))}
              </div>
            </div>
          </details>
        )}
        <Button type="button" variant="outline" size="sm" aria-expanded={expanded} aria-controls={tableId}
          onClick={() => setExpanded((open) => !open)}>
          {expanded ? <><EyeOff /> Fshihe tabelën</> : <><Eye /> Shfaq tabelën</>}
        </Button>
      </div>
      <div id={tableId} hidden={!expanded}>
        <div ref={tableRef} className="overflow-x-auto" dangerouslySetInnerHTML={markup} />
        <p ref={emptyRef} hidden className="rounded-md border p-3 text-sm text-muted-foreground">
          Asnjë detyrë me simbolet e zgjedhura.
        </p>
      </div>
    </div>
  )
}
