"use client"

import * as React from "react"
import Link from "next/link"
import { MessageCircle } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useMarkerComments, type MarkerComment } from "@/components/marker-comments-context"
import { useAuth } from "@/lib/auth"

export function TeamMarkerCommentsButton() {
  const { apiFetch } = useAuth()
  const comments = useMarkerComments()
  const [items, setItems] = React.useState<MarkerComment[]>([])

  React.useEffect(() => {
    let cancelled = false
    void apiFetch("/marker-comments?scope=all").then(async (response) => {
      if (!response?.ok) return
      const data = await response.json() as { items: MarkerComment[] }
      if (!cancelled) setItems(data.items)
    }).catch(() => undefined)
    return () => { cancelled = true }
    // The provider refreshes on notifications, symbol changes, focus and every
    // 30 seconds. Follow those updates without adding another polling timer.
  }, [apiFetch, comments?.items])

  const unread = items.filter((item) => item.recipient_count > 0 && !item.all_read).length
  return <Button asChild variant="outline" size="sm" className={`h-8 gap-2 text-xs ${unread
    ? "border-blue-700 bg-[#0055FF] text-white hover:bg-blue-700 hover:text-white"
    : "border-blue-300 bg-white text-blue-700 hover:bg-blue-50"}`}>
    <Link href="/comments?scope=all&read=all" title="Simbolet dhe komentet e të gjithëve, pavarësisht departamentit" aria-label={`Komentet e të gjithëve, ${unread} të palexuara`}>
      <MessageCircle className="size-4" />
      Komentet e të gjithëve
      {unread > 0 && <span aria-live="polite" className="rounded-full bg-white px-1.5 py-0.5 text-[11px] font-bold text-blue-700">{unread}</span>}
    </Link>
  </Button>
}
