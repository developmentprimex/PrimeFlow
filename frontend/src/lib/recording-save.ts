import type { MeetingRecording } from "./recording-types"

type SaveFileWindow = Window & {
  showSaveFilePicker?: (options: {
    suggestedName: string
    types: { description: string; accept: Record<string, string[]> }[]
  }) => Promise<FileSystemFileHandle>
}

export async function saveRecordingFile(recording: Pick<MeetingRecording, "id" | "title" | "mime_type">) {
  const picker = (window as SaveFileWindow).showSaveFilePicker
  if (!picker) return "unsupported" as const
  const mime = recording.mime_type.split(";")[0]
  const extension = mime === "video/mp4" ? ".mp4" : ".webm"
  const title = recording.title.replace(/[\\/:*?"<>|]/g, "-").replace(/\s+/g, " ").trim().slice(0, 150)
  let handle: FileSystemFileHandle
  try {
    // Open the picker before any network request, while the click is active.
    handle = await picker.call(window, {
      suggestedName: `Regjistrim - ${title || recording.id}${extension}`,
      types: [{ description: "Video e regjistrimit", accept: { [mime]: [extension] } }],
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return "cancelled" as const
    throw error
  }
  const response = await fetch(`/api/meeting-recordings/${recording.id}/download`, { credentials: "same-origin", cache: "no-store" })
  if (response.status !== 200 || !response.body || response.headers.get("content-type")?.split(";")[0] !== mime) {
    await response.body?.cancel()
    throw new Error("Videoja nuk mund të shkarkohet. Rifreskoni faqen dhe provoni përsëri.")
  }
  try {
    const writable = await handle.createWritable()
    // Stream large videos directly to disk without keeping the whole file in memory.
    await response.body.pipeTo(writable)
  } catch (error) {
    await response.body.cancel().catch(() => {})
    throw error
  }
  return "saved" as const
}
