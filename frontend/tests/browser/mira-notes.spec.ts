import { test, expect, type Page } from "@playwright/test"

const user = { id: "22222222-2222-4222-8222-222222222222", full_name: "Arta Krasniqi", email: "arta@example.com", role: "STAFF", is_active: true, department_id: null }
const desktopId = "11111111-1111-4111-8111-111111111111"
const meetingId = "33333333-3333-4333-8333-333333333333"
const rows = [
  { id: desktopId, kind: "PX_NOTE", source: "DESKTOP", title: "Takimi me ekipin", content: "**Vendimet:**\nDetaji i shënimit të desktopit.", status: "OPEN", created_at: "2026-10-28T09:30:00Z", note_id: desktopId, meeting_id: null, url: "/ga-ka-notes", shared_to_px: false },
  { id: meetingId, kind: "1H", source: "1H", title: "1H 10:00 · 28.10.2026", content: "Përmbledhja e takimit 1H.", status: "DONE", created_at: "2026-10-28T08:30:00Z", note_id: null, meeting_id: meetingId, url: "/ga-ka-notes", shared_to_px: false },
]

async function shell(page: Page, { failRead = false, failShare = false, paginated = false } = {}) {
  const writes: string[] = []
  const offsets: number[] = []
  let shared = false, readFailed = false
  await page.addInitScript(({ user }) => {
    localStorage.setItem("primex_access_token", "test-only-browser-token")
    localStorage.setItem("primex_user", JSON.stringify(user))
  }, { user })
  await page.route("http://127.0.0.1:8012/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    if (path === "/api/auth/me") return route.fulfill({ json: user })
    if (path === "/api/mira/status") return route.fulfill({ json: { enabled: false, live: null } })
    if (path === "/api/mira/notes") {
      if (failRead && !readFailed) { readFailed = true; return route.fulfill({ status: 500, json: { detail: "Nuk u ngarkuan shënimet." } }) }
      const offset = Number(url.searchParams.get("offset")); offsets.push(offset)
      if (paginated) return route.fulfill({ json: offset === 0
        ? Array.from({ length: 100 }, (_, index) => ({ ...rows[0], id: `note-${index}`, title: `Shënimi ${index + 1}` }))
        : [{ ...rows[0], id: "older", title: "Shënimi i vjetër", status: "CLOSED", created_at: "2026-01-01T10:00:00Z" }] })
      return route.fulfill({ json: rows.map(row => ({ ...row, shared_to_px: row.id === desktopId && shared })) })
    }
    if (path.endsWith("/show-in-px-notes")) {
      writes.push(request.method() + " " + path)
      if (failShare) return route.fulfill({ status: 500, json: { detail: "Ruajtja dështoi." } })
      shared = true
      return route.fulfill({ json: { note_id: desktopId, shared_to_px: true, url: "/ga-ka-notes" } })
    }
    return route.fulfill({ json: path.includes("count") ? { count: 0 } : [] })
  })
  await page.goto("/mira?tab=shenimet")
  await expect(page.getByRole("heading", { name: /Shënimet e Mira-s/ })).toBeVisible()
  return { writes, offsets }
}

test("notes table expands content and sharing persists without removing the Mira row", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const { writes } = await shell(page)
  const desktop = page.getByRole("row").filter({ hasText: "Takimi me ekipin" })
  await expect(desktop.getByText("Mira Desktop")).toBeVisible()
  await expect(page.getByText("Detaji i shënimit të desktopit.")).toBeHidden()
  await desktop.getByRole("button", { name: "Takimi me ekipin" }).click()
  await expect(page.getByText("Detaji i shënimit të desktopit.")).toBeVisible()
  await page.screenshot({ path: "test-results/mira-notes-desktop.png", fullPage: true })
  await desktop.getByRole("button", { name: "Shfaq në PX Notes" }).click()
  await expect(desktop.getByText("Shfaqet në PX Notes")).toBeVisible()
  expect(writes).toEqual([`POST /api/mira/notes/PX_NOTE/${desktopId}/show-in-px-notes`])
  await page.reload()
  await expect(page.getByRole("row").filter({ hasText: "Takimi me ekipin" }).getByText("Shfaqet në PX Notes")).toBeVisible()
  await expect(page.getByRole("row").filter({ hasText: "1H 10:00" }).getByRole("button", { name: "Shfaq në PX Notes" })).toBeVisible()
})

test("all pages are loaded and old closed notes remain searchable", async ({ page }) => {
  const { offsets } = await shell(page, { paginated: true })
  await page.getByRole("textbox", { name: "Kërko shënime" }).fill("Shënimi i vjetër")
  const row = page.getByRole("row").filter({ hasText: "Shënimi i vjetër" })
  await expect(row.getByText("E mbyllur")).toBeVisible()
  expect(offsets).toEqual([0, 100])
})

test("read errors offer retry and failed sharing never reports success", async ({ page }) => {
  await shell(page, { failRead: true, failShare: true })
  await expect(page.getByRole("alert").filter({ hasText: "Nuk u ngarkuan shënimet." })).toBeVisible()
  await page.getByRole("button", { name: "Provo përsëri" }).click()
  const row = page.getByRole("row").filter({ hasText: "Takimi me ekipin" })
  await row.getByRole("button", { name: "Shfaq në PX Notes" }).click()
  await expect(page.getByText("Ruajtja dështoi.")).toBeVisible()
  await expect(row.getByRole("button", { name: "Shfaq në PX Notes" })).toBeEnabled()
  await expect(row.getByText("Shfaqet në PX Notes")).toBeHidden()
})

test("phone keeps the table inside a horizontal scroll container", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await shell(page)
  await page.getByRole("button", { name: "Close sidebar" }).click()
  await expect(page.getByRole("button", { name: "Takimi me ekipin" })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: "test-results/mira-notes-phone.png", fullPage: true })
})
