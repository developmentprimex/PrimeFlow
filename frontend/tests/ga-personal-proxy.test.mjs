import assert from "node:assert/strict"
import { test } from "node:test"
import { readFileSync } from "node:fs"
import vm from "node:vm"
import ts from "typescript"

function proxy(fetch, env = {}) {
  const source = readFileSync(new URL("../src/app/api/ga-personal/device/[action]/route.ts", import.meta.url), "utf8")
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } })
  const loaded = { exports: {} }
  vm.runInNewContext(outputText, { module: loaded, exports: loaded.exports,
    require: () => ({ API_HTTP_URL: "https://api.example/api" }), process: { env }, fetch, Request, Response, Headers, URL, Buffer, AbortSignal })
  return loaded.exports
}
const context = (action) => ({ params: Promise.resolve({ action }) })
const headers = { Authorization: "Bearer pfgap_device_test_only", "X-Device-Id": "11111111-1111-4111-8111-111111111111" }
const origin = "http://localhost:8799"
function assertCors(response, expectedOrigin = origin) {
  assert.equal(response.headers.get("access-control-allow-origin"), expectedOrigin)
  assert.equal(response.headers.get("access-control-allow-headers"), "Authorization, X-Device-Id, Accept, Content-Type")
  assert.equal(response.headers.get("access-control-allow-methods"), "GET, POST, OPTIONS")
  assert.ok(response.headers.get("vary").split(",").map(value => value.trim()).includes("Origin"))
  assert.equal(response.headers.get("access-control-allow-credentials"), null)
}

test("Kujtesa preflights succeed without credentials or contacting the backend", async () => {
  const api = proxy(async () => { assert.fail("preflight must not call the backend") })
  for (const loopback of [origin, "http://127.0.0.1:8799", "http://[::1]:8799", "https://localhost:9000"]) {
    for (const [action, method] of [["state", "GET"], ["ops", "POST"]]) {
      const response = await api.OPTIONS(new Request(`https://primeflow.example/api/ga-personal/device/${action}`, {
        method: "OPTIONS", headers: { Origin: loopback, "Access-Control-Request-Method": method,
          "Access-Control-Request-Headers": "authorization,x-device-id,accept,content-type" },
      }), context(action))
      assert.equal(response.status, 204)
      assert.equal(await response.text(), "")
      assert.equal(response.headers.get("cache-control"), "private, no-store")
      assertCors(response, loopback)
    }
  }
})

test("preflight rejects untrusted origins, unsupported routes, methods and headers", async () => {
  const api = proxy(async () => { assert.fail("preflight must not call the backend") })
  for (const badOrigin of ["https://evil.example", "http://localhost.evil.example:8799", "null", "file://", "http://user@localhost:8799"]) {
    const response = await api.OPTIONS(new Request("https://primeflow.example/api/ga-personal/device/ops", {
      method: "OPTIONS", headers: { Origin: badOrigin, "Access-Control-Request-Method": "POST" },
    }), context("ops"))
    assert.equal(response.status, 403)
    assert.equal(response.headers.get("access-control-allow-origin"), null)
  }
  for (const [action, method, requestedHeaders, status] of [
    ["password", "POST", "authorization", 404], ["state", "POST", "authorization", 400],
    ["ops", "DELETE", "authorization", 400], ["ops", "POST", "cookie", 400],
  ]) {
    const response = await api.OPTIONS(new Request(`https://primeflow.example/api/ga-personal/device/${action}`, {
      method: "OPTIONS", headers: { Origin: origin, "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": requestedHeaders },
    }), context(action))
    assert.equal(response.status, status)
  }
})

test("additional Kujtesa origins require explicit configuration", async () => {
  const configuredOrigin = "https://kujtesa.example"
  const api = proxy(async () => Response.json({ tasks: [] }), { GA_PERSONAL_DEVICE_CORS_ORIGINS: configuredOrigin })
  const response = await api.GET(new Request("https://primeflow.example/api/ga-personal/device/state", {
    headers: { ...headers, Origin: configuredOrigin },
  }), context("state"))
  assertCors(response, configuredOrigin)
})

test("browser can read local validation, upstream authentication and network errors", async () => {
  const request = (extra = {}) => new Request("https://primeflow.example/api/ga-personal/device/state", {
    headers: { Origin: origin, ...extra },
  })
  const api = proxy(async () => { throw new Error("offline") })
  const missing = await api.GET(request(), context("state"))
  assert.equal(missing.status, 401)
  assertCors(missing)
  const offline = await api.GET(request(headers), context("state"))
  assert.equal(offline.status, 503)
  assertCors(offline)
  const gateway = proxy(async () => new Response("gateway down", { status: 502 }))
  const invalid = await gateway.GET(request(headers), context("state"))
  assert.equal(invalid.status, 502)
  assertCors(invalid)
})

test("ops success and local validation failures include CORS", async () => {
  let calls = 0
  const api = proxy(async () => { calls++; return Response.json({ accepted: [] }) })
  for (const [extra, body, status] of [
    [{ "Content-Type": "application/json" }, "{}", 200],
    [{ "Content-Type": "text/plain" }, "{}", 415],
    [{ "Content-Type": "application/json", "Content-Length": String(2 * 1024 * 1024 + 1) }, "{}", 413],
    [{ "Content-Type": "application/json" }, undefined, 400],
  ]) {
    const response = await api.POST(new Request("https://primeflow.example/api/ga-personal/device/ops", {
      method: "POST", headers: { ...headers, Origin: origin, ...extra }, body,
    }), context("ops"))
    assert.equal(response.status, status)
    assertCors(response)
  }
  assert.equal(calls, 1)
})

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
  const request = new Request(`https://primeflow.example/api/ga-personal/device/state?since=${encodeURIComponent(since)}&upstream=https://evil.example`, { headers: { ...headers, Origin: origin, cookie: "work-session=private" } })
  const response = await api.GET(request, context("state"))
  assert.equal(response.status, 200)
  assertCors(response)
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
    method: "POST", headers: { ...headers, Origin: origin, "Content-Type": "application/json" }, body: payload,
  }), context("ops"))
  assert.equal(response.status, 401)
  assertCors(response)
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
