import type { Metricas } from "@/lib/api"
import type { VariacaoTile } from "@/components/ui/stat-tile"

import {
  formatarDuracao,
  formatarInteiro,
  formatarPercentual,
  formatarUsd,
  formatarVariacao,
} from "./formatar"

export type Kpis = Metricas["kpis"]
export type Sentido = "maior-melhor" | "menor-melhor" | "neutro"
export type Formato = "inteiro" | "percentual" | "usd" | "duracao"
export type Tom = VariacaoTile["tom"]

export type Indicador = { valor: number | string | null; variacao_pct: number | null }

export type DefinicaoIndicador = {
  chave: keyof Kpis
  rotulo: string
  /** Explicação em linguagem de dono de loja. */
  dica: string
  formato: Formato
  /** Quando a variação é boa: subir, cair ou nenhum (não julga). */
  sentido: Sentido
}

/** Os KPIs da visão geral, na ordem em que aparecem. */
export const INDICADORES_PRINCIPAIS: readonly DefinicaoIndicador[] = [
  {
    chave: "conversas_ativas",
    rotulo: "Conversas atendidas",
    dica: "Clientes que trocaram mensagens com a IA no período.",
    formato: "inteiro",
    sentido: "maior-melhor",
  },
  {
    chave: "acordos_fechados",
    rotulo: "Acordos fechados",
    dica: "Negociações em que cliente e IA chegaram a um acordo de compra.",
    formato: "inteiro",
    sentido: "maior-melhor",
  },
  {
    chave: "taxa_conversao",
    rotulo: "Taxa de conversão",
    dica: "De cada 100 conversas atendidas, quantas viraram acordo.",
    formato: "percentual",
    sentido: "maior-melhor",
  },
  {
    chave: "custo_total_usd",
    rotulo: "Gasto com a IA",
    dica: "Quanto a IA custou no período, em dólares.",
    formato: "usd",
    sentido: "menor-melhor",
  },
  {
    chave: "custo_por_conversa_usd",
    rotulo: "Custo por conversa",
    dica: "Gasto com a IA dividido pelas conversas atendidas.",
    formato: "usd",
    sentido: "menor-melhor",
  },
  {
    chave: "tempo_resposta_media_ms",
    rotulo: "Tempo médio de resposta",
    dica: "Quanto o cliente espera, em média, até receber a resposta.",
    formato: "duracao",
    sentido: "menor-melhor",
  },
  {
    chave: "taxa_handoff",
    rotulo: "Passadas ao vendedor",
    dica: "Parte das conversas que a IA encaminhou a um vendedor (inclui acordos fechados).",
    formato: "percentual",
    sentido: "neutro",
  },
  {
    chave: "erros",
    rotulo: "Erros",
    dica: "Falhas da IA ou das suas ferramentas no período.",
    formato: "inteiro",
    sentido: "menor-melhor",
  },
]

/** Se a variação é boa, ruim ou neutra para o dono, conforme o sentido do indicador. */
export function tomDaVariacao(sentido: Sentido, pct: number | null): Tom {
  if (pct === null || pct === 0 || sentido === "neutro") return "neutro"
  const subiu = pct > 0
  return subiu === (sentido === "maior-melhor") ? "bom" : "ruim"
}

export function formatarIndicador(formato: Formato, valor: number | string | null): string | null {
  if (valor === null) return null
  switch (formato) {
    case "inteiro":
      return formatarInteiro(Number(valor))
    case "percentual":
      return formatarPercentual(Number(valor))
    case "usd":
      return formatarUsd(valor)
    case "duracao":
      return formatarDuracao(Number(valor))
  }
}

/** Variação pronta para o `StatTile`: `null` quando não há comparação. */
export function variacaoDoIndicador(sentido: Sentido, pct: number | null): VariacaoTile | null {
  const texto = formatarVariacao(pct)
  if (texto === null || pct === null) return null
  const direcao = pct > 0 ? "alta" : pct < 0 ? "baixa" : "estavel"
  const magnitude = texto.replace(/^[+-]/, "")
  const descricao =
    direcao === "estavel"
      ? "sem mudança em relação ao período anterior"
      : `${direcao === "alta" ? "aumento" : "queda"} de ${magnitude} em relação ao período anterior`
  return { texto, tom: tomDaVariacao(sentido, pct), direcao, descricao }
}

/** Período sem conversas, mensagens nem chamadas à IA: não há o que mostrar. */
export function semDados(m: Metricas): boolean {
  return (
    (m.kpis.conversas_ativas.valor ?? 0) === 0 &&
    (m.kpis.mensagens_recebidas.valor ?? 0) === 0 &&
    m.tokens.chamadas === 0
  )
}
