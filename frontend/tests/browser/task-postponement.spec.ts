import { test, expect, type Page } from "@playwright/test"

const taskId = "11111111-1111-4111-8111-111111111111"
const owner = "22222222-2222-4222-8222-222222222222"
const department = "33333333-3333-4333-8333-333333333333"
const user = { id: owner, full_name: "Test owner", email: "owner@example.com", role: "STAFF", is_active: true, department_id: department }
const day = (offset = 0) => new Date(Date.now() + offset * 86400000).toISOString().slice(0, 10)
const inputDay = (offset: number) => day(offset).split("-").reverse().join("/")

async function shell(page: Page) {
  let task = { id: taskId, title: "DT: Test postponement", status: "TODO", priority: "NORMAL", created_at: `${day()}T08:00:00Z`,
    start_date: `${day()}T10:00:00Z`, due_date: `${day(14)}T10:00:00Z`, system_template_origin_id: taskId,
    assigned_to: owner, assignees: [user], is_active: true, department_id: department }
  const writes: Record<string, unknown>[] = []
  await page.addInitScript(({ user }) => {
    localStorage.setItem("primex_access_token", "test-only-browser-token")
    localStorage.setItem("primex_user", JSON.stringify(user))
  }, { user })
  await page.route("http://127.0.0.1:8013/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path === "/api/auth/me") return route.fulfill({ json: user })
    if (path === "/api/users" || path === "/api/users/lookup") return route.fulfill({ json: [user] })
    if (path === "/api/departments") return route.fulfill({ json: [{ id: department, name: "Development", code: "DEV" }] })
    if (path === "/api/system-tasks/templates") return route.fulfill({ json: [{ id: taskId, title: task.title, frequency: "DAILY" }] })
    if (path === "/api/tasks") return route.fulfill({ json: [task] })
    if (path === `/api/tasks/${taskId}` && request.method() === "PATCH") {
      const body = request.postDataJSON()
      writes.push(body)
      if (!body.postponement_reason_code || !body.postponement_comment?.trim()) {
        return route.fulfill({ status: 409, json: { detail: { code: "TASK_POSTPONEMENT_EXPLANATION_REQUIRED",
          task_id: taskId, task_title: task.title, changes: ["start_date", "due_date"].flatMap(field =>
            body[field]?.slice(0, 10) > task[field as "due_date"].slice(0, 10)
              ? [{ field, from: task[field as "due_date"].slice(0, 10), to: body[field].slice(0, 10) }] : []) } } })
      }
      task = { ...task, ...body }
      return route.fulfill({ json: task })
    }
    return route.fulfill({ json: path.includes("count") ? { count: 0 } : [] })
  })
  await page.goto("/system-task-instances")
  await page.getByRole("button", { name: "Edit", exact: true }).click()
  await expect(page.getByRole("dialog", { name: "Edit task" })).toBeVisible()
  return { writes }
}

for (const movement of ["start", "due", "both"]) {
  test(`${movement} postponement cannot save until both explanation fields are filled`, async ({ page }) => {
    const { writes } = await shell(page)
    if (movement !== "due") await page.getByLabel("Start date", { exact: true }).fill(inputDay(7))
    if (movement !== "start") await page.getByLabel("Due date", { exact: true }).fill(inputDay(21))
    await page.getByRole("button", { name: "Save changes" }).click()
    const dialog = page.getByRole("dialog", { name: "Arsyeja e shtyrjes" })
    await expect(dialog).toBeVisible()
    const save = dialog.getByRole("button", { name: "Ruaj shtyrjen" })
    await expect(save).toBeDisabled()
    await dialog.getByLabel("Arsyeja *", { exact: true }).selectOption("MISSING_INFORMATION")
    await expect(save).toBeDisabled()
    await dialog.getByLabel("Komenti *", { exact: true }).fill("   ")
    await expect(save).toBeDisabled()
    expect(writes).toHaveLength(1)
    await dialog.getByLabel("Komenti *", { exact: true }).fill("  Presim përgjigjjen e klientit.  ")
    await save.click()
    await expect(dialog).toHaveCount(0)
    await expect(page.getByRole("dialog", { name: "Edit task" })).toHaveCount(0)
    expect(writes).toHaveLength(2)
    expect(writes[1]).toMatchObject({ postponement_reason_code: "MISSING_INFORMATION", postponement_comment: "Presim përgjigjjen e klientit." })
    expect(writes[1].start_date).toBe(writes[0].start_date)
    expect(writes[1].due_date).toBe(writes[0].due_date)
  })
}

test("canceling the explanation keeps the edit form and does not retry the date write", async ({ page }) => {
  const { writes } = await shell(page)
  await page.getByLabel("Due date", { exact: true }).fill(inputDay(21))
  await page.getByRole("button", { name: "Save changes" }).click()
  const dialog = page.getByRole("dialog", { name: "Arsyeja e shtyrjes" })
  await expect(dialog).toBeVisible()
  await dialog.getByRole("button", { name: "Anulo" }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole("dialog", { name: "Edit task" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Save changes" })).toBeEnabled()
  expect(writes).toHaveLength(1)
})

for (const source of ["ga-notes", "plan-notes"]) {
  test(`${source}: editing the task dates from Notes opens the mandatory explanation dialog`, async ({ page }) => {
    const noteId = "44444444-4444-4444-8444-444444444444"
    let note = { id: noteId, content: "EF: Notes postponement test", created_at: `${day()}T08:00:00Z`, updated_at: `${day()}T08:00:00Z`,
      created_by: owner, department_id: department, project_id: null, status: "OPEN", note_type: "GENERAL", priority: "NORMAL",
      is_converted_to_task: true, is_discussed: false, attachments: [], one_h_marker: null }
    let task = { id: taskId, title: note.content, description: "Task description", status: "IN_PROGRESS", priority: "NORMAL", progress_percentage: 50,
      assigned_to: owner, assignees: [user], is_active: true, department_id: department, created_at: note.created_at,
      start_date: `${day()}T10:00:00Z`, due_date: `${day(14)}T10:00:00Z`,
      ga_note_origin_id: source === "ga-notes" ? noteId : null, plan_note_origin_id: source === "plan-notes" ? noteId : null }
    const writes: Record<string, unknown>[] = []
    await page.addInitScript(({ user }) => {
      localStorage.setItem("primex_access_token", "test-only-browser-token")
      localStorage.setItem("primex_user", JSON.stringify(user))
    }, { user })
    await page.route("http://127.0.0.1:8013/api/**", async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      if (path.includes("marker-comments")) return route.fulfill({ json: { items: [], unread_count: 0 } })
      if (path === "/api/auth/me") return route.fulfill({ json: user })
      if (path === "/api/users" || path === "/api/users/lookup") return route.fulfill({ json: [user] })
      if (path === "/api/departments") return route.fulfill({ json: [{ id: department, name: "Development", code: "DEV" }] })
      if (path === "/api/ga-notes" || path === "/api/plan-notes") return route.fulfill({ json: path === `/api/${source}` ? [note] : [] })
      if (path === "/api/tasks/by-ga-notes/summary") {
        const body = request.postDataJSON()
        const ids = source === "ga-notes" ? body.ga_note_origin_ids : body.plan_note_origin_ids
        return route.fulfill({ json: ids?.includes(noteId) ? [task] : [] })
      }
      if (path === `/api/${source}/${noteId}/task-bundle`) {
        const body = request.postDataJSON()
        writes.push(body)
        if (!body.postponement_explanations?.[taskId]?.postponement_comment) return route.fulfill({ status: 409, json: {
          detail: { code: "TASK_POSTPONEMENT_EXPLANATION_REQUIRED", postponements: [{ task_id: taskId, task_title: task.title,
            assignee_name: user.full_name, changes: [{ field: "due_date", from: day(14), to: day(21) }] }] },
        } })
        task = { ...task, ...body.assignee_states[0] }
        note = { ...note, content: body.content }
        return route.fulfill({ json: { note, active_task_ids: [taskId], assignee_ids: [owner] } })
      }
      return route.fulfill({ json: path.includes("count") ? { count: 0 } : [] })
    })
    await page.goto("/ga-ka-notes")
    const row = page.getByRole("row").filter({ hasText: note.content }).last()
    await row.getByRole("cell", { name: "Edit", exact: true }).getByRole("button", { name: "Edit", exact: true }).click()
    const edit = page.getByRole("dialog").filter({ hasText: "Save changes" })
    await expect(edit).toBeVisible()
    const dates = edit.locator('input[placeholder="dd/mm/yyyy"]')
    await dates.nth(1).fill(inputDay(21))
    await edit.getByRole("button", { name: "Save changes", exact: true }).click()
    const dialog = page.getByRole("dialog", { name: "Arsyeja e shtyrjes" })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText(user.full_name, { exact: false })).toBeVisible()
    await expect(dialog.getByRole("button", { name: "Ruaj shtyrjen" })).toBeDisabled()
    await dialog.getByLabel("Arsyeja *", { exact: true }).selectOption("WAITING_CLIENT")
    await dialog.getByLabel("Komenti *", { exact: true }).fill("Presim përgjigjjen nga Notes.")
    await dialog.getByRole("button", { name: "Ruaj shtyrjen" }).click()
    await expect(dialog).toHaveCount(0)
    await expect(edit).toHaveCount(0)
    expect(writes).toHaveLength(2)
    expect(writes[1].postponement_explanations).toEqual({ [taskId]: {
      postponement_reason_code: "WAITING_CLIENT", postponement_comment: "Presim përgjigjjen nga Notes.",
    } })
  })
}
