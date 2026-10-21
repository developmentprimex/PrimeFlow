import assert from "node:assert/strict"
import { test } from "node:test"
import { readFileSync } from "node:fs"
import vm from "node:vm"
import ts from "typescript"

function load() {
  const module = { exports: {} }
  const source = readFileSync(new URL("../src/lib/mira-memory.ts", import.meta.url), "utf8")
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } })
  vm.runInNewContext(outputText, { module, exports: module.exports, Intl })
  return module.exports
}
const event = (kind, extra) => ({ kind, text: "", created_at: "2026-10-21T07:58:00+00:00", meeting_title: null, user_name: null, partial: false, ...extra })

test("a meeting mention is labelled with the meeting and its local time", () => {
  const { eventLabel } = load()
  assert.equal(eventLabel(event("MENTION", { meeting_title: "1H" })), "1H · 21.10, 09:58")
})

test("people's corrections name who made them", () => {
  const { eventLabel } = load()
  assert.equal(eventLabel(event("EDIT", { user_name: "Arta Krasniqi" })), "Korrigjuar nga Arta Krasniqi · 21.10, 09:58")
  assert.equal(eventLabel(event("WRONG", { user_name: "Arta Krasniqi" })), "Shënuar si e gabuar nga Arta Krasniqi · 21.10, 09:58")
  assert.equal(eventLabel(event("CLOSE", { meeting_title: "1H" })), "Mbyllur në takim, 1H · 21.10, 09:58")
})

test("mention counts read naturally in Albanian", () => {
  const { mentionText } = load()
  assert.equal(mentionText(1), "1 takim")
  assert.equal(mentionText(3), "3 takime")
})
