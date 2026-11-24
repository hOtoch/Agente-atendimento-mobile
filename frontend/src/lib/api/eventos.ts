import { URL_API } from "./cliente"
import type { components } from "./schema"

type Schemas = components["schemas"]

export type EventoEtapaMudou = Schemas["EventoEtapaMudouSchema"]
export type EventoMensagemNova = Schemas["EventoMensagemNovaSchema"]
export type EventoDonoMudou = Schemas["EventoDonoMudouSchema"]
export type EventoLeadRemovido = Schemas["EventoLeadRemovidoSchema"]
/** Uniao discriminada por `evento`, igual ao payload publicado em `/lojas/{id}/eventos`. */
export type EventoPainel = Schemas["EventoPainel"]

const EVENTOS_CONHECIDOS: ReadonlySet<string> = new Set<EventoPainel["evento"]>([
  "EtapaMudou",
  "MensagemNova",
  "DonoMudou",
  "LeadRemovido",
])

export type OpcoesAssinatura = {
  baseUrl?: string
  /** Erro de conexao; o EventSource reconecta sozinho, entao nao fecha a assinatura. */
  onErro?: (erro: Event) => void
}

function interpretar(dados: string): EventoPainel | null {
  try {
    const evento: unknown = JSON.parse(dados)
    if (
      typeof evento === "object" &&
      evento !== null &&
      "evento" in evento &&
      typeof evento.evento === "string" &&
      EVENTOS_CONHECIDOS.has(evento.evento)
    ) {
      return evento as EventoPainel
    }
  } catch {
    // heartbeat/lixo: ignora
  }
  return null
}

/**
 * Assina o SSE da loja e entrega cada evento tipado. Devolve a funcao que encerra a conexao
 * (chame no cleanup do `useEffect`). Kanban e inbox usam este helper em vez de abrir o seu.
 */
export function assinarEventosLoja(
  lojaId: string,
  onEvento: (evento: EventoPainel) => void,
  { baseUrl = URL_API, onErro }: OpcoesAssinatura = {},
): () => void {
  const fonte = new EventSource(`${baseUrl}/lojas/${lojaId}/eventos`, { withCredentials: true })
  fonte.onmessage = (mensagem: MessageEvent<string>) => {
    const evento = interpretar(mensagem.data)
    if (evento) onEvento(evento)
  }
  if (onErro) fonte.onerror = onErro
  return () => fonte.close()
}
