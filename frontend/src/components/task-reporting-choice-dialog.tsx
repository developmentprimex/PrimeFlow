"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { useTaskExplanationQueue } from "@/components/task-postponement-dialog"
import type { ReportingChoiceDetails, SlotReminderDetails } from "@/lib/task-reporting-choice"

function ChoiceForm({ details, onFinish }: { details: ReportingChoiceDetails; onFinish: (answer: string | null) => void }) {
  const [reason, setReason] = useState("")
  const slot = details.field === "slot"
  const title = {
    slot: "Slot tjetër për të njëjtën detyrë",
    marker: "Simbol tjetër për të njëjtën detyrë",
    task_type: "Lloj tjetër për të njëjtën detyrë",
  }[details.field]
  return <Dialog open onOpenChange={(open) => { if (!open) onFinish(null) }}>
    <DialogContent className="sm:max-w-lg" onInteractOutside={(event) => event.preventDefault()}>
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>Shpjego arsyen për ta ruajtur këtë zgjedhje.</DialogDescription>
      </DialogHeader>
      <form className="space-y-4" onSubmit={(event) => {
        event.preventDefault()
        if (reason.trim()) onFinish(reason.trim())
      }}>
        <p className="max-h-24 overflow-y-auto whitespace-pre-wrap break-words text-sm font-medium">{details.task_title}</p>
        {slot && <p className="text-sm text-muted-foreground">Data e slotit {details.date.split("-").reverse().join(".")}</p>}
        <dl className="divide-y rounded-md border text-sm">
          {details.peers.map((peer) => <div key={peer.owner_id} className="flex justify-between gap-4 px-3 py-2">
            <dt>{peer.person}</dt><dd className="font-semibold">{peer.label}</dd>
          </div>)}
          <div className="flex justify-between gap-4 bg-muted px-3 py-2">
            <dt>Zgjedhja për {details.person}</dt><dd className="font-semibold">{details.label}</dd>
          </div>
        </dl>
        <div className="space-y-2">
          <Label htmlFor="task-reporting-choice-reason">Komenti i detyrueshëm</Label>
          <Textarea id="task-reporting-choice-reason" required rows={3} maxLength={2000} value={reason}
            onChange={(event) => setReason(event.target.value)} />
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="outline" onClick={() => onFinish(null)}>Anulo</Button>
          <Button type="submit" disabled={!reason.trim()}>Vazhdo dhe ruaj</Button>
        </div>
      </form>
    </DialogContent>
  </Dialog>
}

function SlotReminderForm({ details, onFinish }: { details: SlotReminderDetails; onFinish: (answer: string | null) => void }) {
  const [choosing, setChoosing] = useState(false)
  return <Dialog open onOpenChange={(open) => { if (!open) onFinish(null) }}>
    <DialogContent onInteractOutside={(event) => event.preventDefault()}>
      <DialogHeader>
        <DialogTitle>Bllok PM dhe sloti 16:00</DialogTitle>
        <DialogDescription>{details.message}</DialogDescription>
      </DialogHeader>
      {choosing ? <>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Slotet e tjera">
          {details.slots.map((slot) => <Button key={slot} variant="outline" onClick={() => onFinish(slot)}>
            {slot}
          </Button>)}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setChoosing(false)}>Kthehu</Button>
        </DialogFooter>
      </> : <DialogFooter>
        {details.slots.length > 0 && <Button variant="outline" onClick={() => setChoosing(true)}>Ndërro slotin</Button>}
        <Button onClick={() => onFinish("continue")}>Vazhdo me 16:00</Button>
      </DialogFooter>}
    </DialogContent>
  </Dialog>
}

export function useTaskReportingChoice(sessionId: string | null) {
  const { requestExplanation, active } = useTaskExplanationQueue<ReportingChoiceDetails | SlotReminderDetails, string>(sessionId)
  return {
    requestChoiceExplanation: requestExplanation,
    reportingChoiceDialog: active && ("message" in active.details
      ? <SlotReminderForm key={active.id} details={active.details} onFinish={active.finish} />
      : <ChoiceForm key={active.id} details={active.details} onFinish={active.finish} />),
  }
}
