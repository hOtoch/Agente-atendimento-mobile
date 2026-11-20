"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import type { EstadoConexao } from "@/lib/api"

import type { Cliente } from "./grades"

/** Consulta o status a cada 3 s e renova o QR (que expira) a cada ~20 s até conectar. */
export const INTERVALO_STATUS_MS = 3000
export const INTERVALO_QR_MS = 20000

const ROTULO: Record<EstadoConexao, { texto: string; variante: "success" | "warning" | "danger" }> = {
  conectado: { texto: "Conectado", variante: "success" },
  conectando: { texto: "Conectando", variante: "warning" },
  desconectado: { texto: "Desconectado", variante: "danger" },
  inexistente: { texto: "Desconectado", variante: "danger" },
}

/** A API devolve `data:image/png;base64,...`; aceita também o base64 cru sem duplicar o prefixo. */
function origemDoQr(qr: string): string {
  return qr.startsWith("data:") ? qr : `data:image/png;base64,${qr}`
}

type Conexao = { status: EstadoConexao; qr: string | null }

/** `null` = a API ou a Evolution não respondeu (502, rede caída). */
async function buscarStatus(cliente: Cliente, lojaId: string): Promise<EstadoConexao | null> {
  try {
    const { data, response } = await cliente.GET("/lojas/{loja_id}/whatsapp/status", {
      params: { path: { loja_id: lojaId } },
    })
    return response.ok && data ? data.status : null
  } catch {
    return null
  }
}

/** Cria a instância (se preciso) e traz o QR; `null` = Evolution indisponível. */
async function buscarConexao(cliente: Cliente, lojaId: string): Promise<Conexao | null> {
  try {
    const { data, response } = await cliente.POST("/lojas/{loja_id}/whatsapp/conectar", {
      params: { path: { loja_id: lojaId } },
    })
    return response.ok && data ? { status: data.status, qr: data.qr_base64 ?? null } : null
  } catch {
    return null
  }
}

export function PassoWhatsapp({ cliente, lojaId }: { cliente: Cliente; lojaId: string }) {
  const [estado, setEstado] = useState<EstadoConexao | null>(null)
  const [qr, setQr] = useState<string | null>(null)
  const [indisponivel, setIndisponivel] = useState(false)
  const [conectando, setConectando] = useState(false)
  const [acompanhando, setAcompanhando] = useState(false)
  const montado = useRef(true)
  const temQr = useRef(false)

  useEffect(() => {
    temQr.current = qr !== null
  }, [qr])

  useEffect(() => {
    montado.current = true
    return () => {
      montado.current = false
    }
  }, [])

  const aplicarStatus = useCallback((status: EstadoConexao | null) => {
    if (!montado.current) return
    setIndisponivel(status === null)
    if (status === null) return
    setEstado(status)
    if (status === "conectado") {
      setQr(null)
      setAcompanhando(false)
    }
  }, [])

  const consultarStatus = useCallback(
    async () => aplicarStatus(await buscarStatus(cliente, lojaId)),
    [cliente, lojaId, aplicarStatus],
  )

  const conectar = useCallback(async (): Promise<void> => {
    const conexao = await buscarConexao(cliente, lojaId)
    if (!montado.current) return
    setIndisponivel(conexao === null)
    if (conexao === null) return
    setEstado(conexao.status)
    setQr(conexao.status === "conectado" ? null : conexao.qr)
    setAcompanhando(conexao.status !== "conectado")
  }, [cliente, lojaId])

  useEffect(() => {
    let ativo = true
    void buscarStatus(cliente, lojaId).then((status) => {
      if (ativo) aplicarStatus(status)
    })
    return () => {
      ativo = false
    }
  }, [cliente, lojaId, aplicarStatus])

  useEffect(() => {
    if (!acompanhando) return
    let ocupado = false
    let desdeOQr = 0
    const id = setInterval(async () => {
      if (ocupado) return
      ocupado = true
      try {
        desdeOQr += INTERVALO_STATUS_MS
        await consultarStatus()
        // sem QR ainda (instância recém-criada): tenta de novo já neste ciclo
        if ((desdeOQr >= INTERVALO_QR_MS || !temQr.current) && montado.current) {
          desdeOQr = 0
          await conectar()
        }
      } finally {
        ocupado = false
      }
    }, INTERVALO_STATUS_MS)
    return () => clearInterval(id)
  }, [acompanhando, consultarStatus, conectar])

  async function aoConectar() {
    setConectando(true)
    await conectar()
    if (montado.current) setConectando(false)
  }

  const rotulo = estado ? ROTULO[estado] : null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Conectar WhatsApp</CardTitle>
        <CardDescription>Leia o QR Code com o celular da loja.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Situação da conexão:</span>
          {rotulo ? <Badge variant={rotulo.variante}>{rotulo.texto}</Badge> : !indisponivel && <Skeleton className="h-5 w-24" />}
        </div>

        {indisponivel && (
          <div role="alert" className="flex flex-col items-start gap-2 text-sm text-danger">
            <p>Evolution indisponível. Verifique se o serviço do WhatsApp está no ar e tente de novo.</p>
            <Button variant="outline" size="sm" onClick={() => void aoConectar()} disabled={conectando}>
              Tentar de novo
            </Button>
          </div>
        )}

        {estado === "conectado" ? (
          <p className="text-sm">O WhatsApp da loja está conectado. As conversas já chegam ao atendimento.</p>
        ) : (
          <>
            {qr ? (
              // eslint-disable-next-line @next/next/no-img-element -- QR em data URI vindo da API
              <img
                src={origemDoQr(qr)}
                alt="QR Code para conectar o WhatsApp da loja"
                className="size-56 rounded-lg border border-border bg-background p-2"
              />
            ) : acompanhando ? (
              <p className="text-sm text-muted-foreground">Gerando o QR Code…</p>
            ) : null}
            {acompanhando && qr && (
              <p className="text-sm text-muted-foreground">
                No celular: WhatsApp &gt; Aparelhos conectados &gt; Conectar aparelho. O QR Code é renovado sozinho.
              </p>
            )}
            {!indisponivel && !acompanhando && (
              <div>
                <Button onClick={() => void aoConectar()} disabled={conectando}>
                  Conectar
                </Button>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
