import type { components } from "@/lib/api/schema"

export type ConexaoErp = components["schemas"]["ConexaoErpSaida"]
export type CorpoErp = components["schemas"]["ConexaoErpEntrada"]
export type TesteConexaoErp = components["schemas"]["TesteConexaoErpSaida"]

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

const ROTULOS_MOTIVO: Record<string, string> = {
  item_malformado: "Item malformado",
  nao_e_celular: "Não é celular",
  indisponivel: "Indisponível para venda",
  sem_quantidade: "Sem quantidade em estoque",
  sem_modelo: "Sem modelo",
  marca_nao_identificada: "Marca não identificada",
  sem_capacidade: "Sem capacidade",
  estado_nao_informado: "Estado (novo ou seminovo) não informado",
  sem_preco: "Sem preço",
  sku_duplicado: "SKU repetido",
}

export function rotuloMotivo(motivo: string): string {
  return ROTULOS_MOTIVO[motivo] ?? motivo
}

export type LinhaRelatorio = { rotulo: string; valor: string; nivel: 0 | 1 }
export type RelatorioFormatado = { linhas: LinhaRelatorio[]; erro: string | null }

const FORMATO_INTEIRO = new Intl.NumberFormat("pt-BR")
const FORMATO_SEGUNDOS = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 })

function numero(valor: unknown): number | null {
  return typeof valor === "number" && Number.isFinite(valor) ? valor : null
}

const CONTADORES: [chave: string, rotulo: string][] = [
  ["lidos", "Itens lidos do ERP"],
  ["importados", "Importados"],
  ["outra_loja", "De outra loja"],
  ["descartados", "Descartados"],
]

/** Relatório da última sincronização (JSON livre da API) em linhas legíveis; ignora o que não conhece. */
export function formatarRelatorio(relatorio: Record<string, unknown> | null | undefined): RelatorioFormatado {
  const linhas: LinhaRelatorio[] = []
  if (!relatorio) return { linhas, erro: null }
  for (const [chave, rotulo] of CONTADORES) {
    const n = numero(relatorio[chave])
    if (n === null) continue
    linhas.push({ rotulo, valor: FORMATO_INTEIRO.format(n), nivel: 0 })
    if (chave === "descartados" && typeof relatorio.por_motivo === "object" && relatorio.por_motivo) {
      for (const [motivo, qtd] of Object.entries(relatorio.por_motivo)) {
        const q = numero(qtd)
        if (q !== null) linhas.push({ rotulo: rotuloMotivo(motivo), valor: FORMATO_INTEIRO.format(q), nivel: 1 })
      }
    }
  }
  const duracao = numero(relatorio.duracao_s)
  if (duracao !== null) linhas.push({ rotulo: "Duração", valor: `${FORMATO_SEGUNDOS.format(duracao)} s`, nivel: 0 })
  const erro = typeof relatorio.erro === "string" && relatorio.erro ? relatorio.erro : null
  return { linhas, erro }
}
