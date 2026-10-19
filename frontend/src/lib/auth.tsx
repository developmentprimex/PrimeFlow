"use client"

import * as React from "react"
import { toast } from "sonner"

import { API_HTTP_URL, API_HTTP_FALLBACK_URL, API_WS_URL } from "@/lib/config"
import { clearDepartmentBootstrapCache } from "@/lib/department-bootstrap-cache"
import { clearPersistentPageCache } from "@/lib/persistent-page-cache"
import type { User } from "@/lib/types"
import { listenForMeetingAudioUnlock, playMeetingReminderSound, startMeetingReminderAlarm, stopMeetingReminderAlarm, unlockMeetingReminderAudio } from "@/lib/meeting-reminder-audio"
export { playMeetingReminderSound, startMeetingReminderAlarm, stopMeetingReminderAlarm } from "@/lib/meeting-reminder-audio"

type AuthContextValue = {
  user: User | null
  token: string | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  apiFetch: (path: string, init?: RequestInit) => Promise<Response>
  prefetchApiFetch: (path: string, init?: RequestInit) => Promise<Response>
}

const AuthContext = React.createContext<AuthContextValue | null>(null)

const ACCESS_TOKEN_KEY = "primex_access_token"
const LOGOUT_AT_KEY = "primex_logout_at"
const USER_KEY = "primex_user"
const SESSION_DURATION_MS = 24 * 60 * 60 * 1000
const SESSION_TIMEOUT_EXEMPT_USERNAMES = new Set(["gane.arifaj"])
// Auth calls must outlast a busy server; a timeout here must never end the session.
const FETCH_TIMEOUT_MS = 20000
// Refresh token when it has less than 3 minutes remaining (15 min total - 3 min buffer = 12 min)
const TOKEN_REFRESH_BUFFER_MS = 3 * 60 * 1000 // 3 minutes in milliseconds
// A deploy restarts the API for some seconds. GET requests wait through that
// window (about 25s in total) before reporting a network error.
const RESTART_RETRY_DELAYS_MS = [1000, 2000, 3000, 4000, 5000, 5000, 5000]
// Gateway answers meaning "the API process is not listening", not app errors.
const ORIGIN_DOWN_STATUSES = new Set([502, 521, 523, 530])
let refreshPromise: Promise<string | null> | null = null
const inFlightGetRequests = new Map<string, Promise<Response>>()
const referenceResponseCache = new Map<string, { response: Response; expiresAt: number }>()
const prefetchedResponseCache = new Map<string, { response: Response; expiresAt: number }>()
const REFERENCE_CACHE_TTL_MS = 60 * 1000
const PREFETCH_CACHE_TTL_MS = 30 * 1000
const REFERENCE_CACHE_PATHS = new Set(["/departments", "/users/lookup", "/task-statuses", "/boards"])
const MEETING_ALARM_STOP_KEY = "primex_meeting_alarm_stopped_at"
let cacheGeneration = 0

function clearSessionCaches() {
  cacheGeneration += 1
  inFlightGetRequests.clear()
  referenceResponseCache.clear()
  prefetchedResponseCache.clear()
  clearDepartmentBootstrapCache()
  void clearPersistentPageCache()
}

function createRequestKey(url: string, headers: Headers, init: RequestInit) {
  return JSON.stringify([
    url,
    Array.from(headers.entries()).sort(([left], [right]) => left.localeCompare(right)),
    init.cache,
    init.mode,
    init.redirect,
    init.referrer,
    init.referrerPolicy,
    init.integrity,
  ])
}

function isReferenceDataRequest(path: string, init: RequestInit) {
  if (init.cache === "no-store" || path.startsWith("http")) return false
  const pathname = path.split("?", 1)[0]
  return REFERENCE_CACHE_PATHS.has(pathname)
}

function getStoredToken(): string | null {
  if (typeof window === "undefined") return null
  return window.localStorage.getItem(ACCESS_TOKEN_KEY)
}

function setStoredToken(token: string | null) {
  if (typeof window === "undefined") return
  if (!token) {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY)
    // The remembered profile is only valid together with a session.
    window.localStorage.removeItem(USER_KEY)
  } else window.localStorage.setItem(ACCESS_TOKEN_KEY, token)
}

// The last known profile lets a returning user see the page immediately while
// /auth/me is confirmed in the background. The API still authorizes every call.
function getStoredUser(): User | null {
  if (typeof window === "undefined") return null
  try {
    const raw = window.localStorage.getItem(USER_KEY)
    const parsed = raw ? (JSON.parse(raw) as User) : null
    return parsed && typeof parsed === "object" && parsed.id ? parsed : null
  } catch {
    return null
  }
}

function setStoredUser(user: User) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(USER_KEY, JSON.stringify(user))
  } catch {
    // Storage full or blocked: the next load simply waits for /auth/me.
  }
}

function getStoredLogoutAt(): number | null {
  if (typeof window === "undefined") return null
  const raw = window.localStorage.getItem(LOGOUT_AT_KEY)
  if (!raw) return null
  const value = Number(raw)
  return Number.isNaN(value) ? null : value
}

function setStoredLogoutAt(timestampMs: number | null) {
  if (typeof window === "undefined") return
  if (!timestampMs) window.localStorage.removeItem(LOGOUT_AT_KEY)
  else window.localStorage.setItem(LOGOUT_AT_KEY, String(timestampMs))
}

function isSessionTimeoutExempt(user: Pick<User, "username">) {
  return SESSION_TIMEOUT_EXEMPT_USERNAMES.has((user.username || "").trim().toLowerCase())
}

function initializeStoredLogoutAt(user: Pick<User, "username">, reset = false) {
  if (isSessionTimeoutExempt(user)) {
    setStoredLogoutAt(null)
    return
  }
  if (reset || getStoredLogoutAt() == null) {
    setStoredLogoutAt(Date.now() + SESSION_DURATION_MS)
  }
}

/**
 * Decode JWT token to get expiration time
 * Returns expiration timestamp in milliseconds, or null if invalid
 */
function getTokenExpiration(token: string): number | null {
  try {
    const parts = token.split(".")
    if (parts.length !== 3) return null
    const payload = JSON.parse(atob(parts[1]))
    const exp = payload.exp
    if (typeof exp !== "number") return null
    return exp * 1000 // Convert to milliseconds
  } catch {
    return null
  }
}

/**
 * Check if token is about to expire (within buffer time)
 */
function isTokenExpiringSoon(token: string): boolean {
  const expiration = getTokenExpiration(token)
  if (!expiration) return true // If we can't parse it, assume it's expired
  const now = Date.now()
  const timeUntilExpiration = expiration - now
  return timeUntilExpiration < TOKEN_REFRESH_BUFFER_MS
}

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs = FETCH_TIMEOUT_MS) {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } finally {
    window.clearTimeout(timer)
  }
}

async function fetchMe(token: string): Promise<User> {
  const res = await fetchWithTimeout(`${API_HTTP_URL}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
    credentials: "include",
  })
  if (!res.ok) throw new Error("me_failed")
  return res.json()
}

// Set when the server explicitly rejected the refresh cookie (401/403). A timeout
// or network error leaves it false, so a slow server never logs the user out.
let lastRefreshRejected = false

async function refreshAccessToken(): Promise<string | null> {
  lastRefreshRejected = false
  let res: Response
  try {
    res = await fetchWithTimeout(`${API_HTTP_URL}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    })
  } catch {
    return null
  }
  if (!res.ok) {
    lastRefreshRejected = res.status === 401 || res.status === 403
    return null
  }
  const data = (await res.json()) as { access_token: string }
  return data.access_token
}

async function refreshAccessTokenShared(): Promise<string | null> {
  if (refreshPromise) {
    return refreshPromise
  }

  refreshPromise = refreshAccessToken().finally(() => {
    refreshPromise = null
  })

  return refreshPromise
}

async function restoreSessionFromRefreshCookie() {
  // Retry while the server is merely slow; stop at once when it rejects the cookie.
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const refreshed = await refreshAccessTokenShared()
    if (!refreshed) {
      if (lastRefreshRejected) return null
      continue
    }
    try {
      const me = await fetchMe(refreshed)
      return { token: refreshed, user: me }
    } catch {
      // try again
    }
  }
  return null
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = React.useState<string | null>(null)
  const [user, setUser] = React.useState<User | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [activeMeetingAlarm, setActiveMeetingAlarm] = React.useState<{
    title: string
    body?: string
    openUrl?: string
  } | null>(null)
  const logoutInProgressRef = React.useRef(false)
  const tokenRef = React.useRef<string | null>(null)

  const userId = user?.id ?? null

  React.useEffect(() => {
    tokenRef.current = token
  }, [token])

  React.useEffect(() => {
    if (!userId) return
    const removeUnlockListeners = listenForMeetingAudioUnlock()
    return () => {
      removeUnlockListeners()
      stopMeetingReminderAlarm()
    }
  }, [userId])

  const stopActiveMeetingAlarm = React.useCallback(() => {
    stopMeetingReminderAlarm()
    setActiveMeetingAlarm(null)
    window.localStorage.setItem(MEETING_ALARM_STOP_KEY, String(Date.now()))
  }, [])

  React.useEffect(() => {
    const stopFromAnotherTab = (event: StorageEvent) => {
      if (event.key !== MEETING_ALARM_STOP_KEY) return
      stopMeetingReminderAlarm()
      setActiveMeetingAlarm(null)
    }
    window.addEventListener("storage", stopFromAnotherTab)
    return () => window.removeEventListener("storage", stopFromAnotherTab)
  }, [])

  React.useEffect(() => {
    const boot = async () => {
      const existing = getStoredToken()

      try {
        const rememberedUser = getStoredUser()
        if (existing && rememberedUser && !isTokenExpiringSoon(existing)) {
          tokenRef.current = existing
          setToken(existing)
          setUser(rememberedUser)
          initializeStoredLogoutAt(rememberedUser)
          setLoading(false)
          // Confirm the profile without holding the page back. If the session
          // is no longer valid, the first API call gets a 401 and apiFetch
          // refreshes or signs out as usual.
          void fetchMe(existing)
            .then((me) => {
              setStoredUser(me)
              if (JSON.stringify(me) !== JSON.stringify(rememberedUser)) setUser(me)
            })
            .catch(() => undefined)
          return
        }

        if (existing) {
          try {
            const me = await fetchMe(existing)
            tokenRef.current = existing
            setStoredUser(me)
            setToken(existing)
            setUser(me)
            initializeStoredLogoutAt(me)
            return
          } catch {
            const restored = await restoreSessionFromRefreshCookie()
            if (!restored) {
              clearSessionCaches()
              setStoredToken(null)
              setStoredLogoutAt(null)
              setToken(null)
              setUser(null)
              return
            }

            tokenRef.current = restored.token
            setStoredToken(restored.token)
            setStoredUser(restored.user)
            setToken(restored.token)
            setUser(restored.user)
            initializeStoredLogoutAt(restored.user)
            return
          }
        }

        const restored = await restoreSessionFromRefreshCookie()
        if (!restored) {
          clearSessionCaches()
          setStoredToken(null)
          setStoredLogoutAt(null)
          setToken(null)
          setUser(null)
          return
        }

        tokenRef.current = restored.token
        setStoredToken(restored.token)
        setStoredUser(restored.user)
        setToken(restored.token)
        setUser(restored.user)
        initializeStoredLogoutAt(restored.user)
      } catch {
        clearSessionCaches()
        setStoredToken(null)
        setStoredLogoutAt(null)
        setToken(null)
        setUser(null)
      } finally {
        setLoading(false)
      }
    }
    void boot()
  }, [])

  // Proactive token refresh - refresh token before it expires
  React.useEffect(() => {
    if (!token || !userId) return

    const checkAndRefresh = async () => {
      if (isTokenExpiringSoon(token)) {
        const refreshed = await refreshAccessTokenShared()
        if (refreshed) {
          setStoredToken(refreshed)
          setToken(refreshed)
        }
      }
    }

    // Check immediately
    void checkAndRefresh()

    // Check every minute
    const interval = setInterval(() => {
      void checkAndRefresh()
    }, 60 * 1000) // Check every minute

    return () => clearInterval(interval)
  }, [token, userId])

  React.useEffect(() => {
    if (!token || !userId) return

    let stopped = false
    let ws: WebSocket | null = null
    let reconnectTimer: number | null = null
    let heartbeatTimer: number | null = null
    let reconnectDelayMs = 1000

    const clearHeartbeat = () => {
      if (heartbeatTimer !== null) window.clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }

    const handleMessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data) as {
          type?: string
          notification_type?: string
          title?: string
          body?: string
          data?: { open_url?: string; kind?: string }
        }
        if (msg.type === "notification") {
          const openUrl = msg.data?.open_url
          toast(msg.title || "Notification", {
            description: msg.body || undefined,
            action: openUrl ? {
              label: msg.data?.kind?.startsWith("task_marker") ? "Hap" : "Open Meeting",
              onClick: () => {
                if (msg.notification_type === "reminder") stopActiveMeetingAlarm()
                window.open(openUrl, "_blank", "noopener,noreferrer")
              },
            } : undefined,
          })
          if (msg.notification_type === "reminder") {
            startMeetingReminderAlarm()
            setActiveMeetingAlarm({
              title: msg.title || "PrimeFlow Meeting Reminder",
              body: msg.body || undefined,
              openUrl,
            })
            if ("Notification" in window && Notification.permission === "granted") {
              const browserNotification = new Notification(msg.title || "PrimeFlow Meeting Reminder", {
                body: msg.body || undefined,
                tag: openUrl || msg.title,
              })
              browserNotification.onclick = () => {
                stopActiveMeetingAlarm()
                window.focus()
                if (openUrl) window.open(openUrl, "_blank", "noopener,noreferrer")
                browserNotification.close()
              }
            }
          }
          window.dispatchEvent(new CustomEvent("primex:notification"))
        }
      } catch {
        // ignore
      }
    }

    const connect = () => {
      if (stopped) return
      ws = new WebSocket(`${API_WS_URL}/ws/notifications?token=${encodeURIComponent(token)}`)
      ws.onopen = () => {
        reconnectDelayMs = 1000
        clearHeartbeat()
        heartbeatTimer = window.setInterval(() => {
          if (ws?.readyState === WebSocket.OPEN) ws.send("ping")
        }, 30_000)
      }
      ws.onmessage = handleMessage
      ws.onerror = () => ws?.close()
      ws.onclose = () => {
        clearHeartbeat()
        if (stopped) return
        reconnectTimer = window.setTimeout(connect, reconnectDelayMs)
        reconnectDelayMs = Math.min(reconnectDelayMs * 2, 30_000)
      }
    }

    connect()
    return () => {
      stopped = true
      clearHeartbeat()
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer)
      ws?.close()
    }
  }, [stopActiveMeetingAlarm, token, userId])

  const logout = React.useCallback(async () => {
    stopMeetingReminderAlarm()
    setActiveMeetingAlarm(null)
    try {
      await fetch(`${API_HTTP_URL}/auth/logout`, { method: "POST", credentials: "include" })
    } catch {
      // ignore
    }
    clearSessionCaches()
    setStoredToken(null)
    setStoredLogoutAt(null)
    setToken(null)
    setUser(null)
  }, [])

  React.useEffect(() => {
    if (!token || !user) return
    if (isSessionTimeoutExempt(user)) {
      // Remove a timeout stored by an older frontend version for this account.
      setStoredLogoutAt(null)
      return
    }
    const checkLogoutSession = async () => {
      if (logoutInProgressRef.current) return
      const logoutAt = getStoredLogoutAt()
      if (!logoutAt) return
      if (Date.now() >= logoutAt) {
        logoutInProgressRef.current = true
        toast("Session ended", {
          description: "You have been logged out.",
        })
        await logout()
      }
    }

    void checkLogoutSession()
    const interval = setInterval(() => {
      void checkLogoutSession()
    }, 60 * 1000)

    return () => clearInterval(interval)
  }, [token, user, logout])

  const apiFetch = React.useCallback(
    async (path: string, init: RequestInit = {}) => {
      const makeUrl = (base: string) =>
        path.startsWith("http") ? path : `${base}${path.startsWith("/") ? "" : "/"}${path}`
      const url = makeUrl(API_HTTP_URL)
      const currentToken = tokenRef.current
      const headers = new Headers(init.headers)
      if (currentToken) headers.set("Authorization", `Bearer ${currentToken}`)

      const isReadRequest = (init.method || "GET").toUpperCase() === "GET"
      const doFetch = async (overrideToken?: string | null, overrideUrl?: string) => {
        const h = new Headers(headers)
        if (overrideToken) h.set("Authorization", `Bearer ${overrideToken}`)
        const fetchOnce = () => fetch(overrideUrl || url, { ...init, headers: h, credentials: "include" })
        // Writes are never repeated: a lost response does not prove the server
        // did not apply the change.
        if (!isReadRequest) return fetchOnce()

        // Reads ride out a backend restart (deploy) instead of failing at once.
        for (let attempt = 0; ; attempt += 1) {
          const lastAttempt = attempt >= RESTART_RETRY_DELAYS_MS.length
          try {
            const res = await fetchOnce()
            if (lastAttempt || !ORIGIN_DOWN_STATUSES.has(res.status)) return res
          } catch (err) {
            const aborted = init.signal?.aborted || (err as { name?: string } | null)?.name === "AbortError"
            if (lastAttempt || aborted) throw err
          }
          await new Promise((resolve) => window.setTimeout(resolve, RESTART_RETRY_DELAYS_MS[attempt]))
        }
      }

      const executeRequest = async (): Promise<Response> => {
        let res: Response
        try {
          res = await doFetch()
        } catch (err) {
          const errName = (err as { name?: string } | null)?.name
          const aborted = init.signal?.aborted || errName === "AbortError"
          if (aborted) {
            return new Response(null, { status: 499, statusText: "Request aborted" })
          }

          if (!path.startsWith("http") && API_HTTP_FALLBACK_URL !== API_HTTP_URL) {
            try {
              res = await doFetch(undefined, makeUrl(API_HTTP_FALLBACK_URL))
            } catch (fallbackErr) {
              const fallbackErrName = (fallbackErr as { name?: string } | null)?.name
              const fallbackAborted = init.signal?.aborted || fallbackErrName === "AbortError"
              if (fallbackAborted) {
                return new Response(null, { status: 499, statusText: "Request aborted" })
              }
              toast("Network error", {
                description: "Unable to reach the server. Check the API URL or backend status.",
              })
              return new Response(null, { status: 503, statusText: "Network error" })
            }
          } else {
            toast("Network error", {
              description: "Unable to reach the server. Check the API URL or backend status.",
            })
            return new Response(null, { status: 503, statusText: "Network error" })
          }
        }
        if (res.status !== 401) return res

        const refreshed = await refreshAccessTokenShared()
        if (!refreshed) {
          // Only a definite rejection ends the session; a slow or unreachable
          // server keeps the user where they are and the next call retries.
          if (lastRefreshRejected) {
            clearSessionCaches()
            setStoredToken(null)
            setStoredLogoutAt(null)
            setToken(null)
            setUser(null)
          }
          return res
        }

        tokenRef.current = refreshed
        setStoredToken(refreshed)
        setToken(refreshed)

        const retryRes = await doFetch(refreshed)
        if (retryRes.status === 401) {
          clearSessionCaches()
          setStoredToken(null)
          setStoredLogoutAt(null)
          setToken(null)
          setUser(null)
        }
        return retryRes
      }

      const method = (init.method || "GET").toUpperCase()
      if (method !== "GET") {
        // Reference data can be changed by administrative mutations. Clearing
        // all session-local entries keeps subsequent reads authoritative.
        clearSessionCaches()
      }
      const canShareRequest = method === "GET" && init.body == null && init.signal == null
      if (!canShareRequest) return executeRequest()

      const requestKey = createRequestKey(url, headers, init)
      const prefetched = prefetchedResponseCache.get(requestKey)
      if (prefetched && Date.now() < prefetched.expiresAt) {
        prefetchedResponseCache.delete(requestKey)
        return prefetched.response.clone()
      }
      if (prefetched) prefetchedResponseCache.delete(requestKey)
      const canCacheResponse = isReferenceDataRequest(path, init)
      if (canCacheResponse) {
        const cached = referenceResponseCache.get(requestKey)
        if (cached && Date.now() < cached.expiresAt) return cached.response.clone()
        if (cached) referenceResponseCache.delete(requestKey)
      }
      const existingRequest = inFlightGetRequests.get(requestKey)
      if (existingRequest) return (await existingRequest).clone()

      const request = executeRequest()
      const requestCacheGeneration = cacheGeneration
      inFlightGetRequests.set(requestKey, request)
      try {
        const response = await request
        if (canCacheResponse && response.ok && requestCacheGeneration === cacheGeneration) {
          referenceResponseCache.set(requestKey, {
            response: response.clone(),
            expiresAt: Date.now() + REFERENCE_CACHE_TTL_MS,
          })
        }
        return response.clone()
      } finally {
        if (inFlightGetRequests.get(requestKey) === request) {
          inFlightGetRequests.delete(requestKey)
        }
      }
    },
    []
  )

  const prefetchApiFetch = React.useCallback(
    async (path: string, init: RequestInit = {}) => {
      const method = (init.method || "GET").toUpperCase()
      if (method !== "GET" || init.body != null || init.signal != null) {
        return apiFetch(path, init)
      }

      const generation = cacheGeneration
      const response = await apiFetch(path, init)
      if (!response.ok || generation !== cacheGeneration) return response

      const baseUrl = path.startsWith("http") ? "" : API_HTTP_URL
      const url = path.startsWith("http") ? path : `${baseUrl}${path.startsWith("/") ? "" : "/"}${path}`
      const headers = new Headers(init.headers)
      const currentToken = tokenRef.current
      if (currentToken) headers.set("Authorization", `Bearer ${currentToken}`)
      const requestKey = createRequestKey(url, headers, init)
      prefetchedResponseCache.set(requestKey, {
        response: response.clone(),
        expiresAt: Date.now() + PREFETCH_CACHE_TTL_MS,
      })
      return response
    },
    [apiFetch]
  )

  const login = React.useCallback(async (email: string, password: string) => {
    clearSessionCaches()
    let res: Response
    try {
      res = await fetchWithTimeout(`${API_HTTP_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, password }),
      })
    } catch {
      throw new Error("network_error")
    }
    if (!res.ok) throw new Error("login_failed")
    const data = (await res.json()) as { access_token: string }
    const me = await fetchMe(data.access_token)
    // Pages mount and fetch before the token effect runs, so the ref is set first.
    tokenRef.current = data.access_token
    setStoredToken(data.access_token)
    setStoredUser(me)
    setToken(data.access_token)
    setUser(me)
    initializeStoredLogoutAt(me, true)
  }, [])

  const value = React.useMemo<AuthContextValue>(
    () => ({ user, token, loading, login, logout, apiFetch, prefetchApiFetch }),
    [user, token, loading, login, logout, apiFetch, prefetchApiFetch]
  )

  return (
    <AuthContext.Provider value={value}>
      {children}
      {activeMeetingAlarm ? (
        <div
          role="alert"
          aria-live="assertive"
          style={{
            position: "fixed",
            right: 24,
            bottom: 24,
            zIndex: 200,
            width: "min(420px, calc(100vw - 32px))",
            border: "2px solid #dc2626",
            borderRadius: 12,
            background: "white",
            boxShadow: "0 20px 45px rgba(15, 23, 42, 0.28)",
            padding: 16,
          }}
        >
          <strong style={{ display: "block", color: "#991b1b", fontSize: 16 }}>
            {activeMeetingAlarm.title}
          </strong>
          {activeMeetingAlarm.body ? (
            <span style={{ display: "block", marginTop: 6, color: "#334155", whiteSpace: "pre-line" }}>
              {activeMeetingAlarm.body}
            </span>
          ) : null}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 14 }}>
            <button
              type="button"
              onClick={() => {
                void unlockMeetingReminderAudio().then((ready) => {
                  if (!ready || !playMeetingReminderSound()) toast.error("Sound is blocked. Check this tab’s sound settings.")
                })
              }}
              style={{ border: "1px solid #cbd5e1", borderRadius: 8, background: "white", cursor: "pointer", padding: "9px 14px" }}
            >
              Enable sound
            </button>
            <button
              type="button"
              onClick={stopActiveMeetingAlarm}
              style={{
                border: 0,
                borderRadius: 8,
                background: "#dc2626",
                color: "white",
                cursor: "pointer",
                fontWeight: 700,
                padding: "9px 14px",
              }}
            >
              Stop alarm
            </button>
          </div>
        </div>
      ) : null}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = React.useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within AuthProvider")
  return ctx
}

