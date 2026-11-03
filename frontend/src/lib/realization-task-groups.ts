import type { RealizationItemKind } from "@/lib/types"

export const realizationTaskGroups: { kind: RealizationItemKind; label: string; className: string }[] = [
  { kind: "COMPLETED", label: "Të kryera nga plani", className: "border-emerald-200 bg-emerald-50 text-emerald-800" },
  { kind: "EXTRA_COMPLETED", label: "Ekstra të kryera", className: "border-blue-200 bg-blue-50 text-blue-800" },
  { kind: "WFE", label: "WFE (90%)", className: "border-purple-200 bg-purple-50 text-purple-800" },
  { kind: "EXTRA_WFE", label: "Ekstra WFE (90%)", className: "border-purple-200 bg-purple-50 text-purple-800" },
  { kind: "IN_PROGRESS", label: "Në progres", className: "border-amber-200 bg-amber-50 text-amber-800" },
  { kind: "POSTPONED", label: "Të shtyra", className: "border-violet-200 bg-violet-50 text-violet-800" },
  { kind: "NO_PROGRESS", label: "Pa progres", className: "border-pink-300 bg-pink-100 text-pink-900" },
  { kind: "EXTRA_OPEN", label: "Ekstra me deadline të humbur", className: "border-red-300 bg-red-50 text-red-800" },
  { kind: "REASSIGNED_OUT", label: "Kaluar te dikush tjetër", className: "border-slate-200 bg-slate-50 text-slate-700" },
]
