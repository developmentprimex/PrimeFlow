"use client"

import * as React from "react"
import {
  CheckCircle2,
  Download,
  FileText,
  FolderOpen,
  ImageIcon,
  Loader2,
  Upload,
} from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useAuth } from "@/lib/auth"

type ComplianceCheck = {
  id: string
  label: string
  compliant: boolean
}

type Analysis = {
  filename: string
  suggested_description: string
  paragraphs: number
  tables: number
  sections: number
  checks: ComplianceCheck[]
  is_compliant: boolean
}

type Correction = {
  category: string
  detail: string
}

type GenerationReport = {
  filename: string
  generated_at: string
  summary: string
  corrections: Correction[]
  checks: ComplianceCheck[]
}

const requiredStandards = [
  "Logoja zyrtare PrimEx në anën e majtë të header-it",
  "Data automatike DATE në formatin DD/MM/YYYY në anën e djathtë",
  "Informacioni zyrtar i kompanisë në footer",
  "Numërimi automatik Page {PAGE} of {NUMPAGES}",
  "I njëjti header dhe footer në çdo faqe dhe seksion",
  "Margjina Narrow prej 0.5 inç në të katër anët",
]

function errorDetail(value: unknown, fallback: string) {
  if (value && typeof value === "object" && "detail" in value && typeof value.detail === "string") {
    return value.detail
  }
  return fallback
}

export default function WordStandardsPage() {
  const { apiFetch, user } = useAuth()
  const fileInputRef = React.useRef<HTMLInputElement>(null)
  const [file, setFile] = React.useState<File | null>(null)
  const [isDraggingFile, setIsDraggingFile] = React.useState(false)
  const [analysis, setAnalysis] = React.useState<Analysis | null>(null)
  const [description, setDescription] = React.useState("")
  const [analyzing, setAnalyzing] = React.useState(false)
  const [generating, setGenerating] = React.useState(false)
  const [report, setReport] = React.useState<GenerationReport | null>(null)
  const [downloadUrl, setDownloadUrl] = React.useState<string | null>(null)
  const automaticInitials = React.useMemo(() => {
    const label = user?.full_name || user?.username || user?.email || ""
    return label
      .split(/[^0-9A-Za-zÀ-ž]+/)
      .filter(Boolean)
      .map((part) => part[0]?.toUpperCase())
      .join("")
      .slice(0, 10)
  }, [user])

  React.useEffect(() => {
    return () => {
      if (downloadUrl) URL.revokeObjectURL(downloadUrl)
    }
  }, [downloadUrl])

  const resetResult = React.useCallback(() => {
    setReport(null)
    setDownloadUrl((current) => {
      if (current) URL.revokeObjectURL(current)
      return null
    })
  }, [])

  const chooseFile = (nextFile: File | null) => {
    if (nextFile && !/\.docx$/i.test(nextFile.name)) {
      toast.error("Lejohet vetëm formati Word .docx.")
      return
    }
    if (nextFile && nextFile.size > 20 * 1024 * 1024) {
      toast.error("Dokumenti është më i madh se 20 MB.")
      return
    }
    setFile(nextFile)
    setAnalysis(null)
    setDescription("")
    resetResult()
  }

  const handleFileDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDraggingFile(false)
    chooseFile(event.dataTransfer.files?.[0] || null)
  }

  const analyze = async () => {
    if (!file) {
      toast.error("Zgjidh një dokument .docx.")
      return
    }
    setAnalyzing(true)
    resetResult()
    try {
      const body = new FormData()
      body.append("file", file)
      const response = await apiFetch("/standards/word/analyze", { method: "POST", body })
      if (!response.ok) {
        let payload: unknown = null
        try {
          payload = await response.json()
        } catch {
          payload = null
        }
        toast.error(errorDetail(payload, "Dokumenti Word nuk mund të analizohej."))
        return
      }
      const result = (await response.json()) as Analysis
      setAnalysis(result)
      setDescription(result.suggested_description)
      toast.success("Analiza e dokumentit përfundoi.")
    } finally {
      setAnalyzing(false)
    }
  }

  const generate = async () => {
    if (!file || !analysis) return
    setGenerating(true)
    resetResult()
    try {
      const body = new FormData()
      body.append("file", file)
      body.append("description", description.trim())
      const response = await apiFetch("/standards/word/generate", { method: "POST", body })
      if (!response.ok) {
        let payload: unknown = null
        try {
          payload = await response.json()
        } catch {
          payload = null
        }
        toast.error(errorDetail(payload, "Dokumenti Word nuk mund të gjenerohej."))
        return
      }
      const multipart = await response.formData()
      const reportPart = multipart.get("report")
      const documentPart = multipart.get("document")
      const reportText = typeof reportPart === "string" ? reportPart : await reportPart?.text()
      if (!reportText || !(documentPart instanceof Blob)) {
        throw new Error("PËRGJIGJA e serverit nuk përmban dokumentin Word final.")
      }
      const nextReport = JSON.parse(reportText) as GenerationReport
      const url = URL.createObjectURL(documentPart)
      setReport(nextReport)
      setDownloadUrl(url)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = nextReport.filename
      anchor.click()
      toast.success("Dokumenti Word final u gjenerua dhe u shkarkua.")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Dokumenti Word nuk mund të gjenerohej.")
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <div className="flex items-center gap-2">
          <FileText className="h-5 w-5 text-blue-600" />
          <h1 className="text-xl font-semibold">STANDARDET / Word</h1>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          Ngarko një dokument .docx dhe PrimeFlow do t&apos;i aplikojë automatikisht header-in dhe footer-in zyrtar PrimEx.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-xs text-white">1</span>
            Ngarko dhe analizo dokumentin
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div
            className={`flex flex-col items-center justify-center rounded-lg border border-dashed px-6 py-10 text-center transition-colors ${
              isDraggingFile
                ? "border-blue-500 bg-blue-50"
                : "border-slate-300 bg-slate-50 hover:border-slate-400 hover:bg-slate-100"
            }`}
            onDragEnter={(event) => {
              event.preventDefault()
              setIsDraggingFile(true)
            }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setIsDraggingFile(false)}
            onDrop={handleFileDrop}
          >
            <Upload className="mb-3 h-8 w-8 text-slate-500" />
            <span className="text-sm font-medium">
              {file ? file.name : "Tërhiq dokumentin këtu ose zgjidhe nga pajisja"}
            </span>
            <span className="mt-1 text-xs text-muted-foreground">Formati: .docx · Madhësia maksimale: 20 MB</span>
            <Button type="button" variant="outline" className="mt-4" onClick={() => fileInputRef.current?.click()}>
              <FolderOpen className="h-4 w-4" />
              {file ? "Zgjidh një dokument tjetër" : "Zgjidh dokumentin"}
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              className="sr-only"
              onClick={(event) => {
                event.currentTarget.value = ""
              }}
              onChange={(event) => chooseFile(event.target.files?.[0] || null)}
            />
          </div>
          <div className="flex justify-end">
            <Button type="button" onClick={() => void analyze()} disabled={!file || analyzing || generating}>
              {analyzing ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
              {analyzing ? "Duke analizuar..." : "Analizo dokumentin"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {analysis ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-xs text-white">2</span>
              Gjenero dokumentin sipas standardeve PrimEx
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg border p-3 text-sm"><strong>{analysis.paragraphs}</strong> paragrafë</div>
              <div className="rounded-lg border p-3 text-sm"><strong>{analysis.tables}</strong> tabela</div>
              <div className="rounded-lg border p-3 text-sm"><strong>{analysis.sections}</strong> seksione</div>
            </div>

            <div className="rounded-lg border p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <h2 className="font-medium">Kontrolli i dokumentit aktual</h2>
                <Badge variant={analysis.is_compliant ? "secondary" : "outline"}>
                  {analysis.is_compliant ? "Në përputhje" : "Ka standarde për korrigjim"}
                </Badge>
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                {analysis.checks.map((check) => (
                  <div key={check.id} className="flex items-start gap-2 text-sm">
                    <CheckCircle2 className={`mt-0.5 h-4 w-4 shrink-0 ${check.compliant ? "text-emerald-600" : "text-slate-300"}`} />
                    <span>{check.label}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="word-description">Përshkrimi për emrin final</Label>
                <Input
                  id="word-description"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="P.sh. PROCEDURA_E_PUNES"
                />
                <p className="text-xs text-muted-foreground">Data reale dhe inicialet e përdoruesit shtohen automatikisht.</p>
              </div>
              <div className="space-y-2 rounded-md border bg-slate-50 p-3">
                <Label>Gjenerimi automatik</Label>
                <div className="flex flex-wrap gap-2 text-sm">
                  <Badge variant="secondary">Inicialet: {automaticInitials || "—"}</Badge>
                  <Badge variant="secondary">Data: sot</Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  Inicialet merren nga përdoruesi i kyçur; fusha DATE përditësohet automatikisht në Word.
                </p>
              </div>
            </div>

            <div className="rounded-lg border border-blue-100 bg-blue-50 p-4">
              <div className="mb-3 flex items-center gap-2 font-medium text-blue-950">
                <ImageIcon className="h-4 w-4" />
                Header dhe footer i detyrueshëm
              </div>
              <ul className="grid gap-2 text-sm text-blue-950 md:grid-cols-2">
                {requiredStandards.map((item) => (
                  <li key={item} className="flex gap-2">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-blue-600" />
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="flex justify-end">
              <Button type="button" onClick={() => void generate()} disabled={generating}>
                {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                {generating ? "Duke gjeneruar..." : "Gjenero Word-in final"}
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {report && downloadUrl ? (
        <Card className="border-emerald-200">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base text-emerald-800">
              <CheckCircle2 className="h-5 w-5" />
              Dokumenti Word final u gjenerua
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="flex flex-col gap-3 rounded-lg bg-emerald-50 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="font-medium text-emerald-950">{report.filename}</div>
                <div className="text-sm text-emerald-800">{report.summary}</div>
              </div>
              <Button asChild>
                <a href={downloadUrl} download={report.filename}>
                  <Download className="h-4 w-4" />
                  Shkarko përsëri
                </a>
              </Button>
            </div>
            <div>
              <h2 className="mb-3 text-sm font-semibold">Standardet e aplikuara dhe të verifikuara</h2>
              <div className="space-y-2">
                {report.corrections.map((correction, index) => (
                  <div key={`${correction.category}-${index}`} className="flex gap-2 rounded-md border p-3 text-sm">
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                    <span>{correction.detail}</span>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}
