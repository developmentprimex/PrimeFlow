"use client"

import * as React from "react"
import { useRouter } from "next/navigation"

import { LazyCommandPalette } from "@/components/lazy-command-palette"
import { Sidebar } from "@/components/sidebar"
import { Topbar } from "@/components/topbar"
import { SidebarProvider } from "@/components/sidebar-context"
import { WaitingConfirmationGaProvider } from "@/components/waiting-confirmation-ga-context"
import { MarkerCommentsPanel, MarkerCommentsProvider } from "@/components/marker-comments-context"
import { useAuth } from "@/lib/auth"
import { BrowserTabTitleProvider } from "@/components/browser-tab-title"
import { RecorderProvider } from "@/components/meeting-recordings/recorder-provider"

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const { user, loading } = useAuth()

  React.useEffect(() => {
    if (!loading && !user) router.push("/login")
  }, [loading, user, router])

  if (loading) {
    return <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground">Loading...</div>
  }
  if (!user) return null

  return (
    <RecorderProvider key={user.id}>
    <BrowserTabTitleProvider>
    <SidebarProvider>
      <WaitingConfirmationGaProvider>
        <MarkerCommentsProvider key={user.id}>
          <div className="flex min-h-screen print:min-h-0 print:block relative">
            <Sidebar role={user.role} />
            <div className="flex min-w-0 flex-1 flex-col print:block w-full">
              <Topbar />
              <main className="flex-1 p-4 print:p-0"><MarkerCommentsPanel />{children}</main>
            </div>
            <LazyCommandPalette />
          </div>
        </MarkerCommentsProvider>
      </WaitingConfirmationGaProvider>
    </SidebarProvider>
    </BrowserTabTitleProvider>
    </RecorderProvider>
  )
}



