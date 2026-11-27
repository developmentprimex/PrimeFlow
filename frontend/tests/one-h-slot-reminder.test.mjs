import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import vm from "node:vm"
import ts from "typescript"

const source = readFileSync(new URL("../src/lib/task-reporting-choice.ts", import.meta.url), "utf8")
const exports = {}
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText,
  { exports, Headers, Response })
const { slotReminderRequest } = exports
const slot = { method: "PATCH", body: JSON.stringify({ one_h_report_slot: "16:00" }) }

for (const answer of ["continue", null]) {
  test(answer ? "Continue saves with the explicit choice" : "Cancel sends no slot change", async () => {
    const attempts = []
    let prompt = null
    const send = slotReminderRequest(async init => {
      const mode = init.headers.get("X-PrimeFlow-One-H-Slot-Reminder")
      attempts.push(mode)
      return mode === "continue" ? new Response(null, { status: 204 }) : Response.json({
        detail: { code: "ONE_H_PM_BLOCK_REMINDER", message: "Për shkak të Bllokut PM, mos cakto slotin 16:00." },
      }, { status: 409 })
    }, async details => {
      prompt = details.message
      assert.deepEqual(attempts, ["ask"])
      return answer
    })
    const response = await send(slot)
    assert.match(prompt, /Bllokut PM/)
    assert.deepEqual(attempts, answer ? ["ask", "continue"] : ["ask"])
    assert.equal(response.status, answer ? 204 : 409)
  })
}

test("A replacement applies only to affected assignees and survives another API prompt", async () => {
  const attempts = []
  const body = { assignee_states: [
    { assignee_id: "one", one_h_report_slot: "16:00", finish_period: "PM" },
    { assignee_id: "two", one_h_report_slot: "16:00", finish_period: "PM" },
  ] }
  const send = slotReminderRequest(async init => {
    attempts.push(JSON.parse(init.body))
    if (attempts.length > 1) return new Response(null, { status: 204 })
    return Response.json({ detail: {
      code: "ONE_H_PM_BLOCK_REMINDER", message: "Bllok PM", slots: ["11:50", "14:20"], assignee_ids: ["one"],
    } }, { status: 409 })
  }, async details => {
    assert.deepEqual(details.slots, ["11:50", "14:20"])
    return "11:50"
  })
  const init = { method: "PATCH", body: JSON.stringify(body) }
  await send(init)
  await send({ ...init, body: JSON.stringify({ ...body, confirmation: "reason" }) })
  const edited = [
    { assignee_id: "one", one_h_report_slot: "11:50", finish_period: "AM" },
    body.assignee_states[1],
  ]
  assert.deepEqual(attempts[1].assignee_states, edited)
  assert.deepEqual(attempts[2], { assignee_states: edited, confirmation: "reason" })
})
