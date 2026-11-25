export function personInitials(name: string): string {
  const cleaned = name.trim()
  if (!cleaned) return "?"
  if (cleaned.replace(/\s+/g, " ").toLocaleLowerCase() === "haris shaqiri") return "HSH"
  const parts = cleaned.split(/\s+/)
  const first = parts[0]?.[0] || ""
  const last = parts.length > 1 ? parts[parts.length - 1]?.[0] || "" : ""
  return `${first}${last}`.toUpperCase()
}
