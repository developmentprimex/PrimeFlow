export type ProjectTaskCoverage = {
  date: string
  department_name?: string | null
  projectTaskAssigneesByPeriod?: Partial<Record<"AM" | "PM", string[]>>
}

export function isProjectCoverageDepartment(department?: string | null): boolean {
  return ["PCM", "GD", "GDS", "GRAPHIC DESIGN", "PRODUCT CONTENT", "PROJECT CONTENT", "PROJECT CONTENT MANAGER"]
    .includes((department || "").trim().toUpperCase())
}

const oneHSlotPeriod = (slot: string): "AM" | "PM" | null =>
  ["10:00", "11:00", "11:50"].includes(slot) ? "AM" : ["14:20", "16:00"].includes(slot) ? "PM" : null

export function personalUsersForOneHSlot(
  tasks: Array<{ date: string; finishPeriod?: string | null; userId?: string; person?: string; assignees?: string[]; isPersonalTask?: boolean }>,
  date: string,
  slot: string,
  userIdByName: Map<string, string>,
): Set<string> {
  const period = oneHSlotPeriod(slot)
  const users = new Set<string>()
  if (!period) return users
  for (const task of tasks) {
    if (task.date !== date || task.isPersonalTask === false) continue
    const taskPeriod = (task.finishPeriod || "").trim().toUpperCase()
    if (["AM", "PM"].includes(taskPeriod) && taskPeriod !== period) continue
    if (task.userId) users.add(task.userId)
    for (const name of task.assignees?.length ? task.assignees : [task.person || ""]) {
      const id = userIdByName.get(name.trim().toLowerCase())
      if (id) users.add(id)
    }
  }
  return users
}

export function projectUsersForOneHSlot(
  projects: ProjectTaskCoverage[],
  date: string,
  slot: string,
): Set<string> {
  const period = oneHSlotPeriod(slot)
  if (!period) return new Set()
  return new Set(projects
    .filter((project) => project.date === date && isProjectCoverageDepartment(project.department_name))
    .flatMap((project) => project.projectTaskAssigneesByPeriod?.[period] ?? []))
}
