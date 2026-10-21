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

async function shell(page: Page, { conflict = false } = {}) {
  const writes: { method: string; path: string; body: unknown }[] = []
  await page.addInitScript(({ user }) => {
    localStorage.setItem("primex_access_token", "test-only-browser-token")
    localStorage.setItem("primex_user", JSON.stringify(user))
  }, { user })
  await page.route("http://127.0.0.1:8012/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path === "/api/auth/me") return route.fulfill({ json: user })
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
  // The app opens its navigation on small screens; close it like a person would.
  await page.getByRole("button", { name: "Close sidebar" }).click()
  await page.screenshot({ path: "test-results/mira-memory-phone-list.png", fullPage: true })
  await page.getByRole("button", { name: /Oferta për klientin Albaniaplast/ }).click()
  await expect(page.getByRole("button", { name: "Kthehu te lista" })).toBeVisible()
  await expect(page.getByRole("button", { name: /Printeri/ })).toBeHidden()
  await page.screenshot({ path: "test-results/mira-memory-phone-detail.png", fullPage: true })
  await page.getByRole("button", { name: "Kthehu te lista" }).click()
  await expect(page.getByRole("button", { name: /Printeri/ })).toBeVisible()
})
