"use client"

import * as React from "react"

export function CollapsibleTaskTitle({
  title,
  enabled = true,
  renderTitle = (value) => value,
}: {
  title: string
  enabled?: boolean
  renderTitle?: (value: string) => React.ReactNode
}) {
  const [isExpanded, setIsExpanded] = React.useState(false)
  const preview = title.split(/\r?\n/).map((line) => line.trim()).find(Boolean) || title
  const canExpand = enabled && preview !== title
  const content = renderTitle(canExpand && !isExpanded ? preview : title)
  if (!canExpand) return <>{content}</>

  return (
    <span className="inline-flex max-w-full items-start gap-2">
      <span className="min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{content}</span>
      <button
        type="button"
        className="inline-flex shrink-0 rounded border border-slate-300 bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-600 hover:bg-slate-50"
        aria-label={isExpanded ? "Collapse task title" : "Expand task title"}
        aria-expanded={isExpanded}
        onClick={(event) => {
          event.stopPropagation()
          setIsExpanded((previous) => !previous)
        }}
      >
        {isExpanded ? "-" : "+"}
      </button>
    </span>
  )
}
