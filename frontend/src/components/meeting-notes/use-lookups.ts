"use client"

import * as React from "react"
import { useAuth } from "@/lib/auth"
import { fetchUsersLookupCached } from "@/lib/users-cache"
import type { LookupUser } from "@/lib/meeting-notes"

export function useUsersMap() {
  const { apiFetch } = useAuth()
  const [users, setUsers] = React.useState<Map<string, LookupUser>>(new Map())
  React.useEffect(() => {
    let active = true
    void fetchUsersLookupCached(apiFetch).then((rows) => {
      if (active && rows) setUsers(new Map((rows as LookupUser[]).map((user) => [user.id, user])))
    }).catch(() => {})
    return () => { active = false }
  }, [apiFetch])
  return users
}

export function useProjectTitles() {
  const { apiFetch } = useAuth()
  const [titles, setTitles] = React.useState<Map<string, string>>(new Map())
  React.useEffect(() => {
    let active = true
    void apiFetch("/projects").then(async (response) => {
      if (!response.ok) return
      const rows = (await response.json()) as { id: string; title?: string | null }[]
      if (active) setTitles(new Map(rows.map((row) => [row.id, row.title || ""])))
    }).catch(() => {})
    return () => { active = false }
  }, [apiFetch])
  return titles
}
