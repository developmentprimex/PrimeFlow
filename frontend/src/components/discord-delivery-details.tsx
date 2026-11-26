"use client"

import { ExternalLink } from "lucide-react"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog"

export type DiscordDelivery = {
  status: "on_time" | "late" | "missing" | "pending" | "unlinked" | "unavailable" | "ambiguous"
  verified_at?: string
  url?: string
  details?: { content: string; attachments: { name: string; url?: string }[] }
}

export function DiscordDeliveryDetails({ delivery, label }: { delivery?: DiscordDelivery; label: string }) {
  const details = delivery?.details
  if (!details) return null

  return (
    <Dialog>
      <DialogTrigger asChild>
        <button type="button" aria-label={`Shiko dorëzimin për ${label}`}
          className="mt-1 block w-fit rounded-sm text-left text-xs font-medium underline underline-offset-2 focus-visible:outline-2">
          Shiko dorëzimin
        </button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Dorëzimi në Discord</DialogTitle>
          <DialogDescription className="break-words">{label}</DialogDescription>
        </DialogHeader>
        {details.content && (
          <p className="whitespace-pre-wrap [overflow-wrap:anywhere] rounded-md border bg-muted/40 p-3 text-sm">
            {details.content}
          </p>
        )}
        {details.attachments.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-sm font-semibold">Skedarët e bashkëngjitur</h3>
            <ul className="list-disc space-y-1 pl-5 text-sm [overflow-wrap:anywhere]">
              {details.attachments.map((file, index) => (
                <li key={index}>
                  {file.url
                    ? <a href={file.url} target="_blank" rel="noreferrer" className="underline underline-offset-2">{file.name}</a>
                    : file.name}
                </li>
              ))}
            </ul>
          </div>
        )}
        {delivery.url && (
          <a href={delivery.url} target="_blank" rel="noreferrer"
            className="flex w-fit items-center gap-1 text-sm underline underline-offset-2">
            Hap postimin në Discord <ExternalLink className="size-3" aria-hidden="true" />
          </a>
        )}
      </DialogContent>
    </Dialog>
  )
}
