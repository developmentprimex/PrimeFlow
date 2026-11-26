export type ReportingChoiceDetails = {
  key: string
  field: "slot" | "marker"
  date: string
  person: string
  task_title: string
  label: string
  peers: { owner_id: string; person: string; label: string }[]
}

export type SlotReminderDetails = { message: string; slots: string[] }

export function slotReminderRequest(
  send: (init: RequestInit) => Promise<Response>,
  confirm: (details: SlotReminderDetails, signal?: AbortSignal | null) => Promise<string | null>,
) {
  let choice: string | null = null
  let affectedAssignees: Set<string> | null = null

  function confirmedRequest(init: RequestInit, headers: Headers) {
    headers.set("X-PrimeFlow-One-H-Slot-Reminder", "continue")
    if (choice === "continue") return { ...init, headers }
    const body = JSON.parse(init.body as string)
    if (body.one_h_report_slot === "16:00") body.one_h_report_slot = choice
    if (Array.isArray(body.assignee_states) && affectedAssignees) {
      for (const state of body.assignee_states) {
        if (state.one_h_report_slot === "16:00" && affectedAssignees.has(state.assignee_id)) {
          state.one_h_report_slot = choice
          state.finish_period = choice === "14:20" ? "PM" : "AM"
        }
      }
    }
    return { ...init, headers, body: JSON.stringify(body) }
  }

  return async (init: RequestInit): Promise<Response> => {
    if (typeof init.body !== "string" || !/"one_h_report_slot"\s*:\s*"16:00"/.test(init.body)) return send(init)
    const headers = new Headers(init.headers)
    if (choice) return send(confirmedRequest(init, headers))
    headers.set("X-PrimeFlow-One-H-Slot-Reminder", "ask")
    const response = await send({ ...init, headers })
    if (response.status !== 409 || init.signal?.aborted) return response
    let detail
    try { detail = (await response.clone().json()).detail } catch { return response }
    if (detail?.code !== "ONE_H_PM_BLOCK_REMINDER") return response
    const slots = Array.isArray(detail.slots) ? detail.slots : []
    const answer = await confirm({ message: detail.message, slots }, init.signal)
    if (!answer || (answer !== "continue" && !slots.includes(answer)) || init.signal?.aborted) {
      return Response.json({ detail: "Sloti nuk u ndryshua." }, { status: 409 })
    }
    choice = answer
    affectedAssignees = Array.isArray(detail.assignee_ids) ? new Set(detail.assignee_ids) : null
    return send(confirmedRequest(init, headers))
  }
}

export async function withTaskReportingChoice(
  path: string,
  init: RequestInit,
  send: (init: RequestInit) => Promise<Response>,
  explain: (details: ReportingChoiceDetails, signal?: AbortSignal | null) => Promise<string | null>,
): Promise<Response> {
  let response = await send(init)
  if (init.method?.toUpperCase() !== "PATCH" || typeof init.body !== "string"
      || !/^\/tasks\/[^/?]+(?:\/(?:one-h-report-slot|one-h-marker))?(?:\?|$)/.test(path)) return response
  let body
  let confirmations
  while (response.status === 409 && !init.signal?.aborted) {
    let detail
    try { detail = (await response.clone().json()).detail } catch { return response }
    if (detail?.code !== "TASK_REPORTING_CHOICE_REASON_REQUIRED") return response
    body ??= JSON.parse(init.body)
    confirmations ??= { ...body.reporting_choice_confirmations }
    const reason = await explain(detail, init.signal)
    if (!reason?.trim() || init.signal?.aborted) {
      return Response.json({ detail: "Ndryshimi u anulua." }, { status: 409 })
    }
    confirmations[detail.field] = { key: detail.key, reason: reason.trim() }
    response = await send({ ...init, body: JSON.stringify({ ...body, reporting_choice_confirmations: confirmations }) })
  }
  return response
}
