import { test, expect, type Page } from "@playwright/test"

const department = { id: "99999999-9999-4999-8999-999999999999", name: "Development", code: "DEV" }
const owners = ["First Owner", "Second Owner"].map((name, i) => ({
  id: `${i + 2}2222222-2222-4222-8222-222222222222`, full_name: name, username: name,
  email: `owner${i}@example.com`, role: "STAFF", is_active: true, department_id: department.id,
}))
const taskIds = ["55555555-5555-4555-8555-555555555555", "66666666-6666-4666-8666-666666666666"]

async function fixture(page: Page, group: "oneH" | "personal" | "blocked" = "oneH", sharedRecord = false) {
  const user = { ...owners[0], role: "ADMIN" }
  const tasks = owners.map((owner, i) => ({
    id: taskIds[i], task_id: taskIds[i], assigned_to: owner.id, assignees: [owner],
    title: group === "personal" ? "GA: Shared task" : "Shared task", task_title: "Shared task", status: "TODO", priority: "NORMAL",
    department_id: department.id, created_by: user.id, start_date: "2026-11-16", due_date: "2026-12-31",
    created_at: "2026-11-16T08:00:00Z", updated_at: "2026-11-16T08:00:00Z",
    is_1h_report: true, one_h_report_slot: "10:00", finish_period: "AM", is_active: true,
    daily_products: 0, is_bllok: false, is_personal: false, is_r1: false,
    ga_note_origin_id: null, one_h_marker: null as string | null,
    one_h_marker_by_ga: false, one_h_marker_comment: "Keep this comment",
  }))
  const writes: { id: string; body: Record<string, unknown> }[] = []
  await page.addInitScript(user => {
    localStorage.setItem("primex_access_token", "test-only-marker-token")
    localStorage.setItem("primex_user", JSON.stringify(user))
  }, user)
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url()), path = url.pathname
    if (path === "/api/tasks/group/one-h-markers") {
      const { task_ids, one_h_marker } = route.request().postDataJSON()
      const updated = tasks.filter(task => task_ids.includes(task.id))
      for (const task of updated) {
        task.one_h_marker = one_h_marker
        writes.push({ id: task.id, body: { one_h_marker, one_h_marker_comment: task.one_h_marker_comment } })
      }
      return route.fulfill({ json: updated })
    }
    const task = tasks.find(task => path === `/api/tasks/${task.id}` || path === `/api/tasks/${task.id}/one-h-marker`)
    if (task) {
      if (route.request().method() === "PATCH") {
        const body = route.request().postDataJSON()
        writes.push({ id: task.id, body }); Object.assign(task, body)
      }
      return route.fulfill({ json: task })
    }
    if (path === "/api/auth/me") return route.fulfill({ json: user })
    if (path === "/api/users" || path === "/api/users/lookup") return route.fulfill({ json: owners })
    if (path === "/api/departments") return route.fulfill({ json: [department] })
    if (path === "/api/tasks") return route.fulfill({ json: tasks })
    if (/^\/api\/(morning-report|after-break-report|meetings-report)$/.test(path)) return route.fulfill({ status: 404, json: { detail: "No draft" } })
    if (/^\/api\/(morning-report|after-break-report|meetings-report)\/settings$/.test(path)) return route.fulfill({ json: {
      is_active: false, send_time: "07:00", timezone: "Europe/Tirane", weekdays: [], recipients: { to: [], cc: [], bcc: [] },
    } })
    if (path === "/api/admin/primeflow-1h-reports/preview") return route.fulfill({ json: {
      document: { subject: "Report", generated_at: "2026-11-16T10:00:00Z", recipients: { to: [] } },
      html: `<html><body><div data-report-task-section="true">${tasks.map(task => `<table data-report-task="true" data-task-id="${task.id}" data-strike-count="0"><tr><td>${task.title}</td></tr></table>`).join("")}</div></body></html>`,
      task_count: 2, note_count: 0, notes_html: "<html><body></body></html>",
    } })
    if (path.includes("marker-comments")) return route.fulfill({ json: { items: [], unread_count: 0 } })
    if (path === "/api/planners/weekly-table") {
      const monday = url.searchParams.get("week_start") || "2026-11-16"
      const dates = Array.from({ length: 5 }, (_, i) => {
        const day = new Date(`${monday}T12:00:00Z`); day.setUTCDate(day.getUTCDate() + i)
        return day.toISOString().slice(0, 10)
      })
      return route.fulfill({ json: { week_start: dates[0], week_end: dates[4], saved_plan_id: null,
        departments: [{ department_id: department.id, department_name: department.name,
          days: dates.map(date => ({ date, users: owners.map((owner, i) => ({
            user_id: owner.id, user_name: owner.full_name,
            am_projects: [], pm_projects: [], am_system_tasks: [], pm_system_tasks: [],
            am_fast_tasks: [tasks[i]], pm_fast_tasks: [tasks[i]],
          })) })) }] } })
    }
    if (path === "/api/planners/monthly") return route.fulfill({ json: {
      month_start: "2026-11-01", month_end: "2026-11-30", tasks, recurring: [],
      summary: { month_completed: 0, previous_month_completed: 0 },
    } })
    if (path === "/api/common-view") {
      const week = url.searchParams.get("week_start") || "2026-11-16"
      const include = (url.searchParams.get("include") || "tasks,users,departments").split(",")
      const items = Object.fromEntries(["late", "absent", "leave", "externalHoliday", "waitingClient", "blocked", "oneH", "r1", "personal", "external", "internal", "bz", "problems", "feedback", "priority", "diamond"].map(name => [name, []]))
      items[group] = tasks.map((task, i) => ({ id: sharedRecord ? tasks[0].id : task.id, taskId: sharedRecord ? tasks[0].id : task.id, userId: owners[i].id,
        title: task.title, person: owners[i].full_name, assignees: [owners[i].full_name], date: week,
        status: "TODO", finishPeriod: "AM", oneHReportSlot: "10:00", startDate: week,
        oneHMarker: task.one_h_marker, oneHMarkerByGa: false, oneHMarkerComment: task.one_h_marker_comment,
      })) as never[]
      return route.fulfill({ json: { week_start: week, users: owners, departments: [department], items,
        requested: include, included: include, missing: [], guardrails: { truncated: {} } } })
    }
    return route.fulfill({ json: path.includes("count") ? { count: 0 } : [] })
  })
  return { tasks, writes }
}

async function chooseSymbols(page: Page, id: string, waitForSave = true) {
  const editor = page.locator(`[data-task-marker-id="${id}"]:visible`).first()
  await editor.getByRole("button", { name: "Task symbols (maximum 2)", exact: true }).click()
  const picker = page.getByRole("dialog", { name: "Simbolet", exact: true })
  await picker.getByRole("checkbox", { name: "!!!", exact: true }).check()
  await picker.getByRole("checkbox", { name: "M3", exact: true }).check()
  await picker.getByRole("button", { name: "Ruaj", exact: true }).click()
  const comment = page.getByRole("dialog", { name: "Task comment", exact: true })
  await comment.getByRole("button", { name: "Save", exact: true }).click()
  if (waitForSave) await expect(editor.locator('[data-task-marker-symbol]')).toHaveText(['!!!', 'M3'])
}

test("M3 opens the Tomorrow table by default and filters task cards by multiple symbols", async ({ page }) => {
  await fixture(page)
  await page.route(/\/api\/meetings-report\?report_date=/, (route) => route.fulfill({ json: {
    id: "m3-test", report_date: "2026-11-19", tomorrow_date: "2026-11-20", subject: "M3", status: "DRAFT",
    recipients: { to: [], cc: [], bcc: [] },
    sections: [
      { title: "SHIKO DET ME SIMBOLE NE 1H SHTYPI NESER", body: "" },
      { title: "(GA) ZHV: TIKETAT E STD?", body: "Old ticket totals" },
      {
        title: "N- (GA) DET TE REJA LAST WEEK/THIS WEEK/08:00/ME DEADLINE?",
        body: [
          "DET 08:00:", "+---+", "| NR | KUSH | TITULLI |", "+---+",
          "| 1 | GA | Pending morning task [[st:TODO]] |", "+---+",
          "| 2 | GA | Active morning task [[st:IN_PROGRESS]] |", "+---+",
        ].join("\n"),
      },
    ],
    generated_snapshot: { tomorrow_symbols_html: `
      <table><tbody>
        <tr data-task-card-row="content"><th rowspan="2">1H 10:00</th>
          <td data-task-id="f" data-task-marker="F,QUESTION"><span data-task-title-text="true">Physical task</span></td>
          <td data-task-id="ka" data-task-marker="KA"><span data-task-title-text="true">KA task</span></td>
        </tr>
        <tr data-task-card-row="dates"><td>Physical date</td><td>KA date</td></tr>
        <tr data-task-card-row="content"><th rowspan="2">1H 11:00</th>
          <td data-task-id="gent" data-task-marker="GENT"><span data-task-title-text="true">Genti task</span></td>
        </tr>
        <tr data-task-card-row="dates"><td>Genti date</td></tr>
      </tbody></table>` },
  } }))

  await page.goto("/meetings-report")
  await expect(page.getByText("Physical task", { exact: true })).toBeVisible()
  await expect(page.getByText("TIKETAT E STD?", { exact: false })).toHaveCount(0)
  await expect(page.getByText("Old ticket totals", { exact: true })).toHaveCount(0)
  await expect(page.getByRole("row").filter({ hasText: "Pending morning task" })).toHaveClass(/\bbg-pink-200\b/)
  await expect(page.getByRole("row").filter({ hasText: "Active morning task" })).toHaveClass(/\bbg-yellow-100\b/)
  const management = page.locator("summary").filter({ hasText: "Menaxhimi i raportit dhe email-it" })
  const preview = page.getByRole("button", { name: "Email preview", exact: true })
  await expect(management.getByText("+", { exact: true })).toBeVisible()
  await expect(preview).toBeHidden()
  await management.press("Enter")
  await expect(management.getByText("−", { exact: true })).toBeVisible()
  await expect(preview).toBeVisible()
  await expect(page.getByText("Last update", { exact: true })).toBeVisible()
  await management.click()
  await expect(preview).toBeHidden()
  await expect(page.getByText("Physical task", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "Fshihe tabelën" }).click()
  await expect(page.getByText("Physical task", { exact: true })).toBeHidden()
  await page.getByRole("button", { name: "Shfaq tabelën" }).click()
  await page.getByText("Simbolet Të gjitha", { exact: true }).click()
  await page.getByRole("checkbox", { name: "?", exact: true }).check()
  await expect(page.getByText("Physical task", { exact: true })).toBeVisible()
  await expect(page.getByText("KA date", { exact: true })).toBeHidden()
  await expect(page.getByText("1H 11:00", { exact: true })).toBeHidden()
  await page.getByRole("checkbox", { name: "KA", exact: true }).check()
  await expect(page.getByText("KA task", { exact: true })).toBeVisible()
  await page.getByRole("checkbox", { name: "X", exact: true }).check()
  await page.getByRole("checkbox", { name: "KA", exact: true }).uncheck()
  await page.getByRole("checkbox", { name: "?", exact: true }).uncheck()
  await expect(page.getByText("Asnjë detyrë me simbolet e zgjedhura.")).toBeVisible()
  await page.getByRole("button", { name: "Të gjitha simbolet" }).click()
  await expect(page.getByText("Genti task", { exact: true })).toBeVisible()
})

test("Weekly Planner saves only one owner's task and synchronizes all repeated cards", async ({ page }, info) => {
  const { tasks, writes } = await fixture(page)
  await page.goto("/weekly-planner?week=next")
  await expect(page.locator(`[data-task-marker-id="${taskIds[0]}"]`).first()).toBeVisible()
  await chooseSymbols(page, taskIds[0])
  expect(writes).toEqual([{ id: taskIds[0], body: { one_h_marker: "CLIENT_URGENT,M3", one_h_marker_comment: "Keep this comment" } }])
  expect(tasks[1].one_h_marker).toBeNull()
  for (const button of await page.locator(`[data-task-marker-id="${taskIds[0]}"] button[aria-haspopup="dialog"]`).all()) {
    await expect(button.locator('[data-task-marker-symbol]')).toHaveText(['!!!', 'M3'])
  }
  await expect(page.getByRole("dialog", { name: "Task Title", exact: true })).toHaveCount(0)
  await page.emulateMedia({ media: 'print' })
  await expect(page.locator(`[data-task-marker-id="${taskIds[0]}"]`).first()).toBeHidden()
  await expect(page.locator(`[data-task-marker-print="${taskIds[0]}"]`).first()).toBeVisible()
  await expect(page.locator(`[data-task-marker-print="${taskIds[0]}"]`).first()).toHaveText('!!! + M3')
  await page.emulateMedia({ media: 'screen' })
  await page.screenshot({ path: info.outputPath("weekly-symbols.png"), fullPage: true })
})

async function openGroup(page: Page) {
  await page.goto('/common')
  await page.getByRole('button', { name: /^This Week$/i }).click()
  const weekly = page.locator('.week-table-view')
  await expect(weekly.locator('[data-task-marker-group]')).toHaveCount(1)
  await expect(weekly.locator('[data-task-marker-id]')).toHaveCount(0)
  await weekly.getByRole('button', { name: 'Simbolet e grupit', exact: true }).click()
  return page.getByRole('dialog', { name: 'Simbolet e grupit', exact: true })
}

test("Common View distinguishes WFC INT from WFE and shows the selected confirmer", async ({ page }) => {
  await fixture(page)
  await page.route(/\/api\/common-view\?/, (route) => {
    const params = new URL(route.request().url()).searchParams
    const week = params.get("week_start")!
    const included = params.get("include")!.split(",")
    return route.fulfill({ json: {
      week_start: week, included, requested: included, missing: [], users: owners, departments: [department],
      items: {
        feedback: [], blocked: [], oneH: [], r1: [], problems: [],
        personal: [{ title: "GA: Personal work", status: "TODO", date: week }],
        external: [], internal: [], bz: [], late: [], absent: [], leave: [], externalHoliday: [], priority: [], diamond: [],
        waitingConfirmation: [{
          title: "Internal approval", status: "WAITING_CONFIRMATION", date: week,
          taskId: taskIds[0], userId: owners[0].id, assignees: [owners[0].full_name],
          confirmation_assignee_initials: "HS",
        }],
        waitingClient: [{
          title: "Client reply", status: "WAITING_CLIENT", date: week,
          taskId: taskIds[1], userId: owners[1].id, assignees: [owners[1].full_name],
        }],
      },
    } })
  })

  await page.goto("/common")
  await page.getByRole("button", { name: "This Week", exact: true }).click()
  const confirmation = page.locator(".week-table-row.waiting-confirmation")
  const client = page.locator(".week-table-row.waiting-client")
  await expect(confirmation.locator(".week-table-label")).toHaveCSS("background-color", "rgb(153, 246, 228)")
  await expect(client.locator(".week-table-label")).toHaveCSS("background-color", "rgb(226, 193, 91)")
  await expect(page.locator(".week-table-row.personal .week-table-label").first()).toHaveCSS("background-color", "rgb(243, 232, 255)")
  await expect(confirmation.getByText("CON: HS", { exact: true })).toBeVisible()
  await expect(client.getByText("CON: HS", { exact: true })).toHaveCount(0)
})

test("Common View Short filters both workweeks and the weekly print", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await fixture(page)
  let includeShortConfirmations = true
  await page.route(/\/api\/common-view\?/, (route) => {
    const url = new URL(route.request().url())
    const week = url.searchParams.get("week_start")!
    const included = url.searchParams.get("include")!.split(",")
    const task = (offset: number, title: string, fields = {}) => {
      const date = new Date(`${week}T12:00:00Z`)
      date.setUTCDate(date.getUTCDate() + offset)
      return { date: date.toISOString().slice(0, 10), title, status: "TODO", ...fields }
    }
    return route.fulfill({ json: {
      week_start: week, included, requested: included, missing: [], users: owners,
      items: {
        late: [], absent: [], leave: [], externalHoliday: [], problems: [], feedback: [],
        priority: [], bz: [], internal: [],
        external: [task(0, "External meeting", { time: "10:00" })],
        oneH: [
          task(0, "Urgent review", { oneHMarker: "M3,CLIENT_URGENT" }),
          task(2, "08:00 inventory"),
          task(0, "Ordinary review", { oneHMarker: "DOUBLE_EXCLAM" }),
        ],
        r1: [task(1, "Deadline review", { is_deadline_important: true })],
        blocked: [task(3, "Blocked review")],
        personal: [task(4, "GA: Personal review"), task(4, "KA: Other review")],
        waitingConfirmation: [
          task(0, "Ordinary approval", { oneHMarker: "DOUBLE_EXCLAM" }),
          ...(includeShortConfirmations ? [
            task(1, "Deadline approval", { isDeadlineImportant: true }),
            task(2, "08:00 approval workflow"),
            task(3, "Urgent approval", { oneHMarker: "M3,CLIENT_URGENT" }),
          ] : []),
        ].map(entry => ({ ...entry, status: "WAITING_CONFIRMATION" })),
      },
    } })
  })

  await page.goto("/common")
  const fullWeek = page.getByRole("button", { name: "Next Week", exact: true })
  const thisWeekShort = page.getByRole("button", { name: "This Week Short", exact: true })
  const nextWeekShort = page.getByRole("button", { name: "Next Week Short", exact: true })
  await expect(nextWeekShort).toBeVisible()
  expect((await thisWeekShort.boundingBox())!.y).toBeGreaterThan((await fullWeek.boundingBox())!.y)
  expect((await nextWeekShort.boundingBox())!.y).toBe((await thisWeekShort.boundingBox())!.y)
  await expect(thisWeekShort).toHaveCSS("background-color", "rgb(240, 253, 250)")
  const table = page.locator(".week-table-view")
  const confirmation = table.locator(".week-table-row.waiting-confirmation")
  const excludedApproval = confirmation.getByText("Ordinary approval")
  const matchingApprovals = ["Deadline approval", "08:00 approval workflow", "Urgent approval"]
  const matching = ["Urgent review", "Deadline review", "08:00 inventory", "Blocked review", "Personal review"]
  const excluded = ["Ordinary review", "Other review", "External meeting"]
  for (const week of ["This Week", "Next Week"]) {
    const short = page.getByRole("button", { name: `${week} Short`, exact: true })
    await short.click()
    await expect(short).toHaveAttribute("aria-pressed", "true")
    await expect(table.locator(".week-table-date-header")).toHaveCount(5)
    for (const [day, title] of matching.entries()) {
      await expect(table.locator(`tbody tr td:nth-child(${day + 3})`).getByText(title)).toBeVisible()
    }
    for (const title of excluded) await expect(table.getByText(title)).toHaveCount(0)
    for (const title of matchingApprovals) await expect(confirmation.getByText(title, { exact: true })).toBeVisible()
    await expect(excludedApproval).toHaveCount(0)
    await expect(table.locator("tbody .week-table-label")).toHaveCount(5)
  }

  await page.emulateMedia({ media: "print" })
  await expect(table.getByText("COMMON VIEW - WEEK PLAN SHORT")).toBeVisible()
  await expect(table.getByText("Urgent review")).toBeVisible()
  await expect(table.getByText("Ordinary review")).toHaveCount(0)
  for (const title of matchingApprovals) await expect(confirmation.getByText(title, { exact: true })).toBeVisible()
  await expect(excludedApproval).toHaveCount(0)
  await page.emulateMedia({ media: "screen" })

  await page.getByRole("button", { name: "Next Week", exact: true }).click()
  for (const title of excluded) await expect(table.getByText(title)).toBeVisible()
  await expect(excludedApproval).toBeVisible()

  includeShortConfirmations = false
  await page.reload()
  await fullWeek.click()
  await expect(excludedApproval).toBeVisible()
  await nextWeekShort.click()
  await expect(confirmation).toHaveCount(0)
})

test("Common View Short groups 1H by period and sorts each user's tasks by priority", async ({ page }) => {
  await fixture(page)
  const orderedUsers = owners.map((owner, index) => ({ ...owner, weekly_planner_sort_order: 2 - index }))
  await page.route(/\/api\/common-view\?/, (route) => {
    const params = new URL(route.request().url()).searchParams
    const week = params.get("week_start")!
    const included = params.get("include")!.split(",")
    const task = (userIndex: number, title: string, fields = {}) => ({
      title, date: week, status: "TODO", finishPeriod: "AM", oneHMarker: "CLIENT_URGENT",
      userId: owners[userIndex].id, person: owners[userIndex].full_name, departmentId: department.id,
      ...fields,
    })
    const items = Object.fromEntries([
      "late", "absent", "leave", "externalHoliday", "waitingClient", "waitingConfirmation", "blocked",
      "r1", "personal", "external", "internal", "bz", "problems", "feedback", "priority", "diamond",
    ].map(name => [name, []]))
    return route.fulfill({ json: {
      week_start: week, included, requested: included, missing: [], users: orderedUsers, departments: [department],
      items: { ...items, oneH: [
        task(0, "08:00 first user"),
        task(1, "Urgent second user", { oneHReportSlot: "10:00" }),
        task(1, "Deadline second user", { oneHMarker: null, isDeadlineImportant: true }),
        task(1, "08:00 second user", { oneHReportSlot: "11:00", isDeadlineImportant: true, status: "DONE" }),
        task(0, "Urgent first user PM", { finishPeriod: "PM" }),
        task(1, "Urgent second user PM", { finishPeriod: "PM", oneHMarkerComment: "Comment in full view" }),
        task(1, "08:00 second user PM", { finishPeriod: "PM" }),
        task(0, "Task spanning both periods", { finishPeriod: "AM/PM" }),
      ] },
    } })
  })

  await page.goto("/common")
  const row = page.locator(".week-table-row.oneh")
  const am = row.getByRole("group", { name: "AM", exact: true })
  const pm = row.getByRole("group", { name: "PM", exact: true })
  const amRow = row.filter({ has: page.getByRole("group", { name: "AM", exact: true }) })
  const pmRow = row.filter({ has: page.getByRole("group", { name: "PM", exact: true }) })
  const expectedAM = ["08:00 second user", "Deadline second user", "Urgent second user", "08:00 first user"]
  const expectedPM = ["08:00 second user PM", "Urgent second user PM", "Urgent first user PM"]
  for (const week of ["This Week Short", "Next Week Short"]) {
    await page.getByRole("button", { name: week, exact: true }).click()
    await expect(amRow.locator(".week-table-period-heading")).toHaveText(Array(5).fill("AM"))
    await expect(pmRow.locator(".week-table-period-heading")).toHaveText(Array(5).fill("PM"))
    await expect(row.getByRole("group")).toHaveText([/^AM/, /^PM/])
    await expect(am.locator(".period-indicator")).toHaveText(["AM/PM"])
    await expect(pm.locator(".period-indicator")).toHaveCount(0)
    await expect(row.getByText("Comment in full view", { exact: false })).toHaveCount(0)
    await expect(am.locator(".week-table-entry-main > span > span").filter({ hasText: /user/ }))
      .toHaveText(expectedAM)
    await expect(pm.locator(".week-table-entry-main > span > span").filter({ hasText: /user/ }))
      .toHaveText(expectedPM)
  }
  await page.emulateMedia({ media: "print" })
  await expect(am.getByText("08:00 second user", { exact: true })).toBeVisible()
  await expect(pm.getByText("Urgent first user PM", { exact: true })).toBeVisible()
  await expect(pm.locator(".period-indicator")).toHaveCount(0)
  await expect(row.getByText("Comment in full view", { exact: false })).toHaveCount(0)
  await expect(pmRow.locator("td").first()).toHaveCSS("border-top-width", "2px")
  await page.emulateMedia({ media: "screen" })
  await page.getByRole("button", { name: "Next Week", exact: true }).click()
  await expect(am).toHaveCount(0)
  await expect(pm).toHaveCount(0)
  await expect(row.locator(".period-indicator").filter({ hasText: /^PM$/ })).toHaveCount(3)
  await expect(row.getByText("Comment in full view", { exact: false })).toBeVisible()
})

async function chooseGroupSymbols(page: Page) {
  await page.getByRole('button', { name: 'Simbolet për të gjithë', exact: true }).click()
  const picker = page.getByRole('dialog', { name: 'Simbolet', exact: true })
  await picker.getByRole('checkbox', { name: '!!!', exact: true }).check()
  await picker.getByRole('checkbox', { name: 'M3', exact: true }).check()
  await picker.getByRole('button', { name: 'Ruaj', exact: true }).click()
}

test("Common View has one control and applies symbols to all owners by default", async ({ page }, info) => {
  const { tasks, writes } = await fixture(page)
  tasks[1].one_h_marker_comment = 'Second owner comment'
  const dialog = await openGroup(page)
  await expect(dialog.getByRole('button', { name: 'Për të gjithë', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await chooseGroupSymbols(page)
  await dialog.getByRole('button', { name: 'Ruaj për të gjithë', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes).toEqual(tasks.map(task => ({ id: task.id, body: { one_h_marker: 'CLIENT_URGENT,M3', one_h_marker_comment: task.one_h_marker_comment } })))
  await expect(page.locator('.week-table-view [data-task-marker-group] button').first().locator('[data-task-marker-symbol]')).toHaveText(['!!!', 'M3'])
  for (const owner of owners) await expect(page.locator(`.week-table-view .week-table-avatar[title="${owner.full_name}"]`)).toBeVisible()
  await page.screenshot({ path: info.outputPath("common-week-symbols.png"), fullPage: true })
})

for (const group of ['blocked', 'personal'] as const) {
  test(`Common View ${group}: individual controls appear only inside the dialog`, async ({ page }) => {
    const { tasks, writes } = await fixture(page, group)
    const dialog = await openGroup(page)
    await dialog.getByRole('button', { name: 'Sipas personit', exact: true }).click()
    for (const taskId of taskIds) await expect(dialog.locator(`[data-task-marker-id="${taskId}"]`)).toBeVisible()
    await chooseSymbols(page, taskIds[1])
    expect(writes[0].id).toBe(taskIds[1])
    expect(tasks[0].one_h_marker).toBeNull()
    await dialog.getByRole('button', { name: 'Mbyll', exact: true }).click()
    const groupButton = page.locator('.week-table-view [data-task-marker-group] button').first()
    await expect(groupButton).toHaveText('⋯⌄')
    await expect(groupButton).toHaveAttribute('title', /First Owner: — · Second Owner: !!! \+ M3/)
  })
}

test('Common View canceling the shared symbol draft writes nothing', async ({ page }) => {
  const { writes } = await fixture(page)
  const dialog = await openGroup(page)
  await chooseGroupSymbols(page)
  await dialog.getByRole('button', { name: 'Anulo', exact: true }).click()
  expect(writes).toHaveLength(0)
})

test("An individual symbol difference shows the colleague's value and requires an explanation", async ({ page }) => {
  const { tasks, writes } = await fixture(page)
  tasks[0].one_h_marker = "M2"
  await page.route(`**/api/tasks/${taskIds[1]}/one-h-marker`, async route => {
    if (route.request().method() !== "PATCH" || route.request().postDataJSON().reporting_choice_confirmations) {
      return route.fallback()
    }
    return route.fulfill({ status: 409, json: { detail: {
      code: "TASK_REPORTING_CHOICE_REASON_REQUIRED", key: "test-conflict", field: "marker", label: "!!! + M3",
      task_title: tasks[1].title, person: owners[1].full_name, date: "2026-11-25",
      peers: [{ owner_id: owners[0].id, person: owners[0].full_name, label: "M2" }],
    } } })
  })
  const group = await openGroup(page)
  await group.getByRole("button", { name: "Sipas personit", exact: true }).click()
  await chooseSymbols(page, taskIds[1], false)
  const warning = page.getByRole("dialog", { name: "Simbol tjetër për të njëjtën detyrë" })
  await expect(warning.getByText("First Owner", { exact: true })).toBeVisible()
  await expect(warning.getByText("M2", { exact: true })).toBeVisible()
  await expect(warning.getByRole("button", { name: "Vazhdo dhe ruaj" })).toBeDisabled()
  expect(writes).toHaveLength(0)
  await warning.getByRole("textbox", { name: "Komenti i detyrueshëm" }).fill("Dorëzimi im është në fund të ditës.")
  await warning.getByRole("button", { name: "Vazhdo dhe ruaj" }).click()
  await expect(warning).toHaveCount(0)
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].body.reporting_choice_confirmations).toEqual({
    marker: { key: "test-conflict", reason: "Dorëzimi im është në fund të ditës." },
  })
  expect(tasks[0].one_h_marker).toBe("M2")
})

test('Common View retries a rejected group change without erasing owner comments', async ({ page }) => {
  const { tasks, writes } = await fixture(page)
  let fail = true
  await page.route('**/api/tasks/group/one-h-markers', async route => {
    if (fail) return route.fulfill({ status: 503, json: { detail: 'Unavailable' } })
    return route.fallback()
  })
  const dialog = await openGroup(page)
  await chooseGroupSymbols(page)
  await dialog.getByRole('button', { name: 'Ruaj për të gjithë', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('Simbolet nuk u ruajtën')
  expect(tasks[0].one_h_marker).toBeNull()
  expect(tasks[1].one_h_marker).toBeNull()
  fail = false
  await dialog.getByRole('button', { name: 'Ruaj për të gjithë', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  expect(writes.filter(write => write.id === taskIds[1])).toHaveLength(1)
  expect(tasks[1].one_h_marker_comment).toBe('Keep this comment')
})

test('Common View personal: a genuinely shared task has one control for its single task ID', async ({ page }) => {
  const { writes } = await fixture(page, 'personal', true)
  await page.goto('/common')
  await page.getByRole('button', { name: /^This Week$/i }).click()
  const weekly = page.locator('.week-table-view')
  await expect(weekly.locator(`[data-task-marker-id="${taskIds[0]}"]`)).toHaveCount(1)
  await expect(weekly.locator(`[data-task-marker-id="${taskIds[1]}"]`)).toHaveCount(0)
  await chooseSymbols(page, taskIds[0])
  expect(writes).toHaveLength(1)
  expect(writes[0].id).toBe(taskIds[0])
})

test("Monthly Planner symbol click does not navigate to Task Details", async ({ page }) => {
  const { writes } = await fixture(page)
  await page.goto('/monthly-planner')
  await chooseSymbols(page, taskIds[0])
  await expect(page).toHaveURL(/\/monthly-planner/)
  expect(writes[0].id).toBe(taskIds[0])
})

test("Open Tasks edits the selected task directly", async ({ page }) => {
  const { writes } = await fixture(page)
  await page.goto('/open-tasks')
  await chooseSymbols(page, taskIds[0])
  expect(writes[0].id).toBe(taskIds[0])
})

test("older list data cannot erase an existing comment when a blank symbol is edited", async ({ page }) => {
  const { tasks, writes } = await fixture(page)
  await page.route(/\/api\/tasks\?/, route => route.fulfill({ json: tasks.map(task => {
    const copy: Partial<typeof task> = { ...task }
    delete copy.one_h_marker_comment; delete copy.one_h_marker_by_ga
    return copy
  }) }))
  await page.goto('/open-tasks')
  await chooseSymbols(page, taskIds[0])
  expect(writes[0].body.one_h_marker_comment).toBe('Keep this comment')
})

test("Task Details preserves unsaved title edits while saving symbols", async ({ page }) => {
  const { writes } = await fixture(page)
  await page.goto(`/tasks/${taskIds[0]}`)
  await page.getByLabel('Title', { exact: true }).fill('Shared task with an unsaved draft')
  await chooseSymbols(page, taskIds[0])
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Shared task with an unsaved draft')
  expect(writes[0].id).toBe(taskIds[0])
  expect(writes[0].body).not.toHaveProperty('title')
})

test("WFC INT saves symbols without changing the confirmation status", async ({ page }) => {
  const { tasks, writes } = await fixture(page)
  Object.assign(tasks[0], { status: 'WAITING_CONFIRMATION', confirmation_assignee_id: owners[0].id })
  await page.goto('/waiting-confirmation-ga')
  await expect(page.getByRole('heading', { name: 'WFC INT', exact: true })).toBeVisible()
  await chooseSymbols(page, taskIds[0])
  expect(writes[0].id).toBe(taskIds[0])
  expect(tasks[0].status).toBe('WAITING_CONFIRMATION')
  await expect(page.locator(`[data-task-marker-id="${taskIds[0]}"]`)).toBeVisible()
})

test("1H preview opens the shared picker from the identified task card", async ({ page }) => {
  const { writes } = await fixture(page)
  await page.goto('/admin/1h-reports')
  await page.getByRole('tab', { name: 'Reports', exact: true }).click()
  await page.getByRole('button', { name: 'Preview fresh report', exact: true }).click()
  await page.frameLocator('iframe[title="Email preview"]').getByRole('button', { name: 'Edit task symbols', exact: true }).first().click()
  const picker = page.getByRole('dialog', { name: 'Simbolet', exact: true })
  await picker.getByRole('checkbox', { name: '!!!', exact: true }).check()
  await picker.getByRole('button', { name: 'Ruaj', exact: true }).click()
  await page.getByRole('dialog', { name: 'Task comment', exact: true }).getByRole('button', { name: 'Save', exact: true }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0]).toEqual({ id: taskIds[0], body: { one_h_marker: 'CLIENT_URGENT', one_h_marker_comment: 'Keep this comment' } })
})

for (const report of ['morning-report', 'after-break-report', 'meetings-report']) {
  test(`${report}: live task symbols can be edited without rewriting the saved report`, async ({ page }) => {
    const { writes } = await fixture(page)
    await page.goto(`/${report}`)
    await page.locator("summary").filter({ hasText: "Menaxhimi i raportit dhe email-it" }).click()
    await page.getByRole('button', { name: 'Simbolet e detyrave', exact: true }).click()
    await chooseSymbols(page, taskIds[0])
    expect(writes[0].id).toBe(taskIds[0])
    await expect(page.getByText(/Më pas rifresko raportin/)).toBeVisible()
  })
}

for (const source of ['ga-notes', 'plan-notes']) {
  test(`${source}: an unconverted Note ${source === 'ga-notes' ? 'shows read-only symbols in PX Notes' : 'edits its own symbol without changing task copies'}`, async ({ page }) => {
    const { writes } = await fixture(page)
    const note = { id: '11111111-1111-4111-8111-111111111111', content: 'Unconverted direct Note',
      note_type: 'GA', status: 'OPEN', created_by: owners[0].id, department_id: department.id,
      created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
      is_converted_to_task: false, one_h_marker: null, one_h_marker_comment: 'Keep this comment', attachments: [] }
    const noteWrites: Record<string, unknown>[] = []
    await page.route(/\/api\/(ga-notes|plan-notes)(\?|\/|$)/, async route => {
      const path = new URL(route.request().url()).pathname
      if (path === `/api/${source}/${note.id}` && route.request().method() === 'PATCH') {
        const body = route.request().postDataJSON(); noteWrites.push(body); Object.assign(note, body)
        return route.fulfill({ json: note })
      }
      return route.fulfill({ json: path === `/api/${source}` ? [note] : [] })
    })
    await test.step('Open the Note list', async () => {
      await page.goto(source === 'plan-notes' ? '/next-week-plan' : '/ga-ka-notes')
    })
    if (source === 'ga-notes') {
      const row = page.getByRole('row').filter({ hasText: note.content })
      await expect(row).toBeVisible()
      await expect(row.locator('[data-task-marker-id]')).toHaveCount(0)
      await expect(row.getByRole('button', { name: 'Task symbols (maximum 2)', exact: true })).toHaveCount(0)
      expect(noteWrites).toHaveLength(0)
      expect(writes).toHaveLength(0)
      return
    }
    await test.step('Save the Note symbols and comment', async () => {
      await chooseSymbols(page, note.id)
    })
    expect(noteWrites).toEqual([{ one_h_marker: 'CLIENT_URGENT,M3', one_h_marker_comment: 'Keep this comment' }])
    expect(writes).toHaveLength(0)
  })
}
