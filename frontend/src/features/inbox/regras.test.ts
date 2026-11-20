import { describe, expect, it } from "vitest"

import type { EventoMensagemNova } from "@/lib/api"

import { CARD_JOAO, CARD_MARIA, LEAD_MARIA, VENDEDOR_ANA, VENDEDORES, card, mensagem } from "./fixtures"
import {
  achatarConversas,
  aplicarDono,
  incorporarMensagem,
  interpretarDono,
  mensagemDeEvento,
  podeResponder,
} from "./regras"

describe("dono", () => {
  it("interpreta ia e vendedor", () => {
    expect(interpretarDono("ia")).toEqual({ tipo: "ia" })
    expect(interpretarDono(`vendedor:${VENDEDOR_ANA}`)).toEqual({ tipo: "vendedor", vendedorId: VENDEDOR_ANA })
  })

  it("`vendedor` sem id é a conversa aguardando vendedor", () => {
    expect(interpretarDono("vendedor")).toEqual({ tipo: "vendedor", vendedorId: null })
    expect(podeResponder("vendedor", VENDEDOR_ANA)).toBe(false)
  })

  it("só pode responder quando o dono é o vendedor atual", () => {
    expect(podeResponder("ia", VENDEDOR_ANA)).toBe(false)
    expect(podeResponder(`vendedor:${VENDEDOR_ANA}`, VENDEDOR_ANA)).toBe(true)
    expect(podeResponder(`vendedor:${VENDEDOR_ANA}`, "outro")).toBe(false)
    expect(podeResponder(`vendedor:${VENDEDOR_ANA}`, null)).toBe(false)
  })
})

describe("achatarConversas", () => {
  const colunas = [
    { etapa: "novo_contato" as const, nome: "Novo", leads: [CARD_JOAO] },
    { etapa: "interesse_qualificado" as const, nome: "Q", leads: [CARD_MARIA] },
  ]

  it("ordena pela atividade mais recente", () => {
    expect(achatarConversas(colunas, {}).map((c) => c.id)).toEqual([CARD_MARIA.id, CARD_JOAO.id])
  })

  it("atividade vinda de mensagens nova sobrescreve a base", () => {
    const ordem = achatarConversas(colunas, { [CARD_JOAO.id]: "2026-11-20T20:00:00Z" })
    expect(ordem.map((c) => c.id)).toEqual([CARD_JOAO.id, CARD_MARIA.id])
  })
})

describe("aplicarDono", () => {
  it("atualiza dono e nome do vendedor", () => {
    const novo = aplicarDono(
      CARD_MARIA,
      { evento: "DonoMudou", lead_id: LEAD_MARIA, dono: `vendedor:${VENDEDOR_ANA}`, vendedor_id: VENDEDOR_ANA, em: "x" },
      VENDEDORES,
    )
    expect(novo.dono).toBe(`vendedor:${VENDEDOR_ANA}`)
    expect(novo.vendedor_id).toBe(VENDEDOR_ANA)
    expect(novo.vendedor_nome).toBe("Ana Paula")
  })

  it("devolver limpa o vendedor", () => {
    const com = card({ id: "x", dono: `vendedor:${VENDEDOR_ANA}`, vendedor_id: VENDEDOR_ANA, vendedor_nome: "Ana Paula" })
    const novo = aplicarDono(com, { evento: "DonoMudou", lead_id: "x", dono: "ia", vendedor_id: null, em: "x" }, VENDEDORES)
    expect(novo).toMatchObject({ dono: "ia", vendedor_id: null, vendedor_nome: null })
  })
})

describe("mensagemDeEvento", () => {
  it("converte o evento SSE numa mensagem sem id do servidor", () => {
    const evento: EventoMensagemNova = {
      evento: "MensagemNova",
      lead_id: LEAD_MARIA,
      conversa_id: "c1",
      autor: "cliente",
      direcao: "entrada",
      tipo: "texto",
      texto: "Oi",
      midia_url: null,
      em: "2026-11-20T12:05:00Z",
    }
    const m = mensagemDeEvento(evento, 7)
    expect(m).toMatchObject({ id: "sse-7", autor: "cliente", texto: "Oi", criada_em: "2026-11-20T12:05:00Z" })
  })
})

describe("incorporarMensagem", () => {
  const base = [mensagem({ id: "m1", autor: "cliente", texto: "Oi" })]

  it("acrescenta mensagem nova", () => {
    const novo = incorporarMensagem(base, mensagem({ id: "sse-1", autor: "ia", texto: "Olá" }))
    expect(novo.map((m) => m.id)).toEqual(["m1", "sse-1"])
  })

  it("ignora id repetido", () => {
    expect(incorporarMensagem(base, base[0])).toBe(base)
  })

  it("eco do SSE da mensagem que o vendedor acabou de enviar não duplica", () => {
    const enviada = mensagem({ id: "real-1", autor: "vendedor", texto: "Bom dia", criada_em: "2026-11-20T12:10:00Z" })
    const comEnvio = incorporarMensagem(base, enviada)
    const eco = mensagem({ id: "sse-2", autor: "vendedor", texto: "Bom dia", criada_em: "2026-11-20T12:10:02Z" })
    expect(incorporarMensagem(comEnvio, eco)).toBe(comEnvio)
  })

  it("se o SSE chega antes da resposta do POST, a mensagem real substitui a do SSE", () => {
    const eco = mensagem({ id: "sse-2", autor: "vendedor", texto: "Bom dia", criada_em: "2026-11-20T12:10:02Z" })
    const comEco = incorporarMensagem(base, eco)
    const enviada = mensagem({ id: "real-1", autor: "vendedor", texto: "Bom dia", criada_em: "2026-11-20T12:10:00Z" })
    const final = incorporarMensagem(comEco, enviada)
    expect(final.map((m) => m.id)).toEqual(["m1", "real-1"])
  })

  it("mensagens iguais do cliente em sequência são ambas mantidas", () => {
    const a = incorporarMensagem(base, mensagem({ id: "sse-3", autor: "cliente", texto: "Oi" }))
    const b = incorporarMensagem(a, mensagem({ id: "sse-4", autor: "cliente", texto: "Oi" }))
    expect(b).toHaveLength(3)
  })

  it("mesmo texto fora da janela de tempo não é eco", () => {
    const antiga = mensagem({ id: "real-1", autor: "vendedor", texto: "ok", criada_em: "2026-11-20T12:00:00Z" })
    const nova = mensagem({ id: "sse-5", autor: "vendedor", texto: "ok", criada_em: "2026-11-20T12:30:00Z" })
    expect(incorporarMensagem([antiga], nova)).toHaveLength(2)
  })
})
