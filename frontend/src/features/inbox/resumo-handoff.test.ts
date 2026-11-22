import { describe, expect, it } from "vitest"

import { DETALHE_MARIA, MENSAGENS_MARIA, RESUMO_API, detalhe, CARD_MARIA } from "./fixtures"
import { montarResumoHandoff } from "./resumo-handoff"

describe("montarResumoHandoff", () => {
  it("monta aparelho, troca, pagamento, próximo passo e motivo", () => {
    const r = montarResumoHandoff({
      ...DETALHE_MARIA,
      motivo_handoff: "Cliente quer negociar valor da troca",
    })
    expect(r.motivo).toBe("Cliente quer negociar valor da troca")
    expect(r.aparelho).toBe("iPhone 13 · 128 GB · Azul")
    expect(r.troca).toBe("iPhone 11 · 64 GB (tela danificada, bateria 82%)")
    expect(r.pagamento).toBe("Crédito em 10x · Visa")
    expect(r.proximoPasso).toBe("Confirmar o item no estoque")
    expect(r.pendencias).toEqual(["Confirmar o item no estoque", "Câmera do usado", "Bandeira do cartão"])
    expect(r.ultimasMensagens).toHaveLength(3)
  })

  it("limita às últimas 3 mensagens e descreve mídia", () => {
    const muitas = [
      ...MENSAGENS_MARIA,
      { ...MENSAGENS_MARIA[0], id: "m4", texto: "Pode ser 10x?" },
      { ...MENSAGENS_MARIA[0], id: "m5", tipo: "imagem" as const, texto: null, midia_url: "http://x/i.png" },
    ]
    const r = montarResumoHandoff({ ...DETALHE_MARIA, mensagens: muitas })
    expect(r.ultimasMensagens.map((m) => m.texto)).toEqual(["[Áudio]", "Pode ser 10x?", "[Imagem]"])
    expect(r.ultimasMensagens[1].autor).toBe("Cliente")
  })

  it("sem pendências o próximo passo é passar ao fechamento; sem motivo, usa texto padrão", () => {
    const r = montarResumoHandoff(detalhe({ card: CARD_MARIA, handoff_solicitado: true }))
    expect(r.proximoPasso).toBe("Fechar a venda com o cliente")
    expect(r.motivo).toBe("Atendimento transferido para o vendedor")
  })

  it("motivo em código do sistema vira texto legível", () => {
    const r = montarResumoHandoff(detalhe({ card: CARD_MARIA, handoff_solicitado: true, motivo_handoff: "falha_llm" }))
    expect(r.motivo).toBe("A IA teve uma falha técnica e passou o atendimento para você")
  })

  describe("com o resumo vindo da API", () => {
    const comResumo = { ...DETALHE_MARIA, handoff_solicitado: true, resumo_handoff: RESUMO_API }

    it("usa os campos estruturados e as observações do resumo da API", () => {
      const r = montarResumoHandoff(comResumo)
      expect(r.motivo).toBe("Cliente quer fechar a compra")
      expect(r.aparelho).toBe("iPhone 16 128GB")
      expect(r.troca).toContain("iPhone 13 128GB")
      expect(r.troca).toContain("R$")
      expect(r.pagamento).toBe("crédito, 12x, bandeira mastercard")
      expect(r.proposta).toContain("Cartão de crédito em 12x Mastercard")
      expect(r.observacoes).toBe("Cliente decidido, quer parcelar e fechar ainda hoje.")
      expect(r.pendencias).toEqual(["bandeira do cartão"])
      expect(r.proximoPasso).toBe("bandeira do cartão")
      expect(r.ultimasMensagens).toHaveLength(3)
    })

    it("campos nulos viram 'Não informado' e observações ausentes ficam null", () => {
      const r = montarResumoHandoff({
        ...comResumo,
        resumo_handoff: {
          ...RESUMO_API,
          aparelho_desejado: null,
          troca: null,
          valor_troca: null,
          forma_pagamento: null,
          proposta: null,
          valor_proposta: null,
          observacoes: null,
          pendencias: [],
        },
      })
      expect(r.aparelho).toBe("Não informado")
      expect(r.troca).toBe("Não informado")
      expect(r.pagamento).toBe("Não informado")
      expect(r.proposta).toBeNull()
      expect(r.observacoes).toBeNull()
      expect(r.proximoPasso).toBe("Fechar a venda com o cliente")
    })

    it("resumo completo sem o LLM: cor, SKU, condição da troca, valores, parcelas e data", () => {
      const r = montarResumoHandoff({
        ...comResumo,
        resumo_handoff: {
          ...RESUMO_API,
          motivo: "A IA teve uma falha técnica e passou o atendimento para você. O cliente estava em Novo contato; falta: modelo.",
          observacoes: null,
          cor: "Preto",
          sku: "IP16-128-PT",
          troca_condicao: "tela danificada, bateria 82%",
          troca_status: "avaliada",
          valor_aparelho: "4830.00",
          desconto: "130.00",
          parcelas: 12,
          valor_parcela: "325.00",
          ultimas_mensagens_cliente: ["quero o iphone 16"],
        },
      })
      expect(r.motivo).toContain("falha técnica")
      expect(r.aparelho).toBe("iPhone 16 128GB, Preto (SKU IP16-128-PT)")
      expect(r.troca).toContain("iPhone 13 128GB (tela danificada, bateria 82%)")
      expect(r.troca).toContain("avaliada em")
      expect(r.proposta).toContain("12x de")
      expect(r.valores).toContain("aparelho")
      expect(r.valores).toContain("desconto")
      expect(r.dataPrevista).toBe("25/11/2026")
      expect(r.observacoes).toBeNull()
    })

    it("troca avaliada na loja não mostra valor", () => {
      const r = montarResumoHandoff({
        ...comResumo,
        resumo_handoff: { ...RESUMO_API, valor_troca: null, troca_status: "avaliacao_na_loja" },
      })
      expect(r.troca).toContain("avaliação na loja")
      expect(r.troca).not.toContain("R$")
    })

    it("resumo antigo (sem os campos novos) continua legível", () => {
      const r = montarResumoHandoff(comResumo)
      expect(r.aparelho).toBe("iPhone 16 128GB")
      expect(r.valores).toBeNull()
    })

    it("sem resumo da API mantém o resumo local, sem observações", () => {
      const r = montarResumoHandoff({ ...DETALHE_MARIA, resumo_handoff: null })
      expect(r.aparelho).toBe("iPhone 13 · 128 GB · Azul")
      expect(r.observacoes).toBeNull()
      expect(r.proposta).toBeNull()
    })
  })
})
