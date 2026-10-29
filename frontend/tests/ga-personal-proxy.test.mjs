import assert from "node:assert/strict"
import { test } from "node:test"
import { readFileSync } from "node:fs"
import vm from "node:vm"
import ts from "typescript"

function proxy(fetch) {
  const source = readFileSync(new URL("../src/app/api/ga-personal/device/[action]/route.ts", import.meta.url), "utf8")
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } })
  const loaded = { exports: {} }
  vm.runInNewContext(outputText, { module: loaded, exports: loaded.exports,
    require: () => ({ API_HTTP_URL: "https://api.example/api" }), fetch, Request, Response, Headers, URL, Buffer, AbortSignal })
  return loaded.exports
}
const context = (action) => ({ params: Promise.resolve({ action }) })
const headers = { Authorization: "Bearer pfgap_device_test_only", "X-Device-Id": "11111111-1111-4111-8111-111111111111" }

test("state proxy keeps the exact cursor and forwards only tablet credentials to the fixed backend", async () => {
  const since = "2026-10-29T13:00:00+00:00"
  const api = proxy(async (url, init) => {
    assert.equal(url.origin, "https://api.example")
    assert.equal(url.pathname, "/api/ga-personal/device/state")
    assert.equal(url.searchParams.get("since"), since)
    assert.equal(url.searchParams.has("upstream"), false)
    assert.equal(init.headers.get("authorization"), headers.Authorization)
    assert.equal(init.headers.get("x-device-id"), headers["X-Device-Id"])
    assert.equal(init.headers.get("cookie"), null)
    assert.equal(init.redirect, "error")
    assert.equal(init.cache, "no-store")
    return Response.json({ cursor: "next", tasks: [], events: [], statuses: [], arrivals: [] })
  })
  const request = new Request(`https://primeflow.example/api/ga-personal/device/state?since=${encodeURIComponent(since)}&upstream=https://evil.example`, { headers: { ...headers, cookie: "work-session=private" } })
  const response = await api.GET(request, context("state"))
  assert.equal(response.status, 200)
  assert.equal(response.headers.get("cache-control"), "private, no-store")
  assert.equal((await response.json()).cursor, "next")
})

test("ops proxy preserves the JSON payload and backend authentication failures", async () => {
  const payload = JSON.stringify({ device_id: headers["X-Device-Id"], ops: [] })
  const api = proxy(async (url, init) => {
    assert.equal(url.pathname, "/api/ga-personal/device/ops")
    assert.equal(init.method, "POST")
    assert.equal(init.body.toString(), payload)
    return Response.json({ detail: "revoked" }, { status: 401, headers: { "WWW-Authenticate": "Bearer" } })
  })
  const response = await api.POST(new Request("https://primeflow.example/api/ga-personal/device/ops", {
    method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: payload,
  }), context("ops"))
  assert.equal(response.status, 401)
  assert.equal(response.headers.get("www-authenticate"), "Bearer")
  assert.deepEqual(await response.json(), { detail: "revoked" })
})

test("proxy rejects missing credentials, arbitrary paths, oversized bodies and non-JSON gateway errors", async () => {
  let calls = 0
  const api = proxy(async () => { calls++; return new Response("gateway down", { status: 502 }) })
  assert.equal((await api.GET(new Request("https://app.example/api/ga-personal/device/state"), context("state"))).status, 401)
  assert.equal((await api.GET(new Request("https://app.example/api/ga-personal/device/password", { headers }), context("password"))).status, 404)
  assert.equal((await api.POST(new Request("https://app.example/api/ga-personal/device/ops", {
    method: "POST", headers: { ...headers, "Content-Type": "application/json", "Content-Length": String(2 * 1024 * 1024 + 1) }, body: "{}",
  }), context("ops"))).status, 413)
  assert.equal(calls, 0)
  const response = await api.GET(new Request("https://app.example/api/ga-personal/device/state", { headers }), context("state"))
  assert.equal(response.status, 502)
  assert.ok(response.headers.get("content-type").includes("application/json"))
  assert.equal(calls, 1)
})
