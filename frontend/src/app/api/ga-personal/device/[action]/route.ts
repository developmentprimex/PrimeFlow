import { API_HTTP_URL } from "@/lib/config"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
type Context = { params: Promise<{ action: string }> }
const MAX_BYTES = 2 * 1024 * 1024
const privateHeaders = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" }
const failure = (status: number, detail: string) => Response.json({ detail }, { status, headers: privateHeaders })

async function proxy(request: Request, context: Context): Promise<Response> {
  const { action } = await context.params
  if (!((action === "state" && request.method === "GET") || (action === "ops" && request.method === "POST"))) {
    return failure(404, "Rruga nuk u gjet.")
  }
  const authorization = request.headers.get("authorization")
  const deviceId = request.headers.get("x-device-id")
  if (!authorization || !deviceId) return failure(401, "Kërkohet kodi dhe ID e pajisjes.")
  const headers = new Headers({ Authorization: authorization, "X-Device-Id": deviceId, Accept: "application/json" })
  let body: Buffer<ArrayBuffer> | undefined
  if (request.method === "POST") {
    if ((request.headers.get("content-type") || "").split(";", 1)[0].trim().toLowerCase() !== "application/json") {
      return failure(415, "Kërkohet application/json.")
    }
    if (Number(request.headers.get("content-length")) > MAX_BYTES) return failure(413, "Kërkesa duhet të jetë deri në 2 MB.")
    const reader = request.body?.getReader()
    if (!reader) return failure(400, "Mungon trupi i kërkesës.")
    const chunks: Uint8Array[] = []
    let size = 0
    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        size += value.byteLength
        if (size > MAX_BYTES) { await reader.cancel(); return failure(413, "Kërkesa duhet të jetë deri në 2 MB.") }
        chunks.push(value)
      }
    } catch { return failure(400, "Kërkesa nuk u lexua.") }
    body = Buffer.concat(chunks)
    headers.set("Content-Type", "application/json")
  }
  const url = new URL(`${API_HTTP_URL}/ga-personal/device/${action}`)
  const since = new URL(request.url).searchParams.get("since")
  if (action === "state" && since !== null) url.searchParams.set("since", since)
  try {
    const upstream = await fetch(url, { method: request.method, headers, body, cache: "no-store", redirect: "error",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(30_000)]) })
    if (!(upstream.headers.get("content-type") || "").includes("application/json")) {
      return failure(502, "PrimeFlow nuk ktheu përgjigje JSON. Provo përsëri.")
    }
    const responseHeaders = new Headers({ ...privateHeaders, "Content-Type": "application/json" })
    const challenge = upstream.headers.get("www-authenticate")
    if (challenge) responseHeaders.set("WWW-Authenticate", challenge)
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders })
  } catch { return failure(503, "Lidhja me PrimeFlow u ndërpre. Provo përsëri.") }
}

export const GET = proxy
export const POST = proxy
