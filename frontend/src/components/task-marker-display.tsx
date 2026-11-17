import { splitTaskMarkers, taskMarkerLabel } from "@/lib/task-markers"

/** Keep paired symbols visually distinct without adding a plus sign. */
export function TaskMarkerDisplay({ value, byGa = false }: { value?: string | null; byGa?: boolean }) {
  const markers = splitTaskMarkers(value)
  return <span className="inline-flex items-center gap-1">
    {markers.length ? markers.map((marker, index) => <span key={`${marker}-${index}`} data-task-marker-symbol={marker}
      className={markers.length > 1 ? "inline-flex items-center rounded border border-blue-200 bg-white px-1 leading-tight" : undefined}>
      {taskMarkerLabel(marker, byGa)}
    </span>) : "—"}
  </span>
}
