import { describe, expect, it } from "vitest"

import { descreverFicha, descreverProposta } from "./ficha"
import { FICHA_PARCIAL, PROPOSTA } from "./fixtures"

const brl = (s: string) => s.replace(/\s/g, " ")

describe("descreverFicha", () => {
  it("resume aparelho, troca, data e pagamento", () => {
    const f = descreverFicha(FICHA_PARCIAL)
    expect(f.aparelho).toBe("iPhone 13 · 128 GB · Azul")
    expect(f.troca).toBe("iPhone 11 · 64 GB (tela danificada, bateria 82%)")
    expect(f.dataPrevista).toBe("05/12/2026")
    expect(f.pagamento).toBe("Crédito em 10x · Visa")
  })

  it("ficha vazia vira 'Não informado'", () => {
    const f = descreverFicha({})
    expect(f).toEqual({
      aparelho: "Não informado",
      troca: "Não informado",
      dataPrevista: "Não informado",
      pagamento: "Não informado",
    })
  })

  it("sem troca", () => {
    expect(descreverFicha({ tem_troca: false }).troca).toBe("Sem troca")
  })

  it("pagamento com entrada", () => {
    const f = descreverFicha({
      pagamento: { tipo: "entrada_mais_credito", parcelas: 6, bandeira: "elo", entrada: "500.00" },
    })
    expect(brl(f.pagamento)).toBe("Entrada de R$ 500,00 + crédito em 6x · Elo")
  })

  it("pix e débito", () => {
    expect(descreverFicha({ pagamento: { tipo: "pix" } }).pagamento).toBe("Pix ou dinheiro")
    expect(descreverFicha({ pagamento: { tipo: "debito", bandeira: "mastercard" } }).pagamento).toBe(
      "Débito · Mastercard",
    )
  })

  it("capacidade em TB", () => {
    expect(descreverFicha({ interesse: { modelo: { nome: "iPhone 15 Pro" }, capacidade: 1024 } }).aparelho).toBe(
      "iPhone 15 Pro · 1 TB",
    )
  })

  it("troca sem defeitos informados", () => {
    const f = descreverFicha({
      tem_troca: true,
      usado: {
        modelo: { nome: "iPhone 12" },
        capacidade: 128,
        tela_danificada: false,
        traseira_danificada: false,
        carcaca_marcada: false,
        outros_defeitos: [],
      },
    })
    expect(f.troca).toBe("iPhone 12 · 128 GB (sem problemas informados)")
  })

  it("ignora dados malformados", () => {
    expect(descreverFicha({ interesse: "x", pagamento: 3 }).aparelho).toBe("Não informado")
  })
})

describe("descreverProposta", () => {
  it("devolve null sem proposta", () => {
    expect(descreverProposta(null)).toBeNull()
    expect(descreverProposta({ bloqueado: true })).toBeNull()
  })

  it("formata os valores em BRL", () => {
    const p = descreverProposta(PROPOSTA)
    expect(p).not.toBeNull()
    expect(brl(p!.precoAparelho)).toBe("R$ 3.499,90")
    expect(brl(p!.troca!)).toBe("R$ 800,00")
    expect(brl(p!.desconto!)).toBe("R$ 100,00")
    expect(p!.forma).toBe("Cartão de crédito em 10x Visa")
    expect(brl(p!.parcela!)).toBe("10x de R$ 270,00")
    expect(brl(p!.total)).toBe("R$ 2.699,90")
  })

  it("à vista e troca avaliada na loja", () => {
    const p = descreverProposta({
      preco_aparelho: "3000",
      troca: { status: "avaliacao_na_loja" },
      desconto: { total: "0" },
      forma_escolhida: { rotulo: "Pix ou dinheiro à vista", valor_a_vista: "3000.00" },
    })
    expect(p!.troca).toBe("Avaliação na loja")
    expect(p!.desconto).toBeNull()
    expect(p!.parcela).toBeNull()
    expect(brl(p!.total)).toBe("R$ 3.000,00")
  })

  it("sem troca", () => {
    const p = descreverProposta({
      preco_aparelho: "3000",
      troca: { status: "sem_troca" },
      forma_escolhida: { rotulo: "Pix", valor_a_vista: "3000" },
    })
    expect(p!.troca).toBeNull()
  })
})
