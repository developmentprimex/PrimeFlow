export type RecordingManifest = {
  id: string; userId: string; title: string; count: number; acknowledged: number
  bytes: number; uploadedBytes: number; stopped: boolean; fatal?: string; partial?: boolean
}
const MAX_PENDING_BYTES = 96 * 1024 * 1024
export const PAUSE_PENDING_BYTES = 32 * 1024 * 1024
const MAX_CHUNK_BYTES = 32 * 1024 * 1024

export interface RecordingOutbox {
  create(manifest: RecordingManifest): Promise<void>
  list(userId: string): Promise<RecordingManifest[]>
  get(id: string): Promise<RecordingManifest>
  append(id: string, blob: Blob): Promise<void>
  next(id: string): Promise<Blob | undefined>
  acknowledge(id: string, bytes: number): Promise<void>
  stop(id: string, fatal?: string, partial?: boolean): Promise<void>
  remove(id: string): Promise<void>
}

function request<T>(req: IDBRequest<T>) { return new Promise<T>((resolve, reject) => { req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error) }) }

export class IndexedRecordingOutbox implements RecordingOutbox {
  private database = new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open("primeflow-recordings-v1", 1)
    req.onupgradeneeded = () => { req.result.createObjectStore("sessions", { keyPath: "id" }); req.result.createObjectStore("chunks") }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
    req.onblocked = () => reject(new Error("Mbyllni skedat e tjera të regjistrimit dhe provoni përsëri."))
  })
  private async transaction<T>(mode: IDBTransactionMode, action: (sessions: IDBObjectStore, chunks: IDBObjectStore) => Promise<T>): Promise<T> {
    const db = await this.database
    const tx = db.transaction(["sessions", "chunks"], mode)
    const done = new Promise<void>((resolve, reject) => { tx.oncomplete = () => resolve(); tx.onerror = tx.onabort = () => reject(tx.error || new Error("Ruajtja lokale dështoi.")) })
    try {
      const result = await action(tx.objectStore("sessions"), tx.objectStore("chunks"))
      await done
      return result
    } catch (error) {
      try { tx.abort() } catch {}
      await done.catch(() => {})
      throw error
    }
  }
  create(manifest: RecordingManifest) { return this.transaction("readwrite", async s => { await request(s.add(manifest)) }) }
  list(userId: string) { return this.transaction("readonly", async s => (await request<RecordingManifest[]>(s.getAll())).filter(m => m.userId === userId)) }
  get(id: string) { return this.transaction("readonly", async s => { const value = await request<RecordingManifest | undefined>(s.get(id)); if (!value) throw new Error("Mungon sesioni lokal."); return value }) }
  append(id: string, blob: Blob) {
    return this.transaction("readwrite", async (s, c) => {
      const m = await request<RecordingManifest>(s.get(id))
      if (!m || m.stopped || m.fatal) throw new Error("Sesioni lokal është mbyllur.")
      if (blob.size > MAX_CHUNK_BYTES || m.bytes - m.uploadedBytes + blob.size > MAX_PENDING_BYTES) throw new Error("U tejkalua kufiri i radhës lokale; regjistrimi nuk është ruajtur plotësisht.")
      await request(c.add(blob, `${id}:${m.count}`))
      m.count++; m.bytes += blob.size
      await request(s.put(m))
    })
  }
  next(id: string) { return this.transaction("readonly", async (s, c) => { const m = await request<RecordingManifest>(s.get(id)); return request<Blob | undefined>(c.get(`${id}:${m.acknowledged}`)) }) }
  acknowledge(id: string, bytes: number) {
    return this.transaction("readwrite", async (s, c) => {
      const m = await request<RecordingManifest>(s.get(id))
      await request(c.delete(`${id}:${m.acknowledged}`))
      m.acknowledged++; m.uploadedBytes += bytes
      await request(s.put(m))
    })
  }
  stop(id: string, fatal?: string, partial?: boolean) { return this.transaction("readwrite", async s => { const m = await request<RecordingManifest>(s.get(id)); m.stopped = true; if (fatal) m.fatal = fatal; if (partial) m.partial = true; await request(s.put(m)) }) }
  remove(id: string) {
    return this.transaction("readwrite", async (s, c) => {
      const keys = IDBKeyRange.bound(`${id}:`, `${id}:\uffff`)
      await request(c.delete(keys))
      await request(s.delete(id))
    })
  }
}

export type RecordingApiFetch = (path: string, init?: RequestInit) => Promise<Response>
export async function recordingJson(response: Response) {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === "string" ? body.detail : `Kërkesa dështoi (${response.status}).`)
  }
  return response.json()
}

export class RecordingUploader {
  private running?: Promise<void>
  error: string | null = null
  constructor(readonly id: string, private outbox: RecordingOutbox, private apiFetch: RecordingApiFetch,
              private change: () => void, private sleep = (ms: number) => new Promise(r => setTimeout(r, ms))) {}
  pump(): Promise<void> {
    if (this.running) return this.running
    this.error = null
    this.running = this.upload().catch(error => { this.error = String(error instanceof Error ? error.message : error); throw error })
      .finally(() => { this.running = undefined; this.change() })
    return this.running
  }
  private async upload() {
    for (;;) {
      const m = await this.outbox.get(this.id)
      if (m.acknowledged >= m.count) return
      const blob = await this.outbox.next(this.id)
      if (!blob) throw new Error("Mungon një fragment lokal. Regjistrimi nuk mund të shënohet si i plotë.")
      // Only one fragment is in RAM at a time, bounded by MAX_CHUNK_BYTES.
      const digest = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()))).map(b => b.toString(16).padStart(2, "0")).join("")
      for (let attempt = 0; ; attempt++) {
        let response: Response | undefined
        try {
          response = await this.apiFetch(`/meeting-recordings/${this.id}/chunks/${m.acknowledged}`, {
            method: "PUT", headers: { "Content-Type": "application/octet-stream", "X-Chunk-SHA256": digest }, body: blob,
            signal: AbortSignal.timeout(60_000),
          })
        } catch { /* Retry network failures with the identical index/content. */ }
        if (response?.ok) {
          const receipt = await response.json()
          if (receipt.index !== m.acknowledged || receipt.sha256 !== digest || receipt.size_bytes !== blob.size) throw new Error("Konfirmimi i fragmentit nuk përputhet.")
          await this.outbox.acknowledge(this.id, blob.size)
          this.change()
          break
        }
        if (attempt >= 4 || (response && response.status < 500 && ![408, 429, 499].includes(response.status))) {
          throw new Error(response ? `Ngarkimi dështoi (${response.status}). Provoni përsëri.` : "Lidhja me serverin u ndërpre. Provoni përsëri.")
        }
        await this.sleep(Math.min(1000 * 2 ** attempt, 16_000))
      }
    }
  }
  async complete() {
    const initial = await this.outbox.get(this.id)
    if (!initial.stopped || initial.fatal || !initial.count) throw new Error(initial.fatal || "Regjistrimi është i paplotë.")
    await this.pump()
    const m = await this.outbox.get(this.id)
    if (!m.stopped || m.fatal || !m.count || m.acknowledged !== m.count) throw new Error(m.fatal || "Regjistrimi është i paplotë.")
    const result = await recordingJson(await this.apiFetch(`/meeting-recordings/${this.id}/complete`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ chunks: m.count, partial: !!m.partial }), signal: AbortSignal.timeout(660_000),
    }))
    if (result.status !== "READY") throw new Error("Serveri nuk konfirmoi ruajtjen.")
    await this.outbox.remove(this.id)
    return result
  }
}
