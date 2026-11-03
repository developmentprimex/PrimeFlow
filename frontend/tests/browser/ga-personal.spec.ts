import { test, expect, Page } from "@playwright/test"
import { emptyDefinition, localToday, moveDay, type GaOccurrence, type GaTemplate } from "../../src/lib/ga-personal"

const user = { id: "22222222-2222-4222-8222-222222222222", full_name: "Test Adult", email: "test@example.com", role: "STAFF", is_active: true, department_id: null }
const firstId = "11111111-1111-4111-8111-111111111111"
const secondId = "33333333-3333-4333-8333-333333333333"

async function shell(page: Page, options: { available?: boolean; automatic?: boolean; workspaceDelay?: number; view?: "today" | "week" } = {}) {
  let available = options.available ?? true
  let automatic = options.automatic ?? false
  let workspaceReads = 0
  let accessReads = 0
  let accessFailure = false
  let forbiddenAction = false
  let devices: { id: string; name: string; device_id: string | null; created_at: string; last_seen_at: string | null; revoked_at: string | null }[] = []
  let discordSettings = { enabled: false, configured: true, connected: false, version: 0, guild_id: "", channel_id: "", user_ids: {} as Record<string, string>, delivery_counts: {} }
  const writes: { path: string; body: Record<string, unknown> }[] = []
  const rows: GaOccurrence[] = [
    { id: firstId, template_id: firstId, local_date: localToday(), period_key: localToday(), due_at: null, snapshot: { ...emptyDefinition("mrika"), frequency: "daily", enabled: true, title: "Detyra e personit të parë" }, status: "pending", version: 1, completed_at: null, can_edit: true },
    { id: secondId, template_id: secondId, local_date: localToday(), period_key: localToday(), due_at: null, snapshot: { ...emptyDefinition("rrita"), frequency: "daily", enabled: true, title: "Detyra e personit të dytë" }, status: "pending", version: 1, completed_at: null, can_edit: true },
  ]
  const templates: GaTemplate[] = rows.map((r) => ({ id: r.template_id, definition: { ...r.snapshot }, version: 1, archived: false, source_id: null, can_manage: true }))
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
      return route.fulfill({ json: { available, unlocked: available } })
    }
    if (!available) return route.fulfill({ status: 403, json: { detail: "Nuk ke qasje në këtë modul." } })
    if (relative === "/devices") {
      if (request.method() === "POST") {
        const device = { id: "44444444-4444-4444-8444-444444444444", name: request.postDataJSON().name,
          device_id: null, created_at: new Date().toISOString(), last_seen_at: null, revoked_at: null }
        devices = [device, ...devices]
        writes.push({ path: relative, body: request.postDataJSON() })
        return route.fulfill({ status: 201, json: { ...device, code: "pfgap_device_browser_test_only" } })
      }
      return route.fulfill({ json: devices })
    }
    if (relative.startsWith("/devices/") && relative.endsWith("/revoke")) {
      const device = devices.find((device) => relative.includes(device.id))!
      device.revoked_at = new Date().toISOString()
      writes.push({ path: relative, body: {} })
      return route.fulfill({ json: device })
    }
    if (relative === "/discord/settings") {
      if (request.method() === "PUT") {
        const body = request.postDataJSON()
        writes.push({ path: relative, body })
        discordSettings = { ...discordSettings, ...body, version: discordSettings.version + 1 }
      }
      return route.fulfill({ json: discordSettings })
    }
    if (relative === "/automation") {
      if (forbiddenAction) return route.fulfill({ status: 403, json: { detail: "Nuk ke leje për këtë veprim." } })
      automatic = request.postDataJSON().enabled
      writes.push({ path: relative, body: request.postDataJSON() })
      return route.fulfill({ json: { enabled: automatic } })
    }
    if (relative === "/arrival") {
      writes.push({ path: relative, body: request.postDataJSON() })
      return route.fulfill({ json: { day: localToday(), first_home: "mrika", created: 0 } })
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
        const template: GaTemplate = { id: "55555555-5555-4555-8555-555555555555", ...request.postDataJSON(), can_manage: true, version: 1, archived: false, source_id: null }
        templates.push(template)
        if (template.definition.enabled && template.definition.frequency === "once") {
          const d = template.definition
          const assignments = d.completion_mode === "shared" ? [d.assignees] : d.assignees.map(person => [person])
          for (const assignees of assignments) rows.push({ id: `${template.id}-${assignees[0]}`, template_id: template.id,
            local_date: d.on_date!, period_key: d.on_date!, due_at: null, snapshot: { ...d, assignees },
            status: "pending", version: 1, completed_at: null, can_edit: true })
        }
        return route.fulfill({ json: template })
      }
      return route.fulfill({ json: templates })
    }
    if (relative === "/occurrences") return route.fulfill({ json: rows })
    if (relative.startsWith("/occurrences/") && request.method() === "PATCH") {
      const data = request.postDataJSON(), row = rows.find(r => relative.endsWith(r.id))!
      writes.push({ path: relative, body: data })
      row.local_date = data.local_date
      row.due_at = data.due_time ? `${data.local_date}T${data.due_time}:00+01:00` : null
      row.snapshot = { ...row.snapshot, assignees: data.assignees, due_time: data.due_time, discord_destination: data.discord_destination }
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
  if (available && options.view !== "week") {
    await expect(page.getByRole("navigation", { name: "Pamjet e GA PERSONAL" })).toBeVisible()
    if (page.viewportSize()!.width < 768) await page.getByRole("button", { name: "Close sidebar", exact: true }).click()
    await page.getByRole("button", { name: "Detyrat e ditës", exact: true }).click()
  }
  return { writes, workspaceReads: () => workspaceReads, accessReads: () => accessReads,
    rows, templates,
    failAccess: () => { accessFailure = true }, forbidAction: () => { forbiddenAction = true }, revoke: () => { available = false } }
}

test("weekly status controls and legend survive an empty filter and recover the table", async ({ page }) => {
  await shell(page, { view: "week" })
  await expect(page.getByRole("table")).toBeVisible()
  const filters = page.getByRole("group", { name: "Filtro sipas gjendjes" })
  await filters.getByRole("button", { name: "Po e bëj", exact: true }).click()
  await expect(page.getByText("Nuk ka detyra në këtë pamje", { exact: true })).toBeVisible()
  await expect(filters).toBeVisible()
  await expect(page.getByText("Legjenda", { exact: true })).toBeVisible()
  await filters.getByRole("button", { name: "U kry", exact: true }).click()
  await expect(filters.getByRole("button", { name: "U kry", exact: true })).toHaveAttribute("aria-pressed", "true")
  await filters.getByRole("button", { name: "Pastro filtrin", exact: true }).click()
  await expect(page.getByRole("table")).toBeVisible()
})

test("navigating to a distant week loads that week's occurrences", async ({ page }) => {
  const state = await shell(page, { view: "week" })
  await page.route("**/ga-personal/occurrences?**", async route => {
    const url = new URL(route.request().url())
    const start = url.searchParams.get("start")!
    return route.fulfill({ json: [{ ...state.rows[0], local_date: start, period_key: start,
      snapshot: { ...state.rows[0].snapshot, title: "Detyra e javës së zgjedhur" } }] })
  })
  await page.getByLabel("Data", { exact: true }).fill("01/02/2027")
  await expect(page.getByRole("table").getByText("Detyra e javës së zgjedhur", { exact: true })).toBeVisible()
  await expect(page.getByRole("columnheader", { name: /1 shkurt/ })).toBeVisible()
})

test("a late response from the previous week cannot replace the selected week", async ({ page }) => {
  const state = await shell(page, { view: "week" })
  await expect(page.getByRole("table")).toBeVisible()
  let releaseOld!: () => void
  let markOldStarted!: () => void
  const oldStarted = new Promise<void>(resolve => { markOldStarted = resolve })
  const oldGate = new Promise<void>(resolve => { releaseOld = resolve })
  await page.route("**/ga-personal/occurrences?**", async route => {
    const start = new URL(route.request().url()).searchParams.get("start")!
    if (start === "2027-02-01") { markOldStarted(); await oldGate }
    await route.fulfill({ json: [{ ...state.rows[0], local_date: start, period_key: start,
      snapshot: { ...state.rows[0].snapshot, title: `Java ${start}` } }] }).catch(() => {})
  })
  await page.getByLabel("Data", { exact: true }).fill("01/02/2027")
  await oldStarted
  await page.getByLabel("Data", { exact: true }).fill("08/02/2027")
  await expect(page.getByRole("table").getByText("Java 2027-02-08", { exact: true })).toBeVisible()
  releaseOld()
  await page.getByRole("button", { name: "Këtë javë", exact: true }).click()
  await expect(page.getByRole("table").getByText("Java 2027-02-08", { exact: true })).toBeVisible()
})

test("background access checks keep the weekly table mounted", async ({ page }) => {
  await shell(page, { view: "week" })
  const region = page.getByRole("region", { name: "Tabela e planit javor" })
  await expect(region).toBeVisible()
  await region.evaluate(element => element.setAttribute("data-poll-check", "kept"))
  const refreshed = page.waitForResponse(response => response.url().includes("/ga-personal/occurrences?") && response.status() === 200)
  await page.evaluate(() => window.dispatchEvent(new Event("focus")))
  await refreshed
  await expect(region).toHaveAttribute("data-poll-check", "kept")
})

test("arrival records the signed-in person and shows the first person for the day", async ({ page }) => {
  const state = await shell(page)
  await page.getByRole("button", { name: "Erdha në shpi", exact: true }).click()
  await expect(page.getByText("Ardhja u regjistrua. Personi i parë: Person 1.")).toBeVisible()
  expect(state.writes[0].path).toBe("/arrival")
  expect(state.writes[0].body.request_id).toEqual(expect.any(String))
  expect(Object.keys(state.writes[0].body)).toEqual(["request_id"])
})

test("the sidebar and module reject a nonmember", async ({ page }) => {
  const state = await shell(page, { available: false })
  await expect(page.getByText("Ky modul ende nuk është aktivizuar për llogarinë tënde.")).toBeVisible()
  await expect(page.getByRole("link", { name: "GA PERSONAL", exact: true })).toHaveCount(0)
  expect(state.workspaceReads()).toBe(0)
})

test("members open household tasks directly with their existing PrimeFlow login", async ({ page }) => {
  const state = await shell(page)
  await expect(page.getByText("Detyra e personit të parë", { exact: true })).toBeVisible()
  expect(state.workspaceReads()).toBeGreaterThan(0)
  await expect(page.locator('input[type="password"]')).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Kyçe", exact: true })).toHaveCount(0)
  await page.getByRole("button", { name: "Cilësimet", exact: true }).click()
  await expect(page.locator('input[type="password"]')).toHaveCount(0)
  expect(state.writes).toEqual([])
})

test("the module administrator can pause automatic task creation", async ({ page }) => {
  const state = await shell(page, { automatic: true })
  await page.getByRole("button", { name: "Cilësimet", exact: true }).click()
  await page.getByRole("button", { name: "Ndalo krijimin automatik", exact: true }).click()
  await expect(page.getByRole("button", { name: "Aktivizo krijimin automatik", exact: true })).toBeVisible()
  expect(state.writes).toEqual([{ path: "/automation", body: { enabled: false } }])
})

test("the module administrator creates a tablet code, hides it, and revokes access", async ({ page }) => {
  const state = await shell(page)
  await page.getByRole("button", { name: "Cilësimet", exact: true }).click()
  await page.getByLabel("Emri i pajisjes", { exact: true }).fill("Tableti i familjes")
  await page.getByRole("button", { name: "Krijo kod pajisjeje", exact: true }).click()
  await expect(page.getByLabel("Kodi i pajisjes", { exact: true })).toHaveValue("pfgap_device_browser_test_only")
  await expect(page.getByLabel("Adresa e Primeflow", { exact: true })).toHaveValue("https://primeflow.primexeu.com")
  expect(state.writes[0]).toEqual({ path: "/devices", body: { name: "Tableti i familjes" } })
  await page.getByRole("button", { name: "E ruajta kodin", exact: true }).click()
  await expect(page.getByLabel("Kodi i pajisjes", { exact: true })).toHaveCount(0)
  await page.getByRole("button", { name: "Çaktivizo lidhjen", exact: true }).click()
  await expect(page.getByText("E çaktivizuar", { exact: true })).toBeVisible()
  await expect(page.getByRole("button", { name: "Çaktivizo lidhjen", exact: true })).toHaveCount(0)
})

test("focus, returning to the tab and polling keep the editor stable", async ({ page }) => {
  await page.clock.install()
  const state = await shell(page)
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
  const state = await shell(page, { automatic: true })
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

test("a slow workspace opens without displaying a password form", async ({ page }) => {
  await shell(page, { workspaceDelay: 1000, view: "week" })
  await expect(page.getByText("Duke hapur hapësirën…", { exact: true })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Hape hapësirën private" })).toHaveCount(0)
  await expect(page.getByText("Detyra e personit të parë", { exact: true })).toBeVisible()
})

test("membership revocation removes household data on the next access check", async ({ page }) => {
  await page.clock.install()
  const state = await shell(page)
  await expect(page.getByText("Detyra e personit të parë", { exact: true })).toBeVisible()
  state.revoke()
  await page.clock.fastForward(21000)
  await expect(page.getByText("Ky modul ende nuk është aktivizuar për llogarinë tënde.")).toBeVisible()
  await expect(page.getByText("Detyra e personit të parë", { exact: true })).toHaveCount(0)
})

test("the task card edits time and assignee for only this occurrence", async ({ page }) => {
  const state = await shell(page)
  const card = page.getByRole("row").filter({ has: page.getByText("Detyra e personit të parë", { exact: true }) })
  await card.getByRole("button", { name: "Cakto orën", exact: true }).click()
  await page.getByLabel("Ora e detyrës", { exact: true }).fill("18:30")
  await page.getByLabel("Përgjegjësi i detyrës", { exact: true }).selectOption("rrita")
  await page.getByRole("button", { name: "Ruaj ndryshimet", exact: true }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  await expect(card.getByText("18:30", { exact: true })).toBeVisible()
  await expect(card.getByRole("img", { name: "Person 2 · Për t’u bërë", exact: true })).toBeVisible()
  expect(state.writes[0].body).toMatchObject({ due_time: "18:30", assignees: ["rrita"], expected_version: 1, apply_to_future: false })
})

test("the task card can explicitly apply a schedule change to future recurrences", async ({ page }) => {
  const state = await shell(page)
  const card = page.getByRole("row").filter({ has: page.getByText("Detyra e personit të parë", { exact: true }) })
  await card.getByRole("button", { name: "Cakto orën", exact: true }).click()
  await page.getByLabel("Ora e detyrës", { exact: true }).fill("19:15")
  await page.getByLabel("Këtë dhe përsëritjet e ardhshme", { exact: true }).check()
  await page.getByRole("button", { name: "Ruaj ndryshimet", exact: true }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  expect(state.writes[0].body).toMatchObject({ due_time: "19:15", apply_to_future: true, expected_template_version: 1 })
})

test("module admin saves separate Kujtesa settings without requiring all personal IDs", async ({ page }) => {
  const state = await shell(page)
  await page.getByRole("button", { name: "Cilësimet", exact: true }).click()
  await page.getByLabel("Discord Server ID", { exact: true }).fill("111111111111111111")
  await page.getByLabel("Kanali privat i familjes · Channel ID", { exact: true }).fill("222222222222222222")
  await page.getByLabel("Rrita · Discord User ID", { exact: true }).fill("333333333333333333")
  await page.getByRole("button", { name: "Ruaj lidhjen me Kujtesën", exact: true }).click()
  await expect.poll(() => state.writes.length).toBe(1)
  expect(state.writes[0].body).toMatchObject({ enabled: false, user_ids: { rrita: "333333333333333333" }, expected_version: 0 })
  await expect(page.getByLabel("Mrika · Discord User ID", { exact: true })).toHaveValue("")
  await page.screenshot({ path: "test-results/ga-personal-discord-settings.png", fullPage: true })
})

test("an existing task can route its reminders to the family channel", async ({ page }) => {
  const state = await shell(page)
  const card = page.getByRole("row").filter({ has: page.getByText("Detyra e personit të parë", { exact: true }) })
  await card.getByRole("button", { name: "Cakto orën", exact: true }).click()
  await page.getByRole("combobox", { name: "Kujtesat në Discord", exact: true }).selectOption("channel")
  await page.getByRole("button", { name: "Ruaj ndryshimet", exact: true }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  expect(state.writes[0].body).toMatchObject({ discord_destination: "channel", apply_to_future: false })
})

test("creating a task supports several people and individual completion", async ({ page }) => {
  const state = await shell(page)
  await page.getByRole("button", { name: "Detyrë e re", exact: true }).click()
  await page.getByLabel("Titulli", { exact: true }).fill("Puna e përbashkët e rutinës")
  await page.getByLabel("Person 1", { exact: true }).check()
  await page.getByLabel("Person 2", { exact: true }).check()
  await expect(page.getByRole("combobox", { name: "Kryerja", exact: true })).toHaveValue("individual")
  await page.getByRole("button", { name: "Ruaje detyrën", exact: true }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  expect((state.writes[0].body.definition as { assignees: string[] }).assignees).toEqual(["gane", "mrika", "rrita"])
})

test("a new untimed task is active, visible after saving, and survives reload", async ({ page }) => {
  const state = await shell(page)
  await page.getByRole("button", { name: "Të miat", exact: true }).click()
  await page.getByLabel("Kërko detyrë", { exact: true }).fill("unrelated filter")
  await page.getByRole("button", { name: "Detyrë e re", exact: true }).click()
  await page.getByLabel("Titulli", { exact: true }).fill("Detyrë e re pa orar")
  await expect(page.getByLabel("Shto te detyrat e datës", { exact: true })).toBeChecked()
  await page.getByRole("button", { name: "Ruaje detyrën", exact: true }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  expect(state.writes[0].body.definition).toMatchObject({ enabled: true, frequency: "once", due_time: null })
  await expect(page.getByText("Detyrë e re pa orar", { exact: true })).toBeVisible()
  await page.reload()
  await page.getByRole("button", { name: "Detyrat e ditës", exact: true }).click()
  await expect(page.getByRole("row").filter({ hasText: "Detyrë e re pa orar" })).toBeVisible()
})

test("new tasks use the selected day and saving follows a changed date", async ({ page }) => {
  await shell(page)
  const selectedDay = moveDay(localToday(), 2), changedDay = moveDay(selectedDay, 1)
  const displayDate = (day: string) => day.split("-").reverse().join("/")
  await page.getByLabel("Data", { exact: true }).fill(displayDate(selectedDay))
  await page.getByRole("button", { name: "Detyrë e re", exact: true }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByLabel("Data", { exact: true })).toHaveValue(displayDate(selectedDay))
  await dialog.getByLabel("Data", { exact: true }).fill(displayDate(changedDay))
  await dialog.getByLabel("Titulli", { exact: true }).fill("Detyra për datën tjetër")
  await page.getByRole("button", { name: "Ruaje detyrën", exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByLabel("Data", { exact: true })).toHaveValue(displayDate(changedDay))
  await expect(page.getByRole("row").getByText("Detyra për datën tjetër", { exact: true })).toBeVisible()
})

test("an intentionally inactive task remains visible in templates after saving", async ({ page }) => {
  await shell(page)
  await page.getByRole("button", { name: "Detyrë e re", exact: true }).click()
  await page.getByLabel("Titulli", { exact: true }).fill("Detyrë në pritje")
  await page.getByLabel("Shto te detyrat e datës", { exact: true }).uncheck()
  await page.getByRole("button", { name: "Ruaje detyrën", exact: true }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  const card = page.locator("article").filter({ has: page.getByText("Detyrë në pritje", { exact: true }) })
  await expect(card.getByText("Pret konfigurim", { exact: true })).toBeVisible()
})

test("completing one person's occurrence preserves the other and the mobile layout fits", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await shell(page)
  const first = page.getByRole("row").filter({ has: page.getByText("Detyra e personit të parë", { exact: true }) })
  await first.getByRole("button", { name: "U kry", exact: true }).click()
  await expect(first.getByRole("button", { name: "U kry", exact: true })).toHaveCount(0)
  const second = page.getByRole("row").filter({ has: page.getByText("Detyra e personit të dytë", { exact: true }) })
  await expect(second.getByRole("button", { name: "U kry", exact: true })).toBeVisible()
  expect(state.writes).toHaveLength(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: "test-results/ga-personal-mobile.png", fullPage: true })
})

for (const view of ["today", "week"] as const) {
  test(`events filter includes legacy volleyball and explicit events in the ${view} view`, async ({ page }) => {
    const state = await shell(page, { view })
    state.rows[0].snapshot.title = "Volejboll — Mrika"
    state.rows.push({ ...state.rows[0], id: "explicit-event", template_id: "explicit-event",
      snapshot: { ...state.rows[0].snapshot, title: "Event familjar", reminder_group: "events" } })
    await page.reload()
    if (view === "today") await page.getByRole("button", { name: "Detyrat e ditës", exact: true }).click()
    const table = page.getByRole("table")
    const group = page.getByLabel("Filtro grupin", { exact: true })
    await group.selectOption("events")
    await expect(table.getByText(/^Eventet\s*2 detyra$/)).toBeVisible()
    await expect(table.getByText("Volejboll — Mrika", { exact: true })).toBeVisible()
    await expect(table.getByText("Event familjar", { exact: true })).toBeVisible()
    await expect(table.getByText("Detyra e personit të dytë", { exact: true })).toHaveCount(0)
    await expect(table).not.toContainText("Ngjarj")
    await group.selectOption("daily_upkeep")
    await expect(table.getByText("Detyra e personit të dytë", { exact: true })).toBeVisible()
    await expect(table.getByText("Volejboll — Mrika", { exact: true })).toHaveCount(0)
    await expect(table.getByText("Event familjar", { exact: true })).toHaveCount(0)
    await group.selectOption("all")
    await expect(table.getByText("Volejboll — Mrika", { exact: true })).toBeVisible()
    await expect(table.getByText("Event familjar", { exact: true })).toBeVisible()
    expect(state.writes).toEqual([])
    await page.screenshot({ path: `test-results/ga-personal-events-${view}.png`, fullPage: true })
  })
}

test("weekly KPIs precede all filters and codes survive older occurrence snapshots", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 })
  const state = await shell(page, { view: "week" })
  state.templates[0].definition.short_code = "BP-M-D"
  state.templates[1].definition.short_code = "BP-R-D"
  state.rows[1].due_at = `${localToday()}T18:30:00+01:00`
  state.rows[1].status = "needs_help"
  await page.reload()
  const table = page.getByRole("table")
  await expect(table.getByRole("rowheader", { name: "BP-R/M-D", exact: true })).toBeVisible()
  await expect(table.getByRole("columnheader", { name: "Ora", exact: true })).toBeVisible()
  const timeAction = table.getByRole("button", { name: "Cakto orën: BP-R/M-D", exact: true })
  const timeCell = timeAction.locator("..")
  await expect(timeCell).not.toContainText("Shto")
  await expect(timeAction.locator("svg.lucide-plus")).toBeVisible()
  await expect(timeCell.locator("svg.lucide-pencil")).toHaveCount(0)
  await expect(timeCell).toContainText("18:30")
  const timeBox = (await timeCell.boundingBox())!, plusBox = (await timeAction.locator("svg").boundingBox())!
  expect(plusBox.x).toBeGreaterThan(timeBox.x + timeBox.width / 2)
  expect(plusBox.y).toBeLessThan(timeBox.y + 15)
  const summary = page.getByTestId("ga-task-summary"), filters = page.getByTestId("ga-task-filters")
  const summaryBounds = (await summary.boundingBox())!, filterBounds = (await filters.boundingBox())!, tableBounds = (await table.boundingBox())!
  expect(summaryBounds.y + summaryBounds.height).toBeLessThan(filterBounds.y)
  expect(filterBounds.y + filterBounds.height).toBeLessThan(tableBounds.y)
  expect(filterBounds.height).toBeLessThan(75)
  const titleBounds = (await summary.getByRole("heading", { name: "Plani i javës", exact: true }).boundingBox())!
  const kpiBounds = (await summary.getByText("Detyra të javës", { exact: true }).locator("..").boundingBox())!
  expect(titleBounds.y + titleBounds.height / 2).toBeGreaterThanOrEqual(kpiBounds.y)
  expect(titleBounds.y + titleBounds.height / 2).toBeLessThanOrEqual(kpiBounds.y + kpiBounds.height)
  expect(kpiBounds.width).toBeLessThan(190)
  const filterCenters = await Promise.all([filters.getByLabel("Data", { exact: true }), filters.getByRole("group", { name: "Filtro sipas personit" }), filters.getByLabel("Filtro grupin"), filters.getByLabel("Filtro gjendjen"), filters.getByLabel("Kërko detyrë")].map(async (locator) => { const box = (await locator.boundingBox())!; return box.y + box.height / 2 }))
  expect(Math.max(...filterCenters) - Math.min(...filterCenters)).toBeLessThan(4)
  await page.screenshot({ path: "test-results/ga-personal-summary-filters-wide.png", fullPage: true })
  await expect(filters.getByLabel("Filtro grupin")).toBeVisible()
  await expect(filters.getByLabel("Filtro gjendjen")).toBeVisible()
  await filters.getByLabel("Kërko detyrë").fill("BP-M-D")
  await expect(table.getByRole("rowheader", { name: "BP-M-D", exact: true })).toBeVisible()
  await expect(table.getByRole("rowheader", { name: "BP-R-D", exact: true })).toHaveCount(0)
  await expect(summary.getByText("Detyra të javës").locator("..").getByText("2", { exact: true })).toBeVisible()
  await filters.getByLabel("Filtro gjendjen").selectOption("done")
  await expect(page.getByText("Nuk ka detyra në këtë pamje", { exact: true })).toBeVisible()
  await expect(summary).toBeVisible()
  expect(state.writes).toEqual([])
})

test("the weekly table scrolls within phone and tablet widths and cells still open", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("primeflow-sidebar-open", "false"))
  const state = await shell(page, { view: "week" })
  state.templates[0].definition.short_code = "DHGJ-M-D"
  state.templates[1].definition.short_code = "DHGJ-R-D"
  await page.reload()
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    const region = page.getByRole("region", { name: "Tabela e planit javor", exact: true })
    await expect(region).toBeVisible()
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    if (width <= 768) expect(await region.evaluate((el) => el.scrollWidth > el.clientWidth)).toBe(true)
    await region.evaluate((el) => { el.scrollLeft = el.scrollWidth })
    const code = page.getByRole("rowheader", { name: "DHGJ-R/M-D", exact: true })
    const codeBox = (await code.boundingBox())!, regionBox = (await region.boundingBox())!
    expect(codeBox.x).toBeGreaterThanOrEqual(regionBox.x)
    expect(codeBox.x + codeBox.width).toBeLessThan(regionBox.x + regionBox.width)
    await region.evaluate((el) => { el.scrollLeft = 0 })
    await page.screenshot({ path: `test-results/ga-personal-week-${width}.png`, fullPage: true })
  }
  await page.getByRole("table").getByRole("button", { name: /^Detyra e personit të parë,/ }).click()
  await expect(page.getByRole("dialog").getByRole("heading", { name: /DHGJ-M-D.*Detyra e personit të parë/ })).toBeVisible()
})

test("personal duties share a row with independent people, full hover titles and source legend", async ({ page }) => {
  const state = await shell(page, { view: "week" })
  const titles = ["Mirëmbajtja ditore e banjos së Mrika", "Mirëmbajtja ditore e banjos së Rrita", "Mirëmbajtja ditore e banjos së Lirza"]
  state.rows.forEach((row, i) => { row.snapshot.title = titles[i]; state.templates[i].definition.short_code = ["BP-M-D", "BP-R-D"][i] })
  state.rows[1].status = "done"
  state.rows.push({ ...state.rows[0], id: "third", template_id: "third", snapshot: { ...state.rows[0].snapshot, title: titles[2], short_code: "BP-L-D", assignees: ["lirza"] }, status: "needs_help" })
  state.rows.push({ ...state.rows[0], id: "deep", template_id: "deep", status: "in_progress", snapshot: { ...state.rows[0].snapshot, title: "Deep clean i banjos së Mrika", short_code: "BP-M-TH", frequency: "weekly", reminder_group: "weekend_deep_clean" } })
  await page.reload()
  const table = page.getByRole("table"), header = table.getByRole("rowheader", { name: "BP-R/M/L-D", exact: true })
  await expect(header).toHaveCount(1)
  await expect(table.getByRole("rowheader", { name: "BP-M-TH", exact: true })).toBeVisible()
  expect((await table.getByRole("columnheader", { name: "Detyra", exact: true }).boundingBox())!.width).toBeLessThanOrEqual(112)
  expect((await table.getByRole("columnheader", { name: "Ora", exact: true }).boundingBox())!.width).toBeLessThanOrEqual(64)
  await header.getByRole("button").hover()
  for (const title of titles) await expect(page.getByRole("tooltip")).toContainText(title)
  await expect(page.getByRole("tooltip")).toContainText("BP-L-D")
  await page.screenshot({ path: "test-results/ga-personal-grouped-hover.png", fullPage: true })
  await page.getByText("Legjenda", { exact: true }).click()
  await expect(page.getByText("Korridori i vogël", { exact: true })).toBeVisible()
  await expect(page.getByText("Korridori i bibliotekës", { exact: true })).toBeVisible()
  await expect(page.getByText("Para shkollës / mëngjes shkolle", { exact: true })).toBeVisible()
  await expect(page.getByText("Nala përgatitje para gjumit", { exact: true })).toBeVisible()
  await expect(page.getByText("Mërkurë", { exact: true })).toBeVisible()
  await expect(page.locator("details").filter({ has: page.getByText("Legjenda", { exact: true }) }).locator("dt")).toHaveCount(40)
  await expect(page.getByRole("group", { name: "Kategoritë e legjendës", exact: true })).toHaveCount(0)
  await page.screenshot({ path: "test-results/ga-personal-legend.png", fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: "test-results/ga-personal-legend-mobile.png", fullPage: true })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.getByText("Legjenda", { exact: true }).click()
  const cell = table.getByRole("button", { name: new RegExp(`^${titles[0]},`) })
  const personTextColors = new Set<string>()
  for (const [person, status, initials] of [["Person 1", "Për t’u bërë", "MC"], ["Person 2", "U kry", "RRC"], ["Person 3", "Më duhet ndihmë", "LC"]]) {
    const badge = cell.getByRole("img", { name: `${person} · ${status}`, exact: true })
    await expect(badge).toBeVisible()
    await expect(badge).toHaveAttribute("title", `${person} · ${status}`)
    await expect(badge).toHaveText(initials)
    await expect(badge.locator("svg")).toHaveCount(0)
    expect((await badge.boundingBox())!.width).toBeGreaterThanOrEqual(40)
    expect(Number.parseFloat(await badge.evaluate((el) => getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(13)
    expect(Number.parseFloat(await badge.evaluate((el) => getComputedStyle(el).borderRadius))).toBeGreaterThanOrEqual(20)
    personTextColors.add(await badge.locator("span").evaluate((el) => getComputedStyle(el).color))
    await expect(cell.getByText(status, { exact: true })).toHaveCount(0)
  }
  expect(personTextColors.size).toBe(3)
  expect(await cell.getByRole("img", { name: "Person 1 · Për t’u bërë", exact: true }).locator("span").evaluate((el) => getComputedStyle(el).color)).toBe(await table.getByRole("img", { name: "Person 1 · Po e bëj", exact: true }).locator("span").evaluate((el) => getComputedStyle(el).color))
  await expect(cell.getByRole("img", { name: "Person 1 · Për t’u bërë", exact: true })).toHaveCSS("background-color", "rgb(255, 196, 237)")
  await expect(cell.getByRole("img", { name: "Person 2 · U kry", exact: true })).toHaveCSS("background-color", "rgb(196, 253, 196)")
  await expect(table.getByRole("img", { name: "Person 1 · Po e bëj", exact: true })).toHaveCSS("background-color", "rgb(255, 255, 0)")
  expect((await cell.boundingBox())!.height).toBeLessThan(100)
  await page.screenshot({ path: "test-results/ga-personal-compact-cells.png", fullPage: true })
  await cell.click()
  await expect(page.getByRole("dialog").locator("article")).toHaveCount(3)
  expect(state.writes).toEqual([])
})

test("clicking the time column updates selected unfinished duties and each recurrence only once", async ({ page }) => {
  const state = await shell(page, { view: "week" })
  state.templates[0].definition.short_code = "BP-M-D"
  state.templates[1].definition.short_code = "BP-R-D"
  const date = new Date(`${localToday()}T12:00:00Z`)
  const otherDay = moveDay(localToday(), date.getUTCDay() === 0 ? -1 : 1)
  state.rows.push({ ...state.rows[0], id: "other-day", local_date: otherDay, period_key: otherDay })
  state.rows.push({ ...state.rows[1], id: "completed", due_at: `${localToday()}T18:10:00+01:00`, status: "done" })
  await page.reload()
  await page.getByRole("button", { name: "Cakto orën: BP-R/M-D", exact: true }).click()
  const dialog = page.getByRole("dialog")
  await expect(dialog.getByRole("heading", { name: "Cakto orën", exact: true })).toBeVisible()
  await expect(dialog.getByRole("checkbox")).toHaveCount(4)
  await dialog.getByLabel("Ora e detyrës", { exact: true }).fill("19:45")
  await page.screenshot({ path: "test-results/ga-personal-time-editor.png", fullPage: true })
  await dialog.getByLabel("Edhe përsëritjet e ardhshme", { exact: false }).check()
  await dialog.getByRole("button", { name: "Ruaj orën", exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(state.writes).toHaveLength(3)
  expect(state.writes.filter((w) => w.body.apply_to_future)).toHaveLength(2)
  expect(state.writes.map((w) => w.path)).not.toContain("/occurrences/completed")
  for (const write of state.writes) expect(write.body).toMatchObject({ due_time: "19:45", expected_version: 1 })
  expect(state.writes[0].body.assignees).toEqual(["mrika"])
  expect(state.writes[1].body.assignees).toEqual(["rrita"])
  expect(state.rows.find((r) => r.id === "completed")!.status).toBe("done")
  await page.reload()
  const timeAction = page.getByRole("button", { name: "Cakto orën: BP-R/M-D", exact: true })
  const timeCell = timeAction.locator("..")
  await expect(timeCell).toContainText("19:45")
  await expect(timeCell).toContainText("18:10")
  await timeAction.click()
  await dialog.getByLabel("Ora e detyrës", { exact: true }).fill("20:00")
  await dialog.getByRole("checkbox", { name: /Person 2/ }).uncheck()
  await dialog.getByRole("button", { name: "Ruaj orën", exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(state.writes).toHaveLength(5)
  expect(state.writes.slice(3).every((w) => w.body.apply_to_future === false)).toBe(true)
  expect(state.writes.slice(3).some((w) => w.path === `/occurrences/${secondId}`)).toBe(false)
})

test("a partial time-save failure preserves the remaining selection without repeating saved duties", async ({ page }) => {
  const state = await shell(page, { view: "week" })
  state.templates[0].definition.short_code = "BP-M-D"
  state.templates[1].definition.short_code = "BP-R-D"
  let fail = true
  await page.route(`**/ga-personal/occurrences/${secondId}`, async (route) => {
    if (route.request().method() === "PATCH" && fail) {
      fail = false
      return route.fulfill({ status: 409, json: { detail: "Detyra ndryshoi ndërkohë." } })
    }
    return route.fallback()
  })
  await page.reload()
  await page.getByRole("button", { name: "Cakto orën: BP-R/M-D", exact: true }).click()
  const dialog = page.getByRole("dialog")
  await dialog.getByLabel("Ora e detyrës", { exact: true }).fill("20:10")
  await dialog.getByRole("button", { name: "Ruaj orën", exact: true }).click()
  await expect(dialog.getByRole("alert")).toContainText("Ora u ruajt për 1 detyra.")
  await expect(dialog.getByRole("checkbox", { name: /Person 1/ })).toHaveCount(0)
  await expect(dialog.getByRole("checkbox", { name: /Person 2/ })).toBeChecked()
  await expect(dialog.getByLabel("Ora e detyrës", { exact: true })).toHaveValue("20:10")
  await dialog.getByRole("button", { name: "Ruaj orën", exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(state.writes.map((w) => w.path)).toEqual([`/occurrences/${firstId}`, `/occurrences/${secondId}`])
})

test("family additions are reviewed before import and agenda switches save independently", async ({ page }) => {
  const state = await shell(page)
  const imports: unknown[] = []
  await page.route("**/ga-personal/discord/family-pack", async (route) => {
    if (route.request().method() === "POST") {
      imports.push(route.request().postDataJSON())
      return route.fulfill({ json: { applied: true } })
    }
    return route.fulfill({ json: { hash: "a".repeat(64), counts: { create: 1, update: 0, existing: 1 }, rotation_will_change: false,
      tasks: [{ source_id: "family-demo", title: "Rutina shtesë", action: "create", definition: { due_time: "20:20:00", steps: ["Hapi i rutinës"], frequency: "daily" } }] } })
  })
  await page.getByRole("button", { name: "Cilësimet", exact: true }).click()
  await expect(page.getByRole("button", { name: "Importo rutinat në PrimeFlow", exact: true })).toHaveCount(0)
  await page.getByRole("button", { name: "Shiko shtesat para importimit", exact: true }).click()
  await expect(page.getByText("Rutina shtesë · 20:20 · Shtohet", { exact: true })).toBeVisible()
  expect(imports).toHaveLength(0)
  await page.getByRole("button", { name: "Importo rutinat në PrimeFlow", exact: true }).click()
  await expect(page.getByRole("status")).toContainText("Rutinat u ruajtën në PrimeFlow.")
  expect(imports).toEqual([{ expected_hash: "a".repeat(64) }])
  await page.getByRole("checkbox", { name: /Dërgo agjendën e ditës/ }).check()
  await page.getByRole("checkbox", { name: /Njofto zgjimin/ }).check()
  await page.getByRole("button", { name: "Ruaj lidhjen me Kujtesën", exact: true }).click()
  await expect.poll(() => state.writes.filter(w => w.path === "/discord/settings").length).toBe(1)
  expect(state.writes.find(w => w.path === "/discord/settings")!.body).toMatchObject({ daily_agenda: true, presence_notifications: true })
})
