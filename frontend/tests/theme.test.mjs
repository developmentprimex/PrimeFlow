import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import vm from "node:vm"
import test from "node:test"
import ts from "typescript"

function setup(saved, dark = false, blocked = false) {
  const source = readFileSync(new URL("../src/lib/theme.ts", import.meta.url), "utf8")
  const module = { exports: {} }
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { exports: module.exports })
  const events = new EventTarget()
  const media = new EventTarget()
  media.matches = dark
  const root = { dataset: {}, classList: { toggle(_, value) { root.dark = value } } }
  const storage = { value: saved, getItem() { if (blocked) throw Error(); return this.value }, setItem(_, value) { if (blocked) throw Error(); this.value = value } }
  vm.runInNewContext(module.exports.THEME_SCRIPT, {
    document: { documentElement: root }, localStorage: storage,
    window: { matchMedia: () => media, addEventListener: events.addEventListener.bind(events), dispatchEvent: events.dispatchEvent.bind(events) },
    Event,
  })
  return { root, storage, media, set(value) { const event = new Event("primex:set-theme"); event.detail = value; events.dispatchEvent(event) }, sync(value) { storage.value = value; const event = new Event("storage"); event.key = "primex-theme"; events.dispatchEvent(event) } }
}

test("System follows the OS on startup and live changes", () => {
  const app = setup(null, true)
  assert.equal(app.root.dark, true)
  assert.equal(app.root.dataset.theme, "system")
  app.media.matches = false
  app.media.dispatchEvent(new Event("change"))
  assert.equal(app.root.dark, false)
})
test("explicit choices persist and override the OS, then can return to System", () => {
  const app = setup("light", true)
  assert.equal(app.root.dark, false)
  app.set("dark")
  assert.equal(app.storage.value, "dark")
  assert.equal(app.root.dark, true)
  app.set("system")
  assert.equal(app.root.dataset.theme, "system")
  app.media.matches = false
  app.media.dispatchEvent(new Event("change"))
  assert.equal(app.root.dark, false)
})
test("cross-tab changes sync and invalid storage falls back to System", () => {
  const app = setup("invalid", true)
  assert.equal(app.root.dataset.theme, "system")
  app.sync("light")
  assert.equal(app.root.dark, false)
  app.sync(null)
  assert.equal(app.root.dark, true)
})
test("theme remains usable when localStorage is blocked", () => {
  const app = setup(null, false, true)
  app.set("dark")
  assert.equal(app.root.dark, true)
})
