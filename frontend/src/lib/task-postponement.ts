export type PostponementExplanation = {
  postponement_reason_code: string
  postponement_comment: string
}

export type PostponementDetails = {
  task_id: string
  task_title: string
  assignee_name?: string | null
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
      || !/^\/(?:tasks\/[^/?]+|system-tasks\/occurrence-date|(?:ga-notes|plan-notes)\/[^/?]+\/(?:task-bundle|task-deadline))(?:\?|$)/.test(path)) return response
  let detail
  try { detail = (await response.clone().json()).detail } catch { return response }
  if (detail?.code !== "TASK_POSTPONEMENT_EXPLANATION_REQUIRED") return response
  if (Array.isArray(detail.postponements)) {
    const body = JSON.parse(init.body)
    const explanations = { ...body.postponement_explanations }
    for (const task of detail.postponements as PostponementDetails[]) {
      if (init.signal?.aborted) return canceledPostponement()
      const explanation = await explain(task, init.signal)
      if (init.signal?.aborted || !explanation?.postponement_reason_code?.trim() || !explanation.postponement_comment?.trim()) return canceledPostponement()
      explanations[task.task_id] = {
        postponement_reason_code: explanation.postponement_reason_code.trim(),
        postponement_comment: explanation.postponement_comment.trim(),
      }
    }
    return send({ ...init, body: JSON.stringify({ ...body, postponement_explanations: explanations }) })
  }
  const explanation = await explain(detail, init.signal)
  if (init.signal?.aborted || !explanation?.postponement_reason_code?.trim() || !explanation.postponement_comment?.trim()) {
    return canceledPostponement()
  }
  // The first write was rejected before mutation. A lost successful write is never retried here.
  return send({ ...init, body: JSON.stringify({ ...JSON.parse(init.body),
    postponement_reason_code: explanation.postponement_reason_code.trim(),
    postponement_comment: explanation.postponement_comment.trim(),
  }) })
}

function canceledPostponement() {
  return Response.json({ detail: "Shtyrja u anulua. Data nuk u ndryshua." }, { status: 409 })
}
