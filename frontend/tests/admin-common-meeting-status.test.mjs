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
const evaluate = (code, args, result) => new Function(...Object.keys(args), `${transpile(code)}; return ${result};`)(...Object.values(args))
const helpers = evaluate(source.slice(source.indexOf("function meetingOccurrenceStatusLabel("), source.indexOf("export default function AdminTasksPage()")), { React },
  "({ meetingOccurrenceStatusLabel, MeetingOccurrenceStatusBadge, canceledMeetingsLast })")
const dates = ["2026-10-28", "2026-10-29", "2026-10-30"]
const meetings = dates.map((date, index) => ({ id: `meeting:recurring:${date}`, title: "Weekly meeting", time: "08:30", date, occurrenceStatus: ["held", "canceled", ""][index], assignees: ["RA"] }))
const tableDataByDay = Object.fromEntries(dates.map((date, index) => [date, { external: [meetings[index]], internal: [meetings[index]] }]))
const baseArgs = {
  React, tableDataByDay, commonGaRowsByDay: {}, ...helpers,
  commonPrintTitleLine: value => value, formatTimeLabel: value => value,
  entryAssignees: meeting => meeting.assignees || [], commonViewInitials: value => value,
  cn: (...classes) => classes.filter(Boolean).join(" "), isNonDailyWeeklyRecurrence: () => false,
}

test("Admin Tasks weekly EXT/INT cards show each occurrence status, keep avatars and cross only cancellations", () => {
  const start = source.indexOf("    const renderCellContent =")
  const render = evaluate(source.slice(start, source.indexOf("    const renderAssignedBadges =", start)), baseArgs, "renderCellContent")
  for (const kind of ["external", "internal"]) {
    for (const [index, date] of dates.entries()) {
      const html = renderToStaticMarkup(React.createElement(React.Fragment, null, render(kind, date)))
      assert.match(html, /Weekly meeting 08:30/)
      assert.match(html, /class="week-table-avatar" title="RA">RA/)
      assert.equal(html.includes("Mbajtur"), index === 0)
      assert.equal(html.includes("Anuluar"), index === 1)
      assert.equal(html.includes("meeting-occurrence-canceled"), index === 1)
      assert.equal(html.includes("data-meeting-status"), index !== 2)
    }
  }
})

test("weekly Excel export includes held/canceled labels and leaves unmarked meetings blank", () => {
  const start = source.indexOf("    const exportPayload = React.useMemo(")
  const payload = evaluate(source.slice(start, source.indexOf("    const repeatedTaskFirstDateByRow =", start)), {
    ...baseArgs, React: { useMemo: fn => fn() },
    commonWeekISOs: dates, weekTitleRange: "test week",
    fromISODate: value => value, getDayCode: value => value, formatDateHuman: value => value,
    weekTableRows: [{ id: "external", label: "TAK EXT" }, { id: "internal", label: "TAK INT" }],
  }, "exportPayload")
  for (const row of payload.rows) {
    assert.match(row[2], /\[Mbajtur\] Weekly meeting 08:30 \(RA\)/)
    assert.match(row[3], /\[Anuluar X\] Weekly meeting 08:30 \(RA\)/)
    assert.equal(row[4], "1. Weekly meeting 08:30 (RA)")
  }
})

test("weekly EXT and INT sort cancellations last per day and retain chronological order", () => {
  const start = source.indexOf("  const tableDataByDay = React.useMemo(")
  const items = [
    { title: "Canceled early", time: "08:00", date: dates[0], occurrenceStatus: "canceled" },
    { title: "Held", time: "10:00", date: dates[0], occurrenceStatus: "held" },
    { title: "Pending", time: "09:00", date: dates[0] },
    { title: "Other day", time: "08:00", date: dates[1], occurrenceStatus: "canceled" },
  ]
  const commonFiltered = Object.fromEntries(["late", "absent", "leave", "blocked", "oneH", "personal", "bz", "r1", "problems", "feedback", "priority"].map(key => [key, []]))
  Object.assign(commonFiltered, { external: items, internal: items, fullyCoveredDates: new Set() })
  const data = evaluate(source.slice(start, source.indexOf("  const weekTableRows =", start)), {
    React: { useMemo: fn => fn() }, commonFiltered, commonWeekISOs: dates,
    bzSystemTasksByDay: {}, allUsersLeaveByDate: new Map(), ...helpers,
    sortTasksByOrder: items => items,
    sortByTime: items => [...items].sort((a, b) => a.time.localeCompare(b.time)),
  }, "tableDataByDay")
  for (const kind of ["external", "internal"]) {
    assert.deepEqual(data[dates[0]][kind].map(item => item.title), ["Pending", "Held", "Canceled early"])
    assert.deepEqual(data[dates[1]][kind].map(item => item.title), ["Other day"])
  }
})
