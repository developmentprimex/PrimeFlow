export function recordingTaskTitle(text: string): string {
  const [first, ...details] = text.replace(/\r\n/g, "\n").split("\n")
  return [first.toLocaleUpperCase("sq-AL"), ...details].join("\n")
}

/** Preserve spoken text while separating sentences and evidenced task changes. */
export function transcriptParagraphs(text: string, evidence: string[]): string[] {
  const boundaries = new Set<number>([0, text.length])
  const lower = text.toLocaleLowerCase("sq-AL")
  for (const quote of evidence) {
    const needle = quote.trim().replace(/[.!?]+$/, "").toLocaleLowerCase("sq-AL")
    if (!needle) continue
    const index = lower.indexOf(needle)
    if (index > 0) boundaries.add(index)
  }
  for (const match of text.matchAll(/(?:[.!?]+\s+|\n+)/g)) boundaries.add(match.index! + match[0].length)
  const points = [...boundaries].sort((a, b) => a - b)
  return points.slice(0, -1).map((point, i) => text.slice(point, points[i + 1]).trim()).filter(Boolean)
}
