/**
 * Etapas do kanban (espelham `Etapa` em backend/app/domain/kanban.py).
 * `token` e o sufixo do token de design `--stage-<token>` (DESIGN.md §2).
 */
export const ETAPAS = [
  { valor: "novo_contato", rotulo: "Novo contato", token: "novo-contato" },
  { valor: "interesse_identificado", rotulo: "Interesse identificado", token: "interesse-identificado" },
  { valor: "interesse_qualificado", rotulo: "Interesse qualificado", token: "interesse-qualificado" },
  { valor: "com_o_vendedor", rotulo: "Com o vendedor", token: "com-vendedor" },
  { valor: "venda_fechada", rotulo: "Venda fechada", token: "venda-fechada" },
] as const

export type Etapa = (typeof ETAPAS)[number]["valor"]

export function rotuloDaEtapa(etapa: Etapa): string {
  return ETAPAS.find((e) => e.valor === etapa)?.rotulo ?? etapa
}
