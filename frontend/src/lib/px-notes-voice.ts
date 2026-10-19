export type NoteRange = { start: number; end: number }
export type NoteVoiceDraft = { text: string; doneRanges: NoteRange[]; addedRanges: NoteRange[]; cursor: NoteRange }
export type VisibleVoiceNote = { id: string; source: "GA_KA" | "PX_JAV"; content: string; closed?: boolean }
export type NotesVoiceState = { target: string; draft: NoteVoiceDraft; notes: VisibleVoiceNote[]; dirty: boolean; busy: boolean }
export type NoteVoiceOperation = {
  action: "insert_text" | "new_line" | "add_point" | "replace_point" | "move_point" | "number_points"
  text: string | null; number: number | null; position: number | null
}
export type NotesVoiceAdapter = {
  read: () => NotesVoiceState
  write: (draft: NoteVoiceDraft) => Promise<void>
  select: (note: VisibleVoiceNote) => Promise<void>
  newNote: () => Promise<void>
  save: () => Promise<{ id: string } | null>
}

type Piece = { start: number; end: number } | { text: string; added?: boolean }
type Point = { start: number; end: number; prefixEnd: number; numeric: boolean }
const footerPattern = /^(?:DL|AM\/PM|LL|SIMBOLI):/im

function pointsIn(text: string): Point[] {
  const limit = text.search(footerPattern)
  const end = limit < 0 ? text.length : limit
  const matches = [...text.slice(0, end).matchAll(/^[ \t]*(?:(\d+)[.)]|[-*•])[ \t]+/gm)]
  return matches.map((match, i) => ({ start: match.index!, prefixEnd: match.index! + match[0].length,
    end: matches[i + 1]?.index ?? end, numeric: !!match[1] }))
}

// Copy source spans rather than replacing the whole text, so completed/added
// ranges travel with their exact point even when two points have identical text.
function assemble(draft: NoteVoiceDraft, pieces: Piece[]): NoteVoiceDraft {
  let text = ""
  const doneRanges: NoteRange[] = [], addedRanges: NoteRange[] = []
  let cursorStart: number | undefined, cursorEnd: number | undefined
  for (const piece of pieces) {
    const offset = text.length
    if ("text" in piece) {
      text += piece.text
      if (piece.added && piece.text.length) addedRanges.push({ start: offset, end: text.length })
    } else {
      text += draft.text.slice(piece.start, piece.end)
      if (draft.cursor.start >= piece.start && draft.cursor.start <= piece.end) cursorStart = offset + draft.cursor.start - piece.start
      if (draft.cursor.end >= piece.start && draft.cursor.end <= piece.end) cursorEnd = offset + draft.cursor.end - piece.start
      for (const [ranges, result] of [[draft.doneRanges, doneRanges], [draft.addedRanges, addedRanges]]) {
        for (const range of ranges) {
          const start = Math.max(piece.start, range.start), end = Math.min(piece.end, range.end)
          if (start < end) result.push({ start: offset + start - piece.start, end: offset + end - piece.start })
        }
      }
    }
  }
  if (text.length > 50000) throw new Error("Note-i është shumë i gjatë.")
  return { text, doneRanges, addedRanges, cursor: { start: cursorStart ?? text.length, end: cursorEnd ?? cursorStart ?? text.length } }
}

function insert(draft: NoteVoiceDraft, start: number, end: number, text: string) {
  const result = assemble(draft, [{ start: 0, end: start }, { text, added: true }, { start: end, end: draft.text.length }])
  result.cursor = { start: start + text.length, end: start + text.length }
  return result
}

function rebuildPoints(draft: NoteVoiceDraft, points: Point[], order: (Point | string)[], numbered = false) {
  const pieces: Piece[] = [{ start: 0, end: points[0].start }]
  order.forEach((point, i) => {
    if (typeof point === "string") pieces.push({ text: points[0].numeric || numbered ? `${i + 1}. ` : draft.text.slice(points[0].start, points[0].prefixEnd) }, { text: point, added: true })
    else {
      let end = point.end
      if (draft.text[end - 1] === "\n") end--
      if (point.numeric || numbered) pieces.push({ text: `${i + 1}. ` }, { start: point.prefixEnd, end })
      else pieces.push({ start: point.start, end })
    }
    if (i < order.length - 1 || points[points.length - 1].end < draft.text.length) pieces.push({ text: "\n" })
  })
  pieces.push({ start: points[points.length - 1].end, end: draft.text.length })
  return assemble(draft, pieces)
}

export function editNoteDraft(original: NoteVoiceDraft, operations: NoteVoiceOperation[]): NoteVoiceDraft {
  if (!Array.isArray(operations) || !operations.length || operations.length > 20) throw new Error("Komanda nuk është e vlefshme.")
  let draft = original
  for (const operation of operations) {
    if (!operation || Object.keys(operation).some(key => !["action", "text", "number", "position"].includes(key))) throw new Error("Komanda nuk është e vlefshme.")
    const { action, text, number, position } = operation
    if (text !== null && (typeof text !== "string" || text.length > 10000)) throw new Error("Teksti nuk është i vlefshëm.")
    const points = pointsIn(draft.text)
    const index = (value: number | null, max: number) => {
      if (!Number.isInteger(value) || value! < 1 || value! > max) throw new Error("Numri i pikës nuk ekziston.")
      return value! - 1
    }
    if (action === "insert_text" || action === "new_line") {
      if (action === "insert_text" && !text) throw new Error("Mungon teksti.")
      const start = Math.max(0, Math.min(draft.cursor.start, draft.text.length))
      const end = Math.max(start, Math.min(draft.cursor.end, draft.text.length))
      const before = draft.text.slice(0, start), after = draft.text.slice(end)
      const content = action === "new_line" ? "\n" : `${before && !/\s$/.test(before) && !/^[\s,.;:!?]/.test(text!) ? " " : ""}${text}${after && !/^\s|^[,.;:!?]/.test(after) ? " " : ""}`
      draft = insert(draft, start, end, content)
    } else if (action === "add_point") {
      if (!text?.trim()) throw new Error("Mungon teksti i pikës.")
      const at = position === null ? points.length : index(position, points.length + 1)
      if (points.length) {
        const order: (Point | string)[] = [...points]
        order.splice(at, 0, text)
        draft = rebuildPoints(draft, points, order)
        const added = pointsIn(draft.text)[at]
        const cursor = added.end - (draft.text[added.end - 1] === "\n" ? 1 : 0)
        draft.cursor = { start: cursor, end: cursor }
      } else {
        const footer = draft.text.search(footerPattern)
        const at = footer < 0 ? draft.text.length : footer
        const prefix = at > 0 && draft.text[at - 1] !== "\n" ? "\n" : ""
        draft = insert(draft, at, at, `${prefix}1. ${text}${footer < 0 ? "" : "\n"}`)
        if (footer >= 0) draft.cursor = { start: draft.cursor.start - 1, end: draft.cursor.end - 1 }
      }
    } else if (action === "replace_point") {
      const point = points[index(number, points.length)]
      if (!text?.trim()) throw new Error("Mungon teksti i pikës.")
      const end = draft.text[point.end - 1] === "\n" ? point.end - 1 : point.end
      draft = insert(draft, point.prefixEnd, end, text)
    } else if (action === "move_point") {
      const from = index(number, points.length), to = index(position, points.length)
      const order = [...points]
      order.splice(to, 0, order.splice(from, 1)[0])
      draft = rebuildPoints(draft, points, order)
      const moved = pointsIn(draft.text)[to]
      const cursor = moved.end - (draft.text[moved.end - 1] === "\n" ? 1 : 0)
      draft.cursor = { start: cursor, end: cursor }
    } else if (action === "number_points") {
      if (points.length) draft = rebuildPoints(draft, points, points, true)
      else {
        const footer = draft.text.search(footerPattern)
        const end = footer < 0 ? draft.text.length : footer
        const pieces: Piece[] = []
        let start = 0, number = 0
        for (const line of draft.text.slice(0, end).split(/(?<=\n)/)) {
          if (line.trim()) pieces.push({ text: `${++number}. ` })
          pieces.push({ start, end: start + line.length })
          start += line.length
        }
        pieces.push({ start: end, end: draft.text.length })
        draft = assemble(draft, pieces)
      }
    } else throw new Error("Komanda nuk mbështetet.")
  }
  return draft
}

export function createNotesVoiceController(adapter: NotesVoiceAdapter) {
  let version = 0
  let readVersion: string | null = null, signature: string | null = null
  let running = false
  const fingerprint = (state: NotesVoiceState) => JSON.stringify(state)
  const context = (offset = 0) => {
    const state = adapter.read()
    signature = fingerprint(state)
    readVersion = `v${++version}`
    return { success: true, version: readVersion, target: state.target, text: state.draft.text,
      cursor: state.draft.cursor, dirty: state.dirty,
      points: pointsIn(state.draft.text).map((point, i) => ({ number: i + 1, text: state.draft.text.slice(point.prefixEnd, point.end).trim() })),
      notes: state.notes.slice(offset, offset + 50).map((note, i) => ({ number: offset + i + 1, source: note.source, preview: note.content.replace(/\[\[.*?\]\]/g, "").slice(0, 160), closed: !!note.closed })),
      next_offset: state.notes.length > offset + 50 ? offset + 50 : null }
  }
  return async (name: string, raw: Record<string, unknown>): Promise<Record<string, unknown>> => {
    let acquired = false
    try {
      if (running || adapter.read().busy) throw new Error("Prit sa të përfundojë ruajtja.")
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("Komandë e pavlefshme.")
      const fields: Record<string, string[]> = { notes_get_context: ["offset"], notes_edit: ["expected_version", "operations", "save_after"],
        notes_select: ["expected_version", "note_number"], notes_new: ["expected_version"], notes_save: ["expected_version"] }
      if (!fields[name] || Object.keys(raw).some(key => !fields[name].includes(key))) throw new Error("Komandë e pavlefshme.")
      if (name === "notes_edit" && raw.save_after !== undefined && typeof raw.save_after !== "boolean") throw new Error("Komandë e pavlefshme.")
      if (name === "notes_get_context") {
        const offset = raw.offset ?? 0
        if (typeof offset !== "number" || !Number.isInteger(offset) || offset < 0) throw new Error("Renditje e pavlefshme.")
        return context(offset)
      }
      const state = adapter.read()
      if (!readVersion || raw.expected_version !== readVersion || fingerprint(state) !== signature) throw new Error("Note-i ndryshoi. Lexo kontekstin përsëri para ndryshimit.")
      readVersion = null // A completed or uncertain write is never replayed.
      running = true
      acquired = true
      if (name === "notes_edit") {
        const next = editNoteDraft(state.draft, raw.operations as NoteVoiceOperation[])
        await adapter.write(next)
        if (raw.save_after === true) {
          const saved = await adapter.save()
          if (!saved) throw new Error("Nuk u ruajt. Drafti mbetet në editor.")
          return { success: true, saved: true, changed: true, note_id: saved.id, silent: false }
        }
        return { ...context(), silent: true, saved: false }
      }
      if (name === "notes_save") {
        if (!state.draft.text.trim()) throw new Error("Note-i është bosh.")
        const result = await adapter.save()
        if (!result) throw new Error("Note-i nuk u ruajt. Drafti mbetet në editor; kontrollo mesazhin e gabimit.")
        return { success: true, saved: true, changed: true, note_id: result.id, silent: false }
      }
      if (state.dirty) throw new Error("Ruaje Note-in aktual para se të kalosh te një tjetër.")
      if (name === "notes_select") {
        const number = raw.note_number
        if (typeof number !== "number" || !Number.isInteger(number) || number < 1 || number > state.notes.length) throw new Error("Ky numër Note-i nuk shfaqet në listë.")
        const note = state.notes[number - 1]
        if (note.closed) throw new Error("Ky Note është i mbyllur.")
        await adapter.select(note)
      } else await adapter.newNote()
      return { ...context(), silent: false }
    } catch (error) {
      return { success: false, silent: false, error: error instanceof Error ? error.message : "Veprimi nuk u krye." }
    } finally { if (acquired) running = false }
  }
}

// A save response acknowledges its submitted snapshot. It must not replace
// text or progress the user changed while that request was in flight.
export function reconcileSavedNoteDraft(submitted: NoteVoiceDraft, current: NoteVoiceDraft, saved: NoteVoiceDraft): NoteVoiceDraft {
  const content = (draft: NoteVoiceDraft) => JSON.stringify([draft.text, draft.doneRanges, draft.addedRanges])
  return content(submitted) === content(current) ? saved : current
}
