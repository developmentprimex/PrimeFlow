export type PersonKey = "mrika" | "lirza" | "rrita" | "gane"
export type GaStatus = "pending" | "acknowledged" | "in_progress" | "needs_help" | "rescheduled" | "done" | "cancelled"
export type Definition = {
  title: string; description: string; area_id: string
  completion_definition?: string
  schedule_hints?: { trigger_type: string; start_time: string | null; end_time: string | null; notes: string }[]
  assignment: "fixed" | "rotation" | "first_home" | "unassigned"
  assignees: PersonKey[]; completion_mode: "individual" | "shared"
  frequency: "once" | "daily" | "weekly" | "school_day" | "conditional" | "near_daily" | "unresolved"
  on_date: string | null; due_time: string | null; weekdays: number[]; steps: string[]
  estimated_minutes: number | null
  reminder_group: "morning" | "daily_upkeep" | "nala" | "weekend_deep_clean"
  enabled: boolean; readiness: "ready_after_setup" | "needs_confirmation"
  rotation_id: "nala" | null; coverage_key: string | null
}
export type GaTemplate = { id: string; definition: Definition; version: number; archived: boolean; source_id: string | null; can_manage: boolean }
export type GaOccurrence = {
  id: string; template_id: string; local_date: string; period_key: string
  due_at: string | null; snapshot: Definition; status: GaStatus; version: number; completed_at: string | null
  can_edit?: boolean
}
export type Workspace = {
  person_key: PersonKey; is_admin: boolean; timezone: string
  members: { person_key: PersonKey; name: string }[]
  config: { rotation_anchor?: string; areas?: { id: string; name: string }[]; reminders_enabled?: boolean; automatic_generation?: { enabled: boolean; starts_on: string } }
  discord: { connected: boolean; messages_enabled: boolean }
}
export type GaAccess = { available: boolean; unlocked: boolean; configured?: boolean; expires_at?: string; setup_allowed?: boolean; requires_login?: boolean }
export type ImportPreview = {
  dataset_hash: string; templates: number; steps: number; create: string[]; unchanged: string[]
  conflicts: string[]; unresolved_members: string[]; applied?: boolean
}
export const groups = {
  morning: "Mëngjesi", daily_upkeep: "Mirëmbajtja ditore", nala: "Nala", weekend_deep_clean: "Vikendi",
}
export const statuses: Record<GaStatus, string> = {
  pending: "Për t’u bërë", acknowledged: "E pashë", in_progress: "Po e bëj", needs_help: "Më duhet ndihmë",
  rescheduled: "E shtyrë", done: "U kry", cancelled: "E anuluar",
}
export const frequencies: Record<Definition["frequency"], string> = {
  once: "Një herë", daily: "Çdo ditë", weekly: "Një herë në vikend", school_day: "Ditët e shkollës",
  conditional: "Sipas kushtit", near_daily: "Ditë të zgjedhura", unresolved: "Ende pa orar",
}
export function localToday() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Belgrade", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date())
}
export function emptyDefinition(person: PersonKey): Definition {
  return { title: "", description: "", area_id: "home", assignment: "fixed", assignees: [person], completion_mode: "individual",
    frequency: "once", on_date: localToday(), due_time: null, weekdays: [], steps: [], estimated_minutes: null,
    reminder_group: "daily_upkeep", enabled: false, readiness: "ready_after_setup", rotation_id: null, coverage_key: null }
}

export function localTime(value: string | null) {
  return value ? new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Belgrade", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(value)) : ""
}

export function moveDay(day: string, days: number) {
  const value = new Date(`${day}T12:00:00Z`)
  value.setUTCDate(value.getUTCDate() + days)
  return value.toISOString().slice(0, 10)
}

export function dayLabel(day: string, compact = false) {
  const value = new Date(`${day}T12:00:00Z`)
  const weekdays = ["E diel", "E hënë", "E martë", "E mërkurë", "E enjte", "E premte", "E shtunë"]
  const months = ["janar", "shkurt", "mars", "prill", "maj", "qershor", "korrik", "gusht", "shtator", "tetor", "nëntor", "dhjetor"]
  return `${compact ? "" : `${weekdays[value.getUTCDay()]}, `}${value.getUTCDate()} ${months[value.getUTCMonth()]}`
}
