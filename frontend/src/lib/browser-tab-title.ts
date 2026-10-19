const PAGE_TITLES: Record<string, string> = {
  "/dashboard": "Dashboard",
  "/common": "Common View",
  "/ga-ka-notes": "PX Notes",
  "/next-week-plan": "PX JAV",
  "/admin-tasks": "Admin Tasks",
  "/waiting-confirmation-ga": "WFC",
  "/comments": "Simbolet dhe komentet",
  "/skills": "Matrica e Aftësive",
  "/knowledge": "Knowledge PX",
  "/knowledge/prompts": "Prompts · Knowledge PX",
  "/knowledge/definime": "Definime · Knowledge PX",
  "/knowledge/rregullore": "Rregullore · Knowledge PX",
  "/knowledge/trajnime": "Trajnime · Knowledge PX",
  "/primeflow-classifications": "Classifications",
  "/primeflow-pyetje": "Questions",
  "/primeflow-notes": "PrimeFlow Notes",
  "/ga-ka-tasks": "GA/KA Tasks",
  "/system-tasks": "System Tasks",
  "/open-tasks": "Open Tasks",
  "/weekly-planner": "Weekly Planner",
  "/monthly-planner": "Monthly Planner",
  "/meeting-scheduler": "Meeting Scheduler",
  "/realization": "Realization",
  "/today-print-report": "1H SHTYPI Today",
  "/tomorrow-print-report": "1H SHTYPI Tomorrow",
  "/admin/1h-reports": "1H Reports",
  "/system-task-instances": "System Tasks Report",
  "/external-tickets": "STD Tickets EXT",
  "/reviews": "Reviews",
  "/reports": "Reports & Exports",
  "/reports/rlz-daily-control": "Kontrolli ditor RLZ",
  "/reports/weekly-planning-audit": "Weekly Planning Check",
  "/reports/px-jav-weekly": "PX JAV · Kontrolli",
  "/end-week-bz-report": "PIKAT E BZ FIN JAV",
  "/morning-report": "M1 Start of Day",
  "/after-break-report": "M2 Post-Break Summary",
  "/meetings-report": "M3 End of Day",
  "/m1-reporting-points": "M1 PIKAT PER RAP",
  "/m2-reporting-points": "M2 PIKAT PER RAP",
  "/m3-reporting-points": "M3 PIKAT PER RAP",
  "/platforms": "PrimexEU Links",
  "/file-access": "File Access",
  "/discord": "Asistenti Discord",
  "/users": "Users",
  "/settings": "Settings",
  "/standards/excel": "Excel Standards",
  "/standards/word": "Word Standards",
}

const DEPARTMENTS: Record<string, string> = {
  development: "Development",
  "graphic-design": "Graphic Design",
  "project-content-manager": "Product Content",
  pcm: "Product Content",
  "human-resource": "Human Resources",
  finance: "Finance",
}

export function browserTabTitle(pathname: string, params: Pick<URLSearchParams, "get">): string {
  const path = pathname.replace(/\/+$/, "") || "/"
  const department = /^\/departments\/([^/]+)$/.exec(path)
  if (department) {
    const name = DEPARTMENTS[department[1]] || "Department"
    return params.get("view") === "mine" ? `My View · ${name}` : name
  }
  if (path === "/comments") {
    return `${PAGE_TITLES[path]} · ${params.get("scope") === "all" ? "Të gjitha" : "Të miat"}`
  }
  if (PAGE_TITLES[path]) return PAGE_TITLES[path]
  const project = /^\/projects\/(?:(dev|pcm|design)\/)?[^/]+$/.exec(path)
  if (project) return project[1] ? `Project · ${{ dev: "Development", pcm: "Product Content", design: "Graphic Design" }[project[1]]}` : "Project"
  if (/^\/tasks\/[^/]+$/.test(path)) return "Task Details"
  return "PrimeFlow"
}
