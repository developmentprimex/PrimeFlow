export const TASK_MARKER_OPTIONS = [
  { value: "EXCLAMATION", label: "!" },
  { value: "DOUBLE_EXCLAM", label: "!!" }, { value: "CLIENT_URGENT", label: "!!!" },
  { value: "QUESTION", label: "?" },
  { value: "SHARE", label: "SHARE" }, { value: "MONITOR", label: "👁" },
  { value: "CLOSE", label: "X" }, { value: "M2", label: "M2" },
  { value: "M3", label: "M3" }, { value: "M2_M3", label: "M2/3" },
  { value: "GENT", label: "GENT" }, { value: "KA", label: "KA" },
  { value: "FLAG", label: "GA" }, { value: "F", label: "F" },
  { value: "BZ1N1", label: "BZ1N1" },
] as const

export type SingleTaskMarker = typeof TASK_MARKER_OPTIONS[number]["value"]
export type TaskMarkerValue = SingleTaskMarker | `${SingleTaskMarker},${SingleTaskMarker}`

export function splitTaskMarkers(value?: string | null): SingleTaskMarker[] {
  return (value || "").split(",").filter((item): item is SingleTaskMarker =>
    TASK_MARKER_OPTIONS.some(option => option.value === item))
}

export function taskMarkerLabel(value?: string | null, byGa = false): string {
  const label = splitTaskMarkers(value).map(marker =>
    TASK_MARKER_OPTIONS.find(option => option.value === marker)!.label).join(" + ")
  return label && byGa ? `(${label})` : label
}

export function toggleTaskMarker(value: string | null | undefined, marker: SingleTaskMarker): TaskMarkerValue | null {
  const current = splitTaskMarkers(value)
  const next = current.includes(marker) ? current.filter(item => item !== marker)
    : current.length < 2 ? [...current, marker] : current
  return next.join(",") as TaskMarkerValue || null
}

// The report preview lives in an iframe outside React's component tree.
export function openTaskMarkerPicker(document: Document, value: string): Promise<string | null> {
  return new Promise(resolve => {
    const dialog = document.createElement("dialog")
    dialog.style.cssText = "border:1px solid #93c5fd;border-radius:12px;padding:20px;width:300px;color:#0f2a5f;background:white;box-shadow:0 12px 40px #0004"
    const title = document.createElement("h3")
    title.textContent = "Simbolet (maksimumi 2)"
    dialog.append(title)
    const grid = document.createElement("div")
    grid.style.cssText = "display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px"
    dialog.append(grid)
    let draft = value
    const inputs: HTMLInputElement[] = []
    const refresh = () => {
      const chosen = splitTaskMarkers(draft)
      inputs.forEach(input => { input.checked = chosen.includes(input.value as SingleTaskMarker); input.disabled = chosen.length >= 2 && !input.checked })
    }
    TASK_MARKER_OPTIONS.forEach(option => {
      const label = document.createElement("label")
      label.style.cssText = "display:inline-flex;gap:6px;padding:8px;font-weight:900;color:#dc2626;min-width:70px"
      const input = document.createElement("input")
      input.type = "checkbox"; input.value = option.value
      input.addEventListener("change", () => { draft = toggleTaskMarker(draft, option.value) || ""; refresh() })
      inputs.push(input); label.append(input, document.createTextNode(option.label)); grid.append(label)
    })
    const finish = (result: string | null) => { dialog.close(); dialog.remove(); resolve(result) }
    const actions = document.createElement("div")
    actions.style.cssText = "display:flex;gap:8px;margin-top:12px"
    for (const [text, action] of [["Anulo", () => finish(null)], ["Ruaj", () => finish(draft)]] as const) {
      const button = document.createElement("button")
      button.type = "button"; button.textContent = text; button.addEventListener("click", action)
      button.style.cssText = "padding:6px 14px;border:1px solid #93c5fd;border-radius:6px;background:#eff6ff;color:#0f2a5f;cursor:pointer"
      actions.append(button)
    }
    dialog.addEventListener("cancel", event => { event.preventDefault(); finish(null) })
    dialog.setAttribute("aria-label", "Simbolet (maksimumi 2)")
    dialog.append(actions); document.body.append(dialog); refresh(); dialog.showModal()
  })
}
