type TaskDates = { startDateIso: string; dueDateIso: string }

type TemplateAlignment = {
  alignment_user_ids?: string[] | null
  alignment_roles?: string[] | null
  alignment_time?: string | null
  requires_alignment?: boolean | null
}

export function financeUserInitials(label: string) {
  return label.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("")
}

export function financeTaskMatchesDates({ startDateIso, dueDateIso }: TaskDates, from: string, to: string) {
  if (!from && !to) return true
  if (!startDateIso && !dueDateIso) return false

  const [taskStart, taskEnd] = [startDateIso || dueDateIso, dueDateIso || startDateIso].sort()
  const [filterStart, filterEnd] = [from || to, to || from].sort()
  return taskStart <= filterEnd && taskEnd >= filterStart
}

export function financeTaskAlignment(
  taskUserIds: string[] | null | undefined,
  template: TemplateAlignment | undefined,
  labels: ReadonlyMap<string, string>,
) {
  const userIds = [...new Set([...(taskUserIds ?? []), ...(template?.alignment_user_ids ?? [])])]
  const time = template?.alignment_time?.match(/^\d{2}:\d{2}/)?.[0] || template?.alignment_time || ""
  const people = userIds.map((id) => financeUserInitials(labels.get(id) || "")).filter(Boolean).join(", ")
  const roles = template?.alignment_roles?.join(", ")
  const withLabel = people || roles || (userIds.length || template?.requires_alignment || time ? "BZ" : "")
  return { userIds, withLabel, time }
}

export function financeTaskMatchesPerson(row: { assigneeIds: string[]; alignment: { userIds: string[] } }, userId: string) {
  return row.assigneeIds.includes(userId) || row.alignment.userIds.includes(userId)
}
