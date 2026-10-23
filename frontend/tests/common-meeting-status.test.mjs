import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import ts from "typescript"

const source = readFileSync(new URL("../src/app/(app)/common/page.tsx", import.meta.url), "utf8").replace(/\r\n/g, "\n")
const occurrenceStatusKey = (id, date) => `${id}|${date}`
const transpile = (code) => ts.transpileModule(code, {
  compilerOptions: { jsx: ts.JsxEmit.React, target: ts.ScriptTarget.ES2020 },
}).outputText

test("full Common View shows held and canceled statuses only on the matching occurrence", () => {
  const code = source.slice(source.indexOf("  const renderWeekMeetingStatus ="), source.indexOf("  const renderSwimlaneMeetingStatusControl ="))
  const statuses = new Map([
    ["external|2026-10-19", { status: "held" }],
    ["internal|2026-10-20", { status: "canceled" }],
  ])
  const render = new Function("React", "meetingOccurrenceStatuses", "occurrenceStatusKey",
    transpile(code) + "; return renderWeekMeetingStatus;")(React, statuses, occurrenceStatusKey)
  assert.match(renderToStaticMarkup(render({ id: "meeting:external:2026-10-19" }, "2026-10-19")), /Mbajtur/)
  assert.match(renderToStaticMarkup(render({ id: "meeting:internal" }, "2026-10-20")), /Anuluar/)
  assert.equal(render({ id: "meeting:external:2026-10-19" }, "2026-10-20"), null)
  assert.equal(render({ id: "manual-entry" }, "2026-10-19"), null)
  assert.equal(render({}, "2026-10-19"), null)
  assert.equal(source.split("{renderWeekMeetingStatus(e, iso)}").length - 1, 2)
})

test("status loader includes every displayed date, including the whole week when unfiltered", async () => {
  const code = source.slice(source.indexOf("  const loadMeetingOccurrenceStatuses ="), source.indexOf("  React.useEffect(() => {\n    void loadMeetingOccurrenceStatuses()"))
  const weekISOs = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"]
  for (const selected of [weekISOs.slice(0, 2), []]) {
    const requested = []
    let loaded
    const apiFetch = async (url) => {
      const date = url.split("=")[1]
      requested.push(date)
      return { ok: true, json: async () => [{ meeting_id: "external", occurrence_date: date, status: "held" }] }
    }
    const run = new Function("React", "apiFetch", "meetingStatusDate", "selectedDates", "weekISOs", "occurrenceStatusKey",
      "internalMeetingsOpen", "internalMeetingListFilter", "internalMeetingsVisible", "internalMeetingDateFilter", "setMeetingOccurrenceStatuses",
      transpile(code) + "; return loadMeetingOccurrenceStatuses;")(
        { useCallback: (fn) => fn }, apiFetch, "2026-10-23", new Set(selected), weekISOs, occurrenceStatusKey,
        false, "all", [], "", (rows) => { loaded = rows },
      )
    await run()
    const expected = new Set(["2026-10-23", ...(selected.length ? selected : weekISOs)])
    assert.deepEqual(new Set(requested), expected)
    for (const date of expected) assert.equal(loaded.get(`external|${date}`).status, "held")
  }
  const file = ts.createSourceFile("page.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  assert.equal(file.parseDiagnostics.length, 0)
})
