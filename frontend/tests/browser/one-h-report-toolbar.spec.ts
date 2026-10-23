import { test, expect, type Page } from "@playwright/test"
import { execFileSync } from "node:child_process"
import path from "node:path"

const backend = path.resolve(__dirname, "../../../backend")

function report(slot = "11:00", empty = false) {
  const python = process.env.ONE_H_FILTER_PYTHON || path.join(backend, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python")
  return execFileSync(python, ["-c", `
from tests.test_one_h_report_strike_counts import fresh_document
from app.services.primeflow_report import render_html
d,_,_=fresh_document('${slot}')
d.board_reminders=[]
${slot === "14:10" ? "d.sections[-1].employees=d.sections[0].employees" : ""}
${empty ? "for s in d.sections:\n for e in s.employees:\n  for t in e.tasks:t.strike_count=0" : ""}
print(render_html(d,pre_sections_html='<p>Supplement</p>'))
`], { cwd: backend, encoding: "utf8", env: { ...process.env, PYTHONIOENCODING: "utf-8" } })
}

async function openReport(page: Page, role: "ADMIN" | "STAFF", slot = "11:00", empty = false) {
  const html = report(slot, empty)
  const user = { id: "22222222-2222-4222-8222-222222222222", full_name: "Test owner", email: "owner@example.com", role, is_active: true }
  await page.addInitScript(({ user }) => {
    localStorage.setItem("primex_access_token", "test-only-browser-token")
    localStorage.setItem("primex_user", JSON.stringify(user))
  }, { user })
  await page.route("**/api/**", async route => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === "/api/auth/me") return route.fulfill({ json: user })
    if (pathname.includes("marker-comments")) return route.fulfill({ json: { items: [], unread_count: 0 } })
    if (pathname.endsWith("/primeflow-1h-reports/preview")) return route.fulfill({ json: {
      document: { subject: `Report ${slot}`, generated_at: "2026-10-23T11:00:00Z", recipients: { to: ["preview@example.com"] } },
      html, task_count: slot === "10:00" ? 3 : slot === "14:10" ? 4 : 2,
    } })
    return route.fulfill({ json: pathname.includes("count") ? { count: 0 } : [] })
  })
  await page.goto("/admin/1h-reports")
  if (role === "ADMIN") await page.getByRole("tab", { name: "Reports", exact: true }).click()
  await page.getByRole("button", { name: role === "ADMIN" ? "Preview fresh report" : "Generate report", exact: true }).click()
  const frame = page.frameLocator('iframe[title="Email preview"]')
  await expect(frame.locator('[data-report-task="true"]').first()).toBeVisible()
  return frame
}

for (const role of ["ADMIN", "STAFF"] as const) {
  test(`${role}: larger counts and a filter above the iframe that stays selected on regeneration`, async ({ page }, testInfo) => {
    const frame = await openReport(page, role)
    const toolbar = page.getByTestId("one-h-strikes-toolbar")
    const button = toolbar.getByRole("button", { name: "Vetëm me strikes > 0" })
    const buttonBox = await button.boundingBox(), frameBox = await page.locator('iframe[title="Email preview"]').boundingBox()
    expect(buttonBox!.y + buttonBox!.height).toBeLessThanOrEqual(frameBox!.y)
    await expect(frame.getByRole("button", { name: "Vetëm me strikes > 0" })).toHaveCount(0)
    await expect(frame.locator('[data-task-strike-count]').first()).toHaveCSS("font-size", "14px")
    await expect(frame.locator('[data-report-strike-total]')).toHaveCSS("font-size", "16px")
    await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(2)
    await button.click()
    await expect(button).toHaveAttribute("aria-pressed", "true")
    await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(1)
    await expect(frame.locator('[data-report-task="true"]:visible')).toHaveAttribute("data-strike-count", "2")
    await expect(frame.locator('[data-report-task-section]:visible')).toHaveCount(1)
    await expect(frame.locator('[data-report-supplement]')).toBeHidden()
    await expect(toolbar.getByRole("status")).toHaveText("Shfaqen 1 nga 2 detyra")
    await page.getByRole("button", { name: role === "ADMIN" ? "Preview fresh report" : "Generate report", exact: true }).click()
    await expect(button).toHaveAttribute("aria-pressed", "true")
    await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(1)
    await expect(toolbar.getByRole("status")).toHaveText("Shfaqen 1 nga 2 detyra")
    await button.click()
    await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(2)
    await expect(frame.locator('[data-report-supplement]')).toBeVisible()
    await page.screenshot({ path: testInfo.outputPath("toolbar.png") })
  })
}

test("no matches hides empty groups and shows the message above the report", async ({ page }) => {
  const frame = await openReport(page, "ADMIN", "10:00", true)
  const button = page.getByTestId("one-h-strikes-toolbar").getByRole("button")
  await button.click()
  await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(0)
  await expect(frame.locator('[data-report-task-employee]:visible')).toHaveCount(0)
  await expect(frame.locator('[data-report-task-section]:visible')).toHaveCount(0)
  await expect(page.getByText("Nuk ka detyra me strikes > 0 në këtë interval.")).toBeVisible()
  await button.click()
  await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(3)
  await expect(page.getByText("Nuk ka detyra me strikes > 0 në këtë interval.")).toHaveCount(0)
})

test("the top filter also controls BLL table rows", async ({ page }) => {
  const frame = await openReport(page, "STAFF", "14:10")
  const button = page.getByTestId("one-h-strikes-toolbar").getByRole("button")
  await button.click()
  await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(2)
  const bll = frame.locator('[data-bll-task-table] tr[data-report-task="true"]:visible')
  await expect(bll).toHaveCount(1)
  await expect(bll).toHaveAttribute("data-strike-count", "2")
  await button.click()
  await expect(bll).toHaveCount(2)
})
