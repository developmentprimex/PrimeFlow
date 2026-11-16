import { test, expect, type Page } from "@playwright/test"

async function setup(page: Page, role = "ADMIN") {
  const user = { id: "22222222-2222-4222-8222-222222222222", full_name: "Email Administrator", email: "admin@example.com", role, is_active: true }
  let connected = true
  let verified = false
  let failRead = false
  const writes: string[] = []
  await page.addInitScript(user => {
    localStorage.setItem("primex_access_token", "browser-test-only")
    localStorage.setItem("primex_user", JSON.stringify(user))
  }, user)
  await page.route("http://127.0.0.1:8019/api/**", async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (request.method() !== "GET" && !path.startsWith("/api/auth/")) writes.push(`${request.method()} ${path}`)
    if (path === "/api/auth/me") return route.fulfill({ json: user })
    if (path === "/api/mailbox/status") return route.fulfill({ json: {
      configured: true, authorized: connected, connected: connected && verified, encryption_ready: true, mailbox_email: "info@primexeu.com",
      redirect_uri: "http://127.0.0.1:8019/api/mailbox/callback", has_read_permissions: connected,
      last_checked_at: verified ? "2026-11-09T10:00:00Z" : null,
    } })
    if (path === "/api/mailbox/test") {
      if (failRead) return route.fulfill({ status: 409, json: { detail: "Microsoft nuk lejoi leximin." } })
      verified = true
      return route.fulfill({ json: {
        checked_at: "2026-11-09T10:00:00Z", categories: [{ id: "tt", name: "TT" }, { id: "pagesa", name: "Pagesa" }],
        messages: [{ id: "m1", subject: "TT — Kërkesë për tekstin", sender_name: "Klienti", sender_email: "client@example.com", received_at: "2026-11-09T09:00:00Z", preview: '<script>window.emailExecuted=true</script> Ndryshoni tekstin në faqe.', categories: ["TT", "Pagesa"], is_read: false }],
      } })
    }
    if (path === "/api/mailbox/connection") {
      connected = false
      verified = false
      return route.fulfill({ json: { connected: false } })
    }
    return route.fulfill({ json: path.includes("count") ? { count: 0 } : [] })
  })
  await page.goto("/admin/email")
  return { writes, fail: () => { failRead = true } }
}

test("administrator explicitly previews email, handles failure and disconnects without task or Note writes", async ({ page }) => {
  const { writes, fail } = await setup(page)
  const read = page.getByRole("button", { name: "Provo leximin", exact: true })
  await expect(read).toBeEnabled()
  await expect(page.getByText("Autorizimi është ruajtur · leximi ende nuk është verifikuar", { exact: true })).toBeVisible()
  await expect(page.getByText("TT — Kërkesë për tekstin", { exact: true })).toHaveCount(0)
  expect(writes).toEqual([])
  await read.click()
  await expect(page.getByRole("heading", { name: "TT — Kërkesë për tekstin" })).toBeVisible()
  await expect(page.getByText("Autorizimi është ruajtur · leximi është verifikuar", { exact: true })).toBeVisible()
  await expect(page.getByText(/<script>window.emailExecuted/)).toBeVisible()
  expect(await page.evaluate(() => (window as unknown as { emailExecuted?: boolean }).emailExecuted)).toBeUndefined()
  await page.screenshot({ path: "../tmp/mailbox-desktop.png", fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(read).toBeVisible()
  await page.screenshot({ path: "../tmp/mailbox-mobile.png", fullPage: true })
  fail()
  await read.click()
  await expect(page.getByRole("alert").filter({ hasText: "Microsoft nuk lejoi leximin." })).toBeVisible()
  await expect(page.getByRole("heading", { name: "TT — Kërkesë për tekstin" })).toHaveCount(0)
  await page.getByRole("button", { name: "Shkëput", exact: true }).click()
  await expect(read).toBeDisabled()
  expect(writes).toEqual(["POST /api/mailbox/test", "POST /api/mailbox/test", "DELETE /api/mailbox/connection"])
})

test("staff cannot access the mailbox preview", async ({ page }) => {
  const { writes } = await setup(page, "STAFF")
  await expect(page.getByText("Kjo faqe është vetëm për administratorin.")).toBeVisible()
  await expect(page.getByRole("button", { name: "Provo leximin" })).toHaveCount(0)
  expect(writes).toEqual([])
})
