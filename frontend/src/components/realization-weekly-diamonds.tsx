"use client"

import Link from "next/link"
import { Gem } from "lucide-react"
import { getPlainMarkedText } from "@/lib/note-markup"
import type { TaskReviewOverviewRow } from "@/lib/types"

export function RealizationWeeklyDiamonds({ count, taskCount, proposalCount, awards, person }: {
  count: number; taskCount: number; proposalCount: number; awards: TaskReviewOverviewRow[]; person?: string
}) {
  const title = person ? `Diamantat e javës · ${person}` : "Diamantat e javës · Të gjithë"
  const value = <div className="flex flex-col items-end justify-center gap-1">
    <p className="flex items-center gap-1.5 text-lg font-bold tabular-nums text-cyan-900"><Gem className="h-5 w-5 fill-cyan-300 text-cyan-700" aria-hidden="true" />{count}</p>
    {count > 0 ? <p className="text-center text-[10px] leading-4 text-cyan-800">{taskCount} taska · {proposalCount} propozime</p> : null}
  </div>
  return <section aria-label={`${title}: ${count}`} className="rounded-xl border border-cyan-200 bg-cyan-50/50 p-4">
    <div className="mb-3 flex items-start justify-between gap-3 border-b border-cyan-200 pb-3">
      <div><h3 className="font-semibold text-cyan-950">💎 Diamantat e javës</h3><p className="mt-1 text-xs text-cyan-800">{person || "Të gjithë"} · Taskat dhe propozimet që dhanë diamantat.</p></div>
      {value}
    </div>
    {awards.length ? <ul className="max-h-80 space-y-2 overflow-y-auto overscroll-contain">
      {awards.map(award => <li key={`${award.source || "TASK"}:${award.review?.id}:${award.reviewee_user_id}`} className="rounded border border-cyan-100 bg-cyan-50/60 p-2 text-xs">
        <p className="mb-1 flex items-center justify-between gap-2 text-[10px] text-cyan-800">
          <b>{award.source === "REALIZATION_PROPOSAL" ? "Propozim për përmirësim" : "Taskë e vlerësuar"}</b>
          <span>{new Date(award.completed_at).toLocaleDateString("sq-AL")}</span>
        </p>
        {!person ? <p className="mb-1 font-semibold text-slate-900">{award.reviewee_name}</p> : null}
        <Link href={award.task_id ? `/tasks/${award.task_id}` : "/realization"} className="font-medium text-cyan-950 hover:underline">{getPlainMarkedText(award.task_title)}</Link>
        {award.review?.comment ? <p className="mt-1 whitespace-pre-line text-slate-700">{award.review.comment}</p> : null}
        {award.review?.reviewer_name ? <p className="mt-1 text-[10px] text-slate-500">Nga {award.review.reviewer_name}</p> : null}
      </li>)}
    </ul> : <p className="text-sm text-slate-500">Nuk ka diamanta për këtë javë.</p>}
  </section>
}
