"use client"

import * as React from "react"
import { usePathname } from "next/navigation"

import { useAuth } from "@/lib/auth"
import type { Task } from "@/lib/types"

type WaitingConfirmationGaContextValue = {
  tasks: Task[]
  count: number
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  applyTaskResult: (task: Task) => void
}

const WaitingConfirmationGaContext = React.createContext<WaitingConfirmationGaContextValue | null>(null)

export function WaitingConfirmationGaProvider({ children }: { children: React.ReactNode }) {
  const { apiFetch, user } = useAuth()
  const pathname = usePathname()
  const [tasks, setTasks] = React.useState<Task[]>([])
  const [count, setCount] = React.useState(0)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)

  const refresh = React.useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      if (!user?.id) {
        setTasks([])
        setCount(0)
        return
      }
      const params = new URLSearchParams({
        status: "WAITING_CONFIRMATION",
        include_done: "false",
        confirmation_assignee_id: user.id,
      })
      const tasksRes = await apiFetch(`/tasks?${params.toString()}`)

      if (!tasksRes.ok) {
        throw new Error("tasks_failed")
      }

      const fetchedTasks = (await tasksRes.json()) as Task[]
      const matchingTasks = fetchedTasks.filter(
        (task) => task.status === "WAITING_CONFIRMATION" && task.confirmation_assignee_id === user.id
      )
      setTasks(matchingTasks)
      setCount(matchingTasks.length)
    } catch {
      setError("Could not load WFC INT tasks.")
    } finally {
      setLoading(false)
    }
  }, [apiFetch, user?.id])

  const refreshCount = React.useCallback(async () => {
    try {
      const res = await apiFetch("/tasks/waiting-confirmation-ga/count")
      if (!res.ok) return
      const data = (await res.json()) as { count: number }
      setCount(Math.max(0, Number(data.count) || 0))
    } finally {
      setLoading(false)
    }
  }, [apiFetch])

  React.useEffect(() => {
    let cancelled = false
    let timeoutId: ReturnType<typeof window.setTimeout> | null = null
    let idleId: number | null = null

    const onWaitingConfirmationPage = pathname === "/waiting-confirmation-ga"
    const runRefresh = () => {
      if (cancelled) return
      void (onWaitingConfirmationPage ? refresh() : refreshCount())
    }

    if (onWaitingConfirmationPage) {
      runRefresh()
    } else if (typeof window !== "undefined" && typeof window.requestIdleCallback === "function") {
      idleId = window.requestIdleCallback(runRefresh, { timeout: 1200 })
    } else {
      timeoutId = setTimeout(runRefresh, 150)
    }

    return () => {
      cancelled = true
      if (idleId !== null && typeof window !== "undefined" && "cancelIdleCallback" in window) {
        window.cancelIdleCallback(idleId)
      }
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId)
      }
    }
  }, [pathname, refresh, refreshCount])

  const applyTaskResult = React.useCallback(
    (task: Task) => {
      setTasks((prev) => {
        const shouldStay =
          user?.id &&
          task.status === "WAITING_CONFIRMATION" &&
          task.confirmation_assignee_id === user.id

        let next: Task[]
        if (!shouldStay) {
          next = prev.filter((item) => item.id !== task.id)
        } else {
          const existingIndex = prev.findIndex((item) => item.id === task.id)
          next = existingIndex === -1 ? [task, ...prev] : [...prev]
          if (existingIndex !== -1) next[existingIndex] = task
        }
        setCount(next.length)
        return next
      })
    },
    [user?.id]
  )

  const value = React.useMemo<WaitingConfirmationGaContextValue>(
    () => ({
      tasks,
      count,
      loading,
      error,
      refresh,
      applyTaskResult,
    }),
    [applyTaskResult, count, error, loading, refresh, tasks]
  )

  return (
    <WaitingConfirmationGaContext.Provider value={value}>
      {children}
    </WaitingConfirmationGaContext.Provider>
  )
}

export function useWaitingConfirmationGa() {
  const context = React.useContext(WaitingConfirmationGaContext)
  if (!context) {
    throw new Error("useWaitingConfirmationGa must be used within WaitingConfirmationGaProvider")
  }
  return context
}
