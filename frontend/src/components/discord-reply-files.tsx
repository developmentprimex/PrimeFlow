"use client"

import * as React from "react"
import { Paperclip } from "lucide-react"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useAuth } from "@/lib/auth"

export type DiscordReplyReport = { report: "M1" | "M2"; date: string; source?: "reaction" }
type DiscordFile = { url: string; filename: string; image: boolean }

export function DiscordReplyFiles({ value, report }: { value: string; report: DiscordReplyReport }) {
  const { apiFetch } = useAuth()
  const [files, setFiles] = React.useState<DiscordFile[] | null>(null)
  const [loading, setLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [preview, setPreview] = React.useState<DiscordFile | null>(null)
  const [previewFailed, setPreviewFailed] = React.useState(false)
  const source = /^(\d+)\s+(https:\/\/discord\.com\/channels\/\d+\/\d+\/(\d+))$/.exec(value)
  if (!source) return value || "-"
  const [, count, discordUrl, messageId] = source
  const label = count === "1" ? "1 skedar" : `${count} skedarë`

  async function load() {
    setFiles(null)
    setError(null)
    setLoading(true)
    try {
      const query = new URLSearchParams({ report: report.report, report_date: report.date, message_id: messageId })
      if (report.source) query.set("source", report.source)
      const response = await apiFetch(`/discord/ga-replies/attachments?${query}`)
      if (!response.ok) {
        const payload = await response.json().catch(() => null)
        setError(payload?.detail?.code === "discord_preview_not_configured"
          ? payload.detail.message : "Pamja paraprake nuk u ngarkua. Mund të provosh përsëri.")
        return
      }
      setFiles(await response.json())
    } catch {
      setError("Pamja paraprake nuk u ngarkua. Mund të provosh përsëri.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <details className="min-w-28" onToggle={(event) => {
        if (event.currentTarget.open && !loading) void load()
      }}>
        <summary className="cursor-pointer whitespace-nowrap font-medium text-blue-700">
          <Paperclip className="ml-1 inline size-3" /> {label}
        </summary>
        <div className="mt-2 space-y-2">
          {loading ? <p role="status">Duke hapur skedarët…</p> : null}
          {error ? <p role="status" className="max-w-60 whitespace-normal">{error}</p> : null}
          {files?.length === 0 ? <p role="status">Mesazhi nuk ka më bashkëngjitje.</p> : null}
          {files?.map((file) => file.image ? (
            <button key={file.url} type="button" className="block max-w-52 cursor-zoom-in break-all text-left text-blue-700 underline"
              onClick={() => { setPreviewFailed(false); setPreview(file) }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={file.url} alt="" loading="lazy" referrerPolicy="no-referrer" className="mb-1 max-h-36 w-auto rounded object-contain" />
              {file.filename}
            </button>
          ) : (
            <a key={file.url} href={file.url} target="_blank" rel="noreferrer" className="block max-w-52 break-all text-blue-700 underline">
              {file.filename}
            </a>
          ))}
          <a href={discordUrl} target="_blank" rel="noreferrer" className="block whitespace-nowrap text-blue-700 underline">
            Hap në Discord
          </a>
        </div>
      </details>
      <Dialog open={Boolean(preview)} onOpenChange={(open) => { if (!open) setPreview(null) }}>
        <DialogContent className="w-[96vw] sm:max-w-5xl" aria-describedby={undefined}>
          {preview ? (
            <>
              <DialogHeader>
                <DialogTitle className="break-all pr-8">{preview.filename}</DialogTitle>
              </DialogHeader>
              {previewFailed ? (
                <p role="status" className="text-sm">Fotografia nuk u ngarkua. Rihap listën për të rifreskuar skedarin.</p>
              ) : (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={preview.url} alt={preview.filename} referrerPolicy="no-referrer" onError={() => setPreviewFailed(true)}
                  className="mx-auto max-h-[75vh] max-w-full rounded object-contain" />
              )}
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  )
}
