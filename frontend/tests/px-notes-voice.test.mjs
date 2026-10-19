import assert from "node:assert/strict"
import { test } from "node:test"
import { readFileSync } from "node:fs"
import vm from "node:vm"
import ts from "typescript"

function load() {
  const module = { exports: {} }
  const source = readFileSync(new URL("../src/lib/px-notes-voice.ts", import.meta.url), "utf8")
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } })
  vm.runInNewContext(outputText, { module, exports: module.exports })
  return module.exports
}
const draft = (text, doneRanges = [], addedRanges = []) => ({ text, doneRanges, addedRanges, cursor: { start: text.length, end: text.length } })
const operation = (action, text = null, number = null, position = null) => ({ action, text, number, position })

test("dictation, new lines and points edit the draft without writing spoken commands into it", () => {
  const { editNoteDraft } = load()
  const result = editNoteDraft(draft("Raporti"), [operation("new_line"), operation("insert_text", "Kontrollo rezultatet"), operation("add_point", "Dërgo raportin")])
  assert.equal(result.text, "Raporti\nKontrollo rezultatet\n1. Dërgo raportin")
})

test("moving a point renumbers the list while preserving its done mark, duplicate text and footer", () => {
  const { editNoteDraft } = load()
  const original = "Titulli\n1. Një\n2. Një\n3. Tre\nDL:\nAM/PM:"
  const start = original.indexOf("Tre")
  const result = editNoteDraft(draft(original, [{ start, end: start + 3 }]), [operation("move_point", null, 3, 1)])
  assert.equal(result.text, "Titulli\n1. Tre\n2. Një\n3. Një\nDL:\nAM/PM:")
  assert.equal(result.text.slice(result.doneRanges[0].start, result.doneRanges[0].end), "Tre")
})

test("inserting a middle point preserves multiline content and shifts progress marks", () => {
  const { editNoteDraft } = load()
  const original = "Titulli\n1. A\n   Detajet\n2. B"
  const result = editNoteDraft(draft(original, [{ start: original.length - 1, end: original.length }]), [operation("add_point", "E re", null, 2)])
  assert.equal(result.text, "Titulli\n1. A\n   Detajet\n2. E re\n3. B")
  assert.equal(result.text.slice(result.doneRanges[0].start, result.doneRanges[0].end), "B")
})

test("invalid point numbers reject the whole edit batch without changing the original", () => {
  const { editNoteDraft } = load()
  const original = draft("1. A\n2. B")
  assert.throws(() => editNoteDraft(original, [operation("insert_text", "X"), operation("move_point", null, 8, 1)]))
  assert.equal(original.text, "1. A\n2. B")
})

test("continued dictation stays in the added point instead of being appended after the metadata footer", () => {
  const { editNoteDraft } = load()
  const result = editNoteDraft(draft("Titulli\n1. A\nDL:\nLL:"), [operation("add_point", "B"), operation("insert_text", "vazhdim")])
  assert.equal(result.text, "Titulli\n1. A\n2. B vazhdim\nDL:\nLL:")
})

test("adding to a bulleted list preserves the existing bullet style", () => {
  const { editNoteDraft } = load()
  const result = editNoteDraft(draft("Titulli\n• A"), [operation("add_point", "B")])
  assert.equal(result.text, "Titulli\n• A\n• B")
})

function workspace({ failSave = false } = {}) {
  let state = { target: "new", draft: draft(""), dirty: false, busy: false, notes: [
    { id: "b", source: "PX_JAV", content: "Note B" }, { id: "a", source: "GA_KA", content: "Note A" },
  ] }
  let saved = null
  const { createNotesVoiceController } = load()
  const controller = createNotesVoiceController({
    read: () => state,
    write: async next => { state = { ...state, draft: next, dirty: true } },
    select: async note => { state = { ...state, target: `${note.source}:${note.id}`, draft: draft(note.content), dirty: false } },
    newNote: async () => { state = { ...state, target: "new", draft: draft(""), dirty: false } },
    save: async () => { if (failSave) return null; saved = state.draft.text; state = { ...state, dirty: false }; return { id: "saved" } },
  })
  return { controller, read: () => state, change: fn => { state = fn(state) }, saved: () => saved }
}

test("note numbers use the visible filtered row order and never guess another source", async () => {
  const w = workspace()
  const context = await w.controller("notes_get_context", { offset: 0 })
  const result = await w.controller("notes_select", { expected_version: context.version, note_number: 1 })
  assert.equal(result.success, true)
  assert.equal(w.read().target, "PX_JAV:b")
})

test("manual changes and reordered note rows invalidate a previously read voice context", async () => {
  for (const change of [state => ({ ...state, draft: draft("Tastiera") }), state => ({ ...state, notes: [...state.notes].reverse() })]) {
    const w = workspace()
    const context = await w.controller("notes_get_context", { offset: 0 })
    w.change(change)
    const result = await w.controller("notes_edit", { expected_version: context.version, operations: [operation("insert_text", "Zëri")] })
    assert.equal(result.success, false)
    assert.notEqual(w.read().draft.text, "Zëri")
  }
})

test("dictation stays a draft until save and unsaved text cannot be discarded by selecting another note", async () => {
  const w = workspace()
  let context = await w.controller("notes_get_context", { offset: 0 })
  const result = await w.controller("notes_edit", { expected_version: context.version, operations: [operation("insert_text", "Ruaje këtë tekst")] })
  assert.equal(result.silent, true)
  assert.equal(w.saved(), null)
  context = await w.controller("notes_get_context", { offset: 0 })
  assert.equal((await w.controller("notes_select", { expected_version: context.version, note_number: 1 })).success, false)
  assert.equal(w.read().draft.text, "Ruaje këtë tekst")
  context = await w.controller("notes_get_context", { offset: 0 })
  const saved = await w.controller("notes_save", { expected_version: context.version })
  assert.equal(saved.success, true)
  assert.equal(w.saved(), "Ruaje këtë tekst")
  assert.equal((await w.controller("notes_save", { expected_version: context.version })).success, false)
})

test("dictation followed by an explicit save in the same utterance saves the edited content", async () => {
  const w = workspace()
  const context = await w.controller("notes_get_context", { offset: 0 })
  const result = await w.controller("notes_edit", { expected_version: context.version, operations: [operation("insert_text", "Raporti"), operation("add_point", "Kontrollo")], save_after: true })
  assert.equal(result.saved, true)
  assert.equal(result.silent, false)
  assert.equal(w.saved(), "Raporti\n1. Kontrollo")
})

test("a failed save preserves the draft and never reports success", async () => {
  const w = workspace({ failSave: true })
  const context = await w.controller("notes_get_context", { offset: 0 })
  const result = await w.controller("notes_edit", { expected_version: context.version, operations: [operation("insert_text", "Drafti")], save_after: true })
  assert.equal(result.success, false)
  assert.equal(result.silent, false)
  assert.equal(w.read().draft.text, "Drafti")
  assert.equal(w.saved(), null)
})


test("moving a point keeps continued dictation before the footer", () => {
  const { editNoteDraft } = load()
  const result = editNoteDraft(draft("Title\n1. A\n2. B\nDL:\nLL:"), [operation("move_point", null, 2, 1), operation("insert_text", "continued")])
  assert.equal(result.text, "Title\n1. B continued\n2. A\nDL:\nLL:")
})

test("numbering preserves the insertion position within the original point", () => {
  const { editNoteDraft } = load()
  const original = draft("Title\n- A\n- B\nDL:\nLL:")
  original.cursor = { start: 9, end: 9 }
  const result = editNoteDraft(original, [operation("number_points"), operation("insert_text", "continued")])
  assert.equal(result.text, "Title\n1. A continued\n2. B\nDL:\nLL:")
})

test("save reconciliation preserves typing and progress changes made while saving", () => {
  const { reconcileSavedNoteDraft } = load()
  const submitted = draft("1. A")
  const saved = draft("1. A\nDL:")
  assert.equal(reconcileSavedNoteDraft(submitted, submitted, saved), saved)
  const typed = draft("1. A continued")
  assert.equal(reconcileSavedNoteDraft(submitted, typed, saved), typed)
  const marked = draft("1. A", [{ start: 3, end: 4 }])
  assert.equal(reconcileSavedNoteDraft(submitted, marked, saved), marked)
})
