"use client"

import * as React from "react"
import { AlertCircle, CheckCircle2, Download, FileSpreadsheet, FolderOpen, Loader2, Upload } from "lucide-react"
import { toast } from "sonner"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useAuth } from "@/lib/auth"

type MissingHeader = {
  column: string
  column_index: number
}

type SheetAnalysis = {
  name: string
  source_header_row: number
  headers: string[]
  missing_headers: MissingHeader[]
  suggested_title: string
}

type Analysis = {
  filename: string
  suggested_description: string
  sheets: SheetAnalysis[]
  empty_sheets: string[]
  has_missing_headers: boolean
}

type Correction = {
  category: string
  detail: string
  count?: number
}

type GenerationReport = {
  filename: string
  generated_at: string
  summary: string
  sheets: Array<{
    name: string
    source_name: string | null
    corrections: Correction[]
  }>
}

function errorDetail(value: unknown, fallback: string) {
  if (value && typeof value === "object" && "detail" in value && typeof value.detail === "string") {
    return value.detail
  }
  return fallback
}

export default function ExcelStandardsPage() {
  const { apiFetch, user } = useAuth()
  const fileInputRef = React.useRef<HTMLInputElement>(null)
  const [file, setFile] = React.useState<File | null>(null)
  const [isDraggingFile, setIsDraggingFile] = React.useState(false)
  const [analysis, setAnalysis] = React.useState<Analysis | null>(null)
  const [missingHeaders, setMissingHeaders] = React.useState<Record<string, Record<string, string>>>({})
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
    if (nextFile && !/\.(xlsx|csv)$/i.test(nextFile.name)) {
      toast.error("Lejohen vetëm skedarët .xlsx dhe .csv.")
      return
    }
    if (nextFile && nextFile.size > 20 * 1024 * 1024) {
      toast.error("Skedari është më i madh se 20 MB.")
      return
    }
    setFile(nextFile)
    setAnalysis(null)
    setMissingHeaders({})
    setDescription("")
    resetResult()
  }

  const openFilePicker = () => fileInputRef.current?.click()

  const handleFileDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDraggingFile(false)
    chooseFile(event.dataTransfer.files?.[0] || null)
  }

  const analyze = async () => {
    if (!file) {
      toast.error("Zgjidh një skedar .xlsx ose .csv.")
      return
    }
    setAnalyzing(true)
    resetResult()
    try {
      const body = new FormData()
      body.append("file", file)
      const response = await apiFetch("/standards/excel/analyze", { method: "POST", body })
      if (!response.ok) {
        let payload: unknown = null
        try {
          payload = await response.json()
        } catch {
          payload = null
        }
        toast.error(errorDetail(payload, "Skedari nuk mund të analizohej."))
        return
      }
      const result = (await response.json()) as Analysis
      setAnalysis(result)
      setDescription(result.suggested_description)
      const missing: Record<string, Record<string, string>> = {}
      for (const sheet of result.sheets) {
        missing[sheet.name] = Object.fromEntries(sheet.missing_headers.map((item) => [item.column, ""]))
      }
      setMissingHeaders(missing)
      toast.success("Analiza përfundoi.")
    } finally {
      setAnalyzing(false)
    }
  }

  const allMissingHeadersFilled = Boolean(
    analysis &&
      analysis.sheets.every((sheet) =>
        sheet.missing_headers.every((item) => missingHeaders[sheet.name]?.[item.column]?.trim())
      )
  )

  const generate = async () => {
    if (!file || !analysis) return
    if (!allMissingHeadersFilled) {
      toast.error("Plotëso tekstin për çdo header bosh.")
      return
    }
    setGenerating(true)
    resetResult()
    try {
      const body = new FormData()
      body.append("file", file)
      body.append("description", description.trim())
      body.append("missing_headers_json", JSON.stringify(missingHeaders))
      const response = await apiFetch("/standards/excel/generate", { method: "POST", body })
      if (!response.ok) {
        let payload: unknown = null
        try {
          payload = await response.json()
        } catch {
          payload = null
        }
        toast.error(errorDetail(payload, "Excel-i nuk mund të gjenerohej."))
        return
      }
      const multipart = await response.formData()
      const reportPart = multipart.get("report")
      const workbookPart = multipart.get("workbook")
      const reportText = typeof reportPart === "string" ? reportPart : await reportPart?.text()
      if (!reportText || !(workbookPart instanceof Blob)) {
        throw new Error("PËRGJIGJA e serverit nuk përmban Excel-in final.")
      }
      const nextReport = JSON.parse(reportText) as GenerationReport
      const url = URL.createObjectURL(workbookPart)
      setReport(nextReport)
      setDownloadUrl(url)
      const anchor = document.createElement("a")
      anchor.href = url
      anchor.download = nextReport.filename
      anchor.click()
      toast.success("Excel-i final u gjenerua dhe u shkarkua.")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Excel-i nuk mund të gjenerohej.")
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <div className="flex items-center gap-2">
          <FileSpreadsheet className="h-5 w-5 text-emerald-600" />
          <h1 className="text-xl font-semibold">STANDARDET / Excel</h1>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          Ngarko një Excel ose CSV dhe PrimeFlow do ta kthejë në një skedar .xlsx sipas standardeve Primex.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-xs text-white">1</span>
            Ngarko dhe analizo skedarin
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div
            className={`flex flex-col items-center justify-center rounded-lg border border-dashed px-6 py-10 text-center transition-colors ${
              isDraggingFile
                ? "border-emerald-500 bg-emerald-50"
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
              {file ? file.name : "Tërhiq skedarin këtu ose zgjidhe nga pajisja"}
            </span>
            <span className="mt-1 text-xs text-muted-foreground">Formatet: .xlsx, .csv · Madhësia maksimale: 20 MB</span>
            <Button type="button" variant="outline" className="mt-4" onClick={openFilePicker}>
              <FolderOpen className="h-4 w-4" />
              {file ? "Zgjidh një skedar tjetër" : "Zgjidh skedarin"}
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
              className="sr-only"
              onClick={(event) => {
                event.currentTarget.value = ""
              }}
              onChange={(event) => chooseFile(event.target.files?.[0] || null)}
            />
          </div>
          <div className="flex justify-end">
            <Button type="button" onClick={() => void analyze()} disabled={!file || analyzing || generating}>
              {analyzing ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileSpreadsheet className="h-4 w-4" />}
              {analyzing ? "Duke analizuar..." : "Analizo skedarin"}
            </Button>
          </div>
        </CardContent>
      </Card>

      {analysis ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-xs text-white">2</span>
              Plotëso të dhënat e skedarit aktual
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid gap-3 md:grid-cols-2">
              {analysis.sheets.map((sheet) => (
                <div key={sheet.name} className="rounded-lg border p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-medium">{sheet.name}</div>
                    <Badge variant="outline">Header: rreshti {sheet.source_header_row}</Badge>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">Titulli: {sheet.suggested_title}</p>
                  {sheet.missing_headers.length ? (
                    <div className="mt-4 space-y-3">
                      <div className="flex items-center gap-2 text-sm text-amber-700">
                        <AlertCircle className="h-4 w-4" />
                        Header-at e mëposhtëm janë bosh.
                      </div>
                      {sheet.missing_headers.map((item) => (
                        <div key={item.column} className="space-y-1.5">
                          <Label htmlFor={`${sheet.name}-${item.column}`}>Teksti për kolonën {item.column}</Label>
                          <Input
                            id={`${sheet.name}-${item.column}`}
                            value={missingHeaders[sheet.name]?.[item.column] || ""}
                            onChange={(event) =>
                              setMissingHeaders((current) => ({
                                ...current,
                                [sheet.name]: {
                                  ...current[sheet.name],
                                  [item.column]: event.target.value,
                                },
                              }))
                            }
                          />
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-4 flex items-center gap-2 text-sm text-emerald-700">
                      <CheckCircle2 className="h-4 w-4" />
                      Header-i nuk ka qeliza bosh.
                    </div>
                  )}
                </div>
              ))}
            </div>

            {analysis.empty_sheets.length ? (
              <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                Sheet-et bosh do të hiqen: {analysis.empty_sheets.join(", ")}.
              </div>
            ) : null}

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="excel-description">Përshkrimi për emrin final</Label>
                <Input
                  id="excel-description"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="P.sh. STOCK_MI_GL"
                />
                <p className="text-xs text-muted-foreground">Data reale e gjenerimit dhe inicialet shtohen automatikisht.</p>
              </div>
              <div className="space-y-2 rounded-md border bg-slate-50 p-3">
                <Label>Gjenerimi automatik</Label>
                <div className="flex flex-wrap gap-2 text-sm">
                  <Badge variant="secondary">Inicialet: {automaticInitials || "—"}</Badge>
                  <Badge variant="secondary">Data: sot</Badge>
                </div>
                <p className="text-xs text-muted-foreground">
                  Inicialet merren nga përdoruesi i kyçur në PrimeFlow; data dhe ora merren në momentin e gjenerimit.
                </p>
              </div>
            </div>

            <div className="flex justify-end">
              <Button type="button" onClick={() => void generate()} disabled={!allMissingHeadersFilled || generating}>
                {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                {generating ? "Duke gjeneruar..." : "Gjenero Excel-in final"}
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
              Excel-i final u gjenerua
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
              <h2 className="mb-3 text-sm font-semibold">Gabimet e gjetura dhe të korrigjuara</h2>
              <div className="space-y-4">
                {report.sheets.map((sheet, index) => (
                  <div key={`${sheet.name}-${index}`} className="rounded-lg border p-4">
                    <div className="mb-2 font-medium">{sheet.name}</div>
                    <ul className="space-y-2 text-sm text-slate-700">
                      {sheet.corrections.map((correction, correctionIndex) => (
                        <li key={`${correction.category}-${correctionIndex}`} className="flex gap-2">
                          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                          <span>{correction.detail}</span>
                        </li>
                      ))}
                    </ul>
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
