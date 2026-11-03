"use client"

import { CellPopover } from "@/components/cell-popover"
import { firstLineTitle } from "@/components/realization-deadline-tasks"
import type { DailyRealizationMetrics, RealizationItem } from "@/lib/types"
import { cn } from "@/lib/utils"

import { realizationTaskGroups as groups } from "@/lib/realization-task-groups"

function number(value: number) {
  return String(Math.round(value * 100) / 100)
}

function penaltyLabel(item: RealizationItem) {
  if (!item.penalty) return null
  const reason = item.kind === "POSTPONED"
    ? item.deadline ? (item.critical ? "shtyrë, deadline important" : "shtyrë, kishte deadline") : "shtyrë"
    : item.deadline ? (item.critical ? "deadline important i humbur" : "deadline i humbur") : "pa progres"
  return `−${number(item.penalty)} · ${reason}`
}

function ItemRow({ item }: { item: RealizationItem }) {
  const multiDay = item.planned && item.share < 1
  const extraWeight = !item.planned && item.share !== 1
  const penalty = penaltyLabel(item)
  return <li className={cn("flex items-start gap-2 rounded px-1 py-1", item.critical && item.penalty ? "border border-red-300 bg-red-50" : "hover:bg-slate-50")}>
    <span className="min-w-0 flex-1 text-xs leading-4 text-slate-800">{firstLineTitle(item.title)}</span>
    {multiDay ? <span className="shrink-0 whitespace-nowrap text-[10px] text-slate-500" title="Detyrë shumëditore: çdo ditë pune peshon një pjesë të detyrës">1/{Math.round(1 / item.share)} në ditë</span> : null}
    {extraWeight ? <span className="shrink-0 whitespace-nowrap text-[10px] text-slate-500" title="Ekstra peshon sa një detyrë mesatare e planit të kësaj dite">peshë {number(item.share)}</span> : null}
    {item.credit ? <span className="shrink-0 whitespace-nowrap text-[10px] font-bold tabular-nums text-emerald-700">+{number(item.credit)}</span> : null}
    {item.approved || item.confirmation?.confirmed ? <span className="shrink-0 whitespace-nowrap text-[10px] text-violet-700">konfirmuar ? pa penalizim</span> : null}
    {penalty ? <span className="shrink-0 whitespace-nowrap text-[10px] font-bold text-rose-700">{penalty}</span> : null}
  </li>
}

/** Explains a person's Plan RLZ: the formula with their numbers, then the tasks behind each part. */
export function RealizationPlanRlzPopover({ metrics, title, children }: {
  metrics: DailyRealizationMetrics
  title: string
  children: React.ReactNode
}) {
  const items = metrics.realization_items ?? []
  if (!items.length || metrics.raw_plan_realization == null) return <>{children}</>

  const denominator = metrics.realization_plan_weight || metrics.additional_count
  const uncapped = denominator ? metrics.realization_credit * 100 / denominator : 0
  const base = Math.round(Math.min(100, uncapped) * 10) / 10
  const penaltyBase = metrics.original_planned_count || metrics.additional_count
  const penalty = penaltyBase ? Math.round(metrics.realization_penalty_points / penaltyBase * 10) / 10 : 0

  return <CellPopover
    label={title}
    triggerTitle="Kliko për të parë si u llogarit realizimi"
    width={520}
    panel={<>
      <p className="mb-1 flex items-baseline justify-between gap-2 border-b pb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-600">
        <span className="truncate">{title}</span>
        <span className="shrink-0 text-sm font-bold normal-case text-slate-900">{metrics.raw_plan_realization}%</span>
      </p>
      <div className="mb-2 space-y-0.5 rounded border border-slate-200 bg-slate-50 px-2 py-1.5 text-[11px] leading-4 text-slate-700">
        <p>
          <b>Baza:</b> {number(metrics.realization_credit)} kryer ÷ {metrics.realization_plan_weight ? `${number(metrics.realization_plan_weight)} plan` : `${metrics.additional_count} ekstra`} × 100 = <b>{base}%</b>
          {uncapped > 100 ? <span className="text-slate-500"> (kufizuar në 100%)</span> : null}
        </p>
        <p>
          <b>Penalizimi:</b> {number(metrics.realization_penalty_points)} pikë ÷ {penaltyBase} detyra = <b className={penalty ? "text-rose-700" : undefined}>−{penalty}</b>
        </p>
        <p><b>Final:</b> {base} − {penalty} = <b>{metrics.raw_plan_realization}%</b></p>
      </div>
      <div className="max-h-96 space-y-2 overflow-y-auto overscroll-contain">
        {groups.map((group) => {
          const groupItems = items.filter((item) => item.kind === group.kind)
          if (!groupItems.length) return null
          return <section key={group.kind}>
            <p className={cn("mb-0.5 inline-flex rounded border px-1.5 py-px text-[10px] font-bold uppercase", group.className)}>{group.label} · {groupItems.length}</p>
            <ul className="space-y-0.5">
              {groupItems.map((item, index) => <ItemRow key={`${item.task_id ?? "anonymous"}:${index}`} item={item} />)}
            </ul>
          </section>
        })}
      </div>
    </>}
  >
    {children}
  </CellPopover>
}
