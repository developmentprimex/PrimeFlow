"use client"

import { useEffect, useRef, useState, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog"
import { useAuth } from "@/lib/auth"
import { formatDepartmentName } from "@/lib/department-name"
import { checkMeetingAvailability, computeNextOccurrenceDate, type MeetingAvailability } from "@/lib/meeting-creation"
import type { Department, Meeting, UserLookup } from "@/lib/types"

const field = "block w-full min-w-0 rounded-md border bg-background px-2 py-1.5 text-sm"
const weekdays = ["Hënë", "Martë", "Mërkurë", "Enjte", "Premte", "Shtunë", "Diel"]
type Recurrence = "none" | "weekly" | "monthly" | "yearly"

function localInput(value: string) {
  const date = new Date(value)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

export function InternalMeetingCreateDialog({ onCreated }: { onCreated: (meeting: Meeting) => void }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  return (
    <Dialog open={open} onOpenChange={(next) => { if (!busy) setOpen(next) }}>
      <DialogTrigger asChild><Button type="button" size="sm" variant="outline">Shto takim intern</Button></DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogTitle>Shto takim intern</DialogTitle>
        <DialogDescription>Cakto orarin dhe pjesëmarrësit e takimit.</DialogDescription>
        {open && <InternalMeetingForm busy={busy} setBusy={setBusy} onCancel={() => setOpen(false)}
          onCreated={(meeting) => { setOpen(false); onCreated(meeting) }} />}
      </DialogContent>
    </Dialog>
  )
}

function InternalMeetingForm({ busy, setBusy, onCancel, onCreated }: {
  busy: boolean
  setBusy: (busy: boolean) => void
  onCancel: () => void
  onCreated: (meeting: Meeting) => void
}) {
  const { apiFetch, user } = useAuth()
  const [departments, setDepartments] = useState<Department[]>([])
  const [people, setPeople] = useState<UserLookup[]>([])
  const [loading, setLoading] = useState(true)
  const [loadRevision, setLoadRevision] = useState(0)
  const [loadFailed, setLoadFailed] = useState(false)
  const [error, setError] = useState("")
  const [title, setTitle] = useState("")
  const [platform, setPlatform] = useState("")
  const [department, setDepartment] = useState(user?.department_id ?? "")
  const [participants, setParticipants] = useState<string[]>([])
  const [all, setAll] = useState(false)
  const [search, setSearch] = useState("")
  const [recurrence, setRecurrence] = useState<Recurrence>("none")
  const [dateTime, setDateTime] = useState("")
  const [clock, setClock] = useState("")
  const [weekdaysSelected, setWeekdaysSelected] = useState<number[]>([])
  const [monthDays, setMonthDays] = useState<number[]>([])
  const [yearMonth, setYearMonth] = useState(1)
  const [yearDay, setYearDay] = useState(1)
  const [availability, setAvailability] = useState<MeetingAvailability | null>(null)
  const submitting = useRef(false)
  const selectedDepartment = department || (user?.role !== "STAFF" ? departments[0]?.id : "") || ""
  const selectedPeople = all ? people.map((person) => person.id) : participants
  const personName = (person: UserLookup) => person.full_name || person.username || person.email

  useEffect(() => {
    const controller = new AbortController()
    const load = async () => {
      try {
        const [departmentResponse, peopleResponse] = await Promise.all([
          apiFetch("/departments", { signal: controller.signal }),
          apiFetch("/users/lookup?include_inactive=false", { signal: controller.signal }),
        ])
        if (!departmentResponse.ok || !peopleResponse.ok) throw new Error()
        const [nextDepartments, nextPeople] = await Promise.all([
          departmentResponse.json() as Promise<Department[]>,
          peopleResponse.json() as Promise<UserLookup[]>,
        ])
        if (!controller.signal.aborted) {
          setDepartments(nextDepartments)
          setPeople(nextPeople.filter((person) => person.is_active !== false))
        }
      } catch {
        if (!controller.signal.aborted) setLoadFailed(true)
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    void load()
    return () => controller.abort()
  }, [apiFetch, loadRevision])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting.current || loading || !selectedDepartment || !selectedPeople.length || title.trim().length < 2) return
    const start = recurrence === "none" ? new Date(dateTime) : computeNextOccurrenceDate({
      recurrenceType: recurrence,
      daysOfWeek: weekdaysSelected,
      daysOfMonth: recurrence === "yearly" ? [yearDay] : monthDays,
      monthOfYear: yearMonth - 1,
      timeValue: clock,
    })
    if (!start || !Number.isFinite(start.getTime())) {
      setError("Zgjidh një datë, orë dhe ditët e përsëritjes kur duhen.")
      return
    }
    if (start.getTime() < Date.now()) {
      setError("Takimi nuk mund të planifikohet në të kaluarën.")
      return
    }
    const approvedConflict = Boolean(availability?.conflicts.length)
    submitting.current = true
    setBusy(true)
    setError("")
    try {
      if (!approvedConflict) {
        const result = await checkMeetingAvailability(apiFetch, {
          title, meetingType: "internal", startsAt: start, departmentId: selectedDepartment, participantIds: selectedPeople,
        })
        if (!result) throw new Error("Orari nuk u verifikua. Provo përsëri.")
        if (result.conflicts.length) {
          setAvailability(result)
          return
        }
        if (!result.can_create) throw new Error(result.errors.join(" ") || "Orari nuk është i disponueshëm.")
      }
      const response = await apiFetch("/meetings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: title.trim(), platform: platform.trim() || null,
          starts_at: start.toISOString(), meeting_type: "internal", department_id: selectedDepartment,
          participant_ids: selectedPeople, all_participants: all,
          recurrence_type: recurrence === "none" ? null : recurrence,
          recurrence_days_of_week: recurrence === "weekly" ? weekdaysSelected : null,
          recurrence_days_of_month: recurrence === "monthly" ? monthDays : recurrence === "yearly" ? [yearDay] : null,
          allow_one_h_conflict: approvedConflict && Boolean(availability?.conflicts.some((conflict) => conflict.source === "one_h")),
        }),
      })
      if (!response.ok) {
        const data = await response.json().catch(() => null)
        setAvailability(null)
        const message = data?.detail?.message || data?.detail
        throw new Error(typeof message === "string" ? message : "Takimi nuk u ruajt.")
      }
      onCreated(await response.json() as Meeting)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Takimi nuk u ruajt.")
    } finally {
      submitting.current = false
      setBusy(false)
    }
  }

  function toggleDay(day: number, current: number[], set: (days: number[]) => void) {
    set(current.includes(day) ? current.filter((value) => value !== day) : [...current, day])
  }

  return (
    <form className="space-y-3" onSubmit={submit} onChange={() => setAvailability(null)}>
      <fieldset className="grid min-w-0 gap-3 sm:grid-cols-2" disabled={busy}>
        <label className="space-y-1 text-sm sm:col-span-2">Titulli
          <input className={field} value={title} onChange={(event) => setTitle(event.target.value)} required minLength={2} maxLength={200} />
        </label>
        <label className="space-y-1 text-sm">Platforma
          <input className={field} value={platform} onChange={(event) => setPlatform(event.target.value)} placeholder="Teams, Office…" />
        </label>
        <label className="space-y-1 text-sm">Përsëritja
          <select className={field} value={recurrence} onChange={(event) => setRecurrence(event.target.value as Recurrence)}>
            <option value="none">Një herë</option><option value="weekly">Çdo javë</option>
            <option value="monthly">Çdo muaj</option><option value="yearly">Çdo vit</option>
          </select>
        </label>
        {recurrence === "none" ? (
          <label className="space-y-1 text-sm">Data dhe ora
            <input className={field} type="datetime-local" value={dateTime}
              onChange={(event) => setDateTime(event.target.value)} required />
          </label>
        ) : (
          <label className="space-y-1 text-sm">Ora
            <input className={field} type="time" value={clock} onChange={(event) => setClock(event.target.value)} required />
          </label>
        )}
        <label className="space-y-1 text-sm">Departamenti
          <select className={field} value={selectedDepartment} disabled={loading || user?.role === "STAFF"}
            onChange={(event) => setDepartment(event.target.value)} required>
            <option value="">Zgjidh departamentin</option>
            {departments.map((item) => <option key={item.id} value={item.id}>{formatDepartmentName(item.name)}</option>)}
          </select>
        </label>
        {recurrence === "weekly" && <fieldset className="flex flex-wrap gap-2 text-sm sm:col-span-2">
          <legend>Ditët e javës</legend>
          {weekdays.map((day, index) => <label key={day} className="flex items-center gap-1">
            <input type="checkbox" checked={weekdaysSelected.includes(index)} onChange={() => toggleDay(index, weekdaysSelected, setWeekdaysSelected)} />{day}
          </label>)}
        </fieldset>}
        {recurrence === "monthly" && <fieldset className="grid grid-cols-7 gap-1 text-sm sm:col-span-2">
          <legend>Ditët e muajit</legend>
          {Array.from({ length: 31 }, (_, index) => index + 1).map((day) => <label key={day} className="flex items-center gap-1">
            <input type="checkbox" checked={monthDays.includes(day)} onChange={() => toggleDay(day, monthDays, setMonthDays)} />{day}
          </label>)}
        </fieldset>}
        {recurrence === "yearly" && <>
          <label className="space-y-1 text-sm">Muaji
            <select className={field} value={yearMonth} onChange={(event) => setYearMonth(Number(event.target.value))}>
              {Array.from({ length: 12 }, (_, index) => <option key={index} value={index + 1}>
                {new Intl.DateTimeFormat("sq-AL", { month: "long", timeZone: "UTC" }).format(new Date(Date.UTC(2000, index, 1)))}
              </option>)}
            </select>
          </label>
          <label className="space-y-1 text-sm">Dita e muajit
            <select className={field} value={yearDay} onChange={(event) => setYearDay(Number(event.target.value))}>
              {Array.from({ length: 31 }, (_, index) => <option key={index} value={index + 1}>{index + 1}</option>)}
            </select>
          </label>
        </>}
        <fieldset className="space-y-2 text-sm sm:col-span-2">
          <legend>Pjesëmarrësit ({selectedPeople.length})</legend>
          <div className="flex items-center gap-3">
            <input aria-label="Kërko pjesëmarrës" className={field} value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Kërko pjesëmarrës…" />
            {user?.role !== "STAFF" && <label className="flex shrink-0 items-center gap-1">
              <input type="checkbox" checked={all} disabled={!people.length} onChange={(event) => setAll(event.target.checked)} /> ALL
            </label>}
          </div>
          <div className="grid max-h-36 gap-1 overflow-y-auto rounded-md border p-2 sm:grid-cols-2">
            {people.filter((person) => personName(person).toLowerCase().includes(search.trim().toLowerCase())).map((person) => (
              <label key={person.id} className="flex min-w-0 items-center gap-2">
                <input type="checkbox" checked={selectedPeople.includes(person.id)} onChange={() => {
                  setAll(false)
                  setParticipants(selectedPeople.includes(person.id) ? selectedPeople.filter((id) => id !== person.id) : [...selectedPeople, person.id])
                }} />
                <span className="break-words">{personName(person)}</span>
              </label>
            ))}
            {loading && <p>Duke ngarkuar pjesëmarrësit…</p>}
          </div>
        </fieldset>
      </fieldset>
      {availability && (
        <div className="space-y-2 rounded-md border p-2 text-sm" role="status">
          <p className="font-medium">Ky orar ka mbivendosje</p>
          <ul className="list-disc pl-5">{availability.conflicts.map((conflict, index) =>
            <li key={index}>{conflict.source === "one_h" ? "1H" : conflict.title} · {new Date(conflict.starts_at).toLocaleString("sq-AL")}</li>
          )}</ul>
          {availability.suggested_slot && recurrence === "none" && (
            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => {
              setDateTime(localInput(availability.suggested_slot!.starts_at))
              setAvailability(null)
            }}>Përdor orarin e lirë</Button>
          )}
        </div>
      )}
      {loadFailed && <p role="alert" className="text-sm text-destructive">Departamentet dhe pjesëmarrësit nuk u ngarkuan.</p>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <div className="flex flex-wrap justify-end gap-2">
        {loadFailed && (
          <Button type="button" variant="outline" onClick={() => { setLoadFailed(false); setLoading(true); setLoadRevision((value) => value + 1) }}>Ringarko listën</Button>
        )}
        <Button type="button" variant="outline" disabled={busy} onClick={onCancel}>Kthehu</Button>
        <Button type="submit" disabled={busy || loading || !selectedDepartment || !selectedPeople.length || title.trim().length < 2}>
          {busy ? "Duke kontrolluar…" : availability ? "Aprovo gjithsesi" : "Shto takimin"}
        </Button>
      </div>
    </form>
  )
}
