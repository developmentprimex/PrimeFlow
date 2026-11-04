"use client"

import * as React from "react"
import { ImageIcon, Paperclip, X } from "lucide-react"
import { useAuth } from "@/lib/auth"
import type { MeetingNoteAttachment } from "@/lib/meeting-notes"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"

const blobCache = new Map<string, string>()

function useAttachmentUrl(attachment: MeetingNoteAttachment) {
  const { apiFetch } = useAuth()
  const [url, setUrl] = React.useState<string | null>(() => blobCache.get(attachment.id) || null)
  const isImage = (attachment.content_type || "").startsWith("image/")
  React.useEffect(() => {
    if (!isImage || blobCache.has(attachment.id)) return
    let active = true
    void apiFetch(`/meeting-notes/attachments/${attachment.id}`).then(async (response) => {
      if (!response.ok) return
      const objectUrl = URL.createObjectURL(await response.blob())
      blobCache.set(attachment.id, objectUrl)
      if (active) setUrl(objectUrl)
    }).catch(() => {})
    return () => { active = false }
  }, [apiFetch, attachment.id, isImage])
  return { url, isImage }
}

export function AttachmentThumb({ attachment, onDelete }: { attachment: MeetingNoteAttachment; onDelete?: () => void }) {
  const { apiFetch } = useAuth()
  const { url, isImage } = useAttachmentUrl(attachment)
  const [open, setOpen] = React.useState(false)
  const download = async () => {
    const response = await apiFetch(`/meeting-notes/attachments/${attachment.id}`)
    if (!response.ok) return
    const objectUrl = URL.createObjectURL(await response.blob())
    const link = document.createElement("a")
    link.href = objectUrl
    link.download = attachment.original_filename
    link.click()
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
  }
  return <>
    <span className="relative inline-flex">
      <button type="button" title={attachment.original_filename} aria-label={`Hap ${attachment.original_filename}`}
        className="flex h-11 w-[72px] items-center justify-center overflow-hidden rounded border border-slate-600 bg-white text-muted-foreground"
        onClick={() => isImage ? setOpen(true) : void download()}>
        {isImage && url ? <img src={url} alt="" className="h-full w-full object-cover" /> : isImage ? <ImageIcon className="size-4" aria-hidden="true" /> : <Paperclip className="size-4" aria-hidden="true" />}
      </button>
      {onDelete && <button type="button" aria-label="Hiq skedarin" onClick={onDelete}
        className="absolute -right-1.5 -top-1.5 flex size-5 items-center justify-center rounded-full border bg-white text-xs shadow-sm hover:bg-muted" data-button-shape="circle">
        <X className="size-3" aria-hidden="true" />
      </button>}
    </span>
    {open && <Dialog open onOpenChange={setOpen}>
      <DialogContent className="max-w-4xl">
        <DialogHeader><DialogTitle className="truncate pr-8">{attachment.original_filename}</DialogTitle></DialogHeader>
        {url ? <img src={url} alt={attachment.original_filename} className="max-h-[75vh] w-full rounded-md border object-contain" /> : <p className="text-sm text-muted-foreground">Duke ngarkuar…</p>}
        <div className="flex justify-end"><Button variant="outline" onClick={() => void download()}>Shkarko</Button></div>
      </DialogContent>
    </Dialog>}
  </>
}

/** Local preview of a screenshot that is not uploaded yet. */
export function PendingThumb({ file, onRemove }: { file: File; onRemove: () => void }) {
  const [url, setUrl] = React.useState<string | null>(null)
  React.useEffect(() => {
    const objectUrl = URL.createObjectURL(file)
    setUrl(objectUrl)
    return () => URL.revokeObjectURL(objectUrl)
  }, [file])
  return <span className="relative inline-flex">
    <span className="flex h-[76px] w-32 items-center justify-center overflow-hidden rounded-md border border-neutral-400 bg-slate-100">
      {url && file.type.startsWith("image/") ? <img src={url} alt={file.name} className="h-full w-full object-cover" /> : <span className="px-2 text-center text-xs text-muted-foreground">{file.name}</span>}
    </span>
    <button type="button" aria-label={`Hiq ${file.name}`} onClick={onRemove}
      className="absolute right-1 top-1 flex size-5 items-center justify-center rounded bg-white text-xs shadow-sm hover:bg-muted">
      <X className="size-3" aria-hidden="true" />
    </button>
  </span>
}
