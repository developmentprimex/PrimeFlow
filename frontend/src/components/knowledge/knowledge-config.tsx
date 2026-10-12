"use client"

import * as React from "react"

export type KnowledgeType = "PROMPT" | "DEFINITION" | "REGULATION"

export const KNOWLEDGE_CONFIG = {
  PROMPT: { title: "Prompts", route: "/knowledge/prompts", prefix: "PROMPT", singular: "prompt", plural: "prompte" },
  DEFINITION: { title: "Definime", route: "/knowledge/definime", prefix: "DEFINIM", singular: "definim", plural: "definime" },
  REGULATION: { title: "Rregullore", route: "/knowledge/rregullore", prefix: "RREGULLORE", singular: "rregullore", plural: "rregullore" },
} as const

/** Adapt only interface copy; saved titles, content and people are never translated. */
export function knowledgeText(kind: KnowledgeType, value: string): string {
  if (kind === "PROMPT") return value
  const config = KNOWLEDGE_CONFIG[kind]
  const definition = kind === "DEFINITION"
  const words: Record<string, string> = {
    prompts: config.title, prompt: config.singular, prompte: config.plural,
    prompti: definition ? "definimi" : "rregullorja", promptit: definition ? "definimit" : "rregullores",
    promptin: definition ? "definimin" : "rregulloren", promptet: definition ? "definimet" : "rregulloret",
    promptave: definition ? "definimeve" : "rregulloreve",
    test: "Kontroll", testo: "KONTROLLO", testim: "kontroll", testimi: "kontrolli",
    testimin: "kontrollin", testimit: "kontrollit", testoi: "kontrolloi", testuar: "kontrolluar",
    testohen: "kontrollohen", testohet: "kontrollohet", teston: "kontrollon", testojë: "kontrollojë",
    testova: "kontrollova", testues: "kontrollues", testuesi: "kontrolluesi", testuesin: "kontrolluesin",
    testuesit: "kontrolluesit",
  }
  if (value === "p.sh. Amazon bulletpoints prompt") return definition ? "p.sh. Definimi i një projekti" : "p.sh. Rregullorja e punës"
  if (value.startsWith("Çfarë prompti na duhet?")) return definition ? "Çfarë definimi na duhet? Shkruaj kërkesën…" : "Çfarë rregulloreje na duhet? Shkruaj kërkesën…"
  if (value === "p.sh. E testova me 5 produkte, rezultati OK") return "p.sh. E kontrollova përmbajtjen, është e saktë"
  return value.replace(/\bPrompt Library\b/g, `Libraria · ${config.title}`).replace(/\b(?:prompt[a-z]*|test[a-zë]*)(?![a-zë])/gi, (word) => {
    const replacement = words[word.toLowerCase()]
    if (!replacement) return word
    if (word === word.toUpperCase()) return replacement.toUpperCase()
    if (word[0] === word[0].toUpperCase()) return replacement[0].toUpperCase() + replacement.slice(1)
    return replacement
  })
}

const KnowledgeContext = React.createContext<KnowledgeType>("PROMPT")

export function KnowledgeProvider({ kind, children }: { kind: KnowledgeType; children: React.ReactNode }) {
  return <KnowledgeContext.Provider value={kind}>{children}</KnowledgeContext.Provider>
}

export function useKnowledge() {
  const kind = React.useContext(KnowledgeContext)
  const text = React.useCallback((value: string) => knowledgeText(kind, value), [kind])
  return { kind, ...KNOWLEDGE_CONFIG[kind], text }
}
