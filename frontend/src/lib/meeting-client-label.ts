// Display labels only: client IDs and full names remain the saved identity.
const CLIENT_ABBREVIATIONS = new Map<string, string>([
  ["kettler", "KTL"],
  ["trendteam", "TT"],
  ["staud", "STD"],
  ["vs", "VS"],
  ["erpo", "ERPO"],
  ["cor", "COR"],
  ["odoo", "ODOO"],
  ["team 7", "T7"],
  ["wiemann", "WIE"],
  ["beckermann", "BCK"],
  ["wöstmann", "WST"],
  ["pos", "POS"],
  ["fragmento", "FRG"],
])

export function meetingClientLabel(name: string | null | undefined): string {
  const normalized = (name || "").trim().replace(/\s+/g, " ")
  return CLIENT_ABBREVIATIONS.get(normalized.toLowerCase()) || normalized
}
