"use client"

import { Save } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Textarea } from "@/components/ui/textarea"

export const REORGANIZATION_SECTION = "A KA RIORGANIZIM?"
const REORGANIZATION_FIELDS = {
  discussion: "BZ M1",
  comment: "KOMENT",
  underload: "NËNNGARKESË",
  overload: "MBINGARKESË",
  plan: "SI BËHET RIORGANIZIMI?",
  cause: "SHKAKTARI I MUNGESËS OSE VONESËS",
} as const

export function MorningReorganization({
  body, hasAttendanceIssue = false, showAllFollowUps = false, legacyComment = false,
  readOnly, saving = false, saveDisabled, maxLength, onChange, onSave,
}: {
  body: string
  hasAttendanceIssue?: boolean
  showAllFollowUps?: boolean
  legacyComment?: boolean
  readOnly: boolean
  saving?: boolean
  saveDisabled?: boolean
  maxLength?: number
  onChange: (body: string) => void
  onSave?: () => void
}) {
  const { discussion, comment, underload, overload, plan, cause } = REORGANIZATION_FIELDS
  const fields: Record<string, string> = legacyComment && !/^BZ M1: (PO|JO)(?:\n|$)/.test(body)
    ? { [comment]: body.trim() === "(Ploteso manualisht)" ? "" : body }
    : Object.fromEntries(body.split(/\n(?=\S)/).flatMap((field) => {
      const separator = field.indexOf(":")
      return separator < 0 ? [] : [[field.slice(0, separator), field.slice(separator + 1)
        .replace(/^ /, "").replace(/\n /g, "\n")]]
    }))
  if (fields[plan] === undefined && fields["SI BËHET ORGANIZIMI?"] !== undefined) {
    fields[plan] = fields["SI BËHET ORGANIZIMI?"]
  }
  const discussionChecked = fields[discussion] === "PO"
  const needsPlan = showAllFollowUps || hasAttendanceIssue || fields[underload] === "PO" || fields[overload] === "PO"
  const update = (label: string, value: string) => {
    const next: Record<string, string> = { [discussion]: "JO", [underload]: "JO", [overload]: "JO", ...fields, [label]: value }
    onChange(Object.values(REORGANIZATION_FIELDS).flatMap((field) => {
      const answer = next[field]
      return answer === undefined ? [] : [answer ? `${field}: ${answer.replace(/\n/g, "\n ")}` : `${field}:`]
    }).join("\n"))
  }
  const answerField = (label: string) => (
    <label className="grid gap-2 text-sm font-medium">
      {label}
      <Textarea value={fields[label] ?? ""} onChange={(event) => update(label, event.target.value)}
        rows={2} readOnly={readOnly} maxLength={maxLength} />
    </label>
  )
  return (
    <fieldset disabled={saving} className="mt-4 space-y-4">
      <div className="grid items-start gap-4 md:grid-cols-[7rem_minmax(0,1fr)]">
        <label className="grid w-28 gap-2 text-sm font-medium">
          {discussion}
          <span className="flex h-9 items-center justify-between rounded-md border border-input bg-background px-3 has-[:enabled]:cursor-pointer">
            <Checkbox checked={discussionChecked} disabled={readOnly}
              onCheckedChange={(checked) => update(discussion, checked === true ? "PO" : "JO")} />
            <span aria-hidden="true" className={discussionChecked ? "font-semibold text-emerald-700 dark:text-emerald-400" : "text-muted-foreground"}>
              {discussionChecked ? "PO" : "JO"}
            </span>
          </span>
        </label>
        {answerField(comment)}
      </div>
      <div className="flex flex-wrap gap-4">
        {[underload, overload].map((label) => (
          <label key={label} className="grid gap-2 text-sm font-medium">
            {label}
            <select value={fields[label] === "PO" ? "PO" : "JO"}
              onChange={(event) => update(label, event.target.value)} disabled={readOnly}
              className="h-9 rounded-md border border-input bg-background px-3 text-sm">
              <option value="JO">JO</option>
              <option value="PO">PO</option>
            </select>
          </label>
        ))}
      </div>
      {needsPlan ? answerField(plan) : null}
      {showAllFollowUps || hasAttendanceIssue ? answerField(cause) : null}
      {!readOnly && onSave ? (
        <Button type="button" variant="outline" size="sm" disabled={saveDisabled} onClick={onSave}>
          <Save className="h-4 w-4" /> Ruaj
        </Button>
      ) : null}
    </fieldset>
  )
}
