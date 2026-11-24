import { test, expect, type Page } from "@playwright/test"
import { execFileSync } from "node:child_process"
import path from "node:path"

const backend = path.resolve(__dirname, "../../../backend")

test("PX Notes Emails opens the original email with the disclosure button", async ({ page }) => {
  const user = { id: "note-test-admin", full_name: "Notes admin", email: "admin@example.test", role: "ADMIN", is_active: true }
  const email = { id: "px-mail", title: "EM IT: 10:00", subject: "Porosia", sender: "Drita <drita@example.test>" }
  const timestamp = new Date().toISOString()
  const note = { status: "OPEN", note_type: "GA", created_at: timestamp, start_date: timestamp, updated_at: timestamp, attachments: [] }
  let requests = 0
  await page.addInitScript(account => {
    localStorage.setItem("primex_access_token", "test-only-browser-token")
    localStorage.setItem("primex_user", JSON.stringify(account))
  }, user)
  await page.route("**/api/**", route => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === "/api/auth/me") return route.fulfill({ json: user })
    if (pathname === "/api/marker-comments") return route.fulfill({ json: { items: [] } })
    if (pathname === "/api/ga-notes") return route.fulfill({ json: [
      { ...note, id: email.id, content: "Saved original email", knowledge_type: "IT_MAIL", email_preview: email },
      { ...note, id: "manual-mail", content: "EM GA: 09:50 STD-STAUD\nKontrollo dokumentet." },
      { ...note, id: "ordinary", content: "Ordinary PX note" },
    ] })
    if (pathname === "/api/ga-notes/px-mail/email") {
      requests++
      return route.fulfill({ json: { ...email, body: "Complete source email" } })
    }
    return route.fulfill({ json: [] })
  })

  await page.goto("/ga-ka-notes")
  await expect(page.getByText("Ordinary PX note", { exact: true })).toBeVisible()
  await page.getByRole("combobox", { name: "Content" }).click()
  await page.getByRole("option", { name: "Emails", exact: true }).click()
  await expect(page.getByText("Ordinary PX note", { exact: true })).toBeHidden()
  const content = page.locator("#ga-note-content-px-mail")
  await expect(content).toContainText(email.title)
  await expect(content.getByText(email.subject, { exact: false })).toBeHidden()
  await expect(content.getByText(email.sender, { exact: false })).toBeHidden()
  await expect(page.getByText("Saved original email", { exact: true })).toBeHidden()
  expect(requests).toBe(0)
  await content.getByLabel("Hap emailin").click()
  await expect(content.getByText(email.subject, { exact: false })).toBeVisible()
  await expect(content.getByText(email.sender, { exact: false })).toBeVisible()
  await expect(content.getByText("Complete source email")).toBeVisible()
  expect(requests).toBe(1)
  await content.getByLabel("Mbyll emailin").click()
  await expect(content.getByText("Complete source email")).toBeHidden()
  const manual = page.locator("#ga-note-content-manual-mail")
  await expect(manual.getByText("EM GA: 08:00 STD-STAUD")).toBeVisible()
  await expect(manual.getByText("Kontrollo dokumentet.")).toBeHidden()
  await manual.getByLabel("Hap emailin").click()
  await expect(manual.getByText("Kontrollo dokumentet.")).toBeVisible()
})

test("M1 opens a previously imported email only on demand", async ({ page }) => {
  const user = { id: "note-test-admin", full_name: "Report admin", email: "admin@example.test", role: "ADMIN", is_active: true }
  const point = "(GA) NOTES TE REJA ( NOT DISSCUSED)?"
  const recipients = { to: [], cc: [], bcc: [] }
  const email = { id: "old-import", title: "EM IT: 10:00", subject: "Porosia", sender: "Drita <drita@example.test>" }
  let emailRequests = 0
  await page.addInitScript(account => {
    localStorage.setItem("primex_access_token", "test-only-browser-token")
    localStorage.setItem("primex_user", JSON.stringify(account))
  }, user)
  await page.route("**/api/**", route => {
    const path = new URL(route.request().url()).pathname
    if (path === "/api/auth/me") return route.fulfill({ json: user })
    if (path.endsWith("/morning-report/settings")) return route.fulfill({ json: {
      is_active: true, timezone: "Europe/Tirane", weekdays: [1, 2, 3, 4, 5], recipients,
    } })
    if (path.endsWith("/morning-report")) return route.fulfill({ json: {
      id: "old-report", status: "DRAFT", report_date: "2026-11-24", subject: "Morning report", recipients,
      sections: [{ section_key: point, title: point, body: [
        "NOTES:", "+----+------+----------------------------+------+-------+",
        "| NR | DISK | NOTE                       | FROM | TIME  |",
        "+----+------+----------------------------+------+-------+",
        "| 1  | NO   | Saved original email text  | -    | 10:00 |",
        "+----+------+----------------------------+------+-------+",
        "| 2  | NO   | EM GA: 09:50 STD-STAUD Kontrollo dokumentet. | GA | 10:04 |",
        "+----+------+----------------------------+------+-------+",
      ].join("\n") }],
      note_emails: { "1": email },
      note_email_headings: { "2": { original: "EM GA: 09:50 STD-STAUD", title: "EM GA: 08:00 STD-STAUD" } },
    } })
    if (path.endsWith("/ga-notes/old-import/email")) {
      emailRequests++
      return route.fulfill({ json: { ...email, body: "Full original email text" } })
    }
    return route.fulfill({ json: [] })
  })

  await page.goto("/morning-report")
  const row = page.getByRole("row").filter({ hasText: email.title })
  await expect(row.getByText(email.subject, { exact: false })).toBeHidden()
  await expect(row.getByText(email.sender, { exact: false })).toBeHidden()
  await expect(page.getByText("Saved original email text")).toBeHidden()
  expect(emailRequests).toBe(0)
  await row.locator("summary").click()
  await expect(row.getByText("Full original email text")).toBeVisible()
  expect(emailRequests).toBe(1)
  await row.locator("summary").press("Enter")
  await expect(row.getByText("Full original email text")).toBeHidden()
  const manual = page.getByRole("row").filter({ hasText: "EM GA: 08:00 STD-STAUD" })
  await expect(manual.getByText("Kontrollo dokumentet.")).toBeHidden()
  await manual.getByLabel("Hap emailin").click()
  await expect(manual.getByText("Kontrollo dokumentet.")).toBeVisible()
})

test("M1 inbox shows the subject and expands only the selected email", async ({ page }) => {
  const user = { id: "mail-test-admin", full_name: "Report admin", email: "admin@example.test", role: "ADMIN", is_active: true }
  const recipients = { to: [], cc: [], bcc: [] }
  const emailSection = "(GA) DET NGA EMAILS TE REJA"
  const sources = [
    { source: "info-px", title: "EM INFO PX" },
    { source: "it", title: "EM IT" },
    { source: "hf", title: "EM HF" },
    { source: "px-eu", title: "EM PX EU" },
  ]
  await page.addInitScript(account => {
    localStorage.setItem("primex_access_token", "test-only-browser-token")
    localStorage.setItem("primex_user", JSON.stringify(account))
  }, user)
  await page.route("**/api/**", route => {
    const url = new URL(route.request().url())
    if (url.pathname === "/api/auth/me") return route.fulfill({ json: user })
    if (url.pathname.endsWith("/morning-report/settings")) return route.fulfill({ json: {
      is_active: true, timezone: "Europe/Tirane", weekdays: [1, 2, 3, 4, 5], recipients,
    } })
    if (url.pathname.endsWith("/morning-report")) return route.fulfill({ json: {
      id: "mail-draft", status: "DRAFT", report_date: "2026-11-24", subject: "Morning report", recipients,
      sections: [{ section_key: emailSection, title: emailSection, body: "" }],
    } })
    if (url.pathname.endsWith("/microsoft-mail/sync")) {
      const source = url.searchParams.get("source")
      return route.fulfill({ json: {
        configured: true, connected: true, messages: [{
          id: "message", subject: `Subject ${source}`, sender: "Sender <sender@example.test>",
          received_at: "09:08", body: `Full email ${source}\n${"Second line\n".repeat(100)}`,
        }],
      } })
    }
    return route.fulfill({ json: [] })
  })

  await page.goto("/morning-report")
  for (const { source, title } of sources) {
    const row = page.getByRole("row").filter({ hasText: `Subject ${source}` })
    await expect(row.getByText(`${title}: 09:08`, { exact: true })).toBeVisible()
    await expect(row.getByText("Sender <sender@example.test>", { exact: true })).toBeVisible()
    const fullEmail = page.getByText(`Full email ${source}`)
    await expect(fullEmail).toBeHidden()
    await row.getByRole("button", { name: `Hap emailin: Subject ${source}` }).press("Enter")
    await expect(fullEmail).toBeVisible()
    await expect.poll(() => fullEmail.evaluate(element => element.scrollHeight > element.clientHeight && getComputedStyle(element).overflowY === "auto")).toBe(true)
    const collapse = row.getByRole("button", { name: `Mbyll emailin: Subject ${source}` })
    await expect(collapse).toHaveAttribute("aria-expanded", "true")
    await collapse.click()
    await expect(fullEmail).toBeHidden()
  }
})

test("M1 preserves edits and refreshed symbol tables when saving report details", async ({ page }) => {
  const user = { id: "m1-test-admin", full_name: "Report admin", email: "admin@example.test", role: "ADMIN", is_active: true }
  const recipients = { to: ["admin@example.test"], cc: [], bcc: [] }
  const physicalSection = { section_key: "FIZIKISHT ME GA?", title: "FIZIKISHT ME GA?", body: "FG:GA DEVICES" }
  const draft = {
    id: "draft", status: "SENT", report_date: "2026-11-23", subject: "Morning report", recipients,
    sections: [{ title: "First report point", body: "Report content" }, physicalSection],
  }
  await page.addInitScript((account) => {
    localStorage.setItem("primex_access_token", "test-only-browser-token")
    localStorage.setItem("primex_user", JSON.stringify(account))
  }, user)
  await page.route("**/api/**", (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === "/api/auth/me") return route.fulfill({ json: user })
    if (pathname.endsWith("/morning-report/settings")) return route.fulfill({ json: {
      is_active: true, timezone: "Europe/Tirane", weekdays: [1, 2, 3, 4, 5], recipients,
    } })
    if (pathname.endsWith("/morning-report")) return route.fulfill({ json: draft })
    if (pathname.endsWith("/morning-report/draft") && route.request().method() === "PATCH") return route.fulfill({ json: {
      ...draft, subject: "Edited subject",
      sections: [draft.sections[0], { ...physicalSection, body: "(Asnje detyre)" }],
    } })
    return route.fulfill({ json: [] })
  })

  await page.goto("/morning-report")
  const toggle = page.locator("summary").filter({ hasText: "Menaxhimi i raportit dhe email-it" })
  const point = page.getByText("1. First report point", { exact: true })
  const symbols = page.getByRole("button", { name: "Simbolet e detyrave" })
  const status = page.getByText("Sent to", { exact: true })
  await expect(point).toBeVisible()
  await expect(symbols).toBeHidden()
  await expect(status).toBeHidden()
  await expect(toggle.getByText("+", { exact: true })).toBeVisible()

  await toggle.press("Enter")
  await expect(toggle.getByText("−", { exact: true })).toBeVisible()
  await expect(symbols).toBeVisible()
  await expect(page.getByText("Automatic Send", { exact: true })).toBeVisible()
  await expect(status).toBeVisible()
  const subject = page.getByPlaceholder("Generate a draft first")
  await subject.fill("Edited subject")

  await toggle.click()
  await expect(point).toBeVisible()
  await expect(status).toBeHidden()
  await toggle.click()
  await expect(subject).toHaveValue("Edited subject")

  const physicalTask = page.getByText("FG: GA DEVICES", { exact: true })
  await expect(physicalTask).toBeVisible()
  const saved = page.waitForResponse(response => response.url().endsWith("/morning-report/draft") && response.request().method() === "PATCH")
  await page.getByRole("button", { name: "Save", exact: true }).click()
  expect((await saved).ok()).toBe(true)
  await expect(page.getByText("Draft saved", { exact: true })).toBeVisible()
  await expect(physicalTask).toBeVisible()
})

for (const [pagePath, report] of [["morning-report", "M1"], ["after-break-report", "M2"]] as const) {
  test(`${report} shows Discord comment time and opens its files`, async ({ page }) => {
    const user = { id: "22222222-2222-4222-8222-222222222222", full_name: "Test owner", email: "owner@example.test", role: "STAFF", is_active: true }
    const day = "2026-11-23"
    const url = "https://cdn.discordapp.com/attachments/2/4/screenshot.png?ex=test"
    let previewConfigured = true
    await page.addInitScript(({ user }) => {
      localStorage.setItem("primex_access_token", "test-only-browser-token")
      localStorage.setItem("primex_user", JSON.stringify(user))
    }, { user })
    await page.route(url, (route) => route.fulfill({
      contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect width="16" height="16" fill="blue"/></svg>',
    }))
    await page.route("**/api/**", async (route) => {
      const request = new URL(route.request().url())
      if (request.pathname === "/api/auth/me") return route.fulfill({ json: user })
      if (request.pathname.includes("marker-comments")) return route.fulfill({ json: { items: [], unread_count: 0 } })
      if (request.pathname.endsWith("/discord/ga-replies/attachments")) {
        expect(Object.fromEntries(request.searchParams)).toEqual({ report, report_date: day, message_id: "3" })
        expect(route.request().headers().authorization).toBe("Bearer test-only-browser-token")
        if (!previewConfigured) return route.fulfill({ status: 424, json: {
          detail: { code: "discord_preview_not_configured", message: "Ky server nuk ka të konfiguruar botin e Discord për pamjen paraprake." },
        } })
        return route.fulfill({ json: [{ url, filename: "screenshot.png", image: true }] })
      }
      if (request.pathname.endsWith(`/${pagePath}`)) return route.fulfill({ json: {
        id: "draft", status: "SENT", report_date: day, subject: "GA replies",
        recipients: { to: [], cc: [], bcc: [] },
        sections: [{
          title: "(GA) A KA REPLY NGA GA TEK DETYRAT NGA STAFI PER GA?",
          body: [
            "Përgjigjet dhe komentet e GA:",
            "| NR | PËR KË | MESAZHI ORIGJINAL | PËRGJIGJJA E GA | SKEDARËT | DATA / ORA |",
            "| 1 | | | Shiko detyrat | 1 | 20.11.2026 22:49 |",
            "| | | | | https://discord.com/channels/1/2/3 | |",
            "| 2 | | | Koment tjetër | | 23.11.2026 08:12 |",
          ].join("\n"),
        }],
      } })
      return route.fulfill({ json: [] })
    })
    await page.goto(`/${pagePath}`)
    const mediaRow = page.getByRole("row").filter({ hasText: "Shiko detyrat" })
    await expect(mediaRow.getByRole("cell").last()).toHaveText("20.11.2026 22:49")
    await expect(page.getByRole("row").filter({ hasText: "Koment tjetër" }).locator("details")).toHaveCount(0)
    const thumbnail = mediaRow.getByRole("button", { name: "screenshot.png" })
    await expect(thumbnail).toHaveCount(0)
    await mediaRow.getByText("1 skedar").click()
    await expect(thumbnail.locator("img")).toHaveAttribute("src", url)
    await thumbnail.click()
    const preview = page.getByRole("dialog", { name: "screenshot.png" })
    await expect(preview.getByRole("img", { name: "screenshot.png" })).toBeVisible()
    await preview.getByRole("button", { name: "Close" }).click()
    await expect(mediaRow.getByRole("link", { name: "Hap në Discord" })).toHaveAttribute("href", "https://discord.com/channels/1/2/3")
    previewConfigured = false
    const summary = mediaRow.getByText("1 skedar")
    await summary.click()
    await expect(mediaRow.locator("details")).not.toHaveAttribute("open")
    await summary.click()
    await expect(mediaRow.getByRole("status")).toHaveText("Ky server nuk ka të konfiguruar botin e Discord për pamjen paraprake.")
  })
}

function pxNoteReportFixtures() {
  const python = process.env.ONE_H_FILTER_PYTHON || path.join(backend, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python")
  return JSON.parse(execFileSync(python, ["-c", `
import json
from datetime import date
from app.services import after_break_report as m2, morning_report as m1
from app.services.primeflow_report import ReportUndiscussedNote, render_html
from app.services.tomorrow_closing_sections import ClosingSection, ClosingTable, ClosingTableRow
from app.services.tomorrow_print_report import _closing_sections_html
from tests.test_one_h_report_strike_counts import fresh_document
day = date(2026, 11, 23)
values = [["1", "NO", "Note with files", "GA", "09:15"], ["2", "NO", "Note without files", "GA", "09:16"],
          ["3", "NO", "EM GA: 09:50 STD-STAUD Kontrollo dokumentet.", "GA", "09:50"]]
body = m1._notes_section(values)
sections = {"morning-report": [{"title": m1.SECTION_TITLES[3], "body": body}],
            "after-break-report": [{"title": m2.SECTION_TITLES[9], "body": body}]}
document, _, _ = fresh_document()
document.undiscussed_notes = [ReportUndiscussedNote(content=row[2]) for row in values]
closing = [ClosingSection("NOTES PA DISK", [ClosingTable("NOTES", ["NR", "DISK", "NOTE", "FROM", "TIME"],
          [ClosingTableRow(values=row) for row in values], "notes")])]
print(json.dumps({"sections": sections,
  "morning-report": m1.render_html("M1", day, sections["morning-report"]),
  "after-break-report": m2.render_html("M2", day, sections["after-break-report"]),
  "tomorrow-print-report": _closing_sections_html(closing),
  "1h-reports": render_html(document)}))
`], { cwd: backend, encoding: "utf8", env: { ...process.env, PYTHONIOENCODING: "utf-8" } }))
}

for (const reportName of ["morning-report", "after-break-report", "tomorrow-print-report", "1h-reports"] as const) {
  test(`${reportName} opens the files for the matching PX Note`, async ({ page }) => {
    const fixture = pxNoteReportFixtures()
    const reportDay = "2026-11-23"
    const user = { id: "22222222-2222-4222-8222-222222222222", full_name: "Test owner", email: "owner@example.com", role: reportName === "morning-report" ? "ADMIN" : "STAFF", is_active: true }
    const noteAttachments = {
      "1": [{ id: "file-one", original_filename: "First.docx" }, { id: "file-two", original_filename: "Second.xlsx" }],
    }
    await page.addInitScript(({ user }) => {
      localStorage.setItem("primex_access_token", "test-only-browser-token")
      localStorage.setItem("primex_user", JSON.stringify(user))
    }, { user })
    await page.route("**/api/**", async (route) => {
      const pathname = new URL(route.request().url()).pathname
      if (pathname === "/api/auth/me") return route.fulfill({ json: user })
      if (pathname.includes("marker-comments")) return route.fulfill({ json: { items: [], unread_count: 0 } })
      if (pathname.match(/\/attachments\/file-(one|two)\/preview$/)) {
        expect(route.request().headers().authorization).toBe("Bearer test-only-browser-token")
        return route.fulfill({ contentType: "text/html", body: `<p>${pathname.includes("file-two") ? "Spreadsheet" : "Document"} content</p>` })
      }
      if (pathname.endsWith("/attachments/file-two")) {
        return route.fulfill({ contentType: "application/octet-stream", body: "Test download" })
      }
      if (pathname.endsWith(`/${reportName}/settings`)) return route.fulfill({ json: {
        is_active: true, timezone: "Europe/Tirane", weekdays: [1, 2, 3, 4, 5], recipients: { to: [], cc: [], bcc: [] },
      } })
      const html = fixture[reportName]
      const payload = { html, plain_text: "", note_attachments: noteAttachments,
        note_email_headings: { "3": { original: "EM GA: 09:50 STD-STAUD", title: "EM GA: 08:00 STD-STAUD" } },
      }
      if ((pathname.endsWith(`/${reportName}`) || pathname.endsWith(`/${reportName}/draft`)) && fixture.sections[reportName]) {
        return route.fulfill({ json: {
          ...payload, id: "draft", status: "DRAFT", report_date: reportDay, subject: "Notes report",
          recipients: { to: [], cc: [], bcc: [] }, sections: fixture.sections[reportName],
        } })
      }
      if (pathname.endsWith("/draft/preview")) return route.fulfill({ json: payload })
      if (pathname.includes("/tomorrow-print-report/") && (pathname.endsWith("/snapshot") || pathname.endsWith("/generate"))) {
        return route.fulfill({ json: { ...payload, snapshot_id: "sample", subject: "SHTYPI", report_date: reportDay, target_date: "2026-11-24" } })
      }
      if (pathname.endsWith("/primeflow-1h-reports/preview")) {
        return route.fulfill({ json: {
          ...payload, document: { subject: "1H", generated_at: reportDay, recipients: { to: [] } },
          notes_html: html.replace("</body>", "<p>Notes-only view</p></body>"), note_count: 2, task_count: 1,
        } })
      }
      return route.fulfill({ json: [] })
    })
    await page.goto(reportName === "1h-reports" ? "/admin/1h-reports" : `/${reportName}`)
    const fullReport = page.frameLocator('iframe[title="Email preview"]')
    if (reportName === "1h-reports") {
      await page.getByRole("button", { name: "Generate report", exact: true }).click()
      await expect(fullReport.getByRole("button", { name: "View (2)", exact: true })).toHaveCount(1)
      await page.getByRole("button", { name: "Vetëm Notes", exact: true }).click()
      await expect(fullReport.getByText("Notes-only view")).toBeVisible()
    }
    const notes = reportName === "tomorrow-print-report" ? page.frameLocator('iframe[title$="generated email"]')
      : reportName === "1h-reports" ? fullReport : page
    const view = notes.getByRole("button", { name: "View (2)", exact: true })
    await expect(view).toHaveCount(1)
    const emailNote = notes.locator("tr").filter({ hasText: "EM GA: 08:00 STD-STAUD" }).last()
    await expect(emailNote.getByText("Kontrollo dokumentet.")).toBeHidden()
    await emailNote.locator("summary").click()
    await expect(emailNote.getByText("Kontrollo dokumentet.")).toBeVisible()
    const fileRow = notes.locator("tr").filter({ hasText: "Note with files" }).last()
    const emptyRow = notes.locator("tr").filter({ hasText: "Note without files" }).last()
    await expect(fileRow.getByRole("button", { name: "View (2)" })).toBeVisible()
    await expect(emptyRow.getByRole("button")).toHaveCount(0)
    await view.click()
    const dialog = page.getByRole("dialog")
    await expect(dialog.frameLocator('iframe[title="First.docx"]').getByText("Document content")).toBeVisible()
    await dialog.getByRole("combobox", { name: "Bashkëngjitjet" }).selectOption("file-two")
    await expect(dialog.frameLocator('iframe[title="Second.xlsx"]').getByText("Spreadsheet content")).toBeVisible()
    const download = page.waitForEvent("download")
    await dialog.getByRole("button", { name: "Download" }).click()
    expect((await download).suggestedFilename()).toBe("Second.xlsx")
    if (reportName === "morning-report" || reportName === "after-break-report") {
      await dialog.getByRole("button", { name: "Close" }).click()
      if (reportName === "morning-report") await page.locator("summary").filter({ hasText: "Menaxhimi i raportit dhe email-it" }).click()
      await page.getByRole("button", { name: "Preview", exact: true }).click()
      const previewFrame = page.frameLocator('iframe[title$=" preview"]')
      const previewNote = previewFrame.locator("tr").filter({ hasText: "EM GA: 08:00 STD-STAUD" }).last()
      await previewNote.locator("summary").click()
      await expect(previewNote.getByText("Kontrollo dokumentet.")).toBeVisible()
      const previewButton = previewFrame.getByRole("button", { name: "View (2)", exact: true })
      await expect(previewButton).toBeVisible()
      await previewButton.click()
      await expect(page.getByRole("dialog", { name: "First.docx" }).frameLocator('iframe[title="First.docx"]')
        .getByText("Document content")).toBeVisible()
    }
  })
}

function printFixture(legacy: boolean) {
  const python = process.env.ONE_H_FILTER_PYTHON || path.join(backend, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python")
  return JSON.parse(execFileSync(python, ["-c", `
import json, re, uuid
from datetime import date
from app.services.tomorrow_print_report import _html_table
ids=[str(uuid.uuid4()) for _ in range(8)]
items=[dict(task_id=value,title='EF: Task '+str(index),start_date='2026-10-23',due_date='2026-10-26',status='DONE' if index==6 else 'TODO') for index,value in enumerate(ids)]
table=_html_table([('1H 10:00',items[:7],False),('P: GA',items[7:],True)],report_date=date(2026,10,23))
${legacy ? "table=re.sub(r' data-task-status=\"[^\"]*\"', '', table)" : ""}
print(json.dumps(dict(html='<html><body>'+table+'</body></html>',done_id=ids[6],strike_id=ids[0],one_h_strikes=dict(report_date='2026-10-23',captured_at='2026-10-23T11:00:00Z',active_slot='11:00',active_interval=dict(start='10:00',end='11:00'),intervals={},tasks={value:{'11:00':2 if index==0 else 0} for index,value in enumerate(ids)}))))
`], { cwd: backend, encoding: "utf8", env: { ...process.env, PYTHONIOENCODING: "utf-8" } }))
}

async function openPrintReport(page: Page, legacy = false, today = true) {
  const fixture = printFixture(legacy)
  const user = { id: "22222222-2222-4222-8222-222222222222", full_name: "Test owner", email: "owner@example.com", role: "STAFF", is_active: true }
  await page.addInitScript(({ user }) => {
    localStorage.setItem("primex_access_token", "test-only-browser-token")
    localStorage.setItem("primex_user", JSON.stringify(user))
  }, { user })
  await page.route("**/api/**", async route => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname === "/api/auth/me") return route.fulfill({ json: user })
    if (pathname.includes("marker-comments")) return route.fulfill({ json: { items: [], unread_count: 0 } })
    if (pathname.endsWith("/freeze-status")) return route.fulfill({ json: { report_date: "2026-10-23", is_frozen: true, freeze_ready: true } })
    if (pathname.endsWith("/generate") || pathname.endsWith("/snapshot")) return route.fulfill({ json: {
      ...fixture, subject: "SHTYPI test", report_date: "2026-10-23", target_date: "2026-10-23", snapshot_id: "test", generated_at: "2026-10-23T11:00:00Z", is_frozen: true,
    } })
    return route.fulfill({ json: [] })
  })
  await page.goto(today ? "/today-print-report" : "/tomorrow-print-report")
  const frame = page.frameLocator('iframe[title$="generated email"]')
  await expect(frame.locator('td[data-task-id]:visible')).toHaveCount(8)
  return { frame, fixture }
}

function report(slot = "11:00", empty = false, embedded = false, shared = false, done = false) {
  const python = process.env.ONE_H_FILTER_PYTHON || path.join(backend, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python")
  return execFileSync(python, ["-c", `
from tests.test_one_h_report_strike_counts import fresh_document
from app.services.primeflow_report import render_html
import asyncio, uuid
from unittest.mock import AsyncMock, patch
from app.services.tomorrow_print_report import _html_table
from app.services.today_print_strikes import render_embedded_print_strikes
d,shared_id,_=fresh_document('${slot}')
d.board_reminders=[]
${slot === "14:10" ? "d.sections[-1].employees=d.sections[0].employees" : ""}
${empty ? "for s in d.sections:\n for e in s.employees:\n  for t in e.tasks:t.strike_count=0" : ""}
${done ? "d.sections[0].employees[0].tasks[0].status='DONE'" : ""}
supplement='<p>Supplement</p>'
${embedded ? `
ids=[str(uuid.uuid4()) for _ in range(8)]
${shared ? "ids[6]=str(shared_id)" : ""}
items=[dict(task_id=value,title='SHTYPI task '+str(index),start_date='2026-10-23',due_date='2026-10-26',status='DONE' if ${done ? 'True' : 'False'} and index==6 else 'TODO') for index,value in enumerate(ids)]
table=_html_table([('1H 10:00',items[:7],False),('P: GA',items[7:],True)],report_date=d.report_date)
summary={'active_interval':{'start':'10:00','end':'11:00'},'tasks':{value:{'${slot}':${empty ? "0" : "2 if index==6 else 0"}} for index,value in enumerate(ids)}}
with patch('app.services.today_print_strikes.task_strike_summary',new=AsyncMock(return_value=summary)):
 supplement=asyncio.run(render_embedded_print_strikes(AsyncMock(),table,d.report_date,'${slot}'))
` : ""}
print(render_html(d,pre_sections_html=supplement))
`], { cwd: backend, encoding: "utf8", env: { ...process.env, PYTHONIOENCODING: "utf-8" } })
}

async function openReport(page: Page, role: "ADMIN" | "STAFF", slot = "11:00", empty = false, embedded = false, shared = false, done = false, notes = 0) {
  const html = report(slot, empty, embedded, shared, done)
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
      document: { subject: `Report ${slot}`, generated_at: "2026-10-23T11:00:00Z", recipients: { to: ["preview@example.com"] },
        strike_interval: slot === "10:00" ? "08:00–10:00" : slot === "14:10" ? "11:50–14:20" : "10:00–11:00" },
      html, task_count: slot === "10:00" ? 3 : slot === "14:10" ? 4 : 2,
      notes_html: `<html><body><h2>NOTA PA DISKUTUARA</h2><table data-undiscussed-notes-table="true"><tr><th>NOTE</th></tr>${Array.from({ length: notes }, (_, i) => `<tr><td>PX note ${i + 1}</td></tr>`).join("")}</table></body></html>`,
      note_count: notes,
    } })
    return route.fulfill({ json: pathname.includes("count") ? { count: 0 } : [] })
  })
  await page.goto("/admin/1h-reports")
  if (role === "ADMIN") await page.getByRole("tab", { name: "Reports", exact: true }).click()
  if (slot !== "10:00") {
    await page.getByRole("main").getByRole("combobox").click()
    await page.getByRole("option", { name: slot, exact: true }).click()
  }
  await page.getByRole("button", { name: role === "ADMIN" ? "Preview fresh report" : "Generate report", exact: true }).click()
  const frame = page.frameLocator('iframe[title="Email preview"]')
  await expect(frame.locator('[data-report-task="true"]').first()).toBeVisible()
  return frame
}

for (const role of ["ADMIN", "STAFF"] as const) {
  test(`${role}: notes filter persists and downloads notes without affecting Done or full preview`, async ({ page }, testInfo) => {
    const frame = await openReport(page, role, "11:00", false, false, false, true, 2)
    const toolbar = page.getByTestId("one-h-strikes-toolbar")
    const notes = toolbar.getByRole("button", { name: "Vetëm Notes", exact: true })
    await notes.click()
    await expect(notes).toHaveAttribute("aria-pressed", "true")
    await expect(frame.getByText("PX note 1", { exact: true })).toBeVisible()
    await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(0)
    await expect(toolbar.getByRole("status")).toHaveText("Shfaqen 2 Notes")
    await expect(toolbar.getByTestId("one-h-toolbar-strike-total")).toHaveCount(0)
    await page.screenshot({ path: testInfo.outputPath("notes-filter.png"), fullPage: true })
    for (const [label, format] of [["Word", "docx"], ["PNG", "png"], ["Text", "txt"]]) {
      const request = page.waitForRequest(req => req.url().endsWith("/preview") && req.postDataJSON()?.format === format)
      const download = page.waitForEvent("download")
      await page.getByRole("button", { name: label, exact: true }).click()
      expect((await request).postDataJSON().notes_only).toBe(true)
      expect((await download).suggestedFilename()).toContain(`_Notes.${format}`)
    }
    await page.getByRole("button", { name: role === "ADMIN" ? "Preview fresh report" : "Generate report", exact: true }).click()
    await expect(notes).toHaveAttribute("aria-pressed", "true")
    await expect(frame.getByText("PX note 2", { exact: true })).toBeVisible()
    await toolbar.getByRole("button", { name: "Vetëm Done", exact: true }).click()
    await expect(notes).toHaveAttribute("aria-pressed", "false")
    await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(1)
    await notes.click()
    await notes.click()
    await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(2)
    await expect(toolbar.getByRole("status")).toHaveText("Shfaqen 2 nga 2 detyra")
  })
}

test("notes filter shows its own empty state and restores the full report", async ({ page }) => {
  const frame = await openReport(page, "STAFF")
  const notes = page.getByRole("button", { name: "Vetëm Notes", exact: true })
  await notes.click()
  await expect(page.getByText("Nuk ka Notes të padiskutuara në këtë raport.")).toBeVisible()
  await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(0)
  await notes.click()
  await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(2)
})

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
    await expect(toolbar.getByTestId("one-h-toolbar-strike-total")).toHaveText("Total strikes: 2 · 10:00–11:00")
    await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(2)
    await button.click()
    await expect(button).toHaveAttribute("aria-pressed", "true")
    await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(1)
    await expect(frame.locator('[data-report-task="true"]:visible')).toHaveAttribute("data-strike-count", "2")
    await expect(frame.locator('[data-report-task-section]:visible')).toHaveCount(1)
    await expect(frame.locator('[data-report-supplement]')).toBeHidden()
    await expect(toolbar.getByRole("status")).toHaveText("Shfaqen 1 nga 2 detyra")
    await expect(toolbar.getByTestId("one-h-toolbar-strike-total")).toHaveText("Total strikes: 2 · 10:00–11:00")
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
  const button = page.getByTestId("one-h-strikes-toolbar").getByRole("button", { name: "Vet\u00ebm me strikes > 0" })
  await button.click()
  await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(0)
  await expect(frame.locator('[data-report-task-employee]:visible')).toHaveCount(0)
  await expect(frame.locator('[data-report-task-section]:visible')).toHaveCount(0)
  await expect(page.getByTestId("one-h-toolbar-strike-total")).toHaveText("Total strikes: 0 · 08:00–10:00")
  await expect(page.getByText("Nuk ka detyra me strikes > 0 në këtë interval.")).toBeVisible()
  await button.click()
  await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(3)
  await expect(page.getByText("Nuk ka detyra me strikes > 0 në këtë interval.")).toHaveCount(0)
})

test("the top filter also controls BLL table rows", async ({ page }) => {
  const frame = await openReport(page, "STAFF", "14:10")
  const button = page.getByTestId("one-h-strikes-toolbar").getByRole("button", { name: "Vet\u00ebm me strikes > 0" })
  await button.click()
  await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(2)
  const bll = frame.locator('[data-bll-task-table] tr[data-report-task="true"]:visible')
  await expect(bll).toHaveCount(1)
  await expect(bll).toHaveAttribute("data-strike-count", "2")
  await expect(page.getByTestId("one-h-toolbar-strike-total")).toHaveText("Total strikes: 2 · 11:50–14:20")
  await button.click()
  await expect(bll).toHaveCount(2)
})

for (const role of ["ADMIN", "STAFF"] as const) {
  test(`${role}: embedded SHTYPI strikes filter both card halves and restore slot labels`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1840, height: 1050 })
    const frame = await openReport(page, role, "11:00", false, true)
    const toolbar = page.getByTestId("one-h-strikes-toolbar")
    const button = toolbar.getByRole("button", { name: "Vet\u00ebm me strikes > 0" })
    const print = frame.locator('[data-report-print-section]')
    const rows = print.locator('tr[data-task-card-row="content"]')
    await expect(print.locator('[data-task-strike-count]')).toHaveCount(8)
    await expect(print.locator('[data-task-strike-count]').first()).toHaveCSS("font-size", "14px")
    await expect(print.locator('[data-print-strike-total]')).toHaveText("1H SHTYPI · Total strikes: 2 · 10:00–11:00")
    await expect(toolbar.getByRole("status")).toHaveText("Shfaqen 10 nga 10 detyra")
    await expect(toolbar.getByTestId("one-h-toolbar-strike-total")).toHaveText("Total strikes: 4 · 10:00–11:00")
    await button.click()
    await expect(print).toBeVisible()
    await expect(frame.locator('[data-report-supplement]')).toBeVisible()
    await expect(print.locator('td[data-report-task="true"]:visible')).toHaveCount(1)
    await expect(print.locator('td[data-report-task="true"]:visible')).toHaveAttribute("data-strike-count", "2")
    await expect(rows.nth(0)).toBeHidden()
    await expect(rows.nth(1)).toBeVisible()
    await expect(rows.nth(2)).toBeHidden()
    await expect(rows.nth(1).locator('th').first()).toHaveAttribute('rowspan', '2')
    await expect(rows.nth(1).locator('th')).toHaveCount(2)
    await expect(print.locator('tr[data-task-card-row="dates"]:visible')).toHaveCount(1)
    await expect(print.locator('tr[data-task-card-row="dates"]:visible > td:visible')).toHaveCount(1)
    await expect(toolbar.getByRole("status")).toHaveText("Shfaqen 2 nga 10 detyra")
    await expect(toolbar.getByTestId("one-h-toolbar-strike-total")).toHaveText("Total strikes: 4 · 10:00–11:00")
    await print.locator('[data-print-strike-total]').scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath("embedded-filtered.png"), fullPage: true })
    await button.click()
    await expect(print.locator('td[data-report-task="true"]:visible')).toHaveCount(8)
    await expect(rows.nth(0).locator('th').first()).toHaveAttribute('rowspan', '4')
    await expect(rows.nth(1).locator('th')).toHaveCount(0)
    await expect(print.locator('tr[data-task-card-row="dates"]:visible')).toHaveCount(3)
    await expect(toolbar.getByRole("status")).toHaveText("Shfaqen 10 nga 10 detyra")
    await print.locator('[data-print-strike-total]').scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath("embedded-restored.png"), fullPage: true })
  })
}

test("an embedded SHTYPI table without positive strikes is hidden and restores on toggle", async ({ page }) => {
  const frame = await openReport(page, "ADMIN", "11:00", true, true)
  const button = page.getByTestId("one-h-strikes-toolbar").getByRole("button", { name: "Vet\u00ebm me strikes > 0" })
  await button.click()
  await expect(frame.locator('[data-report-print-section]')).toBeHidden()
  await expect(page.getByText("Nuk ka detyra me strikes > 0 në këtë interval.")).toBeVisible()
  await button.click()
  await expect(frame.locator('[data-report-print-section]')).toBeVisible()
  await expect(frame.locator('td[data-report-task="true"]:visible')).toHaveCount(8)
})

test("the toolbar counts a task shared between SHTYPI and the hourly report only once", async ({ page }) => {
  await openReport(page, "ADMIN", "11:00", false, true, true)
  const total = page.getByTestId("one-h-toolbar-strike-total")
  await expect(total).toHaveText("Total strikes: 2 · 10:00–11:00")
  await page.getByTestId("one-h-strikes-toolbar").getByRole("button", { name: "Vet\u00ebm me strikes > 0" }).click()
  await expect(total).toHaveText("Total strikes: 2 · 10:00–11:00")
})

for (const role of ["ADMIN", "STAFF"] as const) {
  test(`${role}: Done filters complete tasks and embedded cards, switches from Strikes and persists on regeneration`, async ({ page }) => {
    const frame = await openReport(page, role, "14:10", false, true, false, true)
    const toolbar = page.getByTestId("one-h-strikes-toolbar")
    const done = toolbar.getByRole("button", { name: "Vetëm Done", exact: true })
    const strikes = toolbar.getByRole("button", { name: "Vetëm me strikes > 0" })
    await strikes.click()
    await done.click()
    await expect(done).toHaveAttribute("aria-pressed", "true")
    await expect(strikes).toHaveAttribute("aria-pressed", "false")
    const visible = frame.locator('[data-report-task="true"]:visible')
    await expect(visible).toHaveCount(3)
    for (const task of await visible.all()) await expect(task).toHaveAttribute("data-task-status", "DONE")
    await expect(frame.locator('[data-bll-task-table] tr[data-report-task="true"]:visible')).toHaveCount(1)
    const print = frame.locator('[data-report-print-section]')
    await expect(print.locator('td[data-report-task="true"]:visible')).toHaveCount(1)
    await expect(print.locator('tr[data-task-card-row="dates"]:visible > td:visible')).toHaveCount(1)
    await expect(print.locator('tr[data-task-card-row="content"]:visible th').first()).toHaveAttribute("rowspan", "2")
    await page.getByRole("button", { name: role === "ADMIN" ? "Preview fresh report" : "Generate report", exact: true }).click()
    await expect(done).toHaveAttribute("aria-pressed", "true")
    await expect(visible).toHaveCount(3)
    await strikes.click()
    await expect(done).toHaveAttribute("aria-pressed", "false")
    await done.click()
    await done.click()
    await expect(visible).toHaveCount(12)
    await expect(print.locator('tr[data-task-card-row="content"]').first().locator("th").first()).toHaveAttribute("rowspan", "4")
  })
}

test("Done with no completed tasks hides empty groups and can be reset", async ({ page }) => {
  const frame = await openReport(page, "STAFF")
  const done = page.getByRole("button", { name: "Vetëm Done", exact: true })
  await done.click()
  await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(0)
  await expect(frame.locator('[data-report-task-section]:visible')).toHaveCount(0)
  await expect(page.getByText("Nuk ka detyra Done në këtë raport.")).toBeVisible()
  await done.click()
  await expect(frame.locator('[data-report-task="true"]:visible')).toHaveCount(2)
})

for (const legacy of [false, true]) {
  test(`SHTYPI Today: Done filters paired cells and switches with Strikes (${legacy ? "legacy frozen" : "current"})`, async ({ page }, testInfo) => {
    const { frame, fixture } = await openPrintReport(page, legacy)
    const done = page.getByRole("button", { name: "Vetëm Done", exact: true })
    const strikes = page.getByRole("button", { name: "Vetëm detyrat me strikes > 0", exact: true })
    await strikes.click()
    await expect(frame.locator('td[data-task-id]:visible')).toHaveAttribute("data-task-id", fixture.strike_id)
    await done.click()
    await expect(strikes).toHaveAttribute("aria-pressed", "false")
    await expect(done).toHaveAttribute("aria-pressed", "true")
    await expect(frame.locator('td[data-task-id]:visible')).toHaveCount(1)
    await expect(frame.locator('td[data-task-id]:visible')).toHaveAttribute("data-task-id", fixture.done_id)
    await expect(frame.locator('tr[data-task-card-row="dates"]:visible > td:visible')).toHaveCount(1)
    await expect(frame.locator('tr[data-task-card-row="content"]:visible th').first()).toHaveAttribute("rowspan", "2")
    await page.screenshot({ path: testInfo.outputPath("shtypi-done.png"), fullPage: true })
    await done.click()
    await expect(frame.locator('td[data-task-id]:visible')).toHaveCount(8)
    await expect(frame.locator('tr[data-task-card-row="content"]').first().locator("th").first()).toHaveAttribute("rowspan", "4")
  })
}

test("SHTYPI Tomorrow keeps the filters limited to pages which already have Strikes", async ({ page }) => {
  await openPrintReport(page, false, false)
  await expect(page.getByRole("button", { name: "Vetëm Done", exact: true })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Vetëm detyrat me strikes > 0", exact: true })).toHaveCount(0)
})
