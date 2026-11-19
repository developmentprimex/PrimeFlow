"use client"

import * as React from "react"
import { useRouter, useSearchParams } from "next/navigation"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuth } from "@/lib/auth"

type AuthorizationRequest = {
  request_id: string
  client_name: string
  redirect_host: string
  scope: string | null
  user_email: string
  allowed: boolean
}

// Consent step of the PrimeFlow OAuth server used by the remote MCP assistant
// (e.g. the claude.ai custom connector). The backend /oauth/authorize redirects
// here; approval returns the browser to the client's registered redirect URI.
export default function OAuthConsentPage() {
  return (
    <React.Suspense fallback={null}>
      <OAuthConsent />
    </React.Suspense>
  )
}

function OAuthConsent() {
  const router = useRouter()
  const requestId = useSearchParams().get("request_id") || ""
  const { user, loading, apiFetch } = useAuth()
  const [request, setRequest] = React.useState<AuthorizationRequest | null>(null)
  const [loadError, setLoadError] = React.useState<string | null>(null)
  const [submitting, setSubmitting] = React.useState(false)
  const error = requestId ? loadError : "Kërkesa e autorizimit mungon."

  React.useEffect(() => {
    if (loading || !requestId) return
    if (!user) {
      const next = `/oauth/consent?request_id=${encodeURIComponent(requestId)}`
      router.push(`/login?next=${encodeURIComponent(next)}`)
      return
    }
    let cancelled = false
    void (async () => {
      const res = await apiFetch(`/oauth/requests/${encodeURIComponent(requestId)}`)
      if (cancelled) return
      if (!res.ok) {
        setLoadError("Kërkesa e autorizimit ka skaduar ose nuk ekziston. Provo lidhjen përsëri nga Claude.")
        return
      }
      setRequest((await res.json()) as AuthorizationRequest)
    })()
    return () => {
      cancelled = true
    }
  }, [apiFetch, loading, requestId, router, user])

  const decide = async (decision: "approve" | "deny") => {
    if (!request) return
    setSubmitting(true)
    setLoadError(null)
    try {
      const res = await apiFetch(`/oauth/requests/${encodeURIComponent(request.request_id)}/${decision}`, {
        method: "POST",
      })
      const data = (await res.json().catch(() => null)) as { redirect_url?: string; detail?: string } | null
      if (!res.ok || !data?.redirect_url) {
        setLoadError(data?.detail || "Autorizimi dështoi.")
        return
      }
      window.location.assign(data.redirect_url)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Lidh asistentin me PrimeFlow</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-sm">
          {error ? <div className="text-destructive">{error}</div> : null}
          {!error && !request ? <div className="text-muted-foreground">Duke ngarkuar…</div> : null}
          {request ? (
            <>
              <p>
                <strong>{request.client_name}</strong> ({request.redirect_host}) kërkon qasje në PrimeFlow në emrin
                tënd: të lexojë agjendën dhe detyrat, dhe të shënojë detyra si të kryera, t&apos;i shtyjë ose t&apos;u
                ndryshojë orën.
              </p>
              <p className="text-muted-foreground">Llogaria: {request.user_email}</p>
              {request.allowed ? (
                <div className="flex gap-2">
                  <Button className="flex-1" disabled={submitting} onClick={() => void decide("approve")}>
                    Lejo
                  </Button>
                  <Button variant="outline" className="flex-1" disabled={submitting} onClick={() => void decide("deny")}>
                    Refuzo
                  </Button>
                </div>
              ) : (
                <>
                  <div className="text-destructive">Kjo llogari nuk lejohet të lidhë asistentin.</div>
                  <Button variant="outline" disabled={submitting} onClick={() => void decide("deny")}>
                    Kthehu
                  </Button>
                </>
              )}
            </>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
