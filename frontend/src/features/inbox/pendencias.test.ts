import { describe, expect, it } from "vitest"

import { rotuloPendencia, rotulosDasPendencias } from "./pendencias"

describe("rotuloPendencia", () => {
  it("traduz os códigos do domínio para pt-BR", () => {
    expect(rotuloPendencia("estoque_confirmado")).toBe("Confirmar o item no estoque")
    expect(rotuloPendencia("usado_bateria")).toBe("Saúde da bateria do usado")
    expect(rotuloPendencia("pagamento_parcelas")).toBe("Número de parcelas")
  })

  it("cobre todas as pendências da ficha do backend", () => {
    const codigos = [
      "aparelho_modelo", "aparelho_capacidade", "estoque_confirmado", "tem_troca", "usado_modelo",
      "usado_capacidade", "usado_tela", "usado_traseira", "usado_carcaca", "usado_bateria",
      "usado_camera", "usado_outros_defeitos", "usado_peca_trocada", "data_compra",
      "pagamento_tipo", "pagamento_parcelas", "pagamento_bandeira", "pagamento_entrada",
    ]
    for (const codigo of codigos) {
      expect(rotuloPendencia(codigo)).not.toMatch(/_/)
    }
  })

  it("não quebra com código desconhecido", () => {
    expect(rotuloPendencia("algo_novo")).toBe("Algo novo")
  })

  it("mapeia a lista inteira", () => {
    expect(rotulosDasPendencias(["tem_troca", "data_compra"])).toEqual([
      "Saber se há aparelho para troca",
      "Data prevista da compra",
    ])
  })
})
