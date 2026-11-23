"use client"

import * as React from "react"
import { Paperclip } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { useAuth } from "@/lib/auth"

export type ReportNoteAttachment = { id: string; original_filename: string }
export type ReportNoteAttachments = Record<string, ReportNoteAttachment[]>

function viewLabel(files: ReportNoteAttachment[]) {
  return files.length === 1 ? "View" : `View (${files.length})`
}

export function ReportNoteCell({ text, files, onOpen }: {
  text: string
  files: ReportNoteAttachment[]
  onOpen: (files: ReportNoteAttachment[]) => void
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
      <span className="min-w-0 flex-1 break-words">{text || "-"}</span>
      <button
        type="button"
        className="inline-flex shrink-0 items-center gap-1 rounded border border-blue-300 bg-white px-2 py-0.5 font-medium text-blue-800 hover:bg-blue-50 print:hidden"
        title={files.map((file) => file.original_filename).join("\n")}
        onClick={() => onOpen(files)}
      >
        <Paperclip className="size-3" /> {viewLabel(files)}
      </button>
    </div>
  )
}

export function installReportNoteControls(
  document: Document | null | undefined,
  attachments: ReportNoteAttachments | undefined,
  onOpen: (files: ReportNoteAttachment[]) => void,
) {
  if (!document) return
  const className = "px-note-attachment-view"
  document.querySelectorAll(`.${className}`).forEach((button) => button.remove())
  if (!attachments || !Object.keys(attachments).length) return
  if (!document.getElementById("px-note-attachment-styles")) {
    const style = document.createElement("style")
    style.id = "px-note-attachment-styles"
    style.textContent = `
      .${className} { float:right; margin:0 0 2px 8px; padding:2px 7px; cursor:pointer;
        border:1px solid #93c5fd; border-radius:4px; color:#1e40af; background:#fff; font:600 11px Arial; }
      .${className}:hover { background:#eff6ff; }
      @media print { .${className} { display:none; } }
    `
    document.head.append(style)
  }
  const tables = Array.from(document.querySelectorAll<HTMLTableElement>(
    "table.report-table-notes, table[data-closing-table], table[data-undiscussed-notes-table]",
  )).filter((table) => {
    const headers = Array.from(table.rows[0]?.cells ?? [], (cell) => cell.textContent?.trim())
    return headers[0] === "NR" && headers.includes("NOTE")
  })
  if (tables.length !== 1) return
  const table = tables[0]
  const noteColumn = Array.from(table.rows[0].cells).findIndex((cell) => cell.textContent?.trim() === "NOTE")
  for (const row of Array.from(table.rows).slice(1)) {
    const number = row.cells[0]?.textContent?.trim() ?? ""
    if (!/^\d+$/.test(number)) continue
    const files = attachments[number]
    const cell = row.cells[noteColumn]
    if (!files?.length || !cell) continue
    const button = document.createElement("button")
    button.type = "button"
    button.className = className
    button.textContent = viewLabel(files)
    button.title = files.map((file) => file.original_filename).join("\n")
    button.addEventListener("click", () => onOpen(files))
    cell.prepend(button)
  }
}

export function ReportNoteAttachmentDialog({ files, onClose }: {
  files: ReportNoteAttachment[] | null
  onClose: () => void
}) {
  return (
    <Dialog open={Boolean(files)} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="w-[96vw] sm:max-w-5xl" aria-describedby={undefined}>
        {files?.length ? <AttachmentPreview files={files} /> : null}
      </DialogContent>
    </Dialog>
  )
}

function AttachmentPreview({ files }: { files: ReportNoteAttachment[] }) {
  const { apiFetch } = useAuth()
  const [selectedId, setSelectedId] = React.useState(files[0].id)
  const file = files.find(({ id }) => id === selectedId) ?? files[0]
  const [preview, setPreview] = React.useState<{ id: string; url: string; type: string } | null>(null)
  const [failedId, setFailedId] = React.useState<string | null>(null)
  const path = `/ga-notes/attachments/${encodeURIComponent(file.id)}`

  React.useEffect(() => {
    let active = true
    let url: string | undefined
    const controller = new AbortController()
    async function load() {
      try {
        const response = await apiFetch(`${path}/preview`, { signal: controller.signal })
        if (!response.ok) throw new Error("Preview unavailable")
        const blob = await response.blob()
        if (!active) return
        url = URL.createObjectURL(blob)
        setPreview({ id: file.id, url, type: blob.type })
        setFailedId(null)
      } catch {
        if (active) setFailedId(file.id)
      }
    }
    void load()
    return () => {
      active = false
      controller.abort()
      if (url) URL.revokeObjectURL(url)
    }
  }, [apiFetch, file.id, path])

  async function download() {
    try {
      const response = await apiFetch(path)
      if (!response.ok) throw new Error("Download unavailable")
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement("a")
      link.href = url
      link.download = file.original_filename
      document.body.append(link)
      link.click()
      link.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch {
      toast.error("Shkarkimi i skedarit dështoi.")
    }
  }

  return (
    <>
      <DialogHeader>
        <div className="flex items-center justify-between gap-3 pr-6">
          <DialogTitle className="min-w-0 truncate" title={file.original_filename}>{file.original_filename}</DialogTitle>
          <Button type="button" variant="outline" size="sm" onClick={() => void download()}>Download</Button>
        </div>
      </DialogHeader>
      {files.length > 1 ? (
        <select
          aria-label="Bashkëngjitjet"
          className="w-full rounded border bg-background px-2 py-1.5 text-sm"
          value={file.id}
          onChange={(event) => { setFailedId(null); setPreview(null); setSelectedId(event.target.value) }}
        >
          {files.map((item) => <option key={item.id} value={item.id}>{item.original_filename}</option>)}
        </select>
      ) : null}
      <div className="flex h-[68vh] items-center justify-center overflow-hidden rounded border bg-white text-slate-700">
        {failedId === file.id ? (
          <p role="alert" className="p-4 text-sm">Skedari nuk u hap. Provo ta shkarkosh.</p>
        ) : preview?.id !== file.id ? (
          <p role="status" className="p-4 text-sm">Duke hapur skedarin…</p>
        ) : preview.type.startsWith("image/") ? (
          // The authenticated preview is a local blob URL.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={preview.url} alt={file.original_filename} className="max-h-full max-w-full object-contain" />
        ) : preview.type.startsWith("audio/") ? (
          <audio src={preview.url} controls className="w-4/5" />
        ) : preview.type.startsWith("video/") ? (
          <video src={preview.url} controls className="max-h-full max-w-full" />
        ) : (
          <iframe
            src={preview.url}
            title={file.original_filename}
            sandbox={preview.type === "application/pdf" ? undefined : ""}
            className="h-full w-full border-0"
          />
        )}
      </div>
    </>
  )
}
