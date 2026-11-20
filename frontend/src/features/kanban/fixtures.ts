import type { CardLead, ColunaKanban } from "@/lib/api"
import { ETAPAS } from "@/lib/etapas"

/** Dados de teste do kanban (compartilhados pelos testes da feature). */
export const LEAD_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
export const LEAD_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
export const LEAD_C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
export const VENDEDOR_ANA = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"

export function card(parcial: Partial<CardLead> & Pick<CardLead, "id" | "etapa">): CardLead {
  return {
    nome: null,
    telefone: "5511999990000",
    canal: "whatsapp",
    etapa_desde: "2025-01-01T00:00:00Z",
    criado_em: "2026-11-20T10:00:00Z",
    dono: "ia",
    vendedor_id: null,
    vendedor_nome: null,
    aparelho_desejado: null,
    valor_estimado: null,
    ...parcial,
  }
}

export function colunas(leads: CardLead[]): ColunaKanban[] {
  return ETAPAS.map((e) => ({
    etapa: e.valor,
    nome: e.rotulo,
    leads: leads.filter((l) => l.etapa === e.valor),
  }))
}

export const CARD_A = card({
  id: LEAD_A,
  etapa: "novo_contato",
  nome: "Maria Souza",
  telefone: "5511988887777",
  aparelho_desejado: "iPhone 13 128GB",
  valor_estimado: "3499.90",
})
export const CARD_B = card({
  id: LEAD_B,
  etapa: "interesse_qualificado",
  nome: "João Lima",
  dono: `vendedor:${VENDEDOR_ANA}`,
  vendedor_id: VENDEDOR_ANA,
  vendedor_nome: "Ana Paula",
})
export const CARD_C = card({ id: LEAD_C, etapa: "venda_fechada", nome: "Carla Dias" })
