import { NextRequest, NextResponse } from "next/server"
import { API_HTTP_URL } from "@/lib/config"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
type Context = { params: Promise<{ id: string; action: string }> }
const validId = (id: string) => /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)

export async function POST(request: NextRequest, context: Context) {
  const { id, action } = await context.params
  if (!validId(id) || action !== "playback") return new Response(null, { status: 404 })
  // Next.js may build request.url using its internal hostname. The public Host
  // is preserved by our reverse proxy; forwarded protocol is proxy-controlled.
  const protocol = request.headers.get("x-forwarded-proto") || new URL(request.url).protocol.slice(0, -1)
  const expectedOrigin = `${protocol}://${request.headers.get("host")}`
  if (request.headers.get("origin") !== expectedOrigin) return new Response(null, { status: 403 })
  const reader = request.body?.getReader()
  if (!reader) return new Response(null, { status: 400 })
  const decoder = new TextDecoder()
  let text = "", bytes = 0
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    bytes += value.byteLength
    if (bytes > 4096) { await reader.cancel(); return new Response(null, { status: 413 }) }
    text += decoder.decode(value, { stream: true })
  }
  text += decoder.decode()
  let token: unknown
  try { token = JSON.parse(text).token } catch { return new Response(null, { status: 400 }) }
  if (typeof token !== "string" || !/^[A-Za-z0-9_.-]{50,3000}$/.test(token)) return new Response(null, { status: 400 })
  // A scoped 15-minute backend grant, never an access/refresh token. Backend
  // verifies its signature, recording scope, active user and current RBAC.
  const response = NextResponse.json({ ok: true }, { headers: { "Cache-Control": "no-store" } })
  response.cookies.set(`px-recording-${id}`, token, { httpOnly: true, secure: protocol === "https" || process.env.NODE_ENV === "production", sameSite: "strict", path: `/api/meeting-recordings/${id}`, maxAge: 900 })
  return response
}

async function proxy(request: NextRequest, context: Context) {
  const { id, action } = await context.params
  if (!validId(id) || !["stream", "download"].includes(action)) return new Response(null, { status: 404 })
  const token = request.cookies.get(`px-recording-${id}`)?.value
  if (!token) return new Response(null, { status: 401 })
  const headers = new Headers({ Authorization: `Bearer ${token}`, "Accept-Encoding": "identity" })
  for (const key of ["range", "if-range"]) { const value = request.headers.get(key); if (value) headers.set(key, value) }
  try {
    const base = (process.env.MEETING_RECORDINGS_API_URL || API_HTTP_URL).replace(/\/$/, "")
    const upstream = await fetch(`${base}/meeting-recordings/${id}/${action}`, { method: request.method, headers, cache: "no-store", redirect: "error", signal: request.signal })
    const responseHeaders = new Headers({ "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" })
    for (const key of ["content-type", "content-length", "content-range", "accept-ranges", "content-disposition", "etag", "last-modified"]) {
      const value = upstream.headers.get(key); if (value) responseHeaders.set(key, value)
    }
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders })
  } catch { return NextResponse.json({ detail: "Recording storage is unavailable" }, { status: 503, headers: { "Cache-Control": "no-store" } }) }
}
export const GET = proxy
export const HEAD = proxy
