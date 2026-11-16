import { test, expect, type Page } from "@playwright/test"
import { readFileSync } from "node:fs"
import ts from "typescript"

const noteId = "11111111-1111-4111-8111-111111111111"
const departmentId = "99999999-9999-4999-8999-999999999999"
const owners = ["First owner", "Second owner", "Third owner"].map((full_name, index) => ({
  id: `${index + 2}${"2".repeat(7)}-2222-4222-8222-222222222222`, full_name,
  email: `owner${index}@example.com`, role: "STAFF", is_active: true, department_id: departmentId,
}))

async function openEditor(page: Page, source: "ga-notes" | "plan-notes") {
  const user = { ...owners[0], role: "ADMIN" }
  const now = new Date().toISOString()
  const note = { id: noteId, content: "Shared work", created_by: user.id, status: "OPEN", note_type: "GA",
    created_at: now, updated_at: now, start_date: now, department_id: departmentId,
    is_converted_to_task: true, one_h_marker: "QUESTION", one_h_marker_comment: "Note comment", attachments: [] }
  const tasks = owners.map((owner, index) => ({
    id: `${index + 5}${"5".repeat(7)}-5555-4555-8555-555555555555`,
    assigned_to: owner.id, assignees: [owner], created_by: user.id, status: "TODO", priority: "NORMAL",
    [source === "ga-notes" ? "ga_note_origin_id" : "plan_note_origin_id"]: noteId,
    department_id: departmentId, one_h_marker: ["KA", "QUESTION", "GENT"][index],
    one_h_marker_comment: `Comment ${index}`, created_at: now, updated_at: now,
  }))
  const writes: Record<string, unknown>[] = []
  const markerWrites: { taskId: string; body: Record<string, unknown> }[] = []
  await page.addInitScript(user => {
    localStorage.setItem("primex_access_token", "test-only-marker-token")
    localStorage.setItem("primex_user", JSON.stringify(user))
  }, user)
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname
    if (path === "/api/auth/me") return route.fulfill({ json: user })
    if (path === "/api/users") return route.fulfill({ json: owners })
    if (path === "/api/departments") return route.fulfill({ json: [{ id: departmentId, name: "Development", code: "DEV" }] })
    if (path === `/api/${source}`) return route.fulfill({ json: [note] })
    if (path === "/api/tasks/by-ga-notes/summary") return route.fulfill({ json: tasks })
    const markerTask = tasks.find(task => path === `/api/tasks/${task.id}` || path === `/api/tasks/${task.id}/one-h-marker`)
    if (markerTask) {
      if (route.request().method() === "PATCH") {
        const body = route.request().postDataJSON()
        markerWrites.push({ taskId: markerTask.id, body }); Object.assign(markerTask, body)
      }
      return route.fulfill({ json: markerTask })
    }
    if (path === `/api/${source}/${noteId}/task-bundle`) {
      writes.push(route.request().postDataJSON())
      return route.fulfill({ json: { note, active_task_ids: tasks.map(task => task.id), assignee_ids: owners.map(owner => owner.id) } })
    }
    return route.fulfill({ json: path.includes("marker-comments") || path.includes("count") ? { items: [], unread_count: 0, count: 0 } : [] })
  })
  await page.goto("/ga-ka-notes")
  await expect(page.getByText("Symbol (optional)", { exact: true })).toHaveCount(0)
  await page.getByRole("row").filter({ hasText: "Shared work" }).getByRole("cell", { name: "Edit", exact: true }).getByRole("button", { name: "Edit", exact: true }).click()
  const editor = page.getByRole("dialog", { name: "Edit Note", exact: true })
  await expect(editor).toBeVisible()
  await expect(editor.getByText("Note symbol", { exact: true })).toHaveCount(0)
  const symbols = owners.map(owner => editor.getByRole("button", { name: `Symbol for ${owner.full_name}`, exact: true }))
  await expect(symbols[0]).toContainText("KA")
  await expect(symbols[1]).toContainText("?")
  await expect(symbols[2]).toContainText("GENT")
  return { editor, symbols, writes, markerWrites, tasks }
}

test("PX Notes inline symbols edit only the selected assignee without opening Edit Note", async ({ page }) => {
  const { editor, markerWrites, tasks, writes } = await openEditor(page, "ga-notes")
  await page.keyboard.press('Escape')
  await expect(editor).toHaveCount(0)
  const inline = page.locator(`[data-task-marker-id="${tasks[0].id}"]`).first()
  await inline.getByRole('button', { name: 'Task symbols (maximum 2)', exact: true }).click()
  const picker = page.getByRole('dialog', { name: 'Simbolet', exact: true })
  await picker.getByRole('checkbox', { name: 'M3', exact: true }).check()
  await picker.getByRole('button', { name: 'Ruaj', exact: true }).click()
  await page.getByRole('dialog', { name: 'Task comment', exact: true }).getByRole('button', { name: 'Save', exact: true }).click()
  await expect(inline).toContainText('KA + M3')
  expect(markerWrites).toEqual([{ taskId: tasks[0].id, body: { one_h_marker: 'KA,M3', one_h_marker_comment: 'Comment 0' } }])
  expect(writes).toHaveLength(0)
  expect(tasks[1].one_h_marker).toBe('QUESTION')
})

for (const source of ["ga-notes", "plan-notes"] as const) {
  test(`${source}: changing one owner's symbol and comment preserves the other two`, async ({ page }) => {
    const { editor, symbols, writes } = await openEditor(page, source)
    page.once("dialog", dialog => void dialog.accept("Only the second owner"))
    await symbols[1].click()
    const picker = page.getByRole("dialog", { name: "Simbolet", exact: true })
    await picker.getByRole("checkbox", { name: "M3", exact: true }).check()
    await expect(picker.getByRole("checkbox", { name: "KA", exact: true })).toBeDisabled()
    await picker.getByRole("button", { name: "Ruaj", exact: true }).click()
    await expect(symbols[0]).toContainText("KA")
    await expect(symbols[1]).toContainText("? + M3")
    await expect(symbols[2]).toContainText("GENT")
    await editor.getByRole("button", { name: "Save changes", exact: true }).filter({ visible: true }).click()
    await expect(editor).toHaveCount(0)
    expect(writes).toHaveLength(1)
    expect(writes[0].assignee_states).toEqual([expect.objectContaining({
      assignee_id: owners[1].id, one_h_marker: "QUESTION,M3", one_h_marker_comment: "Only the second owner",
    })])
    expect(writes[0]).not.toHaveProperty("one_h_marker")
    expect(writes[0]).not.toHaveProperty("one_h_marker_comment")
  })
}

test("canceling a symbol change leaves each owner's symbol intact; clearing affects only one", async ({ page }) => {
  const { editor, symbols, writes } = await openEditor(page, "ga-notes")
  await symbols[1].click()
  let picker = page.getByRole("dialog", { name: "Simbolet", exact: true })
  await picker.getByRole("checkbox", { name: "M3", exact: true }).check()
  await picker.getByRole("button", { name: "Anulo", exact: true }).click()
  await expect(symbols[1]).toContainText("?")
  await symbols[1].click()
  picker = page.getByRole("dialog", { name: "Simbolet", exact: true })
  await picker.getByRole("button", { name: "Hiqi të gjitha", exact: true }).click()
  await picker.getByRole("button", { name: "Ruaj", exact: true }).click()
  await expect(symbols[0]).toContainText("KA")
  await expect(symbols[2]).toContainText("GENT")
  await editor.getByRole("button", { name: "Save changes", exact: true }).filter({ visible: true }).click()
  await expect(editor).toHaveCount(0)
  expect(writes[0].assignee_states).toEqual([expect.objectContaining({
    assignee_id: owners[1].id, one_h_marker: null, one_h_marker_comment: "Comment 1",
  })])
})

test("report iframe picker caps selection at two, supports replacement and cancellation", async ({ page }) => {
  const source = readFileSync("src/lib/task-markers.ts", "utf8")
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  await page.goto("about:blank")
  await page.evaluate(code => {
    const module = { exports: {} as { openTaskMarkerPicker: (document: Document, value: string) => Promise<string | null> } }
    new Function("module", "exports", code)(module, module.exports)
    const button = document.createElement("button")
    button.textContent = "Edit report symbols"
    button.onclick = async () => {
      const result = await module.exports.openTaskMarkerPicker(document, button.dataset.value || "CLIENT_URGENT")
      if (result !== null) button.dataset.value = result
    }
    document.body.append(button)
  }, code)
  const trigger = page.getByRole("button", { name: "Edit report symbols" })
  await trigger.click()
  let picker = page.getByRole("dialog")
  await picker.getByRole("checkbox", { name: "M3", exact: true }).check()
  await expect(picker.getByRole("checkbox", { name: "KA", exact: true })).toBeDisabled()
  await picker.getByRole("checkbox", { name: "!!!", exact: true }).uncheck()
  await picker.getByRole("checkbox", { name: "KA", exact: true }).check()
  await picker.getByRole("button", { name: "Ruaj", exact: true }).click()
  await expect(trigger).toHaveAttribute("data-value", "M3,KA")
  await trigger.click()
  picker = page.getByRole("dialog")
  await picker.getByRole("checkbox", { name: "KA", exact: true }).uncheck()
  await picker.getByRole("button", { name: "Anulo", exact: true }).click()
  await expect(trigger).toHaveAttribute("data-value", "M3,KA")
})
