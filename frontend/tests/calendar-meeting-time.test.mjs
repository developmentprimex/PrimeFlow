import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import ts from "typescript"

process.env.TZ = "Europe/Tirane"
const source = readFileSync(new URL("../src/lib/calendar-meeting-time.ts", import.meta.url), "utf8")
const module = { exports: {} }
new Function("module", "exports", ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText)(module, module.exports)
const { calendarMeetingTimeRange, meetingTimeColumns } = module.exports
const meeting = { meeting_type: "external", calendar_imported: true,
  starts_at: "2026-11-04T09:00:00Z", ends_at: "2026-11-04T10:30:00Z" }

test("calendar window uses local time without a parenthesized day offset", () => {
  assert.equal(calendarMeetingTimeRange(meeting), "10:00 - 11:30")
  assert.equal(calendarMeetingTimeRange({ ...meeting, ends_at: "2026-11-05T01:00:00Z" }), "10:00 - 02:00")
})

test("time columns separate clocks, omit old day offsets and leave an unknown end blank", () => {
  assert.deepEqual(meetingTimeColumns("23:00 - 01:00 (+1d)"), { from: "23:00", to: "01:00" })
  assert.deepEqual(meetingTimeColumns("10:00"), { from: "10:00", to: "-" })
})

test("missing or invalid end, manual and internal meetings keep their previous start label", () => {
  for (const override of [{ ends_at: null }, { ends_at: "bad" }, { starts_at: "bad" },
    { ends_at: meeting.starts_at }, { ends_at: "2026-11-04T08:00:00Z" },
    { meeting_type: "internal" }, { calendar_imported: false }]) {
    assert.equal(calendarMeetingTimeRange({ ...meeting, ...override }), null)
  }
  assert.equal(calendarMeetingTimeRange({ ...meeting, calendar_imported: false, microsoft_event_id: "event" }), "10:00 - 11:30")
})
