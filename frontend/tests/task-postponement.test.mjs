import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { test } from "node:test"
import vm from "node:vm"
import ts from "typescript"

const source = readFileSync(new URL("../src/lib/task-postponement.ts", import.meta.url), "utf8")
const module = { exports: {} }
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
} }).outputText, { module, exports: module.exports, Response, DOMException })
const { withPostponementExplanation } = module.exports
const detail = { code: "TASK_POSTPONEMENT_EXPLANATION_REQUIRED", task_title: "Task", changes: [{ field: "due_date", from: "2026-10-20", to: "2026-10-21" }] }
const conflict = () => Response.json({ detail }, { status: 409 })
const init = { method: "PATCH", body: JSON.stringify({ due_date: "2026-10-21", title: "Unchanged payload" }) }

test("retries a rejected date write only after collecting both fields, preserving its payload", async () => {
  const requests = []
  let prompts = 0
  const response = await withPostponementExplanation("/tasks/task-id", init, async request => {
    requests.push(JSON.parse(request.body))
    return requests.length === 1 ? conflict() : Response.json({ id: "task-id" })
  }, async info => {
    prompts++
    assert.equal(info.task_title, "Task")
    return { postponement_reason_code: "OTHER", postponement_comment: " Explanation " }
  })
  assert.equal(response.status, 200)
  assert.equal(prompts, 1)
  assert.deepEqual(requests, [JSON.parse(init.body), { ...JSON.parse(init.body), postponement_reason_code: "OTHER", postponement_comment: "Explanation" }])
})

test("cancel, whitespace, and incomplete explanations never send the date again", async () => {
  for (const answer of [null, { postponement_reason_code: "OTHER", postponement_comment: "  " }, { postponement_comment: "Why" }]) {
    let requests = 0
    const response = await withPostponementExplanation("/tasks/task-id", init, async () => { requests++; return conflict() }, async () => answer)
    assert.equal(requests, 1)
    assert.equal(response.ok, false)
  }
})

test("unrelated errors and successful requests retain their response and do not prompt", async () => {
  for (const status of [200, 400, 403, 409, 500]) {
    const original = Response.json({ detail: "Original message" }, { status })
    let requests = 0
    const response = await withPostponementExplanation("/tasks/task-id", init, async () => { requests++; return original }, async () => assert.fail("Unexpected prompt"))
    assert.equal(requests, 1)
    assert.equal(response, original)
    assert.deepEqual(await response.json(), { detail: "Original message" })
  }
})

test("system occurrence moves use the same guard and aborting while explaining prevents the retry", async () => {
  const controller = new AbortController()
  let requests = 0
  const response = await withPostponementExplanation("/system-tasks/occurrence-date", { ...init, signal: controller.signal },
    async () => { requests++; return conflict() }, async () => {
      controller.abort()
      return { postponement_reason_code: "OTHER", postponement_comment: "Why" }
    })
  assert.equal(requests, 1)
  assert.equal(response.ok, false)
})

for (const path of ["/ga-notes/note/task-bundle", "/plan-notes/note/task-bundle", "/plan-notes/note/task-deadline"]) {
  test(`${path} collects every task explanation before one atomic retry`, async () => {
    const requests = [], prompted = []
    const body = { content: "Keep draft", assignee_states: [{ assignee_id: "a", due_date: "2026-10-21" }] }
    const response = await withPostponementExplanation(path, { method: "PATCH", body: JSON.stringify(body) }, async request => {
      requests.push(JSON.parse(request.body))
      return requests.length === 1 ? Response.json({ detail: { ...detail, postponements: [
        { ...detail, task_id: "task-a", assignee_id: "a" }, { ...detail, task_id: "task-b", assignee_id: "b" },
      ] } }, { status: 409 }) : Response.json({ saved: true })
    }, async info => { prompted.push(info.task_id); return { postponement_reason_code: "OTHER", postponement_comment: `Why ${info.task_id}` } })
    assert.equal(response.ok, true)
    assert.deepEqual(prompted, ["task-a", "task-b"])
    assert.equal(requests.length, 2)
    assert.deepEqual(requests[1], { ...body, postponement_explanations: {
      "task-a": { postponement_reason_code: "OTHER", postponement_comment: "Why task-a" },
      "task-b": { postponement_reason_code: "OTHER", postponement_comment: "Why task-b" },
    } })
  })
}

test("canceling a later note task explanation never partially submits the bundle", async () => {
  let requests = 0, prompts = 0
  const response = await withPostponementExplanation("/ga-notes/note/task-bundle", init, async () => {
    requests++
    return Response.json({ detail: { ...detail, postponements: [{ ...detail, task_id: "a" }, { ...detail, task_id: "b" }] } }, { status: 409 })
  }, async () => ++prompts === 1 ? { postponement_reason_code: "OTHER", postponement_comment: "First reason" } : null)
  assert.equal(response.ok, false)
  assert.equal(requests, 1)
  assert.equal(prompts, 2)
})
