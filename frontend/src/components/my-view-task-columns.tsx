const columns = {
  waiting: [3, 7, 7, 9, 5, 32, 6, 7, 8, 6, 6, 4],
  project: [3, 7, 6, 5, 35, 7, 8, 8, 7, 7, 7],
  fast: [3, 7, 5, 35, 8, 9, 9, 8, 8, 8],
  system: [3, 5, 35, 8, 9, 7, 9, 8, 8, 8],
}

/** Content-independent widths keep expansion from resizing every column. */
export function MyViewTaskColumns({ kind }: { kind: keyof typeof columns }) {
  return <colgroup>{columns[kind].map((width, index) => <col key={index} style={{ width: `${width}%` }} />)}</colgroup>
}
