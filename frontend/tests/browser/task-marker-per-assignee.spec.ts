import { test, expect, type Page } from "@playwright/test"

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
  const symbols = owners.map(owner => editor.getByRole("combobox", { name: `Symbol for ${owner.full_name}`, exact: true }))
  await expect(symbols[0]).toHaveText("KA")
  await expect(symbols[1]).toHaveText("?")
  await expect(symbols[2]).toHaveText("GENT")
  return { editor, symbols, writes }
}

for (const source of ["ga-notes", "plan-notes"] as const) {
  test(`${source}: changing one owner's symbol and comment preserves the other two`, async ({ page }) => {
    const { editor, symbols, writes } = await openEditor(page, source)
    page.once("dialog", dialog => void dialog.accept("Only the second owner"))
    await symbols[1].click()
    await page.getByRole("option", { name: "M3", exact: true }).click()
    await expect(symbols[0]).toHaveText("KA")
    await expect(symbols[1]).toHaveText("M3")
    await expect(symbols[2]).toHaveText("GENT")
    await editor.getByRole("button", { name: "Save changes", exact: true }).filter({ visible: true }).click()
    await expect(editor).toHaveCount(0)
    expect(writes).toHaveLength(1)
    expect(writes[0].assignee_states).toEqual([expect.objectContaining({
      assignee_id: owners[1].id, one_h_marker: "M3", one_h_marker_comment: "Only the second owner",
    })])
    expect(writes[0]).not.toHaveProperty("one_h_marker")
    expect(writes[0]).not.toHaveProperty("one_h_marker_comment")
  })
}

test("canceling a symbol change leaves each owner's symbol intact; clearing affects only one", async ({ page }) => {
  const { editor, symbols, writes } = await openEditor(page, "ga-notes")
  page.once("dialog", dialog => void dialog.dismiss())
  await symbols[1].click()
  await page.getByRole("option", { name: "M3", exact: true }).click()
  await expect(symbols[1]).toHaveText("?")
  await symbols[1].click()
  await page.getByRole("option", { name: "No symbol", exact: true }).click()
  await expect(symbols[0]).toHaveText("KA")
  await expect(symbols[2]).toHaveText("GENT")
  await editor.getByRole("button", { name: "Save changes", exact: true }).filter({ visible: true }).click()
  await expect(editor).toHaveCount(0)
  expect(writes[0].assignee_states).toEqual([expect.objectContaining({
    assignee_id: owners[1].id, one_h_marker: null, one_h_marker_comment: null,
  })])
})
