import * as React from "react"

function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*|\[\d{2}:\d{2}:\d{2}\])/g).map((part, index) =>
    part.startsWith("**") ? <strong key={index} className="font-semibold text-foreground">{part.slice(2, -2)}</strong>
      : /^\[\d{2}:\d{2}:\d{2}\]$/.test(part) ? <span key={index} className="whitespace-nowrap text-xs text-muted-foreground">{part}</span>
        : part
  )
}

export function RecordingSummaryContent({ text }: { text: string }) {
  const blocks: React.ReactNode[] = []
  const lines = text.replace(/\r\n/g, "\n").split("\n")
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index].trim()
    if (!line) continue
    const heading = line.match(/^(?:#{1,6}\s+(.+)|\*\*([^*]+)\*\*\s*)$/)
    if (heading) {
      blocks.push(<h4 key={index} className="pt-2 font-semibold text-foreground">{inline(heading[1] || heading[2])}</h4>)
    } else if (/^[-*•]\s+/.test(line)) {
      const start = index
      const items: string[] = []
      while (index < lines.length && /^[-*•]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^[-*•]\s+/, ""))
        index++
      }
      index--
      blocks.push(<ul key={start} className="list-disc space-y-2 pl-5 marker:text-muted-foreground">{items.map((item, itemIndex) => <li key={itemIndex}>{inline(item)}</li>)}</ul>)
    } else {
      blocks.push(<p key={index}>{inline(line)}</p>)
    }
  }
  return <div className="space-y-3 text-sm leading-7 text-foreground/85">{blocks}</div>
}
