import { test, expect } from "@playwright/test"
import { execFileSync } from "node:child_process"
import path from "node:path"

const backend = path.resolve(__dirname, "../../../backend")

function report(slot = "11:00", empty = false) {
  const python = process.env.ONE_H_FILTER_PYTHON || path.join(backend, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python")
  return execFileSync(python, ["-c", `
from tests.test_one_h_report_strike_counts import fresh_document
from app.services.primeflow_report import render_html,add_preview_strike_filter
d,_,_=fresh_document('${slot}')
d.board_reminders=[]
${slot === "14:10" ? "d.sections[-1].employees=d.sections[0].employees" : ""}
${empty ? "for s in d.sections:\n for e in s.employees:\n  for t in e.tasks:t.strike_count=0" : ""}
print(add_preview_strike_filter(render_html(d,pre_sections_html='<p>Supplement</p>')))
`], { cwd: backend, encoding: "utf8", env: { ...process.env, PYTHONIOENCODING: "utf-8" } })
}

test("filter keeps only positive tasks and restores the full report", async ({ page }) => {
  await page.setContent(report())
  const button = page.getByRole("button", { name: "Vetëm me strikes > 0" })
  await expect(page.locator('[data-report-task="true"]:visible')).toHaveCount(2)
  await expect(page.locator('[data-report-task-section]:visible')).toHaveCount(2)
  await button.click()
  await expect(button).toHaveAttribute("aria-pressed", "true")
  await expect(page.locator('[data-report-task="true"]:visible')).toHaveCount(1)
  await expect(page.locator('[data-report-task="true"]:visible')).toHaveAttribute("data-strike-count", "2")
  await expect(page.locator('[data-report-task-section]:visible')).toHaveCount(1)
  await expect(page.locator('[data-report-supplement]')).toBeHidden()
  await expect(page.getByRole("status")).toHaveText("Shfaqen 1 detyra")
  await button.click()
  await expect(button).toHaveAttribute("aria-pressed", "false")
  await expect(page.locator('[data-report-task="true"]:visible')).toHaveCount(2)
  await expect(page.locator('[data-report-task-section]:visible')).toHaveCount(2)
  await expect(page.locator('[data-report-supplement]')).toBeVisible()
})

test("no matches hides empty groups and shows an explanation", async ({ page }) => {
  await page.setContent(report("10:00", true))
  await page.getByRole("button", { name: "Vetëm me strikes > 0" }).click()
  await expect(page.locator('[data-report-task="true"]:visible')).toHaveCount(0)
  await expect(page.locator('[data-report-task-employee]:visible')).toHaveCount(0)
  await expect(page.locator('[data-report-task-section]:visible')).toHaveCount(0)
  await expect(page.getByText("Nuk ka detyra me strikes > 0 në këtë interval.")).toBeVisible()
  await page.getByRole("button", { name: "Vetëm me strikes > 0" }).click()
  await expect(page.locator('[data-report-task="true"]:visible')).toHaveCount(3)
  await expect(page.getByText("Nuk ka detyra me strikes > 0 në këtë interval.")).toBeHidden()
})

test("BLL table rows also obey the positive-strikes filter", async ({ page }) => {
  await page.setContent(report("14:10"))
  await page.getByRole("button", { name: "Vetëm me strikes > 0" }).click()
  await expect(page.locator('[data-report-task="true"]:visible')).toHaveCount(2)
  const bll = page.locator('[data-bll-task-table] tr[data-report-task="true"]:visible')
  await expect(bll).toHaveCount(1)
  await expect(bll).toHaveAttribute("data-strike-count", "2")
  await page.getByRole("button", { name: "Vetëm me strikes > 0" }).click()
  await expect(page.locator('[data-bll-task-table] tr[data-report-task="true"]:visible')).toHaveCount(2)
})
