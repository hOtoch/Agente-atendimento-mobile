"use client"

import { useCallback, useEffect, useState } from "react"

import { api, mensagemDeErro, type Metricas } from "@/lib/api"

export type StatusDesempenho = "carregando" | "pronto" | "erro"

type Resultado = { chave: string; erro: boolean; dados: Metricas | null }

/**
 * Busca as métricas do período. Ao trocar o período mantém a resposta anterior na tela
 * (`atualizando`), sem voltar ao esqueleto; só a primeira carga (ou a de depois de um erro) mostra esqueleto.
 */
export function useDesempenho(lojaId: string, de: string, ate: string) {
  const [tentativa, setTentativa] = useState(0)
  const [resultado, setResultado] = useState<Resultado | null>(null)
  const chave = `${lojaId}|${de}|${ate}|${tentativa}`

  useEffect(() => {
    let ativo = true
    const registrar = (dados: Metricas | null) =>
      setResultado((anterior) => ({
        chave,
        erro: dados === null,
        dados: dados ?? anterior?.dados ?? null,
      }))

    api
      .GET("/lojas/{loja_id}/metricas", { params: { path: { loja_id: lojaId }, query: { de, ate } } })
      .then(({ data, error }) => {
        if (!ativo) return
        if (!data) console.error("desempenho:", mensagemDeErro(error))
        registrar(data ?? null)
      })
      .catch(() => {
        if (ativo) registrar(null)
      })

    return () => {
      ativo = false
    }
  }, [chave, lojaId, de, ate])

  const recarregar = useCallback(() => setTentativa((t) => t + 1), [])

  const atual = resultado?.chave === chave
  const status: StatusDesempenho = atual
    ? resultado.erro
      ? "erro"
      : "pronto"
    : resultado?.dados && !resultado.erro
      ? "pronto"
      : "carregando"

  return {
    status,
    dados: status === "pronto" ? (resultado?.dados ?? null) : null,
    atualizando: status === "pronto" && !atual,
    recarregar,
  }
}
