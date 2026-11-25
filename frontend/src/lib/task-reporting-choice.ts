export type ReportingChoiceDetails = {
  key: string
  field: "slot" | "marker"
  date: string
  person: string
  task_title: string
  label: string
  peers: { owner_id: string; person: string; label: string }[]
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
