"use client"

import * as React from "react"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuth } from "@/lib/auth"
import { Loader2, Check, AlertCircle } from "lucide-react"

export type LegendEntry = {
  id: string
  department_id: string
  week_start_date: string
  key: string
  label: string
  question_text: string
  answer_text: string | null
  created_by: string | null
  created_at: string
  updated_at: string
}

export type LegendSwatchItem = {
  key: string
  label: string
  displayLabel: string
  color: string
}

// Color mapping for legend labels:
// - RED = TO DO (New task)
// - GREEN = KRYER (Done)
// - PINK = NUK ESHTE PUNUAR (Not worked)
// - YELLOW = PROCES (In process)
// - LIGHT GREY = PV
export const LEGEND_COLORS: Record<string, string> = {
  // Current labels
  "TO DO": "#FF0000", // Red
  KRYER: "#C4FDC4", // Green
  "NUK ESHTE PUNUAR": "#FFC4ED", // Pink
  PROCES: "#FFFF00", // Yellow (match IN_PROGRESS)
  PV: "#D3D3D3", // Light Grey
  "KOMPLET (100% PROJEKTE)": "#D3D3D3", // Light task)
  "WAITING CONFIRMATION": "#FFEDD5", // Amber
  WAITING_CONFIRMATION: "#FFEDD5", // Amber
  "KONFIRMIM NE PRITJE": "#FFEDD5", // Amber
  // Alternative/new labels (for backward compatibility)
  "NEW TASK / TO DO": "#FF0000", // Red
  DONE: "#C4FDC4", // Green
  "NË PROCES": "#FFFF00", // Yellow (match IN_PROGRESS)
}

const LEGEND_LABEL_DISPLAY: Record<string, string> = {
  "NUK ESHTE PUNUAR": "DETYRE E RE",
  "MBINGARKESE?": "-",
  "KOMPLET (100% PROJEKTE)": "-",
}
export const getLegendLabelDisplay = (label: string) => LEGEND_LABEL_DISPLAY[label] ?? label

export const LEGEND_EXTRA_SWATCHES: ReadonlyArray<{ label: string; color: string }> = [
  { label: "DETYRE E RE E KRIJUAR KETE JAVE", color: "#DBEAFE" },
  { label: "KONFIRMIM NE PRITJE", color: "#FFEDD5" },
  { label: "DETYRE E RE KRYER", color: "#02E6C7" },
]

export const buildLegendSwatches = (
  entries: Array<Pick<LegendEntry, "label">>,
  options?: { hideUnknown?: boolean }
): LegendSwatchItem[] => {
  const swatches: LegendSwatchItem[] = []
  const seen = new Set<string>()
  const hideUnknown = options?.hideUnknown ?? false

  const addSwatch = (label: string, fallbackColor?: string) => {
    if (!label || seen.has(label)) return
    const resolvedColor = LEGEND_COLORS[label] || fallbackColor
    if (hideUnknown && !resolvedColor) return
    if (getLegendLabelDisplay(label) === "-") return
    seen.add(label)
    swatches.push({
      key: label,
      label,
      displayLabel: getLegendLabelDisplay(label),
      color: resolvedColor || "#E5E7EB",
    })
  }

  entries.forEach((entry) => addSwatch(entry.label))
  LEGEND_EXTRA_SWATCHES.forEach((swatch) => addSwatch(swatch.label, swatch.color))

  return swatches
}

type WeeklyPlannerLegendTableProps = {
  departmentId: string
  weekStart: string
  departmentName?: string
}

type SaveState = "idle" | "saving" | "saved" | "error"

const LEGEND_QUESTION_CONFIGS: Record<
  string,
  {
    order: string[]
    questions: Record<string, string>
  }
> = {
  development: {
    order: ["KRYER", "PROCES", "NUK ESHTE PUNUAR", "PV"],
    questions: {
      KRYER: "A KEMI PROJEKTE TE TJERA TE P(A)PLANIFIKUARA?",
      PROCES: "A PRITEN PROJEKTE TE TJERA GJATE JAVES QE DUHET ME I PLNF KETE JAVE, APO BARTEN JAVEN TJETER?",
      "NUK ESHTE PUNUAR": "BLLOK?",
      PV: "",
    },
  },
  graphicdesign: {
    order: [
      "KRYER",
      "PROCES",
      "NUK ESHTE PUNUAR",
      "PV",
      "MBINGARKESE?",
      "KOMPLET (100% PROJEKTE)",
    ],
    questions: {
      KRYER: "A KEMI PROJEKTE TE TJERA TE PAPLANIFIKUARA?",
      PROCES: "A PRITEN PROJEKTE TE TJERA GJATE JAVES QE DUHET ME I PLNF KETE JAVE, APO BARTEN JAVEN TJETER?",
      "NUK ESHTE PUNUAR": "A KA KLIENT QE NUK KEMI PROJEKTE TE HAPURA?",
      PV: "NENGARKESE (NUK ESHTE I PLANIFIKUAR PERSONI PER KOMPLET JAVEN)?",
      "MBINGARKESE?": "MBINGARKESE?",
      "KOMPLET (100% PROJEKTE)": "KOMPLET (100% PROJEKTE)",
    },
  },
  productcontent: {
    order: [
      "KRYER",
      "PROCES",
      "NUK ESHTE PUNUAR",
      "PV",
      "MBINGARKESE?",
      "KOMPLET (100% PROJEKTE)",
    ],
    questions: {
      KRYER: "A KEMI PROJEKTE TE TJERA TE PAPLANIFIKUARA?",
      PROCES: "A PRITEN PROJEKTE TE TJERA GJATE JAVES QE DUHET ME I PLNF KETE JAVE, APO BARTEN JAVEN TJETER?",
      "NUK ESHTE PUNUAR": "A KA KLIENT QE NUK KEMI PROJEKTE TE HAPURA?",
      PV: "NENGARKESE (NUK ESHTE I PLANIFIKUAR PERSONI PER KOMPLET JAVEN)?",
      "MBINGARKESE?": "MBINGARKESE?",
      "KOMPLET (100% PROJEKTE)": "KOMPLET (100% PROJEKTE)",
    },
  },
}

const normalizeDepartmentKey = (name?: string) => {
  const normalized = (name || "").trim().toLowerCase().replace(/\s+/g, "")
  if (normalized === "zhvillim") return "development"
  if (normalized === "grafikdizajn" || normalized === "dizajngrafik") return "graphicdesign"
  if (normalized === "productcontent" || normalized === "produktcontent") return "productcontent"
  if (normalized === "projectcontentmanager") return "productcontent"
  return normalized
}

export const getLegendQuestions = (departmentName?: string) => {
  const key = normalizeDepartmentKey(departmentName)
  return LEGEND_QUESTION_CONFIGS[key] || null
}

export const buildLegendDisplayEntries = ({
  entries,
  departmentId,
  weekStart,
  departmentName,
}: {
  entries: LegendEntry[]
  departmentId: string
  weekStart: string
  departmentName?: string
}) => {
  const legendConfig = getLegendQuestions(departmentName)
  if (!legendConfig) return entries

  const byLabel = new Map<string, LegendEntry>()
  entries.forEach((entry) => {
    if (!byLabel.has(entry.label)) {
      byLabel.set(entry.label, entry)
    }
  })

  return legendConfig.order.map((label) => {
    const match = byLabel.get(label)
    if (!match) {
      return {
        id: `__placeholder__${label}`,
        department_id: departmentId,
        week_start_date: weekStart,
        key: label,
        label,
        question_text: legendConfig.questions[label],
        answer_text: null,
        created_by: null,
        created_at: "",
        updated_at: "",
      }
    }
    return {
      ...match,
      question_text: legendConfig.questions[label] ?? match.question_text,
    }
  })
}

export function WeeklyPlannerLegendTable({
  departmentId,
  weekStart,
  departmentName,
}: WeeklyPlannerLegendTableProps) {
  const { apiFetch, loading: authLoading, user } = useAuth()
  const [entries, setEntries] = React.useState<LegendEntry[]>([])
  const [isLoading, setIsLoading] = React.useState(true)
  const [saveStates, setSaveStates] = React.useState<Map<string, SaveState>>(new Map())
  const debounceTimersRef = React.useRef<Map<string, NodeJS.Timeout>>(new Map())
  // Track last saved value per entry to detect changes
  const lastSavedValuesRef = React.useRef<Map<string, string>>(new Map())

  const loadLegend = React.useCallback(async () => {
    // Wait for auth to finish loading and ensure user is authenticated
    if (authLoading || !user) {
      setIsLoading(false)
      return
    }
    if (!departmentId || !weekStart) {
      setIsLoading(false)
      return
    }

    setIsLoading(true)
    // Clear any pending debounce timers when loading new data
    debounceTimersRef.current.forEach((timer) => clearTimeout(timer))
    debounceTimersRef.current.clear()
    try {
      const qs = new URLSearchParams()
      qs.set("department_id", departmentId)
      qs.set("week_start", weekStart)
      const res = await apiFetch(`/planners/weekly-planner/legend?${qs.toString()}`)
      if (res.ok) {
        const data = (await res.json()) as LegendEntry[]
        setEntries(data)
        // Reset save states when loading new data
        setSaveStates(new Map())
        // Initialize last saved values
        lastSavedValuesRef.current = new Map(
          data.map((e) => [e.id, e.answer_text || ""])
        )
      } else {
        // Don't log 401 errors as they're expected if user is not authenticated
        if (res.status !== 401) {
          console.error("Failed to load legend:", res.status)
        }
        setEntries([])
      }
    } catch (error) {
      console.error("Error loading legend:", error)
      setEntries([])
    } finally {
      setIsLoading(false)
    }
  }, [apiFetch, departmentId, weekStart, authLoading, user])

  React.useEffect(() => {
    void loadLegend()
  }, [loadLegend])

  // Cleanup debounce timers on unmount
  React.useEffect(() => {
    return () => {
      debounceTimersRef.current.forEach((timer) => clearTimeout(timer))
      debounceTimersRef.current.clear()
    }
  }, [])

  const saveAnswer = React.useCallback(
    async (entryId: string, answerText: string) => {
      setSaveStates((prev) => new Map(prev).set(entryId, "saving"))
      try {
        const res = await apiFetch(`/planners/weekly-planner/legend/${entryId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ answer_text: answerText.trim() || null }),
        })
        if (res.ok) {
          const updated = (await res.json()) as LegendEntry
          setEntries((prev) => prev.map((e) => (e.id === entryId ? updated : e)))
          // Update last saved value
          lastSavedValuesRef.current.set(entryId, updated.answer_text || "")
          setSaveStates((prev) => new Map(prev).set(entryId, "saved"))
          // Clear "saved" indicator after 2 seconds
          setTimeout(() => {
            setSaveStates((prev) => {
              const next = new Map(prev)
              if (next.get(entryId) === "saved") {
                next.set(entryId, "idle")
              }
              return next
            })
          }, 2000)
        } else {
          const errorText = await res.text().catch(() => "Unknown error")
          console.error("Failed to save legend entry:", res.status, errorText)
          setSaveStates((prev) => new Map(prev).set(entryId, "error"))
          // Keep error state visible for 3 seconds
          setTimeout(() => {
            setSaveStates((prev) => {
              const next = new Map(prev)
              if (next.get(entryId) === "error") {
                next.set(entryId, "idle")
              }
              return next
            })
          }, 3000)
        }
      } catch (error) {
        console.error("Error saving legend entry:", error)
        setSaveStates((prev) => new Map(prev).set(entryId, "error"))
        setTimeout(() => {
          setSaveStates((prev) => {
            const next = new Map(prev)
            if (next.get(entryId) === "error") {
              next.set(entryId, "idle")
            }
            return next
          })
        }, 3000)
      }
    },
    [apiFetch]
  )

  const debouncedSave = React.useCallback(
    (entryId: string, answerText: string) => {
      // Clear existing timer for this entry
      const existingTimer = debounceTimersRef.current.get(entryId)
      if (existingTimer) {
        clearTimeout(existingTimer)
      }

      // Set new timer
      const timer = setTimeout(() => {
        void saveAnswer(entryId, answerText)
        debounceTimersRef.current.delete(entryId)
      }, 600) // 600ms debounce

      debounceTimersRef.current.set(entryId, timer)
    },
    [saveAnswer]
  )

  const handleInputChange = React.useCallback(
    (entryId: string, newValue: string) => {
      // Update local state immediately (controlled input)
      setEntries((prev) =>
        prev.map((e) => (e.id === entryId ? { ...e, answer_text: newValue } : e))
      )
      // Reset save state to idle when user types
      setSaveStates((prev) => {
        const next = new Map(prev)
        if (next.get(entryId) === "saved" || next.get(entryId) === "error") {
          next.set(entryId, "idle")
        }
        return next
      })
      // Debounce the save
      debouncedSave(entryId, newValue)
    },
    [debouncedSave]
  )

  const handleBlur = React.useCallback(
    (entryId: string, value: string) => {
      // Cancel any pending debounced save
      const timer = debounceTimersRef.current.get(entryId)
      if (timer) {
        clearTimeout(timer)
        debounceTimersRef.current.delete(entryId)
      }
      // Save immediately on blur if value has changed from last saved
      const lastSaved = lastSavedValuesRef.current.get(entryId) || ""
      const trimmedValue = value.trim()
      const trimmedLastSaved = lastSaved.trim()
      if (trimmedValue !== trimmedLastSaved) {
        void saveAnswer(entryId, value)
      }
    },
    [saveAnswer]
  )

  const handleKeyDown = React.useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>, entryId: string, value: string) => {
      if (e.key === "Enter") {
        e.preventDefault()
        // Cancel any pending debounced save
        const timer = debounceTimersRef.current.get(entryId)
        if (timer) {
          clearTimeout(timer)
          debounceTimersRef.current.delete(entryId)
        }
        // Save immediately if value has changed from last saved
        const lastSaved = lastSavedValuesRef.current.get(entryId) || ""
        const trimmedValue = value.trim()
        const trimmedLastSaved = lastSaved.trim()
        if (trimmedValue !== trimmedLastSaved) {
          void saveAnswer(entryId, value)
        }
        // Blur the input
        e.currentTarget.blur()
      }
    },
    [saveAnswer]
  )

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Legend / Questions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        </CardContent>
      </Card>
    )
  }

  if (entries.length === 0) {
    return null
  }

  const displayEntries = buildLegendDisplayEntries({
    entries,
    departmentId,
    weekStart,
    departmentName,
  })
  const isProductContent = normalizeDepartmentKey(departmentName) === "productcontent"
  const legendSwatches = buildLegendSwatches(displayEntries, { hideUnknown: isProductContent })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Legend / Questions</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 md:grid-cols-[400px_minmax(0,1fr)]">
          <div className="overflow-x-auto rounded-lg border border-slate-300 bg-slate-50/40 p-3">
            <div className="mb-2 text-sm font-semibold text-slate-800">Color Labels</div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16 text-center">Color</TableHead>
                  <TableHead>Label</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {legendSwatches.map((swatch) => (
                  <TableRow key={swatch.key}>
                    <TableCell className="p-2">
                      <div
                        className="h-8 w-12 rounded border border-gray-300"
                        style={{ backgroundColor: swatch.color }}
                      />
                    </TableCell>
                    <TableCell className="font-semibold">{swatch.displayLabel}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className="overflow-x-auto rounded-lg border border-slate-300 bg-white p-3">
            <div className="mb-2 text-sm font-semibold text-slate-800">Questions / Answers</div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Question</TableHead>
                  <TableHead className="w-48">Answer</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {displayEntries.map((entry) => {
                  const saveState = saveStates.get(entry.id) || "idle"
                  const isPlaceholder = entry.id.startsWith("__placeholder__")
                  return (
                    <TableRow key={entry.id}>
                      <TableCell>
                        {entry.question_text ? (
                          <span className="text-sm font-medium text-red-600">{entry.question_text}</span>
                        ) : (
                          <span className="text-sm text-muted-foreground">-</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {isPlaceholder ? (
                          <span className="text-sm text-muted-foreground">-</span>
                        ) : (
                          <div className="relative">
                            <Input
                              value={entry.answer_text || ""}
                              onChange={(e) => handleInputChange(entry.id, e.target.value)}
                              onBlur={(e) => handleBlur(entry.id, e.target.value)}
                              onKeyDown={(e) => handleKeyDown(e, entry.id, e.currentTarget.value)}
                              placeholder="Enter answer..."
                              className="w-full"
                              disabled={saveState === "saving"}
                            />
                            <div className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center">
                              {saveState === "saving" && (
                                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                              )}
                              {saveState === "saved" && <Check className="h-4 w-4 text-green-600" />}
                              {saveState === "error" && (
                                <AlertCircle className="h-4 w-4 text-red-600" aria-label="Failed to save" />
                              )}
                            </div>
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

