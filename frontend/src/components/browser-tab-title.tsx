"use client"

import * as React from "react"
import { usePathname, useSearchParams } from "next/navigation"
import { browserTabTitle } from "@/lib/browser-tab-title"

type PageTitle = { pathname: string; title: string }
const Context = React.createContext<React.Dispatch<React.SetStateAction<PageTitle | null>> | null>(null)

function RouteTabTitle({ pageTitle }: { pageTitle: PageTitle | null }) {
  const pathname = usePathname()
  const params = useSearchParams()
  const title = pageTitle?.pathname === pathname ? pageTitle.title : browserTabTitle(pathname, params)
  React.useEffect(() => { document.title = title }, [title, pathname, params])
  return null
}

export function BrowserTabTitleProvider({ children }: { children: React.ReactNode }) {
  const [pageTitle, setPageTitle] = React.useState<PageTitle | null>(null)
  return <Context.Provider value={setPageTitle}>
    <React.Suspense fallback={null}><RouteTabTitle pageTitle={pageTitle} /></React.Suspense>
    {children}
  </Context.Provider>
}

/** Lets views with local controls (Department / My View) name their current tab. */
export function useBrowserTabTitle(title: string) {
  const pathname = usePathname()
  const setPageTitle = React.useContext(Context)
  React.useEffect(() => {
    if (!setPageTitle) return
    const entry = { pathname, title }
    setPageTitle(entry)
    return () => setPageTitle((current) => current === entry ? null : current)
  }, [pathname, title, setPageTitle])
}
