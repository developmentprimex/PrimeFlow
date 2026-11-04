export type RealizationStatusKey = "completed" | "progress" | "postponed" | "no-progress"

// The metric columns hold a different number of bands — Deadline adds the
// priority row — so they anchor to the top and reserve the same height per
// band. Otherwise the taller cell recentres its neighbours and the numbers and
// colour cells stop lining up across the row.
export const metricCell = "align-top"
export const metricHeadline = "flex h-7 items-center whitespace-nowrap"
// Matches a status-grid row: 20px line box + 4px padding + 2px border.
export const metricBand = "mt-1 flex h-[26px] items-center"

const legendItems = [
  { label: "Kryer", className: "bg-emerald-400" },
  { label: "Progres", className: "bg-amber-400" },
  { label: "Shtyrë", className: "bg-violet-400" },
  { label: "Pa progres", className: "bg-pink-500" },
  { label: "Deadline important i pambyllur (alarm)", className: "bg-red-600" },
]

export function RealizationStatusLegend({ deadlineLabel }: { deadlineLabel?: string } = {}) {
  return <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-slate-600" aria-label="Legjenda e ngjyrave">
    {legendItems.map((item) => <span key={item.label} className="inline-flex items-center gap-1 whitespace-nowrap"><span className={`h-2.5 w-2.5 rounded-sm ${item.className}`} aria-hidden="true" />{item.className === "bg-red-600" && deadlineLabel ? deadlineLabel : item.label}</span>)}
  </div>
}

export function RealizationPlanStatusGrid({ completed, progress, postponed, noProgress, onSelect, columns = 4, combinePostponed = false }: {
  completed: number
  progress: number
  postponed: number
  noProgress: number
  onSelect?: (status: RealizationStatusKey) => void
  columns?: 2 | 4
  combinePostponed?: boolean
}) {
  const items = [
    { key: "completed" as const, label: "Kryer", value: completed, className: "border-emerald-200 bg-emerald-50 text-emerald-800" },
    { key: "progress" as const, label: "Progres", value: progress, className: "border-amber-200 bg-amber-50 text-amber-800" },
    { key: "postponed" as const, label: "Shtyrë", value: postponed, className: "border-violet-200 bg-violet-50 text-violet-800" },
    { key: "no-progress" as const, label: "Pa progres", value: noProgress + (combinePostponed ? postponed : 0), className: "border-pink-300 bg-pink-100 text-pink-900" },
  ].filter(item => !combinePostponed || item.key !== "postponed")
  return <div className={`mt-1 grid gap-1 ${combinePostponed ? "grid-cols-3" : columns === 2 ? "grid-cols-2" : "grid-cols-4"}`}>
    {items.map((item) => {
      const className = `flex min-w-0 items-center justify-center gap-1 rounded border px-1 py-0.5 ${item.className}${onSelect ? " hover:brightness-95" : ""}`
      const content = <><strong className="text-base leading-5 tabular-nums" title={item.label} aria-label={`${item.label}: ${item.value}`}>{item.value}</strong>{combinePostponed && item.key === "no-progress" && postponed > 0 ? <span className="shrink-0 whitespace-nowrap text-[10px] font-bold text-violet-800">· {postponed} shtyrë</span> : null}</>
      return onSelect ? <button type="button" key={item.key} className={className} onClick={() => onSelect(item.key)}>{content}</button> : <div key={item.key} className={className}>{content}</div>
    })}
  </div>
}

export function RealizationDeadlineStatusGrid({ completed, progress, postponed, noProgress, critical, combinePostponed = false }: {
  completed: number
  progress: number
  postponed: number
  noProgress: number
  // The red badge only says how many deadlines were important, never which
  // state they ended in. Marking that box answers it without an extra click.
  critical?: { completed: number; progress: number; postponed: number; noProgress: number }
  combinePostponed?: boolean
}) {
  const items = [
    // An important deadline that was met is reassuring; one left open is an
    // alarm, so only the unmet states turn the box red.
    { label: "Kryer", value: completed, critical: critical?.completed ?? 0, alarming: false, className: "border-emerald-200 bg-emerald-50 text-emerald-800" },
    { label: "Në progres", value: progress, critical: critical?.progress ?? 0, alarming: true, className: "border-amber-200 bg-amber-50 text-amber-800" },
    { label: "Shtyrë", value: postponed, critical: critical?.postponed ?? 0, alarming: true, className: "border-violet-200 bg-violet-50 text-violet-800" },
    { label: "Pa progres", value: noProgress + (combinePostponed ? postponed : 0), critical: (critical?.noProgress ?? 0) + (combinePostponed ? critical?.postponed ?? 0 : 0), alarming: true, className: "border-pink-300 bg-pink-100 text-pink-900" },
  ].filter(item => !combinePostponed || item.label !== "Shtyrë")
  return <div className={`mt-1 grid gap-1 ${combinePostponed ? "grid-cols-3" : "grid-cols-4"}`}>
    {items.map((item) => {
      const alarm = item.critical > 0 && item.alarming
      return <div
        key={item.label}
        className={`flex min-w-0 items-center justify-center gap-0.5 rounded border px-1 py-0.5 ${alarm ? "border-red-700 bg-red-600 text-white ring-2 ring-red-600" : item.className}${item.critical && !alarm ? " ring-2 ring-red-600" : ""}`}
        title={alarm
          ? `ALARM: ${item.critical} nga ${item.value} ${item.label.toLowerCase()} janë me deadline important dhe nuk u mbyllën`
          : item.critical
            ? `${item.label}: ${item.value}, nga të cilat ${item.critical} me deadline important`
            : `${item.label}: ${item.value}`}
      >
        <strong className="text-sm leading-5 tabular-nums" aria-label={`${item.label}: ${item.value}`}>{item.value}</strong>
        {combinePostponed && item.label === "Pa progres" && postponed > 0 ? <span className="shrink-0 whitespace-nowrap text-[10px] font-bold">· {postponed} shtyrë</span> : null}
        {item.critical ? <span
          className={`self-start text-[10px] font-black leading-none tabular-nums ${alarm ? "text-white" : "text-red-700"}`}
          aria-label={alarm ? `alarm: ${item.critical} me deadline important` : `${item.critical} me deadline important`}
        >{item.critical}</span> : null}
      </div>
    })}
  </div>
}

export function RealizationExtraStatusGrid({ progress, noProgress, onProgress, onNoProgress }: {
  progress: number
  noProgress: number
  onProgress?: () => void
  onNoProgress?: () => void
}) {
  const items = [
    { label: "Progres", value: progress, className: "border-amber-200 bg-amber-50 text-amber-800", onClick: onProgress },
    { label: "Pa progres", value: noProgress, className: "border-pink-300 bg-pink-100 text-pink-900", onClick: onNoProgress },
  ]
  return <div className="mt-1 grid grid-cols-2 gap-1">
    {items.map((item) => {
      const className = `flex min-w-0 items-center justify-center gap-1 rounded border px-1 py-0.5 ${item.className}${item.onClick ? " hover:brightness-95" : ""}`
      const content = <strong className="text-base leading-5 tabular-nums" title={item.label} aria-label={`${item.label}: ${item.value}`}>{item.value}</strong>
      return item.onClick ? <button type="button" key={item.label} className={className} onClick={item.onClick}>{content}</button> : <div key={item.label} className={className}>{content}</div>
    })}
  </div>
}
