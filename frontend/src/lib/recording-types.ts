export type MeetingRecording = {
  id: string; meeting_id: string | null; created_by: string; title: string; description: string | null
  capture_source_type: string; status: "CREATED" | "RECORDING" | "UPLOADING" | "FINALIZING" | "READY" | "FAILED"
  recording_started_at: string; recording_stopped_at: string | null; duration_seconds: number | null
  mime_type: string; video_width: number | null; video_height: number | null
  has_microphone_audio: boolean; has_system_audio: boolean; is_partial: boolean; size_bytes: number; chunks_received: number
  upload_completed_at: string | null; created_at: string; updated_at: string; error_message: string | null
  recorded_by_name: string | null; meeting_title: string | null
  media_available?: boolean | null
}
export const RECORDING_STATUS: Record<string, string> = {
  CREATED: "I krijuar", RECORDING: "Duke regjistruar", UPLOADING: "Duke ngarkuar", FINALIZING: "Duke përpunuar", READY: "I ruajtur", FAILED: "I dështuar",
}
export function recordingTime(seconds: number | null) {
  const n = Math.floor(seconds || 0)
  return `${Math.floor(n / 3600).toString().padStart(2, "0")}:${Math.floor(n / 60 % 60).toString().padStart(2, "0")}:${(n % 60).toString().padStart(2, "0")}`
}
export function recordingSize(bytes: number) { return `${(bytes / 1024 / 1024).toFixed(1)} MB` }
