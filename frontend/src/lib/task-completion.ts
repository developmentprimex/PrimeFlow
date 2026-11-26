import type { Task } from "@/lib/types"

type ApiFetch = (path: string, init?: RequestInit) => Promise<Response>

async function readTaskError(response: Response, fallback: string) {
  const body = await response.json().catch(() => null) as { detail?: unknown } | null
  const detail = body?.detail
  const structured = detail && typeof detail === "object"
    ? detail as { code?: unknown; message?: unknown }
    : null
  const message = typeof detail === "string" ? detail : structured?.message
  return {
    code: structured?.code,
    message: typeof message === "string" && message.trim() ? message : fallback,
  }
}

export async function taskResponseError(response: Response, fallback: string) {
  return (await readTaskError(response, fallback)).message
}

export async function updateTaskWithCompletion(
  apiFetch: ApiFetch,
  task: Pick<Task, "id" | "assigned_to" | "assignees">,
  userId: string | undefined,
  updates: Record<string, unknown>,
  fallback: string,
): Promise<Task | null> {
  const path = `/tasks/${task.id}`
  const patch = (url: string, payload: Record<string, unknown>) => apiFetch(url, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })

  let response = await patch(path, updates)
  if (response.ok) return response.json()

  const { code, message } = await readTaskError(response, fallback)
  if (updates.status !== "DONE" || response.status !== 409 ||
      (code !== "RLZ_TASK_COMMENT_REQUIRED" && code !== "RLZ_COMPLETION_OVERRIDE_REASON_REQUIRED")) {
    throw new Error(message)
  }

  const isAssignee = Boolean(userId && (
    task.assigned_to === userId || task.assignees?.some(({ id }) => id === userId)
  ))
  const needsOverride = code === "RLZ_COMPLETION_OVERRIDE_REASON_REQUIRED" && !isAssignee
  const note = window.prompt(needsOverride
    ? "Shkruaj arsyen pse po e mbyll këtë detyrë për përgjegjësin."
    : "Para mbylljes, shto komentin për rezultatin e kësaj detyre.")?.trim()
  if (!note) return null

  if (needsOverride) {
    response = await patch(path, { ...updates, completion_override_reason: note })
  } else {
    const commentResponse = await patch(`${path}/comment`, { comment: note })
    if (!commentResponse.ok) {
      throw new Error(await taskResponseError(commentResponse, "Komenti i rezultatit nuk u ruajt."))
    }
    response = await patch(path, updates)
  }

  if (!response.ok) throw new Error(await taskResponseError(response, fallback))
  return response.json()
}
