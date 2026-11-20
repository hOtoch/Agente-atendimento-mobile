import type { CardLead, ColunaKanban, EventoPainel } from "@/lib/api"
import type { Etapa } from "@/lib/etapas"

/**
 * Regras puras do kanban no front. O servidor é a autoridade (backend/app/domain/kanban.py);
 * aqui só se bloqueia de antemão o óbvio e se aplica estado otimista / eventos SSE.
 */

export type Movimento = { permitido: true } | { permitido: false; noop: boolean; motivo: string }

export function validarMovimento(origem: Etapa, destino: Etapa): Movimento {
  if (origem === destino) return { permitido: false, noop: true, motivo: "O lead já está nesta etapa." }
  if (origem === "venda_fechada") {
    return { permitido: false, noop: false, motivo: "Venda fechada é uma etapa final." }
  }
  return { permitido: true }
}

export function localizarCard(
  colunas: ColunaKanban[],
  leadId: string,
): { card: CardLead; indice: number } | null {
  for (const coluna of colunas) {
    const indice = coluna.leads.findIndex((l) => l.id === leadId)
    if (indice >= 0) return { card: coluna.leads[indice], indice }
  }
  return null
}

function inserir(colunas: ColunaKanban[], card: CardLead, indice: number): ColunaKanban[] {
  return colunas.map((coluna) => {
    const sem = coluna.leads.filter((l) => l.id !== card.id)
    if (coluna.etapa !== card.etapa) return sem.length === coluna.leads.length ? coluna : { ...coluna, leads: sem }
    const i = Math.min(Math.max(indice, 0), sem.length)
    return { ...coluna, leads: [...sem.slice(0, i), card, ...sem.slice(i)] }
  })
}

/** Move o card para o topo da coluna destino (update otimista / evento). */
export function moverCard(colunas: ColunaKanban[], leadId: string, para: Etapa, em: string): ColunaKanban[] {
  const achado = localizarCard(colunas, leadId)
  if (!achado) return colunas
  return inserir(colunas, { ...achado.card, etapa: para, etapa_desde: em }, 0)
}

/** Desfaz um movimento otimista: devolve o card original à posição de origem. */
export function restaurarCard(colunas: ColunaKanban[], original: CardLead, indice: number): ColunaKanban[] {
  return inserir(colunas, original, indice)
}

/** Troca o card pelo devolvido pela API (mantendo a coluna indicada por ele). */
export function substituirCard(colunas: ColunaKanban[], card: CardLead): ColunaKanban[] {
  const achado = localizarCard(colunas, card.id)
  return inserir(colunas, card, achado && achado.card.etapa === card.etapa ? achado.indice : 0)
}

export type ResultadoEvento = { colunas: ColunaKanban[]; recarregar: boolean }

function nomeDoVendedor(colunas: ColunaKanban[], vendedorId: string): string | null {
  for (const coluna of colunas) {
    for (const lead of coluna.leads) {
      if (lead.vendedor_id === vendedorId && lead.vendedor_nome) return lead.vendedor_nome
    }
  }
  return null
}

export function aplicarEvento(colunas: ColunaKanban[], evento: EventoPainel): ResultadoEvento {
  const achado = localizarCard(colunas, evento.lead_id)
  if (!achado) return { colunas, recarregar: true }
  const { card, indice } = achado

  if (evento.evento === "EtapaMudou") {
    if (card.etapa === evento.para) return { colunas, recarregar: false }
    return { colunas: moverCard(colunas, card.id, evento.para, evento.em), recarregar: false }
  }

  if (evento.evento === "DonoMudou") {
    const vendedorId = evento.vendedor_id ?? null
    const nome =
      vendedorId === null
        ? null
        : card.vendedor_id === vendedorId
          ? card.vendedor_nome
          : nomeDoVendedor(colunas, vendedorId)
    const atualizado: CardLead = { ...card, dono: evento.dono, vendedor_id: vendedorId, vendedor_nome: nome }
    return {
      colunas: inserir(colunas, atualizado, indice),
      recarregar: vendedorId !== null && nome === null,
    }
  }

  return { colunas, recarregar: false }
}

export type FiltroVendedor = "todos" | "ia" | (string & {})
export type OpcaoFiltro = { valor: FiltroVendedor; rotulo: string }

export function opcoesDeVendedor(colunas: ColunaKanban[]): OpcaoFiltro[] {
  const vendedores = new Map<string, string>()
  for (const coluna of colunas) {
    for (const lead of coluna.leads) {
      if (lead.vendedor_id && !vendedores.has(lead.vendedor_id)) {
        vendedores.set(lead.vendedor_id, lead.vendedor_nome ?? "Vendedor")
      }
    }
  }
  return [
    { valor: "todos", rotulo: "Todos" },
    { valor: "ia", rotulo: "IA" },
    ...[...vendedores].map(([valor, rotulo]) => ({ valor, rotulo })),
  ]
}

export function filtrarColunas(colunas: ColunaKanban[], filtro: FiltroVendedor): ColunaKanban[] {
  if (filtro === "todos") return colunas
  const bate = (l: CardLead) => (filtro === "ia" ? l.dono === "ia" : l.vendedor_id === filtro)
  return colunas.map((c) => ({ ...c, leads: c.leads.filter(bate) }))
}

export function tempoNaEtapa(desde: string, agora: Date): string {
  const min = Math.floor((agora.getTime() - new Date(desde).getTime()) / 60_000)
  if (min < 1) return "agora"
  if (min < 60) return `há ${min} min`
  const h = Math.floor(min / 60)
  if (h < 24) return `há ${h} h`
  return `há ${Math.floor(h / 24)} d`
}

const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" })

/** Só exibição: o valor vem do servidor como string decimal. */
export function formatarValor(valor: string | null): string | null {
  if (valor === null) return null
  const n = Number(valor)
  return Number.isFinite(n) ? BRL.format(n) : null
}
