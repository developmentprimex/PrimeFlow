"use client"

import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { useRecorder } from "@/components/meeting-recordings/recorder-provider"
import { useAuth } from "@/lib/auth"
import type { MeetingRecording } from "@/lib/recording-types"

export function RecoverRetainedButton({ recording }: { recording: MeetingRecording }) {
  const { user } = useAuth()
  const { manifest, recoveries, busy, saving, recoverRetained } = useRecorder()
  if (recording.created_by !== user?.id || recording.status !== "FAILED" || recording.chunks_received <= 0
      || [manifest, ...recoveries].some(local => local?.id === recording.id)) return null

  const recover = async () => {
    if (!window.confirm("Të ruhet si regjistrim i pjesshëm pjesa që ka mbërritur në server? Fundi i takimit mund të mungojë.")) return
    try {
      await recoverRetained(recording.id, recording.chunks_received)
      toast.success("Pjesa e rikuperuar u ruajt.")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error))
    }
  }

  return <Button type="button" size="sm" variant="outline" disabled={busy || saving} onClick={() => void recover()}>
    Rikupero nga serveri
  </Button>
}
