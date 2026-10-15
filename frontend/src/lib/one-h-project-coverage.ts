export type ProjectTaskCoverage = {
  date: string
  department_name?: string | null
  projectTaskAssigneesByPeriod?: Partial<Record<"AM" | "PM", string[]>>
}

export function isProjectCoverageDepartment(department?: string | null): boolean {
  return ["PCM", "GD", "GDS", "GRAPHIC DESIGN", "PRODUCT CONTENT", "PROJECT CONTENT", "PROJECT CONTENT MANAGER"]
    .includes((department || "").trim().toUpperCase())
}

export function projectUsersForOneHSlot(
  projects: ProjectTaskCoverage[],
  date: string,
  slot: string,
): Set<string> {
  const period = ["10:00", "11:00", "11:50"].includes(slot)
    ? "AM"
    : ["14:20", "16:00"].includes(slot) ? "PM" : null
  if (!period) return new Set()
  return new Set(projects
    .filter((project) => project.date === date && isProjectCoverageDepartment(project.department_name))
    .flatMap((project) => project.projectTaskAssigneesByPeriod?.[period] ?? []))
}
