import { describe, expect, it } from "vitest"

import {
  corpoParaForm,
  formatarRelatorio,
  formParaCorpo,
  rotuloMotivo,
  rotuloStatus,
  validarForm,
  type FormErp,
} from "./erp"

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

  it("traduz os motivos de descarte para português", () => {
    expect(rotuloMotivo("sem_preco")).toBe("Sem preço")
    expect(rotuloMotivo("nao_e_celular")).toBe("Não é celular")
    expect(rotuloMotivo("sku_duplicado")).toBe("SKU repetido")
    expect(rotuloMotivo("motivo_novo")).toBe("motivo_novo")
  })

  describe("formatarRelatorio", () => {
    it("sem relatório não mostra nada", () => {
      expect(formatarRelatorio(null)).toEqual({ linhas: [], erro: null })
    })

    it("formata os contadores, os descartes por motivo e a duração", () => {
      const r = formatarRelatorio({
        lidos: 2664,
        importados: 1087,
        outra_loja: 1500,
        descartados: 77,
        por_motivo: { sem_preco: 70, nao_e_celular: 7 },
        duracao_s: 21.34,
      })
      expect(r.erro).toBeNull()
      expect(r.linhas).toEqual([
        { rotulo: "Itens lidos do ERP", valor: "2.664", nivel: 0 },
        { rotulo: "Importados", valor: "1.087", nivel: 0 },
        { rotulo: "De outra loja", valor: "1.500", nivel: 0 },
        { rotulo: "Descartados", valor: "77", nivel: 0 },
        { rotulo: "Sem preço", valor: "70", nivel: 1 },
        { rotulo: "Não é celular", valor: "7", nivel: 1 },
        { rotulo: "Duração", valor: "21,3 s", nivel: 0 },
      ])
    })

    it("relatório de erro traz a mensagem e ainda mostra o que souber", () => {
      const r = formatarRelatorio({ erro: "ERP indisponível no momento: timeout", duracao_s: 15 })
      expect(r.erro).toBe("ERP indisponível no momento: timeout")
      expect(r.linhas).toEqual([{ rotulo: "Duração", valor: "15 s", nivel: 0 }])
    })

    it("ignora campos desconhecidos e tipos errados", () => {
      const r = formatarRelatorio({ lidos: "muitos", produtos: 10, por_motivo: { sem_preco: "x" } })
      expect(r).toEqual({ linhas: [], erro: null })
    })
  })
})
