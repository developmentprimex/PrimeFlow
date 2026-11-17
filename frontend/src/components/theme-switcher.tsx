"use client"

import { Monitor, Moon, Sun } from "lucide-react"
import type { Theme } from "@/lib/theme"
import { useTheme } from "@/lib/use-theme"

export function ThemeSwitcher() {
  const { theme, setTheme } = useTheme()
  const Icon = theme === "system" ? Monitor : theme === "dark" ? Moon : Sun
  return (
    <label className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md border bg-background px-2 text-sm print:hidden">
      <Icon className="size-4" aria-hidden="true" />
      <select
        aria-label="Color theme"
        className="min-w-0 cursor-pointer bg-background text-foreground outline-offset-2"
        value={theme}
        onChange={(event) => setTheme(event.target.value as Theme)}
      >
        <option value="light">Light</option>
        <option value="dark">Dark</option>
        <option value="system">System</option>
      </select>
    </label>
  )
}
