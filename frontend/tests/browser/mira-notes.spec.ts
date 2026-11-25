import { expect, test, type Page } from "@playwright/test"

const user = { id: "22222222-2222-4222-8222-222222222222", full_name: "Arta Krasniqi", email: "arta@example.com", role: "STAFF", is_active: true, department_id: null }
const meetingId = "11111111-1111-4111-8111-111111111111"
const noteId = "33333333-3333-4333-8333-333333333333"
const archiveId = "44444444-4444-4444-8444-444444444444"
const note = { id: noteId, kind: "PX_NOTE", title: "Shënimet e regjistrimit", content: "Vendimi i ruajtur në Desktop.",
  status: "OPEN", note_id: noteId, created_at: "2026-10-28T09:30:00Z" }
const archive = { ...note, id: archiveId, note_id: archiveId, title: "Shënimi i vjetër", content: "Vendimi historik.", status: "CLOSED", shared_to_px: false }
const meeting = { id: meetingId, source: "desktop", title: "Takimi me ekipin", started_at: note.created_at,
  status: "SAVED", group: "OTHER", partial: false, open_count: 0 }

async function shell(page: Page, { failShare = false } = {}) {
  let shared = false
  const writes: string[] = []
  await page.addInitScript(({ user }) => {
    localStorage.setItem("primex_access_token", "test-only-browser-token")
    localStorage.setItem("primex_user", JSON.stringify(user))
  }, { user })
  await page.route("http://127.0.0.1:8012/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname
    if (path === "/api/auth/me") return route.fulfill({ json: user })
    if (path === "/api/mira/status") return route.fulfill({ json: { enabled: false, live: null } })
    if (path === "/api/mira/meeting-catalog") {
      const group = url.searchParams.get("group")
      const items = group && group !== meeting.group ? [] : [meeting]
      return route.fulfill({ json: { items, total: items.length, follow_up: [], has_unlinked_notes: true } })
    }
    if (path === `/api/mira/meeting-catalog/desktop/${meetingId}`) return route.fulfill({ json: {
      ...meeting, host_ids: [], notes: [{ ...note, shared_to_px: shared }], transcript_allowed: false,
    } })
    if (path === `/api/mira/notes/${noteId}/meeting`) return route.fulfill({ json: { id: meetingId, source: "desktop" } })
    if (path === "/api/mira/unlinked-notes") {
      const offset = Number(url.searchParams.get("offset"))
      return route.fulfill({ json: { notes: offset ? [archive] : [{ ...archive, title: "Shënim më i ri" }], has_more: !offset } })
    }
    if (path.endsWith("/show-in-px-notes")) {
      writes.push(request.method() + " " + path)
      if (failShare) return route.fulfill({ status: 500, json: { detail: "Ruajtja dështoi." } })
      shared = true
      return route.fulfill({ json: { note_id: noteId, shared_to_px: true } })
    }
    return route.fulfill({ json: path.includes("count") ? { count: 0 } : [] })
  })
  return writes
}

test("the meeting list opens Desktop notes and sharing persists", async ({ page }) => {
  const writes = await shell(page)
  await page.goto("/mira?tab=shenimet")
  await page.getByRole("button", { name: "1H", exact: true }).click()
  await expect(page.getByText("Nuk ka takime për të shfaqur.")).toBeVisible()
  await page.getByRole("button", { name: "Të tjera", exact: true }).click()
  await page.getByRole("link", { name: /Takimi me ekipin.*Mira Desktop/ }).click()
  await expect(page.getByText(note.content)).toBeVisible()
  await expect(page.getByRole("link", { name: "Transkripti", exact: true })).toHaveCount(0)
  await page.getByRole("button", { name: "Shfaq në PX Notes" }).click()
  await expect(page.getByRole("link", { name: "Shfaqet në PX Notes" })).toBeVisible()
  expect(writes).toEqual([`POST /api/mira/notes/PX_NOTE/${noteId}/show-in-px-notes`])
  await page.reload()
  await expect(page.getByRole("link", { name: "Shfaqet në PX Notes" })).toBeVisible()
})

test("meeting dates appear once per row in an aligned column", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await shell(page)
  const discord = { ...meeting, id: "discord-meeting", source: "discord", group: "1H",
    title: "1H 820/10/11/1150/1420/16 · 24.11.2026 08:08", started_at: "2026-11-24T07:08:00Z" }
  const agent = { ...discord, id: "agent-meeting", recorder: "ai_agent", group: "AI_AGENT",
    title: "Mira Zhvillim", created_task_count: 1, created_note_count: 2 }
  await page.route("**/api/mira/meeting-catalog?*", route => route.fulfill({
    json: { items: [discord, agent, meeting], total: 3, follow_up: [] },
  }))
  await page.route(`**/api/mira/meeting-catalog/discord/${agent.id}`, route => route.fulfill({
    json: { ...agent, host_ids: [], notes: [], transcript: [] },
  }))
  await page.goto("/mira?tab=takimet")
  const discordRow = page.getByRole("link", { name: /^1H 820/ })
  const desktopRow = page.getByRole("link", { name: /^Takimi me ekipin/ })
  await expect(discordRow.locator("time")).toHaveText("24.11.2026 08:08")
  await expect(discordRow.getByText("1H 820/10/11/1150/1420/16", { exact: true })).toBeVisible()
  await expect(discordRow.getByText("24.11.2026 08:08", { exact: false })).toHaveCount(1)
  await expect(desktopRow.locator("time")).toHaveText("28.10.2026 10:30")
  expect((await discordRow.locator("time").boundingBox())?.x).toBe((await desktopRow.locator("time").boundingBox())?.x)
  await expect(page.getByRole("button", { name: "Zhvillim", exact: true })).toBeVisible()
  const agentRow = page.getByRole("link", { name: /^Zhvillim/ })
  await expect(discordRow.getByText("1H", { exact: true })).toHaveCount(0)
  await expect(discordRow.getByText("Discord", { exact: true })).toHaveCount(0)
  await expect(agentRow.getByText("Zhvillim", { exact: true })).toHaveCount(1)
  await expect(agentRow.getByText("Discord", { exact: true })).toHaveCount(0)
  await expect(discordRow.locator("img")).toHaveAttribute("src", /mira-avatar\.png/)
  await expect(agentRow.locator("img")).toHaveAttribute("src", /mira-ai-agent-avatar\.png/)
  await expect(agentRow.getByText("1 detyrë e krijuar")).toBeVisible()
  await expect(agentRow.getByText("2 shënime të krijuara")).toBeVisible()
  await agentRow.click()
  await expect(page.getByRole("heading", { name: "Zhvillim", exact: true })).toBeVisible()
})

test("a PX Notes link opens the exact note and failed sharing keeps the action available", async ({ page }) => {
  await shell(page, { failShare: true })
  await page.goto(`/mira?tab=takimet&note=${noteId}`)
  await expect(page).toHaveURL(new RegExp(`meeting=${meetingId}&source=desktop&view=full#note-${noteId}`))
  await expect(page.locator(`#note-${noteId}`)).toContainText(note.content)
  await page.getByRole("button", { name: "Shfaq në PX Notes" }).click()
  await expect(page.getByText("Ruajtja dështoi.")).toBeVisible()
  await expect(page.getByRole("button", { name: "Shfaq në PX Notes" })).toBeEnabled()
})

test("historical notes with no linked meeting remain available on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await shell(page)
  await page.goto("/mira")
  await page.getByRole("button", { name: "Close sidebar" }).click()
  await page.getByRole("link", { name: "Shënime pa takim të lidhur" }).click()
  await page.getByRole("button", { name: "Tjetër" }).click()
  await expect(page.getByRole("heading", { name: archive.title })).toBeVisible()
  await expect(page.getByText("E mbyllur")).toBeVisible()
  await expect.poll(() => page.locator("main").evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
})
