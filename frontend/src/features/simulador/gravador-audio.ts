"use client"

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react"

const MIMES_PREFERIDOS = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"]

function escolherMime(): string | undefined {
  return MIMES_PREFERIDOS.find((m) => MediaRecorder.isTypeSupported?.(m))
}

function extensao(tipo: string): string {
  if (tipo.includes("ogg")) return "ogg"
  if (tipo.includes("mp4")) return "m4a"
  return "webm"
}

const semAssinatura = () => () => {}

function detectarSuporte(): boolean {
  return typeof MediaRecorder !== "undefined" && typeof navigator.mediaDevices?.getUserMedia === "function"
}

/** Gravação de áudio do microfone (MediaRecorder). `parar()` devolve o arquivo gravado. */
export function useGravadorAudio() {
  const suportado = useSyncExternalStore(semAssinatura, detectarSuporte, () => false)
  const [gravando, setGravando] = useState(false)
  const gravador = useRef<MediaRecorder | null>(null)
  const fluxo = useRef<MediaStream | null>(null)
  const pedacos = useRef<Blob[]>([])

  const liberar = useCallback(() => {
    fluxo.current?.getTracks().forEach((faixa) => faixa.stop())
    fluxo.current = null
    gravador.current = null
    setGravando(false)
  }, [])

  useEffect(() => liberar, [liberar])

  const iniciar = useCallback(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mime = escolherMime()
    const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
    pedacos.current = []
    rec.ondataavailable = (e) => {
      if (e.data.size > 0) pedacos.current.push(e.data)
    }
    fluxo.current = stream
    gravador.current = rec
    rec.start()
    setGravando(true)
  }, [])

  const parar = useCallback(
    () =>
      new Promise<File | null>((resolve) => {
        const rec = gravador.current
        if (!rec) return resolve(null)
        rec.onstop = () => {
          const tipo = (rec.mimeType || "audio/webm").split(";")[0]
          const arquivo = new File(pedacos.current, `audio.${extensao(tipo)}`, { type: tipo })
          liberar()
          resolve(arquivo)
        }
        rec.stop()
      }),
    [liberar],
  )

  return { suportado, gravando, iniciar, parar }
}
