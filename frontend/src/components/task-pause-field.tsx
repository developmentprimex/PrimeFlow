"use client"

import * as React from "react"
import { Pause } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { currentTaskPauseDay } from "@/lib/task-pause"

export function TaskPauseField({ value, onChange, until, disabled }: {
  value: number | null | undefined
  onChange: (days: number | null | undefined) => void
  until?: string | null
  disabled?: boolean
}) {
  const id = React.useId()
  const today = currentTaskPauseDay()
  const activeUntil = until && until >= today ? until : null

  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={value ? id : undefined}>Pauza</Label>
      <div className="flex flex-wrap items-center gap-2">
        {value ? (
          <>
            <Input id={id} type="number" min={1} max={365} step={1} value={value} disabled={disabled}
              className="w-20"
              onFocus={(event) => event.currentTarget.select()}
              onChange={(event) => onChange(Math.min(365, Math.max(1, Math.trunc(event.currentTarget.valueAsNumber || 1))))}
            />
            <span className="text-xs text-muted-foreground">{value === 1 ? "ditë · vetëm sot" : "ditë · duke përfshirë sot"}</span>
          </>
        ) : value === undefined && activeUntil ? (
          <span className="text-sm">Në pauzë deri më {activeUntil.split("-").reverse().join(".")}</span>
        ) : null}
        {!value && (value !== undefined || !activeUntil) && (
          <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={() => onChange(1)}>
            <Pause className="size-3.5" /> Vendos në pauzë
          </Button>
        )}
        {value === undefined && activeUntil && (
          <Button type="button" variant="outline" size="sm" disabled={disabled}
            onClick={() => onChange(Math.round((Date.parse(activeUntil) - Date.parse(today)) / 86_400_000) + 1)}>
            Ndrysho ditët
          </Button>
        )}
        {(value || (value === undefined && activeUntil)) && (
          <Button type="button" variant="ghost" size="sm" disabled={disabled}
            onClick={() => onChange(activeUntil ? null : undefined)}>
            Hiq pauzën
          </Button>
        )}
        {value === null && activeUntil && (
          <Button type="button" variant="ghost" size="sm" disabled={disabled} onClick={() => onChange(undefined)}>
            Mbaj pauzën ekzistuese
          </Button>
        )}
      </div>
    </div>
  )
}

export function TaskPauseBadge() {
  return <span className="shrink-0 rounded border border-slate-400 bg-white px-1 text-[10px] font-semibold text-slate-800">Pauzë</span>
}
