import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useGravadorAudio } from "./gravador-audio"

class MediaRecorderFalso {
  static ultimo: MediaRecorderFalso
  ondataavailable: ((e: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null
  state: "inactive" | "recording" = "inactive"
  mimeType: string
  constructor(
    public stream: MediaStream,
    opcoes?: { mimeType?: string },
  ) {
    this.mimeType = opcoes?.mimeType ?? "audio/webm"
    MediaRecorderFalso.ultimo = this
  }
  static isTypeSupported = (t: string) => t === "audio/webm;codecs=opus"
  start() {
    this.state = "recording"
  }
  stop() {
    this.state = "inactive"
    this.ondataavailable?.({ data: new Blob(["voz"], { type: this.mimeType }) })
    this.onstop?.()
  }
}

const parar = vi.fn()
const getUserMedia = vi.fn()

beforeEach(() => {
  parar.mockReset()
  getUserMedia.mockReset().mockResolvedValue({ getTracks: () => [{ stop: parar }] })
  vi.stubGlobal("MediaRecorder", MediaRecorderFalso)
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia }, configurable: true })
})
afterEach(() => vi.unstubAllGlobals())

describe("useGravadorAudio", () => {
  it("grava, devolve um File de áudio e libera o microfone", async () => {
    const { result } = renderHook(() => useGravadorAudio())
    expect(result.current.suportado).toBe(true)
    expect(result.current.gravando).toBe(false)

    await act(() => result.current.iniciar())
    expect(result.current.gravando).toBe(true)

    let arquivo: File | null = null
    await act(async () => {
      arquivo = await result.current.parar()
    })

    expect(result.current.gravando).toBe(false)
    expect(arquivo).toBeInstanceOf(File)
    expect((arquivo as unknown as File).type).toBe("audio/webm")
    expect((arquivo as unknown as File).name).toMatch(/\.webm$/)
    expect(parar).toHaveBeenCalled()
  })

  it("propaga a recusa de permissão do microfone", async () => {
    getUserMedia.mockRejectedValue(new DOMException("negado", "NotAllowedError"))
    const { result } = renderHook(() => useGravadorAudio())
    await expect(act(() => result.current.iniciar())).rejects.toThrow()
    expect(result.current.gravando).toBe(false)
  })

  it("reporta não suportado sem MediaRecorder", () => {
    vi.stubGlobal("MediaRecorder", undefined)
    const { result } = renderHook(() => useGravadorAudio())
    expect(result.current.suportado).toBe(false)
  })
})
