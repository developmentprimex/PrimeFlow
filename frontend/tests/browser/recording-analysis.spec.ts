import { test, expect, type Page } from "@playwright/test"

const id = "11111111-1111-4111-8111-111111111111"
const owner = "22222222-2222-4222-8222-222222222222"
const department = "33333333-3333-4333-8333-333333333333"
const actionId = "44444444-4444-4444-8444-444444444444"
const taskId = "55555555-5555-4555-8555-555555555555"
const user = { id: owner, full_name: "Test owner", email: "owner@example.com", role: "STAFF", is_active: true, department_id: department }
const action = { id: actionId, segment_index: 0, title: "Dërgo raportin", description: "Përgatit raportin.", evidence: "Do ta dërgoj raportin.", assignee_text: null, deadline_text: null, suggested_assignee_id: null, suggested_due_date: null, created_task_id: null, confirmed_at: null }

async function shell(page: Page, configured = true) {
  let state: Record<string, unknown> = { configured, can_manage: true, analysis: null, actions: [], segments: [] }
  const writes: { url: string; body: Record<string, unknown> }[] = []
  await page.addInitScript(({ user }) => {
    localStorage.setItem("primex_access_token", "test-only-browser-token")
    localStorage.setItem("primex_user", JSON.stringify(user))
  }, { user })
  await page.route("http://127.0.0.1:8012/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    if (path === "/api/auth/me") return route.fulfill({ json: user })
    if (path === "/api/users/lookup") return route.fulfill({ json: [user] })
    if (path === "/api/departments") return route.fulfill({ json: [{ id: department, name: "Ekipi test" }] })
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
  return { writes, ready: () => { state = { ...state, analysis: { status: "READY", language: "sq", total_segments: 1, segments_done: 1, summary: "U diskutua raporti i takimit.", error_message: null, decisions: [] }, actions: [action], segments: [{ index: 0, start_seconds: 0, duration_seconds: 28, text: action.evidence }] } } }
}

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
  await expect(page.getByRole("link", { name: "Hap detyrën e krijuar" })).toHaveCount(0)
  await page.getByText("Transkripti (1 pjesë)").click()
  await expect(page.locator("details").getByText(action.evidence)).toBeVisible()
  await page.getByLabel("Titulli i detyrës").fill("Dërgo raportin e kontrolluar")
  await page.getByLabel("Përgjegjësi", { exact: true }).selectOption(owner)
  await page.getByRole("button", { name: "Konfirmo dhe krijo detyrën" }).click()
  await expect(page.getByRole("link", { name: "Hap detyrën e krijuar" })).toHaveAttribute("href", `/tasks/${taskId}`)
  expect(harness.writes).toHaveLength(2)
  expect(harness.writes[1].body).toMatchObject({ title: "Dërgo raportin e kontrolluar", assigned_to: owner, department_id: department, due_date: null })
  await page.reload()
  await expect(page.getByRole("link", { name: "Hap detyrën e krijuar" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Konfirmo dhe krijo detyrën" })).toHaveCount(0)
})

test("missing provider key is visible and cannot initiate processing", async ({ page }) => {
  const harness = await shell(page, false)
  await expect(page.getByText(/Shërbimi AI nuk është konfiguruar/)).toBeVisible()
  await page.getByRole("checkbox", { name: /Kam autorizimin/ }).check()
  await expect(page.getByRole("button", { name: "Transkripto dhe përmblidh" })).toBeDisabled()
  expect(harness.writes).toHaveLength(0)
})
