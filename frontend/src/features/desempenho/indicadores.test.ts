import { describe, expect, it } from "vitest"

import { metricasCompletas, metricasVazias } from "./fixtures"
import { INDICADORES_PRINCIPAIS, semDados, tomDaVariacao } from "./indicadores"

describe("tomDaVariacao", () => {
  it("maior-melhor: alta é boa, queda é ruim", () => {
    expect(tomDaVariacao("maior-melhor", 10)).toBe("bom")
    expect(tomDaVariacao("maior-melhor", -10)).toBe("ruim")
  })

  it("menor-melhor: custo subindo não é bom", () => {
    expect(tomDaVariacao("menor-melhor", 10)).toBe("ruim")
    expect(tomDaVariacao("menor-melhor", -10)).toBe("bom")
  })

  it("neutro, estável ou sem comparação nunca ganham cor de bom/ruim", () => {
    expect(tomDaVariacao("neutro", 50)).toBe("neutro")
    expect(tomDaVariacao("maior-melhor", 0)).toBe("neutro")
    expect(tomDaVariacao("menor-melhor", null)).toBe("neutro")
  })
})

describe("indicadores principais", () => {
  it("são os 8 pedidos, na ordem", () => {
    expect(INDICADORES_PRINCIPAIS.map((i) => i.rotulo)).toEqual([
      "Conversas atendidas",
      "Acordos fechados",
      "Taxa de conversão",
      "Gasto com a IA",
      "Custo por conversa",
      "Tempo médio de resposta",
      "Passadas ao vendedor",
      "Erros",
    ])
  })

  it("todas as chaves existem nos KPIs da API", () => {
    const { kpis } = metricasCompletas()
    for (const i of INDICADORES_PRINCIPAIS) expect(kpis[i.chave]).toBeDefined()
  })
})

describe("semDados", () => {
  it("é verdadeiro sem conversas, mensagens nem chamadas à IA", () => {
    expect(semDados(metricasVazias())).toBe(true)
  })

  it("é falso havendo atividade no período", () => {
    expect(semDados(metricasCompletas())).toBe(false)
  })
})
