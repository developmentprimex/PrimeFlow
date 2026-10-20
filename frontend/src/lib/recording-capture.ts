export type CaptureState = "idle" | "selecting" | "prepared" | "recording" | "paused" | "stopping" | "stopped" | "error"
export type CaptureInfo = { source: string; microphone: boolean; system: boolean; mime: string }

/** One controller owns every capture resource. It never connects to speakers. */
export class RecordingCapture {
  state: CaptureState = "idle"
  info: CaptureInfo = { source: "unknown", microphone: false, system: false, mime: "" }
  private display?: MediaStream
  private microphone?: MediaStream
  private mixed?: MediaStream
  private context?: AudioContext
  private nodes: AudioNode[] = []
  private recorder?: MediaRecorder
  private stopped?: Promise<void>
  private resolveStop?: () => void
  private ended?: () => void
  private elapsed = 0
  private runningAt = 0
  private generation = 0
  constructor(private events: {
    change: () => void
    chunk: (blob: Blob) => void
    stopped: () => void
    error: (error: Error) => void
  }) {}

  async prepare(deviceId: string | false, preferredSource: string) {
    if (!["idle", "stopped", "error"].includes(this.state)) return
    const generation = ++this.generation
    this.state = "selecting"
    this.events.change()
    try {
      if (!navigator.mediaDevices?.getDisplayMedia || typeof MediaRecorder === "undefined") {
        throw new Error("Ky shfletues nuk mbështet regjistrimin e ekranit. Përdorni Chrome ose Edge me HTTPS.")
      }
      // Must be invoked directly by the user's click, before any network await.
      const display = await navigator.mediaDevices.getDisplayMedia({
        video: { displaySurface: preferredSource, frameRate: { ideal: 15, max: 30 } },
        audio: true,
        ...{ systemAudio: "include", windowAudio: "system", selfBrowserSurface: "exclude" },
      })
      if (generation !== this.generation) { display.getTracks().forEach(t => t.stop()); return }
      this.display = display
      const video = display.getVideoTracks()[0]
      if (!video || video.readyState === "ended") throw new Error("Ndarja e ekranit përfundoi.")
      this.ended = () => { if (this.state === "recording" || this.state === "paused") void this.stop(); else this.cancel() }
      video.addEventListener("ended", this.ended)
      if (deviceId !== false) {
        const mic = await navigator.mediaDevices.getUserMedia({ audio: {
          ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
          echoCancellation: true, noiseSuppression: true, autoGainControl: true,
        } })
        if (generation !== this.generation) { mic.getTracks().forEach(t => t.stop()); return }
        this.microphone = mic
      }
      if (this.display?.getVideoTracks()[0]?.readyState !== "live") throw new Error("Ndarja e ekranit përfundoi.")
      const liveAudio = (stream?: MediaStream) => stream?.getAudioTracks().some(t => t.readyState === "live") ?? false
      const mime = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4"].find(t => MediaRecorder.isTypeSupported(t))
      if (!mime) throw new Error("Nuk u gjet një format video i mbështetur.")
      this.info = { source: video.getSettings().displaySurface || "unknown", microphone: liveAudio(this.microphone), system: liveAudio(display), mime }
      for (const track of [...display.getAudioTracks(), ...(this.microphone?.getAudioTracks() || [])]) {
        track.addEventListener("ended", this.audioChanged)
        track.addEventListener("mute", this.events.change)
        track.addEventListener("unmute", this.events.change)
      }
      this.state = "prepared"
      this.events.change()
    } catch (error) {
      if (generation !== this.generation) return
      this.release()
      this.state = "error"
      this.events.error(error instanceof Error ? error : new Error(String(error)))
      this.events.change()
    }
  }

  private audioChanged = () => {
    this.info.microphone = this.microphone?.getAudioTracks().some(t => t.readyState === "live") ?? false
    this.info.system = this.display?.getAudioTracks().some(t => t.readyState === "live") ?? false
    this.events.change()
  }

  get inputStatus() {
    const describe = (stream?: MediaStream) => {
      const tracks = stream?.getAudioTracks().filter(t => t.readyState === "live") || []
      return tracks.length ? tracks.some(t => t.enabled && !t.muted) ? "on" : "muted" : "unavailable"
    }
    return { microphone: describe(this.microphone), system: describe(this.display) }
  }

  async start() {
    if (this.state !== "prepared") throw new Error("Zgjidhni burimin e ekranit përsëri.")
    const video = this.display!.getVideoTracks()[0]
    if (video.readyState !== "live") throw new Error("Ndarja e ekranit përfundoi.")
    this.mixed = new MediaStream([video])
    if (this.info.microphone || this.info.system) {
      this.context = new AudioContext()
      await this.context.resume()
      if (this.state !== "prepared" || video.readyState !== "live") throw new Error("Ndarja e ekranit përfundoi.")
      const destination = this.context.createMediaStreamDestination()
      this.nodes.push(destination)
      for (const stream of [this.display, this.microphone]) {
        const tracks = stream?.getAudioTracks().filter(t => t.readyState === "live") || []
        if (!tracks.length) continue
        const source = this.context.createMediaStreamSource(new MediaStream(tracks))
        // Headroom for two sources. No connection to context.destination.
        const gain = this.context.createGain()
        gain.gain.value = 0.5
        source.connect(gain).connect(destination)
        this.nodes.push(source, gain)
      }
      destination.stream.getAudioTracks().forEach(t => this.mixed!.addTrack(t))
    }
    this.recorder = new MediaRecorder(this.mixed, { mimeType: this.info.mime, videoBitsPerSecond: 2_000_000, audioBitsPerSecond: 128_000 })
    this.recorder.ondataavailable = event => { if (event.data.size) this.events.chunk(event.data) }
    this.recorder.onerror = () => { this.events.error(new Error("Regjistrimi u ndërpre nga shfletuesi.")); void this.stop() }
    this.stopped = new Promise(resolve => { this.resolveStop = resolve })
    this.recorder.onstop = () => {
      this.freezeTime()
      this.state = "stopped"
      this.release()
      this.resolveStop?.()
      this.events.stopped()
      this.events.change()
    }
    this.elapsed = 0
    this.runningAt = performance.now()
    this.recorder.start(4000)
    this.state = "recording"
    this.events.change()
  }

  get seconds() { return (this.elapsed + (this.runningAt ? performance.now() - this.runningAt : 0)) / 1000 }
  private freezeTime() { if (this.runningAt) this.elapsed += performance.now() - this.runningAt; this.runningAt = 0 }
  pause() {
    if (this.state !== "recording") return
    this.recorder!.pause()
    this.freezeTime()
    this.state = "paused"
    this.events.change()
  }
  resume() {
    if (this.state !== "paused") return
    this.recorder!.resume()
    this.runningAt = performance.now()
    this.state = "recording"
    this.events.change()
  }
  toggle(input: "microphone" | "system") {
    const tracks = (input === "microphone" ? this.microphone : this.display)?.getAudioTracks() || []
    const enabled = !tracks.some(t => t.enabled)
    tracks.forEach(t => { t.enabled = enabled })
    this.events.change()
  }
  stop() {
    if (["recording", "paused"].includes(this.state)) {
      this.freezeTime()
      this.state = "stopping"
      this.recorder!.stop()
      this.events.change()
    }
    return this.stopped || Promise.resolve()
  }
  cancel() {
    if (["recording", "paused", "stopping"].includes(this.state)) { void this.stop(); return }
    this.generation++
    this.release()
    this.state = "idle"
    this.events.change()
  }
  private release() {
    if (this.ended) this.display?.getVideoTracks()[0]?.removeEventListener("ended", this.ended)
    for (const stream of [this.display, this.microphone, this.mixed]) {
      stream?.getTracks().forEach(track => {
        track.removeEventListener("ended", this.audioChanged)
        track.removeEventListener("mute", this.events.change)
        track.removeEventListener("unmute", this.events.change)
        track.stop()
      })
    }
    this.nodes.forEach(node => node.disconnect())
    this.nodes = []
    void this.context?.close().catch(() => {})
    this.context = undefined
    if (this.recorder) { this.recorder.ondataavailable = null; this.recorder.onstop = null; this.recorder.onerror = null }
    this.recorder = undefined
    this.display = this.microphone = this.mixed = undefined
  }
}
