"use client"

import type { Meeting, UserLookup } from "@/lib/types"
import { useCanceledMeetings } from "@/lib/use-canceled-meetings"
import { MeetingCanceledBadge } from "@/components/meeting-canceled-badge"

type DailyReportMeetingsTableProps = {
  meetings: Meeting[]
  users: UserLookup[]
  reportDateIso: string
}

function parseDateOnly(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return null
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
  return Number.isNaN(date.getTime()) ? null : date
}

function isSameCalendarDay(left: Date, right: Date): boolean {
  return left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate()
}

function meetingOccursOnDate(meeting: Meeting, reportDate: Date): boolean {
  if (!meeting.starts_at) return false
  const start = new Date(meeting.starts_at)
  if (Number.isNaN(start.getTime())) return false

  const recurrenceType = meeting.recurrence_type || "none"
  if (recurrenceType === "none") return isSameCalendarDay(start, reportDate)

  const reportDayStart = new Date(reportDate)
  reportDayStart.setHours(0, 0, 0, 0)
  const meetingDayStart = new Date(start)
  meetingDayStart.setHours(0, 0, 0, 0)
  if (reportDayStart < meetingDayStart) return false

  if (recurrenceType === "weekly") {
    if (!meeting.recurrence_days_of_week?.length) return isSameCalendarDay(start, reportDate)
    const mondayBasedDay = (reportDate.getDay() + 6) % 7
    return meeting.recurrence_days_of_week.includes(mondayBasedDay)
  }
  if (recurrenceType === "monthly") {
    if (!meeting.recurrence_days_of_month?.length) return isSameCalendarDay(start, reportDate)
    return meeting.recurrence_days_of_month.includes(reportDate.getDate())
  }
  if (recurrenceType === "yearly") {
    return reportDate.getMonth() === start.getMonth() && reportDate.getDate() === start.getDate()
  }
  return isSameCalendarDay(start, reportDate)
}

function participantLabel(user: UserLookup): string {
  return user.full_name?.trim() || user.username?.trim() || user.email
}

export function DailyReportMeetingsTable({
  meetings,
  users,
  reportDateIso,
}: DailyReportMeetingsTableProps) {
  const canceledMeetings = useCanceledMeetings(reportDateIso)
  const reportDate = parseDateOnly(reportDateIso)
  const userNames = new Map(users.map((user) => [user.id, participantLabel(user)]))
  const reportMeetings = reportDate
    ? meetings
      .filter((meeting) => meetingOccursOnDate(meeting, reportDate))
      .sort((left, right) => {
        const leftDate = left.starts_at ? new Date(left.starts_at) : null
        const rightDate = right.starts_at ? new Date(right.starts_at) : null
        const leftTime = leftDate ? leftDate.getHours() * 60 + leftDate.getMinutes() : 0
        const rightTime = rightDate ? rightDate.getHours() * 60 + rightDate.getMinutes() : 0
        return leftTime - rightTime
      })
    : []

  return (
    <section className="mt-3 overflow-hidden rounded-lg border border-slate-300 bg-white" aria-label="Daily meetings">
      <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-3 py-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-700">Meetings</h3>
        <span className="text-[11px] text-slate-500">{reportMeetings.length} total</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[900px] table-fixed border-collapse text-[11px]">
          <colgroup>
            <col className="w-[42px]" />
            <col className="w-[80px]" />
            <col className="w-[260px]" />
            <col />
            <col className="w-[120px]" />
            <col className="w-[110px]" />
            <col className="w-[90px]" />
          </colgroup>
          <thead className="bg-slate-50 text-slate-700">
            <tr>
              <th className="border border-slate-200 px-2 py-2 text-left uppercase">Nr</th>
              <th className="border border-slate-200 px-2 py-2 text-left uppercase">Lloji</th>
              <th className="border border-slate-200 px-2 py-2 text-left uppercase">Emri</th>
              <th className="border border-slate-200 px-2 py-2 text-left uppercase">Personat</th>
              <th className="border border-slate-200 px-2 py-2 text-left uppercase">Kur</th>
              <th className="border border-slate-200 px-2 py-2 text-left uppercase">Data</th>
              <th className="border border-slate-200 px-2 py-2 text-left uppercase">Koha</th>
            </tr>
          </thead>
          <tbody>
            {reportMeetings.length ? (
              reportMeetings.map((meeting, index) => {
                const start = new Date(meeting.starts_at as string)
                const isExternal = (meeting.meeting_type || "external") === "external"
                const persons = (meeting.participant_ids || [])
                  .map((participantId) => userNames.get(participantId))
                  .filter((name): name is string => Boolean(name))
                return (
                  <tr
                    key={meeting.id}
                    className={isExternal ? "bg-red-50/40 outline outline-2 outline-red-500 outline-offset-[-2px]" : "bg-white"}
                  >
                    <td className="border border-slate-200 px-2 py-2 align-top">{index + 1}</td>
                    <td className="border border-slate-200 px-2 py-2 align-top">
                      <span className={`inline-flex rounded-full border px-2 py-0.5 font-semibold ${isExternal
                        ? "border-red-500 bg-red-100 text-red-700"
                        : "border-blue-300 bg-blue-50 text-blue-700"
                        }`}>
                        {isExternal ? "EXT" : "INT"}
                      </span>
                    </td>
                    <td className="border border-slate-200 px-2 py-2 align-top font-semibold text-slate-900">
                      {meeting.title || "Meeting"}
                      {canceledMeetings.has(meeting.id) ? <MeetingCanceledBadge /> : null}
                    </td>
                    <td className="border border-slate-200 px-2 py-2 align-top text-slate-700">
                      {persons.length ? persons.join(", ") : "-"}
                    </td>
                    <td className="border border-slate-200 px-2 py-2 align-top text-slate-700">
                      {reportDate?.toLocaleDateString("en-US", { weekday: "long" }) || "-"}
                    </td>
                    <td className="border border-slate-200 px-2 py-2 align-top text-slate-700">
                      {reportDate?.toLocaleDateString("en-GB") || "-"}
                    </td>
                    <td className="border border-slate-200 px-2 py-2 align-top font-medium text-slate-900">
                      {start.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}
                    </td>
                  </tr>
                )
              })
            ) : (
              <tr>
                <td colSpan={7} className="border border-slate-200 px-3 py-4 text-center text-slate-500">
                  No meetings for this date.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
