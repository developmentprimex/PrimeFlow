import { test, expect, Page } from "@playwright/test"
import { emptyDefinition, localToday } from "../../src/lib/ga-personal"

const user = { id: "22222222-2222-4222-8222-222222222222", full_name: "Test Adult", email: "test@example.com", role: "STAFF", is_active: true, department_id: null }
const firstId = "11111111-1111-4111-8111-111111111111"
const secondId = "33333333-3333-4333-8333-333333333333"

async function shell(page: Page, options: { available?: boolean; initiallyUnlocked?: boolean; initiallyConfigured?: boolean; automatic?: boolean; workspaceDelay?: number; expiresInMs?: number } = {}) {
  let unlocked = options.initiallyUnlocked ?? false
  let configured = options.initiallyConfigured ?? true
  let automatic = options.automatic ?? false
  let workspaceReads = 0
  let accessReads = 0
  let accessFailure = false
  let forbiddenAction = false
  const expiresAt = options.expiresInMs ? new Date(Date.now() + options.expiresInMs).toISOString() : undefined
  const writes: { path: string; body: Record<string, unknown> }[] = []
  const rows = [
    { id: firstId, template_id: firstId, local_date: localToday(), period_key: localToday(), due_at: null as string | null, snapshot: { ...emptyDefinition("mrika"), frequency: "daily" as const, enabled: true, title: "Detyra e personit të parë" }, status: "pending", version: 1, can_edit: true },
    { id: secondId, template_id: secondId, local_date: localToday(), period_key: localToday(), due_at: null as string | null, snapshot: { ...emptyDefinition("rrita"), frequency: "daily" as const, enabled: true, title: "Detyra e personit të dytë" }, status: "pending", version: 1, can_edit: true },
  ]
  const templates = rows.map((r) => ({ id: r.template_id, definition: { ...r.snapshot }, version: 1, archived: false, source_id: null, can_manage: true }))
  await page.addInitScript(({ user }) => {
    localStorage.setItem("primex_access_token", "browser-test-only")
    localStorage.setItem("primex_user", JSON.stringify(user))
  }, { user })
  await page.route("http://127.0.0.1:8015/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path === "/api/auth/me") return route.fulfill({ json: user })
    if (!path.startsWith("/api/ga-personal")) return route.fulfill({ json: path.includes("count") ? { count: 0 } : [] })
    const relative = path.replace("/api/ga-personal", "")
    if (relative === "/access") {
      accessReads++
      if (accessFailure) { accessFailure = false; return route.fulfill({ status: 503, json: { detail: "Lidhje e përkohshme e ndërprerë." } }) }
      return route.fulfill({ json: { available: options.available ?? true, unlocked, configured, setup_allowed: !configured, requires_login: false, expires_at: expiresAt } })
    }
    if (relative === "/password/setup") {
      configured = true
      writes.push({ path: relative, body: request.postDataJSON() })
      return route.fulfill({ json: { configured: true, unlocked: false } })
    }
    if (relative === "/unlock") {
      if (request.postDataJSON().password !== "test-only-password") return route.fulfill({ status: 403, json: { detail: "Fjalëkalimi nuk është i saktë." } })
      unlocked = true
      return route.fulfill({ json: { unlocked: true } })
    }
    if (relative === "/lock") { unlocked = false; return route.fulfill({ json: { unlocked: false } }) }
    if (!unlocked) return route.fulfill({ status: 423, json: { detail: "Hape modulin." } })
    if (relative === "/automation") {
      if (forbiddenAction) return route.fulfill({ status: 403, json: { detail: "Nuk ke leje për këtë veprim." } })
      automatic = request.postDataJSON().enabled
      writes.push({ path: relative, body: request.postDataJSON() })
      return route.fulfill({ json: { enabled: automatic } })
    }
    if (relative === "/workspace") {
      workspaceReads++
      if (options.workspaceDelay) await new Promise((resolve) => setTimeout(resolve, options.workspaceDelay))
      return route.fulfill({ json: { person_key: "gane", is_admin: true, timezone: "Europe/Belgrade",
        members: [{ person_key: "gane", name: "Test Adult" }, { person_key: "mrika", name: "Person 1" }, { person_key: "rrita", name: "Person 2" }, { person_key: "lirza", name: "Person 3" }],
        config: { automatic_generation: { enabled: automatic, starts_on: localToday() } }, discord: { connected: false, messages_enabled: false } } })
    }
    if (relative === "/templates") {
      if (request.method() === "POST") {
        writes.push({ path: relative, body: request.postDataJSON() })
        return route.fulfill({ json: { id: firstId, ...request.postDataJSON(), can_manage: true, version: 1, archived: false } })
      }
      return route.fulfill({ json: templates })
    }
    if (relative === "/occurrences") return route.fulfill({ json: rows })
    if (relative.startsWith("/occurrences/") && request.method() === "PATCH") {
      const data = request.postDataJSON(), row = rows.find(r => relative.endsWith(r.id))!
      writes.push({ path: relative, body: data })
      row.local_date = data.local_date
      row.due_at = data.due_time ? `${data.local_date}T${data.due_time}:00+01:00` : null
      row.snapshot = { ...row.snapshot, assignees: data.assignees, due_time: data.due_time }
      row.version++
      if (data.apply_to_future) {
        const template = templates.find(t => t.id === row.template_id)!
        template.definition = { ...template.definition, assignees: data.assignees, due_time: data.due_time }
        template.version++
      }
      return route.fulfill({ json: row })
    }
    if (relative.endsWith("/actions")) {
      const data = request.postDataJSON(), row = rows.find(r => relative.includes(r.id))!
      writes.push({ path: relative, body: data }); row.status = data.status; row.version++
      return route.fulfill({ json: row })
    }
    return route.fulfill({ json: [] })
  })
  await page.goto("/ga-personal")
  return { writes, workspaceReads: () => workspaceReads, accessReads: () => accessReads,
    failAccess: () => { accessFailure = true }, forbidAction: () => { forbiddenAction = true }, expire: () => { unlocked = false } }
}

test("the sidebar and module reject a nonmember", async ({ page }) => {
  const state = await shell(page, { available: false })
  await expect(page.getByText("Ky modul ende nuk është aktivizuar për llogarinë tënde.")).toBeVisible()
  await expect(page.getByRole("link", { name: "GA PERSONAL", exact: true })).toHaveCount(0)
  expect(state.workspaceReads()).toBe(0)
})

test("household data loads only after the extra password and disappears on lock", async ({ page }) => {
  const state = await shell(page)
  await expect(page.getByRole("heading", { name: "Hape hapësirën private" })).toBeVisible()
  expect(state.workspaceReads()).toBe(0)
  await page.getByLabel("Fjalëkalimi shtesë").fill("wrong")
  await page.getByRole("button", { name: "Hape modulin", exact: true }).click()
  await expect(page.getByText("Fjalëkalimi nuk është i saktë.", { exact: true })).toBeVisible()
  expect(state.workspaceReads()).toBe(0)
  await page.getByLabel("Fjalëkalimi shtesë").fill("test-only-password")
  await page.getByRole("button", { name: "Hape modulin", exact: true }).click()
  await expect(page.getByText("Detyra e personit të parë")).toBeVisible()
  await page.screenshot({ path: "test-results/ga-personal-desktop.png", fullPage: true })
  await page.getByRole("button", { name: "Kyçe", exact: true }).click()
  await expect(page.getByText("Detyra e personit të parë")).toHaveCount(0)
  await expect(page.getByRole("heading", { name: "Hape hapësirën private" })).toBeVisible()
})

test("the module administrator chooses the first extra password in the page", async ({ page }) => {
  const state = await shell(page, { initiallyConfigured: false })
  await expect(page.getByRole("heading", { name: "Vendos fjalëkalimin shtesë" })).toBeVisible()
  expect(state.workspaceReads()).toBe(0)
  await page.getByLabel("Fjalëkalimi i ri", { exact: true }).fill("test-only-password")
  await page.getByLabel("Përsërite fjalëkalimin", { exact: true }).fill("test-only-password")
  await page.getByRole("button", { name: "Ruaje dhe hape modulin", exact: true }).click()
  await expect(page.getByText("Detyra e personit të parë", { exact: true })).toBeVisible()
  expect(state.writes.filter((w) => w.path === "/password/setup")).toHaveLength(1)
})

test("the module administrator can pause automatic task creation", async ({ page }) => {
  const state = await shell(page, { initiallyUnlocked: true, automatic: true })
  await page.getByRole("button", { name: "Cilësimet", exact: true }).click()
  await page.getByRole("button", { name: "Ndalo krijimin automatik", exact: true }).click()
  await expect(page.getByRole("button", { name: "Aktivizo krijimin automatik", exact: true })).toBeVisible()
  expect(state.writes).toEqual([{ path: "/automation", body: { enabled: false } }])
})

test("focus, returning to the tab and polling keep the editor and unlocked page stable", async ({ page }) => {
  await page.clock.install()
  const state = await shell(page, { initiallyUnlocked: true })
  await page.getByRole("button", { name: "Detyrë e re", exact: true }).click()
  await page.getByLabel("Titulli", { exact: true }).fill("Drafti ruhet gjatë punës")
  const before = state.accessReads()
  await page.evaluate(() => window.dispatchEvent(new Event("focus")))
  await expect.poll(state.accessReads).toBeGreaterThan(before)
  await expect(page.getByLabel("Titulli", { exact: true })).toHaveValue("Drafti ruhet gjatë punës")
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" })
    document.dispatchEvent(new Event("visibilitychange"))
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" })
    document.dispatchEvent(new Event("visibilitychange"))
  })
  await expect(page.getByText("Po verifikohet sesioni…", { exact: true })).toBeHidden()
  await page.clock.fastForward(21000)
  await expect(page.getByLabel("Titulli", { exact: true })).toHaveValue("Drafti ruhet gjatë punës")
  await expect(page.getByRole("heading", { name: "Hape hapësirën private" })).toHaveCount(0)
})

test("a temporary connection error or forbidden action does not ask for the password", async ({ page }) => {
  const state = await shell(page, { initiallyUnlocked: true, automatic: true })
  await expect(page.getByText("Detyra e personit të parë", { exact: true })).toBeVisible()
  state.failAccess()
  await page.evaluate(() => window.dispatchEvent(new Event("focus")))
  await expect(page.getByText("Lidhje e përkohshme e ndërprerë.", { exact: true })).toBeVisible()
  await expect(page.getByText("Detyra e personit të parë", { exact: true })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Hape hapësirën private" })).toHaveCount(0)
  await page.getByRole("button", { name: "Provo përsëri", exact: true }).click()
  await expect(page.getByText("Lidhje e përkohshme e ndërprerë.", { exact: true })).toHaveCount(0)
  state.forbidAction()
  await page.getByRole("button", { name: "Cilësimet", exact: true }).click()
  await page.getByRole("button", { name: "Ndalo krijimin automatik", exact: true }).click()
  await expect(page.getByText("Nuk ke leje për këtë veprim.", { exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "Detyrë e re", exact: true })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Hape hapësirën private" })).toHaveCount(0)
})

test("an already unlocked session loads slowly without flashing a password form", async ({ page }) => {
  await shell(page, { initiallyUnlocked: true, workspaceDelay: 1000 })
  await expect(page.getByText("Duke hapur hapësirën…", { exact: true })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Hape hapësirën private" })).toHaveCount(0)
  await expect(page.getByText("Detyra e personit të parë", { exact: true })).toBeVisible()
})

test("real module expiry removes private data and asks for the extra password", async ({ page }) => {
  await page.clock.install()
  const state = await shell(page, { initiallyUnlocked: true, expiresInMs: 10000 })
  await expect(page.getByText("Detyra e personit të parë", { exact: true })).toBeVisible()
  state.expire()
  await page.clock.fastForward(11000)
  await expect(page.getByRole("heading", { name: "Hape hapësirën private" })).toBeVisible()
  await expect(page.getByText("Detyra e personit të parë", { exact: true })).toHaveCount(0)
})

test("the task card edits time and assignee for only this occurrence", async ({ page }) => {
  const state = await shell(page, { initiallyUnlocked: true })
  const card = page.locator("article").filter({ has: page.getByText("Detyra e personit të parë", { exact: true }) })
  await card.getByRole("button", { name: "Ndrysho", exact: true }).click()
  await page.getByLabel("Ora e detyrës", { exact: true }).fill("18:30")
  await page.getByLabel("Përgjegjësi i detyrës", { exact: true }).selectOption("rrita")
  await page.getByRole("button", { name: "Ruaj ndryshimet", exact: true }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  await expect(card.getByText("18:30", { exact: true })).toBeVisible()
  await expect(card.getByText("Person 2", { exact: true })).toBeVisible()
  expect(state.writes[0].body).toMatchObject({ due_time: "18:30", assignees: ["rrita"], expected_version: 1, apply_to_future: false })
})

test("the task card can explicitly apply a schedule change to future recurrences", async ({ page }) => {
  const state = await shell(page, { initiallyUnlocked: true })
  const card = page.locator("article").filter({ has: page.getByText("Detyra e personit të parë", { exact: true }) })
  await card.getByRole("button", { name: "Ndrysho", exact: true }).click()
  await page.getByLabel("Ora e detyrës", { exact: true }).fill("19:15")
  await page.getByLabel("Këtë dhe përsëritjet e ardhshme", { exact: true }).check()
  await page.getByRole("button", { name: "Ruaj ndryshimet", exact: true }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  expect(state.writes[0].body).toMatchObject({ due_time: "19:15", apply_to_future: true, expected_template_version: 1 })
})

test("creating a task supports several people and individual completion", async ({ page }) => {
  const state = await shell(page, { initiallyUnlocked: true })
  await page.getByRole("button", { name: "Detyrë e re", exact: true }).click()
  await page.getByLabel("Titulli", { exact: true }).fill("Puna e përbashkët e rutinës")
  await page.getByLabel("Person 1", { exact: true }).check()
  await page.getByLabel("Person 2", { exact: true }).check()
  await expect(page.getByRole("combobox", { name: "Kryerja", exact: true })).toHaveValue("individual")
  await page.getByRole("button", { name: "Ruaje detyrën", exact: true }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  expect((state.writes[0].body.definition as { assignees: string[] }).assignees).toEqual(["gane", "mrika", "rrita"])
})

test("completing one person's occurrence preserves the other and the mobile layout fits", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await shell(page, { initiallyUnlocked: true })
  await page.getByRole("button", { name: "Close sidebar" }).click()
  const first = page.locator("article").filter({ has: page.getByText("Detyra e personit të parë", { exact: true }) })
  await first.getByRole("button", { name: "U kry", exact: true }).click()
  await expect(first.getByRole("button", { name: "U kry", exact: true })).toHaveCount(0)
  const second = page.locator("article").filter({ has: page.getByText("Detyra e personit të dytë", { exact: true }) })
  await expect(second.getByRole("button", { name: "U kry", exact: true })).toBeVisible()
  expect(state.writes).toHaveLength(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: "test-results/ga-personal-mobile.png", fullPage: true })
})
