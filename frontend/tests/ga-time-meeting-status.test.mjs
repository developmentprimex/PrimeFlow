import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import ts from "typescript"

const source = readFileSync(new URL("../src/app/(app)/admin-tasks/page.tsx", import.meta.url), "utf8").replace(/\r\n/g, "\n")
const transpile = code => ts.transpileModule(code, {
  compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2020 },
}).outputText
const component = source.slice(source.indexOf("function GaTimeMeetingCard("), source.indexOf("export default function AdminTasksPage()"))
const GaTimeMeetingCard = new Function("React", "cn", "formatTimeLabel", "internalMeetingLegendTone", "meetingLegendTone",
  `${transpile(component)}; return GaTimeMeetingCard;`)(
    React, (...classes) => classes.filter(Boolean).join(" "), value => value,
    () => "outlook-manual", () => "outlook-teal",
  )

test("external and internal timetable meetings show held/canceled or a blank status", () => {
  for (const kind of ["external", "internal"]) {
    for (const status of [undefined, "", "planned", "held", "canceled"]) {
      const html = renderToStaticMarkup(React.createElement(GaTimeMeetingCard, {
        kind, meeting: { id: "meeting:recurring:2026-10-28", date: "2026-10-28", time: "08:30", title: "Weekly meeting", occurrenceStatus: status },
      }))
      assert.match(html, /Weekly meeting/)
      assert.match(html, /08:30/)
      assert.match(html, kind === "internal" ? /TAK INT:/ : /TAK EXT:/)
      assert.equal(html.includes("Mbajtur"), status === "held")
      assert.equal(html.includes("Anuluar"), status === "canceled")
      assert.equal(html.includes("ga-time-meeting-canceled"), status === "canceled")
      assert.equal(html.includes("data-meeting-status"), status === "held" || status === "canceled")
    }
  }
})

test("printed timetable uses each day's occurrence status for the same recurring meeting", () => {
  const start = source.indexOf('<table className={cn("ga-time-table-table",')
  const table = source.slice(start, source.indexOf("</table>", start) + 8)
  const dates = ["2026-10-28", "2026-10-29", "2026-10-30"]
  const meetings = new Map(dates.map((date, index) => [`${index}|08:00`, [{
    kind: "external", meeting: { id: `meeting:recurring:${date}`, title: `Meeting ${date}`, date, time: "08:30", occurrenceStatus: ["held", "canceled", ""][index] },
  }]]))
  const args = {
    React, cn: (...classes) => classes.filter(Boolean).join(" "), GaTimeMeetingCard,
    gaTimeSelectedDate: "", gaTimeVisibleDates: dates,
    fromISODate: iso => new Date(`${iso}T12:00:00`), getDayCode: d => d.getDay(),
    formatDateHuman: iso => iso, toDayOfWeek: iso => dates.indexOf(iso),
    gaTimeRows: [{ start: "08:00", end: "09:00", nrLabel: "1", label: "08:00 - 09:00" }],
    gaTimeCommentsForRow: () => [], gaTimeEntriesByCell: new Map(), gaMeetingsByCell: meetings,
    gaTimeEntryStyle: () => ({}), GaTimeEntryContent: () => null,
  }
  const render = new Function(...Object.keys(args), `${transpile(`const render = () => (${table});`)}; return render;`)(...Object.values(args))
  const html = renderToStaticMarkup(React.createElement(render))
  assert.equal((html.match(/data-meeting-status="held"/g) || []).length, 1)
  assert.equal((html.match(/data-meeting-status="canceled"/g) || []).length, 1)
  assert.equal((html.match(/ga-time-meeting-canceled/g) || []).length, 1)
  for (const date of dates) assert.ok(html.includes(`Meeting ${date}`))
})

test("canceled meetings follow other meetings in the same slot without moving to another day or time", () => {
  const start = source.indexOf("  const gaMeetingsByCell = React.useMemo(")
  const code = source.slice(start, source.indexOf("  const createGaTimeEntry =", start))
  const args = {
    React: { useMemo: fn => fn() },
    commonFiltered: {
      internal: [{ title: "Held", date: "2026-10-28", time: "08:30", occurrenceStatus: "held" }],
      external: [
        { title: "Canceled", date: "2026-10-28", time: "08:00", occurrenceStatus: "canceled" },
        { title: "Pending", date: "2026-10-28", time: "08:15" },
        { title: "Next slot", date: "2026-10-28", time: "09:00", occurrenceStatus: "canceled" },
        { title: "Other day", date: "2026-10-29", time: "08:00", occurrenceStatus: "canceled" },
      ],
    },
    commonWeekISOs: ["2026-10-28", "2026-10-29"], gaTimeRows: [{ start: "08:00" }, { start: "09:00" }],
    parseTimeToMinutes: value => Number(value.slice(0, 2)) * 60 + Number(value.slice(3)),
    resolveGaTimeRowStart: value => value.slice(0, 2) + ":00",
    minutesToTimeValue: value => `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`,
    toDayOfWeek: date => date, isManualInternalMeeting: () => true,
  }
  const cells = new Function(...Object.keys(args), `${transpile(code)}; return gaMeetingsByCell;`)(...Object.values(args))
  assert.deepEqual(cells.get("2026-10-28|08:00").map(item => item.meeting.title), ["Pending", "Held", "Canceled"])
  assert.deepEqual(cells.get("2026-10-28|09:00").map(item => item.meeting.title), ["Next slot"])
  assert.deepEqual(cells.get("2026-10-29|08:00").map(item => item.meeting.title), ["Other day"])
})
