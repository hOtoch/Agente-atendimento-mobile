import { describe, expect, it } from "vitest"

import { DETALHE_MARIA, MENSAGENS_MARIA, detalhe, CARD_MARIA } from "./fixtures"
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
    expect(r.motivo).toBe("A IA ficou indisponível e passou a conversa para o vendedor")
  })
})
