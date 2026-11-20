import { describe, expect, it } from "vitest"

import { descreverErroImportacao, lerCaminhoApi, lerCelulaPlanilha } from "./erros"

describe("lerCaminhoApi (caminho de erro da API -> linha/coluna da grade)", () => {
  it("separa lista, índice 0-based e campo", () => {
    expect(lerCaminhoApi("tabela_troca[3].desconto_tela")).toEqual({
      lista: "tabela_troca",
      indice: 3,
      campo: "desconto_tela",
    })
  })

  it("aceita erro de linha inteira (sem campo)", () => {
    expect(lerCaminhoApi("estoque[0]")).toEqual({ lista: "estoque", indice: 0, campo: null })
  })

  it("devolve null para erro que não aponta para uma linha", () => {
    expect(lerCaminhoApi("vendedores")).toBeNull()
    expect(lerCaminhoApi("max_parcelas")).toBeNull()
  })
})

describe("lerCelulaPlanilha (formato aba!D7 da importação)", () => {
  it("traduz a letra da coluna na chave da coluna da grade e a linha em índice", () => {
    expect(lerCelulaPlanilha("troca!D7")).toMatchObject({
      aba: "troca",
      celula: "D7",
      linha: 7,
      indice: 5,
      colunaKey: "desconto_tela",
      colunaRotulo: "Desconto tela",
    })
  })

  it("na aba de outras marcas a primeira coluna é a marca", () => {
    expect(lerCelulaPlanilha("outras_marcas!A2")).toMatchObject({
      colunaKey: "marca",
      indice: 0,
    })
    expect(lerCelulaPlanilha("outras_marcas!C3")).toMatchObject({ colunaKey: "capacidade_gb" })
  })

  it("estoque e taxas", () => {
    expect(lerCelulaPlanilha("estoque!F4")).toMatchObject({ colunaKey: "preco_pix", indice: 2 })
    expect(lerCelulaPlanilha("taxas!C5")).toMatchObject({ colunaKey: "visa" })
    expect(lerCelulaPlanilha("taxas!A5")).toMatchObject({ colunaKey: "chave" })
  })

  it("regras de preço não têm coluna de grade", () => {
    expect(lerCelulaPlanilha("regras!B3")).toMatchObject({ aba: "regras", colunaKey: null })
  })

  it("devolve null quando não é uma referência de célula", () => {
    expect(lerCelulaPlanilha("arquivo")).toBeNull()
    expect(lerCelulaPlanilha("troca")).toBeNull()
  })
})

describe("descreverErroImportacao", () => {
  it("mostra aba, linha, coluna e a mensagem", () => {
    const texto = descreverErroImportacao({
      caminho: "troca!D7",
      mensagem: "Desconto maior que o valor base.",
    })
    expect(texto).toContain("Tabela de troca")
    expect(texto).toContain("linha 7")
    expect(texto).toContain("Desconto tela")
    expect(texto).toContain("D7")
    expect(texto).toContain("Desconto maior que o valor base.")
  })

  it("erro sem célula mostra só a mensagem", () => {
    expect(descreverErroImportacao({ caminho: "arquivo", mensagem: "Arquivo inválido." })).toBe(
      "Arquivo inválido.",
    )
  })
})
