import { describe, expect, it } from "vitest"

import { formParaCorpo, corpoParaForm, validarForm, type FormFollowup } from "./followup"

const CORPO = {
  ligado: true,
  horas_por_etapa: { interesse_qualificado: 2, interesse_identificado: 24 },
  max_tentativas: 3,
  intervalo_horas: 12,
  hora_inicio: "09:00",
  hora_fim: "18:00",
  max_dias_parado: 7,
}

describe("follow-up: conversão API <-> formulário", () => {
  it("converte o corpo da API em campos de texto, com etapa vazia quando não configurada", () => {
    const f = corpoParaForm(CORPO)
    expect(f.ligado).toBe("sim")
    expect(f.horas.interesse_qualificado).toBe("2")
    expect(f.horas.interesse_identificado).toBe("24")
    expect(f.horas.novo_contato).toBe("")
    expect(f.max_tentativas).toBe("3")
    expect(f.hora_inicio).toBe("09:00")
  })

  it("ida e volta preserva os valores e descarta etapas vazias", () => {
    expect(formParaCorpo(corpoParaForm(CORPO))).toEqual(CORPO)
  })

  it("normaliza horário com segundos vindo da API", () => {
    const f = corpoParaForm({ ...CORPO, hora_inicio: "09:00:00", hora_fim: "18:30:00" })
    expect([f.hora_inicio, f.hora_fim]).toEqual(["09:00", "18:30"])
  })
})

function form(parcial: Partial<FormFollowup> = {}): FormFollowup {
  return { ...corpoParaForm(CORPO), ...parcial }
}

describe("follow-up: validação no cliente", () => {
  it("formulário correto não tem erros", () => {
    expect(validarForm(form())).toEqual({})
  })

  it.each([
    ["max_tentativas", { max_tentativas: "0" }],
    ["max_tentativas", { max_tentativas: "6" }],
    ["max_tentativas", { max_tentativas: "" }],
    ["intervalo_horas", { intervalo_horas: "0" }],
    ["max_dias_parado", { max_dias_parado: "-1" }],
    ["hora_inicio", { hora_inicio: "19:00" }],
    ["hora_inicio", { hora_inicio: "" }],
  ] as const)("recusa %s inválido", (campo, parcial) => {
    expect(validarForm(form(parcial))[campo]).toBeTruthy()
  })

  it("exige ao menos uma etapa com horas quando ligado", () => {
    const vazio = form({ horas: { novo_contato: "", interesse_identificado: "", interesse_qualificado: "" } })
    expect(validarForm(vazio).horas_por_etapa).toBeTruthy()
    expect(validarForm({ ...vazio, ligado: "nao" }).horas_por_etapa).toBeUndefined()
  })

  it("recusa horas fracionadas ou menores que 1", () => {
    expect(validarForm(form({ horas: { ...form().horas, interesse_qualificado: "0" } })).horas_por_etapa).toBeTruthy()
    expect(validarForm(form({ horas: { ...form().horas, interesse_qualificado: "1.5" } })).horas_por_etapa).toBeTruthy()
  })
})
