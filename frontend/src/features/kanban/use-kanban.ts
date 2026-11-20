"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { useToast } from "@/components/ui/toast"
import { api, assinarEventosLoja, mensagemDeErro, type ColunaKanban } from "@/lib/api"
import type { Etapa } from "@/lib/etapas"

import { aplicarEvento, localizarCard, moverCard, restaurarCard, substituirCard, validarMovimento } from "./regras"

export type StatusKanban = "carregando" | "pronto" | "erro"

export function useKanban(lojaId: string) {
  const toast = useToast()
  const [colunas, setColunas] = useState<ColunaKanban[]>([])
  const [status, setStatus] = useState<StatusKanban>("carregando")
  const [tempoRealOk, setTempoRealOk] = useState(true)
  const colunasRef = useRef(colunas)
  const sequencia = useRef(0)
  const offline = useRef(false)

  const atualizar = useCallback((fn: (atual: ColunaKanban[]) => ColunaKanban[]) => {
    colunasRef.current = fn(colunasRef.current)
    setColunas(colunasRef.current)
  }, [])

  const carregar = useCallback(
    (exibirErro: boolean) => {
      const minha = ++sequencia.current
      api
        .GET("/lojas/{loja_id}/leads", { params: { path: { loja_id: lojaId } } })
        .then(({ data, error }) => {
          if (minha !== sequencia.current) return
          if (data) {
            colunasRef.current = data.etapas
            setColunas(data.etapas)
            setStatus("pronto")
          } else if (exibirErro) {
            console.error("kanban:", mensagemDeErro(error))
            setStatus("erro")
          }
        })
        .catch(() => {
          // falha de rede: mantém o que já está na tela; só a carga inicial/manual mostra erro
          if (minha === sequencia.current && exibirErro) setStatus("erro")
        })
    },
    [lojaId],
  )

  useEffect(() => {
    carregar(true)
    const fechar = assinarEventosLoja(
      lojaId,
      (evento) => {
        const voltou = offline.current
        offline.current = false
        setTempoRealOk(true)
        const r = aplicarEvento(colunasRef.current, evento)
        if (r.colunas !== colunasRef.current) atualizar(() => r.colunas)
        if (r.recarregar || voltou) carregar(false)
      },
      {
        onErro: () => {
          offline.current = true
          setTempoRealOk(false)
        },
      },
    )
    const contador = sequencia
    return () => {
      contador.current++
      fechar()
    }
  }, [lojaId, carregar, atualizar])

  const recarregar = useCallback(() => {
    setStatus("carregando")
    carregar(true)
  }, [carregar])

  const mover = useCallback(
    async (leadId: string, destino: Etapa) => {
      const achado = localizarCard(colunasRef.current, leadId)
      if (!achado) return
      const { card, indice } = achado
      const regra = validarMovimento(card.etapa, destino)
      if (!regra.permitido) {
        if (!regra.noop) toast.erro(regra.motivo)
        return
      }
      atualizar((c) => moverCard(c, leadId, destino, new Date().toISOString()))
      const { data, error } = await api.POST("/lojas/{loja_id}/leads/{lead_id}/etapa", {
        params: { path: { loja_id: lojaId, lead_id: leadId } },
        body: { etapa: destino },
      })
      if (data) {
        atualizar((c) => substituirCard(c, data))
      } else {
        atualizar((c) => restaurarCard(c, card, indice))
        toast.erro("Não foi possível mover o lead", { descricao: mensagemDeErro(error) })
      }
    },
    [lojaId, atualizar, toast],
  )

  return { colunas, status, tempoRealOk, mover, recarregar }
}
