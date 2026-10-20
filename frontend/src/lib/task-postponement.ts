export type PostponementExplanation = {
  postponement_reason_code: string
  postponement_comment: string
}

export type PostponementDetails = {
  task_id: string
  task_title: string
  changes: { field: "start_date" | "due_date"; from: string; to: string }[]
}

export async function withPostponementExplanation(
  path: string,
  init: RequestInit,
  send: (request: RequestInit) => Promise<Response>,
  explain: (details: PostponementDetails, signal?: AbortSignal | null) => Promise<PostponementExplanation | null>,
): Promise<Response> {
  const response = await send(init)
  if (response.status !== 409 || init.method?.toUpperCase() !== "PATCH" || typeof init.body !== "string"
      || !/^\/(?:tasks\/[^/?]+|system-tasks\/occurrence-date)(?:\?|$)/.test(path)) return response
  let detail
  try { detail = (await response.clone().json()).detail } catch { return response }
  if (detail?.code !== "TASK_POSTPONEMENT_EXPLANATION_REQUIRED") return response
  const explanation = await explain(detail, init.signal)
  if (init.signal?.aborted || !explanation?.postponement_reason_code?.trim() || !explanation.postponement_comment?.trim()) {
    return Response.json({ detail: "Shtyrja u anulua. Data nuk u ndryshua." }, { status: 409 })
  }
  // The first write was rejected before mutation. A lost successful write is never retried here.
  return send({ ...init, body: JSON.stringify({ ...JSON.parse(init.body),
    postponement_reason_code: explanation.postponement_reason_code.trim(),
    postponement_comment: explanation.postponement_comment.trim(),
  }) })
}
