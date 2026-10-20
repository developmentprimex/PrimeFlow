"use client"

import * as React from "react"
import Link from "next/link"

import { toast } from "sonner"
import { playMeetingReminderSound, unlockMeetingReminderAudio } from "@/lib/meeting-reminder-audio"

import type { Meeting, User } from "@/lib/types"

type Props = {
  meeting: Meeting | null
  users: User[]
  canEdit: boolean
  saving: boolean
  formatWhen: (meeting: Meeting) => string
  onClose: () => void
  onSave: (participantIds: string[], reminderMinutes: number | null) => Promise<void>
}

const REMINDER_OPTIONS = [
  { value: "off", label: "No reminder" },
  { value: "0", label: "At meeting start" },
  { value: "5", label: "5 minutes before meeting" },
  { value: "10", label: "10 minutes before meeting" },
  { value: "15", label: "15 minutes before meeting" },
  { value: "30", label: "30 minutes before meeting" },
  { value: "60", label: "1 hour before meeting" },
] as const

function userLabel(user: User) {
  return user.full_name || user.username || user.email
}

export function MeetingDetailsDialog({
  meeting,
  users,
  canEdit,
  saving,
  formatWhen,
  onClose,
  onSave,
}: Props) {
  const [participantIds, setParticipantIds] = React.useState<string[]>([])
  const [reminderMinutes, setReminderMinutes] = React.useState<number | null>(15)
  const [search, setSearch] = React.useState("")
  const [notificationPermission, setNotificationPermission] = React.useState<NotificationPermission | "unsupported">("unsupported")

  React.useEffect(() => {
    if (!meeting) return
    setParticipantIds(meeting.participant_ids || [])
    setReminderMinutes(meeting.reminder_minutes_before === undefined ? 15 : meeting.reminder_minutes_before)
    setSearch("")
    setNotificationPermission("Notification" in window ? Notification.permission : "unsupported")
  }, [meeting])

  const originalIds = meeting?.participant_ids || []
  const isDirty = Boolean(meeting) && (
    [...participantIds].sort().join(",") !== [...originalIds].sort().join(",")
    || reminderMinutes !== (meeting?.reminder_minutes_before === undefined ? 15 : meeting.reminder_minutes_before)
  )

  const requestClose = React.useCallback(() => {
    if (saving) return
    if (isDirty && !window.confirm("Discard unsaved participant and reminder changes?")) return
    onClose()
  }, [isDirty, onClose, saving])

  React.useEffect(() => {
    if (!meeting) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") requestClose()
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [meeting, requestClose])

  if (!meeting) return null

  const activeUsers = users
    .filter((user) => user.is_active)
    .filter((user) => userLabel(user).toLowerCase().includes(search.trim().toLowerCase()))
  const userById = new Map(users.map((user) => [user.id, user]))

  const enableBrowserAlerts = async () => {
    const audioReady = unlockMeetingReminderAudio()
    if (!("Notification" in window)) return
    const permission = await Notification.requestPermission()
    setNotificationPermission(permission)
    await audioReady
    if (permission === "granted") void testBrowserAlerts()
  }

  const testBrowserAlerts = async () => {
    const ready = await unlockMeetingReminderAudio()
    if (!ready || !playMeetingReminderSound()) {
      toast.error("Sound could not start. Click Test sound again and check this tab’s sound settings.")
      return
    }
    toast.success("Test sound played. Check that you can hear it.")
    if (!("Notification" in window) || Notification.permission !== "granted") return
    new Notification("PrimeFlow browser alerts enabled", {
      body: "Meeting reminder popups and sounds are ready on this browser.",
      tag: "primeflow-browser-alert-test",
    })
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="meeting-details-title"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) requestClose()
      }}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 80,
        display: "grid",
        placeItems: "center",
        padding: "20px",
        background: "rgba(15, 23, 42, 0.55)",
      }}
    >
      <div style={{ width: "min(620px, 100%)", maxHeight: "90vh", overflowY: "auto", borderRadius: "16px", background: "#ffffff", padding: "22px", boxShadow: "0 24px 60px rgba(15, 23, 42, 0.3)" }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "16px" }}>
          <div>
            <div id="meeting-details-title" style={{ fontSize: "20px", fontWeight: 800, color: "#0f172a" }}>Meeting Details</div>
            <div style={{ marginTop: "8px", fontSize: "16px", fontWeight: 700 }}>{meeting.title}</div>
            <Link className="text-sm underline" href={`/meeting-recordings?meeting_id=${meeting.id}&title=${encodeURIComponent(meeting.title)}`} onClick={onClose}>Regjistro këtë takim</Link>
            <div className="external-meeting-meta" style={{ marginTop: "5px" }}>
              <span>{formatWhen(meeting)}</span>
              <span>{meeting.platform || "Platform TBD"}</span>
            </div>
            <div className="external-meeting-meta">
              <span>Source: {meeting.calendar_imported ? "Outlook Calendar" : "PrimeFlow"}</span>
            </div>
          </div>
          <button className="btn-surface" type="button" onClick={requestClose} disabled={saving}>Close</button>
        </div>

        <div style={{ marginTop: "22px", borderTop: "1px solid #e2e8f0", paddingTop: "18px" }}>
          <div style={{ fontSize: "14px", fontWeight: 800, color: "#0f172a" }}>PrimeFlow Participants</div>
          <div style={{ marginTop: "4px", fontSize: "12px", color: "#64748b" }}>
            Only users selected here receive PrimeFlow reminders. Calendar attendees are never added automatically.
          </div>
          {!canEdit ? (
            <div style={{ marginTop: "10px", padding: "8px 10px", borderRadius: "8px", background: "#f8fafc", color: "#64748b", fontSize: "12px" }}>
              You can view these settings, but only the meeting owner, its department, managers, or admins can change them.
            </div>
          ) : null}
          {participantIds.length ? (
            <div className="external-person-chips" style={{ marginTop: "10px" }} aria-label="Assigned PrimeFlow participants">
              {participantIds.map((participantId) => {
                const participant = userById.get(participantId)
                if (!participant) return null
                return (
                  <button
                    key={participantId}
                    className="external-person-chip"
                    type="button"
                    disabled={!canEdit}
                    onClick={() => setParticipantIds((current) => current.filter((id) => id !== participantId))}
                    title={canEdit ? `Remove ${userLabel(participant)}` : userLabel(participant)}
                  >
                    <span>{userLabel(participant)}</span>
                    {canEdit ? <span className="external-person-chip-remove" aria-hidden="true">&times;</span> : null}
                  </button>
                )
              })}
            </div>
          ) : (
            <div style={{ marginTop: "10px", fontSize: "13px", color: "#64748b" }}>No users assigned</div>
          )}
          {canEdit ? (
            <>
              <input
                className="input"
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search PrimeFlow users..."
                aria-label="Search PrimeFlow users"
                style={{ marginTop: "12px", width: "100%" }}
              />
              <div style={{ marginTop: "8px", maxHeight: "180px", overflowY: "auto", border: "1px solid #e2e8f0", borderRadius: "10px", padding: "6px" }}>
                {activeUsers.map((candidate) => (
                  <label key={candidate.id} className="external-person-picker-option">
                    <input
                      type="checkbox"
                      checked={participantIds.includes(candidate.id)}
                      onChange={(event) => setParticipantIds((current) => event.target.checked
                        ? Array.from(new Set([...current, candidate.id]))
                        : current.filter((id) => id !== candidate.id))}
                    />
                    <span>{userLabel(candidate)}</span>
                  </label>
                ))}
                {!activeUsers.length ? <div style={{ padding: "8px", fontSize: "12px", color: "#64748b" }}>No users found</div> : null}
              </div>
            </>
          ) : null}
        </div>

        <label style={{ display: "grid", gap: "7px", marginTop: "18px", fontSize: "14px", fontWeight: 800, color: "#0f172a" }}>
          Reminder
          <select
            className="input"
            disabled={!canEdit}
            value={reminderMinutes === null ? "off" : String(reminderMinutes)}
            onChange={(event) => setReminderMinutes(event.target.value === "off" ? null : Number(event.target.value))}
          >
            {REMINDER_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>

        <div style={{ marginTop: "14px", display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: "12px", padding: "10px", borderRadius: "10px", background: "#f8fafc" }}>
          <div style={{ fontSize: "12px", color: "#475569" }}>
            Browser alerts: {notificationPermission === "unsupported" ? "unsupported" : notificationPermission}
          </div>
          <button className="btn-surface" type="button" onClick={() => void testBrowserAlerts()}>Test sound</button>
          {notificationPermission === "default" ? (
            <button className="btn-surface" type="button" onClick={() => void enableBrowserAlerts()}>Enable browser alerts</button>
          ) : notificationPermission === "granted" ? (
            <button className="btn-surface" type="button" onClick={() => void testBrowserAlerts()}>Test browser alert</button>
          ) : null}
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "22px" }}>
          <button className="btn-surface" type="button" onClick={requestClose} disabled={saving}>{canEdit ? "Cancel" : "Close"}</button>
          {canEdit ? (
            <button
              className="btn-primary"
              type="button"
              onClick={() => void onSave(participantIds, reminderMinutes)}
              disabled={saving || !isDirty}
              style={{ background: "#2563eb", color: "#ffffff" }}
            >
              {saving ? "Saving..." : "Save participants & reminder"}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  )
}
