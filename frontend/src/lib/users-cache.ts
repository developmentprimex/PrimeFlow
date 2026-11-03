import {
  clearDepartmentBootstrapCache,
  getDepartmentBootstrapCache,
  setDepartmentBootstrapCache,
} from "./department-bootstrap-cache"

const USERS_LOOKUP_CACHE_KEY = "work-users-lookup-v2"
const TTL_MS = 5 * 60 * 1000 // 5 minutes

type ApiFetch = (url: string) => Promise<Response>

export async function fetchUsersLookupCached(apiFetch: ApiFetch): Promise<unknown[] | null> {
  const cached = getDepartmentBootstrapCache<unknown[]>(USERS_LOOKUP_CACHE_KEY)
  if (cached) return cached
  const res = await apiFetch("/users/lookup")
  if (!res.ok) return null
  const data = (await res.json()) as unknown[]
  setDepartmentBootstrapCache(USERS_LOOKUP_CACHE_KEY, data, TTL_MS)
  return data
}

export function invalidateUsersLookupCache() {
  clearDepartmentBootstrapCache(USERS_LOOKUP_CACHE_KEY)
}
