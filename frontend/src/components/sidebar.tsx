"use client"

import * as React from "react"
import Image from "next/image"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { 
  LayoutDashboard, 
  Video,
  Globe, 
  Code2, 
  FileText, 
  FileSpreadsheet,
  Palette, 
  CalendarDays, 
  CalendarRange, 
  BarChart3, 
  ListTodo,
  Users, 
  Settings,
  Layers,
  ClipboardCheck,
  StickyNote,
  CalendarClock,
  Briefcase,
  DollarSign,
  FolderLock,
  Clock3,
  MailCheck,
  Shield,
  PanelLeftClose,
  Gem,
  Activity,
  ChevronDown,
  ScrollText,
  TicketCheck,
  Brain,
  BrainCircuit,
  BookOpen,
  Sparkles,
  BookA,
  Scale,
  GraduationCap,
  type LucideIcon
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useAuth } from "@/lib/auth"
import type { UserRole } from "@/lib/types"
import { useSidebar } from "./sidebar-context"
import { useWaitingConfirmationGa } from "./waiting-confirmation-ga-context"

// 1. Add an 'icon' property to your type definition
type NavItem = { 
  href: string; 
  label: string; 
  icon: LucideIcon;
  match?: string[];
  exact?: boolean;
  roles?: UserRole[] 
}

type NavSubgroup = {
  id: string
  label: string
  icon: LucideIcon
  items: NavItem[]
}

type NavGroup = {
  id: string
  label: string
  icon: LucideIcon
  items: NavItem[]
  subgroups?: NavSubgroup[]
}

const primaryItems: NavItem[] = [
  { href: "/meeting-recordings", label: "Regjistrimet", icon: Video },
  { 
    href: "/dashboard", 
    label: "Dashboard", 
    icon: LayoutDashboard 
  },
  { 
    href: "/common", 
    label: "Common View", 
    icon: Globe 
  },
  {
    href: "/ga-ka-notes",
    label: "PX Notes",
    icon: StickyNote,
  },
  { href: "/mira", label: "Mira", icon: Brain },
  {
    href: "/next-week-plan",
    label: "PX JAV",
    icon: CalendarClock,
  },
  {
    href: "/admin-tasks",
    label: "Admin Tasks",
    icon: ClipboardCheck,
  },
  {
    href: "/waiting-confirmation-ga",
    label: "WFC",
    icon: Clock3,
  },
]

const gaReportItems: NavItem[] = [
  { href: "/today-print-report", label: "1H SHTYPI Today", icon: MailCheck },
  { href: "/tomorrow-print-report", label: "1H SHTYPI Tomorrow", icon: MailCheck },
  { href: "/morning-report", label: "M1 Start of Day", icon: MailCheck },
  { href: "/after-break-report", label: "M2 Post-Break Summary", icon: MailCheck },
  { href: "/meetings-report", label: "M3 End of Day", icon: MailCheck },
  { href: "/m1-reporting-points", label: "M1 PIKAT PER RAP", icon: ClipboardCheck },
  { href: "/m2-reporting-points", label: "M2 PIKAT PER RAP", icon: ClipboardCheck },
  { href: "/m3-reporting-points", label: "M3 PIKAT PER RAP", icon: ClipboardCheck },
]

const gaReportHrefs = new Set(gaReportItems.map((item) => item.href))

const navGroups: NavGroup[] = [
  {
    id: "team",
    label: "Ekipi",
    icon: Users,
    items: [{ href: "/skills", label: "Matrica e Aftësive", icon: BrainCircuit }],
  },
  {
    id: "knowledge-px",
    label: "Knowledge PX",
    icon: BookOpen,
    items: [
      { href: "/knowledge/prompts", label: "Prompts", icon: Sparkles },
      { href: "/knowledge/definime", label: "Definime", icon: BookA },
      { href: "/knowledge/rregullore", label: "Rregullore", icon: Scale },
      { href: "/knowledge/trajnime", label: "Trajnime", icon: GraduationCap },
    ],
  },
  {
    id: "tasks",
    label: "Tasks",
    icon: ListTodo,
    items: [
      { href: "/primeflow-classifications", label: "Classifications", icon: Layers },
      { href: "/primeflow-pyetje", label: "Questions", icon: ClipboardCheck },
      { href: "/system-tasks", label: "System Tasks", icon: Layers },
      { href: "/open-tasks", label: "Open Tasks", icon: ListTodo },
    ],
  },
  {
    id: "departments",
    label: "Departments",
    icon: Briefcase,
    items: [
      {
        href: "/departments/development",
        label: "Development",
        icon: Code2,
        match: ["/departments/development", "/projects/dev"],
      },
      {
        href: "/departments/project-content-manager",
        label: "Product Content",
        icon: FileText,
        match: ["/departments/project-content-manager", "/projects/pcm"],
      },
      {
        href: "/departments/graphic-design",
        label: "Graphic Design",
        icon: Palette,
        match: ["/departments/graphic-design", "/projects/design"],
      },
      {
        href: "/departments/human-resource",
        label: "Human Resources",
        icon: Briefcase,
        match: ["/departments/human-resource"],
      },
      {
        href: "/departments/finance",
        label: "Finance",
        icon: DollarSign,
        match: ["/departments/finance"],
      },
    ],
  },
  {
    id: "planning",
    label: "Planning",
    icon: CalendarDays,
    items: [
      { href: "/weekly-planner", label: "Weekly Planner", icon: CalendarDays },
      { href: "/monthly-planner", label: "Monthly Planner", icon: CalendarRange },
      { href: "/meeting-scheduler", label: "Meeting Scheduler", icon: CalendarClock },
      {
        href: "/realization",
        label: "Realization",
        icon: Activity,
        roles: ["ADMIN", "MANAGER", "STAFF"],
      },
    ],
  },
  {
    id: "reports",
    label: "Reports & Control",
    icon: BarChart3,
    items: [
      { href: "/today-print-report", label: "1H SHTYPI Today", icon: MailCheck },
      { href: "/tomorrow-print-report", label: "1H SHTYPI Tomorrow", icon: MailCheck },
      {
        href: "/admin/1h-reports",
        label: "1H Reports",
        icon: MailCheck,
      },
      { href: "/system-task-instances", label: "System Tasks Report", icon: Layers },
      { href: "/external-tickets", label: "STD Tickets EXT", icon: TicketCheck },
      { href: "/reviews", label: "Reviews", icon: Gem },
      { href: "/reports", label: "Reports & Exports", icon: BarChart3, exact: true },
      { href: "/reports/rlz-daily-control", label: "Kontrolli ditor RLZ", icon: Activity },
      {
        href: "/reports/weekly-planning-audit",
        label: "Weekly Planning Check",
        icon: FileSpreadsheet,
      },
      {
        href: "/reports/px-jav-weekly",
        label: "PX JAV – Kontrolli",
        icon: FileText,
      },
      {
        href: "/end-week-bz-report",
        label: "PIKAT E BZ FIN JAV",
        icon: MailCheck,
      },
    ],
    subgroups: [
      {
        id: "meetings",
        label: "Meetings",
        icon: MailCheck,
        items: [
          { href: "/morning-report", label: "M1 Start of Day", icon: MailCheck },
          { href: "/after-break-report", label: "M2 Post-Break Summary", icon: MailCheck },
          { href: "/meetings-report", label: "M3 End of Day", icon: MailCheck },
          { href: "/m1-reporting-points", label: "M1 PIKAT PER RAP", icon: ClipboardCheck },
          { href: "/m2-reporting-points", label: "M2 PIKAT PER RAP", icon: ClipboardCheck },
          { href: "/m3-reporting-points", label: "M3 PIKAT PER RAP", icon: ClipboardCheck },
        ],
      },
    ],
  },
  {
    id: "administration",
    label: "Administration",
    icon: Settings,
    items: [
      { href: "/platforms", label: "PrimexEU Links", icon: Shield },
      { href: "/file-access", label: "File Access", icon: FolderLock },
      { href: "/discord", label: "Asistenti Discord", icon: Sparkles },
      { href: "/users", label: "Users", icon: Users, roles: ["ADMIN", "MANAGER"] },
      { href: "/settings", label: "Settings", icon: Settings, roles: ["ADMIN", "MANAGER"] },
    ],
  },
]

export function Sidebar({ role }: { role: UserRole }) {
  const pathname = usePathname()
  const router = useRouter()
  const { apiFetch, prefetchApiFetch, user } = useAuth()
  const isGaUser = [user?.username, user?.email?.split("@")[0]]
    .some((value) => value?.trim().toLowerCase() === "gane.arifaj")
  const currentUserId = user?.id
  const [gaPersonalAvailable, setGaPersonalAvailable] = React.useState(false)
  React.useEffect(() => {
    let cancelled = false
    setGaPersonalAvailable(false)
    if (currentUserId) void apiFetch("/ga-personal/access", { cache: "no-store" })
      .then(async (response) => response.ok ? response.json() : null)
      .then((access) => { if (!cancelled) setGaPersonalAvailable(access?.available === true) })
      .catch(() => { if (!cancelled) setGaPersonalAvailable(false) })
    return () => { cancelled = true }
  }, [apiFetch, currentUserId])
  const { isOpen, isDesktop, setIsOpen } = useSidebar()
  const { count } = useWaitingConfirmationGa()
  const excelStandardsActive = pathname === "/standards/excel" || pathname.startsWith("/standards/excel/")
  const wordStandardsActive = pathname === "/standards/word" || pathname.startsWith("/standards/word/")
  const standardsActive = excelStandardsActive || wordStandardsActive
  const [standardsOpen, setStandardsOpen] = React.useState(standardsActive)
  const [resolvedProjectRoute, setResolvedProjectRoute] = React.useState<"dev" | "pcm" | "design" | null>(null)
  const genericProjectId = React.useMemo(() => {
    const match = pathname.match(/^\/projects\/([^/]+)$/)
    return match ? decodeURIComponent(match[1]) : null
  }, [pathname])

  React.useEffect(() => {
    if (standardsActive) setStandardsOpen(true)
  }, [standardsActive])

  React.useEffect(() => {
    if (!genericProjectId) {
      setResolvedProjectRoute(null)
      return
    }

    let cancelled = false

    const resolveProjectRoute = async () => {
      try {
        const [projectRes, departmentsRes] = await Promise.all([
          apiFetch(`/projects/${genericProjectId}`),
          apiFetch("/departments"),
        ])

        if (!projectRes.ok || !departmentsRes.ok) {
          if (!cancelled) setResolvedProjectRoute(null)
          return
        }

        const project = (await projectRes.json()) as { department_id?: string | null }
        const departments = (await departmentsRes.json()) as Array<{ id: string; name: string; code?: string | null }>
        const department = departments.find((item) => item.id === project.department_id) || null
        const departmentKey = (department?.code || department?.name || "").trim().toLowerCase()

        let nextRoute: "dev" | "pcm" | "design" | null = null
        if (departmentKey === "development" || departmentKey === "dev") nextRoute = "dev"
        else if (
          departmentKey === "graphic design" ||
          departmentKey === "graphic-design" ||
          departmentKey === "gd"
        ) nextRoute = "design"
        else if (
          departmentKey === "project content manager" ||
          departmentKey === "project-content-manager" ||
          departmentKey === "pcm"
        ) nextRoute = "pcm"

        if (!cancelled) setResolvedProjectRoute(nextRoute)
      } catch {
        if (!cancelled) setResolvedProjectRoute(null)
      }
    }

    void resolveProjectRoute()

    return () => {
      cancelled = true
    }
  }, [apiFetch, genericProjectId])

  React.useEffect(() => {
    if (!currentUserId) return
    const warmReferenceData = () => {
      void Promise.all([prefetchApiFetch("/departments"), prefetchApiFetch("/users/lookup")])
    }
    if (typeof window.requestIdleCallback === "function") {
      const idleId = window.requestIdleCallback(warmReferenceData, { timeout: 1500 })
      return () => window.cancelIdleCallback(idleId)
    }
    const timeoutId = window.setTimeout(warmReferenceData, 250)
    return () => window.clearTimeout(timeoutId)
  }, [currentUserId, prefetchApiFetch])

  const prefetchDepartmentData = React.useCallback(
    (href: string) => {
      if (!currentUserId) return
      void import("@/lib/department-prefetch")
        .then((module) => module.prefetchDepartmentData(href, currentUserId, prefetchApiFetch))
        .catch(() => {
          // Route loading remains the fallback when the optional prefetch chunk fails.
        })
    },
    [currentUserId, prefetchApiFetch]
  )

  const projectRoute =
    pathname.startsWith("/projects/pcm")
      ? "pcm"
      : pathname.startsWith("/projects/design")
        ? "design"
        : pathname.startsWith("/projects/dev")
          ? "dev"
          : genericProjectId
            ? resolvedProjectRoute
            : null

  const canViewItem = React.useCallback(
    (item: NavItem) => !item.roles || item.roles.includes(role),
    [role]
  )

  const isItemActive = React.useCallback(
    (item: NavItem) => {
      const matchTargets = item.match || [item.href]
      return (
        matchTargets.some((target) =>
          item.exact ? pathname === target : pathname === target || pathname.startsWith(target + "/")
        ) ||
        (item.label === "Development" && projectRoute === "dev") ||
        (item.label === "Product Content" && projectRoute === "pcm") ||
        (item.label === "Graphic Design" && projectRoute === "design")
      )
    },
    [pathname, projectRoute]
  )

  const visibleGroups = React.useMemo(
    () =>
      navGroups
        .map((group) => ({
          ...group,
          items: group.items.filter((item) => canViewItem(item) && (!isGaUser || !gaReportHrefs.has(item.href))),
          subgroups: (group.subgroups || [])
            .map((subgroup) => ({
              ...subgroup,
              items: subgroup.items.filter((item) => canViewItem(item) && (!isGaUser || !gaReportHrefs.has(item.href))),
            }))
            .filter((subgroup) => subgroup.items.length > 0),
        }))
        .filter((group) => group.items.length > 0 || (group.subgroups?.length ?? 0) > 0),
    [canViewItem, isGaUser]
  )

  const groupHasActiveItem = React.useCallback(
    (group: (typeof visibleGroups)[number]) =>
      group.items.some(isItemActive) ||
      (group.subgroups || []).some((subgroup) => subgroup.items.some(isItemActive)),
    [isItemActive]
  )

  const activeGroupId = React.useMemo(
    () => visibleGroups.find((group) => groupHasActiveItem(group))?.id ?? null,
    [groupHasActiveItem, visibleGroups]
  )
  const [openGroupId, setOpenGroupId] = React.useState<string | null>(null)
  const [openSubgroupId, setOpenSubgroupId] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (activeGroupId) setOpenGroupId(activeGroupId)
  }, [activeGroupId])

  React.useEffect(() => {
    const activeSubgroup = visibleGroups
      .flatMap((group) => group.subgroups || [])
      .find((subgroup) => subgroup.items.some(isItemActive))
    if (activeSubgroup) setOpenSubgroupId(activeSubgroup.id)
  }, [isItemActive, visibleGroups])

  const renderNavItem = (item: NavItem, nested = false) => {
    const active = isItemActive(item)
    const displayLabel =
      item.href === "/waiting-confirmation-ga" ? `${item.label} (${count})` : item.label

    return (
      <Link
        key={item.href}
        href={item.href}
        prefetch={false}
        onMouseEnter={() => {
          router.prefetch(item.href)
          prefetchDepartmentData(item.href)
        }}
        onFocus={() => {
          router.prefetch(item.href)
          prefetchDepartmentData(item.href)
        }}
        onClick={() => {
          if (!isDesktop) setIsOpen(false)
        }}
        className={cn(
          "group flex items-center gap-3 rounded-md py-2.5 text-sm font-medium transition-colors",
          nested ? "pl-9 pr-3" : "px-3",
          "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
          active
            ? "bg-sidebar-accent text-sidebar-accent-foreground"
            : "text-muted-foreground"
        )}
      >
        <item.icon
          className={cn(
            "h-4 w-4 shrink-0 transition-colors",
            active ? "text-primary" : "text-muted-foreground group-hover:text-foreground"
          )}
        />
        <span className="min-w-0 truncate">{displayLabel}</span>
      </Link>
    )
  }

  return (
    <>
      {/* Mobile backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-[100] md:hidden"
          aria-hidden="true"
          onClick={() => setIsOpen(false)}
        />
      )}
      
      <aside
        className={cn(
          "fixed md:sticky md:top-0 left-0 z-[110] md:z-50 w-64 shrink-0 overflow-hidden border-r bg-sidebar text-sidebar-foreground flex flex-col h-screen md:h-[100vh] print:hidden transition-[width,transform] duration-300 ease-in-out",
          isOpen ? "translate-x-0 md:w-64" : "-translate-x-full md:w-0 md:translate-x-0 md:border-r-0"
        )}
        style={{ touchAction: "pan-y" }}
      >
        {/* Header / Logo Area */}
        <div className="flex h-20 w-64 items-center justify-between border-b px-3">
          <Link
            href="/dashboard"
            className="flex h-full min-w-0 flex-1 items-center justify-center px-2"
            aria-label="PrimeFlow dashboard"
          >
            <Image
              src="/primeflow-sidebar-logo-transparent.png"
              alt="Prime Flow"
              width={160}
              height={58}
              priority
              className="h-auto max-h-[54px] w-full max-w-[160px] object-contain"
            />
          </Link>
          <button
            onClick={() => setIsOpen(false)}
            className="p-2 rounded-md hover:bg-sidebar-accent transition-colors"
            aria-label="Close sidebar"
            title="Close sidebar"
          >
            <PanelLeftClose className="h-5 w-5" />
          </button>
        </div>

      {/* Navigation Links */}
      <nav className="w-64 flex-1 overflow-y-auto py-4 px-3 space-y-1">
        {gaPersonalAvailable && renderNavItem({ href: "/ga-personal", label: "GA PERSONAL", icon: FolderLock })}
        {primaryItems
          .flatMap((item) => isGaUser && item.href === "/admin-tasks" ? [item, ...gaReportItems] : [item])
          .filter(canViewItem)
          .map((item) => renderNavItem(item))}

        <div className="my-2 border-t border-sidebar-border" />

        {visibleGroups.map((group) => {
          const isExpanded = openGroupId === group.id
          const containsActiveItem = groupHasActiveItem(group)

          return (
            <div key={group.id}>
              <button
                type="button"
                aria-expanded={isExpanded}
                aria-controls={`sidebar-group-${group.id}`}
                onClick={() => setOpenGroupId((current) => (current === group.id ? null : group.id))}
                className={cn(
                  "group flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm font-semibold transition-colors",
                  "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                  containsActiveItem ? "text-sidebar-accent-foreground" : "text-muted-foreground"
                )}
              >
                <group.icon
                  className={cn(
                    "h-4 w-4 shrink-0 transition-colors",
                    containsActiveItem
                      ? "text-primary"
                      : "text-muted-foreground group-hover:text-foreground"
                  )}
                />
                <span className="min-w-0 flex-1 truncate">{group.label}</span>
                <ChevronDown
                  className={cn(
                    "h-4 w-4 shrink-0 transition-transform duration-200",
                    isExpanded && "rotate-180"
                  )}
                />
              </button>

              {isExpanded && (
                <div id={`sidebar-group-${group.id}`} className="mt-1 space-y-1">
                  {(group.subgroups || []).map((subgroup) => {
                    const subgroupExpanded = openSubgroupId === subgroup.id
                    const subgroupActive = subgroup.items.some(isItemActive)
                    return (
                      <div key={subgroup.id}>
                        <button
                          type="button"
                          aria-expanded={subgroupExpanded}
                          aria-controls={`sidebar-subgroup-${subgroup.id}`}
                          onClick={() =>
                            setOpenSubgroupId((current) => (current === subgroup.id ? null : subgroup.id))
                          }
                          className={cn(
                            "group flex w-full items-center gap-3 rounded-md py-2.5 pl-9 pr-3 text-left text-sm font-medium transition-colors",
                            "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                            subgroupActive ? "text-sidebar-accent-foreground" : "text-muted-foreground"
                          )}
                        >
                          <subgroup.icon
                            className={cn(
                              "h-4 w-4 shrink-0 transition-colors",
                              subgroupActive
                                ? "text-primary"
                                : "text-muted-foreground group-hover:text-foreground"
                            )}
                          />
                          <span className="min-w-0 flex-1 truncate">{subgroup.label}</span>
                          <ChevronDown
                            className={cn(
                              "h-4 w-4 shrink-0 transition-transform duration-200",
                              subgroupExpanded && "rotate-180"
                            )}
                          />
                        </button>
                        {subgroupExpanded ? (
                          <div id={`sidebar-subgroup-${subgroup.id}`} className="mt-1 space-y-1">
                            {subgroup.items.map((item) => (
                              <Link
                                key={item.href}
                                href={item.href}
                                prefetch={false}
                                onMouseEnter={() => {
                                  router.prefetch(item.href)
                                  prefetchDepartmentData(item.href)
                                }}
                                onFocus={() => {
                                  router.prefetch(item.href)
                                  prefetchDepartmentData(item.href)
                                }}
                                onClick={() => {
                                  if (!isDesktop) setIsOpen(false)
                                }}
                                className={cn(
                                  "group flex items-center gap-3 rounded-md py-2.5 pl-14 pr-3 text-sm font-medium transition-colors",
                                  "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                                  isItemActive(item)
                                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                                    : "text-muted-foreground"
                                )}
                              >
                                <item.icon
                                  className={cn(
                                    "h-4 w-4 shrink-0 transition-colors",
                                    isItemActive(item)
                                      ? "text-primary"
                                      : "text-muted-foreground group-hover:text-foreground"
                                  )}
                                />
                                <span className="min-w-0 truncate">{item.label}</span>
                              </Link>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    )
                  })}
                  {group.items.map((item) => renderNavItem(item, true))}
                </div>
              )}
            </div>
          )
        })}
        <div className="pt-1">
          <button
            type="button"
            onClick={() => setStandardsOpen((current) => !current)}
            className={cn(
              "group flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
              "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
              standardsActive ? "bg-sidebar-accent text-sidebar-accent-foreground" : "text-muted-foreground"
            )}
            aria-expanded={standardsOpen}
          >
            <ScrollText className={cn("h-4 w-4 shrink-0", standardsActive ? "text-primary" : "text-muted-foreground")} />
            <span className="flex-1 text-left normal-case">Standards</span>
            <ChevronDown className={cn("h-4 w-4 transition-transform", standardsOpen && "rotate-180")} />
          </button>
          {standardsOpen ? (
            <div className="space-y-1">
              <Link
                href="/standards/excel"
                onMouseEnter={() => router.prefetch("/standards/excel")}
                onFocus={() => router.prefetch("/standards/excel")}
                onClick={() => {
                  if (!isDesktop) setIsOpen(false)
                }}
                className={cn(
                  "ml-6 mt-1 flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                  excelStandardsActive ? "bg-sidebar-accent text-sidebar-accent-foreground" : "text-muted-foreground"
                )}
              >
                <FileSpreadsheet className={cn("h-4 w-4", excelStandardsActive ? "text-primary" : "text-muted-foreground")} />
                Excel
              </Link>
              <Link
                href="/standards/word"
                onMouseEnter={() => router.prefetch("/standards/word")}
                onFocus={() => router.prefetch("/standards/word")}
                onClick={() => {
                  if (!isDesktop) setIsOpen(false)
                }}
                className={cn(
                  "ml-6 flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  "hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                  wordStandardsActive ? "bg-sidebar-accent text-sidebar-accent-foreground" : "text-muted-foreground"
                )}
              >
                <FileText className={cn("h-4 w-4", wordStandardsActive ? "text-primary" : "text-muted-foreground")} />
                Word
              </Link>
            </div>
          ) : null}
        </div>
      </nav>

      {/* Optional: User Profile / Footer area could go here */}
    </aside>
    </>
  )
}

