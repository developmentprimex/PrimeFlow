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
