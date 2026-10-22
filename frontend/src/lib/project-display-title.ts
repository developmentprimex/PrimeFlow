type ProjectLike = {
  title?: string | null
  name?: string | null
  project_title?: string | null
  display_title?: string | null
}

export function resolveProjectTitle(project?: ProjectLike | null): string {
  if (!project) return ""
  return (
    project.display_title?.trim() ||
    project.project_title?.trim() ||
    project.title?.trim() ||
    project.name?.trim() ||
    ""
  )
}
