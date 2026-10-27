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
const dates = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]

test("print table includes only the selected day's column and entries", () => {
  const start = source.indexOf('<table className={cn("ga-time-table-table",')
  const table = source.slice(start, source.indexOf("</table>", start) + 8)
  const code = transpile(`const render = () => (${table});`)
  const entries = new Map(dates.map((date, day) => [`${day}|08:00`, [{ id: date, content: date }]]))
  for (const selected of ["", dates[1], dates[4]]) {
    const args = {
      React, cn: (...classes) => classes.filter(Boolean).join(" "),
      gaTimeSelectedDate: selected, gaTimeVisibleDates: selected ? [selected] : dates,
      fromISODate: iso => new Date(`${iso}T12:00:00`), getDayCode: d => d.getDay(),
      formatDateHuman: iso => iso, toDayOfWeek: iso => dates.indexOf(iso),
      gaTimeRows: [{ start: "08:00", end: "09:00", nrLabel: "1", label: "08:00 - 09:00" }],
      gaTimeCommentsForRow: () => [], gaTimeEntriesByCell: entries, gaMeetingsByCell: new Map(),
      gaTimeEntryStyle: () => ({}), GaTimeEntryContent: ({ entry }) => entry.content,
    }
    const render = new Function(...Object.keys(args), `${code}; return render;`)(...Object.values(args))
    const html = renderToStaticMarkup(React.createElement(render))
    assert.equal((html.match(/<th\s/g) || []).length, selected ? 4 : 9)
    assert.equal((html.match(/<td\s/g) || []).length, selected ? 4 : 9)
    for (const date of dates) {
      assert.equal(html.includes(date), !selected || date === selected)
    }
  }
  assert.equal(ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX).parseDiagnostics.length, 0)
})

test("Excel request passes the selected date and leaves weekly requests unfiltered", async () => {
  const start = source.indexOf("  const exportGaTime = async () => {")
  const code = transpile(source.slice(start, source.indexOf("  // Direct link for phones:", start)))
  for (const selected of ["", "2026-10-28"]) {
    let requested
    const args = {
      exportingGaTime: false, setExportingGaTime: () => {}, commonWeekStart: dates[0],
      toISODate: date => date, gaTimeSelectedDate: selected,
      apiFetch: async url => { requested = url; return { ok: false, text: async () => "test" } },
      toast: { error: () => {} },
    }
    const run = new Function(...Object.keys(args), `${code}; return exportGaTime;`)(...Object.values(args))
    await run()
    assert.equal(requested, `/exports/ga-time.xlsx?week_start=${dates[0]}${selected ? `&selected_date=${selected}` : ""}`)
  }
})
