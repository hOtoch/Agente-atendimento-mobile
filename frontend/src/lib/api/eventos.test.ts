import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { assinarEventosLoja, type EventoPainel } from "./eventos"

class EventSourceFalso {
  static instancias: EventSourceFalso[] = []
  onmessage: ((e: MessageEvent<string>) => void) | null = null
  onerror: ((e: Event) => void) | null = null
  closed = false

  constructor(
    public url: string,
    public opcoes?: EventSourceInit,
  ) {
    EventSourceFalso.instancias.push(this)
  }

  close() {
    this.closed = true
  }

  emitir(dados: unknown) {
    this.onmessage?.({ data: typeof dados === "string" ? dados : JSON.stringify(dados) } as MessageEvent<string>)
  }
}

const LOJA = "11111111-1111-1111-1111-111111111111"
const LEAD = "22222222-2222-2222-2222-222222222222"

const etapaMudou: EventoPainel = {
  evento: "EtapaMudou",
  lead_id: LEAD,
  de: "novo_contato",
  para: "com_o_vendedor",
  ator: "vendedor",
  motivo: "Movido manualmente para Com o vendedor.",
  em: "2026-11-20T15:00:00Z",
}

beforeEach(() => {
  EventSourceFalso.instancias = []
  vi.stubGlobal("EventSource", EventSourceFalso)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("assinarEventosLoja", () => {
  it("abre o EventSource em /lojas/{id}/eventos na base da API", () => {
    assinarEventosLoja(LOJA, vi.fn(), { baseUrl: "http://api.local" })
    expect(EventSourceFalso.instancias).toHaveLength(1)
    expect(EventSourceFalso.instancias[0].url).toBe(`http://api.local/lojas/${LOJA}/eventos`)
  })

  it("abre o EventSource com cookies (withCredentials)", () => {
    assinarEventosLoja(LOJA, vi.fn(), { baseUrl: "http://api.local" })
    expect(EventSourceFalso.instancias[0].opcoes).toEqual({ withCredentials: true })
  })

  it("entrega cada evento tipado ao callback, discriminado por `evento`", () => {
    const recebidos: EventoPainel[] = []
    assinarEventosLoja(LOJA, (e) => recebidos.push(e), { baseUrl: "http://api.local" })
    const es = EventSourceFalso.instancias[0]

    es.emitir(etapaMudou)
    es.emitir({
      evento: "MensagemNova",
      lead_id: LEAD,
      conversa_id: "33333333-3333-3333-3333-333333333333",
      autor: "cliente",
      direcao: "entrada",
      tipo: "texto",
      texto: "oi",
      midia_url: null,
      em: "2026-11-20T15:00:01Z",
    })
    es.emitir({
      evento: "DonoMudou",
      lead_id: LEAD,
      dono: "ia",
      vendedor_id: null,
      em: "2026-11-20T15:00:02Z",
    })

    expect(recebidos.map((e) => e.evento)).toEqual(["EtapaMudou", "MensagemNova", "DonoMudou"])
    const primeiro = recebidos[0]
    if (primeiro.evento === "EtapaMudou") {
      expect(primeiro.para).toBe("com_o_vendedor")
    }
  })

  it("ignora payload que nao e JSON ou nao e um dos tres eventos", () => {
    const onEvento = vi.fn()
    assinarEventosLoja(LOJA, onEvento, { baseUrl: "http://api.local" })
    const es = EventSourceFalso.instancias[0]
    es.emitir("isto nao e json")
    es.emitir({ evento: "Outro", lead_id: LEAD })
    es.emitir({ sem: "evento" })
    expect(onEvento).not.toHaveBeenCalled()
  })

  it("a funcao devolvida fecha a conexao", () => {
    const cancelar = assinarEventosLoja(LOJA, vi.fn(), { baseUrl: "http://api.local" })
    const es = EventSourceFalso.instancias[0]
    expect(es.closed).toBe(false)
    cancelar()
    expect(es.closed).toBe(true)
  })

  it("repassa erros de conexao para onErro (o EventSource reconecta sozinho)", () => {
    const onErro = vi.fn()
    assinarEventosLoja(LOJA, vi.fn(), { baseUrl: "http://api.local", onErro })
    const es = EventSourceFalso.instancias[0]
    es.onerror?.(new Event("error"))
    expect(onErro).toHaveBeenCalledTimes(1)
    expect(es.closed).toBe(false)
  })
})
