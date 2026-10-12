import Link from "next/link"
import { ExternalLink } from "lucide-react"

const PROMPT_LINK_RE = /\/knowledge\/(prompts|definime|rregullore)\?prompt=([0-9a-f-]{36})/i

/** Prompt tasks (PROMPT: … / PROMPT: TESTO: …) carry only a link to the full prompt in their description. */
export function promptHrefFromText(text?: string | null): string | null {
  const match = (text || "").match(PROMPT_LINK_RE)
  return match ? `/knowledge/${match[1].toLowerCase()}?prompt=${match[2]}` : null
}

export function PromptLinkButton({ text, compact = false }: { text?: string | null; compact?: boolean }) {
  const href = promptHrefFromText(text)
  if (!href) return null
  return (
    <Link
      href={href}
      className={
        compact
          ? "inline-flex max-w-full items-center gap-1 rounded border border-violet-300 bg-violet-50 px-1.5 py-0.5 text-[11px] font-medium text-violet-800 hover:bg-violet-100"
          : "inline-flex items-center gap-1.5 rounded-md border border-violet-300 bg-violet-50 px-2.5 py-1 text-sm font-medium text-violet-800 hover:bg-violet-100"
      }
    >
      <ExternalLink className={compact ? "h-3 w-3 shrink-0" : "h-3.5 w-3.5"} />
      {href.startsWith("/knowledge/definime") ? "Shiko definimin e plotë" : href.startsWith("/knowledge/rregullore") ? "Shiko rregulloren e plotë" : "Shiko promptin e plotë"}
    </Link>
  )
}
