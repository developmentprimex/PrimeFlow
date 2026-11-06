"use client"

import * as React from "react"
import { Plus, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useConfirm } from "@/components/providers/confirm-dialog-provider"

export type ManualReportSection = { section_key?: string; title: string; body: string }

function customManualPosition(section: ManualReportSection) {
  const match = section.section_key?.match(/^manual:custom:([1-9]\d*):/)
  return match ? Number(match[1]) : null
}

export function orderManualReportSections(
  sections: ManualReportSection[],
  isManual: (section: ManualReportSection, index: number) => boolean,
) {
  const manual = sections.filter(isManual)
  const numbered = manual.filter((section) => customManualPosition(section) !== null)
  const ordered = manual.filter((section) => customManualPosition(section) === null)
  numbered
    .map((section, index) => ({ section, index, position: customManualPosition(section)! }))
    .sort((a, b) => b.position - a.position || b.index - a.index)
    .forEach(({ section, position }) => ordered.splice(Math.min(position - 1, ordered.length), 0, section))
  return [...ordered, ...sections.filter((section, index) => !isManual(section, index))]
}

export function isCustomManualReportSection(section: ManualReportSection) {
  return section.section_key?.startsWith("manual:custom:") === true
}

export function ManualReportQuestionDelete({ title, onDelete, disabled }: {
  title: string
  onDelete: () => Promise<void>
  disabled?: boolean
}) {
  const confirm = useConfirm()
  return (
    <Button
      type="button"
      variant="destructive"
      size="sm"
      disabled={disabled}
      onClick={async () => {
        if (await confirm({
          title: "Fshi pikën manuale?",
          description: `Pika “${title}” do të hiqet nga raportet e ardhshme. PËRGJIGJA në këtë raport do të fshihet.`,
          confirmLabel: "Fshi",
          variant: "destructive",
        })) await onDelete()
      }}
    >
      <Trash2 className="size-4" /> Fshi
    </Button>
  )
}

export function addManualReportSection(
  sections: ManualReportSection[],
  title: string,
  position: number,
  isManual: (section: ManualReportSection, index: number) => boolean,
): ManualReportSection[] | null {
  const cleanTitle = title.trim()
  const normalized = cleanTitle.replace(/\s+/g, " ").toLocaleLowerCase()
  if (!normalized || !Number.isSafeInteger(position) || position < 1 || sections.some((section) => section.title.trim().replace(/\s+/g, " ").toLocaleLowerCase() === normalized)) {
    return null
  }
  return orderManualReportSections([
    ...sections,
    { section_key: `manual:custom:${position}:${crypto.randomUUID()}`, title: cleanTitle, body: "(Ploteso manualisht)" },
  ], isManual)
}

export function ManualReportQuestionAdd({ onAdd, disabled }: { onAdd: (title: string, position: number) => Promise<boolean>; disabled?: boolean }) {
  const [open, setOpen] = React.useState(false)
  const [title, setTitle] = React.useState("")
  const [position, setPosition] = React.useState("")
  const [adding, setAdding] = React.useState(false)

  const add = async () => {
    if (adding || disabled) return
    if (!title.trim()) {
      toast.error("Shkruaj titullin e pikës")
      return
    }
    const parsedPosition = Number(position)
    if (!Number.isSafeInteger(parsedPosition) || parsedPosition < 1) {
      toast.error("Shkruaj një numër të vlefshëm për renditjen")
      return
    }
    setAdding(true)
    try {
      if (!await onAdd(title, parsedPosition)) return
      setTitle("")
      setPosition("")
      setOpen(false)
    } finally {
      setAdding(false)
    }
  }

  return (
    <>
      <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={() => setOpen(true)}>
        <Plus className="size-4" /> Add point
      </Button>
      <Dialog open={open} onOpenChange={(nextOpen) => { if (!adding) setOpen(nextOpen) }}>
        <DialogContent>
          <DialogHeader><DialogTitle>Shto pikë manuale</DialogTitle></DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="manual-report-question-position">Numri i pikës</Label>
            <Input id="manual-report-question-position" type="number" min="1" step="1" value={position} onChange={(event) => setPosition(event.target.value)} placeholder="p.sh. 2" disabled={adding} autoFocus />
            <Label htmlFor="manual-report-question-title">Titulli i pikës</Label>
            <Input id="manual-report-question-title" value={title} onChange={(event) => setTitle(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void add() }} placeholder="Shkruaj pyetjen..." disabled={adding} />
          </div>
          <Button type="button" onClick={() => void add()} disabled={adding}>{adding ? "Duke ruajtur..." : "Shto pikën"}</Button>
        </DialogContent>
      </Dialog>
    </>
  )
}
