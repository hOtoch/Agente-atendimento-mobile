import { describe, expect, it } from "vitest"

import {
  linhasParaTaxas,
  linhasParaTroca,
  linhasParaVendedores,
  somaPercentuais,
  taxasParaLinhas,
  trocaParaLinhas,
  vendedoresParaLinhas,
} from "./conversores"

describe("vendedores", () => {
  it("mostra só os ativos, com o peso como número", () => {
    const linhas = vendedoresParaLinhas([
      { id: "a", nome: "Ana", telefone: null, peso_percentual: "60.00", ativo: true },
      { id: "b", nome: "Bruno", telefone: "+55 11 90000-0002", peso_percentual: "40.00", ativo: false },
    ])
    expect(linhas).toEqual([
      { id: "a", nome: "Ana", telefone: "", peso_percentual: 60 },
    ])
  })

  it("serializa mantendo o id dos existentes e sem id nos novos", () => {
    const corpo = linhasParaVendedores([
      { id: "a", nome: " Ana ", telefone: "", peso_percentual: 60 },
      { id: null, nome: "Bruno", telefone: "+55 11 90000-0002", peso_percentual: 40 },
    ])
    expect(corpo).toEqual({
      vendedores: [
        { id: "a", nome: "Ana", telefone: null, peso_percentual: 60, ativo: true },
        { id: null, nome: "Bruno", telefone: "+55 11 90000-0002", peso_percentual: 40, ativo: true },
      ],
    })
  })

  it("soma os percentuais sem erro de ponto flutuante", () => {
    expect(
      somaPercentuais([{ peso_percentual: 33.3 }, { peso_percentual: 33.3 }, { peso_percentual: 33.4 }]),
    ).toBe(100)
    expect(somaPercentuais([{ peso_percentual: 0.1 }, { peso_percentual: 0.2 }])).toBe(0.3)
    expect(somaPercentuais([{ peso_percentual: null }, { peso_percentual: 50 }])).toBe(50)
    expect(somaPercentuais([])).toBe(0)
  })
})

describe("taxas", () => {
  it("monta uma linha por parcela, com 'igual' para taxa nula", () => {
    const linhas = taxasParaLinhas([
      { chave: 2, bandeira: "mastercard", taxa_pct: "4.50" },
      { chave: 1, bandeira: "mastercard", taxa_pct: "3.10" },
      { chave: 1, bandeira: "visa", taxa_pct: null },
      { chave: "debito", bandeira: "mastercard", taxa_pct: "1.20" },
    ])
    expect(linhas.map((l) => l.chave)).toEqual(["1", "2", "debito"])
    expect(linhas[0]).toMatchObject({ mastercard: "3,1", visa: "igual", elo: "" })
  })

  it("sem taxas salvas, devolve as parcelas 1 a 21 e débito vazias", () => {
    const linhas = taxasParaLinhas([])
    expect(linhas).toHaveLength(22)
    expect(linhas[0].chave).toBe("1")
    expect(linhas[21].chave).toBe("debito")
  })

  it("serializa só as células preenchidas e guarda a origem de cada item", () => {
    const { taxas, origens } = linhasParaTaxas([
      { chave: "1", mastercard: "3,1", visa: "igual", elo: "", hipercard: "", amex: "" },
      { chave: "2", mastercard: "", visa: "", elo: "5", hipercard: "", amex: "" },
    ])
    expect(taxas).toEqual({
      taxas: [
        { chave: 1, bandeira: "mastercard", taxa_pct: 3.1 },
        { chave: 1, bandeira: "visa", taxa_pct: null },
        { chave: 2, bandeira: "elo", taxa_pct: 5 },
      ],
    })
    expect(origens).toEqual([
      { linha: 0, coluna: "mastercard" },
      { linha: 0, coluna: "visa" },
      { linha: 1, coluna: "elo" },
    ])
  })

  it("chave 'debito' vai como texto; texto inválido na taxa segue para a API validar", () => {
    const { taxas } = linhasParaTaxas([
      { chave: "debito", mastercard: "abc", visa: "", elo: "", hipercard: "", amex: "" },
    ])
    expect(taxas.taxas).toEqual([{ chave: "debito", bandeira: "mastercard", taxa_pct: "abc" }])
  })
})

describe("tabela de troca", () => {
  const api = {
    marca: "Apple",
    modelo: "iPhone 16",
    capacidade_gb: 128,
    valor_sem_detalhes: "3100.00",
    desconto_tela: "600.00",
    desconto_tela_sem: false,
    desconto_traseira: null,
    desconto_traseira_sem: true,
    desconto_carcaca: "0.00",
    desconto_carcaca_sem: false,
    desconto_bateria: "190.00",
    desconto_bateria_sem: false,
    limite_bateria_pct: 80,
  }

  it("mostra SEM como texto e valores como número", () => {
    const [linha] = trocaParaLinhas([api])
    expect(linha).toMatchObject({
      marca: "Apple",
      modelo: "iPhone 16",
      capacidade_gb: 128,
      valor_sem_detalhes: 3100,
      desconto_tela: "600",
      desconto_traseira: "SEM",
      desconto_carcaca: "0",
      limite_bateria_pct: 80,
    })
  })

  it("serializa de volta (ida e volta) com os campos _sem", () => {
    const corpo = linhasParaTroca(trocaParaLinhas([api]))
    expect(corpo.tabela_troca[0]).toMatchObject({
      desconto_tela: 600,
      desconto_tela_sem: false,
      desconto_traseira: null,
      desconto_traseira_sem: true,
      desconto_carcaca: 0,
      desconto_bateria: 190,
    })
  })

  it("aceita vírgula decimal e sem em minúsculas", () => {
    const [linha] = trocaParaLinhas([api])
    const corpo = linhasParaTroca([
      { ...linha, desconto_tela: "600,50", desconto_bateria: "sem" },
    ])
    expect(corpo.tabela_troca[0]).toMatchObject({
      desconto_tela: 600.5,
      desconto_bateria: null,
      desconto_bateria_sem: true,
    })
  })

  it("célula vazia vai nula e sem marcar SEM (a API reclama na célula)", () => {
    const [linha] = trocaParaLinhas([api])
    const corpo = linhasParaTroca([{ ...linha, desconto_tela: "" }])
    expect(corpo.tabela_troca[0]).toMatchObject({ desconto_tela: null, desconto_tela_sem: false })
  })
})
