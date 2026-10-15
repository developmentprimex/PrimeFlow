import { dailyCoverageNotices, type CoverageRow } from "@/lib/daily-project-coverage"

export function DailyProjectCoverageNotices({ rows, department, slotDisplay }: {
  rows: CoverageRow[]; department: string; slotDisplay: (row: CoverageRow) => string
}) {
  return dailyCoverageNotices(rows, department, slotDisplay).map((notice) => (
    <p key={notice.key} role="status" className={`mt-3 rounded-md border px-3 py-2 text-sm font-semibold ${notice.covered
      ? "border-green-300 bg-green-50 text-green-700"
      : "border-red-300 bg-red-50 text-red-700"}`}>
      {notice.text}
    </p>
  ))
}
