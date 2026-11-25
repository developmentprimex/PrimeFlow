export function weeklyPlanStatusBgClass(status?: string | null): string {
  const normalized = (status || "")
    .trim()
    .toUpperCase()
    .replace(/\s+/g, "_")

  const resolved =
    normalized === "TO_DO"
      ? "TODO"
      : normalized === "INPROGRESS"
        ? "IN_PROGRESS"
        : normalized

  if (resolved === "TODO") {
    return "bg-[#FFC4ED] text-[#000000]"
  }
  if (resolved === "IN_PROGRESS") {
    return "bg-[#FFFF00] text-[#000000]"
  }
  if (resolved === "PAUSED") {
    return "bg-[#CBD5E1] text-[#1E293B]"
  }
  if (resolved === "WAITING_CLIENT") {
    return "bg-[#E2C15B] text-[#4F3A00]"
  }
  if (resolved === "WAITING_CONFIRMATION") {
    return "bg-[#CCFBF1] text-[#134E4A]"
  }
  if (resolved === "DONE") {
    return "bg-[#C4FDC4] text-[#000000]"
  }
  return ""
}

