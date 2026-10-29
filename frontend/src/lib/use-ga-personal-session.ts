"use client"

import * as React from "react"
import { useAuth } from "@/lib/auth"
import type { GaAccess, GaOccurrence, GaTemplate, Workspace } from "@/lib/ga-personal"

export type GaEvent = { id: string; kind: string; created_at: string; payload: { from?: string; to?: string; day?: string } }
export class GaApiError extends Error {
  constructor(message: string, public status: number) { super(message) }
}

export function useGaPersonalSession(onClear: () => void) {
  const { apiFetch, user } = useAuth()
  const fetchRef = React.useRef(apiFetch)
  const clearRef = React.useRef(onClear)
  React.useEffect(() => { fetchRef.current = apiFetch }, [apiFetch])
  React.useEffect(() => { clearRef.current = onClear }, [onClear])
  const [access, setAccess] = React.useState<GaAccess | null>(null)
  const [workspace, setWorkspace] = React.useState<Workspace | null>(null)
  const [templates, setTemplates] = React.useState<GaTemplate[]>([])
  const [occurrences, setOccurrences] = React.useState<GaOccurrence[]>([])
  const [history, setHistory] = React.useState<GaEvent[]>([])
  const [obscured, setObscured] = React.useState(false)
  const [connectionError, setConnectionError] = React.useState("")
  const generation = React.useRef(0)
  const reads = React.useRef<AbortController | null>(null)
  const checking = React.useRef<{ generation: number; promise: Promise<void> } | null>(null)

  const invalidate = React.useCallback(() => {
    generation.current += 1
    reads.current?.abort()
    checking.current = null
  }, [])

  const clear = React.useCallback(() => {
    invalidate()
    setWorkspace(null); setTemplates([]); setOccurrences([]); setHistory([])
    setObscured(false); setConnectionError("")
    setAccess((value) => value ? { available: false, unlocked: false } : value)
    clearRef.current()
  }, [invalidate])

  const request = React.useCallback(async <T,>(path: string, init?: RequestInit): Promise<T> => {
    const version = generation.current
    const response = await fetchRef.current(`/ga-personal${path}`, {
      ...init, cache: "no-store", headers: { "Content-Type": "application/json", ...init?.headers },
    })
    if (version !== generation.current) throw new GaApiError("Kërkesa u anulua.", 499)
    if (!response.ok) {
      // Network errors and forbidden edits preserve the page and unsaved drafts.
      if (response.status === 401 || (response.status === 403 && (init?.method || "GET") === "GET" && path !== "/access")) clear()
      const body = await response.json().catch(() => ({}))
      throw new GaApiError(typeof body.detail === "string" ? body.detail : "Lidhja me serverin u ndërpre. Provo përsëri.", response.status)
    }
    return response.json() as Promise<T>
  }, [clear])

  const load = React.useCallback(async (signal?: AbortSignal) => {
    const version = generation.current
    const [w, t, o, h] = await Promise.all([
      request<Workspace>("/workspace", { signal }), request<GaTemplate[]>("/templates", { signal }),
      request<GaOccurrence[]>("/occurrences", { signal }), request<GaEvent[]>("/history", { signal }),
    ])
    if (version !== generation.current) return
    setWorkspace(w); setTemplates(t); setOccurrences(o); setHistory(h)
  }, [request])

  const check = React.useCallback((): Promise<void> => {
    const version = generation.current
    if (checking.current?.generation === version) return checking.current.promise
    const controller = new AbortController()
    reads.current = controller
    const entry = { generation: version, promise: Promise.resolve() as Promise<void> }
    checking.current = entry
    entry.promise = (async () => {
      try {
        const result = await request<GaAccess>("/access", { signal: controller.signal })
        if (version !== generation.current) return
        if (!result.available) {
          clear(); setAccess(result)
          return
        }
        setAccess(result)
        await load(controller.signal)
        if (version === generation.current) {
          setConnectionError(""); setObscured(document.visibilityState === "hidden")
        }
      } catch (error) {
        if (version === generation.current && !controller.signal.aborted) {
          setConnectionError(error instanceof Error ? error.message : "Nuk u lidhëm me serverin.")
        }
      } finally {
        if (checking.current === entry) checking.current = null
      }
    })()
    return entry.promise
  }, [request, load, clear])

  React.useEffect(() => {
    clear(); setAccess(null)
    void check()
    const onFocus = () => { if (document.visibilityState !== "hidden") void check() }
    const onVisibility = () => {
      if (document.visibilityState === "hidden") setObscured(true)
      else void check()
    }
    const onStorage = (event: StorageEvent) => { if (event.key === "primex_access_token" && !event.newValue) clear() }
    window.addEventListener("focus", onFocus)
    document.addEventListener("visibilitychange", onVisibility)
    window.addEventListener("storage", onStorage)
    const timer = window.setInterval(onFocus, 20000)
    return () => {
      window.removeEventListener("focus", onFocus)
      document.removeEventListener("visibilitychange", onVisibility)
      window.removeEventListener("storage", onStorage)
      window.clearInterval(timer); invalidate()
    }
  }, [user?.id, check, clear, invalidate])

  return { access, workspace, templates, occurrences, history, request, load, check,
    clear, invalidate, obscured: obscured && !!workspace, connectionError }
}
