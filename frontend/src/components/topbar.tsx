"use client"

import * as React from "react"
import Link from "next/link"
import { Briefcase, CheckCheck, MessageCircle, PanelLeftOpen, Trash2 } from "lucide-react"
import { toast } from "sonner"

import { AccountMenu } from "@/components/account-menu"
import { VoiceAssistant } from "@/components/voice-assistant"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { useAuth } from "@/lib/auth"
import { API_HTTP_URL } from "@/lib/config"
import type { Notification, User } from "@/lib/types"
import { useSidebar } from "./sidebar-context"
import { useMarkerComments } from "./marker-comments-context"

type RequestTrace = {
  method: string
  path: string
  url: string
  response: Response
}

function initials(user: User) {
  const src = user.full_name || user.username || user.email
  return src
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("")
}

function departmentRoute(department: { name: string; code?: string | null }) {
  const key = (department.code || department.name).trim().toLowerCase().replace(/[_\s]+/g, "-")
  if (["development", "dev"].includes(key)) return "/departments/development"
  if (["project-content-manager", "product-content", "pcm"].includes(key)) return "/departments/project-content-manager"
  if (["graphic-design", "gd"].includes(key)) return "/departments/graphic-design"
  if (["human-resource", "human-resources", "hr"].includes(key)) return "/departments/human-resource"
  if (["finance", "fin"].includes(key)) return "/departments/finance"
  return `/departments/${encodeURIComponent(key)}`
}

export function Topbar() {
  const { user, apiFetch } = useAuth()
  const markerComments = useMarkerComments()
  const unreadComments = markerComments?.unread.length || 0
  const { isOpen, toggle } = useSidebar()
  const [sheetOpen, setSheetOpen] = React.useState(false)
  const [notifications, setNotifications] = React.useState<Notification[]>([])
  const [unreadCount, setUnreadCount] = React.useState(0)
  const [markingAllRead, setMarkingAllRead] = React.useState(false)
  const [deletingAll, setDeletingAll] = React.useState(false)
  const [deletingIds, setDeletingIds] = React.useState<string[]>([])
  const [departmentViewHref, setDepartmentViewHref] = React.useState<string | null>(null)
  const isDev = process.env.NODE_ENV !== "production"
  const apiTargetLabel = React.useMemo(() => API_HTTP_URL, [])

  const getErrorMessage = React.useCallback(async (res: Response, fallback: string) => {
    try {
      const data = (await res.json()) as { detail?: string }
      return data.detail || fallback
    } catch {
      return fallback
    }
  }, [])

  const requestWithTrace = React.useCallback(
    async (path: string, init: RequestInit): Promise<RequestTrace> => {
      const response = await apiFetch(path, init)
      return {
        method: init.method || "GET",
        path,
        url: `${API_HTTP_URL}${path.startsWith("/") ? "" : "/"}${path}`,
        response,
      }
    },
    [apiFetch]
  )

  const buildFailureDescription = React.useCallback(
    async (trace: RequestTrace, fallback: string) => {
      const detail = await getErrorMessage(trace.response, fallback)
      const requestInfo = `${trace.method} ${trace.path} -> ${trace.response.status} ${trace.response.statusText || ""}`.trim()
      return isDev ? `${detail} [${requestInfo}] API: ${apiTargetLabel}` : detail
    },
    [apiTargetLabel, getErrorMessage, isDev]
  )

  const deleteNotificationCompat = React.useCallback(
    async (notificationId: string): Promise<RequestTrace> => {
      const primary = await requestWithTrace(`/notifications/${notificationId}/delete`, { method: "POST" })
      if (primary.response.ok || (primary.response.status !== 404 && primary.response.status !== 405)) {
        return primary
      }
      return requestWithTrace(`/notifications/${notificationId}`, { method: "DELETE" })
    },
    [requestWithTrace]
  )

  const loadAllNotifications = React.useCallback(async () => {
    const res = await apiFetch("/notifications")
    if (!res.ok) return
    const data = (await res.json()) as Notification[]
    setNotifications(data)
  }, [apiFetch])

  const loadUnreadCount = React.useCallback(async () => {
    const res = await apiFetch("/notifications/unread-count")
    if (!res.ok) return
    const data = (await res.json()) as { count: number }
    setUnreadCount(Math.max(0, Number(data.count) || 0))
  }, [apiFetch])

  const handleNotificationsOpenChange = React.useCallback(
    async (open: boolean) => {
      setSheetOpen(open)
      if (!open) return

      await loadAllNotifications()
    },
    [loadAllNotifications]
  )

  const handleMarkAllRead = React.useCallback(async () => {
    if (markingAllRead || unreadCount === 0) return
    setMarkingAllRead(true)
    const trace = await requestWithTrace("/notifications/read-all", { method: "POST" })
    if (!trace.response.ok) {
      toast("Unable to mark notifications as read", {
        description: await buildFailureDescription(trace, "Notifications could not be marked as read."),
      })
      setMarkingAllRead(false)
      return
    }

    const readAt = new Date().toISOString()
    setNotifications((current) =>
      current.map((notification) =>
        notification.read_at ? notification : { ...notification, read_at: readAt }
      )
    )
    setUnreadCount(0)
    setMarkingAllRead(false)
  }, [buildFailureDescription, markingAllRead, requestWithTrace, unreadCount])

  const handleDeleteNotification = React.useCallback(
    async (notificationId: string) => {
      setDeletingIds((current) => [...current, notificationId])
      const trace = await deleteNotificationCompat(notificationId)
      if (!trace.response.ok) {
        toast("Unable to delete notification", {
          description: await buildFailureDescription(trace, "The notification could not be deleted."),
        })
        setDeletingIds((current) => current.filter((id) => id !== notificationId))
        return
      }
      setNotifications((current) => {
        const removed = current.find((notification) => notification.id === notificationId)
        if (removed && !removed.read_at) {
          setUnreadCount((count) => Math.max(0, count - 1))
        }
        return current.filter((notification) => notification.id !== notificationId)
      })
      setDeletingIds((current) => current.filter((id) => id !== notificationId))
    },
    [buildFailureDescription, deleteNotificationCompat]
  )

  const handleDeleteAllNotifications = React.useCallback(async () => {
    if (deletingAll) return
    setDeletingAll(true)
    const trace = await requestWithTrace("/notifications/delete-all", { method: "POST" })
    if (!trace.response.ok && notifications.length) {
      if (trace.response.status === 404 || trace.response.status === 405) {
        const results = await Promise.all(notifications.map((notification) => deleteNotificationCompat(notification.id)))
        const failedTrace = results.find((result) => !result.response.ok)
        if (!failedTrace) {
          setNotifications([])
          setUnreadCount(0)
          toast("Notifications deleted", {
            description: "All notifications have been removed.",
          })
          setDeletingAll(false)
          return
        }
        toast("Unable to delete notifications", {
          description: await buildFailureDescription(failedTrace, "Some notifications could not be deleted."),
        })
        setDeletingAll(false)
        return
      }
    }
    if (!trace.response.ok) {
      toast("Unable to delete notifications", {
        description: await buildFailureDescription(trace, "All notifications could not be deleted."),
      })
      setDeletingAll(false)
      return
    }
    setNotifications([])
    setUnreadCount(0)
    toast("Notifications deleted", {
      description: "All notifications have been removed.",
    })
    setDeletingAll(false)
  }, [buildFailureDescription, deleteNotificationCompat, deletingAll, notifications, requestWithTrace])

  React.useEffect(() => {
    const timer = window.setTimeout(() => void loadUnreadCount(), 0)
    return () => window.clearTimeout(timer)
  }, [loadUnreadCount])

  React.useEffect(() => {
    const departmentId = user?.department_id
    if (!departmentId) return
    let cancelled = false
    const loadDepartmentRoute = async () => {
      const response = await apiFetch("/departments")
      if (!response.ok || cancelled) return
      const departments = (await response.json()) as Array<{ id: string; name: string; code?: string | null }>
      const department = departments.find((item) => item.id === departmentId)
      if (!cancelled && department) setDepartmentViewHref(`${departmentRoute(department)}?view=mine&daily=full`)
    }
    void loadDepartmentRoute()
    return () => { cancelled = true }
  }, [apiFetch, user?.department_id])

  React.useEffect(() => {
    const handleNotification = () => {
      void loadUnreadCount()
      if (sheetOpen) {
        void loadAllNotifications()
      }
    }

    window.addEventListener("primex:notification", handleNotification)
    return () => window.removeEventListener("primex:notification", handleNotification)
  }, [loadAllNotifications, loadUnreadCount, sheetOpen])

  if (!user) return null

  return (
    <header className="flex h-14 items-center justify-between border-b px-4 print:hidden">
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="icon"
          onClick={toggle}
          className={isOpen ? "md:hidden" : undefined}
          aria-label="Open sidebar"
          title="Open sidebar"
        >
          <PanelLeftOpen className="h-5 w-5" />
        </Button>
        <div className="text-sm text-muted-foreground hidden md:block">Ctrl+K to search</div>
      </div>
      <div className="flex items-center gap-2">
        {departmentViewHref ? (
          <Button asChild variant="outline">
            <Link href={departmentViewHref} title="Open your department directly in My View">
              <Briefcase className="h-4 w-4" />
              <span className="hidden sm:inline">My View Dep</span>
            </Link>
          </Button>
        ) : null}
        <Button asChild variant="outline" className={unreadComments ? "border-blue-700 bg-[#0055FF] text-white hover:bg-blue-700 hover:text-white" : "border-blue-300 text-blue-700"}>
          <Link href="/comments" aria-label={`Simbole dhe komente, ${unreadComments} të palexuara`} title="Simbolet dhe komentet">
            <MessageCircle className="h-4 w-4" />
            <span className="hidden sm:inline">Komente</span>
            {unreadComments > 0 && <span className="rounded-full bg-white px-1.5 py-0.5 text-xs font-bold text-blue-700" aria-live="polite">{unreadComments}</span>}
          </Link>
        </Button>
        <Sheet open={sheetOpen} onOpenChange={(open) => void handleNotificationsOpenChange(open)}>
          <SheetTrigger asChild>
            <Button variant="outline">
              Notifications{unreadCount ? ` (${unreadCount})` : ""}
            </Button>
          </SheetTrigger>
          <SheetContent>
            <SheetHeader className="pr-12">
              <SheetTitle>Notifications</SheetTitle>
              {isDev ? <div className="text-xs text-muted-foreground">API: {apiTargetLabel}</div> : null}
            </SheetHeader>
            <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
              {notifications.length ? (
                <div className="mb-3 flex flex-wrap justify-end gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={markingAllRead || deletingAll || unreadCount === 0}
                    onClick={() => void handleMarkAllRead()}
                  >
                    <CheckCheck className="mr-1.5 h-4 w-4" />
                    {markingAllRead ? "Marking..." : "Mark all as read"}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={deletingAll || markingAllRead}
                    onClick={() => void handleDeleteAllNotifications()}
                  >
                    {deletingAll ? "Deleting..." : "Delete all"}
                  </Button>
                </div>
              ) : null}
              <div className="space-y-3">
              {notifications.length ? (
                notifications.map((n) => (
                  <div key={n.id} className="rounded-md border p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium">{n.title}</div>
                        {n.body ? <div className="text-sm text-muted-foreground">{n.body}</div> : null}
                        <div className="mt-1 text-xs text-muted-foreground">
                          {n.read_at ? "Read" : "Unread"}
                        </div>
                        {(n.type === "reminder" || n.data?.kind === "task_marker_comment" || n.data?.kind === "task_marker") && typeof n.data?.open_url === "string" ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="mt-2"
                            onClick={() => window.open(n.data?.open_url as string, "_blank", "noopener,noreferrer")}
                          >
                            {n.data?.kind === "task_marker_comment" ? "Lexo komentin" : n.data?.kind === "task_marker" ? n.data?.comment_id ? "Lexo simbolin" : "Hap detyrën" : "Open Meeting"}
                          </Button>
                        ) : null}
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="shrink-0"
                        aria-label="Delete notification"
                        disabled={deletingAll || deletingIds.includes(n.id)}
                        onClick={() => void handleDeleteNotification(n.id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-sm text-muted-foreground">No notifications.</div>
              )}
              </div>
            </div>
          </SheetContent>
        </Sheet>

        <VoiceAssistant key={user.id} />
        <AccountMenu initials={initials(user)} />
      </div>
    </header>
  )
}


