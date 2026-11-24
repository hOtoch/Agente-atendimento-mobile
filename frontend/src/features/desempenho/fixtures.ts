import type { Metricas } from "@/lib/api"

type Indicador = { valor: number | null; anterior: number | null; variacao_pct: number | null }
type IndicadorUsd = { valor: string | null; anterior: string | null; variacao_pct: number | null }

const ind = (valor: number | null, anterior: number | null, variacao_pct: number | null): Indicador => ({
  valor,
  anterior,
  variacao_pct,
})
const usd = (valor: string | null, anterior: string | null, variacao_pct: number | null): IndicadorUsd => ({
  valor,
  anterior,
  variacao_pct,
})

const ETAPAS_FUNIL = [
  ["novo_contato", "Novo contato", 40, 30],
  ["interesse_identificado", "Interesse identificado", 30, 28],
  ["interesse_qualificado", "Interesse qualificado", 20, 15],
  ["com_o_vendedor", "Com o vendedor", 12, 10],
  ["venda_fechada", "Venda fechada", 6, 5],
] as const

/** Série diária de teste: `dias` pontos a partir de `de` (AAAA-MM-DD), valores previsíveis. */
export function serieDiaria(de: string, dias: number): Metricas["series"] {
  const base = new Date(`${de}T00:00:00Z`)
  return Array.from({ length: dias }, (_, i) => {
    const d = new Date(base)
    d.setUTCDate(d.getUTCDate() + i)
    return {
      dia: d.toISOString().slice(0, 10),
      conversas_novas: i + 1,
      conversas_ativas: i + 2,
      mensagens_recebidas: (i + 1) * 10,
      tokens: 1000 * (i + 1),
      custo_usd: ((i + 1) * 0.05).toFixed(4),
      latencia_llm_media_ms: i === 0 ? null : 900 + i * 10,
      latencia_llm_p95_ms: i === 0 ? null : 2000 + i * 10,
      tempo_resposta_media_ms: i === 0 ? null : 2400 + i * 10,
      tempo_resposta_p95_ms: i === 0 ? null : 5000 + i * 10,
      erros: i % 3 === 0 ? 1 : 0,
    }
  })
}

/** Resposta da API com atividade no período (compartilhada pelos testes da feature). */
export function metricasCompletas(sobrescrever: Partial<Metricas> = {}): Metricas {
  return {
    periodo: {
      de: "2026-10-24",
      ate: "2026-11-22",
      dias: 30,
      fuso: "America/Sao_Paulo",
      anterior_de: "2026-09-24",
      anterior_ate: "2026-10-23",
    },
    kpis: {
      conversas_novas: ind(60, 50, 20),
      conversas_ativas: ind(120, 100, 20),
      mensagens_recebidas: ind(900, 800, 12.5),
      mensagens_enviadas: ind(1000, 900, 11.1),
      mensagens_por_conversa: ind(15.8, 17, -7.1),
      handoffs: ind(12, 10, 20),
      taxa_handoff: ind(0.1, 0.1, 0),
      acordos_fechados: ind(15, 10, 50),
      taxa_conversao: ind(0.125, 0.1, 25),
      tokens_total: ind(500000, 400000, 25),
      taxa_cache: ind(0.9, 0.8, 12.5),
      custo_total_usd: usd("15.3", "10.2", 50),
      custo_por_conversa_usd: usd("0.1275", "0.102", 25),
      custo_por_acordo_usd: usd("1.02", "1.02", 0),
      latencia_llm_media_ms: ind(900, 1000, -10),
      latencia_llm_p95_ms: ind(2000, 2200, -9.1),
      tempo_resposta_media_ms: ind(2400, 3000, -20),
      tempo_resposta_p95_ms: ind(5200, 6000, -13.3),
      erros: ind(5, 2, 150),
      respostas_descartadas: ind(1, 1, 0),
    },
    funil: ETAPAS_FUNIL.map(([etapa, nome, leads, leads_anterior]) => ({ etapa, nome, leads, leads_anterior })),
    handoffs: {
      total: 12,
      por_motivo: [
        { motivo: "pedido_cliente", nome: "Pedido do cliente", quantidade: 5, anterior: 4 },
        { motivo: "acordo_fechado", nome: "Acordo fechado", quantidade: 6, anterior: 5 },
        { motivo: "falha_tecnica", nome: "Falha técnica", quantidade: 1, anterior: 1 },
        { motivo: "negociacao", nome: "Negociação além do teto", quantidade: 0, anterior: 0 },
        { motivo: "outros", nome: "Outros", quantidade: 0, anterior: 0 },
      ],
    },
    tokens: { entrada: 50000, saida: 30000, cache_leitura: 400000, cache_escrita: 20000, total: 500000, chamadas: 300 },
    custo: {
      total_usd: "15.3",
      completo: true,
      modelos_sem_preco: [],
      por_modelo: [
        {
          modelo: "claude-sonnet-5-5",
          custo_usd: "15.3",
          chamadas: 300,
          entrada: 50000,
          saida: 30000,
          cache_leitura: 400000,
          cache_escrita: 20000,
        },
      ],
    },
    erros: {
      total: 5,
      llm: 2,
      ferramentas: 1,
      limite_iteracoes: 1,
      respostas_descartadas: 1,
      llm_por_tipo: [{ tipo: "RateLimitError", quantidade: 2 }],
    },
    ferramentas: [
      { nome: "consultar_estoque", execucoes: 80, erros: 1 },
      { nome: "calcular_preco", execucoes: 40, erros: 0 },
    ],
    modelos_procurados: [
      { modelo: "iPhone 13 128GB", leads: 18 },
      { modelo: "Galaxy S23", leads: 9 },
    ],
    mapa_horario: [
      { dia_semana: 0, hora: 14, mensagens: 32 },
      { dia_semana: 2, hora: 9, mensagens: 21 },
      { dia_semana: 4, hora: 18, mensagens: 10 },
    ],
    series: serieDiaria("2026-10-24", 30),
    ...sobrescrever,
  }
}

/** Período sem nenhuma atividade: a API devolve a estrutura completa, tudo zerado/nulo. */
export function metricasVazias(): Metricas {
  const base = metricasCompletas()
  const zero = ind(0, 0, 0)
  const nulo = ind(null, null, null)
  return {
    ...base,
    kpis: {
      conversas_novas: zero,
      conversas_ativas: zero,
      mensagens_recebidas: zero,
      mensagens_enviadas: zero,
      mensagens_por_conversa: nulo,
      handoffs: zero,
      taxa_handoff: nulo,
      acordos_fechados: zero,
      taxa_conversao: nulo,
      tokens_total: zero,
      taxa_cache: nulo,
      custo_total_usd: usd("0", "0", 0),
      custo_por_conversa_usd: usd(null, null, null),
      custo_por_acordo_usd: usd(null, null, null),
      latencia_llm_media_ms: nulo,
      latencia_llm_p95_ms: nulo,
      tempo_resposta_media_ms: nulo,
      tempo_resposta_p95_ms: nulo,
      erros: zero,
      respostas_descartadas: zero,
    },
    funil: base.funil.map((e) => ({ ...e, leads: 0, leads_anterior: 0 })),
    handoffs: { total: 0, por_motivo: base.handoffs.por_motivo.map((m) => ({ ...m, quantidade: 0, anterior: 0 })) },
    tokens: { entrada: 0, saida: 0, cache_leitura: 0, cache_escrita: 0, total: 0, chamadas: 0 },
    custo: { total_usd: "0", completo: true, modelos_sem_preco: [], por_modelo: [] },
    erros: { total: 0, llm: 0, ferramentas: 0, limite_iteracoes: 0, respostas_descartadas: 0, llm_por_tipo: [] },
    ferramentas: [],
    modelos_procurados: [],
    mapa_horario: [],
    series: [],
  }
}
