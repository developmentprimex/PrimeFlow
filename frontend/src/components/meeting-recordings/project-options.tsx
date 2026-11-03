import type { Department, Project } from "@/lib/types"

export function RecordingProjectOptions({ projects, departments }: {
  projects: Project[]
  departments: Department[]
}) {
  const names = new Map(departments.map(department => [department.id, department.name]))
  const groups = new Map<string, Project[]>()
  for (const project of projects) {
    const department = project.department_id || ""
    const group = groups.get(department) || []
    group.push(project)
    groups.set(department, group)
  }
  const label = (id: string) => id ? names.get(id) || "Departament tjetër" : "Pa departament"
  const title = (project: Project) => project.display_title || project.title || project.name || project.id
  return <>{[...groups].sort(([a], [b]) => {
    if (!a) return 1
    if (!b) return -1
    return label(a).localeCompare(label(b), "sq")
  }).map(([id, items]) => <optgroup key={id} label={label(id)}>
    {[...items].sort((a, b) => title(a).localeCompare(title(b), "sq", { numeric: true }))
      .map(project => <option key={project.id} value={project.id}>{title(project)}</option>)}
  </optgroup>)}</>
}
