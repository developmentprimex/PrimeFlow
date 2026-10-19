"use client"

import * as React from "react"
import { toast } from "sonner"

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { useAuth } from "@/lib/auth"

export function AccountMenu({ initials }: { initials: string }) {
  const { user, apiFetch, logout } = useAuth()
  const canUsePhoto = user?.email.trim().toLowerCase() === "42primex.eu@gmail.com"
  const userId = user?.id
  const [photo, setPhoto] = React.useState<{ userId: string; url: string } | null>(null)
  const [version, setVersion] = React.useState(0)
  const [busy, setBusy] = React.useState(false)
  const input = React.useRef<HTMLInputElement>(null)
  const photoUrl = canUsePhoto && photo && photo.userId === userId ? photo.url : undefined

  React.useEffect(() => {
    if (!canUsePhoto || !userId) return
    let cancelled = false
    let objectUrl: string | undefined
    const load = async () => {
      try {
        const response = await apiFetch("/profile-photo", { cache: "no-store" })
        if (!response.ok) {
          if (!cancelled) setPhoto(null)
          return
        }
        const blob = await response.blob()
        if (cancelled) return
        objectUrl = URL.createObjectURL(blob)
        setPhoto({ userId, url: objectUrl })
      } catch {
        if (!cancelled) setPhoto(null)
      }
    }
    void load()
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [apiFetch, canUsePhoto, userId, version])

  const updatePhoto = async (file?: File) => {
    if (!canUsePhoto || busy) return
    if (file && file.size > 5 * 1024 * 1024) {
      toast.error("Photo must be at most 5 MB")
      return
    }
    setBusy(true)
    try {
      const body = new FormData()
      if (file) body.append("file", file)
      const response = await apiFetch("/profile-photo", {
        method: file ? "PUT" : "DELETE",
        ...(file ? { body } : {}),
      })
      if (!response.ok) {
        const error = await response.json().catch(() => null)
        throw new Error(error?.detail || "Could not update profile photo")
      }
      setPhoto(null)
      setVersion((current) => current + 1)
      toast.success(file ? "Profile photo saved. Only you can see it." : "Profile photo removed")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not update profile photo")
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {canUsePhoto ? (
        <input
          ref={input}
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="hidden"
          aria-label="Upload private profile photo"
          disabled={busy}
          onChange={(event) => {
            const file = event.target.files?.[0]
            event.target.value = ""
            if (file) void updatePhoto(file)
          }}
        />
      ) : null}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" className="h-10 w-10 rounded-full p-0" aria-label="Account menu">
            <Avatar className="h-8 w-8">
              {photoUrl ? <AvatarImage src={photoUrl} alt="Your private profile photo" className="object-cover" /> : null}
              <AvatarFallback>{initials}</AvatarFallback>
            </Avatar>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {canUsePhoto ? (
            <>
              <DropdownMenuItem disabled={busy} onClick={() => input.current?.click()}>
                {busy ? "Saving photo…" : photoUrl ? "Change profile photo" : "Upload profile photo"}
              </DropdownMenuItem>
              {photoUrl ? (
                <DropdownMenuItem disabled={busy} onClick={() => void updatePhoto()}>
                  Remove profile photo
                </DropdownMenuItem>
              ) : null}
            </>
          ) : null}
          <DropdownMenuItem onClick={() => void logout()}>Sign out</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  )
}
