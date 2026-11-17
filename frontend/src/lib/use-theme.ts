"use client"

import { useSyncExternalStore } from "react"
import type { Theme } from "@/lib/theme"

function subscribe(callback: () => void) {
  window.addEventListener("primex:theme-change", callback)
  return () => window.removeEventListener("primex:theme-change", callback)
}
const getTheme = () => (document.documentElement.dataset.theme || "system") as Theme
const getServerTheme = () => "system" as Theme
const getResolvedTheme = (): "light" | "dark" => document.documentElement.dataset.resolvedTheme === "dark" ? "dark" : "light"
const getServerResolvedTheme = () => "light" as const

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, getTheme, getServerTheme)
  const resolvedTheme = useSyncExternalStore(subscribe, getResolvedTheme, getServerResolvedTheme)
  return { theme, resolvedTheme, setTheme: (value: Theme) => window.dispatchEvent(new CustomEvent("primex:set-theme", { detail: value })) }
}
