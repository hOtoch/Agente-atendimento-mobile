import type { components } from "@/lib/api/schema"

export type ConexaoErp = components["schemas"]["ConexaoErpSaida"]
export type CorpoErp = components["schemas"]["ConexaoErpEntrada"]

export const INTERVALO_MINIMO = 5
export const INTERVALO_MAXIMO = 1440
export const INTERVALO_PADRAO = 15

export type FormErp = {
  system_unit_id: string
  filtro_loja: string
  ativo: boolean
  intervalo_min: string
  exportar_handoff: boolean
}

export type ErrosErp = Partial<Record<"system_unit_id" | "filtro_loja" | "intervalo_min", string>>

export function corpoParaForm(c: ConexaoErp): FormErp {
  return {
    system_unit_id: c.system_unit_id === null ? "" : String(c.system_unit_id),
    filtro_loja: c.filtro_loja ?? "",
    ativo: c.ativo,
    intervalo_min: String(c.intervalo_min),
    exportar_handoff: c.exportar_handoff,
  }
}

/** Inteiro positivo ou `null` (vazio, fracionado, negativo, zero ou lixo). */
function inteiro(texto: string): number | null {
  if (!/^\d+$/.test(texto.trim())) return null
  const n = Number(texto)
  return n >= 1 ? n : null
}

export function formParaCorpo(f: FormErp): CorpoErp {
  return {
    system_unit_id: Number(f.system_unit_id),
    filtro_loja: f.filtro_loja.trim() || null,
    ativo: f.ativo,
    intervalo_min: Number(f.intervalo_min),
    exportar_handoff: f.exportar_handoff,
  }
}

export function validarForm(f: FormErp): ErrosErp {
  const erros: ErrosErp = {}
  if (inteiro(f.system_unit_id) === null) {
    erros.system_unit_id = "Informe a unidade do ERP (número inteiro maior que zero)."
  }
  const intervalo = inteiro(f.intervalo_min)
  if (intervalo === null || intervalo < INTERVALO_MINIMO || intervalo > INTERVALO_MAXIMO) {
    erros.intervalo_min = `Informe um número de minutos entre ${INTERVALO_MINIMO} e ${INTERVALO_MAXIMO}.`
  }
  return erros
}

const ROTULOS_STATUS: Record<string, string> = {
  ok: "Sincronizada",
  parcial: "Sincronizada com avisos",
  erro: "Falhou",
}

export function rotuloStatus(status: string): string {
  return ROTULOS_STATUS[status] ?? status
}

export function variantStatus(status: string): "success" | "warning" | "danger" | "outline" {
  if (status === "ok") return "success"
  if (status === "parcial") return "warning"
  if (status === "erro") return "danger"
  return "outline"
}

const FORMATO_DATA = new Intl.DateTimeFormat("pt-BR", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "America/Sao_Paulo",
})

export function formatarData(iso: string): string {
  return FORMATO_DATA.format(new Date(iso))
}
