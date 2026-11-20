import { test, expect, type Page } from "@playwright/test"

const user = { id: "22222222-2222-4222-8222-222222222222", full_name: "Arta Krasniqi", email: "arta@example.com", role: "STAFF", is_active: true, department_id: null }
const offer = "11111111-1111-4111-8111-111111111111"
const printer = "33333333-3333-4333-8333-333333333333"
const list = {
  counts: { open: 2, closed: 1 }, failed_meetings: 1,
  items: [
    { id: offer, title: "Oferta për klientin Albaniaplast", kind: "TASK", status: "OPEN", quiet: false, mention_count: 3, last_mentioned_at: "2026-10-21T07:58:00+00:00" },
    { id: printer, title: "Printeri në zyrën e dytë nuk punon", kind: "TOPIC", status: "OPEN", quiet: true, mention_count: 5, last_mentioned_at: "2026-09-10T07:58:00+00:00" },
  ],
}
const detail = (version: number, extra: Record<string, unknown> = {}) => ({
  ...list.items[0], description: "Arta e përgatit ofertën. Pret çmimet nga furnitori.", people: ["Arta", "Besnik"], version, human_edited: false,
  events: [
    { kind: "MENTION", text: "Arta: ende pret çmimet nga furnitori.", created_at: "2026-10-21T07:58:00+00:00", meeting_title: "1H", user_name: null, partial: false },
    { kind: "MENTION", text: "Besnik pyeti për afatin; Arta tha deri të enjten.", created_at: "2026-10-20T12:18:00+00:00", meeting_title: "1H", user_name: null, partial: true },
    { kind: "MENTION", text: "U vendos që oferta të shkojë te Arta.", created_at: "2026-10-17T08:30:00+00:00", meeting_title: "Shitja", user_name: null, partial: false },
  ],
  ...extra,
})

async function shell(page: Page, { conflict = false, role = "STAFF" } = {}) {
  const writes: { method: string; path: string; body: unknown }[] = []
  const viewer = { ...user, role }
  await page.addInitScript(({ user }) => {
    localStorage.setItem("primex_access_token", "test-only-browser-token")
    localStorage.setItem("primex_user", JSON.stringify(user))
  }, { user: viewer })
  await page.route("http://127.0.0.1:8012/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path === "/api/auth/me") return route.fulfill({ json: viewer })
    if (path === "/api/mira-memory/items") return route.fulfill({ json: list })
    if (path === `/api/mira-memory/items/${offer}`) {
      if (request.method() === "PATCH") {
        writes.push({ method: "PATCH", path, body: request.postDataJSON() })
        if (conflict) return route.fulfill({ status: 409, json: { detail: "Pika është ndryshuar ndërkohë. U rifreskua." } })
        return route.fulfill({ json: detail(2, { description: "Arta e dërgon të premten.", human_edited: true }) })
      }
      return route.fulfill({ json: detail(1) })
    }
    return route.fulfill({ json: path.includes("count") ? { count: 0 } : [] })
  })
  await page.goto("/mira-kujtesa")
  await expect(page.getByRole("heading", { name: "Kujtesa e Mira-s" })).toBeVisible()
  return writes
}

test("the register lists items, shows history and saves a correction with its version", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 860 })
  const writes = await shell(page)
  await expect(page.getByText("e heshtur")).toBeVisible()
  await page.getByRole("button", { name: /Oferta për klientin Albaniaplast/ }).click()
  await expect(page.getByText("1H · 21.10, 09:58")).toBeVisible()
  await expect(page.getByText("(takim i pjesshëm)")).toBeVisible()
  await expect(page.getByText("1 takim nuk u përfshi në kujtesë.")).toBeVisible()
  await expect(page.getByRole("button", { name: "Provo përsëri" })).toHaveCount(0)
  await page.screenshot({ path: "test-results/mira-memory-desktop.png", fullPage: true })
  await page.getByRole("button", { name: "Korrigjo" }).click()
  await page.getByLabel("Gjendja aktuale").fill("Arta e dërgon të premten.")
  await page.getByRole("button", { name: "Ruaj" }).click()
  await expect(page.getByText("Arta e dërgon të premten.")).toBeVisible()
  expect(writes).toEqual([{ method: "PATCH", path: `/api/mira-memory/items/${offer}`,
    body: { version: 1, title: "Oferta për klientin Albaniaplast", description: "Arta e dërgon të premten." } }])
})

test("a stale correction shows the conflict and reloads the item", async ({ page }) => {
  await shell(page, { conflict: true })
  await page.getByRole("button", { name: /Oferta për klientin Albaniaplast/ }).click()
  await page.getByRole("button", { name: "Korrigjo" }).click()
  await page.getByLabel("Gjendja aktuale").fill("Ndryshim i vjetër.")
  await page.getByRole("button", { name: "Ruaj" }).click()
  await expect(page.getByText("Pika është ndryshuar ndërkohë. U rifreskua.")).toBeVisible()
  // The stale draft is dropped so the other person's change is what you see, not overwritten by a second save.
  await expect(page.getByLabel("Gjendja aktuale")).toBeHidden()
  await expect(page.getByText("Arta e përgatit ofertën. Pret çmimet nga furnitori.")).toBeVisible()
})

test("on a phone the list and the item take turns", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await shell(page)
  const closeSidebar = page.getByRole("button", { name: "Close sidebar" })
  if (await closeSidebar.evaluate((button) => button.getBoundingClientRect().right > 0)) {
    await closeSidebar.click()
  }
  await page.screenshot({ path: "test-results/mira-memory-phone-list.png", fullPage: true })
  await page.getByRole("button", { name: /Oferta për klientin Albaniaplast/ }).click()
  await expect(page.getByRole("button", { name: "Kthehu te lista" })).toBeVisible()
  await expect(page.getByRole("button", { name: /Printeri/ })).toBeHidden()
  await page.screenshot({ path: "test-results/mira-memory-phone-detail.png", fullPage: true })
  await page.getByRole("button", { name: "Kthehu te lista" }).click()
  await expect(page.getByRole("button", { name: /Printeri/ })).toBeVisible()
})

test("Notetaker shows a clarification and links its evidence to the transcript", async ({ page }) => {
  const meeting = "44444444-4444-4444-8444-444444444444"
  const priorMeeting = "55555555-5555-4555-8555-555555555555"
  const source = { id: "source", speaker: "GA", start_ms: 316000, end_ms: 330000 }
  const question = "Kush është përgjegjës?"
  const { id, title, kind, status } = list.items[0]
  const writes: unknown[] = []
  await shell(page)
  await page.route(`**/api/mira/notetaker/meetings/${meeting}`, route => route.fulfill({ json: {
    id: meeting, title: "Takimi Modeco", started_at: "2026-11-19T09:00:00+01:00",
    partial: true, quick_summary: null, full_notes: "Shënime", error: null,
    transcript: [{ ...source, text: "Kontrollojeni ofertën deri nesër." }],
    memory: { points: [{ id, title, kind, status, needs_follow_up: true, text: "Kontrolli i ofertës u kërkua nga GA.",
      correction: null, project: "Modeco", requested_by: "GA", assignee: null, deadline_text: "nesër",
      deadline_date: "2026-11-20", questions: [question], answers: {}, sources: [source], discussion_state: "REPEATED" },
    { id: "decision", title: "Vendimi për ofertën", kind: "DECISION", status: "OPEN", needs_follow_up: false,
      text: "Oferta u miratua.", questions: [], answers: {}, sources: [] }],
    previous: [{ id, title, text: "U diskutua oferta.", meeting_id: priorMeeting, meeting_title: "Takimi paraprak Modeco",
      date: "2026-11-18T09:00:00+01:00" }] },
  } }))
  await page.route(`**/api/mira/notetaker/meetings/${priorMeeting}`, route => route.fulfill({ json: {
    id: priorMeeting, title: "Takimi paraprak Modeco", started_at: "2026-11-18T09:00:00+01:00",
    partial: false, quick_summary: null, full_notes: "Shënimet e mëparshme", error: null, transcript: [],
  } }))
  await page.route(`**/api/mira-memory/items/${offer}/clarifications`, async route => {
    const body = route.request().postDataJSON()
    writes.push(body)
    await route.fulfill({ json: { question, answer: body.answer } })
  })
  await page.goto(`/mira?tab=notetaker&meeting=${meeting}&view=quick`)
  await expect(page.getByText("Regjistrimi ose transkripti është i pjesshëm.")).toBeVisible()
  await expect(page.getByRole("heading", { name: "Kërkohet sqarim" })).toBeVisible()
  await page.getByRole("button", { name: "Përgjigju" }).click()
  await page.getByRole("textbox", { name: question }).fill("Arta.")
  await page.getByRole("button", { name: "Ruaj sqarimin" }).click()
  await expect(page.getByRole("heading", { name: "Kërkohet sqarim" })).toHaveCount(0)
  expect(writes).toEqual([{ meeting_id: meeting, question, answer: "Arta." }])
  await page.getByRole("link", { name: "Kujtesa e takimit" }).click()
  await expect(page.getByText(/Diskutuar më parë/)).toBeVisible()
  await expect(page.getByText("Arta.", { exact: true })).toBeVisible()
  await expect(page.getByText("Vendimi për ofertën")).toBeVisible()
  await page.getByRole("link", { name: "Pikat e hapura" }).click()
  await expect(page.getByText("Kontrolli i ofertës u kërkua nga GA.")).toBeVisible()
  await expect(page.getByText("Vendimi për ofertën")).toHaveCount(0)
  await page.getByRole("link", { name: "GA · 05:16–05:30" }).click()
  await expect(page).toHaveURL(/view=transcript#segment-source/)
  await expect(page.locator('#segment-source[data-source="true"]')).toContainText("Kontrollojeni ofertën deri nesër.")
  await page.getByRole("link", { name: "Historiku i takimeve" }).click()
  await page.getByRole("link", { name: /Takimi paraprak Modeco/ }).click()
  await expect(page.getByRole("heading", { name: "Takimi paraprak Modeco" })).toBeVisible()
})

test("Notetaker can filter open points before the next meeting", async ({ page }) => {
  await shell(page)
  const point = { id: offer, title: "Oferta Modeco", text: "Pritet përgjigjja.", meeting_id: offer,
    meeting_title: "Takimi Modeco", date: "2026-11-19T09:00:00+01:00" }
  await page.route(/\/api\/mira\/notetaker\/meetings\?/, route => {
    const query = new URL(route.request().url()).searchParams.get("follow_up_query")
    return route.fulfill({ json: { items: [], follow_up: query === "Dantese" ? [] : [point] } })
  })
  await page.goto("/mira?tab=notetaker")
  await expect(page.getByText("Oferta Modeco")).toBeVisible()
  await page.getByLabel("Kërko pika të hapura sipas projektit ose temës").fill("Dantese")
  await page.getByRole("button", { name: "Kërko", exact: true }).click()
  await expect(page.getByText("Nuk u gjetën pika të hapura për këtë kërkim.")).toBeVisible()
  await expect(page.getByText("Oferta Modeco")).toHaveCount(0)
})

test("an admin can generate a missing 1H summary from its saved transcript", async ({ page }) => {
  await shell(page, { role: "ADMIN" })
  const meeting = "44444444-4444-4444-8444-444444444444"
  const endpoint = `**/api/mira/notetaker/meetings/${meeting}`
  let queued = false
  await page.route(endpoint, route => route.fulfill({ json: {
    id: meeting, title: "Takimi 1H", started_at: "2026-11-20T11:51:00+01:00",
    partial: true, full_notes: "Shënimet e ruajtura.", error: null,
    transcript: [{ id: "source", speaker: "Ana", start_ms: 0, end_ms: 1000, text: "Dërgohet raporti." }],
    quick_summary: queued ? { discussion: ["U diskutua raporti."], decisions: [], actions: [], open_points: [], follow_up: [] } : null,
  } }))
  await page.route(`${endpoint}/summarize`, route => {
    expect(route.request().method()).toBe("POST")
    queued = true
    return route.fulfill({ status: 202, json: { queued: true } })
  })
  await page.goto(`/mira?tab=notetaker&meeting=${meeting}`)
  await expect(page.getByRole("link", { name: "Hap transkriptin" })).toBeVisible()
  await page.getByRole("button", { name: "Gjenero përmbledhjen" }).click()
  await expect(page.getByText("MIRA po përgatit përmbledhjen nga transkripti.")).toBeVisible()
  await expect(page.getByText("U diskutua raporti.")).toBeVisible()
  await expect(page.getByText("Regjistrimi ose transkripti është i pjesshëm.")).toBeVisible()
})
