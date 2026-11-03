import type { Department, Meeting } from "@/lib/types"
import { CommandGroup, CommandItem } from "@/components/ui/command"

export function RecordingMeetingOptions({ meetings, departments, onSelect }: {
  meetings: Meeting[]
  departments: Department[]
  onSelect: (id: string) => void
}) {
  const names = new Map(departments.map(department => [department.id, department.name]))
  const groups = new Map<string, Meeting[]>()
  for (const meeting of meetings) {
    const key = meeting.department_id || ""
    const group = groups.get(key) || []
    group.push(meeting)
    groups.set(key, group)
  }
  const label = (id: string) => id ? names.get(id) || "Departament tjetër" : "Pa departament"
  const timestamp = (meeting: Meeting) => {
    const value = meeting.starts_at ? Date.parse(meeting.starts_at) : NaN
    return Number.isFinite(value) ? value : -Infinity
  }
  return <>{[...groups].sort(([a], [b]) => {
    if (!a) return 1
    if (!b) return -1
    return label(a).localeCompare(label(b), "sq")
  }).map(([id, items]) => <CommandGroup key={id} heading={label(id)}>
    {[...items].sort((a, b) => timestamp(b) - timestamp(a) || a.title.localeCompare(b.title, "sq"))
      .map(meeting => {
        const date = Number.isFinite(timestamp(meeting)) ? new Date(meeting.starts_at!) : null
        return <CommandItem key={meeting.id} value={meeting.id} onSelect={() => onSelect(meeting.id)}>
          <span className="grid w-full min-w-0 grid-cols-[minmax(0,1fr)_6rem_3.5rem] items-center gap-3">
            <span className="truncate" title={meeting.title}>{meeting.title}</span>
            <span className="text-right tabular-nums text-muted-foreground">{date ? date.toLocaleDateString("en-GB").replaceAll("/", ".") : "Pa datë"}</span>
            <span className="text-right tabular-nums text-muted-foreground">{date ? date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }) : "—"}</span>
          </span>
        </CommandItem>
      })}
  </CommandGroup>)}</>
}
