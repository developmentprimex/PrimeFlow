"use client"

import * as React from "react"

export function CollapsibleTaskTitle({
  title,
  enabled = true,
  alignToggle = false,
  renderTitle = (value) => value,
}: {
  title: string
  enabled?: boolean
  alignToggle?: boolean
  renderTitle?: (value: string) => React.ReactNode
}) {
  const [isExpanded, setIsExpanded] = React.useState(false)
  const toggleRef = React.useRef<HTMLButtonElement>(null)
  const anchorTop = React.useRef<number | null>(null)
  React.useLayoutEffect(() => {
    if (anchorTop.current === null || !toggleRef.current) return
    const difference = toggleRef.current.getBoundingClientRect().top - anchorTop.current
    anchorTop.current = null
    if (difference) window.scrollBy(0, difference)
  }, [isExpanded])
  const preview = title.split(/\r?\n/).map((line) => line.trim()).find(Boolean) || title
  const canExpand = enabled && preview !== title
  const content = renderTitle(canExpand && !isExpanded ? preview : title)
  if (!canExpand) return <>{content}</>

  return (
    <span className="inline-flex max-w-full items-start gap-2">
      <span className="min-w-0 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">{content}</span>
      <button
        ref={toggleRef}
        type="button"
        className={`inline-flex shrink-0 rounded border border-slate-300 bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-600 hover:bg-slate-50 ${alignToggle ? "absolute right-0 top-0" : ""}`}
        aria-label={isExpanded ? "Collapse task title" : "Expand task title"}
        aria-expanded={isExpanded}
        onClick={(event) => {
          event.stopPropagation()
          anchorTop.current = event.currentTarget.getBoundingClientRect().top
          setIsExpanded((previous) => !previous)
        }}
      >
        {isExpanded ? "-" : "+"}
      </button>
    </span>
  )
}
