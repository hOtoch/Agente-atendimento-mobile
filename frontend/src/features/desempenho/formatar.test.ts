import { describe, expect, it } from "vitest"

import {
  TRACO,
  formatarCompacto,
  formatarDataCurta,
  formatarDecimal,
  formatarDuracao,
  formatarInteiro,
  formatarIntervalo,
  formatarPercentual,
  formatarUsd,
  formatarVariacao,
} from "./formatar"

/** Intl usa espaço sem quebra entre unidade e número; nos testes comparamos com espaço comum. */
const n = (s: string) => s.replace(/[  ]/g, " ")

describe("formatação pt-BR do desempenho", () => {
  it("inteiros usam ponto como separador de milhar", () => {
    expect(formatarInteiro(1234567)).toBe("1.234.567")
    expect(formatarInteiro(0)).toBe("0")
    expect(formatarInteiro(null)).toBe(TRACO)
  })

  it("decimais usam vírgula", () => {
    expect(formatarDecimal(4.25)).toBe("4,3")
    expect(formatarDecimal(4, 1)).toBe("4")
    expect(formatarDecimal(null)).toBe(TRACO)
  })

  it("percentuais partem de fração (0,2 = 20%) e têm no máximo 1 casa", () => {
    expect(n(formatarPercentual(0.2))).toBe("20%")
    expect(n(formatarPercentual(0.12345))).toBe("12,3%")
    expect(n(formatarPercentual(0))).toBe("0%")
    expect(formatarPercentual(null)).toBe(TRACO)
  })

  it("dólar usa 2 casas e sobe para 4 quando o valor é menor que 1", () => {
    expect(n(formatarUsd("15.3"))).toBe("US$ 15,30")
    expect(n(formatarUsd("1234.5"))).toBe("US$ 1.234,50")
    expect(n(formatarUsd("0.0123"))).toBe("US$ 0,0123")
    expect(n(formatarUsd("0"))).toBe("US$ 0,00")
    expect(formatarUsd(null)).toBe(TRACO)
  })

  it("duração converte ms em ms, s ou min", () => {
    expect(formatarDuracao(850)).toBe("850 ms")
    expect(formatarDuracao(2400)).toBe("2,4 s")
    expect(formatarDuracao(12000)).toBe("12 s")
    expect(formatarDuracao(65000)).toBe("1 min 5 s")
    expect(formatarDuracao(null)).toBe(TRACO)
  })

  it("variação mostra sinal explícito", () => {
    expect(n(formatarVariacao(12.5) ?? "")).toBe("+12,5%")
    expect(n(formatarVariacao(-3) ?? "")).toBe("-3%")
    expect(n(formatarVariacao(0) ?? "")).toBe("0%")
    expect(formatarVariacao(null)).toBeNull()
  })

  it("compacta números dos eixos a partir de mil", () => {
    expect(formatarCompacto(950)).toBe("950")
    expect(n(formatarCompacto(1200))).toBe("1,2 mil")
    expect(n(formatarCompacto(2_500_000))).toBe("2,5 mi")
  })

  it("datas curtas e intervalos em dia/mês/ano", () => {
    expect(formatarDataCurta("2026-11-05")).toBe("05/11")
    expect(formatarIntervalo("2026-10-24", "2026-11-22")).toBe("24/10/2026 a 22/11/2026")
  })
})
