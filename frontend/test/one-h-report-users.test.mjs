import assert from "node:assert/strict"
import test from "node:test"
import { reportTaskUsers, reportSummaryUser, reportUserOptions, reportPlannerUserOrder, isReportSummaryTask, collapseEmptyReportTaskRows } from "../src/lib/one-h-report-users.ts"

const cell = (dataset, text = "") => ({ dataset, querySelector: () => ({ textContent: text }) })

test("all report owners follow department and saved planner order, even outside the GA summary", () => {
  const departments = [
    { id: "dev", code: "DEV", name: "Development" },
    { id: "design", code: "GD", name: "Graphic Design" },
    { id: "pcm", code: "PCM", name: "Product Content" },
  ]
  const users = [
    ["D M", "pcm", 1], ["E S", "design", 0], ["E F", "dev", 0],
    ["R A", "dev", 1], ["L H", "dev", 2], ["O H", "pcm", 0],
    ["Absent User", "dev", 3], ["Z Z", "dev", null],
  ].map(([full_name, department_id, weekly_planner_sort_order]) => ({ full_name, department_id, weekly_planner_sort_order, email: "" }))
  const order = reportPlannerUserOrder(users, departments)
  assert.deepEqual(order, ["EF", "RA", "LH", "AU", "ZZ", "ES", "OH", "DM"])
  const document = { querySelectorAll: (selector) => selector.includes("data-task-card-row")
    ? [cell({ taskUsers: "RA|ES|DM|EF" }), cell({ taskUsers: "LH" })]
    : [cell({ gaSummaryUser: "EF" }), cell({ gaSummaryUser: "LH" }), cell({ gaSummaryUser: "OH" })] }
  assert.deepEqual(reportUserOptions(document, order), ["EF", "RA", "LH", "ES", "OH", "DM"])
})

test("report owners include every assignee and support older saved titles", () => {
  assert.deepEqual(reportTaskUsers(cell({ taskUsers: "EF|RA" })), ["EF", "RA"])
  assert.deepEqual(reportTaskUsers(cell({}, "2. EF/RA: Task with shared owners")), ["EF", "RA"])
  assert.deepEqual(reportTaskUsers(cell({}, "3. LH: Personal task")), ["LH"])
  assert.deepEqual(reportTaskUsers(cell({}, "")), [])
  assert.deepEqual(reportTaskUsers(cell({}, "1. Title mentions EF later")), [])
})

test("summary owners support current metadata and older saved summary cells", () => {
  assert.equal(reportSummaryUser(cell({ gaSummaryUser: "RA" })), "RA")
  assert.equal(reportSummaryUser(cell({}, " EF ")), "EF")
})

test("user options preserve summary order and append remaining task owners once", () => {
  const document = { querySelectorAll: (selector) => selector.includes("data-task-card-row")
    ? [cell({ taskUsers: "RA|EF" }), cell({}, "2. LH: Legacy task")]
    : [cell({ gaSummaryUser: "OH" }), cell({}, "EF")] }
  assert.deepEqual(reportUserOptions(document), ["OH", "EF", "RA", "LH"])
})

test("without a summary user options follow task appearance order", () => {
  const document = { querySelectorAll: (selector) => selector.includes("data-task-card-row")
    ? [cell({ taskUsers: "RA|EF" }), cell({ taskUsers: "RA|LH" })] : [] }
  assert.deepEqual(reportUserOptions(document), ["RA", "EF", "LH"])
})

test("clicking EF's P and M2 summary selects those tasks and excludes other EF work", () => {
  const tasks = [
    cell({ taskUsers: "EF", taskGaPersonal: "true" }),
    cell({ taskUsers: "EF", taskMarker: "M2", taskGaPersonal: "false" }),
    cell({ taskUsers: "EF", taskMarker: "M3", taskGaPersonal: "false" }),
    cell({ taskUsers: "RA", taskMarker: "M2" }),
  ]
  assert.deepEqual(tasks.map((task) => reportTaskUsers(task).includes("EF") && isReportSummaryTask(task)),
    [true, true, false, false])
})

test("summary filtering matches all counted symbols and older personal titles", () => {
  for (const marker of ["FLAG", "GA", "F", "M2", "M2_M3"]) {
    assert.equal(isReportSummaryTask(cell({ taskMarker: marker })), true)
  }
  assert.equal(isReportSummaryTask(cell({}, "1. EF/GA: Personal")), true)
  assert.equal(isReportSummaryTask(cell({}, "1. EF/KA/GA: Personal")), false)
  assert.equal(isReportSummaryTask(cell({}, "1. EF/GENT/GA: Personal")), false)
  assert.equal(isReportSummaryTask(cell({ taskGaPersonal: "false" }, "1. EF/GA: Ordinary task")), false)
})

test("filtered report hides empty slots and chunks, preserves labels and restores every row", () => {
  const task = (id, hidden) => ({ tagName: "TD", dataset: { taskId: id }, style: { display: hidden ? "none" : "" }, querySelector: () => null })
  const header = () => ({ tagName: "TH", dataset: {}, style: {}, rowSpan: 4 })
  const row = (cells) => {
    const result = {
      cells, dataset: {}, style: {},
      nextElementSibling: { style: {}, matches: () => true },
      get firstChild() { return this.cells[0] },
      insertBefore(node) {
        if (node.parent) node.parent.cells.splice(node.parent.cells.indexOf(node), 1)
        this.cells.unshift(node)
        node.parent = this
      },
    }
    cells.forEach((node) => { node.parent = result })
    return result
  }
  const labels = [header(), header()]
  const emptySlot = row([header(), header(), task("other", true)])
  const firstChunk = row([...labels, task("hidden-first", true)])
  const secondChunk = row([task("visible", false)])
  const rows = [emptySlot, firstChunk, secondChunk]
  const document = { querySelectorAll: () => rows }
  collapseEmptyReportTaskRows(document, true)
  assert.equal(emptySlot.style.display, "none")
  assert.equal(emptySlot.nextElementSibling.style.display, "none")
  assert.equal(firstChunk.style.display, "none")
  assert.equal(secondChunk.style.display, "")
  assert.deepEqual(secondChunk.cells.slice(0, 2), labels)
  assert.equal(labels[0].rowSpan, 2)
  // A second filter pass must keep the original slot groups intact.
  collapseEmptyReportTaskRows(document, true)
  assert.deepEqual(secondChunk.cells.slice(0, 2), labels)
  collapseEmptyReportTaskRows(document, false)
  assert.ok(rows.every((row) => row.style.display === "" && row.nextElementSibling.style.display === ""))
  assert.deepEqual(firstChunk.cells.slice(0, 2), labels)
  assert.equal(labels[0].rowSpan, 4)
  assert.equal(secondChunk.cells.length, 1)
})
