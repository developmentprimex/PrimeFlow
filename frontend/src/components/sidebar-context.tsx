"use client"

import * as React from "react"
import { usePathname } from "next/navigation"

import { isPxNotesQuickLaunch } from "@/lib/px-notes-quick"

interface SidebarContextType {
  isOpen: boolean
  isDesktop: boolean
  setIsOpen: (open: boolean) => void
  toggle: () => void
  collapseForPage: () => () => void
}

const SidebarContext = React.createContext<SidebarContextType | undefined>(undefined)
const SIDEBAR_STORAGE_KEY = "primeflow-sidebar-open"

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const [isOpen, setIsOpen] = React.useState(false)
  const [isDesktop, setIsDesktop] = React.useState(false)
  const [pageOverride, setPageOverride] = React.useState<{ pathname: string; isOpen: boolean } | null>(null)
  const hasPageOverride = pageOverride?.pathname === pathname
  const visibleIsOpen = hasPageOverride ? pageOverride.isOpen : isOpen
  const previousPathnameRef = React.useRef<string | null>(null)

  React.useEffect(() => {
    const mediaQuery = window.matchMedia("(min-width: 768px)")

    const syncSidebarForViewport = (event?: MediaQueryListEvent) => {
      const nextIsDesktop = mediaQuery.matches
      setIsDesktop(nextIsDesktop)

      // The PX Notes home screen icon opens straight at the note box, so the
      // menu stays closed. The top bar button opens it.
      if (isPxNotesQuickLaunch()) {
        setIsOpen(false)
        return
      }

      if (!nextIsDesktop) {
        // Rotating a phone back to portrait must not throw the menu over the
        // page the user is reading; it opens only on a fresh load.
        // Admin Tasks is opened on phones straight at the GA time table, so
        // there the menu stays closed even then. The top bar button opens it.
        setIsOpen(!event && !window.location.pathname.startsWith("/admin-tasks"))
        return
      }

      // A phone held sideways is wide enough to count as desktop. The GA time
      // table link is used that way, and the table needs the full width.
      const gaTimeTableView =
        window.location.hash === "#ga-time-table" || window.matchMedia("(pointer: coarse)").matches
      if (window.location.pathname.startsWith("/admin-tasks") && gaTimeTableView) {
        setIsOpen(false)
        return
      }

      const savedPreference = window.localStorage.getItem(SIDEBAR_STORAGE_KEY)
      setIsOpen(savedPreference == null ? true : savedPreference === "true")
    }

    syncSidebarForViewport()
    mediaQuery.addEventListener("change", syncSidebarForViewport)

    return () => mediaQuery.removeEventListener("change", syncSidebarForViewport)
  }, [])

  React.useEffect(() => {
    if (previousPathnameRef.current === null) {
      previousPathnameRef.current = pathname
      return
    }

    if (previousPathnameRef.current === pathname) return
    previousPathnameRef.current = pathname

    if (!isDesktop) {
      setIsOpen(false)
    }
  }, [isDesktop, pathname])

  const setSidebarOpen = React.useCallback((open: boolean) => {
    if (hasPageOverride) {
      setPageOverride((current) => current ? { ...current, isOpen: open } : current)
      return
    }
    setIsOpen(open)

    if (typeof window !== "undefined" && window.matchMedia("(min-width: 768px)").matches) {
      window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(open))
    }
  }, [hasPageOverride])

  const toggle = React.useCallback(() => {
    if (hasPageOverride) {
      setPageOverride((current) => current ? { ...current, isOpen: !current.isOpen } : current)
      return
    }
    setIsOpen((prev) => {
      const next = !prev

      if (typeof window !== "undefined" && window.matchMedia("(min-width: 768px)").matches) {
        window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(next))
      }

      return next
    })
  }, [hasPageOverride])

  // Route-scoped collapse leaves the saved desktop preference untouched.
  const collapseForPage = React.useCallback(() => {
    setPageOverride({ pathname, isOpen: false })
    return () => setPageOverride((current) => current?.pathname === pathname ? null : current)
  }, [pathname])

  const value = React.useMemo(
    () => ({ isOpen: visibleIsOpen, isDesktop, setIsOpen: setSidebarOpen, toggle, collapseForPage }),
    [isDesktop, visibleIsOpen, setSidebarOpen, toggle, collapseForPage]
  )

  return (
    <SidebarContext.Provider value={value}>
      {children}
    </SidebarContext.Provider>
  )
}

export function useSidebar() {
  const context = React.useContext(SidebarContext)
  if (context === undefined) {
    throw new Error("useSidebar must be used within a SidebarProvider")
  }
  return context
}
