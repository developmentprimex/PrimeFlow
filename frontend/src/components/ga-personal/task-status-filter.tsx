"use client"

import { Button } from "@/components/ui/button"

const options = [
  ["pending", "Për t’u bërë", "bg-pink-200 text-pink-950 ring-pink-400"],
  ["in_progress", "Po e bëj", "bg-yellow-200 text-yellow-950 ring-yellow-400"],
  ["needs_help", "Më duhet ndihmë", "bg-red-100 text-red-950 ring-red-400"],
  ["done", "U kry", "bg-green-100 text-green-950 ring-green-400"],
] as const

export function TaskStatusFilter({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filtro sipas gjendjes">
    {options.map(([key, label, color]) => <button key={key} type="button" aria-pressed={value === key} onClick={() => onChange(value === key ? "all" : key)} className={`rounded-md px-2.5 py-1.5 text-xs font-medium transition-shadow ${color} ${value === key ? "ring-2 ring-offset-1" : "opacity-80 hover:opacity-100"}`}>{label}</button>)}
    {value !== "all" && <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={() => onChange("all")}>Pastro filtrin</Button>}
  </div>
}
