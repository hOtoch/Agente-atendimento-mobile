import { describe, expect, it } from "vitest"

import type { EventoPainel } from "@/lib/api"

import { CARD_A, CARD_B, CARD_C, LEAD_A, LEAD_B, VENDEDOR_ANA, card, colunas } from "./fixtures"
import {
  aplicarEvento,
  filtrarColunas,
  formatarValor,
  moverCard,
  opcoesDeVendedor,
  restaurarCard,
  tempoNaEtapa,
  validarMovimento,
} from "./regras"

const base = () => colunas([CARD_A, CARD_B, CARD_C])
const idsDa = (cols: ReturnType<typeof base>, etapa: string) =>
  cols.find((c) => c.etapa === etapa)?.leads.map((l) => l.id) ?? []

describe("validarMovimento", () => {
  it("permite mover para outra etapa", () => {
    expect(validarMovimento("novo_contato", "com_o_vendedor")).toEqual({ permitido: true })
    expect(validarMovimento("interesse_qualificado", "novo_contato")).toEqual({ permitido: true })
  })

  it("soltar na mesma coluna é no-op, sem aviso", () => {
    expect(validarMovimento("novo_contato", "novo_contato")).toMatchObject({ permitido: false, noop: true })
  })

  it("venda fechada é final", () => {
    expect(validarMovimento("venda_fechada", "novo_contato")).toMatchObject({
      permitido: false,
      noop: false,
      motivo: "Venda fechada é uma etapa final.",
    })
  })
})

describe("moverCard / restaurarCard", () => {
  it("move o card para o topo da coluna destino e atualiza etapa e etapa_desde", () => {
    const novo = moverCard(base(), LEAD_A, "com_o_vendedor", "2026-11-20T12:00:00Z")
    expect(idsDa(novo, "novo_contato")).toEqual([])
    expect(idsDa(novo, "com_o_vendedor")).toEqual([LEAD_A])
    const movido = novo.find((c) => c.etapa === "com_o_vendedor")?.leads[0]
    expect(movido).toMatchObject({ etapa: "com_o_vendedor", etapa_desde: "2026-11-20T12:00:00Z" })
  })

  it("não muta o estado anterior", () => {
    const antes = base()
    moverCard(antes, LEAD_A, "com_o_vendedor", "2026-11-20T12:00:00Z")
    expect(idsDa(antes, "novo_contato")).toEqual([LEAD_A])
  })

  it("restaurarCard devolve o card original à posição de origem", () => {
    const antes = colunas([CARD_A, card({ id: "x", etapa: "novo_contato" })])
    const movido = moverCard(antes, LEAD_A, "venda_fechada", "2026-11-20T12:00:00Z")
    const volta = restaurarCard(movido, CARD_A, 0)
    expect(idsDa(volta, "novo_contato")).toEqual([LEAD_A, "x"])
    expect(idsDa(volta, "venda_fechada")).toEqual([])
    expect(volta[0].leads[0].etapa_desde).toBe(CARD_A.etapa_desde)
  })
})

describe("aplicarEvento", () => {
  const etapaMudou = (lead_id: string, para: "com_o_vendedor") =>
    ({
      evento: "EtapaMudou",
      lead_id,
      de: "novo_contato",
      para,
      ator: "ia",
      motivo: "x",
      em: "2026-11-20T12:30:00Z",
    }) as EventoPainel

  it("EtapaMudou move o card conhecido", () => {
    const { colunas: novo, recarregar } = aplicarEvento(base(), etapaMudou(LEAD_A, "com_o_vendedor"))
    expect(recarregar).toBe(false)
    expect(idsDa(novo, "com_o_vendedor")).toEqual([LEAD_A])
    expect(novo.find((c) => c.etapa === "com_o_vendedor")?.leads[0].etapa_desde).toBe("2026-11-20T12:30:00Z")
  })

  it("EtapaMudou para a etapa em que o card já está é idempotente", () => {
    const inicial = moverCard(base(), LEAD_A, "com_o_vendedor", "2026-11-20T12:00:00Z")
    const { colunas: novo, recarregar } = aplicarEvento(inicial, etapaMudou(LEAD_A, "com_o_vendedor"))
    expect(recarregar).toBe(false)
    expect(novo).toBe(inicial)
  })

  it("lead desconhecido pede recarga (EtapaMudou e MensagemNova)", () => {
    expect(aplicarEvento(base(), etapaMudou("zzz", "com_o_vendedor")).recarregar).toBe(true)
    const msg = { evento: "MensagemNova", lead_id: "zzz" } as unknown as EventoPainel
    expect(aplicarEvento(base(), msg).recarregar).toBe(true)
  })

  it("MensagemNova de lead conhecido não muda nada", () => {
    const inicial = base()
    const msg = { evento: "MensagemNova", lead_id: LEAD_A } as unknown as EventoPainel
    expect(aplicarEvento(inicial, msg)).toEqual({ colunas: inicial, recarregar: false })
  })

  it("DonoMudou atualiza o dono; devolver à IA limpa o vendedor", () => {
    const evento = {
      evento: "DonoMudou",
      lead_id: LEAD_B,
      dono: "ia",
      vendedor_id: null,
      em: "2026-11-20T12:30:00Z",
    } as EventoPainel
    const { colunas: novo, recarregar } = aplicarEvento(base(), evento)
    expect(recarregar).toBe(false)
    const b = novo.flatMap((c) => c.leads).find((l) => l.id === LEAD_B)
    expect(b).toMatchObject({ dono: "ia", vendedor_id: null, vendedor_nome: null })
  })

  it("DonoMudou para vendedor já conhecido reaproveita o nome; desconhecido pede recarga", () => {
    const conhecido = {
      evento: "DonoMudou",
      lead_id: LEAD_A,
      dono: `vendedor:${VENDEDOR_ANA}`,
      vendedor_id: VENDEDOR_ANA,
      em: "2026-11-20T12:30:00Z",
    } as EventoPainel
    const r1 = aplicarEvento(base(), conhecido)
    const a = r1.colunas.flatMap((c) => c.leads).find((l) => l.id === LEAD_A)
    expect(a).toMatchObject({ vendedor_id: VENDEDOR_ANA, vendedor_nome: "Ana Paula" })
    expect(r1.recarregar).toBe(false)

    const desconhecido = { ...conhecido, dono: "vendedor:novo", vendedor_id: "novo" } as EventoPainel
    expect(aplicarEvento(base(), desconhecido).recarregar).toBe(true)
  })
})

describe("filtro por vendedor", () => {
  it("opções: Todos, IA e cada vendedor presente nos cards", () => {
    expect(opcoesDeVendedor(base())).toEqual([
      { valor: "todos", rotulo: "Todos" },
      { valor: "ia", rotulo: "IA" },
      { valor: VENDEDOR_ANA, rotulo: "Ana Paula" },
    ])
  })

  it("filtra por IA, por vendedor e mantém as 5 colunas", () => {
    const ia = filtrarColunas(base(), "ia")
    expect(ia).toHaveLength(5)
    expect(ia.flatMap((c) => c.leads.map((l) => l.id)).sort()).toEqual(
      [CARD_A.id, CARD_C.id].sort(),
    )
    const ana = filtrarColunas(base(), VENDEDOR_ANA)
    expect(ana.flatMap((c) => c.leads.map((l) => l.id))).toEqual([LEAD_B])
    expect(filtrarColunas(base(), "todos").flatMap((c) => c.leads)).toHaveLength(3)
  })
})

describe("formatação", () => {
  const agora = new Date("2026-11-20T12:00:00Z")
  it("tempo na etapa em pt-BR curto", () => {
    expect(tempoNaEtapa("2026-11-20T11:59:40Z", agora)).toBe("agora")
    expect(tempoNaEtapa("2026-11-20T11:55:00Z", agora)).toBe("há 5 min")
    expect(tempoNaEtapa("2026-11-20T09:00:00Z", agora)).toBe("há 3 h")
    expect(tempoNaEtapa("2026-11-17T12:00:00Z", agora)).toBe("há 3 d")
    expect(tempoNaEtapa("2026-11-20T12:05:00Z", agora)).toBe("agora")
  })

  it("valor em BRL; nulo vira null", () => {
    expect(formatarValor("3499.90")).toMatch(/^R\$\s3\.499,90$/)
    expect(formatarValor(null)).toBeNull()
  })
})
