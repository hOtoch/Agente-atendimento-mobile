import { describe, expect, it } from "vitest"

import { corpoParaForm, formParaCorpo, rotuloStatus, validarForm, type FormErp } from "./erp"

const SAIDA = {
  configurada: true,
  provedor: "mercadophone",
  system_unit_id: 12,
  filtro_loja: "Centro",
  ativo: true,
  intervalo_min: 30,
  exportar_handoff: true,
  ultima_sincronizacao_em: null,
  ultimo_status: null,
  ultimo_relatorio: null,
}

const VAZIA = { ...SAIDA, configurada: false, system_unit_id: null, filtro_loja: null, ativo: false, intervalo_min: 15, exportar_handoff: false }

describe("erp", () => {
  it("converte a resposta da API em formulário e de volta", () => {
    const form = corpoParaForm(SAIDA)
    expect(form).toEqual({
      system_unit_id: "12",
      filtro_loja: "Centro",
      ativo: true,
      intervalo_min: "30",
      exportar_handoff: true,
    })
    expect(formParaCorpo(form)).toEqual({
      system_unit_id: 12,
      filtro_loja: "Centro",
      ativo: true,
      intervalo_min: 30,
      exportar_handoff: true,
    })
  })

  it("loja sem conexão vira formulário vazio com o intervalo padrão", () => {
    expect(corpoParaForm(VAZIA)).toEqual({
      system_unit_id: "",
      filtro_loja: "",
      ativo: false,
      intervalo_min: "15",
      exportar_handoff: false,
    })
  })

  it("filtro vazio vai como null", () => {
    const form: FormErp = { ...corpoParaForm(SAIDA), filtro_loja: "   " }
    expect(formParaCorpo(form).filtro_loja).toBeNull()
  })

  it("valida a unidade (> 0) e o intervalo (5 a 1440)", () => {
    const base = corpoParaForm(SAIDA)
    expect(validarForm(base)).toEqual({})
    expect(validarForm({ ...base, system_unit_id: "" }).system_unit_id).toBeDefined()
    expect(validarForm({ ...base, system_unit_id: "0" }).system_unit_id).toBeDefined()
    expect(validarForm({ ...base, system_unit_id: "1,5" }).system_unit_id).toBeDefined()
    expect(validarForm({ ...base, intervalo_min: "4" }).intervalo_min).toMatch(/entre 5 e 1440/)
    expect(validarForm({ ...base, intervalo_min: "1441" }).intervalo_min).toBeDefined()
    expect(validarForm({ ...base, intervalo_min: "5" })).toEqual({})
    expect(validarForm({ ...base, intervalo_min: "1440" })).toEqual({})
  })

  it("traduz o status da sincronização", () => {
    expect(rotuloStatus("ok")).toBe("Sincronizada")
    expect(rotuloStatus("parcial")).toBe("Sincronizada com avisos")
    expect(rotuloStatus("erro")).toBe("Falhou")
    expect(rotuloStatus("outro")).toBe("outro")
  })
})
