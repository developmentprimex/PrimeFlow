import { test, expect, type Page } from "@playwright/test"

const id = "11111111-1111-4111-8111-111111111111"
const owner = "22222222-2222-4222-8222-222222222222"
const department = "33333333-3333-4333-8333-333333333333"
const actionId = "44444444-4444-4444-8444-444444444444"
const taskId = "55555555-5555-4555-8555-555555555555"
const projectId = "66666666-6666-4666-8666-666666666666"
const user = { id: owner, full_name: "Test owner", email: "owner@example.com", role: "STAFF", is_active: true, department_id: department }
const action = { id: actionId, segment_index: 0, title: "Dërgo raportin", description: "Përgatit raportin.", evidence: "Do ta dërgoj raportin.", assignee_text: null, deadline_text: null, suggested_assignee_id: null, suggested_due_date: null, created_task_id: null, confirmed_at: null }

async function shell(page: Page, configured = true) {
  let state: Record<string, unknown> = { configured, can_manage: true, timing_configured: true, timing: null, analysis: null, actions: [], segments: [] }
  let savedTask: Record<string, unknown> = { id: taskId, department_id: department, title: action.title, description: action.description, status: "TODO", priority: "NORMAL", assigned_to: null, assignees: [], created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
  const writes: { url: string; body: Record<string, unknown> }[] = []
  await page.addInitScript(({ user }) => {
    localStorage.setItem("primex_access_token", "test-only-browser-token")
    localStorage.setItem("primex_user", JSON.stringify(user))
  }, { user })
  await page.route("http://127.0.0.1:8012/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    if (path === "/api/auth/me") return route.fulfill({ json: user })
    if (path.endsWith('/citation-times')) {
      writes.push({ url: path, body: {} })
      state = { ...state, timing: { status: 'QUEUED' } }
      return route.fulfill({ status: 202, json: { status: 'QUEUED' } })
    }
    if (path === "/api/users/lookup") return route.fulfill({ json: [user] })
    if (path === "/api/departments") return route.fulfill({ json: [{ id: department, name: "Ekipi test" }] })
    if (path === "/api/projects") return route.fulfill({ json: [{ id: projectId, title: "Projekti test", department_id: department }] })
    if (path === "/api/skills/infer-category") return route.fulfill({ json: { category: "management", reason: "Planifikimi i raportit", confidence: "high" } })
    if (path === `/api/tasks/${taskId}`) {
      if (request.method() === "PATCH") {
        const body = request.postDataJSON()
        writes.push({ url: path, body })
        savedTask = { ...savedTask, ...body }
      }
      return route.fulfill({ json: savedTask })
    }
    if (path.endsWith("/analysis")) {
      if (request.method() === "POST") {
        writes.push({ url: path, body: request.postDataJSON() })
        state = { ...state, analysis: { status: "QUEUED", language: "sq", total_segments: 1, segments_done: 0, summary: null, error_message: null } }
        return route.fulfill({ status: 202, json: { status: "QUEUED" } })
      }
      return route.fulfill({ json: state })
    }
    if (path.endsWith(`/actions/${actionId}/task`)) {
      writes.push({ url: path, body: request.postDataJSON() })
      savedTask = { ...savedTask, ...request.postDataJSON(), assignees: [user], ga_note_origin_id: "77777777-7777-4777-8777-777777777777" }
      state = { ...state, actions: [{ ...action, created_task_id: taskId, confirmed_at: new Date().toISOString() }] }
      return route.fulfill({ json: { task_id: taskId, duplicate: false } })
    }
    if (path === `/api/meeting-recordings/${id}`) return route.fulfill({ json: {
      id, title: "Regjistrim për analizë", created_by: owner, recorded_by_name: user.full_name, status: "READY", mime_type: "video/webm", duration_seconds: 28,
      created_at: new Date().toISOString(), size_bytes: 500000, video_width: 160, video_height: 90,
    } })
    if (path.endsWith("/playback")) return route.fulfill({ json: { token: "test-only-playback", expires_in: 900 } })
    return route.fulfill({ json: path.includes("count") ? { count: 0 } : [] })
  })
  await page.route(`http://127.0.0.1:3101/api/meeting-recordings/${id}/playback`, route => route.fulfill({ json: { ok: true } }))
  await page.route(`http://127.0.0.1:3101/api/meeting-recordings/${id}/stream`, route => route.fulfill({ status: 204 }))
  await page.goto(`/meeting-recordings/${id}`)
  await expect(page.getByText("Transkripti, përmbledhja dhe detyrat", { exact: true })).toBeVisible()
  return { writes, timesReady: () => { state = { ...state, timing: { status: 'READY', results: { [actionId]: { start: 7.83, end: 11.65, approximate: true } } } } }, ready: () => { state = { ...state, analysis: { status: "READY", language: "sq", total_segments: 1, segments_done: 1, summary: "U diskutua raporti i takimit.", error_message: null, decisions: [] }, actions: [action], segments: [{ index: 0, start_seconds: 0, duration_seconds: 28, text: `Hapja e takimit. ${action.evidence}` }] } } }
}

test('citation timing requires a click and survives reload without reprocessing', async ({ page }) => {
  const harness = await shell(page)
  harness.ready()
  await page.reload()
  const button = page.getByRole('button', { name: 'Gjej kohët e citimeve', exact: true })
  await expect(button).toBeEnabled()
  expect(harness.writes).toHaveLength(0)
  await button.click()
  await expect(page.getByText(/Në radhë për gjetjen/)).toBeVisible()
  await expect(button).toHaveCount(0)
  expect(harness.writes).toHaveLength(1)
  harness.timesReady()
  await page.reload()
  const jump = page.getByRole('button', { name: /Rreth 00:00:07/ })
  await expect(jump).toBeVisible()
  await page.locator('video').evaluate((video: HTMLVideoElement) => {
    Object.defineProperty(video, 'currentTime', { writable: true, value: 0 })
    video.play = () => Promise.resolve()
  })
  await jump.click()
  expect(await page.locator('video').evaluate((video: HTMLVideoElement) => video.currentTime)).toBeCloseTo(7.58)
  expect(harness.writes).toHaveLength(1)
})

test("configuration and consent guard processing; proposals require review and persist after reload", async ({ page }) => {
  const harness = await shell(page)
  const start = page.getByRole("button", { name: "Transkripto dhe përmblidh" })
  await expect(start).toBeDisabled()
  await page.getByRole("checkbox", { name: /Kam autorizimin/ }).check()
  await start.click()
  await expect(page.getByText(/Në pritje të përpunimit/)).toBeVisible()
  expect(harness.writes).toHaveLength(1)
  expect(harness.writes[0].body).toEqual({ language: "sq", consent_acknowledged: true })
  harness.ready()
  await page.reload()
  await expect(page.getByText("U diskutua raporti i takimit.")).toBeVisible()
  await expect(page.getByRole("button", { name: "Edito detyrë", exact: true })).toHaveCount(0)
  const transcript = page.getByRole("region", { name: "Transkripti", exact: true })
  await expect(transcript.getByText(action.evidence, { exact: true })).toBeVisible()
  await expect(transcript.getByText("Hapja e takimit.", { exact: true })).toBeVisible()
  expect(await transcript.evaluate(element => Boolean(element.compareDocumentPosition(document.querySelector("video")!) & Node.DOCUMENT_POSITION_PRECEDING))).toBe(true)
  await expect(page.getByRole("heading", { name: "DËRGO RAPORTIN", exact: true })).toBeVisible()
  const actionsTable = page.getByRole("table", { name: "Detyrat e regjistrimit" })
  await expect(actionsTable.getByRole("columnheader")).toHaveText(["NR", "Detyra", "Përgjegjësi", "Afati", "Statusi", "Veprime"])
  await expect(actionsTable.getByRole("textbox")).toHaveCount(0)
  await actionsTable.scrollIntoViewIfNeeded()
  await page.screenshot({ path: test.info().outputPath("recording-tasks-table.png"), animations: "disabled" })
  await page.getByRole("button", { name: "Krijo detyrë", exact: true }).click()
  await expect(page.getByRole("dialog")).toBeVisible()
  await expect(page.getByLabel("Titulli i detyrës")).toHaveValue("DËRGO RAPORTIN\nPërgatit raportin.")
  await expect(page.getByRole("dialog").getByText("Përshkrimi", { exact: true })).toHaveCount(0)
  await page.screenshot({ path: test.info().outputPath("recording-task-dialog.png"), animations: "disabled" })
  await page.getByLabel("Titulli i detyrës").fill("Dërgo raportin e kontrolluar\nPërgatit raportin.")
  await expect(page.getByLabel("Titulli i detyrës")).toHaveValue("DËRGO RAPORTIN E KONTROLLUAR\nPërgatit raportin.")
  await page.getByLabel("Assign to", { exact: true }).selectOption(owner)
  await page.getByLabel("Project (optional)", { exact: true }).selectOption(projectId)
  await page.getByLabel("Priority", { exact: true }).selectOption("1H")
  await page.getByLabel("1H slot (optional)", { exact: true }).selectOption("11:50")
  await page.getByLabel("Symbol (optional)", { exact: true }).selectOption("QUESTION")
  await page.getByLabel("Symbol comment (optional)", { exact: true }).fill("Kontrollo raportin")
  await page.getByLabel("Start date (optional)", { exact: true }).fill("01/11/2026")
  await page.getByLabel("Due date (optional)", { exact: true }).fill("03/11/2026")
  await page.getByLabel("Deadline important", { exact: true }).check()
  await page.getByRole("button", { name: "Analizo me AI përsëri" }).click()
  await expect(page.getByText("Planifikimi i raportit", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "Konfirmo dhe krijo detyrën" }).click()
  await expect(page.getByRole("button", { name: "Edito detyrë", exact: true })).toBeVisible()
  expect(harness.writes).toHaveLength(2)
  expect(harness.writes[1].body).toMatchObject({ title: "DËRGO RAPORTIN E KONTROLLUAR\nPërgatit raportin.", description: '', assigned_to: owner, assignees: [owner], department_id: department, project_id: projectId, is_1h_report: true, one_h_report_slot: "11:50", finish_period: "AM", one_h_marker: "QUESTION", one_h_marker_comment: "Kontrollo raportin", is_deadline_important: true, skill_category: "management" })
  expect(harness.writes[1].body.start_date).toBeTruthy()
  expect(harness.writes[1].body.due_date).toBeTruthy()
  await page.getByRole("button", { name: "Edito detyrë", exact: true }).click()
  await expect(page.getByRole("dialog", { name: "Edit task" })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`/meeting-recordings/${id}$`))
  await expect(page.getByLabel("Titulli i detyrës")).toHaveValue("DËRGO RAPORTIN E KONTROLLUAR\nPërgatit raportin.")
  await expect(page.getByLabel("Project (optional)", { exact: true })).toHaveValue(projectId)
  await expect(page.getByLabel("1H slot (optional)", { exact: true })).toHaveValue("11:50")
  await page.getByLabel("Titulli i detyrës").fill("raporti i përditësuar")
  await page.getByLabel("Status", { exact: true }).selectOption("IN_PROGRESS")
  await page.getByLabel("Due date (optional)", { exact: true }).fill("05/11/2026")
  await page.getByRole("button", { name: "Save changes", exact: true }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  expect(harness.writes).toHaveLength(3)
  expect(harness.writes[2].body).toMatchObject({ title: "RAPORTI I PËRDITËSUAR", status: "IN_PROGRESS" })
  expect(harness.writes[2].body.start_date).toBeUndefined()
  expect(harness.writes[2].body.assignees).toBeUndefined()
  await expect(page.getByRole("table", { name: "Detyrat e regjistrimit" }).getByRole("heading", { name: "RAPORTI I PËRDITËSUAR", exact: true })).toBeVisible()
  await page.getByRole("button", { name: "Edito detyrë", exact: true }).click()
  await expect(page.getByLabel("Titulli i detyrës")).toHaveValue("RAPORTI I PËRDITËSUAR")
  await page.screenshot({ path: test.info().outputPath("recording-task-edit.png"), animations: "disabled" })
  await page.getByRole("button", { name: "Cancel", exact: true }).click()
  await page.reload()
  await expect(page.getByRole("button", { name: "Edito detyrë", exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "Krijo detyrë", exact: true })).toHaveCount(0)
})

test("missing provider key is visible and cannot initiate processing", async ({ page }) => {
  const harness = await shell(page, false)
  await expect(page.getByText(/Shërbimi AI nuk është konfiguruar/)).toBeVisible()
  await page.getByRole("checkbox", { name: /Kam autorizimin/ }).check()
  await expect(page.getByRole("button", { name: "Transkripto dhe përmblidh" })).toBeDisabled()
  expect(harness.writes).toHaveLength(0)
})

test("task dialog scrolls on a small screen and keeps confirmation visible", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const harness = await shell(page)
  harness.ready()
  await page.reload()
  await page.getByRole("button", { name: "Close sidebar", exact: true }).click()
  await page.getByRole("button", { name: "Krijo detyrë", exact: true }).click()
  const dialog = page.getByRole("dialog")
  await dialog.getByRole("button", { name: "Analizo me AI përsëri" }).scrollIntoViewIfNeeded()
  const confirm = dialog.getByRole("button", { name: "Konfirmo dhe krijo detyrën" })
  await expect(confirm).toBeVisible()
  await expect(confirm).toBeDisabled()
  const bounds = await dialog.boundingBox()
  expect(bounds!.x).toBeGreaterThanOrEqual(0)
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(391)
  await page.screenshot({ path: test.info().outputPath("recording-task-mobile.png"), animations: "disabled" })
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(harness.writes).toHaveLength(0)
})


test("created recording task links PX Notes and renders completed points with strike", async ({ page }) => {
  const harness = await shell(page)
  harness.ready()
  await page.reload()
  await page.getByRole("button", { name: "Krijo detyr\u00eb", exact: true }).click()
  await page.getByLabel("Titulli i detyr\u00ebs").fill("TASK TITLE\n[[done]]Completed point[[/done]]\nOpen point")
  await page.getByLabel("Assign to", { exact: true }).selectOption(owner)
  await page.getByRole("button", { name: "Konfirmo dhe krijo detyr\u00ebn" }).click()
  const table = page.getByRole("table", { name: "Detyrat e regjistrimit" })
  await expect(table.getByRole("link", { name: "Hap n\u00eb PX Notes" })).toHaveAttribute("href", "/ga-ka-notes")
  await expect(table.locator("span.line-through", { hasText: "Completed point" })).toBeVisible()
  await expect(table.getByText("Open point", { exact: true })).toBeVisible()
  await expect(table.getByRole("heading", { name: "TASK TITLE", exact: true })).toBeVisible()
})
