import { test, expect } from "@playwright/test"

const user = { id: "22222222-2222-4222-8222-222222222222", full_name: "Elsa Ferati", email: "elsa@example.test", role: "MANAGER", is_active: true, department_id: null }
const row = { id: "11111111-1111-4111-8111-111111111111", date: "2026-10-27", slot: "14:20", status: "DISCORD_REPORT", started_at: null,
  staff_started_at: null, ended_at: null, duration_minutes: null, summary_status: null, has_summary: false, error: null, people: [] }
const tasks = [
  { id: "33333333-3333-4333-8333-333333333333", title: "EF/DV: ASIST DISCORD PERSONAL", planned_status: "TODO", status: "IN_PROGRESS", available: true,
    answer: "Po vazhdoj me konfigurimin.", expected_at: "Sot 15:30", skipped: false, history: [
      { kind: "ANSWER", at: "2026-10-27T14:21:00+01:00", question: "Pse s’ke vazhdu me këtë detyrë? Kur vazhdon?", answer: "Pres materialet.", expected_at: "Sot 15:00" },
      { kind: "ANSWER", at: "2026-10-27T14:22:00+01:00", question: "A ke me vazhdu me këtë detyrë? Kur pritet me u kry?", answer: "Po vazhdoj me konfigurimin.", expected_at: "Sot 15:30" },
      { kind: "ACTION", at: "2026-10-27T14:23:00+01:00", instruction: "Bëj strike pikën 1", status: "DONE", message: "Pika u përditësua" },
    ], postponements: [] },
  { id: "44444444-4444-4444-8444-444444444444", title: "EF/RA: RAPORTI I FUNDIT TË MUAJIT", planned_status: "TODO", status: "TODO", available: true,
    answer: null, expected_at: null, skipped: true, history: [], postponements: [
      { id: "request", status: "PENDING", label: "Në pritje të Diellzës", comment: "Pres konfirmimin e klientit.", proposed_dates: { due_date: "2026-10-28T15:00:00Z" }, at: "2026-10-27T14:24:00+01:00" },
    ] },
]

test("Mira groups Discord answers and task outcomes without requiring a voice-host meeting", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 950 })
  await page.addInitScript(({ user }) => {
    localStorage.setItem("primex_access_token", "test-only-browser-token")
    localStorage.setItem("primex_user", JSON.stringify(user))
  }, { user })
  await page.route("http://127.0.0.1:8012/api/**", async route => {
    const path = new URL(route.request().url()).pathname
    if (path === "/api/auth/me") return route.fulfill({ json: user })
    if (path === "/api/mira/status") return route.fulfill({ json: { enabled: false, live: null } })
    if (path === "/api/mira/meetings") return route.fulfill({ json: { total: 1, items: [row] } })
    if (path === `/api/mira/meetings/${row.id}`) return route.fulfill({ json: {
      ...row, turns: [], summary: null, transcript: [], events: [], mentions: [], recorder: null,
      discord_reports: [
        { id: "report", user_id: user.id, name: user.full_name, state: "PARTIAL", created_at: "2026-10-27T14:20:00+01:00", sent_at: "2026-10-27T14:20:01+01:00", tasks,
          next: { answer: "EF: OFERTA E RADHËS", selection_kind: "TASKS", history: [], selected_tasks: [
            { id: "66666666-6666-4666-8666-666666666666", title: "EF: OFERTA E RADHËS", status: "TODO", slot: "16:00", group: "LATER" },
          ] } },
        { id: "done-report", user_id: "oh", name: "Olsa Hajdari", state: "DONE", created_at: "2026-10-27T14:20:00+01:00", sent_at: "2026-10-27T14:20:01+01:00",
          tasks: [{ ...tasks[0], id: "55555555-5555-4555-8555-555555555555", title: "OH: OFERTA", status: "DONE", planned_status: "DONE", answer: null, expected_at: null, history: [], postponements: [] }],
          next: { answer: "Vazhdoj me përgatitjen e ofertës tjetër.", history: [] } },
      ],
    } })
    return route.fulfill({ json: path.includes("count") ? { count: 0 } : [] })
  })
  await page.goto("/mira")
  await page.getByRole("button", { name: /14:20 Raportimet e stafit/ }).click()
  await expect(page.getByRole("heading", { name: "Raportimet nga Discord" })).toBeVisible()
  await expect(page.getByText("Po vazhdoj me konfigurimin.", { exact: true }).first()).toBeVisible()
  await expect(page.getByText("Pjesërisht i raportuar", { exact: true })).toBeVisible()
  await expect(page.getByText("Në pritje të Diellzës", { exact: false })).toBeVisible()
  await expect(page.getByText("E kaluar pa përgjigje", { exact: true })).toBeVisible()
  const nextQuestion = page.getByText("Me çka ke me vazhdu në slotin tjetër?", { exact: true })
  await expect(nextQuestion).toHaveCount(2)
  await expect(page.getByRole("link", { name: "EF: OFERTA E RADHËS" })).toBeVisible()
  const questionBox = await nextQuestion.first().boundingBox()
  const taskBox = await page.getByRole("link", { name: "EF/DV: ASIST DISCORD PERSONAL" }).boundingBox()
  expect(questionBox!.y).toBeLessThan(taskBox!.y)
  await expect(page.getByText("Nuk ka transkript.")).toHaveCount(0)
  await page.getByText("Historiku · 3", { exact: true }).click()
  await expect(page.getByText("Pres materialet.", { exact: true })).toBeVisible()
  await expect(page.getByText("Pika u përditësua", { exact: false })).toBeVisible()
  await page.screenshot({ path: "test-results/mira-discord-reports-desktop.png", fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole("heading", { name: "Raportimet nga Discord" })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: "test-results/mira-discord-reports-mobile.png", fullPage: true })
})
