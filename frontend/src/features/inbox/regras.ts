import type { CardLead, ColunaKanban, EventoDonoMudou, EventoMensagemNova, MensagemLead } from "@/lib/api"

export type VendedorResumo = { id: string; nome: string; ativo: boolean }

/** `vendedorId` null = aguardando vendedor (a IA chamou um e ninguém assumiu ainda). */
export type DonoLead = { tipo: "ia" } | { tipo: "vendedor"; vendedorId: string | null }

/** `CardLead.dono` é `ia`, `vendedor:<uuid>` ou `vendedor` (aguardando vendedor). */
export function interpretarDono(dono: string): DonoLead {
  if (dono.startsWith("vendedor:")) return { tipo: "vendedor", vendedorId: dono.slice("vendedor:".length) }
  if (dono === "vendedor") return { tipo: "vendedor", vendedorId: null }
  return { tipo: "ia" }
}

/** Conversa que o vendedor ainda pode pegar: com a IA ou aguardando vendedor. */
export function podeAssumir(dono: string): boolean {
  const d = interpretarDono(dono)
  return d.tipo === "ia" || d.vendedorId === null
}

/** O campo de resposta só vale quando o dono é exatamente o vendedor que está atendendo. */
export function podeResponder(dono: string, vendedorAtualId: string | null): boolean {
  const d = interpretarDono(dono)
  return d.tipo === "vendedor" && vendedorAtualId !== null && d.vendedorId === vendedorAtualId
}

/** Lista única de conversas, da atividade mais recente para a mais antiga. */
export function achatarConversas(colunas: Pick<ColunaKanban, "leads">[], atividade: Record<string, string>): CardLead[] {
  const instante = (c: CardLead) =>
    Math.max(Date.parse(atividade[c.id] ?? "") || 0, Date.parse(c.etapa_desde) || 0, Date.parse(c.criado_em) || 0)
  return colunas.flatMap((c) => c.leads).sort((a, b) => instante(b) - instante(a))
}

export function aplicarDono(cardAtual: CardLead, evento: EventoDonoMudou, vendedores: VendedorResumo[]): CardLead {
  const vendedorId = evento.vendedor_id ?? null
  return {
    ...cardAtual,
    dono: evento.dono,
    vendedor_id: vendedorId,
    vendedor_nome: vendedorId ? (vendedores.find((v) => v.id === vendedorId)?.nome ?? null) : null,
  }
}

/** O evento SSE não traz o id da mensagem: usa um id local `sse-<n>` até o próximo recarregamento. */
export function mensagemDeEvento(evento: EventoMensagemNova, sequencia: number): MensagemLead {
  return {
    id: `sse-${sequencia}`,
    conversa_id: evento.conversa_id,
    direcao: evento.direcao,
    autor: evento.autor,
    tipo: evento.tipo,
    texto: evento.texto,
    midia_url: evento.midia_url,
    criada_em: evento.em,
  }
}

const JANELA_ECO_MS = 15_000

const ehLocal = (m: MensagemLead) => m.id.startsWith("sse-")

function ehEco(a: MensagemLead, b: MensagemLead): boolean {
  return (
    a.autor === "vendedor" &&
    b.autor === "vendedor" &&
    a.tipo === b.tipo &&
    a.texto === b.texto &&
    a.midia_url === b.midia_url &&
    ehLocal(a) !== ehLocal(b) &&
    Math.abs(Date.parse(a.criada_em) - Date.parse(b.criada_em)) <= JANELA_ECO_MS
  )
}

/**
 * Acrescenta uma mensagem sem duplicar a que o próprio vendedor enviou: a resposta do POST (id
 * real) e o evento SSE (id `sse-`) descrevem a mesma mensagem, em qualquer ordem de chegada.
 * Só vale para mensagens do vendedor: nunca se descarta mensagem do cliente ou da IA (dois "Oi"
 * seguidos do cliente continuam separados).
 */
export function incorporarMensagem(mensagens: MensagemLead[], nova: MensagemLead): MensagemLead[] {
  if (mensagens.some((m) => m.id === nova.id)) return mensagens
  const i = mensagens.findIndex((m) => ehEco(m, nova))
  if (i < 0) return [...mensagens, nova]
  if (ehLocal(mensagens[i]) && !ehLocal(nova)) return mensagens.map((m, j) => (j === i ? nova : m))
  return mensagens
}
